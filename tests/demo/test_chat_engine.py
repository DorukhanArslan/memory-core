from demo.chat_engine import ChatMessage, FakeChatEngine, OpenAICompatibleChatEngine, engine_status


class StubResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_fake_engine_uses_memory_context_without_keyword_trigger():
    engine = FakeChatEngine()

    response = engine.complete(
        messages=[ChatMessage(role="user", content="Ben kısa yanıtları severim.")],
        memory_context=["MEMORY.md#1: User prefers Turkish."],
    )

    assert response.role == "assistant"
    assert "memory context" in response.content.lower()
    assert "Ben kısa yanıtları severim." in response.content


def test_fake_engine_flush_decision_does_not_require_remember_word():
    engine = FakeChatEngine()

    output = engine.flush(
        system_prompt="Pre-compaction memory flush turn.",
        prompt="Pre-compaction memory flush.",
        transcript=[
            ChatMessage(
                role="user",
                content="Ben bundan sonra teknik cevapları Türkçe tercih ediyorum.",
            )
        ],
        target="memory/2026-05-03.md",
    )

    assert '"shouldWrite": true' in output.raw_text
    assert "memory/2026-05-03.md" in output.raw_text
    assert "Türkçe" in output.raw_text


def test_fake_engine_flush_writes_json_for_durable_facts_without_remember_word():
    engine = FakeChatEngine()

    for fact in ("My name is Alex", "I live in Ankara", "I work at Acme"):
        output = engine.flush(
            system_prompt="Pre-compaction memory flush turn.",
            prompt="Pre-compaction memory flush.",
            transcript=[ChatMessage(role="user", content=fact)],
            target="memory/2026-05-03.md",
        )

        assert '"shouldWrite": true' in output.raw_text
        assert "memory/2026-05-03.md" in output.raw_text
        assert fact in output.raw_text


def test_fake_engine_flush_returns_silent_token_for_transient_chat():
    engine = FakeChatEngine()

    output = engine.flush(
        system_prompt="Pre-compaction memory flush turn.",
        prompt="Pre-compaction memory flush.",
        transcript=[ChatMessage(role="user", content="Selam, nasılsın?")],
        target="memory/2026-05-03.md",
    )

    assert output.raw_text == "<NO_REPLY>"


def test_openai_engine_is_unavailable_without_config(monkeypatch):
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_MODEL", raising=False)

    assert engine_status()["openai"]["available"] is False
    assert OpenAICompatibleChatEngine.from_env() is None


def test_openai_engine_status_uses_config_without_exposing_api_key(monkeypatch):
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
