from datetime import UTC, datetime
from pathlib import Path
import json
import os

import pytest

from fastapi.testclient import TestClient

import demo.app as demo_app
from demo.chat_engine import ChatResponse, FlushModelOutput
from memory_core.consolidation import (
    record_daily_memory_flush,
    record_short_term_recalls,
    run_short_term_promotion,
)
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore

app = demo_app.app


def fake_demo_store(payload=None):
    del payload
    return SQLiteMemoryStore(demo_app.demo_config(), FakeEmbeddingProvider(dimensions=16))


class CountingStore:
    def __init__(self):
        self.reindex_calls = 0

    def reindex(self, workspace):
        del workspace
        self.reindex_calls += 1
        return 7

    def count_chunks(self):
        return 11


class FailingChunkStore(CountingStore):
    def count_chunks(self):
        raise RuntimeError("chunk count failed")


class StubOpenAIEngine:
    name = "openai"

    def __init__(self):
        self.workspace_contexts = []

    def complete(self, *, messages, memory_context, workspace_context=""):
        del memory_context
        self.workspace_contexts.append(workspace_context)
        return ChatResponse(
            role="assistant",
            content=f"stub response to {messages[-1].content}",
        )

    def stream_complete(self, *, messages, memory_context, workspace_context=""):
        del memory_context
        self.workspace_contexts.append(workspace_context)
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
    assert "memory-core Lab" in response.text
    assert "chat-form" in response.text
    assert "memory-pipeline" in response.text
    assert "Raw Flush Output" in response.text
    assert "engine-status" in response.text
    assert "api-key" in response.text
    assert '<details class="controls-panel"' in response.text
    assert "Lab controls" in response.text
    assert "Provider key" in response.text
    assert "Provider endpoint URL" in response.text
    assert "openai/gpt-4o-mini" in response.text
    assert "https://openrouter.ai/api/v1" in response.text
    assert "Tool Inspector" in response.text
    assert "Workspace Files" in response.text
    assert "workspaceBootstrapNode" in response.text
    assert "Injected before memory context" in response.text
    assert "memoryWriteDetailsNode" in response.text
    assert "memory-detail" in response.text
    assert "renderMarkdown" in response.text
    assert "renderJsonView" in response.text
    assert "renderJsonValue(definition, value, 1)" in response.text
    assert "diff-view" in response.text
    assert "kv-grid" in response.text
    assert "promotion-sweep" in response.text
    assert "dreaming-run" in response.text
    assert "memory-audit" in response.text
    assert "memory-repair" in response.text
    assert "Dreaming Sweep" in response.text
    assert "Audit / Repair" in response.text
    assert "OpenClaw Parity" in response.text
    assert "parity-trace" in response.text
    assert "/api/parity/trace" in response.text
    assert "renderParityTrace" in response.text
    assert "Python Port" in response.text
    assert "OpenClaw TS Oracle" in response.text
    assert "/api/memory/promote" in response.text
    assert "/api/dreaming/run" in response.text
    assert "/api/memory/audit" in response.text
    assert '/api/memory/audit", null, "GET"' in response.text
    assert "/api/memory/repair" in response.text
    assert "renderJsonView(state.dreamingSweep)" in response.text
    assert "data-observability-fields" not in response.text
    assert '<option value="sessions">sessions</option>' in response.text
    assert "daily-memory-select" in response.text
    assert "dailyMemoryPaths" in response.text
    assert "latestDailyMemoryPath" in response.text
    assert "Long-term and reference files" in response.text
    assert "OpenClaw defaults" in response.text
    assert "streamingAssistantText" in response.text
    assert "renderMarkdown(body, streamingAssistantText)" in response.text
    assert "Live SDK Task" in response.text
    assert "live-task-form" in response.text
    assert "/api/live-task/turn-stream" in response.text
    assert "/api/live-task/reset" in response.text
    assert "/api/live-task/summary" in response.text
    assert "mode-switch" in response.text
    assert "mode-chat" in response.text
    assert "mode-live" in response.text
    assert "primary-panel active" in response.text
    assert "live-observability" in response.text
    assert "renderModeLayout" in response.text
    assert "renderLiveTask" in response.text
    assert "Subject Memory" in response.text
    assert "subjectMemoryFiles" in response.text
    assert "Workspace Files (Injected)" in response.text
    assert "workspaceInjectedFiles" in response.text
    assert "identityFiles" in response.text
    assert '"Injected order": (layout.injectedOrder || []).join(" -> ")' in response.text
    assert '"Budget order": (layout.loadOrder || []).join(" -> ")' in response.text
    assert "Injected only while bootstrap is pending" in response.text
    assert "a missing MEMORY.md and empty files are skipped" in response.text
    assert "Live mode reads its own workspace root, separate from the chat workspace" in response.text
    assert "does not inject the root MEMORY.md into subject prompts" in response.text
    assert "Chat and live modes read the same workspace root" not in response.text
    assert "These OpenClaw workspace files" not in response.text
    assert "interaction-stack" not in response.text
    assert 'textContent += text' not in response.text
    assert "Fake</option>" not in response.text
    assert 'id="auto-flush" type="checkbox" checked' in response.text


