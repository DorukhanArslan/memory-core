"""Offline tests for the Responses converter and the pre-prompt decision's replay hand-off.

The oracle comparison (thousands of histories against the real TS) is in
tests/integration/test_openclaw_responses_converter_oracle.py and
tests/integration/test_openclaw_preemptive_replay_oracle.py; these pin shapes and the wiring that
need no oracle.
"""

from __future__ import annotations

from typing import Any

import pytest

from memory_core import compaction_replay as cr
from memory_core import preemptive_compaction as pc
from memory_core import responses_converter as rc
from memory_core import tool_result_text as trt
from memory_core import transcript_transform as tt

MODEL = cr.ReplayModel("openai", "openai-responses", "gpt-x", "https://api.openai.com/v1")
REASONING = cr.ReplayModel(
    "openai", "openai-responses", "gpt-r", "https://api.openai.com/v1", reasoning=True
)


def _assistant(content: Any, model: cr.ReplayModel = MODEL, **extra: Any) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": content,
        "provider": model.provider,
        "api": model.api,
        "model": model.id,
        "usage": {"input": 1, "output": 1, "totalTokens": 2},
        "stopReason": "stop",
        "timestamp": 1,
        **extra,
    }


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def test_user_assistant_and_system_prompt_shapes():
    messages = [
        {"role": "user", "content": "hello"},
        _assistant([_text("hi")]),
        {
            "role": "user",
            "content": [_text("x"), {"type": "image", "data": "QUJD", "mimeType": "image/png"}],
        },
    ]
    wire = rc.convert_responses_messages(REASONING, messages, "be nice")
    assert wire[0] == {
        "type": "message",
        "role": "developer",
        "content": [{"type": "input_text", "text": "be nice"}],
    }
    assert wire[1]["content"] == [{"type": "input_text", "text": "hello"}]
    assert wire[2] == {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "hi", "annotations": []}],
        "status": "completed",
        "id": "msg_1",
    }
    assert wire[3]["content"][1] == {
        "type": "input_image",
        "detail": "auto",
        "image_url": "data:image/png;base64,QUJD",
    }
    # A non-reasoning model gets a system message; no prompt, no message.
    assert rc.convert_responses_messages(MODEL, messages, "p")[0]["role"] == "system"
    assert rc.convert_responses_messages(MODEL, messages)[0]["role"] == "user"
    assert (
        rc.convert_responses_messages(MODEL, messages, "p", include_system_prompt=False)[0]["role"]
        == "user"
    )


def test_tool_calls_results_and_missing_result_repair():
    call = {"type": "toolCall", "id": "call_1|fc_1", "name": "read", "arguments": {"p": 1.5}}
    messages = [
        {"role": "user", "content": "go"},
        _assistant([call]),
        {
            "role": "toolResult",
            "toolCallId": "call_1|fc_1",
            "toolName": "read",
            "content": [_text("result")],
            "isError": False,
        },
        _assistant([{**call, "id": "call_2|fc_2"}]),
    ]
    wire = rc.convert_responses_messages(MODEL, messages)
    kinds = [item["type"] for item in wire]
    assert kinds == [
        "message",
        "function_call",
        "function_call_output",
        "function_call",
        "function_call_output",
    ]
    assert wire[1] == {
        "type": "function_call",
        "id": "fc_1",
        "call_id": "call_1",
        "name": "read",
        "arguments": '{"p":1.5}',
    }
    assert wire[2]["output"] == "result"
    assert wire[4]["output"] == "aborted"  # the Responses family's synthetic result text


def test_text_only_models_drop_or_placeholder_user_images():
    text_only = cr.ReplayModel("openai", "openai-responses", "t", None, ("text",))
    image = {"type": "image", "data": "QUJD", "mimeType": "image/png"}
    wire = rc.convert_responses_messages(
        text_only, [{"role": "user", "content": [_text("a"), image]}]
    )
    # The transport projection filters the image part out of the wire content.
    assert wire[0]["content"] == [{"type": "input_text", "text": "a"}]
    # The provider projection replaces it with the omission placeholder first.
    provider = rc.convert_provider_responses_messages(
        text_only, [{"role": "user", "content": [_text("a"), image]}]
    )
    assert provider[0]["content"] == [
        {"type": "input_text", "text": "a"},
        {"type": "input_text", "text": tt.NON_VISION_USER_IMAGE_PLACEHOLDER},
    ]


