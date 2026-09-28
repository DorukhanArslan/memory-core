from __future__ import annotations

from collections.abc import AsyncIterable, Callable, Iterable, Mapping
from dataclasses import dataclass, replace
import inspect
import json
from pathlib import Path
import re
from typing import Any, Literal, Protocol

from memory_core.bootstrap import (
    DEFAULT_BOOTSTRAP_MAX_CHARS,
    DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
    DEFAULT_WORKSPACE_LAYOUT,
    ContextFile,
    WorkspaceLayout,
    build_workspace_context,
    load_workspace_bootstrap_files,
    render_project_context,
    render_workspace_files_injected,
    render_workspace_prompt,
)
from memory_core.bootstrap.files import BootstrapMode
from memory_core.bootstrap.tools_md import ToolsMdMigrationFinding
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.current_time import DEFAULT_TIME_FORMAT
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.live.consolidation import SubjectConsolidation, SubjectPromotionDisabledError
from memory_core.memory_flush import SILENT_REPLY_TOKEN, build_memory_flush_plan
from memory_core.runtime_context_prompt import build_runtime_context_system_context
from memory_core.runtime_identity import (
    OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    MEMORY_CORE_RUNTIME_IDENTITY,
    RuntimeIdentity,
)

# Compatibility re-export: ``(file name, file name)`` pairs in the default
# layout's load order. The second element used to be a section title; live
# prompts now render upstream ``## <path>`` headings, so it repeats the name.
IDENTITY_FILE_ORDER = tuple((name, name) for name in DEFAULT_WORKSPACE_LAYOUT.load_order)
# Compatibility alias: the default layout's file names.
IDENTITY_FILE_NAMES = frozenset(DEFAULT_WORKSPACE_LAYOUT.load_order)
# Workspace files that exist upstream but are never injected: BOOT.md is the
# gateway boot checklist (src/gateway/boot.ts:36), DREAMS.md / dreams.md the
# dreaming diary (extensions/memory-core/src/dreaming-dreams-file.ts:10).
NON_INJECTED_WORKSPACE_FILES = frozenset({"BOOT.md", "DREAMS.md", "dreams.md"})
# Workspace files v2026.9.6 retired but still finds in older workspaces: TOOLS.md waits for
# memory_core.bootstrap.migrate_tools_md (669db2968fc, #113966; LiveIdentity.migration_findings
# reports it), HEARTBEAT.md for memory_core.heartbeat_migration.migrate_heartbeat_md (its text
# moves into the heartbeat monitor scratch, 3e2b3ea4d5e #112967; its tasks: become automation
# jobs, b23c7bd0f84 #113165). Neither is injected; the strict unknown-file policy accepts them.
RETIRED_WORKSPACE_FILES = frozenset({"TOOLS.md", "HEARTBEAT.md"})
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
# Upstream SAFE_SESSION_ID_RE (src/config/sessions/paths.ts:63 at 4c42815348): a leading
# letter or digit, then up to 127 of [A-Za-z0-9._-]. Applied only where a session id
# becomes a file name (JsonlTraceSink.for_session); turn and summary calls take any id.
SAFE_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SENTENCE_RE = re.compile(r"(.+?[.!?…])(?:\s+|$)", re.DOTALL)
LIVE_TURN_STARTED = "live_turn_started"
MEMORY_RECALL_COMPLETED = "memory_recall_completed"
PROMPT_ASSEMBLED = "prompt_assembled"
TEXT_DELTA = "text_delta"
PROVIDER_EVENT = "provider_event"
SENTENCE = "sentence"
LIVE_TURN_COMPLETED = "live_turn_completed"
LIVE_TURN_FAILED = "live_turn_failed"
SESSION_SUMMARY_STARTED = "session_summary_started"
SESSION_SUMMARY_COMPLETED = "session_summary_completed"
SESSION_SUMMARY_SKIPPED = "session_summary_skipped"
SESSION_SUMMARY_FAILED = "session_summary_failed"
LiveTurnEventType = Literal[
    "live_turn_started",
    "memory_recall_completed",
    "prompt_assembled",
    "text_delta",
    "provider_event",
    "sentence",
    "live_turn_completed",
    "live_turn_failed",
    "session_summary_started",
    "session_summary_completed",
    "session_summary_skipped",
    "session_summary_failed",
]
UnknownIdentityFilePolicy = Literal["ignore", "error"]
SentenceBoundaryPolicy = Literal["punctuation"]
# Why record_session_summary wrote nothing: NO_REPLY, nothing left after
# sanitization, or neither a JSON object nor a bullet list.
SessionSummarySkipReason = Literal["silent", "empty", "unstructured"]
SubjectPathBuilder = Callable[[Path, str], Path]


class IdentityLoadError(ValueError):
    pass


