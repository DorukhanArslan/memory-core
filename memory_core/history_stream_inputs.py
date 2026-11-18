"""Model-callback tool-input repair for unowned completion/Responses replay.

Ports the unsigned branch of ``sanitizeReplayToolCallInputs`` and its name
resolver from OpenClaw v2026.9.9's ``attempt-tool-call-replay-sanitization.ts``
and ``attempt-tool-call-name-resolution.ts``. This callback owner deliberately
differs from the persisted-history input sanitizer: it resolves offered tool
aliases and structured names, and does not interpret ``partialJson``.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
from typing import Any

from memory_core.bootstrap._js import JS_SPACE_CLASS, js_trim, js_truthy, utf16_len
from memory_core.compaction_replay import replace_compaction_replay_owner_content
from memory_core.replay_repair import _completed_tool_call_predicate

_RUNNER_TOOL_CALL_TYPES = frozenset({"toolCall", "toolUse", "functionCall"})
_TOOL_NAME_ALIASES = {"bash": "exec", "apply-patch": "apply_patch", "cron": "automations"}
_TOOL_NAME_MAX_CHARS = 64
_JS_SPACE = re.compile(f"[{JS_SPACE_CLASS}]")
_COUNTER_SEPARATOR = re.compile(r"[:._/-][0-9]+$")
_COUNTER = re.compile(r"[0-9]+$")
_TOOL_PREFIXES = (re.compile(r"^functions?[._-]?", re.IGNORECASE | re.ASCII),
                  re.compile(r"^tools?[._-]?", re.IGNORECASE | re.ASCII))
_MALFORMED_PREFIX = re.compile(r"^(?:functions?|tools?)[._-]?", re.IGNORECASE | re.ASCII)
_MALFORMED_COUNTER = re.compile(r"(?:[:._-][0-9]+|[0-9]+)$")


@dataclass(frozen=True)
class ReplayToolCallSanitizeReport:
    """The actual callback input and count of assistant rows repair removed."""

    messages: list[Any]
    dropped_assistant_messages: int


def _normalized_policy_name(name: str) -> str:
    folded = js_trim(name).lower()
    return _TOOL_NAME_ALIASES.get(folded, folded)


def _case_insensitive_allowed_name(raw_name: str, allowed: tuple[str, ...]) -> str | None:
    folded = js_trim(raw_name).lower()
    match = None
    for name in allowed:
        if js_trim(name).lower() != folded:
            continue
        if match and match != name:
            return None
        match = name
    return match


def _exact_allowed_name(raw_name: str, allowed: tuple[str, ...]) -> str | None:
    if raw_name in allowed:
        return raw_name
    normalized = _normalized_policy_name(raw_name)
    if normalized in allowed:
        return normalized
    return (_case_insensitive_allowed_name(raw_name, allowed)
            or _case_insensitive_allowed_name(normalized, allowed))


def _structured_name_candidates(raw_name: str) -> list[str]:
    trimmed = js_trim(raw_name)
    if not trimmed:
        return []
    candidates: dict[str, None] = {}

    def add_candidate(value: str) -> None:
        candidate = js_trim(value)
        if candidate:
            candidates[candidate] = None
            candidates[_normalized_policy_name(candidate)] = None

    add_candidate(trimmed)
    seeds = [trimmed]
    offsets = [offset for separator in ('"', "'", "<")
               if (offset := trimmed.find(separator)) > 0]
    if offsets:
        prefix = trimmed[:min(offsets)]
        add_candidate(prefix)
        seeds.append(prefix)
    for seed in seeds:
        normalized_delimiter = seed.replace("/", ".")
        add_candidate(normalized_delimiter)
        segments = [normalized for segment in normalized_delimiter.split(".")
                    if (normalized := js_trim(segment))]
        for index in range(1, len(segments)):
            add_candidate(".".join(segments[index:]))
    return list(candidates)


def _structured_allowed_name(raw_name: str, allowed: tuple[str, ...]) -> str | None:
    candidates = _structured_name_candidates(raw_name)
    for candidate in candidates:
        if candidate in allowed:
            return candidate
    for candidate in candidates:
        match = _case_insensitive_allowed_name(candidate, allowed)
        if match:
            return match
    return None


def _infer_name_from_call_id(raw_id: str | None, allowed: tuple[str, ...] | None) -> str | None:
    if not raw_id or not allowed:
        return None
    identifier = js_trim(raw_id)
    if not identifier:
        return None
    candidates: dict[str, None] = {}

    def add_counter_variants(value: str) -> None:
        candidates[value] = None
        candidates[_COUNTER_SEPARATOR.sub("", value)] = None
        candidates[_COUNTER.sub("", value)] = None

    def add_token(value: str) -> None:
        trimmed = js_trim(value)
        if not trimmed:
            return
        normalized_delimiter = trimmed.replace("/", ".")
        add_counter_variants(trimmed)
        add_counter_variants(normalized_delimiter)
        for pattern in _TOOL_PREFIXES:
            stripped = pattern.sub("", normalized_delimiter, count=1)
            if stripped != normalized_delimiter:
                add_counter_variants(stripped)

    for seed in (identifier, identifier.split(":")[0]):
        add_token(seed)
    single_match = None
    for candidate in candidates:
        match = _structured_allowed_name(candidate, allowed)
        if not match:
            continue
        if single_match and single_match != match:
            return None
        single_match = match
    return single_match


def _resolve_tool_call_name(raw_name: str, allowed: tuple[str, ...] | None,
                            raw_call_id: str) -> str | None:
    """``resolveToolCallName`` with its callback's ``requireAllowed=true``."""
    trimmed = js_trim(raw_name)
    if not trimmed:
        return _infer_name_from_call_id(raw_call_id, allowed)
    if not allowed:
        return trimmed
    exact = _exact_allowed_name(trimmed, allowed)
    if exact:
        return exact
    inferred = _infer_name_from_call_id(trimmed, allowed)
    if inferred:
        return inferred
    normalized_delimiter = trimmed.replace("/", ".")
    if _MALFORMED_PREFIX.search(normalized_delimiter) and _MALFORMED_COUNTER.search(normalized_delimiter):
        return None
    return _structured_allowed_name(trimmed, allowed)


