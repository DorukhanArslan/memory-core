"""Opt-in, unowned-provider history preparation for actual host model requests.

The supported transports are OpenAI completions and Responses. Policy is derived
from model facts using OpenClaw v2026.9.9 ``transcript-policy.ts``; callers cannot
provide policy flags or a model-switch cutoff. This owner runs the history and
stream stages, without invoking a downstream provider converter.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
import math
import re
from typing import Any

from memory_core.bootstrap._js import js_trim
from memory_core.compaction_replay import (
    ReplayIdentity, ReplayModel, preserve_compaction_replay_window,
    resolve_compaction_replay_eligibility,
)
from memory_core.history import get_history_limit_from_session_key, limit_history_turns
from memory_core.history_stream_inputs import sanitize_replay_tool_call_inputs
from memory_core.history_validation import (
    sanitize_anthropic_replay_tool_results, sanitize_google_turn_ordering,
    strip_trailing_assistant_prefill_turns, validate_anthropic_turns, validate_gemini_turns,
)
from memory_core.replay_history import normalize_assistant_replay_content
from memory_core.replay_repair import (
    _extract_tool_calls_from_assistant, _extract_tool_result_id,
    sanitize_tool_call_inputs, sanitize_tool_use_result_pairing,
    sanitize_tool_use_result_pairing_for_model,
)
from memory_core.responses_history import (
    downgrade_openai_function_call_reasoning_pairs, drop_stale_openai_reasoning,
    normalize_openai_responses_tool_call_ids,
)
from memory_core.session_entry import js_date_parse
from memory_core.tool_call_ids import sanitize_tool_call_ids
from memory_core.usage_normalization import normalize_usage

_RESPONSES = frozenset({"openai-responses", "openai-chatgpt-responses", "azure-openai-responses"})
_REASONING_MODELS = frozenset({
    "kimi-for-coding", "kimi-k2.5", "kimi-k2.6", "kimi-k2.7-code", "kimi-k2.7-code-highspeed",
    "kimi-k3", "kimi-k2-thinking", "kimi-k2-thinking-turbo", "mimo-v2-pro", "mimo-v2-omni",
    "mimo-v2.5", "mimo-v2.5-pro", "mimo-v2.6-flash", "mimo-v2.6-pro", "mimo-v2.6-pro-ultraspeed",
})


@dataclass(frozen=True)
class HistoryReplayContext:
    """Trusted model/configuration facts for the supported unowned transports."""

    model: ReplayModel
    config: Mapping[str, Any] | None = None
    route: Mapping[str, Any] | None = None
    forwarded_auth_profile_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.model, ReplayModel):
            raise TypeError("history replay model must be a ReplayModel")
        if self.model.api not in {"openai-completions", *_RESPONSES}:
            raise ValueError("History replay supports unowned OpenAI completions and Responses APIs")
        if any(not isinstance(value, str) or not js_trim(value)
               for value in (self.model.provider, self.model.api, self.model.id)):
            raise ValueError("History replay requires provider, API and model identity")
        if self.config is not None and not isinstance(self.config, Mapping):
            raise TypeError("history replay config must be a mapping")
        if self.route is not None and not isinstance(self.route, Mapping):
            raise TypeError("history replay route must be a mapping")
        if self.forwarded_auth_profile_id is not None and not isinstance(self.forwarded_auth_profile_id, str):
            raise TypeError("the forwarded auth profile id must be a string")
        object.__setattr__(self, "model", replace(self.model,
            params=deepcopy(self.model.params), compat=deepcopy(self.model.compat)))
        object.__setattr__(self, "config", deepcopy(dict(self.config)) if self.config is not None else None)
        object.__setattr__(self, "route", deepcopy(dict(self.route)) if self.route is not None else None)


@dataclass(frozen=True)
class HistoryReplayPolicy:
    """The actual unowned fallback policy, retained for passive observation."""

    sanitizeMode: str = "images-only"
    sanitizeToolCallIds: bool = True
    toolCallIdMode: str = "strict"
    preserveNativeAnthropicToolUseIds: bool = False
    repairToolUseResultPairing: bool = True
    preserveSignatures: bool = False
    appendOnlyRuntimeContext: bool = False
    dropThinkingBlocks: bool = False
    dropReasoningFromHistory: bool = False
    applyGoogleTurnOrdering: bool = False
    validateGeminiTurns: bool = False
    validateAnthropicTurns: bool = False
    allowSyntheticToolResults: bool = False


def resolve_history_replay_policy(model: ReplayModel) -> HistoryReplayPolicy:
    """``buildUnownedProviderTransportReplayFallback`` merged with core defaults."""
    completions = model.api == "openai-completions"
    model_id = js_trim(model.id).lower()
    final = next((part for part in reversed(model_id.split("/")) if part), model_id)
    colon = [part for part in final.split(":") if part]
    candidates = {final, *(colon[:1] + colon[-1:] if len(colon) > 1 else [])}
    preserve_reasoning = model.reasoning is True or bool(candidates & _REASONING_MODELS)
    claude = bool(re.search(r"(?:^|[./:_-])claude(?:$|[./:_-])", model_id))
    return HistoryReplayPolicy(
        dropReasoningFromHistory=completions and not preserve_reasoning,
        applyGoogleTurnOrdering=completions, validateGeminiTurns=completions,
        validateAnthropicTurns=completions or claude,
        allowSyntheticToolResults=model.api in _RESPONSES,
    )


def _same_snapshot(left, right):
    return all((left.get(key) or "") == (right.get(key) or "")
               for key in ("provider", "modelApi", "modelId"))


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _timestamp(value):
    if _finite(value):
        return value
    parsed = js_date_parse(value) if isinstance(value, str) else math.nan
    return parsed if math.isfinite(parsed) else None


def _zero_usage():
    return {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0,
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}


def _matching_usage_numbers(raw, normalized, keys):
    return isinstance(raw, Mapping) and all(
        _finite(raw.get(key)) and raw[key] == normalized[key] for key in keys
    )


def _usage_snapshot_matches(raw, normalized):
    """Keep provider metadata when the native snapshot needs no repair."""
    if not _matching_usage_numbers(raw, normalized, ("input", "output", "cacheRead", "cacheWrite", "totalTokens")):
        return False
    if "contextUsage" in normalized:
        context = normalized["contextUsage"]
        original = raw.get("contextUsage")
        if not isinstance(original, Mapping) or original.get("state") != context["state"]:
            return False
        if context["state"] != "unavailable" and not _matching_usage_numbers(
                original, context, ("promptTokens", "totalTokens")):
            return False
    elif "contextUsage" in raw:
        return False
    if "cost" in normalized:
        return _matching_usage_numbers(raw.get("cost"), normalized["cost"],
                                       ("input", "output", "cacheRead", "cacheWrite", "total"))
    return "cost" not in raw


def _usage_snapshots(messages):
    """Replay's usage normalization, including the latest compaction fence."""
    compaction = next((index for index in range(len(messages) - 1, -1, -1)
                       if messages[index].get("role") == "compactionSummary"), -1)
    cutoff = _timestamp(messages[compaction].get("timestamp")) if compaction >= 0 else None
    out = list(messages)
    changed = False
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        raw = message.get("usage")
        timestamp = _timestamp(message.get("timestamp"))
        stale = compaction >= 0 and isinstance(raw, (Mapping, list)) and (
            timestamp <= cutoff if timestamp is not None and cutoff is not None else index < compaction)
        normalized = normalize_usage(raw)
        if stale or normalized is None:
            usage = _zero_usage()
        else:
            usage = {key: normalized.get(key, 0) for key in ("input", "output", "cacheRead", "cacheWrite")}
            if "contextUsage" in normalized:
                usage["contextUsage"] = deepcopy(normalized["contextUsage"])
            usage["totalTokens"] = normalized.get("total", sum(usage[key] for key in (
                "input", "output", "cacheRead", "cacheWrite")))
            cost = raw.get("cost") if isinstance(raw, Mapping) else None
            if isinstance(cost, Mapping) and any(_finite(cost.get(key)) for key in (
                    "input", "output", "cacheRead", "cacheWrite", "total")):
                buckets = {key: cost[key] if _finite(cost.get(key)) else 0
                           for key in ("input", "output", "cacheRead", "cacheWrite")}
                buckets["total"] = cost["total"] if _finite(cost.get("total")) else sum(buckets.values())
                if cost.get("totalOrigin") == "provider-billed":
                    buckets["totalOrigin"] = "provider-billed"
                usage["cost"] = buckets
        if stale or not _usage_snapshot_matches(raw, usage):
            out[index] = {**message, "usage": usage}
            changed = True
    return out if changed else messages


