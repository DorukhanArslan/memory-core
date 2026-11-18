"""Provider turn validation at the model callback boundary.

Ports OpenClaw v2026.9.9 ``embedded-agent-helpers/turns.ts``,
``shared/google-turn-ordering.ts``, and the result/prefill guards in
``embedded-agent-runner/run/attempt-tool-call-replay-sanitization.ts``.
These transforms retain complete message metadata and never persist their output.
"""
from __future__ import annotations

from collections.abc import Mapping
import time
from typing import Any

from memory_core.bootstrap._js import js_trim, js_truthy
from memory_core.replay_repair import (
    _extract_tool_calls_from_assistant,
    _extract_tool_result_id,
)


_MISSING = object()
_TOOL_CALL_TYPES = frozenset({"toolUse", "toolCall", "functionCall"})
_RESULT_ID_KEYS = (
    "toolUseId", "toolCallId", "tool_use_id", "tool_call_id", "callId", "call_id",
)


def _optional_string(value: Any) -> str | None:
    return (js_trim(value) or None) if isinstance(value, str) else None


def _is_tool_call(block: Any) -> bool:
    return isinstance(block, Mapping) and block.get("type") in _TOOL_CALL_TYPES


def _has_replay_tool_call(message: Any) -> bool:
    return (
        isinstance(message, Mapping)
        and message.get("role") == "assistant"
        and isinstance(message.get("content"), list)
        and any(_is_tool_call(block) for block in message["content"])
    )


def _has_thinking(content: list[Any]) -> bool:
    return any(isinstance(block, Mapping) and block.get("type") in {
        "thinking", "redacted_thinking",
    } for block in content)


def _result_match_ids(record: Mapping[str, Any]) -> set[str]:
    return {identifier for key in _RESULT_ID_KEYS
            if (identifier := _optional_string(record.get(key))) is not None}


def _result_match_name(record: Mapping[str, Any]) -> str | None:
    return _optional_string(record.get("toolName")) or _optional_string(record.get("name"))


def _any_tool_result_ids(message: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    if message.get("role") == "toolResult":
        identifier = _extract_tool_result_id(message)
        if identifier:
            ids.add(identifier)
    elif message.get("role") == "tool":
        ids.update(_result_match_ids(message))
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, Mapping) and block.get("type") in {"toolResult", "tool"}:
                ids.update(_result_match_ids(block))
    return ids


def _trusted_tool_result_matches(message: Mapping[str, Any]) -> dict[str, set[str]]:
    if message.get("role") not in {"toolResult", "tool"}:
        return {}
    ids = _result_match_ids(message)
    if message.get("role") == "toolResult":
        identifier = _extract_tool_result_id(message)
        if identifier:
            ids.add(identifier)
    name = _result_match_name(message)
    return {identifier: {name} if name else set() for identifier in ids}


def _future_tool_results(messages: list[Any], start: int) -> tuple[
    dict[str, set[str]], set[str],
]:
    matches: dict[str, set[str]] = {}
    ids: set[str] = set()
    for message in messages[start + 1:]:
        if not isinstance(message, Mapping):
            continue
        if message.get("role") == "assistant":
            break
        for identifier, names in _trusted_tool_result_matches(message).items():
            matches.setdefault(identifier, set()).update(names)
        ids.update(_any_tool_result_ids(message))
    return matches, ids


def _strip_dangling_anthropic_tool_uses(messages: list[Any]) -> list[Any]:
    result: list[Any] = []
    for index, message in enumerate(messages):
        if not js_truthy(message):
            continue
        if not isinstance(message, Mapping) or message.get("role") != "assistant":
            result.append(message)
            continue
        content = message.get("content")
        content = content if isinstance(content, list) else []
        if not content or not _extract_tool_calls_from_assistant(message):
            result.append(message)
            continue
        matches, valid_ids = _future_tool_results(messages, index)
        aborted = message.get("stopReason") in {"aborted", "error"}
        omitted = [] if aborted else [{"type": "text", "text": "[tool calls omitted]"}]
        if _has_thinking(content):
            resolvable = True
            for block in content:
                if not _is_tool_call(block):
                    continue
                identifier = _optional_string(block.get("id"))
                name = _optional_string(block.get("name"))
                if not identifier or not name or identifier not in matches:
                    resolvable = False
                    break
                names = matches[identifier]
                if names and name not in names:
                    resolvable = False
                    break
            result.append(message if resolvable else {**message, "content": omitted})
            continue
        filtered = [block for block in content if js_truthy(block) and (
            not _is_tool_call(block)
            or _optional_string(block.get("id")) in valid_ids
        )]
        result.append(message if len(filtered) == len(content) else {
            **message, "content": filtered if filtered else omitted,
        })
    return result


