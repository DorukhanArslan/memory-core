"""The turn in flight as JSON, for hosts whose steps run apart (docs/host_kit.md, F2, F3).

A :class:`~memory_core.host.kit.TurnContext` holds the ``WorkspaceContext`` it was built from and
does not serialize, while a host with durable steps (a LangGraph graph, a queue worker) runs the
model calls, the tool calls and ``after_turn`` of one turn in steps that read their input from
stored state. :class:`TurnState` keeps what those steps read, and the reset turn a bare ``/new``
or ``/reset`` starts; ``to_json`` / ``from_json`` carry it. Adapter-only kit code: nothing here is
an upstream structure.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from memory_core.host.kit import ResetTurn, TurnContext
from memory_core.host.session import SessionState


@dataclass(frozen=True)
class TurnState:
    """What the steps after ``before_turn`` read, as a value that serializes.

    ``session`` is the context's session (for ``HostKit.dispatcher`` and ``after_turn``);
    ``system_prompt``, ``runtime_context`` and ``tools`` go to every model call of the turn.
    ``reset`` is the ``NewSession.reset`` the turn runs: on every model call its
    ``model_prompt`` replaces the text of the turn's active user message while that text is
    its ``transcript_prompt`` (docs/host_kit.md, F3; assembling the model input is the host's).
    The tools are private deep copies.
    """

    session: SessionState
    system_prompt: str
    runtime_context: str | None
    tools: tuple[dict[str, Any], ...]
    reset: ResetTurn | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session, SessionState):
            raise TypeError("session must be a SessionState")
        if not isinstance(self.system_prompt, str):
            raise TypeError("system_prompt must be a string")
        if self.runtime_context is not None and not isinstance(self.runtime_context, str):
            raise TypeError("runtime_context must be a string or None")
        if not all(isinstance(tool, Mapping) for tool in self.tools):
            raise TypeError("tools must be mappings")
        if self.reset is not None and not isinstance(self.reset, ResetTurn):
            raise TypeError("reset must be a ResetTurn or None")
        object.__setattr__(self, "tools", tuple(copy.deepcopy(dict(tool)) for tool in self.tools))

    @classmethod
    def from_context(cls, context: TurnContext, *, reset: ResetTurn | None = None) -> TurnState:
        """The turn state of ``HostKit.before_turn``'s context, with the reset turn it runs."""
        return cls(
            session=context.session,
            system_prompt=context.system_prompt,
            runtime_context=context.runtime_context,
            tools=context.tools,
            reset=reset,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "session": self.session.to_json(),
            "systemPrompt": self.system_prompt,
            "runtimeContext": self.runtime_context,
            "tools": [copy.deepcopy(tool) for tool in self.tools],
            "reset": self.reset.to_json() if self.reset is not None else None,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> TurnState:
        """Read :meth:`to_json` output; ``ValueError`` for anything else.

        ``session``, ``systemPrompt`` and ``tools`` are required; a missing ``runtimeContext``
        or ``reset`` reads as null and unknown keys are ignored, as ``SessionState.from_json``
        does. The JSON is unversioned: changes stay additive.
        """
        if not isinstance(data, Mapping):
            raise ValueError("not a turn state: expected an object")
        session, tools, reset = data.get("session"), data.get("tools"), data.get("reset")
        if not isinstance(session, Mapping):
            raise ValueError("not a turn state: session must be an object")
        if not isinstance(data.get("systemPrompt"), str):
            raise ValueError("not a turn state: systemPrompt must be a string")
        runtime = data.get("runtimeContext")
        if runtime is not None and not isinstance(runtime, str):
            raise ValueError("not a turn state: runtimeContext must be a string or null")
        if not isinstance(tools, list) or not all(isinstance(tool, Mapping) for tool in tools):
            raise ValueError("not a turn state: tools must be a list of objects")
        if reset is not None and not isinstance(reset, Mapping):
            raise ValueError("not a turn state: reset must be an object or null")
        return cls(
            session=SessionState.from_json(session),
            system_prompt=data["systemPrompt"],
            runtime_context=runtime,
            tools=tuple(tools),
            reset=ResetTurn.from_json(reset) if reset is not None else None,
        )
