"""Flush plan, flush gate and flush session-entry state at OpenClaw v2026.9.6.

Upstream: extensions/memory-core/src/flush-plan.ts (buildMemoryFlushPlan),
src/agents/agent-compaction-constants.ts (resolveEffectiveCompactionReserveTokens),
src/auto-reply/reply/memory-flush.ts (resolveCompactionThreshold, shouldRunMemoryFlush,
shouldRunPreflightCompaction, hasAlreadyFlushedForCurrentCompaction),
src/config/sessions/types.ts (resolveFreshSessionTotalTokens) and
src/auto-reply/reply/agent-runner-memory.ts (runMemoryFlushIfNeeded, recordMemoryFlushFailure).
"""

from dataclasses import replace
from pathlib import Path

import pytest

from memory_core import _memory_flush_constants as extracted
from memory_core.memory_flush import (
    DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR,
    DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES,
    DEFAULT_MEMORY_FLUSH_PROMPT,
    DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
    DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT,
    MAX_FLUSH_ERROR_LENGTH,
    MAX_FLUSH_FAILURES,
    MEMORY_FLUSH_READ_ONLY_HINT,
    SESSION_TOTAL_TOKENS_VERSION,
    SILENT_REPLY_TOKEN,
    UnsafeMemoryFlushTargetError,
    build_memory_flush_plan,
    build_memory_flush_plan_from_config,
    ensure_memory_flush_safety_hints,
    ensure_no_reply_hint,
    explain_memory_flush_trigger,
    followup_uses_cli_runtime,
    format_current_time_line,
    has_already_flushed_for_current_compaction,
    record_memory_flush_failure,
    record_memory_flush_success,
    resolve_compaction_threshold,
    resolve_effective_compaction_reserve_tokens,
    resolve_fresh_session_total_tokens,
    resolve_memory_flush_threshold,
    should_force_memory_flush_by_transcript_size,
    should_run_memory_flush,
    should_run_memory_flush_trigger,
    truncate_memory_flush_error_message,
    validate_daily_memory_target,
)

NOW_MS = 1777824000000  # 2026-05-03 in Europe/Istanbul


def fresh(total_tokens, **fields):
    """A session entry whose totalTokens is a fresh v1 snapshot (types.ts:863-877)."""
    return {
        "totalTokens": total_tokens,
        "totalTokensFresh": True,
        "totalTokensVersion": SESSION_TOTAL_TOKENS_VERSION,
        **fields,
    }


def plan_with(context_window_tokens=None, **overrides):
    plan = build_memory_flush_plan(
        workspace_dir=None, now_ms=NOW_MS, context_window_tokens=context_window_tokens
    )
    return replace(plan, **overrides)


# --- flush plan ------------------------------------------------------------------------------


def test_flush_constants_come_from_the_extracted_upstream_module():
    assert DEFAULT_MEMORY_FLUSH_PROMPT == extracted.DEFAULT_MEMORY_FLUSH_PROMPT
    assert DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT == extracted.DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT
    assert MEMORY_FLUSH_READ_ONLY_HINT == extracted.MEMORY_FLUSH_READ_ONLY_HINT
    assert SILENT_REPLY_TOKEN == extracted.SILENT_REPLY_TOKEN == "NO_REPLY"
    assert DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR == 20_000
    assert SESSION_TOTAL_TOKENS_VERSION == 1


