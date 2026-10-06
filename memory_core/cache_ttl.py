"""Cache-TTL provider eligibility, the session marker and the pruning call sites at v2026.9.6.

Ports ``src/agents/embedded-agent-runner/cache-ttl.ts`` (``isCacheTtlEligibleProvider``,
``readLastCacheTtlTimestamp``), the Anthropic-family and Google rules it consults
(``anthropic-family-cache-semantics.ts``, ``prompt-cache-retention.ts``), the marker append of
``run/attempt-thread-helpers.ts`` (``appendAttemptCacheTtlIfNeeded``) and the wiring of
``run/attempt-setup.ts`` that gates ``pruneExpiredCacheTtlToolResults`` behind the same eligibility
and feeds it the cache-touch time (:class:`CacheTtlContextTransform`).

The provider plugin's ``isCacheTtlEligible`` hook is host-supplied: a callable taking the
``ProviderCacheTtlEligibilityContext`` mapping (``provider``, ``modelId``, ``modelApi``,
``baseUrl``, ``supportsPromptCacheKey``) and returning ``True``, ``False`` or ``None`` to fall
back to the core rules. Upstream resolves the plugin by provider id inside the plugin runtime;
here the host does that lookup and passes the callable for the provider at hand.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from memory_core.bootstrap._js import js_trim
from memory_core.tool_result_projection import (
    CACHE_TTL_CUSTOM_TYPE,
    CacheTtlPruningSettings,
    ToolResultPromptProjectionState,
    hash_tool_result_projection_snapshot,
    prune_expired_cache_ttl_tool_results,
    resolve_cache_ttl_pruning_settings,
    serialize_cache_ttl_tool_result_projections,
)

CacheTtlProviderHook = Callable[[dict[str, Any]], "bool | None"]

# Application Inference Profile ARNs across all AWS partitions with Bedrock.
_BEDROCK_APP_INFERENCE_PROFILE_ARN_RE = re.compile(r"^arn:aws(-cn|-us-gov)?:bedrock:")


def _normalize_optional_lowercase(value: Any) -> str | None:
    """``normalizeOptionalLowercaseString``: trimmed, lowercased, ``None`` when blank or not text."""

    if not isinstance(value, str):
        return None
    trimmed = js_trim(value)
    return trimmed.lower() if trimmed else None


def _normalize_lowercase_or_empty(value: Any) -> str:
    return _normalize_optional_lowercase(value) or ""


def is_anthropic_model_ref(model_id: str) -> bool:
    return _normalize_lowercase_or_empty(model_id).startswith("anthropic/")


def _is_anthropic_bedrock_model(model_id: str) -> bool:
    normalized = _normalize_lowercase_or_empty(model_id)
    # Direct Claude ids and regional inference profiles, e.g. "us.anthropic.claude-sonnet-4-6".
    if "anthropic.claude" in normalized or "anthropic/claude" in normalized:
        return True
    # Application inference profile ARN: a name heuristic on the profile id segment.
    if (
        _BEDROCK_APP_INFERENCE_PROFILE_ARN_RE.search(normalized)
        and ":application-inference-profile/" in normalized
    ):
        profile_id = normalized.split(":application-inference-profile/")[1]
        return "claude" in profile_id
    return False


def is_anthropic_family_cache_ttl_eligible(
    *, provider: str, model_id: str, model_api: str | None = None
) -> bool:
    normalized_provider = _normalize_optional_lowercase(provider)
    if normalized_provider in ("anthropic", "anthropic-vertex"):
        return True
    if normalized_provider == "amazon-bedrock":
        return _is_anthropic_bedrock_model(model_id)
    return model_api == "anthropic-messages"


def is_google_prompt_cache_eligible(*, model_api: str | None = None, model_id: str | None = None) -> bool:
    if model_api != "google-generative-ai":
        return False
    normalized = _normalize_lowercase_or_empty(model_id)
    return normalized.startswith("gemini-2.5") or normalized.startswith("gemini-3")


def is_cache_ttl_eligible_provider(
    provider: str,
    model_id: str,
    model_api: str | None = None,
    route: Mapping[str, Any] | None = None,
    *,
    provider_hook: CacheTtlProviderHook | None = None,
) -> bool:
    """``isCacheTtlEligibleProvider``: whether this provider/model supports cache-TTL markers.

    The provider plugin decides first (``provider_hook``; a ``None`` result defers); then the
    Anthropic family (``anthropic``, ``anthropic-vertex``, Claude on Bedrock, any
    ``anthropic-messages`` route), Kilo Code routing an ``anthropic/`` model, and the Google
    ``gemini-2.5``/``gemini-3`` models over ``google-generative-ai``. ``route`` carries
    ``baseUrl`` and ``supportsPromptCacheKey`` for the hook.
    """

    normalized_provider = _normalize_lowercase_or_empty(provider)
    normalized_model_id = _normalize_lowercase_or_empty(model_id)
    if provider_hook is not None:
        route = route or {}
        context: dict[str, Any] = {"provider": normalized_provider, "modelId": normalized_model_id}
        for key, value in (
            ("modelApi", model_api),
            ("baseUrl", route.get("baseUrl")),
            ("supportsPromptCacheKey", route.get("supportsPromptCacheKey")),
        ):
            if value is not None:
                context[key] = value
        plugin_eligibility = provider_hook(context)
        if plugin_eligibility is not None:
            return bool(plugin_eligibility)
    return (
        is_anthropic_family_cache_ttl_eligible(
            provider=normalized_provider, model_id=normalized_model_id, model_api=model_api
        )
        or (normalized_provider == "kilocode" and is_anthropic_model_ref(normalized_model_id))
        or is_google_prompt_cache_eligible(model_api=model_api, model_id=normalized_model_id)
    )


def _matches_cache_ttl_context(data: Any, context: Mapping[str, Any] | None) -> bool:
    if not context:
        return True
    record = data if isinstance(data, Mapping) else {}
    expected_provider = _normalize_optional_lowercase(context.get("provider"))
    if expected_provider and _normalize_optional_lowercase(record.get("provider")) != expected_provider:
        return False
    expected_model = _normalize_optional_lowercase(context.get("modelId"))
    return not (
        expected_model and _normalize_optional_lowercase(record.get("modelId")) != expected_model
    )


def read_last_cache_ttl_timestamp(
    entries: Sequence[Any] | Callable[[], Sequence[Any]] | None,
    context: Mapping[str, Any] | None = None,
) -> int | float | None:
    """``readLastCacheTtlTimestamp``: the newest marker timestamp matching ``provider``/``modelId``.

    ``entries`` is the session manager's entry list (``getEntries()``), or a callable returning it;
    a store without entries reads as empty, and a failing read as ``None``.
    """

    try:
        listed = entries() if callable(entries) else entries
        for entry in reversed(list(listed or [])):
            if not isinstance(entry, Mapping):
                continue
            if entry.get("type") != "custom" or entry.get("customType") != CACHE_TTL_CUSTOM_TYPE:
                continue
            data = entry.get("data")
            if not _matches_cache_ttl_context(data, context):
                continue
            timestamp = data.get("timestamp") if isinstance(data, Mapping) else None
            if (
                isinstance(timestamp, (int, float))
                and not isinstance(timestamp, bool)
                and timestamp
                and math.isfinite(timestamp)
            ):
                return timestamp
    except Exception:  # noqa: BLE001 - upstream swallows every read failure
        return None
    return None


def _is_cache_ttl_mode(config: Any) -> bool:
    """``config.agents.defaults.contextPruning.mode === "cache-ttl"``."""

    return (
        isinstance(config, Mapping)
        and isinstance(config.get("agents"), Mapping)
        and isinstance(config["agents"].get("defaults"), Mapping)
        and isinstance(config["agents"]["defaults"].get("contextPruning"), Mapping)
        and config["agents"]["defaults"]["contextPruning"].get("mode") == "cache-ttl"
    )


def should_append_attempt_cache_ttl(
    *,
    timed_out_during_compaction: bool,
    compaction_occurred_this_attempt: bool,
    config: Any,
    provider: str,
    model_id: str,
    model_api: str | None = None,
    model_route: Mapping[str, Any] | None = None,
    is_eligible: Callable[..., bool] = is_cache_ttl_eligible_provider,
) -> bool:
    """``shouldAppendAttemptCacheTtl``: compaction and timeout attempts skip the marker."""

    if timed_out_during_compaction or compaction_occurred_this_attempt:
        return False
    return _is_cache_ttl_mode(config) and bool(is_eligible(provider, model_id, model_api, model_route))


def append_attempt_cache_ttl_if_needed(
    *,
    append_custom_entry: Callable[[str, Any], Any] | None,
    timed_out_during_compaction: bool,
    compaction_occurred_this_attempt: bool,
    config: Any,
    provider: str,
    model_id: str,
    tool_result_prompt_projection_state: ToolResultPromptProjectionState,
    model_api: str | None = None,
    model_route: Mapping[str, Any] | None = None,
    is_eligible: Callable[..., bool] = is_cache_ttl_eligible_provider,
    now: int | float | None = None,
) -> bool:
    """``appendAttemptCacheTtlIfNeeded``: append the marker when policy and model allow it.

    The marker carries ``timestamp``, ``provider`` and ``modelId``, plus the projection snapshot
    when it changed since the last write. Returns whether the transcript was eligible for a marker;
    a session manager without ``appendCustomEntry`` (``append_custom_entry=None``) records none.
    """

    if not should_append_attempt_cache_ttl(
        timed_out_during_compaction=timed_out_during_compaction,
        compaction_occurred_this_attempt=compaction_occurred_this_attempt,
        config=config,
        provider=provider,
        model_id=model_id,
        model_api=model_api,
        model_route=model_route,
        is_eligible=is_eligible,
    ):
        return False
    if append_custom_entry is not None:
        state = tool_result_prompt_projection_state
        snapshot = serialize_cache_ttl_tool_result_projections(state)
        digest = hash_tool_result_projection_snapshot(snapshot)
        append_custom_entry(
            CACHE_TTL_CUSTOM_TYPE,
            {
                "timestamp": now if now is not None else int(time.time() * 1000),
                "provider": provider,
                "modelId": model_id,
                **(snapshot if digest != state.last_written_snapshot_hash else {}),
            },
        )
        state.last_written_snapshot_hash = digest
    return True


def resolve_attempt_cache_ttl_settings(
    *,
    config: Any,
    provider: str,
    model_id: str,
    model_api: str | None = None,
    model_route: Mapping[str, Any] | None = None,
    is_eligible: Callable[..., bool] = is_cache_ttl_eligible_provider,
) -> CacheTtlPruningSettings | None:
    """The ``cacheTtlSettings`` gate of ``attempt-setup.ts``.

    ``contextPruning.mode`` is checked before the provider so that disabled pruning never resolves
    provider hooks; an ineligible provider gets no pruning settings either.
    """

    if not _is_cache_ttl_mode(config):
        return None
    if not is_eligible(provider, model_id, model_api, model_route):
        return None
    return resolve_cache_ttl_pruning_settings(config["agents"]["defaults"]["contextPruning"])


class CacheTtlContextTransform:
    """The ``transformContext`` wrapper installed by ``attempt-setup.ts`` for cache-TTL pruning.

    Each call first runs the previous transform (when there is one), then projects expired
    cache-TTL tool results over its result with the current cache-touch time. A prune moves the
    touch time to now; :meth:`record_cache_touch` sets it from the model call. Server-side tool
    clearing owns new rounds: while it is on, earlier client projections still replay but no new
    round is pruned, so the prefix already sent does not change.
    """

    def __init__(
        self,
        *,
        settings: CacheTtlPruningSettings,
        context_window_tokens: int | float,
        projection_state: ToolResultPromptProjectionState,
        last_cache_touch_at: int | float | None = None,
        previous_transform: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
        drop_thinking_blocks_for_estimate: bool | Callable[[], bool] = False,
        server_tool_clearing_enabled: bool | Callable[[], bool] = False,
        clock_ms: Callable[[], int | float] = lambda: int(time.time() * 1000),
    ) -> None:
        self.settings = settings
        self.context_window_tokens = context_window_tokens
        self.projection_state = projection_state
        self.last_cache_touch_at = last_cache_touch_at
        self._previous = previous_transform
        self._drop_thinking = drop_thinking_blocks_for_estimate
        self._server_clearing = server_tool_clearing_enabled
        self._clock_ms = clock_ms

    def __call__(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        transformed = self._previous(messages) if self._previous is not None else messages
        source = transformed if isinstance(transformed, list) else messages
        drop = self._drop_thinking() if callable(self._drop_thinking) else self._drop_thinking
        clearing = (
            self._server_clearing() if callable(self._server_clearing) else self._server_clearing
        )
        return prune_expired_cache_ttl_tool_results(
            messages=source,
            settings=self.settings,
            context_window_tokens=self.context_window_tokens,
            last_cache_touch_at=self.last_cache_touch_at,
            drop_thinking_blocks_for_estimate=bool(drop),
            now=self._clock_ms(),
            projection_state=self.projection_state,
            prune_new_rounds=not clearing,
            on_pruned=self._on_pruned,
        )

    def _on_pruned(self) -> None:
        self.last_cache_touch_at = self._clock_ms()

    def record_cache_touch(self, started_at: int | float) -> None:
        """``recordCacheTouch``: the model call that just started touched the provider cache."""

        self.last_cache_touch_at = started_at


def install_cache_ttl_context_transform(
    *,
    config: Any,
    provider: str,
    model_id: str,
    model_api: str | None,
    model_route: Mapping[str, Any] | None,
    context_window_tokens: int | float,
    projection_state: ToolResultPromptProjectionState,
    session_entries: Sequence[Any] | Callable[[], Sequence[Any]] | None,
    previous_transform: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    drop_thinking_blocks_for_estimate: bool | Callable[[], bool] = False,
    server_tool_clearing_enabled: bool | Callable[[], bool] = False,
    is_eligible: Callable[..., bool] = is_cache_ttl_eligible_provider,
    clock_ms: Callable[[], int | float] = lambda: int(time.time() * 1000),
) -> CacheTtlContextTransform | None:
    """The whole ``attempt-setup.ts`` cache-TTL block: settings gate, marker read, transform.

    ``None`` when pruning is off or the provider is not eligible (the previous transform then
    stays as it is). The initial cache-touch time is the newest marker matching this
    provider/model.
    """

    settings = resolve_attempt_cache_ttl_settings(
        config=config,
        provider=provider,
        model_id=model_id,
        model_api=model_api,
        model_route=model_route,
        is_eligible=is_eligible,
    )
    if settings is None:
        return None
    return CacheTtlContextTransform(
        settings=settings,
        context_window_tokens=context_window_tokens,
        projection_state=projection_state,
        last_cache_touch_at=read_last_cache_ttl_timestamp(
            session_entries, {"provider": provider, "modelId": model_id}
        ),
        previous_transform=previous_transform,
        drop_thinking_blocks_for_estimate=drop_thinking_blocks_for_estimate,
        server_tool_clearing_enabled=server_tool_clearing_enabled,
        clock_ms=clock_ms,
    )


__all__ = [
    "CacheTtlContextTransform",
    "CacheTtlProviderHook",
    "append_attempt_cache_ttl_if_needed",
    "install_cache_ttl_context_transform",
    "is_anthropic_family_cache_ttl_eligible",
    "is_anthropic_model_ref",
    "is_cache_ttl_eligible_provider",
    "is_google_prompt_cache_eligible",
    "read_last_cache_ttl_timestamp",
    "resolve_attempt_cache_ttl_settings",
    "should_append_attempt_cache_ttl",
]
