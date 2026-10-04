from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from memory_core._tool_result_budget import (
    estimate_string_chars,
    estimate_string_chars_with_minimum_raw_weight,
    slice_tool_result_text_tail_to_budget,
    slice_tool_result_text_to_budget,
)
from memory_core.bootstrap._js import slice_utf16_safe, utf16_len


ESTIMATED_CHARS_PER_TOKEN = 4
TOOL_RESULT_CHARS_PER_TOKEN = 2
JSON_PAYLOAD_CHARS_PER_TOKEN = 3
MESSAGE_BOUNDARY_OVERHEAD_TOKENS = 12
CONTENT_BLOCK_OVERHEAD_TOKENS = 6
IMAGE_BLOCK_TOKENS = 2_000
TRUNCATION_ROUTE_BUFFER_TOKENS = 512
MIN_PROMPT_BUDGET_RATIO = 0.5
MIN_PROMPT_BUDGET_TOKENS = 8_000
SAFETY_MARGIN = 1.2
MAX_TOOL_RESULT_CONTEXT_SHARE = 0.3
DEFAULT_MAX_LIVE_TOOL_RESULT_CHARS = 16_000
LARGE_CONTEXT_MAX_LIVE_TOOL_RESULT_CHARS = 32_000
XL_CONTEXT_MAX_LIVE_TOOL_RESULT_CHARS = 64_000
LARGE_CONTEXT_TOOL_RESULT_TOKENS = 100_000
XL_CONTEXT_TOOL_RESULT_TOKENS = 200_000
MIN_KEEP_CHARS = 2_000
RECOVERY_MIN_KEEP_CHARS = 0
MIDDLE_OMISSION_MARKER = "\n\n⚠️ [... middle content omitted — showing head and tail ...]\n\n"
# Aggregate truncation shares the 0.5 history-pressure invariant used by
# OpenClaw safeguard compaction; see tool-result-truncation.ts.
PROMPT_TOOL_RESULT_AGGREGATE_CAP_MULTIPLIER = 4
AGGREGATE_TOOL_RESULT_CONTEXT_SHARE = 0.5
AGGREGATE_ELISION_MARKER = (
    "[tool result elided: aggregate tool-result budget exceeded; "
    "rerun the command if the output is needed]"
)

COMPACTION_SUMMARY_PREFIX = (
    "The conversation history before this point was compacted into the following summary:"
    "\n\n<summary>\n"
)
COMPACTION_SUMMARY_SUFFIX = "\n</summary>"
BRANCH_SUMMARY_PREFIX = (
    "The following is a summary of a branch that this conversation came back from:"
    "\n\n<summary>\n"
)
BRANCH_SUMMARY_SUFFIX = "</summary>"

@dataclass(frozen=True)
class ToolResultReductionPotential:
    max_chars: int
    aggregate_budget_chars: int
    tool_result_count: int
    total_tool_result_chars: int
    oversized_count: int
    oversized_reducible_chars: int
    aggregate_reducible_chars: int
    max_reducible_chars: int


@dataclass(frozen=True)
class PreemptiveCompactionDecision:
    route: str
    should_compact: bool
    estimated_prompt_tokens: int
    pressure_source: str
    prompt_budget_before_reserve: int
    overflow_tokens: int
    tool_result_reducible_chars: int
    effective_reserve_tokens: int


@dataclass(frozen=True)
class SessionToolResultTruncationResult:
    truncated: bool
    truncated_count: int
    reason: str | None = None
    tool_texts: tuple[str, ...] = ()
    tool_contents: tuple[str | None, ...] = ()


def estimate_string_token_pressure(text: str, chars_per_token: int = ESTIMATED_CHARS_PER_TOKEN) -> int:
    return math.ceil(estimate_string_chars(text) / chars_per_token)


def _serialize_json_payload(value: Any) -> str | None:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def estimate_json_payload_token_pressure(
    value: Any, chars_per_token: int = JSON_PAYLOAD_CHARS_PER_TOKEN
) -> int:
    serialized = _serialize_json_payload(value)
    if serialized is None:
        return 256
    return math.ceil(estimate_string_chars(serialized) / chars_per_token)


def estimate_identifier_token_pressure(
    value: Any, chars_per_token: int = JSON_PAYLOAD_CHARS_PER_TOKEN
) -> int:
    if value is None:
        return 0
    if isinstance(value, str | int | float | bool):
        return estimate_string_token_pressure(str(value), chars_per_token)
    return estimate_json_payload_token_pressure(value, chars_per_token)


def estimate_content_block_token_pressure(
    block: Any, chars_per_token: int = ESTIMATED_CHARS_PER_TOKEN
) -> int:
    if isinstance(block, str):
        return estimate_string_token_pressure(block, chars_per_token)
    if not isinstance(block, dict):
        return estimate_json_payload_token_pressure(block, chars_per_token)
    block_type = block.get("type")
    if block_type == "text" and isinstance(block.get("text"), str):
        return CONTENT_BLOCK_OVERHEAD_TOKENS + estimate_string_token_pressure(
            block["text"], chars_per_token
        )
    if block_type == "thinking" and isinstance(block.get("thinking"), str):
        return CONTENT_BLOCK_OVERHEAD_TOKENS + estimate_string_token_pressure(
            block["thinking"], chars_per_token
        )
    if block_type == "image":
        return IMAGE_BLOCK_TOKENS
    return CONTENT_BLOCK_OVERHEAD_TOKENS + estimate_json_payload_token_pressure(
        block, chars_per_token
    )


def _estimate_tool_result_string_token_pressure(text: str) -> int:
    conservative_estimate = math.ceil(utf16_len(text) / TOOL_RESULT_CHARS_PER_TOKEN)
    cjk_aware_estimate = estimate_string_token_pressure(text)
    return max(conservative_estimate, cjk_aware_estimate)


def _estimate_tool_result_json_token_pressure(value: Any) -> int:
    serialized = _serialize_json_payload(value)
    if serialized is None:
        return 256
    return _estimate_tool_result_string_token_pressure(serialized)


