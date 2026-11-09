"""Real query-generation admission and close custody with session publication."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.host.session_publication import SessionPublicationController
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.workspace import MemoryWorkspace


NOW = 1_794_182_400_000


def _owner(tmp_path):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    (root / "memory/2026-11-09.md").write_text("My drink preference is cedar tea.\n")
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW)
    catalog.upsert_session("agent:main:writer", {"sessionId": "writer", "updatedAt": NOW})
    catalog.append_message("writer", {"role": "user", "content": "Remember my drink preference: cedar tea."},
                           session_key="agent:main:writer", event_id="writer:1", now_ms=NOW)
    workspace = MemoryWorkspace(root, session_catalog=catalog, index_sources=("memory", "sessions"))
    config = MemoryConfig(workspace_dir=root, store_path=tmp_path / "index.sqlite",
                          flags=FeatureFlags(vector_search=False, temporal_decay=False))
    store = ManagedSQLiteMemoryStore(config, workspace)
    store.reindex(workspace)
    with store.connect() as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    controller = SessionPublicationController(store, workspace, catalog)
    return store, workspace, catalog, controller


def _append_fresh(catalog):
    catalog.upsert_session("agent:main:fresh", {"sessionId": "fresh", "updatedAt": NOW + 1})
    catalog.append_message("fresh", {"role": "user", "content":
        "What drink preference did I ask you to remember? Please look up the previous preference."},
        session_key="agent:main:fresh", event_id="fresh:1", now_ms=NOW + 1)


def test_startup_publication_finishes_while_query_keeps_real_admitted_generation(tmp_path, monkeypatch):
    store, _, catalog, controller = _owner(tmp_path)
    previous = store.search("drink preference", sources={"memory"})
    previous_revision = store.index_revision()
    _append_fresh(catalog)
    store.bind_session_publication(controller)
    admit = store._on_search_snapshot

    def publish_inside_read_lease(db):
        admit(db)
        # WAL permits a genuine writer commit while the query retains its
        # already-read SQLite generation. No saved rows or timing sleep stands
        # in for the database's actual reader snapshot.
        assert controller.wait_idle(timeout=5)
        assert store.index_revision() > previous_revision

    monkeypatch.setattr(store, "_on_search_snapshot", publish_inside_read_lease)
    try:
        actual = store.search("drink preference", sources={"memory"})
        assert actual == previous
        snapshot = store.lifecycle_snapshot()
        assert snapshot["sessionReadAdmissions"][-1]["revision"] == previous_revision
        assert store.index_revision() > previous_revision
        warm = store.search("drink preference", sources={"memory"})
        assert warm[0].text_score != previous[0].text_score
        assert store.lifecycle_snapshot()["sessionReadAdmissions"][-1]["revision"] == store.index_revision()
    finally:
        store.close()


def test_close_joins_query_which_has_not_yet_started_controller(tmp_path, monkeypatch):
    store, _, _, controller = _owner(tmp_path)
    store.bind_session_publication(controller)
    entered, release = threading.Event(), threading.Event()
    admit = store._on_search_snapshot

    def hold_snapshot(db):
        entered.set()
        assert release.wait(5)
        admit(db)

    monkeypatch.setattr(store, "_on_search_snapshot", hold_snapshot)
    with ThreadPoolExecutor(max_workers=2) as pool:
        search = pool.submit(store.search, "drink preference")
        assert entered.wait(5)
        closing = pool.submit(store.close)
        with store._condition:
            assert store._condition.wait_for(lambda: store._closing, timeout=5)
        try:
            assert not closing.done()
            with pytest.raises(RuntimeError, match="closed"):
                store.search("new caller")
        finally:
            release.set()
        assert search.result(timeout=5)
        closing.result(timeout=5)
    assert store.closed and store.lifecycle_snapshot()["activeOperations"] == 0
    assert controller.status()["notStarted"] is True


def test_binding_is_inert_and_rejects_other_physical_owners(tmp_path):
    store, workspace, catalog, controller = _owner(tmp_path)
    try:
        other = ManagedSQLiteMemoryStore(store.config, workspace)
        try:
            with pytest.raises(ValueError, match="exact managed index"):
                other.bind_session_publication(controller)
        finally:
            other.close()
        store.bind_session_publication(controller)
        assert controller.status()["notStarted"] is True
        assert store.lifecycle_snapshot()["sessionReadAdmissions"] == []
        assert catalog is controller.catalog
        assert store.search(" ") == []
        assert controller.status()["notStarted"] is True
    finally:
        store.close()


def test_close_joins_admitted_controller_job_before_it_enters_store_lane(tmp_path, monkeypatch):
    store, _, catalog, controller = _owner(tmp_path)
    _append_fresh(catalog)
    store.bind_session_publication(controller)
    entered, release = threading.Event(), threading.Event()
    publish = store.reindex_sources
    revision = store.index_revision()

    def hold_publication(workspace, **options):
        assert controller.owns_current_job()
        entered.set()
        assert release.wait(5)
        return publish(workspace, **options)

    monkeypatch.setattr(store, "reindex_sources", hold_publication)
    controller.start()
    assert entered.wait(5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        closing = pool.submit(store.close)
        with store._condition:
            assert store._condition.wait_for(lambda: store._closing, timeout=5)
        try:
            assert not closing.done()
            with pytest.raises(RuntimeError, match="closed"):
                publish(store._workspace, sources={"memory"})
        finally:
            release.set()
        closing.result(timeout=5)
    assert store.closed
    assert store.index_revision() > revision
    jobs = controller.lifecycle_snapshot()["jobs"]
    assert jobs[-1]["state"] == "completed"


def test_scoped_managed_sync_refuses_other_workspace_and_closed_owner(tmp_path):
    store, workspace, _, _ = _owner(tmp_path)
    with pytest.raises(ValueError, match="bound workspace"):
        store.reindex_sources(MemoryWorkspace(tmp_path / "other"), sources={"memory"})
    store.close()
    with pytest.raises(RuntimeError, match="closed"):
        store.reindex_sources(workspace, sources={"sessions"})


def test_default_timer_publishes_a_real_committed_session_without_explicit_flush(tmp_path, monkeypatch):
    store, _, catalog, controller = _owner(tmp_path)
    store.bind_session_publication(controller)
    store.search("drink preference")
    assert controller.wait_idle(timeout=5)
    published = threading.Event()
    publish = store.reindex_sources

    def observe_publication(workspace, **options):
        result = publish(workspace, **options)
        published.set()
        return result

    monkeypatch.setattr(store, "reindex_sources", observe_publication)
    try:
        _append_fresh(catalog)
        assert controller.status()["timerPending"] is True
        # Exercise the actual default five-second Timer and genuine committed
        # corpus, rather than driving an injected scheduler or flushing early.
        assert published.wait(10)
        assert controller.wait_idle(timeout=5)
        assert controller.status()["pending"] is False
        assert any(row["path"] == "sessions/main/fresh.jsonl"
                   for row in store.read_published_index()["sources"])
    finally:
        store.close()
