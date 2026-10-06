"""Prompt projection of tool results at v2026.9.6: cache-TTL pruning, frozen keys, replay.

Ports the projection half of ``src/agents/embedded-agent-runner/tool-result-truncation.ts`` and
``session-prompt-state.ts``: the per-session :class:`ToolResultPromptProjectionState`
(``replacements``, ``frozen``, ``ambiguousBaseKeys``, ``sourceHashByKey``, ``restoredCacheTtl``),
the key resolution (``getToolResultProjectionKeys``), ``projectToolResultBranch`` (private
upstream, reached through the exported functions below), cache-TTL pruning
(``pruneExpiredCacheTtlToolResults``), the transcript marker (``restoreCacheTtlToolResultProjections``,
``serializeCacheTtlToolResultProjections``, ``persistToolResultProjections``), reconciliation after
a canonical rewrite (``reconcileToolResultPromptProjectionState``) and the projecting variant of
``truncateOversizedToolResultsInMessages``. The budget and plan code stays in
:mod:`memory_core.preemptive_compaction` and :mod:`memory_core._tool_result_budget`.

Deviation: upstream stores the projection key on the message object as a symbol property;
here it is the ``projection_key`` attribute of :class:`~memory_core.preemptive_compaction.ProjectedMessage`.
"""

from __future__ import annotations

import base64
import hashlib
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from memory_core._tool_result_budget import estimate_string_chars
from memory_core.bootstrap._js import (
    js_json_stringify,
    js_trim,
    slice_utf16_safe,
    utf16_len,
)
from memory_core.heartbeat import parse_duration_ms
from memory_core.preemptive_compaction import (
    RECOVERY_MIN_KEEP_CHARS,
    ProjectedMessage,
    _recovery_aggregate_tool_result_chars,
    build_tool_result_replacement_plan,
    calculate_max_tool_result_chars,
    spread_message,
)

CACHE_TTL_CUSTOM_TYPE = "openclaw.cache-ttl"
CACHE_TTL_IMAGE_CHARS = 8_000
CACHE_TTL_IMAGE_MARKER = "[image removed during context pruning]"
CACHE_TTL_DEFAULT_PLACEHOLDER = "[Old tool result content cleared]"
OMITTED_ASSISTANT_REASONING_TEXT = "[assistant reasoning omitted]"

_UNSET: Any = object()


@dataclass
class ToolResultPromptProjectionState:
    """``ToolResultPromptProjectionState`` (session-prompt-state.ts), insertion-ordered like JS."""

    # key -> {"content": [...], "cacheTtl": "soft" | "hard" | None}
    replacements: dict[str, dict[str, Any]] = field(default_factory=dict)
    frozen: set[str] = field(default_factory=set)
    ambiguous_base_keys: dict[str, None] = field(default_factory=dict)
    source_hash_by_key: dict[str, str] = field(default_factory=dict)
    # key -> {"mode": "soft"} | {"mode": "hard", "placeholder": str}
    restored_cache_ttl: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_written_snapshot_hash: str | None = None


def create_tool_result_prompt_projection_state() -> ToolResultPromptProjectionState:
    return ToolResultPromptProjectionState()


def clone_tool_result_prompt_projection_state(
    state: ToolResultPromptProjectionState,
) -> ToolResultPromptProjectionState:
    return ToolResultPromptProjectionState(
        replacements=dict(state.replacements),
        frozen=set(state.frozen),
        ambiguous_base_keys=dict(state.ambiguous_base_keys),
        source_hash_by_key=dict(state.source_hash_by_key),
        restored_cache_ttl=dict(state.restored_cache_ttl),
        last_written_snapshot_hash=state.last_written_snapshot_hash,
    )


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _is_text_block(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") == "text" and isinstance(
        block.get("text"), str
    )


def record_tool_result_prompt_projection(
    state: ToolResultPromptProjectionState,
    key: str,
    message: dict[str, Any],
    cache_ttl: Any = _UNSET,
) -> None:
    if cache_ttl is _UNSET:
        previous = state.replacements.get(key)
        cache_ttl = previous.get("cacheTtl") if previous else None
    content = message.get("content")
    content = content if isinstance(content, list) else []
    # Ordinary replay merges canonical metadata and non-text blocks; TTL owns exact content.
    state.replacements[key] = {
        "cacheTtl": cache_ttl,
        "content": content
        if cache_ttl
        else [{"type": "text", "text": block["text"]} for block in content if _is_text_block(block)],
    }