def _estimate_tool_result_block_token_pressure(block: Any) -> int:
    if isinstance(block, str):
        return _estimate_tool_result_string_token_pressure(block)
    if not isinstance(block, dict):
        return _estimate_tool_result_json_token_pressure(block)
    block_type = block.get("type")
    if block_type == "text" and isinstance(block.get("text"), str):
        return CONTENT_BLOCK_OVERHEAD_TOKENS + _estimate_tool_result_string_token_pressure(
            block["text"]
        )
    if block_type == "thinking" and isinstance(block.get("thinking"), str):
        return CONTENT_BLOCK_OVERHEAD_TOKENS + _estimate_tool_result_string_token_pressure(
            block["thinking"]
        )
    if block_type == "image":
        return IMAGE_BLOCK_TOKENS
    return CONTENT_BLOCK_OVERHEAD_TOKENS + _estimate_tool_result_json_token_pressure(block)


def estimate_tool_result_content_token_pressure(content: Any) -> int:
    if isinstance(content, str):
        return _estimate_tool_result_string_token_pressure(content)
    if isinstance(content, list):
        return sum(_estimate_tool_result_block_token_pressure(block) for block in content)
    if content is not None:
        return _estimate_tool_result_json_token_pressure(content)
    return 0


def estimate_assistant_tool_call_token_pressure(block: dict[str, Any]) -> int:
    args = block.get("arguments", block.get("input", block.get("args", {})))
    return (
        CONTENT_BLOCK_OVERHEAD_TOKENS
        + estimate_identifier_token_pressure(block.get("name"), JSON_PAYLOAD_CHARS_PER_TOKEN)
        + estimate_json_payload_token_pressure(args, JSON_PAYLOAD_CHARS_PER_TOKEN)
    )


def estimate_content_token_pressure(content: Any) -> int:
    if isinstance(content, str):
        return estimate_string_token_pressure(content)
    if isinstance(content, list):
        return sum(estimate_content_block_token_pressure(block) for block in content)
    if content is not None:
        return estimate_json_payload_token_pressure(content)
    return 0


def _is_tool_result_message(message: dict[str, Any]) -> bool:
    return message.get("role") in {"toolResult", "tool"} or message.get("type") == "toolResult"


def bash_execution_to_text(message: dict[str, Any]) -> str:
    command = message.get("command")
    text = f"Ran `{command if command is not None else ''}`\n"
    output = message.get("output")
    if output:
        text += f"```\n{output}\n```"
    else:
        text += "(no output)"
    exit_code = message.get("exitCode")
    if message.get("cancelled"):
        text += "\n\n(command cancelled)"
    elif exit_code is not None and exit_code != 0:
        text += f"\n\nCommand exited with code {exit_code}"
    if message.get("truncated") and message.get("fullOutputPath"):
        text += f"\n\n[Output truncated. Full output: {message['fullOutputPath']}]"
    return text


def estimate_message_token_pressure(message: dict[str, Any]) -> int:
    tokens = MESSAGE_BOUNDARY_OVERHEAD_TOKENS
    if _is_tool_result_message(message):
        tokens += estimate_tool_result_content_token_pressure(message.get("content"))
        tokens += estimate_identifier_token_pressure(
            message.get("toolName", message.get("tool_name"))
        )
        return tokens
    role = message.get("role")
    if role == "bashExecution":
        if message.get("excludeFromContext") is True:
            return 0
        tokens += estimate_string_token_pressure(bash_execution_to_text(message))
        return tokens
    if role == "branchSummary":
        summary = message.get("summary")
        summary = summary if isinstance(summary, str) else ""
        tokens += estimate_string_token_pressure(
            BRANCH_SUMMARY_PREFIX + summary + BRANCH_SUMMARY_SUFFIX
        )
        return tokens
    if role == "compactionSummary":
        summary = message.get("summary")
        summary = summary if isinstance(summary, str) else ""
        tokens += estimate_string_token_pressure(
            COMPACTION_SUMMARY_PREFIX + summary + COMPACTION_SUMMARY_SUFFIX
        )
        return tokens
    if role == "assistant":
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") in {"toolCall", "tool_use"}:
                    tokens += estimate_assistant_tool_call_token_pressure(block)
                else:
                    tokens += estimate_content_block_token_pressure(block)
        else:
            tokens += estimate_content_token_pressure(content)
        tool_calls = message.get("toolCalls", message.get("tool_calls"))
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                tokens += (
                    estimate_assistant_tool_call_token_pressure(tool_call)
                    if isinstance(tool_call, dict)
                    else estimate_json_payload_token_pressure(tool_call)
                )
        return tokens
    tokens += estimate_content_token_pressure(message.get("content"))
    return tokens


def estimate_pre_prompt_tokens(
    *, messages: list[dict[str, Any]], system_prompt: str | None = None, prompt: str
) -> int:
    history_tokens = sum(estimate_message_token_pressure(message) for message in messages)
    system_tokens = (
        MESSAGE_BOUNDARY_OVERHEAD_TOKENS + estimate_string_token_pressure(system_prompt)
        if isinstance(system_prompt, str) and system_prompt.strip()
        else 0
    )
    prompt_tokens = MESSAGE_BOUNDARY_OVERHEAD_TOKENS + estimate_string_token_pressure(prompt)
    return max(0, math.ceil((history_tokens + system_tokens + prompt_tokens) * SAFETY_MARGIN))


def resolve_auto_live_tool_result_max_chars(context_window_tokens: int | float) -> int:
    if not math.isfinite(context_window_tokens):
        return DEFAULT_MAX_LIVE_TOOL_RESULT_CHARS
    tokens = math.floor(context_window_tokens)
    if tokens >= XL_CONTEXT_TOOL_RESULT_TOKENS:
        return XL_CONTEXT_MAX_LIVE_TOOL_RESULT_CHARS
    if tokens >= LARGE_CONTEXT_TOOL_RESULT_TOKENS:
        return LARGE_CONTEXT_MAX_LIVE_TOOL_RESULT_CHARS
    return DEFAULT_MAX_LIVE_TOOL_RESULT_CHARS


