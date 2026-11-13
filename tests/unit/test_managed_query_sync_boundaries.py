"""Real on-search publication joining, retry policy and coherent read boundaries."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import threading

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.forget import plan_memory_index, purge_memory_index
from memory_core.consolidation.origins import MemoryIndexRevisionConflictError
from memory_core.flags import FeatureFlags
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.index.identity import MEMORY_INDEX_META_KEY
from memory_core.index.sqlite_store import MemoryIndexSourceChangedError, SQLiteMemoryStore
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.tools.memory_search import MemorySearchToolContext
from memory_core.tools.search_factory import create_memory_search_tool
from memory_core.workspace import MemoryWorkspace, workspace_index_lock


OLD = "# Note\n\nThe old marker is boundarycedar642.\n"
NEW = "# Note\n\nThe new marker is boundarywillow297.\n"


@contextmanager
def _owner(tmp_path, *, names=("note",), publication="on-search"):
    root = tmp_path / "workspace"
    (root / "memory/topics").mkdir(parents=True)
    for name in names:
        (root / f"memory/topics/{name}.md").write_text(OLD if name == "note" else f"Actual {name} source.\n")
    config = MemoryConfig(root, store_path=tmp_path / "index.sqlite", citation_mode="off",
        session_search=False, flags=FeatureFlags(vector_search=False, temporal_decay=False))
    workspace = MemoryWorkspace(root, index_sources=["memory"])
    options = {} if publication is None else {"memory_publication": publication}
    store = ManagedSQLiteMemoryStore(config, workspace,
        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, **options)
    try:
        yield store, workspace
    finally:
        journal = Path(str(store.path) + "-journal")
        if journal.is_symlink():
            journal.unlink()
        store.close()


def _query(store, query="boundarywillow297"):
    tool = create_memory_search_tool(store.config, store,
        context=MemorySearchToolContext(clock=lambda: 1_794_268_800_000),
        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    result = tool.execute("actual-query", {"query": query, "corpus": "memory", "minScore": 0})
    assert json.loads(result["content"][0]["text"]) == result["details"]
    return result["details"]


def _journal_fault(store):
    path = Path(str(store.path) + "-journal")
    assert not path.exists() and not path.is_symlink()
    target = path.parent / "actual-missing-parent" / "journal"
    assert not target.parent.exists()
    path.symlink_to(target)
    return path


def _settled(store):
    with store._condition:
        assert store._condition.wait_for(lambda: not store._memory_active, timeout=5)
    return store.lifecycle_snapshot()["memoryPublication"]


def _purge(store, path):
    plan = plan_memory_index(store, agent_id="main", changed_paths={path}, removed_paths={path},
        session_ids=set(), excluded_session_ids=set(), matches_memory=lambda _text: False)
    assert plan.chunks and purge_memory_index(store, plan)


def _pending_writer(store, monkeypatch):
    pending, original = threading.Event(), store.connect

    def connect():
        db = original()
        db.set_trace_callback(lambda sql: pending.set() if sql.strip().upper() == "BEGIN IMMEDIATE" else None)
        return db

    monkeypatch.setattr(store, "connect", connect)
    return pending


def _join_observer(store, monkeypatch, count=2):
    joined, operations, original = threading.Event(), [], store._update

    def update(operation, **fields):
        original(operation, **fields)
        if "joinedFullSync" in fields:
            operations.append(operation["id"])
            if len(operations) == count:
                joined.set()

    monkeypatch.setattr(store, "_update", update)
    return joined, operations


def test_real_pending_writer_is_shared_by_force_joiner_and_cold_query_and_close(tmp_path, monkeypatch):
    with _owner(tmp_path) as (store, workspace):
        pending = _pending_writer(store, monkeypatch)
        joined, operations = _join_observer(store, monkeypatch)
        with closing(sqlite3.connect(store.path)) as gate, ThreadPoolExecutor(max_workers=4) as pool:
            gate.execute("BEGIN IMMEDIATE")
            try:
                leader = pool.submit(store.reindex, workspace, force=True)
                assert pending.wait(2)
                follower = pool.submit(store.reindex, workspace, force=True)
                query = pool.submit(_query, store, "boundarycedar642")
                assert joined.wait(2)
                closing_store = pool.submit(store.close)
                with store._condition:
                    assert store._condition.wait_for(lambda: store._closing, timeout=2)
                assert not leader.done() and not follower.done() and not query.done() and not closing_store.done()
                with pytest.raises(RuntimeError, match="closed"):
                    store.search("boundarycedar642")
            finally:
                gate.rollback()
            assert leader.result(5) == follower.result(5) == 1
            actual = query.result(5)
            assert actual["results"][0]["snippet"] == OLD and "warning" not in actual
            assert closing_store.result(5) is None and store.closed
        lifecycle = store.lifecycle_snapshot()
        assert len(operations) == 2
        assert len([row for row in lifecycle["operations"] if "fullSync" in row]) == 1
        assert len([row for row in lifecycle["operations"] if "joinedFullSync" in row]) == 2
        assert len(lifecycle["repairs"]) == 1 and lifecycle["repairs"][0]["reason"] == "search-bootstrap"
        assert store.read_published_index()["revision"] == 1


def test_joined_real_storage_failure_shares_exact_exception_and_keeps_query_warning_unchanged(tmp_path, monkeypatch):
    with _owner(tmp_path) as (store, workspace):
        pending = _pending_writer(store, monkeypatch)
        joined, _ = _join_observer(store, monkeypatch)
        before = store.read_published_index()
        with closing(sqlite3.connect(store.path)) as gate, ThreadPoolExecutor(max_workers=3) as pool:
            gate.execute("BEGIN IMMEDIATE")
            try:
                leader = pool.submit(store.reindex, workspace, force=True)
                assert pending.wait(2)
                fault = _journal_fault(store)
                follower = pool.submit(store.reindex, workspace, force=True)
                query = pool.submit(_query, store, "boundarycedar642")
                assert joined.wait(2)
            finally:
                gate.rollback()
            first_error = leader.exception(5)
            assert isinstance(first_error, sqlite3.OperationalError)
            assert follower.exception(5) is first_error
            actual = query.result(5)
            assert actual["unavailable"] is True and actual["results"] == []
            assert "Automatic memory index repair" not in actual["warning"]
        assert store.read_published_index() == before
        assert len([row for row in store.lifecycle_snapshot()["operations"] if "fullSync" in row]) == 1
        fault.unlink()
        assert _query(store, "boundarycedar642")["results"][0]["snippet"] == OLD


def test_automatic_newer_refusal_enters_base_then_preserves_racing_metadata(tmp_path, monkeypatch):
    with _owner(tmp_path, names=()) as (store, workspace):
        store.reindex(workspace)
        (workspace.root / "memory/topics/note.md").write_text(OLD)
        planned, release = threading.Event(), threading.Event()
        original, base = store.reindex, SQLiteMemoryStore.reindex
        base_entries = []

        def observe_base(receiver, bound_workspace, **options):
            base_entries.append((receiver, bound_workspace, options))
            return base(receiver, bound_workspace, **options)

        def delayed_automatic(bound_workspace, **options):
            if getattr(store._local, "automatic_reindex", None) is not None:
                planned.set()
                assert release.wait(5)
            return original(bound_workspace, **options)

        monkeypatch.setattr(SQLiteMemoryStore, "reindex", observe_base)
        monkeypatch.setattr(store, "reindex", delayed_automatic)
        with ThreadPoolExecutor(max_workers=1) as pool:
            query = pool.submit(_query, store, "boundarycedar642")
            try:
                assert planned.wait(2)
                lock = workspace_index_lock(workspace.root)
                assert lock.acquire(timeout=1), "Automatic admission must release the planning workspace lock"
                try:
                    metadata = store.read_index_meta()
                    metadata["chunkingVersion"] += 1
                    with closing(store.connect()) as db, db:
                        db.execute("UPDATE memory_index_meta SET value=? WHERE key=?",
                                   (json.dumps(metadata), MEMORY_INDEX_META_KEY))
                    before = store.read_published_index()
                finally:
                    lock.release()
            finally:
                release.set()
            result = query.result(5)
        assert result["unavailable"] is True and result["results"] == []
        assert len(base_entries) == 1
        assert store.read_index_meta() == metadata and store.read_published_index() == before
        request = store.lifecycle_snapshot()["repairs"][-1]
        assert request["state"] == "completed" and request["returned"] == 0
        assert request["automaticRefusal"]["versionOrder"] == "newer"
        store.reindex(workspace, force=True)
        assert _query(store, "boundarycedar642")["results"][0]["snippet"] == OLD


def test_warm_preflight_refusal_recovers_through_real_scoped_jobs_without_full_notice(tmp_path):
    with _owner(tmp_path) as (store, workspace):
        _query(store, "boundarycedar642")
        (workspace.root / "memory/topics/note.md").write_text(NEW)
        fault = _journal_fault(store)
        with pytest.raises(sqlite3.OperationalError):
            store.reindex(workspace, force=True)
        assert not store._full_retry_required
        first = _query(store)
        assert first["results"] == [] and first["stale"] is True
        assert "Automatic memory index repair" not in first["warning"]
        assert _settled(store)["jobs"][-1]["state"] == "failed"
        fault.unlink()
        second = _query(store)
        assert second["results"] == [] and second["stale"] is True
        assert "Automatic memory index repair" not in second["warning"]
        publication = _settled(store)
        assert [row["state"] for row in publication["jobs"]] == ["failed", "completed"]
        assert "lastSyncError" not in store.status()
        assert _query(store)["results"][0]["snippet"] == NEW
        assert store.lifecycle_snapshot()["automaticRebuildNotice"]["sequence"] == 1


@pytest.mark.parametrize("automatic_conflicts", [1, 2])
def test_real_full_cas_retry_is_bounded_and_preserves_pinned_failure(tmp_path, monkeypatch, automatic_conflicts):
    names = ("note", "rival-prep", "rival-a", "rival-b")
    with _owner(tmp_path, names=names) as (store, workspace):
        _query(store, "boundarycedar642")
        (workspace.root / "memory/topics/note.md").write_text(NEW)
        paths = deque(f"memory/topics/{name}.md" for name in names[1:2 + automatic_conflicts])
        original, publications, caught = store.publish_prepared_index, [], []

        def publish(prepared, revision, **options):
            publications.append(revision)
            if paths:
                _purge(store, paths.popleft())
            try:
                return original(prepared, revision, **options)
            except MemoryIndexRevisionConflictError as error:
                caught.append(error)
                raise

        monkeypatch.setattr(store, "publish_prepared_index", publish)
        with pytest.raises(MemoryIndexRevisionConflictError) as preparation:
            store.reindex(workspace, force=True)
        assert store._full_retry_required
        initial_error = str(preparation.value)

        result = _query(store)

        assert result["results"] == [] and result["stale"] is True
        assert initial_error in result["warning"]
        assert "Automatic memory index repair was requested." in result["warning"]
        publication = _settled(store)
        assert len(publications) == 3 and len(caught) == 1 + automatic_conflicts
        assert len(publication["jobs"]) == 1 and publication["jobs"][0]["fullRetry"] is True
        if automatic_conflicts == 1:
            assert publication["jobs"][0]["state"] == "completed"
            assert "lastSyncError" not in store.status() and not store._full_retry_required
            assert any(row["text"] == NEW for row in store.read_published_index()["chunks"])
        else:
            assert publication["jobs"][0]["state"] == "failed" and store._full_retry_required
            assert store.status()["lastSyncError"] == str(caught[-1])
            assert not any(row["text"] == NEW for row in store.read_published_index()["chunks"])


def test_real_source_change_during_automatic_rebuild_is_not_treated_as_typed_retry(tmp_path, monkeypatch):
    with _owner(tmp_path, names=("note", "rival-prep")) as (store, workspace):
        _query(store, "boundarycedar642")
        original_publish, preparing = store.publish_prepared_index, store._prepare_source_chunks

        def competing_purge(prepared, revision, **options):
            _purge(store, "memory/topics/rival-prep.md")
            return original_publish(prepared, revision, **options)

        monkeypatch.setattr(store, "publish_prepared_index", competing_purge)
        with pytest.raises(MemoryIndexRevisionConflictError):
            store.reindex(workspace, force=True)
        monkeypatch.setattr(store, "publish_prepared_index", original_publish)
        attempts = []

        def source_changes(entry, *options):
            chunks = preparing(entry, *options)
            if entry.path == "memory/topics/note.md":
                attempts.append(True)
                (workspace.root / entry.path).write_text(NEW)
            return chunks

        monkeypatch.setattr(store, "_prepare_source_chunks", source_changes)
        _query(store)
        publication = _settled(store)
        assert len(attempts) == 1
        assert publication["jobs"][-1]["state"] == "failed"
        assert publication["jobs"][-1]["error"]["name"] == MemoryIndexSourceChangedError.__name__


def test_default_on_write_remains_explicit_and_recursive_producer_cannot_self_join(tmp_path, monkeypatch):
    default_dir, managed_dir = tmp_path / "default", tmp_path / "managed"
    with _owner(default_dir, publication=None) as (store, workspace):
        fault = _journal_fault(store)
        with pytest.raises(sqlite3.OperationalError):
            store.reindex(workspace, force=True)
        fault.unlink()
        assert _query(store, "boundarycedar642")["unavailable"] is True
        assert len([row for row in store.lifecycle_snapshot()["operations"] if row["name"] == "reindex"]) == 1
    with _owner(managed_dir) as (store, workspace):
        original = store._on_index_preparation_admitted

        def recursive_request():
            original()
            store.reindex(workspace, force=True)

        monkeypatch.setattr(store, "_on_index_preparation_admitted", recursive_request)
        with pytest.raises(RuntimeError, match="own producer"):
            store.reindex(workspace, force=True)
        assert store._full_sync is None
