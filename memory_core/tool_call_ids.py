"""Strict provider replay IDs, separate from executable and persisted call IDs.

Ports the occurrence-aware strict branch of OpenClaw's tool-call-id.ts. The
Mistral strict9 transport is deliberately unsupported by this owner.
"""
from collections import defaultdict, deque
from collections.abc import Mapping
import hashlib
import re
import time

from memory_core.bootstrap._js import js_trim, js_utf8_encode
from memory_core.replay_repair import (
    _completed_tool_call_predicate, _extract_tool_calls_from_assistant,
    _is_allowed_tool_call_name, _normalize_allowed_tool_names,
)

_TYPES = {"toolCall", "toolUse", "functionCall"}
_KIMI = re.compile(r"functions\.[A-Za-z0-9_-]+:[0-9]+\Z")
_ANTHROPIC = re.compile(r"toolu_[A-Za-z0-9_]+\Z")
_OPENAI = re.compile(r"call_[A-Za-z0-9_-]+\Z")
_RESULT_FIELDS = ("toolCallId", "toolUseId", "tool_call_id", "tool_use_id", "callId", "call_id")


def _hash(value, size):
    return hashlib.sha256(js_utf8_encode(value)).hexdigest()[:size]


def _unique(value, used):
    sanitized = value if _KIMI.fullmatch(value) else re.sub(r"[^a-zA-Z0-9]", "", value)
    base = (sanitized or ("defaulttoolid" if not value else "sanitizedtoolid"))[:40]
    if base not in used:
        return base
    candidate = base[:32] + _hash(value, 8)
    if candidate not in used:
        return candidate
    for ordinal in range(2, 1000):
        suffix = f"x{ordinal}"
        alternate = candidate[:40 - len(suffix)] + suffix
        if alternate not in used:
            return alternate
    suffix = f"t{time.time_ns() // 1_000_000}"
    return candidate[:40 - len(suffix)] + suffix


def _thinking_reservations(messages, allowed):
    reserved, preserved = set(), set()
    completed = _completed_tool_call_predicate(messages)
    for index, message in enumerate(messages):
        if not isinstance(message, Mapping) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        saw_thinking, saw_call, valid, seen = False, False, True, set()
        for block in content:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") in {"thinking", "redacted_thinking"}:
                saw_thinking = True
                continue
            if block.get("type") not in _TYPES:
                continue
            saw_call = True
            raw_id, name = block.get("id"), block.get("name")
            identifier = js_trim(raw_id) if isinstance(raw_id, str) else ""
            has_input = block.get("input") is not None or block.get("arguments") is not None
            if (not has_input or not identifier or identifier in seen
                    or not _is_allowed_tool_call_name(name, None if completed(block) else allowed)
                    or (isinstance(name, str) and bool(name) and name != js_trim(name))):
                valid = False
                break
            seen.add(identifier)
        if not (valid and saw_thinking and saw_call):
            continue
        calls = _extract_tool_calls_from_assistant(message)
        if any(identifier in reserved for identifier, _name in calls):
            continue
        preserved.add(index)
        reserved.update(identifier for identifier, _name in calls)
    return reserved, preserved


def sanitize_tool_call_ids(messages, mode="strict", *, preserve_native_anthropic_tool_use_ids=False,
                           duplicate_tool_call_id_style=None, preserve_replay_safe_thinking_tool_call_ids=False,
                           allowed_tool_names=None):
    """Return complete replay messages with paired occurrence-safe strict IDs.

    This transport projection never changes execution receipts or source rows.
    Unknown modes/styles fail explicitly instead of selecting another policy.
    """
    if mode != "strict":
        raise ValueError("Only the strict provider tool-call ID policy is supported")
    if duplicate_tool_call_id_style not in {None, "openai"}:
        raise ValueError("Unsupported duplicate tool-call ID style")
    allowed = _normalize_allowed_tool_names(allowed_tool_names)
    used, preserved = (_thinking_reservations(messages, allowed) if preserve_replay_safe_thinking_tool_call_ids
                       else (set(), set()))
    assistant_counts, orphan_counts, pending = defaultdict(int), defaultdict(int), defaultdict(deque)

    def allocate(seed):
        result = _unique(seed, used)
        used.add(result)
        return result

    def assistant_id(identifier, preserve=False):
        if preserve:
            used.add(identifier)
            pending[identifier].append(identifier)
            return identifier
        assistant_counts[identifier] += 1
        occurrence = assistant_counts[identifier]
        if duplicate_tool_call_id_style == "openai" and occurrence > 1:
            attempt = 0
            while True:
                result = "call_" + _hash(f"{identifier}:{occurrence}:{attempt}", 24)
                if result not in used:
                    used.add(result)
                    break
                attempt += 1
        elif (occurrence == 1 and identifier not in used and (
                (duplicate_tool_call_id_style == "openai" and _OPENAI.fullmatch(identifier))
                or (preserve_native_anthropic_tool_use_ids and _ANTHROPIC.fullmatch(identifier)))):
            result = identifier
            used.add(result)
        else:
            result = allocate(identifier if occurrence == 1 else f"{identifier}:{occurrence}")
        pending[identifier].append(result)
        return result

    def result_id(identifier):
        if pending[identifier]:
            return pending[identifier].popleft()
        orphan_counts[identifier] += 1
        occurrence = orphan_counts[identifier]
        if (preserve_native_anthropic_tool_use_ids and _ANTHROPIC.fullmatch(identifier)
                and occurrence == 1 and identifier not in used):
            used.add(identifier)
            return identifier
        return allocate(f"{identifier}:tool_result:{occurrence}")

    changed, output = False, []
    for index, message in enumerate(messages):
        value = message
        if not isinstance(message, Mapping):
            output.append(message)
            continue
        if message.get("role") == "assistant" and isinstance(message.get("content"), list):
            parts, different = [], False
            for block in message["content"]:
                identifier = block.get("id") if isinstance(block, Mapping) else None
                if isinstance(block, Mapping) and block.get("type") in _TYPES and isinstance(identifier, str) and identifier:
                    resolved = assistant_id(identifier, index in preserved)
                    if resolved != identifier:
                        block, different = {**block, "id": resolved}, True
                parts.append(block)
            if different:
                value = {**message, "content": parts}
        elif message.get("role") == "toolResult":
            identifiers = {key: message[key] for key in _RESULT_FIELDS
                           if isinstance(message.get(key), str) and message[key]}
            primary = next((identifiers[key] for key in ("call_id", "callId", "tool_call_id", "tool_use_id",
                                                        "toolCallId", "toolUseId") if key in identifiers), None)
            if primary is not None:
                resolved = result_id(primary)
                updates = {key: resolved for key, identifier in identifiers.items() if resolved != identifier}
                if not isinstance(message.get("toolCallId"), str) and resolved:
                    updates["toolCallId"] = resolved
                if updates:
                    value = {**message, **updates}
        changed = changed or value is not message
        output.append(value)
    return output if changed else messages
