from __future__ import annotations

from dataclasses import dataclass
import re


MAX_OVERFLOW_COMPACTION_ATTEMPTS = 3
MID_TURN_PRECHECK_CONTINUATION_PROMPT = (
    "Continue from the current transcript after the latest tool result. Do not repeat the "
    "original user request, and do not rerun completed tools unless the transcript shows they "
    "are still needed."
)
OVERFLOW_RECOVERY_TEXT = (
    "Context overflow: prompt too large for the model. Try /reset (or /new) to start a fresh "
    "session, or use a larger-context model."
)


_CONTEXT_WINDOW_TOO_SMALL_RE = re.compile(r"context window.*(too small|minimum is)", re.I)
_CONTEXT_OVERFLOW_HINT_RE = re.compile(
    r"context.*overflow|"
    r"context window.*(too (?:large|long)|exceed|over|limit|max(?:imum)?|requested|sent|tokens)|"
    r"prompt.*(too (?:large|long)|exceed|over|limit|max(?:imum)?)|"
    r"(?:request|input).*(?:context|window|length|token).*"
    r"(too (?:large|long)|exceed|over|limit|max(?:imum)?)",
    re.I,
)
_RATE_LIMIT_HINT_RE = re.compile(
    r"rate limit|too many requests|requests per (?:minute|hour|day)|quota|throttl|429\b|"
    r"tokens per day",
    re.I,
)
_CONFIGURED_CONTEXT_SIZE_OVERFLOW_RE = re.compile(
    r"prompt has [\d,]+ tokens?, but the configured context size is [\d,]+ tokens?",
    re.I,
)
_OBSERVED_OVERFLOW_TOKEN_PATTERNS = (
    re.compile(r"prompt is too long:\s*([\d,]+)\s+tokens\s*>\s*[\d,]+\s+maximum", re.I),
    re.compile(
        r"prompt is too long:\s*([\d,]+)\s*,\s*model maximum context length\s*:\s*[\d,]+",
        re.I,
    ),
    re.compile(r"requested\s+([\d,]+)\s+tokens", re.I),
    re.compile(r"token limit\s*:\s*[\d,]+\s*\(requested\s*:\s*([\d,]+)\)", re.I),
    re.compile(r"resulted in\s+([\d,]+)\s+tokens", re.I),
)
_OBSERVED_OVERFLOW_TOKEN_SUM_PATTERNS = (
    re.compile(
        r"input length(?:\s+and\s+max_tokens)?\s+exceed\s+context"
        r"(?:\s+limit|\s+window)?\s*\(i\.e\s*([\d,]+)\s*\+\s*([\d,]+)\s*>\s*[\d,]+\)",
        re.I,
    ),
)


@dataclass(frozen=True)
class OverflowClassification:
    is_overflow: bool
    is_compaction_failure: bool
    observed_tokens: int | None
    tokens_for_compaction: int | None


@dataclass(frozen=True)
class ProviderOverflowRecoveryDecision:
    action: str
    should_retry: bool
    should_compact: bool
    should_truncate_tool_results: bool
    next_overflow_compaction_attempts: int
    continue_from_current_transcript: bool
    suppress_next_user_message_persistence: bool
    next_prompt_override: str | None
    tokens_for_compaction: int | None
    error_kind: str | None = None
    user_visible_error_text: str | None = None


def _lower(raw: str | None) -> str:
    return raw.lower() if isinstance(raw, str) else ""


def _has_rate_limit_tpm_hint(raw: str | None) -> bool:
    return bool(raw and (re.search(r"\btpm\b", raw, re.I) or "tokens per minute" in _lower(raw)))


def _is_reasoning_constraint_error(raw: str | None) -> bool:
    lower = _lower(raw)
    return (
        "reasoning is mandatory" in lower
        or "reasoning is required" in lower
        or "requires reasoning" in lower
        or ("reasoning" in lower and "cannot be disabled" in lower)
    )


def _is_rate_limit_error(raw: str | None) -> bool:
    return bool(raw and _RATE_LIMIT_HINT_RE.search(raw))


def _is_billing_error(raw: str | None) -> bool:
    lower = _lower(raw)
    return (
        "402" in lower
        or "payment required" in lower
        or "insufficient credits" in lower
        or "credit balance" in lower
        or ("billing" in lower and ("limit" in lower or "plan" in lower))
    )


