from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
import re
from typing import Any, Literal

from memory_core._overflow_tables import (
    is_billing_error_message,
    is_rate_limit_error_message,
    js_regex,
    looks_like_provider_context_overflow_candidate,
    matches_context_overflow_message,
)
from memory_core.bootstrap._js import js_trim


MAX_OVERFLOW_COMPACTION_ATTEMPTS = 3
# run/session-prompt-state.ts CONTINUATION_PROMPT: the internal prompt of every transcript
# continuation (the pin's mid-turn-only "Continue from the current transcript ..." text is gone).
CONTINUATION_PROMPT = (
    "Continue the current task from the existing transcript, preserving completed work. If an "
    "action was interrupted, inspect its state before deciding whether to retry it. Do not "
    "restart the task or repeat completed actions."
)
MID_TURN_PRECHECK_CONTINUATION_PROMPT = CONTINUATION_PROMPT
OVERFLOW_RECOVERY_TEXT = (
    "Context overflow: prompt too large for the model. Try /reset (or /new) to start a fresh "
    "session, or use a larger-context model."
)


_STATED_TOKEN_SIZES_RE = re.compile(
    r"(?:\btpm\b|tokens per minute)[^.\n]*?\blimit\s+([\d,]+)[^.\n]*?\brequested\s+([\d,]+)",
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
    re.compile(
        r"input length\s+and\s+`max_tokens`\s+exceed\s+context\s+limit:\s*([\d,]+)\s*\+\s*([\d,]+)\s*>\s*[\d,]+",
        re.I,
    ),
)


def _read_stated_token_count(digits: str | None) -> int | None:
    if not digits:
        return None
    value = int(digits.replace(",", ""))
    return value if value > 0 else None


def is_provider_request_size_ceiling_error(error_message: str | None) -> bool:
    """A request larger than the provider's whole TPM bucket: reset guidance, not compaction."""

    if not error_message:
        return False
    match = _STATED_TOKEN_SIZES_RE.search(error_message)
    if match is None:
        return False
    limit = _read_stated_token_count(match.group(1))
    requested = _read_stated_token_count(match.group(2))
    return limit is not None and requested is not None and requested > limit


def _is_timeout_compaction_reason(reason: str | None) -> bool:
    """``classifyCompactionReason(reason) === "timeout"`` (compact-reasons.ts)."""

    text = (reason or "").lower()
    if not text:
        return False
    earlier = (
        "nothing to compact",
        "no real conversation messages",
        "below threshold",
        "already under target",
        "already compacted",
        "already_compacted",
        "deferred to background",
        "still exceeds target",
        "guard",
        "summary",
    )
    if text.startswith("no api key found") or (
        text.startswith("authentication failed for ") and "credentials may have expired" in text
    ):
        return False
    if any(marker in text for marker in earlier):
        return False
    if "session transcript" in text and "not persisted" in text:
        return False
    return "timed out" in text or "timeout" in text


