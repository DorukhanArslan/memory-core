from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from collections.abc import Callable
from typing import Any
from uuid import uuid4


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


def estimate_string_token_pressure(text: str, chars_per_token: int = ESTIMATED_CHARS_PER_TOKEN) -> int:
    return math.ceil(len(text) / chars_per_token)


def estimate_json_payload_token_pressure(
    value: Any, chars_per_token: int = JSON_PAYLOAD_CHARS_PER_TOKEN
) -> int:
    try:
        serialized = json.dumps(value, separators=(",", ":"))
    except (TypeError, ValueError):
        return 256
    return math.ceil(len(serialized) / chars_per_token) if isinstance(serialized, str) else 1


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


def estimate_tool_result_content_token_pressure(content: Any) -> int:
    if isinstance(content, str):
        return estimate_string_token_pressure(content, TOOL_RESULT_CHARS_PER_TOKEN)
    if isinstance(content, list):
        return sum(
            estimate_content_block_token_pressure(block, TOOL_RESULT_CHARS_PER_TOKEN)
            for block in content
        )
    if content is not None:
        return estimate_json_payload_token_pressure(content, TOOL_RESULT_CHARS_PER_TOKEN)
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


def estimate_message_token_pressure(message: dict[str, Any]) -> int:
    tokens = MESSAGE_BOUNDARY_OVERHEAD_TOKENS
    if _is_tool_result_message(message):
        tokens += estimate_tool_result_content_token_pressure(message.get("content"))
        tokens += estimate_identifier_token_pressure(
            message.get("toolName", message.get("tool_name"))
        )
        return tokens
    if message.get("role") == "assistant":
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


def get_tool_result_text_length(message: dict[str, Any]) -> int:
    if not _is_tool_result_message(message):
        return 0
    content = message.get("content")
    if not isinstance(content, list):
        return 0
    total = 0
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            total += len(block["text"])
    return total


def _default_suffix_length() -> int:
    return len("[... 1 more characters truncated; rerun with narrower args if needed]")


def _compact_recovery_suffix_length() -> int:
    return len("[... 1 chars truncated; narrow args]")


def _default_suffix(truncated_chars: int) -> str:
    return (
        f"[... {max(1, math.floor(truncated_chars))} more characters truncated; "
        "rerun with narrower args if needed]"
    )


def _has_important_tail(text: str) -> bool:
    tail = text[-2000:].lower().strip()
    return bool(
        re.search(r"\b(error|exception|failed|fatal|traceback|panic|stack trace|errno|exit code)\b", tail)
        or re.search(r"}\s*$", tail)
        or re.search(r"\b(total|summary|result|complete|finished|done)\b", tail)
    )


def _resolve_effective_min_keep_chars(
    *, max_chars: int, min_keep_chars: int, suffix_factory: Any
) -> int:
    suffix_floor = len(suffix_factory(1))
    return max(0, min(min_keep_chars, max(0, max_chars - suffix_floor)))


def _append_bounded_truncation_suffix(
    *,
    kept_text: str,
    original_text_length: int,
    max_chars: int,
    suffix_factory: Any,
) -> str:
    def build(value: str) -> str:
        return value + suffix_factory(max(1, original_text_length - len(value)))

    current = kept_text
    while True:
        final_text = build(current)
        if len(final_text) <= max_chars:
            return final_text
        if len(current) == 0:
            return final_text[:max_chars]
        overflow = len(final_text) - max_chars
        next_kept_text = current[: max(0, len(current) - overflow)]
        current = next_kept_text if len(next_kept_text) < len(current) else current[:-1]


def truncate_tool_result_text(
    text: str,
    max_chars: int,
    *,
    suffix: str | Callable[[int], str] | None = None,
    min_keep_chars: int = MIN_KEEP_CHARS,
) -> str:
    suffix_factory = (
        suffix
        if callable(suffix)
        else (lambda _truncated_chars: suffix)
        if suffix is not None
        else _default_suffix
    )
    effective_min_keep_chars = _resolve_effective_min_keep_chars(
        max_chars=max_chars,
        min_keep_chars=min_keep_chars,
        suffix_factory=suffix_factory,
    )
    if len(text) <= max_chars:
        return text
    default_suffix = suffix_factory(max(1, len(text) - max_chars))
    budget = max(effective_min_keep_chars, max_chars - len(default_suffix))

    if _has_important_tail(text) and budget > effective_min_keep_chars * 2:
        tail_budget = min(math.floor(budget * 0.3), 4_000)
        head_budget = budget - tail_budget - len(MIDDLE_OMISSION_MARKER)
        if head_budget > effective_min_keep_chars:
            head_cut = head_budget
            head_newline = text.rfind("\n", 0, head_budget + 1)
            if head_newline > head_budget * 0.8:
                head_cut = head_newline

            tail_start = len(text) - tail_budget
            tail_newline = text.find("\n", tail_start)
            if tail_newline != -1 and tail_newline < tail_start + tail_budget * 0.2:
                tail_start = tail_newline + 1

            kept_text = text[:head_cut] + MIDDLE_OMISSION_MARKER + text[tail_start:]
            return _append_bounded_truncation_suffix(
                kept_text=kept_text,
                original_text_length=len(text),
                max_chars=max_chars,
                suffix_factory=suffix_factory,
            )

    cut_point = budget
    last_newline = text.rfind("\n", 0, budget + 1)
    if last_newline > budget * 0.8:
        cut_point = last_newline
    kept_text = text[:cut_point]
    return _append_bounded_truncation_suffix(
        kept_text=kept_text,
        original_text_length=len(text),
        max_chars=max_chars,
        suffix_factory=suffix_factory,
    )


