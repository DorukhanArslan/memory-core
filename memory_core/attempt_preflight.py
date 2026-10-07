"""The upstream callers of the compaction replay decision at v2026.9.6, as decision functions.

OpenClaw's embedded runner calls ``shouldPreemptivelyCompactBeforePrompt``
(:func:`memory_core.preemptive_compaction.should_preemptively_compact_before_prompt`) from three
places, and ``resolveCompactionReplayEligibility``
(:func:`memory_core.compaction_replay.resolve_compaction_replay_eligibility`) from two more. This
module ports what those callers decide; the agent loop, the session manager, the logger and the
provider attempt stay with the host, which supplies their inputs and acts on the returned value.

* :func:`prepare_attempt_prompt_preflight` (``run/attempt-prompt-preflight.ts``
  ``prepareEmbeddedAttemptPromptPreflight``): the pre-prompt call site. It builds the replay context
  (model, session, forwarded auth profile, eligibility), runs the decision, skips it when a context
  engine owns compaction, builds the context-budget record and the operator log line, and, when the
  provider checkpoint's own window overflows, returns the recovery route with a precheck error and
  ``skip_prompt_submission``. A raw-history maximum that overflows is only logged
  (``[context-pressure-diagnostic]``). :class:`CompactionReplayRefreshRequiredError` becomes a
  ``precheck`` prompt error.
* :func:`handle_attempt_mid_turn_precheck` (same file, ``handleEmbeddedAttemptMidTurnPrecheck``): the
  routing of a :class:`~memory_core.tool_result_context_guard.MidTurnPrecheckSignal`. A
  ``truncate_tool_results_only`` route first tries the persisted tool-result truncation (the host's
  callable) and is handled in place, or falls back to ``compact_only`` with the precheck error.
* :mod:`memory_core.tool_result_context_guard` (``tool-result-context-guard.ts``): the mid-turn guard
  that raises the signal and carries ``getReplay``.
* :func:`resolve_attempt_compaction_replay_enabled` (``run/attempt-stream-settle.ts``) and
  :func:`resolve_compaction_session_replay` (``compaction-session-execution.ts``): the eligibility
  call sites. The settle site passes the prepared ``extraParams`` and transport API key and hands the
  flag to the preflight; the compaction site additionally fences the history window
  (``preserveCompactionReplayWindow``) and measures the post-server-compaction window with the same
  replay context.

Deviations (host-supplied inputs): ``normalizeMessagesForLlmBoundary`` (the unwindowed precheck view)
and ``sanitizeCompactionReplayMessages`` are host callables; the truncation of the persisted session
is the host's ``truncate_tool_results``; logging is a ``log(level, message)`` callable (levels
``debug``/``info``/``warn``); ``Date.now()`` of the budget record is ``now``. The rest of
``attempt-stream-settle.ts`` and ``compaction-session-execution.ts`` (transport, hooks, the compaction
runs themselves) is the host's and not ported.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from memory_core.compaction_replay import (
    CompactionReplayRefreshRequiredError,
    ReplayIdentity,
    ReplayModel,
    preserve_compaction_replay_window,
    resolve_compaction_replay_eligibility,
)
from memory_core.preemptive_compaction import (
    PREEMPTIVE_OVERFLOW_ERROR_TEXT,
    CompactionReplayPressureContext,
    PreemptiveCompactionDecision,
    build_pre_prompt_context_budget_status,
    calculate_max_tool_result_chars_with_cap,
    estimate_llm_boundary_token_pressure,
    _js_text,
    format_pre_prompt_precheck_log,
    resolve_auto_live_tool_result_max_chars,
    should_preemptively_compact_before_prompt,
)
from memory_core.tool_result_context_guard import MidTurnPrecheckRequest

# src/agents/defaults.ts DEFAULT_CONTEXT_TOKENS
DEFAULT_CONTEXT_TOKENS = 200_000
NO_OVERSIZED_TOOL_RESULTS_REASON = "no oversized or aggregate tool results"
PREASSEMBLY_MAY_OVERFLOW = "preassembly_may_overflow"

Log = Callable[[str, str], None]


def _no_log(_level: str, _message: str) -> None:
    return None


# --- result shapes ------------------------------------------------------------------------------


@dataclass(frozen=True)
class PreflightRecovery:
    """``EmbeddedRunAttemptResult["preflightRecovery"]``: the route the outer recovery loop takes.

    ``source`` is ``"mid-turn"`` only for the mid-turn handler; ``handled`` and ``truncated_count``
    are set when the handler already truncated the persisted tool results.
    """

    route: str
    estimated_prompt_tokens: int | float
    prompt_budget_before_reserve: int
    overflow_tokens: int | float
    source: str | None = None
    handled: bool | None = None
    truncated_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"route": self.route}
        if self.source is not None:
            out["source"] = self.source
        out["estimatedPromptTokens"] = self.estimated_prompt_tokens
        out["promptBudgetBeforeReserve"] = self.prompt_budget_before_reserve
        out["overflowTokens"] = self.overflow_tokens
        if self.handled is not None:
            out["handled"] = self.handled
        if self.truncated_count is not None:
            out["truncatedCount"] = self.truncated_count
        return out


def _budget_snapshot(
    snapshot: PreemptiveCompactionDecision | MidTurnPrecheckRequest,
) -> dict[str, Any]:
    """``buildPreflightRecoveryBudgetSnapshot``: the measured budget the compaction engine needs."""

    return {
        "estimated_prompt_tokens": snapshot.estimated_prompt_tokens,
        "prompt_budget_before_reserve": snapshot.prompt_budget_before_reserve,
        "overflow_tokens": snapshot.overflow_tokens,
    }


@dataclass(frozen=True)
class AttemptPromptPreflightState:
    """``AttemptPromptPreflightState``: what the preflight reads and returns."""

    context_budget_status: dict[str, Any] | None = None
    preflight_recovery: PreflightRecovery | None = None
    prompt_error: BaseException | None = None
    prompt_error_source: str | None = None
    skip_prompt_submission: bool = False


@dataclass(frozen=True)
class ContextEngineInfo:
    """``AttemptContextEngine["info"]``: the active engine's id and compaction ownership."""

    id: str
    owns_compaction: bool = False


