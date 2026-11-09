"""An SDK host's serialized conversation, persistence and publication boundary.

This is a stronger synchronous-publication host policy than the pinned native
background search refresh. It is not an assertion of native host equivalence,
cross-process writer custody, or an exactly-once provider transaction.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, replace
import json
import inspect
from pathlib import Path
import threading
from typing import Any, Literal
from uuid import uuid4

from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.curation import CURATION_OPERATIONS
from memory_core.host.flush import FlushOutcome, FlushRequest
from memory_core.host.kit import HostKit, TurnContext
from memory_core.host.session import SessionState, TurnUsage, apply_turn_usage
from memory_core.session_catalog import MemorySessionCatalog, normalize_session_agent_id
from memory_core.session_visibility import is_incognito_session_key, resolve_session_agent_id
from memory_core.tools.common import format_error_message
from memory_core.turn_tool_dispatch import TurnTool, TurnToolDispatcher
from memory_core.turn_trust import (
    TurnTrust, build_tool_execution_error_result, build_tool_result_message,
)

_STATE = "sdkHostLifecycle"
_KEEP_PUBLICATION = object()
_ENTRY_FIELDS = ("sessionId", "compactionCount", "totalTokens", "totalTokensFresh",
                 "totalTokensVersion", "memoryFlush")


@dataclass(frozen=True)
class HostTurnFailure:
    phase: str
    error_type: str
    message: str
    committed: bool = False
    publication: Literal["committed", "uncertain"] | None = None


@dataclass(frozen=True)
class HostModelResult:
    """The host model callback's terminal facts; messages are recorded as emitted."""

    usage: TurnUsage | None = None
    payloads: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class HostTurnOutcome:
    turn_id: str
    session: SessionState
    messages: tuple[dict[str, Any], ...]
    appends: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...]
    transcript_committed: bool
    memory_writes_committed: bool
    index_status: Literal["ready", "failed", "not-run"]
    failures: tuple[HostTurnFailure, ...] = ()
    flush: FlushOutcome | None = None
    cancelled: bool = False
    payloads: tuple[Mapping[str, Any], ...] = ()
    memory_publication: Literal["none", "committed", "uncertain"] = "none"

    @property
    def ready(self) -> bool:
        return (self.index_status == "ready" and not self.failures and not self.cancelled
                and self.memory_publication != "uncertain")


@dataclass
class _Lane:
    loop: asyncio.AbstractEventLoop
    lock: asyncio.Lock
    reservations: int = 0


@dataclass
class _RunCapture:
    state: SessionState
    appends: list[dict[str, Any]]
    receipts: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    accepted: bool = False
    flush: FlushOutcome | None = None
    payloads: tuple[Mapping[str, Any], ...] = ()
    memory_publication: Literal["none", "committed", "uncertain"] = "none"


@dataclass
class _DispatchReservation:
    call: dict[str, Any]
    receipt: dict[str, Any]
    started: bool = False
    rejected: bool = False
    released: bool = False


_lanes: dict[tuple[str, str, str], _Lane] = {}
_lanes_guard = threading.Lock()


@dataclass
class _Admission:
    key: tuple[str, str, str]
    active: bool = True


_current_lanes: ContextVar[tuple[_Admission, ...]] = ContextVar("host_session_lifecycle_lanes", default=())


async def _acquire_lane(key: tuple[str, str, str]) -> Callable[[], None]:
    loop = asyncio.get_running_loop()
    with _lanes_guard:
        lane = _lanes.get(key)
        if lane is not None and lane.loop is not loop:
            raise RuntimeError("This session has an active owner in another event loop")
        if lane is None:
            lane = _Lane(loop, asyncio.Lock())
            _lanes[key] = lane
        lane.reservations += 1
    try:
        await lane.lock.acquire()
    except BaseException:
        with _lanes_guard:
            lane.reservations -= 1
            if not lane.reservations:
                _lanes.pop(key, None)
        raise

    def release() -> None:
        lane.lock.release()
        with _lanes_guard:
            lane.reservations -= 1
            if not lane.reservations:
                _lanes.pop(key, None)

    return release


def _failure(phase: str, error: BaseException, *, committed: bool = False) -> HostTurnFailure:
    return HostTurnFailure(phase, type(error).__name__, format_error_message(error), committed)


def _model_result(value: HostModelResult | None) -> HostModelResult:
    if value is None:
        return HostModelResult()
    if not isinstance(value, HostModelResult):
        raise TypeError("A host model callback must return HostModelResult or None")
    if value.usage is not None and not isinstance(value.usage, TurnUsage):
        raise TypeError("Model usage must be TurnUsage or None")
    if not isinstance(value.payloads, tuple) or any(not isinstance(payload, Mapping) for payload in value.payloads):
        raise TypeError("Model payloads must be a tuple of mappings")
    return value


def _result_message_payload(result: Any) -> dict[str, Any]:
    """Adapt the SDK's mapping receipts to the ordinary agent-result owner.

    Native-shaped content/details pass unchanged. The SDK curation extension
    has a mapping receipt instead: its complete mapping becomes model-visible
    text and details. The original receipt is also retained in the outcome.
    """
    if not isinstance(result, Mapping):
        raise TypeError("Registered host tools must return a mapping receipt")
    if "content" in result:
        return dict(result)
    return {"content": [{"type": "text", "text": json.dumps(
        result, ensure_ascii=False, allow_nan=False, separators=(",", ":"))}], "details": deepcopy(dict(result))}


