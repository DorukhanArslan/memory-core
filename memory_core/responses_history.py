"""OpenAI Responses history projection over whole harness messages.

Ports ``normalizeOpenAIResponsesToolCallIds``,
``downgradeOpenAIFunctionCallReasoningPairs`` and ``dropStaleOpenAIReasoning``
from OpenClaw v2026.9.9 ``src/agents/embedded-agent-helpers/openai.ts`` and the
pure ID owner ``packages/ai/src/transports/openai-responses-tool-call-id-shape.ts``.
The input list itself is returned when nothing changes; durable transcripts are
never written. String timestamps use the existing ISO timestamp owner, whose
documented Date.parse limitations remain in :mod:`memory_core.session_entry`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import math
import re
from typing import Any

from memory_core.bootstrap._js import (
    js_json_stringify,
    js_trim,
    js_truthy,
    js_utf8_encode,
    reject_json_constant,
    utf16_len,
)
from memory_core.compaction_replay import replace_compaction_replay_owner_content
from memory_core.session_entry import js_date_parse

OPENAI_RESPONSES_ID_MAX_LENGTH = 64
_CALL_ID = re.compile(r"call_[A-Za-z0-9_-]{1,59}\Z", re.ASCII)
_ITEM_ID = re.compile(r"fc_[A-Za-z0-9_-]{1,61}\Z", re.ASCII)
_TOOL_TYPES = ("toolCall", "toolUse", "functionCall")
_RESULT_FIELDS = ("toolCallId", "toolUseId", "tool_call_id", "tool_use_id", "callId", "call_id")
_PRIMARY_RESULT_FIELDS = ("call_id", "callId", "tool_call_id", "tool_use_id", "toolCallId", "toolUseId")

__all__ = [
    "OPENAI_RESPONSES_ID_MAX_LENGTH",
    "split_openai_function_call_pairing",
    "normalize_openai_responses_function_call_id",
    "should_normalize_openai_responses_tool_call_id",
    "normalize_openai_responses_tool_call_ids",
    "downgrade_openai_function_call_reasoning_pairs",
    "drop_stale_openai_reasoning",
]


def split_openai_function_call_pairing(identifier: str) -> dict[str, str]:
    """Split the first non-edge ``|`` into ``callId`` and ``itemId``."""
    separator = identifier.find("|")
    if separator <= 0 or separator >= len(identifier) - 1:
        return {"callId": identifier}
    return {"callId": identifier[:separator], "itemId": identifier[separator + 1:]}


def _normalize_id_part(value: str, prefix: str, pattern: re.Pattern[str]) -> str:
    trimmed = js_trim(value)
    if pattern.fullmatch(trimmed):
        return trimmed
    raw_tail = trimmed[len(prefix):] if trimmed.startswith(prefix) else trimmed
    digest = hashlib.sha256(js_utf8_encode(trimmed or prefix)).hexdigest()[:10]
    max_tail_length = OPENAI_RESPONSES_ID_MAX_LENGTH - len(prefix)
    suffix = "_" + digest
    # JavaScript's non-Unicode regexp replaces each UTF-16 code unit separately.
    safe_tail = "".join(
        char if char.isascii() and (char.isalnum() or char in "_-")
        else "_" * utf16_len(char)
        for char in raw_tail
    ).strip("_")
    clipped = safe_tail[:max(1, max_tail_length - len(suffix))]
    return prefix + ((clipped or "id") + suffix)[:max_tail_length]


def normalize_openai_responses_function_call_id(identifier: str) -> str:
    """Shape a whole native pairing into bounded Responses ``call_*|fc_*`` IDs."""
    pairing = split_openai_function_call_pairing(identifier)
    call_id, item_id = pairing["callId"], pairing.get("itemId")
    normalized_call = _normalize_id_part(
        f"{call_id}|{item_id}" if item_id else call_id, "call_", _CALL_ID,
    )
    if not item_id:
        return normalized_call
    return normalized_call + "|" + _normalize_id_part(item_id, "fc_", _ITEM_ID)


def should_normalize_openai_responses_tool_call_id(identifier: str) -> bool:
    """Whether either component of a Responses tool-call pairing is invalid."""
    pairing = split_openai_function_call_pairing(identifier)
    return not _CALL_ID.fullmatch(pairing["callId"]) or (
        "itemId" in pairing and not _ITEM_ID.fullmatch(pairing["itemId"])
    )


def _rewrite_tool_result_ids(message: Mapping[str, Any], resolve: Callable[[str], str]):
    raw_ids = {field: message[field] for field in _RESULT_FIELDS
               if isinstance(message.get(field), str) and message[field]}
    primary = next((raw_ids[field] for field in _PRIMARY_RESULT_FIELDS if field in raw_ids), None)
    if primary is None:
        return message
    resolved = resolve(primary)
    updates = {field: resolved for field, raw in raw_ids.items() if resolved != raw}
    if not isinstance(message.get("toolCallId"), str) and resolved:
        updates["toolCallId"] = resolved
    return {**message, **updates} if updates else message


def normalize_openai_responses_tool_call_ids(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize assistant IDs and every persisted result alias consistently."""
    rewritten: dict[str, str] = {}

    def resolve(identifier):
        if identifier in rewritten:
            return rewritten[identifier]
        if not should_normalize_openai_responses_tool_call_id(identifier):
            return identifier
        normalized = normalize_openai_responses_function_call_id(identifier)
        rewritten[identifier] = normalized
        return normalized

    changed, out = False, []
    for message in messages:
        value = message
        if isinstance(message, Mapping):
            if message.get("role") == "assistant" and isinstance(message.get("content"), list):
                content, assistant_changed = [], False
                for block in message["content"]:
                    next_block = block
                    if (isinstance(block, Mapping) and block.get("type") in _TOOL_TYPES
                            and isinstance(block.get("id"), str)):
                        identifier = resolve(block["id"])
                        if identifier != block["id"]:
                            next_block = {**block, "id": identifier}
                            assistant_changed = True
                    content.append(next_block)
                if assistant_changed:
                    value = replace_compaction_replay_owner_content(message, content)
            elif message.get("role") == "toolResult":
                value = _rewrite_tool_result_ids(message, resolve)
        changed = changed or value is not message
        out.append(value)
    return out if changed else messages