def _drop_reasoning(messages):
    latest_user = next((index for index in range(len(messages) - 1, -1, -1)
                        if messages[index].get("role") == "user"), -1)
    out = []
    for index, message in enumerate(messages):
        content = message.get("content")
        if message.get("role") != "assistant" or not isinstance(content, list):
            out.append(message)
            continue
        has_call = any(isinstance(block, Mapping) and block.get("type") in {
            "toolCall", "tool_use", "function_call"} for block in content)
        previous_assistant = next((messages[pos].get("role") for pos in range(index - 1, -1, -1)
                                   if messages[pos].get("role") in {"user", "assistant"}), None) == "assistant"
        following_result = False
        for following in messages[index + 1:]:
            if following.get("role") == "toolResult":
                following_result = True
                break
            if following.get("role") == "user":
                break
        preserve = index >= latest_user and has_call and not previous_assistant and following_result
        parts = content if preserve else [block for block in content if not (
            isinstance(block, Mapping) and block.get("type") in {"thinking", "redacted_thinking"})]
        out.append(message if len(parts) == len(content) else {**message, "content": parts or [
            {"type": "text", "text": "[assistant reasoning omitted]"}]})
    return out


def _assert_responses_pairs(messages):
    pending = {}
    for index, message in enumerate(messages):
        role = message.get("role")
        if pending and role != "toolResult":
            identifier, position = next(iter(pending.items()))
            raise ValueError("invalid_replay_transcript: OpenAI Responses replay contains "
                             f"dangling_tool_call toolCallId={identifier} at message index {position}")
        if role == "toolResult":
            identifier = _extract_tool_result_id(message)
            if not identifier or identifier not in pending:
                detail = f" toolCallId={identifier}" if identifier else ""
                raise ValueError("invalid_replay_transcript: OpenAI Responses replay contains "
                                 f"orphan_tool_result{detail} at message index {index}")
            del pending[identifier]
        elif role == "assistant":
            for identifier, _name in _extract_tool_calls_from_assistant(message):
                pending[identifier] = index
    if pending:
        identifier, position = next(iter(pending.items()))
        raise ValueError("invalid_replay_transcript: OpenAI Responses replay contains "
                         f"dangling_tool_call toolCallId={identifier} at message index {position}")
    return messages


