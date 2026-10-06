from __future__ import annotations

import re
from typing import Any

from memory_core.bootstrap._js import js_trim, js_truthy
from memory_core.compaction_replay import replace_compaction_replay_owner_content
from memory_core.memory_flush import SILENT_REPLY_TOKEN
from memory_core.replay_repair import _extract_tool_calls_from_assistant
from memory_core.runtime_context_prompt import (
    OPENCLAW_RUNTIME_CONTEXT_NOTICE,
    _find_delimited_token_index,
)
from memory_core.runtime_identity import (
    OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    MEMORY_CORE_RUNTIME_IDENTITY,
)
from memory_core.session_entry import strip_inbound_metadata
from memory_core.usage_normalization import has_nonzero_normalized_usage


STREAM_ERROR_FALLBACK_TEXT = "[assistant turn failed before producing content]"
_TRANSCRIPT_ONLY_OPENCLAW_MODELS = {"delivery-mirror", "gateway-injected"}
_MANAGED_DISPLAY_BLOCK_TYPES = {"attachment", "attachment_error", "audio", "image", "video"}


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

        # Failed attempts have no model content; discard the legacy placeholder too.
        # Keep billed silent replies and incomplete tool/length states unchanged.
        if _is_stream_error_fallback_content(message.get("content")) and (
            message.get("stopReason") == "error"
            or _is_zero_usage_empty_stop_assistant_turn({**message, "content": []})
        ):
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
            assistant_message = replace_compaction_replay_owner_content(message, replay_content)
            touched = True

        normalized_blocks = _normalize_assistant_replay_block_content(
            assistant_message,
            replay_content,
        )
        if normalized_blocks is not assistant_message:
            touched = True
            if normalized_blocks is None:
                continue
            assistant_message = normalized_blocks

        if _is_reasoning_only_length_assistant_turn(assistant_message):
            # Token-limited thinking is incomplete provider state; replaying it can
            # resend a partial signature.
            touched = True
            continue

        # Historical side-branch rebuilds could strip every mirror marker while
        # retaining the zero-usage receipt right after its source reply.
        if _is_bare_delivery_mirror_duplicate(out, assistant_message):
            touched = True
            continue

        out.append(assistant_message)

    return out if touched else messages


def _sanitize_user_replay_content(message: dict[str, Any]) -> dict[str, Any] | None:
    content = message.get("content")
    if isinstance(content, str):
        return message if content.strip() or _has_persisted_media(message) else None
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
        return {**message, "content": ""} if _has_persisted_media(message) else None
    return {**message, "content": sanitized} if touched else message


def _has_persisted_media(message: dict[str, Any]) -> bool:
    """``hasPersistedMedia`` (sessions/user-turn-media.ts): a meaningful canonical media fact.

    Reads the canonical envelope (``__openclaw.media``) only, normalizing each entry like
    ``normalizeMediaFact`` (media/media-facts.ts): path, url and contentType are trimmed strings
    (anything else is absent), a ``kind`` counts when truthy and not ``"unknown"``, and a
    non-object or ``null`` slot is an empty fact. A kind derived from the content type adds
    nothing, since a non-blank content type is meaningful on its own.
    """

    if not isinstance(message, dict):
        return False
    metadata = message.get("__openclaw")
    media = metadata.get("media") if isinstance(metadata, dict) else None
    if not isinstance(media, list):
        return False
    return any(_is_meaningful_media_input(entry) for entry in media)