def calculate_max_tool_result_chars_with_cap(
    context_window_tokens: int | float, hard_cap_chars: int
) -> int:
    max_tokens = math.floor(context_window_tokens * MAX_TOOL_RESULT_CONTEXT_SHARE)
    max_chars = max_tokens * 4
    return min(max_chars, max(1, hard_cap_chars))


def calculate_max_tool_result_chars(context_window_tokens: int | float) -> int:
    return calculate_max_tool_result_chars_with_cap(
        context_window_tokens, resolve_auto_live_tool_result_max_chars(context_window_tokens)
    )


def _is_tool_result_text_block(block: Any) -> bool:
    # OpenClaw HEAD also truncates Codex-style blocks typed "toolResult".
    return (
        isinstance(block, dict)
        and block.get("type") in {"text", "toolResult"}
        and isinstance(block.get("text"), str)
    )


def get_tool_result_text_length(message: dict[str, Any]) -> int:
    if not isinstance(message, dict) or message.get("role") != "toolResult":
        return 0
    content = message.get("content")
    if not isinstance(content, list):
        return 0
    return sum(
        estimate_string_chars(block["text"]) for block in content if _is_tool_result_text_block(block)
    )


def _default_suffix_length() -> int:
    return estimate_string_chars(_default_suffix(1))


def _compact_recovery_suffix_length() -> int:
    return estimate_string_chars(_compact_recovery_suffix(1))


def _default_suffix(truncated_chars: int) -> str:
    return (
        f"[... {max(1, math.floor(truncated_chars))} more characters truncated; "
        "rerun with narrower args if needed]"
    )


def _compact_recovery_suffix(truncated_chars: int) -> str:
    return f"[... {max(1, math.floor(truncated_chars))} chars truncated; narrow args]"


def _has_important_tail(text: str) -> bool:
    tail = _js_lower(slice_utf16_safe(text, -2000))
    return bool(
        re.search(r"\b(error|exception|failed|fatal|traceback|panic|stack trace|errno|exit code)\b", tail)
        or re.search(r"}\s*$", tail.strip())
        or re.search(r"\b(total|summary|result|complete|finished|done)\b", tail)
    )


def _js_lower(text: str) -> str:
    return text.lower()


def _resolve_suffix_factory(
    suffix: str | Callable[[int], str] | None,
) -> Callable[[int], str]:
    if callable(suffix):
        return suffix
    if isinstance(suffix, str):
        return lambda _truncated_chars: suffix
    return _default_suffix


def _resolve_effective_min_keep_chars(
    *,
    max_chars: int | float,
    min_keep_chars: int,
    suffix_factory: Any,
    minimum_raw_weight: int | float | None = None,
) -> int | float:
    suffix_floor = estimate_string_chars_with_minimum_raw_weight(
        suffix_factory(1), minimum_raw_weight
    )
    return max(0, min(min_keep_chars, max(0, max_chars - suffix_floor)))


def _append_bounded_truncation_suffix(
    *,
    kept_text: str,
    original_text_length: int,
    max_chars: int | float,
    suffix_factory: Any,
    minimum_raw_weight: int | float | None = None,
) -> str:
    def weigh(value: str) -> int | float:
        return estimate_string_chars_with_minimum_raw_weight(value, minimum_raw_weight)

    while True:
        suffix = suffix_factory(max(1, original_text_length - utf16_len(kept_text)))
        suffix_chars = weigh(suffix)
        if suffix_chars >= max_chars:
            full_omission_suffix = suffix_factory(max(1, original_text_length))
            return slice_tool_result_text_to_budget(
                full_omission_suffix, max_chars, minimum_raw_weight
            )
        next_kept_text = slice_tool_result_text_to_budget(
            kept_text, max_chars - suffix_chars, minimum_raw_weight
        )
        final_text = next_kept_text + suffix
        if len(next_kept_text) == len(kept_text) and weigh(final_text) <= max_chars:
            return final_text
        if len(next_kept_text) == 0 and len(kept_text) == 0:
            return slice_tool_result_text_to_budget(final_text, max_chars, minimum_raw_weight)
        kept_text = next_kept_text


def truncate_tool_result_text(
    text: str,
    max_chars: int | float,
    *,
    suffix: str | Callable[[int], str] | None = None,
    min_keep_chars: int = MIN_KEEP_CHARS,
    minimum_raw_weight: int | float | None = None,
) -> str:
    """Truncate text while preserving an important diagnostic tail (budgets are CJK-weighted)."""

    suffix_factory = _resolve_suffix_factory(suffix)

    def weigh(value: str) -> int | float:
        return estimate_string_chars_with_minimum_raw_weight(value, minimum_raw_weight)

    effective_min_keep_chars = _resolve_effective_min_keep_chars(
        max_chars=max_chars,
        min_keep_chars=min_keep_chars,
        suffix_factory=suffix_factory,
        minimum_raw_weight=minimum_raw_weight,
    )
    text_length = utf16_len(text)
    if text_length <= max_chars and weigh(text) <= max_chars:
        return text
    initial_kept_text = slice_tool_result_text_to_budget(text, max_chars, minimum_raw_weight)
    default_suffix = suffix_factory(max(1, text_length - utf16_len(initial_kept_text)))
    budget = max(effective_min_keep_chars, max_chars - weigh(default_suffix))

    if _has_important_tail(text) and budget > effective_min_keep_chars * 2:
        tail_budget = min(math.floor(budget * 0.3), 4_000)
        head_budget = budget - tail_budget - weigh(MIDDLE_OMISSION_MARKER)
        if head_budget > effective_min_keep_chars:
            head_text = slice_tool_result_text_to_budget(text, head_budget, minimum_raw_weight)
            head_newline = _last_index_of_newline(head_text)
            if head_newline > utf16_len(head_text) * 0.8:
                head_text = slice_utf16_safe(head_text, 0, head_newline)

            tail_text = slice_tool_result_text_tail_to_budget(text, tail_budget, minimum_raw_weight)
            tail_newline = _index_of_newline(tail_text)
            if tail_newline != -1 and tail_newline < utf16_len(tail_text) * 0.2:
                tail_text = slice_utf16_safe(tail_text, tail_newline + 1)

            if utf16_len(head_text) + utf16_len(tail_text) < text_length:
                return _append_bounded_truncation_suffix(
                    kept_text=head_text + MIDDLE_OMISSION_MARKER + tail_text,
                    original_text_length=text_length,
                    max_chars=max_chars,
                    suffix_factory=suffix_factory,
                    minimum_raw_weight=minimum_raw_weight,
                )

    kept_text = slice_tool_result_text_to_budget(text, budget, minimum_raw_weight)
    last_newline = _last_index_of_newline(kept_text)
    if last_newline > utf16_len(kept_text) * 0.8:
        kept_text = slice_utf16_safe(kept_text, 0, last_newline)
    return _append_bounded_truncation_suffix(
        kept_text=kept_text,
        original_text_length=text_length,
        max_chars=max_chars,
        suffix_factory=suffix_factory,
        minimum_raw_weight=minimum_raw_weight,
    )