def serialize_cache_ttl_tool_result_projections(
    state: ToolResultPromptProjectionState,
) -> dict[str, Any]:
    marks: dict[str, dict[str, Any]] = dict(state.restored_cache_ttl)
    for key, projection in state.replacements.items():
        cache_ttl = projection.get("cacheTtl")
        if cache_ttl == "soft":
            marks[key] = {"mode": "soft"}
        elif cache_ttl == "hard":
            marks[key] = {
                "mode": "hard",
                "placeholder": "\n".join(
                    block["text"] if isinstance(block.get("text"), str) else ""
                    for block in projection["content"]
                    if isinstance(block, dict) and block.get("type") == "text"
                ),
            }
    frozen_results: list[dict[str, Any]] = []
    for key, source_hash in state.source_hash_by_key.items():
        if key not in state.frozen:
            continue
        projection = state.replacements.get(key)
        item: dict[str, Any] = {"key": key, "sourceHash": source_hash}
        if projection is not None and not projection.get("cacheTtl"):
            item["texts"] = [
                block["text"]
                for block in projection["content"]
                if isinstance(block, dict) and block.get("type") == "text" and "text" in block
            ]
        frozen_results.append(item)
    return {
        "prunedToolResults": [{"key": key, **mark} for key, mark in marks.items()],
        "ambiguousToolResultBaseKeys": list(state.ambiguous_base_keys),
        "frozenToolResults": frozen_results,
    }


def hash_tool_result_projection_snapshot(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(js_json_stringify(snapshot).encode("utf-8")).hexdigest()


def persist_tool_result_projections(
    state: ToolResultPromptProjectionState, append_entry: Callable[[str, Any], None]
) -> None:
    if not state.frozen:
        return
    snapshot = serialize_cache_ttl_tool_result_projections(state)
    snapshot_hash = hash_tool_result_projection_snapshot(snapshot)
    if snapshot_hash == state.last_written_snapshot_hash:
        return
    append_entry(CACHE_TTL_CUSTOM_TYPE, snapshot)
    # A failed owned write must leave the snapshot eligible for persistence.
    state.last_written_snapshot_hash = snapshot_hash


# --- keys and hashes -------------------------------------------------------------------------


def _js_number_to_string(value: int | float) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        if value.is_integer() and abs(value) < 1e21:
            return str(int(value))
        return repr(value)
    return str(value)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def get_tool_result_projection_base_key(message: Any) -> str | None:
    if not isinstance(message, dict) or message.get("role") != "toolResult":
        return None
    tool_call_id = message.get("toolCallId")
    timestamp = message.get("timestamp")
    timestamp_key = f":{_js_number_to_string(timestamp)}" if _is_number(timestamp) else ""
    if isinstance(tool_call_id, str) and tool_call_id:
        return f"tool:{tool_call_id}{timestamp_key}"
    return f"timestamp:{_js_number_to_string(timestamp)}" if _is_number(timestamp) else None


def get_tool_result_text_blocks(message: Any) -> list[str]:
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return []
    return [
        block["text"] if isinstance(block.get("text"), str) else ""
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]


def hash_tool_result_text(texts: list[str]) -> str:
    # JSON framing preserves block boundaries and lone surrogates, including persisted fallback keys.
    digest = hashlib.sha256(js_json_stringify(texts).encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def get_tool_result_projection_keys(
    messages: Sequence[Any], state: ToolResultPromptProjectionState
) -> list[str | None]:
    base_keys = [get_tool_result_projection_base_key(message) for message in messages]
    base_key_counts: dict[str, int] = {}
    for base_key in base_keys:
        if base_key:
            count = base_key_counts.get(base_key, 0) + 1
            base_key_counts[base_key] = count
            if count > 1:
                state.ambiguous_base_keys[base_key] = None
    occurrences: dict[str, int] = {}
    keys: list[str | None] = []
    for index, base_key in enumerate(base_keys):
        message = messages[index]
        carried = getattr(message, "projection_key", None)
        if isinstance(carried, str):
            keys.append(carried)
            continue
        if base_key and base_key not in state.ambiguous_base_keys:
            keys.append(base_key)
            continue
        if not isinstance(message, dict) or message.get("role") != "toolResult":
            keys.append(None)
            continue
        # Stable identities keep ambiguous tool ids from rewriting cache-tail projections (#99495).
        message_id = message.get("id")
        source_identity = (
            f"id:{message_id}"
            if isinstance(message_id, str) and message_id
            else f"text:{hash_tool_result_text(get_tool_result_text_blocks(message))}"
        )
        fallback_base = f"fallback:{base_key or 'tool'}:{source_identity}"
        occurrence = occurrences.get(fallback_base, 0)
        occurrences[fallback_base] = occurrence + 1
        key = f"{fallback_base}:{occurrence}"
        previous_source = state.source_hash_by_key.get(base_key) if base_key else None
        if (
            base_key
            and previous_source
            and previous_source == hash_tool_result_text(get_tool_result_text_blocks(message))
        ):
            # A later duplicate must move the original projection, not make its sent bytes vanish.
            replacement = state.replacements.get(base_key)
            if replacement is not None:
                state.replacements[key] = replacement
                del state.replacements[base_key]
            state.source_hash_by_key[key] = previous_source
            del state.source_hash_by_key[base_key]
            if base_key in state.frozen:
                state.frozen.discard(base_key)
                state.frozen.add(key)
        keys.append(key)
    return keys


# --- transcript marker -----------------------------------------------------------------------


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _parse_cache_ttl_snapshot(data: Any) -> dict[str, Any] | None:
    """``cacheTtlProjectionSnapshotSchema.safeParse``: strips unknown keys, None on a mismatch."""

    if not isinstance(data, dict) or not isinstance(data.get("prunedToolResults"), list):
        return None
    pruned: list[dict[str, Any]] = []
    for item in data["prunedToolResults"]:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            return None
        if item.get("mode") == "soft":
            pruned.append({"key": item["key"], "mode": "soft"})
        elif item.get("mode") == "hard" and isinstance(item.get("placeholder"), str):
            pruned.append({"key": item["key"], "mode": "hard", "placeholder": item["placeholder"]})
        else:
            return None
    parsed: dict[str, Any] = {"prunedToolResults": pruned}
    if "ambiguousToolResultBaseKeys" in data:
        if not _is_string_list(data["ambiguousToolResultBaseKeys"]):
            return None
        parsed["ambiguousToolResultBaseKeys"] = list(data["ambiguousToolResultBaseKeys"])
    if "frozenToolResults" in data:
        frozen = data["frozenToolResults"]
        if not isinstance(frozen, list):
            return None
        parsed_frozen: list[dict[str, Any]] = []
        for item in frozen:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("key"), str)
                or not isinstance(item.get("sourceHash"), str)
            ):
                return None
            entry: dict[str, Any] = {"key": item["key"], "sourceHash": item["sourceHash"]}
            if "texts" in item:
                if not _is_string_list(item["texts"]):
                    return None
                entry["texts"] = list(item["texts"])
            parsed_frozen.append(entry)
        parsed["frozenToolResults"] = parsed_frozen
    return parsed