def test_build_memory_flush_plan_ports_openclaw_defaults(tmp_path: Path):
    plan = build_memory_flush_plan(
        workspace_dir=tmp_path,
        now_ms=NOW_MS,
        timezone="Europe/Istanbul",
    )

    assert plan.soft_threshold_tokens == DEFAULT_MEMORY_FLUSH_SOFT_TOKENS == 4000
    assert (
        plan.force_flush_transcript_bytes
        == DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES
        == 2 * 1024 * 1024
    )
    assert plan.reserve_tokens_floor == DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR
    assert plan.relative_path == "memory/2026-05-03.md"
    assert plan.model is None
    assert plan.prompt.startswith(
        DEFAULT_MEMORY_FLUSH_PROMPT.replace("YYYY-MM-DD", "2026-05-03") + "\nCurrent time: "
    )
    assert plan.system_prompt == DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT.replace(
        "YYYY-MM-DD", "2026-05-03"
    )
    # 669db2968fc (#113966) retired TOOLS.md: the read-only hint no longer names it.
    assert (
        "Treat workspace bootstrap/reference files such as MEMORY.md, DREAMS.md, "
        "SOUL.md, and AGENTS.md as read-only during this flush; never "
        "overwrite, replace, or edit them."
    ) in plan.prompt
    assert "TOOLS.md" not in plan.prompt and "TOOLS.md" not in plan.system_prompt
    assert f"If nothing to store, reply with {SILENT_REPLY_TOKEN}." in plan.prompt
    assert f"You may reply, but usually {SILENT_REPLY_TOKEN} is correct." in plan.system_prompt


@pytest.mark.parametrize("removed", ["prompt", "system_prompt", "reserve_tokens_floor"])
def test_build_memory_flush_plan_has_no_removed_overrides(tmp_path: Path, removed: str):
    # edecdbd05ef (#111527) removed the prompt/systemPrompt overrides and 783a5d21cfc
    # (#111382) the reserveTokensFloor knob; the reserve now derives from the window.
    with pytest.raises(TypeError):
        build_memory_flush_plan(workspace_dir=tmp_path, now_ms=NOW_MS, **{removed: "x"})


@pytest.mark.parametrize(
    ("window", "reserve", "soft"),
    [
        (None, 20_000, 4_000),
        (0, 20_000, 4_000),
        (-5, 20_000, 4_000),
        (200_000, 20_000, 4_000),
        (80_000, 20_000, 4_000),
        (79_999, 19_999, 4_000),
        (26_000, 6_500, 4_000),
        (26_000.9, 6_500, 4_000),
        (8_000, 2_000, 3_000),
        (100, 25, 37),
        (1, 0, 0),
    ],
)
def test_build_memory_flush_plan_derives_reserve_and_soft_threshold_from_the_window(
    window, reserve, soft
):
    # flush-plan.ts at v2026.9.6 (6b6f1969c11 #130072): reserve = min(20000, floor(W * 0.25)),
    # soft = min(soft, floor((W - reserve) / 2)) when the window is a positive integer.
    plan = build_memory_flush_plan(workspace_dir=None, now_ms=NOW_MS, context_window_tokens=window)

    assert (plan.reserve_tokens_floor, plan.soft_threshold_tokens) == (reserve, soft)


def test_build_memory_flush_plan_keeps_a_smaller_configured_soft_threshold():
    plan = build_memory_flush_plan(
        workspace_dir=None, now_ms=NOW_MS, soft_threshold_tokens=456, context_window_tokens=26_000
    )

    assert (plan.reserve_tokens_floor, plan.soft_threshold_tokens) == (6_500, 456)


@pytest.mark.parametrize(("value", "expected"), [(-1, 4_000), (2.9, 2), (0, 0), ("7", 4_000), (True, 4_000)])
def test_soft_threshold_normalizes_like_normalize_non_negative_int(value, expected):
    plan = build_memory_flush_plan(workspace_dir=None, now_ms=NOW_MS, soft_threshold_tokens=value)

    assert plan.soft_threshold_tokens == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # numbers: Math.floor, then a safe integer that is not negative (byte-size.ts)
        (1.5, 1),
        (-0.5, DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES),
        (-1e-9, DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES),
        (2**53 - 1, 2**53 - 1),
        (2**53, DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES),
        (2**60, DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES),
        (float("nan"), DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES),
        (True, DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES),
        # strings: parseByteSize with Math.round (halves up) and an ASCII-only pattern
        ("0.5", 1),
        ("0.5b", 1),
        ("2.5b", 3),
        ("1.5kb", 1536),
        (" 3MB ", 3 * 1024 * 1024),
        ("2 mb", DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES),
        ("1pb", DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES),
        ("", DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES),
        ("٣", DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES),
        ("3\n", 3),
        ("9007199254740993", DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES),
    ],
)
def test_force_flush_transcript_bytes_parses_like_parse_non_negative_byte_size(value, expected):
    plan = build_memory_flush_plan(workspace_dir=None, now_ms=NOW_MS, force_flush_transcript_bytes=value)

    assert plan.force_flush_transcript_bytes == expected