def _last_index_of_newline(text: str) -> int:
    index = text.rfind("\n")
    return -1 if index < 0 else utf16_len(text[:index])


def _index_of_newline(text: str) -> int:
    index = text.find("\n")
    return -1 if index < 0 else utf16_len(text[:index])


def truncate_tool_result_message(
    message: dict[str, Any],
    max_chars: int | float,
    *,
    suffix: str | Callable[[int], str] | None = None,
    min_keep_chars: int = MIN_KEEP_CHARS,
    minimum_raw_weight: int | float | None = None,
) -> dict[str, Any]:
    suffix_factory = _resolve_suffix_factory(suffix)

    def weigh(value: str) -> int | float:
        return estimate_string_chars_with_minimum_raw_weight(value, minimum_raw_weight)

    effective_min_keep_chars = _resolve_effective_min_keep_chars(
        max_chars=max_chars,
        min_keep_chars=min_keep_chars,
        suffix_factory=suffix_factory,
        minimum_raw_weight=minimum_raw_weight,
    )
    content = message.get("content")
    if not isinstance(content, list):
        return message

    block_text_chars = [
        weigh(block["text"]) if _is_tool_result_text_block(block) else 0 for block in content
    ]
    total_text_chars = sum(block_text_chars)
    if total_text_chars <= max_chars:
        return message

    # A caller's raw-text safety floor changes cost, not which semantic blocks are short.
    # Reserve their actual weighted cost before shrinking larger text.
    small_blocks = [
        block_text_chars[index] > 0
        and _is_tool_result_text_block(block)
        and utf16_len(block["text"]) <= effective_min_keep_chars
        and estimate_string_chars(block["text"]) <= effective_min_keep_chars
        for index, block in enumerate(content)
    ]
    block_notice_chars = [
        weigh(suffix_factory(max(1, utf16_len(block["text"]))))
        if block_text_chars[index] > 0 and _is_tool_result_text_block(block)
        else 0
        for index, block in enumerate(content)
    ]
    small_block_chars = sum(c for c, small in zip(block_text_chars, small_blocks) if small)
    large_block_notice_chars = sum(c for c, small in zip(block_notice_chars, small_blocks) if not small)
    # Preserve short semantic blocks when larger ones can retain a complete truncation notice.
    preserve_small_blocks = small_block_chars + large_block_notice_chars <= max_chars
    preserved_chars = small_block_chars if preserve_small_blocks else 0
    remaining_budget = max(0, max_chars - preserved_chars)
    reducible_chars = total_text_chars - preserved_chars
    reducible_notice_chars = (
        large_block_notice_chars if preserve_small_blocks else sum(block_notice_chars)
    )
    notice_scale = (
        min(1, remaining_budget / reducible_notice_chars) if reducible_notice_chars > 0 else 0
    )
    distributable_budget = max(0, remaining_budget - reducible_notice_chars)

    new_content: list[Any] = []
    for index, block in enumerate(content):
        if not _is_tool_result_text_block(block):
            new_content.append(block)
            continue
        text_chars = block_text_chars[index]
        preserve_block = preserve_small_blocks and small_blocks[index]
        block_share = text_chars / reducible_chars if reducible_chars > 0 else 0
        notice_budget = block_notice_chars[index] * notice_scale
        block_budget = (
            text_chars
            if preserve_block
            else math.floor(notice_budget + distributable_budget * block_share)
        )
        block_min_keep_chars = (
            text_chars if preserve_block else math.floor(effective_min_keep_chars * block_share)
        )
        truncated_text = truncate_tool_result_text(
            block["text"],
            block_budget,
            suffix=suffix_factory,
            min_keep_chars=block_min_keep_chars,
            minimum_raw_weight=minimum_raw_weight,
        )
        next_block = {**block, "text": truncated_text}
        if isinstance(block.get("content"), str):
            next_block["content"] = truncated_text
        new_content.append(next_block)
    return {**message, "content": new_content}


@dataclass(frozen=True)
class _AggregateElisionMarkers:
    full: str
    compact: str
    truncation_suffix: Callable[[int], str]


def format_full_output_footer(path: str) -> str:
    return f"Full output: {path}"


def _get_tool_result_spill_details(message: dict[str, Any]) -> dict[str, Any] | None:
    details = message.get("details")
    if not isinstance(details, dict):
        return None
    full_output_path = details.get("fullOutputPath")
    if not isinstance(full_output_path, str) or not full_output_path:
        return None
    spilled_chars = details.get("spilledChars")
    normalized_spilled_chars = (
        max(0, math.floor(spilled_chars))
        if isinstance(spilled_chars, int | float)
        and not isinstance(spilled_chars, bool)
        and math.isfinite(spilled_chars)
        else None
    )
    return {
        "full_output_path": full_output_path,
        "spill_truncated": details.get("spillTruncated") is True,
        "spilled_chars": normalized_spilled_chars,
    }


