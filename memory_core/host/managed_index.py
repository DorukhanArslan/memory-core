"""An explicit provider-none index owner with real search-time bootstrap.

Ordinary ``HostKit.open`` remains eager. Hosts selecting this owner construct a
``Memory``/``HostKit`` around it without an initial reindex. Repairs use the
normal checked SQLite publisher; status and notices describe those real calls.
Background refresh, provider lifecycle and session scheduling are not supplied
by this owner.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from copy import deepcopy
import threading
from typing import Any

from memory_core.bootstrap._js import js_trim
from memory_core.cancellation import CancellationSignal
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.consolidation.origins import IndexRevisionFence
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.index.hybrid import HybridResult
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.session_catalog import normalize_session_agent_id
from memory_core.tools.common import format_error_message
from memory_core.tools.deadline import MemorySearchDeadlineControl
from memory_core.workspace import MemoryWorkspace, workspace_index_lock


class ManagedSQLiteMemoryStore(SQLiteMemoryStore):
    """A bound FTS-only store whose first search can bootstrap its real index.

    ``status`` retains one live notice object so the ordinary memory tool can
    observe a repair requested during that call. A prior notice is not replayed.
    ``close`` refuses new managed search/reindex/status operations and joins
    those already admitted, including a publication whose caller stopped waiting.
    Inherited raw SQL inspection APIs remain outside this managed admission lane.
    A failed publication requires an explicit successful ``reindex`` before
    automatic preparation resumes; search does not retry a failed producer.
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
        self._automatic_rebuild_notice: dict[str, Any] = {"sequence": 0, "warning": ""}
        self._operations: deque[dict[str, Any]] = deque(maxlen=512)
        self._repairs: deque[dict[str, Any]] = deque(maxlen=256)
        self._operation_count = 0
        self._repair_count = 0
        super().__init__(config, None, revision_fence=revision_fence, artifact_provenance=artifact_provenance)

    @contextmanager
    def _operation(self, name: str) -> Iterator[dict[str, Any]]:
        with self._condition:
            depth = getattr(self._local, "depth", 0)
            if self._closed or self._closing and not depth:
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
            if self._last_sync_error is not None:
                result["lastSyncError"] = self._last_sync_error
            return result

    def reindex(self, workspace: MemoryWorkspace, *, force: bool = False) -> int:
        """Publish only the bound workspace; preserve the original return/error."""
        with self._operation("reindex") as operation:
            self._assert_workspace(workspace)
            self._update(operation, request={"force": force}, before=self._read_state(),
                         revisionBefore=self.read_published_index()["revision"])
            try:
                result = super().reindex(workspace, force=force)
            except BaseException as error:
                self._last_sync_error = format_error_message(error)
                raise
            self._last_sync_error = None
            self._update(operation, returned=result, after=self._read_state(),
                         revisionAfter=self.read_published_index()["revision"])
            return result

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
            return deepcopy({"workspace": str(self._bound_workspace), "indexPath": str(self._bound_index),
                "agentId": self._bound_agent, "activeOperations": self._active_operations,
                "closing": self._closing, "closed": self._closed,
                "automaticRebuildNotice": self._automatic_rebuild_notice,
                "lastSyncError": self._last_sync_error,
                "operationCount": self._operation_count, "repairCount": self._repair_count,
                "operationJournalTruncated": self._operation_count > len(self._operations),
                "repairJournalTruncated": self._repair_count > len(self._repairs),
                "operations": list(self._operations), "repairs": list(self._repairs)})

    @property
    def closed(self) -> bool:
        with self._condition:
            return self._closed

    def close(self) -> None:
        """Join actual admitted operations; this store keeps no idle DB handle."""
        with self._condition:
            if getattr(self._local, "depth", 0):
                raise RuntimeError("An active managed index operation cannot close its own owner")
            if self._closed:
                return
            self._closing = True
            self._condition.notify_all()
            while self._active_operations:
                self._condition.wait()
            self._closed = True
            self._closing = False
            self._condition.notify_all()
