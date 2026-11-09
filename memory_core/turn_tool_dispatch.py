"""Execute registered host tools and feed real outcomes to shared turn trust.

This is an SDK callable dispatcher, not the provider loop, approval engine or
native loop-diagnostic hashing owner. Source classification belongs to the
trusted registration. Arguments and returned JSON cannot replace it. Actual
complete outcomes are available to the host observer.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import inspect
from typing import Any

from memory_core.turn_trust import TurnTrust


@dataclass(frozen=True)
class TurnTool:
    name: str
    execute: Callable[[str, Mapping[str, Any]], Any]
    result_content_source: str | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name or not callable(self.execute):
            raise ValueError("A host tool requires a name and executable source")
        if self.result_content_source not in {None, "network"}:
            raise ValueError("The supported registered content source is network")


class TurnToolDispatcher:
    """An actual execution boundary shared across attempts of one host turn."""

    def __init__(self, trust: TurnTrust, tools: Sequence[TurnTool], *,
                 on_outcome: Callable[[dict[str, Any]], None] | None = None,
                 model_result_preparer: Callable[[Any], Any] | None = None) -> None:
        if not isinstance(trust, TurnTrust):
            raise TypeError("The dispatcher requires the owning turn's trust state")
        self.trust = trust
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("A tool name must select exactly one trusted registration")
        self._on_outcome = on_outcome
        self._model_result_preparer = model_result_preparer

    def _observe(self, tool: TurnTool, call_id: str, arguments, **outcome):
        observation = {"toolName": tool.name, "toolCallId": call_id, "arguments": deepcopy(arguments),
                       **({"resultContentSource": tool.result_content_source} if tool.result_content_source else {}),
                       **outcome}
        self.trust.observe(observation)
        if self._on_outcome is not None:
            self._on_outcome(observation)

    def dispatch(self, name: str, arguments: Mapping[str, Any], *, tool_call_id: str) -> Any:
        """Run the selected implementation, observe its actual terminal outcome, return it."""
        if name not in self._tools:
            raise KeyError(f"Unknown registered tool: {name}")
        if not isinstance(arguments, Mapping) or not isinstance(tool_call_id, str):
            raise TypeError("Tool calls require mapping arguments and an explicit call id")
        tool = self._tools[name]
        if inspect.iscoroutinefunction(tool.execute):
            raise TypeError("Async tool sources require dispatch_async")
        try:
            result = tool.execute(tool_call_id, arguments)
        except Exception as error:
            detail = {"name": getattr(error, "name", type(error).__name__), "message": str(error),
                      **{key: deepcopy(value) for key, value in vars(error).items() if key not in {"name", "stack"}}}
            self._observe(tool, tool_call_id, arguments, error=detail)
            raise
        self._observe(tool, tool_call_id, arguments, result=deepcopy(result))
        return self._model_result_preparer(result) if self._model_result_preparer else result

    async def dispatch_async(self, name: str, arguments: Mapping[str, Any], *, tool_call_id: str) -> Any:
        """Observe async tools only after their actual source execution settles."""
        if name not in self._tools:
            raise KeyError(f"Unknown registered tool: {name}")
        if not isinstance(arguments, Mapping) or not isinstance(tool_call_id, str):
            raise TypeError("Tool calls require mapping arguments and an explicit call id")
        tool = self._tools[name]
        try:
            result = tool.execute(tool_call_id, arguments)
            if inspect.isawaitable(result):
                result = await result
        except Exception as error:
            detail = {"name": getattr(error, "name", type(error).__name__), "message": str(error),
                      **{key: deepcopy(value) for key, value in vars(error).items() if key not in {"name", "stack"}}}
            self._observe(tool, tool_call_id, arguments, error=detail)
            raise
        self._observe(tool, tool_call_id, arguments, result=deepcopy(result))
        return self._model_result_preparer(result) if self._model_result_preparer else result
