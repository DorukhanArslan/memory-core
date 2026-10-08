"""Offline Lab diagnostic privacy at the tool, event and model-feedback boundaries."""

from __future__ import annotations

import json

import pytest

from demo import lab_runtime
from demo.lab_tools import LabToolbox, ToolLoopOutcome, run_tool_loop
from memory_core.host import FlushRequest, HostKit
from memory_core.secret_registry import (
    capture_secret_redaction_registry_snapshot,
    encode_uri_component,
    json_string_content,
)
from test_demo_app import (
    HEARTBEAT_HEADER,
    StubEngine,
    _no_provider_env as _no_provider_env,
    client as client,
    frames_of,
    lab as lab,
    parse_sse,
    put_scratch,
    tool_call,
    use_engine,
)

KEY = "request-scoped-live-key-123"
LONG = "a1B2c3D4e5F6g7H8i9J0kLmNoPqRsTuVwXyZ"
ENCODED = 'a b"c\\d é 😀 secret'
FAILURE = f"provider refused {KEY}; token={LONG}"


def assert_private(value):
    text = json.dumps(value, ensure_ascii=False)
    assert KEY not in text
    assert LONG not in text
    assert "[redacted]" in text
    assert "token=" in text and ("…" in text or "token=***" in text)


def test_shared_diagnostics_compose_builtin_and_scoped_exact_redaction():
    before = capture_secret_redaction_registry_snapshot()
    forms = (ENCODED, encode_uri_component(ENCODED), json_string_content(ENCODED))
    message = f"{FAILURE}; {' | '.join(forms)}; secret-longer secret"

    result = lab_runtime.safe_exception_message(
        RuntimeError(message), (KEY, ENCODED, "secret", "secret-longer")
    )

    assert_private(result)
    assert result.startswith("RuntimeError: provider refused [redacted]")
    assert all(form not in result for form in forms)
    assert result.endswith("[redacted] [redacted]")
    assert "-longer" not in result
    assert capture_secret_redaction_registry_snapshot() == before
    assert lab_runtime.safe_exception_message(ValueError("invalid JSON")) == "ValueError: invalid JSON"


def test_payload_redaction_preserves_control_fields_and_masks_diagnostics():
    payload = {"code": "provider_unreachable", "status": 503, "cause": {"code": "ECONNREFUSED"},
               "error": FAILURE, "usage": {"promptTokens": 1000}}

    result = lab_runtime.redact_payload(payload, (KEY,))

    assert_private(result)
    assert result["code"] == "provider_unreachable" and result["status"] == 503
    assert result["cause"] == {"code": "ECONNREFUSED"}
    assert result["usage"] == {"promptTokens": 1000}
    assert payload["error"] == FAILURE


