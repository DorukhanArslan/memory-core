from memory_core.replay_history import (
    STREAM_ERROR_FALLBACK_TEXT,
    normalize_assistant_replay_content,
)


def _user(text: str) -> dict:
    return {"role": "user", "content": text, "timestamp": 0}


def _assistant(content, stop_reason: str = "error", usage: dict | None = None) -> dict:
    return {
        "role": "assistant",
        "content": content,
        "api": "bedrock-converse-stream",
        "provider": "amazon-bedrock",
        "model": "anthropic.claude-3-haiku-20240307-v1:0",
        "usage": usage
        or {
            "input": 0,
            "output": 0,
            "cacheRead": 0,
            "cacheWrite": 0,
            "totalTokens": 0,
        },
        "stopReason": stop_reason,
        "timestamp": 0,
    }


def _openclaw_transcript_assistant(model: str) -> dict:
    return {
        "role": "assistant",
        "content": [{"type": "text", "text": "channel mirror"}],
        "provider": "openclaw",
        "model": model,
        "timestamp": 0,
    }


def test_normalize_assistant_replay_content_converts_mid_turn_empty_error_to_sentinel():
    messages = [_user("hello"), _assistant([], "error"), _user("retry")]

    out = normalize_assistant_replay_content(messages)

    assert out[1]["content"] == [{"type": "text", "text": STREAM_ERROR_FALLBACK_TEXT}]
    assert out[2] == messages[2]


def test_normalize_assistant_replay_content_drops_trailing_empty_error_and_zero_usage_stop():
    assert normalize_assistant_replay_content([_user("hello"), _assistant([], "error")]) == [
        _user("hello")
    ]
    assert normalize_assistant_replay_content([_user("hello"), _assistant([], "stop")]) == [
        _user("hello")
    ]


def test_normalize_assistant_replay_content_preserves_nonzero_silent_stop():
    silent_stop = _assistant(
        [],
        "stop",
        usage={"input": 100, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 100},
    )
    messages = [_user("hello"), silent_stop]

    assert normalize_assistant_replay_content(messages) == messages


def test_normalize_assistant_replay_content_wraps_legacy_assistant_content():
    assert normalize_assistant_replay_content([_user("hi"), _assistant("plain string", "stop")])[
        1
    ]["content"] == [{"type": "text", "text": "plain string"}]
    block = {"type": "text", "text": "plain object"}
    assert normalize_assistant_replay_content([_user("hi"), _assistant(block, "stop")])[1][
        "content"
    ] == [block]


def test_normalize_assistant_replay_content_drops_blank_user_text_blocks():
    image_block = {"type": "image", "data": "AA==", "mimeType": "image/png"}
    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "   "}, image_block],
            "timestamp": 0,
        }
    ]

    assert normalize_assistant_replay_content(messages)[0]["content"] == [image_block]


def test_normalize_assistant_replay_content_filters_openclaw_transcript_only_assistants():
    messages = [
        _user("hello"),
        _openclaw_transcript_assistant("delivery-mirror"),
        _assistant([{"type": "text", "text": "real reply"}], "stop"),
        _openclaw_transcript_assistant("gateway-injected"),
    ]

    out = normalize_assistant_replay_content(messages)

    assert [message["role"] for message in out] == ["user", "assistant"]
    assert out[1]["provider"] == "amazon-bedrock"


def test_normalize_assistant_replay_content_strips_internal_runtime_context_from_text_blocks():
    messages = [
        _user("first"),
        _assistant(
            [
                {
                    "type": "text",
                    "text": "\n".join(
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
                }
            ],
            "stop",
        ),
    ]

    out = normalize_assistant_replay_content(messages)

    assert out[1]["content"] == [{"type": "text", "text": "Visible before\n\nVisible after"}]


def test_normalize_assistant_replay_content_strips_memory_core_internal_runtime_context():
    messages = [
        _user("first"),
        _assistant(
            [
                {
                    "type": "text",
                    "text": "\n".join(
                        [
                            "Visible before",
                            "<<<BEGIN_MEMORY_CORE_INTERNAL_CONTEXT>>>",
                            "keep this internal",
                            "<<<END_MEMORY_CORE_INTERNAL_CONTEXT>>>",
                            "memory-core runtime context for the immediately preceding user message.",
                            "This context is runtime-generated, not user-authored. Keep internal details private.",
                            "",
                            "Visible after",
                        ]
                    ),
                }
            ],
            "stop",
        ),
    ]

    out = normalize_assistant_replay_content(messages)

    assert out[1]["content"] == [{"type": "text", "text": "Visible before\n\nVisible after"}]
