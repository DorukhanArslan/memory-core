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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from memory_core.bootstrap import (
    DEFAULT_BOOTSTRAP_MAX_CHARS,
    DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
    DEFAULT_WORKSPACE_LAYOUT,
    WorkspaceContext,
    WorkspaceInitResult,
    WorkspaceLayout,
    build_workspace_context,
    initialize_agent_workspace,
)
from memory_core.bootstrap.budget import BootstrapPromptWarningMode
from memory_core.bootstrap.files import (
    BootstrapContextMode,
    BootstrapContextRunKind,
    ContextInjectionMode,
)
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation import record_short_term_recalls, undecorate_search_results
from memory_core.curation import CurationPolicy, MemoryCurator
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.host._calls import ToolCallRefused, read_tool_call, tool_error
from memory_core.host.session import SessionState
from memory_core.prompt_section import build_prompt_section
from memory_core.runtime_context_prompt import build_runtime_context_system_context
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

# Session kinds that get upstream's minimal system prompt, which has no Memory Recall section
# (src/agents/system-prompt.ts:202-225 buildMemorySection returns nothing when isMinimal).
MINIMAL_PROMPT_KINDS = frozenset({"subagent", "cron"})
_RUN_KINDS = (None, "default", "heartbeat", "cron")
_CONTEXT_MODES = ("full", "lightweight")


@dataclass(frozen=True)
class TurnContext:
    """What one turn sends the model, and the session state to pass to ``after_turn``.

    ``system_prompt`` is the stable part (Memory Recall, then the workspace's bootstrap
    sections and Project Context) for above a prompt-cache boundary; ``runtime_context`` the
    marker-wrapped dynamic block for below it. ``memory_recall`` holds the Memory Recall lines
    inside ``system_prompt`` and ``workspace`` the core result they were built from.
    ``workspace_init`` is ``None`` when the call ran no ensure.
    """

    session: SessionState
    system_prompt: str
    runtime_context: str | None
    tools: tuple[dict[str, Any], ...]
    memory_recall: tuple[str, ...]
    workspace: WorkspaceContext
    workspace_init: WorkspaceInitResult | None


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
        bootstrap_max_chars: int = DEFAULT_BOOTSTRAP_MAX_CHARS,
        bootstrap_total_max_chars: int = DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
        context_injection: ContextInjectionMode = "always",
        truncation_warning_mode: BootstrapPromptWarningMode = "always",
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
        self._bootstrap_max_chars = bootstrap_max_chars
        self._bootstrap_total_max_chars = bootstrap_total_max_chars
        self._context_injection = context_injection
        self._truncation_warning_mode = truncation_warning_mode
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

    def before_turn(
        self,
        session: SessionState,
        *,
        runtime_context: str | None = None,
        run_kind: BootstrapContextRunKind | None = None,
        context_mode: BootstrapContextMode = "full",
        has_bootstrap_file_access: bool = False,
        offer_tools: bool = True,
        ensure: bool = True,
    ) -> TurnContext:
        """The system prompt, runtime block and tools of one turn (docs/host_kit.md, entry 3).

        Runs :meth:`ensure` first unless ``ensure=False`` (an inspector, or a host that already
        ran it for this turn), then ``build_workspace_context`` for the session and the Memory
        Recall section for the offered tools (none for the minimal kinds, none with
        ``offer_tools=False``). ``run_kind`` defaults from the session kind. No search results
        are injected: the model recalls through the tools. Pass the returned ``session`` to
        ``after_turn`` only for a turn that completed.
        """
        if run_kind not in _RUN_KINDS:
            raise ValueError(f"run_kind must be default, heartbeat or cron, got {run_kind!r}")
        if context_mode not in _CONTEXT_MODES:
            raise ValueError(f"context_mode must be full or lightweight, got {context_mode!r}")
        workspace_init = self.ensure() if ensure else None
        workspace = self._workspace_context(
            session,
            run_kind=run_kind,
            context_mode=context_mode,
            has_bootstrap_file_access=has_bootstrap_file_access,
        )
        tools = tuple(self.tools()) if offer_tools else ()
        memory_recall = (
            ()
            if session.kind in MINIMAL_PROMPT_KINDS
            else tuple(
                build_prompt_section(
                    {tool["name"] for tool in tools},
                    citations_mode=self._memory.config.citation_mode,
                )
            )
        )
        # Upstream puts the memory section before the workspace sections (system-prompt.ts:1059).
        system_prompt = "\n\n".join(
            part
            for part in ("\n".join(memory_recall).strip(), workspace.prompt_text.strip())
            if part
        )
        runtime_text = runtime_context.strip() if runtime_context else ""
        return TurnContext(
            session=replace(
                session,
                seen_truncation_signatures=tuple(
                    workspace.prompt_warning.warning_signatures_seen
                ),
                completed_bootstrap_turn=(
                    session.completed_bootstrap_turn or workspace.record_completed_bootstrap_turn
                ),
            ),
            system_prompt=system_prompt,
            runtime_context=(
                build_runtime_context_system_context(runtime_text, identity=self._identity)
                if runtime_text
                else None
            ),
            tools=tools,
            memory_recall=memory_recall,
            workspace=workspace,
            workspace_init=workspace_init,
        )

    def _workspace_context(
        self,
        session: SessionState,
        *,
        run_kind: BootstrapContextRunKind | None = None,
        context_mode: BootstrapContextMode = "full",
        has_bootstrap_file_access: bool = False,
    ) -> WorkspaceContext:
        return build_workspace_context(
            self._root,
            layout=self._layout,
            session_kind=session.kind,
            run_kind=run_kind,
            context_mode=context_mode,
            context_injection=self._context_injection,
            has_completed_bootstrap_turn=session.completed_bootstrap_turn,
            has_bootstrap_file_access=has_bootstrap_file_access,
            max_chars=self._bootstrap_max_chars,
            total_max_chars=self._bootstrap_total_max_chars,
            truncation_warning_mode=self._truncation_warning_mode,
            seen_truncation_signatures=session.seen_truncation_signatures,
            identity=self._identity,
        )

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