def test_memory_system_page_loads_without_changing_lab():
    client = TestClient(app)

    response = client.get("/memory-system")

    assert response.status_code == 200
    assert "Memory Sistemi Anlatımı" in response.text
    assert "memory-core Lab sunum sayfası" in response.text
    assert "Layer 1 - MEMORY.md" in response.text
    assert "figjam-canvas" in response.text
    assert "Bir mesajdan kalıcı hafızaya giden yol" in response.text
    assert "memory/YYYY-MM-DD.md" in response.text
    assert "short-term-recall.json" in response.text
    assert "phase-signals.json" in response.text
    assert "Dreaming phases" in response.text
    assert "Kesin şema" in response.text
    assert "flowchart LR" in response.text
    assert "mermaid" in response.text
    assert "/static/memory_system.css" in response.text
    assert "chat-form" not in response.text


def test_memory_system_css_is_responsive_and_separate():
    client = TestClient(app)

    response = client.get("/static/memory_system.css")

    assert response.status_code == 200
    assert ".flow-map" in response.text
    assert ".figjam-canvas" in response.text
    assert ".highlight-lines mark" in response.text
    assert ".svg-arrow" in response.text
    assert ".memory-grid" in response.text
    assert ".phase-lanes" in response.text
    assert "color-scheme: dark" in response.text
    assert "@media (max-width: 640px)" in response.text


def test_demo_css_uses_full_screen_layout():
    client = TestClient(app)
    response = client.get("/static/styles.css")

    assert response.status_code == 200
    assert "color-scheme: dark" in response.text
    assert "overflow: auto" in response.text
    assert "min-height: 100dvh" in response.text
    assert "grid-template-columns: minmax(0, 1.35fr) minmax(360px, 0.75fr)" in response.text
    assert ".primary-panel.active" in response.text
    assert ".inspector-panel.active" in response.text
    assert ".tab-panels" in response.text
    assert ".controls-panel" in response.text
    assert ".controls-panel[open] summary::before" in response.text
    assert "@media (max-width: 820px)" in response.text


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
    assert payload["workspaceFiles"] == [
        "AGENTS.md",
        "SOUL.md",
        "TOOLS.md",
        "IDENTITY.md",
        "USER.md",
        "PROACTIVE_PREFERENCES.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
    ]
    assert "workspaceFileContents" in payload
    assert "Operating Instructions" in payload["workspaceFileContents"]["AGENTS.md"]
    assert "Persona and Tone" in payload["workspaceFileContents"]["SOUL.md"]
    # The seed creates memory/ and MEMORY.md: setup counts as complete, so no
    # BOOTSTRAP.md is written and no Bootstrap Pending section is injected.
    assert payload["workspaceFileContents"]["BOOTSTRAP.md"] == ""
    workspace_root = os.path.abspath(demo_app.DEMO_WORKSPACE)
    context = payload["workspaceContext"]
    assert context.startswith(
        "## Workspace Files (injected)\n"
        "These user-editable files are loaded by memory-core and included below in Project Context.\n"
        "# Project Context\n"
    )
    assert f"## {workspace_root}/AGENTS.md\n# AGENTS.md - Operating Instructions" in context
    assert f"## {workspace_root}/MEMORY.md\n# MEMORY.md - Long-Term Memory" in context
    assert context.index(f"## {workspace_root}/USER.md") < context.index(
        f"## {workspace_root}/TOOLS.md"
    )
    assert "# Dynamic Project Context" in context
    assert "Bootstrap Pending" not in context
    assert payload["workspaceLayout"] == {
        "name": "memory-core",
        "loadOrder": [
            "AGENTS.md",
            "SOUL.md",
            "TOOLS.md",
            "IDENTITY.md",
            "USER.md",
            "PROACTIVE_PREFERENCES.md",
            "HEARTBEAT.md",
            "BOOTSTRAP.md",
            "MEMORY.md",
        ],
        "injectedOrder": [
            "AGENTS.md",
            "SOUL.md",
            "IDENTITY.md",
            "USER.md",
            "PROACTIVE_PREFERENCES.md",
            "TOOLS.md",
            "BOOTSTRAP.md",
            "MEMORY.md",
            "HEARTBEAT.md",
        ],
    }
    assert "MEMORY.md" in payload["memoryFileContents"]
    assert "Long-Term Memory" in payload["memoryFileContents"]["MEMORY.md"]
    assert "OpenClaw" not in payload["memoryFileContents"]["MEMORY.md"]
    assert payload["config"]["workspace"]
    assert payload["config"]["timezone"] == "Europe/Istanbul"
    assert payload["config"]["dailyMemoryPath"] == demo_app._demo_flush_plan().relative_path
    assert payload["config"]["promotion"]["upstreamDefaults"]["minRecallCount"] == 3
    assert payload["config"]["promotion"]["upstreamDefaults"]["minUniqueQueries"] == 3
    assert payload["config"]["promotion"]["upstreamDefaults"]["minScore"] == 0.8
    assert payload["config"]["promotion"]["upstreamDefaults"]["enabled"] is False
    assert payload["config"]["promotion"]["upstreamDefaults"]["limit"] == 10
    assert payload["config"]["promotion"]["upstreamDefaults"]["maxAgeDays"] == 30
    assert payload["liveTask"]["workflow"]["current_step"] == "verify_identity"
    assert payload["liveTask"]["tracePath"].endswith(".jsonl")
    assert payload["turns"] == []


