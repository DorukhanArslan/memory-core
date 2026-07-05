from __future__ import annotations

from collections.abc import AsyncIterable, Callable, Iterable, Mapping
from dataclasses import dataclass
import inspect
from pathlib import Path
import re
from typing import Any

from memory_core.client import Memory, MemoryRecordResult
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.flags import FeatureFlags
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
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SENTENCE_RE = re.compile(r"(.+?[.!?…])(?:\s+|$)", re.DOTALL)


@dataclass(frozen=True)
class LiveIdentity:
    sections: tuple[tuple[str, str], ...]

    @classmethod
    def from_dir(cls, identity_dir: str | Path) -> "LiveIdentity":
        root = Path(identity_dir)
        sections: list[tuple[str, str]] = []
        for filename, title in IDENTITY_FILE_ORDER:
            path = root / filename
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8").strip()
            if text:
                sections.append((title, text))
        return cls(tuple(sections))

    def to_prompt_section(self) -> str:
        return "\n\n".join(f"## {title}\n{text}" for title, text in self.sections)


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
    type: str
    text: str = ""
    data: dict[str, Any] | None = None


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
        embedding_provider: EmbeddingProvider | None = None,
        config: MemoryConfig | None = None,
        initialize: bool = True,
        reindex: bool = True,
    ) -> "SubjectMemory":
        safe_subject_id = _validate_safe_id(subject_id, label="subject_id")
        workspace = Path(workspace_dir) / "subjects" / safe_subject_id
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
        openclaw_compatible: bool = False,
        max_results: int = 5,
        min_score: float = 0.0,
        corpus: str = "all",
    ) -> AsyncIterable[LiveTurnEvent]:
        yield LiveTurnEvent(
            "live_turn_started",
            data={
                "subject_id": context.subject_id,
                "session_id": context.session_id,
            },
        )
        prepared = self.prepare_live_turn(
            context,
            identity=identity,
            openclaw_compatible=openclaw_compatible,
            max_results=max_results,
            min_score=min_score,
            corpus=corpus,
        )
        yield LiveTurnEvent(
            "memory_recall_completed",
            data={"results": prepared.memory_results, "memory_context": prepared.memory_context},
        )
        yield LiveTurnEvent(
            "prompt_assembled",
            data={"trace_context": prepared.trace_context, "runtime_context": prepared.runtime_context},
        )

        assistant_parts: list[str] = []
        sentence_buffer = ""
        async for chunk in _aiter_stream(llm(prepared.messages)):
            text = _coerce_text_delta(chunk)
            if not text:
                continue
            assistant_parts.append(text)
            sentence_buffer += text
            yield LiveTurnEvent("text_delta", text=text)
            sentences, sentence_buffer = _pop_complete_sentences(sentence_buffer)
            for sentence in sentences:
                yield LiveTurnEvent("sentence", text=sentence)

        remainder = sentence_buffer.strip()
        if remainder:
            yield LiveTurnEvent("sentence", text=remainder)
        assistant_text = "".join(assistant_parts).strip()
        yield LiveTurnEvent(
            "live_turn_completed",
            data={
                "assistant_text": assistant_text,
                "trace_context": prepared.trace_context,
            },
        )

    def record_session_summary(
        self,
        *,
        session_id: str,
        transcript: str,
        summary_llm: Callable[[list[dict[str, str]]], str],
        redactor: Callable[[str], str] | None = None,
        now_ms: int | None = None,
        timezone: str = "UTC",
    ) -> MemoryRecordResult:
        redacted_transcript = redactor(transcript) if redactor is not None else transcript
        return self.memory.record_turn(
            f"Session memory extraction for session {session_id}.",
            redacted_transcript,
            flush_llm=summary_llm,
            now_ms=now_ms,
            timezone=timezone,
        )


def _validate_safe_id(value: str, *, label: str) -> str:
    if not SAFE_ID_RE.fullmatch(value):
        raise ValueError(f"{label} is not filesystem-safe: {value}")
    return value


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
    "LiveIdentity",
    "SubjectMemory",
    "LiveTurnContext",
    "LiveTurnEvent",
    "PreparedLiveTurn",
]