def test_byte_size_units_come_from_the_extracted_upstream_table():
    assert extracted.UNIT_MULTIPLIERS == {
        "b": 1, "kb": 1024, "k": 1024, "mb": 1024**2, "m": 1024**2,
        "gb": 1024**3, "g": 1024**3, "tb": 1024**4, "t": 1024**4,
    }


@pytest.mark.parametrize("now_ms", [8_640_000_000_000_001, -8_640_000_000_000_001, float("nan"), float("inf"), None])
def test_flush_plan_falls_back_when_the_timestamp_is_outside_date_range(monkeypatch, now_ms):
    # flush-plan.test.ts:10-18 (resolveMemoryCoreNowMs): Date.now() is mocked to 2026-05-30T12:00Z.
    import memory_core.memory_flush as memory_flush

    monkeypatch.setattr(memory_flush, "_date_now_ms", lambda: 1780142400000)

    plan = build_memory_flush_plan(workspace_dir=None, now_ms=now_ms)

    assert plan.relative_path == "memory/2026-05-30.md"
    assert "Reference UTC: 2026-05-30 12:00 UTC" in plan.prompt


def test_flush_plan_truncates_fractional_timestamps_toward_zero_like_date():
    # new Date(-0.5) is the epoch (TimeClip truncates toward zero), not 23:59 on 1969-12-31.
    plan = build_memory_flush_plan(workspace_dir=None, now_ms=-0.5)

    assert plan.relative_path == "memory/1970-01-01.md"
    assert "Reference UTC: 1970-01-01 00:00 UTC" in plan.prompt


def test_flush_plan_rejects_date_valid_instants_python_cannot_represent():
    # Deviation: upstream formats years past 9999 (and before 1000 with an unpadded year);
    # Python dates stop at 9999 and the daily path must be memory/YYYY-MM-DD.md.
    assert build_memory_flush_plan(workspace_dir=None, now_ms=253402300799999).relative_path == (
        "memory/9999-12-31.md"
    )
    with pytest.raises(ValueError, match="years 1-9999"):
        build_memory_flush_plan(workspace_dir=None, now_ms=253402300800000)
    with pytest.raises(UnsafeMemoryFlushTargetError):
        build_memory_flush_plan(workspace_dir=None, now_ms=-62135596800000)


def test_build_memory_flush_plan_from_config_ignores_removed_keys():
    plan = build_memory_flush_plan_from_config(
        workspace_dir=None,
        now_ms=NOW_MS,
        cfg={
            "agents": {
                "defaults": {
                    "userTimezone": "Europe/Istanbul",
                    "compaction": {
                        "reserveTokensFloor": 123,
                        "memoryFlush": {
                            "softThresholdTokens": 456,
                            "forceFlushTranscriptBytes": "3mb",
                            "model": " flush-model ",
                            "prompt": "Custom prompt.",
                            "systemPrompt": "Custom system.",
                        },
                    },
                }
            }
        },
    )

    assert plan is not None
    assert plan.reserve_tokens_floor == 20_000
    assert plan.soft_threshold_tokens == 456
    assert plan.force_flush_transcript_bytes == 3 * 1024 * 1024
    assert plan.model == "flush-model"
    assert "Custom" not in plan.prompt and "Custom" not in plan.system_prompt
    assert plan.system_prompt == DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT.replace("YYYY-MM-DD", "2026-05-03")


def test_build_memory_flush_plan_from_config_takes_the_context_window():
    plan = build_memory_flush_plan_from_config(
        workspace_dir=None, now_ms=NOW_MS, cfg={}, context_window_tokens=26_000
    )

    assert plan is not None
    assert (plan.reserve_tokens_floor, plan.soft_threshold_tokens) == (6_500, 4_000)


def test_build_memory_flush_plan_from_config_disabled_returns_none():
    cfg = {"agents": {"defaults": {"compaction": {"memoryFlush": {"enabled": False}}}}}

    assert build_memory_flush_plan_from_config(workspace_dir=None, cfg=cfg, now_ms=NOW_MS) is None