@dataclass(frozen=True)
class AttemptPromptPreflightAttempt:
    """The ``EmbeddedRunAttemptParams`` fields the preflight reads."""

    provider: str
    model_id: str
    model: ReplayModel
    session_id: str | None = None
    session_key: str | None = None
    session_file: str | None = None
    runtime_plan: Mapping[str, Any] | None = None
    context_token_budget: int | float | None = None


def resolve_attempt_stream_auth_profile_id(
    runtime_plan: Mapping[str, Any] | None,
) -> str | None:
    """``resolveAttemptStreamAuthProfileId``: only the profile the runtime plan forwards."""

    auth = runtime_plan.get("auth") if isinstance(runtime_plan, Mapping) else None
    if not isinstance(auth, Mapping):
        return None
    value = auth.get("forwardedAuthProfileId")
    return value if value is not None else None


# --- eligibility call sites ---------------------------------------------------------------------


def resolve_attempt_compaction_replay_enabled(
    model: ReplayModel,
    *,
    effective_extra_params: Mapping[str, Any] | None,
    transport_api_key: str | None,
    env: Mapping[str, str] | None = None,
    endpoint_class: Any = None,
    resolve_secret_sentinel: Callable[[str], str] | None = None,
) -> bool:
    """``compactionReplayEnabled`` of ``attempt-stream-settle.ts``.

    ``resolveCompactionReplayEligibility(attempt.model, {extraParams: effectiveExtraParams,
    apiKey: transportApiKey})``: the prepared route's own extra params and key decide whether the
    attempt may use a provider checkpoint; the flag then rides the preflight's replay context.
    """

    return resolve_compaction_replay_eligibility(
        model,
        extra_params=effective_extra_params,
        api_key=transport_api_key,
        env=env,
        endpoint_class=endpoint_class,
        resolve_secret_sentinel=resolve_secret_sentinel,
    )


@dataclass(frozen=True)
class CompactionSessionReplay:
    """The replay settings ``compaction-session-execution.ts`` derives once per compaction run."""

    enabled: bool
    identity: ReplayIdentity
    pressure_context: CompactionReplayPressureContext

    def preserve_window(
        self,
        source: Sequence[Mapping[str, Any]],
        windowed: list[Mapping[str, Any]],
        egress_projection: Any = None,
    ) -> list[Mapping[str, Any]]:
        """``preserveCompactionReplayWindow(originalMessages, limitedMessages, model, identity)``."""

        return preserve_compaction_replay_window(
            source, windowed, self.pressure_context.model, self.identity, egress_projection
        )

    def estimate_server_compaction_tokens_after(
        self, *, messages: list[dict[str, Any]], system_prompt: str | None
    ) -> int:
        """``recordServerCompaction``'s ``serverTokensAfter``: the replacement window's pressure."""

        return estimate_llm_boundary_token_pressure(
            messages=messages,
            system_prompt=system_prompt,
            prompt="",
            replay=self.pressure_context,
        )


