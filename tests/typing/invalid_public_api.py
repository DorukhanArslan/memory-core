"""Intentional consumer errors; every expected diagnostic has an E marker."""

from typing import Any
from pathlib import Path

from memory_core import (
    FeatureFlags, HostKit, HostModelResult, HostSessionRunner, HostTurn,
    SessionState, MemoryConfig,
)
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.host.managed_session import ManagedHostSession, ManagedHostSessionRunner
from memory_core.host.session_publication import SessionPublicationController
from memory_core.live import JsonlTraceSink, SubjectMemory
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.workspace import MemoryWorkspace


def wrong_payload(payload: dict[str, Any]) -> str:
    return "not an object"


def wrong_output(text: str) -> int:
    return 1


def invalid_contract(kit: HostKit, memory: SubjectMemory) -> None:
    session = SessionState.new(session_key="session", session_id="session", kind="private")  # E: arg-type
    kit.before_turn("not a session")  # E: arg-type
    kit.dispatch("memory_search", [], session=session)  # E: arg-type
    FeatureFlags(vector_search="yes")  # E: arg-type
    JsonlTraceSink("unused.jsonl", payload_redactor=wrong_payload)  # E: arg-type
    memory.record_session_summary(
        session_id="session", transcript="hello", summary_llm=lambda messages: "- note",
        output_redactor=wrong_output,  # E: arg-type
    )


async def valid_model(turn: HostTurn) -> HostModelResult:
    return HostModelResult()


async def invalid_lifecycle(runner: HostSessionRunner, workspace: Path) -> None:
    HostSessionRunner.open(workspace, catalog=MemorySessionCatalog(workspace / "s.sqlite"),
        session="invalid")  # E: arg-type
    await runner.run_turn(42, execute=valid_model)  # E: arg-type
    HostModelResult(usage="tokens")  # E: arg-type
    await runner.acknowledge_memory_publication(expected_turn_id=42)  # E: arg-type


def invalid_managed(store: ManagedSQLiteMemoryStore, config: MemoryConfig) -> None:
    store.search("needle", max_results="many")  # E: arg-type
    ManagedSQLiteMemoryStore(config, "not a workspace")  # E: arg-type


def invalid_session_publication(store: ManagedSQLiteMemoryStore, workspace: MemoryWorkspace,
                                catalog: MemorySessionCatalog, controller: SessionPublicationController) -> None:
    store.reindex_sources(workspace, sources={42})  # E: arg-type
    store.reindex_sources(workspace, sources={"sessions"}, paths=[42])  # E: list-item
    store.reindex_sources(workspace, sources={"memory"}, force_sources="yes")  # E: arg-type
    store.bind_session_publication(None)  # E: arg-type
    controller.wait_idle(timeout="soon")  # E: arg-type
    SessionPublicationController(store, workspace, "invalid catalog")  # E: arg-type
    catalog.subscribe_transcript_changes("invalid callback")  # E: arg-type


def invalid_managed_host(owner: ManagedHostSession, workspace: Path) -> None:
    ManagedHostSession.open(workspace, catalog="invalid catalog")  # E: arg-type
    ManagedHostSession.open(workspace, catalog=owner.catalog, maintenance="later")  # E: arg-type
    ManagedHostSession.open(workspace, catalog=owner.catalog, maintenance=False)  # E: arg-type
    owner.runner("invalid session")  # E: arg-type
    owner.reindex(force="yes")  # E: arg-type
    owner.synchronize(timeout="soon")  # E: arg-type
    owner.close("extra")  # E: call-arg


async def invalid_managed_delivery(runner: ManagedHostSessionRunner) -> None:
    await runner.run_turn("recall", execute=valid_model, deliver="later")  # E: arg-type
