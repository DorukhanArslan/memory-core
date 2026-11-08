"""Public flush completion and host-tool composition; native parity is tested separately."""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, SessionState, TurnUsage


NOW_MS = 1_790_375_400_000
TARGET = "memory/2026-09-25.md"
READ = {"name": "read", "description": "Read host context", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
}}


def _session(**entry):
    return SessionState(session_key="agent:main:main", session_id="source",
                        entry={"sessionId": "source", "compactionCount": 0, **entry})


def _kit(root, **options):
    memory = Memory.from_workspace(
        root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False)),
        initialize=False,
    )
    return HostKit(memory, now_ms=lambda: NOW_MS, **options)


def _request(root, **options):
    kit = _kit(root, **options)
    request = kit.request_flush(_session(), transcript=())
    assert request is not None
    return request


def test_write_receipt_retains_actual_native_content_and_changed_flag(tmp_path):
    request = _request(tmp_path)
    result = request.dispatch("write", {"path": TARGET, "content": "NO_REPLY\r\n\r\n"})
    assert (tmp_path / TARGET).read_bytes() == b"NO_REPLY\r\n\r\n"
    assert result["content"] == [{"type": "text", "text": f"Appended content to {TARGET}."}]
    assert result["details"] == {"changed": True}
    assert request.complete(_session()).entries == ("NO_REPLY\r\n\r\n",)


def test_recoverable_tool_error_does_not_make_a_recovered_model_run_fail(tmp_path):
    request = _request(tmp_path)
    refused = request.dispatch("write", {"path": "MEMORY.md", "content": "wrong path"})
    assert refused["details"]["status"] == "error"
    assert refused["isError"] is True
    accepted = request.dispatch("write", {"path": TARGET, "content": "corrected"})
    assert accepted["details"]["changed"] is True
    outcome = request.complete(_session(), payloads=[{"text": "NO_REPLY"}])
    assert outcome.failure is None and not outcome.cancelled
    assert outcome.session.entry["memoryFlush"] == {"kind": "succeeded", "compactionCount": 0}


def test_resolved_visible_model_errors_prevent_success_and_keep_committed_bytes(tmp_path):
    request = _request(tmp_path)
    request.dispatch("write", {"path": TARGET, "content": "kept"})
    outcome = request.complete(_session(), payloads=[
        {"isError": True, "text": " first problem "},
        {"isError": False, "text": "not an error"},
        {"isError": True, "text": "second problem"},
    ])
    assert (tmp_path / TARGET).read_bytes() == b"kept"
    assert outcome.entries == ("kept",)
    assert outcome.failure.error == "first problem\nsecond problem"
    assert outcome.session.entry["memoryFlush"] == {"kind": "failed", "failureCount": 1}


@pytest.mark.parametrize("payload", [
    {"isError": True, "text": "  "}, {"isError": 1, "text": "ignored"},
    {"isError": False, "mediaUrl": "https://example.invalid/error.png"},
])
def test_nonrenderable_or_nonerror_payloads_do_not_prevent_success(tmp_path, payload):
    outcome = _request(tmp_path).complete(_session(), payloads=[payload])
    assert outcome.failure is None
    assert outcome.session.entry["memoryFlush"]["kind"] == "succeeded"


@pytest.mark.parametrize("fields", [
    {"mediaUrl": "https://example.invalid/error.png"}, {"mediaUrls": [" ", "asset"]},
    {"channelData": {"host": "error card"}}, {"location": {}}, {"audioAsVoice": True},
])
def test_renderable_nontext_errors_use_the_native_fallback_message(tmp_path, fields):
    outcome = _request(tmp_path).complete(_session(), payloads=[{"isError": True, **fields}])
    assert outcome.failure.error == "Memory flush returned an error response"
    assert outcome.session.entry["memoryFlush"]["kind"] == "failed"


def test_host_ui_classifier_receives_the_original_payload_and_can_ignore_it(tmp_path):
    payload = {"isError": True, "presentation": {"blocks": [{"type": "divider"}]}}
    seen = []

    def classify(actual):
        assert actual is payload
        seen.append(actual)
        return False

    outcome = _request(tmp_path).complete(
        _session(), payloads=[payload], payload_is_renderable=classify,
    )
    assert seen == [payload]
    assert outcome.failure is None


def test_ui_metadata_requires_a_host_classifier_and_cannot_stamp_success(tmp_path):
    session = _session()
    before = deepcopy(dict(session.entry))
    request = _request(tmp_path)
    with pytest.raises(ValueError, match="payload_is_renderable"):
        request.complete(session, payloads=[{"isError": True, "presentation": {"title": "Error"}}])
    assert session.entry == before
    with pytest.raises(RuntimeError, match="already completed"):
        request.complete(session)