def resolve_compaction_session_replay(
    model: ReplayModel,
    *,
    session_id: str | None,
    forwarded_auth_profile_id: str | None,
    extra_params: Mapping[str, Any] | None,
    transport_api_key: str | None,
    env: Mapping[str, str] | None = None,
    endpoint_class: Any = None,
    resolve_secret_sentinel: Callable[[str], str] | None = None,
) -> CompactionSessionReplay:
    """The eligibility call site of ``compaction-session-execution.ts``.

    ``compactionReplayEnabled = resolveCompactionReplayEligibility(effectiveModel, {extraParams:
    effectiveExtraParams, apiKey: transportApiKey})`` and the identity
    ``{sessionId, authProfileId: runtimePlan.auth.forwardedAuthProfileId, enabled}`` shared by the
    history-window fence and the post-compaction measurement.
    """

    enabled = resolve_attempt_compaction_replay_enabled(
        model,
        effective_extra_params=extra_params,
        transport_api_key=transport_api_key,
        env=env,
        endpoint_class=endpoint_class,
        resolve_secret_sentinel=resolve_secret_sentinel,
    )
    return CompactionSessionReplay(
        enabled=enabled,
        identity=ReplayIdentity(session_id, forwarded_auth_profile_id, enabled),
        pressure_context=CompactionReplayPressureContext(
            model, session_id, forwarded_auth_profile_id, enabled
        ),
    )


# --- the pre-prompt call site -------------------------------------------------------------------


