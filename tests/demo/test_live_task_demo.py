from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

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


def test_live_task_prompt_names_what_each_workflow_step_needs(tmp_path: Path):
    # The model words the replies, so it must ask for what the step machine accepts:
    # a live gpt-6-luna turn asked for a full name while verify_identity waits for a date.
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset()
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

    assert "Bootstrap Pending" not in seen[0]
    assert not (tmp_path / "BOOTSTRAP.md").exists()
    assert "verify_identity: date of birth" in seen[0]
    assert "never ask again once verified is true" in seen[0]
    assert "current_step: verify_identity" in seen[0]


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
    assert "Kimlik doğrulama bilgisi: [kimlik bilgisi gizlendi]" in result["durable_facts"]
    assert not any("12.04.1990" in fact for fact in result["durable_facts"])
    assert "12.04.1990" not in memory_text
    assert result["redacted"] is True and result["skip_reason"] is None
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


def test_live_task_demo_summary_llm_never_sees_the_identity_proof(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset()
    seen = []

    async def run_flow():
        async for _ in demo.stream_turn(
            session_id="session_1", subject_id="subject_1", user_utterance="Müşteri numaram 4821."
        ):
            pass

    asyncio.run(run_flow())
    result = demo.record_summary(
        session_id="session_1",
        subject_id="subject_1",
        summary_llm=lambda messages: seen.append(messages) or '{"durable_facts": ["Kimlik doğrulandı."]}',
    )

    assert "4821" not in json.dumps(seen, ensure_ascii=False)
    assert "[kimlik bilgisi gizlendi]" in seen[0][-1]["content"]
    assert result["durable_facts"] == ["Kimlik doğrulandı."]


def test_live_task_demo_skips_an_unstructured_summary(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset()

    result = demo.record_summary(
        session_id="session_1", subject_id="subject_1", summary_llm=lambda messages: "Sure! Here is a summary."
    )

    assert result["wrote"] is False
    assert result["skip_reason"] == "unstructured"


def test_live_task_masks_verified_proof_in_output_state_and_new_trace(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    proof = "Doğum tarihim 12.04.1990"
    seen = []

    async def echo(messages):
        seen.append(messages)
        yield proof[:15]
        yield proof[15:]

    async def collect():
        return [event async for event in demo.stream_turn(
            session_id="session_1", subject_id="subject_1", user_utterance=proof, llm=echo
        )]

    events = asyncio.run(collect())
    trace = (tmp_path / "trace/live-task/session_1.jsonl").read_text(encoding="utf-8")
    assert seen[0][-1]["content"] == proof
    assert "12.04.1990" not in json.dumps(events, ensure_ascii=False)
    assert "12.04.1990" not in "".join(e["text"] for e in events if e["type"] == "text_delta")
    assert "12.04.1990" not in json.dumps(demo.state().transcript, ensure_ascii=False)
    assert "12.04.1990" not in trace


def test_live_task_masks_summary_model_repeated_proof_before_daily_write(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)

    async def verify():
        async for _ in demo.stream_turn(
            session_id="session_1", subject_id="subject_1",
            user_utterance="Doğum tarihim 12.04.1990",
        ):
            pass

    asyncio.run(verify())
    result = demo.record_summary(
        session_id="session_1", subject_id="subject_1",
        summary_llm=lambda messages: json.dumps({
            "durable_facts": ["Doğum tarihim 12.04.1990"],
            "preferences": ["12.04.1990"], "follow_ups": ["12.04.1990"],
        }, ensure_ascii=False),
    )
    daily = tmp_path / "subjects/subject_1" / result["path"]
    assert result["wrote"] is True
    assert "12.04.1990" not in daily.read_text(encoding="utf-8")
    assert "12.04.1990" not in json.dumps(result, ensure_ascii=False)
    assert "12.04.1990" not in (tmp_path / "trace/live-task/session_1.jsonl").read_text(encoding="utf-8")


def test_live_task_failure_discards_pending_key_prefix_without_committing(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset(session_id="session_1", subject_id="subject_1")
    key = "request-scoped-live-key-123"
    events = []

    async def failing(messages):
        yield key[:12]
        raise RuntimeError("token=abcdefghijklmnopqrstuvwxyz")

    async def collect():
        async for event in demo.stream_turn(
            session_id="session_1", subject_id="subject_1", user_utterance="Merhaba",
            llm=failing, secrets=(key,),
        ):
            events.append(event)

    with pytest.raises(RuntimeError):
        asyncio.run(collect())
    assert events[-1]["type"] == "live_turn_failed"
    assert key[:12] not in json.dumps(events)
    assert "abcdefghijklmnopqrstuvwxyz" not in json.dumps(events)
    assert demo.state().transcript == []
    assert demo.state().workflow["verified"] is False
    trace = (tmp_path / "trace/live-task/session_1.jsonl").read_text(encoding="utf-8")
    assert key[:12] not in trace and "abcdefghijklmnopqrstuvwxyz" not in trace
    assert "live_turn_completed" not in trace


def test_live_task_closed_stream_discards_pending_proof_without_committing(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset(session_id="session_1", subject_id="subject_1")
    events = []

    async def incomplete(messages):
        yield "Doğum tarihim 12."
        yield "04.1990"

    async def close_at_delta():
        stream = demo.stream_turn(
            session_id="session_1", subject_id="subject_1",
            user_utterance="Doğum tarihim 12.04.1990", llm=incomplete,
        )
        async for event in stream:
            events.append(event)
            if event["type"] == "text_delta":
                await stream.aclose()
                break

    asyncio.run(close_at_delta())
    assert events[-1]["text"] == ""
    assert demo.state().transcript == []
    assert demo.state().workflow["verified"] is False
    assert demo._identity_proofs == []
    trace = (tmp_path / "trace/live-task/session_1.jsonl").read_text(encoding="utf-8")
    assert "12." not in trace and "live_turn_completed" not in trace


def test_live_task_failing_host_policy_emits_fixed_failure_without_commit(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset(session_id="session_1", subject_id="subject_1")
    key = "request-scoped-live-key-123"

    def broken_redactor(text):
        raise RuntimeError(key)

    async def collect():
        return [event async for event in demo.stream_turn(
            session_id="session_1", subject_id="subject_1", user_utterance="Merhaba",
            secrets=(key,), redactor=broken_redactor,
        )]

    events = asyncio.run(collect())
    assert events[-1]["type"] == "live_turn_failed"
    assert "redaction failed" in events[-1]["data"]["error"]
    assert key not in json.dumps(events)
    assert demo.state().transcript == []
    trace = (tmp_path / "trace/live-task/session_1.jsonl").read_text(encoding="utf-8")
    assert key not in trace and "live_turn_completed" not in trace


def test_live_task_summary_output_policy_failure_prevents_daily_write(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    key = "request-scoped-live-key-123"

    def broken_on_output(text):
        if "token=" in text:
            raise RuntimeError(key)
        return text

    with pytest.raises(RuntimeError, match="redaction failed") as caught:
        demo.record_summary(
            session_id="session_1", subject_id="subject_1", transcript="Merhaba",
            summary_llm=lambda messages: '{"durable_facts": ["token=abcdefghijklmnopqrstuvwxyz"]}',
            secrets=(key,), redactor=broken_on_output,
        )
    assert key not in str(caught.value)
    assert list((tmp_path / "subjects/subject_1/memory").glob("*.md")) == []
    trace = (tmp_path / "trace/live-task/session_1.jsonl").read_text(encoding="utf-8")
    assert key not in trace and "abcdefghijklmnopqrstuvwxyz" not in trace
    assert "session_summary_completed" not in trace


def test_live_task_summary_proof_policy_is_snapshotted_before_model_call(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    proof = "Doğum tarihim 12.04.1990"
    demo._identity_proofs.append(proof)

    def summary(messages):
        assert "12.04.1990" not in json.dumps(messages, ensure_ascii=False)
        demo._identity_proofs.clear()
        return json.dumps({"durable_facts": [proof]}, ensure_ascii=False)

    result = demo.record_summary(
        session_id="session_1", subject_id="subject_1", transcript=proof, summary_llm=summary,
    )
    assert result["wrote"] is True
    assert "12.04.1990" not in json.dumps(result, ensure_ascii=False)
    daily = tmp_path / "subjects/subject_1" / result["path"]
    assert "12.04.1990" not in daily.read_text(encoding="utf-8")


def test_live_task_known_literal_filter_streams_safe_prefix_before_model_finishes(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    key = "request-scoped-live-key-123"
    model_finished = False
    events = []

    async def chunks(messages):
        nonlocal model_finished
        yield "Merhaba. " + key[:12]
        assert events[-1]["type"] == "sentence"
        assert any(event["type"] == "text_delta" and event["text"] == "Merhaba. " for event in events)
        yield key[12:]
        model_finished = True

    async def collect():
        async for event in demo.stream_turn(
            session_id="session_1", subject_id="subject_1", user_utterance="Merhaba",
            llm=chunks, secrets=(key,),
        ):
            assert "elapsed_ms" in event
            if event["type"] == "text_delta" and event["text"] == "Merhaba. ":
                assert model_finished is False
            events.append(event)

    asyncio.run(collect())
    assert key not in "".join(event["text"] for event in events if event["type"] == "text_delta")
    assert events[-1]["type"] == "live_turn_completed"


def test_live_task_scoped_keys_are_never_registered_or_retained(tmp_path: Path):
    from memory_core.secret_registry import get_secret_redaction_registry_revision

    demo = LiveTaskDemo(workspace_dir=tmp_path)
    key = "request-scoped-live-key-123"
    revision = get_secret_redaction_registry_revision()

    async def echo(messages):
        yield messages[-1]["content"]

    async def collect():
        return [event async for event in demo.stream_turn(
            session_id="session_1", subject_id="subject_1",
            user_utterance=f"Doğum tarihim 12.04.1990 {key}", llm=echo, secrets=(key,),
        )]

    asyncio.run(collect())
    assert get_secret_redaction_registry_revision() == revision
    assert key not in repr(vars(demo))
    assert key not in json.dumps(demo.state().transcript)


@pytest.mark.parametrize("failure_target", ["user_text", "state_payload"])
def test_live_task_commit_policy_failure_preserves_previous_state(tmp_path: Path, failure_target):
    demo = LiveTaskDemo(workspace_dir=tmp_path)
    demo.reset(session_id="session_1", subject_id="subject_1")
    preparing_commit = False

    def fail_on_committed_user_text(text):
        trigger = "[kimlik bilgisi gizlendi]" if failure_target == "user_text" else "requested_slot"
        if preparing_commit and text == trigger:
            raise RuntimeError("request-scoped-live-key-123")
        return text

    async def collect():
        nonlocal preparing_commit
        events = []
        async for event in demo.stream_turn(
            session_id="session_1", subject_id="subject_1",
            user_utterance="Doğum tarihim 12.04.1990", redactor=fail_on_committed_user_text,
        ):
            events.append(event)
            if event["type"] == "live_turn_completed":
                preparing_commit = True
        return events

    events = asyncio.run(collect())
    assert demo.state().workflow["verified"] is False
    assert demo.state().transcript == []
    assert demo._identity_proofs == []
    assert events[-1]["type"] == "live_turn_failed"
    assert "redaction failed" in events[-1]["data"]["error"]
    assert "request-scoped-live-key-123" not in json.dumps(events)
    trace = (tmp_path / "trace/live-task/session_1.jsonl").read_text(encoding="utf-8")
    assert json.loads(trace.splitlines()[-1])["type"] == "live_turn_failed"


def test_live_task_proof_redaction_does_not_change_authoritative_routing_ids(tmp_path: Path):
    demo = LiveTaskDemo(workspace_dir=tmp_path)

    async def collect():
        for utterance in ("Müşteri numaram 4821.", "Yarın saat 15:00 uygun olur"):
            async for _ in demo.stream_turn(
                session_id="session_4821", subject_id="subject_4821", user_utterance=utterance,
            ):
                pass

    asyncio.run(collect())
    assert demo._state.session_id == "session_4821"
    assert demo._state.subject_id == "subject_4821"
    assert demo.state().workflow["current_step"] == "confirm_change"
    assert demo.state().workflow["requested_slot"] == "Yarın saat 15:00 uygun olur"


@pytest.mark.parametrize("split", range(len("request-scoped-live-key-123") + 1))
def test_live_task_overlapping_known_literals_are_masked_at_every_split(split):
    from demo.live_privacy import LiteralStreamFilter, LivePrivacyPolicy

    key = "request-scoped-live-key-123"
    policy = LivePrivacyPolicy(secrets=(key[:12], key))
    stream_filter = LiteralStreamFilter(policy)
    first = stream_filter.feed("Merhaba. " + key[:split])
    assert first == ("Merhaba. [redacted]" if split == len(key) else "Merhaba. ")
    text = first + stream_filter.feed(key[split:]) + stream_filter.finish()
    assert text == "Merhaba. [redacted]"


@pytest.mark.parametrize("mode", ["failure", "close"])
def test_live_task_unsuccessful_session_switch_preserves_active_session(tmp_path: Path, mode):
    demo = LiveTaskDemo(workspace_dir=tmp_path)

    async def establish_session():
        async for _ in demo.stream_turn(
            session_id="session_1", subject_id="subject_1",
            user_utterance="Doğum tarihim 12.04.1990",
        ):
            pass

    asyncio.run(establish_session())
    previous_state = demo._state
    previous_transcript = list(demo._transcript)
    previous_proofs = list(demo._identity_proofs)

    async def interrupted(messages):
        yield "Müşteri numaram 4821."
        raise RuntimeError("token=abcdefghijklmnopqrstuvwxyz")

    async def switch_session():
        stream = demo.stream_turn(
            session_id="session_2", subject_id="subject_2",
            user_utterance="Müşteri numaram 4821.", llm=interrupted,
        )
        events = []
        try:
            async for event in stream:
                events.append(event)
                if mode == "close" and event["type"] == "text_delta":
                    await stream.aclose()
                    break
        except RuntimeError:
            assert mode == "failure"
        return events

    events = asyncio.run(switch_session())
    assert all(event["type"] != "live_turn_completed" for event in events)
    assert demo._state == previous_state
    assert demo._transcript == previous_transcript
    assert demo._identity_proofs == previous_proofs
