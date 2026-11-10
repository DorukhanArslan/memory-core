"""An explicit provider-none index owner with real search-time bootstrap.

Ordinary ``HostKit.open`` remains eager. Hosts selecting this owner construct a
``Memory``/``HostKit`` around it without an initial reindex. Repairs use the
normal checked SQLite publisher; status and notices describe those real calls.
An optional explicitly bound session controller starts after a real search read
generation is acquired. Ordinary construction does not start background work.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Collection, Iterator, Sequence
from contextlib import closing, contextmanager
from copy import deepcopy
import threading
import sqlite3
from typing import TYPE_CHECKING, Any

from memory_core.bootstrap._js import js_trim
from memory_core.cancellation import CancellationSignal
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.consolidation.origins import IndexRevisionFence
from memory_core.index.sqlite_store import MemoryIndexRequiresFullReindexError, SQLiteMemoryStore
from memory_core.index.hybrid import HybridResult
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.session_catalog import normalize_session_agent_id
from memory_core.tools.common import format_error_message
from memory_core.tools.deadline import MemorySearchDeadlineControl
from memory_core.workspace import MemoryWorkspace, workspace_index_lock

if TYPE_CHECKING:
    from memory_core.host.session_publication import SessionPublicationController


class ManagedSQLiteMemoryStore(SQLiteMemoryStore):
    """A bound FTS-only store whose first search can bootstrap its real index.

    ``status`` retains one live notice object so the ordinary memory tool can
    observe a repair requested during that call. A prior notice is not replayed.
    ``close`` refuses new managed search/reindex/status operations and joins
    those already admitted, including a publication whose caller stopped waiting.
    Inherited raw SQL inspection APIs remain outside this managed admission lane.
    A failed whole publication requires an explicit successful ``reindex`` before
    automatic preparation resumes; search does not retry a failed producer.
    A failed memory-scope ``reindex_sources`` publication is retained separately:
    ``status`` reports it (when no whole publication failure is retained) until
    the failed selection publishes or a whole ``reindex`` succeeds. It does not
    gate automatic preparation.
    """

    def __init__(self, config: MemoryConfig, workspace: MemoryWorkspace, *,
                 artifact_provenance: MemoryArtifactProvenanceStore | None = None,
                 revision_fence: IndexRevisionFence | None = None,
                 runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY) -> None:
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
        self._condition = threading.Condition(threading.RLock())
        self._local = threading.local()
        self._active_operations = 0
        self._closing = False
        self._closed = False
        self._last_sync_error: str | None = None
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
        super().__init__(config, None, revision_fence=revision_fence, artifact_provenance=artifact_provenance)

    @contextmanager
    def _operation(self, name: str) -> Iterator[dict[str, Any]]:
        with self._condition:
            depth = getattr(self._local, "depth", 0)
            draining_publication = (name == "reindex-sources" and self._session_publication is not None
                                    and self._session_publication.owns_current_job())
            if self._closed or self._closing and not depth and not draining_publication:
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

    @staticmethod
    def _error(error: BaseException) -> dict[str, Any]:
        return {"name": getattr(error, "name", type(error).__name__), "message": format_error_message(error)}

    def _update(self, record: dict[str, Any], **values: Any) -> None:
        with self._condition:
            record.update(values)

    def _read_state(self) -> dict[str, Any]:
        with closing(self.connect()) as db:
            db.execute("BEGIN")
            identity = self.index_identity(db=db)
            fts_available = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunks_fts'").fetchone() is not None
            chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            fts_content = fts_available and db.execute("SELECT 1 FROM chunks_fts LIMIT 1").fetchone() is not None
            counts = {source: count for source, count in db.execute("SELECT source,COUNT(*) FROM chunks GROUP BY source")}
            sources = self._workspace.index_sources or ("memory", "sessions")
            return {"identity": identity, "hasContent": bool(chunks or fts_content), "chunks": chunks,
                    "ftsAvailable": fts_available,
                    "sourceCounts": [{"source": source, "chunks": counts.get(source, 0)} for source in sources]}

    def status(self) -> dict[str, Any]:
        """Read actual published SQL state and the live repair-request notice."""
        with self._operation("status"):
            self._assert_workspace(self._workspace)
            state = self._read_state()
            result = {"backend": "builtin", "provider": "none", "requestedProvider": "none",
                "chunks": state["chunks"], "sourceCounts": state["sourceCounts"],
                "fts": {"enabled": self.flags.text_search, "available": state["ftsAvailable"]},
                "custom": {"indexIdentity": state["identity"],
                           "automaticRebuildNotice": self._automatic_rebuild_notice}}
            sync_error, scoped = self._last_sync_error, self._memory_scope_failure
            if sync_error is None and scoped is not None:
                sync_error = scoped[0]
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

    def _on_search_snapshot(self, db: sqlite3.Connection) -> None:
        controller = self._session_publication
        if controller is None:
            return
        # The caller has already read index identity in this transaction: BEGIN
        # alone would not pin SQLite's deferred read snapshot.
        revision = self.index_revision(db=db)
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
                controller.start()

    def reindex(self, workspace: MemoryWorkspace, *, force: bool = False) -> int:
        """Publish only the bound workspace; preserve the original return/error."""
        with self._operation("reindex") as operation:
            self._assert_workspace(workspace)
            self._update(operation, request={"force": force}, before=self._read_state(),
                         revisionBefore=self.read_published_index()["revision"])
            # The outcome is recorded before another cooperating publication can
            # interleave: the reentrant workspace guard is the publisher's own.
            with workspace_index_lock(workspace.root):
                try:
                    result = super().reindex(workspace, force=force)
                except BaseException as error:
                    self._last_sync_error = format_error_message(error)
                    raise
                self._last_sync_error = None
                self._memory_scope_failure = None
            self._update(operation, returned=result, after=self._read_state(),
                         revisionAfter=self.read_published_index()["revision"])
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
        """
        with self._operation("reindex-sources") as operation:
            self._assert_workspace(workspace)
            self._update(operation, request={"sources": list(sources),
                "paths": None if paths is None else list(paths), "forceSources": force_sources},
                revisionBefore=self.index_revision())
            selection = self._validated_source_selection(workspace, sources, paths, force_sources)
            # As in ``reindex``, the outcome is recorded under the publisher's guard.
            with workspace_index_lock(workspace.root):
                try:
                    result = super().reindex_sources(workspace, sources=selection.sources,
                                                     paths=selection.paths, force_sources=force_sources)
                except MemoryIndexRequiresFullReindexError:
                    raise
                except Exception as error:
                    self._settle_memory_scope(selection.sources, selection.paths, error)
                    raise
                self._settle_memory_scope(selection.sources, selection.paths, None)
            self._update(operation, returned=result, revisionAfter=self.index_revision())
            return result

    def _settle_memory_scope(self, sources: frozenset[str], paths: frozenset[str] | None,
                             error: Exception | None) -> None:
        """Retain or settle a failed memory selection; the caller holds the index guard."""
        if "memory" not in sources:
            return
        retained = self._memory_scope_failure
        if error is not None:
            if paths is not None and not paths:
                return  # An empty selection had nothing to publish.
            whole = paths is None or retained is not None and retained[1] is None
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

    def _record_rebuild_request(self) -> None:
        agent = f" --agent {self.config.agent_id}" if self.config.agent_id else ""
        guidance = self._runtime_identity.memory_index_rebuild_guidance_keyword_only.format(agent=agent)
        self._automatic_rebuild_notice.update(sequence=self._automatic_rebuild_notice["sequence"] + 1,
            warning=f"Automatic memory index repair was requested. To rebuild manually, run: {guidance}")

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
            with workspace_index_lock(self._workspace.root):
                state = self._read_state()
                identity = state["identity"]
                repair = self._automatic_repair_allowed(identity)
                if self._last_sync_error is None and (repair or not state["hasContent"] and identity["status"] == "valid"):
                    request = {"searchOperationId": operation["id"],
                        "reason": "search-bootstrap" if not state["hasContent"] else "search-identity",
                        "force": repair, "before": state,
                        "noticeSequenceBefore": self._automatic_rebuild_notice["sequence"], "state": "requested"}
                    with self._condition:
                        self._repair_count += 1
                        request["id"] = self._repair_count
                        self._repairs.append(request)
                    if repair:
                        self._record_rebuild_request()
                    self._update(request, noticeSequenceAfter=self._automatic_rebuild_notice["sequence"])
                    try:
                        returned = self.reindex(self._workspace, force=repair)
                    except Exception as error:
                        self._update(request, state="failed", error=self._error(error), after=self._read_state())
                        # The actual failed repair is retained by reindex/status.
                        # The ordinary tool presents the genuine remaining index
                        # identity and sync failure rather than a fabricated hit.
                        pass
                    else:
                        self._update(request, state="completed", returned=returned, after=self._read_state())
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
            controller = self._session_publication
            if controller is not None and controller.owns_current_job():
                raise RuntimeError("A session publication job cannot close its own managed index")
            while self._closing:
                self._condition.wait()
            if self._closed:
                return
            self._closing = True
            self._condition.notify_all()
        try:
            if controller is not None:
                controller.close()
        except BaseException:
            with self._condition:
                self._closing = False
                self._condition.notify_all()
            raise
        with self._condition:
            while self._active_operations:
                self._condition.wait()
            self._closed = True
            self._closing = False
            self._condition.notify_all()
