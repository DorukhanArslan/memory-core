from memory_core.context_engine_lifecycle import (
    OPENCLAW_COMPAT_BRANDING,
    assemble_context_engine_messages,
    build_context_engine_conversation_snapshot,
    strip_runtime_context_custom_messages,
)


def _message(role: str, text: str, timestamp: int) -> dict:
    return {"role": role, "content": [{"type": "text", "text": text}], "timestamp": timestamp}


def _runtime_context_message(text: str, timestamp: int) -> dict:
    return {
        "role": "custom",
        "customType": "memory_core.runtime-context",
        "content": text,
        "display": False,
        "details": {"source": "memory-core-runtime-context"},
        "timestamp": timestamp,
    }


def test_strip_runtime_context_custom_messages_can_use_openclaw_compat_branding():
    visible_user = _message("user", "visible ask", 1)
    runtime_context = {
        "role": "custom",
        "customType": "openclaw.runtime-context",
        "content": "hidden",
        "timestamp": 2,
    }

    assert strip_runtime_context_custom_messages(
        [visible_user, runtime_context],
        branding=OPENCLAW_COMPAT_BRANDING,
    ) == [visible_user]


def test_strip_runtime_context_custom_messages_removes_hidden_runtime_context_only():
    visible_user = _message("user", "visible ask", 1)
    runtime_context = _runtime_context_message("hidden", 2)
    other_custom = {"role": "custom", "customType": "other", "content": "keep", "timestamp": 3}
    visible_assistant = _message("assistant", "visible answer", 4)

    assert strip_runtime_context_custom_messages(
        [visible_user, runtime_context, other_custom, visible_assistant]
    ) == [visible_user, other_custom, visible_assistant]


def test_assemble_context_engine_messages_strips_hidden_runtime_context():
    visible_user = _message("user", "visible ask", 1)
    runtime_context = _runtime_context_message("hidden", 2)
    visible_assistant = _message("assistant", "visible answer", 3)

    assert assemble_context_engine_messages(
        [visible_user, runtime_context, visible_assistant]
    ) == [visible_user, visible_assistant]


def test_build_context_engine_conversation_snapshot_adjusts_pre_prompt_count():
    before_user = _message("user", "old ask", 1)
    before_runtime = _runtime_context_message("old hidden", 2)
    before_assistant = _message("assistant", "old answer", 3)
    turn_user = _message("user", "new ask", 4)
    turn_runtime = _runtime_context_message("new hidden", 5)
    turn_assistant = _message("assistant", "new answer", 6)

    snapshot = build_context_engine_conversation_snapshot(
        messages_snapshot=[
            before_user,
            before_runtime,
            before_assistant,
            turn_user,
            turn_runtime,
            turn_assistant,
        ],
        pre_prompt_message_count=3,
    )

    assert snapshot == {
        "messages": [before_user, before_assistant, turn_user, turn_assistant],
        "prePromptMessageCount": 2,
    }