def test_reasoning_replay_fences_ciphertext_to_the_route():
    meta = cr.build_openai_responses_reasoning_replay_metadata(MODEL)
    mine = '{"type":"reasoning","id":"rs_1","encrypted_content":"ENC","__openclaw_replay":%s}' % (
        __import__("json").dumps(meta)
    )
    foreign = '{"type":"reasoning","id":"rs_2","encrypted_content":"ENC"}'
    messages = [
        {"role": "user", "content": "q"},
        _assistant(
            [
                {"type": "thinking", "thinking": "", "thinkingSignature": mine},
                {"type": "thinking", "thinking": "", "thinkingSignature": foreign},
                _text("a"),
            ]
        ),
    ]
    provider = rc.convert_provider_responses_messages(MODEL, messages)
    reasoning = [item for item in provider if item["type"] == "reasoning"]
    # The provider projection preserves unattributed ciphertext; the matching one too.
    assert [item.get("encrypted_content") for item in reasoning] == ["ENC", "ENC"]
    transport = rc.convert_responses_messages(MODEL, messages)
    # Transport style only replays object signatures and strips unattributed ciphertext.
    assert [item["id"] for item in transport if item["type"] == "reasoning"] == ["rs_1", "rs_2"]
    assert "encrypted_content" in next(i for i in transport if i.get("id") == "rs_1")
    assert "encrypted_content" not in next(i for i in transport if i.get("id") == "rs_2")


def test_transcript_transforms_drop_failed_turns_and_other_models_thinking():
    other = cr.ReplayModel("anthropic", "anthropic-messages", "claude-sonnet-4")
    messages = [
        {"role": "user", "content": "q"},
        _assistant([_text("partial")], MODEL, stopReason="aborted"),
        _assistant(
            [{"type": "thinking", "thinking": "hidden", "thinkingSignature": "sig"}, _text("a")],
            other,
        ),
    ]
    out = tt.transform_messages(messages, MODEL)
    assert out[1]["content"] == [{"type": "text", "text": tt.FAILED_ASSISTANT_REPLAY_TEXT}]
    assert out[2]["content"] == [
        {"type": "text", "text": "hidden"},
        {"type": "text", "text": "a"},
    ]


@pytest.mark.parametrize(
    ("source", "target", "mode"),
    [
        ("gpt-x", "gpt-y", "default"),
        ("claude-fable-5-1", "claude-fable-5-1", "preserve"),
        ("claude-sonnet-5", "claude-fable-5-1", "preserve"),
        ("claude-fable-5", "claude-fable-5-1", "preserve"),
        ("claude-opus-5", "claude-sonnet-5", "drop"),
        ("claude-sonnet-4", "claude-fable-5", "drop"),
    ],
)
def test_model_bound_thinking_replay_mode(source, target, mode):
    ref = {"provider": "anthropic", "api": "anthropic-messages"}
    assert (
        tt.resolve_model_bound_thinking_replay_mode(
            {**ref, "modelId": source}, {**ref, "modelId": target}
        )
        == mode
    )


def test_tool_result_text_blocks_and_structured_redaction():
    assert trt.extract_tool_result_text([_text("a"), _text("b")]) == "a\nb"
    assert trt.extract_tool_result_text([{"type": "image", "data": "x"}]) == ""
    structured = trt.extract_tool_result_text(
        [{"type": "json", "z": 1, "a": {"data": "https://x/y", "10": 1, "2": 2}}]
    )
    assert structured == '{"type":"json","z":1,"a":{"2":2,"10":1,"data":"https://x/y"}}'
    big = trt.extract_tool_result_text([{"type": "x", "v": "v" * 9000}])
    assert big.endswith("\n…(truncated)…")
    seen = trt.extract_tool_result_text(
        [{"type": "x", "v": "see data:image/png;base64,AAAA here"}], redact=lambda value: value
    )
    assert "[inline data URI: 21 chars]" in seen
    assert trt.sanitize_surrogates("a\ud83d b\U0001f600") == "a b\U0001f600"
    assert (
        trt.describe_tool_result_media_placeholder(
            [{"type": "image", "data": "x"}, {"type": "audio", "data": "y"}]
        )
        == "(see attached media)"
    )


def test_default_projector_binds_measured_usage_to_the_built_in_wire_input():
    """Round trip: the saved prefix hash of the built-in converter's own wire input binds."""

    identity = cr.ReplayIdentity()
    state = {"v": 1, "type": "openai-responses-compaction", "data": "ENC", "replayIndex": 1}
    state.update({k: v for k, v in cr.build_provider_replay_context(MODEL).items() if v})
    owner = _assistant([_text("A"), _text("B")], providerReplay=state)
    target = _assistant(
        [_text("answer")],
        usage={"contextUsage": {"state": "available", "promptTokens": 90, "totalTokens": 100}},
    )
    messages = [{"role": "user", "content": "q1"}, owner, {"role": "user", "content": "q2"}, target]
    tail = {"role": "user", "content": "later"}
    wire = rc.convert_responses_messages(
        MODEL, [*messages, tail], None, include_system_prompt=False
    )
    prefix = rc.convert_responses_messages(MODEL, messages, None, include_system_prompt=False)
    target["openclawResponsesInputReplay"] = {
        "contextUsage": {
            **{k: v for k, v in cr.build_provider_replay_context(MODEL).items() if v},
            "projection": "transport",
            "includeSystemPrompt": False,
            "prefixHash": cr.responses_context_fingerprint(prefix),
            "prefixLength": len(prefix),
            "promptTokens": 90,
            "totalTokens": 100,
        }
    }
    boundary = cr.resolve_responses_context_usage_boundary([*messages, tail], MODEL, identity, None)
    assert boundary is not None
    assert boundary["totalTokens"] == 100
    assert boundary["suffix"] == wire[len(prefix) :]
    out = cr.resolve_compaction_replay_pressure(
        [*messages, tail], MODEL, identity, cr.default_replay_pressure_estimator()
    )
    assert out is not None and out["measuredTokens"] == 100 and out["messages"] == []