@dataclass(frozen=True)
class LiveIdentity:
    """Workspace bootstrap files injected into live subject prompts.

    Built by :meth:`from_dir` through :mod:`memory_core.bootstrap`: the layout's
    files are loaded, filtered like a main session, budgeted (20,000 chars per
    file, 60,000 total, UTF-16 units) and rendered as upstream Project Context.
    ``sections`` holds ``(path, injected content)`` pairs in render order;
    ``bootstrap_text`` holds ``## Bootstrap Pending`` / ``## Bootstrap Context
    Notice`` when they apply; ``warnings`` are the budget warnings.
    ``migration_findings`` are upstream's doctor findings for a leftover TOOLS.md
    (``collectToolsMdMigrationFindings``: no layout loads it since v2026.9.6, so its notes
    reach no subject prompt until the host runs ``memory_core.bootstrap.migrate_tools_md``);
    they are host-facing and never rendered into the prompt.
    """

    sections: tuple[tuple[str, str], ...]
    bootstrap_text: str = ""
    warnings: tuple[str, ...] = ()
    truncated: bool = False
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT
    migration_findings: tuple[ToolsMdMigrationFinding, ...] = ()

    @classmethod
    def from_dir(
        cls,
        identity_dir: str | Path,
        *,
        required_files: Iterable[str] = (),
        max_chars_per_file: int | None = DEFAULT_BOOTSTRAP_MAX_CHARS,
        total_max_chars: int | None = DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
        unknown_files: UnknownIdentityFilePolicy = "ignore",
        layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
        include_agent_memory: bool = False,
        bootstrap_mode: BootstrapMode | None = None,
        has_bootstrap_file_access: bool = False,
        is_canonical_workspace: bool = True,
        path_style: str = "absolute",
    ) -> "LiveIdentity":
        """Load a workspace's bootstrap files for live prompts.

        Missing layout files render upstream's ``[MISSING] Expected at:``
        marker (USER.md, MEMORY.md and PROACTIVE_PREFERENCES.md are skipped when
        absent, empty files are not injected, a refused read renders
        ``[UNREADABLE: <reason>]``). ``max_chars_per_file`` / ``total_max_chars`` of ``None`` or
        ``<= 0`` fall back to the defaults, like upstream's config resolution.

        Deliberate deviation (decided 2026-09-26): the agent's root MEMORY.md is
        not injected unless ``include_agent_memory=True``; upstream injects it
        for every non-subagent, non-cron session. Subject memory reaches the
        prompt through recall instead. ``bootstrap_mode`` overrides upstream's
        resolution. ``has_bootstrap_file_access`` says whether the host gives
        the model a ``read`` tool for the workspace (upstream derives it from
        the run's tools); it defaults to ``False`` because memory_core.live itself
        exposes no tools. A pending workspace then resolves ``limited``
        (BOOTSTRAP.md left out, limited ``## Bootstrap Pending`` lines), unless
        BOOTSTRAP.md has content, which upstream counts as file access
        (``full``, file in Project Context). ``is_canonical_workspace`` is
        passed through to ``resolveBootstrapMode``.
        """
        root = Path(identity_dir)
        _validate_required_identity_files(root, required_files, layout)
        _validate_unknown_identity_files(root, unknown_files, layout)
        context = build_workspace_context(
            root,
            layout=layout,
            session_kind="main",
            exclude_files=() if include_agent_memory else (layout.memory_file,),
            bootstrap_mode=bootstrap_mode,
            has_bootstrap_file_access=has_bootstrap_file_access,
            is_canonical_workspace=is_canonical_workspace,
            # build_workspace_context applies resolveBootstrapMaxChars semantics.
            max_chars=max_chars_per_file,
            total_max_chars=total_max_chars,
            path_style=path_style,
        )
        return cls(
            sections=tuple((file.path, file.content) for file in context.files),
            bootstrap_text=context.bootstrap_text,
            warnings=context.warnings,
            truncated=context.truncated,
            layout=layout,
            migration_findings=context.migration_findings,
        )

    def to_prompt_section(
        self, runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY
    ) -> str:
        """Render the injected files in upstream prompt order and line format.

        Bootstrap sections, ``## Workspace Files (injected)`` (brand from
        ``runtime_identity``) and ``# Project Context``, joined without a cache
        boundary. Unlike upstream, the Workspace Files lines are left out when no
        file is injected.
        """
        files = [ContextFile(path, content) for path, content in self.sections]
        return render_workspace_prompt(
            bootstrap_text=self.bootstrap_text,
            workspace_files_text=render_workspace_files_injected(runtime_identity) if files else "",
            stable_text=render_project_context(files, self.layout),
        )


@dataclass
class LiveIdentityStore:
    """Caches a :class:`LiveIdentity` until :meth:`reload`.

    The cache holds the bootstrap state too (bootstrap mode, ``## Bootstrap
    Pending``, the truncation notice). Upstream reloads bootstrap files every
    turn and runs ``ensureAgentWorkspace`` on each reply; a host that wants the
    BOOTSTRAP.md lifecycle calls ``initialize_agent_workspace`` with its
    templates and then :meth:`reload` per turn or session.
    """

    identity_dir: Path
    required_files: tuple[str, ...] = ()
    max_chars_per_file: int | None = DEFAULT_BOOTSTRAP_MAX_CHARS
    total_max_chars: int | None = DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS
    unknown_files: UnknownIdentityFilePolicy = "ignore"
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT
    include_agent_memory: bool = False
    bootstrap_mode: BootstrapMode | None = None
    has_bootstrap_file_access: bool = False
    is_canonical_workspace: bool = True
    path_style: str = "absolute"
    _cached: LiveIdentity | None = None

    def __init__(
        self,
        identity_dir: str | Path,
        *,
        required_files: Iterable[str] = (),
        max_chars_per_file: int | None = DEFAULT_BOOTSTRAP_MAX_CHARS,
        total_max_chars: int | None = DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
        unknown_files: UnknownIdentityFilePolicy = "ignore",
        layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
        include_agent_memory: bool = False,
        bootstrap_mode: BootstrapMode | None = None,
        has_bootstrap_file_access: bool = False,
        is_canonical_workspace: bool = True,
        path_style: str = "absolute",
    ):
        self.identity_dir = Path(identity_dir)
        self.required_files = tuple(required_files)
        self.max_chars_per_file = max_chars_per_file
        self.total_max_chars = total_max_chars
        self.unknown_files = unknown_files
        self.layout = layout
        self.include_agent_memory = include_agent_memory
        self.bootstrap_mode = bootstrap_mode
        self.has_bootstrap_file_access = has_bootstrap_file_access
        self.is_canonical_workspace = is_canonical_workspace
        self.path_style = path_style
        self._cached = None

    def load(self) -> LiveIdentity:
        if self._cached is None:
            self._cached = self.reload()
        return self._cached

    def reload(self) -> LiveIdentity:
        self._cached = LiveIdentity.from_dir(
            self.identity_dir,
            required_files=self.required_files,
            max_chars_per_file=self.max_chars_per_file,
            total_max_chars=self.total_max_chars,
            unknown_files=self.unknown_files,
            layout=self.layout,
            include_agent_memory=self.include_agent_memory,
            bootstrap_mode=self.bootstrap_mode,
            has_bootstrap_file_access=self.has_bootstrap_file_access,
            is_canonical_workspace=self.is_canonical_workspace,
            path_style=self.path_style,
        )
        return self._cached