def test_chat_state_endpoint_encodes_a_truncated_all_emoji_workspace_file():
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    (demo_app.DEMO_WORKSPACE / "SOUL.md").write_text("😀" * 15_000, encoding="utf-8")
    try:
        response = client.get("/api/chat/state")

        assert response.status_code == 200
        assert "�" in response.json()["workspaceContext"]
    finally:
        client.post("/api/chat/reset", json={})


def test_live_task_reset_and_state_endpoints():
    client = TestClient(app)

    reset_response = client.post(
        "/api/live-task/reset",
        json={"sessionId": "session_demo", "subjectId": "subject_demo"},
    )
    state_response = client.get("/api/live-task/state")

    assert reset_response.status_code == 200
    assert state_response.status_code == 200
    payload = state_response.json()
    assert payload["workflow"]["session_id"] == "session_demo"
    assert payload["workflow"]["subject_id"] == "subject_demo"
    assert payload["workflow"]["current_step"] == "verify_identity"
    assert payload["transcript"] == []
    assert payload["tracePath"].endswith("session_demo.jsonl")
    assert isinstance(payload["subjectMemoryFiles"], dict)
    assert "AGENTS.md" in payload["workspaceInjectedFiles"]
    assert "SOUL.md" in payload["workspaceInjectedFiles"]
    assert "TOOLS.md" in payload["workspaceInjectedFiles"]
    assert "IDENTITY.md" in payload["workspaceInjectedFiles"]
    assert "USER.md" in payload["workspaceInjectedFiles"]
    assert "HEARTBEAT.md" in payload["workspaceInjectedFiles"]
    # The live workspace has no memory/ or MEMORY.md at its root, so its
    # BOOTSTRAP.md stays pending and is injected like upstream's full mode.
    assert "BOOTSTRAP.md" in payload["workspaceInjectedFiles"]
    assert "MEMORY.md" not in payload["workspaceInjectedFiles"]
    assert "PROACTIVE_PREFERENCES.md" not in payload["workspaceInjectedFiles"]
    assert list(payload["workspaceInjectedFiles"])[:4] == [
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
    ]
    assert payload["workspaceInjectedFiles"]["AGENTS.md"].count(
        "## Live Task Demo: appointment_reschedule"
    ) == 1


def test_live_task_summary_before_reset_keeps_state_endpoints_working(monkeypatch, tmp_path):
    from demo.live_task_demo import LiveTaskDemo

    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(demo_app, "LIVE_TASK_DEMO", LiveTaskDemo(workspace_dir=tmp_path / "live"))
    client = TestClient(app)

    summary = client.post(
        "/api/live-task/summary",
        json={"sessionId": "session_demo", "subjectId": "subject_demo"},
    )
    chat_state = client.get("/api/chat/state")
    live_state = client.get("/api/live-task/state")

    assert summary.status_code == 200
    assert chat_state.status_code == 200
    assert live_state.status_code == 200
    # The workspace was never seeded: the display shows upstream's missing markers.
    injected = live_state.json()["workspaceInjectedFiles"]
    assert injected["AGENTS.md"].startswith("[MISSING] Expected at: ")


def test_live_task_state_endpoints_survive_a_deleted_required_file(monkeypatch, tmp_path):
    from demo.live_task_demo import LiveTaskDemo

    live_root = tmp_path / "live"
    monkeypatch.setattr(demo_app, "LIVE_TASK_DEMO", LiveTaskDemo(workspace_dir=live_root))
    client = TestClient(app)
    client.post("/api/live-task/reset", json={"sessionId": "session_demo", "subjectId": "subject_demo"})
    (live_root / "USER.md").unlink()

    chat_state = client.get("/api/chat/state")
    live_state = client.get("/api/live-task/state")

    assert chat_state.status_code == 200
    assert live_state.status_code == 200
    injected = live_state.json()["workspaceInjectedFiles"]
    assert injected["USER.md"] == f"[MISSING] Expected at: {os.path.abspath(live_root)}/USER.md"


