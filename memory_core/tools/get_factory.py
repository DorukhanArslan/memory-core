"""Model-facing memory-get factory and complete JSON result boundary.

The factory is bound to one workspace and agent. A live configuration getter
may revoke the capability or update read policy without changing that owner.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_core.bootstrap._js import js_json_stringify
from memory_core.config import MemoryConfig
from memory_core.supplements import MemoryCorpusSupplement
from memory_core.tools.common import MemoryToolError
from memory_core.tools.memory_get import execute_memory_get_tool, memory_get_tool_definition

_DISABLED = "Memory is disabled for this agent. Enable memory search for this agent, then retry."


def serialize_get_tool_result(payload: Any) -> dict[str, Any]:
    """Native ``jsonResult``: complete details and their pretty JSON text."""
    return {
        "content": [{"type": "text", "text": js_json_stringify(payload, indent=2)}],
        "details": payload,
    }


def _owner(config: MemoryConfig) -> tuple[Path, str]:
    return config.workspace_dir.resolve(), config.agent_id


@dataclass(frozen=True)
class MemoryGetTool:
    """A captured definition with current host read policy checked on execution."""

    _definition: dict[str, Any]
    _config: MemoryConfig
    _get_config: Callable[[], MemoryConfig | None] | None
    _supplements: tuple[MemoryCorpusSupplement, ...]
    _owner: tuple[Path, str]
    _extra_paths: tuple[str | Path, ...]
    _agent_session_key: str | None
    _sandboxed: bool | None

    @property
    def definition(self) -> dict[str, Any]:
        return deepcopy(self._definition)

    @property
    def name(self) -> str:
        return self._definition["name"]

    @property
    def label(self) -> str:
        return self._definition["label"]

    @property
    def description(self) -> str:
        return self._definition["description"]

    @property
    def parameters(self) -> dict[str, Any]:
        return deepcopy(self._definition["parameters"])

    def execute(self, tool_call_id: str, params: object) -> dict[str, Any]:
        del tool_call_id
        config = self._get_config() if self._get_config is not None else self._config
        if config is None or not config.effective_flags().memory:
            raise MemoryToolError(_DISABLED, tool="memory_get")
        if _owner(config) != self._owner:
            raise MemoryToolError(
                "Memory get configuration belongs to a different workspace or agent; "
                "create a new tool for that owner.", tool="memory_get",
            )
        return serialize_get_tool_result(execute_memory_get_tool(
            config, params, supplements=list(self._supplements),
            extra_paths=self._extra_paths,
            agent_session_key=self._agent_session_key,
            sandboxed=self._sandboxed,
        ))


def create_memory_get_tool(
    config: MemoryConfig | None,
    *,
    get_config: Callable[[], MemoryConfig | None] | None = None,
    supplements: Sequence[MemoryCorpusSupplement] | None = None,
    extra_paths: Sequence[str | Path] = (),
    agent_session_key: str | None = None,
    sandboxed: bool | None = None,
) -> MemoryGetTool | None:
    """Create the read tool, or omit it for missing or disabled current config.

    A live getter takes precedence over the configuration snapshot. Source
    guidance and execution use the supplied trusted extra paths.
    Native memory-get has no argument-preparation hook.
    """
    current = get_config() if get_config is not None else config
    if current is None or not current.effective_flags().memory:
        return None
    definition = memory_get_tool_definition(extra_paths=extra_paths)
    definition["label"] = "Memory Get"
    return MemoryGetTool(
        definition, current, get_config, tuple(supplements or ()), _owner(current),
        tuple(extra_paths), agent_session_key, sandboxed,
    )