class HostTurn:
    """One admitted model callback's actual context, messages and tools.

    Record each assistant message before dispatching its tool calls. Both
    dispatch methods persist the actual result message. ``dispatch_async``
    reserves the synchronous source before scheduling a worker thread.
    ``dispatch`` also protects sources invoked through a host's own thread pool.
    Late calls after callback completion are refused before their source runs.
    """

    def __init__(self, runner: HostSessionRunner, turn_id: str, session: SessionState,
                 context: TurnContext | None, messages: Sequence[Mapping[str, Any]],
                 trust: TurnTrust, *, flush: FlushRequest | None = None) -> None:
        self._runner = runner
        self.turn_id = turn_id
        self.session = session
        self.context = context
        self.flush_request = flush
        self.trust = trust
        self.cancel_requested = runner._cancel_requested
        self._messages = list(deepcopy(messages))
        self._appends: list[dict[str, Any]] = []
        self._receipts: list[dict[str, Any]] = []
        self._guard = threading.RLock()
        self._open = True
        self._active = 0
        self._waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future]] = []
        self._pending: dict[str, dict[str, Any]] = {}
        self._completed_calls: set[str] = set()
        self._counter = 0
        if flush is None:
            self._publication_tools = frozenset(spec["name"] for spec in runner.kit.tools()
                if spec["name"] in CURATION_OPERATIONS)
            observer = trust.write_observer(store=runner.artifact_provenance,
                mutation_root=runner.kit.memory.workspace.root, workspace_dir=runner.kit.memory.workspace.root,
                session_id=session.session_id, session_key=session.session_key, now=runner._clock)
            tools = [TurnTool(spec["name"], lambda _id, args, name=spec["name"]:
                runner.kit.dispatch(name, args, session=session, write_provenance=observer))
                for spec in runner.kit.tools()]
            tools.extend(runner.extra_tools)
            self.tools = tuple(deepcopy(runner.kit.tools()))
        else:
            self._publication_tools = frozenset()
            tools = [TurnTool(spec["name"], lambda _id, args, name=spec["name"]: flush.dispatch(name, args))
                     for spec in flush.tools]
            self.tools = tuple(deepcopy(flush.tools))
        self._sources = {tool.name: tool.result_content_source for tool in tools}
        self._dispatcher = TurnToolDispatcher(trust, tools)

    @property
    def messages(self) -> list[dict[str, Any]]:
        with self._guard:
            return deepcopy(self._messages)

    @property
    def cancelled(self) -> bool:
        return self.cancel_requested.is_set()

    def record_message(self, message: Mapping[str, Any]) -> dict[str, Any]:
        """Persist one actual model-produced assistant record with owned trust."""
        with self._guard:
            if not self._open:
                raise RuntimeError("The host turn is closed")
            self._runner._assert_identity()
            if not isinstance(message, Mapping) or message.get("role") != "assistant":
                raise ValueError("The model callback records assistant messages only")
            if "__openclaw" in message:
                raise ValueError("Model messages cannot supply trusted turn metadata")
            value = self.trust.stamp_assistant(deepcopy(dict(message)))
            content = value.get("content")
            calls = [block for block in content if isinstance(block, Mapping) and block.get("type") == "toolCall"] \
                if isinstance(content, list) else []
            new_ids = set()
            for call in calls:
                identifier = call.get("id")
                if (not isinstance(identifier, str) or not identifier or identifier in self._pending
                        or identifier in self._completed_calls or identifier in new_ids or not isinstance(call.get("name"), str)
                        or not isinstance(call.get("arguments"), Mapping)):
                    raise ValueError("A tool call needs a unique id, name and mapping arguments")
                new_ids.add(identifier)
            saved = self._record(value)
            for call in calls:
                self._pending[call["id"]] = deepcopy(dict(call))
            return saved

    def _record(self, message: dict[str, Any]) -> dict[str, Any]:
        if self.flush_request is None:
            result = self._runner.catalog.append_message(
                self.session.session_id, message, session_key=self.session.session_key,
                event_id=f"{self.turn_id}:message:{self._counter}", now_ms=self._runner._clock(),
                cwd=str(self._runner.kit.memory.workspace.root))
            self._counter += 1
            self._appends.append(deepcopy(result))
            saved = result["message"]
        else:
            # A flush is private maintenance context, never a user transcript append.
            saved = deepcopy(message)
        self._messages.append(deepcopy(saved))
        return deepcopy(saved)

    def _reserve(self, tool_call_id: str, name: str, arguments: Mapping[str, Any]) -> _DispatchReservation:
        with self._guard:
            if not self._open:
                raise RuntimeError("The host turn is closed")
            if _memory_publication(self._receipts, None) == "uncertain":
                raise RuntimeError("A memory publication is uncertain; acknowledge the current files before another tool dispatch")
            call = self._pending.get(tool_call_id)
            if call is None or call["name"] != name or dict(call["arguments"]) != dict(arguments):
                raise ValueError("Dispatch must match a recorded assistant tool call")
            del self._pending[tool_call_id]
            self._completed_calls.add(tool_call_id)
            self._active += 1
            receipt = {"turnId": self.turn_id, "toolCallId": call["id"], "name": call["name"],
                       "arguments": deepcopy(call["arguments"]), "sourceExecuted": False,
                       "maintenance": self.flush_request is not None,
                       "memoryPublicationOwner": call["name"] in self._publication_tools}
            self._receipts.append(receipt)
            return _DispatchReservation(call, receipt)

    def _release_dispatch(self, reservation: _DispatchReservation) -> None:
        with self._guard:
            if reservation.released:
                return
            reservation.released = True
            self._active -= 1
            if self._active == 0:
                for loop, future in self._waiters:
                    loop.call_soon_threadsafe(_resolve, future)
                self._waiters.clear()

    def _reject_submission(self, reservation: _DispatchReservation, error: BaseException) -> None:
        with self._guard:
            reservation.receipt["schedulingError"] = {
                "type": type(error).__name__, "message": str(error), "attributes": deepcopy(vars(error))}
            if reservation.started or reservation.released:
                # A submit implementation may fail after starting a worker.
                # That physical source retains custody and releases itself.
                return
            reservation.rejected = True
            try:
                message = build_tool_result_message(reservation.call, build_tool_execution_error_result(error),
                    is_error=True, timestamp_ms=self._runner._clock())
                self._record(message)
            finally:
                self._release_dispatch(reservation)

    def _dispatch_reserved(self, reservation: _DispatchReservation) -> Any:
        with self._guard:
            if reservation.rejected:
                # A queued work item from an unsuccessful submit cannot later
                # become an unowned write after the admission has settled.
                return None
            reservation.started = True
        call, receipt = reservation.call, reservation.receipt
        caught = None
        try:
            try:
                self._runner._assert_identity()
                receipt["sourceExecuted"] = call["name"] in self._sources
                result = self._dispatcher.dispatch(call["name"], call["arguments"], tool_call_id=call["id"])
                receipt["result"] = deepcopy(result)
                payload = _result_message_payload(result)
                failed = result.get("isError") is True or result.get("status") == "error"
            except Exception as error:
                caught = error
                receipt["error"] = {"type": type(error).__name__, "message": str(error),
                                    "attributes": deepcopy(vars(error))}
                payload = build_tool_execution_error_result(error)
                failed = True
                result = None
            message = build_tool_result_message(call, payload, is_error=failed,
                timestamp_ms=self._runner._clock(), result_content_source=self._sources.get(call["name"]))
            with self._guard:
                self._record(message)
            if caught is not None:
                raise caught
            return result
        finally:
            self._release_dispatch(reservation)

    def dispatch(self, tool_call_id: str, name: str, arguments: Mapping[str, Any]) -> Any:
        return self._dispatch_reserved(self._reserve(tool_call_id, name, arguments))

    async def dispatch_async(self, tool_call_id: str, name: str, arguments: Mapping[str, Any]) -> Any:
        reservation = self._reserve(tool_call_id, name, arguments)
        try:
            operation = asyncio.get_running_loop().run_in_executor(None, self._dispatch_reserved, reservation)
        except BaseException as error:
            self._reject_submission(reservation, error)
            raise
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            operation.add_done_callback(_consume)
            raise

    async def _close_and_join(self) -> None:
        loop = asyncio.get_running_loop()
        with self._guard:
            self._open = False
            if not self._active:
                return
            settled = loop.create_future()
            self._waiters.append((loop, settled))
        await asyncio.shield(settled)


