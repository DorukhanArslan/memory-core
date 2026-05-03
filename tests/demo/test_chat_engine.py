from demo.chat_engine import ChatMessage, FakeChatEngine, OpenAICompatibleChatEngine, engine_status


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
