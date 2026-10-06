"""Session context window at v2026.9.6: the reset boundary and its kept tail.

Ports ``iterateSessionContextEntries`` / ``resolveSessionContextWindow``
(``packages/agent-core/src/harness/session/session.ts``) and ``selectResetKeptEntries``
(``.../session/tool-result-pairing.ts``). A reset boundary keeps the entries after its
``firstKeptEntryId`` only where they are user or assistant messages or tool results that a
retained tool call owns; a compaction boundary keeps every message-like entry from
``firstKeptEntryId`` on.

Entries are the plain mappings of a session branch (``type``, ``id``, ``message`` ...). Selection
is by object identity, as upstream's ``Set`` of entries and of tool-result messages is.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Literal

from memory_core.replay_repair import _classify_tool_use_result_pairing

ContextKind = Literal["current", "retained", "reset-retained"]

_MISSING: Any = object()


def _strict_equal(left: Any, right: Any) -> bool:
    """JS ``===`` for JSON values (``True == 1`` is false there)."""

    if left is _MISSING or right is _MISSING:
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    return type(left) is type(right) and left == right


def select_reset_kept_entries(entries: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """``selectResetKeptEntries``: reset-tail model context, entry bytes and order untouched."""

    messages = [entry["message"] for entry in entries if entry.get("type") == "message"]
    pairing = _classify_tool_use_result_pairing(messages)
    paired = {
        id(occurrence.source_result)
        for frame in pairing.frames
        for occurrence in frame.occurrences
        if occurrence.source_result is not None
    }
    kept: list[Mapping[str, Any]] = []
    for entry in entries:
        if entry.get("type") != "message":
            continue
        role = entry["message"].get("role")
        if role in ("user", "assistant") or (role == "toolResult" and id(entry["message"]) in paired):
            kept.append(entry)
    return kept


def resolve_session_context_window(entries: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """``resolveSessionContextWindow``: ``(boundaryIndex, firstKeptIndex)``, ``-1`` without a boundary."""

    boundary_index = -1
    for index in range(len(entries) - 1, -1, -1):
        if entries[index].get("type") in ("reset", "compaction"):
            boundary_index = index
            break
    wanted = entries[boundary_index].get("firstKeptEntryId", _MISSING) if boundary_index >= 0 else _MISSING
    found = next(
        (i for i, entry in enumerate(entries) if _strict_equal(entry.get("id", _MISSING), wanted)),
        -1,
    )
    return boundary_index, found if 0 <= found < boundary_index else boundary_index


def iterate_session_context_entries(
    path_entries: Sequence[Mapping[str, Any]],
) -> Iterator[tuple[Mapping[str, Any], ContextKind]]:
    """``iterateSessionContextEntries``: ``(entry, context)`` pairs inside the context window."""

    boundary_index, first_kept_index = resolve_session_context_window(path_entries)
    boundary = path_entries[boundary_index] if boundary_index >= 0 else None
    reset_kept: set[int] | None = None
    if boundary is not None and boundary.get("type") == "reset":
        reset_kept = {
            id(entry)
            for entry in select_reset_kept_entries(path_entries[first_kept_index:boundary_index])
        }
    if boundary is not None:
        yield boundary, "current"
    for index, entry in enumerate(path_entries):
        retained = index < boundary_index
        if index == boundary_index or (
            retained
            and (index < first_kept_index or (reset_kept is not None and id(entry) not in reset_kept))
        ):
            continue
        has_message = entry.get("type") in ("message", "custom_message", "branch_summary")
        if not has_message:
            continue
        message = entry.get("message")
        if (
            (reset_kept is None or id(entry) not in reset_kept)
            and entry.get("type") == "message"
            and isinstance(message, Mapping)
            and message.get("excludeFromContext") is True
        ):
            continue
        context: ContextKind = (
            ("reset-retained" if reset_kept is not None else "retained") if retained else "current"
        )
        yield entry, context


__all__ = [
    "ContextKind",
    "iterate_session_context_entries",
    "resolve_session_context_window",
    "select_reset_kept_entries",
]