def _parse_reasoning_signature(value):
    if not js_truthy(value):
        return None
    candidate = value
    if isinstance(value, str):
        trimmed = js_trim(value)
        if not trimmed.startswith("{") or not trimmed.endswith("}"):
            return None
        try:
            candidate = json.loads(trimmed, parse_constant=reject_json_constant)
        except (ValueError, TypeError):
            return None
    if not isinstance(candidate, Mapping):
        return None
    identifier, kind = candidate.get("id"), candidate.get("type")
    if (isinstance(identifier, str) and identifier.startswith("rs_")
            and isinstance(kind, str) and (kind == "reasoning" or kind.startswith("reasoning."))):
        return {"id": identifier, "type": kind}
    return None


def downgrade_openai_function_call_reasoning_pairs(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop ``|fc_*`` from calls lacking preceding replayable reasoning."""
    changed, out, pending = False, [], None
    for message in messages:
        if not isinstance(message, Mapping):
            pending = None
            out.append(message)
            continue
        role = message.get("role")
        if role == "assistant":
            if not isinstance(message.get("content"), list):
                pending = None
                out.append(message)
                continue
            local, content, seen_reasoning = {}, [], False
            for block in message["content"]:
                next_block = block
                if isinstance(block, Mapping):
                    if (block.get("type") == "thinking"
                            and _parse_reasoning_signature(block.get("thinkingSignature"))):
                        seen_reasoning = True
                    elif (block.get("type") in _TOOL_TYPES
                            and isinstance(block.get("id"), str)):
                        pairing = split_openai_function_call_pairing(block["id"])
                        if not seen_reasoning and pairing.get("itemId", "").startswith("fc_"):
                            local[block["id"]] = pairing["callId"]
                            next_block = {**block, "id": pairing["callId"]}
                content.append(next_block)
            pending = local or None
            if local:
                changed = True
                out.append(replace_compaction_replay_owner_content(message, content))
            else:
                out.append(message)
            continue
        if role == "toolResult" and pending:
            updates = {field: pending[message[field]] for field in ("toolCallId", "toolUseId")
                       if isinstance(message.get(field), str) and message[field] in pending
                       and pending[message[field]] != message[field]}
            if updates:
                changed = True
                out.append({**message, **updates})
            else:
                out.append(message)
            continue
        pending = None
        out.append(message)
    return out if changed else messages


def _parse_timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return value if math.isfinite(value) else None
        except OverflowError:
            return None
    if isinstance(value, str):
        parsed = js_date_parse(value)
        return parsed if math.isfinite(parsed) else None
    return None


def _text_signature_phase(signature):
    if not isinstance(signature, str):
        raise TypeError("textSignature.startsWith is not a function")
    if not signature.startswith("{"):
        return None
    try:
        parsed = json.loads(signature, parse_constant=reject_json_constant)
    except (ValueError, TypeError):
        return None
    if (isinstance(parsed, Mapping) and not isinstance(parsed.get("v"), bool)
            and parsed.get("v") == 1 and parsed.get("phase") in ("commentary", "final_answer")):
        return parsed["phase"]
    return None


def drop_stale_openai_reasoning(
    messages: list[dict[str, Any]], drop_before: int | float | None = None,
) -> list[dict[str, Any]]:
    """Remove stale Responses reasoning and paired text IDs after a route switch."""
    if drop_before is None:
        return messages
    changed, out = False, []
    for message in messages:
        if (not isinstance(message, Mapping) or message.get("role") != "assistant"
                or not isinstance(message.get("content"), list)):
            out.append(message)
            continue
        timestamp = _parse_timestamp(message.get("timestamp"))
        if timestamp is not None and timestamp > drop_before:
            out.append(message)
            continue
        content, message_changed, dropped_reasoning = [], False, False
        for block in message["content"]:
            if not js_truthy(block):
                message_changed = True
                continue
            if (isinstance(block, Mapping) and block.get("type") == "thinking"
                    and _parse_reasoning_signature(block.get("thinkingSignature"))):
                message_changed = dropped_reasoning = True
                continue
            content.append(block)
        if not message_changed:
            out.append(message)
            continue
        changed = True
        if not content:
            continue
        if dropped_reasoning:
            projected = []
            for block in content:
                if (isinstance(block, Mapping) and block.get("type") == "text"
                        and "textSignature" in block):
                    phase = _text_signature_phase(block["textSignature"])
                    block = {key: value for key, value in block.items() if key != "textSignature"}
                    if phase is not None:
                        block["textSignature"] = js_json_stringify({"v": 1, "phase": phase})
                projected.append(block)
            content = projected
        out.append(replace_compaction_replay_owner_content(message, content))
    return out if changed else messages
