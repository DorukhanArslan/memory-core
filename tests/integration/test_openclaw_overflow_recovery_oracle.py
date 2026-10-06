"""Overflow recovery beyond the run-loop scenarios, against the real ``recoverEmbeddedRunOverflow``.

Covers what ``test_openclaw_run_loop_oracle.py`` leaves open: parked Code Mode work blocking the
mid-turn continuation after a session-rotating compaction, the no-real-conversation compaction
no-op that resets the stale token snapshot, and the failed-compaction texts. One Vitest run (the
upstream mock harness of ``run.overflow-context-recovery.test.ts``) records every scenario; Python
replays the same scenario through ``decide_provider_overflow_recovery`` and must reach the same
action, user text, side-effect counts and retry preparation.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_run_loop_oracle import run_overflow_recovery_oracle
from memory_core.overflow_recovery import (
    MAX_OVERFLOW_COMPACTION_ATTEMPTS,
    decide_provider_overflow_recovery,
    is_no_real_conversation_compaction_noop,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENCLAW_ORACLE_REPO"),
    reason="OPENCLAW_ORACLE_REPO is not set",
)

DEFAULT_ERROR = "request_too_large: Request size exceeds context window"
MID_TURN = {"route": "compact_only", "source": "mid-turn"}
NOOP = {"ok": True, "compacted": False, "reason": "no real conversation messages"}
SUCCESS = {
    "ok": True,
    "compacted": True,
    "result": {"summary": "Compacted session", "tokensBefore": 150_000, "tokensAfter": 80_000},
}

SCENARIOS: list[dict[str, Any]] = [
    # Parked Code Mode work: the compaction rotated the session, so `wait` cannot redeem it.
    {"name": "parked_mid_turn_rotated", "preflightRecovery": MID_TURN, "codeModeSuspended": True, "rotate": True},
    {
        "name": "parked_unsafe_replay_rotated",
        "codeModeSuspended": True,
        "hadPotentialSideEffects": True,
        "rotate": True,
    },
    {"name": "parked_replay_unsafe_without_effects", "codeModeSuspended": True, "replayUnsafe": True, "rotate": True},
    {"name": "parked_but_not_rotated", "preflightRecovery": MID_TURN, "codeModeSuspended": True, "rotate": False},
    {
        "name": "suspended_replay_safe_rotated",
        "preflightRecovery": {"route": "compact_only"},
        "codeModeSuspended": True,
        "rotate": True,
    },
    {"name": "rotated_mid_turn_without_suspension", "preflightRecovery": MID_TURN, "rotate": True},
    {
        "name": "parked_blocks_truncation_fallback",
        "preflightRecovery": MID_TURN,
        "codeModeSuspended": True,
        "rotate": True,
        "oversized": True,
        "truncateHelps": True,
    },
    {
        "name": "parked_compact_then_truncate",
        "preflightRecovery": {"route": "compact_then_truncate", "source": "mid-turn"},
        "codeModeSuspended": True,
        "rotate": True,
        "truncateHelps": True,
    },
    {
        "name": "parked_after_in_attempt_compaction",
        "preflightRecovery": MID_TURN,
        "codeModeSuspended": True,
        "rotate": True,
        "attemptCompactionCount": 1,
    },
    # No-real-conversation no-op: reset the stale snapshot and retry instead of failing.
    {"name": "noop_precheck_reset", "preflightRecovery": {"route": "compact_only"}, "compactResult": NOOP, "seedSnapshot": True},
    {"name": "noop_mid_turn_reset", "preflightRecovery": MID_TURN, "compactResult": NOOP, "seedSnapshot": True},
    {
        "name": "noop_replay_unsafe_reset",
        "preflightRecovery": {"route": "compact_only"},
        "compactResult": NOOP,
        "replayUnsafe": True,
    },
    {"name": "noop_without_preflight_is_a_failed_compaction", "compactResult": NOOP},
    {
        "name": "noop_without_preflight_truncates",
        "compactResult": NOOP,
        "oversized": True,
        "truncateHelps": True,
    },
    {
        "name": "noop_reason_must_match_exactly",
        "preflightRecovery": {"route": "compact_only"},
        "terminalSource": "precheck",
        "compactResult": {"ok": True, "compacted": False, "reason": "nothing to compact"},
    },
    {
        "name": "noop_requires_ok",
        "preflightRecovery": {"route": "compact_only"},
        "terminalSource": "precheck",
        "compactResult": {"ok": False, "compacted": False, "reason": "no real conversation messages"},
    },
    {
        "name": "noop_with_substring_reason_is_not_a_noop",
        "preflightRecovery": {"route": "compact_only"},
        "terminalSource": "precheck",
        "compactResult": {"ok": True, "compacted": False, "reason": "No real conversation messages"},
    },
    {
        "name": "precheck_compaction_timeout_text",
        "preflightRecovery": {"route": "compact_only"},
        "terminalSource": "precheck",
        "compactResult": {"ok": False, "compacted": False, "reason": "compaction timed out"},
    },
    {
        "name": "precheck_compaction_failure_with_side_effects",
        "preflightRecovery": {"route": "compact_only"},
        "terminalSource": "precheck",
        "compactResult": {"ok": False, "compacted": False, "reason": "model refused"},
        "hadPotentialSideEffects": True,
    },
    {
        "name": "truncation_fallback_continues_from_transcript",
        "compactResult": {"ok": True, "compacted": False, "reason": "nothing to compact"},
        "oversized": True,
        "truncateHelps": True,
        "replayUnsafe": True,
    },
    {
        "name": "truncation_that_does_not_help_surfaces",
        "compactResult": {"ok": True, "compacted": False, "reason": "nothing to compact"},
        "oversized": True,
        "truncateHelps": False,
    },
    {
        "name": "compaction_attempts_exhausted",
        "startAttempts": MAX_OVERFLOW_COMPACTION_ATTEMPTS,
    },
]


def _simulate(scenario: dict[str, Any]) -> dict[str, Any]:
    """The Python decision function driven the way the run loop drives it."""

    preflight = scenario.get("preflightRecovery") or {}
    unsafe = bool(scenario.get("replayUnsafe") or scenario.get("hadPotentialSideEffects"))
    common: dict[str, Any] = {
        "error_text": scenario.get("errorText", DEFAULT_ERROR),
        "context_tokens": 200_000,
        "attempt_compaction_count": scenario.get("attemptCompactionCount", 0),
        "preflight_source": preflight.get("source"),
        "preflight_route": preflight.get("route"),
        "has_preflight_recovery": bool(preflight),
        "current_attempt_replay_safe": not unsafe,
        "had_potential_side_effects": bool(scenario.get("hadPotentialSideEffects")),
        "prompt_error_source": scenario.get("terminalSource", "prompt"),
    }
    attempts = scenario.get("startAttempts", 0)
    out = {
        "compactCalls": 0,
        "truncateCalls": 0,
        "truncateProtectTrailing": None,
        "markOwnedTranscriptRetry": 0,
        "prepareCurrentTranscriptRetry": 0,
        "prepareCompactedTranscriptRetry": 0,
        "armPostCompactionGuard": 0,
        "onAutoCompactionSucceeded": 0,
        "resetSnapshotCalls": 0,
        "toolResultTruncationAttempted": False,
    }
    decision = decide_provider_overflow_recovery(overflow_compaction_attempts=attempts, **common)
    truncation_attempted = False
    if decision.action == "compact":
        out["compactCalls"] = 1
        attempts = decision.next_overflow_compaction_attempts
        result = scenario.get("compactResult", SUCCESS)
        compacted = result["compacted"]
        decision = decide_provider_overflow_recovery(
            overflow_compaction_attempts=attempts,
            compaction_attempted=True,
            compaction_succeeded=compacted,
            compaction_ok=result["ok"],
            compaction_reason=result.get("reason"),
            failed_compaction_reason=None if compacted else (result.get("reason") or "nothing to compact"),
            previous_session_id="session-1" if scenario.get("rotate") and compacted else None,
            code_mode_suspended=bool(scenario.get("codeModeSuspended")),
            has_oversized_tool_results=bool(scenario.get("oversized")),
            **common,
        )
        if compacted:
            out["armPostCompactionGuard"] = out["onAutoCompactionSucceeded"] = 1
        if decision.should_truncate_tool_results and decision.action in {"retry_after_compaction", "give_up"}:
            out["truncateCalls"] += 1
            out["truncateProtectTrailing"] = decision.protect_trailing_tool_results
        if decision.action == "truncate_tool_results":
            truncation_attempted = True
            out["truncateCalls"] += 1
            out["truncateProtectTrailing"] = decision.protect_trailing_tool_results
            if not scenario.get("truncateHelps"):
                decision = decide_provider_overflow_recovery(
                    overflow_compaction_attempts=attempts,
                    compaction_attempted=True,
                    compaction_succeeded=compacted,
                    compaction_ok=result["ok"],
                    compaction_reason=result.get("reason"),
                    failed_compaction_reason=result.get("reason") or "nothing to compact",
                    tool_result_truncation_attempted=True,
                    has_oversized_tool_results=True,
                    **common,
                )
    elif decision.action == "truncate_tool_results":
        truncation_attempted = True
        out["truncateCalls"] = 1
        out["truncateProtectTrailing"] = decision.protect_trailing_tool_results
        if not scenario.get("truncateHelps"):
            decision = decide_provider_overflow_recovery(
                overflow_compaction_attempts=attempts, tool_result_truncation_attempted=True, **common
            )
    out["toolResultTruncationAttempted"] = truncation_attempted
    retried = decision.should_retry or (decision.action == "truncate_tool_results" and scenario.get("truncateHelps"))
    action = "retry" if retried else "surface" if decision.action == "give_up" else "none"
    if decision.action == "reset_snapshot_and_retry":
        out["resetSnapshotCalls"] = 1
    elif retried:
        out["markOwnedTranscriptRetry"] = 1
    if retried:
        if decision.continue_from_current_transcript:
            out["prepareCurrentTranscriptRetry"] = 1
        elif decision.action == "retry_after_compaction":
            out["prepareCompactedTranscriptRetry"] = 1
    out["overflowCompactionAttempts"] = decision.next_overflow_compaction_attempts
    return {
        "name": scenario["name"],
        "action": action,
        "kind": decision.error_kind if action == "surface" else None,
        "userText": decision.user_visible_error_text if action == "surface" else None,
        **out,
    }


@pytest.fixture(scope="module")
def recorded() -> dict[str, dict]:
    result = run_overflow_recovery_oracle(
        repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), scenarios=SCENARIOS
    )
    assert result["ok"] is True
    return {scenario["name"]: scenario for scenario in result["scenarios"]}


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
def test_recover_embedded_run_overflow_matches_python_decision(recorded, scenario):
    oracle = dict(recorded[scenario["name"]])
    # A successful compaction records its own tokens after, so the snapshot is only a signal
    # of the no-op reset, which the dedicated test below asserts.
    oracle.pop("snapshotCleared")
    expected = _simulate(scenario)
    assert expected == oracle


def test_parked_code_mode_work_blocks_the_mid_turn_continuation(recorded):
    parked = recorded["parked_mid_turn_rotated"]
    assert parked["action"] == "surface"
    assert parked["kind"] == "context_overflow"
    assert parked["compactCalls"] == 1
    # The compaction stays committed, but nothing retries or truncates around the parked work.
    assert parked["armPostCompactionGuard"] == 1
    assert parked["markOwnedTranscriptRetry"] == 0
    assert parked["prepareCurrentTranscriptRetry"] == 0
    assert recorded["parked_blocks_truncation_fallback"]["truncateCalls"] == 0
    assert recorded["parked_compact_then_truncate"]["truncateCalls"] == 1
    # Without a rotation, without the mid-turn requirement, or without suspension it retries.
    for name in (
        "parked_but_not_rotated",
        "suspended_replay_safe_rotated",
        "rotated_mid_turn_without_suspension",
    ):
        assert recorded[name]["action"] == "retry", name


def test_no_real_conversation_noop_resets_the_snapshot_and_retries(recorded):
    for name in ("noop_precheck_reset", "noop_mid_turn_reset", "noop_replay_unsafe_reset"):
        scenario = recorded[name]
        assert scenario["action"] == "retry", name
        assert scenario["resetSnapshotCalls"] == 1, name
        assert scenario["markOwnedTranscriptRetry"] == 0, name
        assert scenario["armPostCompactionGuard"] == 0, name
    assert recorded["noop_precheck_reset"]["snapshotCleared"] is True
    assert recorded["noop_mid_turn_reset"]["prepareCurrentTranscriptRetry"] == 1
    assert recorded["noop_without_preflight_is_a_failed_compaction"]["resetSnapshotCalls"] == 0
    assert recorded["noop_without_preflight_is_a_failed_compaction"]["action"] == "surface"
    # Only the exact reason of an ok, not-compacted result is the no-op.
    for name in ("noop_reason_must_match_exactly", "noop_requires_ok", "noop_with_substring_reason_is_not_a_noop"):
        assert recorded[name]["resetSnapshotCalls"] == 0, name
        assert recorded[name]["kind"] == "compaction_failure", name


def test_no_real_conversation_noop_predicate_matches_upstream_contract():
    assert is_no_real_conversation_compaction_noop(ok=True, compacted=False, reason="no real conversation messages")
    assert not is_no_real_conversation_compaction_noop(ok=True, compacted=True, reason="no real conversation messages")
    assert not is_no_real_conversation_compaction_noop(ok=False, compacted=False, reason="no real conversation messages")
    assert not is_no_real_conversation_compaction_noop(ok=True, compacted=False, reason="nothing to compact")
    assert not is_no_real_conversation_compaction_noop(ok=True, reason="no real conversation messages")
    assert not is_no_real_conversation_compaction_noop()
