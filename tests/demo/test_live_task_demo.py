from __future__ import annotations

import asyncio
import json
from pathlib import Path

from demo.live_task_demo import (
    LIVE_TASK_AGENTS_SECTION_HEADING,
    LiveTaskDemo,
    LiveTaskSessionState,
    advance_appointment_workflow,
    latency_event_payload,
)
from memory_core.live import LIVE_TURN_COMPLETED, SENTENCE


def test_advance_appointment_workflow_collects_slots_in_order():
    state = LiveTaskSessionState(session_id="session_1", subject_id="subject_1")

    verified = advance_appointment_workflow(state, "Doğum tarihim 12.04.1990")
    scheduled = advance_appointment_workflow(verified, "Yarın saat 15:00 uygun olur")
    completed = advance_appointment_workflow(scheduled, "Evet onaylıyorum")

    assert verified.current_step == "collect_new_time"
    assert verified.verified is True
    assert scheduled.current_step == "confirm_change"
    assert scheduled.requested_slot == "Yarın saat 15:00 uygun olur"
    assert completed.current_step == "completed"
    assert completed.completed is True
    assert completed.business_action == {
        "type": "appointment_rescheduled",
        "requested_slot": "Yarın saat 15:00 uygun olur",
    }


def test_live_task_demo_bootstraps_identity_and_streams_sentence_events(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset()

    async def collect():
        return [
            event
            async for event in demo.stream_turn(
                session_id="session_1",
                subject_id="subject_1",
                user_utterance="Doğum tarihim 12.04.1990",
            )
        ]

    events = asyncio.run(collect())
    sentences = [event for event in events if event["type"] == SENTENCE]

    assert (tmp_path / "AGENTS.md").exists()
    assert "appointment_reschedule" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert sentences
    assert "elapsed_ms" in events[0]
    assert events[-1]["type"] == LIVE_TURN_COMPLETED
    assert demo.state().workflow["current_step"] == "collect_new_time"
    assert (tmp_path / "trace" / "live-task" / "session_1.jsonl").exists()


def test_live_task_demo_appends_its_agents_section_once(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset()
    demo.reset()

    async def collect():
        return [
            event
            async for event in demo.stream_turn(
                session_id="session_1",
                subject_id="subject_1",
                user_utterance="Doğum tarihim 12.04.1990",
            )
        ]

    asyncio.run(collect())
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    edited = agents.replace("Ask for one missing item at a time.", "Ask one thing per turn.")
    (tmp_path / "AGENTS.md").write_text(edited, encoding="utf-8")
    demo.reset()

    assert agents.count(LIVE_TASK_AGENTS_SECTION_HEADING) == 1
    assert agents.startswith("# AGENTS.md - Operating Instructions")
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == edited


def test_live_task_demo_keeps_root_memory_out_of_live_prompts(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset()
    (tmp_path / "MEMORY.md").write_text("Operator-only long-term note.", encoding="utf-8")
    seen: list[str] = []

    async def capturing_llm(messages):
        seen.append(messages[0]["content"])
        yield "Tamam."

    async def collect():
        return [
            event
            async for event in demo.stream_turn(
                session_id="session_1",
                subject_id="subject_1",
                user_utterance="Merhaba",
                llm=capturing_llm,
            )
        ]

    asyncio.run(collect())

    assert "Operator-only long-term note." not in seen[0]
    assert "# Project Context\n" in seen[0]
    assert LIVE_TASK_AGENTS_SECTION_HEADING in seen[0]
    assert "MEMORY.md" not in demo.state().identity_files


def test_live_task_demo_transcript_records_assistant_text_once(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset()

    async def collect():
        return [
            event
            async for event in demo.stream_turn(
                session_id="session_1",
                subject_id="subject_1",
                user_utterance="Doğum tarihim 12.04.1990",
            )
        ]

    events = asyncio.run(collect())
    completed = [event for event in events if event["type"] == LIVE_TURN_COMPLETED][0]
    transcript = demo.state().transcript

    assert transcript[-1] == {
        "role": "assistant",
        "content": completed["data"]["assistant_text"],
    }


def test_live_task_demo_stream_turn_uses_injected_llm(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset()

    async def custom_llm(messages):
        assert messages[0]["role"] == "system"
        assert messages[-1] == {"role": "user", "content": "Doğum tarihim 12.04.1990"}
        yield {"type": "llm", "provider": "openai", "model": "test-model"}
        yield "Merhaba. "
        yield "Size nasıl yardımcı olabilirim?"

    async def collect():
        return [
            event
            async for event in demo.stream_turn(
                session_id="session_1",
                subject_id="subject_1",
                user_utterance="Doğum tarihim 12.04.1990",
                llm=custom_llm,
            )
        ]

    events = asyncio.run(collect())
    deltas = [event["text"] for event in events if event["type"] == "text_delta"]
    provider_payloads = [event["data"] for event in events if event["type"] == "provider_event"]

    assert "".join(deltas) == "Merhaba. Size nasıl yardımcı olabilirim?"
    assert {"type": "llm", "provider": "openai", "model": "test-model"} in provider_payloads
    assert demo.state().transcript[-1] == {
        "role": "assistant",
        "content": "Merhaba. Size nasıl yardımcı olabilirim?",
    }


def test_live_task_demo_record_summary_uses_injected_llm(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset()

    result = demo.record_summary(
        session_id="session_1",
        subject_id="subject_1",
        summary_llm=lambda messages: json.dumps(
            {"durable_facts": ["Özel kalıcı not"]}, ensure_ascii=False
        ),
    )

    assert result["wrote"] is True
    assert result["durable_facts"] == ["Özel kalıcı not"]


def test_live_task_demo_records_structured_summary(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset()

    async def run_flow():
        for utterance in (
            "Doğum tarihim 12.04.1990",
            "Yarın saat 15:00 uygun olur",
            "Evet onaylıyorum",
        ):
            async for _ in demo.stream_turn(
                session_id="session_1",
                subject_id="subject_1",
                user_utterance=utterance,
            ):
                pass

    asyncio.run(run_flow())
    result = demo.record_summary(session_id="session_1", subject_id="subject_1")

    memory_path = tmp_path / "subjects" / "subject_1" / result["path"]
    memory_text = memory_path.read_text(encoding="utf-8")
    assert result["wrote"] is True
    assert any("Doğum tarihim 12.04.1990" in fact for fact in result["durable_facts"])
    assert any("Yarın saat 15:00" in fact for fact in result["durable_facts"])
    assert result["follow_ups"] == ["Randevu değişikliğini takvim sisteminde doğrula."]
    assert "Randevu talebi" in memory_text

    subject_memory_files = demo.state().subject_memory_files
    assert "Randevu talebi" in subject_memory_files[result["path"]]


def test_live_task_demo_summary_without_turns_records_incomplete_flow(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset()

    result = demo.record_summary(session_id="session_1", subject_id="subject_1")

    assert result["wrote"] is True
    assert result["durable_facts"] == ["Randevu değişikliği görüşmesi başladı ancak tamamlanmadı."]
    assert result["follow_ups"] == []


def test_latency_event_payload_preserves_event_data():
    payload = latency_event_payload(
        event_type="sentence",
        text="Tamam.",
        data={"step": "verify_identity"},
        started_at=100.0,
        now=100.125,
    )

    assert payload == {
        "type": "sentence",
        "text": "Tamam.",
        "data": {"step": "verify_identity"},
        "elapsed_ms": 125,
    }
    json.dumps(payload)
