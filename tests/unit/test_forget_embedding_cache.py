"""Persistent derived vectors must participate in session forget and recovery."""
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.forget import (
    IndexPlan,
    forget_memory_entries,
    plan_memory_index,
    purge_memory_index,
)
from memory_core.consolidation.origins import MemoryEntryOriginLedger
from memory_core.embeddings import FakeEmbeddingProvider
from memory_core.index.embedding_cache import upsert_memory_embedding_cache
from memory_core.index.identity import INDEX_SOURCES_TABLE, INDEX_SYNC_TABLE
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


def _store(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    config = MemoryConfig(workspace_dir=root, store_path=tmp_path / "index.sqlite")
    store = SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=2))
    origins = MemoryEntryOriginLedger(lambda agent: tmp_path / f"origins-{agent}.sqlite")
    return store, origins


def _seed(store, *, provider="fake", chunk_hash="retained"):
    with store.connect() as db:
        upsert_memory_embedding_cache(
            db, enabled=True, provider={"id": provider, "model": "model"}, provider_key="key",
            entries=[{"hash": chunk_hash, "embedding": [0.5, 0.25]}], now=1,
        )


def _count(store):
    with store.connect() as db:
        return db.execute("SELECT COUNT(*) FROM memory_embedding_cache").fetchone()[0]


def _generation(store):
    with store.connect() as db:
        return db.execute(
            f"SELECT revision, needs_rebuild FROM {INDEX_SYNC_TABLE} WHERE id = 1"
        ).fetchone()


def _forget(store, origins, **changes):
    return forget_memory_entries(
        config=store.config, agent_id="main", origins=origins,
        session_ids=["forgotten-session"], store=store, now_ms=1_000, **changes,
    )


def test_cache_only_forget_counts_all_identities_and_dry_run_changes_nothing(tmp_path):
    store, origins = _store(tmp_path)
    _seed(store)
    _seed(store, provider="another-provider", chunk_hash="other")
    before = _generation(store)

    report = _forget(store, origins, dry_run=True)
    assert report.artifacts["indexChunks"] == 0
    assert report.artifacts["indexSources"] == 0
    assert report.artifacts["embeddingCacheRows"] == 2
    assert _count(store) == 2
    assert _generation(store) == before
    assert not origins.list_session_tombstones("main", ["forgotten-session"])

    committed = _forget(store, origins)
    assert committed.artifacts["embeddingCacheRows"] == 2
    assert _count(store) == 0
    assert _generation(store) == (before[0] + 1, 1)
    assert origins.list_session_tombstones("main", ["forgotten-session"])


def test_forget_clears_cache_even_when_unrelated_index_chunks_remain(tmp_path):
    store, origins = _store(tmp_path)
    root = Path(store.config.workspace_dir)
    (root / "MEMORY.md").write_text("An unrelated durable preference.\n", encoding="utf-8")
    store.reindex(MemoryWorkspace(root))
    before = store.count_chunks()
    assert before > 0 and _count(store) > 0

    report = _forget(store, origins)
    assert report.artifacts["indexChunks"] == 0
    assert report.artifacts["embeddingCacheRows"] > 0
    assert store.count_chunks() == before
    assert _count(store) == 0


def test_no_resolved_sessions_leave_the_cache_and_generation_untouched(tmp_path):
    store, origins = _store(tmp_path)
    _seed(store)
    before = _generation(store)
    report = forget_memory_entries(
        config=store.config, agent_id="main", origins=origins,
        participants=["not-in-the-session-roster"], store=store,
    )
    assert report.session_ids == []
    assert report.artifacts["embeddingCacheRows"] == 0
    assert _count(store) == 1 and _generation(store) == before


def test_cache_added_after_an_empty_plan_is_still_purged(tmp_path):
    store, _origins = _store(tmp_path)
    plan = plan_memory_index(
        store, agent_id="main", changed_paths=set(), removed_paths=set(),
        session_ids={"forgotten-session"}, excluded_session_ids=set(),
        matches_memory=lambda text: False,
    )
    assert plan.embedding_cache_rows == 0 and plan.purge_cache
    _seed(store)  # A valid earlier provider batch finished after planning.

    assert purge_memory_index(store, plan)
    assert _count(store) == 0
    assert _generation(store) == (1, 1)


def test_cache_failure_rolls_back_chunk_source_and_generation_changes(tmp_path):
    store, _origins = _store(tmp_path)
    root = Path(store.config.workspace_dir)
    (root / "MEMORY.md").write_text("A durable preference.\n", encoding="utf-8")
    store.reindex(MemoryWorkspace(root))
    with store.connect() as db:
        rows = db.execute("SELECT id, path, source FROM chunks").fetchall()
        sources = db.execute(f"SELECT * FROM {INDEX_SOURCES_TABLE}").fetchall()
        fts_count = db.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
        db.execute(
            "CREATE TRIGGER fail_cache_purge BEFORE DELETE ON memory_embedding_cache "
            "BEGIN SELECT RAISE(ABORT, 'cache purge failed'); END"
        )
    generation, cache_count = _generation(store), _count(store)
    plan = IndexPlan(rows, [("MEMORY.md", "memory")], fts_count, cache_count, True)
    with pytest.raises(sqlite3.DatabaseError, match="cache purge failed"):
        purge_memory_index(store, plan)

    assert _generation(store) == generation and _count(store) == cache_count
    with store.connect() as db:
        assert db.execute("SELECT id, path, source FROM chunks").fetchall() == rows
        assert db.execute(f"SELECT * FROM {INDEX_SOURCES_TABLE}").fetchall() == sources
        assert db.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0] == fts_count


def test_failed_cache_purge_keeps_the_tombstone_for_an_explicit_retry(tmp_path):
    store, origins = _store(tmp_path)
    _seed(store)
    with store.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_cache_purge BEFORE DELETE ON memory_embedding_cache "
            "BEGIN SELECT RAISE(ABORT, 'cache purge failed'); END"
        )
    before = _generation(store)
    with pytest.raises(sqlite3.DatabaseError, match="cache purge failed"):
        _forget(store, origins)
    assert origins.list_session_tombstones("main", ["forgotten-session"])
    assert _count(store) == 1 and _generation(store) == before

    with store.connect() as db:
        db.execute("DROP TRIGGER fail_cache_purge")
    assert _forget(store, origins).artifacts["embeddingCacheRows"] == 1
    assert _count(store) == 0 and _generation(store) == (before[0] + 1, 1)


def test_legacy_index_without_cache_or_private_generation_remains_supported(tmp_path):
    store, origins = _store(tmp_path)
    with store.connect() as db:
        for table in ("memory_embedding_cache", INDEX_SOURCES_TABLE, INDEX_SYNC_TABLE):
            db.execute(f"DROP TABLE {table}")
    legacy = SimpleNamespace(config=store.config, connect=store.connect)
    report = _forget(legacy, origins)
    assert report.artifacts["embeddingCacheRows"] == 0
    assert origins.list_session_tombstones("main", ["forgotten-session"])
