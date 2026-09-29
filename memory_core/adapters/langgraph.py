"""LangGraph host glue over the host kit (docs/integrations/langgraph.md).

Adapter-only and framework-free: it reads LangChain messages (``langchain_core.messages``
objects or their dict forms) by their attributes and returns plain dicts, which LangGraph's
``add_messages`` and LangChain chat models convert. Nothing here imports LangGraph or
LangChain, owns the agent loop or calls a model; the graph is host code
(examples/langgraph_agent.py).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from memory_core.host import ToolCallRepair, TurnUsage

# BaseMessage.type of each LangChain message class (and of its chunk) and the kit's role.
_ROLES = {
    "human": "user",
    "ai": "assistant",
    "tool": "tool",
    "system": "system",
    "HumanMessageChunk": "user",
    "AIMessageChunk": "assistant",
    "ToolMessageChunk": "tool",
    "SystemMessageChunk": "system",
}
# ChatMessage carries its role in a field.
_CHAT_TYPES = ("chat", "ChatMessageChunk")

ToolDispatch = Callable[[str, Mapping[str, Any] | str | None], dict[str, Any]]
ToolCallRepairer = Callable[[Sequence[Mapping[str, Any]]], ToolCallRepair]
# The private key that ties a repaired row's call back to the message's call lists.
_CALL_INDEX = "adapterCallIndex"


def transcript_rows(messages: Iterable[Any]) -> list[dict[str, Any]]:
    """The kit's transcript rows of LangChain messages, for ``after_turn`` and ``on_new_session``.

    human -> user, ai -> assistant, tool -> tool (with ``tool_call_id`` and ``name``), system ->
    system, a chat message -> its role; the content as it is (a string or content blocks, whose
    text blocks the kit reads). A role dict is copied; a LangChain type dict (``model_dump()``
    or ``messages_to_dict`` form) reads like the object. No row carries a ``type`` key: the
    session-memory hook reads a mapping with one as a raw transcript entry and would drop it.
    ``ValueError`` for anything else (a host error).
    """
    return [_row(message) for message in messages]


def turn_usage(message: Any) -> TurnUsage | None:
    """The kit's usage of an AI message: ``usage_metadata`` input and output tokens, else ``None``.

    ``prompt_tokens`` is ``input_tokens`` (LangChain's total input, cached tokens included) and
    ``completion_tokens`` is ``output_tokens``; a missing or non-integer count stays ``None``.
    """
    usage = _field(message, "usage_metadata")
    if not isinstance(usage, Mapping):
        return None
    return TurnUsage(
        prompt_tokens=_count(usage.get("input_tokens")),
        completion_tokens=_count(usage.get("output_tokens")),
    )


def has_tool_calls(message: Any) -> bool:
    """Whether an AI message asks for tools: its ``tool_calls`` or its ``invalid_tool_calls``.

    LangGraph's ``tools_condition`` routes on ``tool_calls`` only, but a provider sends the
    invalid calls back as tool calls too, and each needs its tool message.
    """
    return bool(_field(message, "tool_calls") or _field(message, "invalid_tool_calls"))


def tool_messages(message: Any, dispatch: ToolDispatch) -> list[dict[str, Any]]:
    """Answer every tool call of an AI message through ``dispatch``, in order.

    ``tool_calls`` with their parsed ``args``, then ``invalid_tool_calls`` with their raw
    ``args`` text, which the kit answers with its error payload when it is not a JSON object;
    an invalid call without a name is dispatched as ``""``, so the model gets the kit's
    ``tool  is not available`` payload. Pass ``kit.dispatcher(session)`` for a turn and
    ``FlushRequest.dispatch`` for a flush run: both take the two arguments. One
    ``{"role": "tool", "tool_call_id", "name", "content", "status"}`` dict per call:
    ``content`` is the payload as JSON text and ``status`` is ``"error"`` for any payload with
    ``"status": "error"``, else ``"success"``: the kit's error payloads (bad arguments, invalid
    JSON, an unknown tool) and, since v2026.9.6, a refused or failed ``memory_get`` read
    (``{"status": "error", "code", ...}``, memory-read-tool.ts:58-69), which upstream's
    ``isToolResultError`` counts as an error too (src/agents/tool-result-error.ts:90-118); a
    ``memory_get`` ``not_found`` stays ``"success"``. Labelled gap: ``isToolResultError`` also
    counts a truthy ``error`` or ``timedOut: true`` (:119-123), so upstream flags a result that
    carries one (a ``memory_search`` unavailable result, a failed corpus, a deadline partial),
    which stays ``"success"`` here.
    ``ValueError``, before any call is dispatched, when a call's id is not a string: a tool
    message needs it.
    """
    calls = _all_calls(message)
    for call in calls:
        if not isinstance(call.get("id"), str):
            raise ValueError(
                f"tool call {call.get('name')!r} has no string id, which its tool message needs"
            )
    rows = []
    for call in calls:
        name = call.get("name")
        name = name if isinstance(name, str) else ""
        payload = dispatch(name, call.get("args"))
        rows.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "name": name,
                "content": json.dumps(payload, ensure_ascii=False),
                "status": "error" if payload.get("status") == "error" else "success",
            }
        )
    return rows


def repair_tool_calls(messages: Iterable[Any], repair: ToolCallRepairer) -> list[Any]:
    """The messages with upstream's replay repair of their tool calls, for the next model call.

    ``repair`` is ``kit.repair_tool_calls`` (or a function passing it ``allowed_tool_names``).
    The messages go to it as the kit's rows (``transcript_rows``' mapping, plus each AI
    message's calls: ``tool_calls``, then ``invalid_tool_calls`` with their raw ``args`` text,
    and each tool message's ``status``) and come back by ``ToolCallRepair.sources``: an unchanged
    row is its original message, a changed AI message a copy with only the kept calls
    (``tool_calls`` and ``invalid_tool_calls`` rebuilt, trimmed names applied, and
    ``additional_kwargs["tool_calls"]`` filtered by the kept ids, which langchain-openai sends
    when both lists are empty; ``function_call`` and ``tool_call_chunks`` go when no call is
    kept), a tool message without an id (none, or blank) that the kit paired with its frame's
    only call a copy with that call's ``tool_call_id`` and ``status: "error"``, and a synthetic
    result a tool dict with the owning call's ``name`` and ``status: "error"``, the shape
    ``tool_messages`` emits. A role dict comes back as the kit's row. The
    host keeps its stored messages as they are (docs/host_kit.md, F26).
    """
    originals = list(messages)
    rows = [_repair_row(message) for message in originals]
    result = repair(rows)
    out: list[Any] = []
    names: dict[str, str] = {}
    for row, source in zip(result.messages, result.sources, strict=True):
        if row.get("role") == "assistant":
            names = {call.get("id"): _call_name(call) for call in row.get("tool_calls") or ()}
        if source is None:
            synthetic = dict(row)
            name = names.get(row.get("tool_call_id"))
            if isinstance(name, str) and name:
                synthetic["name"] = name
            out.append({**synthetic, "status": "error"})
        elif row is rows[source]:
            out.append(originals[source])
        else:
            out.append(_repaired(originals[source], row))
    return out


def _repair_row(message: Any) -> dict[str, Any]:
    row = _row(message)
    if isinstance(message, Mapping) and "role" in message:
        return row  # a role dict: its own tool_calls, in the kit's shapes
    fields = _fields(message)
    if row["role"] == "assistant":
        calls = _all_calls(fields)
        if calls:
            row["tool_calls"] = [
                {
                    "id": call.get("id"),
                    "name": call.get("name"),
                    "args": call.get("args"),
                    _CALL_INDEX: index,
                }
                for index, call in enumerate(calls)
            ]
    elif row["role"] == "tool" and _field(fields, "status") is not None:
        row["status"] = _field(fields, "status")
    return row


def _repaired(message: Any, row: Mapping[str, Any]) -> Any:
    if isinstance(message, Mapping) and "role" in message:
        return row
    if row.get("role") == "tool":  # the kit paired an id-less result with its call, as an error
        update = {"tool_call_id": row["tool_call_id"]}
        if "status" in row:
            update["status"] = row["status"]
        return _updated(message, update)
    fields = _fields(message)
    calls = _all_calls(fields)
    valid_count = len(_field(fields, "tool_calls") or ())
    kept_valid, kept_invalid = [], []
    for call in row.get("tool_calls") or ():
        index, name = call[_CALL_INDEX], call["name"]
        original = calls[index]
        kept = original if original.get("name") == name else {**original, "name": name}
        (kept_valid if index < valid_count else kept_invalid).append(kept)
    ids = {call.get("id") for call in (*kept_valid, *kept_invalid)}
    extra = dict(_field(fields, "additional_kwargs") or {})
    if "tool_calls" in extra:
        raw = [
            call
            for call in extra["tool_calls"]
            if isinstance(call, Mapping) and call.get("id") in ids
        ]
        if raw:
            extra["tool_calls"] = raw
        else:
            del extra["tool_calls"]
    update: dict[str, Any] = {"tool_calls": kept_valid, "invalid_tool_calls": kept_invalid}
    if not ids:
        extra.pop("function_call", None)
    update["additional_kwargs"] = extra
    chunks = _field(fields, "tool_call_chunks")
    if chunks is not None:
        update["tool_call_chunks"] = [chunk for chunk in chunks if chunk.get("id") in ids]
    return _updated(message, update)


def _updated(message: Any, update: dict[str, Any]) -> Any:
    if isinstance(message, Mapping):
        if "content" not in message and isinstance(message.get("data"), Mapping):
            return {**message, "data": {**message["data"], **update}}
        return {**message, **update}
    return message.model_copy(update=update)


def _fields(message: Any) -> Any:
    """What a message's fields are read from: the object, or a dict form's own fields."""
    if isinstance(message, Mapping) and "content" not in message:
        data = message.get("data")
        if isinstance(data, Mapping):
            return data
    return message


def _all_calls(message: Any) -> list[Mapping[str, Any]]:
    """``tool_calls``, then ``invalid_tool_calls``: the order ``tool_messages`` answers them in."""
    return [*(_field(message, "tool_calls") or ()), *(_field(message, "invalid_tool_calls") or ())]


def _call_name(call: Mapping[str, Any]) -> Any:
    function = call.get("function")
    return function.get("name") if isinstance(function, Mapping) else call.get("name")


def _row(message: Any) -> dict[str, Any]:
    if isinstance(message, Mapping):
        if "role" in message:
            return {key: value for key, value in message.items() if key != "type"}
        if "content" not in message and isinstance(message.get("data"), Mapping):
            message = {**message["data"], "type": message.get("type")}
    kind = _field(message, "type")
    role = _field(message, "role") if kind in _CHAT_TYPES else _ROLES.get(kind)
    if not isinstance(role, str) or not role:
        raise ValueError(f"not a chat message: type {kind!r}")
    row = {"role": role, "content": _field(message, "content")}
    if role == "tool":
        row["tool_call_id"] = _field(message, "tool_call_id")
        name = _field(message, "name")
        if name:
            row["name"] = name
    return row


def _field(message: Any, name: str) -> Any:
    if isinstance(message, Mapping):
        return message.get(name)
    return getattr(message, name, None)


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
