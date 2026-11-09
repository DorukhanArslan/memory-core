"""Real SQLite/source/provider failure boundaries of incremental refresh.

These are Python regressions, independent of native helper comparisons. The
complete native manager lifecycle remains a separate acceptance requirement.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from memory_core.config import MemoryConfig
from memory_core.client import Memory
from memory_core.consolidation.origins import MemoryEntryOriginLedger, MemoryIndexRevisionConflictError
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.index.embedding_cache import MALFORMED_VECTOR_RESPONSE
from memory_core.index.identity import INDEX_SOURCES_TABLE, MEMORY_INDEX_META_KEY
from memory_core.index.sqlite_store import MemoryIndexSourceChangedError, SQLiteMemoryStore
from memory_core.workspace import MemoryFile, MemoryWorkspace


class CountingProvider(FakeEmbeddingProvider):
    def __init__(self, dimensions=4, *, endpoint="a"):
        super().__init__(dimensions)
        self.endpoint = endpoint
        self.calls = []
        self.callback = None
        self.response = ...

    def cache_key_data(self):
        return {"provider": self.provider_id, "model": self.model, "endpoint": self.endpoint}

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        if self.callback is not None:
            self.callback()
        if self.response is not ...:
            return self.response
        return super().embed_documents(texts)


def create_store(tmp_path, files, provider=None, *, vector=True):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    for name, text in files.items():
        target = workspace_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    config = MemoryConfig(workspace_dir=workspace_root, store_path=tmp_path / "index.sqlite",
                          flags=FeatureFlags(vector_search=vector))
    provider = provider or (CountingProvider() if vector else None)
    return SQLiteMemoryStore(config, provider), MemoryWorkspace(workspace_root), provider


def rows(store, sql, args=()):
    with store.connect() as db:
        return db.execute(sql, args).fetchall()


def published(store):
    return {
        "chunks": rows(store, "SELECT * FROM chunks ORDER BY id"),
        "fts": rows(store, "SELECT id, text FROM chunks_fts ORDER BY id"),
        "paths": rows(store, "SELECT path, source FROM paths_fts ORDER BY path, source"),
        "sources": rows(store, f"SELECT * FROM {INDEX_SOURCES_TABLE} ORDER BY source, path"),
        "meta": store.read_index_meta(),
    }


def cache_rows(store):
    return rows(store, "SELECT provider, model, provider_key, hash, embedding, dims "
                       "FROM memory_embedding_cache ORDER BY provider, model, provider_key, hash")


def test_no_change_and_fresh_store_do_not_reembed_or_reparse(tmp_path, monkeypatch):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "glacier alpha"})
    assert store.reindex(workspace) == 1
    before = published(store)
    ids = rows(store, "SELECT rowid, id FROM chunks")

    def no_reparse(*args, **kwargs):
        raise AssertionError("unchanged source must not be chunked again")

    monkeypatch.setattr("memory_core.index.sqlite_store.chunk_markdown", no_reparse)
    assert store.reindex(workspace) == 1
    reopened = SQLiteMemoryStore(store.config, provider)
    assert reopened.reindex(workspace) == 1
    assert provider.calls == [["glacier alpha"]]
    assert published(reopened) == before
    assert rows(reopened, "SELECT rowid, id FROM chunks") == ids


def test_only_changed_sources_replace_rows_and_request_embeddings(tmp_path):
    store, workspace, provider = create_store(tmp_path, {
        "memory/a.md": "glacier alpha", "memory/b.md": "calendar beta",
    })
    store.reindex(workspace)
    unchanged = rows(store, "SELECT rowid, * FROM chunks WHERE path='memory/b.md'")
    (workspace.root / "memory/a.md").write_text("volcano gamma", encoding="utf-8")
    assert store.reindex(workspace) == 2
    assert provider.calls[-1] == ["volcano gamma"]
    assert rows(store, "SELECT rowid, * FROM chunks WHERE path='memory/b.md'") == unchanged
    assert [hit.path for hit in store.search_memory_keywords("volcano")] == ["memory/a.md"]
    assert store.search_memory_keywords("glacier") == []


def test_rename_reuses_content_embeddings_and_delete_removes_all_derived_rows(tmp_path):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "glacier alpha"})
    store.reindex(workspace)
    (workspace.root / "memory/a.md").rename(workspace.root / "memory/renamed.md")
    assert store.reindex(workspace) == 1
    assert len(provider.calls) == 1
    assert [hit.path for hit in store.search_memory_keywords("glacier")] == ["memory/renamed.md"]
    (workspace.root / "memory/renamed.md").unlink()
    assert store.reindex(workspace) == 0
    assert store.count_chunks() == 0
    assert rows(store, "SELECT * FROM chunks_fts") == []
    assert rows(store, "SELECT * FROM paths_fts") == []
    assert rows(store, f"SELECT * FROM {INDEX_SOURCES_TABLE}") == []
    assert len(provider.calls) == 1


def test_content_hash_detects_same_size_same_mtime_changes(tmp_path):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "glacier"})
    target = workspace.root / "memory/a.md"
    stamp = 1_700_000_000_000_000_000
    os.utime(target, ns=(stamp, stamp))
    store.reindex(workspace)
    target.write_text("volcano", encoding="utf-8")
    os.utime(target, ns=(stamp, stamp))
    store.reindex(workspace)
    assert provider.calls == [["glacier"], ["volcano"]]


def test_empty_sources_survive_reopen_and_are_not_reparsed(tmp_path, monkeypatch):
    store, workspace, _ = create_store(tmp_path, {"memory/empty.md": ""}, vector=False)
    assert store.reindex(workspace) == 1
    assert rows(store, f"SELECT path, chunk_count FROM {INDEX_SOURCES_TABLE}") == [("memory/empty.md", 0)]
    monkeypatch.setattr("memory_core.index.sqlite_store.chunk_markdown",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("reparse")))
    assert SQLiteMemoryStore(store.config, None).reindex(workspace) == 1
    (workspace.root / "memory/empty.md").unlink()
    assert store.reindex(workspace) == 0


def test_force_refresh_repairs_unchanged_chunk_text_without_extra_provider_call(tmp_path):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "glacier alpha"})
    store.reindex(workspace)
    with store.connect() as db:
        db.execute("UPDATE chunks SET text='corrupt derived text'")
    store.reindex(workspace, force=True)
    assert rows(store, "SELECT text FROM chunks") == [("glacier alpha",)]
    assert len(provider.calls) == 1


def test_provider_endpoint_change_never_borrows_another_cache_space(tmp_path):
    store, workspace, first = create_store(tmp_path, {"memory/a.md": "glacier alpha"})
    store.reindex(workspace)
    other = CountingProvider(endpoint="b")
    reopened = SQLiteMemoryStore(store.config, other)
    assert reopened.index_identity()["status"] == "mismatched"
    reopened.reindex(workspace)
    assert other.calls == [["glacier alpha"]]
    assert len(first.calls) == 1
    assert len(cache_rows(store)) == 2
    assert reopened.index_identity() == {"status": "valid"}


def test_declared_provider_alias_can_reuse_equivalent_old_model_space(tmp_path):
    store, workspace, first = create_store(tmp_path, {"memory/a.md": "glacier alpha"})
    store.reindex(workspace)
    before = published(store)
    other = CountingProvider()
    other.model = "new-compatible-model"
    other.index_identity_aliases = [{"model": first.model, "cacheKeyData": first.cache_key_data()}]
    reopened = SQLiteMemoryStore(store.config, other)
    assert reopened.index_identity() == {"status": "valid"}
    reopened.reindex(workspace)
    assert other.calls == []
    assert published(reopened) == before
    assert reopened.read_index_meta()["model"] == first.model
    assert reopened.search("glacier", min_score=0)


def test_alias_source_update_keeps_canonical_meta_and_both_model_spaces_searchable(tmp_path):
    store, workspace, first = create_store(tmp_path, {"memory/a.md": "glacier alpha", "memory/b.md": "calendar beta"})
    store.reindex(workspace)
    meta = store.read_index_meta()
    unchanged = rows(store, "SELECT * FROM chunks WHERE path='memory/b.md'")
    other = CountingProvider()
    other.model = "new-compatible-model"
    other.index_identity_aliases = [{"model": first.model, "cacheKeyData": first.cache_key_data()}]
    reopened = SQLiteMemoryStore(store.config, other)
    (workspace.root / "memory/a.md").write_text("volcano gamma", encoding="utf-8")
    reopened.reindex(workspace)
    assert reopened.read_index_meta() == meta
    assert rows(reopened, "SELECT * FROM chunks WHERE path='memory/b.md'") == unchanged
    assert set(row[0] for row in rows(reopened, "SELECT model FROM memory_index_chunk_details")) == {first.model, other.model}
    assert reopened.index_identity() == {"status": "valid"}
    assert {hit.path for hit in reopened.search("volcano calendar", min_score=0)} == {"memory/a.md", "memory/b.md"}
    again = SQLiteMemoryStore(store.config, other)
    before = published(reopened)
    again.reindex(workspace)
    assert published(again) == before


def test_undeclared_model_namespace_does_not_reuse_same_text_cache(tmp_path):
    store, workspace, first = create_store(tmp_path, {"memory/a.md": "glacier alpha"})
    store.reindex(workspace)
    other = CountingProvider()
    other.model = "different-model"
    reopened = SQLiteMemoryStore(store.config, other)
    assert reopened.index_identity()["code"] == "model"
    reopened.reindex(workspace)
    assert other.calls == [["glacier alpha"]]
    assert reopened.read_index_meta()["model"] == other.model
    assert {row[1] for row in cache_rows(reopened)} == {first.model, other.model}


def test_declared_alias_does_not_bypass_other_index_settings_or_force_rebuild(tmp_path):
    store, workspace, first = create_store(tmp_path, {"memory/a.md": "glacier alpha"})
    store.reindex(workspace)
    other = CountingProvider()
    other.model = "new-compatible-model"
    other.index_identity_aliases = [{"model": first.model, "cacheKeyData": first.cache_key_data()}]
    reopened = SQLiteMemoryStore(store.config, other)
    old_meta = store.read_index_meta()
    corrupted = {**old_meta, "scopeHash": "different-scope"}
    with reopened.connect() as db:
        db.execute("UPDATE memory_index_meta SET value=? WHERE key=?", (json.dumps(corrupted), MEMORY_INDEX_META_KEY))
    assert reopened.index_identity()["code"] == "scope"
    with reopened.connect() as db:
        db.execute("UPDATE memory_index_meta SET value=? WHERE key=?", (json.dumps(old_meta), MEMORY_INDEX_META_KEY))
    reopened.reindex(workspace, force=True)
    assert reopened.read_index_meta()["model"] == other.model


def test_default_cache_capacity_is_applied_at_store_writes(tmp_path, monkeypatch):
    monkeypatch.setattr("memory_core.index.sqlite_store.EMBEDDING_CACHE_MAX_ENTRIES", 2)
    store, workspace, provider = create_store(tmp_path, {
        "memory/a.md": "alpha", "memory/b.md": "beta", "memory/c.md": "gamma",
    })
    store.reindex(workspace)
    assert len(cache_rows(store)) == 2
    cached = {row[3] for row in cache_rows(store)}
    missing_texts = {text for text in ("alpha", "beta", "gamma")
                     if hashlib.sha256(text.encode()).hexdigest() not in cached}
    before = len(provider.calls)
    store.reindex(workspace, force=True)
    assert {text for call in provider.calls[before:] for text in call} == missing_texts
    assert len(cache_rows(store)) == 2
    assert store.count_chunks() == 3


@pytest.mark.parametrize("response", [None, [], [[1, 2]], [[1, 2], []],
                                      [[1, 2], [1]], [[math.nan], [1]], [[True], [1]]])
def test_malformed_batch_does_not_publish_or_retain_any_new_vector(tmp_path, response):
    store, workspace, provider = create_store(tmp_path, {"memory/old.md": "old source"})
    store.reindex(workspace)
    before, cached = published(store), cache_rows(store)
    (workspace.root / "memory/a.md").write_text("alpha", encoding="utf-8")
    (workspace.root / "memory/b.md").write_text("beta", encoding="utf-8")
    provider.response = response
    with pytest.raises(ValueError, match=re.escape(MALFORMED_VECTOR_RESPONSE)):
        store.reindex(workspace)
    assert published(store) == before
    # Dimensional disagreement deliberately clears the active cache, while
    # count/empty/non-finite responses leave the previous valid entries alone.
    assert cache_rows(store) in (cached, [])
    new_hashes = {hashlib.sha256(text.encode()).hexdigest() for text in ("alpha", "beta")}
    assert not new_hashes.intersection(row[3] for row in cache_rows(store))


def test_dimension_change_invalidates_cache_and_explicit_retry_rebuilds_all_sources(tmp_path):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "alpha"})
    store.reindex(workspace)
    before = published(store)
    (workspace.root / "memory/b.md").write_text("beta", encoding="utf-8")
    provider.dimensions = 2
    with pytest.raises(ValueError, match="malformed vector response"):
        store.reindex(workspace)
    assert published(store) == before
    assert cache_rows(store) == []
    before_retry = len(provider.calls)
    assert store.reindex(workspace) == 2
    assert sorted(text for call in provider.calls[before_retry:] for text in call) == ["alpha", "beta"]
    assert store.read_index_meta()["vectorDims"] == 2
    assert {len(json.loads(row[0])) for row in rows(store, "SELECT embedding FROM chunks")} == {2}


def test_valid_cache_survives_later_atomic_index_publication_failure(tmp_path):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "old alpha"})
    store.reindex(workspace)
    before = published(store)
    (workspace.root / "memory/a.md").write_text("new beta", encoding="utf-8")
    with store.connect() as db:
        db.execute("CREATE TRIGGER fail_publication BEFORE INSERT ON chunks "
                   "BEGIN SELECT RAISE(ABORT, 'publication failed'); END")
    with pytest.raises(sqlite3.IntegrityError, match="publication failed"):
        store.reindex(workspace)
    assert published(store) == before
    assert len(cache_rows(store)) == 2
    calls = list(provider.calls)
    with store.connect() as db:
        db.execute("DROP TRIGGER fail_publication")
    store.reindex(workspace)
    assert provider.calls == calls
    assert rows(store, "SELECT text FROM chunks") == [("new beta",)]


@pytest.mark.parametrize("mutation", ["update", "delete", "fifo"])
def test_changed_source_during_provider_call_cannot_enter_cache(tmp_path, mutation):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "old alpha"})
    store.reindex(workspace)
    before, cached = published(store), cache_rows(store)
    target = workspace.root / "memory/a.md"
    target.write_text("new beta", encoding="utf-8")

    def change_source():
        if mutation == "update":
            target.write_text("different gamma", encoding="utf-8")
        else:
            target.unlink()
            if mutation == "fifo":
                os.mkfifo(target)

    provider.callback = change_source
    with pytest.raises(MemoryIndexSourceChangedError, match="Memory source changed"):
        store.reindex(workspace)
    assert published(store) == before
    assert cache_rows(store) == cached


@pytest.mark.parametrize("attribute,value", [("endpoint", "b"), ("model", "new-model")])
def test_provider_generation_change_during_embedding_is_not_mislabeled(tmp_path, attribute, value):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "old alpha"})
    store.reindex(workspace)
    before, cached = published(store), cache_rows(store)
    (workspace.root / "memory/a.md").write_text("new beta", encoding="utf-8")
    provider.callback = lambda: setattr(provider, attribute, value)
    with pytest.raises(MemoryIndexSourceChangedError, match="owner changed"):
        store.reindex(workspace)
    assert published(store) == before
    assert cache_rows(store) == cached


def test_late_provider_change_preserves_captured_metadata_identity(tmp_path, monkeypatch):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "old alpha"})
    store.reindex(workspace)
    captured_key = store.read_index_meta()["providerKey"]
    (workspace.root / "memory/a.md").write_text("new beta", encoding="utf-8")
    connect = store.connect

    def connection_with_mutation():
        db = connect()
        db.create_function("change_provider", 0, lambda: setattr(provider, "endpoint", "b"))
        return db

    monkeypatch.setattr(store, "connect", connection_with_mutation)
    with store.connect() as db:
        db.execute("CREATE TRIGGER late_owner_change AFTER INSERT ON chunks "
                   "BEGIN SELECT change_provider(); END")
    store.reindex(workspace)
    assert store.read_index_meta()["providerKey"] == captured_key
    assert store.index_identity()["status"] == "mismatched"


def test_another_store_publication_cannot_be_overwritten_by_an_old_generation(tmp_path):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "old alpha"})
    store.reindex(workspace)
    (workspace.root / "memory/a.md").write_text("new beta", encoding="utf-8")
    inner = CountingProvider()
    inner.response = [[1, 2, 3, 4]]
    provider.response = [[9, 9, 9, 9]]
    provider.callback = lambda: SQLiteMemoryStore(store.config, inner).reindex(workspace)
    with pytest.raises(MemoryIndexSourceChangedError, match="Memory index changed"):
        store.reindex(workspace)
    assert rows(store, "SELECT embedding FROM chunks") == [("[1, 2, 3, 4]",)]
    cached = cache_rows(store)
    assert len(cached) == 2
    # The outer stale response must not replace the inner committed vector.
    digest = hashlib.sha256(b"new beta").hexdigest()
    from memory_core.index.embedding_cache import decode_memory_embedding
    assert decode_memory_embedding(next(row[4] for row in cached if row[3] == digest)) == [1, 2, 3, 4]


def test_session_projection_is_authoritative_and_revalidated_before_cache_acceptance(tmp_path, monkeypatch):
    store, workspace, provider = create_store(tmp_path, {})
    transcript = tmp_path / "raw.jsonl"
    transcript.write_text('{"raw":"must not be indexed"}\n', encoding="utf-8")
    projection = {"text": "User: first fact"}
    monkeypatch.setattr(workspace, "discover_indexable_files", lambda: [
        MemoryFile("sessions/main/s.jsonl", transcript, "sessions", projection["text"]),
    ])
    store.reindex(workspace)
    assert provider.calls == [["User: first fact"]]
    projection["text"] = "User: second fact"
    before, cached = published(store), cache_rows(store)
    provider.callback = lambda: projection.update(text="User: third fact")
    with pytest.raises(MemoryIndexSourceChangedError, match="Memory source changed"):
        store.reindex(workspace)
    assert published(store) == before
    assert cache_rows(store) == cached


def test_forget_revision_during_embedding_prevents_cache_retention(tmp_path):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "old alpha"})
    ledger = MemoryEntryOriginLedger(lambda agent: store.path)
    store.revision_fence = ledger.revision_fence("main")
    store.reindex(workspace)
    cached = cache_rows(store)
    before = published(store)
    (workspace.root / "memory/a.md").write_text("new beta", encoding="utf-8")
    provider.callback = lambda: ledger.record_session_tombstones("main", ["forgotten-session"])
    with pytest.raises(MemoryIndexRevisionConflictError):
        store.reindex(workspace)
    assert cache_rows(store) == cached
    assert published(store) == before


def test_real_forget_purge_fences_inflight_cache_without_an_external_fence(tmp_path):
    from memory_core.consolidation.forget import forget_memory_entries

    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "old alpha"})
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / "origins.sqlite")
    store.reindex(workspace)
    before = published(store)
    (workspace.root / "memory/a.md").write_text("new beta", encoding="utf-8")
    reports = []

    def forget():
        reports.append(forget_memory_entries(
            config=store.config, agent_id="main", origins=ledger,
            session_ids=["forgotten-session"], store=store, now_ms=1_000,
        ))

    provider.callback = forget
    with pytest.raises(MemoryIndexSourceChangedError, match="Memory index changed"):
        store.reindex(workspace)
    assert len(reports) == 1 and reports[0].artifacts["embeddingCacheRows"] == 1
    assert published(store) == before
    assert cache_rows(store) == []
    assert ledger.list_session_tombstones("main", ["forgotten-session"])


def test_failed_provider_dispatch_leaves_publication_and_cache_untouched_without_retry(tmp_path):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "old alpha"})
    store.reindex(workspace)
    before, cached = published(store), cache_rows(store)
    (workspace.root / "memory/a.md").write_text("new beta", encoding="utf-8")

    def fail():
        raise RuntimeError("scripted provider failure")

    provider.callback = fail
    with pytest.raises(RuntimeError, match="scripted provider failure"):
        store.reindex(workspace)
    assert len(provider.calls) == 2
    assert published(store) == before
    assert cache_rows(store) == cached


def test_reused_database_under_another_workspace_removes_old_sources(tmp_path):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "private alpha"})
    store.reindex(workspace)
    other_root = tmp_path / "other-workspace"
    (other_root / "memory").mkdir(parents=True)
    (other_root / "memory/b.md").write_text("other beta", encoding="utf-8")
    other = MemoryWorkspace(other_root)
    store.reindex(other)
    assert rows(store, "SELECT path FROM chunks") == [("memory/b.md",)]
    assert store.search_memory_keywords("private") == []
    assert provider.calls[-1] == ["other beta"]


def test_fts_only_refresh_never_uses_document_provider(tmp_path):
    provider = CountingProvider()
    provider.response = None
    store, workspace, _ = create_store(tmp_path, {"memory/a.md": "alpha"}, provider, vector=False)
    store.reindex(workspace)
    (workspace.root / "memory/a.md").write_text("beta", encoding="utf-8")
    store.reindex(workspace)
    assert provider.calls == []
    assert cache_rows(store) == []
    assert store.read_index_meta()["model"] == "fts-only"
    assert rows(store, "SELECT embedding FROM chunks") == [("[]",)]


def test_missing_source_chunk_rows_are_rebuilt_without_reembedding(tmp_path):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "alpha"})
    store.reindex(workspace)
    with store.connect() as db:
        db.execute("DELETE FROM chunks")
    store.reindex(workspace)
    assert rows(store, "SELECT text FROM chunks") == [("alpha",)]
    assert len(provider.calls) == 1
    assert len(rows(store, "SELECT * FROM chunks_fts")) == 1


def test_identity_change_rebuilds_sources_while_reusing_compatible_cache(tmp_path):
    store, workspace, provider = create_store(tmp_path, {"memory/a.md": "alpha"})
    store.reindex(workspace)
    with store.connect() as db:
        meta = store.read_index_meta()
        meta["chunkingVersion"] = 0
        db.execute("UPDATE memory_index_meta SET value=? WHERE key=?",
                   (json.dumps(meta), MEMORY_INDEX_META_KEY))
    assert store.index_identity()["status"] == "mismatched"
    store.reindex(workspace)
    assert len(provider.calls) == 1
    assert store.index_identity() == {"status": "valid"}


def test_distinct_curators_and_stores_serialize_write_through_refresh(tmp_path, monkeypatch):
    store, workspace, first_provider = create_store(tmp_path, {"MEMORY.md": "# Preferences\n"})
    first_memory = Memory.from_workspace(
        workspace.root, config=store.config, embedding_provider=first_provider, initialize=False,
    )
    second_provider = CountingProvider()
    second_memory = Memory.from_workspace(
        workspace.root, config=store.config, embedding_provider=second_provider, initialize=False,
    )
    first, second = first_memory.curator(), second_memory.curator()
    embedding_started, release_embedding = threading.Event(), threading.Event()
    second_attempted, second_write_started = threading.Event(), threading.Event()

    def blocked_embedding():
        embedding_started.set()
        assert release_embedding.wait(10), "test did not release the first provider"

    original_write = second._write_target

    def write(*args, **kwargs):
        second_write_started.set()
        return original_write(*args, **kwargs)

    monkeypatch.setattr(second, "_write_target", write)
    first_provider.callback = blocked_embedding

    def second_operation():
        second_attempted.set()
        return second.upsert_user_directive("Prefer betavolcano.")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_result = executor.submit(first.add_memory_entry, "Preferences", "alphaglacier is paused")
        try:
            assert embedding_started.wait(10)
            second_result = executor.submit(second_operation)
            assert second_attempted.wait(10)
            # The second operation started, but its file must remain unwritten
            # until the first write's index publication completes.
            assert not second_write_started.wait(0.1)
            assert not (workspace.root / "USER.md").exists()
        finally:
            release_embedding.set()
        assert first_result.result(timeout=10).after_write_error is None
        assert second_result.result(timeout=10).after_write_error is None
    assert second_write_started.is_set()
    assert "alphaglacier is paused" in (workspace.root / "MEMORY.md").read_text()
    assert "Prefer betavolcano." in (workspace.root / "USER.md").read_text()
    assert [hit.path for hit in store.search_memory_keywords("alphaglacier")] == ["MEMORY.md"]
    assert [hit.path for hit in store.search_memory_keywords("betavolcano")] == ["USER.md"]


@pytest.mark.parametrize("factory", ["standalone", "sdk-replacement"])
@pytest.mark.parametrize("operation", ["memory", "daily"])
def test_custom_after_write_can_join_a_refresh_in_another_thread(tmp_path, factory, operation):
    from memory_core.curation import MemoryCurator

    config = MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(tmp_path, config=config)
    dispatched = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        def refresh_in_worker(result):
            future = executor.submit(memory.store.reindex, memory.workspace)
            dispatched.append(future)
            future.result(timeout=2)

        if factory == "standalone":
            curator = MemoryCurator(tmp_path, after_write=refresh_in_worker)
        else:
            curator = memory.curator()
            curator.after_write = refresh_in_worker
        if operation == "memory":
            written = curator.add_memory_entry("Preferences", "glacier preference")
        else:
            written = curator.append_daily_note("glacier preference")
        assert written.after_write_error is None
    assert len(dispatched) == 1 and dispatched[0].result() >= 1
    assert memory.store.search_memory_keywords("glacier")
