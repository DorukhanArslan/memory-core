"""Intentional consumer errors; every expected diagnostic has an E marker."""

from typing import Any
from pathlib import Path

from memory_core import (
    FeatureFlags, HostKit, HostModelResult, HostSessionRunner, HostTurn,
    SessionState,
)
from memory_core.live import JsonlTraceSink, SubjectMemory
from memory_core.session_catalog import MemorySessionCatalog


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
