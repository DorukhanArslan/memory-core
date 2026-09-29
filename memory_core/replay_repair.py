"""Tool-call replay repair of OpenClaw v2026.9.6 (src/agents/session-transcript-repair.ts).

``repair_tool_use_result_pairing`` ports ``repairToolUseResultPairing`` over the classifier of
packages/agent-core/src/harness/session/tool-result-pairing.ts (``classifyToolUseResultPairing``):
each assistant turn with tool calls is a frame, its calls are occurrences paired with results by
provider id and order (a provider may reuse an id on later turns), results displaced after a
user turn or into a later frame move back to the one unresolved occurrence that can own them, a
later real result replaces a synthetic one, orphans and duplicates are dropped, and each call of
a non-failed turn without a result gets a synthetic error result. Messages are upstream's
``AgentMessage`` dicts (``role`` ``assistant`` with ``toolCall`` content blocks, ``toolResult``
with ``toolCallId``); nothing here reads a host's chat-completions rows (the host kit maps them,
memory_core/host/_tool_calls.py).
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from memory_core._transcript_repair_constants import (
    DEFAULT_MISSING_TOOL_RESULT_TEXT,
    SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY,
)
from memory_core.bootstrap._js import js_trim

AgentMessage = dict[str, Any]
ErroredAssistantResultPolicy = Literal["preserve", "drop"]

# tool-result-pairing.ts TOOL_CALL_TYPES: the block types the pairing reads as tool calls.
_TOOL_CALL_TYPES = frozenset({"toolCall", "toolUse", "functionCall"})
# extractToolResultIds: the id keys of a tool result, in order.
_TOOL_RESULT_ID_KEYS = ("toolCallId", "toolUseId", "tool_call_id", "tool_use_id", "callId", "call_id")

__all__ = [
    "DEFAULT_MISSING_TOOL_RESULT_TEXT",
    "SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY",
    "ErroredAssistantResultPolicy",
    "ToolUseRepairReport",
    "is_synthetic_missing_tool_result",
    "repair_tool_use_result_pairing",
    "sanitize_tool_use_result_pairing",
    "sanitize_tool_use_result_pairing_for_model",
]


@dataclass(frozen=True)
class ToolUseRepairReport:
    """Upstream ``ToolUseRepairReport``: ``messages`` is the input list itself when unchanged.

    ``discarded`` holds the original messages the repair dropped, in transcript order.
    """

    messages: list[AgentMessage]
    added: list[AgentMessage]
    dropped_duplicate_count: int
    dropped_orphan_count: int
    moved: bool
    discarded: list[AgentMessage] = field(default_factory=list)


@dataclass
class _Occurrence:
    content_index: int
    id: str
    name: str | None
    result: AgentMessage | None = None
    source_result: AgentMessage | None = None
    source_result_index: int | None = None


@dataclass
class _ResultRecord:
    result: AgentMessage
    source_result: AgentMessage
    index: int
    id: str | None


@dataclass
class _Frame:
    start_index: int
    end_index: int
    assistant: AgentMessage
    remainder: list[AgentMessage]
    occurrences: list[_Occurrence]
    failed: bool
    unclaimed_results: list[_ResultRecord]


@dataclass
class _Pairing:
    frames: list[_Frame]
    dropped_duplicate_count: int
    dropped_orphan_count: int
    dropped_results: list[tuple[AgentMessage, int]]


class _OccurrenceQueue:
    """createToolCallOccurrenceQueue: repeated provider ids by occurrence, not as a set."""

    def __init__(self) -> None:
        self._pending: dict[str, list[_Occurrence]] = {}

    def add(self, tool_id: str, occurrence: _Occurrence) -> None:
        self._pending.setdefault(tool_id, []).append(occurrence)

    def claim(self, tool_id: str) -> _Occurrence | None:
        pending = self._pending.get(tool_id)
        if not pending:
            return None
        occurrence = pending.pop(0)
        if not pending:
            del self._pending[tool_id]
        return occurrence


def repair_tool_use_result_pairing(
    messages: list[AgentMessage],
    *,
    errored_assistant_result_policy: ErroredAssistantResultPolicy = "preserve",
    missing_tool_result_text: str | None = None,
    preserve_unframed_tool_results: bool = False,
) -> ToolUseRepairReport:
    """Port of ``repairToolUseResultPairing`` (session-transcript-repair.ts:391-480).

    ``errored_assistant_result_policy="drop"`` drops a failed (``stopReason`` ``error`` or
    ``aborted``) assistant turn with its results; ``"preserve"`` keeps both and synthesizes
    nothing for it. ``preserve_unframed_tool_results`` keeps results that no frame owns
    (upstream ``preserveUnframedToolResults``, for a Responses replay checkpoint).
    """
    pairing = _classify_tool_use_result_pairing(
        messages, preserve_unframed_tool_results=preserve_unframed_tool_results
    )
    added: list[AgentMessage] = []
    dropped_orphan_count = pairing.dropped_orphan_count
    discarded = list(pairing.dropped_results)
    drop_failed = errored_assistant_result_policy == "drop"
    out: list[AgentMessage] = []
    cursor = 0

    def push_unframed_range(end_index: int) -> None:
        nonlocal cursor, dropped_orphan_count
        while cursor < end_index:
            message = messages[cursor]
            if isinstance(message, Mapping):
                if message.get("role") == "toolResult" and not preserve_unframed_tool_results:
                    dropped_orphan_count += 1
                    discarded.append((message, cursor))
                else:
                    out.append(message)
            cursor += 1

    for frame in pairing.frames:
        push_unframed_range(frame.start_index)
        cursor = frame.end_index
        if not (frame.failed and drop_failed):
            out.append(frame.assistant)
            for occurrence in frame.occurrences:
                if occurrence.result is not None:
                    out.append(occurrence.result)
                    continue
                if frame.failed:
                    continue
                missing = _make_missing_tool_result(
                    tool_call_id=occurrence.id,
                    tool_name=occurrence.name,
                    text=missing_tool_result_text,
                )
                occurrence.result = missing
                added.append(missing)
                out.append(missing)
        else:
            for occurrence in frame.occurrences:
                if occurrence.source_result is not None:
                    index = occurrence.source_result_index
                    discarded.append(
                        (
                            occurrence.source_result,
                            index if index is not None else _index_of(messages, occurrence),
                        )
                    )
        out.extend(frame.remainder)
    push_unframed_range(len(messages))

    changed = len(out) != len(messages) or any(
        message is not original for message, original in zip(out, messages, strict=False)
    )
    discarded.sort(key=lambda item: item[1])
    return ToolUseRepairReport(
        messages=out if changed else messages,
        added=added,
        dropped_duplicate_count=pairing.dropped_duplicate_count,
        dropped_orphan_count=dropped_orphan_count,
        moved=changed,
        discarded=[message for message, _ in discarded],
    )


def sanitize_tool_use_result_pairing(
    messages: list[AgentMessage],
    *,
    errored_assistant_result_policy: ErroredAssistantResultPolicy = "preserve",
    missing_tool_result_text: str | None = None,
    preserve_unframed_tool_results: bool = False,
) -> list[AgentMessage]:
    """``sanitizeToolUseResultPairing``: the repaired messages only."""
    return repair_tool_use_result_pairing(
        messages,
        errored_assistant_result_policy=errored_assistant_result_policy,
        missing_tool_result_text=missing_tool_result_text,
        preserve_unframed_tool_results=preserve_unframed_tool_results,
    ).messages


def sanitize_tool_use_result_pairing_for_model(
    messages: list[AgentMessage], is_openai_responses_api: bool
) -> list[AgentMessage]:
    """``sanitizeToolUseResultPairingForModel`` (session-transcript-repair.ts:367-376).

    The model-replay form: failed turns are dropped, and the OpenAI Responses API gets the
    missing-result text ``aborted``.
    """
    return sanitize_tool_use_result_pairing(
        messages,
        errored_assistant_result_policy="drop",
        missing_tool_result_text="aborted" if is_openai_responses_api else None,
    )


def is_synthetic_missing_tool_result(message: Mapping[str, Any]) -> bool:
    """``isSyntheticMissingToolResult`` (tool-result-pairing.ts:165-192).

    An error result whose ``details`` carry the synthetic marker, or with a text block that is
    exactly the default missing-result text.
    """
    if not _truthy(message.get("isError")):
        return False
    details = message.get("details")
    if isinstance(details, Mapping) and details.get(SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY) is True:
        return True
    content = message.get("content")
    return isinstance(content, list) and any(
        isinstance(block, Mapping)
        and block.get("type") == "text"
        and block.get("text") == DEFAULT_MISSING_TOOL_RESULT_TEXT
        for block in content
    )


def _classify_tool_use_result_pairing(
    messages: list[AgentMessage], *, preserve_unframed_tool_results: bool = False
) -> _Pairing:
    """Port of ``classifyToolUseResultPairing`` (tool-result-pairing.ts:234-391)."""
    frame_starts = [
        index
        for index, message in enumerate(messages)
        if isinstance(message, Mapping)
        and message.get("role") == "assistant"
        and _extract_tool_calls_from_assistant(message)
    ]
    dropped_duplicate_count = 0
    dropped_orphan_count = 0
    dropped_results: list[tuple[AgentMessage, int]] = []
    frames: list[_Frame] = []
    for frame_index, start_index in enumerate(frame_starts):
        assistant = messages[start_index]
        tool_calls: list[tuple[str, str | None]] = []
        occurrences: list[_Occurrence] = []
        pending = _OccurrenceQueue()
        synthetic_by_id: dict[str, list[_Occurrence]] = {}
        for content_index, block in enumerate(assistant["content"]):
            tool_call = _read_tool_call(block)
            if tool_call is None:
                continue
            tool_calls.append(tool_call)
            occurrence = _Occurrence(content_index, *tool_call)
            occurrences.append(occurrence)
            pending.add(tool_call[0], occurrence)
        end_index = (
            frame_starts[frame_index + 1] if frame_index + 1 < len(frame_starts) else len(messages)
        )
        remainder: list[AgentMessage] = []
        unclaimed: list[_ResultRecord] = []
        for index in range(start_index + 1, end_index):
            message = messages[index]
            if not isinstance(message, Mapping):
                continue
            if message.get("role") != "toolResult":
                remainder.append(message)
                continue
            normalized = _normalize_legacy_tool_result_id(message, tool_calls)
            tool_id = _extract_tool_result_id(normalized)
            occurrence = pending.claim(tool_id) if tool_id else None
            if occurrence is not None:
                occurrence.result = _normalize_tool_result_name(normalized, occurrence.name)
                occurrence.source_result = message
                occurrence.source_result_index = index
                if is_synthetic_missing_tool_result(occurrence.result):
                    synthetic_by_id.setdefault(occurrence.id, []).append(occurrence)
                continue
            if not tool_id or not any(candidate.id == tool_id for candidate in occurrences):
                unclaimed.append(_ResultRecord(normalized, message, index, tool_id))
                if preserve_unframed_tool_results:
                    remainder.append(normalized)
                continue
            dropped_duplicate_count += 1
            replaceable = (
                None
                if is_synthetic_missing_tool_result(normalized)
                else _shift(synthetic_by_id.get(tool_id))
            )
            if replaceable is not None:
                if replaceable.source_result is not None:
                    source_index = replaceable.source_result_index
                    dropped_results.append(
                        (replaceable.source_result, source_index if source_index is not None else index)
                    )
                replaceable.result = _normalize_tool_result_name(normalized, replaceable.name)
                replaceable.source_result = message
                replaceable.source_result_index = index
            else:
                dropped_results.append((message, index))
        stop_reason = assistant.get("stopReason")
        frames.append(
            _Frame(
                start_index=start_index,
                end_index=end_index,
                assistant=assistant,
                remainder=remainder,
                occurrences=occurrences,
                failed=stop_reason in ("error", "aborted"),
                unclaimed_results=unclaimed,
            )
        )

    # Displaced results cross a frame only when one unresolved occurrence can own them.
    unresolved_by_id: dict[str, list[_Occurrence]] = {}
    for frame in frames:
        for occurrence in frame.occurrences:
            if occurrence.result is None or is_synthetic_missing_tool_result(occurrence.result):
                unresolved_by_id.setdefault(occurrence.id, []).append(occurrence)
        for record in frame.unclaimed_results:
            record_is_synthetic = is_synthetic_missing_tool_result(record.result)
            candidates = (
                [
                    candidate
                    for candidate in unresolved_by_id.get(record.id, [])
                    if candidate.result is None
                    or (
                        is_synthetic_missing_tool_result(candidate.result)
                        and not record_is_synthetic
                    )
                ]
                if record.id
                else []
            )
            if len(candidates) != 1:
                if not preserve_unframed_tool_results:
                    dropped_orphan_count += 1
                    dropped_results.append((record.source_result, record.index))
                continue
            (candidate,) = candidates
            dropped_duplicate_count += 1 if candidate.result is not None else 0
            if candidate.result is not None and is_synthetic_missing_tool_result(candidate.result):
                if candidate.source_result is not None:
                    source_index = candidate.source_result_index
                    dropped_results.append(
                        (
                            candidate.source_result,
                            source_index if source_index is not None else record.index,
                        )
                    )
            candidate.result = _normalize_tool_result_name(record.result, candidate.name)
            candidate.source_result = record.source_result
            candidate.source_result_index = record.index
            if preserve_unframed_tool_results:
                frame.remainder = [
                    message for message in frame.remainder if message is not record.result
                ]

    return _Pairing(frames, dropped_duplicate_count, dropped_orphan_count, dropped_results)


def _shift(items: list[_Occurrence] | None) -> _Occurrence | None:
    return items.pop(0) if items else None


def _index_of(messages: list[AgentMessage], occurrence: _Occurrence) -> int:
    # messages.indexOf(occurrence.sourceResult): -1 when absent.
    for index, message in enumerate(messages):
        if message is occurrence.source_result:
            return index
    return -1


def _read_tool_call(block: object) -> tuple[str, str | None] | None:
    """tool-result-pairing.ts readToolCall: ``(id, name)`` of a tool-call block."""
    if not isinstance(block, Mapping):
        return None
    tool_id = block.get("id")
    if block.get("type") not in _TOOL_CALL_TYPES or not isinstance(tool_id, str) or not tool_id:
        return None
    name = block.get("name")
    return tool_id, name if isinstance(name, str) else None


def _extract_tool_calls_from_assistant(message: Mapping[str, Any]) -> list[tuple[str, str | None]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [call for call in map(_read_tool_call, content) if call is not None]


def _extract_tool_result_ids(message: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in _TOOL_RESULT_ID_KEYS:
        value = message.get(key)
        if not isinstance(value, str):
            continue
        tool_id = js_trim(value)
        if tool_id and tool_id not in ids:
            ids.append(tool_id)
    return ids


def _extract_tool_result_id(message: Mapping[str, Any]) -> str | None:
    ids = _extract_tool_result_ids(message)
    return ids[0] if ids else None


def _normalize_legacy_tool_result_id(
    message: AgentMessage, tool_calls: list[tuple[str, str | None]]
) -> AgentMessage:
    """``normalizeLegacyToolResultId``: an id-less result of a frame's only call is its error."""
    if _extract_tool_result_id(message) or len(tool_calls) != 1:
        return message
    call_id, call_name = tool_calls[0]
    result_name = _normalize_optional_string(message.get("toolName"))
    call_name = _normalize_optional_string(call_name)
    if result_name and call_name and result_name != call_name:
        return message
    return {**message, "toolCallId": call_id, "isError": True}


def _normalize_tool_result_name(
    message: AgentMessage, fallback_name: str | None = None
) -> AgentMessage:
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
    """normalization-core ``normalizeOptionalString``: the JS-trimmed text, or ``None``."""
    if not isinstance(value, str):
        return None
    return js_trim(value) or None


def _truthy(value: object) -> bool:
    """JavaScript truthiness of a JSON value."""
    if value is None or value is False:
        return False
    if isinstance(value, int | float) and not isinstance(value, bool):
        return value == value and value != 0
    if isinstance(value, str):
        return value != ""
    return True


def _make_missing_tool_result(
    *, tool_call_id: str, tool_name: str | None, text: str | None
) -> AgentMessage:
    """``makeMissingToolResult`` (tool-result-pairing.ts:149-163)."""
    return {
        "role": "toolResult",
        "toolCallId": tool_call_id,
        "toolName": tool_name if tool_name is not None else "unknown",
        "content": [
            {"type": "text", "text": text if text is not None else DEFAULT_MISSING_TOOL_RESULT_TEXT}
        ],
        "details": {SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY: True, "reason": "missing_tool_result"},
        "isError": True,
        "timestamp": int(time.time() * 1000),
    }
