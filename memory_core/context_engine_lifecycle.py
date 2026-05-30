from __future__ import annotations

from typing import Any


OPENCLAW_RUNTIME_CONTEXT_CUSTOM_TYPE = "openclaw.runtime-context"


def strip_runtime_context_custom_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not any(_is_openclaw_runtime_context_custom_message(message) for message in messages):
        return messages
    return [
        message
        for message in messages
        if not _is_openclaw_runtime_context_custom_message(message)
    ]


def assemble_context_engine_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return strip_runtime_context_custom_messages(messages)


def build_context_engine_conversation_snapshot(
    *,
    messages_snapshot: list[dict[str, Any]],
    pre_prompt_message_count: int,
) -> dict[str, Any]:
    safe_count = max(0, min(pre_prompt_message_count, len(messages_snapshot)))
    pre_prompt_messages = strip_runtime_context_custom_messages(messages_snapshot[:safe_count])
    turn_messages = strip_runtime_context_custom_messages(messages_snapshot[safe_count:])
    return {
        "messages": [*pre_prompt_messages, *turn_messages],
        "prePromptMessageCount": len(pre_prompt_messages),
    }


def _is_openclaw_runtime_context_custom_message(message: object) -> bool:
    return (
        isinstance(message, dict)
        and message.get("role") == "custom"
        and message.get("customType") == OPENCLAW_RUNTIME_CONTEXT_CUSTOM_TYPE
    )
