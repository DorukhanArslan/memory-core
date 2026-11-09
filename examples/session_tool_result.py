"""A model-free host example of dispatched tool output and guarded persistence.

The host supplies its actual registered tool and the tool call it received.
No model/provider is called. The same dispatcher, trust, settlement and catalog
owners can be composed around an application's provider loop.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from memory_core.model_tool_result import sanitize_tool_result
from memory_core.redact import LoggingConfig
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_context import convert_to_llm
from memory_core.tool_result_persistence import settle_session_tool_result
from memory_core.turn_tool_dispatch import TurnTool, TurnToolDispatcher
from memory_core.turn_trust import TurnTrust, build_tool_execution_error_result, build_tool_result_message


def _ensure_session(catalog: MemorySessionCatalog, session_key: str, session_id: str, now_ms: int) -> None:
    entry = catalog.get_session_entry(session_key)
    if entry is None:
        catalog.upsert_session(session_key, {"sessionId": session_id, "updatedAt": now_ms})
    elif entry.get("sessionId") != session_id:
        raise ValueError("The active session key belongs to a different session")


def dispatch_and_persist(
    workspace: Path, registration: TurnTool, call: Mapping[str, Any], *,
    session_id: str, session_key: str, turn_id: str, now_ms: int,
    logging_config: LoggingConfig | None = None,
    trust: TurnTrust | None = None, sender_is_owner: bool | None = None,
    on_event=None,
) -> dict[str, Any]:
    """Execute a real host registration, then retain its full guarded records."""
    if call.get("name") != registration.name:
        raise ValueError("The call must select the actual trusted host registration")
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    catalog = MemorySessionCatalog(workspace / "session-catalog.sqlite", clock_ms=lambda: now_ms)
    _ensure_session(catalog, session_key, session_id, now_ms)
    if trust is None:
        trust = TurnTrust(turn_id, sender_is_owner=sender_is_owner)
    elif trust.turn_id != turn_id:
        raise ValueError("The existing trust owner belongs to a different turn")
    outcomes, stages = [], []
    dispatcher = TurnToolDispatcher(trust, [registration], on_outcome=outcomes.append)
    try:
        result = dispatcher.dispatch(registration.name, call["arguments"], tool_call_id=call["id"])
        failed = False
    except Exception as error:
        result, failed = build_tool_execution_error_result(error), True
    # Telemetry observes the same genuine execution result without replacing
    # the live AgentSession message's diagnostic details policy.
    telemetry = sanitize_tool_result(result, logging_config=logging_config)
    message = build_tool_result_message(call, result, is_error=failed, timestamp_ms=now_ms,
                                        result_content_source=registration.result_content_source)
    settled = settle_session_tool_result(
        catalog, session_id, message, session_key=session_key,
        event_id=f"{turn_id}:result:{call['id']}", now_ms=now_ms, cwd="/fixture/work",
        logging_config=logging_config,
        on_event=on_event,
        on_stage=lambda stage, value: stages.append({"stage": stage, "message": deepcopy(value)}),
    )
    return {"liveMessage": settled.live_message, "appendResult": settled.append_result,
            "toolOutcomes": outcomes, "telemetry": telemetry, "stages": stages, "trust": trust.to_json(),
            "catalogPath": str(catalog.path)}


class HostToolSession:
    """Small host example around actual SDK owners, without a provider loop.

    The application supplies actual user/assistant messages and registered tool
    calls. Live context retains the live result; a reopened process obtains the
    committed result through the catalog's actual continuation reader.
    """

    def __init__(self, workspace: Path, *, session_id: str, session_key: str,
                 logging_config: LoggingConfig | None = None, now_ms: int) -> None:
        self.workspace, self.session_id, self.session_key = Path(workspace), session_id, session_key
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.logging_config = logging_config
        self.catalog = MemorySessionCatalog(self.workspace / "session-catalog.sqlite", clock_ms=lambda: now_ms)
        _ensure_session(self.catalog, session_key, session_id, now_ms)
        continuation = self.catalog.read_continuation(session_id, session_key=session_key)
        self.live_messages = deepcopy(continuation["context"]["messages"] if continuation else [])
        self.trust = None

    def begin_turn(self, turn_id: str, *, sender_is_owner: bool | None = None) -> None:
        if self.trust is not None and self.trust.turn_id == turn_id:
            if self.trust.sender_is_owner != sender_is_owner:
                raise ValueError("An existing turn retains its trusted sender identity")
            return
        self.trust = TurnTrust(turn_id, sender_is_owner=sender_is_owner)

    def append_message(self, message: Mapping[str, Any], *, now_ms: int) -> dict[str, Any]:
        live = dict(message)
        if self.trust is not None and live.get("role") == "assistant":
            live = self.trust.stamp_assistant(live)
        appended = self.catalog.append_message(self.session_id, live, session_key=self.session_key,
            now_ms=now_ms, cwd="/fixture/work", logging_config=self.logging_config)
        self.live_messages.append(live)
        return appended["message"]

    def dispatch(self, registration: TurnTool, call: Mapping[str, Any], *, now_ms: int, on_event=None) -> dict[str, Any]:
        if self.trust is None:
            raise ValueError("Begin the owning turn before dispatching a tool")
        result = dispatch_and_persist(self.workspace, registration, call,
            session_id=self.session_id, session_key=self.session_key,
            turn_id=self.trust.turn_id, now_ms=now_ms, logging_config=self.logging_config,
            trust=self.trust, on_event=on_event)
        self.live_messages.append(result["liveMessage"])
        return result

    def model_messages(self) -> list[dict[str, Any]]:
        return convert_to_llm(self.live_messages)

    def continuation(self) -> dict[str, Any] | None:
        return self.catalog.read_continuation(self.session_id, session_key=self.session_key)