def _tool_result_text_contains_full_output_footer(
    message: dict[str, Any], full_output_path: str
) -> bool:
    content = message.get("content")
    if not isinstance(content, list):
        return False
    footer = format_full_output_footer(full_output_path)
    escaped_footer = json.dumps(footer, ensure_ascii=False)[1:-1]
    return any(
        _is_tool_result_text_block(block)
        and (footer in block["text"] or escaped_footer in block["text"])
        for block in content
    )


def _resolve_aggregate_elision_markers(
    message: dict[str, Any],
) -> _AggregateElisionMarkers | None:
    spill = _get_tool_result_spill_details(message)
    if spill is None:
        return None
    # Details alone are not model-visible. Only preserve paths that already
    # appeared in the original footer, so elision discloses nothing new.
    if not _tool_result_text_contains_full_output_footer(message, spill["full_output_path"]):
        return None
    # Aggregate elision is a rare recovery path, not a request hot path; one
    # existence check avoids pointing the model at already-deleted spill files.
    if not os.path.exists(spill["full_output_path"]):
        return None
    path = spill["full_output_path"]
    if spill["spill_truncated"]:
        count = (
            "capped content"
            if spill["spilled_chars"] is None
            else f"first {spill['spilled_chars']} chars"
        )
        return _AggregateElisionMarkers(
            full=(
                f"[tool result elided: partial output preserved at {path} ({count}); "
                "read it if the output is needed]"
            ),
            compact=f"[partial: {path}]",
            truncation_suffix=lambda truncated_chars: (
                f"[... {max(1, math.floor(truncated_chars))} chars truncated; "
                f"partial output at {path}]"
            ),
        )
    return _AggregateElisionMarkers(
        full=(
            f"[tool result elided: full output preserved at {path}; "
            "read it if the output is needed]"
        ),
        compact=f"[read {path}]",
        truncation_suffix=lambda truncated_chars: (
            f"[... {max(1, math.floor(truncated_chars))} chars truncated; "
            f"full output at {path}]"
        ),
    )


def _format_aggregate_elision_text(
    remaining_text_budget: int | float,
    spill_markers: _AggregateElisionMarkers | None,
) -> str:
    if remaining_text_budget <= 0:
        return ""
    if spill_markers is not None and len(spill_markers.full) <= remaining_text_budget:
        return spill_markers.full
    if spill_markers is not None and len(spill_markers.compact) <= remaining_text_budget:
        return spill_markers.compact
    if remaining_text_budget >= len(AGGREGATE_ELISION_MARKER):
        return AGGREGATE_ELISION_MARKER
    return AGGREGATE_ELISION_MARKER[: math.floor(remaining_text_budget)]


def _clear_tool_result_text(
    message: dict[str, Any],
    max_text_chars: int | float = math.inf,
    resolved_spill_markers: _AggregateElisionMarkers | None = None,
) -> dict[str, Any]:
    content = message.get("content")
    if not isinstance(content, list):
        return message
    remaining_text_budget: int | float = (
        max(0, math.floor(max_text_chars)) if math.isfinite(max_text_chars) else max_text_chars
    )
    spill_markers = resolved_spill_markers or _resolve_aggregate_elision_markers(message)
    if spill_markers is not None:
        # The pointer is what makes elision recoverable. ~130 chars per entry is
        # negligible against the 64k+ aggregate floor, and accounting uses actual lengths.
        remaining_text_budget = max(remaining_text_budget, len(spill_markers.compact))
    new_content: list[Any] = []
    for block in content:
        if not _is_tool_result_text_block(block):
            new_content.append(block)
            continue
        replacement_text = _format_aggregate_elision_text(remaining_text_budget, spill_markers)
        remaining_text_budget = max(0, remaining_text_budget - len(replacement_text))
        next_block = {**block, "text": replacement_text}
        if isinstance(block.get("content"), str):
            next_block["content"] = replacement_text
        new_content.append(next_block)
    return {**message, "content": new_content}


