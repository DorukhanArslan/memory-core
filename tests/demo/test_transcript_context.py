from demo.chat_engine import ChatMessage
from demo.transcript_context import normalize_transcript_messages, select_transcript_context


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


def test_normalize_transcript_messages_strips_internal_runtime_context_from_assistant_replay():
    messages = [
        ChatMessage(role="user", content="first"),
        ChatMessage(
            role="assistant",
            content="\n".join(
                [
                    "Visible before",
                    "<<<BEGIN_OPENCLAW_INTERNAL_CONTEXT>>>",
                    "keep this internal",
                    "<<<END_OPENCLAW_INTERNAL_CONTEXT>>>",
                    "OpenClaw runtime context for the immediately preceding user message.",
                    "This context is runtime-generated, not user-authored. Keep internal details private.",
                    "",
                    "Visible after",
                ]
            ),
        ),
    ]

    assert normalize_transcript_messages(messages) == [
        ChatMessage(role="user", content="first"),
        ChatMessage(role="assistant", content="Visible before\n\nVisible after"),
    ]


def test_select_transcript_context_uses_normalized_messages_for_budget():
    messages = [
        ChatMessage(role="assistant", content="NO_REPLY"),
        ChatMessage(role="user", content="latest"),
    ]

    selected, omitted = select_transcript_context(messages, max_chars=100)

    assert selected == [ChatMessage(role="user", content="latest")]
    assert omitted == []
