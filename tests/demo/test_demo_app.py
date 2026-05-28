from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

import demo.app as demo_app
from demo.chat_engine import ChatResponse, FlushModelOutput
from demo.short_term_promotion import (
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
    assert "gpt-5.2" in response.text
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
    assert "height: 100dvh" in response.text
    assert "grid-template-rows: auto minmax(0, 1fr) minmax(260px, 0.45fr)" in response.text
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
    ]
    assert "workspaceFileContents" in payload
    assert "Operating Instructions" in payload["workspaceFileContents"]["AGENTS.md"]
    assert "Persona and Tone" in payload["workspaceFileContents"]["SOUL.md"]
    assert "Workspace Files (injected)" in payload["workspaceContext"]
    assert "### AGENTS.md" in payload["workspaceContext"]
    assert "### MEMORY.md" in payload["workspaceContext"]
    assert "MEMORY.md" in payload["memoryFileContents"]
    assert "Long-Term Memory" in payload["memoryFileContents"]["MEMORY.md"]
    assert "OpenClaw" not in payload["memoryFileContents"]["MEMORY.md"]
    assert payload["config"]["workspace"]
    assert payload["config"]["timezone"] == "Europe/Istanbul"
    assert payload["config"]["dailyMemoryPath"] == demo_app._demo_flush_plan().relative_path
    assert payload["config"]["promotion"]["openclawDefaults"]["minRecallCount"] == 3
    assert payload["config"]["promotion"]["openclawDefaults"]["minUniqueQueries"] == 3
    assert payload["config"]["promotion"]["openclawDefaults"]["minScore"] == 0.8
    assert payload["config"]["promotion"]["openclawDefaults"]["enabled"] is False
    assert payload["config"]["promotion"]["openclawDefaults"]["limit"] == 10
    assert payload["config"]["promotion"]["openclawDefaults"]["maxAgeDays"] == 30
    assert payload["turns"] == []


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
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_API_KEY", raising=False)

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
    monkeypatch.delenv("OPENCLAW_DEMO_OPENAI_API_KEY", raising=False)

    try:
        demo_app.demo_store({})
    except demo_app.DemoPayloadError as exc:
        assert "openai embeddings require an API key" in str(exc)
    else:
        raise AssertionError("expected DemoPayloadError")


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
    assert "### AGENTS.md" in engine.workspace_contexts[-1]
    assert "### MEMORY.md" in engine.workspace_contexts[-1]


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
