from __future__ import annotations

import asyncio
from pathlib import Path

from memory_core.live import (
    LiveIdentity,
    LiveTurnContext,
    LiveTurnEvent,
    SubjectMemory,
)
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY


def test_identity_loader_reads_known_files_in_prompt_order(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "STYLE.md").write_text("Speak briefly.", encoding="utf-8")
    (identity_dir / "POLICY.md").write_text("Verify identity first.", encoding="utf-8")
    (identity_dir / "AGENT.md").write_text("You are a support voice agent.", encoding="utf-8")

    identity = LiveIdentity.from_dir(identity_dir)

    assert identity.to_prompt_section() == "\n\n".join(
        [
            "## Agent Identity\nYou are a support voice agent.",
            "## Policy\nVerify identity first.",
            "## Style\nSpeak briefly.",
        ]
    )


def test_subject_memory_uses_separate_workspace_per_subject(tmp_path: Path):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)

    result = memory.record_session_summary(
        session_id="session_1",
        transcript="User wants evening delivery.",
        summary_llm=lambda messages: "- Subject prefers evening delivery.",
        now_ms=1_788_526_800_000,
        timezone="Europe/Istanbul",
    )

    assert result.wrote is True
    assert result.path == "memory/2026-09-04.md"
    assert (
        tmp_path / "subjects" / "subj_123" / "memory" / "2026-09-04.md"
    ).read_text(encoding="utf-8") == "- Subject prefers evening delivery.\n"
    assert not (tmp_path / "memory" / "2026-09-04.md").exists()


def test_prepare_live_turn_wraps_workflow_state_as_openclaw_runtime_context(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "AGENT.md").write_text("You are a voice support agent.", encoding="utf-8")
    identity = LiveIdentity.from_dir(identity_dir)
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)

    prepared = memory.prepare_live_turn(
        LiveTurnContext(
            subject_id="subj_123",
            session_id="session_1",
            user_utterance="Adresimi değiştirmek istiyorum.",
            workflow_state={
                "workflow_id": "address_change",
                "current_step": "verify_identity",
                "pending_steps": ["verify_identity", "collect_new_address"],
            },
        ),
        identity=identity,
        openclaw_compatible=True,
    )

    assert prepared.messages[0]["role"] == "system"
    assert "You are a voice support agent." in prepared.messages[0]["content"]
    assert OPENCLAW_COMPAT_RUNTIME_IDENTITY.runtime_context_begin in prepared.messages[0]["content"]
    assert "workflow_id: address_change" in prepared.messages[0]["content"]
    assert "current_step: verify_identity" in prepared.messages[0]["content"]
    assert prepared.messages[-1] == {
        "role": "user",
        "content": "Adresimi değiştirmek istiyorum.",
    }


def test_stream_live_turn_emits_sentence_events_for_tts(tmp_path: Path):
    async def llm_stream(messages):
        assert any("Active workflow" in message["content"] for message in messages)
        for chunk in ["Tabii, ", "yardımcı olayım. ", "Önce kimliğinizi doğrulayalım."]:
            yield chunk

    async def collect_events() -> list[LiveTurnEvent]:
        memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
        events: list[LiveTurnEvent] = []
        async for event in memory.stream_live_turn(
            LiveTurnContext(
                subject_id="subj_123",
                session_id="session_1",
                user_utterance="Adresimi değiştirmek istiyorum.",
                workflow_state={"workflow_id": "address_change"},
            ),
            llm=llm_stream,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    assert [event.type for event in events] == [
        "live_turn_started",
        "memory_recall_completed",
        "prompt_assembled",
        "text_delta",
        "text_delta",
        "sentence",
        "text_delta",
        "sentence",
        "live_turn_completed",
    ]
    assert [event.text for event in events if event.type == "sentence"] == [
        "Tabii, yardımcı olayım.",
        "Önce kimliğinizi doğrulayalım.",
    ]
    assert events[-1].data["assistant_text"] == (
        "Tabii, yardımcı olayım. Önce kimliğinizi doğrulayalım."
    )