def test_live_task_turn_stream_emits_latency_events(monkeypatch):
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", raising=False)
    client = TestClient(app)
    client.post("/api/live-task/reset", json={"sessionId": "session_demo", "subjectId": "subject_demo"})

    response = client.post(
        "/api/live-task/turn-stream",
        json={
            "sessionId": "session_demo",
            "subjectId": "subject_demo",
            "message": "Doğum tarihim 12.04.1990",
        },
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert any(event["event"] == "sentence" for event in events)
    live_events = [event for event in events if event["event"] not in {"error", "live_task_state"}]
    assert all("elapsed_ms" in event["data"] for event in live_events)
    assert live_events[-1]["event"] == "live_turn_completed"
    assert events[-1]["event"] == "live_task_state"
    provider_payloads = [
        event["data"]["data"] for event in events if event["event"] == "provider_event"
    ]
    assert {"type": "llm", "provider": "scripted", "model": "workflow-script"} in provider_payloads


def test_live_task_rejects_a_session_id_that_would_leave_the_trace_dir(monkeypatch):
    # The Lab names trace files after the session: JsonlTraceSink.for_session checks it.
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", raising=False)
    client = TestClient(app)
    client.post("/api/live-task/reset", json={})
    payload = {"sessionId": "../../escaped", "subjectId": "subject_demo"}

    turn = client.post("/api/live-task/turn-stream", json={**payload, "message": "Merhaba"})
    summary = client.post("/api/live-task/summary", json=payload)

    events = _parse_sse(turn.text)
    assert [event["event"] for event in events] == ["error"]
    assert "session_id is not filesystem-safe" in events[0]["data"]["error"]
    assert summary.status_code == 400
    assert "session_id is not filesystem-safe" in summary.json()["error"]
    # trace/live-task/../../escaped.jsonl would land in the workspace root.
    assert not list(demo_app.LIVE_TASK_DEMO.workspace_dir.rglob("escaped.jsonl"))


def test_live_task_turn_failure_redacts_the_request_key(monkeypatch):
    # stream_live_turn yields live_turn_failed with str(exc); the Lab redacts it first.
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", raising=False)
    key = "sk-request-scoped-key-123"

    class FailingEngine:
        model = "test-model"

        def raw_chat_stream(self, messages):
            del messages
            raise RuntimeError(f"401 Unauthorized: invalid api key {key}")
            yield ""

    monkeypatch.setattr(demo_app, "_optional_live_task_engine", lambda payload: FailingEngine())
    client = TestClient(app)
    client.post("/api/live-task/reset", json={"sessionId": "session_demo", "subjectId": "subject_demo"})

    response = client.post(
        "/api/live-task/turn-stream",
        json={
            "sessionId": "session_demo",
            "subjectId": "subject_demo",
            "message": "Merhaba",
            "openai": {"apiKey": key},
        },
    )

    events = _parse_sse(response.text)
    failed = [event for event in events if event["event"] == "live_turn_failed"]
    assert failed and "[redacted]" in failed[0]["data"]["data"]["error"]
    assert events[-1]["event"] == "error"
    assert key not in response.text


def test_live_task_summary_writes_subject_memory(monkeypatch):
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", raising=False)
    client = TestClient(app)
    client.post("/api/live-task/reset", json={"sessionId": "session_demo", "subjectId": "subject_demo"})
    for message in ("Doğum tarihim 12.04.1990", "Yarın saat 15:00 uygun olur", "Evet onaylıyorum"):
        client.post(
            "/api/live-task/turn-stream",
            json={"sessionId": "session_demo", "subjectId": "subject_demo", "message": message},
        )

    response = client.post(
        "/api/live-task/summary",
        json={"sessionId": "session_demo", "subjectId": "subject_demo"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["wrote"] is True
    assert any("Yarın saat 15:00" in fact for fact in payload["summary"]["durable_facts"])
    assert payload["summary"]["follow_ups"] == [
        "Randevu değişikliğini takvim sisteminde doğrula."
    ]
    assert payload["state"]["workflow"]["session_id"] == "session_demo"


def _parse_sse(body: str):
    events = []
    for raw_event in body.strip().split("\n\n"):
        lines = raw_event.splitlines()
        event_name = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        events.append({"event": event_name, "data": data})
    return events


def test_chat_state_uses_current_timezone_date_for_daily_memory(monkeypatch):
    monkeypatch.setattr(
        demo_app,
        "_now_ms",
        lambda: int(datetime(2026, 5, 7, 12, 0, tzinfo=UTC).timestamp() * 1000),
    )
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.get("/api/chat/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["dailyMemoryPath"] == "memory/2026-05-07.md"
    assert "memory/2026-05-07.md" in payload["memoryFiles"]
    assert payload["memoryFileContents"]["memory/2026-05-07.md"] == "# 2026-05-07\n"
    assert "router VLAN" not in payload["memoryFileContents"]["memory/2026-05-07.md"]


def test_chat_reset_removes_stale_daily_memory_files(monkeypatch):
    monkeypatch.setattr(
        demo_app,
        "_now_ms",
        lambda: int(datetime(2026, 5, 7, 12, 0, tzinfo=UTC).timestamp() * 1000),
    )
    config = demo_app.demo_config()
    stale_daily = config.workspace_dir / "memory" / "2026-05-03.md"
    stale_daily.parent.mkdir(parents=True, exist_ok=True)
    stale_daily.write_text(
        "# 2026-05-03\n\n- User preference: wants to be addressed as Kudret.\n",
        encoding="utf-8",
    )
    (config.workspace_dir / "memory.sqlite").write_text("stale index", encoding="utf-8")

    client = TestClient(app)
    response = client.post("/api/chat/reset", json={})

    assert response.status_code == 200
    payload = response.json()
    assert "memory/2026-05-03.md" not in payload["memoryFiles"]
    assert "memory/2026-05-03.md" not in payload["memoryFileContents"]
    assert not stale_daily.exists()
    assert not (config.workspace_dir / "memory.sqlite").exists()
    assert payload["config"]["dailyMemoryPath"] == "memory/2026-05-07.md"
    assert "memory/2026-05-07.md" in payload["memoryFiles"]


def test_chat_auto_context_loads_memory_today_and_yesterday_only(monkeypatch):
    monkeypatch.setattr(
        demo_app,
        "_now_ms",
        lambda: int(datetime(2026, 5, 7, 12, 0, tzinfo=UTC).timestamp() * 1000),
    )
    results = [
        {
            "path": "MEMORY.md",
            "citation": "Source: MEMORY.md#1",
            "snippet": "Long-term memory",
        },
        {
            "path": "memory/2026-05-07.md",
            "citation": "Source: memory/2026-05-07.md#1",
            "snippet": "Today note",
        },
        {
            "path": "memory/2026-05-06.md",
            "citation": "Source: memory/2026-05-06.md#1",
            "snippet": "Yesterday note",
        },
        {
            "path": "memory/2026-05-03.md",
            "citation": "Source: memory/2026-05-03.md#1",
            "snippet": "Older note",
        },
    ]

    filtered = demo_app._filter_chat_auto_memory_results(results)

    assert [result["path"] for result in filtered] == [
        "MEMORY.md",
        "memory/2026-05-07.md",
        "memory/2026-05-06.md",
    ]


def test_demo_store_uses_openai_embeddings_from_payload(monkeypatch):
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", raising=False)

    store = demo_app.demo_store(
        {
            "openai": {
                "apiKey": "request-key",
                "baseUrl": "https://example.test/v1/",
            }
        }
    )

    assert store.embeddings.provider_id == "openai-compatible"
    assert store.embeddings.model == "text-embedding-3-small"
    assert store.embeddings.api_key == "request-key"
    assert store.embeddings.base_url == "https://example.test/v1"


def test_demo_store_requires_openai_embedding_key(monkeypatch):
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_BASE_URL", "https://api.openai.com/v1")

    try:
        demo_app.demo_store({})
    except demo_app.DemoPayloadError as exc:
        assert "openai embeddings require an API key" in str(exc)
    else:
        raise AssertionError("expected DemoPayloadError")


def test_demo_store_falls_back_to_fake_embeddings_for_openrouter(monkeypatch):
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_BASE_URL", "https://openrouter.ai/api/v1")

    store = demo_app.demo_store({})

    assert store.embeddings.provider_id == "fake"


def test_load_env_defaults_reads_dotenv_without_overwriting_existing_values(
    tmp_path: Path, monkeypatch
):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "MEMORY_CORE_DEMO_OPENAI_API_KEY=file-key",
                "MEMORY_CORE_DEMO_OPENAI_BASE_URL=https://from-file.example/v1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MEMORY_CORE_DEMO_OPENAI_BASE_URL", "https://existing.example/v1")

    demo_app._load_env_defaults(env_path)

    assert demo_app.os.environ["MEMORY_CORE_DEMO_OPENAI_API_KEY"] == "file-key"
    assert demo_app.os.environ["MEMORY_CORE_DEMO_OPENAI_BASE_URL"] == "https://existing.example/v1"


def test_chat_send_runs_recall_and_returns_turn(monkeypatch):
    engine = StubOpenAIEngine()
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: engine)
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
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
    assert engine.workspace_contexts
    workspace_root = os.path.abspath(demo_app.DEMO_WORKSPACE)
    assert f"## {workspace_root}/AGENTS.md" in engine.workspace_contexts[-1]
    assert f"## {workspace_root}/MEMORY.md" in engine.workspace_contexts[-1]


def test_chat_send_writes_indexable_session_transcript(monkeypatch):
    monkeypatch.setattr(
        demo_app,
        "_now_ms",
        lambda: int(datetime(2026, 5, 7, 12, 0, tzinfo=UTC).timestamp() * 1000),
    )
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: StubOpenAIEngine())
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.post(
        "/api/chat/send",
        json={
            "message": "we discussed session corpus",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
            "autoFlush": False,
        },
    )

    assert response.status_code == 200
    transcript_path = (
        demo_app.DEMO_WORKSPACE / "memory" / ".dreams" / "session-corpus" / "2026-05-07.md"
    )
    transcript = transcript_path.read_text(encoding="utf-8")
    assert transcript.startswith("# Session transcript 2026-05-07")
    assert "[chat] User: we discussed session corpus" in transcript
    assert "[chat] Assistant: stub response to we discussed session corpus" in transcript


def test_chat_send_exposes_live_transcript_context_without_flush(monkeypatch):
    class RecordingEngine(StubOpenAIEngine):
        def __init__(self):
            super().__init__()
            self.message_batches = []

        def complete(self, *, messages, memory_context, workspace_context=""):
            self.message_batches.append([(message.role, message.content) for message in messages])
            return super().complete(
                messages=messages,
                memory_context=memory_context,
                workspace_context=workspace_context,
            )

    engine = RecordingEngine()
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: engine)
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    first = client.post(
        "/api/chat/send",
        json={
            "message": "Bana Doruk diye hitap et.",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
            "autoFlush": False,
        },
    )
    second = client.post(
        "/api/chat/send",
        json={
            "message": "Bana nasil hitap edeceksin?",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
            "autoFlush": False,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert engine.message_batches[-1] == [
        ("user", "Bana Doruk diye hitap et."),
        ("assistant", "stub response to Bana Doruk diye hitap et."),
        ("user", "Bana nasil hitap edeceksin?"),
    ]
    latest_turn = second.json()["turns"][-1]
    assert latest_turn["transcriptMessages"] == [
        {"role": "user", "content": "Bana Doruk diye hitap et."},
        {"role": "assistant", "content": "stub response to Bana Doruk diye hitap et."},
        {"role": "user", "content": "Bana nasil hitap edeceksin?"},
    ]
    assert latest_turn["flush"] is None


def test_chat_send_windows_live_transcript_and_reports_omitted_messages(monkeypatch):
    class RecordingEngine(StubOpenAIEngine):
        def __init__(self):
            super().__init__()
            self.message_batches = []

        def complete(self, *, messages, memory_context, workspace_context=""):
            self.message_batches.append([(message.role, message.content) for message in messages])
            return super().complete(
                messages=messages,
                memory_context=memory_context,
                workspace_context=workspace_context,
            )

    engine = RecordingEngine()
    monkeypatch.setattr(demo_app, "DEMO_TRANSCRIPT_MESSAGE_WINDOW", 3)
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: engine)
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    for message in ("turn one", "turn two", "turn three"):
        response = client.post(
            "/api/chat/send",
            json={
                "message": message,
                "engine": "openai",
                "openai": {"apiKey": "request-key"},
                "autoFlush": False,
            },
        )
        assert response.status_code == 200

    assert engine.message_batches[-1] == [
        ("assistant", "stub response to turn one"),
        ("user", "turn two"),
        ("assistant", "stub response to turn two"),
        ("user", "turn three"),
    ]
    latest_turn = response.json()["turns"][-1]
    assert latest_turn["transcriptOmittedCount"] == 1
    assert latest_turn["omittedTranscriptMessages"] == [
        {"role": "user", "content": "turn one"},
    ]
    assert latest_turn["transcriptMessages"] == [
        {"role": "assistant", "content": "stub response to turn one"},
        {"role": "user", "content": "turn two"},
        {"role": "assistant", "content": "stub response to turn two"},
        {"role": "user", "content": "turn three"},
    ]


def test_chat_send_applies_live_transcript_char_budget(monkeypatch):
    class RecordingEngine(StubOpenAIEngine):
        def __init__(self):
            super().__init__()
            self.message_batches = []

        def complete(self, *, messages, memory_context, workspace_context=""):
            self.message_batches.append([(message.role, message.content) for message in messages])
            return super().complete(
                messages=messages,
                memory_context=memory_context,
                workspace_context=workspace_context,
            )

    engine = RecordingEngine()
    monkeypatch.setattr(demo_app, "DEMO_TRANSCRIPT_MESSAGE_WINDOW", 40)
    monkeypatch.setattr(demo_app, "DEMO_TRANSCRIPT_CHAR_BUDGET", 55)
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: engine)
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    first = client.post(
        "/api/chat/send",
        json={
            "message": "very long first turn that should fall out",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
            "autoFlush": False,
        },
    )
    second = client.post(
        "/api/chat/send",
        json={
            "message": "short",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
            "autoFlush": False,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert engine.message_batches[-1] == [("user", "short")]
    latest_turn = second.json()["turns"][-1]
    assert latest_turn["transcriptOmittedCount"] == 2
    assert latest_turn["transcriptMessages"] == [{"role": "user", "content": "short"}]


def test_chat_manual_flush_updates_latest_turn_and_memory_file(monkeypatch):
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: StubOpenAIEngine())
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
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
    assert latest["flush"]["parsed"]["target"] in response.json()["memoryFiles"]


def test_chat_send_auto_flush_updates_turn(monkeypatch):
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: StubOpenAIEngine())
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
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
    assert response.json()["turns"][-1]["promotion"] is None


