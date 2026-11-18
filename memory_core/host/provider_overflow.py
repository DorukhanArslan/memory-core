"""Execute a provider turn with preflight, durable compaction and tool-result recovery."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
import json
from typing import Any

from memory_core.attempt_preflight import (
    AttemptPromptPreflightAttempt,
    AttemptPromptPreflightState,
    handle_attempt_mid_turn_precheck,
    prepare_attempt_prompt_preflight,
    resolve_compaction_session_replay,
)
from memory_core.compaction_replay import ReplayModel
from memory_core.host.lifecycle import HostModelResult, HostTurn
from memory_core.host.session import TurnUsage
from memory_core.overflow_recovery import decide_provider_overflow_recovery, resolve_context_overflow_error
from memory_core.preemptive_compaction import (
    RECOVERY_MIN_KEEP_CHARS,
    SessionToolResultTruncationResult,
    estimate_llm_boundary_token_pressure,
    build_tool_result_replacement_plan,
    estimate_message_token_pressure,
    estimate_tool_result_reduction_potential,
    resolve_auto_live_tool_result_max_chars,
    resolve_effective_compaction_reserve_tokens,
)
from memory_core.tool_result_context_guard import (
    MidTurnPrecheckOptions,
    MidTurnPrecheckSignal,
    ToolResultContextGuard,
)
from memory_core.tool_result_projection import resolve_tool_result_budgets, session_context_entries
from memory_core.session_context import build_session_context
from memory_core.transcript_rewrite import (
    TranscriptSessionManager,
    rewrite_transcript_entries_in_session_manager,
)


_NO_FIT = (
    "No complete recent message fits beside the foreground prompt, tools, and summary. "
    "Reduce the request or select a larger context window."
)


@dataclass(frozen=True)
class ProviderSummaryRequest:
    """Messages belonging to one summary request and the previously saved summary, if any."""

    messages: tuple[Mapping[str, Any], ...]
    previous_summary: str | None
    split_turn: bool


def _messages_text(message):
    content = message.get("content")
    if isinstance(content, str):
        return content
    return "\n".join(item["text"] for item in content or () if item.get("type") == "text")


@dataclass(frozen=True)
class _RecoverySession:
    runner: Any
    session: Any
    turn_id: str
    restore: Callable | None = None

    def read(self):
        return self.runner.catalog.read_continuation(
            self.session.session_id, session_key=self.session.session_key
        )

    def commit(self, snapshot, additions):
        if self.runner._cancel_requested.is_set():
            raise RuntimeError("The provider turn was cancelled before publishing recovery")
        self.runner.catalog.append_events(
            self.session.session_id,
            additions,
            session_key=self.session.session_key,
            expected_version=snapshot["version"],
            updated_at_ms=self.runner._clock(),
        )
        if self.restore is not None:
            self.restore(self.read())


@dataclass
class _QueuedAdmissionRecovery:
    """Stage checkpoints against the branch that the next admitted message will actually see."""

    turn_id: str
    entries: list
    checkpoints: list = field(default_factory=list)

    def read(self):
        return {"visibleEvents": self.entries, "context": build_session_context(self.entries)}

    def commit(self, _snapshot, additions):
        self.entries.extend(additions)
        self.checkpoints.extend(additions)


def _truncate(session, budget, max_chars, *, protect_trailing=False):
    snapshot = session.read()
    manager = TranscriptSessionManager.from_active_branch(snapshot["visibleEvents"])
    before = {e["id"] for e in manager.get_persisted_entries() if "id" in e}
    limit, aggregate = resolve_tool_result_budgets(context_window_tokens=budget, max_chars_override=max_chars)
    plan = build_tool_result_replacement_plan(
        branch=session_context_entries(manager.get_branch()),
        max_chars=limit,
        aggregate_budget_chars=aggregate,
        min_keep_chars=RECOVERY_MIN_KEEP_CHARS,
        protect_trailing_tool_results=protect_trailing,
    )
    rewritten = rewrite_transcript_entries_in_session_manager(
        session_manager=manager,
        replacements=[{"entryId": k, "message": v} for k, v in plan.replacement_messages_by_entry_id.items()],
    )
    if not rewritten.changed:
        return SessionToolResultTruncationResult(False, 0, "no oversized or aggregate tool results")
    additions = [e for e in manager.get_persisted_entries() if e.get("id") not in before]
    session.commit(snapshot, additions)
    return SessionToolResultTruncationResult(True, len(plan.replacement_messages_by_entry_id))


def _retained_cut(entries, keep, maximum):
    cut = len(entries)
    total = 0
    for index in range(len(entries) - 1, -1, -1):
        message = entries[index].get("message")
        if not message:
            continue
        total += estimate_message_token_pressure(message)
        if total > maximum:
            break
        if message["role"] in {
            "assistant",
            "user",
            "custom",
            "bashExecution",
            "branchSummary",
            "compactionSummary",
        }:
            cut = index
            if total >= keep:
                break
    return cut


@dataclass(frozen=True)
class ProviderTurnExecutor:
    """Pass as HostSessionRunner.run_turn's executor. Callbacks only provide model output.

    The model callback receives the complete ordinary request and returns the emitted assistant
    message. The summarizer receives the source messages of each split and returns its text.
    Both callbacks may perform I/O. The durable comparison and append happens after the
    summary is available, so another writer can never lose a newer conversation branch.
    """

    model: ReplayModel
    context_window_tokens: int
    stream: Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]]]
    summarize: Callable[[ProviderSummaryRequest], Awaitable[str]]
    reserve_tokens: int = 16_384
    keep_recent_tokens: int = 20_000
    mid_turn_precheck: bool = False
    observe: Callable[[str, Any], None] | None = None

    extra_params: Mapping[str, Any] | None = None
    transport_api_key: str | None = field(default=None, repr=False)
    auth_profile_id: str | None = None

    def _replay(self, session):
        return resolve_compaction_session_replay(
            self.model,
            session_id=session.session_id,
            forwarded_auth_profile_id=self.auth_profile_id,
            extra_params=self.extra_params,
            transport_api_key=self.transport_api_key,
        )

    def __post_init__(self):
        if (
            not isinstance(self.model, ReplayModel)
            or not callable(self.stream)
            or not callable(self.summarize)
            or type(self.context_window_tokens) is not int
            or self.context_window_tokens <= 0
            or type(self.keep_recent_tokens) is not int
            or self.keep_recent_tokens < 1
            or type(self.reserve_tokens) is not int
            or self.reserve_tokens < 0
        ):
            raise ValueError("A provider executor needs a model, positive budgets and both model callbacks")

    def _emit(self, kind, value):
        if self.observe is not None:
            self.observe(kind, deepcopy(value))

    def _attempt(self, session):
        return AttemptPromptPreflightAttempt(
            self.model.provider,
            self.model.id,
            self.model,
            session_id=session.session_id,
            session_key=session.session_key,
            runtime_plan={"auth": {"forwardedAuthProfileId": self.auth_profile_id}},
            context_token_budget=self.context_window_tokens,
        )

    def preflight(self, session, *, history, prompt, system_prompt, now_ms):
        """Resolve the current prompt before admission, preserving eligible model checkpoints."""
        state = prepare_attempt_prompt_preflight(
            attempt=self._attempt(session),
            state=AttemptPromptPreflightState(),
            compaction_replay_enabled=self._replay(session).enabled,
            context_engine_assembly_succeeded=True,
            context_engine_prompt_authority="canonical",
            context_token_budget=self.context_window_tokens,
            hook_messages_for_current_prompt=history,
            prompt_for_precheck=prompt,
            reserve_tokens=self.reserve_tokens,
            session_message_count=len(history),
            system_prompt=system_prompt,
            tool_result_max_chars=resolve_auto_live_tool_result_max_chars(self.context_window_tokens),
            now=now_ms,
        )
        route = (
            state.preflight_recovery.route
            if state.preflight_recovery
            else (state.context_budget_status or {}).get("route", "fits")
        )
        self._emit("preflight", {"route": route, "admitted": not state.skip_prompt_submission})
        return state

    async def prepare_admission(self, runner, session, turn_id, prompt, system_prompt, *, queued_history=None):
        branch = (_QueuedAdmissionRecovery(turn_id, list(queued_history)) if queued_history is not None
                  else _RecoverySession(runner, session, turn_id))
        staged = branch.checkpoints if isinstance(branch, _QueuedAdmissionRecovery) else []
        attempts = 0
        while True:
            current = branch.read()
            preflight = self.preflight(
                session,
                history=current["context"]["messages"],
                prompt=prompt,
                system_prompt=system_prompt,
                now_ms=runner._clock(),
            )
            if not preflight.skip_prompt_submission or preflight.preflight_recovery is None:
                return preflight, staged
            decision = decide_provider_overflow_recovery(
                error_text=str(preflight.prompt_error),
                context_tokens=self.context_window_tokens,
                overflow_compaction_attempts=attempts,
                attempt_compaction_count=0,
                preflight_route=preflight.preflight_recovery.route,
                prompt_error_source=preflight.prompt_error_source,
            )
            if not decision.should_compact:
                return preflight, staged
            attempts = decision.next_overflow_compaction_attempts
            self._emit("compaction-attempt", {"attempt": attempts})
            ok, _reason = await self._compact(
                branch, foreground=prompt, mid_turn=False, before_admission=True, system_prompt=system_prompt
            )
            if not ok:
                return preflight, staged

    async def _compact(self, session, *, foreground, mid_turn, before_admission=False, system_prompt=""):
        snapshot = session.read()
        manager = TranscriptSessionManager.from_active_branch(snapshot["visibleEvents"])
        branch = session_context_entries(manager.get_branch())
        messages = [e for e in branch if isinstance(e.get("message"), dict)]
        reserve = resolve_effective_compaction_reserve_tokens(self.context_window_tokens, self.reserve_tokens)
        maximum = self.context_window_tokens - reserve
        if mid_turn:
            maximum -= estimate_message_token_pressure({"role": "user", "content": foreground})
        keep = self.keep_recent_tokens
        if before_admission:
            # A pending request may already exceed the whole window. In that case the
            # reference retention budget asks history to improve by one token, reserves
            # room for the summary and keeps one complete recent message/tool atom.
            maximum -= estimate_llm_boundary_token_pressure(
                messages=[], system_prompt=system_prompt, prompt=foreground
            )
            if maximum <= 0:
                maximum = sum(estimate_message_token_pressure(e["message"]) for e in messages) - 1
            summary_reservation = estimate_message_token_pressure(
                {"role": "compactionSummary", "summary": "x" * 16_000}
            )
            keep = min(keep, max(1, maximum - summary_reservation))
        cut = _retained_cut(messages, keep, maximum)
        if cut == len(messages):
            return False, _NO_FIT
        if not cut:
            return False, "not enough messages to compact"
        if mid_turn and all(m["message"]["role"] != "user" for m in messages[cut:]):
            # Keep the active user and their entire tool turn together.
            live = next(
                (i for i in range(len(messages) - 1, -1, -1) if messages[i]["message"]["role"] == "user"),
                None,
            )
            if (
                live is not None
                and sum(estimate_message_token_pressure(e["message"]) for e in messages[live:]) > maximum
            ):
                return False, _NO_FIT
        latest = next(
            (_messages_text(e["message"]) for e in reversed(messages) if e["message"]["role"] == "user"), ""
        )
        prior = next(
            (e.get("summary") for e in reversed(manager.get_branch()) if e.get("type") == "compaction"), None
        )
        start = next((i for i in range(cut - 1, -1, -1) if messages[i]["message"]["role"] == "user"), 0)
        split = messages[cut]["message"]["role"] == "assistant"
        boundary = start if split else cut

        async def summarize(entries, split_turn):
            answer = await self.summarize(
                ProviderSummaryRequest(
                    tuple(deepcopy(e["message"]) for e in entries), None if split_turn else prior, split_turn
                )
            )
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("The compaction model returned an empty summary")
            return answer

        try:
            summary = (
                await summarize(messages[:boundary], False) if boundary else prior or "No prior history."
            )
            if split:
                suffix = await summarize(messages[start:cut], True)
                summary += "\n\n---\n\n**Turn Context (split turn):**\n\n" + suffix
        except Exception as error:
            return False, str(error)
        if latest:
            summary = (
                "## Latest unresolved user request\n"
                + json.dumps(latest, ensure_ascii=False)
                + "\n\n"
                + summary
            )
        first = messages[cut]["id"]
        manager.append_compaction(
            summary,
            first,
            sum(estimate_message_token_pressure(e["message"]) for e in messages),
            details={"latestUnresolvedUserRequest": latest},
            from_hook=False,
            metadata={"runId": session.turn_id},
        )
        [entry] = [e for e in manager.get_persisted_entries() if e.get("id") == manager.get_leaf_id()]
        session.commit(snapshot, [entry])
        if not isinstance(session, _QueuedAdmissionRecovery):
            self._emit("compacted", {"firstKeptEntryId": first, "summary": summary})
        return True, None

    async def __call__(self, turn: HostTurn) -> HostModelResult:
        branch = _RecoverySession(turn._runner, turn.session, turn.turn_id, turn._restore_provider_context)
        budget = self.context_window_tokens
        max_chars = resolve_auto_live_tool_result_max_chars(budget)
        foreground = _messages_text(next(m for m in reversed(turn.messages) if m["role"] == "user"))
        override = None
        attempts = 0
        truncated = False
        tools_executed = False
        guard = ToolResultContextGuard(
            context_window_tokens=budget,
            mid_turn_precheck=MidTurnPrecheckOptions(
                context_token_budget=budget,
                reserve_tokens=lambda: self.reserve_tokens,
                get_replay=lambda: self._replay(turn.session).pressure_context,
                enabled=self.mid_turn_precheck,
                tool_result_max_chars=max_chars,
                get_system_prompt=lambda: turn.model_request()["systemPrompt"],
                observe_decision=lambda decision: self._emit("midturn", decision.route),
            ),
        )
        while True:
            request = turn.model_request()
            if override:
                request["messages"].append(
                    {"role": "user", "content": override, "timestamp": turn._runner._clock()}
                )
            source = route = failure = None
            assistant = None
            try:
                request["messages"] = guard.transform_context(request["messages"])
            except MidTurnPrecheckSignal as error:
                recovered = handle_attempt_mid_turn_precheck(
                    attempt=self._attempt(turn.session),
                    request=error.request,
                    pre_prompt_message_count=guard.last_seen_length or 0,
                    truncate_tool_results=lambda window, cap: _truncate(branch, window, cap),
                )
                if recovered.preflight_recovery.handled:
                    guard.last_seen_length = len(turn.model_request()["messages"])
                    truncated = True
                    continue
                failure = recovered.prompt_error
                source, route = "mid-turn", error.request.route
            else:
                try:
                    assistant = dict(await self.stream(deepcopy(request)))
                except Exception as error:
                    failure = error
                if assistant is not None:
                    if assistant.get("role") != "assistant":
                        raise ValueError("A provider response must be an assistant message")
                    stop = assistant.get("stopReason")
                    if stop != "error":
                        turn.record_message(assistant)
                        calls = [
                            c
                            for c in assistant.get("content", ())
                            if isinstance(c, Mapping) and c.get("type") == "toolCall"
                        ]
                        if calls:
                            for call in calls:
                                await turn.dispatch_async(call["id"], call["name"], call["arguments"])
                                tools_executed = True
                            continue
                        text = _messages_text(assistant)
                        self._emit("terminal", {"kind": "completed", "text": text or None})
                        reported = assistant.get("usage", {})
                        return HostModelResult(
                            usage=TurnUsage(reported.get("input"), reported.get("output")),
                            payloads=({"text": text},) if text else (),
                        )
            error = resolve_context_overflow_error(
                prompt_error=failure,
                assistant=assistant,
                assistant_error_text=(assistant or {}).get("errorMessage"),
                context_token_budget=budget,
            )
            if error is None:
                if failure is not None:
                    raise failure
                turn.record_message(assistant)
                raise RuntimeError(assistant.get("errorMessage") or "The provider turn failed")
            args = dict(
                error_text=error.text,
                context_tokens=budget,
                overflow_compaction_attempts=attempts,
                attempt_compaction_count=0,
                preflight_source=source,
                preflight_route=route,
                current_message_persisted=True,
                current_attempt_replay_safe=not tools_executed,
                prompt_error_source="precheck" if source is not None else None,
                tool_result_truncation_attempted=truncated,
                had_potential_side_effects=any(r.get("memoryMutationOwner") for r in turn._receipts),
            )
            potential = estimate_tool_result_reduction_potential(
                messages=turn.messages, context_window_tokens=budget, max_chars_override=max_chars
            )
            args["has_oversized_tool_results"] = (
                potential.oversized_count > 0 or potential.aggregate_reducible_chars > 0
            )
            decision = decide_provider_overflow_recovery(**args)
            if decision.should_compact:
                attempts = decision.next_overflow_compaction_attempts
                self._emit("compaction-attempt", {"attempt": attempts})
                ok, reason = await self._compact(branch, foreground=foreground, mid_turn=source == "mid-turn")
                args.update(
                    overflow_compaction_attempts=attempts,
                    compaction_attempted=True,
                    compaction_succeeded=ok,
                    failed_compaction_reason=reason,
                    compaction_reason=reason,
                )
                decision = decide_provider_overflow_recovery(**args)
            retry = decision.should_retry
            if decision.should_truncate_tool_results:
                trimmed = _truncate(
                    branch, budget, max_chars, protect_trailing=decision.protect_trailing_tool_results
                )
                truncated = True
                self._emit("truncation", {"count": trimmed.truncated_count})
                if trimmed.truncated and decision.action == "truncate_tool_results":
                    retry = True
                elif not retry:
                    args["tool_result_truncation_attempted"] = True
                    decision = decide_provider_overflow_recovery(**args)
            if retry:
                override = decision.next_prompt_override
                state = self.preflight(
                    turn.session,
                    history=turn.model_request()["messages"],
                    prompt=override or foreground,
                    system_prompt=request["systemPrompt"],
                    now_ms=turn._runner._clock(),
                )
                if not state.skip_prompt_submission:
                    guard.last_seen_length = None
                    continue
            if assistant is not None:
                turn.record_message(assistant)
            text = decision.user_visible_error_text or str(error.text)
            self._emit("terminal", {"kind": decision.error_kind or "context_overflow", "text": text})
            return HostModelResult(payloads=({"text": text, "isError": True},))
