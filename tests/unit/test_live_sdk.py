from __future__ import annotations

import asyncio
import json
from pathlib import Path

from memory_core.live import (
    IdentityLoadError,
    JsonlTraceSink,
    LIVE_TURN_COMPLETED,
    LIVE_TURN_FAILED,
    LIVE_TURN_STARTED,
    LiveSDKConfig,
    LiveIdentity,
    LiveIdentityStore,
    LiveTurnContext,
    LiveTurnEvent,
    PROVIDER_EVENT,
    SENTENCE,
    SESSION_SUMMARY_COMPLETED,
    SESSION_SUMMARY_FAILED,
    SESSION_SUMMARY_SKIPPED,
    SESSION_SUMMARY_STARTED,
    SubjectMemory,
    TEXT_DELTA,
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


def test_identity_loader_enforces_required_files(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "AGENT.md").write_text("You are a support voice agent.", encoding="utf-8")

    try:
        LiveIdentity.from_dir(identity_dir, required_files=["AGENT.md", "POLICY.md"])
    except IdentityLoadError as exc:
        assert "POLICY.md" in str(exc)
    else:
        raise AssertionError("expected missing required identity file error")


def test_identity_loader_can_reject_unknown_markdown_files(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "AGENT.md").write_text("You are a support voice agent.", encoding="utf-8")
    (identity_dir / "RANDOM.md").write_text("Unexpected.", encoding="utf-8")

    try:
        LiveIdentity.from_dir(identity_dir, unknown_files="error")
    except IdentityLoadError as exc:
        assert "RANDOM.md" in str(exc)
    else:
        raise AssertionError("expected unknown identity file error")


def test_identity_loader_truncates_sections_deterministically(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    (identity_dir / "AGENT.md").write_text("A" * 200, encoding="utf-8")

    identity = LiveIdentity.from_dir(identity_dir, max_chars_per_file=32)

    section = identity.to_prompt_section()
    assert "## Agent Identity" in section
    assert "[truncated]" in section
    assert len(identity.sections[0][1]) <= 32


def test_identity_store_caches_until_reload(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    identity_dir.mkdir()
    path = identity_dir / "AGENT.md"
    path.write_text("First identity.", encoding="utf-8")
    store = LiveIdentityStore(identity_dir)

    first = store.load()
    path.write_text("Second identity.", encoding="utf-8")
    cached = store.load()
    reloaded = store.reload()

    assert first.to_prompt_section() == cached.to_prompt_section()
    assert "First identity." in cached.to_prompt_section()
    assert "Second identity." in reloaded.to_prompt_section()


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


def test_subject_memory_can_use_custom_namespace(tmp_path: Path):
    memory = SubjectMemory.open(
        workspace_dir=tmp_path,
        subject_id="subj_123",
        namespace="accounts",
        reindex=False,
    )

    result = memory.record_session_summary(
        session_id="session_1",
        transcript="User wants evening delivery.",
        summary_llm=lambda messages: "- Subject prefers evening delivery.",
        now_ms=1_788_526_800_000,
        timezone="Europe/Istanbul",
    )

    assert result.wrote is True
    assert (tmp_path / "accounts" / "subj_123" / result.path).exists()


def test_subject_memory_can_use_custom_path_builder(tmp_path: Path):
    memory = SubjectMemory.open(
        workspace_dir=tmp_path,
        subject_id="subj_123",
        subject_path_builder=lambda root, subject_id: root / "tenants" / "default" / subject_id,
        reindex=False,
    )

    result = memory.record_session_summary(
        session_id="session_1",
        transcript="User wants evening delivery.",
        summary_llm=lambda messages: "- Subject prefers evening delivery.",
        now_ms=1_788_526_800_000,
        timezone="Europe/Istanbul",
    )

    assert result.wrote is True
    assert (tmp_path / "tenants" / "default" / "subj_123" / result.path).exists()


def test_record_session_summary_writes_only_durable_structured_entries(tmp_path: Path):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")

    result = memory.record_session_summary(
        session_id="session_1",
        transcript="Transcript with durable preference.",
        summary_llm=lambda messages: json.dumps(
            {
                "durable_facts": ["Subject moved to the premium plan."],
                "preferences": ["Subject prefers evening delivery."],
                "follow_ups": ["Send updated invoice."],
                "admin_review_suggestions": ["Consider changing the global refund policy."],
            }
        ),
        now_ms=1_788_526_800_000,
        timezone="Europe/Istanbul",
        trace_sink=trace_sink,
    )

    memory_text = (
        tmp_path / "subjects" / "subj_123" / "memory" / "2026-09-04.md"
    ).read_text(encoding="utf-8")
    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result.wrote is True
    assert result.path == "memory/2026-09-04.md"
    assert result.durable_facts == ("Subject moved to the premium plan.",)
    assert result.preferences == ("Subject prefers evening delivery.",)
    assert result.follow_ups == ("Send updated invoice.",)
    assert result.admin_review_suggestions == ("Consider changing the global refund policy.",)
    assert "Subject moved to the premium plan." in memory_text
    assert "Subject prefers evening delivery." in memory_text
    assert "Send updated invoice." in memory_text
    assert "global refund policy" not in memory_text
    assert [record["type"] for record in records] == [
        SESSION_SUMMARY_STARTED,
        SESSION_SUMMARY_COMPLETED,
    ]
    assert records[-1]["data"]["admin_review_suggestions"] == [
        "Consider changing the global refund policy."
    ]


def test_record_session_summary_traces_skip_when_only_admin_suggestions(tmp_path: Path):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")

    result = memory.record_session_summary(
        session_id="session_1",
        transcript="Transcript with policy idea only.",
        summary_llm=lambda messages: json.dumps(
            {"admin_review_suggestions": ["Tighten escalation policy."]}
        ),
        trace_sink=trace_sink,
    )

    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result.wrote is False
    assert result.admin_review_suggestions == ("Tighten escalation policy.",)
    assert not list((tmp_path / "subjects" / "subj_123" / "memory").glob("*.md"))
    assert [record["type"] for record in records] == [
        SESSION_SUMMARY_STARTED,
        SESSION_SUMMARY_SKIPPED,
    ]


def test_record_session_summary_traces_failure_before_reraising(tmp_path: Path):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")

    def failing_summary(messages):
        raise RuntimeError("summary provider down")

    try:
        memory.record_session_summary(
            session_id="session_1",
            transcript="Transcript.",
            summary_llm=failing_summary,
            trace_sink=trace_sink,
        )
    except RuntimeError as exc:
        assert "summary provider down" in str(exc)
    else:
        raise AssertionError("expected summary failure to be re-raised")

    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["type"] == SESSION_SUMMARY_FAILED
    assert records[-1]["data"]["error"] == "summary provider down"


def test_async_record_session_summary_accepts_awaitable_summary_llm(tmp_path: Path):
    async def async_summary(messages):
        return json.dumps({"preferences": ["Subject prefers SMS updates."]})

    async def run_summary():
        memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
        trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")
        return await memory.async_record_session_summary(
            session_id="session_1",
            transcript="Subject asks for SMS updates.",
            summary_llm=async_summary,
            trace_sink=trace_sink,
        )

    result = asyncio.run(run_summary())
    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert result.wrote is True
    assert result.preferences == ("Subject prefers SMS updates.",)
    assert records[-1]["type"] == SESSION_SUMMARY_COMPLETED


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


def test_stream_live_turn_writes_append_only_trace_events(tmp_path: Path):
    async def llm_stream(messages):
        for chunk in ["Tamam."]:
            yield chunk

    async def collect_events() -> list[LiveTurnEvent]:
        memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
        trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")
        events: list[LiveTurnEvent] = []
        async for event in memory.stream_live_turn(
            LiveTurnContext(
                subject_id="subj_123",
                session_id="session_1",
                user_utterance="Selam.",
                workflow_state={"workflow_id": "greeting"},
            ),
            llm=llm_stream,
            trace_sink=trace_sink,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())
    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert [record["type"] for record in records] == [event.type for event in events]
    assert records[0]["data"] == {"subject_id": "subj_123", "session_id": "session_1"}
    assert records[-1]["data"]["assistant_text"] == "Tamam."


def test_live_event_type_constants_are_exported():
    assert LIVE_TURN_STARTED == "live_turn_started"
    assert TEXT_DELTA == "text_delta"
    assert PROVIDER_EVENT == "provider_event"
    assert SENTENCE == "sentence"
    assert LIVE_TURN_COMPLETED == "live_turn_completed"
    assert LIVE_TURN_FAILED == "live_turn_failed"
    assert SESSION_SUMMARY_STARTED == "session_summary_started"
    assert SESSION_SUMMARY_COMPLETED == "session_summary_completed"
    assert SESSION_SUMMARY_SKIPPED == "session_summary_skipped"
    assert SESSION_SUMMARY_FAILED == "session_summary_failed"


def test_stream_live_turn_traces_failure_before_reraising(tmp_path: Path):
    async def failing_stream(messages):
        yield "Basladim. "
        raise RuntimeError("provider disconnected")

    async def collect_until_failure() -> None:
        memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
        trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")
        async for _event in memory.stream_live_turn(
            LiveTurnContext(
                subject_id="subj_123",
                session_id="session_1",
                user_utterance="Selam.",
            ),
            llm=failing_stream,
            trace_sink=trace_sink,
        ):
            pass

    try:
        asyncio.run(collect_until_failure())
    except RuntimeError as exc:
        assert "provider disconnected" in str(exc)
    else:
        raise AssertionError("expected stream failure to be re-raised")

    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["type"] == LIVE_TURN_FAILED
    assert records[-1]["data"] == {
        "error_type": "RuntimeError",
        "error": "provider disconnected",
        "assistant_text": "Basladim.",
    }


def test_stream_live_turn_passes_through_provider_events(tmp_path: Path):
    async def provider_stream(messages):
        yield {"type": "tool_call", "name": "lookup_order", "arguments": {"id": "ord_1"}}
        yield {"delta": "Siparisinizi kontrol ediyorum."}

    async def collect_events() -> list[LiveTurnEvent]:
        memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
        trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")
        events: list[LiveTurnEvent] = []
        async for event in memory.stream_live_turn(
            LiveTurnContext(
                subject_id="subj_123",
                session_id="session_1",
                user_utterance="Siparisim nerede?",
            ),
            llm=provider_stream,
            trace_sink=trace_sink,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())
    provider_events = [event for event in events if event.type == PROVIDER_EVENT]
    records = [
        json.loads(line)
        for line in (tmp_path / "trace" / "session_1.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert provider_events == [
        LiveTurnEvent(
            PROVIDER_EVENT,
            data={"type": "tool_call", "name": "lookup_order", "arguments": {"id": "ord_1"}},
        )
    ]
    assert any(event.type == TEXT_DELTA for event in events)
    assert any(record["type"] == PROVIDER_EVENT for record in records)


def test_stream_live_turn_accepts_sdk_config_defaults(tmp_path: Path):
    async def llm_stream(messages):
        assert "BEGIN_OPENCLAW_INTERNAL_CONTEXT" in messages[0]["content"]
        yield "Tamam."

    async def collect_events() -> list[LiveTurnEvent]:
        memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
        trace_sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl")
        config = LiveSDKConfig(openclaw_compatible=True, trace_sink=trace_sink)
        events: list[LiveTurnEvent] = []
        async for event in memory.stream_live_turn(
            LiveTurnContext(
                subject_id="subj_123",
                session_id="session_1",
                user_utterance="Selam.",
            ),
            llm=llm_stream,
            config=config,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    assert events[-1].type == LIVE_TURN_COMPLETED
    assert (tmp_path / "trace" / "session_1.jsonl").exists()
