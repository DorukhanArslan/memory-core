from demo.chat_engine import (
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    ChatMessage,
    OpenAICompatibleChatEngine,
    engine_status,
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


def test_openai_engine_flush_posts_prompt_target_and_transcript(monkeypatch):
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return StubResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"shouldWrite": true}',
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

    assert output.raw_text == '{"shouldWrite": true}'
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/chat/completions")
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-key"
    assert calls[0]["json"]["model"] == "demo-model"
    assert calls[0]["json"]["messages"][0] == {
        "role": "system",
        "content": "Pre-compaction memory flush turn.",
    }
    user_message = calls[0]["json"]["messages"][1]
    assert user_message["role"] == "user"
    assert "Pre-compaction memory flush." in user_message["content"]
    assert "Target: memory/2026-05-03.md" in user_message["content"]
    assert "Transcript:" in user_message["content"]
    assert "user: My name is Alex" in user_message["content"]
    assert "assistant: Noted." in user_message["content"]
