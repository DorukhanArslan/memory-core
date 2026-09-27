import os
from pathlib import Path

import pytest

from demo.openclaw_run_loop_oracle import run_overflow_run_loop_oracle
from memory_core.overflow_recovery import (
    MAX_OVERFLOW_COMPACTION_ATTEMPTS,
    decide_provider_overflow_recovery,
)


pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)


@pytest.fixture(scope="module")
def scenarios() -> dict[str, dict]:
    # One Vitest run records every scenario; each test below checks one of them.
    result = run_overflow_run_loop_oracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]))
    assert result["ok"] is True
    return {scenario["name"]: scenario for scenario in result["scenarios"]}


def test_real_openclaw_run_loop_successful_compaction_retries(scenarios):
    assert scenarios["successful_compaction_retries"] == {
        "name": "successful_compaction_retries",
        "attemptCalls": 2,
        "compactCalls": 1,
        "truncateCalls": 0,
        "errorKind": None,
        "payloadIsError": None,
    }


def test_real_openclaw_run_loop_attempt_level_compaction_retries(scenarios):
    assert scenarios["attempt_level_compaction_retries_without_extra_compaction"] == {
        "name": "attempt_level_compaction_retries_without_extra_compaction",
        "attemptCalls": 2,
        "compactCalls": 0,
        "truncateCalls": 0,
        "errorKind": None,
        "payloadIsError": None,
    }


def test_real_openclaw_run_loop_failed_compaction_uses_tool_truncation(scenarios):
    fallback_decision = decide_provider_overflow_recovery(
        error_text="request_too_large: Request size exceeds model context window",
        overflow_compaction_attempts=1,
        attempt_compaction_count=0,
        compaction_attempted=True,
        compaction_succeeded=False,
        has_oversized_tool_results=True,
    )
    assert fallback_decision.action == "truncate_tool_results"
    assert scenarios["failed_compaction_uses_tool_truncation_fallback"] == {
        "name": "failed_compaction_uses_tool_truncation_fallback",
        "attemptCalls": 2,
        "compactCalls": 1,
        "truncateCalls": 1,
        "errorKind": None,
        "payloadIsError": None,
        # run.ts:2937 only protects trailing tool results on the
        # compact_then_truncate preflight route; this scenario has none.
        "truncateProtectTrailing": fallback_decision.protect_trailing_tool_results,
    }


def test_real_openclaw_run_loop_compact_then_truncate(scenarios):
    post_compaction_decision = decide_provider_overflow_recovery(
        error_text="Context overflow: prompt too large for the model (precheck).",
        overflow_compaction_attempts=1,
        attempt_compaction_count=0,
        preflight_route="compact_then_truncate",
        compaction_attempted=True,
        compaction_succeeded=True,
    )
    assert post_compaction_decision.action == "retry_after_compaction"
    assert post_compaction_decision.should_truncate_tool_results is True
    assert scenarios["compact_then_truncate_runs_after_compaction"] == {
        "name": "compact_then_truncate_runs_after_compaction",
        "attemptCalls": 2,
        "compactCalls": 1,
        "truncateCalls": 1,
        "errorKind": None,
        "payloadIsError": None,
        # run.ts:2873 sets protectTrailingToolResults on the post-compaction
        # truncation of the compact_then_truncate route.
        "truncateProtectTrailing": post_compaction_decision.protect_trailing_tool_results,
    }


def test_real_openclaw_run_loop_assistant_error_overflow(scenarios):
    assert scenarios["assistant_error_overflow_compacts_and_retries"] == {
        "name": "assistant_error_overflow_compacts_and_retries",
        "attemptCalls": 2,
        "compactCalls": 1,
        "truncateCalls": 0,
        "errorKind": None,
        "payloadIsError": None,
    }


def test_real_openclaw_run_loop_mid_turn_precheck_continuation(scenarios):
    assert scenarios["mid_turn_precheck_continues_from_transcript"] == {
        "name": "mid_turn_precheck_continues_from_transcript",
        "attemptCalls": 2,
        "compactCalls": 1,
        "truncateCalls": 0,
        "errorKind": None,
        "payloadIsError": None,
        "secondPromptIncludesContinuation": True,
        "secondSuppressesUserPersistence": True,
    }


def test_real_openclaw_run_loop_gives_up_after_max_compaction_attempts(scenarios):
    assert scenarios["give_up_after_max_compaction_attempts"] == {
        "name": "give_up_after_max_compaction_attempts",
        "attemptCalls": MAX_OVERFLOW_COMPACTION_ATTEMPTS + 1,
        "compactCalls": MAX_OVERFLOW_COMPACTION_ATTEMPTS,
        "truncateCalls": 0,
        "errorKind": "context_overflow",
        "payloadIsError": True,
    }
