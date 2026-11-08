"""Model-facing memory-search factory and its JSON result boundary.

The supplied store belongs to one workspace. A live config getter may revoke
the tool or update search policy, but cannot route that store to another owner.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from memory_core.bootstrap._js import js_json_stringify
from memory_core.config import MemoryConfig
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.supplements import MemoryCorpusSupplement
from memory_core.tools.common import MemoryToolError, as_tool_params_record
from memory_core.tools.memory_search import (
    MemorySearchToolContext,
    execute_memory_search_tool,
    memory_search_tool_definition,
)

_DISABLED = "Memory is disabled for this agent. Enable memory search for this agent, then retry."


def prepare_memory_search_arguments(params: object) -> object:
    """Normalize numeric aliases without changing inputs or hiding invalid values.

    With no aliases the original object is returned, including non-record input.
    Explicit camelCase values always win, even when null or otherwise invalid.
    """
    raw = as_tool_params_record(params)
    if "min_score" not in raw and "max_results" not in raw:
        return params
    normalized = dict(raw)
    for alias, key in (("min_score", "minScore"), ("max_results", "maxResults")):
        if alias in normalized:
            if key not in normalized:
                normalized[key] = normalized[alias]
            del normalized[alias]
    return normalized


def serialize_search_tool_result(payload: Any) -> dict[str, Any]:
    """Native ``jsonResult``: pretty JSON text plus the complete original details."""
    return {"content": [{"type": "text", "text": js_json_stringify(payload, indent=2)}],
            "details": payload}


def _enabled(context: MemorySearchToolContext) -> bool:
    return context.enabled() if callable(context.enabled) else context.enabled


def _owner(config: MemoryConfig) -> tuple[Path, Path, str]:
    return (config.workspace_dir.resolve(), config.resolved_store_path().resolve(), config.agent_id)


@dataclass(frozen=True)
class MemorySearchTool:
    """A fixed definition with live configuration checked at every execution."""

    _definition: dict[str, Any]
    _config: MemoryConfig
    _store: SQLiteMemoryStore
    _get_config: Callable[[], MemoryConfig | None] | None
    _context: MemorySearchToolContext
    _agent_session_key: str | None
    _active_project_keys: tuple[str, ...] | None
    _supplements: tuple[MemoryCorpusSupplement, ...]
    _runtime_identity: RuntimeIdentity
    _owner: tuple[Path, Path, str]

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

    @staticmethod
    def prepare_arguments(params: object) -> object:
        return prepare_memory_search_arguments(params)

    def execute(self, tool_call_id: str, params: object) -> dict[str, Any]:
        del tool_call_id
        config = self._get_config() if self._get_config is not None else self._config
        if config is None or not config.effective_flags().memory or not _enabled(self._context):
            raise MemoryToolError(_DISABLED, tool="memory_search")
        manager_started = self._context.clock() if self._context.manager_ms is None else None
        store = self._store
        if _owner(config) != self._owner:
            raise MemoryToolError(
                "Memory search configuration belongs to a different workspace or index; "
                "create a new tool with its matching store.", tool="memory_search",
            )
        # A factory acquires its already-open manager by resolving its captured
        # store and validating ownership. Direct SDK retrieval has no acquisition.
        execution_context = replace(self._context, enabled=True)
        if manager_started is not None:
            execution_context = replace(
                execution_context, manager_ms=max(0, self._context.clock() - manager_started),
            )
        payload = execute_memory_search_tool(
            config, store, params,
            supplements=list(self._supplements),
            agent_session_key=self._agent_session_key,
            active_project_keys=self._active_project_keys,
            runtime_identity=self._runtime_identity,
            # Enablement was resolved once above, alongside the live config.
            context=execution_context,
        )
        return serialize_search_tool_result(payload)


def create_memory_search_tool(
    config: MemoryConfig | None,
    store: SQLiteMemoryStore,
    *,
    get_config: Callable[[], MemoryConfig | None] | None = None,
    context: MemorySearchToolContext | None = None,
    agent_session_key: str | None = None,
    active_project_keys: Sequence[str] | None = None,
    conversation_recall: Mapping[str, Any] | None = None,
    supplements: Sequence[MemoryCorpusSupplement] | None = None,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
    extra_paths: Sequence[str | Path] = (),
) -> MemorySearchTool | None:
    """Create the native-shaped tool, or omit it when current config is disabled.

    ``FeatureFlags.memory`` and ``context.enabled`` resolve host enable policy.
    ``extra_paths`` affects source guidance; the host still owns indexing them.
    A live getter takes precedence over the supplied configuration snapshot.
    """
    current = get_config() if get_config is not None else config
    execution_context = context if context is not None else MemorySearchToolContext()
    if current is None or not current.effective_flags().memory or not _enabled(execution_context):
        return None
    if _owner(store.config) != _owner(current):
        raise MemoryToolError(
            "Memory search configuration belongs to a different workspace or index; "
            "create a new tool with its matching store.", tool="memory_search",
        )
    if conversation_recall is not None:
        execution_context = replace(
            execution_context, conversation_recall_corpus=conversation_recall.get("corpus"),
        )
    definition = memory_search_tool_definition(
        index_sessions=current.session_search, extra_paths=extra_paths,
    )
    definition["label"] = "Memory Search"
    return MemorySearchTool(
        definition, current, store, get_config, execution_context, agent_session_key,
        tuple(active_project_keys) if active_project_keys is not None else None,
        tuple(supplements or ()), runtime_identity, _owner(current),
    )