@dataclass(frozen=True)
class LiveTurnContext:
    """Host input for one live turn.

    ``transcript_window``, ``host_context`` (host-owned facts about the subject
    or session, such as an account record or device state), ``workflow_state``
    and ``trace_events`` are rendered as marker-wrapped runtime context
    (``## Transcript window``, ``## Host context``, ``## Active workflow``,
    ``## Recent trace``); none of them is written to memory.
    """

    subject_id: str
    session_id: str
    user_utterance: str
    transcript_window: str | Iterable[str] | None = None
    host_context: Mapping[str, Any] | str | None = None
    workflow_state: Mapping[str, Any] | None = None
    trace_events: Iterable[Mapping[str, Any]] | None = None


@dataclass(frozen=True)
class PreparedLiveTurn:
    messages: list[dict[str, str]]
    memory_results: list[dict[str, Any]]
    memory_context: str
    runtime_context: str
    trace_context: dict[str, Any]


@dataclass(frozen=True)
class LiveTurnEvent:
    type: LiveTurnEventType
    text: str = ""
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class SessionSummaryResult:
    wrote: bool
    path: str
    text: str
    raw_text: str
    durable_facts: tuple[str, ...] = ()
    preferences: tuple[str, ...] = ()
    follow_ups: tuple[str, ...] = ()
    # None when something was written; see SessionSummarySkipReason.
    skip_reason: SessionSummarySkipReason | None = None


class TraceSink(Protocol):
    def record(self, event: LiveTurnEvent) -> None:
        """Persist a live turn event."""


@dataclass(frozen=True)
class LiveSDKConfig:
    openclaw_compatible: bool = False
    max_results: int = 5
    min_score: float = 0.0
    corpus: str = "all"
    sentence_boundary_policy: SentenceBoundaryPolicy = "punctuation"
    trace_sink: TraceSink | None = None