@pytest.mark.parametrize("error", [asyncio.CancelledError(), RuntimeError("This operation was aborted")])
def test_cancelled_completion_keeps_committed_bytes_without_a_cycle_stamp(tmp_path, error):
    request = _request(tmp_path)
    request.dispatch("write", {"path": TARGET, "content": "committed"})
    session = _session()
    outcome = request.complete(session, error=error)
    assert outcome.cancelled and outcome.failure is None
    assert outcome.session.entry == session.entry
    assert outcome.entries == ("committed",)
    assert (tmp_path / TARGET).read_bytes() == b"committed"


def test_explicit_owner_cancellation_preserves_the_failure_counter(tmp_path):
    session = _session(memoryFlush={"kind": "failed", "failureCount": 2})
    outcome = _request(tmp_path).complete(session, error="owner reason", cancelled=True)
    assert outcome.cancelled
    assert outcome.session.entry["memoryFlush"] == {"kind": "failed", "failureCount": 2}


def test_flush_provenance_uses_the_distinct_internal_execution_identity(tmp_path):
    store = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    request = _request(tmp_path, artifact_provenance=store)
    request.dispatch("write", {"path": TARGET, "content": "internal execution fact"})
    record = dict(store.list(tmp_path))[TARGET]
    assert record.session_id == request.execution_session_id != "source"
    assert record.session_key == request.execution_session_key != "agent:main:main"
    assert request.execution_session_id.startswith("internal-session-effects-")
    assert request.execution_session_key.startswith("agent:main:internal-session-effects:")
    with pytest.raises(AttributeError):
        request.execution_session_id = "source"
    assert _request(tmp_path).execution_session_id != request.execution_session_id


@pytest.mark.parametrize("method,tainted,expected", [
    ("after_turn", False, "untrusted"), ("prepare_flush", False, "untrusted"),
    ("forced", False, "agent"), ("forced", True, "untrusted"),
])
def test_automatic_maintenance_cannot_inherit_source_ownership(tmp_path, method, tainted, expected):
    store = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    kit = _kit(tmp_path, artifact_provenance=store)
    session = _session(totalTokens=176000, totalTokensFresh=True, totalTokensVersion=1)
    if method == "after_turn":
        request = kit.after_turn(
            session, transcript=(), usage=TurnUsage(176000, 0), untrusted_turn=tainted,
        ).flush
    elif method == "prepare_flush":
        request = kit.prepare_flush(session, transcript=(), untrusted_turn=tainted).flush
    else:
        request = kit.request_flush(session, transcript=(), untrusted_turn=tainted)
    assert request is not None
    request.dispatch("write", {"path": TARGET, "content": "maintenance fact"})
    record = dict(store.list(tmp_path))[TARGET]
    assert record.origin_class == expected
    assert record.session_id == request.execution_session_id != session.session_id


def test_host_read_definition_and_result_are_delegated_without_rewriting(tmp_path):
    definition = deepcopy(READ)
    result = {"content": [{"type": "text", "text": "host context"}], "details": {"kind": "text"}}
    seen = []

    def read(args):
        seen.append(args)
        return result

    request = _request(tmp_path, flush_read_tool=definition, flush_read_dispatch=read)
    definition["description"] = "changed after creation"
    assert request.tools[0] == READ
    assert request.tools[1]["name"] == "write"
    assert request.dispatch("read", {"path": "USER.md"}) is result
    assert seen == [{"path": "USER.md"}]
    assert request.complete(_session()).wrote is False


def test_a_failing_host_read_is_a_recoverable_native_shaped_tool_error(tmp_path):
    def read(_args):
        raise OSError("read failed")

    request = _request(tmp_path, flush_read_tool=READ, flush_read_dispatch=read)
    result = request.dispatch("read", {"path": "USER.md"})
    assert result["details"] == {"status": "error", "tool": "read", "error": "read failed"}
    assert result["content"][0]["text"].startswith('{\n  "status": "error",')
    assert request.complete(_session()).failure is None


@pytest.mark.parametrize("options", [
    {"flush_read_tool": READ}, {"flush_read_dispatch": lambda _args: {}},
    {"flush_read_tool": {"name": "exec"}, "flush_read_dispatch": lambda _args: {}},
])
def test_read_delegation_rejects_incomplete_or_unrelated_tool_registration(tmp_path, options):
    with pytest.raises(ValueError):
        _kit(tmp_path, **options)
