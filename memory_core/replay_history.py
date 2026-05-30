from __future__ import annotations

import re
from typing import Any

from memory_core.runtime_context_prompt import (
    OPENCLAW_NEXT_TURN_RUNTIME_CONTEXT_HEADER,
    OPENCLAW_RUNTIME_CONTEXT_NOTICE,
)


STREAM_ERROR_FALLBACK_TEXT = "[assistant turn failed before producing content]"
_TRANSCRIPT_ONLY_OPENCLAW_MODELS = {"delivery-mirror", "gateway-injected"}


def normalize_assistant_replay_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    touched = False
    out: list[dict[str, Any]] = []

    for message in messages:
        if message.get("role") == "user":
            sanitized_user = _sanitize_user_replay_content(message)
            if sanitized_user is not None:
                out.append(sanitized_user)
            if sanitized_user != message:
                touched = True
            continue

        if message.get("role") != "assistant":
            out.append(message)
            continue

        if _is_transcript_only_openclaw_assistant(message):
            touched = True
            continue

        replay_content = message.get("content")
        assistant_message = message
        if isinstance(replay_content, str):
            normalized = _normalize_assistant_replay_text_content(message, replay_content)
            if normalized is not None:
                out.append(normalized)
            touched = True
            continue

        if not isinstance(replay_content, list):
            replay_content = [replay_content] if isinstance(replay_content, dict) else []
            assistant_message = {**message, "content": replay_content}
            touched = True

        normalized_blocks = _normalize_assistant_replay_block_content(
            assistant_message,
            replay_content,
        )
        if normalized_blocks != assistant_message:
            if normalized_blocks is not None:
                out.append(normalized_blocks)
            touched = True
            continue

        if len(replay_content) == 0:
            stop_reason = assistant_message.get("stopReason")
            if stop_reason == "error" or _is_zero_usage_empty_stop_assistant_turn(assistant_message):
                out.append(
                    {
                        **assistant_message,
                        "content": [{"type": "text", "text": STREAM_ERROR_FALLBACK_TEXT}],
                    }
                )
                touched = True
                continue

        out.append(assistant_message)

    while out and _is_replay_droppable_trailing_assistant(out[-1]):
        out.pop()
        touched = True

    return out if touched else messages


def _sanitize_user_replay_content(message: dict[str, Any]) -> dict[str, Any] | None:
    content = message.get("content")
    if isinstance(content, str):
        return message if content.strip() else None
    if not isinstance(content, list):
        return message

    touched = False
    sanitized = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            sanitized.append(block)
            continue
        text = block.get("text")
        if not isinstance(text, str) or text.strip():
            sanitized.append(block)
            continue
        touched = True
    if not sanitized:
        return None
    return {**message, "content": sanitized} if touched else message


def _is_transcript_only_openclaw_assistant(message: dict[str, Any]) -> bool:
    return (
        message.get("role") == "assistant"
        and message.get("provider") == "openclaw"
        and message.get("model") in _TRANSCRIPT_ONLY_OPENCLAW_MODELS
    )


def _normalize_assistant_replay_text_content(
    message: dict[str, Any],
    replay_content: str,
) -> dict[str, Any] | None:
    stripped = _strip_internal_metadata_for_display(replay_content)
    trimmed = stripped.strip()
    if not trimmed or _is_silent_reply_payload_text(trimmed):
        return None
    return {**message, "content": [{"type": "text", "text": stripped}]}


def _normalize_assistant_replay_block_content(
    message: dict[str, Any],
    replay_content: list[Any],
) -> dict[str, Any] | None:
    touched = False
    sanitized = []
    for block in replay_content:
        if not isinstance(block, dict) or not isinstance(block.get("text"), str):
            sanitized.append(block)
            continue
        text = block["text"]
        stripped = _strip_internal_metadata_for_display(text)
        if stripped == text:
            if not _is_silent_reply_payload_text(text.strip()):
                sanitized.append(block)
            else:
                touched = True
            continue
        touched = True
        trimmed = stripped.strip()
        if trimmed and not _is_silent_reply_payload_text(trimmed):
            sanitized.append({**block, "text": stripped})
    if not touched:
        return message
    if not sanitized:
        return None
    return {**message, "content": sanitized}


