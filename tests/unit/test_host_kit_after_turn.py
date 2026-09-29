"""HostKit.after_turn(): token snapshot and flush decision (docs/host_kit.md, entry 4, Task 4a)."""

from __future__ import annotations

import pytest

from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import DEFAULT_CONTEXT_WINDOW_TOKENS, HostKit, SessionState, TurnUsage
from memory_core.memory_flush import build_memory_flush_plan, explain_memory_flush_trigger

NOW_MS = 1_790_375_400_000  # 2026-09-25 22:30 UTC, 2026-09-26 01:30 in Istanbul


def _kit(root, **options) -> HostKit:
    config = MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(root, config=config, initialize=False, reindex=False)
    return HostKit(memory, now_ms=lambda: NOW_MS, seed_bootstrap=False, **options)


def _session(kind="main", **entry) -> SessionState:
    base = SessionState.new(session_key=f"agent:main:{kind}", session_id="s1", kind=kind)
    return SessionState(
        session_key=base.session_key,
        session_id=base.session_id,
        kind=kind,
        entry={**base.entry, **entry},
    )


def test_after_turn_records_a_fresh_token_snapshot(tmp_path):
    session = _session()

    record = _kit(tmp_path).after_turn(session, transcript=(), usage=TurnUsage(5000, 120))

    assert dict(record.session.entry) == {
        "sessionId": "s1",
        "compactionCount": 0,
        "totalTokens": 5000,
        "totalTokensFresh": True,
        "totalTokensVersion": 1,
    }
    assert record.session.last_output_tokens == 120
    assert record.flush_decision.total_tokens == 5120
    assert record.flush_decision.reason == "under_threshold"
    assert dict(session.entry) == {"sessionId": "s1", "compactionCount": 0}


def test_after_turn_without_usage_reports_missing_tokens(tmp_path):
    kit = _kit(tmp_path)
    fresh = kit.after_turn(_session(), transcript=(), usage=TurnUsage(5000, 10)).session

    stale = kit.after_turn(fresh, transcript=(), usage=None)
    output_only = kit.after_turn(fresh, transcript=(), usage=TurnUsage(prompt_tokens=None, completion_tokens=7))

    assert stale.flush_decision.reason == "missing_tokens"
    assert stale.session.entry["totalTokensFresh"] is False
    assert stale.session.entry["totalTokens"] == 5000
    assert stale.session.last_output_tokens is None
    assert output_only.flush_decision.reason == "missing_tokens"
    assert output_only.session.last_output_tokens == 7
    assert kit.after_turn(fresh, transcript=(), usage=TurnUsage(0)).flush_decision.reason == "missing_tokens"


CASES = [
    # (entry, usage, window, transcript bytes, the token count the kit must pass: total + output)
    ({}, TurnUsage(1000, 50), None, None, 1050),
    ({}, TurnUsage(176_000), None, None, 176_000),
    ({}, TurnUsage(175_900, 100), None, None, 176_000),
    ({"memoryFlush": {"kind": "succeeded", "compactionCount": 0}}, TurnUsage(180_000), None, None,
     180_000),
    ({"compactionCount": 1, "memoryFlush": {"kind": "succeeded", "compactionCount": 0}},
     TurnUsage(180_000), None, None, 180_000),
    ({}, TurnUsage(2_100), 5_333, None, 2_100),
    ({}, TurnUsage(1_900), 5_333, None, 1_900),
    ({}, None, None, 2 * 1024 * 1024, None),
    ({"memoryFlush": {"kind": "failed", "failureCount": 2}}, TurnUsage(10), None, 3 * 1024 * 1024,
     10),
]


@pytest.mark.parametrize(("entry", "usage", "window", "size", "token_count"), CASES)
def test_after_turn_decision_equals_explain_memory_flush_trigger(
    tmp_path, entry, usage, window, size, token_count
):
    session = _session(**entry)

    record = _kit(tmp_path, timezone="Europe/Istanbul", time_format="12").after_turn(
        session, transcript=(), usage=usage, context_window_tokens=window, transcript_bytes=size
    )

    effective_window = window if window is not None else 200_000
    plan = build_memory_flush_plan(
        workspace_dir=tmp_path,
        now_ms=NOW_MS,
        timezone="Europe/Istanbul",
        context_window_tokens=effective_window,
        time_format="12",
    )
    assert record.flush_plan == plan
    assert record.flush_plan.relative_path == "memory/2026-09-26.md"
    assert record.flush_decision == explain_memory_flush_trigger(
        entry=dict(record.session.entry),
        plan=plan,
        context_window_tokens=effective_window,
        token_count=token_count,
        transcript_byte_size=size,
    )