def _min_truncated_text_chars(min_keep_chars: int, aggregate_budget_chars: int, candidate_count: int) -> int:
    suffix_length = (
        _compact_recovery_suffix_length()
        if min_keep_chars == RECOVERY_MIN_KEEP_CHARS
        and aggregate_budget_chars < candidate_count * _default_suffix_length()
        else _default_suffix_length()
    )
    return min_keep_chars + suffix_length


def _truncated_length(text_length: int, target_chars: int, min_keep_chars: int) -> int:
    # OpenClaw may shave a few chars to fit the suffix exactly. For routing decisions, the
    # important contract is reducible size and route threshold, not exact replacement text.
    if text_length <= target_chars:
        return text_length
    return max(1, min(text_length, target_chars, max(min_keep_chars, target_chars)))


def _replacement_reductions(
    text_lengths: list[int], max_chars: int, aggregate_budget_chars: int, min_keep_chars: int
) -> tuple[int, int, int]:
    oversized_reductions: list[int] = []
    trimmed_lengths: list[int] = []
    oversized_count = 0
    for length in text_lengths:
        if length > max_chars:
            oversized_count += 1
            new_length = _truncated_length(length, max_chars, min_keep_chars)
            oversized_reductions.append(max(0, length - new_length))
            trimmed_lengths.append(new_length)
        else:
            trimmed_lengths.append(length)

    if len(trimmed_lengths) < 2 or sum(trimmed_lengths) <= aggregate_budget_chars:
        return oversized_count, sum(oversized_reductions), 0

    min_truncated = _min_truncated_text_chars(
        min_keep_chars=min_keep_chars,
        aggregate_budget_chars=aggregate_budget_chars,
        candidate_count=len(trimmed_lengths),
    )
    remaining_reduction = sum(trimmed_lengths) - aggregate_budget_chars
    aggregate_reduction = 0
    indexed = sorted(enumerate(trimmed_lengths), key=lambda item: (-item[0], -item[1]))
    for _, length in indexed:
        if remaining_reduction <= 0:
            break
        reducible = max(0, length - min_truncated)
        if reducible <= 0:
            continue
        requested = min(reducible, remaining_reduction)
        target = max(min_truncated, length - requested)
        new_length = _truncated_length(length, target, min_keep_chars)
        actual = max(0, length - new_length)
        if actual <= 0:
            continue
        aggregate_reduction += actual
        remaining_reduction -= actual
    return oversized_count, sum(oversized_reductions), aggregate_reduction


def _tool_result_replacement_text_lengths(
    text_lengths: list[int], max_chars: int, aggregate_budget_chars: int, min_keep_chars: int
) -> dict[int, int]:
    replacements: dict[int, int] = {}
    trimmed_lengths: list[int] = []
    for index, length in enumerate(text_lengths):
        if length > max_chars:
            new_length = _truncated_length(length, max_chars, min_keep_chars)
            replacements[index] = new_length
            trimmed_lengths.append(new_length)
        else:
            trimmed_lengths.append(length)

    if len(trimmed_lengths) < 2 or sum(trimmed_lengths) <= aggregate_budget_chars:
        return replacements

    min_truncated = _min_truncated_text_chars(
        min_keep_chars=min_keep_chars,
        aggregate_budget_chars=aggregate_budget_chars,
        candidate_count=len(trimmed_lengths),
    )
    remaining_reduction = sum(trimmed_lengths) - aggregate_budget_chars
    indexed = sorted(enumerate(trimmed_lengths), key=lambda item: (-item[0], -item[1]))
    for index, length in indexed:
        if remaining_reduction <= 0:
            break
        reducible = max(0, length - min_truncated)
        if reducible <= 0:
            continue
        requested = min(reducible, remaining_reduction)
        target = max(min_truncated, length - requested)
        new_length = _truncated_length(length, target, min_keep_chars)
        actual = max(0, length - new_length)
        if actual <= 0:
            continue
        replacements[index] = new_length
        trimmed_lengths[index] = new_length
        remaining_reduction -= actual
    return replacements


def _compact_recovery_suffix(truncated_chars: int) -> str:
    return f"[... {max(1, math.floor(truncated_chars))} chars truncated; narrow args]"


