"""Tool-call transport glue shared by ``HostKit.dispatch`` and ``FlushRequest.dispatch``.

A host's transport hands over the model's arguments as JSON text or an already-decoded
mapping. Decoding the text here deliberately differs from the core's ``asToolParamsRecord``
(``memory_core.tools.common.as_tool_params_record``, where a string reads as ``{}``): the core sees
decoded values, the kit sees the transport's raw text. Model-caused problems become the
``{"status": "error", "tool", "error"}`` payload upstream's tool adapter builds
(src/agents/agent-tool-definition-adapter.ts:228-284); host programming errors raise.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class ToolCallRefused(Exception):
    """A tool call the model got wrong; ``payload`` is what the model is sent back."""

    def __init__(self, tool: str, message: str) -> None:
        super().__init__(message)
        self.payload = tool_error(tool, message)


def tool_error(tool: str, message: str) -> dict[str, str]:
    return {"status": "error", "tool": tool, "error": message}


def read_tool_call(name: object, arguments: object) -> dict[str, Any]:
    """The call's arguments as a dict.

    ``None`` and blank text read as ``{}``. Raises ``TypeError`` for a non-string ``name`` or
    an ``arguments`` that is neither a mapping, text nor ``None`` (host errors), and
    :class:`ToolCallRefused` for text that is not JSON or not a JSON object.
    """
    if not isinstance(name, str):
        raise TypeError("tool name must be a string")
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        if not arguments.strip():
            return {}
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ToolCallRefused(name, f"invalid JSON arguments: {exc.msg}") from exc
        if not isinstance(arguments, dict):
            raise ToolCallRefused(name, "arguments must be a JSON object")
        return arguments
    if not isinstance(arguments, Mapping):
        raise TypeError("arguments must be a mapping, its JSON text or None")
    return dict(arguments)
