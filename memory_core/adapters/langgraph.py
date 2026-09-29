"""LangGraph host glue over the host kit (docs/integrations/langgraph.md).

Adapter-only and framework-free: it reads LangChain messages (``langchain_core.messages``
objects or their dict forms) by their attributes and returns plain dicts, which LangGraph's
``add_messages`` and LangChain chat models convert. Nothing here imports LangGraph or
LangChain, owns the agent loop or calls a model; the graph is host code
(examples/langgraph_agent.py).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from memory_core.host import TurnUsage

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
    ``FlushRequest.dispatch`` for a flush run: both take the two arguments. One ``{"role": "tool", "tool_call_id", "name", "content", "status"}``
    dict per call: ``content`` is the payload as JSON text and ``status`` is ``"error"`` for the
    kit's error payload (``{"status": "error", ...}``), else ``"success"``. ``ValueError``, before
    any call is dispatched, when a call's id is not a string: a tool message needs it.
    """
    calls = [*(_field(message, "tool_calls") or ()), *(_field(message, "invalid_tool_calls") or ())]
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