def test_safety_and_no_reply_helpers_leave_the_defaults_unchanged():
    # flush-plan.ts still wraps the defaults; with the overrides gone both are no-ops there.
    assert ensure_memory_flush_safety_hints(DEFAULT_MEMORY_FLUSH_PROMPT) == DEFAULT_MEMORY_FLUSH_PROMPT
    assert ensure_no_reply_hint(DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT) == DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT
    assert ensure_no_reply_hint("Write it.") == (
        "Write it.\n\nIf no user-visible reply is needed, start with NO_REPLY."
    )


# --- thresholds ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("budget", "reserve", "expected"),
    [(200_000, 20_000, 20_000), (26_000, 20_000, 6_500), (26_000, 1_000, 1_000), (0, 20_000, 0), (3, -4, 0)],
)
def test_resolve_effective_compaction_reserve_tokens(budget, reserve, expected):
    assert (
        resolve_effective_compaction_reserve_tokens(context_token_budget=budget, reserve_tokens=reserve)
        == expected
    )


def test_resolve_compaction_threshold_matches_memory_flush_ts():
    assert resolve_compaction_threshold(context_window_tokens=100, reserve_tokens_floor=10) == 90
    assert resolve_compaction_threshold(context_window_tokens=100, reserve_tokens_floor=200) == 0
    assert (
        resolve_compaction_threshold(
            context_window_tokens=100, reserve_tokens_floor=90, minimum_threshold_tokens=50.7
        )
        == 50
    )
    assert resolve_compaction_threshold(context_window_tokens=0, reserve_tokens_floor=0) == 1


def test_resolve_memory_flush_threshold_subtracts_the_soft_margin():
    # agent-runner-memory.ts:1254-1260 (inline in runMemoryFlushIfNeeded).
    assert (
        resolve_memory_flush_threshold(
            context_window_tokens=26_000, reserve_tokens_floor=6_500, soft_threshold_tokens=4_000
        )
        == 15_500
    )
    assert (
        resolve_memory_flush_threshold(
            context_window_tokens=100, reserve_tokens_floor=10, soft_threshold_tokens=500
        )
        == 0
    )


# --- fresh totals and the gate ----------------------------------------------------------------


def test_resolve_fresh_session_total_tokens_needs_fresh_v1_snapshots():
    assert resolve_fresh_session_total_tokens(fresh(85)) == 85
    assert resolve_fresh_session_total_tokens(fresh(0)) == 0
    assert resolve_fresh_session_total_tokens({"totalTokens": 85}) is None
    assert resolve_fresh_session_total_tokens({"totalTokens": 85, "totalTokensFresh": True}) is None
    assert resolve_fresh_session_total_tokens(fresh(85, totalTokensVersion=2)) is None
    assert resolve_fresh_session_total_tokens(fresh(85, totalTokensVersion=True)) is None
    assert resolve_fresh_session_total_tokens(fresh(-1)) is None
    assert resolve_fresh_session_total_tokens(None) is None


def test_should_run_memory_flush_matches_openclaw_threshold_boundary():
    assert should_run_memory_flush(entry=fresh(85), threshold=85)
    assert not should_run_memory_flush(entry=fresh(84), threshold=85)


def test_should_run_memory_flush_counts_only_fresh_session_totals():
    # 084d51d0c7b (#152268): a legacy entry without totalTokensFresh/Version is unknown.
    assert not should_run_memory_flush(entry={"totalTokens": 96_000}, threshold=93_000)
    assert not should_run_memory_flush(
        entry={"totalTokens": 96_000, "totalTokensFresh": False, "compactionCount": 1},
        threshold=93_000,
    )


def test_should_run_memory_flush_uses_projected_token_count_over_stale_total():
    assert should_run_memory_flush(
        entry={"totalTokens": 10, "totalTokensFresh": False, "compactionCount": 1},
        token_count=93_000,
        threshold=93_000,
    )
    assert not should_run_memory_flush(entry=None, token_count=93_000, threshold=1)


