"""The host kit: memory-core's memory behaviour for one workspace as a few entry points.

``HostKit`` composes the core functions a host would otherwise call in order (workspace
seeding, the memory tools, the injected context, the memory flush, the session-memory hook,
the heartbeat turn). It never calls a model and keeps no per-session state: the host stores a
:class:`~memory_core.host.session.SessionState` per session and gets new copies back. The
specification, the upstream anchors and the parity labels are in docs/host_kit.md.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from memory_core.bootstrap import (
    DEFAULT_WORKSPACE_LAYOUT,
    WorkspaceInitResult,
    WorkspaceLayout,
    initialize_agent_workspace,
)
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation import record_short_term_recalls, undecorate_search_results
from memory_core.curation import CurationPolicy, MemoryCurator
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.host._calls import ToolCallRefused, read_tool_call, tool_error
from memory_core.host.session import SessionState
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.tools.common import MemoryToolInputError, to_tool_error
from memory_core.tools.memory_get import (
    MEMORY_GET_TOOL_NAME,
    execute_memory_get_tool,
    memory_get_tool_definition,
)
from memory_core.tools.memory_search import (
    MEMORY_SEARCH_TOOL_NAME,
    execute_memory_search_tool,
    memory_search_tool_definition,
)


class HostKit:
    """The host kit for one workspace root (docs/host_kit.md, "Object model").

    ``memory`` is the workspace's :class:`~memory_core.client.Memory` (config, flags, store).
    The options are inputs of the core functions the kit composes. ``seed_bootstrap=None``
    seeds BOOTSTRAP.md only when ``templates`` supplies the layout's bootstrap file (memory-core has
    no ritual text of its own); ``False`` marks setup complete at once. Construction does no
    I/O beyond validating the options; the kit is immutable afterwards.
    """

    def __init__(
        self,
        memory: Memory,
        *,
        layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
        templates: Mapping[str, str] | None = None,
        seed_bootstrap: bool | None = None,
        timezone: str = "UTC",
        identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
        curation_policy: CurationPolicy | None = None,
        dreaming_enabled: bool = False,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._memory = memory
        self._root = memory.workspace.root
        self._layout = layout
        self._templates = dict(templates) if templates is not None else None
        self._seed_bootstrap = (
            seed_bootstrap
            if seed_bootstrap is not None
            else layout.bootstrap_file in (self._templates or {})
        )
        self._identity = identity
        self._dreaming_enabled = dreaming_enabled
        self._clock = now_ms or (lambda: time.time_ns() // 1_000_000)
        # The curator validates the timezone and the policy against the layout.
        self._curator = memory.curator(
            layout=layout, policy=curation_policy, timezone=timezone, now_ms=self._clock
        )

    @classmethod
    def open(
        cls,
        workspace_dir: str | os.PathLike[str],
        *,
        embedding_provider: EmbeddingProvider | None = None,
        config: MemoryConfig | None = None,
        **options: Any,
    ) -> HostKit:
        """Open a workspace: the store, the kit, one :meth:`ensure` and one reindex.

        ``options`` are the keyword options of ``__init__``. The store config is checked before
        anything is written (the default config is hybrid, so pass an embedder or
        ``FeatureFlags(vector_search=False)``). ``Memory`` is opened without
        ``initialize_memory_core_workspace``: its MEMORY.md would count as setup evidence and
        keep BOOTSTRAP.md from being seeded.
        """
        memory = Memory.from_workspace(
            Path(workspace_dir),
            embedding_provider=embedding_provider,
            config=config,
            initialize=False,
            reindex=False,
        )
        kit = cls(memory, **options)
        kit.ensure()
        memory.store.reindex(memory.workspace)
        return kit

    @property
    def memory(self) -> Memory:
        return self._memory

    @property
    def curator(self) -> MemoryCurator:
        """The curator :meth:`dispatch` runs curated writes through (reindexes after them)."""
        return self._curator

    def ensure(self) -> WorkspaceInitResult:
        """Seed the workspace and run the BOOTSTRAP.md lifecycle.

        ``initialize_agent_workspace`` with the kit's layout, templates and seed setting:
        upstream runs ``ensureAgentWorkspace`` on every reply
        (src/auto-reply/reply/get-reply.ts:443-448), which is where BOOTSTRAP.md is reconciled
        away once setup evidence appears.
        """
        return initialize_agent_workspace(
            self._root,
            layout=self._layout,
            templates=self._templates,
            seed_bootstrap=self._seed_bootstrap,
            now_ms=self._clock(),
        )

    def tools(self) -> list[dict[str, Any]]:
        """Provider-neutral ``{"name", "description", "parameters"}`` specs of the kit's tools.

        ``memory_search`` and ``memory_get`` (pin-era definitions until port plan area 5), then
        the curation tools the flag and the policy allow.
        """
        return [
            memory_search_tool_definition(),
            memory_get_tool_definition(),
            *self._curator.tool_definitions(),
        ]

    def dispatch(
        self,
        name: str,
        arguments: Mapping[str, Any] | str | None,
        *,
        session: SessionState,
    ) -> dict[str, Any]:
        """Run one tool call of the model and return the payload to send back verbatim.

        ``arguments`` is a mapping, its JSON text or ``None``. Every model-caused error is an
        ``{"status": "error", "tool", "error"}`` payload (docs/host_kit.md, entry point 2):
        invalid JSON, a non-object, a tool :meth:`tools` does not offer, bad params and refused
        curated writes (``MemoryToolInputError``), and any other ``Exception`` a tool raises.
        ``TypeError`` for a non-string name or arguments of another type.
        """
        try:
            args = read_tool_call(name, arguments)
        except ToolCallRefused as refused:
            return refused.payload
        if name not in {tool["name"] for tool in self.tools()}:
            return tool_error(name, f"tool {name} is not available")
        try:
            if name == MEMORY_SEARCH_TOOL_NAME:
                return self._memory_search(args, session)
            if name == MEMORY_GET_TOOL_NAME:
                return execute_memory_get_tool(self._memory.config, args)
            return self._curator.dispatch(name, args)
        except MemoryToolInputError as error:
            return error.to_tool_error(name)
        except Exception as error:
            return to_tool_error(error, tool=name)

    def _memory_search(self, args: dict[str, Any], session: SessionState) -> dict[str, Any]:
        memory = self._memory
        result = execute_memory_search_tool(
            memory.config,
            memory.store,
            args,
            agent_session_key=session.session_key,
            runtime_identity=self._identity,
        )
        if self._dreaming_enabled and not result.get("unavailable"):
            # tools.ts:491-507: with dreaming enabled, a successful search records its
            # memory-corpus hits (raw, without the Source: citation) off the reply path and
            # ignores recording errors.
            hits = [hit for hit in result.get("results") or [] if hit.get("corpus") == "memory"]
            try:
                record_short_term_recalls(
                    config=memory.config,
                    query=str(args.get("query", "")),
                    results=undecorate_search_results(hits),
                    now_ms=self._clock(),
                )
            except Exception:
                pass
        return result