def test_chat_send_auto_flush_records_daily_signal(monkeypatch):
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: StubOpenAIEngine())
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.post(
        "/api/chat/send",
        json={
            "message": "User preference: address me as Kudret.",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
            "autoFlush": True,
        },
    )

    assert response.status_code == 200
    store_path = demo_app.demo_config().workspace_dir / "memory" / ".dreams" / "short-term-recall.json"
    assert '"dailyCount": 1' in store_path.read_text(encoding="utf-8")
    assert "address me as Kudret" in store_path.read_text(encoding="utf-8")
    assert response.json()["turns"][-1]["promotion"] is None


def test_record_daily_memory_flush_matches_appended_daily_line():
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    config = demo_app.demo_config()
    daily = config.workspace_dir / "memory" / "2026-05-03.md"
    daily.write_text(
        "# 2026-05-03\n\n- User preference: address me as Kudret.\n",
        encoding="utf-8",
    )

    changed = record_daily_memory_flush(
        config=config,
        target="memory/2026-05-03.md",
        entry="- User preference: address me as Kudret.\n",
        now_ms=demo_app.DEMO_NOW_MS,
    )

    store_path = config.workspace_dir / "memory" / ".dreams" / "short-term-recall.json"
    assert changed == 1
    text = store_path.read_text(encoding="utf-8")
    assert '"dailyCount": 1' in text
    assert '"recallCount": 0' in text
    assert "User preference: address me as Kudret." in text


