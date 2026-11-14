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