def _tool_result_replacement_texts(
    texts: list[str], max_chars: int, aggregate_budget_chars: int, min_keep_chars: int
) -> dict[int, str]:
    replacements: dict[int, str] = {}
    current_texts = list(texts)
    for index, text in enumerate(texts):
        if len(text) > max_chars:
            current_texts[index] = truncate_tool_result_text(
                text,
                max_chars,
                min_keep_chars=min_keep_chars,
            )
            replacements[index] = current_texts[index]

    if len(current_texts) < 2 or sum(len(text) for text in current_texts) <= aggregate_budget_chars:
        return replacements

    min_truncated = _min_truncated_text_chars(
        min_keep_chars=min_keep_chars,
        aggregate_budget_chars=aggregate_budget_chars,
        candidate_count=len(current_texts),
    )
    remaining_reduction = sum(len(text) for text in current_texts) - aggregate_budget_chars
    indexed = sorted(enumerate(current_texts), key=lambda item: (-item[0], -len(item[1])))
    for index, text in indexed:
        if remaining_reduction <= 0:
            break
        reducible = max(0, len(text) - min_truncated)
        if reducible <= 0:
            continue
        requested = min(reducible, remaining_reduction)
        target = max(min_truncated, len(text) - requested)
        truncated = truncate_tool_result_text(
            text,
            target,
            suffix=_compact_recovery_suffix
            if min_keep_chars == RECOVERY_MIN_KEEP_CHARS
            and aggregate_budget_chars < len(current_texts) * _default_suffix_length()
            else None,
            min_keep_chars=min_keep_chars,
        )
        actual = max(0, len(text) - len(truncated))
        if actual <= 0:
            continue
        current_texts[index] = truncated
        replacements[index] = truncated
        remaining_reduction -= actual
    return replacements


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
    text_lengths = [
        get_tool_result_text_length(message)
        for message in messages
        if _is_tool_result_message(message) and get_tool_result_text_length(message) > 0
    ]
    oversized_count, oversized_reducible, aggregate_reducible = _replacement_reductions(
        text_lengths,
        max_chars,
        aggregate_budget_chars,
        RECOVERY_MIN_KEEP_CHARS,
    )
    return ToolResultReductionPotential(
        max_chars=max_chars,
        aggregate_budget_chars=aggregate_budget_chars,
        tool_result_count=len(text_lengths),
        total_tool_result_chars=sum(text_lengths),
        oversized_count=oversized_count,
        oversized_reducible_chars=oversized_reducible,
        aggregate_reducible_chars=aggregate_reducible,
        max_reducible_chars=oversized_reducible + aggregate_reducible,
    )


def _first_tool_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            return block["text"]
    return ""


def _with_first_tool_text(message: dict[str, Any], text: str) -> dict[str, Any]:
    content = message.get("content")
    if not isinstance(content, list):
        return message
    replaced = False
    next_content: list[Any] = []
    for block in content:
        if (
            not replaced
            and isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ):
            next_content.append({**block, "text": text})
            replaced = True
        else:
            next_content.append(block)
    return {**message, "content": next_content}


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


def truncate_oversized_tool_results_in_session_file(
    session_file: str | Path,
    *,
    context_window_tokens: int,
    max_chars_override: int | None = None,
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
    )
    tool_entries: list[tuple[int, dict[str, Any], dict[str, Any], str]] = []
    for branch_index, entry in enumerate(branch):
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "toolResult":
            continue
        text = _first_tool_text(message)
        if text:
            tool_entries.append((branch_index, entry, message, text))
    replacement_texts_by_tool_index = _tool_result_replacement_texts(
        [text for _, _, _, text in tool_entries],
        max_chars,
        aggregate_budget_chars,
        RECOVERY_MIN_KEEP_CHARS,
    )
    if not replacement_texts_by_tool_index:
        return SessionToolResultTruncationResult(
            False,
            0,
            "no oversized or aggregate tool results",
            tuple(text for _, _, _, text in tool_entries),
        )

    replacements_by_entry_id: dict[str, dict[str, Any]] = {}
    for tool_index, replacement_text in replacement_texts_by_tool_index.items():
        _, entry, message, text = tool_entries[tool_index]
        entry_id = entry.get("id")
        if not isinstance(entry_id, str):
            continue
        replacements_by_entry_id[entry_id] = _with_first_tool_text(message, replacement_text)
    if not replacements_by_entry_id:
        return SessionToolResultTruncationResult(False, 0, "no replacements requested")

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
    rewritten_ids: dict[str, str] = {}
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
        rewritten_ids[old_id] = new_id
        current_parent_id = new_id
        appended.append(next_entry)
    _append_jsonl_entries(path, appended)

    after_branch = _active_branch([*entries, *appended])
    tool_texts = tuple(
        _first_tool_text(message)
        for entry in after_branch
        if isinstance((message := entry.get("message")), dict) and message.get("role") == "toolResult"
    )
    return SessionToolResultTruncationResult(True, truncated_count, None, tool_texts)


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
