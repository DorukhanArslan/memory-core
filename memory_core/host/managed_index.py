"""An explicit provider-none index owner with real search-time bootstrap.

Ordinary ``HostKit.open`` remains eager. Hosts selecting this owner construct a
``Memory``/``HostKit`` around it without an initial reindex. Repairs use the
normal checked SQLite publisher; status and notices describe those real calls.
An optional explicitly bound session controller starts after a real search read
generation is acquired. The explicit ``on-search`` memory policy also watches
committed memory sources and admits a scoped publisher at that boundary,
retaining the query's original read snapshot. Ordinary on-write construction
starts no background work.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Collection, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack, closing, contextmanager, nullcontext
from copy import deepcopy
import threading
import sqlite3
import time
from typing import TYPE_CHECKING, Any, Literal

from memory_core.bootstrap._js import js_trim
from memory_core.cancellation import CancellationSignal
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.consolidation.origins import IndexRevisionFence, MemoryIndexRevisionConflictError
from memory_core.index.sqlite_store import MemoryIndexRequiresFullReindexError, SQLiteMemoryStore
from memory_core.index.identity import INDEX_SOURCES_TABLE, INDEX_SYNC_TABLE
from memory_core.index.hybrid import HybridResult
from memory_core.host.reindex_lease import memory_index_producer_guard
from memory_core.host.memory_watcher import MemoryFileWatcher
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.session_catalog import normalize_session_agent_id
from memory_core.tools.common import format_error_message
from memory_core.tools.deadline import MemorySearchDeadlineControl
from memory_core.workspace import MemoryWorkspace, workspace_index_lock

if TYPE_CHECKING:
    from memory_core.host.session_publication import SessionPublicationController


class _ManagedSearchResults(list[HybridResult]):
    """Keep this reader's status with its results, independently of later publishers."""

    def __init__(self, results: list[HybridResult], status: dict[str, Any]) -> None:
        super().__init__(results)
        self._memory_search_status = status