def test_should_run_memory_flush_treats_an_empty_entry_like_js():
    # An empty object is truthy in JS: the projected token count still decides.
    assert should_run_memory_flush(entry={}, token_count=93_000, threshold=93_000)
    assert not should_run_memory_flush(entry={}, threshold=1)


def test_fresh_totals_must_be_finite():
    assert resolve_fresh_session_total_tokens(fresh(float("inf"))) is None
    assert resolve_fresh_session_total_tokens(fresh(float("nan"))) is None
    assert not has_already_flushed_for_current_compaction(
        {"compactionCount": True, "memoryFlush": {"kind": "succeeded", "compactionCount": 1}}
    )


def test_should_run_memory_flush_needs_a_positive_threshold():
    assert not should_run_memory_flush(entry=fresh(10), threshold=0)


def test_should_run_memory_flush_skips_current_compaction_cycle_duplicate():
    entry = fresh(90_000, compactionCount=2, memoryFlush={"kind": "succeeded", "compactionCount": 2})

    assert not should_run_memory_flush(entry=entry, threshold=1_000)


def test_has_already_flushed_reads_the_memory_flush_object():
    # 8ee1d046d33 (#115299) consolidated the flat memoryFlush* fields into entry.memoryFlush.
    assert has_already_flushed_for_current_compaction(
        {"compactionCount": 3, "memoryFlush": {"kind": "succeeded", "compactionCount": 3}}
    )
    assert not has_already_flushed_for_current_compaction(
        {"compactionCount": 3, "memoryFlush": {"kind": "succeeded", "compactionCount": 2}}
    )
    assert has_already_flushed_for_current_compaction({"memoryFlush": {"kind": "failed", "compactionCount": 0, "failureCount": 1}})
    assert not has_already_flushed_for_current_compaction({"compactionCount": 1})
    # The pre-tag flat field is not read (upstream migrates it at store load).
    assert not has_already_flushed_for_current_compaction(
        {"compactionCount": 3, "memoryFlushCompactionCount": 3}
    )


def test_should_force_memory_flush_by_transcript_size_matches_openclaw_boundary():
    assert not should_force_memory_flush_by_transcript_size(
        transcript_byte_size=None, force_flush_transcript_bytes=100
    )
    assert not should_force_memory_flush_by_transcript_size(
        transcript_byte_size=99, force_flush_transcript_bytes=100
    )
    assert should_force_memory_flush_by_transcript_size(
        transcript_byte_size=100, force_flush_transcript_bytes=100
    )
    assert not should_force_memory_flush_by_transcript_size(
        transcript_byte_size=100, force_flush_transcript_bytes=0
    )


# --- the runtime trigger (runMemoryFlushIfNeeded order) --------------------------------------


def test_explain_memory_flush_trigger_derives_the_threshold_from_the_plan():
    plan = plan_with(26_000)

    decision = explain_memory_flush_trigger(entry=fresh(15_500), plan=plan, context_window_tokens=26_000)

    assert decision.should_flush is True
    assert decision.reason == "token_threshold"
    assert (decision.total_tokens, decision.threshold) == (15_500, 15_500)


def test_explain_memory_flush_trigger_reports_under_threshold_and_missing_tokens():
    plan = plan_with(100_000)

    under = explain_memory_flush_trigger(entry=fresh(10_000), plan=plan, context_window_tokens=100_000)
    stale = explain_memory_flush_trigger(
        entry={"totalTokens": 99_000}, plan=plan, context_window_tokens=100_000
    )

    assert (under.should_flush, under.reason, under.threshold) == (False, "under_threshold", 76_000)
    assert (stale.should_flush, stale.reason, stale.total_tokens) == (False, "missing_tokens", None)


def test_explain_memory_flush_trigger_reports_transcript_size_reason():
    plan = plan_with(100_000, force_flush_transcript_bytes=2_000)

    decision = explain_memory_flush_trigger(
        entry=fresh(1, compactionCount=1),
        plan=plan,
        context_window_tokens=100_000,
        transcript_byte_size=2_000,
    )

    assert decision.should_flush is True
    assert decision.reason == "transcript_size"
    assert decision.transcript_size_gate is True and decision.token_gate is False