def prepare_attempt_prompt_preflight(
    *,
    attempt: AttemptPromptPreflightAttempt,
    state: AttemptPromptPreflightState,
    compaction_replay_enabled: bool,
    context_engine_assembly_succeeded: bool,
    context_engine_prompt_authority: str,
    context_token_budget: int | float,
    hook_messages_for_current_prompt: list[dict[str, Any]],
    prompt_for_precheck: str,
    reserve_tokens: int | float,
    session_message_count: int,
    system_prompt: str,
    tool_result_max_chars: int | None,
    active_context_engine: ContextEngineInfo | None = None,
    append_only_runtime_context: bool | None = None,
    include_boundary_timestamp: bool = True,
    timezone: str | None = None,
    tool_schema_tokens: int | float | None = None,
    unwindowed_context_engine_messages_for_precheck: list[dict[str, Any]] | None = None,
    normalize_messages_for_llm_boundary: Callable[
        [list[dict[str, Any]], dict[str, Any]], list[dict[str, Any]]
    ]
    | None = None,
    now: int | None = None,
    log: Log = _no_log,
) -> AttemptPromptPreflightState:
    """``prepareEmbeddedAttemptPromptPreflight``: decide whether the provider attempt is admitted."""

    context_budget_status = state.context_budget_status
    skip_prompt_submission = state.skip_prompt_submission
    unwindowed_boundary_messages: list[dict[str, Any]] | None = None
    if (
        context_engine_prompt_authority == PREASSEMBLY_MAY_OVERFLOW
        and unwindowed_context_engine_messages_for_precheck is not None
    ):
        boundary_options: dict[str, Any] = {
            "appendOnlyRuntimeContext": append_only_runtime_context,
            **({"timezone": timezone} if timezone else {}),
            **({} if include_boundary_timestamp else {"includeTimestamp": False}),
        }
        normalize = normalize_messages_for_llm_boundary
        if normalize is None:
            msg = "normalize_messages_for_llm_boundary is required for an unwindowed precheck"
            raise TypeError(msg)
        unwindowed_boundary_messages = normalize(
            unwindowed_context_engine_messages_for_precheck, boundary_options
        )
    preemptive: PreemptiveCompactionDecision | None = None
    if not skip_prompt_submission:
        try:
            preemptive = should_preemptively_compact_before_prompt(
                messages=hook_messages_for_current_prompt,
                unwindowed_messages=unwindowed_boundary_messages,
                system_prompt=system_prompt,
                prompt=prompt_for_precheck,
                context_token_budget=context_token_budget,
                reserve_tokens=reserve_tokens,
                tool_result_max_chars=tool_result_max_chars,
                tool_schema_tokens=(
                    tool_schema_tokens
                    if isinstance(tool_schema_tokens, int | float)
                    and not isinstance(tool_schema_tokens, bool)
                    else None
                ),
                replay=CompactionReplayPressureContext(
                    attempt.model,
                    attempt.session_id,
                    resolve_attempt_stream_auth_profile_id(attempt.runtime_plan),
                    compaction_replay_enabled,
                ),
            )
        except CompactionReplayRefreshRequiredError as error:
            return AttemptPromptPreflightState(
                context_budget_status=state.context_budget_status,
                preflight_recovery=state.preflight_recovery,
                prompt_error=error,
                prompt_error_source="precheck",
                skip_prompt_submission=True,
            )
    should_skip_precheck = skip_prompt_submission or bool(
        context_engine_assembly_succeeded
        and active_context_engine is not None
        and active_context_engine.owns_compaction
        and context_engine_prompt_authority != PREASSEMBLY_MAY_OVERFLOW
        and not (preemptive is not None and preemptive.compaction_replay is not None)
    )
    if should_skip_precheck and not skip_prompt_submission:
        engine_id = active_context_engine.id if active_context_engine is not None else ""
        log("info", f'[context-overflow-precheck] skipped: context engine "{engine_id}" owns compaction')
    if should_skip_precheck:
        preemptive = None
    if preemptive is not None:
        unwindowed_count = (
            {"unwindowed_message_count": len(unwindowed_context_engine_messages_for_precheck)}
            if context_engine_prompt_authority == PREASSEMBLY_MAY_OVERFLOW
            and unwindowed_context_engine_messages_for_precheck is not None
            else {}
        )
        context_budget_status = build_pre_prompt_context_budget_status(
            result=preemptive,
            provider=attempt.provider,
            model_id=attempt.model_id,
            message_count=session_message_count,
            context_token_budget=context_token_budget,
            reserve_tokens=reserve_tokens,
            session_id=attempt.session_id or None,
            now=now,
            **unwindowed_count,
        )
        log(
            "debug",
            format_pre_prompt_precheck_log(
                result=preemptive,
                provider=attempt.provider,
                model_id=attempt.model_id,
                message_count=session_message_count,
                context_token_budget=context_token_budget,
                reserve_tokens=reserve_tokens,
                session_key=attempt.session_key or None,
                session_id=attempt.session_id or None,
                session_file=attempt.session_file or None,
                **unwindowed_count,
            ),
        )
        checkpoint_pressure = preemptive.compaction_replay
        if checkpoint_pressure is not None and checkpoint_pressure.route != "fits":
            # Only the actual canonical window can require recovery; the raw-history maximum
            # above remains diagnostic even when it exceeds this window.
            return AttemptPromptPreflightState(
                context_budget_status=context_budget_status,
                preflight_recovery=PreflightRecovery(
                    route=checkpoint_pressure.route, **_budget_snapshot(checkpoint_pressure)
                ),
                prompt_error=Exception(PREEMPTIVE_OVERFLOW_ERROR_TEXT),
                prompt_error_source="precheck",
                skip_prompt_submission=True,
            )
        if preemptive.route != "fits":
            # This pressure estimate is diagnostic only; it never compacts or discards history.
            log(
                "info",
                f"[context-pressure-diagnostic] admitted provider attempt for "
                f"{attempt.provider}/{attempt.model_id} route={preemptive.route} "
                f"estimatedPromptTokens={preemptive.estimated_prompt_tokens} "
                f"promptBudgetBeforeReserve={preemptive.prompt_budget_before_reserve}",
            )
    return AttemptPromptPreflightState(
        context_budget_status=context_budget_status,
        preflight_recovery=state.preflight_recovery,
        prompt_error=state.prompt_error,
        prompt_error_source=state.prompt_error_source,
        skip_prompt_submission=state.skip_prompt_submission,
    )


# --- the mid-turn handler -----------------------------------------------------------------------


@dataclass(frozen=True)
class MidTurnPrecheckOutcome:
    """``handleEmbeddedAttemptMidTurnPrecheck``'s return: the route, and a precheck error to raise."""

    preflight_recovery: PreflightRecovery
    prompt_error: BaseException | None = None


