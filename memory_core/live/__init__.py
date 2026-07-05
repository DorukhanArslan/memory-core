from __future__ import annotations

from collections.abc import AsyncIterable, Callable, Iterable, Mapping
from dataclasses import dataclass
import inspect
import json
from pathlib import Path
import re
from typing import Any, Literal, Protocol

from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.memory_flush import SILENT_REPLY_TOKEN, build_memory_flush_plan
from memory_core.runtime_context_prompt import build_runtime_context_system_context
from memory_core.runtime_identity import (
    OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    MEMORY_CORE_RUNTIME_IDENTITY,
)

IDENTITY_FILE_ORDER = (
    ("AGENT.md", "Agent Identity"),
    ("COMPANY.md", "Company"),
    ("POLICY.md", "Policy"),
    ("ESCALATION.md", "Escalation"),
    ("STYLE.md", "Style"),
)
IDENTITY_FILE_NAMES = frozenset(filename for filename, _title in IDENTITY_FILE_ORDER)
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
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
SubjectPathBuilder = Callable[[Path, str], Path]


class IdentityLoadError(ValueError):
    pass


@dataclass(frozen=True)
class LiveIdentity:
    sections: tuple[tuple[str, str], ...]

    @classmethod
    def from_dir(
        cls,
        identity_dir: str | Path,
        *,
        required_files: Iterable[str] = (),
        max_chars_per_file: int | None = None,
        unknown_files: UnknownIdentityFilePolicy = "ignore",
    ) -> "LiveIdentity":
        root = Path(identity_dir)
        _validate_required_identity_files(root, required_files)
        _validate_unknown_identity_files(root, unknown_files)
        sections: list[tuple[str, str]] = []
        for filename, title in IDENTITY_FILE_ORDER:
            path = root / filename
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8").strip()
            if text:
                text = _truncate_identity_text(text, max_chars_per_file)
                sections.append((title, text))
        return cls(tuple(sections))

    def to_prompt_section(self) -> str:
        return "\n\n".join(f"## {title}\n{text}" for title, text in self.sections)


@dataclass
class LiveIdentityStore:
    identity_dir: Path
    required_files: tuple[str, ...] = ()
    max_chars_per_file: int | None = None
    unknown_files: UnknownIdentityFilePolicy = "ignore"
    _cached: LiveIdentity | None = None

    def __init__(
        self,
        identity_dir: str | Path,
        *,
        required_files: Iterable[str] = (),
        max_chars_per_file: int | None = None,
        unknown_files: UnknownIdentityFilePolicy = "ignore",
    ):
        self.identity_dir = Path(identity_dir)
        self.required_files = tuple(required_files)
        self.max_chars_per_file = max_chars_per_file
        self.unknown_files = unknown_files
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
            unknown_files=self.unknown_files,
        )
        return self._cached


