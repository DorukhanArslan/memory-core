from __future__ import annotations

from demo.chat_engine import ChatMessage
from memory_core.replay_history import normalize_assistant_replay_content


def select_transcript_context(
    messages: list[ChatMessage],
    *,
    max_chars: int,
) -> tuple[list[ChatMessage], list[ChatMessage]]:
    messages = normalize_transcript_messages(messages)
    if max_chars <= 0:
        return [], list(messages)

    selected_reversed: list[ChatMessage] = []
    total_chars = 0
    for message in reversed(messages):
        message_chars = _message_budget_chars(message)
        if selected_reversed and total_chars + message_chars > max_chars:
            break
        selected_reversed.append(message)
        total_chars += message_chars

    selected = list(reversed(selected_reversed))
    omitted_count = max(0, len(messages) - len(selected))
    return selected, messages[:omitted_count]


def _message_budget_chars(message: ChatMessage) -> int:
    return len(message.role) + 2 + len(message.content)


def normalize_transcript_messages(messages: list[ChatMessage]) -> list[ChatMessage]:
    replay_messages = [
        {"role": message.role, "content": message.content}
        for message in messages
        if message.role in {"user", "assistant"}
    ]
    normalized = normalize_assistant_replay_content(replay_messages)
    return [
        ChatMessage(role=str(message.get("role")), content=_message_text_content(message.get("content")))
        for message in normalized
        if message.get("role") in {"user", "assistant"}
        and _message_text_content(message.get("content")).strip()
    ]


def _message_text_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for block in content:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            texts.append(block["text"])
    return "\n".join(texts)
