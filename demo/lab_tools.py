"""The Lab's host tool loop over the host kit's tools.

A real host loop (critique high #1): the model gets ``HostKit.tools()`` (the
upstream ``memory_search``/``memory_get`` definitions and the curation tools the
Lab flags allow); every call goes through ``HostKit.dispatch`` and its payload is
sent back with sanitized diagnostics. The Lab adds what a host adds: call records, events, and a
before/after snapshot of every curated write so it can be reverted (only while the
file is unchanged); refused writes are recorded too. The loop is bounded: after
``MAX_TOOL_ROUNDS`` rounds with tool calls, one last round runs without tools.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from demo.chat_engine import ChatEngine
from demo.lab_events import unified_diff
from demo.lab_runtime import (
    CURATION_FLAG,
    LabRuntime,
    LabSession,
    redact_diagnostic_payload,
    safe_exception_message,
)
from memory_core.curation import (
    ADD_MEMORY_ENTRY,
    APPEND_DAILY_NOTE,
    CURATION_OPERATIONS,
    MEMORY_ENTRY_OPERATIONS,
    REMOVE_MEMORY_ENTRY,
    REPLACE_MEMORY_ENTRY,
    SET_PROACTIVE_PREFERENCES,
    UPSERT_USER_DIRECTIVE,
)
from memory_core.host import HostKit
from memory_core.tools.memory_search import MEMORY_SEARCH_TOOL_NAME

MAX_TOOL_ROUNDS = 6
_WRITE_KIND = {
    ADD_MEMORY_ENTRY: "memory_entry",
    REPLACE_MEMORY_ENTRY: "memory_entry",
    REMOVE_MEMORY_ENTRY: "memory_entry",
    UPSERT_USER_DIRECTIVE: "user_directive",
    APPEND_DAILY_NOTE: "daily_note",
    SET_PROACTIVE_PREFERENCES: "proactive_preferences",
}


def openai_tools(definitions: list[dict]) -> list[dict]:
    return [{"type": "function", "function": definition} for definition in definitions]


def redact_tool_diagnostics(result: dict[str, Any], secrets: tuple[str, ...]) -> dict[str, Any]:
    """Protect failure diagnostics before records, events or model feedback; keep normal content."""
    # memory_search and memory_get can return useful content alongside failed corpus metadata
    # without an overall failure status (tools/corpus.py:compose_memory_corpus_metadata).
    updates = {
        key: redact_diagnostic_payload(result[key], secrets)
        for key in ("error", "warning", "action", "afterWriteError", "debug", "cause")
        if key in result
    }
    if isinstance(result.get("corpora"), list):
        updates["corpora"] = [
            redact_tool_diagnostics(corpus, secrets) if isinstance(corpus, dict) else corpus
            for corpus in result["corpora"]
        ]
    return {**result, **updates} if updates else result


@dataclass
class LabToolbox:
    """Tools offered to one turn (the kit's) and the Lab's records of their calls."""

    lab: LabRuntime
    kit: HostKit
    session: LabSession
    turn_id: int | None
    curated: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    secrets: tuple[str, ...] = field(default=(), repr=False)

    def definitions(self) -> list[dict]:
        return self.kit.tools()

    def dispatch(self, call_id: str, name: str, raw_arguments: str) -> dict[str, Any]:
        """Run one tool call; returns the call record with the payload sent to the model.

        The raw arguments go to ``HostKit.dispatch``, which decodes them; the record shows them
        decoded when they are JSON.
        """
        started = time.perf_counter()
        arguments = preview_arguments(raw_arguments)
        record: dict[str, Any] = {"id": call_id, "name": name, "arguments": arguments}
        offered = {definition["name"] for definition in self.definitions()}
        if name in offered and name in CURATION_OPERATIONS:
            result = self._curate(name, raw_arguments, record)
        elif name == MEMORY_SEARCH_TOOL_NAME:
            result = self._memory_search(raw_arguments, arguments)
        else:
            result = redact_tool_diagnostics(
                self.kit.dispatch(name, raw_arguments, session=self.session.state), self.secrets
            )
        finish_call(record, result, started)
        self.calls.append(record)
        return record

    def _memory_search(self, raw_arguments: str, arguments: Any) -> dict[str, Any]:
        # The kit records the hits as short-term recalls (dreaming enabled in the Lab).
        with self.lab.tracked("recall", turn_id=self.turn_id):
            result = self.kit.dispatch(
                MEMORY_SEARCH_TOOL_NAME, raw_arguments, session=self.session.state
            )
        result = redact_tool_diagnostics(result, self.secrets)
        if result.get("status") == "error":
            return result
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
        # The search ran, so the arguments were a JSON object.
        self.lab.bus.emit(
            "search.completed",
            summary=f"memory_search (model): {len(hits)} sonuç",
            data={"query": arguments.get("query"), "hits": len(hits), "via": "tool"},
            turn_id=self.turn_id,
        )
        return result

    def _target(self, name: str) -> str:
        if name in MEMORY_ENTRY_OPERATIONS:
            return self.lab.layout.memory_file
        if name == UPSERT_USER_DIRECTIVE:
            return "USER.md"
        if name == SET_PROACTIVE_PREFERENCES:
            return "PROACTIVE_PREFERENCES.md"
        return f"memory/{self.kit.curator.today()}.md"

    def _curate(self, name: str, raw_arguments: str, record: dict[str, Any]) -> dict[str, Any]:
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
        with self.lab.tracked("curation", turn_id=self.turn_id):
            result = self.kit.dispatch(name, raw_arguments, session=self.session.state)
        result = redact_tool_diagnostics(result, self.secrets)
        # Every error payload is a refused write: a refusal, bad or invalid arguments, a failure.
        if result.get("status") == "error":
            reason = str(result.get("error"))
            refused = {**base, "id": self.lab.allocate_write_id(), "path": target, "refused": True,
                       "reason": reason, "diff": ""}
            self.lab.curated_writes.append(refused)
            self.curated.append(refused)
            record["curation"] = refused
            self.lab.bus.emit(
                "curation.refused",
                summary=f"{target} reddedildi: {reason}",
                data={"path": target, "operation": name, "reason": reason, "writeId": refused["id"]},
                turn_id=self.turn_id,
            )
            return result
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


def finish_call(record: dict[str, Any], result: dict[str, Any], started: float) -> None:
    """Complete a call record with the payload sent back and the time the call took."""
    record["result"] = result
    # A refusal the memory tools answer themselves carries ``status: error`` (``memory_search``'s
    # unavailable result still carries ``disabled``; docs/host_kit.md).
    record["ok"] = not (
        isinstance(result, dict) and (result.get("status") == "error" or result.get("disabled"))
    )
    record["ms"] = int((time.perf_counter() - started) * 1000)


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


class Toolbox(Protocol):
    """What the tool loop needs: the offered definitions and a dispatch that records calls."""

    calls: list[dict[str, Any]]

    def definitions(self) -> list[dict[str, Any]]: ...

    def dispatch(self, call_id: str, name: str, raw_arguments: str) -> dict[str, Any]: ...


def run_tool_loop(
    engine: ChatEngine,
    messages: list[dict[str, Any]],
    toolbox: Toolbox | None,
    outcome: ToolLoopOutcome,
    *,
    max_rounds: int = MAX_TOOL_ROUNDS,
    secrets: tuple[str, ...] = (),
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
            yield "tool_call", {"id": call["id"], "name": call["name"], "arguments": preview_arguments(call["arguments"]),
                                "round": round_index + 1}
            try:
                record = toolbox.dispatch(call["id"], call["name"], call["arguments"] or "")
            except Exception as exc:  # a tool failure goes back to the model, like upstream
                record = {"id": call["id"], "name": call["name"], "ok": False, "ms": 0,
                          "result": {"status": "error", "tool": call["name"],
                                     "error": safe_exception_message(exc, secrets)}}
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


def preview_arguments(raw: str) -> Any:
    try:
        return json.loads(raw) if raw and raw.strip() else {}
    except json.JSONDecodeError:
        return raw


__all__ = [
    "MAX_TOOL_ROUNDS",
    "LabToolbox",
    "ToolLoopOutcome",
    "Toolbox",
    "finish_call",
    "preview_arguments",
    "public_write",
    "run_tool_loop",
]