@dataclass(frozen=True)
class LiveTurnContext:
    subject_id: str
    session_id: str
    user_utterance: str
    transcript_window: str | Iterable[str] | None = None
    crm_context: Mapping[str, Any] | str | None = None
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
    admin_review_suggestions: tuple[str, ...] = ()


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
    ) -> "SubjectMemory":
        safe_subject_id = _validate_safe_id(subject_id, label="subject_id")
        workspace = _resolve_subject_workspace(
            Path(workspace_dir),
            safe_subject_id,
            namespace=namespace,
            subject_path_builder=subject_path_builder,
        )
        resolved_config = config or MemoryConfig(
            workspace_dir=workspace,
            flags=None if embedding_provider is not None else FeatureFlags(vector_search=False),
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
            identity.to_prompt_section() if identity is not None else "",
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
            data={"results": prepared.memory_results, "memory_context": prepared.memory_context},
        )
        yield _record_trace_event(
            PROMPT_ASSEMBLED,
            trace_sink=resolved_config.trace_sink,
            data={"trace_context": prepared.trace_context, "runtime_context": prepared.runtime_context},
        )

        assistant_parts: list[str] = []
        sentence_buffer = ""
        try:
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
            _record_trace_event(
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
    ) -> SessionSummaryResult:
        plan, messages = self._prepare_session_summary_messages(
            session_id=session_id,
            transcript=transcript,
            redactor=redactor,
            now_ms=now_ms,
            timezone=timezone,
            trace_sink=trace_sink,
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
    ) -> SessionSummaryResult:
        plan, messages = self._prepare_session_summary_messages(
            session_id=session_id,
            transcript=transcript,
            redactor=redactor,
            now_ms=now_ms,
            timezone=timezone,
            trace_sink=trace_sink,
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
        )
        messages = [
            {"role": "system", "content": plan.system_prompt},
            {
                "role": "user",
                "content": (
                    f"{plan.prompt}\n\n"
                    f"Session memory extraction for session {session_id}.\n"
                    "Extract only durable facts, preferences, and follow-ups. "
                    "Return admin/policy suggestions separately if using JSON.\n\n"
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
        text = extraction["memory_text"]
        result = SessionSummaryResult(
            wrote=False,
            path=relative_path,
            text=text,
            raw_text=raw_text,
            durable_facts=extraction["durable_facts"],
            preferences=extraction["preferences"],
            follow_ups=extraction["follow_ups"],
            admin_review_suggestions=extraction["admin_review_suggestions"],
        )
        if not text or text.startswith(SILENT_REPLY_TOKEN):
            _record_trace_event(
                SESSION_SUMMARY_SKIPPED,
                trace_sink=trace_sink,
                data=_session_summary_trace_data(result),
            )
            return result

        self.memory.workspace.append_daily_memory(relative_path, text)
        self.memory.store.reindex(self.memory.workspace)
        result = SessionSummaryResult(
            wrote=True,
            path=relative_path,
            text=text,
            raw_text=raw_text,
            durable_facts=extraction["durable_facts"],
            preferences=extraction["preferences"],
            follow_ups=extraction["follow_ups"],
            admin_review_suggestions=extraction["admin_review_suggestions"],
        )
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
    if not SAFE_ID_RE.fullmatch(value):
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


def _validate_required_identity_files(root: Path, required_files: Iterable[str]) -> None:
    missing = [
        filename
        for filename in required_files
        if filename not in IDENTITY_FILE_NAMES or not (root / filename).is_file()
    ]
    if missing:
        raise IdentityLoadError(f"missing required identity files: {', '.join(sorted(missing))}")


def _validate_unknown_identity_files(root: Path, policy: UnknownIdentityFilePolicy) -> None:
    if policy == "ignore" or not root.is_dir():
        return
    if policy != "error":
        raise IdentityLoadError(f"unknown identity file policy: {policy}")
    unknown = sorted(path.name for path in root.glob("*.md") if path.name not in IDENTITY_FILE_NAMES)
    if unknown:
        raise IdentityLoadError(f"unknown identity files: {', '.join(unknown)}")


def _truncate_identity_text(text: str, max_chars: int | None) -> str:
    if max_chars is None or max_chars <= 0 or len(text) <= max_chars:
        return text
    suffix = "\n\n[truncated]"
    if max_chars <= len(suffix):
        return text[:max_chars]
    return f"{text[: max_chars - len(suffix)].rstrip()}{suffix}"


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
    return {
        "wrote": result.wrote,
        "path": result.path,
        "durable_facts": list(result.durable_facts),
        "preferences": list(result.preferences),
        "follow_ups": list(result.follow_ups),
        "admin_review_suggestions": list(result.admin_review_suggestions),
    }


def _parse_session_summary_output(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if not text or text.startswith(SILENT_REPLY_TOKEN):
        return _session_summary_payload(memory_text="", raw_text=raw_text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _session_summary_payload(memory_text=text, raw_text=raw_text)
    if not isinstance(payload, dict):
        return _session_summary_payload(memory_text=text, raw_text=raw_text)

    durable_facts = _string_tuple(payload.get("durable_facts"))
    preferences = _string_tuple(payload.get("preferences"))
    follow_ups = _string_tuple(payload.get("follow_ups"))
    admin_review_suggestions = _string_tuple(payload.get("admin_review_suggestions"))
    memory_text = _format_structured_session_memory(
        durable_facts=durable_facts,
        preferences=preferences,
        follow_ups=follow_ups,
    )
    return {
        "memory_text": memory_text,
        "durable_facts": durable_facts,
        "preferences": preferences,
        "follow_ups": follow_ups,
        "admin_review_suggestions": admin_review_suggestions,
    }


def _session_summary_payload(*, memory_text: str, raw_text: str) -> dict[str, Any]:
    return {
        "memory_text": memory_text,
        "durable_facts": (),
        "preferences": (),
        "follow_ups": (),
        "admin_review_suggestions": (),
    }


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if not isinstance(value, list | tuple):
        return ()
    items = []
    for item in value:
        if isinstance(item, str) and item.strip():
            items.append(item.strip())
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
        ("CRM context", context.crm_context),
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
    "SentenceBoundaryPolicy",
    "SubjectMemory",
    "SubjectPathBuilder",
    "TEXT_DELTA",
    "TraceSink",
    "LiveTurnContext",
    "LiveTurnEvent",
    "PreparedLiveTurn",
]
