"""Optional live SDK privacy boundaries; all storage and models are scratch/scripted."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from memory_core.live import (
    JsonlTraceSink, LiveTurnContext, LiveTurnEvent, SubjectMemory,
    PROVIDER_EVENT, SESSION_SUMMARY_COMPLETED, TEXT_DELTA,
)
from memory_core.redact import redact_secrets, redact_sensitive_text

# Existing fixtures from test_redact.py and test_live_task_demo.py, never live data.
LONG = "abcdefghijklmnopqrstuvwxyz0123456789"
PROOF = "Doğum tarihim 12.04.1990"
NOW_MS = 1_788_526_800_000


def _redact(text: str) -> str:
    return redact_sensitive_text(text.replace(PROOF, "[redacted]"))


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_trace_payload_redactor_gets_a_copy_and_preserves_structure(tmp_path: Path):
    data = {"nested": [{"password": "short"}], "runtime_context": PROOF, "count": 2}
    event = LiveTurnEvent(PROVIDER_EVENT, text=f"token={LONG}", data=data)

    def sanitize(payload):
        payload["data"]["runtime_context"] = "[redacted]"
        payload["data"]["nested"].append({"ok": True})
        return redact_secrets(payload)

    sink = JsonlTraceSink(tmp_path / "trace" / "session_1.jsonl", payload_redactor=sanitize)
    sink.record(event)

    (record,) = _records(sink.path)
    assert LONG not in json.dumps(record) and PROOF not in json.dumps(record)
    assert record["data"] == {
        "nested": [{"password": "***"}, {"ok": True}],
        "runtime_context": "[redacted]", "count": 2,
    }
    assert event.text == f"token={LONG}"
    assert data == {"nested": [{"password": "short"}], "runtime_context": PROOF, "count": 2}


def test_trace_for_session_forwards_policy_and_keeps_append_order(tmp_path: Path):
    sink = JsonlTraceSink.for_session(tmp_path, "session_1", payload_redactor=redact_secrets)
    for event in (LiveTurnEvent(TEXT_DELTA, text=f"token={LONG}"), LiveTurnEvent(TEXT_DELTA, "OK.")):
        sink.record(event)
    records = _records(sink.path)
    assert [row["type"] for row in records] == [TEXT_DELTA, TEXT_DELTA]
    assert records[0]["text"] != f"token={LONG}" and records[1]["text"] == "OK."


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("invalid_result", [False, True])
def test_trace_redaction_failure_never_appends_raw_data(tmp_path: Path, existing, invalid_result):
    path = tmp_path / "trace" / "session_1.jsonl"
    if existing:
        JsonlTraceSink(path).record(LiveTurnEvent(TEXT_DELTA, "OK."))
    before = path.read_bytes() if existing else None

    def broken(payload):
        if invalid_result:
            return None
        raise RuntimeError("redactor failed")

    sink = JsonlTraceSink(path, payload_redactor=broken)
    with pytest.raises(TypeError if invalid_result else RuntimeError,
                       match="payload_redactor must return dict" if invalid_result else "redactor failed"):
        sink.record(LiveTurnEvent(TEXT_DELTA, f"token={LONG}"))
    assert (path.read_bytes() if path.exists() else None) == before
    if not existing:
        assert not path.parent.exists()


def test_stream_redacts_only_the_trace_copy(tmp_path: Path):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    path = tmp_path / "trace" / "session_1.jsonl"
    context = LiveTurnContext(
        subject_id="subj_123", session_id="session_1", user_utterance="Merhaba",
        host_context={"token": LONG},
    )
    model_inputs = []

    async def llm(messages):
        model_inputs.extend(messages)
        yield {"type": "llm", "password": "short"}
        yield f"token={LONG}"

    async def run():
        return [event async for event in memory.stream_live_turn(
            context, llm=llm, trace_sink=JsonlTraceSink(path, payload_redactor=redact_secrets),
        )]

    events = asyncio.run(run())
    assert LONG in json.dumps(model_inputs)
    assert any(event.text == f"token={LONG}" for event in events)
    assert LONG not in path.read_text()
    assert [row["type"] for row in _records(path)] == [event.type for event in events]


def test_trace_serialization_failure_precedes_filesystem_operations(tmp_path: Path):
    path = tmp_path / "trace" / "session_1.jsonl"
    sink = JsonlTraceSink(path, payload_redactor=lambda _payload: {"data": object()})
    with pytest.raises(TypeError, match="not JSON serializable"):
        sink.record(LiveTurnEvent(TEXT_DELTA, f"token={LONG}"))
    assert not path.parent.exists()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("shape", ["json", "bullets"])
def test_summary_output_policy_precedes_write_and_result(tmp_path: Path, asynchronous, shape):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    reply = (json.dumps({"durable_facts": [PROOF], "preferences": [f"token={LONG}"],
                         "follow_ups": ["Send updated invoice."]})
             if shape == "json" else f"- {PROOF}\n- token={LONG}")
    path = tmp_path / "trace" / "session_1.jsonl"
    options = dict(session_id="session_1", transcript=PROOF, now_ms=NOW_MS,
                   timezone="Europe/Istanbul", output_redactor=_redact,
                   trace_sink=JsonlTraceSink(path, payload_redactor=redact_secrets))
    seen = []

    def summary(messages):
        seen.extend(messages)
        return reply

    async def async_summary(messages):
        return summary(messages)

    result = (asyncio.run(memory.async_record_session_summary(**options, summary_llm=async_summary))
              if asynchronous else memory.record_session_summary(**options, summary_llm=summary))

    assert PROOF in json.dumps(seen, ensure_ascii=False)  # Input policy is independent.
    assert result.wrote and result.skip_reason is None
    assert PROOF not in result.text and LONG not in result.text
    assert PROOF not in result.raw_text and LONG not in result.raw_text
    daily = memory.memory.workspace.root / result.path
    assert daily.read_text().strip() == result.text
    assert PROOF not in path.read_text() and LONG not in path.read_text()
    assert _records(path)[-1]["type"] == SESSION_SUMMARY_COMPLETED
    if shape == "json":
        assert result.durable_facts == ("[redacted]",)
        assert result.follow_ups == ("Send updated invoice.",)


@pytest.mark.parametrize("reply,reason", [
    ("NO_REPLY", "silent"), (PROOF, "unstructured"), ("", "empty"),
])
def test_summary_output_policy_preserves_skip_reasons(tmp_path: Path, reply, reason):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    result = memory.record_session_summary(
        session_id="session_1", transcript="Transcript.", summary_llm=lambda _m: reply,
        output_redactor=_redact,
    )
    assert not result.wrote and result.skip_reason == reason
    assert PROOF not in result.raw_text


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("invalid_result", [False, True])
def test_summary_output_policy_failure_prevents_durable_write(tmp_path: Path, asynchronous, invalid_result):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)

    def broken(text):
        if invalid_result:
            return None
        raise RuntimeError("redactor failed")

    options = dict(session_id="session_1", transcript="Transcript.", now_ms=NOW_MS,
                   summary_llm=lambda _m: f"- {PROOF}", output_redactor=broken)
    with pytest.raises(TypeError if invalid_result else RuntimeError,
                       match="output_redactor must return str" if invalid_result else "redactor failed"):
        if asynchronous:
            asyncio.run(memory.async_record_session_summary(**options))
        else:
            memory.record_session_summary(**options)
    assert not list(memory.memory.workspace.root.glob("memory/*.md"))


@pytest.mark.parametrize("shape", ["json", "bullets"])
def test_summary_output_policy_can_remove_every_fact(tmp_path: Path, shape):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    result = memory.record_session_summary(
        session_id="session_1", transcript="Transcript.",
        summary_llm=lambda _m: (json.dumps({"durable_facts": [PROOF]}) if shape == "json" else f"- {PROOF}"),
        output_redactor=lambda _text: "",
    )
    assert not result.wrote and result.skip_reason == "empty" and result.text == ""


def test_existing_summary_redactor_remains_input_only(tmp_path: Path):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    seen = []
    reply = f"- {PROOF}"

    def summary(messages):
        seen.extend(messages)
        return reply

    result = memory.record_session_summary(
        session_id="session_1", transcript=PROOF, summary_llm=summary,
        redactor=lambda _text: "Transcript removed.",
    )
    assert PROOF not in json.dumps(seen, ensure_ascii=False)
    assert "Transcript removed." in seen[-1]["content"]
    assert result.wrote and result.text == reply and result.raw_text == reply


@pytest.mark.parametrize("asynchronous", [False, True])
def test_raw_summary_policy_failure_also_prevents_durable_write(tmp_path: Path, asynchronous):
    memory = SubjectMemory.open(workspace_dir=tmp_path, subject_id="subj_123", reindex=False)
    reply = json.dumps({"durable_facts": ["Subject prefers SMS."]})
    sanitized = []

    def policy(text):
        sanitized.append(text)
        if text == reply:
            raise RuntimeError("raw reply policy failed")
        return text

    options = dict(session_id="session_1", transcript="Transcript.", now_ms=NOW_MS,
                   summary_llm=lambda _m: reply, output_redactor=policy)
    with pytest.raises(RuntimeError, match="raw reply policy failed"):
        if asynchronous:
            asyncio.run(memory.async_record_session_summary(**options))
        else:
            memory.record_session_summary(**options)
    assert sanitized == ["Subject prefers SMS.", reply]
    assert not list(memory.memory.workspace.root.glob("memory/*.md"))
