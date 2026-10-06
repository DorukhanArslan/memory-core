"""Cache-TTL provider hook and call-site wiring (memory_core/cache_ttl.py).

The provider plugin hook and the ``attempt-setup.ts`` transform are not reachable from the oracle
(no plugin can be registered from the runner; the transform is built inline in the attempt
installer), so they are ported from source and checked here. The pruning itself, the eligibility
rules and the marker are compared with the real TypeScript in
``tests/integration/test_openclaw_cache_ttl_oracle.py`` and ``..._tool_result_projection_oracle.py``.
"""

from __future__ import annotations

from typing import Any

from memory_core import tool_result_projection as projection
from memory_core.cache_ttl import (
    CacheTtlContextTransform,
    append_attempt_cache_ttl_if_needed,
    install_cache_ttl_context_transform,
    is_cache_ttl_eligible_provider,
    resolve_attempt_cache_ttl_settings,
)

CONFIG = {
    "agents": {
        "defaults": {"contextPruning": {"mode": "cache-ttl", "ttl": "5m"}},
    }
}


def test_plugin_hook_decides_before_the_core_rules():
    seen: list[dict[str, Any]] = []

    def hook(context: dict[str, Any]) -> bool | None:
        seen.append(context)
        return {"proxy": True, "anthropic": False}.get(context["provider"])

    route = {"baseUrl": "https://proxy.example", "supportsPromptCacheKey": True}
    # The plugin overrides in both directions and receives the normalized context.
    assert is_cache_ttl_eligible_provider(" Proxy ", " GPT-5 ", "openai-responses", route, provider_hook=hook)
    assert not is_cache_ttl_eligible_provider("anthropic", "claude", "anthropic-messages", provider_hook=hook)
    assert seen[0] == {
        "provider": "proxy",
        "modelId": "gpt-5",
        "modelApi": "openai-responses",
        "baseUrl": "https://proxy.example",
        "supportsPromptCacheKey": True,
    }
    assert seen[1] == {"provider": "anthropic", "modelId": "claude", "modelApi": "anthropic-messages"}
    # ``None`` falls back to the core rules.
    assert is_cache_ttl_eligible_provider("amazon-bedrock", "us.anthropic.claude-x", provider_hook=lambda _c: None)
    assert not is_cache_ttl_eligible_provider("openai", "gpt-5", provider_hook=lambda _c: None)
    # A falsy but defined answer still wins.
    assert not is_cache_ttl_eligible_provider("kilocode", "anthropic/claude", provider_hook=lambda _c: False)
    assert is_cache_ttl_eligible_provider("kilocode", "anthropic/claude", provider_hook=lambda _c: None)


def test_settings_gate_checks_mode_before_the_provider():
    calls: list[str] = []

    def eligible(provider: str, *_rest: Any) -> bool:
        calls.append(provider)
        return provider == "anthropic"

    off = {"agents": {"defaults": {"contextPruning": {"mode": "off"}}}}
    assert resolve_attempt_cache_ttl_settings(config=off, provider="anthropic", model_id="c", is_eligible=eligible) is None
    assert resolve_attempt_cache_ttl_settings(config=None, provider="anthropic", model_id="c", is_eligible=eligible) is None
    assert calls == [], "disabled pruning must not resolve the provider"
    assert resolve_attempt_cache_ttl_settings(config=CONFIG, provider="openai", model_id="g", is_eligible=eligible) is None
    settings = resolve_attempt_cache_ttl_settings(config=CONFIG, provider="anthropic", model_id="c", is_eligible=eligible)
    assert settings is not None and settings.ttl_ms == 300_000


def _conversation() -> list[dict[str, Any]]:
    text = "alpha beta gamma delta\n" * 500
    messages: list[dict[str, Any]] = [{"role": "user", "content": "go"}]
    for index in range(4):
        messages.append({"role": "assistant", "content": [{"type": "text", "text": f"round {index}"}]})
        messages.append(
            {
                "role": "toolResult",
                "toolName": "read",
                "toolCallId": f"c{index}",
                "isError": False,
                "timestamp": 100 + index,
                "content": [{"type": "text", "text": text}],
            }
        )
    messages += [
        {"role": "assistant", "content": [{"type": "text", "text": "a"}]},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": [{"type": "text", "text": "b"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "c"}]},
    ]
    return messages


