"""Runtime flush accounting, including the maintenance/fresh-usage asymmetry."""

from copy import deepcopy
from dataclasses import replace

import pytest

from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, SessionState, TurnUsage
from memory_core.memory_flush import (
    build_memory_flush_plan,
    resolve_memory_flush_runtime_accounting,
)
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

NOW = 1_790_375_400_000


def fresh(total=175_990, **fields):
    return {"totalTokens": total, "totalTokensFresh": True, "totalTokensVersion": 1, **fields}


def event(usage=None, *, role="assistant", text="", **message):
    value = {"role": role, "content": [{"type": "text", "text": text}], **message}
    if usage is not None:
        value["usage"] = usage
    return {"type": "message", "message": value}


def accounting(entry, events=(), **options):
    plan = build_memory_flush_plan(workspace_dir=None, now_ms=NOW, context_window_tokens=200_000)
    return resolve_memory_flush_runtime_accounting(
        entry=entry, plan=plan, context_window_tokens=200_000,
        transcript_events=events, **options,
    )


def kit(root, **options):
    memory = Memory.from_workspace(
        root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False)),
        initialize=False,
    )
    return HostKit(memory, now_ms=lambda: NOW, **options)


def session(entry=None, **options):
    return SessionState(
        session_key="agent:main:main", session_id="s1",
        entry={"sessionId": "s1", "compactionCount": 0, **(entry or {})}, **options,
    )


def test_empty_maintenance_prompt_does_not_read_output_for_fresh_totals(monkeypatch):
    def forbidden(_):
        pytest.fail("fresh maintenance unexpectedly scanned transcript usage")

    monkeypatch.setattr("memory_core.usage_normalization.normalize_usage", forbidden)
    result = accounting(fresh(), [event({"input": 175_990, "output": 100_000})])
    assert not result.read_transcript_usage
    assert result.decision.total_tokens == 175_990
    assert not result.decision.should_flush


@pytest.mark.parametrize("entry", [{}, fresh(totalTokensFresh=False), fresh(totalTokensVersion=0)])
def test_stale_and_missing_usage_recover_prompt_and_output(entry):
    result = accounting(entry, [event({"input": 175_990, "output": 10})])
    assert result.read_transcript_usage
    assert result.decision.should_flush
    assert result.decision.total_tokens == 176_000
    assert result.entry["totalTokens"] == 175_990
    assert result.entry["totalTokensFresh"] is True
    assert result.entry["totalTokensVersion"] == 1


@pytest.mark.parametrize(("total", "read"), [(167_806, False), (167_807, True), (175_990, True)])
def test_nonblank_next_prompt_controls_the_exact_8192_read_boundary(total, read):
    result = accounting(fresh(total), [event({"input": total, "output": 10})],
                        prompt_for_estimate="four")
    assert result.prompt_token_estimate == 1
    assert result.read_transcript_usage is read
    assert result.decision.total_tokens == total + 1 + (10 if read else 0)


def test_recovered_prompt_only_increases_a_fresh_snapshot():
    lower = accounting(fresh(), [event({"input": 170_000, "output": 20})],
                       prompt_for_estimate="four")
    higher = accounting(fresh(), [event({"input": 190_000, "output": 20})],
                        prompt_for_estimate="four")
    assert lower.entry == fresh()
    assert lower.decision.total_tokens == 176_011
    assert higher.entry == fresh(190_000)
    assert higher.decision.total_tokens == 190_021


def test_trailing_messages_project_context_without_message_overhead():
    events = [event({"input": 175_990, "output": 5}),
              event(role="user", text="中文測試")]
    before = deepcopy(events)
    result = accounting({}, events)
    assert result.transcript_prompt_tokens == 175_994
    assert result.decision.total_tokens == 175_999
    assert result.entry["totalTokens"] == 175_994
    assert events == before


@pytest.mark.parametrize("barrier", [
    {"type": "reset"}, {"type": "compaction"},
    event({"input": 1}, api="cli"),
    event({"contextUsage": {"state": "unavailable"}}),
])
def test_transcript_barriers_prevent_reusing_older_usage(barrier):
    result = accounting({}, [event({"input": 190_000, "output": 10}), barrier])
    assert result.decision.reason == "missing_tokens"
    assert result.transcript_prompt_tokens is None
    assert result.transcript_output_tokens is None


def test_newer_output_only_anchor_does_not_reuse_an_older_prompt():
    result = accounting({}, [event({"input": 190_000}), event({"output": 10})])
    assert result.transcript_output_tokens == 10
    assert result.decision.reason == "missing_tokens"


