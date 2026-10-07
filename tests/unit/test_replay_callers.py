"""Offline tests of the replay decision callers (the oracle test covers them against the real TS)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from memory_core import attempt_preflight as pf
from memory_core import compaction_replay as cr
from memory_core import tool_result_context_guard as guard
from memory_core.preemptive_compaction import PREEMPTIVE_OVERFLOW_ERROR_TEXT

RESPONSES = cr.ReplayModel("openai", "openai-responses", "gpt-x", "https://api.openai.com/v1")
ANTHROPIC = cr.ReplayModel("anthropic", "anthropic-messages", "claude-x", "https://api.anthropic.com")


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text, "timestamp": 1}


def _tool_result(text: str) -> dict[str, Any]:
    return {
        "role": "toolResult",
        "toolCallId": "c1",
        "toolName": "read",
        "content": [{"type": "text", "text": text}],
        "isError": False,
        "timestamp": 1,
    }


def _attempt(**over: Any) -> pf.AttemptPromptPreflightAttempt:
    base: dict[str, Any] = {
        "provider": "openai",
        "model_id": "gpt-x",
        "model": RESPONSES,
        "session_id": "s1",
        "session_key": "main",
        "session_file": "/tmp/s.jsonl",
    }
    base.update(over)
    return pf.AttemptPromptPreflightAttempt(**base)


def _preflight(**over: Any) -> pf.AttemptPromptPreflightState:
    args: dict[str, Any] = {
        "attempt": _attempt(),
        "state": pf.AttemptPromptPreflightState(),
        "compaction_replay_enabled": True,
        "context_engine_assembly_succeeded": False,
        "context_engine_prompt_authority": "assembled",
        "context_token_budget": 10_000,
        "hook_messages_for_current_prompt": [_user("hi")],
        "prompt_for_precheck": "hello",
        "reserve_tokens": 500,
        "session_message_count": 1,
        "system_prompt": "sys",
        "tool_result_max_chars": None,
        "now": 1_700_000_000_000,
    }
    args.update(over)
    return pf.prepare_attempt_prompt_preflight(**args)


# --- the guard ----------------------------------------------------------------------------------


def test_guard_caps_tool_results_and_returns_the_same_list_when_nothing_changes():
    instance = guard.ToolResultContextGuard(context_window_tokens=1_000)
    small = [_user("hi"), _tool_result("ok")]
    assert instance.transform_context(small) is small
    big = [_user("hi"), _tool_result("x" * 50_000)]
    out = instance.transform_context(big)
    assert out is not big
    assert guard.estimate_message_chars(out[1]) <= instance.max_single_tool_result_chars
    assert out[0] is big[0]


def test_guard_raises_the_signal_only_for_a_tool_result_after_the_fence():
    seen: list[guard.MidTurnPrecheckRequest] = []
    options = guard.MidTurnPrecheckOptions(
        context_token_budget=2_000,
        reserve_tokens=lambda: 0,
        enabled=True,
        get_pre_prompt_message_count=lambda: 1,
        on_mid_turn_precheck=seen.append,
    )
    instance = guard.ToolResultContextGuard(context_window_tokens=200_000, mid_turn_precheck=options)
    history = [_user("go " * 5_000)]
    # No tool result past the fence: the oversized prompt is the provider's to refuse.
    assert instance.transform_context(history) is history
    with pytest.raises(guard.MidTurnPrecheckSignal) as raised:
        instance.transform_context([*history, _tool_result("data")])
    assert raised.value.request.route == "compact_only"
    assert seen == [raised.value.request]
    assert str(raised.value) == guard.MID_TURN_PRECHECK_ERROR_MESSAGE
    assert guard.is_mid_turn_precheck_signal(raised.value)


def test_guard_disabled_precheck_never_raises():
    options = guard.MidTurnPrecheckOptions(
        context_token_budget=10, reserve_tokens=lambda: 0, enabled=False
    )
    instance = guard.ToolResultContextGuard(context_window_tokens=1_000, mid_turn_precheck=options)
    messages = [_user("x" * 10_000), _tool_result("y" * 100)]
    assert instance.transform_context(messages) is messages


def test_guard_replay_is_read_per_check():
    calls: list[int] = []

    def get_replay() -> Any:
        calls.append(1)
        return None

    options = guard.MidTurnPrecheckOptions(
        context_token_budget=100_000,
        reserve_tokens=lambda: 0,
        enabled=True,
        get_replay=get_replay,
        get_pre_prompt_message_count=lambda: 0,
    )
    instance = guard.ToolResultContextGuard(context_window_tokens=100_000, mid_turn_precheck=options)
    instance.transform_context([_user("a"), _tool_result("b")])
    assert calls == [1]


def test_estimator_weights_cjk_images_and_unknown_blocks():
    assert guard.estimate_message_chars({"role": "user", "content": "abc"}) == 3
    result = {
        "role": "toolResult",
        "content": [{"type": "text", "text": "ab"}, {"type": "image"}, {"k": 1}],
    }
    # 2 chars at weight 2, one image, '{"k":1}' (7) at weight 2.
    assert guard.estimate_message_chars(result) == 4 + guard.TOOL_IMAGE_CHARS + 14
    assert guard.estimate_message_chars({"role": "user", "content": "x", "excludeFromContext": True}) == 0
    assert guard.estimate_message_chars({"role": "weird"}) == 256
    assert guard.resolve_tool_result_context_max_chars(10) == 1_024
    assert guard.format_context_limit_truncation_notice(0) == (
        "[... 1 more characters truncated; rerun with narrower args if needed]"
    )


def test_image_results_keep_what_fits_and_say_what_was_dropped():
    message = {
        "role": "toolResult",
        "toolCallId": "c",
        "toolName": "t",
        "content": [{"type": "image", "data": "A"} for _ in range(4)],
        "isError": False,
    }
    out = guard.truncate_tool_result_to_chars(message, guard.TOOL_IMAGE_CHARS * 2 + 600)
    images = [block for block in out["content"] if block["type"] == "image"]
    assert len(images) == 2
    assert out["content"][-1]["text"].startswith("[2 images omitted from context")
    assert guard.truncate_tool_result_to_chars({"role": "user", "content": "x" * 99_999}, 5) == {
        "role": "user",
        "content": "x" * 99_999,
    }


def test_assistant_error_marker_is_recognized():
    assert guard.is_mid_turn_precheck_assistant_error(
        {
            "role": "assistant",
            "stopReason": "error",
            "errorMessage": guard.MID_TURN_PRECHECK_ERROR_MESSAGE,
        }
    )
    assert not guard.is_mid_turn_precheck_assistant_error({"role": "assistant", "stopReason": "stop"})
    assert not guard.is_mid_turn_precheck_assistant_error(None)


# --- the preflight ------------------------------------------------------------------------------


def test_preflight_fitting_prompt_records_the_budget_and_logs_without_recovery():
    logs: list[tuple[str, str]] = []
    state = _preflight(log=lambda level, message: logs.append((level, message)))
    assert state.skip_prompt_submission is False
    assert state.preflight_recovery is None
    assert state.context_budget_status["source"] == "pre-prompt-estimate"
    assert state.context_budget_status["updatedAt"] == 1_700_000_000_000
    assert state.context_budget_status["sessionId"] == "s1"
    assert [level for level, _ in logs] == ["debug"]
    assert "sessionKey=main provider=openai/gpt-x route=fits" in logs[0][1]


def test_preflight_raw_history_overflow_is_diagnostic_only():
    logs: list[tuple[str, str]] = []
    state = _preflight(
        hook_messages_for_current_prompt=[_user("x" * 200_000)],
        log=lambda level, message: logs.append((level, message)),
    )
    assert state.skip_prompt_submission is False
    assert state.preflight_recovery is None
    assert state.context_budget_status["route"] == "compact_only"
    assert any("[context-pressure-diagnostic] admitted provider attempt" in m for _, m in logs)


def test_preflight_context_engine_owning_compaction_skips_the_precheck():
    logs: list[tuple[str, str]] = []
    state = _preflight(
        hook_messages_for_current_prompt=[_user("x" * 200_000)],
        context_engine_assembly_succeeded=True,
        active_context_engine=pf.ContextEngineInfo("lcm", owns_compaction=True),
        log=lambda level, message: logs.append((level, message)),
    )
    assert state.context_budget_status is None
    assert logs == [("info", '[context-overflow-precheck] skipped: context engine "lcm" owns compaction')]


def test_preflight_preassembly_may_overflow_needs_the_host_normalizer():
    with pytest.raises(TypeError):
        _preflight(
            context_engine_prompt_authority="preassembly_may_overflow",
            unwindowed_context_engine_messages_for_precheck=[_user("a")],
        )
    seen: list[dict[str, Any]] = []

    def normalize(messages: list[Any], options: dict[str, Any]) -> list[Any]:
        seen.append(options)
        return [*messages, _user("y" * 200_000)]

    state = _preflight(
        context_engine_prompt_authority="preassembly_may_overflow",
        unwindowed_context_engine_messages_for_precheck=[_user("a")],
        normalize_messages_for_llm_boundary=normalize,
        include_boundary_timestamp=False,
        timezone="UTC",
        append_only_runtime_context=True,
    )
    assert seen == [{"appendOnlyRuntimeContext": True, "timezone": "UTC", "includeTimestamp": False}]
    # The unwindowed maximum is the diagnostic; the outgoing window still fits.
    assert state.context_budget_status["route"] == "compact_only"
    assert state.context_budget_status["unwindowedMessageCount"] == 1
    assert state.preflight_recovery is None


def test_preflight_refresh_required_checkpoint_becomes_a_precheck_error():
    ctx = {
        key: value
        for key, value in cr.build_provider_replay_context(
            RESPONSES, cr.ReplayIdentity("s1", None)
        ).items()
        if value is not None  # a persisted state has no key for an absent hash
    }
    replay_state = {
        "v": 1,
        "type": "openai-responses-compaction",
        "data": "ENCRYPTED",
        "replayIndex": 1,
        **ctx,
        "compactedWindow": {"state": "refresh-required"},
    }
    owner = {
        "role": "assistant",
        "content": [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}],
        "api": "openai-responses",
        "provider": "openai",
        "model": "gpt-x",
        "usage": {"input": 1, "output": 1, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 2},
        "stopReason": "stop",
        "timestamp": 1,
        "providerReplay": replay_state,
    }
    state = _preflight(hook_messages_for_current_prompt=[_user("q"), owner, _user("t")])
    assert state.skip_prompt_submission is True
    assert state.prompt_error_source == "precheck"
    assert isinstance(state.prompt_error, cr.CompactionReplayRefreshRequiredError)
    assert state.preflight_recovery is None


def test_preflight_state_skip_flag_bypasses_the_decision():
    prior = pf.AttemptPromptPreflightState(
        context_budget_status={"old": 1}, skip_prompt_submission=True
    )
    state = _preflight(state=prior, hook_messages_for_current_prompt=[_user("x" * 200_000)])
    assert state == prior


def test_attempt_auth_profile_is_the_runtime_plan_forwarded_one_only():
    assert pf.resolve_attempt_stream_auth_profile_id(None) is None
    assert pf.resolve_attempt_stream_auth_profile_id({"auth": {}}) is None
    assert (
        pf.resolve_attempt_stream_auth_profile_id({"auth": {"forwardedAuthProfileId": "a1"}}) == "a1"
    )


# --- the mid-turn handler -----------------------------------------------------------------------


def _request(route: str) -> guard.MidTurnPrecheckRequest:
    return guard.MidTurnPrecheckRequest(route, 9_000, 8_000, 1_000, 40_000, 500)


def _truncation(truncated: bool, count: int = 0, reason: str | None = None) -> Any:
    return SimpleNamespace(truncated=truncated, truncated_count=count, reason=reason)


def test_handler_truncation_success_is_handled_and_replaces_the_session_messages():
    calls: list[tuple[Any, Any]] = []
    replaced: list[Any] = []
    logs: list[tuple[str, str]] = []
    outcome = pf.handle_attempt_mid_turn_precheck(
        attempt=_attempt(context_token_budget=100_000),
        request=_request("truncate_tool_results_only"),
        pre_prompt_message_count=4,
        truncate_tool_results=lambda window, max_chars: calls.append((window, max_chars))
        or _truncation(True, 2),
        build_session_context_messages=lambda: [_user("built")],
        sanitize_compaction_replay_messages=lambda messages: [*messages, _user("sanitized")],
        replace_session_messages=replaced.append,
        log=lambda level, message: logs.append((level, message)),
    )
    # 30 percent of the window, 4 chars per token, capped at the 32,000 live cap of a large window.
    assert calls == [(100_000, 32_000)]
    assert outcome.prompt_error is None
    assert outcome.preflight_recovery.to_dict() == {
        "route": "truncate_tool_results_only",
        "source": "mid-turn",
        "estimatedPromptTokens": 9_000,
        "promptBudgetBeforeReserve": 8_000,
        "overflowTokens": 1_000,
        "handled": True,
        "truncatedCount": 2,
    }
    assert replaced == [[_user("built"), _user("sanitized")]]
    assert logs[0][0] == "warn"
    assert "handled=true truncatedCount=2 sessionFile=/tmp/s.jsonl" in logs[0][1]
    assert "prePromptMessageCount=4" in logs[0][1]


def test_handler_nothing_to_truncate_retries_without_compaction():
    outcome = pf.handle_attempt_mid_turn_precheck(
        attempt=_attempt(),
        request=_request("truncate_tool_results_only"),
        pre_prompt_message_count=0,
        truncate_tool_results=lambda *_: _truncation(False, 0, pf.NO_OVERSIZED_TOOL_RESULTS_REASON),
    )
    assert outcome.prompt_error is None
    assert outcome.preflight_recovery.handled is True
    assert outcome.preflight_recovery.truncated_count == 0


def test_handler_failed_truncation_falls_back_to_compact_only():
    window: list[Any] = []
    outcome = pf.handle_attempt_mid_turn_precheck(
        attempt=_attempt(),
        request=_request("truncate_tool_results_only"),
        pre_prompt_message_count=0,
        truncate_tool_results=lambda w, _m: window.append(w) or _truncation(False, 0, "boom"),
    )
    assert window == [pf.DEFAULT_CONTEXT_TOKENS]
    assert outcome.preflight_recovery.route == "compact_only"
    assert outcome.preflight_recovery.source == "mid-turn"
    assert outcome.preflight_recovery.handled is None
    assert str(outcome.prompt_error) == PREEMPTIVE_OVERFLOW_ERROR_TEXT


@pytest.mark.parametrize("route", ["compact_only", "compact_then_truncate"])
def test_handler_compaction_routes_do_not_truncate(route: str):
    def fail(*_: Any) -> Any:
        raise AssertionError

    outcome = pf.handle_attempt_mid_turn_precheck(
        attempt=_attempt(),
        request=_request(route),
        pre_prompt_message_count=0,
        truncate_tool_results=fail,
    )
    assert outcome.preflight_recovery.route == route
    assert str(outcome.prompt_error) == PREEMPTIVE_OVERFLOW_ERROR_TEXT


# --- eligibility call sites ---------------------------------------------------------------------


def test_attempt_eligibility_follows_the_prepared_route():
    assert pf.resolve_attempt_compaction_replay_enabled(
        RESPONSES, effective_extra_params=None, transport_api_key=None
    )
    assert not pf.resolve_attempt_compaction_replay_enabled(
        ANTHROPIC, effective_extra_params={"anthropicServerCompaction": True}, transport_api_key=None
    )
    assert pf.resolve_attempt_compaction_replay_enabled(
        ANTHROPIC,
        effective_extra_params={"anthropicServerCompaction": True},
        transport_api_key="sk-ant-api03-abc",
        env={},
    )


def test_compaction_session_replay_shares_one_identity():
    session = pf.resolve_compaction_session_replay(
        ANTHROPIC,
        session_id="s1",
        forwarded_auth_profile_id="a1",
        extra_params={"anthropicServerCompaction": True},
        transport_api_key="sk-ant-api03-abc",
        env={},
    )
    assert session.enabled is True
    assert session.identity == cr.ReplayIdentity("s1", "a1", True)
    assert (session.pressure_context.session_id, session.pressure_context.auth_profile_id) == ("s1", "a1")
    assert session.pressure_context.enabled is True
    window = [_user("kept")]
    assert session.preserve_window([_user("a"), _user("kept")], window) is window
    assert session.estimate_server_compaction_tokens_after(messages=window, system_prompt="sys") > 0
    disabled = pf.resolve_compaction_session_replay(
        ANTHROPIC,
        session_id="s1",
        forwarded_auth_profile_id=None,
        extra_params=None,
        transport_api_key=None,
        env={},
    )
    assert disabled.enabled is False