def _get_trailing_tool_result_entry_ids(branch: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    saw_message = False
    for entry in reversed(branch):
        message = entry.get("message")
        if entry.get("type") != "message" or not isinstance(message, dict) or not message:
            if not saw_message:
                continue
            break
        saw_message = True
        if message.get("role") != "toolResult":
            break
        entry_id = entry.get("id")
        if isinstance(entry_id, str):
            ids.add(entry_id)
    return ids


def _build_oversized_tool_result_replacements(
    *,
    branch: list[dict[str, Any]],
    max_chars: int,
    min_keep_chars: int = MIN_KEEP_CHARS,
    protected_entry_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    replacements: list[dict[str, Any]] = []
    for entry in branch:
        if entry.get("type") != "message":
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "toolResult":
            continue
        if get_tool_result_text_length(message) <= max_chars:
            continue
        replacement_min_keep_chars = (
            max(min_keep_chars, MIN_KEEP_CHARS)
            if protected_entry_ids is not None and entry.get("id") in protected_entry_ids
            else min_keep_chars
        )
        spill_markers = _resolve_aggregate_elision_markers(message)
        suffix_factory = spill_markers.truncation_suffix if spill_markers is not None else None
        entry_max_chars = max(
            max_chars, len(suffix_factory(1)) if suffix_factory is not None else 0
        )
        replacements.append(
            {
                "entry_id": entry.get("id"),
                "message": truncate_tool_result_message(
                    message,
                    entry_max_chars,
                    suffix=suffix_factory,
                    min_keep_chars=replacement_min_keep_chars,
                ),
            }
        )
    return replacements


def _build_aggregate_tool_result_replacements(
    *,
    branch: list[dict[str, Any]],
    spill_source_branch: list[dict[str, Any]] | None = None,
    aggregate_budget_chars: int,
    min_keep_chars: int = MIN_KEEP_CHARS,
    protect_trailing_tool_results: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    protected_entry_ids = (
        _get_trailing_tool_result_entry_ids(branch) if protect_trailing_tool_results else set()
    )
    candidates: list[dict[str, Any]] = []
    for index, entry in enumerate(branch):
        if entry.get("type") != "message":
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "toolResult":
            continue
        text_length = get_tool_result_text_length(message)
        if text_length <= 0:
            continue
        spill_source_message = message
        if spill_source_branch is not None and index < len(spill_source_branch):
            source_message = spill_source_branch[index].get("message")
            if isinstance(source_message, dict):
                spill_source_message = source_message
        candidates.append(
            {
                "index": index,
                "entry_id": entry.get("id"),
                "message": message,
                "spill_source_message": spill_source_message,
                "text_length": text_length,
                "protected": entry.get("id") in protected_entry_ids,
            }
        )

    if len(candidates) < 2:
        return [], False

    suffix_factory = (
        _compact_recovery_suffix
        if min_keep_chars == RECOVERY_MIN_KEEP_CHARS
        and aggregate_budget_chars < len(candidates) * _default_suffix_length()
        else _default_suffix
    )
    min_truncated_text_chars = min_keep_chars + len(suffix_factory(1))

    total_chars = sum(candidate["text_length"] for candidate in candidates)
    if total_chars <= aggregate_budget_chars:
        return [], False

    remaining_reduction = total_chars - aggregate_budget_chars
    replacements: list[dict[str, Any]] = []
    # Spend aggregate reduction on older entries first so fresh tool output stays intact.
    recovery_candidates = sorted(
        (candidate for candidate in candidates if not candidate["protected"]),
        key=lambda candidate: (candidate["index"], -candidate["text_length"]),
    )

    for candidate in recovery_candidates:
        if remaining_reduction <= 0:
            break
        reducible_chars = max(0, candidate["text_length"] - min_truncated_text_chars)
        if reducible_chars <= 0:
            continue

        requested_reduction = min(reducible_chars, remaining_reduction)
        target_chars = max(min_truncated_text_chars, candidate["text_length"] - requested_reduction)
        spill_markers = _resolve_aggregate_elision_markers(candidate["spill_source_message"])
        candidate_suffix_factory = (
            spill_markers.truncation_suffix if spill_markers is not None else suffix_factory
        )
        candidate_target_chars = max(target_chars, len(candidate_suffix_factory(1)))
        truncated_message = truncate_tool_result_message(
            candidate["message"],
            candidate_target_chars,
            suffix=candidate_suffix_factory,
            min_keep_chars=min_keep_chars,
        )
        new_length = get_tool_result_text_length(truncated_message)
        actual_reduction = max(0, candidate["text_length"] - new_length)
        if actual_reduction <= 0:
            continue

        replacements.append({"entry_id": candidate["entry_id"], "message": truncated_message})
        remaining_reduction -= actual_reduction

    if remaining_reduction > 0:
        for candidate in recovery_candidates:
            if remaining_reduction <= 0:
                break
            existing_index = next(
                (
                    index
                    for index, replacement in enumerate(replacements)
                    if replacement["entry_id"] == candidate["entry_id"]
                ),
                None,
            )
            base_message = (
                replacements[existing_index]["message"]
                if existing_index is not None
                else candidate["message"]
            )
            base_text_length = get_tool_result_text_length(base_message)
            target_text_chars = max(0, base_text_length - remaining_reduction)
            spill_markers = _resolve_aggregate_elision_markers(candidate["spill_source_message"])
            empty_message = _clear_tool_result_text(
                candidate["message"], target_text_chars, spill_markers
            )
            actual_reduction = max(
                0, base_text_length - get_tool_result_text_length(empty_message)
            )
            if actual_reduction <= 0 and spill_markers is None:
                continue
            replacement = {"entry_id": candidate["entry_id"], "message": empty_message}
            if existing_index is not None:
                replacements[existing_index] = replacement
            else:
                replacements.append(replacement)
            remaining_reduction -= actual_reduction

    return replacements, True


def _calculate_replacement_reduction(
    branch: list[dict[str, Any]], replacements: list[dict[str, Any]]
) -> int:
    if not replacements:
        return 0
    branch_by_id = {
        entry.get("id"): entry for entry in branch if isinstance(entry.get("id"), str)
    }
    reduction = 0
    for replacement in replacements:
        entry = branch_by_id.get(replacement["entry_id"])
        message = entry.get("message") if entry is not None else None
        if not isinstance(message, dict):
            continue
        reduction += max(
            0,
            get_tool_result_text_length(message)
            - get_tool_result_text_length(replacement["message"]),
        )
    return reduction


def _apply_tool_result_replacements_to_branch(
    branch: list[dict[str, Any]], replacements: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if not replacements:
        return branch
    replacements_by_id = {replacement["entry_id"]: replacement for replacement in replacements}
    next_branch: list[dict[str, Any]] = []
    for entry in branch:
        replacement = replacements_by_id.get(entry.get("id"))
        if replacement is None or entry.get("type") != "message":
            next_branch.append(entry)
        else:
            next_branch.append({**entry, "message": replacement["message"]})
    return next_branch


@dataclass(frozen=True)
class ToolResultReplacementPlan:
    replacements: tuple[dict[str, Any], ...]
    oversized_replacement_count: int
    aggregate_replacement_count: int
    aggregate_pressure_exceeded: bool
    oversized_reducible_chars: int
    aggregate_reducible_chars: int
    replacement_messages_by_entry_id: dict[str, dict[str, Any]] = field(default_factory=dict)


def build_tool_result_replacement_plan(
    *,
    branch: list[dict[str, Any]],
    max_chars: int,
    aggregate_budget_chars: int,
    min_keep_chars: int = MIN_KEEP_CHARS,
    protect_trailing_tool_results: bool = False,
) -> ToolResultReplacementPlan:
    protected_entry_ids = (
        _get_trailing_tool_result_entry_ids(branch) if protect_trailing_tool_results else None
    )
    oversized_replacements = _build_oversized_tool_result_replacements(
        branch=branch,
        max_chars=max_chars,
        min_keep_chars=min_keep_chars,
        protected_entry_ids=protected_entry_ids,
    )
    oversized_reducible_chars = _calculate_replacement_reduction(branch, oversized_replacements)
    oversized_trimmed_branch = _apply_tool_result_replacements_to_branch(
        branch, oversized_replacements
    )
    aggregate_replacements, aggregate_pressure_exceeded = (
        _build_aggregate_tool_result_replacements(
            branch=oversized_trimmed_branch,
            spill_source_branch=branch,
            aggregate_budget_chars=aggregate_budget_chars,
            min_keep_chars=min_keep_chars,
            protect_trailing_tool_results=protect_trailing_tool_results,
        )
    )
    aggregate_reducible_chars = _calculate_replacement_reduction(
        oversized_trimmed_branch, aggregate_replacements
    )
    all_replacements = [*oversized_replacements, *aggregate_replacements]
    # Aggregate replacements are computed on top of the oversized-trimmed branch,
    # so on entry-id collisions the aggregate message wins (matches OpenClaw's Map).
    replacement_messages_by_entry_id = {
        replacement["entry_id"]: replacement["message"]
        for replacement in all_replacements
        if isinstance(replacement["entry_id"], str) and replacement["entry_id"].strip()
    }
    return ToolResultReplacementPlan(
        replacements=tuple(all_replacements),
        oversized_replacement_count=len(oversized_replacements),
        aggregate_replacement_count=len(aggregate_replacements),
        aggregate_pressure_exceeded=aggregate_pressure_exceeded,
        oversized_reducible_chars=oversized_reducible_chars,
        aggregate_reducible_chars=aggregate_reducible_chars,
        replacement_messages_by_entry_id=replacement_messages_by_entry_id,
    )


def resolve_live_tool_result_aggregate_max_chars(
    *,
    context_window_tokens: int,
    per_result_max_chars: int,
) -> int:
    per_result = max(1, int(per_result_max_chars))
    window = max(1, int(context_window_tokens)) if context_window_tokens > 0 else 1
    context_share_chars = int(window * 4 * AGGREGATE_TOOL_RESULT_CONTEXT_SHARE)
    return max(per_result * PROMPT_TOOL_RESULT_AGGREGATE_CAP_MULTIPLIER, context_share_chars)


def _recovery_aggregate_tool_result_chars(
    context_window_tokens: int,
    max_chars_override: int | None = None,
    aggregate_max_chars_override: int | None = None,
) -> int:
    if aggregate_max_chars_override is not None:
        return max(1, aggregate_max_chars_override)
    return max(
        1,
        resolve_live_tool_result_aggregate_max_chars(
            context_window_tokens=context_window_tokens,
            per_result_max_chars=(
                max_chars_override
                if max_chars_override is not None
                else calculate_max_tool_result_chars(context_window_tokens)
            ),
        ),
    )


def estimate_tool_result_reduction_potential(
    *,
    messages: list[dict[str, Any]],
    context_window_tokens: int,
    max_chars_override: int | None = None,
    aggregate_max_chars_override: int | None = None,
) -> ToolResultReductionPotential:
    max_chars = max(1, max_chars_override or calculate_max_tool_result_chars(context_window_tokens))
    aggregate_budget_chars = _recovery_aggregate_tool_result_chars(
        context_window_tokens,
        max_chars,
        aggregate_max_chars_override,
    )
    branch = [
        {"id": f"message-{index}", "type": "message", "message": message}
        for index, message in enumerate(messages)
    ]
    tool_result_count = 0
    total_tool_result_chars = 0
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "toolResult":
            continue
        text_length = get_tool_result_text_length(message)
        if text_length <= 0:
            continue
        tool_result_count += 1
        total_tool_result_chars += text_length
    plan = build_tool_result_replacement_plan(
        branch=branch,
        max_chars=max_chars,
        aggregate_budget_chars=aggregate_budget_chars,
        min_keep_chars=RECOVERY_MIN_KEEP_CHARS,
    )
    return ToolResultReductionPotential(
        max_chars=max_chars,
        aggregate_budget_chars=aggregate_budget_chars,
        tool_result_count=tool_result_count,
        total_tool_result_chars=total_tool_result_chars,
        oversized_count=plan.oversized_replacement_count,
        oversized_reducible_chars=plan.oversized_reducible_chars,
        aggregate_reducible_chars=plan.aggregate_reducible_chars,
        max_reducible_chars=plan.oversized_reducible_chars + plan.aggregate_reducible_chars,
    )


def _first_tool_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    for block in content:
        if _is_tool_result_text_block(block):
            return block["text"]
    return ""


def _first_tool_content(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    if not isinstance(content, list):
        return None
    for block in content:
        if _is_tool_result_text_block(block):
            block_content = block.get("content")
            return block_content if isinstance(block_content, str) else None
    return None


def _read_jsonl_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


def _active_branch(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {entry.get("id"): entry for entry in entries if isinstance(entry.get("id"), str)}
    leaf_id = next(
        (entry.get("id") for entry in reversed(entries) if isinstance(entry.get("id"), str)),
        None,
    )
    branch: list[dict[str, Any]] = []
    seen: set[str] = set()
    current_id = leaf_id
    while isinstance(current_id, str) and current_id not in seen:
        seen.add(current_id)
        entry = by_id.get(current_id)
        if not entry:
            break
        branch.append(entry)
        parent_id = entry.get("parentId")
        current_id = parent_id if isinstance(parent_id, str) else None
    branch.reverse()
    return branch


def _append_jsonl_entries(path: Path, entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    with path.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(f"{json.dumps(entry, separators=(',', ':'))}\n")


def _branch_tool_texts(branch: list[dict[str, Any]]) -> tuple[tuple[str, ...], tuple[str | None, ...]]:
    texts: list[str] = []
    contents: list[str | None] = []
    for entry in branch:
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "toolResult":
            continue
        texts.append(_first_tool_text(message))
        contents.append(_first_tool_content(message))
    return tuple(texts), tuple(contents)


def truncate_oversized_tool_results_in_session_file(
    session_file: str | Path,
    *,
    context_window_tokens: int,
    max_chars_override: int | None = None,
    aggregate_max_chars_override: int | None = None,
    protect_trailing_tool_results: bool = False,
) -> SessionToolResultTruncationResult:
    path = Path(session_file)
    try:
        entries = _read_jsonl_entries(path)
    except OSError as exc:
        return SessionToolResultTruncationResult(False, 0, str(exc))
    branch = _active_branch(entries)
    if not branch:
        return SessionToolResultTruncationResult(False, 0, "empty session")

    max_chars = max(1, max_chars_override or calculate_max_tool_result_chars(context_window_tokens))
    aggregate_budget_chars = _recovery_aggregate_tool_result_chars(
        context_window_tokens,
        max_chars,
        aggregate_max_chars_override,
    )
    plan = build_tool_result_replacement_plan(
        branch=branch,
        max_chars=max_chars,
        aggregate_budget_chars=aggregate_budget_chars,
        min_keep_chars=RECOVERY_MIN_KEEP_CHARS,
        protect_trailing_tool_results=protect_trailing_tool_results,
    )
    replacements_by_entry_id = plan.replacement_messages_by_entry_id
    if not replacements_by_entry_id:
        texts, contents = _branch_tool_texts(branch)
        return SessionToolResultTruncationResult(
            False,
            0,
            "no oversized or aggregate tool results",
            texts,
            contents,
        )

    first_match = next(
        (
            index
            for index, entry in enumerate(branch)
            if isinstance(entry.get("id"), str) and entry["id"] in replacements_by_entry_id
        ),
        None,
    )
    if first_match is None:
        return SessionToolResultTruncationResult(False, 0, "no matching message entries")

    parent_id = branch[first_match].get("parentId")
    current_parent_id = parent_id if isinstance(parent_id, str) else None
    appended: list[dict[str, Any]] = []
    truncated_count = 0
    for entry in branch[first_match:]:
        old_id = entry.get("id")
        if not isinstance(old_id, str):
            continue
        new_id = uuid4().hex[:8]
        message = entry.get("message")
        replacement = replacements_by_entry_id.get(old_id)
        next_entry = dict(entry)
        next_entry["id"] = new_id
        next_entry["parentId"] = current_parent_id
        if replacement is not None:
            next_entry["message"] = replacement
            truncated_count += 1
        elif isinstance(message, dict):
            next_entry["message"] = message
        current_parent_id = new_id
        appended.append(next_entry)
    _append_jsonl_entries(path, appended)

    after_branch = _active_branch([*entries, *appended])
    texts, contents = _branch_tool_texts(after_branch)
    return SessionToolResultTruncationResult(True, truncated_count, None, texts, contents)


def should_preemptively_compact_before_prompt(
    *,
    messages: list[dict[str, Any]],
    system_prompt: str | None = None,
    prompt: str,
    context_token_budget: int,
    reserve_tokens: int,
    tool_result_max_chars: int | None = None,
    unwindowed_messages: list[dict[str, Any]] | None = None,
) -> PreemptiveCompactionDecision:
    estimated_prompt_tokens = estimate_pre_prompt_tokens(
        messages=messages,
        system_prompt=system_prompt,
        prompt=prompt,
    )
    pressure_source = "transcript_estimate"
    messages_for_pressure = messages
    if unwindowed_messages is not None and unwindowed_messages is not messages:
        unwindowed_estimate = estimate_pre_prompt_tokens(
            messages=unwindowed_messages,
            system_prompt=system_prompt,
            prompt=prompt,
        )
        if unwindowed_estimate > estimated_prompt_tokens:
            estimated_prompt_tokens = unwindowed_estimate
            messages_for_pressure = unwindowed_messages
            pressure_source = "unwindowed_transcript_estimate"

    context_budget = max(1, math.floor(context_token_budget))
    requested_reserve = max(0, math.floor(reserve_tokens))
    min_prompt_budget = min(
        MIN_PROMPT_BUDGET_TOKENS,
        max(1, math.floor(context_budget * MIN_PROMPT_BUDGET_RATIO)),
    )
    effective_reserve = min(requested_reserve, max(0, context_budget - min_prompt_budget))
    prompt_budget_before_reserve = max(1, context_budget - effective_reserve)
    overflow_tokens = max(0, estimated_prompt_tokens - prompt_budget_before_reserve)
    potential = estimate_tool_result_reduction_potential(
        messages=messages_for_pressure,
        context_window_tokens=context_token_budget,
        max_chars_override=tool_result_max_chars,
    )
    overflow_chars = overflow_tokens * ESTIMATED_CHARS_PER_TOKEN
    truncation_buffer_chars = TRUNCATION_ROUTE_BUFFER_TOKENS * ESTIMATED_CHARS_PER_TOKEN
    truncate_only_threshold_chars = max(
        overflow_chars + truncation_buffer_chars,
        math.ceil(overflow_chars * 1.5),
    )
    reducible = potential.max_reducible_chars

    route = "fits"
    if overflow_tokens > 0:
        if reducible <= 0:
            route = "compact_only"
        elif reducible >= truncate_only_threshold_chars:
            route = "truncate_tool_results_only"
        else:
            route = "compact_then_truncate"
    return PreemptiveCompactionDecision(
        route=route,
        should_compact=route in {"compact_only", "compact_then_truncate"},
        estimated_prompt_tokens=estimated_prompt_tokens,
        pressure_source=pressure_source,
        prompt_budget_before_reserve=prompt_budget_before_reserve,
        overflow_tokens=overflow_tokens,
        tool_result_reducible_chars=reducible,
        effective_reserve_tokens=effective_reserve,
    )