def test_short_term_promotion_writes_repeated_recalls_to_memory_md():
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    config = demo_app.demo_config()
    daily = config.workspace_dir / "memory" / "2026-05-03.md"
    daily.write_text(
        "# 2026-05-03\n\n- User was fired from work.\n",
        encoding="utf-8",
    )

    for offset, query in enumerate(
        ["job loss", "fired from work", "work situation", "career event", "employment status"]
    ):
        record_short_term_recalls(
            config=config,
            query=query,
            results=[
                {
                    "source": "memory",
                    "path": "memory/2026-05-03.md",
                    "startLine": 3,
                    "endLine": 3,
                    "snippet": "- User was fired from work.",
                    "score": 1,
                }
            ],
            now_ms=demo_app.DEMO_NOW_MS + offset * 24 * 60 * 60 * 1000,
        )

    promotion = run_short_term_promotion(
        config=config,
        store=fake_demo_store(),
        now_ms=demo_app.DEMO_NOW_MS + 4 * 24 * 60 * 60 * 1000,
        timezone=demo_app.DEMO_TIMEZONE,
    )

    memory_text = (config.workspace_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert promotion.parsed.should_write is True
    assert promotion.target == "MEMORY.md"
    assert "Promoted From Short-Term Memory" in memory_text
    assert "User was fired from work." in memory_text


def test_memory_promote_endpoint_applies_short_term_promotions(monkeypatch):
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
    monkeypatch.setattr(
        demo_app,
        "_now_ms",
        lambda: demo_app.DEMO_NOW_MS + 4 * 24 * 60 * 60 * 1000,
    )
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    config = demo_app.demo_config()
    daily = config.workspace_dir / "memory" / "2026-05-03.md"
    daily.write_text(
        "# 2026-05-03\n\n- User was fired from work.\n",
        encoding="utf-8",
    )
    for offset, query in enumerate(
        ["job loss", "fired from work", "work situation", "career event", "employment status"]
    ):
        record_short_term_recalls(
            config=config,
            query=query,
            results=[
                {
                    "source": "memory",
                    "path": "memory/2026-05-03.md",
                    "startLine": 3,
                    "endLine": 3,
                    "snippet": "- User was fired from work.",
                    "score": 1,
                }
            ],
            now_ms=demo_app.DEMO_NOW_MS + offset * 24 * 60 * 60 * 1000,
        )

    response = client.post(
        "/api/memory/promote",
        json={"openai": {"apiKey": "request-key"}},
    )

    assert response.status_code == 200
    assert response.json()["promotionSweep"]["parsed"]["shouldWrite"] is True
    candidate = response.json()["promotionSweep"]["evaluatedCandidates"][0]
    assert candidate["reasons"] == []
    assert candidate["ageDays"] >= 0
    assert candidate["conceptTags"]
    assert candidate["components"]["frequency"] > 0
    assert "phaseBoost" in candidate["components"]
    assert "User was fired from work." in response.json()["memoryFileContents"]["MEMORY.md"]


def test_memory_promote_endpoint_rejects_single_daily_signal_like_openclaw(monkeypatch):
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    config = demo_app.demo_config()
    daily = config.workspace_dir / "memory" / "2026-05-03.md"
    daily.write_text(
        "# 2026-05-03\n\n- User preference: wants to be addressed as Kudret.\n",
        encoding="utf-8",
    )
    record_daily_memory_flush(
        config=config,
        target="memory/2026-05-03.md",
        entry="- User preference: wants to be addressed as Kudret.\n",
        now_ms=demo_app.DEMO_NOW_MS,
    )

    response = client.post(
        "/api/memory/promote",
        json={"openai": {"apiKey": "request-key"}},
    )

    candidate = response.json()["promotionSweep"]["evaluatedCandidates"][0]
    assert response.status_code == 200
    assert response.json()["promotionSweep"]["parsed"]["shouldWrite"] is False
    assert candidate["signalCount"] == 1
    assert "signals 1 < 3" in candidate["reasons"]
    assert "unique queries/days 1 < 3" in candidate["reasons"]
    assert "User preference: wants to be addressed as Kudret." not in response.json()[
        "memoryFileContents"
    ]["MEMORY.md"]


def test_memory_audit_and_repair_endpoints(monkeypatch):
    del monkeypatch
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    store_path = demo_app.DEMO_WORKSPACE / "memory" / ".dreams" / "short-term-recall.json"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("{not-json", encoding="utf-8")

    audit = client.get("/api/memory/audit")
    repair = client.post("/api/memory/repair", json={})

    assert audit.status_code == 200
    assert audit.json()["memoryAudit"]["issues"][0]["code"] == "recall-store-unreadable"
    assert repair.status_code == 200
    assert repair.json()["memoryRepair"]["changed"] is True
    assert {
        issue["code"] for issue in repair.json()["memoryAudit"]["issues"]
    } == set()


def test_dreaming_endpoint_runs_light_sweep(monkeypatch):
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.post(
        "/api/dreaming/run",
        json={"phase": "light", "openai": {"apiKey": "request-key"}},
    )

    assert response.status_code == 200
    assert response.json()["dreamingSweep"]["phase"] == "light"


def test_dreaming_endpoint_reindexes_changed_files(monkeypatch):
    store = CountingStore()
    monkeypatch.setattr(demo_app, "demo_store", lambda payload: store)
    monkeypatch.setattr(
        demo_app,
        "run_dreaming_sweep",
        lambda **kwargs: {"phase": "rem", "filesChanged": ["DREAMS.md"]},
    )
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.post(
        "/api/dreaming/run",
        json={"phase": "rem", "openai": {"apiKey": "request-key"}},
    )

    assert response.status_code == 200
    assert store.reindex_calls == 1
    assert response.json()["dreamingSweep"]["indexedFiles"] == 7
    assert response.json()["dreamingSweep"]["chunks"] == 11
    assert response.json()["dreamingSweep"]["reindexError"] is None


def test_dreaming_endpoint_preserves_sweep_when_reindex_metadata_fails(monkeypatch):
    store = FailingChunkStore()
    monkeypatch.setattr(demo_app, "demo_store", lambda payload: store)
    monkeypatch.setattr(
        demo_app,
        "run_dreaming_sweep",
        lambda **kwargs: {
            "phase": "rem",
            "filesChanged": ["DREAMS.md"],
            "candidateCount": 0,
        },
    )
    client = TestClient(app)
    client.post("/api/chat/reset", json={})

    response = client.post(
        "/api/dreaming/run",
        json={"phase": "rem", "openai": {"apiKey": "request-key"}},
    )

    sweep = response.json()["dreamingSweep"]
    assert response.status_code == 200
    assert sweep["phase"] == "rem"
    assert sweep["filesChanged"] == ["DREAMS.md"]
    assert sweep["indexedFiles"] == 0
    assert sweep["chunks"] == 0
    assert "chunk count failed" in sweep["reindexError"]


def test_reset_clears_dreaming_artifacts():
    client = TestClient(app)
    dreams = demo_app.DEMO_WORKSPACE / "memory" / ".dreams"
    dreams.mkdir(parents=True, exist_ok=True)
    (dreams / "phase-signals.json").write_text("{}", encoding="utf-8")

    client.post("/api/chat/reset", json={})

    assert not (demo_app.DEMO_WORKSPACE / "memory" / ".dreams" / "phase-signals.json").exists()


def test_reset_clears_memory_endpoint_state(monkeypatch):
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    store_path = demo_app.DEMO_WORKSPACE / "memory" / ".dreams" / "short-term-recall.json"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("{not-json", encoding="utf-8")
    client.get("/api/memory/audit")
    client.post("/api/memory/repair", json={})
    client.post("/api/dreaming/run", json={"phase": "light", "openai": {"apiKey": "request-key"}})

    response = client.post("/api/chat/reset", json={})

    assert response.status_code == 200
    assert response.json()["dreamingSweep"] is None
    assert response.json()["memoryAudit"] is None
    assert response.json()["memoryRepair"] is None


def test_chat_send_defaults_to_auto_flush(monkeypatch):
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: StubOpenAIEngine())
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
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
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
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


