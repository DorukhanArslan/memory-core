"""Guarded persistence bounds details and preserves actual live output policy."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from memory_core import redact, secret_registry
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.tool_result_persistence import (
    BoundedJsonBytes, bounded_json_utf8_bytes, cap_tool_result_for_persistence,
    normalize_persisted_tool_result_name, redact_persisted_detail_string, sanitize_tool_result_details_for_persistence,
)
from memory_core.turn_tool_dispatch import TurnTool


@pytest.fixture(autouse=True)
def clean_policy():
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)
    yield
    secret_registry.reset_secret_redaction_registry()
    redact.configure_logging_redaction(None)


@pytest.mark.parametrize("value,limit,expected", [
    ("abc", 5, BoundedJsonBytes(5, True)), ("abc", 4, BoundedJsonBytes(5, False)),
    ({"log": '"' * 5000}, 8192, BoundedJsonBytes(10009, False)),
    ({"value": "😀" * 3000}, 8192, BoundedJsonBytes(8193, False)),
    ([0] * 4096, 8192, BoundedJsonBytes(8193, False)),
])
def test_early_exit_json_count_retains_actual_byte_lower_bound(value, limit, expected):
    assert bounded_json_utf8_bytes(value, limit) == expected


def test_cycles_stop_at_the_bounded_json_owner_and_details_depth_limit():
    value = {}
    value["self"] = value
    assert bounded_json_utf8_bytes(value, 8192) == BoundedJsonBytes(8193, False)
    actual = sanitize_tool_result_details_for_persistence(value)
    assert actual["persistedDetailsTruncated"] is True
    assert actual["originalDetailsBytesAtLeast"] == 8193
    assert actual["originalDetailKeys"] == ["self"]


def test_sensitive_container_key_keeps_inherited_protection_and_source_unmodified():
    value = {"token": {"nested": [7, False, None, "fixture-secret"]}, "ordinary": {"plain": 7}}
    before = deepcopy(value)
    assert sanitize_tool_result_details_for_persistence(value) == {
        "token": {"nested": ["***", "***", None, "***"]}, "ordinary": {"plain": 7},
    }
    assert value == before


def test_changed_details_match_original_object_assignment_for_a_json_prototype_key():
    value = json.loads('{"__proto__":"literal","password":"fixture-secret"}')
    assert sanitize_tool_result_details_for_persistence(value) == {"password": "***"}
    assert value == {"__proto__": "literal", "password": "fixture-secret"}
    unchanged = json.loads('{"__proto__":"literal","ordinary":"complete"}')
    assert sanitize_tool_result_details_for_persistence(unchanged) is unchanged


def test_large_details_keep_bounded_status_and_first_ten_session_summaries():
    value = {"log": "large unneeded metadata " * 1000, "status": "completed", "success": False,
             "sessions": [{"sessionId": f"session-{i}", "command": "echo done", "private": "drop"} for i in range(12)]}
    actual = sanitize_tool_result_details_for_persistence(value)
    assert actual["persistedDetailsTruncated"] is True
    assert actual["originalDetailsBytesAtLeast"] == 8193
    assert actual["status"] == "completed" and actual["success"] is False
    assert actual["sessionsTruncated"] == 2 and len(actual["sessions"]) == 10
    assert actual["sessions"][0] == {"sessionId": "session-0", "command": "echo done"}
    assert "large unneeded metadata" not in json.dumps(actual)


def test_expanding_custom_rule_cannot_escape_final_details_byte_cap():
    value = {"status": "x" * 1000}
    config = redact.LoggingConfig(("x",))
    actual = sanitize_tool_result_details_for_persistence(value, config)
    assert actual == {"status": "***" * 1000}
    # More expansions cross the original cap after redaction and select its fallback owner.
    value = {"status": "x" * 3000}
    actual = sanitize_tool_result_details_for_persistence(value, config)
    assert actual["persistedDetailsTruncated"] and actual["finalDetailsTruncated"]
    assert actual["sanitizedDetailsBytes"] > 8192
    assert len(json.dumps(actual).encode()) <= 8192


def test_redaction_scan_drops_boundary_overlap_instead_of_retaining_partial_credentials():
    text = "a" * 1470 + " token=" + "z" * 2000
    actual = redact_persisted_detail_string(text)
    assert "z" * 100 not in actual
    assert "[OpenClaw persisted detail redacted: boundary overlap omitted]" in actual
    assert "[OpenClaw persisted detail truncated: 1477 original chars omitted]" in actual


def test_detail_state_uses_javascript_truthiness_for_nonstring_errors():
    value = {"error": [], "disabled": False, "success": 1, "log": "x" * 9000}
    actual = sanitize_tool_result_details_for_persistence(value)
    assert actual["error"] is True and actual["disabled"] is False and "success" not in actual


def test_cap_preserves_unchanged_content_but_applies_diagnostic_detail_policy():
    block = {"type": "text", "text": "Source api_key=fixture-value"}
    message = {"role": "toolResult", "content": [block], "details": {"log": "api_key=fixture-value"}}
    actual = cap_tool_result_for_persistence(message)
    assert actual["content"] is message["content"] and actual["content"][0] is block
    assert actual["details"] == {"log": "api_key=***"}
    assert message["details"]["log"] == "api_key=fixture-value"


def test_guard_normalizes_tool_identity_before_caps_without_mutating_the_live_result(tmp_path):
    from memory_core.tool_result_persistence import settle_session_tool_result

    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: 1000)
    catalog.upsert_session("agent:main:dm:session-1", {"sessionId": "session-1", "updatedAt": 1000})
    message = {"role": "toolResult", "toolCallId": "direct-call", "toolName": " lookup ",
               "content": [{"type": "text", "text": "plain"}], "timestamp": 1000}
    settled = settle_session_tool_result(catalog, "session-1", message, session_key="agent:main:dm:session-1", now_ms=1000)
    assert settled.append_result["message"] == {**message, "toolName": "lookup", "isError": False}
    assert message["toolName"] == " lookup " and "isError" not in message
    assert normalize_persisted_tool_result_name({"role": "toolResult", "content": []}, " fallback ", " call ") == {
        "role": "toolResult", "content": [], "toolName": "fallback", "toolCallId": "call", "isError": False,
    }


def test_real_dispatcher_example_runs_guard_stages_in_source_order_and_reopens(tmp_path: Path):
    from examples.session_tool_result import dispatch_and_persist

    calls = []

    def actual_source(call_id, arguments):
        calls.append((call_id, arguments))
        return {"content": [{"type": "text", "text": "foo"}], "details": {"token": "fixture-secret"}}

    output = dispatch_and_persist(tmp_path, TurnTool("lookup", actual_source, "network"),
        {"id": "call-1", "name": "lookup", "arguments": {"query": "request"}},
        session_id="session-1", session_key="agent:main:dm:session-1", turn_id="turn-1", now_ms=1000,
        logging_config=redact.LoggingConfig((r"foo|\*",)))

    assert calls == [("call-1", {"query": "request"})]
    assert [stage["stage"] for stage in output["stages"]] == [
        "before-live-listeners", "after-live-listeners", "first-persistence-cap",
        "before-message-write-policy", "final-persistence-cap", "committed-message", "after-write-settlement",
    ]
    assert [stage["message"]["details"]["token"] for stage in output["stages"]] == [
        "fixture-secret", "fixture-secret", "***", "*********", "*" * 27, "*" * 81, "fixture-secret",
    ]
    assert output["liveMessage"]["content"][0]["text"] == "***"
    assert output["liveMessage"]["details"]["token"] == "fixture-secret"
    assert output["trust"]["tainted"] is True
    assert output["toolOutcomes"][0]["result"]["details"]["token"] == "fixture-secret"
    reopened = MemorySessionCatalog(Path(output["catalogPath"])).read_transcript("session-1")
    assert reopened.events[-1]["message"] == output["appendResult"]["message"]
    assert reopened.events[-1]["message"]["details"]["token"] == "*" * 81


def test_host_example_retains_one_turn_trust_across_network_and_local_results(tmp_path):
    from examples.session_tool_result import HostToolSession

    session = HostToolSession(tmp_path, session_id="session-1", session_key="agent:main:dm:session-1", now_ms=1000)
    session.begin_turn("turn-1", sender_is_owner=True)
    session.append_message({"role": "user", "content": "start", "timestamp": 1000}, now_ms=1000)
    def source(_call_id, _arguments):
        return {"content": [{"type": "text", "text": "complete"}]}
    first = session.dispatch(TurnTool("remote", source, "network"),
        {"id": "call-1", "name": "remote", "arguments": {}}, now_ms=1000)
    session.begin_turn("turn-1", sender_is_owner=True)
    second = session.dispatch(TurnTool("local", source),
        {"id": "call-2", "name": "local", "arguments": {}}, now_ms=1000)
    assert first["trust"]["tainted"] and second["trust"]["tainted"]
    persisted = session.append_message({"role": "assistant", "content": [], "timestamp": 1000}, now_ms=1000)
    assert persisted["__openclaw"]["turnTainted"] is True


def test_reopening_the_host_example_keeps_existing_metadata_and_committed_context(tmp_path):
    from examples.session_tool_result import HostToolSession

    key = "agent:main:dm:session-1"
    catalog = MemorySessionCatalog(tmp_path / "session-catalog.sqlite", clock_ms=lambda: 1000)
    catalog.upsert_session(key, {"sessionId": "session-1", "updatedAt": 1000, "displayName": "Existing conversation"})
    catalog.append_message("session-1", {"role": "user", "content": "saved", "timestamp": 1000}, session_key=key, now_ms=1000)
    before = catalog.get_session_entry(key)
    session = HostToolSession(tmp_path, session_id="session-1", session_key=key, now_ms=2000)
    assert catalog.get_session_entry(key) == before
    assert session.model_messages() == [{"role": "user", "content": "saved", "timestamp": 1000}]