class ManagedSQLiteMemoryStore(SQLiteMemoryStore):
    """A bound FTS-only store whose first search can bootstrap its real index.

    ``status`` retains one live notice object so the ordinary memory tool can
    observe a repair requested during that call. A prior notice is not replayed.
    ``close`` refuses new managed search/reindex/status operations and joins
    those already admitted, including a publication whose caller stopped waiting.
    Inherited raw SQL inspection APIs remain outside this managed admission lane.
    On-search full publications share one admitted producer among overlapping
    requests. An empty search joins that producer or attempts its own bootstrap.
    A failed admitted rebuild retains bounded automatic full-retry work; an
    unopened storage refusal permits ordinary dirty-source recovery. The default
    on-write policy retains explicit recovery. Identity restrictions remain in force.
    A failed memory-scope ``reindex_sources`` publication is retained separately:
    ``status`` reports it (when no whole publication failure is retained) until
    the failed selection publishes or a whole ``reindex`` succeeds. It does not
    gate automatic preparation.
    """

    def __init__(self, config: MemoryConfig, workspace: MemoryWorkspace, *,
                 artifact_provenance: MemoryArtifactProvenanceStore | None = None,
                 revision_fence: IndexRevisionFence | None = None,
                 runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
                 memory_publication: Literal["on-write", "on-search"] = "on-write") -> None:
        if not isinstance(memory_publication, str) or memory_publication not in {"on-write", "on-search"}:
            raise ValueError("memory_publication must be on-write or on-search")
        if not isinstance(workspace, MemoryWorkspace):
            raise TypeError("A managed memory index requires its actual MemoryWorkspace")
        if (config.workspace_dir.resolve() != workspace.root.resolve()
                or normalize_session_agent_id(config.agent_id) != normalize_session_agent_id(workspace.agent_id)
                or workspace.session_catalog is not None
                and workspace.session_catalog.agent_id != normalize_session_agent_id(config.agent_id)):
            raise ValueError("The managed index configuration and workspace must have the same owner")
        if config.effective_flags().vector_search:
            raise ValueError("ManagedSQLiteMemoryStore currently supports provider-none indexes only")
        self._workspace = workspace
        self._bound_workspace = workspace.root.resolve()
        self._bound_index = config.resolved_store_path().resolve()
        self._bound_agent = normalize_session_agent_id(config.agent_id)
        self._bound_catalog = workspace.session_catalog
        self._runtime_identity = runtime_identity
        self._memory_publication = memory_publication
        self._condition = threading.Condition(threading.RLock())
        self._local = threading.local()
        self._provider_initialized = False
        self._active_operations = 0
        self._closing = False
        self._closed = False
        self._last_sync_error: str | None = None
        self._whole_failure_revision = 0
        self._full_retry_required = False
        self._whole_failure_sources: frozenset[str] = frozenset()
        self._full_sync: dict[str, Any] | None = None
        self._full_sync_count = 0
        # (error message, failed memory paths); ``None`` paths mean the whole memory corpus.
        self._memory_scope_failure: tuple[str, frozenset[str] | None] | None = None
        self._automatic_rebuild_notice: dict[str, Any] = {"sequence": 0, "warning": ""}
        self._operations: deque[dict[str, Any]] = deque(maxlen=512)
        self._repairs: deque[dict[str, Any]] = deque(maxlen=256)
        self._operation_count = 0
        self._repair_count = 0
        self._session_publication: SessionPublicationController | None = None
        self._read_admissions: deque[dict[str, Any]] = deque(maxlen=256)
        self._read_admission_count = 0
        self._memory_dirty = False
        self._memory_active = False
        self._memory_worker_token: object | None = None
        self._memory_executor: ThreadPoolExecutor | None = None
        self._memory_job_error: str | None = None
        self._memory_jobs: deque[dict[str, Any]] = deque(maxlen=256)
        self._memory_job_count = 0
        self._memory_job_futures: dict[int, Future] = {}
        self._memory_watcher: MemoryFileWatcher | None = None
        self._memory_watch_generation = 0
        self._memory_watch_ready_generation = 0
        self._memory_watch_published_generation = 0
        self._memory_watch_error: str | None = None
        self._memory_watch_facts: deque[dict[str, int]] = deque(maxlen=4096)
        self._memory_watch_settlements: deque[dict[str, Any]] = deque(maxlen=256)
        super().__init__(config, None, revision_fence=revision_fence, artifact_provenance=artifact_provenance)
        if memory_publication == "on-search" and workspace.is_session_forgotten is None:
            # The opted-in managed producer owns this index database. Read its
            # existing agent tombstones without copying them into the catalog;
            # an explicit host predicate remains authoritative.
            workspace.is_session_forgotten = self.is_session_forgotten
        if (memory_publication == "on-search"
                and "memory" in (workspace.index_sources or ("memory", "sessions"))):
            self._memory_watcher = MemoryFileWatcher(workspace.root,
                on_dirty=self._memory_watch_dirty, on_change=self._memory_watch_changed,
                on_unavailable=self._memory_watch_unavailable)
            try:
                self._memory_watcher.start()
            except Exception as error:
                self._memory_watcher.close()
                self._memory_watch_unavailable(error)

    @contextmanager
    def _operation(self, name: str) -> Iterator[dict[str, Any]]:
        with self._condition:
            depth = getattr(self._local, "depth", 0)
            draining_publication = (name == "reindex-sources" and self._session_publication is not None
                                    and self._session_publication.owns_current_job())
            draining_memory = getattr(self._local, "memory_publisher", False)
            if self._closed or self._closing and not depth and not draining_publication and not draining_memory:
                raise RuntimeError("Memory index manager is closed")
            self._active_operations += 1
            self._local.depth = depth + 1
            parents = getattr(self._local, "operations", ())
            self._operation_count += 1
            operation = {"id": self._operation_count, "name": name, "state": "running",
                         "parentOperationId": parents[-1] if parents else None,
                         "threadId": threading.get_ident()}
            self._operations.append(operation)
            self._local.operations = (*parents, operation["id"])
        try:
            yield operation
        except BaseException as error:
            self._update(operation, state="failed", error=self._error(error))
            raise
        else:
            self._update(operation, state="completed")
        finally:
            with self._condition:
                self._local.depth -= 1
                self._local.operations = self._local.operations[:-1]
                self._active_operations -= 1
                self._condition.notify_all()

    def _assert_workspace(self, workspace: MemoryWorkspace) -> None:
        if (workspace is not self._workspace or workspace.root.resolve() != self._bound_workspace
                or self.config.workspace_dir.resolve() != self._bound_workspace
                or self.path.resolve() != self._bound_index or self.config.resolved_store_path().resolve() != self._bound_index
                or normalize_session_agent_id(self.config.agent_id) != self._bound_agent
                or normalize_session_agent_id(workspace.agent_id) != self._bound_agent
                or workspace.session_catalog is not self._bound_catalog):
            raise ValueError("The managed index may only publish its bound workspace")

    @property
    def bound_workspace(self) -> MemoryWorkspace:
        """Return the actual publication owner, including its catalog and scope."""
        self._assert_workspace(self._workspace)
        return self._workspace

    @property
    def memory_watcher(self) -> MemoryFileWatcher | None:
        """Return this owner's actual detector; reading never creates one."""
        self._assert_workspace(self._workspace)
        return self._memory_watcher

    @staticmethod
    def _error(error: BaseException) -> dict[str, Any]:
        return {"name": getattr(error, "name", type(error).__name__), "message": format_error_message(error)}

    def _update(self, record: dict[str, Any], **values: Any) -> None:
        with self._condition:
            record.update(values)

    def _read_state(self, *, db: sqlite3.Connection | None = None,
                    provider_key_known: bool | None = None) -> dict[str, Any]:
        if db is None:
            with closing(self.connect()) as connection:
                connection.execute("BEGIN")
                return self._read_state(db=connection, provider_key_known=provider_key_known)
        if provider_key_known is None:
            with self._condition:
                provider_key_known = self._provider_initialized
        identity = self._resolve_index_identity(db=db, provider_key_known=provider_key_known)
        fts_available = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_fts'").fetchone() is not None
        chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        fts_content = fts_available and db.execute("SELECT 1 FROM chunks_fts LIMIT 1").fetchone() is not None
        counts = {source: count for source, count in db.execute("SELECT source,COUNT(*) FROM chunks GROUP BY source")}
        needs_rebuild = bool(db.execute(
            f"SELECT needs_rebuild FROM {INDEX_SYNC_TABLE} WHERE id=1").fetchone()[0])
        sources = self._workspace.index_sources or ("memory", "sessions")
        return {"identity": identity, "hasContent": bool(chunks or fts_content), "chunks": chunks,
                "ftsAvailable": fts_available, "needsRebuild": needs_rebuild,
                "sourceCounts": [{"source": source, "chunks": counts.get(source, 0)} for source in sources]}

    def _retained_sync_error(self) -> str | None:
        with self._condition:
            if self._last_sync_error is not None:
                return self._last_sync_error
            if self._memory_scope_failure is not None:
                return self._memory_scope_failure[0]
            return self._memory_job_error if self._memory_publication == "on-search" else None

    def _refresh_memory_dirty(self, *, acknowledge_watch: bool = False, db: sqlite3.Connection | None = None) -> None:
        """Compare actual memory sources with SQL; caller holds the workspace guard."""
        if self._memory_publication != "on-search":
            return
        with self._condition:
            observed_watch_generation = self._memory_watch_generation
        selection = self._validated_source_selection(self._workspace, ("memory",), None, False)
        sources = self._read_source_snapshots(self._workspace, selection=selection)
        current = {path: (entry.hash, entry.mtime, entry.size)
                   for (_, path), entry in sources.items()}
        with (nullcontext(db) if db is not None else closing(self.connect())) as connection:
            published = {path: (digest, mtime, size) for path, digest, mtime, size in connection.execute(
                f"SELECT path,hash,mtime,size FROM {INDEX_SOURCES_TABLE} WHERE source='memory'")}
        with self._condition:
            if acknowledge_watch and current == published:
                # Only a real successful publisher may acknowledge delivered
                # watch facts. Searches only observe the retained dirty state.
                self._memory_watch_published_generation = max(
                    self._memory_watch_published_generation, observed_watch_generation)
            self._memory_dirty = (current != published
                or self._memory_watch_generation > self._memory_watch_published_generation)

    def _memory_watch_dirty(self) -> None:
        """Accept a filesystem fact independently of any search request."""
        with self._condition:
            if self._closing or self._closed:
                return
            self._memory_watch_generation += 1
            detector_generation = (self._memory_watcher.delivery_generation
                                   if self._memory_watcher is not None else None)
            if detector_generation is not None:
                self._memory_watch_facts.append({"detectorGeneration": detector_generation,
                    "watchGeneration": self._memory_watch_generation})
            self._memory_dirty = True
            self._condition.notify_all()

    def _memory_watch_unavailable(self, error: Exception) -> None:
        with self._condition:
            if not self._closing and not self._closed:
                self._memory_dirty = True
                self._memory_watch_error = format_error_message(error)

    def _memory_watch_changed(self) -> None:
        """Queue only filesystem facts that passed the watcher's settling."""
        with self._condition:
            if self._closing or self._closed:
                return
            self._memory_watch_ready_generation = self._memory_watch_generation
            generation = self._memory_watch_ready_generation
            detector_generation = (self._memory_watcher.settling_generation
                                   if self._memory_watcher is not None else None)
            self._memory_dirty = True
            self._condition.notify_all()
        job_id = self._queue_memory_watch_publication()
        with self._condition:
            self._memory_watch_settlements.append({"detectorGeneration": detector_generation,
                "watchGeneration": generation, "jobId": job_id})
            self._condition.notify_all()

    def _queue_memory_watch_publication(self) -> int | None:
        # This callback never manufactures source snapshots or writes SQL.
        # The ordinary worker rechecks its source/index selection after actual
        # producer admission, under the same cross-process lease and fences.
        with self._operation("watch-memory"):
            self._assert_workspace(self._workspace)
            state = self._read_state(provider_key_known=True)
            revision = self.index_revision()
            with self._condition:
                if not self._closing and not self._closed:
                    self._memory_watch_error = None
                    previous_job = self._memory_jobs[-1] if self._memory_jobs else None
                    self._submit_memory_publication(revision,
                        needs_rebuild=state["needsRebuild"] or self._automatic_repair_allowed(state["identity"]),
                        reason="watch")
                    current_job = self._memory_jobs[-1] if self._memory_jobs else None
                    if current_job is not None and (self._memory_active or current_job is not previous_job):
                        return current_job["id"]
        return None

    def wait_for_memory_watches(self, versions: Sequence[dict[str, Any]], *,
                                timeout: float | None = None) -> dict[str, Any]:
        """Join delivered versions and their existing publisher, without new work.

        Targets come from ``memory_watcher.capture_versions`` at the caller's
        original write boundary. This method never recaptures paths, starts a
        detector, changes a timer, marks a source dirty, or requests a sync.
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        def remaining() -> float | None:
            return None if deadline is None else max(0.0, deadline - time.monotonic())

        with self._operation("wait-memory-watches"):
            self._assert_workspace(self._workspace)
            watcher = self._memory_watcher
            if watcher is None:
                raise RuntimeError("This managed index has no memory file watcher")
            if getattr(self._local, "memory_publisher", False) or watcher.owns_current_thread():
                raise RuntimeError("A memory watch callback or publisher cannot join its own work")
            delivery = watcher.wait_for_versions(versions, timeout=remaining())
            with self._condition:
                generations = {row["generation"] for row in delivery["deliveries"]}
                facts = [fact for fact in self._memory_watch_facts if fact["detectorGeneration"] in generations]
                if {fact["detectorGeneration"] for fact in facts} != generations:
                    raise RuntimeError("The delivered memory watch generation is no longer retained by its owner")
                target = max(fact["watchGeneration"] for fact in facts)
                while True:
                    completed = next((job for job in self._memory_jobs
                        if job.get("publishedWatchGeneration", -1) >= target and job["state"] == "completed"), None)
                    unsuccessful = next((job for job in reversed(self._memory_jobs)
                        if job["watchGeneration"] >= target and job["state"] in {"failed", "refused"}), None)
                    job = completed or (unsuccessful if not self._memory_active else None)
                    if job is not None:
                        future = self._memory_job_futures.get(job["id"])
                        if future is None:
                            raise RuntimeError("The memory watch publication has no retained submitted Future")
                        break
                    if self._closed or self._closing and not self._memory_active:
                        raise RuntimeError("The managed index closed before its delivered memory version published")
                    wait = remaining()
                    if wait is not None and wait <= 0:
                        raise TimeoutError("The delivered memory version has not completed its admitted publication")
                    self._condition.wait(wait)
            returned = future.result(timeout=remaining())
            with self._condition:
                return {"status": job["state"], "delivery": delivery, "watchGeneration": target,
                    "job": deepcopy(job), "futureObjectId": str(id(future)), "futureReturned": returned}

    def _defer_memory_publication(self, workspace: MemoryWorkspace, *,
                                  sources: Collection[str]) -> bool | None:
        """Select the opt-in policy, returning actual current/pending readiness.

        ``None`` leaves other policies and publication scopes unchanged. No
        publication is scheduled here; only a pinned search reader admits work.
        """
        if self._memory_publication != "on-search" or set(sources) != {"memory"}:
            return None
        with self._operation("defer-memory-publication"):
            self._assert_workspace(workspace)
            with workspace_index_lock(workspace.root):
                self._refresh_memory_dirty()
                identity = self.index_identity()
                with self._condition:
                    return (identity["status"] == "valid" and not self._memory_dirty
                            and self._last_sync_error is None and self._memory_scope_failure is None
                            and self._memory_job_error is None)

    def _submit_memory_publication(self, revision: int, *, needs_rebuild: bool = False,
                                   reason: str = "search") -> None:
        """Admit one actual memory publisher under the pinned reader's gate."""
        needed = (self._memory_dirty or self._memory_scope_failure is not None
                  or self._memory_job_error is not None or self._full_retry_required or needs_rebuild)
        if (self._memory_publication != "on-search" or not needed
                or self._memory_active or self._closing or self._closed):
            return
        if self._memory_executor is None:
            self._memory_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-publication")
        self._memory_job_count += 1
        job: dict[str, Any] = {"id": self._memory_job_count, "readRevision": revision, "state": "queued"}
        job["watchGeneration"] = self._memory_watch_ready_generation
        if reason == "watch":
            job["reason"] = reason
        if needs_rebuild:
            job["fullRebuild"] = True
        if self._last_sync_error is not None:
            job.update(wholeFailureRevision=self._whole_failure_revision,
                       fullRetry=self._full_retry_required)
        if self._full_retry_required:
            self._record_rebuild_request()
        self._memory_jobs.append(job)
        retained = {entry["id"] for entry in self._memory_jobs}
        self._memory_job_futures = {key: value for key, value in self._memory_job_futures.items() if key in retained}
        token = object()
        self._memory_worker_token = token
        self._memory_active = True
        try:
            self._memory_job_futures[job["id"]] = self._memory_executor.submit(self._run_memory_publication, job, token)
        except BaseException as error:
            self._memory_worker_token = None
            self._memory_active = False
            self._memory_job_error = format_error_message(error)
            job.update(state="failed", error=self._error(error))
            self._condition.notify_all()

    def _run_memory_publication(self, job: dict[str, Any], token: object) -> None:
        """Keep an admitted worker owned through its real publication and close."""
        with self._condition:
            if self._memory_worker_token is not token:
                return
            self._local.memory_publisher = True
            job.update(state="running", threadId=threading.get_ident())
        error, refused = None, None
        try:
            with self._operation("memory-background-publication"):
                with (self._index_producer_guard(self._workspace)
                      if job.get("reason") == "watch" else nullcontext()):
                    if job.get("reason") == "watch":
                        # A queued watcher must choose its route after the
                        # real lease admits it, including a marker committed
                        # while it waited behind an older producer.
                        state = self._read_state(provider_key_known=True)
                        with self._condition:
                            job["fullRetry"] = self._full_retry_required
                            job["wholeFailureRevision"] = self._whole_failure_revision
                        job["fullRebuild"] = (state["needsRebuild"]
                            or self._automatic_repair_allowed(state["identity"]))
                        job["admissionRevision"] = self.index_revision()
                    if job.get("fullRetry") or job.get("fullRebuild"):
                        # Each retry is a new real sync generation. Only the first
                        # typed CAS conflict permits one more attempt in this job.
                        for attempt in range(2):
                            try:
                                retry = bool(job.get("fullRetry"))
                                with self._automatic_reindex(full_retry=retry) as intent:
                                    returned = self.reindex(self._workspace, force=retry)
                                refused = intent.get("refused")
                                if refused is not None:
                                    with self._condition:
                                        job.update(automaticRefusal=refused, returned=returned)
                                    return
                                break
                            except MemoryIndexRevisionConflictError:
                                if attempt:
                                    raise
                    else:
                        # Settle source/error coverage under the publisher guard;
                        # historical worker completion cannot replay a covered error.
                        with self._index_producer_guard(self._workspace):
                            try:
                                returned = self.reindex_sources(self._workspace, sources=("memory",))
                            except BaseException as caught:
                                with self._condition:
                                    self._memory_job_error = format_error_message(caught)
                                raise
                            with self._condition:
                                if (job.get("wholeFailureRevision") == self._whole_failure_revision
                                        and not self._full_retry_required
                                        and self._whole_failure_sources <= {"memory"}):
                                    self._last_sync_error = None
                                    self._whole_failure_sources = frozenset()
                # A source event remains a manager-owned dirty fact until a
                # real publisher has covered its settled generation. A query's
                # opportunistic FS/SQL comparison cannot acknowledge it.
                with workspace_index_lock(self._workspace.root):
                    with self._condition:
                        self._memory_watch_published_generation = max(
                            self._memory_watch_published_generation, job["watchGeneration"])
                    self._refresh_memory_dirty(acknowledge_watch=True)
                    with self._condition:
                        job["publishedWatchGeneration"] = self._memory_watch_published_generation
                with self._condition:
                    job["returned"] = returned
        except BaseException as caught:
            error = caught
        finally:
            with self._condition:
                if error is None:
                    job["state"] = "refused" if refused is not None else "completed"
                else:
                    job.update(state="failed", error=self._error(error))
                self._memory_worker_token = None
                self._memory_active = False
                self._local.memory_publisher = False
                follow_up = (not self._closing and not self._closed
                    and self._memory_watch_ready_generation > job["watchGeneration"])
                self._condition.notify_all()
            if follow_up:
                try:
                    self._queue_memory_watch_publication()
                except Exception as follow_up_error:
                    self._memory_watch_unavailable(follow_up_error)

    def status(self) -> dict[str, Any]:
        """Read actual published SQL state and the live repair-request notice."""
        with self._operation("status"):
            self._assert_workspace(self._workspace)
            return self._status_from_state(self._read_state())

    def _status_from_state(self, state: dict[str, Any]) -> dict[str, Any]:
        result = {"backend": "builtin", "provider": "none", "requestedProvider": "none",
            "chunks": state["chunks"], "sourceCounts": state["sourceCounts"],
            "fts": {"enabled": self.flags.text_search, "available": state["ftsAvailable"]},
            "custom": {"indexIdentity": state["identity"],
                       "automaticRebuildNotice": self._automatic_rebuild_notice}}
        sync_error = self._retained_sync_error()
        if sync_error is not None:
            result["lastSyncError"] = sync_error
        if self._session_publication is not None:
            result["custom"]["sessionPublication"] = self._session_publication.status()
        return result

    def bind_session_publication(self, controller: SessionPublicationController) -> None:
        """Opt in to lazy session publication for this exact store and corpus.

        Binding is inert. The first valid nonempty search starts the controller
        only after SQLite has admitted its real read generation. This does not
        alter the eager publication barrier of ``HostSessionRunner``.
        """
        from memory_core.host.session_publication import SessionPublicationController

        if not isinstance(controller, SessionPublicationController):
            raise TypeError("A managed session publisher requires SessionPublicationController")
        if (controller.store is not self or controller.workspace is not self._workspace
                or controller.catalog is not self._bound_catalog):
            raise ValueError("The session controller must belong to this exact managed index and catalog")
        with self._condition:
            if self._closed or self._closing:
                raise RuntimeError("Memory index manager is closed")
            if self._active_operations:
                raise RuntimeError("Bind session publication before admitting managed operations")
            if self._session_publication is not None and self._session_publication is not controller:
                raise RuntimeError("This managed index already has a session publication owner")
            self._assert_workspace(self._workspace)
            self._session_publication = controller

    def _prepared_search_db(self) -> sqlite3.Connection | None:
        frames = getattr(self._local, "search_status_frames", ())
        return frames[-1]["db"] if frames else None

    def _on_search_snapshot(self, db: sqlite3.Connection) -> None:
        controller = self._session_publication
        if controller is None and self._memory_publication != "on-search":
            return
        # The caller has already read index identity in this transaction: BEGIN
        # alone would not pin SQLite's deferred read snapshot.
        revision = self.index_revision(db=db)
        frames = getattr(self._local, "search_status_frames", ())
        frame = frames[-1] if frames else None
        state = frame["state"] if frame is not None else (
            self._read_state(db=db) if self._memory_publication == "on-search" else None)
        with self._condition:
            self._read_admission_count += 1
            operations = getattr(self._local, "operations", ())
            self._read_admissions.append({"id": self._read_admission_count,
                "operationId": operations[-1] if operations else None,
                "revision": revision, "threadId": threading.get_ident()})
            # Closing and first acquisition share this admission gate. An
            # already admitted query can finish its reader without starting
            # new controller work after close has begun.
            if not self._closing and not self._closed:
                if controller is not None:
                    controller.start()
                self._submit_memory_publication(revision, needs_rebuild=bool(state and state["needsRebuild"]))

    @contextmanager
    def _automatic_reindex(self, *, full_retry: bool = False):
        previous = getattr(self._local, "automatic_reindex", None)
        intent = {"fullRetry": full_retry}
        self._local.automatic_reindex = intent
        try:
            yield intent
        finally:
            self._local.automatic_reindex = previous

    def _uses_row_mutation_revision(self) -> bool:
        return self._memory_publication == "on-search"

    def _allow_full_reindex(self, workspace: MemoryWorkspace, *, force: bool) -> bool:
        intent = getattr(self._local, "automatic_reindex", None)
        if intent is None:
            return True
        identity = self._read_state(provider_key_known=True)["identity"]
        allowed = identity["status"] == "valid" or self._automatic_repair_allowed(identity)
        if not allowed:
            intent["refused"] = deepcopy(identity)
        return allowed

    def _full_sync_result(self, generation, operation, intent, notice):
        """Deliver the reserved generation without inventing another producer."""
        if intent is not None and intent is not generation["intent"]:
            intent.update(joined=True)
            if generation.get("refused") is not None:
                intent["refused"] = generation["refused"]
        if notice is not None and notice is not generation["notice"]:
            notice.update(joined=True, unopened=generation.get("unopened", False))
        self._update(operation, producerOperationId=generation["operationId"],
                     reservationOperationId=generation["reservationOperationId"])
        if generation["error"] is not None:
            raise generation["error"]
        self._update(operation, returned=generation["result"])
        return generation["result"]

    @contextmanager
    def _index_producer_guard(self, workspace: MemoryWorkspace, *, generation=None):
        """Queue a genuine producer without blocking this owner's foreground reads."""
        try:
            with memory_index_producer_guard(workspace.root, self.path,
                    enabled=self._memory_publication == "on-search"):
                yield
        except BaseException as error:
            # Acquisition can fail before the generation begins (for example,
            # an inaccessible real lease database). Its joiners must still
            # receive the actual failure and permit a later independent call.
            if generation is not None and not generation["started"]:
                with self._condition:
                    generation.update(result=None, error=error, settled=True)
                    if self._full_sync is generation:
                        self._full_sync = None
                    self._condition.notify_all()
            raise

    def reindex(self, workspace: MemoryWorkspace, *, force: bool = False) -> int:
        """Reserve a generation; its first workspace holder executes it once.

        A real curated write can already own the reentrant workspace guard.
        Waiting on a condition there would prevent the reserved caller from
        ever acquiring that guard. Such a caller executes the unstarted work
        with the first request's force/authority instead.
        """
        with self._operation("reindex") as operation:
            self._assert_workspace(workspace)
            intent = getattr(self._local, "automatic_reindex", None)
            notice = getattr(self._local, "automatic_repair_notice", None)
            self._update(operation, request={"force": force})
            generation = None
            if self._memory_publication == "on-search":
                with self._condition:
                    generation = self._full_sync
                    if generation is None:
                        self._full_sync_count += 1
                        generation = {"id": self._full_sync_count,
                            "reservationOperationId": operation["id"], "operationId": None,
                            "reservationThreadId": threading.get_ident(), "threadId": None,
                            "started": False, "settled": False, "force": force,
                            "intent": intent, "notice": notice, "result": None, "error": None}
                        self._update(operation, reservedFullSync=generation["id"])
                        self._full_sync = generation
                    else:
                        self._update(operation, joinedFullSync=generation["id"],
                                     reservationOperationId=generation["reservationOperationId"])
            # Every unfinished request acquires the actual publisher guard.
            # No condition wait can retain an external workspace RLock.
            with self._index_producer_guard(workspace, generation=generation):
                if generation is not None:
                    if generation["settled"]:
                        return self._full_sync_result(generation, operation, intent, notice)
                    if generation["started"]:
                        raise RuntimeError("A full publication cannot join its own producer")
                    generation.update(started=True, operationId=operation["id"],
                                      threadId=threading.get_ident())
                previous_phase = getattr(self._local, "full_sync_phase", None)
                self._local.full_sync_phase = {"changes": 0}
                if generation is not None:
                    self._local.automatic_reindex = generation["intent"]
                    self._local.automatic_repair_notice = generation["notice"]
                producer_intent = getattr(self._local, "automatic_reindex", None)
                producer_force = generation["force"] if generation is not None else force
                result, failure = None, None
                try:
                    if generation is not None:
                        self._update(operation, fullSync=generation["id"],
                            reservationOperationId=generation["reservationOperationId"],
                            producerOperationId=operation["id"], producerRequest={"force": producer_force})
                    self._update(operation, request={"force": force}, before=self._read_state(),
                                 revisionBefore=self.read_published_index()["revision"])
                    effective_force = producer_force
                    if producer_intent is not None and not producer_intent["fullRetry"]:
                        effective_force = self._automatic_repair_allowed(
                            self._read_state(provider_key_known=True)["identity"])
                    try:
                        result = super().reindex(workspace, force=effective_force)
                    except BaseException as error:
                        code = getattr(error, "sqlite_errorcode", None)
                        unopened = (isinstance(error, sqlite3.Error) and isinstance(code, int)
                                    and code & 0xFF == sqlite3.SQLITE_CANTOPEN
                                    and self._local.full_sync_phase["changes"] == 0)
                        self._last_sync_error = format_error_message(error)
                        self._whole_failure_revision += 1
                        self._full_retry_required = self._memory_publication == "on-search" and not unopened
                        self._whole_failure_sources = frozenset(self._workspace.index_sources or ("memory", "sessions"))
                        if generation is not None:
                            generation["unopened"] = unopened
                        producer_notice = getattr(self._local, "automatic_repair_notice", None)
                        if producer_notice is not None:
                            producer_notice["unopened"] = unopened
                        if getattr(self._local, "memory_publisher", False):
                            self._memory_job_error = format_error_message(error)
                        raise
                    refused = producer_intent.get("refused") if producer_intent is not None else None
                    if generation is not None and refused is not None:
                        generation["refused"] = refused
                    if refused is None:
                        self._last_sync_error = None
                        self._full_retry_required = False
                        self._whole_failure_sources = frozenset()
                        self._memory_scope_failure = None
                        self._memory_job_error = None
                        self._refresh_memory_dirty(acknowledge_watch=True)
                    self._update(operation, returned=result, after=self._read_state(),
                                 revisionAfter=self.read_published_index()["revision"])
                    if refused is not None:
                        self._update(operation, automaticRefusal=refused)
                except BaseException as error:
                    failure = error
                finally:
                    self._local.full_sync_phase = previous_phase
                    self._local.automatic_reindex = intent
                    self._local.automatic_repair_notice = notice
                    if generation is not None:
                        # Settle before releasing the workspace guard. A later
                        # holder consumes this exact result/error, even if a
                        # newer independent generation has since been reserved.
                        with self._condition:
                            generation.update(result=result, error=failure, settled=True)
                            if self._full_sync is generation:
                                self._full_sync = None
                            self._condition.notify_all()
                if generation is not None:
                    return self._full_sync_result(generation, operation, intent, notice)
                if failure is not None:
                    raise failure
                return result

    def reindex_sources(self, workspace: MemoryWorkspace, *, sources: Collection[str],
                        paths: Collection[str] | None = None, force_sources: bool = False) -> int:
        """Refresh an explicit source scope under the managed admission lane.

        A failed publication that selected the memory corpus leaves the published
        index behind its committed source, so it is retained for ``status`` (and
        the search tool's stale report) until that selection publishes: a later
        memory publication with ``paths=None``, later path-limited memory
        publications that together cover the failed paths, or a whole
        ``reindex``. Refused requests (argument errors, an index that needs a
        full reindex) attempted no publication and are not retained. Sessions-only
        publications neither set nor settle it; they keep their controller receipt.
        A sessions-only refresh over a separate durable catalog reserves its
        source generation through publication. Mixed scopes, process-memory
        catalogs and a catalog sharing the index database retain strict source
        validation without that reservation.
        """
        with self._operation("reindex-sources") as operation:
            self._assert_workspace(workspace)
            self._update(operation, request={"sources": list(sources),
                "paths": None if paths is None else list(paths), "forceSources": force_sources},
                revisionBefore=self.index_revision())
            selection = self._validated_source_selection(workspace, sources, paths, force_sources)
            # As in ``reindex``, the outcome is recorded under the publisher's guard.
            with self._index_producer_guard(workspace):
                reservation = None
                try:
                    with self._session_source_reservation(selection.sources) as reservation:
                        if reservation is not None:
                            self._update(operation, catalogSourceReservation=deepcopy(reservation))
                        result = super().reindex_sources(workspace, sources=selection.sources,
                                                         paths=selection.paths, force_sources=force_sources)
                except MemoryIndexRequiresFullReindexError:
                    raise
                except BaseException as error:
                    # As in ``reindex``: an interrupted publication also leaves the index behind.
                    self._settle_memory_scope(selection.sources, selection.paths, error)
                    raise
                finally:
                    if reservation is not None:
                        self._update(operation, catalogSourceReservation=deepcopy(reservation))
                self._settle_memory_scope(selection.sources, selection.paths, None)
                if "memory" in selection.sources:
                    # Background admissions select the complete memory corpus;
                    # an empty or path-limited refresh cannot certify that job.
                    if selection.paths is None:
                        self._memory_job_error = None
                    self._refresh_memory_dirty(acknowledge_watch=True)
            self._update(operation, returned=result, revisionAfter=self.index_revision())
            return result

    @contextmanager
    def _session_source_reservation(self, sources: frozenset[str]) -> Iterator[dict[str, Any] | None]:
        catalog = self._bound_catalog
        if "sessions" not in sources or catalog is None:
            yield None
            return
        if sources != frozenset({"sessions"}):
            # Memory publication may consult a lazily created trust ledger in
            # the catalog database. Keep that broader scope on its existing
            # strict source validation rather than reserving its own writer.
            yield {"catalogPath": str(catalog.path), "agentId": catalog.agent_id,
                   "mode": "strict-source-validation", "acquired": False,
                   "reason": "mixed-source-selection", "released": True}
            return
        # A reservation on the index's own physical database would prevent its
        # separate publisher connection from writing. Preserve strict optimistic
        # validation for that layout, including aliases of the same inode.
        same_database = False
        if catalog._memory_uri is None:
            same_database = catalog.path == self.path
            if not same_database:
                try:
                    same_database = catalog.path.samefile(self.path)
                except FileNotFoundError:
                    pass
        if same_database or catalog._memory_uri is not None:
            yield {"catalogPath": str(catalog.path), "agentId": catalog.agent_id,
                   "mode": "strict-source-validation", "acquired": False,
                   "reason": ("catalog-and-index-share-physical-database" if same_database else
                              "process-memory-catalog"), "released": True}
            return
        with catalog._reserve_index_sources() as reservation:
            yield reservation

    def _settle_memory_scope(self, sources: frozenset[str], paths: frozenset[str] | None,
                             error: BaseException | None) -> None:
        """Retain or settle a failed memory selection; the caller holds the index guard."""
        if "memory" not in sources:
            return
        retained = self._memory_scope_failure
        if error is not None:
            if paths is not None and not paths:
                return  # An empty selection had nothing to publish.
            # Paths of a selection across both corpora do not say which are memory
            # files; a sessions-only publication could then never settle them.
            whole = (paths is None or "sessions" in sources
                     or retained is not None and retained[1] is None)
            failed = None if whole else paths | (retained[1] if retained is not None else frozenset())
            self._memory_scope_failure = (format_error_message(error), failed)
        elif retained is not None:
            if paths is None:
                self._memory_scope_failure = None
            elif retained[1] is not None:
                remaining = retained[1] - paths
                self._memory_scope_failure = (retained[0], remaining) if remaining else None

    @staticmethod
    def _automatic_repair_allowed(identity: dict[str, Any]) -> bool:
        return identity["status"] == "missing" or (
            identity["status"] == "mismatched" and identity.get("owner") == "openclaw"
            and identity.get("versionOrder") == "older"
        )

    def _on_index_preparation_admitted(self) -> None:
        super()._on_index_preparation_admitted()
        # Provider-none initialization requires no external resource, but its
        # knowledge still belongs to an admitted search/publication, not status.
        with self._condition:
            self._provider_initialized = True

    def _record_rebuild_request(self) -> None:
        agent = f" --agent {self.config.agent_id}" if self.config.agent_id else ""
        guidance = self._runtime_identity.memory_index_rebuild_guidance_keyword_only.format(agent=agent)
        self._automatic_rebuild_notice.update(sequence=self._automatic_rebuild_notice["sequence"] + 1,
            warning=f"Automatic memory index repair was requested. To rebuild manually, run: {guidance}")

    def _on_index_publication_write(
        self, db: sqlite3.Connection, *, changes: int, error: BaseException | None,
    ) -> None:
        super()._on_index_publication_write(db, changes=changes, error=error)
        phase = getattr(self._local, "full_sync_phase", None)
        if phase is not None:
            phase["changes"] = max(phase["changes"], changes)
        notice = getattr(self._local, "automatic_repair_notice", None)
        if notice is None:
            return
        # Cold bootstrap first acquires its storage owner. A failed first
        # dirty-page write has not opened the rollback journal; announcing a
        # rebuild there would precede Native's failed publisher-lease acquisition.
        # A populated identity repair announces earlier, before acquisition.
        code = getattr(error, "sqlite_errorcode", None)
        notice["unopened"] = (isinstance(error, sqlite3.Error)
                              and isinstance(code, int) and code & 0xFF == sqlite3.SQLITE_CANTOPEN
                              and changes == 0)
        if not notice["unopened"] and not notice["recorded"]:
            self._record_rebuild_request()
            notice["recorded"] = True

    def _repair_search(self, state: dict[str, Any], operation: dict[str, Any]) -> None:
        repair = self._automatic_repair_allowed(state["identity"])
        request = {"searchOperationId": operation["id"],
            "reason": "search-bootstrap" if not state["hasContent"] else "search-identity",
            "force": repair, "before": state,
            "noticeSequenceBefore": self._automatic_rebuild_notice["sequence"], "state": "requested"}
        with self._condition:
            self._repair_count += 1
            request["id"] = self._repair_count
            self._repairs.append(request)
        cold_notice = ({"recorded": False, "unopened": False}
                       if repair and not state["hasContent"] else None)
        if repair and cold_notice is None:
            self._record_rebuild_request()
        previous_notice = getattr(self._local, "automatic_repair_notice", None)
        self._local.automatic_repair_notice = cold_notice
        automatic = self._memory_publication == "on-search"
        try:
            with self._automatic_reindex() if automatic else nullcontext() as intent:
                try:
                    returned = self.reindex(self._workspace, force=repair)
                except Exception as error:
                    if (cold_notice is not None and not cold_notice["unopened"]
                            and not cold_notice["recorded"] and not cold_notice.get("joined")):
                        self._record_rebuild_request()
                        cold_notice["recorded"] = True
                    self._update(request, state="failed", error=self._error(error), after=self._read_state())
                else:
                    if (cold_notice is not None and not cold_notice["recorded"]
                            and not cold_notice.get("joined") and not (intent or {}).get("refused")):
                        self._record_rebuild_request()
                    self._update(request, state="completed", returned=returned, after=self._read_state())
                    if (intent or {}).get("refused"):
                        self._update(request, automaticRefusal=intent["refused"])
        finally:
            self._local.automatic_repair_notice = previous_notice
            self._update(request, noticeSequenceAfter=self._automatic_rebuild_notice["sequence"])

    @contextmanager
    def _managed_search_generation(self, operation: dict[str, Any], signal: CancellationSignal | None):
        guard = workspace_index_lock(self._workspace.root)
        with ExitStack() as reader:
            with ExitStack() as admission:
                db = None
                if guard.acquire(blocking=False):
                    admission.callback(guard.release)
                    db = reader.enter_context(self._search_connection(signal))
                # A cold reader must see and join an unfinished bootstrap even
                # when its publisher already owns the workspace guard.
                state = self._read_state(db=db, provider_key_known=True)
                with self._condition:
                    self._provider_initialized = True
                repair = not state["hasContent"] or (
                    self._last_sync_error is None and self._automatic_repair_allowed(state["identity"]))
                if repair or db is None:
                    reader.close()
                    admission.close()
                    if repair:
                        self._repair_search(state, operation)
                    admission.enter_context(guard)
                    db = reader.enter_context(self._search_connection(signal))
                    state = self._read_state(db=db, provider_key_known=True)
                self._refresh_memory_dirty(db=db)
                frame = {"db": db, "state": state, "status": deepcopy(self._status_from_state(state))}
            # Keep only the SQLite generation through lexical retrieval. WAL
            # publishers and live metadata readers retain their normal owners.
            frames = getattr(self._local, "search_status_frames", ())
            self._local.search_status_frames = (*frames, frame)
            try:
                yield frame
            finally:
                self._local.search_status_frames = frames

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        min_score: float = 0.0,
        sources: set[str] | None = None,
        signal: CancellationSignal | None = None,
        active_project_keys: Sequence[str] | None = None,
        on_partial_results: Callable[[list[HybridResult] | None], None] | None = None,
        session_key: str | None = None,
        on_debug: Callable[[dict[str, Any]], None] | None = None,
        deadline_control: MemorySearchDeadlineControl | None = None,
    ) -> list[HybridResult]:
        """Prepare a cold index through its actual publisher, then search it."""
        options = {"max_results": max_results, "min_score": min_score, "sources": sources,
            "signal": signal, "active_project_keys": active_project_keys,
            "on_partial_results": on_partial_results, "session_key": session_key,
            "on_debug": on_debug, "deadline_control": deadline_control}
        with self._operation("search") as operation:
            self._assert_workspace(self._workspace)
            if signal is not None:
                signal.throw_if_aborted()
            if not js_trim(query):
                return super().search(query, **options)
            self._update(operation, query=query)
            if self._memory_publication == "on-search":
                with self._managed_search_generation(operation, signal) as frame:
                    if signal is not None:
                        signal.throw_if_aborted()
                    return _ManagedSearchResults(super().search(query, **options), frame["status"])
            with workspace_index_lock(self._workspace.root):
                state = self._read_state(provider_key_known=True)
                with self._condition:
                    self._provider_initialized = True
                identity = state["identity"]
                if self._last_sync_error is None and (self._automatic_repair_allowed(identity)
                        or not state["hasContent"] and identity["status"] == "valid"):
                    self._repair_search(state, operation)
            if signal is not None:
                signal.throw_if_aborted()
            return super().search(query, **options)

    def lifecycle_snapshot(self) -> dict[str, Any]:
        """Copy actual admitted operations/repair receipts, including after close."""
        with self._condition:
            controller = self._session_publication
            scoped = self._memory_scope_failure
            snapshot = deepcopy({"workspace": str(self._bound_workspace), "indexPath": str(self._bound_index),
                "agentId": self._bound_agent, "activeOperations": self._active_operations,
                "closing": self._closing, "closed": self._closed,
                "automaticRebuildNotice": self._automatic_rebuild_notice,
                "lastSyncError": self._last_sync_error,
                "operationCount": self._operation_count, "repairCount": self._repair_count,
                "operationJournalTruncated": self._operation_count > len(self._operations),
                "repairJournalTruncated": self._repair_count > len(self._repairs),
                "operations": list(self._operations), "repairs": list(self._repairs),
                "sessionReadAdmissionCount": self._read_admission_count,
                "sessionReadJournalTruncated": self._read_admission_count > len(self._read_admissions),
                "sessionReadAdmissions": list(self._read_admissions)})
        if scoped is not None:
            # Present only while a failed memory-scope publication is retained, so
            # receipts of runs without one are unchanged.
            snapshot["memoryScopeSyncFailure"] = {
                "error": scoped[0], "paths": None if scoped[1] is None else sorted(scoped[1])}
        if self._memory_publication == "on-search":
            with self._condition:
                snapshot["memoryPublication"] = deepcopy({"policy": "on-search", "dirty": self._memory_dirty,
                    "active": self._memory_active, "lastError": self._memory_job_error,
                    "jobCount": self._memory_job_count, "jobs": list(self._memory_jobs),
                    "jobsTruncated": self._memory_job_count > len(self._memory_jobs),
                    "watchGeneration": self._memory_watch_generation,
                    "watchReadyGeneration": self._memory_watch_ready_generation,
                    "watchPublishedGeneration": self._memory_watch_published_generation,
                    "watchFacts": list(self._memory_watch_facts),
                    "watchSettlements": list(self._memory_watch_settlements),
                    "watchError": self._memory_watch_error})
            if self._memory_watcher is not None:
                snapshot["memoryPublication"]["watcher"] = self._memory_watcher.status()
        if controller is not None:
            snapshot["sessionPublication"] = controller.status()
        return snapshot

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed

    def close(self) -> None:
        """Join actual admitted operations; this store keeps no idle DB handle."""
        with self._condition:
            if getattr(self._local, "depth", 0):
                raise RuntimeError("An active managed index operation cannot close its own owner")
            if getattr(self._local, "memory_publisher", False):
                raise RuntimeError("A memory publication job cannot close its own managed index")
            controller = self._session_publication
            watcher = self._memory_watcher
            if watcher is not None and watcher.owns_current_thread():
                raise RuntimeError("A memory watcher cannot close its own managed index")
            if controller is not None and controller.owns_current_job():
                raise RuntimeError("A session publication job cannot close its own managed index")
            while self._closing:
                self._condition.wait()
            if self._closed:
                return
            self._closing = True
            self._condition.notify_all()
        try:
            if watcher is not None:
                watcher.close()
            if controller is not None:
                controller.close()
        except BaseException:
            with self._condition:
                self._closing = False
                self._condition.notify_all()
            raise
        with self._condition:
            while self._active_operations or self._memory_active:
                self._condition.wait()
            executor = self._memory_executor
        if executor is not None:
            executor.shutdown(wait=True)
        with self._condition:
            self._closed = True
            self._closing = False
            self._condition.notify_all()
