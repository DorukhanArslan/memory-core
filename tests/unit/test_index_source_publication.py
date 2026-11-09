"""Selected real sources publish atomically without replacing unrelated corpus rows."""
from __future__ import annotations

from dataclasses import replace
import json
import os
import sqlite3
import threading

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.origins import MemoryEntryOriginLedger, MemoryIndexRevisionConflictError
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.index.identity import INDEX_SYNC_TABLE, MEMORY_INDEX_META_KEY
from memory_core.index.sqlite_store import (
    MemoryIndexRequiresFullReindexError,
    MemoryIndexSourceChangedError,
    SQLiteMemoryStore,
)
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_corpus import MemoryCoreSessionCorpus
from memory_core.workspace import MemoryWorkspace


NOW = 1_794_182_400_000


def _append(catalog, identifier, text, event):
    key = f"agent:main:dm:{identifier}"
    if catalog.get_session_entry(key) is None:
        catalog.upsert_session(key, {"sessionId": identifier})
    return catalog.append_message(identifier, {"role": "user", "content": text},
        session_key=key, event_id=event, now_ms=NOW)


def _owner(tmp_path, *, vector=False, bootstrap=True):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    (root / "memory/a.md").write_text("Cedar memory baseline.\n")
    (root / "memory/b.md").write_text("Maple memory baseline.\n")
    catalog = MemorySessionCatalog(tmp_path / "sessions.sqlite", clock_ms=lambda: NOW)
    _append(catalog, "first", "Cedar first session.", "first-one")
    _append(catalog, "second", "Maple second session.", "second-one")
    workspace = MemoryWorkspace(root, session_catalog=catalog, index_sources=["memory", "sessions"])
    config = MemoryConfig(workspace_dir=root, store_path=tmp_path / "index.sqlite",
        flags=FeatureFlags(vector_search=vector, temporal_decay=False))
    store = SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=2) if vector else None)
    if bootstrap:
        store.reindex(workspace)
    return store, workspace, catalog


def _view(published, keys):
    chunks = [row for row in published["chunks"] if (row["source"], row["path"]) in keys]
    identifiers = {row["id"] for row in chunks}
    return {"chunks": chunks,
        **{name: [row for row in published[name] if (row["source"], row["path"]) in keys]
           for name in ("sources", "paths", "fts")},
        **{name: [row for row in published[name] if row["chunkId"] in identifiers]
           for name in ("provenance", "recall", "details")}}


@pytest.mark.parametrize("vector", [False, True])
def test_targeted_session_preparation_preserves_all_unselected_publication(vector, tmp_path):
    store, workspace, catalog = _owner(tmp_path, vector=vector)
    before = store.read_published_index()
    selected = ("sessions", "sessions/main/first.jsonl")
    unselected = {(row["source"], row["path"]) for row in before["sources"]} - {selected}
    _append(catalog, "first", "Cedar selected update.", "first-two")
    _append(catalog, "second", "Maple unselected update.", "second-two")
    (workspace.root / "memory/a.md").write_text("Cedar unpublished memory update.\n")

    assert store.reindex_sources(workspace, sources={"sessions"}, paths={selected[1]}) == 1

    after = store.read_published_index()
    assert after["revision"] == before["revision"] + 1
    assert _view(after, unselected) == _view(before, unselected)
    assert after["meta"] == before["meta"]
    assert any("selected update" in row["text"] for row in _view(after, {selected})["chunks"])
    assert workspace.index_sources == ("memory", "sessions")
    if vector:
        assert store.read_index_meta()["vectorDims"] == 2


def test_selected_forgotten_source_deletes_only_its_own_rows(tmp_path):
    store, workspace, catalog = _owner(tmp_path)
    before = store.read_published_index()
    selected = ("sessions", "sessions/main/first.jsonl")
    unselected = {(row["source"], row["path"]) for row in before["sources"]} - {selected}
    catalog.tombstone_session("first", session_key="agent:main:dm:first")

    assert store.reindex_sources(workspace, sources={"sessions"}, paths={selected[1]}) == 0

    after = store.read_published_index()
    assert _view(after, unselected) == _view(before, unselected)
    assert all(not rows for rows in _view(after, {selected}).values())


def test_source_wide_reconciliation_removes_stale_sessions_and_adds_real_new_ones(tmp_path):
    store, workspace, catalog = _owner(tmp_path)
    before = store.read_published_index()
    memory_keys = {(row["source"], row["path"]) for row in before["sources"] if row["source"] == "memory"}
    catalog.tombstone_session("first", session_key="agent:main:dm:first")
    _append(catalog, "third", "New third catalog source.", "third-one")

    assert store.reindex_sources(workspace, sources={"sessions"}) == 2

    after = store.read_published_index()
    assert _view(after, memory_keys) == _view(before, memory_keys)
    assert {row["path"] for row in after["sources"] if row["source"] == "sessions"} == {
        "sessions/main/second.jsonl", "sessions/main/third.jsonl",
    }