def _anthropic_owner(summary: str) -> dict[str, Any]:
    model = cr.ReplayModel(
        "anthropic", "anthropic-messages", "claude-x", "https://api.anthropic.com"
    )
    state = {"v": 1, "type": "anthropic-compaction", "data": summary, "replayIndex": 1}
    state.update({k: v for k, v in cr.build_provider_replay_context(model).items() if v})
    return _assistant([_text("old"), _text("new")], model, providerReplay=state)


def test_preemptive_decision_uses_the_checkpoint_window_and_reports_the_outgoing_budget():
    model = cr.ReplayModel(
        "anthropic", "anthropic-messages", "claude-x", "https://api.anthropic.com"
    )
    history = [
        {"role": "user", "content": "x " * 20_000},
        _anthropic_owner("short summary"),
        {"role": "user", "content": "next"},
    ]
    common = {
        "messages": history,
        "prompt": "hi",
        "context_token_budget": 2_000,
        "reserve_tokens": 100,
    }
    without = pc.should_preemptively_compact_before_prompt(**common)
    assert without.compaction_replay is None and without.route == "compact_only"
    with_replay = pc.should_preemptively_compact_before_prompt(
        **common, replay=pc.CompactionReplayPressureContext(model, enabled=True)
    )
    outgoing = with_replay.compaction_replay
    assert outgoing is not None
    assert outgoing.pressure_source == "provider_compaction_estimate"
    assert outgoing.route == "fits"
    assert outgoing.estimated_prompt_tokens < without.estimated_prompt_tokens
    # Disabled server compaction ignores the checkpoint.
    ignored = pc.should_preemptively_compact_before_prompt(
        **common, replay=pc.CompactionReplayPressureContext(model, enabled=None)
    )
    assert ignored.compaction_replay is None


def test_preemptive_decision_measured_usage_tool_schema_and_boundary_pressure():
    measured = {
        "role": "assistant",
        "content": "a",
        "usage": {"contextUsage": {"state": "available", "promptTokens": 800, "totalTokens": 900}},
    }
    base = {"prompt": "p", "context_token_budget": 10_000, "reserve_tokens": 0}
    plain = pc.should_preemptively_compact_before_prompt(
        messages=[{"role": "user", "content": "q"}, measured], **base
    )
    assert plain.pressure_source == "provider_context_usage"
    assert plain.estimated_prompt_tokens == 900 + pc.math.ceil(
        pc.estimate_rendered_prompt_tokens(prompt="p") * pc.SAFETY_MARGIN
    )
    schema = pc.should_preemptively_compact_before_prompt(
        messages=[{"role": "user", "content": "q"}, measured], tool_schema_tokens=50, **base
    )
    # No replay: the measured total already covers the definitions.
    assert schema.estimated_prompt_tokens == plain.estimated_prompt_tokens
    unmeasured = pc.should_preemptively_compact_before_prompt(
        messages=[{"role": "user", "content": "q"}], tool_schema_tokens=50, **base
    )
    assert unmeasured.pressure_source == "transcript_estimate"
    assert (
        unmeasured.estimated_prompt_tokens
        == pc.estimate_pre_prompt_tokens(messages=[{"role": "user", "content": "q"}], prompt="p")
        + 50
    )
    rendered = pc.should_preemptively_compact_before_prompt(
        messages=[{"role": "user", "content": "q" * 100_000}],
        llm_boundary_token_pressure=pc.LlmBoundaryTokenPressure(123.2, " rendered "),
        **base,
    )
    assert (rendered.pressure_source, rendered.estimated_prompt_tokens) == ("rendered", 124)
    # The reserve is capped at a quarter of the window.
    capped = pc.should_preemptively_compact_before_prompt(
        messages=[], prompt="p", context_token_budget=1_000, reserve_tokens=900
    )
    assert capped.effective_reserve_tokens == 250 and capped.prompt_budget_before_reserve == 750


def test_checkpoint_needing_refresh_propagates_from_the_decision():
    state = {"v": 1, "type": "openai-responses-retained-compaction", "data": "ENC"}
    state.update({k: v for k, v in cr.build_provider_replay_context(MODEL).items() if v})
    owner = _assistant([_text("a")], providerReplay=state)
    with pytest.raises(cr.CompactionReplayRefreshRequiredError):
        pc.should_preemptively_compact_before_prompt(
            messages=[owner],
            prompt="p",
            context_token_budget=10_000,
            reserve_tokens=0,
            replay=pc.CompactionReplayPressureContext(MODEL),
        )
