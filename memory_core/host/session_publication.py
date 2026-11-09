"""Explicit session publication over committed catalog and SQLite owners.

Construction is inert. The host starts this controller only after acquiring its
real search snapshot. Pending sessions never imply that the complete index is
ready. Full bootstrap/rebuild remains the caller's explicit responsibility.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import threading
from typing import Any, Protocol

from memory_core.index.sqlite_store import SQLiteMemoryStore, read_index_source
from memory_core.session_catalog import MemorySessionCatalog, SessionTranscriptChange, normalize_session_agent_id
from memory_core.tools.common import format_error_message
from memory_core.workspace import MemoryWorkspace


class ScheduledCall(Protocol):
    def cancel(self) -> None: ...


Scheduler = Callable[[float, Callable[[], None]], ScheduledCall]
SESSION_DEBOUNCE_SECONDS = 5.0


def _schedule(delay: float, callback: Callable[[], None]) -> ScheduledCall:
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    timer.start()
    return timer


class SessionPublicationController:
    """Own real session-source claims without weakening ``store.reindex``.

    Notifications are process-local append/replace commits. Startup and explicit
    reconciliation discover authoritative admitted sources, including deletions.
    Metadata/archive/tombstone changes currently require that reconciliation;
    unrelated processes are observed on a later discovery, not a cross-process
    event bus. Failed claims stay pending until an explicit flush or a newly
    admitted notification. Closing cancels a pending timer and joins admitted
    jobs; it does not publish the cancelled timer's targets early.
    """

    def __init__(self, store: SQLiteMemoryStore, workspace: MemoryWorkspace,
                 catalog: MemorySessionCatalog, *, scheduler: Scheduler | None = None) -> None:
        self._store, self._workspace, self._catalog = store, workspace, catalog
        self._root = workspace.root.resolve()
        self._index = store.path.resolve()
        self._catalog_path = catalog.path.resolve()
        self._agent = normalize_session_agent_id(catalog.agent_id)
        sources = workspace.index_sources
        self._index_sources = sources
        self._enabled = "sessions" in (sources if sources is not None else ("memory", "sessions"))
        self._scheduler = scheduler or _schedule
        self._condition = threading.Condition(threading.RLock())
        self._local = threading.local()
        self._started = self._startup_complete = self._closing = self._closed = False
        self._active = self._due = False
        self._worker_token: object | None = None
        self._generation = self._published_generation = 0
        self._pending: dict[str, dict[str, Any]] = {}
        self._reconcile_pending = False
        self._in_flight: dict[str, Any] | None = None
        self._timer: ScheduledCall | None = None
        self._timer_token = 0
        self._unsubscribe: Callable[[], None] | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._last_exception: BaseException | None = None
        self._last_error: dict[str, str] | None = None
        self._jobs: deque[dict[str, Any]] = deque(maxlen=256)
        self._job_count = 0
        self.assert_bound(store, workspace, catalog)

    @property
    def store(self) -> SQLiteMemoryStore:
        return self._store

    @property
    def workspace(self) -> MemoryWorkspace:
        return self._workspace

    @property
    def catalog(self) -> MemorySessionCatalog:
        return self._catalog

    def assert_bound(self, store: SQLiteMemoryStore | None = None,
                     workspace: MemoryWorkspace | None = None,
                     catalog: MemorySessionCatalog | None = None) -> None:
        if (store is not None and store is not self._store
                or workspace is not None and workspace is not self._workspace
                or catalog is not None and catalog is not self._catalog
                or self._workspace.root.resolve() != self._root
                or self._store.config.workspace_dir.resolve() != self._root
                or self._store.path.resolve() != self._index
                or self._store.config.resolved_store_path().resolve() != self._index
                or self._catalog.path.resolve() != self._catalog_path
                or self._workspace.session_catalog is not self._catalog
                or self._workspace.index_sources != self._index_sources
                or normalize_session_agent_id(self._workspace.agent_id) != self._agent
                or normalize_session_agent_id(self._store.config.agent_id) != self._agent
                or normalize_session_agent_id(self._catalog.agent_id) != self._agent):
            raise ValueError("Session publication requires its exact store, workspace and catalog owner")

    def owns_current_job(self) -> bool:
        """Whether this physical thread is executing this owner's admitted job."""
        return getattr(self._local, "owned", False)

    def _ensure_open(self) -> None:
        if self._closed or self._closing:
            raise RuntimeError("Session publication controller is closed")

    def _record_error_locked(self, error: BaseException) -> None:
        try:
            message = format_error_message(error)
        except BaseException:
            message = "Session publication diagnostic could not be formatted"
        self._last_exception = error
        self._last_error = {"type": type(error).__name__, "message": message}

    def start(self) -> None:
        """Subscribe, then admit one asynchronous authoritative startup scan."""
        with self._condition:
            self._ensure_open()
            self.assert_bound()
            if self._started:
                return
            self._started = True
            if not self._enabled:
                self._startup_complete = True
                return
            self._unsubscribe = self._catalog.subscribe_transcript_changes(self._on_change)
            self._submit_locked("startup", discover=True)

    def _on_change(self, change: SessionTranscriptChange) -> None:
        if (change.agent_id != self._agent or Path(change.store_path).resolve() != self._catalog_path):
            return
        with self._condition:
            if not self._started or self._closing or self._closed:
                return
            self.assert_bound()
            path = f"sessions/{change.agent_id}/{change.session_id}.jsonl"
            self._generation += 1
            observed = asdict(change)
            observed["store_path"] = str(change.store_path)
            observed["generation_claim"] = self._generation
            prior = self._pending.get(path)
            if prior is None or prior.get("catalog_revision", -1) <= change.catalog_revision:
                self._pending[path] = observed
            if self._timer is None:
                self._timer_token += 1
                token = self._timer_token
                try:
                    self._timer = self._scheduler(SESSION_DEBOUNCE_SECONDS, lambda: self._timer_fired(token))
                except BaseException as error:
                    self._record_error_locked(error)
                    raise

    def _cancel_timer_locked(self) -> None:
        self._timer_token += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _timer_fired(self, token: int) -> None:
        with self._condition:
            if token != self._timer_token or self._closing or self._closed:
                return
            self._timer = None
            try:
                self._submit_locked("session-delta")
            except BaseException:
                # Admission failure is already retained; a timer cannot turn
                # it into an unhandled thread exception or retry loop.
                return

    def _submit_locked(self, reason: str, *, discover: bool = False) -> None:
        if self._active:
            self._due = True
            return
        token = object()
        self._active, self._worker_token = True, token
        try:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="session-publication")
            self._executor.submit(self._work, reason, discover, token)
        except BaseException as error:
            self._active, self._worker_token = False, None
            self._reconcile_pending |= discover
            self._record_error_locked(error)
            self._condition.notify_all()
            raise

    def _discover(self) -> tuple[dict[str, dict[str, Any]], bool, dict[str, Any]]:
        self.assert_bound()
        before = self._catalog.snapshot().revision
        current = {}
        for file in self._workspace.discover_session_transcript_files():
            entry = read_index_source(file)
            if entry is not None:
                current[entry.path] = {"hash": entry.hash, "mtime": entry.mtime, "size": entry.size}
        published = {row["path"]: row for row in self._store.read_published_index()["sources"]
                     if row["source"] == "sessions"}
        dirty = {path: metadata for path, metadata in current.items()
                 if path not in published or not published[path]["hash"]
                 or any(published[path][key] != metadata[key] for key in ("hash", "mtime", "size"))}
        stale = sorted(published.keys() - current.keys())
        return dirty, bool(stale), {"catalogRevisionBefore": before,
            "catalogRevisionAfter": self._catalog.snapshot().revision,
            "observed": current, "stalePaths": stale}

    def _work(self, reason: str, discover: bool, token: object) -> None:
        self._local.owned = True
        try:
            while True:
                with self._condition:
                    self._job_count += 1
                    job: dict[str, Any] = {"id": self._job_count, "reason": reason, "state": "running"}
                    self._jobs.append(job)
                claim: dict[str, dict[str, Any]] = {}
                reconcile = False
                generation = 0
                try:
                    self.assert_bound()
                    if discover:
                        dirty, stale, observation = self._discover()
                        with self._condition:
                            job["discovery"] = observation
                            if dirty or stale:
                                self._generation += 1
                                for path, metadata in dirty.items():
                                    self._pending.setdefault(path, {**metadata, "generation_claim": self._generation})
                                self._reconcile_pending |= stale
                            self._startup_complete = True
                    with self._condition:
                        claim, self._pending = self._pending, {}
                        reconcile, self._reconcile_pending = self._reconcile_pending, False
                        generation = self._generation
                        self._in_flight = {"generation": generation, "paths": sorted(claim), "reconcile": reconcile}
                        job.update(self._in_flight)
                    if claim or reconcile:
                        before = self._store.read_published_index()["revision"]
                        returned = self._store.reindex_sources(self._workspace, sources={"sessions"},
                            paths=None if reconcile else frozenset(claim))
                        after = self._store.read_published_index()["revision"]
                        with self._condition:
                            job.update(returned=returned, revisionBefore=before, revisionAfter=after)
                    with self._condition:
                        self._published_generation = max(self._published_generation, generation)
                        self._last_exception = self._last_error = None
                        job["state"] = "completed"
                except BaseException as error:
                    with self._condition:
                        for path, metadata in claim.items():
                            self._pending.setdefault(path, metadata)
                        self._reconcile_pending |= reconcile or discover
                        self._record_error_locked(error)
                        job.update(state="failed", error=dict(self._last_error))
                with self._condition:
                    self._in_flight = None
                    if self._due and not self._closing and (self._pending or self._reconcile_pending):
                        self._due = False
                        reason, discover = "queued-session-delta", False
                        continue
                    self._due = False
                    self._active, self._worker_token = False, None
                    self._condition.notify_all()
                    return
        except BaseException as error:
            with self._condition:
                self._record_error_locked(error)
                self._reconcile_pending = True
        finally:
            self._local.owned = False
            with self._condition:
                if self._worker_token is token:
                    self._active, self._worker_token = False, None
                    self._in_flight = None
                    if self._due and not self._closing and (self._pending or self._reconcile_pending):
                        self._due = False
                        try:
                            self._submit_locked("queued-after-settlement")
                        except BaseException:
                            pass  # The actual admission failure remains retained.
                    self._condition.notify_all()

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Join already admitted jobs without firing or cancelling a timer."""
        if self.owns_current_job():
            raise RuntimeError("A publication job cannot wait for its own controller")
        with self._condition:
            return self._condition.wait_for(lambda: not self._active, timeout)

    def raise_if_failed(self) -> None:
        """Rethrow the original last publication failure without admitting work."""
        with self._condition:
            if self._last_exception is not None:
                raise self._last_exception

    def flush(self, *, reconcile: bool = False, timeout: float | None = None) -> dict[str, Any]:
        """Explicitly publish pending claims once; an explicit call may retry failure."""
        if self.owns_current_job():
            raise RuntimeError("A publication job cannot flush its own controller")
        self.start()
        with self._condition:
            self._ensure_open()
            if not self._enabled:
                return self.status()
            self._cancel_timer_locked()
            if reconcile:
                self._generation += 1
                self._reconcile_pending = True
            if self._pending or self._reconcile_pending:
                self._submit_locked("explicit-reconcile" if reconcile else "explicit-flush",
                                    discover=not self._startup_complete)
        if not self.wait_idle(timeout):
            raise TimeoutError("Session publication did not become idle")
        with self._condition:
            if self._last_exception is not None:
                raise self._last_exception
        return self.status()

    def reconcile(self, *, timeout: float | None = None) -> dict[str, Any]:
        return self.flush(reconcile=True, timeout=timeout)

    def status(self) -> dict[str, Any]:
        """Observe owner state; before start, session publication is unknown."""
        with self._condition:
            pending = None if not self._startup_complete else bool(
                self._pending or self._reconcile_pending or self._active)
            state = ("closed" if self._closed else "closing" if self._closing else
                     "not-started" if not self._started else "failed" if self._last_error else
                     "starting" if not self._startup_complete else "syncing" if self._active else
                     "pending" if pending else "idle")
            return deepcopy({"state": state, "notStarted": not self._started,
                "started": self._started, "startupComplete": self._startup_complete,
                "pending": pending, "generation": self._generation,
                "publishedGeneration": self._published_generation,
                "pendingPaths": sorted(self._pending), "reconcilePending": self._reconcile_pending,
                "timerPending": self._timer is not None, "activeJobs": int(self._active),
                "inFlight": self._in_flight, "lastError": self._last_error,
                "closing": self._closing, "closed": self._closed,
                "jobCount": self._job_count, "jobsTruncated": self._job_count > len(self._jobs),
                "jobs": list(self._jobs)})

    lifecycle_snapshot = status

    def close(self) -> None:
        """Cancel a future timer and join physical admitted work without flushing."""
        if self.owns_current_job():
            raise RuntimeError("A publication job cannot close its own controller")
        with self._condition:
            if self._closed:
                return
            self._closing = True
            self._cancel_timer_locked()
            unsubscribe, self._unsubscribe = self._unsubscribe, None
        if unsubscribe is not None:
            unsubscribe()
        self.wait_idle()
        if self._executor is not None:
            self._executor.shutdown(wait=True)
        with self._condition:
            self._closed = True
            self._closing = False
            self._condition.notify_all()
