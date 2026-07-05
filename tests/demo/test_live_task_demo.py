from __future__ import annotations

import asyncio
import json
from pathlib import Path

from demo.live_task_demo import (
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

    assert (tmp_path / "identity" / "AGENT.md").exists()
    assert sentences
    assert "elapsed_ms" in events[0]
    assert events[-1]["type"] == LIVE_TURN_COMPLETED
    assert demo.state().workflow["current_step"] == "collect_new_time"
    assert (tmp_path / "trace" / "live-task" / "session_1.jsonl").exists()


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


def test_live_task_demo_records_structured_summary(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset()

    result = demo.record_summary(
        session_id="session_1",
        subject_id="subject_1",
        transcript="User verified identity and moved appointment to tomorrow at 15:00.",
    )

    memory_path = tmp_path / "subjects" / "subject_1" / result["path"]
    assert result["wrote"] is True
    assert result["follow_ups"] == ["Confirm appointment change with the scheduling system."]
    assert "appointment" in memory_path.read_text(encoding="utf-8")


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
