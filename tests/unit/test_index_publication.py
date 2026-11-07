"""Prepared SQLite publication and real reader/failure interleavings."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import sqlite3

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.origins import MemoryIndexRevisionConflictError
from memory_core.embeddings import FakeEmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.index.identity import INDEX_SOURCES_TABLE
from memory_core.index.publication import (
    CHUNK_DETAILS_TABLE,
    CHUNK_PROVENANCE_TABLE,
    CHUNK_RECALL_TABLE,
    ChunkProvenance,
    ChunkRecallMetadata,
    PreparedChunk,
    PreparedIndexRevision,
    PreparedSource,
)
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


def make_store(tmp_path, *, vector=False):
    root = tmp_path / "workspace"
    root.mkdir()
    config = MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=vector))
    store = SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=2) if vector else None)
    with store.connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
    return store


def prepare(store, label, *, path=None, empty=False):
    path = path or f"memory/{label}.md"
    text = f"router {label}"
    chunks = () if empty else (PreparedChunk(
        id=f"chunk-{label}", path=path, source="memory", start_line=2, end_line=3,
        text=text, embedding=(), hash=hashlib.sha256(text.encode()).hexdigest(),
        model="fts-only", updated_at=100,
        provenance=ChunkProvenance("owner", "interactive", 42, "previous-entry"),
        recall=ChunkRecallMetadata(7, '["router","coffee"]', "project-a"),
    ),)
    meta = store._build_index_meta(None, provider=store._index_provider(), provider_key=store._provider_key())
    meta["fixtureRevision"] = label
    return PreparedIndexRevision(
        (PreparedSource(path, "memory", f"hash-{label}", 12.5, len(text), chunks),),
        json.dumps(meta, separators=(",", ":")), workspace=str(store.config.workspace_dir),
    )


def publish(store, prepared, **kwargs):
    return store.publish_prepared_index(prepared, store.index_revision(), **kwargs)


def test_prepared_metadata_is_persisted_without_rederiving_or_dropping_fields(tmp_path):
    store = make_store(tmp_path)
    old = prepare(store, "old")
    with store.connect() as db:
        db.execute("INSERT INTO memory_index_meta VALUES ('unrelated', 'retained')")
    publish(store, old)
    new = prepare(store, "new")
    empty = prepare(store, "empty", empty=True).sources[0]
    new = replace(new, sources=(*new.sources, empty))
    publish(store, new)

    state = store.read_published_index()
    chunk = state["chunks"][0]
    assert chunk["id"] == "chunk-new" and chunk["hash"] == new.sources[0].chunks[0].hash
    assert chunk["model"] == "fts-only" and chunk["updatedAt"] == 100
    assert chunk["provenance"] == {
        "originClass": "owner", "sessionKind": "interactive", "observedAt": 42,
        "supersedesKey": "previous-entry",
    }
    assert chunk["recall"] == {
        "importance": 7, "triggers": '["router","coffee"]', "projectKey": "project-a",
    }
    assert state["paths"] == [{"path": "memory/empty.md", "source": "memory"},
                              {"path": "memory/new.md", "source": "memory"}]
    assert state["fts"] == [{
        "id": "chunk-new", "text": "router new", "path": "memory/new.md", "source": "memory",
        "startLine": 2, "endLine": 3, "model": "fts-only",
    }]
    assert {row["key"]: row["value"] for row in state["meta"]}["unrelated"] == "retained"
    assert SQLiteMemoryStore(store.config, None).read_published_index() == state


def test_prepared_revision_freezes_caller_owned_lists():
    embeddings = [0.25, 0.75]
    chunk = PreparedChunk("id", "memory/a.md", "memory", 1, 1, "a", embeddings, "hash", "model", 1)
    chunks = [chunk]
    source = PreparedSource("memory/a.md", "memory", "hash", 0, 1, chunks)
    sources = [source]
    prepared = PreparedIndexRevision(sources, "{}")
    embeddings.clear()
    chunks.clear()
    sources.clear()
    assert prepared.sources == (source,) and source.chunks == (chunk,)
    assert chunk.embedding == (0.25, 0.75)


def test_reader_snapshot_remains_coherent_across_publication_and_reopen(tmp_path):
    store = make_store(tmp_path)
    publish(store, prepare(store, "old"))
    old = store.read_published_index()
    reader = store.connect()
    reader.execute("BEGIN")
    assert store.read_published_index(db=reader) == old
    observations = []

    def on_begin(writer):
        observations.append((store.read_published_index(db=writer), store.read_published_index()))

    def commit(commit):
        writer = current_writer[0]
        new = store.read_published_index(db=writer)
        assert new["chunks"][0]["text"] == "router new"
        assert store.read_published_index() == old
        assert store.read_published_index(db=reader) == old
        commit()
        assert store.read_published_index() == new
        assert store.read_published_index(db=reader) == old

    current_writer = []

    def capture(writer):
        current_writer.append(writer)
        on_begin(writer)

    publish(store, prepare(store, "new"), on_begin=capture, with_commit=commit)
    assert observations == [(old, old)]
    reader.rollback()
    assert store.read_published_index(db=reader) == store.read_published_index()
    reader.close()


@pytest.mark.parametrize("table", ["chunks", INDEX_SOURCES_TABLE, CHUNK_DETAILS_TABLE,
                                   CHUNK_PROVENANCE_TABLE, CHUNK_RECALL_TABLE, "memory_index_meta"])
def test_failures_at_every_published_owner_roll_back_one_revision(tmp_path, table):
    store = make_store(tmp_path)
    publish(store, prepare(store, "old"))
    old = store.read_published_index()
    with store.connect() as db:
        db.execute(f"CREATE TRIGGER reject_publication BEFORE INSERT ON {table} "
                   "BEGIN SELECT RAISE(ABORT, 'publication fixture failure'); END")
    with pytest.raises(sqlite3.DatabaseError, match="publication fixture failure"):
        publish(store, prepare(store, "new"))
    assert store.read_published_index() == old


@pytest.mark.parametrize("phase", ["begin", "before-commit", "after-commit"])
def test_injected_commit_failures_report_actual_durability(tmp_path, phase):
    store = make_store(tmp_path)
    publish(store, prepare(store, "old"))
    old = store.read_published_index()

    def begin(writer):
        if phase == "begin":
            raise RuntimeError("begin fixture failure")

    def commit(commit):
        if phase == "after-commit":
            commit()
        raise RuntimeError("commit fixture failure")

    with pytest.raises(RuntimeError, match="fixture failure"):
        publish(store, prepare(store, "new"), on_begin=begin, with_commit=commit)
    reopened = SQLiteMemoryStore(store.config, None).read_published_index()
    if phase == "after-commit":
        assert reopened["chunks"][0]["text"] == "router new"
        assert reopened["revision"] == old["revision"] + 1
    else:
        assert reopened == old


def test_stale_revision_cannot_publish_and_begin_mutation_is_rolled_back(tmp_path):
    store = make_store(tmp_path)
    stale = store.index_revision()
    publish(store, prepare(store, "old"))
    old = store.read_published_index()
    with pytest.raises(MemoryIndexRevisionConflictError):
        store.publish_prepared_index(prepare(store, "new"), stale)
    assert store.read_published_index() == old


@pytest.mark.parametrize("provenance,recall", [
    (ChunkProvenance("invented", "interactive", 1), ChunkRecallMetadata()),
    (ChunkProvenance("owner", "invented", 1), ChunkRecallMetadata()),
    (ChunkProvenance(), ChunkRecallMetadata(0)),
    (ChunkProvenance(), ChunkRecallMetadata(11)),
    (ChunkProvenance(), ChunkRecallMetadata(1.5)),
])
def test_invalid_prepared_metadata_cannot_partially_replace_valid_state(tmp_path, provenance, recall):
    store = make_store(tmp_path)
    publish(store, prepare(store, "old"))
    old = store.read_published_index()
    new = prepare(store, "new")
    chunk = replace(new.sources[0].chunks[0], provenance=provenance, recall=recall)
    new = replace(new, sources=(replace(new.sources[0], chunks=(chunk,)),))
    with pytest.raises(sqlite3.DatabaseError):
        publish(store, new)
    assert store.read_published_index() == old


def test_every_store_connection_cascades_metadata_on_direct_chunk_deletion(tmp_path):
    store = make_store(tmp_path)
    publish(store, prepare(store, "old"))
    with store.connect() as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        db.execute("DELETE FROM chunks")
    state = store.read_published_index()
    assert state["provenance"] == state["recall"] == state["details"] == []


def test_ordinary_reindex_uses_publication_and_repairs_missing_metadata(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    workspace = MemoryWorkspace(store.config.workspace_dir)
    target = workspace.root / "memory/a.md"
    target.parent.mkdir()
    target.write_text("router durable note", encoding="utf-8")
    calls = []
    original = store.publish_prepared_index

    def observe(prepared, *args, **kwargs):
        calls.append(prepared)
        return original(prepared, *args, **kwargs)

    monkeypatch.setattr(store, "publish_prepared_index", observe)
    store.reindex(workspace)
    assert len(calls) == 1
    before = store.read_published_index()
    assert before["provenance"][0]["originClass"] == "agent"
    with store.connect() as db:
        db.execute(f"DELETE FROM {CHUNK_RECALL_TABLE}")
    store.reindex(workspace)
    assert len(calls) == 2 and len(store.read_published_index()["recall"]) == 1


def test_query_uses_one_generation_between_body_and_path_probes(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    publish(store, prepare(store, "old"))
    original = store._query_body_hits
    published = []

    def interleave(*args, **kwargs):
        hits = original(*args, **kwargs)
        if not published:
            published.append(publish(store, prepare(store, "new")))
        return hits

    monkeypatch.setattr(store, "_query_body_hits", interleave)
    hits = store.search_memory_keywords("router")
    assert [hit.path for hit in hits] == ["memory/old.md"]
    assert [hit.path for hit in store.search_memory_keywords("router")] == ["memory/new.md"]


def test_changed_identity_during_query_embedding_fails_closed(tmp_path):
    store = make_store(tmp_path, vector=True)
    workspace = MemoryWorkspace(store.config.workspace_dir)
    target = workspace.root / "memory/a.md"
    target.parent.mkdir()
    target.write_text("router old note", encoding="utf-8")
    store.reindex(workspace)
    provider = store.embeddings
    original = provider.embed_query

    def change_identity(query):
        vector = original(query)
        provider.model = "different-space"
        store.reindex(workspace)
        return vector

    provider.embed_query = change_identity
    assert store.search("router") == []


def test_hybrid_query_does_not_mix_body_path_and_vector_generations(tmp_path, monkeypatch):
    store = make_store(tmp_path, vector=True)
    workspace = MemoryWorkspace(store.config.workspace_dir)
    old_path = workspace.root / "memory/old.md"
    old_path.parent.mkdir()
    old_path.write_text("router old note", encoding="utf-8")
    store.reindex(workspace)
    original = store._query_body_hits
    published = []

    def interleave(*args, **kwargs):
        hits = original(*args, **kwargs)
        if not published:
            old_path.unlink()
            (old_path.parent / "new.md").write_text("router new note", encoding="utf-8")
            published.append(store.reindex(workspace))
        return hits

    monkeypatch.setattr(store, "_query_body_hits", interleave)
    assert [hit.path for hit in store.search("router")] == ["memory/old.md"]
    assert [hit.path for hit in store.search("router")] == ["memory/new.md"]


def test_reopening_legacy_metadata_invalidates_source_without_inventing_trust(tmp_path):
    store = make_store(tmp_path)
    workspace = MemoryWorkspace(store.config.workspace_dir)
    target = workspace.root / "memory/a.md"
    target.parent.mkdir()
    target.write_text("router legacy note", encoding="utf-8")
    store.reindex(workspace)
    with store.connect() as db:
        for table in (CHUNK_DETAILS_TABLE, CHUNK_PROVENANCE_TABLE, CHUNK_RECALL_TABLE):
            db.execute(f"DROP TABLE {table}")
    reopened = SQLiteMemoryStore(store.config, None)
    state = reopened.read_published_index()
    assert state["sources"][0]["hash"] == ""
    assert state["provenance"][0]["originClass"] == "untrusted"
    assert state["provenance"][0]["observedAt"] == 0
    reopened.reindex(workspace)
    refreshed = reopened.read_published_index()
    assert refreshed["sources"][0]["hash"]
    assert refreshed["provenance"][0]["originClass"] == "agent"
    assert refreshed["details"][0]["model"] == "fts-only"


def test_session_line_provenance_and_reset_partition_survive_publication(tmp_path, monkeypatch):
    from memory_core.session_entry import SessionEntry
    from memory_core.workspace import MemoryFile

    store = make_store(tmp_path)
    workspace = MemoryWorkspace(store.config.workspace_dir)
    transcript = tmp_path / "source.jsonl"
    transcript.write_text("raw transcript bytes", encoding="utf-8")
    entry = SessionEntry(
        content="User: owner fact\nAssistant: agent fact", line_map=[4, 8],
        message_timestamps_ms=[10, 20],
        line_provenance=[
            {"originClass": "owner", "sessionKind": "interactive", "observedAt": 10},
            {"originClass": "agent", "sessionKind": "interactive", "observedAt": 20},
        ], hash="full-projection-hash", session_kind="interactive",
        reset_recall_cutoff={"state": "valid", "cutoffLine": 8},
    )
    monkeypatch.setattr(workspace, "discover_indexable_files", lambda: [
        MemoryFile("sessions/main/chat.jsonl", transcript, "sessions", index_entry=entry),
    ])
    store.reindex(workspace)
    state = store.read_published_index()
    assert state["sources"][0]["hash"] == "full-projection-hash"
    assert state["sources"][0]["size"] == len("raw transcript bytes")
    chunks = sorted(state["chunks"], key=lambda chunk: chunk["startLine"])
    assert [(chunk["startLine"], chunk["endLine"]) for chunk in chunks] == [(4, 4), (8, 8)]
    assert [chunk["provenance"]["originClass"] for chunk in chunks] == ["owner", "agent"]
    assert [chunk["provenance"]["observedAt"] for chunk in chunks] == [10, 20]
