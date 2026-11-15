"""SQLite producer admission matching Native's maintenance sidecar lease.

The sidecar contains no application tables. An exclusive locking-mode
connection retains the writer lease after its schema-free header transaction
commits, and the operating system releases it when a process exits.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Iterator

from memory_core.workspace import workspace_index_lock


_RETRY_SECONDS = 0.025


def _is_busy(error: BaseException) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    return (isinstance(code, int) and code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
            or "database is locked" in str(error).lower())


@dataclass
class _ReindexLease:
    """One process/path's actual connection; callers serialize each SQL step.

    A COMMIT blocked by a shared reader must retain its PENDING connection.
    Another waiting thread may continue that same admission under ``guard``;
    no thread owns a producer until the real COMMIT succeeds. This also lets a
    curator already holding the workspace guard execute a reserved generation.
    """

    path: Path
    guard: threading.RLock = field(default_factory=threading.RLock)
    database: sqlite3.Connection | None = None
    owner_thread: int | None = None
    depth: int = 0
    waiters: int = 0

    def _close(self) -> None:
        database, self.database = self.database, None
        self.owner_thread, self.depth = None, 0
        if database is not None:
            database.close()

    def _open_database(self) -> None:
        database = sqlite3.connect(self.path, timeout=0, isolation_level=None, check_same_thread=False)
        self.database = database
        database.execute("PRAGMA busy_timeout = 0")
        database.execute("PRAGMA locking_mode = EXCLUSIVE")
        database.execute("BEGIN IMMEDIATE")
        database.execute("PRAGMA user_version = 0")

    def try_acquire(self) -> bool:
        """Attempt admission without retaining a workspace guard during waits."""
        with self.guard:
            current = threading.get_ident()
            if self.owner_thread is not None:
                if self.owner_thread != current:
                    return False
                self.depth += 1
                return True
            if self.database is None:
                try:
                    self._open_database()
                except BaseException as error:
                    self._close()
                    if _is_busy(error):
                        return False
                    raise
            try:
                self.database.execute("COMMIT")
            except BaseException as error:
                if _is_busy(error):
                    # Keep the real connection and its PENDING intent, rather
                    # than reopening and allowing a later reader to overtake.
                    return False
                self._close()
                raise
            self.owner_thread, self.depth = current, 1
            return True

    def release(self) -> None:
        with self.guard:
            if self.owner_thread != threading.get_ident():
                raise RuntimeError("A memory reindex lease must be released by its producer thread")
            self.depth -= 1
            if not self.depth:
                self._close()

    @contextmanager
    def waiting(self) -> Iterator[None]:
        with self.guard:
            self.waiters += 1
        try:
            yield
        finally:
            with self.guard:
                self.waiters -= 1
                if not self.waiters and self.owner_thread is None:
                    self._close()


_LEASES_GUARD = threading.Lock()
_LEASES: dict[tuple[int, str], _ReindexLease] = {}


def _lease_for(index_path: Path) -> _ReindexLease:
    canonical = index_path.resolve()
    key = (os.getpid(), str(canonical))
    with _LEASES_GUARD:
        return _LEASES.setdefault(key, _ReindexLease(Path(f"{canonical}.reindex-lock.sqlite")))


@contextmanager
def memory_index_producer_guard(workspace_root: Path, index_path: Path, *, enabled: bool) -> Iterator[None]:
    """Own the workspace guard and actual cross-process producer lease.

    Each nonblocking SQLite attempt follows workspace → producer → publication
    lock order. A queued background worker releases the workspace guard between
    attempts so foreground readers can keep their existing index generation.
    There is no admitted-producer timeout or PID/age-based lock-file recovery.
    Disabled policies retain their ordinary process-local workspace guard.
    """
    workspace_guard = workspace_index_lock(workspace_root)
    if not enabled:
        with workspace_guard:
            yield
        return
    lease = _lease_for(index_path)
    with lease.waiting():
        while True:
            with workspace_guard:
                if lease.try_acquire():
                    try:
                        yield
                    finally:
                        lease.release()
                    return
            time.sleep(_RETRY_SECONDS)
