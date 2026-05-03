from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.prompt_section import build_prompt_section
from memory_core.tools.memory_get import memory_get
from memory_core.tools.memory_search import memory_search
from memory_core.workspace import MemoryWorkspace

DEMO_ROOT = Path(__file__).resolve().parent
DEMO_WORKSPACE = DEMO_ROOT / "workspace"

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


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


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
    return memory_search(
        demo_config(),
        demo_store(),
        query=str(payload.get("query", "")),
        max_results=int(payload.get("maxResults", 5)),
        min_score=float(payload.get("minScore", 0)),
    )


@app.post("/api/get")
def get_memory(payload: dict):
    return memory_get(
        demo_config(),
        path=str(payload.get("path", "MEMORY.md")),
        from_line=_optional_int(payload.get("from")),
        lines=_optional_int(payload.get("lines")),
    )


@app.post("/api/prompt-preview")
def prompt_preview(payload: dict):
    return {
        "lines": build_prompt_section(
            set(payload.get("tools", [])),
            citations_mode=str(payload.get("citationsMode", "on")),
        )
    }
