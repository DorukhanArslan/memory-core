"""Offline tests for the compaction replay writers, egress hook, eligibility and pressure.

The oracle comparison lives in tests/integration/test_openclaw_compaction_checkpoint_oracle.py;
these pin what it cannot reach (host hooks, the number formatter used by the usage fingerprint)
and the override semantics of the optional hooks.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from memory_core import compaction_replay as cr
from memory_core.inline_image import (
    canonicalize_base64,
    sanitize_inline_image_data_url,
    sanitize_inline_image_data_url_for_storage,
)
from memory_core.js_url import url_hostname

MODEL = cr.ReplayModel("openai", "openai-responses", "gpt-x", "https://api.openai.com/v1")
PROXY = cr.ReplayModel("custom", "openai-responses", "gpt-x", "https://proxy.example/v1")
ANTHROPIC = cr.ReplayModel(
    "anthropic", "anthropic-messages", "claude-x", "https://api.anthropic.com"
)
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def _window(*, status: str | None = None, url: str | None = None) -> list[Any]:
    content: list[Any] = [{"type": "input_text", "text": "hi"}]
    if url is not None:
        content.append({"type": "input_image", "detail": "auto", "image_url": url})
    message: dict[str, Any] = {"type": "message", "role": "user", "content": content}
    if status:
        message["status"] = status
    return [message, {"type": "compaction", "encrypted_content": "ENC"}]


def _replay(window: list[Any]) -> dict[str, Any]:
    return {"data": "ENC", "compactedWindow": {"state": "ready", "output": json.dumps(window)}}


def test_builtin_projection_keeps_native_routes_and_strips_status_on_proxies():
    window = _window(status="completed", url=PNG)
    assert cr.read_openai_responses_compaction_window(_replay(window), MODEL) == window
    assert cr.read_openai_responses_compaction_window(_replay(window), PROXY) is None
    # Without a model only the image sanitiser runs.
    assert cr.read_openai_responses_compaction_window(_replay(window)) == window


def test_builtin_projection_rejects_images_the_sanitiser_rewrites():
    relabeled = _window(url=PNG.replace("image/png", "image/jpeg"))
    bmp = _window(url="data:image/bmp;base64,Qk0AAAAAAAA=")
    assert cr.read_openai_responses_compaction_window(_replay(relabeled), MODEL) is None
    assert cr.read_openai_responses_compaction_window(_replay(bmp), MODEL) is None
    assert cr.read_openai_responses_compaction_window(_replay(_window(url=PNG)), MODEL)


def test_egress_projection_hook_overrides_the_builtin():
    window = _window(status="completed")
    seen: list[Any] = []

    def identity(value: list[Any]) -> Any:
        seen.append(value)
        return value

    assert cr.read_openai_responses_compaction_window(_replay(window), PROXY, identity) == window
    assert seen
    assert (
        cr.read_openai_responses_compaction_window(_replay(window), MODEL, lambda value: value[:1])
        is None
    )


def test_image_sanitiser_basics():
    assert sanitize_inline_image_data_url(PNG) == PNG
    assert sanitize_inline_image_data_url("https://x/y.png") == "https://x/y.png"
    assert sanitize_inline_image_data_url("data:image/png;base64,") is None
    assert sanitize_inline_image_data_url("data:image/bmp;base64,Qk0AAAAAAAA=") is None
    assert sanitize_inline_image_data_url_for_storage("data:image/bmp;base64,Qk0AAAAAAAA=")
    assert canonicalize_base64(" QUJD\n") == "QUJD"
    assert canonicalize_base64("QUJDRA") == "QUJDRA=="
    assert canonicalize_base64("QUJDRB==") is None


def test_url_hostname_follows_the_whatwg_parser():
    assert url_hostname("https://User:pw@API.OpenAI.com:8443/v1") == "api.openai.com"
    assert url_hostname("api.openai.com/v1") is None
    assert url_hostname("api.openai.com:443/v1") == ""
    assert url_hostname("https://0x7f.1/") == "127.0.0.1"
    assert url_hostname("https://[2001:db8:0:0:1:0:0:1]/") == "[2001:db8::1:0:0:1]"
    assert url_hostname("https://ß.de") == "xn--zca.de"
    assert url_hostname("https://a b/") is None


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (1, "1"),
        (1.0, "1"),
        (1.5, "1.5"),
        (0.000001, "0.000001"),
        (1e-7, "1e-7"),
        (1.5e-7, "1.5e-7"),
        (1e21, "1e+21"),
        (123456789012345680000.0, "123456789012345680000"),
        (1e16, "10000000000000000"),
        (-0.5, "-0.5"),
        (0.1 + 0.2, "0.30000000000000004"),
    ],
)
def test_number_formatter_matches_ecmascript(value, text):
    assert cr._js_number_to_string(value) == text


def test_stable_stringify_sorts_keys_by_utf16_code_unit():
    value = {"￿": 1, "\U00010000": 2, "b": [True, None, 1.0, "x"], "a": {}}
    assert cr._stable_stringify(value) == ('{"a":{},"b":[true,null,1,"x"],"\U00010000":2,"￿":1}')


def test_anthropic_eligibility_hooks():
    params = {"anthropicServerCompaction": True}
    kwargs = {"extra_params": params, "api_key": "sk-ant-api03-x", "env": {}}
    assert cr.resolve_compaction_replay_eligibility(ANTHROPIC, **kwargs)
    proxy = cr.ReplayModel("anthropic", "anthropic-messages", "c", "https://proxy.example")
    assert not cr.resolve_compaction_replay_eligibility(proxy, **kwargs)
    # A plugin manifest can classify more hosts as the public endpoint.
    assert cr.resolve_compaction_replay_eligibility(
        proxy, **kwargs, endpoint_class=lambda _url: "anthropic-public"
    )
    # A sentinel is swapped before the OAuth check.
    oauth = {**kwargs, "api_key": "sentinel"}
    assert cr.resolve_compaction_replay_eligibility(ANTHROPIC, **oauth)
    assert not cr.resolve_compaction_replay_eligibility(
        ANTHROPIC, **oauth, resolve_secret_sentinel=lambda _v: "sk-ant-oat01-secret"
    )
    # ANTHROPIC_BASE_URL is the fallback endpoint.
    bare = cr.ReplayModel("anthropic", "anthropic-messages", "c", None)
    assert cr.resolve_compaction_replay_eligibility(bare, **kwargs)
    assert not cr.resolve_compaction_replay_eligibility(
        bare, **{**kwargs, "env": {"ANTHROPIC_BASE_URL": "https://proxy.example"}}
    )
    with pytest.raises(TypeError):
        cr.resolve_compaction_replay_eligibility(ANTHROPIC, extra_params=params, api_key=5)  # type: ignore[arg-type]


def test_responses_apis_are_always_eligible():
    assert cr.resolve_compaction_replay_eligibility(MODEL)
    assert not cr.resolve_compaction_replay_eligibility(
        cr.ReplayModel("openai", "openai-completions", "m", None)
    )


def _state(model: cr.ReplayModel, **over: Any) -> dict[str, Any]:
    context = cr.build_provider_replay_context(model)
    return {
        "v": 1,
        "type": "openai-responses-compaction",
        "data": "ENC",
        "replayIndex": 1,
        **{k: v for k, v in context.items() if v is not None},
        **over,
    }


def _assistant(text: str, **extra: Any) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [{"type": "text", "text": text}, {"type": "text", "text": text + "2"}],
        "provider": MODEL.provider,
        "api": MODEL.api,
        "model": MODEL.id,
        "usage": {"input": 1},
        **extra,
    }


def test_measured_usage_boundary_uses_the_projector_and_the_fingerprint():
    wire = [
        {"type": "compaction", "encrypted_content": "ENC"},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "q"}]},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "tail"}]},
    ]
    context = cr.build_provider_replay_context(MODEL)
    usage_state = {
        **{k: v for k, v in context.items() if v is not None},
        "projection": "transport",
        "includeSystemPrompt": False,
        "prefixHash": cr.responses_context_fingerprint(wire[:2]),
        "prefixLength": 2,
        "promptTokens": 90,
        "totalTokens": 100,
    }
    target = _assistant(
        "t",
        usage={"contextUsage": {"state": "available", "promptTokens": 90, "totalTokens": 100}},
        openclawResponsesInputReplay={"contextUsage": usage_state},
    )
    messages = [
        {"role": "user", "content": "q"},
        _assistant("o", providerReplay=_state(MODEL)),
        target,
    ]
    calls: list[tuple[Any, ...]] = []

    def projector(projection, msgs, system_prompt, include):
        calls.append((projection, len(msgs), system_prompt, include))
        return wire

    identity = cr.ReplayIdentity()
    estimator = cr.default_replay_pressure_estimator()
    out = cr.resolve_compaction_replay_pressure(
        messages, MODEL, identity, estimator, "sys", projector=projector
    )
    assert out is not None
    assert out["messages"] == []
    assert out["measuredTokens"] == 100
    assert out["prefixTokens"] == 100 + cr.estimate_responses_input(wire[2:], estimator)
    assert calls == [("transport", 3, "sys", False)]
    # A tampered fingerprint falls back to the estimate; no projector is an error.
    usage_state["prefixHash"] = "0" * 64
    fallback = cr.resolve_compaction_replay_pressure(
        messages, MODEL, identity, estimator, projector=projector
    )
    assert fallback is not None and "measuredTokens" not in fallback
    usage_state["prefixHash"] = cr.responses_context_fingerprint(wire[:2])
    with pytest.raises(cr.ResponsesProjectionUnavailableError):
        cr.resolve_compaction_replay_pressure(messages, MODEL, identity, estimator)


def test_default_estimator_counts_an_undefined_content_as_one_token():
    estimator = cr.default_replay_pressure_estimator()
    assert estimator.json(cr.UNDEFINED) == 1
    assert cr.estimate_responses_input([{"type": "message"}], estimator) == (
        estimator.json({"type": "message"}) + 1
    )


def test_capture_and_tracker_round_trip():
    output: dict[str, Any] = {}
    capture = cr.CompactionCapture(output, ANTHROPIC)
    assert capture.begin(0, {"type": "compaction", "content": "S"}, 2)
    assert capture.delta(
        0, {"type": "compaction_delta", "content": "UM", "encrypted_content": None}
    )
    assert capture.complete(0)
    assert output["providerReplay"]["data"] == "SUM"
    assert output["providerReplay"]["encryptedContent"] is None
    assert output["providerReplay"]["replayIndex"] == 2
    assert not capture.complete(0)
    cr.suppress_anthropic_compaction(output, ANTHROPIC)
    assert output["providerReplay"]["type"] == "anthropic-compaction-suppression"

    responses: dict[str, Any] = {}
    tracker = cr.CompactionTracker(responses, MODEL)
    tracker.added({"type": "compaction", "id": "rs_1"}, 3)
    tracker.completed({"type": "compaction", "id": "rs_1", "encrypted_content": "ENC"}, 9)
    assert responses["providerReplay"]["replayIndex"] == 3
    assert responses["providerReplay"]["id"] == "rs_1"
    rejected: list[Any] = []
    cr.suppress_openai_responses_compaction(responses, MODEL, None, {"why": 1}, rejected.append)
    assert rejected == [{"why": 1}]
    assert responses["providerReplay"]["type"] == "openai-responses-compaction-suppression"


def test_capture_validates_the_compacted_output():
    output: dict[str, Any] = {}
    item = {"type": "compaction", "encrypted_content": "ENC"}
    cr.capture_openai_responses_compaction(output, item, 1, MODEL, None, _window())
    assert json.loads(output["providerReplay"]["compactedWindow"]["output"]) == _window()
    with pytest.raises(cr.ResponsesCompactionCaptureError):
        cr.capture_openai_responses_compaction(
            {}, item, 1, PROXY, None, _window(status="completed")
        )
    with pytest.raises(cr.ResponsesCompactionCaptureError):
        cr.capture_openai_responses_compaction({}, {**item, "id": "x"}, 1, MODEL, None, _window())