def _install(entries: Any, **overrides: Any) -> tuple[CacheTtlContextTransform, list[int]]:
    clock = [1_000 + 600_000]
    transform = install_cache_ttl_context_transform(
        config=CONFIG,
        provider="anthropic",
        model_id="claude",
        model_api="anthropic-messages",
        model_route=None,
        context_window_tokens=8_000,
        projection_state=projection.create_tool_result_prompt_projection_state(),
        session_entries=entries,
        clock_ms=lambda: clock[0],
        **overrides,
    )
    assert transform is not None
    return transform, clock


def _marker(timestamp: int, provider: str = "anthropic", model_id: str = "claude") -> dict[str, Any]:
    return {
        "type": "custom",
        "customType": "openclaw.cache-ttl",
        "data": {"timestamp": timestamp, "provider": provider, "modelId": model_id},
    }


def test_transform_prunes_after_the_ttl_and_moves_the_cache_touch():
    transform, clock = _install([_marker(1_000), _marker(5_000, "openai", "gpt")])
    assert transform.last_cache_touch_at == 1_000, "only a matching marker seeds the touch time"
    messages = _conversation()
    out = transform(messages)
    assert out is not messages and any(a is not b for a, b in zip(out, messages, strict=True))
    assert transform.last_cache_touch_at == clock[0], "a prune is a cache touch"
    assert transform.projection_state.frozen, "pruned results are frozen for replay"
    # Within the TTL of the new touch, nothing new is pruned but the frozen bytes replay.
    again = transform(messages)
    assert again == out


def test_transform_without_a_touch_or_within_ttl_leaves_messages_alone():
    transform, _clock = _install([])
    assert transform.last_cache_touch_at is None
    messages = _conversation()
    assert transform(messages) is messages
    transform.record_cache_touch(1_000 + 599_000)
    assert transform(messages) is messages
    transform.record_cache_touch(1_000)
    assert transform(messages) is not messages


def test_server_side_clearing_stops_new_rounds_only():
    flag = [True]
    transform, _clock = _install([_marker(1_000)], server_tool_clearing_enabled=lambda: flag[0])
    messages = _conversation()
    assert transform(messages) is messages, "server clearing owns new rounds"
    flag[0] = False
    pruned = transform(messages)
    assert pruned is not messages
    flag[0] = True
    assert transform(messages) == pruned, "earlier client projections still replay"


def test_transform_composes_after_the_previous_transform():
    marker = [_marker(1_000)]

    def previous(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return messages[:-1]

    transform, _clock = _install(marker, previous_transform=previous)
    messages = _conversation()
    out = transform(messages)
    assert len(out) == len(messages) - 1
    # A previous transform that returns something other than a list falls back to the input.
    transform_bad, _ = _install(marker, previous_transform=lambda _m: None)  # type: ignore[arg-type,return-value]
    assert len(transform_bad(messages)) == len(messages)


def test_no_transform_when_pruning_is_off_or_provider_ineligible():
    for config, provider in (({}, "anthropic"), (CONFIG, "openai")):
        assert (
            install_cache_ttl_context_transform(
                config=config,
                provider=provider,
                model_id="m",
                model_api=None,
                model_route=None,
                context_window_tokens=8_000,
                projection_state=projection.create_tool_result_prompt_projection_state(),
                session_entries=[],
            )
            is None
        )


def test_marker_append_uses_the_hook_through_is_eligible():
    state = projection.create_tool_result_prompt_projection_state()
    entries: list[tuple[str, Any]] = []

    def eligible(provider: str, model_id: str, model_api: Any, route: Any) -> bool:
        return is_cache_ttl_eligible_provider(
            provider, model_id, model_api, route, provider_hook=lambda c: c["provider"] == "proxy" or None
        )

    for provider, expected in (("proxy", True), ("openai", False)):
        assert (
            append_attempt_cache_ttl_if_needed(
                append_custom_entry=lambda t, d: entries.append((t, d)),
                timed_out_during_compaction=False,
                compaction_occurred_this_attempt=False,
                config=CONFIG,
                provider=provider,
                model_id="m",
                tool_result_prompt_projection_state=state,
                is_eligible=eligible,
                now=42,
            )
            is expected
        )
    assert entries == [("openclaw.cache-ttl", {"timestamp": 42, "provider": "proxy", "modelId": "m", **projection.serialize_cache_ttl_tool_result_projections(state)})]