def _resolve(future: asyncio.Future) -> None:
    if not future.done():
        future.set_result(None)


def _consume(future: asyncio.Future) -> None:
    if not future.cancelled():
        future.exception()


class HostSessionRunner:
    """One reusable host session with durable context and a publication barrier.

    Different runner instances for the same catalog/agent/key share a process
    lane. Active use across event loops fails closed; multiple processes and
    arbitrary filesystem writes outside the provided dispatcher are not fenced.
    """

    def __init__(self, kit: HostKit, catalog: MemorySessionCatalog, *, session: SessionState,
                 extra_tools: Sequence[TurnTool] = ()) -> None:
        if not isinstance(kit, HostKit) or not isinstance(catalog, MemorySessionCatalog):
            raise TypeError("A runner requires HostKit and MemorySessionCatalog")
        if not isinstance(session, SessionState) or not session.session_key or not session.session_id:
            raise ValueError("A runner requires an explicit nonempty SessionState identity")
        if is_incognito_session_key(session.session_key):
            raise ValueError("Incognito host lifecycle writes are unsupported; use the volatile catalog APIs directly")
        if catalog.agent_id != normalize_session_agent_id(kit.memory.config.agent_id):
            raise ValueError("HostKit and session catalog belong to different agents")
        ledger = kit.memory.store.artifact_provenance
        if ledger is None:
            raise ValueError("Construct HostKit with artifact_provenance, or use HostSessionRunner.open")
        if kit.memory.workspace.session_catalog is not catalog:
            raise ValueError("HostKit must use this exact session catalog for indexing")
        self.kit, self.catalog, self.artifact_provenance = kit, catalog, ledger
        # Reuse the catalog's actual canonical-key owner; do not duplicate its
        # provider-owned identity normalization rules in a host adapter.
        key = catalog._session_key(session.session_key)
        if not key:
            raise ValueError("The canonical session key must be nonempty")
        if key.startswith("agent:") and resolve_session_agent_id(key) != catalog.agent_id:
            raise ValueError("The session key belongs to another catalog agent")
        if Path(kit.memory.config.workspace_dir).resolve() != kit.memory.workspace.root.resolve():
            raise ValueError("HostKit config and workspace must describe the same owner")
        self.session = replace(session, session_key=key)
        self.extra_tools = tuple(extra_tools)
        if any(not isinstance(tool, TurnTool) for tool in self.extra_tools):
            raise TypeError("Extra host tools must be trusted TurnTool registrations")
        if any(inspect.iscoroutinefunction(tool.execute) for tool in self.extra_tools):
            raise TypeError("This runner profile uses synchronous registered tools; the model callback may be async")
        names = [tool["name"] for tool in kit.tools()] + [tool.name for tool in self.extra_tools]
        if len(names) != len(set(names)):
            raise ValueError("A host tool name must select exactly one registration")
        self._lane_key = (str(catalog.path), catalog.agent_id, key)
        self.last_outcome: HostTurnOutcome | None = None
        self._active_turn: HostTurn | None = None
        self._cancel_requested = asyncio.Event()
        self._blocking_guard = threading.Lock()
        self._blocking_count = 0
        self._blocking_waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future]] = []

    @classmethod
    def open(cls, workspace_dir: str | Path, *, catalog: MemorySessionCatalog, session: SessionState,
             config: MemoryConfig | None = None, extra_tools: Sequence[TurnTool] = (),
             artifact_provenance: MemoryArtifactProvenanceStore | None = None, **kit_options) -> HostSessionRunner:
        """Create the ledger before the immutable kit; pass its normal provider options."""
        if is_incognito_session_key(session.session_key):
            raise ValueError("Incognito host lifecycle writes are unsupported; use the volatile catalog APIs directly")
        config = config or MemoryConfig(workspace_dir=Path(workspace_dir).resolve(), agent_id=catalog.agent_id)
        if normalize_session_agent_id(config.agent_id) != catalog.agent_id:
            raise ValueError("HostKit and session catalog belong to different agents")
        key = catalog._session_key(session.session_key)
        if key and key.startswith("agent:") and resolve_session_agent_id(key) != catalog.agent_id:
            raise ValueError("The session key belongs to another catalog agent")
        if Path(config.workspace_dir).resolve() != Path(workspace_dir).resolve():
            raise ValueError("HostKit config and workspace must describe the same owner")
        index = config.resolved_store_path().resolve()
        ledger = artifact_provenance or MemoryArtifactProvenanceStore(index.with_name(f"{index.stem}.provenance.sqlite"))
        kit = HostKit.open(workspace_dir, config=config, session_catalog=catalog,
                           artifact_provenance=ledger, **kit_options)
        return cls(kit, catalog, session=session, extra_tools=extra_tools)

    def _clock(self) -> int:
        return int(self.catalog.now_ms())

    async def _blocking(self, function: Callable[..., Any], *args) -> Any:
        """Keep physical source custody even if its awaiting task is cancelled."""
        with self._blocking_guard:
            self._blocking_count += 1

        def release() -> None:
            with self._blocking_guard:
                self._blocking_count -= 1
                if self._blocking_count == 0:
                    for loop, future in self._blocking_waiters:
                        loop.call_soon_threadsafe(_resolve, future)
                    self._blocking_waiters.clear()

        def run() -> Any:
            try:
                return function(*args)
            finally:
                release()

        try:
            operation = asyncio.get_running_loop().run_in_executor(None, run)
        except BaseException:
            release()
            raise
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            operation.add_done_callback(_consume)
            raise

    async def _join_blocking(self) -> None:
        loop = asyncio.get_running_loop()
        with self._blocking_guard:
            if self._blocking_count == 0:
                return
            settled = loop.create_future()
            self._blocking_waiters.append((loop, settled))
        await asyncio.shield(settled)

    async def _terminal_cancelled(self, capture: _RunCapture, turn_id: str) -> HostTurnOutcome:
        """A cancelled producer cannot release work it no longer awaits itself."""
        turn = self._active_turn
        if turn is not None:
            await turn._close_and_join()
            known_appends = {row["messageId"] for row in capture.appends}
            capture.appends.extend(deepcopy(row) for row in turn._appends if row["messageId"] not in known_appends)
            known_tools = {(row["turnId"], row["toolCallId"]) for row in capture.receipts}
            capture.receipts.extend(deepcopy(row) for row in turn._receipts
                if (row["turnId"], row["toolCallId"]) not in known_tools)
            if turn.flush_request is None:
                capture.messages = turn.messages
            elif capture.flush is None:
                capture.flush = turn.flush_request.complete(capture.state, cancelled=True)
                capture.state = capture.flush.session
        await self._join_blocking()
        failures = [HostTurnFailure("producer", "CancelledError", "The admitted producer was cancelled", capture.accepted)]
        if capture.accepted:
            try:
                self._persist(capture.state, needs_index=True, turn_id=turn_id,
                    pending_memory_publication=_pending_publication(capture.receipts, turn_id, self.kit))
            except Exception as error:
                failures.append(_failure("cancel-finalization", error, committed=True))
        return HostTurnOutcome(turn_id, capture.state, tuple(capture.messages), tuple(capture.appends),
            tuple(capture.receipts), capture.accepted, _memory_wrote(capture.receipts, capture.flush),
            "failed" if capture.accepted else "not-run", tuple(failures), capture.flush,
            cancelled=True, payloads=tuple(deepcopy(capture.payloads)),
            memory_publication=_memory_publication(capture.receipts, capture.flush,
                                                   inherited=capture.memory_publication))

    def _assert_identity(self) -> None:
        current = self.catalog.get_session_entry(self.session.session_key)
        if current is None or current.get("sessionId") != self.session.session_id:
            raise RuntimeError("The current session incarnation changed; reopen the runner")

    def _assert_maintenance_current(self) -> None:
        self._assert_identity()
        if self._cancel_requested.is_set():
            raise asyncio.CancelledError("Host maintenance was cancelled")

    def _assert_publication_owner(self, pending: Mapping[str, Any]) -> None:
        if (pending["workspace"] != str(self.kit.memory.workspace.root.resolve())
                or pending["indexPath"] != str(self.kit.memory.store.path.resolve())
                or pending["provenancePath"] != str(self.artifact_provenance.path.resolve())):
            raise RuntimeError("The pending memory publication belongs to a different workspace, index or provenance store")

    def _load(self) -> tuple[SessionState, dict[str, Any], bool]:
        current = self.catalog.get_session_entry(self.session.session_key)
        if current is None:
            entry = deepcopy(dict(self.session.entry))
            entry["sessionId"] = self.session.session_id
            self.catalog.upsert_session(self.session.session_key, entry)
            current = self.catalog.get_session_entry(self.session.session_key)
        if current.get("sessionId") != self.session.session_id:
            raise RuntimeError("The current session incarnation changed; reopen the runner")
        if current.get("incognito") is True:
            raise ValueError("Incognito host lifecycle writes are unsupported")
        continuation = self.catalog.read_continuation(self.session.session_id, session_key=self.session.session_key)
        if continuation is None:
            raise RuntimeError("The registered conversation has no continuation snapshot")
        entry = continuation["instanceEntry"]
        auxiliary = entry.get(_STATE, {})
        if (not isinstance(auxiliary, Mapping) or type(auxiliary.get("version", 1)) is not int
                or auxiliary.get("version", 1) != 1):
            raise ValueError("The stored host lifecycle state is invalid")
        state = SessionState.from_json({"sessionKey": self.session.session_key, "sessionId": self.session.session_id,
            "entry": entry, "kind": auxiliary.get("kind", self.session.kind),
            "lastOutputTokens": auxiliary.get("lastOutputTokens", self.session.last_output_tokens),
            "seenTruncationSignatures": auxiliary.get("seenTruncationSignatures", list(self.session.seen_truncation_signatures)),
            "completedBootstrapTurn": auxiliary.get("completedBootstrapTurn", self.session.completed_bootstrap_turn)})
        return state, continuation, auxiliary.get("needsIndex") is True

    def _persist(self, state: SessionState, *, needs_index: bool, turn_id: str,
                 pending_memory_publication: object = _KEEP_PUBLICATION,
                 expected_pending_turn_id: str | None = None,
                 acknowledgment: Mapping[str, Any] | None = None) -> None:
        current = self.catalog.get_session_entry(state.session_key)
        if current is None or current.get("sessionId") != state.session_id:
            raise RuntimeError("The current session incarnation changed during this turn")
        continuation = self.catalog.read_continuation(state.session_id, session_key=state.session_key)
        if continuation is None:
            raise RuntimeError("The current transcript disappeared during this turn")
        entry = deepcopy(continuation["instanceEntry"])
        auxiliary = deepcopy(dict(entry.get(_STATE, {})))
        if expected_pending_turn_id is not None:
            pending = _stored_pending_publication(entry)
            if pending is None or pending["turnId"] != expected_pending_turn_id:
                raise RuntimeError("The pending memory publication changed; acknowledge its current turn id")
            self._assert_publication_owner(pending)
        for key in _ENTRY_FIELDS:
            if key in state.entry:
                entry[key] = deepcopy(state.entry[key])
            else:
                entry.pop(key, None)
        auxiliary.update({"version": 1, "kind": state.kind, "lastOutputTokens": state.last_output_tokens,
            "seenTruncationSignatures": list(state.seen_truncation_signatures),
            "completedBootstrapTurn": state.completed_bootstrap_turn, "needsIndex": needs_index, "lastTurnId": turn_id})
        if pending_memory_publication is not _KEEP_PUBLICATION:
            if pending_memory_publication is None:
                auxiliary.pop("pendingMemoryPublication", None)
            else:
                auxiliary["pendingMemoryPublication"] = deepcopy(pending_memory_publication)
        if acknowledgment is not None:
            auxiliary["lastMemoryPublicationAcknowledgment"] = deepcopy(dict(acknowledgment))
        entry[_STATE] = auxiliary
        entry["updatedAt"] = self._clock()
        self.catalog.upsert_session(state.session_key, entry)

    async def acknowledge_memory_publication(self, *, expected_turn_id: str) -> None:
        """Accept CURRENT files, reindex them and release the matching uncertainty.

        This is the host's explicit acknowledgment after inspecting the saved
        files. It does not establish which historical write survived, replay a
        tool, or assert that requested bytes still exist. Cancellation before
        acknowledgment commits, index failure, identity rotation and a changed
        pending turn keep the marker.
        The same in-process session lane used by run_turn owns this operation.
        """
        if not isinstance(expected_turn_id, str) or not expected_turn_id:
            raise ValueError("expected_turn_id must be a nonempty string")
        ancestors = tuple(owner for owner in _current_lanes.get() if owner.active)
        if any(owner.key == self._lane_key for owner in ancestors):
            raise RuntimeError("A model callback cannot acknowledge its own active session turn")
        release = await _acquire_lane(self._lane_key)
        admission = _Admission(self._lane_key)
        token = _current_lanes.set((*ancestors, admission))
        cancelled = asyncio.Event()

        async def acknowledge() -> None:
            self._assert_identity()
            state, continuation, _ = self._load()
            pending = _stored_pending_publication(continuation["instanceEntry"])
            if pending is None or pending["turnId"] != expected_turn_id:
                raise RuntimeError("No matching pending memory publication; inspect its current turn id")
            self._assert_publication_owner(pending)
            if cancelled.is_set():
                raise asyncio.CancelledError("The memory publication acknowledgment was cancelled")
            await self._blocking(self.kit.memory.store.reindex, self.kit.memory.workspace)
            if cancelled.is_set():
                raise asyncio.CancelledError("The memory publication acknowledgment was cancelled")
            # Read the live metadata after IO, preserving independent edits.
            self._assert_identity()
            state, _, _ = self._load()
            self._persist(state, needs_index=False, turn_id=expected_turn_id,
                pending_memory_publication=None, expected_pending_turn_id=expected_turn_id,
                acknowledgment={"turnId": expected_turn_id, "acknowledgedAt": self._clock(),
                    "workspace": pending["workspace"], "indexPath": pending["indexPath"],
                    "provenancePath": pending["provenancePath"]})
            self.session = state

        producer = asyncio.create_task(acknowledge())
        cancellation = None
        try:
            while True:
                try:
                    await asyncio.shield(producer)
                    break
                except asyncio.CancelledError as error:
                    cancellation = error
                    cancelled.set()
                    if producer.done() and producer.cancelled():
                        break
            if cancellation is not None:
                raise cancellation
        finally:
            # shield keeps an accepted synchronous index source alive; never
            # release the lane while it can still publish into this workspace.
            joining = asyncio.create_task(self._join_blocking())
            while not joining.done():
                try:
                    await asyncio.shield(joining)
                except asyncio.CancelledError:
                    cancelled.set()
            joining.result()
            admission.active = False
            _current_lanes.reset(token)
            release()

    async def run_turn(self, user_message: str | Mapping[str, Any], *,
                       execute: Callable[[HostTurn], Awaitable[HostModelResult | None]],
                       execute_flush: Callable[[HostTurn], Awaitable[HostModelResult | None]] | None = None,
                       request_id: str | None = None, sender_is_owner: bool | None = True,
                       context_window_tokens: int | None = None) -> HostTurnOutcome:
        """Run the real host callback and hold admission until its accepted work settles.

        Caller cancellation remains cancellation, but is delivered only after
        the producer and all accepted dispatches settle. Inspect ``last_outcome``
        for committed effects after cancellation. A replayed request id never
        silently starts another provider turn.
        """
        if not callable(execute) or execute_flush is not None and not callable(execute_flush):
            raise TypeError("Host execution callbacks must be callable")
        if request_id is not None and (not isinstance(request_id, str) or not request_id):
            raise ValueError("request_id must be a nonempty string")
        ancestors = tuple(owner for owner in _current_lanes.get() if owner.active)
        if any(owner.key == self._lane_key for owner in ancestors):
            raise RuntimeError("A model callback cannot reenter its own session turn")
        release = await _acquire_lane(self._lane_key)
        admission = _Admission(self._lane_key)
        token = _current_lanes.set((*ancestors, admission))
        cancellation = None
        turn_id = request_id or uuid4().hex
        try:
            self._cancel_requested = asyncio.Event()
            capture = _RunCapture(self.session, [], [], [])
            producer = asyncio.create_task(self._produce(user_message, execute, execute_flush, turn_id,
                sender_is_owner, context_window_tokens, capture))
            while True:
                try:
                    outcome = await asyncio.shield(producer)
                    break
                except asyncio.CancelledError as error:
                    cancellation = error
                    self._cancel_requested.set()
                    if self._active_turn is not None:
                        self._active_turn.cancel_requested.set()
                    if producer.done() and producer.cancelled():
                        # A terminal cancelled Future never becomes awaitable
                        # success. Join its real sources under a new owner,
                        # rather than spinning on shield(done_cancelled).
                        settlement = asyncio.create_task(self._terminal_cancelled(capture, turn_id))
                        while True:
                            try:
                                outcome = await asyncio.shield(settlement)
                                break
                            except asyncio.CancelledError:
                                self._cancel_requested.set()
                                if settlement.done() and settlement.cancelled():
                                    settlement = asyncio.create_task(self._terminal_cancelled(capture, turn_id))
                        break
            if cancellation is not None:
                outcome = replace(outcome, cancelled=True)
            self.last_outcome = outcome
            self.session = outcome.session
            if cancellation is not None:
                raise cancellation
            return outcome
        finally:
            self._active_turn = None
            admission.active = False
            _current_lanes.reset(token)
            release()

    async def _produce(self, user_message, execute, execute_flush, turn_id, sender_is_owner,
                       context_window_tokens, capture: _RunCapture) -> HostTurnOutcome:
        state = self.session
        failures: list[HostTurnFailure] = []
        appends = capture.appends
        receipts = capture.receipts
        messages = capture.messages
        accepted = False
        flush_outcome = None
        index_status = "not-run"
        result = HostModelResult()
        turn = None
        phase = "admission"
        trust = TurnTrust(turn_id, sender_is_owner=sender_is_owner)
        try:
            state, continuation, needs_index = self._load()
            capture.state = state
            pending = _stored_pending_publication(continuation["instanceEntry"])
            if pending is not None:
                capture.memory_publication = "uncertain"
                phase = "publication-reconciliation"
                failures.append(HostTurnFailure(phase, "MemoryPublicationUncertain",
                    format_error_message(
                        f"Acknowledge current memory files for pending turn {pending['turnId']} before admitting another message"),
                    publication="uncertain"))
                return HostTurnOutcome(turn_id, state, (), (), (), False, False, "not-run",
                    tuple(failures), memory_publication="uncertain")
            if needs_index:
                phase = "index-repair"
                await self._blocking(self.kit.memory.store.reindex, self.kit.memory.workspace)
                self._persist(state, needs_index=False, turn_id=turn_id)
            phase = "before-turn"
            context = self.kit.before_turn(state)
            state = context.session
            capture.state = state
            user = {"role": "user", "content": user_message} if isinstance(user_message, str) else deepcopy(dict(user_message))
            if user.get("role") != "user" or "__openclaw" in user:
                raise ValueError("The host admission requires an ordinary user message")
            user.setdefault("timestamp", self._clock())
            user.setdefault("idempotencyKey", turn_id)
            saved = self.catalog.append_message(state.session_id, user, session_key=state.session_key,
                event_id=f"{turn_id}:user", now_ms=self._clock(), cwd=str(self.kit.memory.workspace.root))
            appends.append(saved)
            accepted = True
            capture.accepted = True
            if not saved["appended"]:
                raise RuntimeError("This request was already admitted; no model turn was repeated")
            self._persist(state, needs_index=True, turn_id=turn_id)
            continuation = self.catalog.read_continuation(state.session_id, session_key=state.session_key)
            model_messages = continuation["llmMessages"]
            turn = HostTurn(self, turn_id, state, context, model_messages, trust)
            self._active_turn = turn
            phase = "model"
            try:
                result = _model_result(await execute(turn))
                capture.payloads = result.payloads
            finally:
                await turn._close_and_join()
                appends.extend(turn._appends)
                receipts.extend(deepcopy(turn._receipts))
                messages = turn.messages
                capture.messages = messages
            phase = "after-turn"
            continuation = self.catalog.read_continuation(state.session_id, session_key=state.session_key)
            if _memory_publication(receipts, None) == "uncertain":
                state = apply_turn_usage(state, result.usage)
                capture.state = state
                # Optional maintenance must not add writes to an unresolved
                # publication. Settlement below records the real receipt first.
                phase = "publication-reconciliation"
                raise RuntimeError("A memory publication is uncertain; acknowledge current files before continuing")
            try:
                record = self.kit.after_turn(state, transcript=messages, usage=result.usage,
                    context_window_tokens=context_window_tokens, transcript_events=continuation["visibleEvents"],
                    untrusted_turn=lambda: trust.resolve_origin_class() == "untrusted",
                    assert_current=self._assert_maintenance_current)
            except asyncio.CancelledError:
                # The visible model finished before optional maintenance was
                # cancelled. Retain its actual usage even though no flush
                # target or request may be created by this stale owner.
                state = apply_turn_usage(state, result.usage)
                capture.state = state
                raise
            state = record.session
            capture.state = state
            if record.flush_failure is not None:
                failures.append(HostTurnFailure("flush-prepare", "MemoryFlushFailure",
                                               format_error_message(record.flush_failure.error)))
            if record.flush is not None:
                phase = "flush"
                request = record.flush
                if execute_flush is None:
                    failures.append(HostTurnFailure("flush", "MissingFlushExecutor", "A due memory flush needs execute_flush"))
                    flush_outcome = request.complete(state, cancelled=True)
                    capture.flush = flush_outcome
                else:
                    maintenance = HostTurn(self, f"{turn_id}:flush", state, None, request.messages, trust, flush=request)
                    self._active_turn = maintenance
                    flush_error = None
                    flush_result = HostModelResult()
                    try:
                        flush_result = _model_result(await execute_flush(maintenance))
                    except asyncio.CancelledError as error:
                        flush_error = error
                        failures.append(_failure("flush", error))
                    except Exception as error:
                        flush_error = error
                        failures.append(_failure("flush", error))
                    finally:
                        await maintenance._close_and_join()
                        receipts.extend(deepcopy(maintenance._receipts))
                    tool_errors = [row["result"] for row in maintenance._receipts
                        if isinstance(row.get("result"), Mapping) and (row["result"].get("isError") is True
                            or row["result"].get("status") == "error")]
                    execution_errors = [row[field]["message"] for row in maintenance._receipts
                        for field in ("error", "schedulingError") if field in row]
                    if flush_error is None and (tool_errors or execution_errors):
                        # Tool result envelopes are not final reply payloads. A
                        # failed actual maintenance write is an explicit host
                        # failure even if the model returns an ordinary reply.
                        text = [str(item.get("error") or item.get("text") or item) for item in tool_errors]
                        flush_error = RuntimeError("Memory flush tool failed: " + "; ".join([*text, *execution_errors]))
                    authority_withdrawn = isinstance(flush_error, asyncio.CancelledError)
                    if not authority_withdrawn:
                        try:
                            self._assert_maintenance_current()
                        except (asyncio.CancelledError, Exception) as error:
                            authority_withdrawn = True
                            failures.append(_failure("flush-authority", error,
                                                     committed=_memory_wrote(maintenance._receipts, None)))
                    # Withdrawn authority must not stamp success. The genuine
                    # cancelled completion still reports already appended bodies.
                    flush_outcome = request.complete(state, error=flush_error, cancelled=authority_withdrawn,
                                                     payloads=(*flush_result.payloads, *tool_errors))
                    state = flush_outcome.session
                    capture.flush = flush_outcome
                    capture.state = state
                    if flush_outcome.failure is not None:
                        failures.append(HostTurnFailure("flush", "MemoryFlushFailure",
                                                       format_error_message(flush_outcome.failure.error),
                                                       flush_outcome.wrote))
            phase = "publication"
        except asyncio.CancelledError as error:
            failures.append(_failure(phase, error, committed=accepted))
        except Exception as error:
            if phase == "publication-reconciliation" and _memory_publication(receipts, None) == "uncertain":
                failures.append(HostTurnFailure(phase, type(error).__name__, format_error_message(error),
                    _memory_wrote(receipts, None), "uncertain"))
            else:
                failures.append(_failure(phase, error, committed=accepted))
        finally:
            if turn is not None:
                await turn._close_and_join()
            if accepted:
                for receipt in receipts:
                    actual = receipt.get("result")
                    if "schedulingError" in receipt:
                        error = receipt["schedulingError"]
                        failures.append(HostTurnFailure("tool-scheduling", error["type"], format_error_message(error["message"])))
                    if "error" in receipt:
                        error = receipt["error"]
                        failures.append(HostTurnFailure("tool", error["type"], format_error_message(error["message"])))
                    elif isinstance(actual, Mapping) and (actual.get("status") == "error" or actual.get("isError") is True):
                        publication = _receipt_publication(receipt)
                        failures.append(HostTurnFailure("tool", "ToolExecutionFailure",
                            format_error_message(actual.get("error") or actual.get("text") or actual),
                            _memory_wrote([receipt], None), publication))
                index_errors = [error for row in receipts if (error := _after_write_error(row))]
                for error in index_errors:
                    failures.append(HostTurnFailure("tool-index", "IndexPublicationFailure", format_error_message(error), True))
                try:
                    self._persist(state, needs_index=True, turn_id=turn_id,
                        pending_memory_publication=_pending_publication(receipts, turn_id, self.kit))
                    if index_errors:
                        index_status = "failed"
                    else:
                        await self._blocking(self.kit.memory.store.reindex, self.kit.memory.workspace)
                        self._persist(state, needs_index=False, turn_id=turn_id)
                        index_status = "ready"
                except Exception as error:
                    index_status = "failed"
                    failures.append(_failure("publication", error, committed=True))
            elif any(failure.phase == "index-repair" for failure in failures):
                index_status = "failed"
        return HostTurnOutcome(turn_id, state, tuple(messages), tuple(deepcopy(appends)), tuple(receipts),
            accepted, _memory_wrote(receipts, flush_outcome), index_status, tuple(failures), flush_outcome,
            payloads=tuple(deepcopy(result.payloads)),
            memory_publication=_memory_publication(receipts, flush_outcome,
                                                   inherited=capture.memory_publication))


