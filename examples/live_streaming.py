from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from memory_core import JsonlTraceSink, LiveIdentity, LiveTurnContext, SubjectMemory


async def fake_streaming_llm(messages: list[dict[str, str]]) -> AsyncIterator[str]:
    assert any("Active workflow" in message["content"] for message in messages)
    for chunk in ("Tabii, ", "yardimci olayim. ", "Once kimliginizi dogrulayalim."):
        yield chunk
    yield {"type": "tool_call", "name": "example.follow_up", "arguments": {"ok": True}}


def fake_summary_llm(messages: list[dict[str, str]]) -> str:
    transcript = messages[-1]["content"]
    if "aksam teslimat" in transcript.lower():
        return "- Subject prefers evening delivery."
    return "NO_REPLY"


def redact_sensitive_text(text: str) -> str:
    return text.replace("4111 1111 1111 1111", "[redacted-card]")


async def run_live_turn(workspace_dir: str | Path, identity_dir: str | Path) -> list[str]:
    identity = LiveIdentity.from_dir(identity_dir)
    workspace = Path(workspace_dir)
    memory = SubjectMemory.open(
        workspace_dir=workspace,
        subject_id="subj_123",
        reindex=False,
    )
    trace_sink = JsonlTraceSink(workspace / "trace" / "session_456.jsonl")
    context = LiveTurnContext(
        subject_id="subj_123",
        session_id="session_456",
        user_utterance="Adresimi degistirmek istiyorum.",
        transcript_window=[
            "User: Merhaba.",
            "Assistant: Size nasil yardimci olabilirim?",
        ],
        workflow_state={
            "workflow_id": "address_change",
            "current_step": "verify_identity",
            "pending_steps": ["verify_identity", "collect_new_address", "confirm"],
        },
    )

    tts_sentences: list[str] = []
    async for event in memory.stream_live_turn(
        context,
        identity=identity,
        llm=fake_streaming_llm,
        openclaw_compatible=True,
        trace_sink=trace_sink,
    ):
        if event.type == "sentence":
            tts_sentences.append(event.text)
        elif event.type == "provider_event":
            pass
    return tts_sentences


def record_session_summary(workspace_dir: str | Path) -> str:
    memory = SubjectMemory.open(
        workspace_dir=workspace_dir,
        subject_id="subj_123",
        reindex=False,
    )
    result = memory.record_session_summary(
        session_id="session_456",
        transcript="User wants aksam teslimat. Card: 4111 1111 1111 1111",
        redactor=redact_sensitive_text,
        summary_llm=fake_summary_llm,
        timezone="Europe/Istanbul",
    )
    return result.path if result.wrote else ""


def seed_identity(identity_dir: str | Path) -> None:
    root = Path(identity_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENT.md").write_text(
        "You are a concise live support agent.",
        encoding="utf-8",
    )
    (root / "POLICY.md").write_text(
        "Verify identity before changing account data.",
        encoding="utf-8",
    )


async def main() -> None:
    workspace_dir = Path(".memory-core-live-example")
    identity_dir = workspace_dir / "identity"
    seed_identity(identity_dir)

    sentences = await run_live_turn(workspace_dir, identity_dir)
    for sentence in sentences:
        print(f"TTS: {sentence}")

    memory_path = record_session_summary(workspace_dir)
    if memory_path:
        print(f"Wrote memory: {memory_path}")


if __name__ == "__main__":
    asyncio.run(main())