@pytest.mark.parametrize("endpoint", ["/api/chat/send", "/api/chat/send-stream"])
def test_chat_send_records_raw_hits_without_source_citation(monkeypatch, endpoint):
    # Upstream records the raw memory_search hits (tools.ts queueShortTermRecallTracking);
    # the "Source: path#La-Lb" citation must not become its own recall entry.
    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: StubOpenAIEngine())
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
    client = TestClient(app)
    client.post("/api/chat/reset", json={})
    today = demo_app._local_date(demo_app._now_ms()).isoformat()
    daily = demo_app.DEMO_WORKSPACE / "memory" / f"{today}.md"
    daily.write_text(f"# {today}\n\n- Glacier backups run weekly on Sunday.\n", encoding="utf-8")

    response = client.post(
        endpoint,
        json={
            "message": "glacier backups",
            "engine": "openai",
            "openai": {"apiKey": "request-key"},
            "autoFlush": False,
        },
    )

    assert response.status_code == 200
    store_path = demo_app.DEMO_WORKSPACE / "memory" / ".dreams" / "short-term-recall.json"
    entries = json.loads(store_path.read_text(encoding="utf-8"))["entries"]
    assert f"memory:memory/{today}.md:3:3" in entries
    assert not [key for key, entry in entries.items() if "Source:" in entry["snippet"]]


