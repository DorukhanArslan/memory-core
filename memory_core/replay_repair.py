from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal


AgentMessage = dict[str, Any]
ErroredAssistantResultPolicy = Literal["preserve", "drop"]

_TOOL_CALL_TYPES = {"toolCall", "toolUse", "functionCall"}


@dataclass(frozen=True)
class ToolUseRepairReport:
    messages: list[AgentMessage]
    added: list[AgentMessage]
    dropped_duplicate_count: int
    dropped_orphan_count: int
    moved: bool


def repair_tool_use_result_pairing(
    messages: list[AgentMessage],
    *,
    errored_assistant_result_policy: ErroredAssistantResultPolicy = "preserve",
    missing_tool_result_text: str | None = None,
) -> ToolUseRepairReport:
    out: list[AgentMessage] = []
    added: list[AgentMessage] = []
    seen_tool_result_ids: set[str] = set()
    dropped_duplicate_count = 0
    dropped_orphan_count = 0
    moved = False
    changed = False

    def push_tool_result(message: AgentMessage) -> tuple[int, bool]:
        result_id = _extract_tool_result_id(message)
        if result_id and result_id in seen_tool_result_ids:
            return 1, True
        if result_id:
            seen_tool_result_ids.add(result_id)
        out.append(message)
        return 0, False

    i = 0
    while i < len(messages):
        message = messages[i]
        role = message.get("role") if isinstance(message, Mapping) else None
        if role != "assistant":
            if role != "toolResult":
                out.append(message)
            else:
                dropped_orphan_count += 1
                changed = True
            i += 1
            continue

        tool_calls = _extract_tool_calls_from_assistant(message)
        if not tool_calls:
            out.append(message)
            i += 1
            continue

        tool_call_ids = {tool_call["id"] for tool_call in tool_calls}
        tool_call_names_by_id = {
            tool_call["id"]: tool_call.get("name")
            for tool_call in tool_calls
            if isinstance(tool_call.get("name"), str)
        }
        span_results_by_id: dict[str, AgentMessage] = {}
        remainder: list[AgentMessage] = []

        j = i + 1
        while j < len(messages):
            next_message = messages[j]
            next_role = next_message.get("role") if isinstance(next_message, Mapping) else None
            if next_role == "assistant":
                if _assistant_has_tool_calls(next_message):
                    break
                remainder.append(next_message)
                j += 1
                continue

            if next_role == "toolResult":
                tool_result = _normalize_legacy_tool_result_id(next_message, tool_calls)
                result_id = _extract_tool_result_id(tool_result)
                if result_id and result_id in tool_call_ids:
                    if result_id in seen_tool_result_ids:
                        dropped_duplicate_count += 1
                        changed = True
                        j += 1
                        continue
                    normalized = _normalize_tool_result_name(
                        tool_result,
                        tool_call_names_by_id.get(result_id),
                    )
                    span_results_by_id.setdefault(result_id, normalized)
                    if normalized is not next_message:
                        changed = True
                    j += 1
                    continue

            if next_role != "toolResult":
                remainder.append(next_message)
            else:
                dropped_orphan_count += 1
                changed = True
            j += 1

        stop_reason = message.get("stopReason")
        if stop_reason in {"error", "aborted"}:
            if errored_assistant_result_policy != "drop":
                out.append(message)
                for tool_call in tool_calls:
                    result = span_results_by_id.get(tool_call["id"])
                    if not result:
                        continue
                    duplicate, did_change = push_tool_result(result)
                    dropped_duplicate_count += duplicate
                    changed = changed or did_change
            else:
                changed = True
            out.extend(remainder)
            i = j
            continue

        out.append(message)
        if span_results_by_id and remainder:
            moved = True
            changed = True

        for tool_call in tool_calls:
            existing = span_results_by_id.get(tool_call["id"])
            if existing:
                duplicate, did_change = push_tool_result(existing)
                dropped_duplicate_count += duplicate
                changed = changed or did_change
                continue
            missing = _make_missing_tool_result(
                tool_call_id=tool_call["id"],
                tool_name=tool_call.get("name"),
                text=missing_tool_result_text,
            )
            added.append(missing)
            changed = True
            duplicate, did_change = push_tool_result(missing)
            dropped_duplicate_count += duplicate
            changed = changed or did_change

        out.extend(remainder)
        i = j

    changed_or_moved = changed or moved
    return ToolUseRepairReport(
        messages=out if changed_or_moved else messages,
        added=added,
        dropped_duplicate_count=dropped_duplicate_count,
        dropped_orphan_count=dropped_orphan_count,
        moved=changed_or_moved,
    )


