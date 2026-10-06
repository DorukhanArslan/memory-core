from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from memory_core._tool_result_budget import (
    estimate_string_chars,
    estimate_string_chars_with_minimum_raw_weight,
    slice_tool_result_text_tail_to_budget,
    slice_tool_result_text_to_budget,
)
from memory_core.bootstrap._js import js_json_stringify, js_trim, slice_utf16_safe, utf16_len
from memory_core.compaction_replay import (
    ReplayIdentity,
    ReplayModel,
    default_replay_pressure_estimator,
    resolve_compaction_replay_pressure,
)


ESTIMATED_CHARS_PER_TOKEN = 4
TOOL_RESULT_CHARS_PER_TOKEN = 2
JSON_PAYLOAD_CHARS_PER_TOKEN = 3
MESSAGE_BOUNDARY_OVERHEAD_TOKENS = 12
CONTENT_BLOCK_OVERHEAD_TOKENS = 6
IMAGE_BLOCK_TOKENS = 2_000
TRUNCATION_ROUTE_BUFFER_TOKENS = 512
MAX_COMPACTION_RESERVE_RATIO = 0.25
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

class ProjectedMessage(dict):
    """A message dict that carries its prompt-projection key.

    Upstream hangs the key on the message object as a symbol property
    (``TOOL_RESULT_PROJECTION_KEY``), which object spread copies and ``JSON.stringify`` skips.
    The attribute survives :func:`spread_message` and never reaches ``json.dumps``.
    """

    __slots__ = ("projection_key",)


