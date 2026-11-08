"""Literal input integrity. Actual independent owner evidence establishes parity."""
from copy import deepcopy
import json

from equivalence.durable_session_fixtures import build_durable_session_cases


def test_durable_inputs_are_fresh_deterministic_json_and_uncredited():
    cases = build_durable_session_cases()
    assert len(cases) == 2
    assert cases == build_durable_session_cases()
    assert len({case["id"] for case in cases}) == 2
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert all(case["covers"] == [] and case["requirement"] == "sessions.durable-context"
               and case["operation"] == "durable-session-runtime" for case in cases)
    mutated = deepcopy(cases)
    mutated[0]["input"]["phases"][0]["sessions"].clear()
    assert build_durable_session_cases() == cases


def test_each_request_has_exactly_three_phases_and_no_injected_prior_outputs():
    for case in build_durable_session_cases():
        value = case["input"]
        assert value["kind"] == "durable"
        assert [phase["label"] for phase in value["phases"]] == ["write", "continue", "verify"]
        assert [phase["nowMs"] for phase in value["phases"]] == sorted(phase["nowMs"] for phase in value["phases"])
        verify = value["phases"][2]
        assert not verify.get("sessions") and not verify.get("appendMessages")
        assert all("expected" not in json.dumps(phase).lower() for phase in value["phases"])
        assert all("history" not in phase and "context" not in phase and "messages" not in phase
                   for phase in value["phases"])
        assert all(phase["queries"] and phase["anchorEntryId"] for phase in value["phases"])
        for phase in value["phases"]:
            for append in phase.get("appendMessages", []):
                assert append["eventId"] and append["cwd"] == "/fixture/workspace"
                assert isinstance(append["message"], dict)


def test_durable_profile_replays_and_continues_full_owned_tool_records_after_rollover():
    value = build_durable_session_cases()[0]["input"]
    write, continued, verified = value["phases"]
    prior, current = write["sessions"]
    assert prior["sessionKey"] == current["sessionKey"] == value["sessionKey"]
    assert current["entry"]["previousSessionId"] == prior["entry"]["sessionId"]
    assert prior["events"] and "events" not in current
    assert current["participants"][0]["identity"] == {"type": "profile", "id": "alice"}
    messages = [item["message"] for item in write["appendMessages"]]
    assert [message["role"] for message in messages] == ["user", "assistant", "toolResult", "assistant"]
    call = messages[1]["content"][0]
    assert call["type"] == "toolCall" and call["id"] == messages[2]["toolCallId"]
    assert messages[1]["usage"] and messages[2]["details"] and messages[3]["usage"]
    replay, conflict = [item["message"] for item in continued["appendMessages"][:2]]
    assert replay["idempotencyKey"] == conflict["idempotencyKey"] == messages[0]["idempotencyKey"]
    assert replay["content"] == messages[0]["content"] != conflict["content"]
    assert continued["anchorEntryId"] == verified["anchorEntryId"]
    assert current["entry"]["memoryFlush"]["kind"] == "failed"
    assert continued["sessions"][0]["entry"]["memoryFlush"]["kind"] == "succeeded"


def test_reset_private_profile_supplies_facts_but_no_context_or_visibility_answer():
    write, continued, verified = build_durable_session_cases()[1]["input"]["phases"]
    ordinary, private = write["sessions"]
    types = {event["type"] for event in ordinary["events"]}
    assert {"thinking_level_change", "model_change", "reset", "compaction"} <= types
    assert "incognito-" in private["sessionKey"] and private["events"][1]["message"]["content"]
    assert write["identityReads"] == continued["identityReads"] == verified["identityReads"]
    assert all(seed["sessionKey"] != private["sessionKey"] for seed in continued["sessions"])
    assert not verified.get("sessions")
    assert all("visible" not in seed and "admitted" not in seed for seed in write["sessions"])
