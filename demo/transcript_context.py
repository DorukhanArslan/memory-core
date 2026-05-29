from __future__ import annotations

from demo.chat_engine import ChatMessage


def select_transcript_context(
    messages: list[ChatMessage],
    *,
    max_chars: int,
) -> tuple[list[ChatMessage], list[ChatMessage]]:
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
