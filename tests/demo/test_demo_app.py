from pathlib import Path

from fastapi.testclient import TestClient

from demo.app import app


def test_demo_home_loads():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "OpenClaw Memory Demo" in response.text


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

    response = client.get("/api/chat/state")

    assert response.status_code == 200
    payload = response.json()
    assert "engines" in payload
    assert "memoryFiles" in payload
    assert payload["turns"] == []


def test_chat_send_runs_recall_and_returns_turn():
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    client.post("/api/seed")
    client.post("/api/reindex")

    response = client.post(
        "/api/chat/send",
        json={
            "message": "Ben kısa teknik cevapları Türkçe tercih ediyorum.",
            "engine": "fake",
            "autoFlush": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["turns"][0]["userMessage"] == "Ben kısa teknik cevapları Türkçe tercih ediyorum."
    assert payload["turns"][0]["recallQuery"]
    assert payload["turns"][0]["assistantResponse"]
    assert payload["turns"][0]["flush"] is None


def test_chat_manual_flush_updates_latest_turn_and_memory_file():
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    client.post(
        "/api/chat/send",
        json={
            "message": "Ben teknik cevapları Türkçe tercih ediyorum.",
            "engine": "fake",
            "autoFlush": False,
        },
    )

    response = client.post("/api/chat/flush", json={"engine": "fake"})

    assert response.status_code == 200
    latest = response.json()["turns"][-1]
    assert latest["flush"]["parsed"]["shouldWrite"] is True
    assert "memory/2026-05-03.md" in response.json()["memoryFiles"]


def test_chat_send_auto_flush_updates_turn():
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.post(
        "/api/chat/send",
        json={
            "message": "Project decision: use OpenClaw prompt text exactly.",
            "engine": "fake",
            "autoFlush": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["turns"][-1]["flush"]["parsed"]["shouldWrite"] is True


def test_chat_send_unconfigured_openai_returns_json_error(monkeypatch):
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_MODEL", raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/chat/send",
        json={"message": "hello", "engine": "openai", "autoFlush": False},
    )

    assert response.status_code == 400
    assert "error" in response.json()