def test_diagnostic_sanitizer_failure_does_not_format_or_return_sensitive_exception(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError(KEY)

    monkeypatch.setattr(lab_runtime, "redact_tool_payload_text", fail, raising=False)

    assert lab_runtime.safe_exception_message(RuntimeError(FAILURE), (KEY,)) == "error details unavailable"
    assert lab_runtime.redact_secrets(FAILURE, (KEY,)) == "error details unavailable"


def test_unprintable_exception_fails_closed():
    class UnprintableError(RuntimeError):
        def __str__(self):
            raise RuntimeError(KEY)

    assert lab_runtime.safe_exception_message(UnprintableError(), (KEY,)) == "error details unavailable"


@pytest.mark.parametrize("operation", ["chat", "heartbeat", "flush"])
@pytest.mark.parametrize("key_source", ["request", "env"])
def test_dispatch_exception_is_private_in_response_saved_calls_bus_and_model(
    client, lab, monkeypatch, operation, key_source
):
    name = "write" if operation == "flush" else "memory_get"
    engine = use_engine(monkeypatch, StubEngine([
        ("", [tool_call("c1", name, {})]), ("NO_REPLY", []),
    ]))

    def fail(*args, **kwargs):
        raise RuntimeError(FAILURE)

    monkeypatch.setattr(FlushRequest if operation == "flush" else HostKit, "dispatch", fail)
    payload = {"openai": {"apiKey": KEY}} if key_source == "request" else {}
    if key_source == "env":
        monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", KEY)
    if operation == "chat":
        response = client.post("/api/lab/chat/stream", json={"message": "Merhaba", **payload})
        frames = parse_sse(response.text)
        detail = frames_of(frames, "turn_done")[0]["detail"]
        saved = client.get(f"/api/lab/turns/{detail['id']}").json()
    elif operation == "heartbeat":
        put_scratch(client, HEARTBEAT_HEADER)
        response = client.post("/api/lab/heartbeat/run", json=payload)
        saved = lab.heartbeat_runs
    else:
        response = client.post("/api/chat/flush", json={"forced": True, **payload})
        saved = response.json()["flush"]["toolCalls"]

    assert response.status_code == 200
    assert_private(response.text)
    assert_private(saved)
    assert_private(engine.calls[1]["messages"][-1])
    events = client.get("/api/lab/events", params={"once": "true"}).text
    assert KEY not in events and LONG not in events


@pytest.mark.parametrize("name,result,event_type", [
    ("memory_search", {"disabled": True, "unavailable": True, "results": [],
                       "error": FAILURE, "warning": FAILURE, "action": FAILURE}, "search.unavailable"),
    ("upsert_user_directive", {"status": "error", "error": FAILURE,
                              "code": "invalid_arguments", "cause": {"code": "ECONNREFUSED"}},
     "curation.refused"),
])
def test_returned_diagnostics_are_private_before_tool_records_events_and_feedback(
    lab, monkeypatch, name, result, event_type
):
    lab.ensure()
    kit = lab.kit(lab.store(lab.resolve_embedding({}), mode="text"))
    monkeypatch.setattr(HostKit, "dispatch", lambda *args, **kwargs: result)
    toolbox = LabToolbox(lab, kit, lab.session("main"), None, secrets=(KEY,))
    outcome = ToolLoopOutcome()
    engine = StubEngine([("", [tool_call("c1", name, {"query": "note"})]), ("done", [])])

    events = list(run_tool_loop(engine, [], toolbox, outcome, secrets=(KEY,)))

    assert_private(events)
    assert_private(toolbox.calls)
    assert_private(engine.calls[1]["messages"][-1])
    event = next(event for event in lab.bus.recent() if event["type"] == event_type)
    assert_private(event)
    assert result["error"] == FAILURE
    if name == "upsert_user_directive":
        assert toolbox.calls[0]["result"]["code"] == "invalid_arguments"
        assert toolbox.calls[0]["result"]["cause"] == {"code": "ECONNREFUSED"}


def test_successful_tool_content_is_unchanged(lab):
    lab.ensure()
    store = lab.store(lab.resolve_embedding({}), mode="text")
    lab.reindex(store)
    kit = lab.kit(store)
    toolbox = LabToolbox(lab, kit, lab.session("main"), None, secrets=(KEY,))

    record = toolbox.dispatch("c1", "memory_search", '{"query":"note"}')

    assert record["result"] == {"results": [], "provider": "none", "model": "fts-only", "citations": "on"}


@pytest.mark.parametrize("result", [
    {"status": "error", "tool": "write", "error": FAILURE, "code": "write_failed"},
    {"status": "ok", "tool": "write", "action": "appended", "afterWriteError": FAILURE},
])
def test_returned_flush_diagnostic_is_private_before_calls_and_model_feedback(
    client, lab, monkeypatch, result
):
    engine = use_engine(monkeypatch, StubEngine([
        ("", [tool_call("f1", "write", {})]), ("NO_REPLY", []),
    ]))
    monkeypatch.setattr(FlushRequest, "dispatch", lambda *args, **kwargs: result)

    response = client.post("/api/chat/flush", json={"forced": True, "openai": {"apiKey": KEY}})

    assert response.status_code == 200
    assert_private(response.text)
    assert_private(response.json()["flush"]["toolCalls"])
    assert_private(engine.calls[1]["messages"][-1])
    assert result["status"] == response.json()["flush"]["toolCalls"][0]["result"]["status"]
    assert result.get("error", result.get("afterWriteError")) == FAILURE