def restore_cache_ttl_tool_result_projections(
    state: ToolResultPromptProjectionState, entries: Sequence[Any]
) -> None:
    """Reads pruned keys from the active transcript branch, never from a sibling branch."""

    state.last_written_snapshot_hash = None
    for entry in reversed(entries):
        entry_type = entry.get("type") if isinstance(entry, dict) else None
        if entry_type == "reset":
            return
        if entry_type != "custom" or entry.get("customType") != CACHE_TTL_CUSTOM_TYPE:
            continue
        parsed = _parse_cache_ttl_snapshot(entry.get("data"))
        if parsed is None:
            continue
        state.last_written_snapshot_hash = hash_tool_result_projection_snapshot(
            {
                "prunedToolResults": parsed["prunedToolResults"],
                "ambiguousToolResultBaseKeys": parsed.get("ambiguousToolResultBaseKeys", []),
                "frozenToolResults": parsed.get("frozenToolResults", []),
            }
        )
        for key in parsed.get("ambiguousToolResultBaseKeys", []):
            state.ambiguous_base_keys[key] = None
        for item in parsed.get("frozenToolResults", []):
            key = item["key"]
            # A live attempt can be ahead of its last marker; never roll it back.
            if key in state.source_hash_by_key:
                continue
            state.source_hash_by_key[key] = item["sourceHash"]
            state.frozen.add(key)
            if "texts" in item:
                state.replacements[key] = {
                    "cacheTtl": None,
                    "content": [{"type": "text", "text": text} for text in item["texts"]],
                }
        for mark in parsed["prunedToolResults"]:
            key = mark["key"]
            replacement = state.replacements.get(key)
            if not (replacement and replacement.get("cacheTtl")):
                state.restored_cache_ttl[key] = {k: v for k, v in mark.items() if k != "key"}
        return


