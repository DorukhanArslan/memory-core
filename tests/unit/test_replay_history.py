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


def test_normalize_assistant_replay_content_drops_failed_turns_and_the_legacy_sentinel():
    sentinel = [{"type": "text", "text": STREAM_ERROR_FALLBACK_TEXT}]
    for failed in (_assistant([], "error"), _assistant([], "stop"), _assistant(sentinel, "error")):
        assert normalize_assistant_replay_content(
            [_user("hello"), failed, _user("retry")]
        ) == [_user("hello"), _user("retry")]


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


def test_normalize_assistant_replay_content_drops_reasoning_only_length_turns():
    thinking = _assistant([{"type": "thinking", "thinking": "partial", "signature": "s"}], "length")
    assert normalize_assistant_replay_content([_user("hi"), thinking]) == [_user("hi")]


def test_normalize_assistant_replay_content_drops_managed_display_blocks_and_bare_mirrors():
    reply = _assistant([{"type": "text", "text": "answer"}], "stop")
    with_image = _assistant(
        [{"type": "image", "data": "AA==", "mimeType": "image/png"}, {"type": "text", "text": "answer"}],
        "stop",
    )
    out = normalize_assistant_replay_content([_user("hi"), with_image])
    assert out[1]["content"] == [{"type": "text", "text": "answer"}]
    # a zero-usage receipt right after its source reply is a mirror duplicate
    assert normalize_assistant_replay_content([_user("hi"), reply, dict(reply)]) == [
        _user("hi"),
        reply,
    ]
    billed = {**reply, "usage": {"input": 5, "output": 5, "totalTokens": 10}}
    assert normalize_assistant_replay_content([_user("hi"), reply, billed])[2] == billed


def test_normalize_assistant_replay_content_keeps_blank_user_turns_with_persisted_media():
    media_turn = {
        "role": "user",
        "content": "",
        "__openclaw": {"media": [{"path": "/tmp/a.png"}]},
        "timestamp": 0,
    }
    assert normalize_assistant_replay_content([media_turn])[0] == media_turn
    only_blank = {"role": "user", "content": [{"type": "text", "text": " "}], "__openclaw": {"media": [{"url": "u"}]}}
    assert normalize_assistant_replay_content([only_blank])[0]["content"] == ""
