"""Model-only projection of tool responses lost during an interrupted publication."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection

from memory_core.replay_repair import missing_tool_result_insertions
from memory_core.session_context import convert_to_llm, iterate_session_context_messages
from memory_core.session_context_window import iterate_session_context_entries


def recovered_session_messages(
    continuation: dict, interrupted_turn_ids: Collection[str], *, now_ms: int | float,
    responses: bool = False,
) -> tuple[list, list]:
    """Return the callback and prompt views of the current stored branch.

    HostTurn persisted every model/tool event as "<turn>:message:<counter>",
    including older events without run metadata. Use that identity to keep
    unrelated turns independent even when a provider reuses a tool call id.
    """
    original = continuation["llmMessages"], continuation["context"]["messages"]
    if not interrupted_turn_ids:
        return original

    visible = continuation["visibleEvents"]
    turns = defaultdict(list)
    for entry, _ in iterate_session_context_entries(visible):
        if entry.get("type") != "message" or not isinstance(entry.get("id"), str):
            continue
        turn_id, separator, counter = entry["id"].rpartition(":message:")
        if separator and turn_id in interrupted_turn_ids and counter.isascii() and counter.isdecimal():
            turns[turn_id].append(entry["message"])

    after = defaultdict(list)
    for messages in turns.values():
        for previous, result in missing_tool_result_insertions(messages, now_ms=now_ms, responses=responses):
            after[id(previous)].append({"type": "message", "message": result})
    if not after:
        return original

    expanded = []
    for event in visible:
        expanded.append(event)
        expanded.extend(after.get(id(event.get("message")), ()))
    projected = list(iterate_session_context_messages(expanded))
    return convert_to_llm(projected), projected