def handle_attempt_mid_turn_precheck(
    *,
    attempt: AttemptPromptPreflightAttempt,
    request: MidTurnPrecheckRequest,
    pre_prompt_message_count: int,
    truncate_tool_results: Callable[[int | float, int], Any],
    build_session_context_messages: Callable[[], list[dict[str, Any]]] | None = None,
    sanitize_compaction_replay_messages: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
    | None = None,
    replace_session_messages: Callable[[list[dict[str, Any]]], None] | None = None,
    log: Log = _no_log,
) -> MidTurnPrecheckOutcome:
    """``handleEmbeddedAttemptMidTurnPrecheck``: route a mid-turn guard signal.

    ``truncate_tool_results(context_window_tokens, max_chars_override)`` is the host's persisted
    truncation (``truncateOversizedToolResultsInSessionManager``, whose Python counterpart is
    :func:`memory_core.preemptive_compaction.truncate_oversized_tool_results_in_session_file`) and
    returns an object with ``truncated``, ``truncated_count`` and ``reason``. After a successful
    truncation the rebuilt context (``build_session_context_messages`` then
    ``sanitize_compaction_replay_messages``) goes to ``replace_session_messages``.
    """

    def log_precheck(route: str, extra: str | None = None) -> None:
        log(
            "warn",
            f"[context-overflow-midturn-precheck] "
            f"sessionKey={_js_text(attempt.session_key if attempt.session_key is not None else attempt.session_id)} "
            f"provider={attempt.provider}/{attempt.model_id} route={route} "
            f"estimatedPromptTokens={request.estimated_prompt_tokens} "
            f"promptBudgetBeforeReserve={request.prompt_budget_before_reserve} "
            f"overflowTokens={request.overflow_tokens} "
            f"toolResultReducibleChars={request.tool_result_reducible_chars} "
            f"effectiveReserveTokens={request.effective_reserve_tokens} "
            f"prePromptMessageCount={pre_prompt_message_count} "
            + (f"{extra} " if extra else "")
            + f"sessionFile={_js_text(attempt.session_file)}",
        )

    if request.route == "truncate_tool_results_only":
        context_token_budget = (
            DEFAULT_CONTEXT_TOKENS
            if attempt.context_token_budget is None
            else attempt.context_token_budget
        )
        tool_result_max_chars = calculate_max_tool_result_chars_with_cap(
            context_token_budget, resolve_auto_live_tool_result_max_chars(context_token_budget)
        )
        truncation = truncate_tool_results(context_token_budget, tool_result_max_chars)
        if truncation.truncated:
            recovery = PreflightRecovery(
                route="truncate_tool_results_only",
                source="mid-turn",
                handled=True,
                truncated_count=truncation.truncated_count,
                **_budget_snapshot(request),
            )
            if replace_session_messages is not None:
                messages = build_session_context_messages() if build_session_context_messages else []
                if sanitize_compaction_replay_messages is not None:
                    messages = sanitize_compaction_replay_messages(messages)
                replace_session_messages(messages)
            log_precheck(
                request.route, f"handled=true truncatedCount={truncation.truncated_count}"
            )
            return MidTurnPrecheckOutcome(recovery)
        if truncation.reason == NO_OVERSIZED_TOOL_RESULTS_REASON:
            # The mid-turn estimate sees the in-memory prompt view, while persisted recovery may
            # already have capped the same tool results: retry without manufacturing compaction.
            log_precheck(
                request.route,
                f"handled=true truncatedCount=0 truncateSkippedReason={truncation.reason}",
            )
            return MidTurnPrecheckOutcome(
                PreflightRecovery(
                    route="truncate_tool_results_only",
                    source="mid-turn",
                    handled=True,
                    truncated_count=0,
                    **_budget_snapshot(request),
                )
            )
        log_precheck(
            "compact_only",
            f"truncateFallbackReason={truncation.reason if truncation.reason else 'unknown'}",
        )
        return MidTurnPrecheckOutcome(
            PreflightRecovery(route="compact_only", source="mid-turn", **_budget_snapshot(request)),
            Exception(PREEMPTIVE_OVERFLOW_ERROR_TEXT),
        )
    log_precheck(request.route)
    return MidTurnPrecheckOutcome(
        PreflightRecovery(route=request.route, source="mid-turn", **_budget_snapshot(request)),
        Exception(PREEMPTIVE_OVERFLOW_ERROR_TEXT),
    )


__all__ = [
    "AttemptPromptPreflightAttempt",
    "AttemptPromptPreflightState",
    "CompactionSessionReplay",
    "ContextEngineInfo",
    "DEFAULT_CONTEXT_TOKENS",
    "MidTurnPrecheckOutcome",
    "PreflightRecovery",
    "handle_attempt_mid_turn_precheck",
    "prepare_attempt_prompt_preflight",
    "resolve_attempt_compaction_replay_enabled",
    "resolve_attempt_stream_auth_profile_id",
    "resolve_compaction_session_replay",
]