@dataclass(frozen=True)
class JsonlTraceSink:
    path: Path

    def __init__(self, path: str | Path):
        object.__setattr__(self, "path", Path(path))

    @classmethod
    def for_session(cls, trace_dir: str | Path, session_id: str) -> "JsonlTraceSink":
        """Trace sink at ``<trace_dir>/<session_id>.jsonl``.

        ``session_id`` must match upstream's ``SAFE_SESSION_ID_RE`` (a leading
        letter or digit, then at most 127 of ``[A-Za-z0-9._-]``), so it cannot
        leave ``trace_dir`` or exceed a file-name limit; otherwise ``ValueError``.
        """
        if not SAFE_SESSION_ID_RE.fullmatch(session_id):
            raise ValueError(f"session_id is not filesystem-safe: {session_id}")
        return cls(Path(trace_dir) / f"{session_id}.jsonl")

    def record(self, event: LiveTurnEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "type": event.type,
            "text": event.text,
            "data": event.data or {},
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n")


class SubjectMemory:
    def __init__(self, *, subject_id: str, memory: Memory):
        self.subject_id = subject_id
        self.memory = memory

    @classmethod
    def open(
        cls,
        *,
        workspace_dir: str | Path,
        subject_id: str,
        namespace: str = "subjects",
        subject_path_builder: SubjectPathBuilder | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        config: MemoryConfig | None = None,
        initialize: bool = True,
        reindex: bool = True,
        flags: FeatureFlags | None = None,
    ) -> "SubjectMemory":
        """Open (and by default initialize and reindex) one subject's memory.

        ``flags`` replaces the default flags of the subject's own config
        (FTS-only without a provider). ``config`` may be shared by every
        subject: its settings are kept, but its paths are rebased onto the
        subject directory (:func:`_rebase_config_onto_subject`), so subjects
        never share an index or read each other's files.
        """
        if flags is not None and config is not None:
            raise ValueError("pass flags inside config, or flags without config")
        safe_subject_id = _validate_safe_id(subject_id, label="subject_id")
        workspace = _resolve_subject_workspace(
            Path(workspace_dir),
            safe_subject_id,
            namespace=namespace,
            subject_path_builder=subject_path_builder,
        )
        if config is not None:
            resolved_config = _rebase_config_onto_subject(config, workspace)
        else:
            default_flags = (
                None if embedding_provider is not None else FeatureFlags(vector_search=False)
            )
            resolved_config = MemoryConfig(
                workspace_dir=workspace,
                flags=flags if flags is not None else default_flags,
            )
        memory = Memory.from_workspace(
            workspace,
            embedding_provider=embedding_provider,
            config=resolved_config,
            initialize=initialize,
            reindex=reindex,
        )
        return cls(subject_id=safe_subject_id, memory=memory)

    def prepare_live_turn(
        self,
        context: LiveTurnContext,
        *,
        identity: LiveIdentity | None = None,
        openclaw_compatible: bool = False,
        max_results: int = 5,
        min_score: float = 0.0,
        corpus: str = "all",
    ) -> PreparedLiveTurn:
        _validate_context_subject(self.subject_id, context.subject_id)
        memory_search = self.memory.search(
            context.user_utterance,
            max_results=max_results,
            min_score=min_score,
            corpus=corpus,
        )
        memory_results = memory_search.get("results", [])
        memory_context = _format_memory_context(memory_results)
        runtime_context = _build_runtime_context(context)
        identity_mode = OPENCLAW_COMPAT_RUNTIME_IDENTITY if openclaw_compatible else MEMORY_CORE_RUNTIME_IDENTITY
        system_parts = [
            identity.to_prompt_section(identity_mode) if identity is not None else "",
            "## Recalled Subject Memory\n" + memory_context if memory_context else "",
            build_runtime_context_system_context(runtime_context, identity=identity_mode)
            if runtime_context
            else "",
        ]
        messages = [
            {"role": "system", "content": "\n\n".join(part for part in system_parts if part)},
            {"role": "user", "content": context.user_utterance},
        ]
        return PreparedLiveTurn(
            messages=messages,
            memory_results=memory_results,
            memory_context=memory_context,
            runtime_context=runtime_context,
            trace_context={
                "subject_id": context.subject_id,
                "session_id": context.session_id,
                "workflow_state": dict(context.workflow_state or {}),
                "memory_result_count": len(memory_results),
            },
        )

    async def stream_live_turn(
        self,
        context: LiveTurnContext,
        *,
        llm: Callable[[list[dict[str, str]]], AsyncIterable[str] | Any],
        identity: LiveIdentity | None = None,
        config: LiveSDKConfig | None = None,
        openclaw_compatible: bool | None = None,
        max_results: int | None = None,
        min_score: float | None = None,
        corpus: str | None = None,
        trace_sink: TraceSink | None = None,
    ) -> AsyncIterable[LiveTurnEvent]:
        """Stream one live turn as :class:`LiveTurnEvent` objects.

        Every event is yielded and, with a trace sink, recorded in the same
        order. After ``live_turn_started``, any exception (a subject_id
        mismatch, a recall error, the host LLM stream raising) yields
        ``live_turn_failed`` with ``error_type``, ``error`` and the partial
        ``assistant_text``; the next iteration step re-raises the original
        exception. A consumer that stops iterating at ``live_turn_failed``
        closes the stream without the re-raise.

        ``context.session_id`` is any host id (``whatsapp:+90...``, a Slack
        thread key); a host that names trace files after it builds the sink
        with :meth:`JsonlTraceSink.for_session`, which checks it.
        """
        resolved_config = _resolve_live_sdk_config(
            config=config,
            openclaw_compatible=openclaw_compatible,
            max_results=max_results,
            min_score=min_score,
            corpus=corpus,
            trace_sink=trace_sink,
        )
        _validate_sentence_boundary_policy(resolved_config.sentence_boundary_policy)
        yield _record_trace_event(
            LIVE_TURN_STARTED,
            trace_sink=resolved_config.trace_sink,
            data={"subject_id": context.subject_id, "session_id": context.session_id},
        )
        assistant_parts: list[str] = []
        sentence_buffer = ""
        try:
            prepared = self.prepare_live_turn(
                context,
                identity=identity,
                openclaw_compatible=resolved_config.openclaw_compatible,
                max_results=resolved_config.max_results,
                min_score=resolved_config.min_score,
                corpus=resolved_config.corpus,
            )
            yield _record_trace_event(
                MEMORY_RECALL_COMPLETED,
                trace_sink=resolved_config.trace_sink,
                data={
                    "results": prepared.memory_results,
                    "memory_context": prepared.memory_context,
                },
            )
            yield _record_trace_event(
                PROMPT_ASSEMBLED,
                trace_sink=resolved_config.trace_sink,
                data={
                    "trace_context": prepared.trace_context,
                    "runtime_context": prepared.runtime_context,
                },
            )
            async for chunk in _aiter_stream(llm(prepared.messages)):
                if _is_provider_event_chunk(chunk):
                    yield _record_trace_event(
                        PROVIDER_EVENT,
                        trace_sink=resolved_config.trace_sink,
                        data=dict(chunk),
                    )
                    continue
                text = _coerce_text_delta(chunk)
                if not text:
                    continue
                assistant_parts.append(text)
                sentence_buffer += text
                yield _record_trace_event(TEXT_DELTA, trace_sink=resolved_config.trace_sink, text=text)
                sentences, sentence_buffer = _pop_complete_sentences(sentence_buffer)
                for sentence in sentences:
                    yield _record_trace_event(
                        SENTENCE, trace_sink=resolved_config.trace_sink, text=sentence
                    )

            remainder = sentence_buffer.strip()
            if remainder:
                yield _record_trace_event(
                    SENTENCE, trace_sink=resolved_config.trace_sink, text=remainder
                )
            assistant_text = "".join(assistant_parts).strip()
            yield _record_trace_event(
                LIVE_TURN_COMPLETED,
                trace_sink=resolved_config.trace_sink,
                data={
                    "assistant_text": assistant_text,
                    "trace_context": prepared.trace_context,
                },
            )
        except Exception as exc:
            yield _record_trace_event(
                LIVE_TURN_FAILED,
                trace_sink=resolved_config.trace_sink,
                data={
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "assistant_text": "".join(assistant_parts).strip(),
                },
            )
            raise

    def record_session_summary(
        self,
        *,
        session_id: str,
        transcript: str,
        summary_llm: Callable[[list[dict[str, str]]], str],
        redactor: Callable[[str], str] | None = None,
        now_ms: int | None = None,
        timezone: str = "UTC",
        trace_sink: TraceSink | None = None,
        time_format: str = DEFAULT_TIME_FORMAT,
    ) -> SessionSummaryResult:
        plan, messages = self._prepare_session_summary_messages(
            session_id=session_id,
            transcript=transcript,
            redactor=redactor,
            now_ms=now_ms,
            timezone=timezone,
            trace_sink=trace_sink,
            time_format=time_format,
        )
        try:
            raw_text = summary_llm(messages)
            if inspect.isawaitable(raw_text):
                raise TypeError("record_session_summary received an awaitable; use async_record_session_summary")
            return self._finalize_session_summary(
                raw_text=raw_text,
                relative_path=plan.relative_path,
                trace_sink=trace_sink,
            )
        except Exception as exc:
            self._trace_session_summary_failed(session_id, exc, trace_sink)
            raise

    async def async_record_session_summary(
        self,
        *,
        session_id: str,
        transcript: str,
        summary_llm: Callable[[list[dict[str, str]]], Any],
        redactor: Callable[[str], str] | None = None,
        now_ms: int | None = None,
        timezone: str = "UTC",
        trace_sink: TraceSink | None = None,
        time_format: str = DEFAULT_TIME_FORMAT,
    ) -> SessionSummaryResult:
        plan, messages = self._prepare_session_summary_messages(
            session_id=session_id,
            transcript=transcript,
            redactor=redactor,
            now_ms=now_ms,
            timezone=timezone,
            trace_sink=trace_sink,
            time_format=time_format,
        )
        try:
            raw_text = summary_llm(messages)
            if inspect.isawaitable(raw_text):
                raw_text = await raw_text
            return self._finalize_session_summary(
                raw_text=raw_text,
                relative_path=plan.relative_path,
                trace_sink=trace_sink,
            )
        except Exception as exc:
            self._trace_session_summary_failed(session_id, exc, trace_sink)
            raise

    def _prepare_session_summary_messages(
        self,
        *,
        session_id: str,
        transcript: str,
        redactor: Callable[[str], str] | None,
        now_ms: int | None,
        timezone: str,
        trace_sink: TraceSink | None,
        time_format: str = DEFAULT_TIME_FORMAT,
    ):
        _record_trace_event(
            SESSION_SUMMARY_STARTED,
            trace_sink=trace_sink,
            data={"subject_id": self.subject_id, "session_id": session_id},
        )
        redacted_transcript = redactor(transcript) if redactor is not None else transcript
        plan = build_memory_flush_plan(
            workspace_dir=self.memory.workspace.root,
            now_ms=now_ms,
            timezone=timezone,
            time_format=time_format,
        )
        messages = [
            {"role": "system", "content": plan.system_prompt},
            {
                "role": "user",
                "content": (
                    f"{plan.prompt}\n\n"
                    f"Session memory extraction for session {session_id}.\n"
                    "Extract only durable facts, preferences, and follow-ups. "
                    "Reply with either a JSON object whose keys durable_facts, preferences "
                    "and follow_ups each hold a list of strings, or a list of lines that "
                    "each start with \"- \". Any other reply shape is not stored.\n\n"
                    f"Session transcript:\n{redacted_transcript}"
                ),
            },
        ]
        return plan, messages

    def _finalize_session_summary(
        self,
        *,
        raw_text: str,
        relative_path: str,
        trace_sink: TraceSink | None,
    ) -> SessionSummaryResult:
        extraction = _parse_session_summary_output(raw_text)
        result = SessionSummaryResult(
            wrote=False,
            path=relative_path,
            text=extraction["memory_text"],
            raw_text=raw_text,
            durable_facts=extraction["durable_facts"],
            preferences=extraction["preferences"],
            follow_ups=extraction["follow_ups"],
            skip_reason=extraction["skip_reason"],
        )
        if result.skip_reason is not None:
            _record_trace_event(
                SESSION_SUMMARY_SKIPPED,
                trace_sink=trace_sink,
                data=_session_summary_trace_data(result),
            )
            return result

        self.memory.workspace.append_daily_memory(relative_path, result.text)
        self.memory.store.reindex(self.memory.workspace)
        result = replace(result, wrote=True)
        _record_trace_event(
            SESSION_SUMMARY_COMPLETED,
            trace_sink=trace_sink,
            data=_session_summary_trace_data(result),
        )
        return result

    def _trace_session_summary_failed(
        self, session_id: str, exc: Exception, trace_sink: TraceSink | None
    ) -> None:
        _record_trace_event(
            SESSION_SUMMARY_FAILED,
            trace_sink=trace_sink,
            data={
                "subject_id": self.subject_id,
                "session_id": session_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )


def _validate_safe_id(value: str, *, label: str) -> str:
    # SAFE_ID_RE admits "." and "..", which name the directory itself or its
    # parent once joined into a path; upstream's SAFE_SESSION_ID_RE
    # (src/config/sessions/paths.ts) excludes them with a leading [a-z0-9].
    if not SAFE_ID_RE.fullmatch(value) or not value.strip("."):
        raise ValueError(f"{label} is not filesystem-safe: {value}")
    return value


def _resolve_live_sdk_config(
    *,
    config: LiveSDKConfig | None,
    openclaw_compatible: bool | None,
    max_results: int | None,
    min_score: float | None,
    corpus: str | None,
    trace_sink: TraceSink | None,
) -> LiveSDKConfig:
    base = config or LiveSDKConfig()
    return LiveSDKConfig(
        openclaw_compatible=(
            base.openclaw_compatible if openclaw_compatible is None else openclaw_compatible
        ),
        max_results=base.max_results if max_results is None else max_results,
        min_score=base.min_score if min_score is None else min_score,
        corpus=base.corpus if corpus is None else corpus,
        sentence_boundary_policy=base.sentence_boundary_policy,
        trace_sink=base.trace_sink if trace_sink is None else trace_sink,
    )


def _validate_sentence_boundary_policy(policy: str) -> None:
    if policy != "punctuation":
        raise ValueError(f"unsupported sentence boundary policy: {policy}")


def _resolve_subject_workspace(
    root: Path,
    subject_id: str,
    *,
    namespace: str,
    subject_path_builder: SubjectPathBuilder | None,
) -> Path:
    if subject_path_builder is not None:
        workspace = subject_path_builder(root, subject_id)
    else:
        safe_namespace = _validate_safe_id(namespace, label="namespace")
        workspace = root / safe_namespace / subject_id
    resolved_root = root.resolve()
    resolved_workspace = Path(workspace).resolve()
    if resolved_workspace != resolved_root and resolved_root not in resolved_workspace.parents:
        raise ValueError(f"subject workspace escapes root: {workspace}")
    return Path(workspace)


def _rebase_config_onto_subject(config: MemoryConfig, workspace: Path) -> MemoryConfig:
    """Point a (possibly shared) config at one subject's workspace.

    ``workspace_dir`` becomes the subject directory, so ``memory_get`` and the
    consolidation stores resolve there. ``store_path``: ``None`` resolves to
    ``<subject>/.memory-core/<agent_id>.sqlite``; a path inside the subject
    directory is kept; a path inside ``config.workspace_dir`` keeps its
    relative location under the subject directory; any other path raises
    ``ValueError``, because one index file would then serve every subject and
    each reindex would delete the other subjects' chunks.
    """
    store_path = config.store_path
    if store_path is not None:
        resolved_store = Path(store_path).resolve()
        subject_root = workspace.resolve()
        config_root = Path(config.workspace_dir).resolve()
        if subject_root not in resolved_store.parents:
            if config_root not in resolved_store.parents:
                raise ValueError(
                    "config.store_path is outside both config.workspace_dir and the subject "
                    f"workspace, so every subject would share it: {store_path}"
                )
            store_path = workspace / resolved_store.relative_to(config_root)
    return replace(config, workspace_dir=workspace, store_path=store_path)


def _validate_required_identity_files(
    root: Path, required_files: Iterable[str], layout: WorkspaceLayout
) -> None:
    # Fail closed against the loader itself: a file the guarded read rejects
    # (hard link, over 2 MiB, any symlink) renders as an "[UNREADABLE: ...]"
    # marker, so it does not satisfy a required file either.
    required = tuple(required_files)
    if not required:
        return
    names = frozenset(layout.load_order)
    loaded = {
        file.name
        for file in load_workspace_bootstrap_files(root, layout)
        if not file.missing and file.unreadable_reason is None
    }
    missing = [filename for filename in required if filename not in names or filename not in loaded]
    if missing:
        raise IdentityLoadError(f"missing required workspace files: {', '.join(sorted(missing))}")


def _validate_unknown_identity_files(
    root: Path, policy: UnknownIdentityFilePolicy, layout: WorkspaceLayout
) -> None:
    if policy == "ignore" or not root.is_dir():
        return
    if policy != "error":
        raise IdentityLoadError(f"unknown identity file policy: {policy}")
    # Root-level Markdown files only; folders (user/, workspace/, memory/,
    # skills/, subjects/) are never workspace bootstrap files.
    allowed = frozenset(layout.load_order) | NON_INJECTED_WORKSPACE_FILES | RETIRED_WORKSPACE_FILES
    unknown = sorted(
        path.name
        for path in root.iterdir()
        if path.name.endswith(".md") and path.is_file() and path.name not in allowed
    )
    if unknown:
        raise IdentityLoadError(f"unknown workspace files: {', '.join(unknown)}")


def _record_trace_event(
    event_type: LiveTurnEventType,
    *,
    trace_sink: TraceSink | None,
    text: str = "",
    data: dict[str, Any] | None = None,
) -> LiveTurnEvent:
    event = LiveTurnEvent(event_type, text=text, data=data)
    if trace_sink is not None:
        trace_sink.record(event)
    return event


def _session_summary_trace_data(result: SessionSummaryResult) -> dict[str, Any]:
    data: dict[str, Any] = {
        "wrote": result.wrote,
        "path": result.path,
        "durable_facts": list(result.durable_facts),
        "preferences": list(result.preferences),
        "follow_ups": list(result.follow_ups),
    }
    if result.skip_reason is not None:
        data["skip_reason"] = result.skip_reason
    return data


# Session summary sanitization: a memory-core rule with no upstream counterpart
# (upstream's flush turn writes through tools and discards its reply text).
# Tool-call spans: <|tool_call>...<tool_call|>, <tool_call>...</tool_call> and
# <|tool_call_begin|>...<|tool_call_end|>; an unclosed span runs to the end.
_SUMMARY_TOOL_CALL_SPAN_RE = re.compile(
    r"<\|?tool_call(?:_begin)?\|?>.*?(?:<\|?/?tool_call(?:_end)?\|?>|\Z)",
    re.DOTALL | re.IGNORECASE,
)
# Special tokens with a pipe on both sides (<|im_end|>, <|channel|>,
# <|tool_calls_section_begin|>) are removed anywhere; text such as "<A|B>" stays.
_SUMMARY_SPECIAL_TOKEN_RE = re.compile(r"<\|[A-Za-z0-9_]+\|>")
# A line that is only a marker is dropped: upstream HARMONY_CHANNEL_MARKER_RE
# (src/auto-reply/tokens.ts:9 at 4c42815348), applied per line.
_SUMMARY_MARKER_LINE_RE = re.compile(
    r"^[ \t]*(?:set-thought\s+)?<[A-Za-z0-9_]*\|[^>\n]*>[ \t]*$", re.MULTILINE
)
# A trailing silent token: upstream stripSilentToken (src/auto-reply/tokens.ts).
_SUMMARY_TRAILING_SILENT_RE = re.compile(
    rf"(?:^|\s+|\*+){re.escape(SILENT_REPLY_TOKEN)}\s*\Z", re.IGNORECASE
)
_SUMMARY_CODE_FENCE_RE = re.compile(r"\A```[\w-]*[ \t]*\n(.*?)\n?```\Z", re.DOTALL)
_SUMMARY_BULLET_RE = re.compile(r"^[-*+]\s+(\S.*)$")
# Label lines dropped before bullets or JSON: "Preferences:", a Markdown heading
# ("## Session notes") or a bold label ("**Preferences:**", "**Preferences**:").
_SUMMARY_LABEL_RE = re.compile(r"^(?:.*:|#{1,6}\s+\S.*|(\*\*|__)\S(?:.*\S)?(?::\1|\1:))$")
_NOT_JSON = object()


def _parse_session_summary_output(raw_text: str) -> dict[str, Any]:
    """Turn the summary model's reply into the bullets appended to daily memory.

    The rule, in order:

    1. Tool-call spans, ``<|name|>`` special tokens (``<|im_end|>``) and lines
       that are only a marker are removed. A reply that then starts with
       ``NO_REPLY`` is ``silent``; a trailing ``NO_REPLY`` is stripped.
    2. A JSON object (the whole reply, or what follows the label lines;
       optionally inside a ```` ``` ```` fence) keeps only ``durable_facts``,
       ``preferences`` and ``follow_ups``, one bullet per item with whitespace
       collapsed.
    3. Otherwise the reply must be a bullet list: label lines (non-bullet
       lines ending with ``:`` such as the preamble ``Appending durable memory
       to memory/2026-09-26.md:``, Markdown headings, bold labels such as
       ``**Preferences:**``) are dropped, an indented line continues the bullet
       above it, and every other non-empty line must start with ``-``, ``*``
       or ``+``; bullets are written as ``- <text>``.
    4. Prose, a non-object JSON value, numbered lists, other bullet glyphs, or
       bullets mixed with prose are ``unstructured``: nothing is written.
       Nothing left is ``empty``.
    """
    text = _SUMMARY_TOOL_CALL_SPAN_RE.sub("", raw_text)
    text = _SUMMARY_SPECIAL_TOKEN_RE.sub("", text)
    text = _SUMMARY_MARKER_LINE_RE.sub("", text).strip()
    if text.startswith(SILENT_REPLY_TOKEN):
        return _session_summary_payload(skip_reason="silent")
    text = _SUMMARY_TRAILING_SILENT_RE.sub("", text).strip()
    body = _drop_summary_preamble(text)
    payload = _load_summary_json(text)
    if payload is _NOT_JSON:
        payload = _load_summary_json(body)
    if payload is not _NOT_JSON:
        if not isinstance(payload, dict):
            return _session_summary_payload(skip_reason="unstructured")
        durable_facts = _string_tuple(payload.get("durable_facts"))
        preferences = _string_tuple(payload.get("preferences"))
        follow_ups = _string_tuple(payload.get("follow_ups"))
        return _session_summary_payload(
            memory_text=_format_structured_session_memory(
                durable_facts=durable_facts,
                preferences=preferences,
                follow_ups=follow_ups,
            ),
            durable_facts=durable_facts,
            preferences=preferences,
            follow_ups=follow_ups,
        )
    fenced = _SUMMARY_CODE_FENCE_RE.match(body)
    bullets = _summary_bullets(fenced.group(1) if fenced else body)
    if bullets is None:
        return _session_summary_payload(skip_reason="unstructured")
    return _session_summary_payload(memory_text="\n".join(bullets))


def _is_summary_label_line(line: str) -> bool:
    return _SUMMARY_BULLET_RE.match(line) is None and _SUMMARY_LABEL_RE.match(line) is not None


def _drop_summary_preamble(text: str) -> str:
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line and not _is_summary_label_line(line):
            break
        index += 1
    return "\n".join(lines[index:]).strip()


def _load_summary_json(text: str) -> Any:
    fenced = _SUMMARY_CODE_FENCE_RE.match(text)
    try:
        return json.loads(fenced.group(1) if fenced else text)
    except json.JSONDecodeError:
        return _NOT_JSON


def _summary_bullets(text: str) -> list[str] | None:
    bullets: list[str] = []
    continues = False
    for line in text.splitlines():
        stripped = line.strip()
        match = _SUMMARY_BULLET_RE.match(stripped)
        if match is not None:
            bullets.append(f"- {_collapse_whitespace(match.group(1))}")
            continues = True
        elif not stripped:
            continues = False
        elif continues and line[:1] in (" ", "\t"):
            # A wrapped bullet: the indented line belongs to the bullet above.
            bullets[-1] = f"{bullets[-1]} {_collapse_whitespace(stripped)}"
        elif _is_summary_label_line(stripped):
            continues = False
        else:
            return None
    return bullets


def _session_summary_payload(
    *,
    memory_text: str = "",
    durable_facts: tuple[str, ...] = (),
    preferences: tuple[str, ...] = (),
    follow_ups: tuple[str, ...] = (),
    skip_reason: SessionSummarySkipReason | None = None,
) -> dict[str, Any]:
    # Nothing to write without a stated reason is "empty".
    if not memory_text and skip_reason is None:
        skip_reason = "empty"
    return {
        "memory_text": memory_text,
        "durable_facts": durable_facts,
        "preferences": preferences,
        "follow_ups": follow_ups,
        "skip_reason": skip_reason,
    }


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = _collapse_whitespace(value)
        return (stripped,) if stripped else ()
    if not isinstance(value, list | tuple):
        return ()
    items = []
    for item in value:
        if isinstance(item, str) and item.strip():
            items.append(_collapse_whitespace(item))
    return tuple(items)


def _format_structured_session_memory(
    *,
    durable_facts: tuple[str, ...],
    preferences: tuple[str, ...],
    follow_ups: tuple[str, ...],
) -> str:
    lines: list[str] = []
    for fact in durable_facts:
        lines.append(f"- {fact}")
    for preference in preferences:
        lines.append(f"- Preference: {preference}")
    for follow_up in follow_ups:
        lines.append(f"- Follow-up: {follow_up}")
    return "\n".join(lines)


def _validate_context_subject(expected: str, actual: str) -> None:
    if expected != actual:
        raise ValueError(f"live turn subject_id mismatch: expected {expected}, got {actual}")


def _format_memory_context(results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in results:
        path = item.get("path", "memory")
        start = item.get("startLine")
        snippet = str(item.get("snippet", "")).strip()
        if snippet:
            lines.append(f"{path}#{start}: {snippet}" if start else f"{path}: {snippet}")
    return "\n".join(lines)


def _build_runtime_context(context: LiveTurnContext) -> str:
    sections = [
        ("Session", {"subject_id": context.subject_id, "session_id": context.session_id}),
        ("Transcript window", _coerce_context_text(context.transcript_window)),
        ("Host context", context.host_context),
        ("Active workflow", context.workflow_state),
        ("Recent trace", list(context.trace_events or [])),
    ]
    rendered = [_render_context_section(title, value) for title, value in sections]
    return "\n\n".join(section for section in rendered if section)


def _render_context_section(title: str, value: Any) -> str:
    if value is None or value == "" or value == [] or value == {}:
        return ""
    if isinstance(value, Mapping):
        body = "\n".join(f"{key}: {_format_context_value(item)}" for key, item in value.items())
    elif isinstance(value, list):
        body = "\n".join(_format_context_value(item) for item in value)
    else:
        body = str(value).strip()
    return f"## {title}\n{body}" if body else ""


def _format_context_value(value: Any) -> str:
    if isinstance(value, Mapping):
        return "{" + ", ".join(f"{key}: {_format_context_value(item)}" for key, item in value.items()) + "}"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_format_context_value(item) for item in value) + "]"
    return str(value)


def _coerce_context_text(value: str | Iterable[str] | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return "\n".join(str(item).strip() for item in value if str(item).strip())


async def _aiter_stream(stream: AsyncIterable[Any] | Iterable[Any] | Any) -> AsyncIterable[Any]:
    if inspect.isawaitable(stream):
        stream = await stream
    if hasattr(stream, "__aiter__"):
        async for item in stream:
            yield item
        return
    for item in stream:
        yield item


def _coerce_text_delta(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, Mapping):
        value = chunk.get("text") or chunk.get("delta") or chunk.get("content")
        return value if isinstance(value, str) else ""
    return ""


def _is_provider_event_chunk(chunk: Any) -> bool:
    return isinstance(chunk, Mapping) and bool(chunk.get("type")) and not _coerce_text_delta(chunk)


def _pop_complete_sentences(buffer: str) -> tuple[list[str], str]:
    sentences: list[str] = []
    cursor = 0
    for match in SENTENCE_RE.finditer(buffer):
        sentence = match.group(1).strip()
        if sentence:
            sentences.append(sentence)
        cursor = match.end()
    return sentences, buffer[cursor:]


__all__ = [
    "IDENTITY_FILE_ORDER",
    "RETIRED_WORKSPACE_FILES",
    "NON_INJECTED_WORKSPACE_FILES",
    "IdentityLoadError",
    "JsonlTraceSink",
    "LIVE_TURN_COMPLETED",
    "LIVE_TURN_FAILED",
    "LIVE_TURN_STARTED",
    "LiveIdentity",
    "LiveIdentityStore",
    "LiveSDKConfig",
    "LiveTurnEventType",
    "MEMORY_RECALL_COMPLETED",
    "PROMPT_ASSEMBLED",
    "PROVIDER_EVENT",
    "SENTENCE",
    "SESSION_SUMMARY_COMPLETED",
    "SESSION_SUMMARY_FAILED",
    "SESSION_SUMMARY_SKIPPED",
    "SESSION_SUMMARY_STARTED",
    "SessionSummaryResult",
    "SessionSummarySkipReason",
    "SentenceBoundaryPolicy",
    "SubjectConsolidation",
    "SubjectMemory",
    "SubjectPathBuilder",
    "SubjectPromotionDisabledError",
    "TEXT_DELTA",
    "TraceSink",
    "UnknownIdentityFilePolicy",
    "LiveTurnContext",
    "LiveTurnEvent",
    "PreparedLiveTurn",
]
