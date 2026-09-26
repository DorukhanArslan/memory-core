"""Deep dreaming (scored promotion) policy defaults and config resolution.

Port of the deep-phase part of ``resolveMemoryDeepDreamingConfig``
(``src/memory-host-sdk/dreaming.ts:386-534`` at OpenClaw pin 4c42815348) and
its ``DEFAULT_MEMORY_DEEP_DREAMING_*`` constants (``dreaming.ts:14,38-44``).
The ``deepPolicy`` oracle operation compares :func:`resolve_deep_dreaming_policy`
with the real function for the empty and a fully configured plugin config.

Not ported: the cron expression, sources, recovery, storage, timezone and
verbose-logging fields (scheduler and runtime concerns, out of scope).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from memory_core.bootstrap._js import js_trim

# dreaming.ts:14. Dreaming is off unless a host enables it (sweeps are manual here).
DEFAULT_DEEP_DREAMING_ENABLED = False
# dreaming.ts:38-44.
DEFAULT_DEEP_DREAMING_LIMIT = 10
DEFAULT_PROMOTION_MIN_SCORE = 0.8
DEFAULT_PROMOTION_MIN_RECALL_COUNT = 3
DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES = 3
DEFAULT_RECENCY_HALF_LIFE_DAYS = 14
DEFAULT_DEEP_DREAMING_MAX_AGE_DAYS = 30
DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS = 160

# A key absent from the config (JavaScript ``undefined``), distinct from JSON null.
_UNDEFINED = object()


@dataclass(frozen=True)
class DeepDreamingPolicy:
    """Resolved deep-phase gates and limits (upstream ``MemoryDeepDreamingConfig`` subset)."""

    enabled: bool = DEFAULT_DEEP_DREAMING_ENABLED
    limit: int = DEFAULT_DEEP_DREAMING_LIMIT
    min_score: float = DEFAULT_PROMOTION_MIN_SCORE
    min_recall_count: int = DEFAULT_PROMOTION_MIN_RECALL_COUNT
    min_unique_queries: int = DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES
    max_age_days: int = DEFAULT_DEEP_DREAMING_MAX_AGE_DAYS
    recency_half_life_days: int = DEFAULT_RECENCY_HALF_LIFE_DAYS
    max_promoted_snippet_tokens: int = DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS

    def as_dict(self) -> dict[str, Any]:
        """Return the policy with upstream camelCase keys (the ``deepPolicy`` oracle shape)."""
        return {
            "minScore": self.min_score,
            "minRecallCount": self.min_recall_count,
            "minUniqueQueries": self.min_unique_queries,
            "maxAgeDays": self.max_age_days,
            "enabled": self.enabled,
            "limit": self.limit,
            "recencyHalfLifeDays": self.recency_half_life_days,
            "maxPromotedSnippetTokens": self.max_promoted_snippet_tokens,
        }


def resolve_deep_dreaming_policy(config: Mapping[str, Any] | None = None) -> DeepDreamingPolicy:
    """Resolve the deep dreaming policy from an OpenClaw-shaped config mapping.

    Accepts either a full config (``plugins.entries["memory-core"].config``)
    or the memory-core plugin config itself, like the oracle runner's
    ``resolveMemoryCorePluginConfig``. Reads ``dreaming.enabled`` and
    ``dreaming.phases.deep.{enabled, limit, minScore, minRecallCount,
    minUniqueQueries, maxAgeDays, recencyHalfLifeDays, maxPromotedSnippetTokens}``.
    Values are coerced like the pin's ``normalizeScore``, ``normalizeNonNegativeInt``
    and ``normalizeOptionalPositiveInt`` (``dreaming.ts:181-230``): JavaScript
    ``Number()`` conversion (``null`` is 0, a blank string falls back), then a
    non-finite value, a score outside [0, 1] or a negative (``maxAgeDays``,
    ``maxPromotedSnippetTokens``: non-positive) integer falls back to the default.
    """
    plugin_config = _memory_core_plugin_config(dict(config or {}))
    dreaming = _as_dict(plugin_config.get("dreaming"))
    phases = _as_dict(dreaming.get("phases"))
    deep = _as_dict(phases.get("deep"))
    dreaming_enabled = _bool(dreaming.get("enabled"), DEFAULT_DEEP_DREAMING_ENABLED)
    deep_enabled = _bool(deep.get("enabled"), True)
    return DeepDreamingPolicy(
        enabled=dreaming_enabled and deep_enabled,
        limit=_non_negative_int(deep.get("limit", _UNDEFINED), DEFAULT_DEEP_DREAMING_LIMIT),
        min_score=_score(deep.get("minScore", _UNDEFINED), DEFAULT_PROMOTION_MIN_SCORE),
        min_recall_count=_non_negative_int(
            deep.get("minRecallCount", _UNDEFINED), DEFAULT_PROMOTION_MIN_RECALL_COUNT
        ),
        min_unique_queries=_non_negative_int(
            deep.get("minUniqueQueries", _UNDEFINED), DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES
        ),
        # dreaming.ts:443-447: a number from normalizeOptionalPositiveInt, else the default.
        max_age_days=_optional_positive_int(deep.get("maxAgeDays", _UNDEFINED))
        or DEFAULT_DEEP_DREAMING_MAX_AGE_DAYS,
        recency_half_life_days=_non_negative_int(
            deep.get("recencyHalfLifeDays", _UNDEFINED), DEFAULT_RECENCY_HALF_LIFE_DAYS
        ),
        # dreaming.ts:448-449: `?? DEFAULT_MEMORY_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS`.
        max_promoted_snippet_tokens=_optional_positive_int(
            deep.get("maxPromotedSnippetTokens", _UNDEFINED)
        )
        or DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS,
    )


def _memory_core_plugin_config(config: dict[str, Any]) -> dict[str, Any]:
    plugins = _as_dict(config.get("plugins"))
    entries = _as_dict(plugins.get("entries"))
    memory_core = _as_dict(entries.get("memory-core"))
    return _as_dict(memory_core.get("config")) or config


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return fallback


def _non_negative_int(value: Any, fallback: int) -> int:
    # dreaming.ts:181-195 normalizeNonNegativeInt.
    if isinstance(value, str) and not js_trim(value):
        return fallback
    number = _js_number(value)
    if not math.isfinite(number):
        return fallback
    floored = math.floor(number)
    return floored if floored >= 0 else fallback


def _optional_positive_int(value: Any) -> int | None:
    # dreaming.ts:197-214 normalizeOptionalPositiveInt.
    if value is _UNDEFINED or value is None:
        return None
    if isinstance(value, str) and not js_trim(value):
        return None
    number = _js_number(value)
    if not math.isfinite(number):
        return None
    floored = math.floor(number)
    return floored if floored > 0 else None


def _score(value: Any, fallback: float) -> float:
    # dreaming.ts:220-230 normalizeScore: out-of-range scores fall back, never clamp.
    if isinstance(value, str) and not js_trim(value):
        return fallback
    number = _js_number(value)
    if not math.isfinite(number) or number < 0 or number > 1:
        return fallback
    return number


# ECMAScript StringToNumber grammar (StrDecimalLiteral / NonDecimalIntegerLiteral).
_JS_DECIMAL_RE = re.compile(r"[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)")
_JS_NON_DECIMAL_RE = re.compile(r"0(?:[xX][0-9a-fA-F]+|[oO][0-7]+|[bB][01]+)")


def _js_number(value: Any) -> float:
    """Return JavaScript ``Number(value)`` for a JSON-shaped Python value.

    ``_UNDEFINED`` (a missing key) is NaN, ``None`` 0, booleans 1/0, strings follow
    StringToNumber (trimmed, empty is 0, no ``inf``/``nan``/``_`` spellings), an
    array converts through its comma-joined string and any other object is NaN.
    """
    if value is _UNDEFINED:
        return math.nan
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float):
        try:
            return float(value)
        except OverflowError:
            return math.inf if value > 0 else -math.inf
    if isinstance(value, str):
        return _js_string_to_number(value)
    if isinstance(value, list | tuple):
        if not value:
            return 0.0
        if len(value) > 1:
            return math.nan  # the joined string contains a comma
        item = value[0]
        if item is None:
            return 0.0  # [null].toString() is ""
        if isinstance(item, bool):
            return math.nan  # "true" / "false"
        return _js_number(item)
    return math.nan


def _js_string_to_number(value: str) -> float:
    text = js_trim(value)
    if not text:
        return 0.0
    if _JS_NON_DECIMAL_RE.fullmatch(text):
        try:
            return float(int(text, 0))
        except OverflowError:
            return math.inf
    if _JS_DECIMAL_RE.fullmatch(text):
        return float(text)
    return math.nan