def spread_message(message: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """``{...message, ...updates}``: also carries the projection key, like a symbol spread."""

    copied = {**message, **updates}
    key = getattr(message, "projection_key", None)
    if key is None:
        return copied
    projected = ProjectedMessage(copied)
    projected.projection_key = key
    return projected


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
    """``PreemptiveCompactionDecision``: the diagnostic maximum, plus the independently selected
    outgoing checkpoint's budget (``compaction_replay``) when a provider checkpoint replaced the
    covered history."""

    route: str
    should_compact: bool
    estimated_prompt_tokens: int
    pressure_source: str
    prompt_budget_before_reserve: int
    overflow_tokens: int
    tool_result_reducible_chars: int
    effective_reserve_tokens: int
    compaction_replay: PreemptiveCompactionDecision | None = None


@dataclass(frozen=True)
class CompactionReplayPressureContext:
    """``CompactionReplayPressureContext``: the model and identity a provider checkpoint is
    fenced to; ``enabled`` is the Anthropic server-compaction switch."""

    model: ReplayModel
    session_id: str | None = None
    auth_profile_id: str | None = None
    enabled: bool | None = None


@dataclass(frozen=True)
class LlmBoundaryTokenPressure:
    """Token pressure reported by the rendered provider-boundary prompt when available."""

    estimated_prompt_tokens: int | float
    source: str
    rendered_chars: int | float | None = None


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


def _js_concat_text(value: Any) -> str:
    """A string operand of ``prefix + value + suffix`` (``undefined`` and ``null`` print)."""

    if value is None:
        return "undefined"
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        from memory_core.compaction_replay import _js_number_to_string  # noqa: PLC0415

        return _js_number_to_string(value)
    return "[object Object]" if isinstance(value, dict) else ",".join(
        "" if item is None else _js_concat_text(item) for item in value
    )


def estimate_message_token_pressure(message: dict[str, Any]) -> int:
    if message.get("excludeFromContext") is True:
        return 0
    tokens = MESSAGE_BOUNDARY_OVERHEAD_TOKENS
    if _is_tool_result_message(message):
        tokens += estimate_tool_result_content_token_pressure(message.get("content"))
        tokens += estimate_identifier_token_pressure(
            message.get("toolName", message.get("tool_name"))
        )
        return tokens
    role = message.get("role")
    if role == "bashExecution":
        tokens += estimate_string_token_pressure(bash_execution_to_text(message))
        return tokens
    if role == "branchSummary":
        tokens += estimate_string_token_pressure(
            BRANCH_SUMMARY_PREFIX + _js_concat_text(message.get("summary")) + BRANCH_SUMMARY_SUFFIX
        )
        return tokens
    if role == "compactionSummary":
        tokens += estimate_string_token_pressure(
            COMPACTION_SUMMARY_PREFIX
            + _js_concat_text(message.get("summary"))
            + COMPACTION_SUMMARY_SUFFIX
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


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _js_ceil(value: int | float) -> int | float:
    """``Math.ceil``: infinities and ``NaN`` pass through."""

    return value if isinstance(value, float) and not math.isfinite(value) else math.ceil(value)


def estimate_rendered_prompt_tokens(*, system_prompt: str | None = None, prompt: str) -> int:
    """``estimateRenderedPromptTokens``: system prompt and prompt, no safety margin."""

    system_tokens = (
        MESSAGE_BOUNDARY_OVERHEAD_TOKENS + estimate_string_token_pressure(system_prompt)
        if isinstance(system_prompt, str) and js_trim(system_prompt)
        else 0
    )
    return (
        system_tokens + MESSAGE_BOUNDARY_OVERHEAD_TOKENS + estimate_string_token_pressure(prompt)
    )


def estimate_pre_prompt_tokens(
    *, messages: list[dict[str, Any]], system_prompt: str | None = None, prompt: str
) -> int:
    """The local transcript estimate with the safety margin (no replay, no measured usage)."""

    history_tokens = sum(estimate_message_token_pressure(message) for message in messages)
    rendered = estimate_rendered_prompt_tokens(system_prompt=system_prompt, prompt=prompt)
    return max(0, math.ceil((history_tokens + rendered) * SAFETY_MARGIN))


def estimate_tool_schema_tokens(tools: list[dict[str, Any]] | None) -> int:
    """``estimateToolSchemaTokens``: name, description and parameters of each definition."""

    if not tools:
        return 0
    return estimate_json_payload_token_pressure(
        [
            {key: tool[key] for key in ("name", "description", "parameters") if key in tool}
            for tool in tools
        ]
    )


def estimate_tool_schema_token_pressure(tools: list[dict[str, Any]] | None) -> int:
    """``estimateToolSchemaTokenPressure``: tool definition tokens with the safety margin."""

    return math.ceil(estimate_tool_schema_tokens(tools) * SAFETY_MARGIN)


def estimate_rendered_llm_boundary_token_pressure(
    *, system_prompt: str | None = None, prompt: str
) -> int:
    """``estimateRenderedLlmBoundaryTokenPressure``: only the rendered prompt/system portion."""

    rendered = estimate_rendered_prompt_tokens(system_prompt=system_prompt, prompt=prompt)
    return max(0, math.ceil(rendered * SAFETY_MARGIN))


_MISSING: Any = object()


def _usage_number(usage: dict[str, Any], key: str) -> float:
    """``usage[key]`` as JavaScript arithmetic reads it (missing is ``NaN``, ``null`` is 0)."""

    value = usage.get(key, _MISSING)
    if value is _MISSING:
        return math.nan
    if value is None:
        return 0
    return value if _is_number(value) else math.nan


def calculate_context_tokens(usage: dict[str, Any]) -> int | float:
    """``calculateContextTokens``: the provider total, else the four usage counters."""

    context_usage = usage.get("contextUsage")
    if isinstance(context_usage, dict) and context_usage.get("state") == "available":
        total = context_usage.get("totalTokens")
        return total if _is_number(total) else math.nan
    total = usage.get("totalTokens")
    if _is_number(total) and total != 0 and total == total:
        return total
    return (
        _usage_number(usage, "input")
        + _usage_number(usage, "output")
        + _usage_number(usage, "cacheRead")
        + _usage_number(usage, "cacheWrite")
    )


def _is_provider_context_usage_barrier(message: dict[str, Any]) -> bool:
    usage = message.get("usage")
    if message.get("role") != "assistant" or not usage or not isinstance(usage, dict):
        return False
    # Zero unavailable and legacy CLI records describe a newer context without provider
    # provenance; scanning past them can undercount the active transcript.
    context_usage = usage.get("contextUsage")
    return (message.get("api") == "cli" and "contextUsage" not in usage) or (
        isinstance(context_usage, dict)
        and context_usage.get("state") == "unavailable"
        and calculate_context_tokens(usage) == 0
    )


def _resolve_provider_context_boundary(
    messages: list[dict[str, Any]],
) -> tuple[int, int] | None:
    """``resolveProviderContextBoundary``: ``(index, total tokens)`` of the newest measured turn."""

    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message and _is_provider_context_usage_barrier(message):
            return None
        usage = message.get("usage") if message and message.get("role") == "assistant" else None
        context_usage = usage.get("contextUsage") if isinstance(usage, dict) else None
        if (
            isinstance(context_usage, dict)
            and context_usage.get("state") == "available"
            and _is_number(context_usage.get("totalTokens"))
            and math.isfinite(context_usage["totalTokens"])
            and context_usage["totalTokens"] > 0
        ):
            return index, math.ceil(context_usage["totalTokens"])
    return None


@dataclass(frozen=True)
class _TranscriptBoundaryPressure:
    estimated_prompt_tokens: int
    source: str
    messages: list[dict[str, Any]]
    has_compaction_replay: bool


def _estimate_transcript_boundary_token_pressure(
    *,
    messages: list[dict[str, Any]],
    system_prompt: str | None,
    prompt: str,
    replay: CompactionReplayPressureContext | None = None,
    tool_schema_tokens: int | float | None = None,
) -> _TranscriptBoundaryPressure:
    """``estimateTranscriptBoundaryTokenPressure``.

    With a ``replay`` context the selected provider checkpoint replaces the covered history
    (:func:`resolve_compaction_replay_pressure`): measured provider usage bound to the replay
    prefix, else the prefix estimate plus the later messages.
    """

    resolved = (
        resolve_compaction_replay_pressure(
            messages,
            replay.model,
            ReplayIdentity(replay.session_id, replay.auth_profile_id, replay.enabled),
            default_replay_pressure_estimator(),
            system_prompt,
        )
        if replay is not None
        else None
    )
    effective = resolved["messages"] if resolved is not None else messages
    boundary = _resolve_provider_context_boundary(effective)
    measured = resolved.get("measuredTokens") if resolved is not None else None
    if measured is None and boundary is not None:
        measured = boundary[1]
    # The provider total owns transcript items through its assistant record. It has no
    # system-prompt provenance, so the current rendered prompt stays local too.
    for_pressure = effective[boundary[0] + 1 :] if boundary is not None else effective
    local = estimate_rendered_prompt_tokens(system_prompt=system_prompt, prompt=prompt)
    if boundary is None and resolved is not None:
        local += resolved["prefixTokens"] - resolved.get("measuredTokens", 0)
    for message in for_pressure:
        local += estimate_message_token_pressure(message)
    schema = tool_schema_tokens if tool_schema_tokens is not None else 0
    schema = schema if schema != schema else max(0, schema)
    return _TranscriptBoundaryPressure(
        estimated_prompt_tokens=(measured or 0)
        + _js_ceil(local * SAFETY_MARGIN)
        # A saved replay prefix does not bind today's tool definitions. Reserve their current size
        # even when covered conversation usage is measured.
        + (0 if boundary is not None and resolved is None else schema),
        source=(
            "provider_context_usage"
            if measured is not None
            else "provider_compaction_estimate"
            if resolved is not None
            else "transcript_estimate"
        ),
        messages=effective,
        has_compaction_replay=resolved is not None,
    )


def estimate_llm_boundary_token_pressure(
    *,
    messages: list[dict[str, Any]],
    system_prompt: str | None = None,
    prompt: str,
    replay: CompactionReplayPressureContext | None = None,
    tool_schema_tokens: int | float | None = None,
) -> int:
    """``estimateLlmBoundaryTokenPressure``: the outgoing prompt estimate for one request."""

    return _estimate_transcript_boundary_token_pressure(
        messages=messages,
        system_prompt=system_prompt,
        prompt=prompt,
        replay=replay,
        tool_schema_tokens=tool_schema_tokens,
    ).estimated_prompt_tokens


def _normalize_llm_boundary_token_pressure(
    pressure: LlmBoundaryTokenPressure | None,
) -> LlmBoundaryTokenPressure | None:
    if (
        pressure is None
        or not _is_number(pressure.estimated_prompt_tokens)
        or not math.isfinite(pressure.estimated_prompt_tokens)
    ):
        return None
    rendered = pressure.rendered_chars
    return LlmBoundaryTokenPressure(
        estimated_prompt_tokens=max(0, math.ceil(pressure.estimated_prompt_tokens)),
        source=js_trim(pressure.source) or "rendered_llm_boundary",
        rendered_chars=(
            max(0, math.ceil(rendered))
            if _is_number(rendered) and math.isfinite(rendered)
            else None
        ),
    )


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
    return spread_message(message, {"content": new_content})


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
    nested = details.get("spill") if isinstance(details.get("spill"), dict) else None
    # web_fetch owns the nested contract; exec tools still own the flat spill fields.
    path = (nested or {}).get("path")
    if path is None:
        path = details.get("fullOutputPath")
    if not isinstance(path, str) or not path:
        return None
    chars = (nested or {}).get("chars")
    if chars is None:
        chars = details.get("spilledChars")
    return {
        "path": path,
        "truncated": (nested or {}).get("truncated") is True or details.get("spillTruncated") is True,
        "chars": (
            max(0, math.floor(chars))
            if isinstance(chars, int | float) and not isinstance(chars, bool) and math.isfinite(chars)
            else None
        ),
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
    # Preserve only paths already visible in the original footer.
    if not _tool_result_text_contains_full_output_footer(message, spill["path"]):
        return None
    # Avoid pointing recovery at already-deleted spill files.
    if not os.path.exists(spill["path"]):
        return None
    path = spill["path"]
    truncated = spill["truncated"]
    kind = "partial" if truncated else "full"
    spilled_chars = spill["chars"]
    count = (
        f" ({'capped content' if spilled_chars is None else f'first {spilled_chars} chars'})"
        if truncated
        else ""
    )
    output = f"{kind} output"
    return _AggregateElisionMarkers(
        full=(
            f"[tool result elided: {output} preserved at {path}{count}; "
            "read it if the output is needed]"
        ),
        compact=f"[partial: {path}]" if truncated else f"[read {path}]",
        truncation_suffix=lambda truncated_chars: (
            f"[... {max(1, math.floor(truncated_chars))} chars truncated; {output} at {path}]"
        ),
    )


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
        # Keep recoverable pointers; their ~130 chars are negligible against the 64k+ floor.
        remaining_text_budget = max(
            remaining_text_budget, estimate_string_chars(spill_markers.compact)
        )
    new_content: list[Any] = []
    for block in content:
        if not _is_tool_result_text_block(block):
            new_content.append(block)
            continue
        replacement_text = next(
            (
                marker
                for marker in (
                    (spill_markers.full, spill_markers.compact) if spill_markers is not None else ()
                )
                if isinstance(marker, str) and estimate_string_chars(marker) <= remaining_text_budget
            ),
            None,
        )
        if replacement_text is None:
            replacement_text = slice_tool_result_text_to_budget(
                AGGREGATE_ELISION_MARKER, remaining_text_budget
            )
        remaining_text_budget = max(
            0, remaining_text_budget - estimate_string_chars(replacement_text)
        )
        next_block = {**block, "text": replacement_text}
        if isinstance(block.get("content"), str):
            next_block["content"] = replacement_text
        new_content.append(next_block)
    return spread_message(message, {"content": new_content})


def _get_trailing_tool_result_entry_ids(branch: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for entry in reversed(branch):
        message = entry.get("message")
        # Only an assistant response consumes tool results. Runtime context and queued
        # steering must not make the pending batch eligible for elision.
        if entry.get("type") == "message" and isinstance(message, dict):
            if message.get("role") == "assistant":
                break
            if message.get("role") == "toolResult" and isinstance(entry.get("id"), str):
                ids.add(entry["id"])
    return ids


def _build_oversized_tool_result_replacements(
    *,
    branch: list[tuple[dict[str, Any], int | float]],
    max_chars: int,
    min_keep_chars: int = MIN_KEEP_CHARS,
    protected_entry_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    replacements: list[dict[str, Any]] = []
    for entry, text_length in branch:
        message = entry.get("message")
        if (
            entry.get("type") != "message"
            or not isinstance(message, dict)
            or message.get("role") != "toolResult"
            or text_length <= max_chars
        ):
            continue
        spill_markers = _resolve_aggregate_elision_markers(message)
        suffix_factory = spill_markers.truncation_suffix if spill_markers is not None else None
        entry_max_chars = max(
            max_chars,
            estimate_string_chars(suffix_factory(1)) if suffix_factory is not None else 0,
        )
        replacement_message = truncate_tool_result_message(
            message,
            entry_max_chars,
            suffix=suffix_factory,
            min_keep_chars=(
                max(min_keep_chars, MIN_KEEP_CHARS)
                if protected_entry_ids is not None and entry.get("id") in protected_entry_ids
                else min_keep_chars
            ),
        )
        replacements.append(
            {
                "entry_id": entry.get("id"),
                "message": replacement_message,
                "text_length": (
                    text_length
                    if replacement_message is message
                    else get_tool_result_text_length(replacement_message)
                ),
            }
        )
    return replacements


def _build_aggregate_tool_result_replacements(
    *,
    branch: list[tuple[dict[str, Any], int | float]],
    spill_source_branch: list[dict[str, Any]] | None = None,
    aggregate_budget_chars: int,
    min_keep_chars: int = MIN_KEEP_CHARS,
    protected_entry_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    candidates: list[dict[str, Any]] = []
    for index, (entry, text_length) in enumerate(branch):
        message = entry.get("message")
        if (
            entry.get("type") != "message"
            or not isinstance(message, dict)
            or message.get("role") != "toolResult"
            or not text_length > 0
        ):
            continue
        spill_source_message = message
        if spill_source_branch is not None and index < len(spill_source_branch):
            source_message = spill_source_branch[index].get("message")
            if isinstance(source_message, dict):
                spill_source_message = source_message
        candidates.append(
            {
                "entry_id": entry.get("id"),
                "message": message,
                "spill_source_message": spill_source_message,
                "text_length": text_length,
                "aggregate_eligible": entry.get("aggregateEligible") is not False,
                "protected": (
                    protected_entry_ids is not None and entry.get("id") in protected_entry_ids
                ),
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
    min_truncated_text_chars = min_keep_chars + estimate_string_chars(suffix_factory(1))

    total_chars = sum(candidate["text_length"] for candidate in candidates)
    if total_chars <= aggregate_budget_chars:
        return [], False

    remaining_reduction = total_chars - aggregate_budget_chars
    replacements: dict[Any, dict[str, Any]] = {}
    # Frozen prompt bytes are immutable. Recover only from unsent tail results; allow budget
    # overflow when frozen history alone exceeds the aggregate cap.
    recovery_candidates = [
        candidate
        for candidate in candidates
        if candidate["aggregate_eligible"] and not candidate["protected"]
    ]

    # Trim all older entries before clearing any, so fresh output and spill pointers stay
    # recoverable.
    for clear in (False, True):
        for candidate in recovery_candidates:
            if remaining_reduction <= 0:
                break
            existing = replacements.get(candidate["entry_id"])
            base_text_length = (
                existing["text_length"] if existing is not None else candidate["text_length"]
            )
            if not clear and base_text_length <= min_truncated_text_chars:
                continue
            spill_markers = _resolve_aggregate_elision_markers(candidate["spill_source_message"])
            if clear:
                # Cleared fresh results keep a visible elision notice on projection paths;
                # an empty tool result reads as failure and loses rerun guidance.
                notice_floor = (
                    estimate_string_chars(
                        spill_markers.compact if spill_markers is not None else AGGREGATE_ELISION_MARKER
                    )
                    if protected_entry_ids is not None
                    else 0
                )
                message = _clear_tool_result_text(
                    candidate["message"],
                    max(notice_floor, base_text_length - remaining_reduction),
                    spill_markers,
                )
            else:
                suffix = (
                    spill_markers.truncation_suffix if spill_markers is not None else suffix_factory
                )
                target_chars = max(
                    min_truncated_text_chars,
                    base_text_length - remaining_reduction,
                    estimate_string_chars(suffix(1)),
                )
                message = truncate_tool_result_message(
                    candidate["message"],
                    target_chars,
                    min_keep_chars=min_keep_chars,
                    suffix=suffix,
                )
            text_length = (
                candidate["text_length"]
                if message is candidate["message"]
                else get_tool_result_text_length(message)
            )
            actual_reduction = max(0, base_text_length - text_length)
            if actual_reduction <= 0 and (not clear or spill_markers is None):
                continue
            replacements[candidate["entry_id"]] = {
                "entry_id": candidate["entry_id"],
                "message": message,
                "text_length": text_length,
            }
            remaining_reduction -= actual_reduction

    return list(replacements.values()), True


def _apply_tool_result_replacements_to_branch(
    branch: list[tuple[dict[str, Any], int | float]], replacements: list[dict[str, Any]]
) -> tuple[list[tuple[dict[str, Any], int | float]], int | float]:
    if not replacements:
        return branch, 0
    replacements_by_id = {replacement["entry_id"]: replacement for replacement in replacements}
    reduced_chars: int | float = 0
    next_branch: list[tuple[dict[str, Any], int | float]] = []
    for entry, text_length in branch:
        replacement = replacements_by_id.get(entry.get("id"))
        if replacement is None or entry.get("type") != "message" or not entry.get("message"):
            next_branch.append((entry, text_length))
            continue
        reduced_chars += max(0, text_length - replacement["text_length"])
        next_branch.append(
            ({**entry, "message": replacement["message"]}, replacement["text_length"])
        )
    return next_branch, reduced_chars


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
    # Measurements belong to this synchronous plan; replacement producers supply the next one.
    measured_branch: list[tuple[dict[str, Any], int | float]] = [
        (
            entry,
            get_tool_result_text_length(entry["message"])
            if entry.get("type") == "message" and isinstance(entry.get("message"), dict)
            else 0,
        )
        for entry in branch
    ]
    oversized_replacements = _build_oversized_tool_result_replacements(
        branch=measured_branch,
        max_chars=max_chars,
        min_keep_chars=min_keep_chars,
        protected_entry_ids=protected_entry_ids,
    )
    oversized_trimmed_branch, oversized_reducible_chars = (
        _apply_tool_result_replacements_to_branch(measured_branch, oversized_replacements)
    )
    aggregate_replacements, aggregate_pressure_exceeded = (
        _build_aggregate_tool_result_replacements(
            branch=oversized_trimmed_branch,
            spill_source_branch=branch,
            aggregate_budget_chars=aggregate_budget_chars,
            min_keep_chars=min_keep_chars,
            protected_entry_ids=protected_entry_ids,
        )
    )
    _, aggregate_reducible_chars = _apply_tool_result_replacements_to_branch(
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
    projection_state: Any = None,
) -> SessionToolResultTruncationResult:
    """The session-file variant of ``truncateOversizedToolResultsInSessionManager``.

    ``projection_state`` (a :class:`~memory_core.tool_result_projection.ToolResultPromptProjectionState`)
    enables the recovery projection: frozen replacements replay into the plan and are rewritten
    into the transcript, and the state is reconciled against the rewritten branch.
    """

    path = Path(session_file)
    try:
        entries = _read_jsonl_entries(path)
    except OSError as exc:
        return SessionToolResultTruncationResult(False, 0, str(exc))
    branch = _active_branch(entries)
    # Only the entries inside the compaction window take part (iterateSessionContextEntries).
    from memory_core import tool_result_projection as projection

    context_entries = projection.session_context_entries(branch)
    if not context_entries:
        return SessionToolResultTruncationResult(False, 0, "empty session")

    max_chars, aggregate_budget_chars = projection.resolve_tool_result_budgets(
        context_window_tokens=context_window_tokens,
        max_chars_override=max_chars_override,
        aggregate_max_chars_override=aggregate_max_chars_override,
    )
    projected_branch = context_entries
    if projection_state is not None:
        projected_branch, _keys = projection.project_tool_result_branch(
            branch=context_entries, projection_state=projection_state, frozen_only=True
        )
    plan = build_tool_result_replacement_plan(
        branch=projected_branch,
        max_chars=max_chars,
        aggregate_budget_chars=aggregate_budget_chars,
        min_keep_chars=RECOVERY_MIN_KEEP_CHARS,
        protect_trailing_tool_results=protect_trailing_tool_results,
    )
    # buildRecoveryToolResultReplacementPlan: a replacement exists only where the final message
    # differs from the stored one (identity, then JSON equality).
    replacements_by_entry_id: dict[str, dict[str, Any]] = {}
    for entry, projected_entry in zip(context_entries, projected_branch, strict=True):
        message = entry.get("message")
        entry_id = entry.get("id")
        if entry.get("type") != "message" or not message or not isinstance(entry_id, str):
            continue
        final_message = plan.replacement_messages_by_entry_id.get(
            entry_id, projected_entry.get("message")
        )
        if not final_message or final_message is message:
            continue
        if js_json_stringify(message) == js_json_stringify(final_message):
            continue
        replacements_by_entry_id[entry_id] = final_message
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
    rewritten_ids: dict[str, str] = {}
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
            # The projection key is an in-memory symbol upstream and never reaches the transcript.
            next_entry["message"] = dict(replacement)
            truncated_count += 1
        elif isinstance(message, dict):
            next_entry["message"] = message
        kept_id = entry.get("firstKeptEntryId")
        if isinstance(kept_id, str) and kept_id in rewritten_ids:
            # A re-appended compaction keeps pointing at the rewritten copy of its first kept entry.
            next_entry["firstKeptEntryId"] = rewritten_ids[kept_id]
        rewritten_ids[old_id] = new_id
        current_parent_id = new_id
        appended.append(next_entry)
    _append_jsonl_entries(path, appended)

    after_branch = _active_branch([*entries, *appended])
    if projection_state is not None:
        # Recovery changed canonical bytes; keeping their former source would undo the next TTL edit.
        projection.reconcile_tool_result_prompt_projection_state(
            projection.session_context_tool_result_messages(after_branch), projection_state
        )
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
    tool_schema_tokens: int | float | None = None,
    llm_boundary_token_pressure: LlmBoundaryTokenPressure | None = None,
    replay: CompactionReplayPressureContext | None = None,
) -> PreemptiveCompactionDecision:
    """``shouldPreemptivelyCompactBeforePrompt``: route a run before it submits the prompt.

    Rendered LLM boundary pressure wins over local transcript estimates when supplied, except
    where a provider checkpoint (``replay``) owns its covered prefix: then the transcript estimate
    over the checkpoint-projected window is the outgoing decision (``compaction_replay``), and the
    returned top-level decision is the diagnostic maximum with the unwindowed history.
    :class:`~memory_core.compaction_replay.CompactionReplayRefreshRequiredError` propagates for a
    Responses checkpoint that needs ``/compact``.
    """

    boundary = _normalize_llm_boundary_token_pressure(llm_boundary_token_pressure)
    transcript = (
        None
        if boundary is not None and replay is None
        else _estimate_transcript_boundary_token_pressure(
            messages=messages,
            system_prompt=system_prompt,
            prompt=prompt,
            replay=replay,
            tool_schema_tokens=tool_schema_tokens,
        )
    )
    # The selected provider window owns its covered prefix, including when a context engine
    # supplied an estimate of the raw transcript instead.
    boundary_pressure = (
        None if transcript is not None and transcript.has_compaction_replay else boundary
    )
    if boundary_pressure is not None:
        estimated: int | float = boundary_pressure.estimated_prompt_tokens
        source = boundary_pressure.source
    elif transcript is not None:
        estimated, source = transcript.estimated_prompt_tokens, transcript.source
    else:
        estimated, source = 0, "transcript_estimate"
    outgoing = _resolve_compaction_pressure_decision(
        transcript.messages if transcript is not None else messages,
        estimated,
        source,
        context_token_budget=context_token_budget,
        reserve_tokens=reserve_tokens,
        tool_result_max_chars=tool_result_max_chars,
    )
    diagnostic = outgoing
    if unwindowed_messages is not None and unwindowed_messages is not messages:
        unwindowed = _estimate_transcript_boundary_token_pressure(
            messages=unwindowed_messages,
            system_prompt=system_prompt,
            prompt=prompt,
            tool_schema_tokens=tool_schema_tokens,
        )
        # Unwindowed history is diagnostic: neither its checkpoints nor its larger raw estimate may
        # authorize recovery of a different outgoing window.
        if unwindowed.estimated_prompt_tokens > outgoing.estimated_prompt_tokens:
            diagnostic = _resolve_compaction_pressure_decision(
                unwindowed.messages,
                unwindowed.estimated_prompt_tokens,
                f"unwindowed_{unwindowed.source}",
                context_token_budget=context_token_budget,
                reserve_tokens=reserve_tokens,
                tool_result_max_chars=tool_result_max_chars,
            )
    if transcript is not None and transcript.has_compaction_replay:
        return dataclasses.replace(diagnostic, compaction_replay=outgoing)
    return diagnostic


def resolve_effective_compaction_reserve_tokens(
    context_token_budget: int | float, reserve_tokens: int | float
) -> int:
    """``resolveEffectiveCompactionReserveTokens``: headroom capped at a quarter of the window."""

    budget = max(1, math.floor(context_token_budget))
    return min(
        max(0, math.floor(reserve_tokens)),
        math.floor(budget * MAX_COMPACTION_RESERVE_RATIO),
    )


def _resolve_compaction_pressure_decision(
    messages: list[dict[str, Any]],
    estimated_prompt_tokens: int | float,
    source: str,
    *,
    context_token_budget: int,
    reserve_tokens: int,
    tool_result_max_chars: int | None,
) -> PreemptiveCompactionDecision:
    """``resolveCompactionPressureDecision``."""

    context_budget = max(1, math.floor(context_token_budget))
    effective_reserve = resolve_effective_compaction_reserve_tokens(context_budget, reserve_tokens)
    prompt_budget_before_reserve = max(1, context_budget - effective_reserve)
    overflow_tokens = max(0, estimated_prompt_tokens - prompt_budget_before_reserve)
    potential = estimate_tool_result_reduction_potential(
        messages=messages,
        context_window_tokens=context_token_budget,
        max_chars_override=tool_result_max_chars,
    )
    try:
        overflow_chars: int | float = float(overflow_tokens) * ESTIMATED_CHARS_PER_TOKEN
    except OverflowError:
        overflow_chars = math.inf
    truncation_buffer_chars = TRUNCATION_ROUTE_BUFFER_TOKENS * ESTIMATED_CHARS_PER_TOKEN
    truncate_only_threshold_chars = max(
        overflow_chars + truncation_buffer_chars,
        _js_ceil(overflow_chars * 1.5),
    )
    reducible = potential.max_reducible_chars

    route = "fits"
    if overflow_tokens > 0:
        # Choose truncate-only only when available reduction comfortably exceeds the overflow.
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
        pressure_source=source,
        prompt_budget_before_reserve=prompt_budget_before_reserve,
        overflow_tokens=overflow_tokens,
        tool_result_reducible_chars=reducible,
        effective_reserve_tokens=effective_reserve,
    )


PREEMPTIVE_OVERFLOW_ERROR_TEXT = "Context overflow: prompt too large for the model (precheck)."


def _js_text(value: Any) -> str:
    """Template-literal text of a log field (``undefined`` prints as ``undefined``)."""

    return "undefined" if value is None else _js_concat_text(value)


def format_pre_prompt_precheck_log(
    *,
    result: PreemptiveCompactionDecision,
    provider: str,
    model_id: str,
    message_count: int,
    context_token_budget: int | float,
    reserve_tokens: int | float,
    session_key: str | None = None,
    session_id: str | None = None,
    unwindowed_message_count: int | None = None,
    session_file: str | None = None,
) -> str:
    """``formatPrePromptPrecheckLog``: the compact operator log line for one budget check."""

    unwindowed = message_count if unwindowed_message_count is None else unwindowed_message_count
    return (
        f"[context-overflow-precheck] pre-prompt check "
        f"sessionKey={_js_text(session_key if session_key is not None else session_id if session_id is not None else 'unknown')} "
        f"provider={provider}/{model_id} "
        f"route={result.route} "
        f"estimatedPromptTokens={_js_text(result.estimated_prompt_tokens)} "
        f"pressureSource={result.pressure_source if result.pressure_source is not None else 'unknown'} "
        f"promptBudgetBeforeReserve={result.prompt_budget_before_reserve} "
        f"overflowTokens={_js_text(result.overflow_tokens)} "
        f"toolResultReducibleChars={result.tool_result_reducible_chars} "
        f"reserveTokens={_js_text(reserve_tokens)} "
        f"effectiveReserveTokens={result.effective_reserve_tokens} "
        f"contextTokenBudget={_js_text(context_token_budget)} "
        f"messages={message_count} "
        f"unwindowedMessages={unwindowed} "
        f"sessionFile={_js_text(session_file)}"
    )


def build_pre_prompt_context_budget_status(
    *,
    result: PreemptiveCompactionDecision,
    provider: str,
    model_id: str,
    message_count: int,
    context_token_budget: int | float,
    reserve_tokens: int | float,
    unwindowed_message_count: int | None = None,
    session_id: str | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """``buildPrePromptContextBudgetStatus``: the persisted session context-budget record."""

    unwindowed = message_count if unwindowed_message_count is None else unwindowed_message_count
    status: dict[str, Any] = {
        "schemaVersion": 1,
        "source": "pre-prompt-estimate",
        "updatedAt": now if now is not None else int(time.time() * 1000),
        "provider": provider,
        "model": model_id,
        "route": result.route,
        "shouldCompact": result.should_compact,
        "estimatedPromptTokens": result.estimated_prompt_tokens,
        "contextTokenBudget": max(1, math.floor(context_token_budget)),
        "promptBudgetBeforeReserve": result.prompt_budget_before_reserve,
        "reserveTokens": max(0, math.floor(reserve_tokens)),
        "effectiveReserveTokens": result.effective_reserve_tokens,
        "remainingPromptBudgetTokens": max(
            0, result.prompt_budget_before_reserve - result.estimated_prompt_tokens
        ),
        "overflowTokens": result.overflow_tokens,
        "toolResultReducibleChars": result.tool_result_reducible_chars,
        "messageCount": max(0, math.floor(message_count)),
        "unwindowedMessageCount": max(0, math.floor(unwindowed)),
    }
    if session_id:
        status["sessionId"] = session_id
    return status
