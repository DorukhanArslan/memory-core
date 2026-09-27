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
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_MODEL", raising=False)

    status = engine_status()

    assert status["openai"] == {
        "available": False,
        "model": DEFAULT_OPENAI_MODEL,
        "baseUrl": DEFAULT_OPENAI_BASE_URL,
    }
    assert OpenAICompatibleChatEngine.from_env() is None


def test_openai_engine_status_uses_env_without_exposing_api_key(monkeypatch):
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", "secret-key")
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_MODEL", "demo-model")

    status = engine_status()

    assert OpenAICompatibleChatEngine.from_env() is not None
    assert status["openai"] == {
        "available": True,
        "model": "demo-model",
        "baseUrl": "https://llm.example/v1",
    }
    assert "secret-key" not in str(status)


def test_openai_engine_from_config_uses_payload_key_and_defaults(monkeypatch):
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_MODEL", raising=False)

    engine = OpenAICompatibleChatEngine.from_config(
        base_url=None,
        api_key="request-key",
        model=None,
    )

    assert engine is not None
    assert engine.base_url == DEFAULT_OPENAI_BASE_URL
    assert engine.api_key == "request-key"
    assert engine.model == DEFAULT_OPENAI_MODEL == "openai/gpt-6-luna"
    assert engine.base_url == "https://openrouter.ai/api/v1"


class StubStream:
    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        yield from self.lines


def test_openai_engine_stream_chat_assembles_streamed_tool_calls(monkeypatch):
    calls = []
    chunks = [
        {"choices": [{"delta": {"content": "Bakıyorum. "}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": "memory_", "arguments": '{"que'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "search", "arguments": 'ry":"x"}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 1200, "completion_tokens": 30, "total_tokens": 1230}},
    ]

    def fake_stream(method, url, *, headers, json, timeout):
        calls.append({"method": method, "url": url, "headers": headers, "json": json, "timeout": timeout})
        return StubStream([f"data: {__import__('json').dumps(chunk)}" for chunk in chunks] + ["data: [DONE]"])

    monkeypatch.setattr("demo.chat_engine.httpx.stream", fake_stream)
    engine = OpenAICompatibleChatEngine(base_url="https://llm.example/v1/", api_key="secret-key", model="demo-model")
    tools = [{"type": "function", "function": {"name": "memory_search", "parameters": {"type": "object"}}}]

    events = list(engine.stream_chat([{"role": "user", "content": "Ne demiştik?"}], tools=tools))

    assert events[0] == {"type": "delta", "text": "Bakıyorum. "}
    assert events[-1] == {
        "type": "message",
        "content": "Bakıyorum. ",
        "toolCalls": [{"id": "call_1", "name": "memory_search", "arguments": '{"query":"x"}'}],
        "usage": {"promptTokens": 1200, "completionTokens": 30, "totalTokens": 1230},
        "finishReason": "tool_calls",
    }
    body = calls[0]["json"]
    assert calls[0]["url"] == "https://llm.example/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-key"
    assert body["tools"] == tools and body["tool_choice"] == "auto"
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
    assert body["messages"] == [{"role": "user", "content": "Ne demiştik?"}]


def test_scripted_engine_never_calls_tools():
    from demo.chat_engine import SCRIPTED_REPLY, ScriptedChatEngine

    events = list(ScriptedChatEngine().stream_chat([], tools=[{"type": "function"}]))

    assert events[-1]["toolCalls"] == []
    assert events[-1]["content"] == SCRIPTED_REPLY
    assert ScriptedChatEngine.provider == "scripted"


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


def test_check_retries_without_a_token_cap_when_the_provider_rejects_max_tokens(monkeypatch):
    # gpt-6-luna on api.openai.com: 400 param=max_tokens ("Use 'max_completion_tokens'
    # instead"), and a tiny max_completion_tokens cannot finish a reasoning model either.
    import httpx

    engine = OpenAICompatibleChatEngine(base_url="https://llm.example/v1", api_key="k", model="m")
    bodies = []
    request = httpx.Request("POST", "https://llm.example/v1/chat/completions")

    def fake_post(url, *, headers, json, timeout):
        bodies.append(json)
        if "max_tokens" in json:
            return httpx.Response(
                400,
                json={"error": {"param": "max_tokens", "message": "Unsupported parameter"}},
                request=request,
            )
        return httpx.Response(200, json={"model": "m-2026", "choices": []}, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)

    assert engine.check() == {"model": "m-2026"}
    assert [("max_tokens" in body) for body in bodies] == [True, False]


def test_check_does_not_retry_other_provider_errors(monkeypatch):
    import httpx
    import pytest

    engine = OpenAICompatibleChatEngine(base_url="https://llm.example/v1", api_key="k", model="m")
    request = httpx.Request("POST", "https://llm.example/v1/chat/completions")
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append(json)
        return httpx.Response(401, json={"error": {"message": "bad key"}}, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(httpx.HTTPStatusError):
        engine.check()
    assert len(calls) == 1


def _tool_refusal():
    import httpx

    return httpx.Response(
        400,
        json={"error": {"param": "reasoning_effort", "message": "Function tools with reasoning_effort are not supported"}},
        request=httpx.Request("POST", "https://llm.example/v1/chat/completions"),
    )


def test_stream_chat_retries_tools_without_reasoning_when_the_provider_names_it(monkeypatch):
    # api.openai.com, gpt-6-luna, 2026-09-27: function tools on /v1/chat/completions need
    # reasoning_effort "none"; the engine retries once and keeps the setting.
    from contextlib import contextmanager

    import httpx

    engine = OpenAICompatibleChatEngine(base_url="https://llm.example/v1", api_key="k", model="m")
    bodies = []
    ok = httpx.Response(
        200,
        content=b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n',
        request=httpx.Request("POST", "https://llm.example/v1/chat/completions"),
    )

    @contextmanager
    def fake_stream(method, url, *, headers, json, timeout):
        bodies.append(json)
        refused = "tools" in json and "reasoning_effort" not in json
        yield _tool_refusal() if refused else ok

    monkeypatch.setattr(httpx, "stream", fake_stream)
    tools = [{"type": "function", "function": {"name": "t", "parameters": {"type": "object"}}}]

    events = list(engine.stream_chat([{"role": "user", "content": "x"}], tools=tools))
    assert events[-1]["content"] == "hi"
    assert [body.get("reasoning_effort") for body in bodies] == [None, "none"]

    list(engine.stream_chat([{"role": "user", "content": "x"}], tools=tools))
    assert bodies[-1]["reasoning_effort"] == "none" and len(bodies) == 3

    list(engine.stream_chat([{"role": "user", "content": "x"}]))
    assert "reasoning_effort" not in bodies[-1]