SIDE_EFFECT_CAUTION = (
    " Completed tool actions were not replayed; verify their effects before retrying."
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
    # Mirrors run.ts: the post-compaction truncation on the compact_then_truncate
    # route and the failed-compaction overflow fallback exempt trailing fresh
    # tool results from aggregate reduction.
    protect_trailing_tool_results: bool = False
    error_kind: str | None = None
    user_visible_error_text: str | None = None
    # A compaction that rotated the session cannot be followed by parked Code Mode work: the
    # compaction stays committed but the mid-turn continuation is withheld (give_up).
    parked_work_blocks_continuation: bool = False
    # The no-real-conversation compaction no-op clears the stale token snapshot and retries.
    reset_context_snapshot: bool = False


NO_REAL_CONVERSATION_MESSAGES_REASON = "no real conversation messages"


def is_no_real_conversation_compaction_noop(
    *, ok: bool | None = None, compacted: bool | None = None, reason: str | None = None
) -> bool:
    """``isNoRealConversationCompactionNoop`` (run/session-bootstrap.ts): exact-reason no-op."""

    return ok is True and compacted is False and reason == NO_REAL_CONVERSATION_MESSAGES_REASON


def _lower(raw: str | None) -> str:
    return raw.lower() if isinstance(raw, str) else ""


def _has_rate_limit_tpm_hint(raw: str | None) -> bool:
    return bool(raw and matches_context_overflow_message(raw, "tpm-rate-limit-hint"))


def _is_reasoning_constraint_error(raw: str | None) -> bool:
    lower = _lower(raw)
    return (
        "reasoning is mandatory" in lower
        or "reasoning is required" in lower
        or "requires reasoning" in lower
        or ("reasoning" in lower and "cannot be disabled" in lower)
    )


def is_context_overflow_error_from_tables(error_message: str | None) -> bool:
    """``isContextOverflowErrorFromTables``: explicit overflow wording, never a TPM rate limit."""

    if not error_message:
        return False
    # Groq uses 413 for TPM limits, a rate limit, unless the request alone exceeds the whole limit.
    if (
        _has_rate_limit_tpm_hint(error_message)
        and not is_provider_request_size_ceiling_error(error_message)
    ) or _is_reasoning_constraint_error(error_message):
        return False
    return matches_context_overflow_message(error_message, "failover-explicit") or (
        looks_like_provider_context_overflow_candidate(error_message)
        and matches_context_overflow_message(error_message, "provider-fallback")
    )


class _Unset:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debug repr only
        return "UNSET"


UNSET: Any = _Unset()

#: ``ProviderSpecificErrorContext`` (failover/provider-patterns.ts) as a mapping with the keys
#: ``errorMessage``, ``provider``, ``modelId``, ``status``, ``code`` and ``errorType``.
ProviderErrorContext = Mapping[str, Any]


@dataclass(frozen=True)
class PreparedProviderFailoverOwner:
    """``PreparedProviderFailoverOwner``: the provider plugin that owns an error, host-supplied.

    ``matches_context_overflow_error`` and ``classify_failover_reason`` are the plugin hooks
    ``matchesContextOverflowError`` and ``classifyFailoverReason``; each receives the context with
    ``provider`` set to ``id`` and may return ``None`` to defer.
    """

    id: str
    matches_context_overflow_error: Callable[[dict[str, Any]], bool | None] | None = None
    classify_failover_reason: Callable[[dict[str, Any]], str | None] | None = None


def classify_provider_plugin_error(
    context: ProviderErrorContext,
    *,
    provider_plugin: PreparedProviderFailoverOwner | None | Any = UNSET,
    discover: Callable[[dict[str, Any]], str | None] | None = None,
) -> str | None:
    """``classifyProviderPluginError``: a failover reason from the owning provider plugin, or ``None``.

    ``provider_plugin=None`` is explicit absence (presentation has no provider owner: no
    discovery). An unset plugin falls back to ``discover``, the host's counterpart of
    ``classifyProviderFailoverSignalWithPlugin`` (provider lookup by ``context["provider"]``); no
    host means no plugin classifies.
    """

    provider_context = dict(context)
    if provider_plugin is None:
        return None
    if isinstance(provider_plugin, PreparedProviderFailoverOwner):
        owned = {**provider_context, "provider": provider_plugin.id}
        matcher = provider_plugin.matches_context_overflow_error
        if matcher is not None and matcher(owned):
            return "context_overflow"
        if provider_plugin.classify_failover_reason is None:
            return None
        return provider_plugin.classify_failover_reason(owned) or None
    if discover is None:
        return None
    return discover(provider_context) or None


def is_context_overflow_error(
    error_message: str | None,
    *,
    provider_plugin: PreparedProviderFailoverOwner | None | Any = UNSET,
    discover_provider_plugin: Callable[[dict[str, Any]], str | None] | None = None,
) -> bool:
    """``isContextOverflowError``: the wording tables, or the provider plugin's own verdict.

    The plugin is asked only for a message that looks like a provider overflow candidate
    (rate limits excluded), exactly as upstream gates ``classifyProviderPluginError``.
    """

    if not error_message:
        return False
    return is_context_overflow_error_from_tables(error_message) or (
        looks_like_provider_context_overflow_candidate(error_message)
        and classify_provider_plugin_error(
            {"errorMessage": error_message},
            provider_plugin=provider_plugin,
            discover=discover_provider_plugin,
        )
        == "context_overflow"
    )


def is_likely_context_overflow_error(
    error_message: str | None,
    *,
    discover_provider_plugin: Callable[[dict[str, Any]], str | None] | None = None,
) -> bool:
    if not error_message:
        return False
    # Settle an unsatisfiable request size first: the TPM and rate-limit exclusions below would
    # otherwise claim the message on its rate-limit wording alone.
    if is_provider_request_size_ceiling_error(error_message):
        return is_context_overflow_error_from_tables(error_message)
    if (
        _has_rate_limit_tpm_hint(error_message)
        or _is_reasoning_constraint_error(error_message)
        # Billing and quota errors can contain "request size exceeds" style wording.
        or is_billing_error_message(error_message)
        or matches_context_overflow_message(error_message, "context-window-too-small")
        # Rate limits can match the broad hint pattern ("request reached organization TPD ...").
        or is_rate_limit_error_message(error_message)
    ):
        return False
    # Upstream passes no plugin here: the provider owner is discovered by the runtime.
    if is_context_overflow_error(error_message, discover_provider_plugin=discover_provider_plugin):
        return True
    if "prompt template" in _lower(error_message.strip()):
        return False
    if matches_context_overflow_message(error_message, "rate-limit-hint"):
        return False
    return matches_context_overflow_message(error_message, "failover-hint")


# --- assistant-error path (packages/ai/src/utils/overflow.ts, run/overflow-context-recovery.ts) ----

_NON_OVERFLOW_PATTERNS = (
    js_regex(r"^(Throttling error|Service unavailable):"),
    js_regex(r"rate limit"),
    js_regex(r"too many requests"),
)


def is_provider_refusal_assistant_error(message: Mapping[str, Any] | None) -> bool:
    """``isProviderRefusalAssistantError``: a ``provider_refusal`` diagnostic on the message."""

    diagnostics = message.get("diagnostics") if isinstance(message, Mapping) else None
    return isinstance(diagnostics, list) and any(
        isinstance(item, Mapping) and item.get("type") == "provider_refusal" for item in diagnostics
    )


def _js_number(value: Any) -> float:
    """A usage bucket as JS arithmetic reads it: absent is ``NaN``, ``null`` is ``0``."""

    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    return value if isinstance(value, (int, float)) else math.nan


def _resolve_context_input_tokens(message: Mapping[str, Any]) -> float | None:
    usage = message["usage"]
    context_usage = usage.get("contextUsage") if isinstance(usage, Mapping) else None
    state = context_usage.get("state") if isinstance(context_usage, Mapping) else None
    if state == "available":
        if "promptTokens" not in context_usage:
            return None
        return _js_number(context_usage["promptTokens"])
    if state == "unavailable":
        return None
    # Cache writes are prompt tokens too: providers that report them separately keep them out of
    # ``input``, so omitting the bucket under-counts the context by exactly that amount.
    return (
        _js_number(usage.get("input", math.nan))
        + _js_number(usage.get("cacheRead", math.nan))
        + _js_number(usage.get("cacheWrite", math.nan))
    )


def is_context_overflow(
    message: Mapping[str, Any], context_window: int | float | None = None
) -> bool:
    """``isContextOverflow``: whether an assistant message is a context overflow.

    Error text (``stopReason`` ``error`` with a known overflow wording, throttling excluded), silent
    overflow (``stop`` with usage above the window) and length-stop overflow (``length`` with no
    output and a prompt filling 99 percent of the window). A provider refusal never qualifies.
    """

    if is_provider_refusal_assistant_error(message):
        return False
    stop_reason = message.get("stopReason")
    error_message = message.get("errorMessage")
    if (
        stop_reason == "error"
        and error_message
        and not any(p.search(error_message) for p in _NON_OVERFLOW_PATTERNS)
        and matches_context_overflow_message(error_message, "assistant-error")
    ):
        return True
    window = context_window if context_window and not math.isnan(context_window) else None
    if window is not None and stop_reason == "stop":
        input_tokens = _resolve_context_input_tokens(message)
        if input_tokens is not None and input_tokens > window:
            return True
    if window is not None and stop_reason == "length" and message["usage"].get("output") == 0:
        input_tokens = _resolve_context_input_tokens(message)
        if input_tokens is not None and input_tokens >= window * 0.99:
            return True
    return False


@dataclass(frozen=True)
class ContextOverflowError:
    text: str
    source: Literal["promptError", "assistantError"]


def resolve_context_overflow_error(
    *,
    aborted: bool = False,
    signal_owned_interruption: bool = False,
    prompt_error: Any = None,
    assistant: Mapping[str, Any] | None = None,
    classification: Mapping[str, Any] | None = None,
    assistant_error_text: str | None = None,
    context_token_budget: int | float | None = None,
    format_error: Callable[[Any], str] = str,
    discover_provider_plugin: Callable[[dict[str, Any]], str | None] | None = None,
) -> ContextOverflowError | None:
    """The overflow selection of ``recoverEmbeddedRunOverflow`` (run/overflow-context-recovery.ts).

    Which error text, if any, drives overflow recovery: a prompt failure by its own wording only;
    otherwise the selected assistant response by its structured classification, a provider refusal
    or a failover reason (both veto), its own overflow shape, or the assistant error text. An
    aborted run or one whose interruption the signal owns selects nothing.

    ``classification`` is the host's ``FailoverClassification`` of the assistant message
    (``{"kind": "reason", "reason": ...}`` or ``{"kind": "context_overflow"}``);
    ``format_error`` stands for ``formatErrorMessage`` (upstream also redacts, host side here).
    """

    if aborted or signal_owned_interruption:
        return None
    kind = classification.get("kind") if classification else None
    if prompt_error:
        error_text = format_error(prompt_error)
        if is_likely_context_overflow_error(
            error_text, discover_provider_plugin=discover_provider_plugin
        ):
            return ContextOverflowError(error_text, "promptError")
        # A non-overflow prompt failure must not inherit a stale assistant error.
        return None
    # Preserve the structured terminal outcome before the text-only fallback below.
    if is_provider_refusal_assistant_error(assistant):
        return None
    # This decision belongs to the selected response, not a text-only guess.
    if assistant is not None and assistant.get("stopReason") == "error" and kind == "reason":
        return None
    if assistant is not None and (
        kind == "context_overflow"
        or (
            context_token_budget is not None
            and is_context_overflow(assistant, context_token_budget)
        )
    ):
        message = assistant.get("errorMessage")
        text = js_trim(message) if isinstance(message, str) else ""
        return ContextOverflowError(text or "Context window exceeded", "assistantError")
    if assistant is not None and assistant.get("stopReason") == "length":
        return None
    if assistant_error_text and is_likely_context_overflow_error(
        assistant_error_text, discover_provider_plugin=discover_provider_plugin
    ):
        return ContextOverflowError(assistant_error_text, "assistantError")
    return None


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
    current_attempt_replay_safe: bool = True,
    had_potential_side_effects: bool = False,
    prompt_error_source: str | None = None,
    failed_compaction_reason: str | None = None,
    max_attempts: int = MAX_OVERFLOW_COMPACTION_ATTEMPTS,
    previous_session_id: str | None = None,
    code_mode_suspended: bool = False,
    compaction_ok: bool | None = None,
    compaction_reason: str | None = None,
    has_preflight_recovery: bool | None = None,
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

    caution = SIDE_EFFECT_CAUTION if had_potential_side_effects else ""
    if is_provider_request_size_ceiling_error(error_text):
        # Compaction cannot make the request fit under the provider's own ceiling.
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
            error_kind=(
                "compaction_failure" if classification.is_compaction_failure else "context_overflow"
            ),
            user_visible_error_text=OVERFLOW_RECOVERY_TEXT + caution,
        )

    # A mid-turn precheck or an attempt whose side effects cannot be replayed must continue
    # from the transcript instead of resending the original user message.
    continue_from_transcript = preflight_source == "mid-turn" or not current_attempt_replay_safe
    next_prompt_override = CONTINUATION_PROMPT if continue_from_transcript else None

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

    if has_preflight_recovery is None:
        has_preflight_recovery = preflight_route is not None or preflight_source is not None
    if (
        compaction_attempted
        and not compaction_succeeded
        and has_preflight_recovery
        and is_no_real_conversation_compaction_noop(
            ok=compaction_ok, compacted=False, reason=compaction_reason
        )
    ):
        # Stale token state with nothing to compact: reset the snapshot and retry the prompt.
        return ProviderOverflowRecoveryDecision(
            action="reset_snapshot_and_retry",
            should_retry=True,
            should_compact=False,
            should_truncate_tool_results=False,
            next_overflow_compaction_attempts=overflow_compaction_attempts,
            continue_from_current_transcript=continue_from_transcript,
            suppress_next_user_message_persistence=continue_from_transcript,
            next_prompt_override=next_prompt_override,
            tokens_for_compaction=classification.tokens_for_compaction,
            reset_context_snapshot=True,
        )

    if compaction_attempted and compaction_succeeded:
        if previous_session_id is not None and continue_from_transcript and code_mode_suspended:
            # A parked Code Mode run is bound to the session it started in and `wait` rejects any
            # other session, so a compaction that adopts a successor cannot redeem parked nested
            # work. The compaction stays committed (the compact_then_truncate truncation still
            # runs); only the mid-turn continuation and the truncation fallback are withheld.
            return ProviderOverflowRecoveryDecision(
                action="give_up",
                should_retry=False,
                should_compact=False,
                should_truncate_tool_results=preflight_route == "compact_then_truncate",
                protect_trailing_tool_results=preflight_route == "compact_then_truncate",
                next_overflow_compaction_attempts=overflow_compaction_attempts,
                continue_from_current_transcript=False,
                suppress_next_user_message_persistence=False,
                next_prompt_override=None,
                tokens_for_compaction=classification.tokens_for_compaction,
                error_kind=(
                    "compaction_failure"
                    if classification.is_compaction_failure
                    else "context_overflow"
                ),
                user_visible_error_text=OVERFLOW_RECOVERY_TEXT + caution,
                parked_work_blocks_continuation=True,
            )
        suppress = continue_from_transcript or current_message_persisted
        return ProviderOverflowRecoveryDecision(
            action="retry_after_compaction",
            should_retry=True,
            should_compact=False,
            should_truncate_tool_results=preflight_route == "compact_then_truncate",
            protect_trailing_tool_results=preflight_route == "compact_then_truncate",
            next_overflow_compaction_attempts=overflow_compaction_attempts,
            continue_from_current_transcript=continue_from_transcript,
            suppress_next_user_message_persistence=suppress,
            next_prompt_override=CONTINUATION_PROMPT if suppress else None,
            tokens_for_compaction=classification.tokens_for_compaction,
        )

    if not tool_result_truncation_attempted and has_oversized_tool_results:
        return ProviderOverflowRecoveryDecision(
            action="truncate_tool_results",
            should_retry=False,
            should_compact=False,
            should_truncate_tool_results=True,
            protect_trailing_tool_results=preflight_route == "compact_then_truncate",
            next_overflow_compaction_attempts=overflow_compaction_attempts,
            # A truncation that helps retries like every other recovery: a transcript
            # continuation when the attempt cannot be replayed (prepareCurrentTranscriptRetry).
            continue_from_current_transcript=continue_from_transcript,
            suppress_next_user_message_persistence=continue_from_transcript,
            next_prompt_override=next_prompt_override,
            tokens_for_compaction=classification.tokens_for_compaction,
        )

    preflight_compaction_failed = (
        prompt_error_source == "precheck" and failed_compaction_reason is not None
    )
    error_kind = (
        "compaction_failure"
        if classification.is_compaction_failure or preflight_compaction_failed
        else "context_overflow"
    )
    if preflight_compaction_failed:
        lead = (
            "Auto-compaction timed out"
            if _is_timeout_compaction_reason(failed_compaction_reason)
            else "Auto-compaction failed"
        )
        user_text = f"{lead} before the next model request. Try again or run /compact.{caution}"
    else:
        user_text = OVERFLOW_RECOVERY_TEXT + caution
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
        user_visible_error_text=user_text,
    )
