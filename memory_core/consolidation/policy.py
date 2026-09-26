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

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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
    minUniqueQueries, maxAgeDays, recencyHalfLifeDays, maxPromotedSnippetTokens}``;
    invalid values fall back to the defaults and scores clamp to [0, 1].
    """
    plugin_config = _memory_core_plugin_config(dict(config or {}))
    dreaming = _as_dict(plugin_config.get("dreaming"))
    phases = _as_dict(dreaming.get("phases"))
    deep = _as_dict(phases.get("deep"))
    dreaming_enabled = _bool(dreaming.get("enabled"), DEFAULT_DEEP_DREAMING_ENABLED)
    deep_enabled = _bool(deep.get("enabled"), True)
    return DeepDreamingPolicy(
        enabled=dreaming_enabled and deep_enabled,
        limit=_non_negative_int(deep.get("limit"), DEFAULT_DEEP_DREAMING_LIMIT),
        min_score=_score(deep.get("minScore"), DEFAULT_PROMOTION_MIN_SCORE),
        min_recall_count=_non_negative_int(
            deep.get("minRecallCount"), DEFAULT_PROMOTION_MIN_RECALL_COUNT
        ),
        min_unique_queries=_non_negative_int(
            deep.get("minUniqueQueries"), DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES
        ),
        max_age_days=_positive_int(deep.get("maxAgeDays"), DEFAULT_DEEP_DREAMING_MAX_AGE_DAYS),
        recency_half_life_days=_non_negative_int(
            deep.get("recencyHalfLifeDays"), DEFAULT_RECENCY_HALF_LIFE_DAYS
        ),
        max_promoted_snippet_tokens=_positive_int(
            deep.get("maxPromotedSnippetTokens"),
            DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS,
        ),
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
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return number if number >= 0 else fallback


def _positive_int(value: Any, fallback: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


def _score(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return number
