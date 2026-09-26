"""The Lab's host tool loop: memory_search, memory_get and the curation tools.

A real host loop (critique high #1): the model gets the upstream
``memory_search``/``memory_get`` definitions (``memory_core.tools``) and
``MemoryCurator.tool_definitions()``; the Lab dispatches each call through the
package's ``execute_*`` adapters or ``MemoryCurator.dispatch``, sends the
result payload back verbatim, and records every curated write with a
before/after snapshot so it can be reverted (only while the file is
unchanged). Refused writes are recorded too. The loop is bounded: after
``MAX_TOOL_ROUNDS`` rounds with tool calls, one last round runs without tools.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from demo.chat_engine import ChatEngine
from demo.lab_events import unified_diff
from demo.lab_runtime import LAB_TIMEZONE, LabRuntime, LabSession, safe_exception_message
from memory_core.config import MemoryConfig
from memory_core.consolidation import record_short_term_recalls, undecorate_search_results
from memory_core.curation import (
    ADD_MEMORY_ENTRY,
    APPEND_DAILY_NOTE,
    CURATION_OPERATIONS,
    MEMORY_ENTRY_OPERATIONS,
    REMOVE_MEMORY_ENTRY,
    REPLACE_MEMORY_ENTRY,
    SET_PROACTIVE_PREFERENCES,
    UPSERT_USER_DIRECTIVE,
    CurationPolicy,
    CurationUnavailableError,
    MemoryCurator,
)
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.tools.common import MemoryToolInputError
from memory_core.tools.memory_get import (
    MEMORY_GET_TOOL_NAME,
    execute_memory_get_tool,
    memory_get_tool_definition,
)
from memory_core.tools.memory_search import (
    MEMORY_SEARCH_TOOL_NAME,
    execute_memory_search_tool,
    memory_search_tool_definition,
)

MAX_TOOL_ROUNDS = 6
CURATION_FLAG = "curated_memory_writes"
_WRITE_KIND = {
    ADD_MEMORY_ENTRY: "memory_entry",
    REPLACE_MEMORY_ENTRY: "memory_entry",
    REMOVE_MEMORY_ENTRY: "memory_entry",
    UPSERT_USER_DIRECTIVE: "user_directive",
    APPEND_DAILY_NOTE: "daily_note",
    SET_PROACTIVE_PREFERENCES: "proactive_preferences",
}
# Lab flag -> the curation operations it gates (per-target policy, D5).
_TARGET_FLAGS = {
    "curation.memory_md": MEMORY_ENTRY_OPERATIONS,
    "curation.user_md": (UPSERT_USER_DIRECTIVE,),
    "curation.daily_note": (APPEND_DAILY_NOTE,),
    "curation.proactive_preferences": (SET_PROACTIVE_PREFERENCES,),
}


def curation_policy(lab: LabRuntime) -> CurationPolicy:
    policy = CurationPolicy.for_layout(
        lab.layout,
        max_file_chars=lab.settings.max_chars,
        total_max_chars=lab.settings.total_max_chars,
    )
    disabled = [
        operation
        for flag, operations in _TARGET_FLAGS.items()
        if not lab.settings.flags.get(flag, True)
        for operation in operations
    ]
    return policy.without(*disabled) if disabled else policy


def lab_curator(lab: LabRuntime, *, after_write: Callable[[Any], None] | None = None) -> MemoryCurator:
    return MemoryCurator(
        lab.root,
        layout=lab.layout,
        policy=curation_policy(lab),
        flags=FeatureFlags(curated_memory_writes=lab.settings.flags.get(CURATION_FLAG, True)),
        after_write=after_write,
        timezone=LAB_TIMEZONE,
    )


def openai_tools(definitions: list[dict]) -> list[dict]:
    return [{"type": "function", "function": definition} for definition in definitions]


@dataclass
class LabToolbox:
    """Tools offered to one turn and the dispatch of their calls."""

    lab: LabRuntime
    config: MemoryConfig
    store: SQLiteMemoryStore
    session: LabSession
    turn_id: int
    memory_tools: bool = True
    curation_tools: bool = True
    curated: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.curator = lab_curator(self.lab, after_write=self._after_write)

    def _after_write(self, result: Any) -> None:
        del result
        self.lab.reindex(self.store, turn_id=self.turn_id)

    def definitions(self) -> list[dict]:
        definitions: list[dict] = []
        if self.memory_tools:
            definitions.extend([memory_search_tool_definition(), memory_get_tool_definition()])
        if self.curation_tools:
            definitions.extend(self.curator.tool_definitions())
        return definitions

    def names(self) -> set[str]:
        return {definition["name"] for definition in self.definitions()}

    def dispatch(self, call_id: str, name: str, raw_arguments: str) -> dict[str, Any]:
        """Run one tool call; returns the call record with the payload sent to the model."""
        started = time.perf_counter()
        record: dict[str, Any] = {"id": call_id, "name": name, "arguments": raw_arguments}
        try:
            arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
        except json.JSONDecodeError as exc:
            arguments = None
            result = {"status": "error", "tool": name, "error": f"invalid JSON arguments: {exc.msg}"}
        if arguments is not None:
            record["arguments"] = arguments
            if not isinstance(arguments, dict):
                result = {"status": "error", "tool": name, "error": "arguments must be a JSON object"}
            elif name not in self.names():
                result = {"status": "error", "tool": name, "error": f"tool {name} is not available"}
            elif name == MEMORY_SEARCH_TOOL_NAME:
                result = self._memory_search(arguments)
            elif name == MEMORY_GET_TOOL_NAME:
                result = self._memory_get(arguments)
            elif name in CURATION_OPERATIONS:
                result = self._curate(name, arguments, record)
            else:
                result = {"status": "error", "tool": name, "error": f"unknown tool: {name}"}
        record["result"] = result
        record["ok"] = not (isinstance(result, dict) and result.get("status") == "error")
        record["ms"] = int((time.perf_counter() - started) * 1000)
        self.calls.append(record)
        return record

    def _memory_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            result = execute_memory_search_tool(
                self.config, self.store, arguments, agent_session_key=self.session.key
            )
        except MemoryToolInputError as error:
            return error.to_tool_error(MEMORY_SEARCH_TOOL_NAME)
        if result.get("unavailable"):
            self.lab.bus.emit(
                "search.unavailable",
                summary=f"memory_search kullanılamıyor: {result.get('error')}",
                data={"error": result.get("error"), "warning": result.get("warning"),
                      "action": result.get("action"), "via": "tool"},
                turn_id=self.turn_id,
            )
            return result
        hits = result.get("results") or []
        if hits:
            with self.lab.tracked("recall", turn_id=self.turn_id):
                # tools.ts queueShortTermRecallTracking records the raw hits (dreaming on).
                record_short_term_recalls(
                    config=self.config,
                    query=str(arguments.get("query", "")),
                    results=undecorate_search_results([hit for hit in hits if hit.get("corpus") == "memory"]),
                    now_ms=self.lab.now_ms(),
                )
        self.lab.bus.emit(
            "search.completed",
            summary=f"memory_search (model): {len(hits)} sonuç",
            data={"query": arguments.get("query"), "hits": len(hits), "via": "tool"},
            turn_id=self.turn_id,
        )
        return result

    def _memory_get(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return execute_memory_get_tool(self.config, arguments)
        except MemoryToolInputError as error:
            return error.to_tool_error(MEMORY_GET_TOOL_NAME)

    def _target(self, name: str) -> str:
        if name in MEMORY_ENTRY_OPERATIONS:
            return self.lab.layout.memory_file
        if name == UPSERT_USER_DIRECTIVE:
            return "USER.md"
        if name == SET_PROACTIVE_PREFERENCES:
            return "PROACTIVE_PREFERENCES.md"
        return f"memory/{self.curator.today()}.md"

    def _curate(self, name: str, arguments: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
        target = self._target(name)
        path = self.lab.root / target
        before = path.read_text(encoding="utf-8") if path.is_file() else None
        base = {
            "ts": self.lab.now_ms(),
            "turnId": self.turn_id,
            "sessionKind": self.session.kind,
            "operation": name,
            "kind": _WRITE_KIND[name],
            "flag": CURATION_FLAG,
            "extension": True,
        }
        try:
            with self.lab.tracked("curation", turn_id=self.turn_id):
                result = self.curator.dispatch(name, arguments)
        except MemoryToolInputError as error:
            payload = error.to_tool_error(name)
            refused = {**base, "id": self.lab.allocate_write_id(), "path": target, "refused": True,
                       "reason": str(error), "diff": ""}
            self.lab.curated_writes.append(refused)
            self.curated.append(refused)
            record["curation"] = refused
            self.lab.bus.emit(
                "curation.refused",
                summary=f"{target} reddedildi: {error}",
                data={"path": target, "operation": name, "reason": str(error), "writeId": refused["id"]},
                turn_id=self.turn_id,
            )
            return payload
        except CurationUnavailableError as error:
            return {"status": "error", "tool": name, "error": str(error)}
        written_path = str(result.get("path") or target)
        target_file = self.lab.root / written_path
        after = target_file.read_text(encoding="utf-8") if target_file.is_file() else None
        if after == before:
            return result
        write = {
            **base,
            "id": self.lab.allocate_write_id(),
            "path": written_path,
            "action": result.get("action"),
            "diff": unified_diff(before, after, written_path),
            "before": before,
            "afterSha256": hashlib.sha256(after.encode("utf-8")).hexdigest() if after is not None else None,
            "refused": False,
        }
        self.lab.curated_writes.append(write)
        self.curated.append(write)
        record["curation"] = {key: value for key, value in write.items() if key != "before"}
        self.lab.bus.emit(
            "curation.written",
            summary=f"{written_path} {result.get('action')} ({name})",
            data={"path": written_path, "operation": name, "action": result.get("action"),
                  "kind": write["kind"], "writeId": write["id"], "flag": CURATION_FLAG},
            turn_id=self.turn_id,
        )
        return result


def public_write(write: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in write.items() if key != "before"}


@dataclass
class ToolLoopOutcome:
    text: str = ""
    rounds: int = 0
    capped: bool = False
    usage: dict[str, Any] | None = None
    usage_total: dict[str, int] = field(default_factory=lambda: {"promptTokens": 0, "completionTokens": 0})
    messages: list[dict[str, Any]] = field(default_factory=list)


def run_tool_loop(
    engine: ChatEngine,
    messages: list[dict[str, Any]],
    toolbox: LabToolbox | None,
    outcome: ToolLoopOutcome,
    *,
    max_rounds: int = MAX_TOOL_ROUNDS,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Stream model rounds and dispatch tool calls; yields ``(event, payload)`` pairs.

    Events: ``assistant_delta {text, round}``, ``tool_call {id, name, arguments, round}``,
    ``tool_result {id, name, ok, result, ms, curation?}``. ``outcome`` holds the final
    text, the last round's usage (the next turn's flush counter) and the message list.
    """
    conversation = list(messages)
    definitions = toolbox.definitions() if toolbox is not None else []
    tools = openai_tools(definitions) if definitions else None
    text_parts: list[str] = []
    for round_index in range(max_rounds + 1):
        final_round = round_index == max_rounds
        outcome.rounds = round_index + 1
        message: dict[str, Any] | None = None
        for event in engine.stream_chat(conversation, tools=None if final_round else tools):
            if event["type"] == "delta":
                text_parts.append(event["text"])
                yield "assistant_delta", {"text": event["text"], "round": round_index + 1}
            elif event["type"] == "message":
                message = event
        if message is None:
            raise RuntimeError("the chat engine ended without a message")
        usage = message.get("usage")
        if usage:
            outcome.usage = usage
            for key in ("promptTokens", "completionTokens"):
                if isinstance(usage.get(key), int):
                    outcome.usage_total[key] += usage[key]
        calls = message.get("toolCalls") or []
        if not calls or toolbox is None:
            outcome.capped = final_round
            outcome.text = "".join(text_parts)
            conversation.append({"role": "assistant", "content": message.get("content") or ""})
            outcome.messages = conversation
            return
        if final_round:
            outcome.capped = True
            break
        conversation.append(
            {
                "role": "assistant",
                "content": message.get("content") or None,
                "tool_calls": [
                    {"id": call["id"], "type": "function",
                     "function": {"name": call["name"], "arguments": call["arguments"] or "{}"}}
                    for call in calls
                ],
            }
        )
        for call in calls:
            yield "tool_call", {"id": call["id"], "name": call["name"], "arguments": _preview_arguments(call["arguments"]),
                                "round": round_index + 1}
            try:
                record = toolbox.dispatch(call["id"], call["name"], call["arguments"] or "")
            except Exception as exc:  # a tool failure goes back to the model, like upstream
                record = {"id": call["id"], "name": call["name"], "ok": False, "ms": 0,
                          "result": {"status": "error", "tool": call["name"],
                                     "error": safe_exception_message(exc)}}
                toolbox.calls.append(record)
            payload = {key: record[key] for key in ("id", "name", "ok", "result", "ms")}
            if "curation" in record:
                payload["curation"] = record["curation"]
            yield "tool_result", payload
            conversation.append(
                {"role": "tool", "tool_call_id": call["id"],
                 "content": json.dumps(record["result"], ensure_ascii=False)}
            )
    outcome.text = "".join(text_parts)
    outcome.capped = True
    outcome.messages = conversation


def _preview_arguments(raw: str) -> Any:
    try:
        return json.loads(raw) if raw and raw.strip() else {}
    except json.JSONDecodeError:
        return raw


__all__ = [
    "MAX_TOOL_ROUNDS",
    "LabToolbox",
    "ToolLoopOutcome",
    "curation_policy",
    "lab_curator",
    "public_write",
    "run_tool_loop",
]

