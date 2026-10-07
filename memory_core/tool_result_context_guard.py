"""The mid-turn tool-result context guard at v2026.9.6 (``tool-result-context-guard.ts``).

``installToolResultContextGuard`` wraps an agent's ``transformContext``: every tool-loop iteration
it caps each tool result to the context share, and, once a tool result newer than the pre-prompt
fence exists, asks ``shouldPreemptivelyCompactBeforePrompt`` (with the prompt already inside the
messages, hence ``prompt=""``) whether the next model call would overflow. When it would, the guard
raises :class:`MidTurnPrecheckSignal` carrying the measured budget, and the attempt runner routes
the signal into overflow recovery (:mod:`memory_core.attempt_preflight`,
:func:`memory_core.overflow_recovery.decide_provider_overflow_recovery`).

There is no agent loop here: :class:`ToolResultContextGuard` is the wrapped function's state and
decision, the host calls :meth:`ToolResultContextGuard.transform_context` from its own
``transformContext`` (after any transform of its own) and lets the signal propagate. Also ported from
``tool-result-char-estimator.ts`` (the guard's character weights), ``tool-result-limits.ts``
(``resolveToolResultContextMaxChars``), ``context-truncation-notice.ts`` and ``midturn-precheck.ts``.

Deviations: the agent is not wrapped (the host owns ``transformContext``), the per-block
``prepareToolResultTextChars`` memo and the ``WeakMap`` caches are dropped (pure caches), and
``installContextEngineLoopHook`` of the same upstream file (context-engine ``afterTurn`` and
``assemble`` per iteration) is not ported.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from memory_core._tool_result_budget import estimate_string_chars_with_minimum_raw_weight
from memory_core.bootstrap._js import js_json_stringify, utf16_len
from memory_core.preemptive_compaction import (
    BRANCH_SUMMARY_PREFIX,
    BRANCH_SUMMARY_SUFFIX,
    COMPACTION_SUMMARY_PREFIX,
    COMPACTION_SUMMARY_SUFFIX,
    CompactionReplayPressureContext,
    PreemptiveCompactionDecision,
    _js_concat_text,
    bash_execution_to_text,
    should_preemptively_compact_before_prompt,
    truncate_tool_result_message,
    truncate_tool_result_text,
)

TOOL_RESULT_CHARS_PER_TOKEN_ESTIMATE = 2
IMAGE_CHAR_ESTIMATE = 8_000
TOOL_IMAGE_CHARS = IMAGE_CHAR_ESTIMATE * TOOL_RESULT_CHARS_PER_TOKEN_ESTIMATE
MID_TURN_PRECHECK_ERROR_MESSAGE = (
    "Context overflow: prompt too large for the model (mid-turn precheck)."
)
_CONTEXT_LIMIT_TRUNCATION_NOTICE = "more characters truncated"
_CONTEXT_LIMIT_TRUNCATION_HINT = "rerun with narrower args if needed"


# --- midturn-precheck.ts ------------------------------------------------------------------------


@dataclass(frozen=True)
class MidTurnPrecheckRequest:
    """``MidTurnPrecheckRequest``: the token-pressure snapshot that stopped the attempt."""

    route: str
    estimated_prompt_tokens: int | float
    prompt_budget_before_reserve: int
    overflow_tokens: int | float
    tool_result_reducible_chars: int
    effective_reserve_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "estimatedPromptTokens": self.estimated_prompt_tokens,
            "promptBudgetBeforeReserve": self.prompt_budget_before_reserve,
            "overflowTokens": self.overflow_tokens,
            "toolResultReducibleChars": self.tool_result_reducible_chars,
            "effectiveReserveTokens": self.effective_reserve_tokens,
        }


class MidTurnPrecheckSignal(Exception):  # noqa: N818 - the upstream class name
    """``MidTurnPrecheckSignal``: control flow thrown after a tool result overflows the next prompt."""

    def __init__(self, request: MidTurnPrecheckRequest) -> None:
        super().__init__(MID_TURN_PRECHECK_ERROR_MESSAGE)
        self.request = request


def is_mid_turn_precheck_signal(error: object) -> bool:
    return isinstance(error, MidTurnPrecheckSignal)


def is_mid_turn_precheck_assistant_error(message: Any) -> bool:
    """``isMidTurnPrecheckAssistantError``: the local routing signal is no provider response."""

    return (
        isinstance(message, dict)
        and message.get("role") == "assistant"
        and message.get("stopReason") == "error"
        and message.get("errorMessage") == MID_TURN_PRECHECK_ERROR_MESSAGE
    )


# --- tool-result-char-estimator.ts --------------------------------------------------------------


def _is_text_block(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)


def _is_image_block(block: Any) -> bool:
    return isinstance(block, dict) and block.get("type") == "image"


def _estimate_unknown_chars(value: Any) -> int:
    if isinstance(value, str):
        return utf16_len(value)
    try:
        return utf16_len(js_json_stringify(value))
    except (TypeError, ValueError):
        return 256


def is_tool_result_message(message: Any) -> bool:
    if not isinstance(message, dict):
        return False
    return message.get("role") in {"toolResult", "tool"} or message.get("type") == "toolResult"


def _tool_result_content(message: dict[str, Any]) -> list[Any]:
    if not is_tool_result_message(message):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def _estimate_content_block_chars(content: Sequence[Any]) -> int:
    chars = 0
    for block in content:
        if _is_text_block(block):
            chars += utf16_len(block["text"])
        elif _is_image_block(block):
            chars += IMAGE_CHAR_ESTIMATE
        else:
            chars += _estimate_unknown_chars(block)
    return chars


def _estimate_tool_result_content_chars(content: Sequence[Any]) -> int | float:
    chars: int | float = 0
    for block in content:
        if _is_text_block(block):
            chars += estimate_string_chars_with_minimum_raw_weight(
                block["text"], TOOL_RESULT_CHARS_PER_TOKEN_ESTIMATE
            )
        elif _is_image_block(block):
            chars += TOOL_IMAGE_CHARS
        else:
            chars += _estimate_unknown_chars(block) * TOOL_RESULT_CHARS_PER_TOKEN_ESTIMATE
    return chars


def get_tool_result_text(message: dict[str, Any]) -> str:
    return "\n".join(
        block["text"] for block in _tool_result_content(message) if _is_text_block(block)
    )


def estimate_message_chars(
    message: Any, content_override: Sequence[Any] | None = None
) -> int | float:
    """``estimateMessageChars``: the raw-weight character cost of one message."""

    if not isinstance(message, dict) or message.get("excludeFromContext") is True:
        return 0
    role = message.get("role")
    if role == "user":
        content = content_override if content_override is not None else message.get("content")
        if isinstance(content, str):
            return utf16_len(content)
        if isinstance(content, list):
            return _estimate_content_block_chars(content)
        return 0
    if role == "assistant":
        chars = 0
        content = content_override if content_override is not None else message.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    # JS: a non-object block is skipped, except null is not an object either.
                    if block is not None and not isinstance(block, str | int | float | bool):
                        chars += _estimate_unknown_chars(block)
                    continue
                block_type = block.get("type")
                if block_type == "text" and isinstance(block.get("text"), str):
                    chars += utf16_len(block["text"])
                elif block_type == "thinking" and isinstance(block.get("thinking"), str):
                    chars += utf16_len(block["thinking"])
                elif block_type == "toolCall":
                    arguments = block.get("arguments")
                    try:
                        chars += utf16_len(
                            js_json_stringify({} if arguments is None else arguments)
                        )
                    except (TypeError, ValueError):
                        chars += 128
                else:
                    chars += _estimate_unknown_chars(block)
        return chars
    if is_tool_result_message(message):
        # ``details`` is stripped before provider conversion; estimate only visible content.
        content = content_override if content_override is not None else _tool_result_content(message)
        return _estimate_tool_result_content_chars(content)
    if role == "bashExecution":
        return utf16_len(bash_execution_to_text(message))
    if role in {"branchSummary", "compactionSummary"}:
        summary = message.get("summary")
        summary = summary if isinstance(summary, str) else ""
        prefix, suffix = (
            (BRANCH_SUMMARY_PREFIX, BRANCH_SUMMARY_SUFFIX)
            if role == "branchSummary"
            else (COMPACTION_SUMMARY_PREFIX, COMPACTION_SUMMARY_SUFFIX)
        )
        return utf16_len(prefix + summary + suffix)
    if role == "custom":
        content = content_override if content_override is not None else message.get("content")
        if isinstance(content, str):
            return utf16_len(content)
        if isinstance(content, list):
            return _estimate_content_block_chars(content)
        return 0
    return 256


# --- context-truncation-notice.ts, tool-result-limits.ts ----------------------------------------


def format_context_limit_truncation_notice(truncated_chars: int | float) -> str:
    return (
        f"[... {max(1, math.floor(truncated_chars))} {_CONTEXT_LIMIT_TRUNCATION_NOTICE}; "
        f"{_CONTEXT_LIMIT_TRUNCATION_HINT}]"
    )


def resolve_tool_result_context_max_chars(context_window_tokens: int | float) -> int:
    """``resolveToolResultContextMaxChars``: one raw-weight char per token of the window (min 1,024)."""

    return max(1_024, math.floor(max(1, math.floor(context_window_tokens)) * 2 * 0.5))


# --- the guard's truncation ---------------------------------------------------------------------


def _replace_tool_result_content(message: dict[str, Any], replacement: str | list[Any]) -> dict[str, Any]:
    content = message.get("content")
    wrap = isinstance(replacement, str) and not (isinstance(content, str) or "content" not in message)
    result = dict(message)
    result["content"] = [{"type": "text", "text": replacement}] if wrap else replacement
    result.pop("details", None)
    return result


def _estimate_budget_to_raw_chars(max_chars: int | float) -> int:
    return max(0, math.floor(max_chars / TOOL_RESULT_CHARS_PER_TOKEN_ESTIMATE))


def truncate_tool_result_to_chars(message: Any, max_chars: int | float) -> Any:
    """``truncateToolResultToChars``: cap one tool result to ``max_chars`` of raw-weight text.

    Images beyond the budget are dropped (with an omission notice), text keeps its head and its
    diagnostic tail; a message already inside the budget comes back as the same object.
    """

    if not is_tool_result_message(message):
        return message
    if estimate_message_chars(message) <= max_chars:
        return message
    content = message.get("content")
    if isinstance(content, list):
        image_count = sum(1 for block in content if _is_image_block(block))

        def omission_notice(retained_images: int) -> str:
            omitted = image_count - retained_images
            return (
                f"[{omitted} image{'' if omitted == 1 else 's'} omitted from context"
                f"{'; no images fit the context limit' if retained_images == 0 else ''}"
                "; rerun with fewer images]"
            )

        def project_content(retained: list[Any], notice_text: str | None = None) -> dict[str, Any]:
            notice = [{"type": "text", "text": notice_text}] if notice_text else []
            reserved = estimate_message_chars(
                message, [*(block for block in retained if not _is_text_block(block)), *notice]
            )
            bounded = truncate_tool_result_message(
                _replace_tool_result_content(message, retained),
                max(0, max_chars - reserved),
                minimum_raw_weight=TOOL_RESULT_CHARS_PER_TOKEN_ESTIMATE,
            )
            return _replace_tool_result_content(message, [*bounded["content"], *notice])

        # Image cost alone rules out larger prefixes; the allocator still reserves other
        # non-text content and preserves diagnostic tails and short text blocks.
        max_retained_images = min(image_count, math.floor(max_chars / TOOL_IMAGE_CHARS))
        for retained_images in range(max_retained_images, -1, -1):
            seen_images = 0
            retained_content: list[Any] = []
            for block in content:
                if not _is_image_block(block):
                    retained_content.append(block)
                else:
                    seen_images += 1
                    if seen_images <= retained_images:
                        retained_content.append(block)
            projected = project_content(
                retained_content,
                omission_notice(retained_images) if retained_images < image_count else None,
            )
            projected_content = projected["content"]
            if any(
                _is_text_block(block)
                and block["text"]
                and (
                    index >= len(projected_content)
                    or not _is_text_block(projected_content[index])
                    or not projected_content[index]["text"]
                )
                for index, block in enumerate(retained_content)
            ):
                continue
            if estimate_message_chars(projected) <= max_chars:
                return projected
        # Dropping unfit non-text content must not flatten away surviving semantic blocks:
        # reserve a visible notice even when only omission markers can fit.
        omitted_chars = estimate_message_chars(
            message, [block for block in content if not _is_text_block(block)]
        )
        return project_content(
            [block for block in content if _is_text_block(block)],
            omission_notice(0)
            if image_count > 0
            else format_context_limit_truncation_notice(
                max(1, _estimate_budget_to_raw_chars(omitted_chars))
            ),
        )
    truncated = truncate_tool_result_text(
        get_tool_result_text(message),
        max_chars,
        min_keep_chars=0,
        minimum_raw_weight=TOOL_RESULT_CHARS_PER_TOKEN_ESTIMATE,
    )
    return _replace_tool_result_content(message, truncated)


def enforce_tool_result_limit(
    messages: list[Any], max_single_tool_result_chars: int | float
) -> list[Any]:
    """``enforceToolResultLimit``: the same list object when no tool result needed a cap."""

    guarded = [truncate_tool_result_to_chars(m, max_single_tool_result_chars) for m in messages]
    return guarded if any(a is not b for a, b in zip(guarded, messages, strict=True)) else messages


def has_new_tool_result_after_fence(messages: Sequence[Any], pre_prompt_message_count: int | float) -> bool:
    start = 0 if isinstance(pre_prompt_message_count, float) and math.isnan(pre_prompt_message_count) else int(pre_prompt_message_count)
    return any(is_tool_result_message(message) for message in messages[start:])


def to_mid_turn_precheck_request(
    result: PreemptiveCompactionDecision,
) -> MidTurnPrecheckRequest | None:
    """``toMidTurnPrecheckRequest``: built from the top-level (diagnostic) decision, as upstream."""

    if result.route == "fits":
        return None
    return MidTurnPrecheckRequest(
        route=result.route,
        estimated_prompt_tokens=result.estimated_prompt_tokens,
        prompt_budget_before_reserve=result.prompt_budget_before_reserve,
        overflow_tokens=result.overflow_tokens,
        tool_result_reducible_chars=result.tool_result_reducible_chars,
        effective_reserve_tokens=result.effective_reserve_tokens,
    )


@dataclass
class MidTurnPrecheckOptions:
    """``MidTurnPrecheckOptions``: the host inputs of the mid-turn check."""

    context_token_budget: int | float
    reserve_tokens: Callable[[], int | float]
    enabled: bool = False
    get_replay: Callable[[], CompactionReplayPressureContext | None] | None = None
    tool_result_max_chars: int | None = None
    get_system_prompt: Callable[[], str | None] | None = None
    get_pre_prompt_message_count: Callable[[], int | float | None] | None = None
    on_mid_turn_precheck: Callable[[MidTurnPrecheckRequest], None] | None = None


def _js_clamp_fence(length: int, last_seen: int | float | None, fallback: Callable[[], Any] | None) -> int | float:
    """``Math.max(0, Math.min(length, lastSeenLength ?? getPrePromptMessageCount?.() ?? length))``."""

    value: Any = last_seen
    if value is None and fallback is not None:
        value = fallback()
    if value is None:
        value = length
    if isinstance(value, float) and math.isnan(value):
        return value
    return max(0, min(length, value))


class ToolResultContextGuard:
    """``installToolResultContextGuard``: the state and decision of the wrapped ``transformContext``."""

    def __init__(
        self,
        *,
        context_window_tokens: int | float,
        mid_turn_precheck: MidTurnPrecheckOptions | None = None,
        log_debug: Callable[[str], None] | None = None,
    ) -> None:
        self.max_single_tool_result_chars = resolve_tool_result_context_max_chars(
            context_window_tokens
        )
        self.mid_turn_precheck = mid_turn_precheck
        self.last_seen_length: int | float | None = None
        self._log_debug = log_debug

    def transform_context(self, messages: list[Any]) -> list[Any]:
        """Cap tool results, then raise :class:`MidTurnPrecheckSignal` when the next prompt overflows."""

        context_messages = enforce_tool_result_limit(messages, self.max_single_tool_result_chars)
        options = self.mid_turn_precheck
        if options is not None and options.enabled:
            pre_prompt = _js_clamp_fence(
                len(context_messages),
                self.last_seen_length,
                options.get_pre_prompt_message_count,
            )
            self.last_seen_length = pre_prompt
            if has_new_tool_result_after_fence(context_messages, pre_prompt):
                # The same post-truncation view the runtime sends to the next model call; recovery
                # re-applies truncation to the persisted session, so this is a routing signal only.
                precheck = should_preemptively_compact_before_prompt(
                    replay=options.get_replay() if options.get_replay else None,
                    messages=context_messages,
                    system_prompt=options.get_system_prompt() if options.get_system_prompt else None,
                    # During a tool loop, the active user prompt is already part of messages.
                    prompt="",
                    context_token_budget=options.context_token_budget,
                    reserve_tokens=options.reserve_tokens(),
                    tool_result_max_chars=options.tool_result_max_chars,
                )
                request = to_mid_turn_precheck_request(precheck)
                if self._log_debug is not None:
                    self._log_debug(
                        f"[context-overflow-midturn-precheck] tool-result-guard check "
                        f"route={precheck.route} messages={len(context_messages)} "
                        f"prePromptMessageCount={_js_concat_text(pre_prompt)} "
                        f"estimatedPromptTokens={_js_concat_text(precheck.estimated_prompt_tokens)} "
                        f"promptBudgetBeforeReserve={precheck.prompt_budget_before_reserve} "
                        f"overflowTokens={_js_concat_text(precheck.overflow_tokens)}"
                    )
                if request is not None:
                    if options.on_mid_turn_precheck is not None:
                        options.on_mid_turn_precheck(request)
                    raise MidTurnPrecheckSignal(request)
            self.last_seen_length = len(context_messages)
        return context_messages


__all__ = [
    "MID_TURN_PRECHECK_ERROR_MESSAGE",
    "MidTurnPrecheckOptions",
    "MidTurnPrecheckRequest",
    "MidTurnPrecheckSignal",
    "ToolResultContextGuard",
    "enforce_tool_result_limit",
    "estimate_message_chars",
    "format_context_limit_truncation_notice",
    "get_tool_result_text",
    "has_new_tool_result_after_fence",
    "is_mid_turn_precheck_assistant_error",
    "is_mid_turn_precheck_signal",
    "is_tool_result_message",
    "resolve_tool_result_context_max_chars",
    "to_mid_turn_precheck_request",
    "truncate_tool_result_to_chars",
]