def test_after_turn_uses_no_prompt_estimate(tmp_path):
    # Threshold at the default window: 200,000 - 20,000 reserve - 4,000 soft = 176,000.
    record = _kit(tmp_path).after_turn(_session(), transcript=(), usage=TurnUsage(175_990, 5))

    assert record.flush_decision.threshold == 176_000
    assert record.flush_decision.total_tokens == 175_995
    assert record.flush_decision.reason == "under_threshold"
    assert _kit(tmp_path).after_turn(_session(), transcript=(), usage=TurnUsage(175_990, 10)).flush_decision.reason == (
        "token_threshold"
    )


def test_after_turn_defaults_to_the_upstream_context_window(tmp_path):
    record = _kit(tmp_path).after_turn(_session(), transcript=(), usage=TurnUsage(1))

    assert DEFAULT_CONTEXT_WINDOW_TOKENS == 200_000
    assert record.flush_plan == build_memory_flush_plan(
        workspace_dir=tmp_path, now_ms=NOW_MS, context_window_tokens=200_000
    )


def test_heartbeat_sessions_never_flush(tmp_path):
    record = _kit(tmp_path).after_turn(
        _session("heartbeat"), transcript=(), usage=TurnUsage(199_000), transcript_bytes=5 * 1024 * 1024
    )

    assert record.flush_decision.should_flush is False
    assert record.flush_decision.reason == "runtime_skip:heartbeat"
    assert record.session.entry["totalTokens"] == 199_000


def test_after_turn_is_idempotent(tmp_path):
    kit = _kit(tmp_path)
    session = _session()

    first = kit.after_turn(session, transcript=(), usage=TurnUsage(4000, 30), transcript_bytes=100)
    second = kit.after_turn(session, transcript=(), usage=TurnUsage(4000, 30), transcript_bytes=100)

    assert first == second
    assert kit.after_turn(first.session, transcript=(), usage=TurnUsage(4000, 30), transcript_bytes=100) == first


def test_after_turn_does_not_share_the_entry(tmp_path):
    session = _session(memoryFlush={"kind": "failed", "failureCount": 1})

    record = _kit(tmp_path).after_turn(session, transcript=(), usage=TurnUsage(10))

    assert record.session.entry["memoryFlush"] == session.entry["memoryFlush"]
    assert record.session.entry["memoryFlush"] is not session.entry["memoryFlush"]


def _target_failure(tmp_path, **options):
    # A symlinked memory/ directory: the flush target cannot be created (a flush strike).
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    root = tmp_path / "ws"
    root.mkdir()
    (root / "memory").symlink_to(outside, target_is_directory=True)
    return _kit(root).after_turn(
        _session(), transcript=(), usage=TurnUsage(190_000, 100), **options
    )


def test_after_turn_redacts_a_flush_target_failure(tmp_path):
    # after_turn(redact=) (docs/host_kit.md, F21): the redact FlushRequest.complete takes.
    seen = []

    def redact(text):
        seen.append(text)
        return text.replace("memory/", "<dir>/")

    record = _target_failure(tmp_path / "redacted", redact=redact)
    plain = _target_failure(tmp_path / "plain")

    assert record.flush is None and record.flush_decision.should_flush
    assert seen == [plain.flush_failure.error]
    assert record.flush_failure.error == "<dir>/ is a symlink; memory writes never follow symlinks"
    # Only the message changes: the entry stores no text.
    assert record.session.entry == plain.session.entry
    assert record.flush_failure.entry == plain.flush_failure.entry
    assert record.flush_failure.failure_count == 1


def test_after_turn_without_redact_keeps_the_failure_message(tmp_path):
    record = _target_failure(tmp_path, redact=None)

    assert record.flush_failure.error == "memory/ is a symlink; memory writes never follow symlinks"
