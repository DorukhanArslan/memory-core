from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from demo.chat_engine import (
    ChatEngine,
    ChatMessage,
    FakeChatEngine,
    OpenAICompatibleChatEngine,
    engine_status,
)
from demo.chat_session import ChatSessionState
from demo.memory_flush import MemoryFlushRun, ParsedFlushOutput, run_memory_flush
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.memory_flush import build_memory_flush_plan
from memory_core.prompt_section import build_prompt_section
from memory_core.tools.memory_get import memory_get
from memory_core.tools.memory_search import memory_search
from memory_core.workspace import MemoryWorkspace

DEMO_ROOT = Path(__file__).resolve().parent
DEMO_WORKSPACE = Path(tempfile.gettempdir()) / "openclaw-memory-demo-workspace"
DEMO_TIMEZONE = "Europe/Istanbul"
DEMO_NOW_MS = 1777824000000
CHAT_STATE = ChatSessionState()

app = FastAPI(title="OpenClaw Memory Demo")
app.mount("/static", StaticFiles(directory=DEMO_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=DEMO_ROOT / "templates")


def demo_config() -> MemoryConfig:
    DEMO_WORKSPACE.mkdir(parents=True, exist_ok=True)
    return MemoryConfig(
        workspace_dir=DEMO_WORKSPACE,
        store_path=DEMO_WORKSPACE / "memory.sqlite",
    )


def demo_store() -> SQLiteMemoryStore:
    return SQLiteMemoryStore(demo_config(), FakeEmbeddingProvider(dimensions=16))


class DemoPayloadError(ValueError):
    pass


def _json_error(message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=400)


def _required_int(payload: dict, key: str, default: int) -> int:
    value = payload.get(key, default)
    if value in (None, ""):
        raise DemoPayloadError(f"{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DemoPayloadError(f"{key} must be an integer") from exc


def _required_float(payload: dict, key: str, default: float) -> float:
    value = payload.get(key, default)
    if value in (None, ""):
        raise DemoPayloadError(f"{key} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise DemoPayloadError(f"{key} must be a number") from exc


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DemoPayloadError("line values must be integers") from exc


def _tools_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        raise DemoPayloadError("tools must be a list")
    return {str(tool) for tool in value}


def _citations_mode(value: Any) -> str:
    mode = str(value if value is not None else "on")
    if mode not in {"on", "off"}:
        raise DemoPayloadError("citationsMode must be 'on' or 'off'")
    return mode


def _chat_engine(name: str) -> ChatEngine:
    if name == "fake":
        return FakeChatEngine()
    if name == "openai":
        engine = OpenAICompatibleChatEngine.from_env()
        if engine is None:
            raise DemoPayloadError(
                "openai engine requires OPENCLAW_DEMO_OPENAI_BASE_URL, "
                "OPENCLAW_DEMO_OPENAI_API_KEY, and OPENCLAW_DEMO_OPENAI_MODEL",
            )
        return engine
    raise DemoPayloadError("engine must be 'fake' or 'openai'")


def _memory_context_from_results(results: list[dict[str, Any]]) -> list[str]:
    context: list[str] = []
    for result in results:
        citation = str(result.get("citation") or result.get("path") or "memory")
        snippet = str(result.get("snippet") or "").strip()
        if snippet:
            context.append(f"{citation}: {snippet}")
    return context


def _chat_messages(message: str) -> list[ChatMessage]:
    messages = CHAT_STATE.transcript_messages()
    messages.append(ChatMessage(role="user", content=message))
    return messages


def _memory_files() -> list[str]:
    workspace = MemoryWorkspace(demo_config().workspace_dir)
    discovered = {file.rel_path for file in workspace.discover_memory_files()}
    plan = build_memory_flush_plan(
        workspace_dir=demo_config().workspace_dir,
        now_ms=DEMO_NOW_MS,
        timezone=DEMO_TIMEZONE,
    )
    discovered.update({"MEMORY.md", "DREAMS.md", plan.relative_path})
    return sorted(discovered)


def _state_payload() -> dict[str, Any]:
    payload = CHAT_STATE.as_dict()
    payload.update(
        {
            "engines": engine_status(),
            "memoryFiles": _memory_files(),
        }
    )
    return payload


def _serialize_flush(flush: MemoryFlushRun) -> dict[str, Any]:
    return {
        "target": flush.target,
        "rawText": flush.raw_text,
        "parsed": _serialize_parsed_flush(flush.parsed),
        "diff": flush.diff,
        "indexedFiles": flush.indexed_files,
        "chunks": flush.chunks,
    }


def _serialize_parsed_flush(parsed: ParsedFlushOutput) -> dict[str, Any]:
    return {
        "shouldWrite": parsed.should_write,
        "target": parsed.target,
        "entry": parsed.entry,
        "reason": parsed.reason,
        "error": parsed.error,
    }


def _reset_demo_memory() -> None:
    seed()
    reindex()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/api/seed")
def seed():
    DEMO_WORKSPACE.mkdir(parents=True, exist_ok=True)
    (DEMO_WORKSPACE / "memory").mkdir(exist_ok=True)
    (DEMO_WORKSPACE / "MEMORY.md").write_text(
        "# Workspace Memory\n\nUser prefers lemon pepper wings with blue cheese.\n",
        encoding="utf-8",
    )
    (DEMO_WORKSPACE / "memory" / "2026-05-03.md").write_text(
        "# 2026-05-03\n\nDiscussed router VLAN troubleshooting and memory recall parity.\n",
        encoding="utf-8",
    )
    return {"ok": True}


@app.post("/api/reindex")
def reindex():
    config = demo_config()
    store = SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=16))
    indexed_files = store.reindex(MemoryWorkspace(config.workspace_dir))
    return {"indexedFiles": indexed_files, "chunks": store.count_chunks()}


@app.post("/api/search")
def search(payload: dict):
    try:
        return memory_search(
            demo_config(),
            demo_store(),
            query=str(payload.get("query", "")),
            max_results=_required_int(payload, "maxResults", 5),
            min_score=_required_float(payload, "minScore", 0),
        )
    except DemoPayloadError as exc:
        return _json_error(str(exc))


@app.post("/api/get")
def get_memory(payload: dict):
    try:
        return memory_get(
            demo_config(),
            path=str(payload.get("path", "MEMORY.md")),
            from_line=_optional_int(payload.get("from")),
            lines=_optional_int(payload.get("lines")),
        )
    except DemoPayloadError as exc:
        return _json_error(str(exc))


@app.post("/api/prompt-preview")
def prompt_preview(payload: dict):
    try:
        return {
            "lines": build_prompt_section(
                _tools_set(payload.get("tools", [])),
                citations_mode=_citations_mode(payload.get("citationsMode", "on")),
            )
        }
    except DemoPayloadError as exc:
        return _json_error(str(exc))


@app.get("/api/chat/state")
def chat_state():
    return _state_payload()


@app.post("/api/chat/reset")
def chat_reset(payload: dict):
    CHAT_STATE.reset()
    if not bool(payload.get("keepMemory", False)):
        _reset_demo_memory()
    return _state_payload()


@app.post("/api/chat/send")
def chat_send(payload: dict):
    try:
        message = str(payload.get("message", "")).strip()
        if not message:
            raise DemoPayloadError("message is required")
        engine = _chat_engine(str(payload.get("engine", "fake")))
        recall_query = message
        store = demo_store()
        recall = memory_search(
            demo_config(),
            store,
            query=recall_query,
            max_results=5,
            min_score=0,
        )
        recall_results = recall.get("results", [])
        memory_context = _memory_context_from_results(recall_results)
        response = engine.complete(
            messages=_chat_messages(message),
            memory_context=memory_context,
        )
        turn = CHAT_STATE.add_turn(
            user_message=message,
            recall_query=recall_query,
            recall_results=recall_results,
            assistant_response=response.content,
            memory_context=memory_context,
        )
        if bool(payload.get("autoFlush", False)):
            turn.flush = _flush_latest_turn(engine)
        return _state_payload()
    except DemoPayloadError as exc:
        return _json_error(str(exc))


@app.post("/api/chat/flush")
def chat_flush(payload: dict):
    try:
        latest = CHAT_STATE.latest()
        if latest is None:
            raise DemoPayloadError("no chat turn to flush")
        engine = _chat_engine(str(payload.get("engine", "fake")))
        latest.flush = _flush_latest_turn(engine)
        return _state_payload()
    except DemoPayloadError as exc:
        return _json_error(str(exc))


def _flush_latest_turn(engine: ChatEngine) -> dict[str, Any]:
    return _serialize_flush(
        run_memory_flush(
            config=demo_config(),
            store=demo_store(),
            engine=engine,
            transcript=CHAT_STATE.transcript_messages(),
            now_ms=DEMO_NOW_MS,
            timezone=DEMO_TIMEZONE,
        )
    )
