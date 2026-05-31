from memory_core.runtime_context_prompt import (
    OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    build_current_inbound_prompt,
    build_runtime_context_custom_message,
    resolve_runtime_context_prompt_parts,
)


def test_default_runtime_context_identity_uses_memory_core_names():
    message = build_runtime_context_custom_message("secret runtime context")

    assert message is not None
    assert message["customType"] == "memory_core.runtime-context"
    assert message["details"] == {"source": "memory-core-runtime-context"}
    assert "memory-core runtime context for the immediately preceding user message." in message["content"]


def test_openclaw_compat_runtime_context_identity_preserves_upstream_names():
    message = build_runtime_context_custom_message(
        "secret runtime context",
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )

    assert message is not None
    assert message["customType"] == "openclaw.runtime-context"
    assert message["details"] == {"source": "openclaw-runtime-context"}
    assert "OpenClaw runtime context for the immediately preceding user message." in message["content"]


def test_resolve_runtime_context_prompt_parts_moves_hidden_context_out_of_visible_prompt():
    effective_prompt = "\n".join(
        [
            "visible ask",
            "",
            "<<<BEGIN_MEMORY_CORE_INTERNAL_CONTEXT>>>",
            "secret runtime context",
            "<<<END_MEMORY_CORE_INTERNAL_CONTEXT>>>",
        ]
    )

    assert resolve_runtime_context_prompt_parts(
        effective_prompt=effective_prompt,
        transcript_prompt="visible ask",
    ) == {
        "prompt": "visible ask",
        "runtimeContext": "<<<BEGIN_MEMORY_CORE_INTERNAL_CONTEXT>>>\nsecret runtime context\n<<<END_MEMORY_CORE_INTERNAL_CONTEXT>>>",
    }


def test_resolve_runtime_context_prompt_parts_keeps_prompt_local_additions_in_model_prompt():
    prompt = "\n\n".join(["runtime prefix", "visible ask", "retry instruction"])
    effective_prompt = "\n\n".join(
        [
            prompt,
            "<<<BEGIN_OPENCLAW_INTERNAL_CONTEXT>>>\nsecret runtime context\n<<<END_OPENCLAW_INTERNAL_CONTEXT>>>",
        ]
    )

    assert resolve_runtime_context_prompt_parts(
        effective_prompt=effective_prompt,
        transcript_prompt="visible ask",
        model_prompt=effective_prompt,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    ) == {
        "prompt": "visible ask",
        "modelPrompt": prompt,
        "runtimeContext": "<<<BEGIN_OPENCLAW_INTERNAL_CONTEXT>>>\nsecret runtime context\n<<<END_OPENCLAW_INTERNAL_CONTEXT>>>",
    }


def test_resolve_runtime_context_prompt_parts_uses_marker_prompt_for_runtime_only_events():
    assert resolve_runtime_context_prompt_parts(
        effective_prompt="internal event",
        transcript_prompt="",
    ) == {
        "prompt": "Continue the memory-core runtime event.",
        "runtimeContext": "internal event",
        "runtimeOnly": True,
        "runtimeSystemContext": "\n".join(
            [
                "memory-core runtime event.",
                "This context is runtime-generated, not user-authored. Keep internal details private.",
                "",
                "internal event",
            ]
        ),
    }


def test_build_current_inbound_prompt_joins_context_and_prompt():
    assert (
        build_current_inbound_prompt(
            context={"text": "Current message:\n#34975 obviyus:", "promptJoiner": " "},
            prompt="What do you mean hidden?",
        )
        == "Current message:\n#34975 obviyus: What do you mean hidden?"
    )


def test_build_runtime_context_custom_message_labels_context_and_hides_display():
    message = build_runtime_context_custom_message("secret runtime context")

    assert message is not None
    assert message["role"] == "custom"
    assert message["customType"] == "memory_core.runtime-context"
    assert message["display"] is False
    assert message["details"] == {"source": "memory-core-runtime-context"}
    assert "not user-authored" in message["content"]
    assert "secret runtime context" in message["content"]
    assert isinstance(message["timestamp"], int)
