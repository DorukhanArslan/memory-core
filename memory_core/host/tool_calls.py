"""Upstream's model-replay repair of tool calls, over a host's message rows (docs/host_kit.md, F26).

A turn that failed between a tool-call reply and its tool results leaves calls without results,
which a provider rejects. Upstream repairs the replayed history on a copy, never the stored
transcript: ``sanitizeToolCallInputs`` and then ``sanitizeToolUseResultPairingForModel``
(src/agents/embedded-agent-runner/replay-history.ts:793,819). :func:`repair_tool_calls` maps the
host's chat-completions rows to upstream's message shape, runs the two core ports
(``memory_core.replay_repair``) in that order and maps the result back, returning the host's own
row objects wherever nothing changed. The row mapping is adapter-only kit code; the two repairs
are the ports. Labelled gaps: host rows carry no stop reason (no turn counts as failed), tool-call
blocks inside a content list and a legacy ``function_call`` are neither read nor rewritten, and
the Responses-API steps (the ``aborted`` text and the id rewrites after it) are not offered.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from memory_core._transcript_repair_constants import DEFAULT_MISSING_TOOL_RESULT_TEXT
from memory_core.replay_repair import (
    TOOL_CALL_BLOCK_TYPES,
    sanitize_tool_call_inputs,
    sanitize_tool_use_result_pairing_for_model,
)

# Private index keys on the mapped messages and tool-call blocks; the repairs' copies keep them
# and nothing returned carries them.
_ROW = "hostRowIndex"
_CALL = "hostCallIndex"


@dataclass(frozen=True)
class ToolCallRepair:
    """The rows to send the model, and for each the index of the host row it is or copies.

    ``sources`` holds ``None`` for a synthetic tool result. Unchanged rows are the host's own
    objects, so ``messages[i] is rows[sources[i]]`` tells a kept row from a changed copy.
    """

    messages: tuple[Mapping[str, Any], ...]
    sources: tuple[int | None, ...]


def repair_tool_calls(
    messages: Sequence[Mapping[str, Any]], *, allowed_tool_names: Iterable[str] | None = None
) -> ToolCallRepair:
    """Repair the tool calls of a host's history for the next model call.

    Host rows are chat-completions messages: an assistant row with ``tool_calls`` (each
    ``{"id", "type": "function", "function": {"name", "arguments"}}`` or the flat ``{"id",
    "name", "args" | "arguments"}``), a tool row with ``tool_call_id`` (and ``name``,
    ``status``), any other row passes through. ``allowed_tool_names`` restricts which unanswered
    calls survive (upstream passes the run's tool names). Returns the repaired rows: a changed
    assistant row is a shallow copy with its kept calls (trimmed names; no ``tool_calls`` key
    when none is kept), a tool row paired by its frame's only call gets that call's
    ``tool_call_id``, dropped rows are left out, and a synthetic result is ``{"role": "tool",
    "tool_call_id", "content"}`` with upstream's text. ``TypeError`` for a row or a call that is
    not a mapping.
    """
    rows = list(messages)
    mapped = [_to_upstream(index, row) for index, row in enumerate(rows)]
    repaired = sanitize_tool_use_result_pairing_for_model(
        sanitize_tool_call_inputs(mapped, allowed_tool_names=allowed_tool_names), False
    )
    out: list[Mapping[str, Any]] = []
    sources: list[int | None] = []
    for message in repaired:
        index = message.get(_ROW)
        if index is None:  # makeMissingToolResult: a synthetic error result
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": message["toolCallId"],
                    "content": DEFAULT_MISSING_TOOL_RESULT_TEXT,
                }
            )
            sources.append(None)
            continue
        out.append(_to_host(rows[index], mapped[index], message))
        sources.append(index)
    return ToolCallRepair(messages=tuple(out), sources=tuple(sources))


def _to_upstream(index: int, row: object) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise TypeError("host rows must be mappings")
    role = row.get("role")
    if role == "assistant":
        content = row.get("content")
        blocks: list[Any] = []
        if isinstance(content, str) and content:
            blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            # Tool-call blocks of a content list are not read: the calls come from tool_calls.
            blocks.extend(
                block
                for block in content
                if not (isinstance(block, Mapping) and block.get("type") in TOOL_CALL_BLOCK_TYPES)
            )
        for position, call in enumerate(_calls(row)):
            name, arguments = _call_name_and_arguments(call)
            blocks.append(
                {
                    "type": "toolCall",
                    "id": call.get("id"),
                    "name": name,
                    "arguments": arguments,
                    _CALL: position,
                }
            )
        return {"role": "assistant", "content": blocks, _ROW: index}
    if role == "tool":
        content = row.get("content")
        mapped: dict[str, Any] = {
            "role": "toolResult",
            "content": [{"type": "text", "text": content}] if isinstance(content, str) else content,
            "isError": row.get("status") == "error",
            _ROW: index,
        }
        if isinstance(row.get("tool_call_id"), str):
            mapped["toolCallId"] = row["tool_call_id"]
        if "name" in row:
            mapped["toolName"] = row["name"]
        return mapped
    return {_ROW: index}  # role-less: both repairs pass it through


def _to_host(row: Mapping[str, Any], mapped: dict[str, Any], message: dict[str, Any]) -> Mapping:
    if message is mapped:
        return row
    if mapped.get("role") == "assistant":
        # The input repair dropped calls or trimmed names; content blocks never change.
        calls = _calls(row)
        kept = []
        for block in message["content"]:
            if not _is_host_call(block):
                continue
            call = calls[block[_CALL]]
            name, _ = _call_name_and_arguments(call)
            kept.append(call if block["name"] == name else _renamed(call, block["name"]))
        copy = {key: value for key, value in row.items() if key != "tool_calls"}
        if kept:
            copy["tool_calls"] = kept
        return copy
    # A tool result: the legacy-id normalization paired an id-less row with its frame's only
    # call (normalizeLegacyToolResultId); a tool-name normalization alone changes nothing here.
    call_id = message.get("toolCallId")
    if isinstance(call_id, str) and not isinstance(row.get("tool_call_id"), str):
        return {**row, "tool_call_id": call_id}
    return row


def _is_host_call(block: object) -> bool:
    return isinstance(block, Mapping) and block.get("type") == "toolCall" and _CALL in block


def _calls(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    calls = row.get("tool_calls")
    if not calls:
        return []
    if isinstance(calls, str | bytes) or not isinstance(calls, Sequence):
        raise TypeError("tool_calls must be a list of mappings")
    if not all(isinstance(call, Mapping) for call in calls):
        raise TypeError("tool calls must be mappings")
    return list(calls)


def _call_name_and_arguments(call: Mapping[str, Any]) -> tuple[Any, Any]:
    function = call.get("function")
    if isinstance(function, Mapping):
        return function.get("name"), function.get("arguments")
    return call.get("name"), call["args"] if "args" in call else call.get("arguments")


def _renamed(call: Mapping[str, Any], name: str) -> dict[str, Any]:
    function = call.get("function")
    if isinstance(function, Mapping):
        return {**call, "function": {**function, "name": name}}
    return {**call, "name": name}
