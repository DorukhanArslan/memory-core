import os
from pathlib import Path

import pytest

from demo.openclaw_run_loop_oracle import run_overflow_run_loop_oracle
from memory_core.overflow_recovery import MAX_OVERFLOW_COMPACTION_ATTEMPTS


pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)


def test_real_openclaw_run_loop_overflow_recovery_scenarios():
    repo_path = Path(os.environ["OPENCLAW_ORACLE_REPO"])

    result = run_overflow_run_loop_oracle(repo_path=repo_path)

    assert result["ok"] is True
    scenarios = {scenario["name"]: scenario for scenario in result["scenarios"]}

    assert scenarios["successful_compaction_retries"] == {
        "name": "successful_compaction_retries",
        "attemptCalls": 2,
        "compactCalls": 1,
        "truncateCalls": 0,
        "errorKind": None,
        "payloadIsError": None,
    }
    assert scenarios["attempt_level_compaction_retries_without_extra_compaction"] == {
        "name": "attempt_level_compaction_retries_without_extra_compaction",
        "attemptCalls": 2,
        "compactCalls": 0,
        "truncateCalls": 0,
        "errorKind": None,
        "payloadIsError": None,
    }
    assert scenarios["failed_compaction_uses_tool_truncation_fallback"] == {
        "name": "failed_compaction_uses_tool_truncation_fallback",
        "attemptCalls": 2,
        "compactCalls": 1,
        "truncateCalls": 1,
        "errorKind": None,
        "payloadIsError": None,
    }
    assert scenarios["compact_then_truncate_runs_after_compaction"] == {
        "name": "compact_then_truncate_runs_after_compaction",
        "attemptCalls": 2,
        "compactCalls": 1,
        "truncateCalls": 1,
        "errorKind": None,
        "payloadIsError": None,
    }
    assert scenarios["assistant_error_overflow_compacts_and_retries"] == {
        "name": "assistant_error_overflow_compacts_and_retries",
        "attemptCalls": 2,
        "compactCalls": 1,
        "truncateCalls": 0,
        "errorKind": None,
        "payloadIsError": None,
    }
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
    assert scenarios["give_up_after_max_compaction_attempts"] == {
        "name": "give_up_after_max_compaction_attempts",
        "attemptCalls": MAX_OVERFLOW_COMPACTION_ATTEMPTS + 1,
        "compactCalls": MAX_OVERFLOW_COMPACTION_ATTEMPTS,
        "truncateCalls": 0,
        "errorKind": "context_overflow",
        "payloadIsError": True,
    }
