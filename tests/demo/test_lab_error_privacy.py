"""Offline Lab diagnostic privacy at the tool, event and model-feedback boundaries."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from demo import lab_runtime
from demo.lab_tools import LabToolbox, ToolLoopOutcome, run_tool_loop
from memory_core.host import FlushRequest, HostKit
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.secret_registry import (
    capture_secret_redaction_registry_snapshot,
    encode_uri_component,
    json_string_content,
)
from memory_core.tools.corpus import CorpusAttempt, compose_memory_corpus_metadata
from memory_core.tools.memory_search import execute_memory_search_tool
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

    result = lab_runtime.redact_diagnostic_payload(payload, (KEY,))

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


def test_successful_tool_content_is_unchanged(lab, monkeypatch):
    lab.ensure()
    store = lab.store(lab.resolve_embedding({}), mode="text")
    lab.reindex(store)
    kit = lab.kit(store)
    toolbox = LabToolbox(lab, kit, lab.session("main"), None, secrets=(KEY,))
    owner_dispatch = HostKit.dispatch
    owner_results = []

    def capture_owner_result(self, *args, **kwargs):
        result = owner_dispatch(self, *args, **kwargs)
        # Capture the complete result before the Lab's privacy boundary. One
        # real search keeps its genuine timing fields comparable without a
        # second operation, field projection, or replacement payload.
        owner_results.append(deepcopy(result))
        return result

    monkeypatch.setattr(HostKit, "dispatch", capture_owner_result)

    record = toolbox.dispatch("c1", "memory_search", '{"query":"note"}')

    assert len(owner_results) == 1
    assert record["result"] == owner_results[0]
    assert record["result"]["results"] == []
    assert record["result"]["provider"] == "none"
    assert "model" not in record["result"]
    assert record["result"]["citations"] == "auto"
    assert set(record["result"]["debug"]) == {
        "backend", "effectiveMode", "searchMs", "hits", "candidateHits",
        "withheldHits", "searchWindow", "toolMs", "outsideSearchMs",
    }


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


@pytest.mark.parametrize("scoped_key", [False, True])
def test_successful_search_endpoint_preserves_content_and_exact_only_redaction(
    client, monkeypatch, scoped_key
):
    import demo.lab_kept_api as kept

    content = f"token={LONG} {KEY}"
    result = {"results": [{"snippet": content, "score": 1}], "citations": "on"}
    monkeypatch.setattr(kept, "execute_memory_search_tool", lambda *args: result)
    payload = {"query": "note", "mode": "text"}
    if scoped_key:
        payload["openai"] = {"apiKey": KEY}

    response = client.post("/api/search", json=payload)

    assert response.status_code == 200
    expected = content.replace(KEY, "[redacted]") if scoped_key else content
    assert response.json()["results"] == [{"snippet": expected, "score": 1}]
    assert result == {"results": [{"snippet": content, "score": 1}], "citations": "on"}
    assert response.json()["citations"] == "on"


def test_general_payload_redaction_does_not_apply_diagnostic_policy():
    value = {"results": [{"snippet": f"token={LONG} {KEY}"}]}

    assert lab_runtime.redact_payload(value, ()) is value
    assert lab_runtime.redact_payload(value, (KEY,)) == {
        "results": [{"snippet": f"token={LONG} [redacted]"}]
    }
    assert value["results"][0]["snippet"] == f"token={LONG} {KEY}"


def test_real_all_corpus_search_diagnostic_is_private_before_records_and_feedback(lab, monkeypatch):
    lab.ensure()
    store = lab.store(lab.resolve_embedding({}), mode="text")
    lab.reindex(store)

    def fail(*args, **kwargs):
        raise RuntimeError(FAILURE)

    monkeypatch.setattr(SQLiteMemoryStore, "search", fail)
    result = execute_memory_search_tool(lab.config(mode="text"), store, {"query": "note", "corpus": "all"})
    assert not any(key in result for key in ("status", "unavailable", "disabled"))
    assert result["corpora"][0]["outcome"] == "unavailable"
    assert result["error"] == FAILURE.replace(LONG, "a1B2c3…wXyZ")
    assert LONG not in json.dumps(result)
    monkeypatch.setattr(HostKit, "dispatch", lambda *args, **kwargs: result)
    toolbox = LabToolbox(lab, lab.kit(store), lab.session("main"), None, secrets=(KEY,))
    engine = StubEngine([("", [tool_call("c1", "memory_search", {"query": "note", "corpus": "all"})]),
                         ("done", [])])

    events = list(run_tool_loop(engine, [], toolbox, ToolLoopOutcome(), secrets=(KEY,)))

    assert_private(events)
    assert_private(toolbox.calls)
    assert_private(engine.calls[1]["messages"][-1])
    assert result["error"] == FAILURE.replace(LONG, "a1B2c3…wXyZ")
    assert LONG not in json.dumps(result)


@pytest.mark.parametrize("name,status", [("memory_search", None), ("memory_get", "ok"),
                                        ("memory_get", "not_found")])
def test_mixed_corpus_diagnostics_are_private_and_successful_content_is_unchanged(
    lab, monkeypatch, name, status
):
    lab.ensure()
    metadata = compose_memory_corpus_metadata([
        CorpusAttempt("memory", "partial", error=FAILURE, deadline=True),
        CorpusAttempt("wiki", "ok"),
    ])
    content = f"token={LONG}"
    result = ({"results": [{"snippet": content, "score": 1}]} if name == "memory_search"
              else {"status": status, "text": content, "path": "MEMORY.md"})
    result.update(metadata)
    before = json.loads(json.dumps(result))
    kit = lab.kit(lab.store(lab.resolve_embedding({}), mode="text"))
    monkeypatch.setattr(HostKit, "dispatch", lambda *args, **kwargs: result)
    toolbox = LabToolbox(lab, kit, lab.session("main"), None, secrets=(KEY,))
    engine = StubEngine([("", [tool_call("c1", name, {"query": "note", "corpus": "all"})]),
                         ("done", [])])

    events = list(run_tool_loop(engine, [], toolbox, ToolLoopOutcome(), secrets=(KEY,)))

    saved = toolbox.calls[0]["result"]
    for published in (dict(events[1][1]["result"]), saved,
                      json.loads(engine.calls[1]["messages"][-1]["content"])):
        assert_private({key: published[key] for key in ("error", "warning", "corpora")})
        assert published.get("results", published.get("text")) == result.get("results", result.get("text"))
        assert published["timedOut"] is True and published["timeoutMs"] == 30_000
    assert result == before
