"""The host kit: the memory behaviour of one workspace as a few entry points.

``HostKit`` composes the core functions a host would otherwise call in order (workspace
seeding, the memory tools, the injected context, the memory flush, the session-memory hook,
the heartbeat turn). It never calls a model and keeps no per-session state: the host stores a
:class:`~memory_core.host.session.SessionState` per session and gets new copies back. The
specification, the upstream anchors and the parity labels are in docs/host_kit.md.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, get_args

from memory_core._memory_flush_constants import CONVERSATION_CONTEXT_HEADER
from memory_core.automation import (
    AutomationStore,
    FileAutomationStore,
    due_automation_jobs,
    heartbeat_scheduled_tasks,
)
from memory_core.bootstrap import (
    DEFAULT_BOOTSTRAP_MAX_CHARS,
    DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
    DEFAULT_WORKSPACE_LAYOUT,
    WorkspaceContext,
    WorkspaceInitResult,
    WorkspaceLayout,
    build_startup_context,
    build_workspace_context,
    format_session_reset_transcript_prompt,
    initialize_agent_workspace,
    resolve_bare_session_reset_prompt_state,
    should_apply_startup_context,
)
from memory_core.bootstrap.budget import BootstrapPromptWarningMode
from memory_core.bootstrap.files import (
    BootstrapContextMode,
    BootstrapContextRunKind,
    BootstrapMode,
    ContextInjectionMode,
)
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation import record_short_term_recalls, undecorate_search_results
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.current_time import DEFAULT_TIME_FORMAT, TimeFormat, resolve_time_format
from memory_core.curation import CurationPolicy, MemoryCurator
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.heartbeat import prepare_heartbeat_turn, resolve_message_text
from memory_core.host._calls import ToolCallRefused, read_tool_call, tool_error
from memory_core.host.flush import FlushRequest
from memory_core.host.heartbeat_run import HeartbeatRun
from memory_core.host.session import SessionState, TurnUsage, apply_turn_usage
from memory_core.host.tool_calls import ToolCallRepair, repair_tool_calls
from memory_core.memory_flush import (
    MemoryFlushFailureOutcome,
    MemoryFlushPlan,
    MemoryFlushTriggerDecision,
    build_memory_flush_plan_from_config,
    ensure_memory_flush_target_file,
    has_already_flushed_for_current_compaction,
    record_memory_flush_failure,
    resolve_memory_flush_runtime_accounting,
    resolve_memory_flush_runtime_skip,
)
from memory_core.memory_paths import UnsafeMemoryPathError
from memory_core.prompt_section import build_prompt_section
from memory_core.runtime_context_prompt import build_runtime_context_system_context
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_memory import SessionMemoryResult, SlugGenerator, save_session_memory
from memory_core.session_visibility import SessionVisibilityContext
from memory_core.tools.common import MemoryToolError, to_tool_error
from memory_core.tools.search_factory import prepare_memory_search_arguments
from memory_core.tools.memory_get import (
    MEMORY_GET_TOOL_NAME,
    execute_memory_get_tool,
    memory_get_tool_definition,
)
from memory_core.tools.memory_search import (
    MEMORY_SEARCH_TOOL_NAME,
    MemorySearchToolContext,
    execute_memory_search_tool,
    memory_search_tool_definition,
)

# Session kinds that get upstream's minimal system prompt, which has no Memory Recall section
# (src/agents/system-prompt.ts:202-225 buildMemorySection returns nothing when isMinimal).
MINIMAL_PROMPT_KINDS = frozenset({"subagent", "cron"})
# Upstream DEFAULT_CONTEXT_TOKENS (src/agents/defaults.ts:6): the flush window when the host
# does not know the model's context size.
DEFAULT_CONTEXT_WINDOW_TOKENS = 200_000
# The reason of a HostKit.request_flush run (memory-core extension, decision Q6).
_FORCED_FLUSH_REASON = "forced"
# The core's Literal types, so a value check never drifts from them.
_RUN_KINDS = (None, *get_args(BootstrapContextRunKind))
_CONTEXT_MODES = get_args(BootstrapContextMode)
_BOOTSTRAP_MODES = get_args(BootstrapMode)


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


@dataclass(frozen=True)
class TurnRecord:
    """A completed turn: the session with its token snapshot and the flush decision.

    ``flush_plan`` is the plan for the turn's context window (the meter's terms);
    ``flush_decision`` is ``explain_memory_flush_trigger``'s answer. ``flush`` is set when the
    flush is due; ``flush_failure`` when it was due but its target file could not be created,
    which counts as one failed flush, as upstream (``session`` then carries that strike).
    """

    session: SessionState
    flush_plan: MemoryFlushPlan | None
    flush_decision: MemoryFlushTriggerDecision
    flush: FlushRequest | None = None
    flush_failure: MemoryFlushFailureOutcome | None = None


@dataclass(frozen=True)
class ResetTurn:
    """The turn a bare ``/new`` or ``/reset`` starts (upstream prompt-prelude.ts:200-225).

    ``model_prompt`` is the next user message for the model: ``startup_context`` (when the
    bootstrap mode is ``none``) and the reset ``prompt``, joined by a blank line.
    ``transcript_prompt`` is what the transcript records instead.
    """

    model_prompt: str
    transcript_prompt: str
    bootstrap_mode: BootstrapMode
    startup_context: str | None
    prompt: str

    def to_json(self) -> dict[str, Any]:
        return {
            "modelPrompt": self.model_prompt,
            "transcriptPrompt": self.transcript_prompt,
            "bootstrapMode": self.bootstrap_mode,
            "startupContext": self.startup_context,
            "prompt": self.prompt,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ResetTurn:
        """Read :meth:`to_json` output; ``ValueError`` for anything else.

        ``modelPrompt``, ``transcriptPrompt``, ``bootstrapMode`` and ``prompt`` are required; a
        missing ``startupContext`` reads as null and unknown keys are ignored.
        """
        if not isinstance(data, Mapping):
            raise ValueError("not a reset turn: expected an object")
        texts = {}
        for key in ("modelPrompt", "transcriptPrompt", "prompt"):
            if not isinstance(data.get(key), str):
                raise ValueError(f"not a reset turn: {key} must be a string")
            texts[key] = data[key]
        mode = data.get("bootstrapMode")
        if mode not in _BOOTSTRAP_MODES:
            raise ValueError(f"not a reset turn: unknown bootstrapMode {mode!r}")
        startup = data.get("startupContext")
        if startup is not None and not isinstance(startup, str):
            raise ValueError("not a reset turn: startupContext must be a string or null")
        return cls(
            model_prompt=texts["modelPrompt"],
            transcript_prompt=texts["transcriptPrompt"],
            bootstrap_mode=mode,
            startup_context=startup,
            prompt=texts["prompt"],
        )


@dataclass(frozen=True)
class NewSession:
    """A new session after ``/new`` or ``/reset``: same key and kind, new id, fresh entry.

    ``saved`` is the ending session's ``memory/<date>-<slug>.md``; ``reset`` is set for a bare
    command only.
    """

    session: SessionState
    saved: SessionMemoryResult
    workspace_init: WorkspaceInitResult
    reset: ResetTurn | None


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
        time_format: TimeFormat = DEFAULT_TIME_FORMAT,
        identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
        curation_policy: CurationPolicy | None = None,
        bootstrap_max_chars: int = DEFAULT_BOOTSTRAP_MAX_CHARS,
        bootstrap_total_max_chars: int = DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
        context_injection: ContextInjectionMode = "always",
        truncation_warning_mode: BootstrapPromptWarningMode = "always",
        dreaming_enabled: bool = False,
        automation_store: AutomationStore | None = None,
        now_ms: Callable[[], int] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        artifact_provenance: MemoryArtifactProvenanceStore | None = None,
        flush_config: Mapping[str, Any] | None = None,
        flush_read_tool: Mapping[str, Any] | None = None,
        flush_read_dispatch: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
        active_project_keys: Sequence[str] | None = None,
        session_visibility: SessionVisibilityContext | None = None,
        source_policy: Mapping[str, Any] | None = None,
    ) -> None:
        self._memory = memory
        self._session_visibility = (
            session_visibility if session_visibility is not None else memory.session_visibility
        )
        policy = source_policy if source_policy is not None else memory.source_policy
        self._source_policy = deepcopy(dict(policy)) if policy is not None else None
        # Writes, ingestion and indexing must consult the same host trust ledger.
        existing_provenance = memory.store.artifact_provenance
        if (artifact_provenance is not None and existing_provenance is not None
                and artifact_provenance.path != existing_provenance.path):
            raise ValueError("HostKit and memory store must use the same artifact provenance store")
        self._artifact_provenance = (
            artifact_provenance if artifact_provenance is not None else existing_provenance
        )
        self._root = memory.workspace.root
        # The host's sink for the ``memory.recall.*`` events of recorded searches.
        self._on_event = on_event
        self._layout = layout
        self._templates = dict(templates) if templates is not None else None
        self._seed_bootstrap = (
            seed_bootstrap
            if seed_bootstrap is not None
            else layout.bootstrap_file in (self._templates or {})
        )
        self._timezone = timezone
        self._flush_config = deepcopy(dict(flush_config)) if flush_config is not None else {}
        if (flush_read_tool is None) != (flush_read_dispatch is None):
            raise ValueError("flush_read_tool and flush_read_dispatch must be supplied together")
        if flush_read_tool is not None and flush_read_tool.get("name") != "read":
            raise ValueError("the delegated flush read tool must be named read")
        if flush_read_dispatch is not None and not callable(flush_read_dispatch):
            raise TypeError("flush_read_dispatch must be callable")
        self._flush_read_tool = deepcopy(dict(flush_read_tool)) if flush_read_tool is not None else None
        self._flush_read_dispatch = flush_read_dispatch
        self._time_format = resolve_time_format(time_format)
        self._identity = identity
        # Project ranking context is supplied by the trusted host, never by
        # model-authored memory_search arguments. This kit stays immutable.
        self._active_project_keys = (
            tuple(active_project_keys) if active_project_keys is not None else None
        )
        self._bootstrap_max_chars = bootstrap_max_chars
        self._bootstrap_total_max_chars = bootstrap_total_max_chars
        self._context_injection = context_injection
        self._truncation_warning_mode = truncation_warning_mode
        self._dreaming_enabled = dreaming_enabled
        self._automation_store = (
            automation_store if automation_store is not None else FileAutomationStore(self._root)
        )
        self._clock = now_ms or (lambda: time.time_ns() // 1_000_000)
        # The curator validates the timezone and the policy against the layout.
        self._curator = memory.curator(
            layout=layout, policy=curation_policy, timezone=timezone, now_ms=self._clock
        )
        memory.store.artifact_provenance = self._artifact_provenance

    @classmethod
    def open(
        cls,
        workspace_dir: str | os.PathLike[str],
        *,
        embedding_provider: EmbeddingProvider | None = None,
        config: MemoryConfig | None = None,
        session_catalog: MemorySessionCatalog | None = None,
        session_visibility: SessionVisibilityContext | None = None,
        source_policy: Mapping[str, Any] | None = None,
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
            session_catalog=session_catalog,
            session_visibility=session_visibility,
            source_policy=source_policy,
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
        A dispatched curated publication error also retains the production
        owner's ``publication`` state so the host can reconcile before retrying.
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
                return self._memory_search(prepare_memory_search_arguments(args), session)
            if name == MEMORY_GET_TOOL_NAME:
                return execute_memory_get_tool(self._memory.config, args)
            return self._curator.dispatch(name, args)
        except MemoryToolError as error:
            return error.to_tool_error(name)
        except Exception as error:
            return to_tool_error(error, tool=name)

    def dispatcher(
        self, session: SessionState
    ) -> Callable[[str, Mapping[str, Any] | str | None], dict[str, Any]]:
        """:meth:`dispatch` bound to ``session``: ``FlushRequest.dispatch``'s two-argument shape.

        One tool-answering helper then serves a turn and its flush run. The returned function
        looks :meth:`dispatch` up at each call and adds nothing to it; ``TypeError`` at once for
        a ``session`` that is not a :class:`SessionState` (docs/host_kit.md, F24).
        """
        if not isinstance(session, SessionState):
            raise TypeError("session must be a SessionState")

        def run_tool(name: str, arguments: Mapping[str, Any] | str | None) -> dict[str, Any]:
            return self.dispatch(name, arguments, session=session)

        return run_tool

    def _memory_search(self, args: dict[str, Any], session: SessionState) -> dict[str, Any]:
        memory = self._memory
        host_options: dict[str, Any] = {}
        if self._active_project_keys is not None:
            host_options["active_project_keys"] = self._active_project_keys
        if self._session_visibility is not None or self._source_policy is not None:
            host_options["context"] = MemorySearchToolContext(
                session_visibility=self._session_visibility,
                source_policy=self._source_policy,
            )
        result = execute_memory_search_tool(
            memory.config,
            memory.store,
            args,
            agent_session_key=session.session_key,
            runtime_identity=self._identity,
            **host_options,
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
                    on_event=self._on_event,
                )
            except Exception:
                pass
        return result

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

    def repair_tool_calls(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        allowed_tool_names: Iterable[str] | None = None,
    ) -> ToolCallRepair:
        """Upstream's replay repair of the history's tool calls, for the next model call.

        A turn that failed between a tool-call reply and its tool results leaves calls
        without results; send ``repair_tool_calls(history).messages`` to the model instead of the
        history (upstream repairs the replayed history the same way at the start of each
        attempt, replay-history.ts:793,819) and keep the stored transcript as it is. Unchanged
        rows come back as the host's objects; a missing result becomes a synthetic error row
        with upstream's text (docs/host_kit.md, F26). Reads no file and writes nothing.
        """
        return repair_tool_calls(messages, allowed_tool_names=allowed_tool_names)

    def after_turn(
        self,
        session: SessionState,
        *,
        transcript: Sequence[Mapping[str, Any]],
        usage: TurnUsage | None,
        context_window_tokens: int | None = None,
        transcript_bytes: int | None = None,
        redact: Callable[[str], str] | None = None,
        untrusted_turn: bool | Callable[[], bool] = False,
        assert_current: Callable[[], None] | None = None,
        transcript_events: Sequence[Mapping[str, Any]] | None = None,
        prompt_for_estimate: str = "",
        memory_flush_writable: bool = True,
        is_cli: bool = False,
    ) -> TurnRecord:
        """Record a completed turn and decide the memory flush (docs/host_kit.md, entry 4).

        Upstream v2026.9.6 decides the flush after a delivered reply, in session maintenance
        (src/auto-reply/reply/agent-runner-result-complete.ts:288, agent-runner-maintenance.ts),
        with ``promptForEstimate: ""`` (src/agents/session-maintenance/run.ts:218-232).
        Fresh totals do not read transcript usage when that estimate is empty. Stale totals
        recover provider usage and projected trailing messages from ``transcript_events``
        (or ``transcript`` wrapped as message events). ``context_window_tokens`` defaults to
        :data:`DEFAULT_CONTEXT_WINDOW_TOKENS`; without ``transcript_bytes`` the transcript-size
        gate stays off. Heartbeat sessions never flush. A due flush first creates its empty
        target (``ensure_memory_flush_target_file``, agent-runner-memory.ts:1447-1451), then
        returns the :class:`~memory_core.host.flush.FlushRequest` over ``transcript``, the host's
        visible messages of the session. The kit keeps no pending-flush state: the host runs the
        session's next ``after_turn`` only after that request's ``complete`` (or after abandoning
        it), as upstream serializes session maintenance per session key
        (src/agents/session-maintenance/coordinator.ts). ``redact`` maps the message of a target
        that cannot be created (``TurnRecord.flush_failure.error``), as
        ``FlushRequest.complete(redact=)`` does for a failed run. With an ``artifact_provenance``
        store the flush's appends record the daily note's trust; ``untrusted_turn`` (a bool, or a
        callable read at each write) marks the turn tainted or its sender not the owner, so the note
        is recorded ``untrusted`` and the dreaming ingestion and promotion treat it so.
        ``assert_current`` may raise when the host's flush authority is cancelled or stale; it
        is checked during target preparation, before handing off the request, at dispatch and
        before completion records a result. Its exception propagates without a failure strike.
        Supply a synchronous check that returns promptly; the host owns its authority state.
        """
        return self.prepare_flush(
            apply_turn_usage(session, usage), transcript=transcript,
            context_window_tokens=context_window_tokens, transcript_bytes=transcript_bytes,
            redact=redact, untrusted_turn=untrusted_turn, assert_current=assert_current,
            transcript_events=transcript_events, prompt_for_estimate=prompt_for_estimate,
            memory_flush_writable=memory_flush_writable, is_cli=is_cli,
        )

    def prepare_flush(
        self,
        session: SessionState,
        *,
        transcript: Sequence[Mapping[str, Any]] = (),
        context_window_tokens: int | None = None,
        transcript_bytes: int | None = None,
        transcript_events: Sequence[Mapping[str, Any]] | None = None,
        prompt_for_estimate: str = "",
        memory_flush_writable: bool = True,
        is_cli: bool = False,
        is_heartbeat: bool | None = None,
        redact: Callable[[str], str] | None = None,
        untrusted_turn: bool | Callable[[], bool] = False,
        assert_current: Callable[[], None] | None = None,
    ) -> TurnRecord:
        """Evaluate a persisted session's flush without recording a new model usage.

        This is the native maintenance admission path. Supply active context-eligible
        chronological ``transcript_events`` and their actual serialized ``transcript_bytes``
        from one host storage snapshot. If events are omitted, visible ``transcript`` messages
        are used for usage recovery. The host persists the returned session and serializes
        maintenance per session; this kit neither owns a turn queue nor guesses byte sizes.
        ``prompt_for_estimate`` is empty for maintenance, or the next input for a preflight
        projection. ``memory_flush_writable`` and ``is_cli`` describe the host runtime.
        """
        window = (
            context_window_tokens
            if context_window_tokens is not None
            else DEFAULT_CONTEXT_WINDOW_TOKENS
        )
        recorded = session
        entry = dict(recorded.entry)
        heartbeat = recorded.kind == "heartbeat" if is_heartbeat is None else is_heartbeat
        skip = resolve_memory_flush_runtime_skip(
            entry=entry, session_key=recorded.session_key,
            memory_flush_writable=memory_flush_writable, is_heartbeat=heartbeat, is_cli=is_cli,
        )
        if skip is not None:
            return TurnRecord(session=recorded, flush_plan=None, flush_decision=skip)
        plan = self._flush_plan(window)
        events = transcript_events if transcript_events is not None else tuple(
            {"type": "message", "message": dict(message)} for message in transcript
        )
        accounting = resolve_memory_flush_runtime_accounting(
            entry=entry, plan=plan, context_window_tokens=window,
            transcript_events=events, transcript_byte_size=transcript_bytes,
            prompt_for_estimate=prompt_for_estimate, session_key=recorded.session_key,
            identity=self._identity,
        )
        decision = accounting.decision
        entry = accounting.entry if accounting.entry is not None else entry
        recorded = replace(recorded, entry=entry)
        if not decision.should_flush:
            return TurnRecord(session=recorded, flush_plan=plan, flush_decision=decision)
        authority_error: BaseException | None = None

        def check_current() -> None:
            nonlocal authority_error
            if assert_current is not None:
                try:
                    assert_current()
                except BaseException as error:
                    authority_error = error
                    raise

        try:
            ensure_memory_flush_target_file(
                self._root, plan.relative_path, assert_current=check_current
            )
        except (UnsafeMemoryPathError, OSError) as error:
            if error is authority_error:
                raise
            if authority_error is not None:
                raise authority_error from error
            # A failed flush preparation is a failed flush (agent-runner-memory.ts recordFailure).
            failure = record_memory_flush_failure(entry, error=error, redact=redact)
            return TurnRecord(
                session=replace(recorded, entry=failure.entry),
                flush_plan=plan,
                flush_decision=decision,
                flush_failure=failure,
            )
        return TurnRecord(
            session=recorded,
            flush_plan=plan,
            flush_decision=decision,
            flush=self._flush_request(
                recorded,
                plan,
                transcript,
                reason=decision.reason,
                untrusted=untrusted_turn,
                assert_current=assert_current,
            ),
        )

    def request_flush(
        self,
        session: SessionState,
        *,
        transcript: Sequence[Mapping[str, Any]],
        untrusted_turn: bool | Callable[[], bool] = False,
        assert_current: Callable[[], None] | None = None,
    ) -> FlushRequest | None:
        """A flush run now, outside the token gate: a memory-core extension (decision Q6).

        Upstream has no forced flush; this serves a host action such as the Lab's ``/flush``.
        It leaves the token snapshot alone and keeps the guards a forced run must not skip:
        heartbeat sessions never flush, and a compaction cycle that already flushed (or failed
        three times) returns ``None`` (``has_already_flushed_for_current_compaction``). Otherwise
        it is the request ``after_turn`` builds for a due flush, with reason ``forced``. A target
        that cannot be created raises (``UnsafeMemoryPathError``, ``OSError``) and records
        nothing. ``assert_current`` has the same cancellation checks as :meth:`after_turn`.
        """
        if session.kind == "heartbeat" or has_already_flushed_for_current_compaction(
            dict(session.entry)
        ):
            return None
        plan = self._flush_plan(DEFAULT_CONTEXT_WINDOW_TOKENS)
        if plan is None:
            return None
        authority_error: BaseException | None = None

        def check_current() -> None:
            nonlocal authority_error
            if assert_current is not None:
                try:
                    assert_current()
                except BaseException as error:
                    authority_error = error
                    raise

        try:
            ensure_memory_flush_target_file(
                self._root, plan.relative_path, assert_current=check_current
            )
        except BaseException as error:
            if authority_error is not None and error is not authority_error:
                raise authority_error from error
            raise
        return self._flush_request(
            session,
            plan,
            transcript,
            reason=_FORCED_FLUSH_REASON,
            untrusted=untrusted_turn,
            assert_current=assert_current,
        )

    def on_new_session(
        self,
        ending: SessionState,
        *,
        command: Literal["new", "reset"],
        session_id: str,
        transcript: Sequence[Mapping[str, Any]] | None = None,
        session_file: str | os.PathLike[str] | None = None,
        text: str | None = None,
        source: str | None = None,
        slug_generator: SlugGenerator | None = None,
        redactor: Callable[[str], str] | None = None,
        has_bootstrap_file_access: bool = False,
    ) -> NewSession:
        """Handle ``/new`` or ``/reset``: save the ending session, then prepare the reset turn.

        ``save_session_memory`` of the ending session's ``transcript`` or ``session_file`` (the
        session-memory hook, raw recent lines unless ``redactor`` maps them), a reindex so
        ``memory_search`` finds the file, :meth:`ensure` (upstream's ensure runs before the
        reset reply, get-reply.ts:443-448), and for a bare command (blank ``text``) the reset
        prompt with the startup context (session-reset-prompt.ts, startup-context.ts). The saved
        file is written first, so the startup context can quote it. The host sends
        ``reset.model_prompt`` through :meth:`before_turn` and records
        ``reset.transcript_prompt``. The kit's optional ``artifact_provenance`` store records
        the ending projection's trust before the saved file is published.
        """
        if command not in ("new", "reset"):
            raise ValueError(f"command must be 'new' or 'reset', got {command!r}")
        now = self._clock()
        saved = save_session_memory(
            self._root,
            session_key=ending.session_key,
            session_id=ending.session_id,
            session_file=session_file,
            messages=list(transcript) if transcript is not None else None,
            source=source,
            now_ms=now,
            timezone=self._timezone,
            slug_generator=slug_generator,
            redactor=redactor,
            artifact_provenance=self._artifact_provenance,
        )
        self._memory.store.reindex(self._memory.workspace)
        workspace_init = self.ensure()
        reset = None
        if not (text and text.strip()):
            state = resolve_bare_session_reset_prompt_state(
                self._root,
                now_ms=now,
                timezone=self._timezone,
                time_format=self._time_format,
                layout=self._layout,
                is_primary_run=ending.kind != "subagent",
                has_bootstrap_file_access=has_bootstrap_file_access,
            )
            startup = (
                build_startup_context(self._root, now_ms=now, timezone=self._timezone)
                if state.should_prepend_startup_context and should_apply_startup_context(command)
                else None
            )
            reset = ResetTurn(
                model_prompt="\n\n".join(part for part in (startup, state.prompt) if part),
                transcript_prompt=format_session_reset_transcript_prompt(command, self._identity),
                bootstrap_mode=state.bootstrap_mode,
                startup_context=startup,
                prompt=state.prompt,
            )
        return NewSession(
            session=SessionState.new(
                session_key=ending.session_key, session_id=session_id, kind=ending.kind
            ),
            saved=saved,
            workspace_init=workspace_init,
            reset=reset,
        )

    def heartbeat_prompt(
        self,
        session: SessionState,
        *,
        source: str | None = None,
        reason: str | None = None,
        context_mode: BootstrapContextMode = "full",
        runtime_context: str | None = None,
        offer_tools: bool = True,
        schedule_now_ms: int | None = None,
        ensure: bool = True,
    ) -> HeartbeatRun:
        """Prepare one heartbeat run the host's scheduler decided to start now.

        The due automation jobs at ``schedule_now_ms`` (the scheduler's instant, default the kit
        clock) become the turn's scheduled tasks when they are heartbeat tasks; other due jobs
        are the host's (``host_jobs``). ``prepare_heartbeat_turn`` builds the message from the
        monitor scratch (its ``Current time:`` line uses the kit clock). Unless the turn is
        skipped, the context is :meth:`before_turn` with run kind ``heartbeat`` (upstream runs
        heartbeats in the main session under that run kind), ``offer_tools`` and ``ensure``
        (``False`` for a preview that never completes the run: no workspace write). Tool calls of
        the run go through :meth:`dispatch` with ``run.session``.
        """
        agent_id = self._memory.config.agent_id
        started_at = schedule_now_ms if schedule_now_ms is not None else self._clock()
        store = self._automation_store
        due = due_automation_jobs(store.list_jobs(agent_id=agent_id), started_at)
        turn = prepare_heartbeat_turn(
            now_ms=self._clock(),
            scratch=store.read_scratch(agent_id),
            scheduled_tasks=heartbeat_scheduled_tasks(due),
            source=source,
            reason=reason,
            timezone=self._timezone,
            time_format=self._time_format,
        )
        in_turn = {task.job_id for task in turn.scheduled_tasks}
        context = (
            None
            if turn.skip_reason
            else self.before_turn(
                session,
                runtime_context=runtime_context,
                run_kind="heartbeat",
                context_mode=context_mode,
                offer_tools=offer_tools,
                ensure=ensure,
            )
        )
        return HeartbeatRun(
            session=context.session if context is not None else session,
            turn=turn,
            jobs=tuple(job for job in due if job.id in in_turn),
            host_jobs=tuple(job for job in due if job.id not in in_turn),
            context=context,
            transcript_prompt=self._identity.heartbeat_transcript_prompt,
            started_at_ms=started_at,
            store=store,
            agent_id=agent_id,
        )

    def _flush_plan(self, context_window_tokens: int) -> MemoryFlushPlan | None:
        return build_memory_flush_plan_from_config(
            workspace_dir=self._root,
            now_ms=self._clock(),
            cfg={"agents": {"defaults": {
                "userTimezone": self._timezone,
                "compaction": {"memoryFlush": self._flush_config},
            }}},
            context_window_tokens=context_window_tokens,
            time_format=self._time_format,
        )

    def _flush_request(
        self,
        session: SessionState,
        plan: MemoryFlushPlan,
        transcript: Sequence[Mapping[str, Any]],
        *,
        reason: str,
        untrusted: bool | Callable[[], bool] = False,
        assert_current: Callable[[], None] | None = None,
    ) -> FlushRequest:
        count = session.entry.get("compactionCount")
        messages = self._flush_messages(session, plan, transcript)
        if assert_current is not None:
            assert_current()
        return FlushRequest(
            self._memory,
            session_id=session.session_id,
            compaction_count=0 if count is None else count,
            target=plan.relative_path,
            reason=reason,
            messages=messages,
            provenance=self._artifact_provenance,
            untrusted=untrusted,
            session_key=session.session_key,
            assert_current=assert_current,
            read_tool=self._flush_read_tool,
            read_dispatch=self._flush_read_dispatch,
            agent_id=session.session_key.split(":")[1]
            if session.session_key.startswith("agent:") else "main",
            maintenance=reason != _FORCED_FLUSH_REASON,
        )

    def _flush_messages(
        self,
        session: SessionState,
        plan: MemoryFlushPlan,
        transcript: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, str], ...]:
        # The flush turn is a full non-interactive run (bootstrap mode none) whose extra system
        # prompt is the flush system prompt under ## Conversation Context
        # (agent-runner-memory.ts:1452-1454, system-prompt.ts:1254-1257). It offers no memory
        # tools, so no Memory Recall section; only the text of user and assistant rows is
        # replayed (a content list gives its text blocks).
        context = self._workspace_context(session, is_interactive_user_facing=False)
        system = "\n\n".join(
            part
            for part in (
                context.prompt_text.strip(),
                f"{CONVERSATION_CONTEXT_HEADER}\n{plan.system_prompt}",
            )
            if part
        )
        rows = ((row.get("role"), resolve_message_text(row.get("content"))) for row in transcript)
        return (
            {"role": "system", "content": system},
            *(
                {"role": role, "content": text}
                for role, text in rows
                if role in ("user", "assistant") and text
            ),
            {"role": "user", "content": plan.prompt},
        )

    def _workspace_context(
        self,
        session: SessionState,
        *,
        run_kind: BootstrapContextRunKind | None = None,
        context_mode: BootstrapContextMode = "full",
        has_bootstrap_file_access: bool = False,
        is_interactive_user_facing: bool = True,
    ) -> WorkspaceContext:
        return build_workspace_context(
            self._root,
            layout=self._layout,
            session_kind=session.kind,
            run_kind=run_kind,
            context_mode=context_mode,
            context_injection=self._context_injection,
            has_completed_bootstrap_turn=session.completed_bootstrap_turn,
            is_interactive_user_facing=is_interactive_user_facing,
            has_bootstrap_file_access=has_bootstrap_file_access,
            max_chars=self._bootstrap_max_chars,
            total_max_chars=self._bootstrap_total_max_chars,
            truncation_warning_mode=self._truncation_warning_mode,
            seen_truncation_signatures=session.seen_truncation_signatures,
            identity=self._identity,
        )