class HistoryReplay:
    """One admitted turn's actual preparation and callback-stage observations."""

    def __init__(self, context, *, session_key, events, allowed_tool_names, now_ms, session_id=None):
        self.context = deepcopy(context)
        self.policy = resolve_history_replay_policy(context.model)
        self.now_ms = now_ms
        self.is_responses = context.model.api in _RESPONSES
        self.replay_identity = ReplayIdentity(session_id, context.forwarded_auth_profile_id,
                                              resolve_compaction_replay_eligibility(context.model))
        self.allowed_tool_names = tuple(allowed_tool_names)
        self.history_limit = get_history_limit_from_session_key(session_key, context.config, context.route)
        self.stages = []
        self.prepared = None
        last, switch = None, None
        for event in events:
            if event.get("type") != "custom" or event.get("customType") != "model-snapshot":
                continue
            data = event.get("data")
            if isinstance(data, Mapping):
                if last is not None and not _same_snapshot(last, data) and _finite(data.get("timestamp")):
                    switch = data["timestamp"]
                last = deepcopy(data)
        current = {"timestamp": now_ms, "provider": context.model.provider,
                   "modelApi": context.model.api, "modelId": context.model.id}
        changed = last is not None and not _same_snapshot(last, current)
        if changed:
            switch = now_ms
        self.snapshot_state = {"lastSnapshot": last, "latestSwitchTimestamp": switch,
                               "currentSnapshot": current, "modelChanged": changed}
        self.snapshot_to_append = current if last is None or changed else None

    def _stage(self, name, messages):
        self.stages.append({"stage": name, "messages": deepcopy(messages)})
        return messages

    def prepare(self, messages):
        if self.prepared is not None:
            raise RuntimeError("History was already prepared for this admitted prompt")
        source = normalize_assistant_replay_content(deepcopy(list(messages)))
        if self.policy.dropReasoningFromHistory:
            source = _drop_reasoning(source)
        source = sanitize_tool_call_inputs(source, allowed_tool_names=self.allowed_tool_names)
        source = sanitize_tool_use_result_pairing_for_model(source, self.is_responses, now_ms=self.now_ms)
        if self.is_responses:
            source = drop_stale_openai_reasoning(source, self.snapshot_state["latestSwitchTimestamp"])
            source = downgrade_openai_function_call_reasoning_pairs(normalize_openai_responses_tool_call_ids(source))
        else:
            source = sanitize_tool_call_ids(source, "strict", allowed_tool_names=self.allowed_tool_names)
        source = [{key: value for key, value in message.items() if key != "details"}
                  if message.get("role") == "toolResult" and "details" in message else message for message in source]
        source = _usage_snapshots(source)
        if self.is_responses:
            source = _assert_responses_pairs(sanitize_tool_use_result_pairing_for_model(
                source, True, now_ms=self.now_ms))
        if self.policy.applyGoogleTurnOrdering:
            source = sanitize_google_turn_ordering(source, now_ms=self.now_ms)
        self._stage("session:sanitized", source)
        if self.policy.validateGeminiTurns:
            source = validate_gemini_turns(source)
        if self.policy.validateAnthropicTurns:
            source = validate_anthropic_turns(source)
        self._stage("session:validated", source)
        source = preserve_compaction_replay_window(
            source, limit_history_turns(source, self.history_limit), self.context.model, self.replay_identity)
        source = sanitize_tool_use_result_pairing_for_model(source, self.is_responses, now_ms=self.now_ms)
        self.prepared = self._stage("session:limited", source)
        return deepcopy(self.prepared)

    def request(self, messages):
        """The native outer malformed-call guard and inner replay-ID guard."""
        report = sanitize_replay_tool_call_inputs(messages, self.allowed_tool_names)
        source = report.messages
        if self.is_responses:
            source = sanitize_tool_use_result_pairing_for_model(source, True, now_ms=self.now_ms)
        elif source is not messages:
            source = sanitize_tool_use_result_pairing(source, now_ms=self.now_ms)
        stripped = False
        if self.policy.validateAnthropicTurns:
            source = sanitize_anthropic_replay_tool_results(source)
        if self.policy.validateAnthropicTurns or self.policy.validateGeminiTurns:
            before = source
            source = strip_trailing_assistant_prefill_turns(source)
            stripped = source is not before
        if source is not messages and (report.dropped_assistant_messages > 0
                                      or self.policy.validateAnthropicTurns or stripped):
            if self.policy.validateGeminiTurns:
                source = validate_gemini_turns(source)
            if self.policy.validateAnthropicTurns:
                source = validate_anthropic_turns(source)
        self._stage("stream:malformed-tool-calls", source)
        if self.is_responses:
            source = sanitize_tool_use_result_pairing_for_model(source, True, now_ms=self.now_ms)
            source = downgrade_openai_function_call_reasoning_pairs(normalize_openai_responses_tool_call_ids(source))
        else:
            source = sanitize_tool_use_result_pairing(source, now_ms=self.now_ms)
            source = sanitize_tool_call_ids(source, "strict", allowed_tool_names=self.allowed_tool_names)
        if self.policy.dropReasoningFromHistory:
            source = _drop_reasoning(source)
        return self._stage("stream:context", source)


__all__ = ["HistoryReplayContext", "HistoryReplayPolicy", "resolve_history_replay_policy"]
