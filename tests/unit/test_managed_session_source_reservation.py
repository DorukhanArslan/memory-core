"""Real source publication excludes concurrent catalog commits without a retry."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import os
import sqlite3
import threading

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.flags import FeatureFlags
from memory_core.host.managed_session import ManagedHostSession
from memory_core.index.sqlite_store import MemoryIndexSourceChangedError
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.workspace import workspace_index_lock


NOW = 1_794_182_400_000
KEY = "agent:main:dm:source-reservation"
SESSION = "source-reservation"
PATH = f"sessions/main/{SESSION}.jsonl"


class _Call:
    def __init__(self, callback):
        self.callback, self.cancelled = callback, False

    def cancel(self):
        self.cancelled = True


class _Scheduler:
    def __init__(self):
        self.calls = []

    def __call__(self, delay, callback):
        call = _Call(callback)
        self.calls.append((delay, call))
        return call


def _append(catalog, text, event):
    return catalog.append_message(SESSION, {"role": "user", "content": text}, session_key=KEY,
                                  event_id=event, now_ms=NOW)


def _owner(tmp_path, *, colocated=False, alias=False):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "MEMORY.md").write_text("An unrelated unchanged memory source.\n")
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW)
    catalog.upsert_session(KEY, {"sessionId": SESSION, "updatedAt": NOW})
    _append(catalog, "Initial published session content.", "initial")
    index = catalog.path if colocated else tmp_path / "index.sqlite"
    if alias:
        index = tmp_path / "index-alias.sqlite"
        os.link(catalog.path, index)
    config = MemoryConfig(workspace, store_path=index,
                          flags=FeatureFlags(vector_search=False, temporal_decay=False))
    scheduler = _Scheduler()
    owner = ManagedHostSession.open(workspace, catalog=catalog, config=config, scheduler=scheduler)
    owner.store.reindex(owner.kit.memory.workspace)
    return owner, catalog, scheduler


def _gate(store, monkeypatch, *, source):
    entered, release = threading.Event(), threading.Event()
    actual = store._prepare_source_chunks
    observed = []

    def prepare(entry, *args):
        if entry.source == source and not observed:
            observed.append(entry)
            entered.set()
            assert release.wait(5), "The fixture must release the real source preparer"
        return actual(entry, *args)

    monkeypatch.setattr(store, "_prepare_source_chunks", prepare)
    return entered, release, observed


def test_startup_reserves_actual_catalog_source_until_publication_and_defers_later_commit(tmp_path, monkeypatch):
    owner, catalog, scheduler = _owner(tmp_path)
    peer = MemorySessionCatalog(catalog.path, clock_ms=lambda: NOW)
    _append(catalog, "Second source revision before startup.", "second")
    entered, release, observed = _gate(owner.store, monkeypatch, source="sessions")
    attempted = threading.Event()
    connect = peer._connect
    catalog_connect = catalog._connect
    catalog_statements = []

    def traced_catalog():
        db = catalog_connect()
        db.set_trace_callback(lambda sql: catalog_statements.append((threading.get_ident(), sql)))
        return db

    def traced():
        db = connect()
        db.set_trace_callback(lambda sql: attempted.set() if sql == "BEGIN IMMEDIATE" else None)
        return db

    monkeypatch.setattr(peer, "_connect", traced)
    monkeypatch.setattr(catalog, "_connect", traced_catalog)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = None
        try:
            owner.controller.start()
            assert entered.wait(5)
            guard = workspace_index_lock(owner.kit.memory.workspace.root)
            unexpectedly_acquired = guard.acquire(blocking=False)
            if unexpectedly_acquired:
                guard.release()
            assert not unexpectedly_acquired
            with closing(sqlite3.connect(catalog.path, timeout=0)) as probe:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    probe.execute("BEGIN IMMEDIATE")
            future = executor.submit(_append, peer, "Third source revision during actual publication.", "third")
            assert attempted.wait(5)
            assert not future.done(), "A catalog commit crossed the admitted publisher's source reservation"
            assert len(catalog.read_transcript(SESSION, session_key=KEY).events) == 3
            release.set()
            assert future.result(timeout=5)["appended"]
            assert owner.controller.wait_idle(5)
            status = owner.controller.status()
            assert status["lastError"] is None and all(job["state"] == "completed" for job in status["jobs"])
            assert status["publishedGeneration"] < status["generation"]
            assert status["pendingPaths"] == [PATH] and status["timerPending"]
            published = owner.store.read_published_index()
            source = next(row for row in published["sources"] if row["path"] == PATH)
            assert source["hash"] == observed[0].hash
            texts = [row["text"] for row in published["chunks"] if row["path"] == PATH]
            assert any("Second source revision" in text for text in texts)
            assert all("Third source revision" not in text for text in texts)
            operation = next(row for row in owner.store.lifecycle_snapshot()["operations"]
                             if row["name"] == "reindex-sources")
            receipt = operation["catalogSourceReservation"]
            assert receipt["acquired"] and receipt["released"] and receipt["catalogChanges"] == 0
            assert receipt["catalogRevisionBefore"] == receipt["catalogRevisionAfter"]
            assert operation["state"] == "completed"
            statements = [sql for thread, sql in catalog_statements if thread == operation["threadId"]]
            assert "BEGIN IMMEDIATE" in statements
            assert all(sql.split()[0].upper() in {"BEGIN", "SELECT", "ROLLBACK"} for sql in statements)
            owner.close()
            assert owner.store.read_published_index() == published
            assert owner.controller.status()["pendingPaths"] == [PATH]
            assert not owner.controller.status()["timerPending"]
            assert len(scheduler.calls) == 1 and scheduler.calls[0][1].cancelled
        finally:
            release.set()
            if future is not None:
                future.result(timeout=5)
            owner.close()


def test_actual_reservation_issues_no_catalog_mutation_and_releases_for_peer_writer(tmp_path):
    owner, catalog, _scheduler = _owner(tmp_path)
    before = catalog.snapshot()
    try:
        with catalog._reserve_index_sources() as receipt:
            assert receipt["acquired"] and not receipt["released"]
            # Actual independent SQLite readers remain admitted under the reservation.
            assert catalog.snapshot() == before
            with closing(sqlite3.connect(catalog.path, timeout=0)) as peer:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    peer.execute("BEGIN IMMEDIATE")
        assert receipt["released"] and receipt["catalogChanges"] == 0
        assert receipt["catalogRevisionBefore"] == receipt["catalogRevisionAfter"]
        assert catalog.snapshot() == before
        with closing(sqlite3.connect(catalog.path, timeout=0)) as peer:
            peer.execute("BEGIN IMMEDIATE")
            peer.rollback()
    finally:
        owner.close()


def test_nested_source_reservation_fails_promptly_without_releasing_its_owner(tmp_path):
    owner, catalog, _scheduler = _owner(tmp_path)
    try:
        with catalog._reserve_index_sources() as receipt:
            with pytest.raises(RuntimeError, match="already active"):
                with catalog._reserve_index_sources():
                    pytest.fail("A nested reservation cannot become a second physical owner")
            assert receipt["acquired"] and not receipt["released"]
            assert catalog.snapshot().revision == receipt["catalogRevisionBefore"]
        assert receipt["released"] and receipt["catalogChanges"] == 0
    finally:
        owner.close()


def test_memory_only_publication_does_not_take_an_unrelated_catalog_reservation(tmp_path):
    owner, catalog, _scheduler = _owner(tmp_path)
    (owner.kit.memory.workspace.root / "MEMORY.md").write_text("A changed real memory source.\n")
    with ThreadPoolExecutor(max_workers=1) as executor, closing(sqlite3.connect(catalog.path)) as lease:
        try:
            lease.execute("BEGIN IMMEDIATE")
            future = executor.submit(owner.store.reindex_sources, owner.kit.memory.workspace, sources={"memory"})
            assert future.result(timeout=5) == 1
            operation = owner.store.lifecycle_snapshot()["operations"][-1]
            assert "catalogSourceReservation" not in operation
        finally:
            lease.rollback()
            owner.close()


@pytest.mark.parametrize("alias", [False, True])
def test_colocated_catalog_preserves_strict_validation_without_self_locking(tmp_path, monkeypatch, alias):
    owner, catalog, _scheduler = _owner(tmp_path, colocated=True, alias=alias)
    peer = MemorySessionCatalog(catalog.path, clock_ms=lambda: NOW)
    _append(catalog, "Second source revision before scoped publication.", "second")
    before = owner.store.read_published_index()
    entered, release, _observed = _gate(owner.store, monkeypatch, source="sessions")
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            future = executor.submit(owner.store.reindex_sources, owner.kit.memory.workspace, sources={"sessions"})
            assert entered.wait(5)
            assert _append(peer, "Actual source mutation in the shared database.", "third")["appended"]
            release.set()
            with pytest.raises(MemoryIndexSourceChangedError, match="source changed"):
                future.result(timeout=5)
            assert owner.store.read_published_index() == before
            operation = owner.store.lifecycle_snapshot()["operations"][-1]
            assert operation["state"] == "failed"
            assert operation["catalogSourceReservation"] == {
                "catalogPath": str(catalog.path), "agentId": "main", "mode": "strict-source-validation",
                "acquired": False, "reason": "catalog-and-index-share-physical-database", "released": True}
        finally:
            release.set()
            owner.close()


def test_real_filesystem_source_change_still_fails_the_original_strict_validation(tmp_path, monkeypatch):
    owner, _catalog, _scheduler = _owner(tmp_path)
    source = owner.kit.memory.workspace.root / "MEMORY.md"
    source.write_text("Second actual memory content.\n")
    before = owner.store.read_published_index()
    entered, release, _observed = _gate(owner.store, monkeypatch, source="memory")
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            future = executor.submit(owner.store.reindex_sources, owner.kit.memory.workspace, sources={"memory"})
            assert entered.wait(5)
            source.write_text("A third actual filesystem source mutation.\n")
            release.set()
            with pytest.raises(MemoryIndexSourceChangedError, match="source changed"):
                future.result(timeout=5)
            assert owner.store.read_published_index() == before
            assert owner.store.lifecycle_snapshot()["operations"][-1]["state"] == "failed"
        finally:
            release.set()
            owner.close()


def test_process_memory_catalog_keeps_its_existing_strict_source_validation(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    durable = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW)
    private_key = "agent:main:dashboard:incognito-reservation"
    durable.upsert_session(private_key, {"sessionId": "private-root"})
    catalog = durable._key_catalog(private_key)
    peer = durable._key_catalog(private_key)
    assert catalog._memory_uri and catalog._memory_lock is peer._memory_lock
    catalog.upsert_session(KEY, {"sessionId": SESSION, "updatedAt": NOW})
    _append(catalog, "Initial process-memory source.", "initial")
    config = MemoryConfig(workspace, store_path=tmp_path / "index.sqlite",
                          flags=FeatureFlags(vector_search=False, temporal_decay=False))
    owner = ManagedHostSession.open(workspace, catalog=catalog, config=config)
    owner.store.reindex(owner.kit.memory.workspace)
    _append(catalog, "Second process-memory source.", "second")
    before = owner.store.read_published_index()
    entered, release, _observed = _gate(owner.store, monkeypatch, source="sessions")
    with ThreadPoolExecutor(max_workers=1) as executor:
        try:
            future = executor.submit(owner.store.reindex_sources, owner.kit.memory.workspace, sources={"sessions"})
            assert entered.wait(5)
            assert _append(peer, "Actual later process-memory source.", "third")["appended"]
            release.set()
            with pytest.raises(MemoryIndexSourceChangedError, match="source changed"):
                future.result(timeout=5)
            assert owner.store.read_published_index() == before
            receipt = owner.store.lifecycle_snapshot()["operations"][-1]["catalogSourceReservation"]
            assert not receipt["acquired"] and receipt["reason"] == "process-memory-catalog"
        finally:
            release.set()
            owner.close()


def test_failed_actual_index_write_releases_catalog_reservation_without_retry(tmp_path):
    owner, catalog, _scheduler = _owner(tmp_path)
    _append(catalog, "Second source revision before failed publisher.", "second")
    journal = type(owner.store.path)(str(owner.store.path) + "-journal")
    journal.symlink_to(tmp_path / "missing-sidecar-directory" / "journal")
    try:
        with pytest.raises(sqlite3.OperationalError, match="unable to open"):
            owner.store.reindex_sources(owner.kit.memory.workspace, sources={"sessions"})
        operation = owner.store.lifecycle_snapshot()["operations"][-1]
        assert operation["state"] == "failed"
        receipt = operation["catalogSourceReservation"]
        assert receipt["acquired"] and receipt["released"] and receipt["catalogChanges"] == 0
        with closing(sqlite3.connect(catalog.path, timeout=0)) as peer:
            peer.execute("BEGIN IMMEDIATE")
            peer.rollback()
        assert len([row for row in owner.store.lifecycle_snapshot()["operations"]
                    if row["name"] == "reindex-sources"]) == 1
    finally:
        journal.unlink()
        owner.close()


def test_mixed_publication_can_create_its_real_provenance_table_in_the_catalog(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW)
    catalog.upsert_session(KEY, {"sessionId": SESSION, "updatedAt": NOW})
    _append(catalog, "Initial actually published session.", "initial")
    ledger = MemoryArtifactProvenanceStore(catalog.path)
    config = MemoryConfig(workspace, store_path=tmp_path / "index.sqlite",
                          flags=FeatureFlags(vector_search=False, temporal_decay=False))
    owner = ManagedHostSession.open(workspace, catalog=catalog, config=config, artifact_provenance=ledger)
    owner.store.reindex(owner.kit.memory.workspace)
    try:
        with closing(sqlite3.connect(catalog.path)) as db:
            assert db.execute("SELECT 1 FROM sqlite_master WHERE name='memory_artifact_provenance'").fetchone() is None
        (workspace / "MEMORY.md").write_text("A real new memory source needs its lazy provenance reader.\n")
        assert owner.store.reindex_sources(owner.kit.memory.workspace, sources={"memory", "sessions"}) == 2
        with closing(sqlite3.connect(catalog.path)) as db:
            assert db.execute("SELECT 1 FROM sqlite_master WHERE name='memory_artifact_provenance'").fetchone() == (1,)
        operation = owner.store.lifecycle_snapshot()["operations"][-1]
        assert operation["state"] == "completed"
        assert operation["catalogSourceReservation"]["reason"] == "mixed-source-selection"
        assert not operation["catalogSourceReservation"]["acquired"]
    finally:
        owner.close()
