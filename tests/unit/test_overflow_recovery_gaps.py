from memory_core.overflow_recovery import (
    decide_provider_overflow_recovery,
    extract_observed_overflow_token_count,
    is_context_overflow_error,
    is_context_overflow_error_from_tables,
    is_likely_context_overflow_error,
    is_no_real_conversation_compaction_noop,
)


def test_provider_fallback_candidates_need_the_candidate_gate():
    assert is_context_overflow_error("AWS Bedrock: Input is too long for this model")
    assert is_context_overflow_error("ollama error: context length exceeded, too many tokens")
    assert is_context_overflow_error("request (4096 tokens) exceeds the available context size")
    # A rate-limit wording is not a candidate even when a fallback pattern matches.
    assert not is_context_overflow_error("rate limit: input is too long for this model")
    assert is_context_overflow_error_from_tables(
        "Cohere: total tokens 130000 exceeds the model's max limit"
    )
    assert not is_likely_context_overflow_error("billing: maximum token limit exceeded for your plan")
    assert not is_likely_context_overflow_error("The prompt template is too long")


def test_backticked_max_tokens_form_is_observed():
    message = "input length and `max_tokens` exceed context limit: 156321 + 48384 > 200000"
    assert extract_observed_overflow_token_count(message) == 204705


def test_parked_code_mode_work_blocks_the_continuation_after_a_rotating_compaction():
    common = {
        "error_text": "request_too_large: Request size exceeds context window",
        "overflow_compaction_attempts": 1,
        "attempt_compaction_count": 0,
        "preflight_source": "mid-turn",
        "preflight_route": "compact_then_truncate",
        "compaction_attempted": True,
        "compaction_succeeded": True,
        "has_oversized_tool_results": True,
    }
    parked = decide_provider_overflow_recovery(
        previous_session_id="s1", code_mode_suspended=True, **common
    )
    assert parked.action == "give_up"
    assert parked.parked_work_blocks_continuation is True
    assert parked.should_retry is False
    # The post-compaction truncation of compact_then_truncate still runs; the fallback does not.
    assert parked.should_truncate_tool_results is True
    assert parked.error_kind == "context_overflow"
    for override in ({"previous_session_id": None}, {"code_mode_suspended": False}):
        kwargs = {"previous_session_id": "s1", "code_mode_suspended": True, **override}
        assert decide_provider_overflow_recovery(**common, **kwargs).action == "retry_after_compaction"
    not_midturn = {**common, "preflight_source": None, "preflight_route": "compact_only"}
    assert (
        decide_provider_overflow_recovery(
            previous_session_id="s1", code_mode_suspended=True, **not_midturn
        ).action
        == "retry_after_compaction"
    )
    unsafe = decide_provider_overflow_recovery(
        previous_session_id="s1",
        code_mode_suspended=True,
        current_attempt_replay_safe=False,
        had_potential_side_effects=True,
        **not_midturn,
    )
    assert unsafe.parked_work_blocks_continuation is True
    assert unsafe.user_visible_error_text.endswith(
        "Completed tool actions were not replayed; verify their effects before retrying."
    )


def test_no_real_conversation_noop_resets_the_snapshot_and_retries():
    common = {
        "error_text": "Context overflow: prompt too large for the model (precheck).",
        "overflow_compaction_attempts": 1,
        "attempt_compaction_count": 0,
        "preflight_route": "compact_only",
        "compaction_attempted": True,
        "compaction_succeeded": False,
        "compaction_ok": True,
        "compaction_reason": "no real conversation messages",
        "prompt_error_source": "precheck",
        "failed_compaction_reason": "no real conversation messages",
    }
    decision = decide_provider_overflow_recovery(**common)
    assert decision.action == "reset_snapshot_and_retry"
    assert decision.reset_context_snapshot is True and decision.should_retry is True
    assert decision.continue_from_current_transcript is False

    mid_turn = decide_provider_overflow_recovery(**{**common, "preflight_source": "mid-turn"})
    assert mid_turn.continue_from_current_transcript is True
    assert mid_turn.next_prompt_override is not None

    for override in (
        {"compaction_ok": False},
        {"compaction_reason": "nothing to compact"},
        {"preflight_route": None},
    ):
        other = decide_provider_overflow_recovery(**{**common, **override})
        assert other.action == "give_up", override
    assert is_no_real_conversation_compaction_noop(
        ok=True, compacted=False, reason="no real conversation messages"
    )
    assert not is_no_real_conversation_compaction_noop(
        ok=True, compacted=True, reason="no real conversation messages"
    )


def test_truncation_fallback_retry_continues_from_the_transcript_when_not_replay_safe():
    decision = decide_provider_overflow_recovery(
        error_text="request_too_large: Request size exceeds context window",
        overflow_compaction_attempts=1,
        attempt_compaction_count=0,
        compaction_attempted=True,
        compaction_succeeded=False,
        has_oversized_tool_results=True,
        current_attempt_replay_safe=False,
    )
    assert decision.action == "truncate_tool_results"
    assert decision.continue_from_current_transcript is True
    assert decision.suppress_next_user_message_persistence is True
