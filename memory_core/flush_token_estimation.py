"""The compaction-planning token estimate used by the memory-flush trigger.

This estimate follows ``compaction-planning.ts`` / agent-core ``estimateTokens``;
it intentionally has no per-message overhead or preemptive-compaction safety factor.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

from memory_core.bootstrap._js import js_trim, utf16_len
from memory_core.context_engine_lifecycle import strip_runtime_context_custom_messages
from memory_core.index.cjk_chars import estimate_string_chars
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.tool_result_text import js_stringify

_MISSING = object()
_OMITTED_CHARS_FIELD = "__openclawCompactionPlanningOmittedChars"


def _stringify(value: Any) -> str:
    if value is _MISSING:
        return "undefined"
    try:
        return js_stringify(value)
    except (TypeError, ValueError, RecursionError):
        return "[unserializable]"


def _content_chars(content: Any) -> int:
    if isinstance(content, str):
        return estimate_string_chars(content)
    texts: list[str] = []
    omissions: dict[str, None] = {}
    image_count = 0
    for block in content or ():
        if not isinstance(block, Mapping):
            continue
        kind = block.get("type")
        text = ""
        if kind in {"text", "toolResult", "tool_result"} and block.get("text"):
            text = block["text"]
        elif kind in {"toolResult", "tool_result"} and isinstance(block.get("content"), str):
            text = block["content"]
        if kind == "image":
            image_count += 1
        if kind != "text" and not text:
            marker = (
                "[image data omitted from summary input]"
                if kind == "image"
                else "[non-text data omitted from summary input]"
            )
            omissions[marker] = None
        if text:
            texts.append(text)
    omission_text = "\n".join(omissions)
    omission_chars = utf16_len(omission_text) + len("\n\n[Tool result]: ") if omission_text else 0
    return estimate_string_chars("\n".join(texts)) + image_count * 8000 + omission_chars


def _sender_suffix(message: Mapping[str, Any]) -> str:
    metadata = message.get("__openclaw")
    if not isinstance(metadata, Mapping):
        return ""
    sender = {}
    for key, source in (("id", "senderId"), ("name", "senderName"), ("username", "senderUsername")):
        value = metadata.get(source)
        normalized = js_trim(value.replace("\x00", "")) if isinstance(value, str) else ""
        if normalized:
            sender[key] = normalized
    return f" sender={_stringify(sender)}" if sender.get("id") else ""


def _message_tokens(message: Mapping[str, Any]) -> int:
    if message.get("excludeFromContext") is True:
        return 0
    role = message.get("role")
    chars = 0
    if role == "assistant":
        content = message.get("content", ())
        # A string is a host convenience; canonical agent assistant messages use blocks.
        for block in content if not isinstance(content, str) else ():
            if not isinstance(block, Mapping):
                continue
            if block.get("type") == "text":
                chars += estimate_string_chars(block["text"])
            elif block.get("type") == "thinking":
                chars += estimate_string_chars(block["thinking"])
            elif block.get("type") == "toolCall":
                chars += estimate_string_chars(block["name"])
                chars += estimate_string_chars(_stringify(block.get("arguments", _MISSING)))
    elif role in {"user", "custom", "toolResult"}:
        chars = _content_chars(message.get("content", ""))
        if role == "user":
            chars += estimate_string_chars(_sender_suffix(message))
    elif role == "bashExecution":
        chars = estimate_string_chars(message["command"]) + estimate_string_chars(message["output"])
    elif role in {"branchSummary", "compactionSummary"}:
        chars = estimate_string_chars(message["summary"])
    return math.ceil(chars / 4)


def estimate_flush_messages_tokens(
    messages: Sequence[dict[str, Any]],
    *,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> int:
    """Estimate canonical agent messages with native CJK/UTF-16 and omission accounting.

    Runtime context is removed using the host's identity. Tool-result ``details`` never enter
    the estimate. The input is read only; no sanitizer mutates the stored transcript.
    """
    total = 0
    for message in strip_runtime_context_custom_messages(list(messages), identity=identity):
        omitted = message.get(_OMITTED_CHARS_FIELD)
        omitted_chars = (
            math.floor(omitted)
            if isinstance(omitted, int | float)
            and not isinstance(omitted, bool)
            and math.isfinite(omitted)
            and omitted > 0
            else 0
        )
        total += _message_tokens(message) + math.ceil(omitted_chars / 4)
    return total