def _resolve_replay_tool_call_name(raw_name: str, raw_id: str,
                                  allowed: tuple[str, ...] | None) -> str | None:
    if utf16_len(raw_name) > _TOOL_NAME_MAX_CHARS * 2:
        return None
    normalized = _resolve_tool_call_name(raw_name, allowed, raw_id)
    if not normalized:
        return None
    trimmed = js_trim(normalized)
    if not trimmed or utf16_len(trimmed) > _TOOL_NAME_MAX_CHARS or _JS_SPACE.search(trimmed):
        return None
    return trimmed


def sanitize_replay_tool_call_inputs(
    messages: list[Any], allowed_tool_names: Iterable[str] | None = None,
) -> ReplayToolCallSanitizeReport:
    """Resolve/drop callback tool inputs, preserving unchanged rows and input list.

    Completed occurrences retain historical tools outside the currently offered
    registry. The source's provider-owned signed-thinking branch is not selected
    by this unsigned completion/Responses owner.
    """
    allowed = tuple(dict.fromkeys(allowed_tool_names)) if allowed_tool_names is not None else None
    completed = _completed_tool_call_predicate(messages)
    changed = False
    dropped_assistant_messages = 0
    out: list[Any] = []
    for message in messages:
        if not js_truthy(message):
            changed = True
            continue
        if (not isinstance(message, Mapping) or message.get("role") != "assistant"
                or not isinstance(message.get("content"), list)):
            out.append(message)
            continue
        next_content = []
        message_changed = False
        for block in message["content"]:
            if not isinstance(block, Mapping) or block.get("type") not in _RUNNER_TOOL_CALL_TYPES:
                next_content.append(block)
                continue
            identifier = block.get("id")
            if ((block.get("input") is None and block.get("arguments") is None)
                    or not isinstance(identifier, str) or not js_trim(identifier)):
                message_changed = True
                continue
            raw_name = block.get("name") if isinstance(block.get("name"), str) else ""
            resolved = _resolve_replay_tool_call_name(raw_name, identifier, None if completed(block) else allowed)
            if not resolved:
                message_changed = True
                continue
            if block.get("name") != resolved:
                message_changed = True
                next_content.append({**block, "name": resolved})
            else:
                next_content.append(block)
        changed = changed or message_changed
        if not next_content and message_changed:
            dropped_assistant_messages += 1
            continue
        out.append(replace_compaction_replay_owner_content(message, next_content)
                   if message_changed else message)
    return ReplayToolCallSanitizeReport(out if changed else messages, dropped_assistant_messages)


__all__ = ["ReplayToolCallSanitizeReport", "sanitize_replay_tool_call_inputs"]
