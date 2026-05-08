from demo.chat_engine import (
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    ChatMessage,
    FlushWriteCall,
    OpenAICompatibleChatEngine,
    engine_status,
    _parse_stream_line,
)


class StubResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_openai_engine_is_unavailable_without_api_key_but_reports_defaults(monkeypatch):
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_MODEL", raising=False)

    status = engine_status()

    assert status["openai"] == {
        "available": False,
        "model": DEFAULT_OPENAI_MODEL,
        "baseUrl": DEFAULT_OPENAI_BASE_URL,
    }
    assert OpenAICompatibleChatEngine.from_env() is None


def test_openai_engine_status_uses_env_without_exposing_api_key(monkeypatch):
    monkeypatch.setenv("OPENCLAW_DEMO_OPENAI_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("OPENCLAW_DEMO_OPENAI_API_KEY", "secret-key")
    monkeypatch.setenv("OPENCLAW_DEMO_OPENAI_MODEL", "demo-model")

    status = engine_status()

    assert OpenAICompatibleChatEngine.from_env() is not None
    assert status["openai"] == {
        "available": True,
        "model": "demo-model",
        "baseUrl": "https://llm.example/v1",
    }
    assert "secret-key" not in str(status)


def test_openai_engine_from_config_uses_payload_key_and_defaults(monkeypatch):
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_MODEL", raising=False)

    engine = OpenAICompatibleChatEngine.from_config(
        base_url=None,
        api_key="request-key",
        model=None,
    )

    assert engine is not None
    assert engine.base_url == DEFAULT_OPENAI_BASE_URL
    assert engine.api_key == "request-key"
    assert engine.model == DEFAULT_OPENAI_MODEL == "gpt-5.2"


def test_openai_engine_complete_posts_openai_compatible_chat_request(monkeypatch):
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return StubResponse(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "Tamam, kısa yanıt."}},
                ]
            }
        )

    monkeypatch.setattr("demo.chat_engine.httpx.post", fake_post)
    engine = OpenAICompatibleChatEngine(
        base_url="https://llm.example/v1/",
        api_key="secret-key",
        model="demo-model",
    )

    response = engine.complete(
        messages=[ChatMessage(role="user", content="Kısa yanıt verir misin?")],
        memory_context=["MEMORY.md#1: User prefers Turkish."],
    )

    assert response.role == "assistant"
    assert response.content == "Tamam, kısa yanıt."
    assert len(calls) == 1
    assert calls[0]["url"] == "https://llm.example/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-key"
    assert calls[0]["headers"]["Content-Type"] == "application/json"
    assert calls[0]["json"]["model"] == "demo-model"
    assert calls[0]["json"]["messages"] == [
        {
            "role": "system",
            "content": "Use the supplied memory context when relevant. Do not invent memory.",
        },
        {
            "role": "system",
            "content": "Memory context:\nMEMORY.md#1: User prefers Turkish.",
        },
        {"role": "user", "content": "Kısa yanıt verir misin?"},
    ]


def test_openai_engine_flush_runs_openclaw_style_write_tool(monkeypatch):
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return StubResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "write",
                                        "arguments": (
                                            '{"path":"memory/2026-05-03.md",'
                                            '"content":"- User was fired from work."}'
                                        ),
                                    },
                                }
                            ],
                        }
                    },
                ]
            }
        )

    monkeypatch.setattr("demo.chat_engine.httpx.post", fake_post)
    engine = OpenAICompatibleChatEngine(
        base_url="https://llm.example/v1",
        api_key="secret-key",
        model="demo-model",
    )

    output = engine.flush(
        system_prompt="Pre-compaction memory flush turn.",
        prompt="Pre-compaction memory flush.",
        transcript=[
            ChatMessage(role="user", content="My name is Alex"),
            ChatMessage(role="assistant", content="Noted."),
        ],
        target="memory/2026-05-03.md",
    )

    assert output.raw_text == "write(memory/2026-05-03.md)"
    assert output.writes == (
        FlushWriteCall(
            path="memory/2026-05-03.md",
            content="- User was fired from work.",
            call_id="call_1",
            name="write",
        ),
    )
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/chat/completions")
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-key"
    assert calls[0]["json"]["model"] == "demo-model"
    assert calls[0]["json"]["tool_choice"] == "auto"
    assert calls[0]["json"]["tools"][0]["function"]["name"] == "write"
    assert "During memory flush, this tool may only append to memory/2026-05-03.md." in calls[0][
        "json"
    ]["tools"][0]["function"]["description"]
    assert calls[0]["json"]["messages"][0] == {
        "role": "system",
        "content": "Pre-compaction memory flush turn.",
    }
    assert calls[0]["json"]["messages"][1] == {"role": "user", "content": "My name is Alex"}
    assert calls[0]["json"]["messages"][2] == {"role": "assistant", "content": "Noted."}
    user_message = calls[0]["json"]["messages"][3]
    assert user_message["role"] == "user"
    assert user_message["content"] == "Pre-compaction memory flush."


def test_parse_stream_line_extracts_delta_content():
    line = 'data: {"choices":[{"delta":{"content":"hello"}}]}'

    assert _parse_stream_line(line) == "hello"
    assert _parse_stream_line("data: [DONE]") is None
    assert _parse_stream_line(": keep-alive") is None