def is_context_overflow_error(error_message: str | None) -> bool:
    if not error_message:
        return False
    lower = _lower(error_message)
    if _has_rate_limit_tpm_hint(error_message) or _is_reasoning_constraint_error(error_message):
        return False

    has_request_size_exceeds = "request size exceeds" in lower
    has_context_window = (
        "context window" in lower
        or "context length" in lower
        or "maximum context length" in lower
    )
    has_context_window_out_of_room = has_context_window and (
        "ran out of room" in lower or "ran out of space" in lower
    )
    return (
        "request_too_large" in lower
        or bool(_CONFIGURED_CONTEXT_SIZE_OVERFLOW_RE.search(error_message))
        or ("invalid_argument" in lower and "maximum number of tokens" in lower)
        or "request exceeds the maximum size" in lower
        or "context length exceeded" in lower
        or "maximum context length" in lower
        or "prompt is too long" in lower
        or "prompt too long" in lower
        or "exceeds model context window" in lower
        or "model token limit" in lower
        or ("input exceeds" in lower and "maximum number of tokens" in lower)
        or has_context_window_out_of_room
        or (has_request_size_exceeds and has_context_window)
        or "context overflow:" in lower
        or "exceed context limit" in lower
        or "exceeds the model's maximum context" in lower
        or ("max_tokens" in lower and "exceed" in lower and "context" in lower)
        or ("input length" in lower and "exceed" in lower and "context" in lower)
        or ("413" in lower and "too large" in lower)
        or "context_window_exceeded" in lower
        or "上下文过长" in error_message
        or "上下文超出" in error_message
        or "上下文长度超" in error_message
        or "超出最大上下文" in error_message
        or "请压缩上下文" in error_message
    )


def is_likely_context_overflow_error(error_message: str | None) -> bool:
    if not error_message:
        return False
    if (
        _has_rate_limit_tpm_hint(error_message)
        or _is_reasoning_constraint_error(error_message)
        or _is_billing_error(error_message)
        or _CONTEXT_WINDOW_TOO_SMALL_RE.search(error_message)
        or _is_rate_limit_error(error_message)
    ):
        return False
    if is_context_overflow_error(error_message):
        return True
    if _RATE_LIMIT_HINT_RE.search(error_message):
        return False
    return bool(_CONTEXT_OVERFLOW_HINT_RE.search(error_message))


def is_compaction_failure_error(error_message: str | None) -> bool:
    if not error_message:
        return False
    lower = _lower(error_message)
    has_compaction_term = (
        "summarization failed" in lower
        or "auto-compaction" in lower
        or "compaction failed" in lower
        or "compaction" in lower
    )
    if not has_compaction_term:
        return False
    if is_likely_context_overflow_error(error_message):
        return True
    return "context overflow" in lower


def extract_observed_overflow_token_count(error_message: str | None) -> int | None:
    if not error_message:
        return None
    for pattern in _OBSERVED_OVERFLOW_TOKEN_SUM_PATTERNS:
        match = pattern.search(error_message)
        if not match:
            continue
        left = int(match.group(1).replace(",", ""))
        right = int(match.group(2).replace(",", ""))
        if left > 0 and right >= 0:
            return left + right
    for pattern in _OBSERVED_OVERFLOW_TOKEN_PATTERNS:
        match = pattern.search(error_message)
        if not match:
            continue
        parsed = int(match.group(1).replace(",", ""))
        if parsed > 0:
            return parsed
    return None


def classify_overflow_error(
    error_text: str | None, *, context_tokens: int | float = 0
) -> OverflowClassification:
    is_overflow = is_likely_context_overflow_error(error_text)
    observed_tokens = extract_observed_overflow_token_count(error_text)
    tokens_for_compaction = observed_tokens
    if tokens_for_compaction is None and is_overflow and context_tokens > 0:
        tokens_for_compaction = int(context_tokens) + 1
    return OverflowClassification(
        is_overflow=is_overflow,
        is_compaction_failure=is_compaction_failure_error(error_text),
        observed_tokens=observed_tokens,
        tokens_for_compaction=tokens_for_compaction,
    )