def _is_silent_reply_payload_text(text: str) -> bool:
    return text == "NO_REPLY"


def _is_replay_droppable_trailing_assistant(message: dict[str, Any] | None) -> bool:
    if not message or message.get("role") != "assistant":
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    if not content:
        stop_reason = message.get("stopReason")
        return stop_reason == "error" or _is_zero_usage_empty_stop_assistant_turn(message)
    if not _is_stream_error_sentinel_content(content):
        return False
    stop_reason = message.get("stopReason")
    if stop_reason == "error":
        return True
    return _is_zero_usage_empty_stop_assistant_turn({**message, "content": []})


def _is_stream_error_sentinel_content(content: list[Any]) -> bool:
    if len(content) != 1 or not isinstance(content[0], dict):
        return False
    return content[0].get("type") == "text" and content[0].get("text") == STREAM_ERROR_FALLBACK_TEXT


def _is_zero_usage_empty_stop_assistant_turn(message: dict[str, Any] | None) -> bool:
    return bool(
        message
        and message.get("stopReason") == "stop"
        and isinstance(message.get("content"), list)
        and len(message["content"]) == 0
        and _has_zero_token_usage_snapshot(message.get("usage"))
    )


def _has_zero_token_usage_snapshot(usage: Any) -> bool:
    if not isinstance(usage, dict):
        return False
    input_tokens = _read_finite_number(usage.get("input"))
    output_tokens = _read_finite_number(usage.get("output"))
    cache_read = _read_finite_number(usage.get("cacheRead"))
    cache_write = _read_finite_number(usage.get("cacheWrite"))
    total = _read_finite_number(
        usage.get("total", usage.get("totalTokens", usage.get("total_tokens")))
    )
    if total is not None:
        return total == 0 and all(
            value is None or value == 0
            for value in [input_tokens, output_tokens, cache_read, cache_write]
        )
    components = [
        value
        for value in [input_tokens, output_tokens, cache_read, cache_write]
        if value is not None
    ]
    return bool(components) and all(value == 0 for value in components)


def _read_finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _strip_internal_metadata_for_display(text: str) -> str:
    return _strip_runtime_context_prompt_preface(_strip_internal_runtime_context(text))


def _strip_internal_runtime_context(text: str) -> str:
    next_text = text
    while True:
        start = _find_delimited_token_index(next_text, "<<<BEGIN_OPENCLAW_INTERNAL_CONTEXT>>>", 0)
        if start == -1:
            return next_text
        end = _find_delimited_token_index(next_text, "<<<END_OPENCLAW_INTERNAL_CONTEXT>>>", start)
        before = next_text[:start].rstrip()
        if end == -1:
            return before
        after = next_text[end + len("<<<END_OPENCLAW_INTERNAL_CONTEXT>>>") :].lstrip()
        next_text = f"{before}\n\n{after}" if before and after else f"{before}{after}"


def _find_delimited_token_index(text: str, token: str, start: int) -> int:
    pattern = re.compile(rf"(?:^|\r?\n){re.escape(token)}(?=\r?\n|$)")
    match = pattern.search(text, max(0, start))
    if not match:
        return -1
    return match.start() + len(match.group(0)) - len(token)


def _strip_runtime_context_prompt_preface(text: str) -> str:
    lines = text.splitlines()
    changed = False
    output = []
    index = 0
    while index < len(lines):
        line = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if (
            line.strip() in {OPENCLAW_NEXT_TURN_RUNTIME_CONTEXT_HEADER, "OpenClaw runtime event."}
            and next_line.strip() == OPENCLAW_RUNTIME_CONTEXT_NOTICE
        ):
            changed = True
            index += 2
            while index < len(lines) and not lines[index].strip():
                index += 1
            continue
        output.append(line)
        index += 1
    if not changed:
        return text
    return re.sub(r"\n{3,}", "\n\n", "\n".join(output)).strip()