def _merge_assistant(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    first, second = previous.get("content"), current.get("content")
    merged = {**previous, "content": [
        *(first if isinstance(first, list) else []),
        *(second if isinstance(second, list) else []),
    ]}
    for key in ("usage", "stopReason", "errorMessage"):
        if js_truthy(current.get(key)):
            merged[key] = current[key]
    return merged


def _user_content(content: Any) -> list[Any]:
    if isinstance(content, list):
        return content
    return [{"type": "text", "text": content}] if isinstance(content, str) else []


def _merge_user(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    merged = {**current, "content": [
        *_user_content(previous.get("content")), *_user_content(current.get("content")),
    ]}
    timestamp = current.get("timestamp")
    if timestamp is None:
        timestamp = previous.get("timestamp", _MISSING)
    if timestamp is _MISSING:
        merged.pop("timestamp", None)
    else:
        merged["timestamp"] = timestamp
    return merged


def _merge_consecutive(messages: list[Any], role: str) -> list[Any]:
    if not messages:
        return messages
    result: list[Any] = []
    last_role: str | None = None
    for message in messages:
        if not isinstance(message, Mapping) or not js_truthy(message.get("role")):
            result.append(message)
            continue
        current_role = message["role"]
        if current_role == last_role == role and result and isinstance(result[-1], Mapping):
            result[-1] = (_merge_assistant if role == "assistant" else _merge_user)(
                result[-1], message,
            )
            continue
        result.append(message)
        last_role = current_role
    return messages if len(result) == len(messages) else result


def validate_gemini_turns(messages: list[Any]) -> list[Any]:
    """Merge adjacent assistant turns, retaining the first message's metadata."""
    return _merge_consecutive(messages, "assistant")


def merge_consecutive_user_messages(messages: list[Any]) -> list[Any]:
    """Merge adjacent users, retaining the last message's metadata and timestamp."""
    return _merge_consecutive(messages, "user")


def validate_anthropic_turns(
    messages: list[Any], *, merge_consecutive_user_turns: bool = True,
) -> list[Any]:
    """Merge assistants, resolve dangling tool uses, and optionally merge users."""
    stripped = _strip_dangling_anthropic_tool_uses(validate_gemini_turns(messages))
    return merge_consecutive_user_messages(stripped) if merge_consecutive_user_turns else stripped


def sanitize_google_turn_ordering(
    messages: list[Any], *, now_ms: int | float | None = None,
) -> list[Any]:
    """Prepend the native bootstrap user when the first turn is an assistant."""
    if not messages or not isinstance(messages[0], Mapping) or messages[0].get("role") != "assistant":
        return messages
    return [{"role": "user", "content": "(session bootstrap)",
             "timestamp": int(time.time() * 1000) if now_ms is None else now_ms}, *messages]


def sanitize_anthropic_replay_tool_results(
    messages: list[Any], *,
    disallow_embedded_user_tool_results_for_signed_thinking_replay: bool = False,
) -> list[Any]:
    """Remove unowned embedded user tool results before callback validation."""
    changed = False
    out: list[Any] = []
    for index, message in enumerate(messages):
        if not js_truthy(message):
            changed = True
            continue
        if (not isinstance(message, Mapping) or message.get("role") != "user"
                or not isinstance(message.get("content"), list)):
            out.append(message)
            continue
        previous = messages[index - 1] if index > 0 else None
        previous_has_calls = _has_replay_tool_call(previous)
        strip_embedded = (disallow_embedded_user_tool_results_for_signed_thinking_replay
                          and previous_has_calls and _has_thinking(previous["content"]))
        valid_ids = {_optional_string(block.get("id")) for block in previous["content"]
                     if _is_tool_call(block) and _optional_string(block.get("id"))} \
            if previous_has_calls else set()
        content: list[Any] = []
        for block in message["content"]:
            if not isinstance(block, Mapping) or block.get("type") not in {"toolResult", "tool"}:
                content.append(block)
                continue
            result_ids = {_optional_string(block.get(key)) for key in _RESULT_ID_KEYS[:4]}
            result_ids.discard(None)
            if not strip_embedded and result_ids and valid_ids.intersection(result_ids):
                content.append(block)
        if len(content) == len(message["content"]):
            out.append(message)
            continue
        changed = True
        out.append({**message, "content": content or [{
            "type": "text", "text": "[tool results omitted]",
        }]})
    return out if changed else messages


def strip_trailing_assistant_prefill_turns(messages: list[Any]) -> list[Any]:
    """Remove trailing assistant spans that contain no executable tool call."""
    end = len(messages)
    while end > 0:
        message = messages[end - 1]
        if (not isinstance(message, Mapping) or message.get("role") != "assistant"
                or _has_replay_tool_call(message)):
            break
        end -= 1
    return messages if end == len(messages) else messages[:end]


__all__ = [
    "merge_consecutive_user_messages", "sanitize_anthropic_replay_tool_results",
    "sanitize_google_turn_ordering", "strip_trailing_assistant_prefill_turns",
    "validate_anthropic_turns", "validate_gemini_turns",
]