def test_explain_memory_flush_trigger_blocks_both_paths_after_a_same_cycle_flush():
    plan = plan_with(100_000, force_flush_transcript_bytes=2_000)
    entry = fresh(99_000, compactionCount=1, memoryFlush={"kind": "succeeded", "compactionCount": 1})

    decision = explain_memory_flush_trigger(
        entry=entry, plan=plan, context_window_tokens=100_000, transcript_byte_size=2_000
    )

    assert decision.should_flush is False
    assert decision.reason == "already_flushed"
    assert decision.already_flushed is True and decision.token_gate and decision.transcript_size_gate


def test_explain_memory_flush_trigger_skips_a_disabled_plan():
    decision = explain_memory_flush_trigger(entry=fresh(99_000), plan=None, context_window_tokens=100_000)

    assert (decision.should_flush, decision.reason) == (False, "disabled")


@pytest.mark.parametrize(
    ("flags", "reason"),
    [
        ({"memory_flush_writable": False}, "runtime_skip:not_writable"),
        ({"is_heartbeat": True}, "runtime_skip:heartbeat"),
        ({"is_cli": True}, "runtime_skip:cli"),
    ],
)
def test_explain_memory_flush_trigger_reports_runtime_skip_reasons(flags, reason):
    plan = plan_with(100_000, force_flush_transcript_bytes=2_000)
    kwargs = {"entry": fresh(99_000), "plan": plan, "context_window_tokens": 100_000, "transcript_byte_size": 2_000}

    assert explain_memory_flush_trigger(**kwargs, **flags).reason == reason
    assert not should_run_memory_flush_trigger(**kwargs, **flags)


def test_should_run_memory_flush_trigger_matches_explain():
    plan = plan_with(100_000)

    assert should_run_memory_flush_trigger(entry=fresh(80_000), plan=plan, context_window_tokens=100_000)
    assert not should_run_memory_flush_trigger(entry=None, plan=plan, context_window_tokens=100_000)


# --- flush session-entry state (agent-runner-memory.ts) ---------------------------------------


def test_max_flush_failure_constants_match_openclaw():
    assert MAX_FLUSH_FAILURES == 3
    assert MAX_FLUSH_ERROR_LENGTH == 200


def test_truncate_memory_flush_error_message_matches_openclaw_boundary():
    exact = "e" * MAX_FLUSH_ERROR_LENGTH
    assert truncate_memory_flush_error_message(exact) == exact

    over = "e" * (MAX_FLUSH_ERROR_LENGTH + 50)
    truncated = truncate_memory_flush_error_message(over)
    assert len(truncated) == MAX_FLUSH_ERROR_LENGTH
    assert truncated == "e" * (MAX_FLUSH_ERROR_LENGTH - 1) + "…"

    assert truncate_memory_flush_error_message(RuntimeError("  boom  ")) == "boom"


def test_truncate_memory_flush_error_message_counts_utf16_units():
    # truncateUtf16Safe: an astral character is two units and is never split.
    message = "e" * (MAX_FLUSH_ERROR_LENGTH - 2) + "\U0001f600" + "x"

    assert truncate_memory_flush_error_message(message) == "e" * (MAX_FLUSH_ERROR_LENGTH - 2) + "…"


def test_record_memory_flush_success_stores_the_succeeded_state():
    entry = {"totalTokens": 90_000, "compactionCount": 4, "memoryFlush": {"kind": "failed", "failureCount": 2}}

    updated = record_memory_flush_success(entry)

    assert updated["memoryFlush"] == {"kind": "succeeded", "compactionCount": 4}
    assert has_already_flushed_for_current_compaction(updated)
    assert entry["memoryFlush"] == {"kind": "failed", "failureCount": 2}


def test_record_memory_flush_success_honors_explicit_flushed_compaction_count():
    updated = record_memory_flush_success({"compactionCount": 7}, flushed_compaction_count=6)

    assert updated["memoryFlush"] == {"kind": "succeeded", "compactionCount": 6}


