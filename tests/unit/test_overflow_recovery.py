from memory_core.overflow_recovery import (
    MAX_OVERFLOW_COMPACTION_ATTEMPTS,
    classify_overflow_error,
    decide_provider_overflow_recovery,
    extract_observed_overflow_token_count,
    is_compaction_failure_error,
    is_context_overflow_error,
    is_likely_context_overflow_error,
)


def test_likely_context_overflow_classifier_matches_openclaw_examples():
    assert is_likely_context_overflow_error("Context window exceeded: requested 12000 tokens")
    assert is_likely_context_overflow_error("Prompt too large for this model")
    assert not is_likely_context_overflow_error("429 Too Many Requests: request exceeds rate limit")
    assert not is_likely_context_overflow_error("Model context window too small (minimum is 128k tokens)")


def test_strict_overflow_matches_configured_context_size_error():
    assert is_context_overflow_error(
        "the prompt has 250,000 tokens, but the configured context size is 200,000 tokens"
    )
    assert not is_context_overflow_error(
        "the configured context size is 200,000 tokens for this deployment"
    )


def test_observed_overflow_token_count_extracts_provider_counts():
    assert (
        extract_observed_overflow_token_count(
            '400 {"message":"prompt is too long: 277403 tokens > 200000 maximum"}'
        )
        == 277403
    )
    assert (
        extract_observed_overflow_token_count(
            "Invalid request: Your request exceeded model token limit: 262144 (requested: 291351)"
        )
        == 291351
    )
    assert (
        extract_observed_overflow_token_count(
            "input length and max_tokens exceed context limit (i.e 156321 + 48384 > 200000)"
        )
        == 204705
    )
    assert extract_observed_overflow_token_count("Prompt too large for this model") is None


def test_compaction_failure_is_overflow_with_compaction_terms():
    assert is_compaction_failure_error("Summarization failed: context window exceeded")
    assert is_compaction_failure_error("auto-compaction failed due to context overflow")
    assert not is_compaction_failure_error("Context overflow: prompt too large")


def test_overflow_classification_uses_context_tokens_when_provider_count_is_missing():
    result = classify_overflow_error("Prompt too large for this model", context_tokens=200_000)

    assert result.is_overflow is True
    assert result.observed_tokens is None
    assert result.tokens_for_compaction == 200_001


def test_provider_overflow_recovery_retries_without_second_compaction_after_attempt_compaction():
    decision = decide_provider_overflow_recovery(
        error_text="Context window exceeded: requested 12000 tokens",
        overflow_compaction_attempts=0,
        attempt_compaction_count=1,
    )

    assert decision.action == "retry_without_compaction"
    assert decision.next_overflow_compaction_attempts == 1
    assert decision.should_retry is True
    assert decision.should_compact is False


def test_provider_overflow_recovery_runs_explicit_compaction_before_truncation_fallback():
    decision = decide_provider_overflow_recovery(
        error_text="Context window exceeded: requested 12000 tokens",
        overflow_compaction_attempts=0,
        attempt_compaction_count=0,
    )

    assert decision.action == "compact"
    assert decision.next_overflow_compaction_attempts == 1
    assert decision.should_retry is False
    assert decision.should_compact is True
    assert decision.tokens_for_compaction == 12000


def test_provider_overflow_recovery_tries_tool_truncation_after_failed_compaction():
    decision = decide_provider_overflow_recovery(
        error_text="Context window exceeded: requested 12000 tokens",
        overflow_compaction_attempts=1,
        attempt_compaction_count=0,
        compaction_attempted=True,
        compaction_succeeded=False,
        has_oversized_tool_results=True,
        tool_result_truncation_attempted=False,
    )

    assert decision.action == "truncate_tool_results"
    assert decision.should_truncate_tool_results is True
    assert decision.should_retry is False


def test_provider_overflow_recovery_gives_up_after_three_compaction_attempts():
    decision = decide_provider_overflow_recovery(
        error_text="Context window exceeded: requested 12000 tokens",
        overflow_compaction_attempts=MAX_OVERFLOW_COMPACTION_ATTEMPTS,
        attempt_compaction_count=0,
        tool_result_truncation_attempted=True,
    )

    assert decision.action == "give_up"
    assert decision.error_kind == "context_overflow"
    assert decision.should_retry is False
    assert decision.should_compact is False


def test_provider_request_size_ceiling_gives_up_without_compaction():
    from memory_core.overflow_recovery import is_provider_request_size_ceiling_error

    text = "Rate limit: TPM limit 30,000, requested 45,000 tokens: context overflow: prompt too large"
    assert is_provider_request_size_ceiling_error(text) is True
    assert is_provider_request_size_ceiling_error("TPM limit 30000, requested 100") is False
    decision = decide_provider_overflow_recovery(
        error_text=text, overflow_compaction_attempts=0, attempt_compaction_count=0
    )
    assert decision.action == "give_up"
    assert decision.should_compact is False


def test_replay_unsafe_attempt_continues_from_transcript_and_cautions_on_give_up():
    from memory_core.overflow_recovery import CONTINUATION_PROMPT, SIDE_EFFECT_CAUTION

    retry = decide_provider_overflow_recovery(
        error_text="Context overflow: prompt too large for the model.",
        overflow_compaction_attempts=0,
        attempt_compaction_count=1,
        current_attempt_replay_safe=False,
    )
    assert retry.action == "retry_without_compaction"
    assert retry.next_prompt_override == CONTINUATION_PROMPT
    assert retry.suppress_next_user_message_persistence is True
    gave_up = decide_provider_overflow_recovery(
        error_text="Context overflow: prompt too large for the model.",
        overflow_compaction_attempts=3,
        attempt_compaction_count=0,
        had_potential_side_effects=True,
    )
    assert gave_up.user_visible_error_text.endswith(SIDE_EFFECT_CAUTION)


def test_failed_preflight_compaction_is_a_compaction_failure():
    decision = decide_provider_overflow_recovery(
        error_text="Context overflow: prompt too large for the model (precheck).",
        overflow_compaction_attempts=3,
        attempt_compaction_count=0,
        prompt_error_source="precheck",
        failed_compaction_reason="compaction timed out",
    )
    assert decision.error_kind == "compaction_failure"
    assert decision.user_visible_error_text.startswith("Auto-compaction timed out")
