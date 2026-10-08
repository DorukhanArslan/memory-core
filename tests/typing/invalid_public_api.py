"""Intentional consumer errors; every expected diagnostic has an E marker."""

from typing import Any

from memory_core import FeatureFlags, HostKit, SessionState
from memory_core.live import JsonlTraceSink, SubjectMemory


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