def test_record_memory_flush_failure_counts_failures_in_the_memory_flush_object():
    outcome = record_memory_flush_failure(
        {"totalTokens": 90_000, "compactionCount": 2}, error=RuntimeError("flush run failed")
    )

    assert outcome.failure_count == 1
    assert outcome.exhausted is False
    assert outcome.error == "flush run failed"
    assert outcome.entry["memoryFlush"] == {"kind": "failed", "failureCount": 1}
    assert not has_already_flushed_for_current_compaction(outcome.entry)


def test_record_memory_flush_failure_keeps_the_last_flushed_cycle():
    entry = {"compactionCount": 3, "memoryFlush": {"kind": "succeeded", "compactionCount": 2}}

    outcome = record_memory_flush_failure(entry, error="boom")

    assert outcome.entry["memoryFlush"] == {"kind": "failed", "compactionCount": 2, "failureCount": 1}


def test_record_memory_flush_failure_exhausts_after_three_consecutive_failures():
    entry = {"totalTokens": 99_000, "compactionCount": 2}
    for attempt in range(1, MAX_FLUSH_FAILURES + 1):
        outcome = record_memory_flush_failure(entry, error=f"failure {attempt}")
        entry = outcome.entry
        assert outcome.failure_count == attempt
        assert outcome.exhausted is (attempt == MAX_FLUSH_FAILURES)

    # Exhaustion marks the cycle as flushed so the duplicate guard suppresses retries.
    assert entry["memoryFlush"] == {"kind": "succeeded", "compactionCount": 2}
    decision = explain_memory_flush_trigger(
        entry={**entry, **fresh(99_000)}, plan=plan_with(100_000), context_window_tokens=100_000
    )
    assert (decision.should_flush, decision.reason) == (False, "already_flushed")


def test_flush_retries_resume_after_next_compaction_increments_count():
    entry = fresh(99_000, compactionCount=2)
    for _ in range(MAX_FLUSH_FAILURES):
        entry = record_memory_flush_failure(entry, error="boom").entry
    assert has_already_flushed_for_current_compaction(entry)

    next_cycle = {**entry, "compactionCount": 3}

    assert not has_already_flushed_for_current_compaction(next_cycle)
    assert should_run_memory_flush(entry=next_cycle, threshold=93_000)


# --- CLI runtime skip (agent-runner-memory.ts followupUsesCliRuntime) --------------------------


def test_followup_uses_cli_runtime_for_direct_cli_provider():
    assert followup_uses_cli_runtime(provider="claude-cli", cli_providers=("claude-cli",))
    assert not followup_uses_cli_runtime(provider="anthropic", cli_providers=("claude-cli",))


def test_followup_uses_cli_runtime_for_session_pinned_runtime_alias():
    assert followup_uses_cli_runtime(
        provider="openai",
        session_entry={"agentRuntimeOverride": " Codex "},
        cli_runtime_bindings=(("openai", "codex"),),
    )
    assert not followup_uses_cli_runtime(
        provider="anthropic",
        session_entry={"agentRuntimeOverride": "codex"},
        cli_runtime_bindings=(("openai", "codex"),),
    )
    assert not followup_uses_cli_runtime(
        provider="openai",
        session_entry={},
        cli_runtime_bindings=(("openai", "codex"),),
    )


# --- the daily target -------------------------------------------------------------------------


def test_validate_daily_memory_target_accepts_only_canonical_daily_file():
    assert validate_daily_memory_target("memory/2026-05-03.md") == "memory/2026-05-03.md"


@pytest.mark.parametrize(
    "target",
    [
        "MEMORY.md",
        "DREAMS.md",
        "memory/2026-05-03-1900.md",
        "memory/note.md",
        "../memory/2026-05-03.md",
        "/memory/2026-05-03.md",
        "memory\\2026-05-03.md",
        "memory/nested/2026-05-03.md",
    ],
)
def test_validate_daily_memory_target_rejects_non_daily_files(target: str):
    with pytest.raises(UnsafeMemoryFlushTargetError):
        validate_daily_memory_target(target)


# --- the current-time line (resolveCronStyleNow, formatUserTime) --------------------------------


