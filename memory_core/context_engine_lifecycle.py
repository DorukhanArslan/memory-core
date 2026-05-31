from __future__ import annotations

from typing import Any

from memory_core.runtime_identity import RuntimeIdentity, OPENCLAW_COMPAT_RUNTIME_IDENTITY, MEMORY_CORE_RUNTIME_IDENTITY

OPENCLAW_RUNTIME_CONTEXT_CUSTOM_TYPE = OPENCLAW_COMPAT_RUNTIME_IDENTITY.runtime_context_custom_type
MEMORY_CORE_RUNTIME_CONTEXT_CUSTOM_TYPE = MEMORY_CORE_RUNTIME_IDENTITY.runtime_context_custom_type


def strip_runtime_context_custom_messages(
    messages: list[dict[str, Any]],
    *,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> list[dict[str, Any]]:
    if not any(_is_runtime_context_custom_message(message, identity=identity) for message in messages):
        return messages
    return [
        message
        for message in messages
        if not _is_runtime_context_custom_message(message, identity=identity)
    ]


def assemble_context_engine_messages(
    messages: list[dict[str, Any]],
    *,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> list[dict[str, Any]]:
    return strip_runtime_context_custom_messages(messages, identity=identity)


def build_context_engine_conversation_snapshot(
    *,
    messages_snapshot: list[dict[str, Any]],
    pre_prompt_message_count: int,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict[str, Any]:
    safe_count = max(0, min(pre_prompt_message_count, len(messages_snapshot)))
    pre_prompt_messages = strip_runtime_context_custom_messages(
        messages_snapshot[:safe_count],
        identity=identity,
    )
    turn_messages = strip_runtime_context_custom_messages(
        messages_snapshot[safe_count:],
        identity=identity,
    )
    return {
        "messages": [*pre_prompt_messages, *turn_messages],
        "prePromptMessageCount": len(pre_prompt_messages),
    }


def _is_runtime_context_custom_message(
    message: object,
    *,
    identity: RuntimeIdentity,
) -> bool:
    return (
        isinstance(message, dict)
        and message.get("role") == "custom"
        and message.get("customType") == identity.runtime_context_custom_type
    )