def _is_meaningful_media_input(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    for key in ("path", "url", "contentType"):
        value = entry.get(key)
        if isinstance(value, str) and js_trim(value):
            return True
    kind = entry.get("kind")
    return kind is not None and js_truthy(kind) and kind != "unknown"


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
    return replace_compaction_replay_owner_content(message, [{"type": "text", "text": stripped}])


def _normalize_assistant_replay_block_content(
    message: dict[str, Any],
    replay_content: list[Any],
) -> dict[str, Any] | None:
    touched = False
    removed_silent_text = False
    sanitized = []
    for block in replay_content:
        if not isinstance(block, dict):
            sanitized.append(block)
            continue
        block_type = block.get("type")
        if isinstance(block_type, str) and block_type in _MANAGED_DISPLAY_BLOCK_TYPES:
            touched = True
            continue
        text = block.get("text")
        if not isinstance(text, str):
            sanitized.append(block)
            continue
        stripped = _strip_internal_metadata_for_display(text)
        if stripped == text:
            if not _is_silent_reply_payload_text(text.strip()):
                sanitized.append(block)
            else:
                touched = True
                removed_silent_text = True
            continue
        touched = True
        trimmed = stripped.strip()
        is_silent_text = bool(trimmed) and _is_silent_reply_payload_text(trimmed)
        if trimmed and not is_silent_text:
            sanitized.append({**block, "text": stripped})
        removed_silent_text = removed_silent_text or is_silent_text
    if not touched:
        return message
    if not sanitized:
        return None
    normalized = replace_compaction_replay_owner_content(message, sanitized)
    # A silent reply has no visible assistant output; do not let its signed reasoning
    # merge into the next assistant turn during strict replay.
    if removed_silent_text and _has_only_assistant_reasoning_content(normalized):
        return None
    return normalized


def _has_only_assistant_reasoning_content(message: dict[str, Any]) -> bool:
    if message.get("role") != "assistant":
        return False
    content = message.get("content")
    if isinstance(content, list):
        blocks = content
    elif isinstance(content, dict):
        blocks = [content]
    else:
        blocks = []
    has_thinking = False
    for block in blocks:
        if not isinstance(block, dict) or "type" not in block:
            return False
        if block["type"] in ("thinking", "redacted_thinking"):
            has_thinking = True
            continue
        if (
            block["type"] == "text"
            and isinstance(block.get("text"), str)
            and not block["text"].strip()
        ):
            continue
        return False
    return has_thinking


def _is_reasoning_only_length_assistant_turn(message: dict[str, Any]) -> bool:
    return message.get("stopReason") == "length" and _has_only_assistant_reasoning_content(message)


def _is_stream_error_fallback_content(content: Any) -> bool:
    if content is None:
        return True
    if isinstance(content, str):
        return not content.strip() or content.strip() == STREAM_ERROR_FALLBACK_TEXT
    return isinstance(content, list) and all(
        isinstance(block, dict)
        and block.get("type") in ("text", "input_text", "output_text")
        and isinstance(block.get("text"), str)
        and _is_stream_error_fallback_content(block["text"])
        for block in content
    )


def _is_bare_delivery_mirror_duplicate(out: list[dict[str, Any]], nxt: dict[str, Any]) -> bool:
    previous = out[-1] if out else None
    if not previous or previous.get("role") != "assistant":
        return False
    usage = nxt.get("usage")
    if (
        not isinstance(usage, dict | list)
        or has_nonzero_normalized_usage(usage)
        or nxt.get("stopReason") != "stop"
        or _extract_tool_calls_from_assistant(previous)
        or _extract_tool_calls_from_assistant(nxt)
    ):
        return False
    previous_content = previous.get("content")
    next_content = nxt.get("content")
    return (
        isinstance(previous_content, list)
        and len(previous_content) > 0
        and isinstance(next_content, list)
        and previous_content == next_content
    )


def _is_silent_reply_payload_text(text: str) -> bool:
    # Known gap: upstream replay-history.ts calls isSilentReplyPayloadText
    # (src/auto-reply/tokens.ts:217), which also accepts repeated tokens,
    # punctuation wrappers, JSON-string, envelope and reasoning-prefixed forms.
    return text == SILENT_REPLY_TOKEN


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
    """``stripInternalMetadataForDisplay``: ``stripInboundMetadata`` over the runtime-context strip."""

    return strip_inbound_metadata(_strip_runtime_context_and_preface(text))


def _strip_runtime_context_and_preface(text: str) -> str:
    """``stripInternalRuntimeContext``: delimited blocks, then the persisted prompt prefaces."""

    return _strip_runtime_context_prompt_preface(_strip_internal_runtime_context(text))


def _strip_internal_runtime_context(text: str) -> str:
    next_text = text
    for identity in (MEMORY_CORE_RUNTIME_IDENTITY, OPENCLAW_COMPAT_RUNTIME_IDENTITY):
        while True:
            start = _find_delimited_token_index(next_text, identity.runtime_context_begin, 0)
            if start == -1:
                break
            end = _find_delimited_token_index(next_text, identity.runtime_context_end, start)
            before = next_text[:start].rstrip()
            if end == -1:
                return before
            after = next_text[end + len(identity.runtime_context_end) :].lstrip()
            next_text = f"{before}\n\n{after}" if before and after else f"{before}{after}"
    return next_text


def _strip_runtime_context_prompt_preface(text: str) -> str:
    lines = text.splitlines()
    changed = False
    output = []
    index = 0
    while index < len(lines):
        line = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        runtime_headers = {
            MEMORY_CORE_RUNTIME_IDENTITY.next_turn_runtime_context_header,
            MEMORY_CORE_RUNTIME_IDENTITY.runtime_event_header,
            OPENCLAW_COMPAT_RUNTIME_IDENTITY.next_turn_runtime_context_header,
            OPENCLAW_COMPAT_RUNTIME_IDENTITY.runtime_event_header,
        }
        if line.strip() in runtime_headers and next_line.strip() == OPENCLAW_RUNTIME_CONTEXT_NOTICE:
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
