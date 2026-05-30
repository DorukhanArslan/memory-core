from __future__ import annotations

from typing import Any

from memory_core.branding import MemoryBranding, OPENCLAW_COMPAT_BRANDING, MEMORY_CORE_BRANDING

OPENCLAW_RUNTIME_CONTEXT_CUSTOM_TYPE = OPENCLAW_COMPAT_BRANDING.runtime_context_custom_type
MEMORY_CORE_RUNTIME_CONTEXT_CUSTOM_TYPE = MEMORY_CORE_BRANDING.runtime_context_custom_type


def strip_runtime_context_custom_messages(
    messages: list[dict[str, Any]],
    *,
    branding: MemoryBranding = MEMORY_CORE_BRANDING,
) -> list[dict[str, Any]]:
    if not any(_is_runtime_context_custom_message(message, branding=branding) for message in messages):
        return messages
    return [
        message
        for message in messages
        if not _is_runtime_context_custom_message(message, branding=branding)
    ]


def assemble_context_engine_messages(
    messages: list[dict[str, Any]],
    *,
    branding: MemoryBranding = MEMORY_CORE_BRANDING,
) -> list[dict[str, Any]]:
    return strip_runtime_context_custom_messages(messages, branding=branding)


def build_context_engine_conversation_snapshot(
    *,
    messages_snapshot: list[dict[str, Any]],
    pre_prompt_message_count: int,
    branding: MemoryBranding = MEMORY_CORE_BRANDING,
) -> dict[str, Any]:
    safe_count = max(0, min(pre_prompt_message_count, len(messages_snapshot)))
    pre_prompt_messages = strip_runtime_context_custom_messages(
        messages_snapshot[:safe_count],
        branding=branding,
    )
    turn_messages = strip_runtime_context_custom_messages(
        messages_snapshot[safe_count:],
        branding=branding,
    )
    return {
        "messages": [*pre_prompt_messages, *turn_messages],
        "prePromptMessageCount": len(pre_prompt_messages),
    }


def _is_runtime_context_custom_message(
    message: object,
    *,
    branding: MemoryBranding,
) -> bool:
    return (
        isinstance(message, dict)
        and message.get("role") == "custom"
        and message.get("customType") == branding.runtime_context_custom_type
    )
