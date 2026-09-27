from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
from pathlib import Path

from memory_core import (
    JsonlTraceSink,
    LiveIdentityStore,
    LiveSDKConfig,
    LiveTurnContext,
    SubjectMemory,
    initialize_agent_workspace,
)


async def fake_streaming_llm(messages: list[dict[str, str]]) -> AsyncIterator[str]:
    assert any("Active workflow" in message["content"] for message in messages)
    for chunk in ("Tabii, ", "yardimci olayim. ", "Once kimliginizi dogrulayalim."):
        yield chunk
    yield {"type": "tool_call", "name": "example.follow_up", "arguments": {"ok": True}}


async def fake_summary_llm(messages: list[dict[str, str]]) -> str:
    transcript = messages[-1]["content"]
    if "aksam teslimat" in transcript.lower():
        return json.dumps(
            {
                "preferences": ["Subject prefers evening delivery."],
            }
        )
    return "NO_REPLY"


def redact_sensitive_text(text: str) -> str:
    return text.replace("4111 1111 1111 1111", "[redacted-card]")


async def run_live_turn(workspace_dir: str | Path) -> list[str]:
    workspace = Path(workspace_dir)
    identity = LiveIdentityStore(workspace, required_files=["AGENTS.md"]).load()
    memory = SubjectMemory.open(
        workspace_dir=workspace,
        subject_id="subj_123",
        reindex=False,
    )
    trace_sink = JsonlTraceSink.for_session(workspace / "trace", "session_456")
    live_config = LiveSDKConfig(openclaw_compatible=True, trace_sink=trace_sink)
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
        config=live_config,
    ):
        if event.type == "sentence":
            tts_sentences.append(event.text)
        elif event.type == "provider_event":
            pass
    return tts_sentences


async def record_session_summary(workspace_dir: str | Path) -> str:
    memory = SubjectMemory.open(
        workspace_dir=workspace_dir,
        subject_id="subj_123",
        reindex=False,
    )
    result = await memory.async_record_session_summary(
        session_id="session_456",
        transcript="User wants aksam teslimat. Card: 4111 1111 1111 1111",
        redactor=redact_sensitive_text,
        summary_llm=fake_summary_llm,
        timezone="Europe/Istanbul",
    )
    return result.path if result.wrote else ""


def seed_identity(workspace_dir: str | Path) -> None:
    # Seed the default memory-core layout with this example's own text. Files without
    # a template are created empty and are not injected; seed_bootstrap=False
    # skips BOOTSTRAP.md because a live host has no first-run ritual.
    initialize_agent_workspace(
        workspace_dir,
        templates={
            # Local tool notes live in the AGENTS.md "## Tools" section (OpenClaw v2026.9.6
            # retired TOOLS.md).
            "AGENTS.md": (
                "You are a concise live support agent. "
                "Verify identity before changing account data.\n\n"
                "## Tools\n\nTool calls are owned by the host runtime.\n"
            ),
            "SOUL.md": "Use short, clear turns suitable for text-to-speech.\n",
        },
        seed_bootstrap=False,
    )


async def main() -> None:
    workspace_dir = Path(".memory-core-live-example")
    seed_identity(workspace_dir)

    sentences = await run_live_turn(workspace_dir)
    for sentence in sentences:
        print(f"TTS: {sentence}")

    memory_path = await record_session_summary(workspace_dir)
    if memory_path:
        print(f"Wrote memory: {memory_path}")


if __name__ == "__main__":
    asyncio.run(main())
