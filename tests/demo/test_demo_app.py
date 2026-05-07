from pathlib import Path

from fastapi.testclient import TestClient

import demo.app as demo_app
from demo.chat_engine import ChatResponse, FlushModelOutput

app = demo_app.app


class StubOpenAIEngine:
    name = "openai"

    def complete(self, *, messages, memory_context):
        del memory_context
        return ChatResponse(
            role="assistant",
            content=f"stub response to {messages[-1].content}",
        )

    def stream_complete(self, *, messages, memory_context):
        del memory_context
        yield "streamed "
        yield f"response to {messages[-1].content}"

    def flush(self, *, system_prompt, prompt, transcript, target):
        del system_prompt, prompt
        return FlushModelOutput(
            raw_text=(
                '{"shouldWrite": true, "target": "'
                + target
                + '", "entry": "- '
                + transcript[-2].content
                + '", "reason": "Durable test memory."}'
            )
        )


def test_demo_home_loads():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "OpenClaw Chat Memory Lab" in response.text
    assert "chat-form" in response.text
    assert "memory-pipeline" in response.text
    assert "Raw Flush Output" in response.text
    assert "engine-status" in response.text
    assert "api-key" in response.text
    assert "gpt-5.2" in response.text
    assert "Tool Inspector" in response.text
    assert "Fake</option>" not in response.text
    assert 'id="auto-flush" type="checkbox" checked' in response.text


def test_prompt_preview_endpoint():
    client = TestClient(app)
    response = client.post(
        "/api/prompt-preview",
        json={"tools": ["memory_search", "memory_get"], "citationsMode": "on"},
    )
    assert response.status_code == 200
    assert response.json()["lines"][0] == "## Memory Recall"


def test_invalid_search_payload_returns_json_error():
    client = TestClient(app)
    response = client.post(
        "/api/search",
        json={"query": "x", "maxResults": "", "minScore": ""},
    )
    assert response.status_code == 400
    assert "error" in response.json()


def test_invalid_prompt_payload_returns_json_error():
    client = TestClient(app)
    response = client.post(
        "/api/prompt-preview",
        json={"tools": None, "citationsMode": "bad"},
    )
    assert response.status_code == 400
    assert "error" in response.json()


def test_endpoint_calls_do_not_create_repo_demo_workspace():
    client = TestClient(app)
    client.post("/api/seed")
    client.post("/api/reindex")
    repo_demo_workspace = Path(__file__).resolve().parents[2] / "demo" / "workspace"
    assert not repo_demo_workspace.exists()


def test_chat_state_endpoint_returns_engines_and_memory_files():
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.get("/api/chat/state")

    assert response.status_code == 200
    payload = response.json()
    assert "engines" in payload
    assert "memoryFiles" in payload
    assert "memoryFileContents" in payload
    assert "MEMORY.md" in payload["memoryFileContents"]
    assert payload["config"]["workspace"]
    assert payload["config"]["timezone"] == "Europe/Istanbul"
    assert payload["config"]["dailyMemoryPath"] == "memory/2026-05-03.md"
    assert payload["turns"] == []


def test_chat_send_runs_recall_and_returns_turn(monkeypatch):
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: StubOpenAIEngine())
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    client.post("/api/seed")
    client.post("/api/reindex")

    response = client.post(
        "/api/chat/send",
        json={
            "message": "Ben kısa teknik cevapları Türkçe tercih ediyorum.",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
            "autoFlush": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["turns"][0]["userMessage"] == "Ben kısa teknik cevapları Türkçe tercih ediyorum."
    assert payload["turns"][0]["recallQuery"]
    assert payload["turns"][0]["assistantResponse"]
    assert payload["turns"][0]["flush"] is None


def test_chat_manual_flush_updates_latest_turn_and_memory_file(monkeypatch):
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: StubOpenAIEngine())
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    client.post(
        "/api/chat/send",
        json={
            "message": "Ben teknik cevapları Türkçe tercih ediyorum.",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
            "autoFlush": False,
        },
    )

    response = client.post(
        "/api/chat/flush",
        json={"engine": "openai", "openai": {"apiKey": "request-key"}},
    )

    assert response.status_code == 200
    latest = response.json()["turns"][-1]
    assert latest["flush"]["parsed"]["shouldWrite"] is True
    assert "memory/2026-05-03.md" in response.json()["memoryFiles"]


def test_chat_send_auto_flush_updates_turn(monkeypatch):
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: StubOpenAIEngine())
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.post(
        "/api/chat/send",
        json={
            "message": "Project decision: use OpenClaw prompt text exactly.",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
            "autoFlush": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["turns"][-1]["flush"]["parsed"]["shouldWrite"] is True


def test_chat_send_defaults_to_auto_flush(monkeypatch):
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: StubOpenAIEngine())
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.post(
        "/api/chat/send",
        json={
            "message": "Project decision: default auto flush.",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
        },
    )

    assert response.status_code == 200
    assert response.json()["turns"][-1]["flush"]["parsed"]["shouldWrite"] is True


def test_chat_send_stream_emits_deltas_and_final_state(monkeypatch):
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: StubOpenAIEngine())
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    with client.stream(
        "POST",
        "/api/chat/send-stream",
        json={
            "message": "Project decision: stream chat.",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
        },
    ) as response:
        body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert "event: assistant_delta" in body
    assert "streamed " in body
    assert "event: final_state" in body
    assert "Project decision: stream chat." in body
    assert '"shouldWrite": true' in body


def test_chat_send_unconfigured_openai_returns_json_error(monkeypatch):
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_MODEL", raising=False)
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.post(
        "/api/chat/send",
        json={"message": "hello", "engine": "openai", "autoFlush": False},
    )

    assert response.status_code == 400
    assert "error" in response.json()


def test_chat_send_runtime_error_returns_json_error(monkeypatch):
    class BrokenEngine:
        name = "broken"

        def complete(self, *, messages, memory_context):
            del messages, memory_context
            raise RuntimeError("boom")

        def flush(self, *, system_prompt, prompt, transcript, target):
            del system_prompt, prompt, transcript, target
            raise AssertionError("flush should not be called")

    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: BrokenEngine())
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.post(
        "/api/chat/send",
        json={
            "message": "hello",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
            "autoFlush": False,
        },
    )

    assert response.status_code == 400
    assert "chat send failed" in response.json()["error"]
    assert "boom" in response.json()["error"]


def test_chat_flush_runtime_error_returns_json_error(monkeypatch):
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: StubOpenAIEngine())
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    client.post(
        "/api/chat/send",
        json={
            "message": "Ben teknik cevapları Türkçe tercih ediyorum.",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
        },
    )

    def fail_flush(**kwargs):
        del kwargs
        raise RuntimeError("boom")

    monkeypatch.setattr(demo_app, "run_memory_flush", fail_flush)

    response = client.post(
        "/api/chat/flush",
        json={"engine": "openai", "openai": {"apiKey": "request-key"}},
    )

    assert response.status_code == 400
    assert "chat flush failed" in response.json()["error"]
    assert "boom" in response.json()["error"]