def reconcile_tool_result_prompt_projection_state(
    messages: Sequence[Any], state: ToolResultPromptProjectionState
) -> None:
    """Drops projections whose source messages were removed or rewritten in canonical history."""

    keys = get_tool_result_projection_keys(messages, state)
    canonical_keys: set[str] = set()
    for index, message in enumerate(messages):
        key = keys[index]
        source = state.source_hash_by_key.get(key) if key else None
        if key and (not source or source == hash_tool_result_text(get_tool_result_text_blocks(message))):
            canonical_keys.add(key)
    for key in [*state.frozen, *state.replacements, *state.source_hash_by_key]:
        if key not in canonical_keys:
            state.frozen.discard(key)
            state.replacements.pop(key, None)
            state.source_hash_by_key.pop(key, None)
    represented = {get_tool_result_projection_base_key(message) for message in messages}
    for base_key in list(state.ambiguous_base_keys):
        if base_key not in represented:
            del state.ambiguous_base_keys[base_key]


# --- projection of a branch ------------------------------------------------------------------


def _soft_prune_cache_ttl_tool_result(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    content = content if isinstance(content, list) else []
    has_image = any(isinstance(block, dict) and block.get("type") == "image" for block in content)
    parts: list[str] = []
    for block in content:
        text = _cache_ttl_text(block)
        if text is not None:
            parts.append(text)
        elif isinstance(block, dict) and block.get("type") == "image":
            parts.append(CACHE_TTL_IMAGE_MARKER)
    text = "\n".join(parts)
    length = utf16_len(text)
    if not has_image and length <= 4_000:
        return message
    projected = (
        text
        if length <= 4_000
        else (
            f"{slice_utf16_safe(text, 0, 1_500)}\n...\n{slice_utf16_safe(text, -1_500)}\n\n"
            f"[Tool result trimmed: kept first 1500 chars and last 1500 chars of {length} chars.]"
        )
    )
    return spread_message(message, {"content": [{"type": "text", "text": projected}]})


def _merge_projected_tool_result_message(
    message: dict[str, Any],
    projected_content: Any,
    source_hash: str | None,
    cache_ttl: str | None = None,
) -> dict[str, Any]:
    if message.get("role") != "toolResult":
        return message
    current_content = message.get("content")
    if not isinstance(current_content, list) or not isinstance(projected_content, list):
        return spread_message(message, {"content": projected_content})
    projected_text = [block["text"] for block in projected_content if _is_text_block(block)]
    current_text = get_tool_result_text_blocks(message)
    if source_hash and hash_tool_result_text(current_text) != source_hash:
        return message
    if cache_ttl:
        return spread_message(message, {"content": projected_content})
    if len(current_text) != len(projected_text):
        return message
    text_index = 0
    merged: list[Any] = []
    for block in current_content:
        if not isinstance(block, dict) or block.get("type") != "text":
            merged.append(block)
            continue
        merged.append({**block, "text": projected_text[text_index]})
        text_index += 1
    return spread_message(message, {"content": merged})


def _materialize_restored_cache_ttl(
    messages: Sequence[dict[str, Any]],
    keys: Sequence[str | None],
    state: ToolResultPromptProjectionState,
) -> None:
    """Restored marker keys become replacements here, at the owner every replay path uses."""

    if not state.restored_cache_ttl:
        return
    for index, message in enumerate(messages):
        key = keys[index]
        if not key or message.get("role") != "toolResult":
            continue
        existing = state.replacements.get(key)
        if existing and existing.get("cacheTtl"):
            continue
        base_key = get_tool_result_projection_base_key(message)
        exact = state.restored_cache_ttl.get(key)
        mark = exact if exact is not None else (
            state.restored_cache_ttl.get(base_key) if base_key else None
        )
        if mark is None:
            continue
        if exact is None and base_key:
            # A key persisted before its tool id became ambiguous belongs to the earliest occurrence.
            del state.restored_cache_ttl[base_key]
        projected = (
            spread_message(message, {"content": [{"type": "text", "text": mark["placeholder"]}]})
            if mark["mode"] == "hard"
            else _soft_prune_cache_ttl_tool_result(message)
        )
        record_tool_result_prompt_projection(state, key, projected, mark["mode"])
        state.frozen.add(key)
        if key not in state.source_hash_by_key:
            state.source_hash_by_key[key] = hash_tool_result_text(get_tool_result_text_blocks(message))
    # Marks whose source left the branch (compaction, reset) are dropped with this pass.
    state.restored_cache_ttl.clear()


def project_tool_result_branch(
    *,
    branch: Sequence[dict[str, Any]],
    projection_state: ToolResultPromptProjectionState,
    frozen_only: bool = False,
    record_sources: bool = False,
) -> tuple[list[dict[str, Any]], list[str | None]]:
    """``projectToolResultBranch``: returns the projected branch and the per-message keys."""

    messages = [
        entry["message"]
        for entry in branch
        if entry.get("type") == "message" and entry.get("message") is not None
    ]
    keys = get_tool_result_projection_keys(messages, projection_state)
    _materialize_restored_cache_ttl(messages, keys, projection_state)
    message_index = 0
    out: list[dict[str, Any]] = []
    for entry in branch:
        if entry.get("type") != "message" or entry.get("message") is None:
            out.append(entry)
            continue
        key = keys[message_index]
        message_index += 1
        frozen = key is not None and key in projection_state.frozen
        projected = (
            projection_state.replacements.get(key) if key and (not frozen_only or frozen) else None
        )
        if key and record_sources and key not in projection_state.source_hash_by_key:
            projection_state.source_hash_by_key[key] = hash_tool_result_text(
                get_tool_result_text_blocks(entry["message"])
            )
        message = entry["message"]
        if projected is not None:
            message = _merge_projected_tool_result_message(
                entry["message"],
                projected["content"],
                projection_state.source_hash_by_key.get(key) if key else None,
                projected.get("cacheTtl"),
            )
        if key and projected is not None and projected.get("cacheTtl") and message is not entry["message"]:
            # Carry canonical identity through content edits, including duplicate or absent tool ids.
            carried = ProjectedMessage(message)
            carried.projection_key = key
            message = carried
        out.append(
            {
                **entry,
                "message": message,
                # Frozen bytes are immutable on dispatch projections; recovery projections
                # (frozen_only) run after a provider context failure, so frozen history must
                # stay reducible.
                "aggregateEligible": frozen_only or not key or not frozen,
            }
        )
    return out, keys


# --- cache-TTL pruning -----------------------------------------------------------------------


@dataclass(frozen=True)
class CacheTtlPruningSettings:
    ttl_ms: int
    hard_clear: bool
    placeholder: str
    is_tool_prunable: Callable[[str], bool]


def _normalize_lower(value: Any) -> str:
    return js_trim(value).lower() if isinstance(value, str) else ""


# JS ``.`` without the s flag: anything but the four line terminators.
_JS_ANY_STAR = "[^\\n\\r\\u2028\\u2029]*"


def _compile_glob(raw: Any) -> tuple[str, str] | None:
    normalized = _normalize_lower(raw)
    if not normalized:
        return None
    if normalized == "*":
        return ("all", "")
    if "*" not in normalized:
        return ("exact", normalized)
    parts = (re.escape(part) for part in normalized.split("*"))
    return ("regex", "^" + _JS_ANY_STAR.join(parts) + "\\Z")


def _compile_glob_patterns(raw: Any) -> list[tuple[str, Any]]:
    if not isinstance(raw, list):
        return []
    compiled: list[tuple[str, Any]] = []
    for item in raw:
        pattern = _compile_glob(item)
        if pattern is None:
            continue
        kind, value = pattern
        compiled.append((kind, re.compile(value) if kind == "regex" else value))
    return compiled


def _matches_any_glob(value: str, patterns: list[tuple[str, Any]]) -> bool:
    for kind, pattern in patterns:
        if kind == "all":
            return True
        if kind == "exact" and value == pattern:
            return True
        if kind == "regex" and pattern.search(value):
            return True
    return False


def resolve_cache_ttl_pruning_settings(config: Any) -> CacheTtlPruningSettings | None:
    """``resolveCacheTtlPruningSettings`` for an ``AgentContextPruningConfig`` mapping."""

    if not isinstance(config, dict) or config.get("mode") != "cache-ttl":
        return None
    ttl_ms = 5 * 60_000
    try:
        ttl = config.get("ttl")
        if ttl:
            ttl_ms = parse_duration_ms(ttl, default_unit="m")
    except (ValueError, TypeError):
        pass  # Invalid durations retain the shipped five-minute default.
    tools = config.get("tools") if isinstance(config.get("tools"), dict) else {}
    deny = _compile_glob_patterns(tools.get("deny"))
    allow = _compile_glob_patterns(tools.get("allow"))
    hard_clear = config.get("hardClear") if isinstance(config.get("hardClear"), dict) else {}
    enabled = hard_clear.get("enabled")
    placeholder = hard_clear.get("placeholder")
    trimmed = js_trim(placeholder) if isinstance(placeholder, str) else ""

    def is_tool_prunable(tool_name: str) -> bool:
        normalized = _normalize_lower(tool_name)
        return not _matches_any_glob(normalized, deny) and (
            not allow or _matches_any_glob(normalized, allow)
        )

    return CacheTtlPruningSettings(
        ttl_ms=ttl_ms,
        hard_clear=True if enabled is None else bool(enabled),
        placeholder=trimmed or CACHE_TTL_DEFAULT_PLACEHOLDER,
        is_tool_prunable=is_tool_prunable,
    )


def _cache_ttl_text(block: Any, serialize_malformed: bool = True) -> str | None:
    if not isinstance(block, dict) or block.get("type") != "text":
        return None
    if isinstance(block.get("text"), str):
        return block["text"]
    if not serialize_malformed:
        return None
    return js_json_stringify(block)


def _cache_ttl_message_chars(message: dict[str, Any]) -> int:
    role = message.get("role")
    if role == "user" and isinstance(message.get("content"), str):
        return int(estimate_string_chars(message["content"]))
    if role not in ("user", "assistant", "toolResult"):
        return 256
    content = message.get("content")
    content = content if isinstance(content, list) else []
    chars = 0
    for block in content:
        if not isinstance(block, dict):
            continue
        text = _cache_ttl_text(block, role != "assistant")
        if text is not None:
            chars += int(estimate_string_chars(text))
            continue
        if block.get("type") == "image":
            chars += CACHE_TTL_IMAGE_CHARS
            continue
        if role != "assistant":
            continue
        block_type = block.get("type")
        if block_type in ("thinking", "redacted_thinking"):
            values = [
                block.get("thinking"),
                block.get("thinkingSignature"),
                *([block.get("data")] if block_type == "redacted_thinking" else []),
            ]
            chars += sum(
                int(estimate_string_chars(value)) for value in values if isinstance(value, str)
            )
            continue
        if block_type != "toolCall":
            continue
        arguments = block.get("arguments")
        chars += utf16_len(js_json_stringify({} if arguments is None else arguments))
    return chars


def _ratio(numerator: int | float, denominator: int | float) -> float:
    """JS ``a / b``: division by zero is ``Infinity`` or ``NaN``, never an exception."""

    if denominator == 0:
        return math.nan if numerator == 0 else math.inf
    return numerator / denominator


def _is_thinking_block(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") in ("thinking", "redacted_thinking")


def drop_thinking_blocks(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``dropThinkingBlocks`` (thinking.ts): the latest assistant turn keeps its reasoning."""

    def has_content(message: Any) -> bool:
        return (
            isinstance(message, dict)
            and message.get("role") == "assistant"
            and isinstance(message.get("content"), list)
        )

    latest = -1
    for index in range(len(messages) - 1, -1, -1):
        if has_content(messages[index]):
            latest = index
            break
    touched = False
    out: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not has_content(message) or index == latest:
            out.append(message)
            continue
        next_content = [block for block in message["content"] if not _is_thinking_block(block)]
        if len(next_content) == len(message["content"]):
            out.append(message)
            continue
        touched = True
        out.append(
            spread_message(
                message,
                {
                    "content": next_content
                    or [{"type": "text", "text": OMITTED_ASSISTANT_REASONING_TEXT}]
                },
            )
        )
    return out if touched else messages


def _planning_branch(messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """``buildToolResultPlanningBranch``: no tool results means nothing can be planned."""

    if not any(isinstance(m, dict) and m.get("role") == "toolResult" for m in messages):
        return []
    return [
        {"id": f"message-{index}", "type": "message", "message": message}
        for index, message in enumerate(messages)
    ]


def prune_expired_cache_ttl_tool_results(
    *,
    messages: list[dict[str, Any]],
    settings: CacheTtlPruningSettings,
    context_window_tokens: int | float,
    last_cache_touch_at: int | float | None,
    drop_thinking_blocks_for_estimate: bool,
    now: int | float,
    projection_state: ToolResultPromptProjectionState,
    prune_new_rounds: bool,
    on_pruned: Callable[[], None] | None = None,
) -> list[dict[str, Any]]:
    """Projects expired cache-TTL history without mutating the transcript."""

    projection_branch, keys = project_tool_result_branch(
        branch=_planning_branch(messages),
        projection_state=projection_state,
        record_sources=True,
    )
    projected_messages = [
        projection_branch[index]["message"] if index < len(projection_branch) else message
        for index, message in enumerate(messages)
    ]
    unchanged = (
        projected_messages
        if any(a is not b for a, b in zip(projected_messages, messages, strict=True))
        else messages
    )
    next_messages: list[dict[str, Any]] | None = None

    def record_projection(index: int, message: dict[str, Any], mode: str) -> None:
        nonlocal next_messages
        key = keys[index] if index < len(keys) else None
        replacement = message
        if key:
            replacement = ProjectedMessage(message)
            replacement.projection_key = key
            # TTL gates new edits only: replay these bytes until their source leaves the session.
            record_tool_result_prompt_projection(projection_state, key, replacement, mode)
            projection_state.frozen.add(key)
        if next_messages is None:
            next_messages = list(projected_messages)
        next_messages[index] = replacement

    if (
        not prune_new_rounds
        or not last_cache_touch_at
        or settings.ttl_ms <= 0
        or now - last_cache_touch_at < settings.ttl_ms
    ):
        return next_messages if next_messages is not None else unchanged
    assistant_indexes = [i for i, m in enumerate(projected_messages) if m.get("role") == "assistant"]
    cutoff = assistant_indexes[-3] if len(assistant_indexes) >= 3 else -1
    start = next((i for i, m in enumerate(projected_messages) if m.get("role") == "user"), -1)
    if cutoff < 0 or start < 0:
        return next_messages if next_messages is not None else unchanged
    estimate = (
        drop_thinking_blocks(projected_messages)
        if drop_thinking_blocks_for_estimate
        else projected_messages
    )
    # Thinking removal preserves positions; reuse costs only within this pruning pass.
    message_chars = [_cache_ttl_message_chars(message) for message in estimate]
    total_chars: int | float = sum(message_chars)
    char_window = context_window_tokens * 4
    if _ratio(total_chars, char_window) < 0.3:
        return next_messages if next_messages is not None else unchanged
    pruned = False
    eligible: list[dict[str, int]] = []
    for index in range(start, cutoff):
        message = projected_messages[index]
        tool_name = message.get("toolName")
        if message.get("role") != "toolResult" or not settings.is_tool_prunable(
            tool_name if isinstance(tool_name, str) else ""
        ):
            continue
        key = keys[index] if index < len(keys) else None
        previous = projection_state.replacements.get(key) if key else None
        previous_mode = previous.get("cacheTtl") if previous else None
        if previous_mode == "hard":
            continue
        candidate = {"index": index, "chars": message_chars[index]}
        eligible.append(candidate)
        if previous_mode == "soft":
            continue
        # Trim the canonical source, not the oversized projection, so a restart re-derives identical bytes.
        source = messages[index]
        projected = _soft_prune_cache_ttl_tool_result(source) if source.get("role") == "toolResult" else source
        if projected is not source and projected.get("role") == "toolResult":
            projected_chars = _cache_ttl_message_chars(projected)
            total_chars += projected_chars - candidate["chars"]
            candidate["chars"] = projected_chars
            record_projection(index, projected, "soft")
            pruned = True
    if (
        _ratio(total_chars, char_window) >= 0.5
        and settings.hard_clear
        and sum(candidate["chars"] for candidate in eligible) >= 50_000
    ):
        for candidate in eligible:
            if _ratio(total_chars, char_window) < 0.5:
                break
            current = (next_messages if next_messages is not None else projected_messages)[
                candidate["index"]
            ]
            if current.get("role") != "toolResult":
                continue
            cleared = spread_message(
                current, {"content": [{"type": "text", "text": settings.placeholder}]}
            )
            total_chars += _cache_ttl_message_chars(cleared) - candidate["chars"]
            record_projection(candidate["index"], cleared, "hard")
            pruned = True
    if pruned and on_pruned is not None:
        on_pruned()
    return next_messages if next_messages is not None else unchanged


# --- projecting truncation of a message list --------------------------------------------------


@dataclass(frozen=True)
class MessagesTruncationResult:
    messages: list[dict[str, Any]]
    truncated_count: int
    aggregate_truncated_count: int
    aggregate_pressure_engaged: bool
    aggregate_budget_chars: int


def resolve_tool_result_budgets(
    *,
    context_window_tokens: int | float,
    max_chars_override: int | float | None = None,
    aggregate_max_chars_override: int | float | None = None,
) -> tuple[int, int]:
    max_chars = max(
        1,
        max_chars_override
        if max_chars_override is not None
        else calculate_max_tool_result_chars(context_window_tokens),
    )
    return int(max_chars), _recovery_aggregate_tool_result_chars(
        int(context_window_tokens), int(max_chars), aggregate_max_chars_override
    )


def truncate_oversized_tool_results_in_messages(
    messages: list[dict[str, Any]],
    context_window_tokens: int | float,
    max_chars_override: int | float | None = None,
    aggregate_max_chars_override: int | float | None = None,
    projection_state: ToolResultPromptProjectionState | None = None,
) -> MessagesTruncationResult:
    """``truncateOversizedToolResultsInMessages``: bounded tool-result history, no mutation."""

    max_chars, aggregate_budget_chars = resolve_tool_result_budgets(
        context_window_tokens=context_window_tokens,
        max_chars_override=max_chars_override,
        aggregate_max_chars_override=aggregate_max_chars_override,
    )
    source_branch = _planning_branch(messages)
    projected_branch = source_branch
    keys: list[str | None] = []
    if projection_state is not None:
        projected_branch, keys = project_tool_result_branch(
            branch=source_branch, projection_state=projection_state, record_sources=True
        )
    plan = build_tool_result_replacement_plan(
        branch=projected_branch,
        max_chars=max_chars,
        aggregate_budget_chars=aggregate_budget_chars,
        min_keep_chars=RECOVERY_MIN_KEEP_CHARS,
        protect_trailing_tool_results=projection_state is not None,
    )
    by_id = plan.replacement_messages_by_entry_id
    replaced = [by_id.get(entry["id"], entry["message"]) for entry in projected_branch]
    if projection_state is not None:
        for index, entry in enumerate(source_branch):
            key = keys[index] if index < len(keys) else None
            if not key:
                continue
            projection_state.frozen.add(key)
            projected_message = replaced[index]
            if (
                plan.replacements
                and projected_message.get("role") == "toolResult"
                and projected_message is not entry["message"]
            ):
                record_tool_result_prompt_projection(projection_state, key, projected_message)
    output = replaced
    return MessagesTruncationResult(
        messages=output
        if any(a is not b for a, b in zip(output, messages, strict=False))
        else messages,
        truncated_count=len({replacement["entry_id"] for replacement in plan.replacements}),
        aggregate_truncated_count=plan.aggregate_replacement_count,
        aggregate_pressure_engaged=plan.aggregate_pressure_exceeded,
        aggregate_budget_chars=aggregate_budget_chars,
    )


# --- session context window -------------------------------------------------------------------


def session_context_entries(branch: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """``iterateSessionContextEntries`` over an active branch: entries inside the context window.

    A compaction boundary is yielded first, then the kept and later message-like entries. A reset
    boundary keeps no retained entries here (upstream consults ``selectResetKeptEntries``).
    """

    boundary_index = -1
    for index, entry in enumerate(branch):
        if entry.get("type") in ("reset", "compaction"):
            boundary_index = index
    first_kept_index = -1
    if boundary_index >= 0:
        wanted = branch[boundary_index].get("firstKeptEntryId")
        found = next((i for i, e in enumerate(branch) if wanted is not None and e.get("id") == wanted), -1)
        first_kept_index = found if 0 <= found < boundary_index else boundary_index
    out: list[dict[str, Any]] = []
    if boundary_index >= 0:
        out.append(branch[boundary_index])
    for index, entry in enumerate(branch):
        retained = index < boundary_index
        if index == boundary_index or (
            retained and (index < first_kept_index or branch[boundary_index].get("type") == "reset")
        ):
            continue
        if entry.get("type") not in ("message", "custom_message", "branch_summary"):
            continue
        message = entry.get("message")
        if (
            entry.get("type") == "message"
            and isinstance(message, dict)
            and message.get("excludeFromContext") is True
        ):
            continue
        out.append(entry)
    return out


def session_context_tool_result_messages(branch: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The tool results of ``buildSessionContext().messages``; other roles never carry a key."""

    return [
        entry["message"]
        for entry in session_context_entries(branch)
        if entry.get("type") == "message"
        and isinstance(entry.get("message"), dict)
        and entry["message"].get("role") == "toolResult"
    ]


__all__ = [
    "CacheTtlPruningSettings",
    "MessagesTruncationResult",
    "ToolResultPromptProjectionState",
    "clone_tool_result_prompt_projection_state",
    "create_tool_result_prompt_projection_state",
    "drop_thinking_blocks",
    "get_tool_result_projection_keys",
    "persist_tool_result_projections",
    "project_tool_result_branch",
    "prune_expired_cache_ttl_tool_results",
    "reconcile_tool_result_prompt_projection_state",
    "record_tool_result_prompt_projection",
    "resolve_cache_ttl_pruning_settings",
    "restore_cache_ttl_tool_result_projections",
    "serialize_cache_ttl_tool_result_projections",
    "session_context_entries",
    "truncate_oversized_tool_results_in_messages",
]