def test_unavailable_context_with_billing_usage_still_supplies_output_to_a_fresh_base():
    result = accounting(
        fresh(), [event({"contextUsage": {"state": "unavailable"}, "output": 20})],
        prompt_for_estimate="four",
    )
    assert result.transcript_prompt_tokens is None
    assert result.transcript_output_tokens == 20
    assert result.decision.total_tokens == 176_011


@pytest.mark.parametrize(("usage", "expected"), [
    ({"input": 10, "cacheRead": 20, "cacheWrite": 30}, 60),
    ({"total": 120, "output": 20}, 100),
    ({"input": 900, "contextUsage": {"state": "available", "promptTokens": 100,
                                     "totalTokens": 120}}, 100),
    ({"prompt_tokens": 120, "prompt_tokens_details": {"cached_tokens": 20}}, 120),
])
def test_transcript_usage_normalization_retains_provider_context_semantics(usage, expected):
    result = accounting({}, [event(usage)])
    assert result.transcript_prompt_tokens == expected
    assert result.entry["totalTokens"] == expected


def test_usage_anchor_outside_the_512_event_tail_is_not_used():
    anchor = event({"input": 190_000})
    trailing = [event(role="user", text="x") for _ in range(512)]
    assert accounting({}, [anchor, *trailing]).decision.reason == "missing_tokens"
    assert accounting({}, [anchor, *trailing[:-1]]).transcript_prompt_tokens == 190_511


def test_runtime_context_custom_rows_are_not_counted_in_trailing_projection():
    events = [event({"input": 100}), {"type": "message", "message": {
        "role": "custom", "customType": "openclaw.runtime-context", "content": "x" * 9000,
    }}]
    result = accounting({}, events, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    assert result.transcript_prompt_tokens == 100


@pytest.mark.parametrize("options", [
    {"memory_flush_writable": False}, {"is_cli": True}, {"is_heartbeat": True},
])
def test_host_admission_exclusions_run_before_plan_and_transcript_access(tmp_path, monkeypatch, options):
    host = kit(tmp_path)

    def forbidden(_):
        pytest.fail("excluded runtime constructed a plan")

    monkeypatch.setattr(host, "_flush_plan", forbidden)
    record = host.prepare_flush(session(fresh(190_000)), **options)
    assert record.flush is None and record.flush_plan is None
    assert record.flush_decision.reason.startswith("runtime_skip:")
    assert not (tmp_path / "memory").exists()


@pytest.mark.parametrize("key", [
    "agent:main:dashboard:incognito-test", " AGENT:MAIN:SUBAGENT:INCOGNITO-X ",
    "agent:main:internal-session-effects:incognito-x",
])
def test_host_incognito_key_exclusion_and_entry_exclusion(tmp_path, key):
    host = kit(tmp_path)
    private = replace(session(fresh(190_000)), session_key=key)
    assert host.prepare_flush(private).flush_decision.reason == "runtime_skip:incognito"
    assert host.prepare_flush(session(fresh(190_000, incognito=True))).flush is None
    assert not (tmp_path / "memory").exists()


def test_host_prepare_flush_keeps_persisted_usage_and_after_turn_applies_new_usage(tmp_path):
    host = kit(tmp_path)
    persisted = session(fresh(190_000), last_output_tokens=50)
    prepared = host.prepare_flush(persisted)
    assert prepared.flush is not None
    assert prepared.session.entry == persisted.entry
    fresh_turn = host.after_turn(persisted, transcript=(), usage=TurnUsage(175_990, 1000))
    assert fresh_turn.flush is None
    assert fresh_turn.flush_decision.total_tokens == 175_990
    assert fresh_turn.session.last_output_tokens == 1000


def test_host_disabled_flush_config_and_explicit_size_threshold(tmp_path):
    disabled = kit(tmp_path / "off", flush_config={"enabled": False})
    assert disabled.prepare_flush(session(fresh(190_000))).flush_decision.reason == "disabled"
    assert disabled.request_flush(session(), transcript=()) is None
    host = kit(tmp_path / "on", flush_config={"forceFlushTranscriptBytes": 123})
    assert host.prepare_flush(session(), transcript_bytes=122).flush is None
    assert host.prepare_flush(session(), transcript_bytes=123).flush_decision.reason == "transcript_size"
    assert host.prepare_flush(session()).flush is None  # no invented byte count


def test_runtime_accounting_never_mutates_the_persisted_entry():
    entry = {"memoryFlush": {"kind": "failed", "failureCount": 1}}
    before = deepcopy(entry)
    result = accounting(entry, [event({"input": 190_000})])
    result.entry["memoryFlush"]["failureCount"] = 99
    assert entry == before
