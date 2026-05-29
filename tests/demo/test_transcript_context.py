from demo.chat_engine import ChatMessage
from demo.transcript_context import select_transcript_context


def test_select_transcript_context_keeps_recent_messages_within_budget():
    messages = [
        ChatMessage(role="user", content="one " * 20),
        ChatMessage(role="assistant", content="two " * 20),
        ChatMessage(role="user", content="three"),
    ]

    selected, omitted = select_transcript_context(messages, max_chars=40)

    assert selected == [ChatMessage(role="user", content="three")]
    assert omitted == messages[:2]


def test_select_transcript_context_keeps_latest_message_even_if_it_exceeds_budget():
    messages = [
        ChatMessage(role="user", content="short"),
        ChatMessage(role="assistant", content="x" * 100),
    ]

    selected, omitted = select_transcript_context(messages, max_chars=10)

    assert selected == [messages[-1]]
    assert omitted == [messages[0]]


def test_select_transcript_context_zero_budget_omits_everything():
    messages = [ChatMessage(role="user", content="hello")]

    selected, omitted = select_transcript_context(messages, max_chars=0)

    assert selected == []
    assert omitted == messages
