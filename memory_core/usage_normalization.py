"""Token usage normalization (src/agents/usage.ts, v2026.9.6).

Ported: ``normalizeUsage`` (provider aliases, nested ``*_details`` objects, cache subtraction
from provider input totals, the context usage snapshot, cost totals) and ``hasNonzeroUsage``.
The result is a plain dict that holds only the keys upstream sets to a value, so a key upstream
leaves ``undefined`` is absent here.

JavaScript distinctions kept on purpose: ``??`` skips ``null`` and ``undefined`` alike, while a
``!== undefined`` check treats a JSON ``null`` as present; ``Number.isFinite`` rejects strings and
booleans (no coercion); an optional chain over a non-object (string, number, array) reads
``undefined``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

MAX_SAFE_INTEGER = 9_007_199_254_740_991
USAGE_COST_COMPONENTS = ("input", "output", "cacheRead", "cacheWrite")

_MISSING: Any = object()


def normalize_usage(raw: Any) -> dict[str, Any] | None:
    """``normalizeUsage(raw)``: ``None`` where upstream returns ``undefined``."""

    if not _js_truthy_object(raw):
        return None
    usage = raw if isinstance(raw, Mapping) else {}

    cache_read = _token_count(
        _coalesce(
            _get(usage, "cacheRead"),
            _get(usage, "cache_read"),
            _get(usage, "cache_read_input_tokens"),
            _get(usage, "cached_input_tokens"),
            _get(usage, "cached"),
            _get(usage, "cached_tokens"),
            _nested(usage, "input_tokens_details", "cached_tokens"),
            _nested(usage, "prompt_tokens_details", "cached_tokens"),
        )
    )
    cache_write = _token_count(
        _coalesce(
            _get(usage, "cacheWrite"),
            _get(usage, "cache_write"),
            _get(usage, "cache_creation_input_tokens"),
            _get(usage, "cache_write_input_tokens"),
            _nested(usage, "input_tokens_details", "cache_write_tokens"),
            _nested(usage, "prompt_tokens_details", "cache_write_tokens"),
            _nested(usage, "prompt_tokens_details", "cache_creation_input_tokens"),
        )
    )
    cache_write_1h = _token_count(_get(usage, "cacheWrite1h"))

    direct_input = _finite(_get(usage, "input"))
    raw_input_value = _coalesce(
        _get(usage, "input"),
        _get(usage, "inputTokens"),
        _get(usage, "input_tokens"),
        _get(usage, "promptTokens"),
        _get(usage, "prompt_tokens"),
        _get(usage, "prompt_n"),
        _nested(usage, "timings", "prompt_n"),
    )

    cli_cache_read_included = _defined(_get(usage, "cached_input_tokens")) or _defined(
        _get(usage, "cached")
    )
    openai_cache_read_included = (
        _defined(_get(usage, "cached_tokens"))
        or _defined(_nested(usage, "input_tokens_details", "cached_tokens"))
        or _defined(_nested(usage, "prompt_tokens_details", "cached_tokens"))
    )
    cache_write_included = (
        _defined(_get(usage, "cache_write_input_tokens"))
        or _defined(_nested(usage, "input_tokens_details", "cache_write_tokens"))
        or _defined(_nested(usage, "prompt_tokens_details", "cache_write_tokens"))
        or _defined(_nested(usage, "prompt_tokens_details", "cache_creation_input_tokens"))
    )

    # Provider prompt/input aliases include cached tokens in the reported total; normalize to
    # uncached input tokens so prompt-token math does not double-count cache reads or writes.
    raw_input = _finite(raw_input_value)
    subtract_cache_read = openai_cache_read_included or (
        direct_input is None and cli_cache_read_included
    )
    if raw_input is not None:
        normalized_input: float | None = (
            raw_input
            - ((cache_read or 0) if subtract_cache_read else 0)
            - ((cache_write or 0) if direct_input is None and cache_write_included else 0)
        )
    else:
        normalized_input = None
    input_tokens = _token_count(normalized_input)
    output = _token_count(
        _coalesce(
            _get(usage, "output"),
            _get(usage, "outputTokens"),
            _get(usage, "output_tokens"),
            _get(usage, "completionTokens"),
            _get(usage, "completion_tokens"),
            _get(usage, "predicted_n"),
            _nested(usage, "timings", "predicted_n"),
        )
    )

    raw_context = _get(usage, "contextUsage")
    context_state = raw_context.get("state") if isinstance(raw_context, Mapping) else None
    context_prompt = (
        _token_count(raw_context.get("promptTokens")) if context_state == "available" else None
    )
    context_total = (
        _token_count(raw_context.get("totalTokens")) if context_state == "available" else None
    )
    context_usage: dict[str, Any] | None
    if context_state == "unavailable":
        context_usage = {"state": "unavailable"}
    elif (
        context_prompt is not None and context_total is not None and context_total >= context_prompt
    ):
        context_usage = {
            "state": "available",
            "promptTokens": context_prompt,
            "totalTokens": context_total,
        }
    else:
        context_usage = None

    reasoning_tokens = _token_count(
        _coalesce(
            _get(usage, "reasoningTokens"),
            _get(usage, "reasoning_tokens"),
            _nested(usage, "completion_tokens_details", "reasoning_tokens"),
            _nested(usage, "output_tokens_details", "reasoning_tokens"),
            _nested(usage, "output_tokens_details", "thinking_tokens"),
        )
    )
    total = _token_count(
        _coalesce(_get(usage, "total"), _get(usage, "totalTokens"), _get(usage, "total_tokens"))
    )

    raw_cost = _get(usage, "cost")
    cost_total = _finite(raw_cost.get("total")) if isinstance(raw_cost, Mapping) else None
    cost: dict[str, Any] | None = None
    if cost_total is not None and cost_total >= 0:
        cost = {"total": cost_total}
        if raw_cost.get("totalOrigin") == "provider-billed":
            cost["totalOrigin"] = "provider-billed"
        if cost_total == 0:
            # Component evidence distinguishes a recorded zero from an adapter default.
            for key in USAGE_COST_COMPONENTS:
                component = _finite(raw_cost.get(key))
                if component is not None and component != 0:
                    cost[key] = component

    if (
        input_tokens is None
        and output is None
        and cache_read is None
        and cache_write is None
        and context_usage is None
        and reasoning_tokens is None
        and total is None
        and cost is None
    ):
        return None

    normalized: dict[str, Any] = {}
    for key, value in (
        ("input", input_tokens),
        ("output", output),
        ("cacheRead", cache_read),
        ("cacheWrite", cache_write),
    ):
        if value is not None:
            normalized[key] = value
    if cache_write_1h is not None:
        normalized["cacheWrite1h"] = cache_write_1h
    if cost is not None:
        normalized["cost"] = cost
    if context_usage is not None:
        normalized["contextUsage"] = context_usage
    if reasoning_tokens is not None:
        normalized["reasoningTokens"] = reasoning_tokens
    if total is not None:
        normalized["total"] = total
    return normalized


def has_nonzero_usage(usage: Mapping[str, Any] | None) -> bool:
    """``hasNonzeroUsage``: any normalized usage bucket is positive, or the context is unavailable."""

    if not usage:
        return False
    context = usage.get("contextUsage")
    context = context if isinstance(context, Mapping) else {}
    available = context.get("state") == "available"
    buckets = [
        usage.get("input"),
        usage.get("output"),
        usage.get("cacheRead"),
        usage.get("cacheWrite"),
        context.get("promptTokens") if available else None,
        context.get("totalTokens") if available else None,
        usage.get("reasoningTokens"),
        usage.get("total"),
    ]
    return (
        any(_finite(value) is not None and value > 0 for value in buckets)
        or context.get("state") == "unavailable"
    )


def has_nonzero_normalized_usage(raw: Any) -> bool:
    """``hasNonzeroUsage(normalizeUsage(raw))``."""

    return has_nonzero_usage(normalize_usage(raw))


def _js_truthy_object(value: Any) -> bool:
    """``!raw`` is false: an object (any ``dict`` or ``list``) or a truthy primitive."""

    if isinstance(value, Mapping | list):
        return True
    if isinstance(value, bool) or value is None:
        return bool(value)
    if isinstance(value, int | float):
        return bool(value) and not (isinstance(value, float) and math.isnan(value))
    return bool(value)


def _get(mapping: Mapping[str, Any], key: str) -> Any:
    return mapping.get(key, _MISSING)


def _nested(mapping: Mapping[str, Any], key: str, inner: str) -> Any:
    """``mapping.key?.inner``: ``undefined`` unless ``key`` holds an object."""

    value = mapping.get(key)
    return value.get(inner, _MISSING) if isinstance(value, Mapping) else _MISSING


def _defined(value: Any) -> bool:
    return value is not _MISSING


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not _MISSING and value is not None:
            return value
    return _MISSING


def _finite(value: Any) -> float | int | None:
    """``asFiniteNumber``: numbers only (no booleans or numeric strings), finite."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value if math.isfinite(value) else None


def _token_count(value: Any) -> int | None:
    numeric = _finite(value)
    if numeric is None:
        return None
    if numeric <= 0:
        return 0
    return min(math.trunc(numeric), MAX_SAFE_INTEGER)
