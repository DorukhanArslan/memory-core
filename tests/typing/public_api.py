"""Static consumer contract; copied outside the checkout and never executed."""

from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any, assert_type

from memory_core import (
    EmbeddingProvider,
    FeatureFlags,
    HostKit,
    HostModelResult,
    HostSessionRunner,
    HostTurn,
    HostTurnOutcome,
    Memory,
    MemoryConfig,
    SessionState,
    TurnContext,
    TurnRecord,
    TurnState,
    TurnUsage,
)
from memory_core.adapters.langgraph import tool_messages, transcript_rows, turn_usage
from memory_core.host import FlushOutcome, FlushRequest
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.live import (
    JsonlTraceSink,
    LiveTurnContext,
    LiveTurnEvent,
    SessionSummaryResult,
    SubjectMemory,
    TraceSink,
)


class HostEmbeddingProvider:
    provider_id: str = "host"
    model: str = "host-model"

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text))]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


def summary(messages: list[dict[str, str]]) -> str:
    return '{"durable_facts": []}'


def sanitize_text(text: str) -> str:
    return text


def sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return payload


async def chunks(messages: list[dict[str, str]]) -> AsyncIterator[str]:
    yield "done"


async def host_model(turn: HostTurn) -> HostModelResult:
    assert_type(turn.context, TurnContext | None)
    assert_type(turn.messages, list[dict[str, Any]])
    return HostModelResult(usage=TurnUsage(20, 2))


async def lifecycle_contract(workspace: Path) -> None:
    catalog = MemorySessionCatalog(workspace / "sessions.sqlite")
    runner = HostSessionRunner.open(workspace, catalog=catalog,
        session=SessionState.new(session_key="agent:main:dm:types", session_id="types"))
    assert_type(runner, HostSessionRunner)
    outcome = await runner.run_turn("Hello", execute=host_model, execute_flush=host_model)
    assert_type(outcome, HostTurnOutcome)
    assert_type(outcome.ready, bool)
    assert_type(outcome.session, SessionState)


def host_contract(workspace: Path) -> None:
    provider: EmbeddingProvider = HostEmbeddingProvider()
    config = MemoryConfig(workspace_dir=workspace, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(workspace, config=config, embedding_provider=provider)
    assert_type(memory, Memory)
    kit = HostKit(memory, seed_bootstrap=False)
    assert_type(HostKit.open(workspace, config=config, seed_bootstrap=False), HostKit)
    session = SessionState.new(session_key="session", session_id="session", kind="main")
    assert_type(SessionState.from_json(session.to_json()), SessionState)
    context = kit.before_turn(session, ensure=False)
    assert_type(context, TurnContext)
    assert_type(TurnState.from_context(context), TurnState)
    dispatch = kit.dispatcher(context.session)
    assert_type(dispatch, Callable[[str, Mapping[str, Any] | str | None], dict[str, Any]])
    assert_type(dispatch("memory_search", {"query": "note"}), dict[str, Any])
    assert_type(transcript_rows([]), list[dict[str, Any]])
    assert_type(tool_messages({}, dispatch), list[dict[str, Any]])
    assert_type(turn_usage({}), TurnUsage | None)
    record = kit.after_turn(session, transcript=[], usage=TurnUsage(prompt_tokens=0))
    assert_type(record, TurnRecord)
    assert_type(record.flush, FlushRequest | None)
    if record.flush is not None:
        assert_type(record.flush.complete(record.session), FlushOutcome)


async def live_contract(workspace: Path) -> None:
    memory = SubjectMemory.open(workspace_dir=workspace, subject_id="subject", reindex=False)
    sink = JsonlTraceSink.for_session(workspace, "session", payload_redactor=sanitize_payload)
    protocol: TraceSink = sink
    context = LiveTurnContext(subject_id="subject", session_id="session", user_utterance="hello")
    assert_type(memory.stream_live_turn(context, llm=chunks, trace_sink=protocol),
                AsyncIterable[LiveTurnEvent])
    assert_type(memory.record_session_summary(
        session_id="session", transcript="hello", summary_llm=summary,
        redactor=sanitize_text, output_redactor=sanitize_text, trace_sink=sink,
    ), SessionSummaryResult)
    assert_type(await memory.async_record_session_summary(
        session_id="session", transcript="hello", summary_llm=summary,
        redactor=sanitize_text, output_redactor=sanitize_text, trace_sink=sink,
    ), SessionSummaryResult)