def sanitize_tool_use_result_pairing(
    messages: list[AgentMessage],
    *,
    errored_assistant_result_policy: ErroredAssistantResultPolicy = "preserve",
    missing_tool_result_text: str | None = None,
) -> list[AgentMessage]:
    return repair_tool_use_result_pairing(
        messages,
        errored_assistant_result_policy=errored_assistant_result_policy,
        missing_tool_result_text=missing_tool_result_text,
    ).messages


def _extract_tool_calls_from_assistant(message: AgentMessage) -> list[dict[str, str]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []

    tool_calls: list[dict[str, str]] = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") not in _TOOL_CALL_TYPES:
            continue
        tool_id = block.get("id")
        if not isinstance(tool_id, str) or not tool_id:
            continue
        tool_call: dict[str, str] = {"id": tool_id}
        if isinstance(block.get("name"), str):
            tool_call["name"] = block["name"]
        tool_calls.append(tool_call)
    return tool_calls


def _assistant_has_tool_calls(message: AgentMessage) -> bool:
    return message.get("role") == "assistant" and bool(_extract_tool_calls_from_assistant(message))


def _extract_tool_result_id(message: AgentMessage) -> str | None:
    ids = _extract_tool_result_ids(message)
    return ids[0] if ids else None


def _extract_tool_result_ids(message: AgentMessage) -> list[str]:
    ids: list[str] = []
    for key in ("toolCallId", "toolUseId", "tool_call_id", "tool_use_id", "callId", "call_id"):
        value = message.get(key)
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized and normalized not in ids:
            ids.append(normalized)
    return ids


def _normalize_legacy_tool_result_id(
    message: AgentMessage,
    tool_calls: list[dict[str, str]],
) -> AgentMessage:
    if _extract_tool_result_id(message) or len(tool_calls) != 1:
        return message
    tool_call = tool_calls[0]
    tool_result_name = _normalize_optional_string(message.get("toolName"))
    tool_call_name = _normalize_optional_string(tool_call.get("name"))
    if tool_result_name and tool_call_name and tool_result_name != tool_call_name:
        return message
    return {**message, "toolCallId": tool_call["id"], "isError": True}


def _normalize_tool_result_name(message: AgentMessage, fallback_name: str | None = None) -> AgentMessage:
    raw_tool_name = message.get("toolName")
    normalized_tool_name = _normalize_optional_string(raw_tool_name)
    if normalized_tool_name:
        if raw_tool_name == normalized_tool_name:
            return message
        return {**message, "toolName": normalized_tool_name}

    normalized_fallback = _normalize_optional_string(fallback_name)
    if normalized_fallback:
        return {**message, "toolName": normalized_fallback}

    if isinstance(raw_tool_name, str):
        return {**message, "toolName": "unknown"}
    return message


def _normalize_optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _make_missing_tool_result(
    *,
    tool_call_id: str,
    tool_name: str | None,
    text: str | None,
) -> AgentMessage:
    return {
        "role": "toolResult",
        "toolCallId": tool_call_id,
        "toolName": tool_name or "unknown",
        "content": [
            {
                "type": "text",
                "text": text
                or "[openclaw] missing tool result in session history; inserted synthetic error result for transcript repair.",
            }
        ],
        "isError": True,
        "timestamp": int(time.time() * 1000),
    }