def test_selection_reads_no_unselected_memory_or_transcript_projection(tmp_path, monkeypatch):
    store, workspace, catalog = _owner(tmp_path)
    _append(catalog, "first", "Selected original source changed.", "first-two")
    original = MemoryCoreSessionCorpus.read_index_entry

    def selected_only(corpus, file, **options):
        assert file.rel_path == "sessions/main/first.jsonl"
        return original(corpus, file, **options)

    monkeypatch.setattr(MemoryCoreSessionCorpus, "read_index_entry", selected_only)
    monkeypatch.setattr(workspace, "discover_memory_files", lambda: pytest.fail("An unselected memory corpus was read"))

    assert store.reindex_sources(workspace, sources={"sessions"}, paths={"sessions/main/first.jsonl"}) == 1


@pytest.mark.parametrize("invalidation", ["cold", "newer", "needs-rebuild"])
def test_selection_cannot_bootstrap_or_repair_a_full_namespace(tmp_path, invalidation, monkeypatch):
    store, workspace, _ = _owner(tmp_path, bootstrap=invalidation != "cold")
    if invalidation == "newer":
        meta = store.read_index_meta()
        meta["chunkingVersion"] += 1
        with store.connect() as db:
            db.execute("UPDATE memory_index_meta SET value=? WHERE key=?", (json.dumps(meta), MEMORY_INDEX_META_KEY))
    elif invalidation == "needs-rebuild":
        with store.connect() as db:
            db.execute(f"UPDATE {INDEX_SYNC_TABLE} SET needs_rebuild=1 WHERE id=1")
    before = store.read_published_index()
    monkeypatch.setattr(workspace, "discover_indexable_files", lambda **_options: pytest.fail("Invalid selection read source bytes"))

    with pytest.raises(MemoryIndexRequiresFullReindexError):
        store.reindex_sources(workspace, sources={"sessions"}, force_sources=True)

    assert store.read_published_index() == before


def test_empty_path_selection_is_not_an_implicit_source_wide_reconciliation(tmp_path):
    store, workspace, catalog = _owner(tmp_path)
    before = store.read_published_index()
    _append(catalog, "first", "Pending source must stay unpublished.", "first-two")
    assert store.reindex_sources(workspace, sources={"sessions"}, paths=set()) == 0
    assert store.read_published_index() == before


def test_source_change_during_real_preparation_cannot_publish_stale_session(tmp_path, monkeypatch):
    store, workspace, catalog = _owner(tmp_path)
    _append(catalog, "first", "First prepared change.", "first-two")
    before = store.read_published_index()
    original = store._prepare_source_chunks
    mutated = False

    def change_after_preparation(entry, *options):
        nonlocal mutated
        chunks = original(entry, *options)
        if not mutated:
            mutated = True
            _append(catalog, "first", "Later genuine source mutation.", "first-three")
        return chunks

    monkeypatch.setattr(store, "_prepare_source_chunks", change_after_preparation)
    with pytest.raises(MemoryIndexSourceChangedError, match="source changed"):
        store.reindex_sources(workspace, sources={"sessions"}, paths={"sessions/main/first.jsonl"})
    assert store.read_published_index() == before


def test_selected_publication_failure_rolls_back_deletes_and_new_rows(tmp_path):
    store, workspace, catalog = _owner(tmp_path)
    _append(catalog, "first", "New selected source body.", "first-two")
    before = store.read_published_index()
    with store.connect() as db:
        db.execute("CREATE TRIGGER refuse_session BEFORE INSERT ON chunks WHEN NEW.source='sessions' "
                   "BEGIN SELECT RAISE(ABORT, 'selected publisher refused'); END")

    with pytest.raises(sqlite3.IntegrityError, match="selected publisher refused"):
        store.reindex_sources(workspace, sources={"sessions"}, paths={"sessions/main/first.jsonl"})

    assert store.read_published_index() == before


def test_selected_generation_cas_preserves_a_competing_genuine_publication(tmp_path, monkeypatch):
    store, workspace, catalog = _owner(tmp_path)
    _append(catalog, "first", "Prepared first session update.", "first-two")
    (workspace.root / "memory/a.md").write_text("Competing cedar memory publication.\n")
    competitor = SQLiteMemoryStore(store.config, None)
    original = store.publish_prepared_index
    competing = []

    def interleave(prepared, generation, **options):
        competitor.reindex_sources(workspace, sources={"memory"}, paths={"memory/a.md"})
        competing.append(competitor.read_published_index())
        return original(prepared, generation, **options)

    monkeypatch.setattr(store, "publish_prepared_index", interleave)
    with pytest.raises(MemoryIndexSourceChangedError, match="index changed"):
        store.reindex_sources(workspace, sources={"sessions"}, paths={"sessions/main/first.jsonl"})
    assert competing and store.read_published_index() == competing[0]


