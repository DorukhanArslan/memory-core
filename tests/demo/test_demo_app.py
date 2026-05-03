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
