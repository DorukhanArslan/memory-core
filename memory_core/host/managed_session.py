"""Explicit shared managed host ownership; eager HostSessionRunner stays unchanged.

The default memory policy publishes synchronously when an index namespace
exists. Opt-in ``on-search`` publication commits writes and admits a real
background memory publisher only after a search pins its SQLite generation.
Cold writes and deferred session publication remain pending. Full ``reindex``
is an explicit owner barrier; ordinary turns never drain a future session timer.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextvars import ContextVar, Token
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, fields, replace
from pathlib import Path
import threading
from typing import Any, Literal

from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.flags import FeatureFlags
from memory_core.host.kit import HostKit
from memory_core.host.lifecycle import (
    HostModelResult, HostSessionRunner, HostTurn, HostTurnOutcome, _Admission, _RunCapture,
    _acquire_lane, _current_lanes, _failure, _memory_publication, _memory_wrote, _stored_pending_publication,
)
from memory_core.host.managed_maintenance import OptionalMaintenance, reserve_foreground, schedule_optional
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.host.session import SessionState, apply_turn_usage
from memory_core.host.session_publication import Scheduler, SessionPublicationController
from memory_core.index.sqlite_store import read_index_source
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.session_catalog import MemorySessionCatalog, normalize_session_agent_id
from memory_core.session_visibility import SessionVisibilityContext
from memory_core.turn_tool_dispatch import TurnTool
from memory_core.workspace import MemoryWorkspace


_active_owners: ContextVar[tuple[object, ...]] = ContextVar("managed_host_owners", default=())
_optional_stages: ContextVar[list[dict[str, Any]] | None] = ContextVar("managed_optional_stages", default=None)
_delivery_callback: ContextVar[Callable[[ManagedHostTurnOutcome], Awaitable[None]] | None] = ContextVar(
    "managed_delivery_callback", default=None)


@dataclass(frozen=True)
class ManagedHostTurnOutcome(HostTurnOutcome):
    publication: Mapping[str, Any] | None = None


class ManagedHostSession:
    """One agent/workspace owner shared by its per-chat managed runners."""

    def __init__(self, kit: HostKit, catalog: MemorySessionCatalog,
                 controller: SessionPublicationController, *,
                 maintenance: Literal["inline", "background"] = "inline") -> None:
        if not isinstance(maintenance, str) or maintenance not in {"inline", "background"}:
            raise ValueError("maintenance must be inline or background")
        if not isinstance(kit.memory.store, ManagedSQLiteMemoryStore):
            raise TypeError("A managed host requires ManagedSQLiteMemoryStore")
        if kit._curation_index_sources != ("memory",) or not kit._defer_cold_index:
            raise ValueError("A managed host requires scoped memory curation with deferred cold publication")
        controller.assert_bound(kit.memory.store, kit.memory.workspace, catalog)
        try:
            kit.memory.store.bind_session_publication(controller)
        except RuntimeError as error:
            raise ValueError("The managed host requires the store's exact publication owner") from error
        self._kit, self._catalog, self._store, self._controller = kit, catalog, kit.memory.store, controller
        self._condition = threading.Condition(threading.RLock())
        self._active_turns = 0
        self._control_active = False
        self._closing = self._closed = False
        self._close_requested = False
        self._maintenance_policy = maintenance
        self._maintenance_jobs: set[OptionalMaintenance] = set()
        self._maintenance_history: deque[OptionalMaintenance] = deque(maxlen=256)
        sources = kit.memory.workspace.index_sources
        self._sessions_enabled = "sessions" in (sources if sources is not None else ("memory", "sessions"))

    @classmethod
    def open(cls, workspace_dir: str | Path, *, catalog: MemorySessionCatalog,
             config: MemoryConfig | None = None, source_policy: Mapping[str, Any] | None = None,
             artifact_provenance: MemoryArtifactProvenanceStore | None = None,
             scheduler: Scheduler | None = None, identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
             initialize: bool = False,
             memory_publication: Literal["on-write", "on-search"] = "on-write",
             maintenance: Literal["inline", "background"] = "inline",
             **kit_options: Any) -> ManagedHostSession:
        if not isinstance(memory_publication, str) or memory_publication not in {"on-write", "on-search"}:
            raise ValueError("memory_publication must be on-write or on-search")
        if not isinstance(maintenance, str) or maintenance not in {"inline", "background"}:
            raise ValueError("maintenance must be inline or background")
        root = Path(workspace_dir).resolve()
        config = config or MemoryConfig(root, agent_id=catalog.agent_id, flags=FeatureFlags(vector_search=False))
        if Path(config.workspace_dir).resolve() != root or normalize_session_agent_id(config.agent_id) != catalog.agent_id:
            raise ValueError("The managed host config, workspace and catalog must have the same owner")
        if "curation_index_sources" in kit_options or "defer_cold_index" in kit_options:
            raise ValueError("The managed owner supplies its own scoped curation policy")
        policy = deepcopy(dict(source_policy)) if source_policy is not None else None
        workspace = MemoryWorkspace(root, agent_id=config.agent_id, session_catalog=catalog,
                                    index_sources=policy["sources"] if policy is not None else None)
        index = config.resolved_store_path().resolve()
        ledger = artifact_provenance or MemoryArtifactProvenanceStore(index.with_name(f"{index.stem}.provenance.sqlite"))
        store = ManagedSQLiteMemoryStore(config, workspace, artifact_provenance=ledger, runtime_identity=identity,
                                        memory_publication=memory_publication)
        controller = SessionPublicationController(store, workspace, catalog, scheduler=scheduler)
        store.bind_session_publication(controller)
        memory = Memory(config, workspace, store, SessionVisibilityContext.from_catalog(catalog), policy)
        kit = HostKit(memory, artifact_provenance=ledger, identity=identity,
                      curation_index_sources=("memory",), defer_cold_index=True, **kit_options)
        if initialize:
            kit.ensure()
        return cls(kit, catalog, controller, maintenance=maintenance)

    @property
    def kit(self) -> HostKit:
        return self._kit

    @property
    def catalog(self) -> MemorySessionCatalog:
        return self._catalog

    @property
    def store(self) -> ManagedSQLiteMemoryStore:
        return self._store

    @property
    def controller(self) -> SessionPublicationController:
        return self._controller

    def _ensure_open(self) -> None:
        if self._close_requested or self._closing or self._closed:
            raise RuntimeError("Managed host owner is closed")

    def maintenance_status(self) -> dict[str, Any]:
        """Actual optional-job receipts; foreground replies are never rewritten later."""
        with self._condition:
            jobs = tuple(self._maintenance_history)
        return {"policy": self._maintenance_policy, "jobs": [job.snapshot() for job in jobs]}

    def _schedule_maintenance(self, runner: ManagedHostSessionRunner, specification) -> None:
        with self._condition:
            if self._close_requested or self._closing or self._closed:
                return

            def settled(job: OptionalMaintenance) -> None:
                with self._condition:
                    self._maintenance_jobs.discard(job)
                    self._condition.notify_all()

            job = schedule_optional(runner._lane_key,
                lambda job: runner._run_background_maintenance(job, specification), settled)
            self._maintenance_jobs.add(job)
            self._maintenance_history.append(job)

    def runner(self, session: SessionState, *, extra_tools: Sequence[TurnTool] = ()) -> ManagedHostSessionRunner:
        with self._condition:
            self._ensure_open()
            return ManagedHostSessionRunner(self, session=session, extra_tools=extra_tools)

    def _session_current(self, session_key: str, session_id: str) -> bool:
        if not self._sessions_enabled:
            return True
        entry = self.catalog.get_session_entry(session_key)
        if entry is None or entry.get("sessionId") != session_id:
            return False
        path = f"sessions/{self.catalog.agent_id}/{session_id}.jsonl"
        current = next((snapshot for file in self.kit.memory.workspace.discover_session_transcript_files(paths={path})
                        if (snapshot := read_index_source(file)) is not None and snapshot.path == path), None)
        row = next((item for item in self.store.read_published_index()["sources"]
                    if item["source"] == "sessions" and item["path"] == path), None)
        # Absence is covered only when the actual admitted source reader and
        # published index agree. Excluded sources with stale rows stay dirty.
        return row is None if current is None else bool(row and all(
            row[key] == getattr(current, key) for key in ("hash", "mtime", "size")))

    def _acknowledge_coverage(self, *, memory: bool = False) -> None:
        """Clear only dirty domains covered by genuine published source state."""
        with self._condition:
            snapshot = self.catalog.snapshot()
            updates: dict[str, Mapping[str, Any]] = {}
            for key, entry in snapshot.entries.items():
                auxiliary = entry.get("sdkHostLifecycle")
                if not isinstance(auxiliary, Mapping) or auxiliary.get("publicationMode") != "managed":
                    continue
                covered = self._session_current(key, entry["sessionId"])
                state = dict(auxiliary)
                if memory and state.get("pendingMemoryPublication") is None:
                    state["needsMemoryIndex"] = False
                if covered:
                    state["needsSessionIndex"] = False
                state["needsIndex"] = state.get("needsMemoryIndex") is True or state.get("needsSessionIndex") is True
                if state != auxiliary:
                    updates[key] = state
            if updates:
                # The catalog compares the plan's revision under its actual
                # write transaction. Conflicts keep dirty markers; no retry can
                # silently acknowledge a later transcript or incarnation.
                self.catalog.compare_and_patch_host_lifecycle(expected_revision=snapshot.revision, updates=updates)

    def publication_status(self) -> dict[str, Any]:
        controller = self.controller.status()
        # The public kit/curator can publish outside a runner turn, so no
        # durable turn marker is guaranteed to describe a retained failure.
        # The read-only lifecycle receipt remains available after close.
        publication = self.store.lifecycle_snapshot()
        entries = self.catalog.snapshot().entries.values()
        memory_pending = (self.store.index_identity()["status"] != "valid"
                          or publication["lastSyncError"] is not None
                          or publication.get("memoryScopeSyncFailure") is not None
                          or publication.get("memoryPublication", {}).get("dirty", False)
                          or publication.get("memoryPublication", {}).get("active", False)
                          or publication.get("memoryPublication", {}).get("lastError") is not None)
        session_dirty = False
        for entry in entries:
            state = entry.get("sdkHostLifecycle", {})
            if isinstance(state, Mapping) and state.get("publicationMode") == "managed":
                memory_pending |= state.get("needsMemoryIndex") is True
                session_dirty |= state.get("needsSessionIndex") is True
        pending = controller["pending"] if self._sessions_enabled else False
        if session_dirty:
            pending = True
        memory_status = "pending" if memory_pending else "ready"
        session_status = ("failed" if controller["lastError"] is not None else
                          "pending" if pending is not False else "ready")
        index_status = "failed" if session_status == "failed" else (
            "ready" if memory_status == session_status == "ready" else "pending")
        return {"memoryIndexStatus": memory_status, "sessionIndexStatus": session_status,
            "indexStatus": index_status, "sessionPending": pending, "controller": controller,
            "ready": index_status == "ready", "activeTurns": self._active_turns,
            "closing": self._close_requested or self._closing, "closed": self._closed}

    def _begin_control(self) -> None:
        with self._condition:
            self._ensure_open()
            if self._active_turns or self._control_active or self._maintenance_jobs:
                raise RuntimeError("Explicit managed publication requires settled host turns")
            self._control_active = True

    def reindex(self, *, force: bool = False) -> int:
        """Explicit full publication plus real startup/reconciliation custody.

        This stronger SDK owner barrier joins its actual admitted startup work;
        it is not a claim that every native manager drains startup discovery.
        """
        self._begin_control()
        try:
            returned = self.store.reindex(self.kit.memory.workspace, force=force)
            self._join_startup()
            self.controller.reconcile()
            self.controller.raise_if_failed()
            self._acknowledge_coverage(memory=True)
            return returned
        finally:
            with self._condition:
                self._control_active = False
                self._condition.notify_all()

    def _join_startup(self, timeout: float | None = None) -> None:
        # A later explicit call may retry a retained failure. A newly admitted
        # startup failure belongs to this call and must surface before any retry.
        retrying_failure = self.controller.status()["lastError"] is not None
        self.controller.start()
        if not self.controller.wait_idle(timeout):
            raise TimeoutError("Session publication did not become idle")
        if not retrying_failure:
            self.controller.raise_if_failed()

    def synchronize(self, *, timeout: float | None = None) -> dict[str, Any]:
        """Publish memory and reconcile actual session sources once, without a cold fallback."""
        self._begin_control()
        try:
            self.kit.memory._refresh_index(sources=("memory",))
            self._join_startup(timeout)
            self.controller.reconcile(timeout=timeout)
            self._acknowledge_coverage(memory=True)
            return self.publication_status()
        finally:
            with self._condition:
                self._control_active = False
                self._condition.notify_all()

    def close(self) -> None:
        """Close a settled owner once; active async hosts use ``await aclose()``."""
        if self in _active_owners.get():
            raise RuntimeError("A host turn cannot close its own managed owner")
        with self._condition:
            if self._active_turns or self._control_active or self._maintenance_jobs:
                raise RuntimeError("Managed host work is active; settle it or use await aclose()")
        self._close_joined()

    def _close_joined(self) -> None:
        with self._condition:
            while self._closing:
                self._condition.wait()
            if self._closed:
                return
            self._closing = True
            self._condition.notify_all()
            self._condition.wait_for(lambda: not self._active_turns and not self._control_active
                                     and not self._maintenance_jobs)
        try:
            self.store.close()
        except BaseException:
            with self._condition:
                self._closing = False
                self._close_requested = False
                self._condition.notify_all()
            raise
        with self._condition:
            self._closed, self._closing = True, False
            self._condition.notify_all()

    async def aclose(self) -> None:
        if self in _active_owners.get():
            raise RuntimeError("A host turn cannot close its own managed owner")
        with self._condition:
            self._close_requested = True
            jobs = tuple(self._maintenance_jobs)
        for job in jobs:
            job.request_cancel()

        async def close_after_jobs() -> None:
            for job in jobs:
                await job.join()
            await asyncio.to_thread(self._close_joined)

        closing = asyncio.create_task(close_after_jobs())
        cancellation = None
        while True:
            try:
                await asyncio.shield(closing)
                break
            except asyncio.CancelledError as error:
                cancellation = error
        if cancellation is not None:
            raise cancellation


class ManagedHostSessionRunner(HostSessionRunner):
    """Per-chat admission using a shared explicit managed host owner."""

    def __init__(self, owner: ManagedHostSession, *, session: SessionState,
                 extra_tools: Sequence[TurnTool] = ()) -> None:
        self.owner = owner
        self._background_job: OptionalMaintenance | None = None
        super().__init__(owner.kit, owner.catalog, session=session, extra_tools=extra_tools)

    async def _run_after_turn(self, state, **options):
        if self.owner._maintenance_policy == "inline":
            return await super()._run_after_turn(state, **options)
        state = apply_turn_usage(state, options["result"].usage)
        options["capture"].state = state
        stages = _optional_stages.get()
        if stages is None:
            raise RuntimeError("A background maintenance plan requires its foreground owner")
        stages.append({"session": state, "turn_id": options["turn_id"],
            "execute_flush": options["execute_flush"], "trust": options["trust"],
            "context_window_tokens": options["context_window_tokens"], "delivery_ok": False})
        return state

    async def _invoke_flush(self, execute_flush, maintenance: HostTurn):
        if self._background_job is None:
            return await super()._invoke_flush(execute_flush, maintenance)
        callback = asyncio.create_task(execute_flush(maintenance))
        self._background_job.bind_model_abort(callback.cancel)
        try:
            return await callback
        finally:
            self._background_job.bind_model_abort(None)

    def _terminal_delivery(self, outcome: HostTurnOutcome):
        if not outcome.cancelled and outcome.memory_publication != "uncertain":
            for specification in _optional_stages.get() or ():
                self.owner._schedule_maintenance(self, specification)
        self.owner._acknowledge_coverage()
        status = self.owner.publication_status()
        values = {item.name: getattr(outcome, item.name) for item in fields(HostTurnOutcome)}
        if outcome.index_status in {"ready", "pending"}:
            values["index_status"] = status["indexStatus"]
        managed = ManagedHostTurnOutcome(**values, publication=status)
        self.last_outcome = managed
        callback = _delivery_callback.get()
        stages = _optional_stages.get() or ()
        if callback is None:
            for specification in stages:
                specification["delivery_ok"] = not managed.cancelled
            return managed

        async def deliver():
            try:
                await callback(managed)
            except BaseException as error:
                self.last_outcome = replace(managed,
                    cancelled=managed.cancelled or isinstance(error, asyncio.CancelledError),
                    failures=(*managed.failures, _failure("delivery", error,
                                                        committed=managed.transcript_committed)))
                raise
            for specification in stages:
                specification["delivery_ok"] = not managed.cancelled and not self._cancel_requested.is_set()
            return managed

        return deliver()

    async def _run_background_maintenance(self, job: OptionalMaintenance, specification):
        worker = ManagedHostSessionRunner(self.owner, session=specification["session"], extra_tools=self.extra_tools)
        worker._cancel_requested = job.cancel_requested
        worker._background_job = job
        release = await _acquire_lane(worker._lane_key)
        admission = _Admission(worker._lane_key)
        ancestors = tuple(item for item in _current_lanes.get() if item.active)
        lane_token = _current_lanes.set((*ancestors, admission))
        owner_token = _active_owners.set((*_active_owners.get(), self.owner))
        state = worker.session
        capture = _RunCapture(state, [], [], [])
        failures = []
        index_status = "not-run"
        admitted = False
        turn_id = specification["turn_id"]
        try:
            worker._assert_maintenance_current()
            if not specification["delivery_ok"]:
                raise asyncio.CancelledError("Optional maintenance lost foreground authority")
            state, continuation, _ = worker._load()
            capture.state = state
            if _stored_pending_publication(continuation["instanceEntry"]) is not None:
                raise RuntimeError("An unresolved memory publication cannot admit optional maintenance")
            if state.entry.get("sdkHostLifecycle", {}).get("lastTurnId") != turn_id:
                raise asyncio.CancelledError("Session changed before optional maintenance admission")
            admitted = True
            state = await HostSessionRunner._run_after_turn(worker, state, result=HostModelResult(),
                messages=continuation["llmMessages"], continuation=continuation,
                trust=specification["trust"], turn_id=turn_id,
                execute_flush=specification["execute_flush"],
                context_window_tokens=specification["context_window_tokens"],
                capture=capture, receipts=capture.receipts, failures=failures, usage_applied=True)
        except (asyncio.CancelledError, Exception) as error:
            failures.append(_failure(capture.maintenance_phase or "flush-prepare", error))
        finally:
            if worker._active_turn is not None:
                await worker._active_turn._close_and_join()
            await worker._join_blocking()
            state = capture.state
            try:
                if admitted:
                    index_status = await worker._settle_memory(state, turn_id, capture.receipts, failures,
                                                               index_scope="memory")
            finally:
                worker._active_turn = None
                admission.active = False
                _active_owners.reset(owner_token)
                _current_lanes.reset(lane_token)
                release()
        outcome = HostTurnOutcome(turn_id, state, (), (), tuple(capture.receipts), False,
            _memory_wrote(capture.receipts, capture.flush), index_status, tuple(failures), capture.flush,
            cancelled=(job.cancel_requested.is_set() or bool(capture.flush and capture.flush.cancelled)
                       or any(item.error_type == "CancelledError" for item in failures)),
            memory_publication=_memory_publication(capture.receipts, capture.flush))
        worker.last_outcome, worker.session = outcome, state
        return outcome

    def _reserve_foreground(self):
        if any(item.active and item.key == self._lane_key for item in _current_lanes.get()):
            raise RuntimeError("A model callback cannot reenter its own session turn")
        return reserve_foreground(self._lane_key)

    @classmethod
    def open(cls, workspace_dir: str | Path, *, catalog: MemorySessionCatalog, session: SessionState,
             config: MemoryConfig | None = None, extra_tools: Sequence[TurnTool] = (),
             artifact_provenance: MemoryArtifactProvenanceStore | None = None, **kit_options: Any) -> ManagedHostSessionRunner:
        """Reject the inherited eager factory before it creates any files."""
        raise TypeError("Use ManagedHostSession.open(...).runner(session); managed runners require a shared owner")

    def _refresh_index(self, allow_deferred: bool = False) -> bool:
        return self.kit.memory._refresh_index(sources=("memory",), defer_cold=allow_deferred)

    def _publication_index_status(self, published: bool) -> Literal["ready", "pending"]:
        return "ready" if published and self.owner.publication_status()["ready"] else "pending"

    def _index_needs_repair(self, auxiliary: Mapping[str, Any]) -> bool:
        if auxiliary.get("publicationMode") == "managed":
            return auxiliary.get("needsMemoryIndex") is True
        return auxiliary.get("needsIndex") is True

    def _decorate_index_metadata(self, auxiliary: dict[str, Any], *, needs_index: bool,
                                 scope: Literal["all", "memory", "transcript"]) -> None:
        legacy = auxiliary.get("publicationMode") != "managed"
        memory = auxiliary.get("needsIndex") is True if legacy else auxiliary.get("needsMemoryIndex") is True
        sessions = auxiliary.get("needsIndex") is True if legacy else auxiliary.get("needsSessionIndex") is True
        if scope == "memory":
            memory = needs_index
        elif scope == "transcript":
            sessions |= needs_index
        else:
            memory = (memory or self.owner.store.index_identity()["status"] != "valid") if needs_index else False
            sessions = not self.owner._session_current(self.session.session_key, self.session.session_id)
        if not self.owner._sessions_enabled:
            sessions = False
        auxiliary.update(publicationMode="managed", needsMemoryIndex=memory,
                         needsSessionIndex=sessions, needsIndex=memory or sessions)

    def _persist(self, *args: Any, **kwargs: Any) -> None:
        with self.owner._condition:
            super()._persist(*args, **kwargs)

    def _admit_owner(self) -> Token[tuple[object, ...]]:
        with self.owner._condition:
            self.owner._ensure_open()
            if self.owner._control_active:
                raise RuntimeError("Managed host publication is active")
            self.owner._active_turns += 1
        return _active_owners.set((*_active_owners.get(), self.owner))

    def _release_owner(self, token: Token[tuple[object, ...]]) -> None:
        _active_owners.reset(token)
        with self.owner._condition:
            self.owner._active_turns -= 1
            self.owner._condition.notify_all()

    async def acknowledge_memory_publication(self, *, expected_turn_id: str) -> None:
        token = self._admit_owner()
        reservation = None
        try:
            if not isinstance(expected_turn_id, str) or not expected_turn_id:
                raise ValueError("expected_turn_id must be a nonempty string")
            reservation = self._reserve_foreground()
            await reservation.join_predecessors()
            await super().acknowledge_memory_publication(expected_turn_id=expected_turn_id)
        finally:
            if reservation is not None:
                reservation.release()
            self._release_owner(token)

    async def run_turn(self, user_message: str | Mapping[str, Any], *,
                       execute: Callable[[HostTurn], Awaitable[HostModelResult | None]],
                       execute_flush: Callable[[HostTurn], Awaitable[HostModelResult | None]] | None = None,
                       request_id: str | None = None, sender_is_owner: bool | None = True,
                       context_window_tokens: int | None = None,
                       deliver: Callable[[ManagedHostTurnOutcome], Awaitable[None]] | None = None) -> ManagedHostTurnOutcome:
        token = self._admit_owner()
        reservation = None
        stages: list[dict[str, Any]] = []
        stage_token = _optional_stages.set(stages)
        delivery_token = _delivery_callback.set(deliver)
        try:
            if not callable(execute) or execute_flush is not None and not callable(execute_flush):
                raise TypeError("Host execution callbacks must be callable")
            if deliver is not None and not callable(deliver):
                raise TypeError("Host delivery callback must be callable")
            if request_id is not None and (not isinstance(request_id, str) or not request_id):
                raise ValueError("request_id must be a nonempty string")
            reservation = self._reserve_foreground()
            await reservation.join_predecessors()
            outcome = await super().run_turn(user_message, execute=execute, execute_flush=execute_flush,
                request_id=request_id, sender_is_owner=sender_is_owner, context_window_tokens=context_window_tokens)
            return outcome
        finally:
            if self._cancel_requested.is_set():
                for specification in stages:
                    specification["delivery_ok"] = False
            _delivery_callback.reset(delivery_token)
            _optional_stages.reset(stage_token)
            if reservation is not None:
                reservation.release()
            self._release_owner(token)