def test_actual_forget_fence_prevents_selected_publication(tmp_path, monkeypatch):
    store, workspace, catalog = _owner(tmp_path)
    ledger = MemoryEntryOriginLedger(lambda _agent: store.path)
    store.revision_fence = ledger.revision_fence("main")
    _append(catalog, "first", "Prepared source before forget.", "first-two")
    before = store.read_published_index()
    original = store._prepare_source_chunks
    forgotten = False

    def forget_after_preparation(entry, *options):
        nonlocal forgotten
        chunks = original(entry, *options)
        if not forgotten:
            forgotten = True
            ledger.record_session_tombstones("main", ["first"])
        return chunks

    monkeypatch.setattr(store, "_prepare_source_chunks", forget_after_preparation)
    with pytest.raises(MemoryIndexRevisionConflictError):
        store.reindex_sources(workspace, sources={"sessions"}, paths={"sessions/main/first.jsonl"})
    assert store.read_published_index() == before


def test_force_sources_reprepares_only_selected_real_file_metadata(tmp_path):
    store, workspace, _ = _owner(tmp_path)
    before = store.read_published_index()
    selected = ("memory", "memory/a.md")
    unselected = {(row["source"], row["path"]) for row in before["sources"]} - {selected}
    os.utime(workspace.root / selected[1], ns=(NOW * 1_000_000, NOW * 1_000_000))

    assert store.reindex_sources(workspace, sources={"memory"}, paths={selected[1]}, force_sources=True) == 1

    after = store.read_published_index()
    assert _view(after, unselected) == _view(before, unselected)
    assert _view(after, {selected})["chunks"][0]["provenance"]["observedAt"] == NOW


def test_base_full_reindex_still_refreshes_all_actual_sources(tmp_path):
    store, workspace, catalog = _owner(tmp_path)
    _append(catalog, "first", "First changed.", "first-two")
    _append(catalog, "second", "Second changed.", "second-two")
    (workspace.root / "memory/a.md").write_text("Actual memory changed.\n")

    assert store.reindex(workspace) == 4

    text = "\n".join(row["text"] for row in store.read_published_index()["chunks"])
    assert all(fragment in text for fragment in ("First changed.", "Second changed.", "Actual memory changed."))


def test_search_snapshot_hook_runs_after_real_read_generation_is_pinned(tmp_path):
    store, workspace, _ = _owner(tmp_path)
    with store.connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
    (workspace.root / "memory/a.md").write_text("Cedar newer publication.\n")
    old_revision = store.read_published_index()["revision"]
    observed = []
    completed = threading.Event()
    failures = []

    def publish():
        try:
            store.reindex_sources(workspace, sources={"memory"}, paths={"memory/a.md"})
        except BaseException as error:
            failures.append(error)
        finally:
            completed.set()

    def admitted(db):
        observed.append((db.in_transaction, store.index_revision(db=db)))
        if len(observed) == 1:
            thread = threading.Thread(target=publish)
            thread.start()
            assert completed.wait(5)
            thread.join()

    store._on_search_snapshot = admitted
    actual = store.search("cedar memory", sources={"memory"}, min_score=0)

    assert not failures and observed == [(True, old_revision)]
    assert any(hit.snippet == "Cedar memory baseline.\n" for hit in actual)
    assert any(row["text"] == "Cedar newer publication.\n" for row in store.read_published_index()["chunks"])


def test_selected_refresh_rejects_another_workspace_before_initialization(tmp_path):
    store, _, _ = _owner(tmp_path)
    other = tmp_path / "other"
    with pytest.raises(ValueError, match="same owner"):
        store.reindex_sources(MemoryWorkspace(other), sources={"sessions"})
    assert not other.exists()


def test_selected_refresh_accepts_the_existing_canonical_agent_owner(tmp_path):
    store, workspace, catalog = _owner(tmp_path)
    canonical_alias = SQLiteMemoryStore(replace(store.config, agent_id="MAIN"), None)
    _append(catalog, "first", "Canonical owner update.", "first-two")
    assert canonical_alias.reindex_sources(workspace, sources={"sessions"}, paths={"sessions/main/first.jsonl"}) == 1


def test_memory_refresh_keeps_legacy_session_corpus_classification(tmp_path):
    store, workspace, _ = _owner(tmp_path)
    relative = "memory/.dreams/session-corpus/2026-11-09.md"
    path = workspace.root / relative
    path.parent.mkdir(parents=True)
    path.write_text("Legacy actual session source.\n")
    store.reindex(workspace)
    before = store.read_published_index()

    assert store.reindex_sources(workspace, sources={"memory"}) == 2

    after = store.read_published_index()
    assert _view(after, {("sessions", relative)}) == _view(before, {("sessions", relative)})
    assert ("memory", relative) not in {(row["source"], row["path"]) for row in after["sources"]}


@pytest.mark.parametrize("options", [
    {"sources": set()}, {"sources": {"unknown"}}, {"sources": "memory"},
    {"sources": {"sessions"}, "paths": "sessions/main/first.jsonl"},
    {"sources": {"sessions"}, "paths": {"../outside"}},
    {"sources": {"sessions"}, "paths": {"/outside"}},
])
def test_source_selection_rejects_ambiguous_domains(tmp_path, options):
    store, workspace, _ = _owner(tmp_path)
    before = store.read_published_index()
    with pytest.raises(ValueError):
        store.reindex_sources(workspace, **options)
    assert store.read_published_index() == before