def decide_provider_overflow_recovery(
    *,
    error_text: str | None,
    context_tokens: int | float = 0,
    overflow_compaction_attempts: int,
    attempt_compaction_count: int,
    preflight_source: str | None = None,
    preflight_route: str | None = None,
    current_message_persisted: bool = False,
    compaction_attempted: bool = False,
    compaction_succeeded: bool | None = None,
    has_oversized_tool_results: bool = False,
    tool_result_truncation_attempted: bool = False,
    max_attempts: int = MAX_OVERFLOW_COMPACTION_ATTEMPTS,
) -> ProviderOverflowRecoveryDecision:
    classification = classify_overflow_error(error_text, context_tokens=context_tokens)
    if not classification.is_overflow:
        return ProviderOverflowRecoveryDecision(
            action="no_overflow",
            should_retry=False,
            should_compact=False,
            should_truncate_tool_results=False,
            next_overflow_compaction_attempts=overflow_compaction_attempts,
            continue_from_current_transcript=False,
            suppress_next_user_message_persistence=False,
            next_prompt_override=None,
            tokens_for_compaction=None,
        )

    continue_from_transcript = preflight_source == "mid-turn"
    next_prompt_override = MID_TURN_PRECHECK_CONTINUATION_PROMPT if continue_from_transcript else None

    if (
        not classification.is_compaction_failure
        and attempt_compaction_count > 0
        and overflow_compaction_attempts < max_attempts
    ):
        return ProviderOverflowRecoveryDecision(
            action="retry_without_compaction",
            should_retry=True,
            should_compact=False,
            should_truncate_tool_results=False,
            next_overflow_compaction_attempts=overflow_compaction_attempts + 1,
            continue_from_current_transcript=continue_from_transcript,
            suppress_next_user_message_persistence=continue_from_transcript,
            next_prompt_override=next_prompt_override,
            tokens_for_compaction=classification.tokens_for_compaction,
        )

    if (
        not classification.is_compaction_failure
        and attempt_compaction_count <= 0
        and overflow_compaction_attempts < max_attempts
        and not compaction_attempted
    ):
        return ProviderOverflowRecoveryDecision(
            action="compact",
            should_retry=False,
            should_compact=True,
            should_truncate_tool_results=False,
            next_overflow_compaction_attempts=overflow_compaction_attempts + 1,
            continue_from_current_transcript=False,
            suppress_next_user_message_persistence=False,
            next_prompt_override=None,
            tokens_for_compaction=classification.tokens_for_compaction,
        )

    if compaction_attempted and compaction_succeeded:
        suppress = continue_from_transcript or current_message_persisted
        return ProviderOverflowRecoveryDecision(
            action="retry_after_compaction",
            should_retry=True,
            should_compact=False,
            should_truncate_tool_results=preflight_route == "compact_then_truncate",
            next_overflow_compaction_attempts=overflow_compaction_attempts,
            continue_from_current_transcript=continue_from_transcript,
            suppress_next_user_message_persistence=suppress,
            next_prompt_override=MID_TURN_PRECHECK_CONTINUATION_PROMPT if suppress else None,
            tokens_for_compaction=classification.tokens_for_compaction,
        )

    if not tool_result_truncation_attempted and has_oversized_tool_results:
        return ProviderOverflowRecoveryDecision(
            action="truncate_tool_results",
            should_retry=False,
            should_compact=False,
            should_truncate_tool_results=True,
            next_overflow_compaction_attempts=overflow_compaction_attempts,
            continue_from_current_transcript=False,
            suppress_next_user_message_persistence=False,
            next_prompt_override=None,
            tokens_for_compaction=classification.tokens_for_compaction,
        )

    error_kind = "compaction_failure" if classification.is_compaction_failure else "context_overflow"
    return ProviderOverflowRecoveryDecision(
        action="give_up",
        should_retry=False,
        should_compact=False,
        should_truncate_tool_results=False,
        next_overflow_compaction_attempts=overflow_compaction_attempts,
        continue_from_current_transcript=False,
        suppress_next_user_message_persistence=False,
        next_prompt_override=None,
        tokens_for_compaction=classification.tokens_for_compaction,
        error_kind=error_kind,
        user_visible_error_text=OVERFLOW_RECOVERY_TEXT,
    )
