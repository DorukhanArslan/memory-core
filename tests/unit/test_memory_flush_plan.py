from pathlib import Path

import pytest

from memory_core.memory_flush import (
    DEFAULT_PI_COMPACTION_RESERVE_TOKENS_FLOOR,
    DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES,
    DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
    MAX_FLUSH_ERROR_LENGTH,
    MAX_FLUSH_FAILURES,
    SILENT_REPLY_TOKEN,
    UnsafeMemoryFlushTargetError,
    build_memory_flush_plan,
    explain_memory_flush_trigger,
    followup_uses_cli_runtime,
    has_already_flushed_for_current_compaction,
    record_memory_flush_failure,
    record_memory_flush_success,
    should_force_memory_flush_by_transcript_size,
    should_run_memory_flush_trigger,
    should_run_memory_flush,
    truncate_memory_flush_error_message,
    validate_daily_memory_target,
)


def test_build_memory_flush_plan_ports_openclaw_defaults(tmp_path: Path):
    plan = build_memory_flush_plan(
        workspace_dir=tmp_path,
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert plan.soft_threshold_tokens == DEFAULT_MEMORY_FLUSH_SOFT_TOKENS == 4000
    assert (
        plan.force_flush_transcript_bytes
        == DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES
        == 2 * 1024 * 1024
    )
    assert plan.reserve_tokens_floor == DEFAULT_PI_COMPACTION_RESERVE_TOKENS_FLOOR == 20_000
    assert plan.relative_path == "memory/2026-05-03.md"
    assert "Pre-compaction memory flush." in plan.prompt
    assert (
        "Store durable memories only in memory/2026-05-03.md "
        "(create memory/ if needed)."
    ) in plan.prompt
    assert (
        "Treat workspace bootstrap/reference files such as MEMORY.md, DREAMS.md, "
        "SOUL.md, TOOLS.md, and AGENTS.md as read-only during this flush; never "
        "overwrite, replace, or edit them."
    ) in plan.prompt
    assert (
        "If memory/2026-05-03.md already exists, APPEND new content only and do "
        "not overwrite existing entries."
    ) in plan.prompt
    assert (
        "Do NOT create timestamped variant files (e.g., 2026-05-03-HHMM.md); "
        "always use the canonical 2026-05-03.md filename."
    ) in plan.prompt
    assert f"If nothing to store, reply with {SILENT_REPLY_TOKEN}." in plan.prompt
    assert "Current time:" in plan.prompt
    assert "Pre-compaction memory flush turn." in plan.system_prompt
    assert (
        f"You may reply, but usually {SILENT_REPLY_TOKEN} is correct."
    ) in plan.system_prompt


def test_build_memory_flush_plan_allows_reserve_floor_override(tmp_path: Path):
    plan = build_memory_flush_plan(
        workspace_dir=tmp_path,
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
        reserve_tokens_floor=123,
    )

    assert plan.reserve_tokens_floor == 123


def test_should_run_memory_flush_matches_openclaw_threshold_boundary():
    assert should_run_memory_flush(
        entry={"totalTokens": 85},
        context_window_tokens=100,
        reserve_tokens_floor=10,
        soft_threshold_tokens=5,
    )


def test_should_run_memory_flush_skips_under_threshold_and_missing_entry():
    assert not should_run_memory_flush(
        entry=None,
        context_window_tokens=16_000,
        reserve_tokens_floor=1_000,
        soft_threshold_tokens=4_000,
    )
    assert not should_run_memory_flush(
        entry={"totalTokens": 10_000},
        context_window_tokens=100_000,
        reserve_tokens_floor=20_000,
        soft_threshold_tokens=10_000,
    )


def test_should_run_memory_flush_ignores_stale_cached_totals():
    assert not should_run_memory_flush(
        entry={"totalTokens": 96_000, "totalTokensFresh": False, "compactionCount": 1},
        context_window_tokens=100_000,
        reserve_tokens_floor=5_000,
        soft_threshold_tokens=2_000,
    )


def test_should_run_memory_flush_uses_projected_token_count_over_stale_total():
    assert should_run_memory_flush(
        entry={"totalTokens": 10, "totalTokensFresh": False, "compactionCount": 1},
        token_count=93_000,
        context_window_tokens=100_000,
        reserve_tokens_floor=5_000,
        soft_threshold_tokens=2_000,
    )


def test_should_run_memory_flush_skips_current_compaction_cycle_duplicate():
    assert not should_run_memory_flush(
        entry={
            "totalTokens": 90_000,
            "compactionCount": 2,
            "memoryFlushCompactionCount": 2,
        },
        context_window_tokens=100_000,
        reserve_tokens_floor=5_000,
        soft_threshold_tokens=2_000,
    )


def test_has_already_flushed_for_current_compaction_matches_openclaw():
    assert has_already_flushed_for_current_compaction(
        {"compactionCount": 3, "memoryFlushCompactionCount": 3}
    )
    assert not has_already_flushed_for_current_compaction(
        {"compactionCount": 3, "memoryFlushCompactionCount": 2}
    )
    assert not has_already_flushed_for_current_compaction({"compactionCount": 1})
    assert has_already_flushed_for_current_compaction({"memoryFlushCompactionCount": 0})


def test_should_force_memory_flush_by_transcript_size_matches_openclaw_boundary():
    assert not should_force_memory_flush_by_transcript_size(
        transcript_byte_size=None,
        force_flush_transcript_bytes=100,
    )
    assert not should_force_memory_flush_by_transcript_size(
        transcript_byte_size=99,
        force_flush_transcript_bytes=100,
    )
    assert should_force_memory_flush_by_transcript_size(
        transcript_byte_size=100,
        force_flush_transcript_bytes=100,
    )
    assert should_force_memory_flush_by_transcript_size(
        transcript_byte_size=101,
        force_flush_transcript_bytes=100,
    )


def test_should_force_memory_flush_by_transcript_size_requires_positive_threshold():
    assert not should_force_memory_flush_by_transcript_size(
        transcript_byte_size=100,
        force_flush_transcript_bytes=0,
    )
    assert not should_force_memory_flush_by_transcript_size(
        transcript_byte_size=100,
        force_flush_transcript_bytes=-1,
    )


def test_should_run_memory_flush_trigger_allows_transcript_size_force_path():
    assert should_run_memory_flush_trigger(
        entry={"totalTokens": 1, "compactionCount": 1},
        context_window_tokens=100_000,
        reserve_tokens_floor=20_000,
        soft_threshold_tokens=4_000,
        transcript_byte_size=2_000,
        force_flush_transcript_bytes=2_000,
    )


def test_should_run_memory_flush_trigger_blocks_force_path_after_same_cycle_flush():
    assert not should_run_memory_flush_trigger(
        entry={
            "totalTokens": 1,
            "compactionCount": 1,
            "memoryFlushCompactionCount": 1,
        },
        context_window_tokens=100_000,
        reserve_tokens_floor=20_000,
        soft_threshold_tokens=4_000,
        transcript_byte_size=2_000,
        force_flush_transcript_bytes=2_000,
    )


def test_should_run_memory_flush_trigger_blocks_runtime_skip_flags():
    assert not should_run_memory_flush_trigger(
        entry={"totalTokens": 99_000},
        context_window_tokens=100_000,
        reserve_tokens_floor=5_000,
        soft_threshold_tokens=2_000,
        transcript_byte_size=2_000,
        force_flush_transcript_bytes=2_000,
        memory_flush_writable=False,
    )
    assert not should_run_memory_flush_trigger(
        entry={"totalTokens": 99_000},
        context_window_tokens=100_000,
        reserve_tokens_floor=5_000,
        soft_threshold_tokens=2_000,
        transcript_byte_size=2_000,
        force_flush_transcript_bytes=2_000,
        is_heartbeat=True,
    )
    assert not should_run_memory_flush_trigger(
        entry={"totalTokens": 99_000},
        context_window_tokens=100_000,
        reserve_tokens_floor=5_000,
        soft_threshold_tokens=2_000,
        transcript_byte_size=2_000,
        force_flush_transcript_bytes=2_000,
        is_cli=True,
    )


def test_explain_memory_flush_trigger_reports_token_threshold_reason():
    decision = explain_memory_flush_trigger(
        entry={"totalTokens": 85},
        context_window_tokens=100,
        reserve_tokens_floor=10,
        soft_threshold_tokens=5,
    )

    assert decision.should_flush is True
    assert decision.reason == "token_threshold"
    assert decision.total_tokens == 85
    assert decision.threshold == 85


def test_explain_memory_flush_trigger_reports_transcript_size_reason():
    decision = explain_memory_flush_trigger(
        entry={"totalTokens": 1},
        context_window_tokens=100_000,
        reserve_tokens_floor=20_000,
        soft_threshold_tokens=4_000,
        transcript_byte_size=2_000,
        force_flush_transcript_bytes=2_000,
    )

    assert decision.should_flush is True
    assert decision.reason == "transcript_size"
    assert decision.transcript_size_gate is True
    assert decision.token_gate is False


def test_explain_memory_flush_trigger_reports_same_cycle_duplicate():
    decision = explain_memory_flush_trigger(
        entry={
            "totalTokens": 99_000,
            "compactionCount": 1,
            "memoryFlushCompactionCount": 1,
        },
        context_window_tokens=100_000,
        reserve_tokens_floor=5_000,
        soft_threshold_tokens=2_000,
        transcript_byte_size=2_000,
        force_flush_transcript_bytes=2_000,
    )

    assert decision.should_flush is False
    assert decision.reason == "already_flushed"
    assert decision.already_flushed is True


def test_explain_memory_flush_trigger_reports_runtime_skip_reason():
    decision = explain_memory_flush_trigger(
        entry={"totalTokens": 99_000},
        context_window_tokens=100_000,
        reserve_tokens_floor=5_000,
        soft_threshold_tokens=2_000,
        memory_flush_writable=False,
    )

    assert decision.should_flush is False
    assert decision.reason == "runtime_skip:not_writable"


def test_explain_memory_flush_trigger_reports_under_threshold_reason():
    decision = explain_memory_flush_trigger(
        entry={"totalTokens": 10_000},
        context_window_tokens=100_000,
        reserve_tokens_floor=20_000,
        soft_threshold_tokens=10_000,
    )

    assert decision.should_flush is False
    assert decision.reason == "under_threshold"
    assert decision.total_tokens == 10_000
    assert decision.threshold == 70_000


# Flush failure exhaustion: OpenClaw commit 4e84d0eaa5,
# src/auto-reply/reply/agent-runner-memory.ts:77-79 (constants) and
# 1432-1533 (success reset / failure persistence / exhaustion suppression).


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


def test_record_memory_flush_failure_persists_failure_fields():
    outcome = record_memory_flush_failure(
        {"totalTokens": 90_000, "compactionCount": 2},
        now_ms=1_777_824_000_000,
        error=RuntimeError("flush run failed"),
    )

    assert outcome.failure_count == 1
    assert outcome.exhausted is False
    assert outcome.entry["memoryFlushFailureCount"] == 1
    assert outcome.entry["memoryFlushLastFailedAt"] == 1_777_824_000_000
    assert outcome.entry["memoryFlushLastFailureError"] == "flush run failed"
    # Below MAX_FLUSH_FAILURES the duplicate guard must stay open for retries.
    assert "memoryFlushAt" not in outcome.entry
    assert "memoryFlushCompactionCount" not in outcome.entry
    assert not has_already_flushed_for_current_compaction(outcome.entry)


def test_record_memory_flush_failure_exhausts_after_three_consecutive_failures():
    entry = {"totalTokens": 99_000, "compactionCount": 2}
    for attempt in range(1, MAX_FLUSH_FAILURES + 1):
        outcome = record_memory_flush_failure(
            entry, now_ms=1_777_824_000_000 + attempt, error=f"failure {attempt}"
        )
        entry = outcome.entry
        assert outcome.failure_count == attempt
        assert outcome.exhausted is (attempt == MAX_FLUSH_FAILURES)

    # Exhaustion stamps memoryFlushAt + memoryFlushCompactionCount so the
    # same-compaction duplicate guard suppresses retries.
    assert entry["memoryFlushAt"] == 1_777_824_000_000 + MAX_FLUSH_FAILURES
    assert entry["memoryFlushCompactionCount"] == 2
    assert has_already_flushed_for_current_compaction(entry)
    decision = explain_memory_flush_trigger(
        entry=entry,
        context_window_tokens=100_000,
        reserve_tokens_floor=5_000,
        soft_threshold_tokens=2_000,
    )
    assert decision.should_flush is False
    assert decision.reason == "already_flushed"


def test_flush_retries_resume_after_next_compaction_increments_count():
    entry = {"totalTokens": 99_000, "compactionCount": 2}
    for attempt in range(MAX_FLUSH_FAILURES):
        entry = record_memory_flush_failure(
            entry, now_ms=1_777_824_000_000 + attempt, error="boom"
        ).entry
    assert has_already_flushed_for_current_compaction(entry)

    next_cycle = {**entry, "compactionCount": 3}

    assert not has_already_flushed_for_current_compaction(next_cycle)
    assert should_run_memory_flush(
        entry=next_cycle,
        context_window_tokens=100_000,
        reserve_tokens_floor=5_000,
        soft_threshold_tokens=2_000,
    )


def test_record_memory_flush_success_resets_failure_fields():
    entry = {
        "totalTokens": 90_000,
        "compactionCount": 4,
        "memoryFlushFailureCount": 2,
        "memoryFlushLastFailedAt": 1_777_823_000_000,
        "memoryFlushLastFailureError": "boom",
    }

    updated = record_memory_flush_success(entry, now_ms=1_777_824_000_000)

    assert updated["memoryFlushAt"] == 1_777_824_000_000
    assert updated["memoryFlushCompactionCount"] == 4
    assert updated["memoryFlushFailureCount"] == 0
    # Cleared fields are persisted as undefined upstream, i.e. dropped keys.
    assert "memoryFlushLastFailedAt" not in updated
    assert "memoryFlushLastFailureError" not in updated
    assert has_already_flushed_for_current_compaction(updated)


def test_record_memory_flush_success_honors_explicit_flushed_compaction_count():
    updated = record_memory_flush_success(
        {"compactionCount": 7},
        now_ms=1_777_824_000_000,
        flushed_compaction_count=6,
    )

    assert updated["memoryFlushCompactionCount"] == 6


# CLI runtime skip: followupUsesCliRuntime treats both CLI providers and
# session-pinned CLI runtime aliases as CLI runs
# (src/auto-reply/reply/agent-runner-memory.ts:263-278).


def test_followup_uses_cli_runtime_for_direct_cli_provider():
    assert followup_uses_cli_runtime(
        provider="claude-cli",
        cli_providers=("claude-cli",),
    )
    assert not followup_uses_cli_runtime(
        provider="anthropic",
        cli_providers=("claude-cli",),
    )


def test_followup_uses_cli_runtime_for_session_pinned_runtime_alias():
    assert followup_uses_cli_runtime(
        provider="openai",
        session_entry={"agentRuntimeOverride": " Codex "},
        cli_runtime_bindings=(("openai", "codex"),),
    )
    # An alias bound to a different provider does not flag this followup.
    assert not followup_uses_cli_runtime(
        provider="anthropic",
        session_entry={"agentRuntimeOverride": "codex"},
        cli_runtime_bindings=(("openai", "codex"),),
    )
    # No pinned runtime override means no alias-based skip.
    assert not followup_uses_cli_runtime(
        provider="openai",
        session_entry={},
        cli_runtime_bindings=(("openai", "codex"),),
    )


def test_validate_daily_memory_target_accepts_only_canonical_daily_file():
    assert (
        validate_daily_memory_target("memory/2026-05-03.md")
        == "memory/2026-05-03.md"
    )


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
