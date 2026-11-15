"""Real SQLite and process ownership for the on-search producer lease."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import multiprocessing
from pathlib import Path
import signal
import sqlite3
import threading

import pytest

from memory_core.host.reindex_lease import _ReindexLease, memory_index_producer_guard
from memory_core.workspace import workspace_index_lock


def _hold_lease(root, index, ready, release):
    with memory_index_producer_guard(Path(root), Path(index), enabled=True):
        ready.set()
        if not release.wait(15):
            raise RuntimeError("Test owner did not receive its release")


def _held_process(tmp_path):
    context = multiprocessing.get_context("spawn")
    root, index = tmp_path / "workspace", tmp_path / "index.sqlite"
    root.mkdir()
    ready, release = context.Event(), context.Event()
    process = context.Process(target=_hold_lease, args=(str(root), str(index), ready, release))
    process.start()
    if not ready.wait(5):
        process.kill()
        process.join(5)
        pytest.fail("Real child producer never acquired its lease")
    return process, release, root, index


def _finish(process, release):
    # A terminated multiprocessing waiter cannot acknowledge Event.notify_all.
    # Only notify a live child; a reaped SIGKILL owner has already released SQL.
    if process.is_alive():
        release.set()
    process.join(5)
    if process.is_alive():
        process.kill()
        process.join(5)
        pytest.fail("Real producer did not close its lease")


def test_native_pending_commit_retains_connection_and_excludes_new_readers(tmp_path):
    path = tmp_path / "index.sqlite.reindex-lock.sqlite"
    with closing(sqlite3.connect(path, isolation_level=None)) as seed:
        seed.execute("PRAGMA user_version=0")
    reader = sqlite3.connect(path, isolation_level=None, timeout=0)
    lease = _ReindexLease(path)
    try:
        reader.execute("BEGIN")
        reader.execute("PRAGMA user_version").fetchone()
        assert lease.try_acquire() is False
        pending = lease.database
        assert pending is not None and pending.in_transaction
        with closing(sqlite3.connect(path, isolation_level=None, timeout=0)) as late:
            with pytest.raises(sqlite3.OperationalError) as error:
                late.execute("PRAGMA user_version").fetchone()
            assert error.value.sqlite_errorcode & 0xFF == sqlite3.SQLITE_BUSY
        reader.rollback()
        assert lease.try_acquire() is True
        assert lease.database is pending
        lease.release()
        with closing(sqlite3.connect(path, isolation_level=None, timeout=0)) as reopened:
            assert reopened.execute("PRAGMA user_version").fetchone() == (0,)
            assert reopened.execute("SELECT name FROM sqlite_schema").fetchall() == []
    finally:
        reader.close()
        lease._close()


def test_killed_owner_releases_real_os_lease_without_pid_age_recovery(tmp_path):
    process, release, root, index = _held_process(tmp_path)
    try:
        with closing(sqlite3.connect(f"{index}.reindex-lock.sqlite", timeout=0)) as reader:
            with pytest.raises(sqlite3.OperationalError):
                reader.execute("PRAGMA user_version").fetchone()
        process.kill()
        process.join(5)
        assert process.exitcode == -signal.SIGKILL
        with memory_index_producer_guard(root, index, enabled=True):
            with closing(sqlite3.connect(index)) as db:
                db.execute("CREATE TABLE actual_publication(value TEXT)")
        with closing(sqlite3.connect(index)) as db:
            assert db.execute("SELECT name FROM sqlite_schema WHERE name='actual_publication'").fetchone()
    finally:
        _finish(process, release)


def test_queued_producer_releases_workspace_guard_for_foreground_read(tmp_path, monkeypatch):
    process, release, root, index = _held_process(tmp_path)
    with closing(sqlite3.connect(index)) as db:
        db.execute("CREATE TABLE retained(value TEXT)")
        db.execute("INSERT INTO retained VALUES('old retained generation')")
        db.commit()
    busy, admitted = threading.Event(), threading.Event()
    original = _ReindexLease.try_acquire

    def observe_attempt(self):
        acquired = original(self)
        if not acquired:
            busy.set()
        return acquired

    monkeypatch.setattr(_ReindexLease, "try_acquire", observe_attempt)

    def publish():
        with memory_index_producer_guard(root, index, enabled=True):
            admitted.set()

    def foreground():
        with workspace_index_lock(root), closing(sqlite3.connect(index)) as db:
            return db.execute("SELECT value FROM retained").fetchall()

    with ThreadPoolExecutor(max_workers=2) as executor:
        producer = executor.submit(publish)
        try:
            assert busy.wait(5), "The queued producer never attempted the real external lease"
            assert not admitted.is_set()
            assert executor.submit(foreground).result(timeout=2) == [("old retained generation",)]
            assert not admitted.is_set(), "A foreground read must not release the other process's lease"
        finally:
            _finish(process, release)
        producer.result(timeout=5)
        assert admitted.is_set()


def test_actual_same_thread_producer_reentry_retains_lease_until_outer_close(tmp_path):
    root, index = tmp_path, tmp_path / "index.sqlite"
    with memory_index_producer_guard(root, index, enabled=True):
        with memory_index_producer_guard(root, index, enabled=True):
            pass
        with closing(sqlite3.connect(f"{index}.reindex-lock.sqlite", timeout=0)) as reader:
            with pytest.raises(sqlite3.OperationalError):
                reader.execute("PRAGMA user_version").fetchone()
    with closing(sqlite3.connect(f"{index}.reindex-lock.sqlite", timeout=0)) as reader:
        assert reader.execute("PRAGMA user_version").fetchone() == (0,)


def test_disabled_profile_uses_workspace_guard_without_creating_lease(tmp_path):
    index = tmp_path / "index.sqlite"
    with memory_index_producer_guard(tmp_path, index, enabled=False):
        with closing(sqlite3.connect(index)) as db:
            db.execute("CREATE TABLE ordinary_on_write(value TEXT)")
    assert not Path(f"{index}.reindex-lock.sqlite").exists()


def _managed_lease_owner(root, index, origins, catalog_path):
    from memory_core.config import MemoryConfig
    from memory_core.consolidation.origins import MemoryEntryOriginLedger
    from memory_core.flags import FeatureFlags
    from memory_core.host.managed_index import ManagedSQLiteMemoryStore
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.workspace import MemoryWorkspace

    ledger = MemoryEntryOriginLedger(lambda _agent: Path(origins))
    catalog = MemorySessionCatalog(Path(catalog_path))
    workspace = MemoryWorkspace(Path(root), agent_id="main", session_catalog=catalog,
        is_session_forgotten=lambda session: bool(ledger.list_session_tombstones("main", [session])),
        index_sources=["memory", "sessions"])
    config = MemoryConfig(Path(root), store_path=Path(index),
                          flags=FeatureFlags(vector_search=False, temporal_decay=False))
    store = ManagedSQLiteMemoryStore(config, workspace, memory_publication="on-search",
                                    revision_fence=ledger.revision_fence("main"))
    return store, workspace, ledger, catalog


def _managed_producer_process(root, index, origins, catalog, connection, *, hold_prepared):
    from memory_core.consolidation.origins import MemoryIndexRevisionConflictError

    store = None
    send_guard = threading.Lock()
    attempted = threading.Event()
    original_try_acquire = _ReindexLease.try_acquire

    def send(phase, **values):
        with send_guard:
            connection.send({"phase": phase, **values})

    def actual_lease_attempt(lease):
        acquired = original_try_acquire(lease)
        if not acquired and not attempted.is_set():
            attempted.set()
            send("lease-wait", acquired=acquired)
        elif acquired:
            send("lease-acquired", acquired=acquired)
        return acquired

    _ReindexLease.try_acquire = actual_lease_attempt
    try:
        store, workspace, _ledger, _catalog = _managed_lease_owner(root, index, origins, catalog)
        if hold_prepared:
            original_publish = store.publish_prepared_index

            def pause_real_prepared_frame(prepared, expected_revision, **options):
                send("prepared", revision=expected_revision,
                     sources=[{"path": source.path, "source": source.source,
                               "texts": [chunk.text for chunk in source.chunks]}
                              for source in prepared.sources])
                if not connection.poll(15) or connection.recv() != "release":
                    raise RuntimeError("The actual prepared producer was not released")
                return original_publish(prepared, expected_revision, **options)

            store.publish_prepared_index = pause_real_prepared_frame
        with ThreadPoolExecutor(max_workers=2) as executor:
            producer = executor.submit(store.reindex, workspace, force=True)
            if not hold_prepared:
                if not attempted.wait(5):
                    raise RuntimeError("The second managed producer did not reach the real held lease")
                hits = executor.submit(store.search, "keeppine853", min_score=0).result(timeout=2)
                send("foreground-query", hits=[{"path": hit.path, "snippet": hit.snippet} for hit in hits])
            try:
                result = producer.result(timeout=15)
            except BaseException as error:
                send("settled", error={"name": type(error).__name__, "message": str(error),
                                       "typedConflict": isinstance(error, MemoryIndexRevisionConflictError)})
            else:
                send("settled", returned=result, published=store.read_published_index(),
                     admitted=[file.rel_path for file in workspace.discover_session_transcript_files()])
    except BaseException as error:
        send("child-error", error={"name": type(error).__name__, "message": str(error)})
        raise
    finally:
        _ReindexLease.try_acquire = original_try_acquire
        if store is not None:
            store.close()
        connection.close()


def _receive_phase(connection, phase, receipts):
    import time

    deadline = time.monotonic() + 5
    while True:
        remaining = deadline - time.monotonic()
        assert remaining > 0 and connection.poll(remaining), f"No actual {phase} receipt arrived"
        row = connection.recv()
        receipts.append(row)
        assert row["phase"] != "child-error", row
        if row["phase"] == phase:
            return row


def _finish_managed_process(process, connection, *, release=False):
    if process.is_alive() and release:
        try:
            connection.send("release")
        except (BrokenPipeError, EOFError, OSError):
            pass
    process.join(5)
    if process.is_alive():
        process.kill()
        process.join(5)
    connection.close()
    assert not process.is_alive(), "The managed producer could not be reaped"


@pytest.mark.parametrize("split_origins", [False, True])
def test_real_managed_processes_preserve_forget_and_queued_foreground_query(tmp_path, split_origins):
    from memory_core.consolidation.forget import forget_memory_entries
    from memory_core.consolidation.origins import MemoryEntryOrigin
    from memory_core.index.sqlite_store import SQLiteMemoryStore

    root, index, catalog_path = tmp_path / "workspace", tmp_path / "index.sqlite", tmp_path / "catalog.sqlite"
    origins = tmp_path / "origins.sqlite" if split_origins else index
    (root / "memory").mkdir(parents=True)
    (root / "MEMORY.md").write_text(
        "# Memory\n\n<!-- memory-core-memory-promotion:chosen -->\n"
        "- A durable forgetmaple742 preference.\n", encoding="utf8",
    )
    (root / "memory/retained.md").write_text("A durable keeppine853 preference.\n", encoding="utf8")
    seed, workspace, ledger, catalog = _managed_lease_owner(root, index, origins, catalog_path)
    ledger.record("main", [MemoryEntryOrigin("chosen", "main", "forgotten",
                  "agent:main:dm:forgotten", "owner", 123)])
    for session, text in (("forgotten", "A durable forgetmaple742 preference."),
                          ("retained", "A durable keeppine853 preference.")):
        key = f"agent:main:dm:{session}"
        catalog.upsert_session(key, {"sessionId": session})
        catalog.append_message(session, {"role": "user", "content": text}, session_key=key,
                               event_id=f"{session}-message", now_ms=123)
    try:
        assert seed.reindex(workspace, force=True) == 4
        before = seed.read_published_index()
        config = seed.config
        with closing(seed.connect()) as db:
            assert db.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    finally:
        seed.close()
    context = multiprocessing.get_context("spawn")
    old_connection, old_child = context.Pipe()
    old = context.Process(target=_managed_producer_process,
        args=(root, index, origins, catalog_path, old_child), kwargs={"hold_prepared": True})
    fresh_connection, fresh_child = context.Pipe()
    fresh = context.Process(target=_managed_producer_process,
        args=(root, index, origins, catalog_path, fresh_child), kwargs={"hold_prepared": False})
    old_receipts, fresh_receipts = [], []
    started_fresh = released_old = False
    old.start()
    old_child.close()
    try:
        prepared = _receive_phase(old_connection, "prepared", old_receipts)
        assert any("forgetmaple742" in text for source in prepared["sources"] for text in source["texts"])
        with closing(sqlite3.connect(f"{index}.reindex-lock.sqlite", timeout=0)) as reader:
            with pytest.raises(sqlite3.OperationalError):
                reader.execute("PRAGMA user_version").fetchone()
        fresh.start()
        started_fresh = True
        fresh_child.close()
        assert _receive_phase(fresh_connection, "lease-wait", fresh_receipts)["acquired"] is False
        foreground = _receive_phase(fresh_connection, "foreground-query", fresh_receipts)
        assert foreground["hits"] and all("keeppine853" in hit["snippet"] for hit in foreground["hits"])
        assert not any(row["phase"] == "lease-acquired" for row in fresh_receipts)
        # Forget owns its actual marker and purge transactions independently of
        # the maintenance sidecar held by the already prepared old producer.
        forget_store = SQLiteMemoryStore(config, None, revision_fence=ledger.revision_fence("main"))
        with ThreadPoolExecutor(max_workers=1) as executor:
            forgotten = executor.submit(forget_memory_entries, config=config, agent_id="main",
                                        origins=ledger, session_ids=["forgotten"], store=forget_store)
            try:
                report = forgotten.result(timeout=3)
                assert report.session_ids == ["forgotten"] and report.artifacts["indexChunks"] > 0
                assert [row.session_id for row in ledger.list_session_tombstones("main")] == ["forgotten"]
                assert forget_store.count_chunks() < len(before["chunks"])
                assert "forgetmaple742" not in (root / "MEMORY.md").read_text(encoding="utf8")
            finally:
                old_connection.send("release")
                released_old = True
        rejected = _receive_phase(old_connection, "settled", old_receipts)
        assert rejected["error"]["typedConflict"] is True
        assert _receive_phase(fresh_connection, "lease-acquired", fresh_receipts)["acquired"] is True
        published = _receive_phase(fresh_connection, "settled", fresh_receipts)
        assert "error" not in published
        assert "sessions/main/forgotten.jsonl" not in published["admitted"]
        assert "sessions/main/retained.jsonl" in published["admitted"]
        texts = [chunk["text"] for chunk in published["published"]["chunks"]]
        assert texts and all("forgetmaple742" not in text for text in texts)
        assert any("keeppine853" in text for text in texts)
        assert catalog.snapshot().forgotten_session_ids == frozenset()
    finally:
        _finish_managed_process(old, old_connection, release=not released_old)
        if started_fresh:
            _finish_managed_process(fresh, fresh_connection)
        else:
            fresh_connection.close()
            fresh_child.close()
    assert old.exitcode == fresh.exitcode == 0