@pytest.mark.parametrize(
    ("now_ms", "time_format", "expected"),
    [
        (NOW_MS, "24", "Sunday, May 3rd, 2026 - 19:00"),
        (NOW_MS, "12", "Sunday, May 3rd, 2026 - 7:00 PM"),
        (1777758600000, "12", "Sunday, May 3rd, 2026 - 12:50 AM"),
        (1777801800000, "12", "Sunday, May 3rd, 2026 - 12:50 PM"),
        (1777798200000, "24", "Sunday, May 3rd, 2026 - 11:50"),
    ],
)
def test_format_current_time_line_supports_the_host_time_format(now_ms, time_format, expected):
    line = format_current_time_line(now_ms, "Europe/Istanbul", time_format)

    assert line.splitlines()[0] == f"Current time: {expected} (Europe/Istanbul)"


@pytest.mark.parametrize(
    ("timezone", "relative_path", "current_time"),
    [
        ("+03:00", "memory/2026-05-04.md", "Monday, May 4th, 2026 - 00:00 (+03:00)"),
        ("+0300", "memory/2026-05-04.md", "Monday, May 4th, 2026 - 00:00 (+0300)"),
        ("+03", "memory/2026-05-04.md", "Monday, May 4th, 2026 - 00:00 (+03)"),
        (" +03:00 ", "memory/2026-05-04.md", "Monday, May 4th, 2026 - 00:00 (+03:00)"),
        ("-05:30", "memory/2026-05-03.md", "Sunday, May 3rd, 2026 - 15:30 (-05:30)"),
        ("\u221203:00", "memory/2026-05-03.md", "Sunday, May 3rd, 2026 - 18:00 (\u221203:00)"),
        ("+23:59", "memory/2026-05-04.md", "Monday, May 4th, 2026 - 20:59 (+23:59)"),
        # Intl rejects these; upstream then takes the host zone, memory-core UTC (deviation).
        ("+24:00", "memory/2026-05-03.md", "Sunday, May 3rd, 2026 - 21:00 (UTC)"),
        ("+03:60", "memory/2026-05-03.md", "Sunday, May 3rd, 2026 - 21:00 (UTC)"),
        ("+3", "memory/2026-05-03.md", "Sunday, May 3rd, 2026 - 21:00 (UTC)"),
        ("UTC+3", "memory/2026-05-03.md", "Sunday, May 3rd, 2026 - 21:00 (UTC)"),
        ("/etc/passwd", "memory/2026-05-03.md", "Sunday, May 3rd, 2026 - 21:00 (UTC)"),
    ],
)
def test_flush_plan_accepts_ecma402_offset_time_zones(timezone, relative_path, current_time):
    # resolveUserTimezone accepts every zone Intl accepts, offsets included; the prompt's label
    # is the configured (trimmed) spelling. 2026-05-03T21:00Z is midnight at +03:00.
    plan = build_memory_flush_plan(workspace_dir=None, now_ms=1777842000000, timezone=timezone)

    assert plan.relative_path == relative_path
    assert f"Current time: {current_time}\nReference UTC: 2026-05-03 21:00 UTC" in plan.prompt


def test_current_time_names_do_not_follow_the_process_locale():
    import locale

    previous = locale.setlocale(locale.LC_TIME)
    try:
        locale.setlocale(locale.LC_TIME, "tr_TR.UTF-8")
    except locale.Error:
        pytest.skip("tr_TR.UTF-8 locale not installed")
    try:
        line = format_current_time_line(NOW_MS, "Europe/Istanbul")
    finally:
        locale.setlocale(locale.LC_TIME, previous)

    assert line.splitlines()[0] == "Current time: Sunday, May 3rd, 2026 - 19:00 (Europe/Istanbul)"


def test_flush_plan_prompt_uses_the_host_time_format():
    plan = build_memory_flush_plan(
        workspace_dir=None, now_ms=NOW_MS, timezone="Europe/Istanbul", time_format="12"
    )

    assert "Current time: Sunday, May 3rd, 2026 - 7:00 PM (Europe/Istanbul)" in plan.prompt
    with pytest.raises(ValueError):
        build_memory_flush_plan(workspace_dir=None, now_ms=NOW_MS, time_format="auto")