def _memory_wrote(receipts, flush_outcome: FlushOutcome | None) -> bool:
    return bool(any(_receipt_publication(row) == "committed" or isinstance(row.get("result"), Mapping) and (
                    row.get("memoryPublicationOwner") is True and row["result"].get("status") == "ok"
                    and row["result"].get("action") not in {"unchanged", "skipped"}
                    or row.get("maintenance") is True and row["name"] == "write"
                    and row["result"].get("action") == "appended"
                    and (row["result"].get("status") == "ok" or bool(row["result"].get("afterWriteError"))))
                    for row in receipts)
                or flush_outcome is not None and flush_outcome.wrote)


def _receipt_publication(receipt) -> Literal["committed", "uncertain"] | None:
    if receipt.get("memoryPublicationOwner") is not True:
        return None
    result = receipt.get("result")
    value = result.get("publication") if isinstance(result, Mapping) else None
    return value if isinstance(value, str) and value in {"committed", "uncertain"} else None


def _after_write_error(receipt):
    if (receipt.get("memoryPublicationOwner") is not True
            and not (receipt.get("maintenance") is True and receipt.get("name") == "write")):
        return None
    result = receipt.get("result")
    return result.get("afterWriteError") if isinstance(result, Mapping) else None


def _memory_publication(receipts, flush_outcome, *, inherited="none") -> Literal["none", "committed", "uncertain"]:
    if inherited == "uncertain" or any(_receipt_publication(row) == "uncertain" for row in receipts):
        return "uncertain"
    return "committed" if _memory_wrote(receipts, flush_outcome) else "none"


def _pending_publication(receipts, turn_id, kit):
    return ({"turnId": turn_id, "publication": "uncertain",
             "workspace": str(kit.memory.workspace.root.resolve()),
             "indexPath": str(kit.memory.store.path.resolve()),
             "provenancePath": str(kit.memory.store.artifact_provenance.path.resolve())}
            if _memory_publication(receipts, None) == "uncertain" else _KEEP_PUBLICATION)


def _stored_pending_publication(entry):
    auxiliary = entry.get(_STATE, {})
    pending = auxiliary.get("pendingMemoryPublication")
    if pending is None:
        return None
    if (not isinstance(pending, Mapping)
            or set(pending) != {"turnId", "publication", "workspace", "indexPath", "provenancePath"}
            or not isinstance(pending["turnId"], str) or not pending["turnId"]
            or any(not isinstance(pending[name], str) or not Path(pending[name]).is_absolute()
                   for name in ("workspace", "indexPath", "provenancePath"))
            or pending["publication"] != "uncertain"):
        raise ValueError("The stored memory publication uncertainty is invalid")
    return pending
