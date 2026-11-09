"""Static consumer contract; copied outside the checkout and never executed."""

from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any, Literal, assert_type

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
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.host.managed_session import ManagedHostSession, ManagedHostSessionRunner, ManagedHostTurnOutcome
from memory_core.host.session_publication import SessionPublicationController
from memory_core.index.hybrid import HybridResult
from memory_core.workspace import MemoryWorkspace
from memory_core.session_catalog import MemorySessionCatalog, SessionTranscriptChange
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
    assert_type(outcome.memory_publication, Literal["none", "committed", "uncertain"])
    if outcome.memory_publication == "uncertain":
        assert_type(await runner.acknowledge_memory_publication(
            expected_turn_id=outcome.turn_id), None)


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


def managed_contract(workspace: Path) -> None:
    config = MemoryConfig(workspace_dir=workspace, flags=FeatureFlags(vector_search=False))
    catalog = MemorySessionCatalog(workspace / "catalog.sqlite")
    memory_workspace = MemoryWorkspace(workspace, session_catalog=catalog)
    store = ManagedSQLiteMemoryStore(config, memory_workspace)
    controller = SessionPublicationController(store, memory_workspace, catalog)
    store.bind_session_publication(controller)

    def committed(change: SessionTranscriptChange) -> None:
        assert_type(change.revision, int)

    unsubscribe = catalog.subscribe_transcript_changes(committed)
    unsubscribe()
    assert_type(store.search("needle", max_results=3, sources={"memory"}), list[HybridResult])
    assert_type(store.status(), dict[str, Any])
    assert_type(store.reindex(memory_workspace, force=True), int)
    assert_type(store.reindex_sources(memory_workspace, sources={"sessions"},
                                     paths={"sessions/main/session.jsonl"}), int)
    assert_type(controller.wait_idle(timeout=0.5), bool)
    assert_type(controller.flush(reconcile=True), dict[str, Any])
    assert_type(controller.status(), dict[str, Any])
    store.close()
    assert_type(store.closed, bool)


async def managed_host_contract(workspace: Path) -> None:
    catalog = MemorySessionCatalog(workspace / "catalog.sqlite")
    config = MemoryConfig(workspace_dir=workspace, flags=FeatureFlags(vector_search=False))
    owner = ManagedHostSession.open(workspace, catalog=catalog, config=config, initialize=False)
    runner = owner.runner(SessionState.new(session_key="agent:main:typed", session_id="typed"))
    assert_type(runner, ManagedHostSessionRunner)
    assert_type(owner.kit, HostKit)
    assert_type(owner.store, ManagedSQLiteMemoryStore)
    assert_type(owner.controller, SessionPublicationController)
    assert_type(owner.publication_status(), dict[str, Any])
    assert_type(owner.reindex(force=True), int)
    assert_type(owner.synchronize(timeout=0.5), dict[str, Any])

    async def model(turn: HostTurn) -> HostModelResult:
        return HostModelResult()

    assert_type(await runner.run_turn("recall", execute=model), ManagedHostTurnOutcome)
    owner.close()
