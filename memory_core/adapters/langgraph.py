"""LangGraph host glue over the host kit (docs/integrations/langgraph.md).

Adapter-only and framework-free: it reads LangChain messages (``langchain_core.messages``
objects or their dict forms) by their attributes and returns plain dicts, which LangGraph's
``add_messages`` and LangChain chat models convert. Nothing here imports LangGraph or
LangChain, owns the agent loop or calls a model; the graph is host code
(examples/langgraph_agent.py).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from memory_core.host import SessionState, TurnContext, TurnUsage

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
    ``tool  is not available`` payload. For ``HostKit.dispatch`` pass
    ``functools.partial(kit.dispatch, session=...)``; ``FlushRequest.dispatch`` takes the two
    arguments as it is. One ``{"role": "tool", "tool_call_id", "name", "content", "status"}``
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


@dataclass(frozen=True)
class PendingTurn:
    """The turn in flight between a graph's prepare and maintain nodes, as checkpointable JSON.

    A :class:`~memory_core.host.TurnContext` holds the ``WorkspaceContext`` it was built from and
    does not serialize, while a graph's model, tools and maintenance nodes run in separate
    supersteps that read their input from the checkpoint. This keeps what those nodes need: the
    context's ``session`` (for ``dispatch`` and ``after_turn``), ``system_prompt``,
    ``runtime_context`` and ``tools``, and for the turn a bare ``/new`` or ``/reset`` starts the
    ``model_prompt`` (``ResetTurn.model_prompt``) the model gets in place of the transcript row
    whose message id is ``model_prompt_message_id``. Assembling the model input is the host's.
    """

    session: SessionState
    system_prompt: str
    runtime_context: str | None
    tools: tuple[dict[str, Any], ...]
    model_prompt: str | None = None
    model_prompt_message_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session, SessionState):
            raise TypeError("session must be a SessionState")
        if not isinstance(self.system_prompt, str):
            raise TypeError("system_prompt must be a string")
        for name in ("runtime_context", "model_prompt", "model_prompt_message_id"):
            if getattr(self, name) is not None and not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} must be a string or None")
        if not all(isinstance(tool, Mapping) for tool in self.tools):
            raise TypeError("tools must be mappings")
        if (self.model_prompt is None) != (self.model_prompt_message_id is None):
            raise ValueError("model_prompt and model_prompt_message_id go together")
        object.__setattr__(self, "tools", tuple(copy.deepcopy(dict(tool)) for tool in self.tools))

    @classmethod
    def from_context(
        cls,
        context: TurnContext,
        *,
        model_prompt: str | None = None,
        model_prompt_message_id: str | None = None,
    ) -> PendingTurn:
        """The pending turn of ``HostKit.before_turn``'s context, with the reset prompt if any."""
        return cls(
            session=context.session,
            system_prompt=context.system_prompt,
            runtime_context=context.runtime_context,
            tools=context.tools,
            model_prompt=model_prompt,
            model_prompt_message_id=model_prompt_message_id,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "session": self.session.to_json(),
            "systemPrompt": self.system_prompt,
            "runtimeContext": self.runtime_context,
            "tools": [copy.deepcopy(tool) for tool in self.tools],
            "modelPrompt": self.model_prompt,
            "modelPromptMessageId": self.model_prompt_message_id,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> PendingTurn:
        """Read :meth:`to_json` output; ``ValueError`` for anything else."""
        if not isinstance(data, Mapping):
            raise ValueError("not a pending turn: expected an object")
        session, tools = data.get("session"), data.get("tools")
        if not isinstance(session, Mapping):
            raise ValueError("not a pending turn: session must be an object")
        if not isinstance(tools, list):
            raise ValueError("not a pending turn: tools must be a list")
        try:
            return cls(
                session=SessionState.from_json(session),
                system_prompt=data["systemPrompt"],
                runtime_context=data.get("runtimeContext"),
                tools=tuple(tools),
                model_prompt=data.get("modelPrompt"),
                model_prompt_message_id=data.get("modelPromptMessageId"),
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"not a pending turn: {exc}") from exc


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
