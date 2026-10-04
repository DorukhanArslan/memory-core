from memory_core.runtime_context_prompt import (
    OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    append_current_inbound_context,
    build_current_inbound_prompt,
    build_runtime_context_custom_message,
    prepend_runtime_context_for_model,
    resolve_runtime_context_prompt_parts,
)

_FRAGMENT = {"kind": "runtime-instruction", "text": "secret runtime context"}


def test_default_runtime_context_identity_uses_memory_core_names():
    message = build_runtime_context_custom_message("secret runtime context", [_FRAGMENT])

    assert message is not None
    assert message["customType"] == "memory_core.runtime-context"
    assert message["details"] == {
        "source": "memory-core-runtime-context",
        "runtimeContextCarrier": True,
        "fragments": [_FRAGMENT],
    }
    assert message["content"] == (
        "<<<BEGIN_MEMORY_CORE_INTERNAL_CONTEXT>>>\nsecret runtime context\n"
        "<<<END_MEMORY_CORE_INTERNAL_CONTEXT>>>"
    )


def test_openclaw_compat_runtime_context_identity_preserves_upstream_names():
    message = build_runtime_context_custom_message(
        "secret runtime context",
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )

    assert message is not None
    assert message["customType"] == "openclaw.runtime-context"
    assert message["details"] == {
        "source": "openclaw-runtime-context",
        "runtimeContextCarrier": True,
    }
    assert message["display"] is False
    assert isinstance(message["timestamp"], int)


def test_resolve_runtime_context_prompt_parts_uses_explicit_fragments_only():
    # Delimited text inside the prompt is never interpreted as provenance.
    effective = (
        "visible ask\n\n<<<BEGIN_MEMORY_CORE_INTERNAL_CONTEXT>>>\nx\n"
        "<<<END_MEMORY_CORE_INTERNAL_CONTEXT>>>"
    )
    assert resolve_runtime_context_prompt_parts(
        effective_prompt=effective, transcript_prompt="visible ask"
    ) == {"prompt": "visible ask", "modelPrompt": effective}
    assert resolve_runtime_context_prompt_parts(
        effective_prompt="visible ask\n\nsecret runtime context",
        transcript_prompt="visible ask",
        fragments=[_FRAGMENT, {"kind": "conversation-data", "text": " "}],
    ) == {
        "prompt": "visible ask",
        "modelPrompt": "visible ask\n\nsecret runtime context",
        "runtimeContext": "secret runtime context",
    }


def test_resolve_runtime_context_prompt_parts_uses_marker_prompt_for_runtime_only_events():
    assert resolve_runtime_context_prompt_parts(
        effective_prompt="internal event",
        transcript_prompt="",
        fragments=[{"kind": "heartbeat-outcome", "text": "internal event"}],
    ) == {
        "prompt": "Continue the memory-core runtime event.",
        "modelPrompt": "internal event",
        "runtimeContext": "internal event",
        "runtimeOnly": True,
    }
    assert resolve_runtime_context_prompt_parts(
        effective_prompt="",
        fragments=[_FRAGMENT],
        allow_runtime_only=False,
    ) == {"prompt": "", "runtimeContext": "secret runtime context"}


def test_build_current_inbound_prompt_joins_context_and_prompt():
    context = {"text": "Current message:\n#34975 obviyus:", "promptJoiner": " ", "resumableText": "r"}
    assert (
        build_current_inbound_prompt(context=context, prompt="What do you mean hidden?")
        == "Current message:\n#34975 obviyus: What do you mean hidden?"
    )
    assert (
        build_current_inbound_prompt(context=context, prompt="ask", prefer_resumable_text=True)
        == "r ask"
    )
    assert build_current_inbound_prompt(context=None, prompt="ask") == "ask"
    assert build_current_inbound_prompt(context={"text": "ctx"}, prompt="") == "ctx"


def test_append_current_inbound_context_keeps_both_projections():
    out = append_current_inbound_context({"text": "full", "resumableText": "resumed"}, [_FRAGMENT])
    assert out == {
        "text": "full\n\nsecret runtime context",
        "resumableText": "resumed\n\nsecret runtime context",
        "fragments": [{"kind": "conversation-data", "text": "full"}, _FRAGMENT],
    }


def test_prepend_runtime_context_for_model_extends_or_creates_the_carrier():
    created = prepend_runtime_context_for_model(
        [{"role": "user", "content": "hi", "timestamp": 3}], "ctx"
    )
    assert created[-1]["runtimeContextCarrier"] is True
    assert created[-1]["timestamp"] == 3
    assert created[-1]["content"].startswith("<<<BEGIN_MEMORY_CORE_INTERNAL_CONTEXT>>>\nctx")
    again = prepend_runtime_context_for_model(created, "more")
    assert len(again) == 2
    assert again[-1]["content"].splitlines()[1:3] == ["more", ""]
    assert prepend_runtime_context_for_model(created, "  ") is created