def test_chat_send_unconfigured_openai_returns_json_error(monkeypatch):
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MEMORY_CORE_DEMO_OPENAI_MODEL", raising=False)
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

        def complete(self, *, messages, memory_context, workspace_context=""):
            del messages, memory_context, workspace_context
            raise RuntimeError("boom")

        def flush(self, *, system_prompt, prompt, transcript, target):
            del system_prompt, prompt, transcript, target
            raise AssertionError("flush should not be called")

    monkeypatch.setattr(demo_app, "_chat_engine", lambda payload: BrokenEngine())
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
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
    monkeypatch.setattr(demo_app, "demo_store", fake_demo_store)
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


def test_parity_trace_endpoint_returns_steps(monkeypatch):
    monkeypatch.setattr(
        demo_app,
        "build_parity_trace",
        lambda: {
            "oracle": {"available": True, "commit": "abc123"},
            "steps": [
                {
                    "id": "deep-policy",
                    "label": "Deep dreaming policy values",
                    "python": {"decision": "computed", "values": {"minScore": 0.75}, "reasons": []},
                    "openclaw": {"decision": "computed", "values": {"minScore": 0.8}, "reasons": []},
                    "diff": {"status": "mismatch", "details": ["minScore differs"]},
                }
            ],
        },
        raising=False,
    )
    client = TestClient(app)

    response = client.post("/api/parity/trace", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["oracle"]["commit"] == "abc123"
    assert payload["steps"][0]["id"] == "deep-policy"
    assert payload["steps"][0]["diff"]["status"] == "mismatch"
