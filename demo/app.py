from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from demo.chat_engine import (
    ChatEngine,
    ChatMessage,
    OpenAICompatibleChatEngine,
    engine_status,
)
from demo.chat_session import ChatSessionState
from demo.dreaming import run_dreaming_sweep
from demo.memory_flush import MemoryFlushRun, ParsedFlushOutput, run_memory_flush
from demo.short_term_promotion import (
    DEFAULT_PROMOTION_MIN_RECALL_COUNT,
    DEFAULT_PROMOTION_MIN_SCORE,
    DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
    MemoryPromotionRun,
    SHORT_TERM_LOCK_RELATIVE_PATH,
    SHORT_TERM_STORE_RELATIVE_PATH,
    audit_short_term_promotion_artifacts,
    record_daily_memory_flush,
    record_short_term_recalls,
    repair_short_term_promotion_artifacts,
    run_short_term_promotion,
)
from memory_core.config import MemoryConfig
from memory_core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.memory_flush import MemoryFlushPlan, build_memory_flush_plan
from memory_core.prompt_section import build_prompt_section
from memory_core.tools.memory_get import memory_get
from memory_core.tools.memory_search import memory_search
from memory_core.workspace import MemoryWorkspace

DEMO_ROOT = Path(__file__).resolve().parent
DEMO_WORKSPACE = Path(tempfile.gettempdir()) / "openclaw-memory-demo-workspace"
DEMO_TIMEZONE = "Europe/Istanbul"
DEMO_NOW_MS = 1777824000000
CHAT_STATE = ChatSessionState()
PROMOTION_SWEEP: dict[str, Any] | None = None
DREAMING_SWEEP: dict[str, Any] | None = None
MEMORY_AUDIT: dict[str, Any] | None = None
MEMORY_REPAIR: dict[str, Any] | None = None

DEFAULT_MEMORY_MD = """# MEMORY.md - Long-Term Memory

This file is the curated long-term memory for the main session.

Use it for durable, high-signal context:

- Important user preferences
- Stable personal or project context
- Significant decisions
- Lessons worth carrying into future sessions

Keep raw day-to-day notes in `memory/YYYY-MM-DD.md`. Periodically promote only the distilled facts that still matter here.

Do not store secrets unless the user explicitly asks. Keep this file concise, accurate, and useful.
"""
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

app = FastAPI(title="OpenClaw Memory Demo")
app.mount("/static", StaticFiles(directory=DEMO_ROOT / "static"), name="static")
templates = Jinja2Templates(directory=DEMO_ROOT / "templates")


def demo_config() -> MemoryConfig:
    DEMO_WORKSPACE.mkdir(parents=True, exist_ok=True)
    return MemoryConfig(
        workspace_dir=DEMO_WORKSPACE,
        store_path=DEMO_WORKSPACE / "memory.sqlite",
    )


def demo_store(payload: dict[str, Any] | None = None) -> SQLiteMemoryStore:
    return SQLiteMemoryStore(demo_config(), _embedding_provider(payload or {}))


class DemoPayloadError(ValueError):
    pass


def _json_error(message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=400)


def _safe_exception_message(exc: Exception, secrets: tuple[str, ...] = ()) -> str:
    message = str(exc) or exc.__class__.__name__
    for secret in (*secrets, os.getenv("OPENCLAW_DEMO_OPENAI_API_KEY") or ""):
        if secret:
            message = message.replace(secret, "[redacted]")
    return f"{exc.__class__.__name__}: {message}"


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


def _chat_engine(payload: dict[str, Any]) -> ChatEngine:
    name = str(payload.get("engine", "openai"))
    if name != "openai":
        raise DemoPayloadError("engine must be 'openai'")
    openai_payload = payload.get("openai", {})
    if not isinstance(openai_payload, dict):
        raise DemoPayloadError("openai config must be an object")
    engine = OpenAICompatibleChatEngine.from_config(
        base_url=_optional_text(openai_payload.get("baseUrl")),
        api_key=_optional_text(openai_payload.get("apiKey")),
        model=_optional_text(openai_payload.get("model")),
    )
    if engine is None:
        raise DemoPayloadError("openai engine requires an API key")
    return engine


def _embedding_provider(payload: dict[str, Any]) -> OpenAICompatibleEmbeddingProvider:
    openai_payload = _openai_payload(payload)
    api_key = _optional_text(openai_payload.get("apiKey")) or os.getenv(
        "OPENCLAW_DEMO_OPENAI_API_KEY", ""
    )
    if not api_key:
        raise DemoPayloadError("openai embeddings require an API key")
    return OpenAICompatibleEmbeddingProvider(
        base_url=_optional_text(openai_payload.get("baseUrl"))
        or os.getenv("OPENCLAW_DEMO_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=api_key,
        model=os.getenv("OPENCLAW_DEMO_OPENAI_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
    )


def _openai_payload(payload: dict[str, Any]) -> dict[str, Any]:
    openai_payload = payload.get("openai", {})
    if not isinstance(openai_payload, dict):
        raise DemoPayloadError("openai config must be an object")
    return openai_payload


def _payload_api_key(payload: dict[str, Any]) -> str:
    openai_payload = _openai_payload(payload)
    return _optional_text(openai_payload.get("apiKey")) or ""


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _memory_context_from_results(results: list[dict[str, Any]]) -> list[str]:
    context: list[str] = []
    for result in results:
        citation = str(result.get("citation") or result.get("path") or "memory")
        snippet = str(result.get("snippet") or "").strip()
        if snippet:
            context.append(f"{citation}: {snippet}")
    return context


def _filter_chat_auto_memory_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed_paths = {"MEMORY.md", "memory.md", *_active_daily_memory_paths(_now_ms())}
    return [result for result in results if str(result.get("path") or "") in allowed_paths]


def _active_daily_memory_paths(now_ms: int) -> set[str]:
    local_today = _local_date(now_ms)
    local_yesterday = local_today.fromordinal(local_today.toordinal() - 1)
    return {
        f"memory/{local_today.isoformat()}.md",
        f"memory/{local_yesterday.isoformat()}.md",
    }


def _local_date(now_ms: int):
    try:
        timezone = ZoneInfo(DEMO_TIMEZONE)
    except ZoneInfoNotFoundError:
        timezone = UTC
    return datetime.fromtimestamp(now_ms / 1000, tz=UTC).astimezone(timezone).date()


def _chat_messages(message: str) -> list[ChatMessage]:
    messages = CHAT_STATE.transcript_messages()
    messages.append(ChatMessage(role="user", content=message))
    return messages


def _now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def _demo_flush_plan() -> MemoryFlushPlan:
    return build_memory_flush_plan(
        workspace_dir=demo_config().workspace_dir,
        now_ms=_now_ms(),
        timezone=DEMO_TIMEZONE,
    )


def _memory_files() -> list[str]:
    workspace = MemoryWorkspace(demo_config().workspace_dir)
    discovered = {file.rel_path for file in workspace.discover_memory_files()}
    plan = _demo_flush_plan()
    discovered.update({"MEMORY.md", "DREAMS.md", plan.relative_path})
    return sorted(discovered)


def _memory_file_contents(paths: list[str]) -> dict[str, str]:
    workspace = MemoryWorkspace(demo_config().workspace_dir)
    contents: dict[str, str] = {}
    for path in paths:
        try:
            contents[path] = workspace.read_text(path).text
        except FileNotFoundError:
            contents[path] = ""
    return contents


def _state_payload() -> dict[str, Any]:
    config = demo_config()
    plan = _demo_flush_plan()
    memory_files = _memory_files()
    payload = CHAT_STATE.as_dict()
    payload.update(
        {
            "engines": engine_status(),
            "memoryFiles": memory_files,
            "memoryFileContents": _memory_file_contents(memory_files),
            "promotionSweep": PROMOTION_SWEEP,
            "dreamingSweep": DREAMING_SWEEP,
            "memoryAudit": MEMORY_AUDIT,
            "memoryRepair": MEMORY_REPAIR,
            "config": {
                "workspace": str(config.workspace_dir),
                "timezone": DEMO_TIMEZONE,
                "dailyMemoryPath": plan.relative_path,
                "promotion": _promotion_config_payload(),
            },
        }
    )
    return payload


def _promotion_config_payload() -> dict[str, Any]:
    return {
        "openclawDefaults": {
            "minScore": DEFAULT_PROMOTION_MIN_SCORE,
            "minRecallCount": DEFAULT_PROMOTION_MIN_RECALL_COUNT,
            "minUniqueQueries": DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
        },
    }


def _serialize_flush(flush: MemoryFlushRun) -> dict[str, Any]:
    return {
        "target": flush.target,
        "rawText": flush.raw_text,
        "parsed": _serialize_parsed_flush(flush.parsed),
        "diff": flush.diff,
        "indexedFiles": flush.indexed_files,
        "chunks": flush.chunks,
        "reindexError": flush.reindex_error,
    }


def _serialize_promotion(promotion: MemoryPromotionRun) -> dict[str, Any]:
    return {
        "target": promotion.target,
        "rawText": promotion.raw_text,
        "parsed": _serialize_parsed_flush(promotion.parsed),
        "diff": promotion.diff,
        "indexedFiles": promotion.indexed_files,
        "chunks": promotion.chunks,
        "evaluatedCandidates": [
            {
                "path": candidate.path,
                "startLine": candidate.start_line,
                "endLine": candidate.end_line,
                "snippet": candidate.snippet,
                "score": round(candidate.score, 3),
                "recallCount": candidate.recall_count,
                "dailyCount": candidate.daily_count,
                "groundedCount": candidate.grounded_count,
                "signalCount": candidate.signal_count,
                "avgScore": round(candidate.avg_score, 3),
                "maxScore": round(candidate.max_score, 3),
                "uniqueQueries": candidate.unique_queries,
                "contextDiversity": candidate.context_diversity,
                "ageDays": round(candidate.age_days, 3),
                "conceptTags": list(candidate.concept_tags),
                "components": {
                    key: round(value, 3) for key, value in candidate.components.items()
                },
                "reasons": list(candidate.reasons),
            }
            for candidate in promotion.evaluated_candidates
        ],
        "reindexError": promotion.reindex_error,
    }


def _serialize_audit(audit: Any) -> dict[str, Any]:
    config = demo_config()
    return {
        "storePath": str(config.workspace_dir / SHORT_TERM_STORE_RELATIVE_PATH),
        "lockPath": str(config.workspace_dir / SHORT_TERM_LOCK_RELATIVE_PATH),
        "updatedAt": datetime.fromtimestamp(_now_ms() / 1000, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "exists": audit.exists,
        "entryCount": audit.entry_count,
        "promotedCount": audit.promoted_entry_count,
        "spacedEntryCount": audit.spaced_entry_count,
        "conceptTaggedEntryCount": audit.concept_tagged_entry_count,
        "invalidEntryCount": audit.invalid_entry_count,
        "issues": [
            {
                "severity": issue.severity,
                "code": issue.code,
                "message": issue.message,
                "fixable": issue.fixable,
            }
            for issue in audit.issues
        ],
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


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/api/seed")
def seed():
    if DEMO_WORKSPACE.exists():
        shutil.rmtree(DEMO_WORKSPACE)
    DEMO_WORKSPACE.mkdir(parents=True, exist_ok=True)
    (DEMO_WORKSPACE / "memory").mkdir(exist_ok=True)
    daily_plan = _demo_flush_plan()
    daily_path = DEMO_WORKSPACE / daily_plan.relative_path
    daily_date = Path(daily_plan.relative_path).stem
    (DEMO_WORKSPACE / "MEMORY.md").write_text(
        DEFAULT_MEMORY_MD,
        encoding="utf-8",
    )
    daily_path.write_text(
        f"# {daily_date}\n\nDiscussed router VLAN troubleshooting and memory recall parity.\n",
        encoding="utf-8",
    )
    return {"ok": True}


@app.post("/api/reindex")
def reindex(payload: dict[str, Any] | None = None):
    try:
        payload = payload or {}
        config = demo_config()
        store = demo_store(payload)
        indexed_files = store.reindex(MemoryWorkspace(config.workspace_dir))
        return {"indexedFiles": indexed_files, "chunks": store.count_chunks()}
    except DemoPayloadError as exc:
        return _json_error(str(exc))


@app.post("/api/search")
def search(payload: dict):
    try:
        return memory_search(
            demo_config(),
            demo_store(payload),
            query=str(payload.get("query", "")),
            max_results=_required_int(payload, "maxResults", 5),
            min_score=_required_float(payload, "minScore", 0),
            corpus=str(payload.get("corpus") or "all"),
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
    global DREAMING_SWEEP, MEMORY_AUDIT, MEMORY_REPAIR, PROMOTION_SWEEP
    CHAT_STATE.reset()
    PROMOTION_SWEEP = None
    DREAMING_SWEEP = None
    MEMORY_AUDIT = None
    MEMORY_REPAIR = None
    if not bool(payload.get("keepMemory", False)):
        _reset_demo_memory()
    return _state_payload()


@app.post("/api/chat/send")
def chat_send(payload: dict):
    try:
        message = str(payload.get("message", "")).strip()
        if not message:
            raise DemoPayloadError("message is required")
        engine = _chat_engine(payload)
        recall_query = message
        store = demo_store(payload)
        store.reindex(MemoryWorkspace(demo_config().workspace_dir))
        recall = memory_search(
            demo_config(),
            store,
            query=recall_query,
            max_results=5,
            min_score=0,
        )
        recall_results = recall.get("results", [])
        chat_recall_results = _filter_chat_auto_memory_results(recall_results)
        record_short_term_recalls(
            config=demo_config(),
            query=recall_query,
            results=chat_recall_results,
            now_ms=_now_ms(),
        )
        memory_context = _memory_context_from_results(chat_recall_results)
        response = engine.complete(
            messages=_chat_messages(message),
            memory_context=memory_context,
        )
        turn = CHAT_STATE.add_turn(
            user_message=message,
            recall_query=recall_query,
            recall_results=chat_recall_results,
            assistant_response=response.content,
            memory_context=memory_context,
        )
        if bool(payload.get("autoFlush", True)):
            turn.flush = _flush_latest_turn(engine, store)
            _record_daily_flush_signal(turn.flush)
        _write_session_transcript(_now_ms())
        return _state_payload()
    except DemoPayloadError as exc:
        return _json_error(str(exc))
    except Exception as exc:
        return _json_error(f"chat send failed: {_safe_exception_message(exc, (_payload_api_key(payload),))}")


@app.post("/api/chat/send-stream")
def chat_send_stream(payload: dict):
    return StreamingResponse(
        _chat_send_stream_events(payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/chat/flush")
def chat_flush(payload: dict):
    try:
        latest = CHAT_STATE.latest()
        if latest is None:
            raise DemoPayloadError("no chat turn to flush")
        engine = _chat_engine(payload)
        store = demo_store(payload)
        latest.flush = _flush_latest_turn(engine, store)
        _record_daily_flush_signal(latest.flush)
        return _state_payload()
    except DemoPayloadError as exc:
        return _json_error(str(exc))
    except Exception as exc:
        return _json_error(f"chat flush failed: {_safe_exception_message(exc, (_payload_api_key(payload),))}")


@app.post("/api/memory/promote")
def memory_promote(payload: dict):
    global PROMOTION_SWEEP
    try:
        store = demo_store(payload)
        PROMOTION_SWEEP = _promote_short_term(store)
        return _state_payload()
    except DemoPayloadError as exc:
        return _json_error(str(exc))
    except Exception as exc:
        return _json_error(f"memory promote failed: {_safe_exception_message(exc, (_payload_api_key(payload),))}")


@app.get("/api/memory/audit")
def memory_audit():
    global MEMORY_AUDIT
    try:
        MEMORY_AUDIT = _serialize_audit(
            audit_short_term_promotion_artifacts(config=demo_config(), now_ms=_now_ms())
        )
        return _state_payload()
    except Exception as exc:
        return _json_error(f"memory audit failed: {_safe_exception_message(exc)}")


@app.post("/api/memory/repair")
def memory_repair(payload: dict | None = None):
    global MEMORY_REPAIR
    try:
        MEMORY_REPAIR = repair_short_term_promotion_artifacts(
            config=demo_config(), now_ms=_now_ms()
        )
        return _state_payload()
    except Exception as exc:
        payload = payload or {}
        return _json_error(f"memory repair failed: {_safe_exception_message(exc, (_payload_api_key(payload),))}")


@app.post("/api/dreaming/run")
def dreaming_run(payload: dict):
    global DREAMING_SWEEP
    try:
        phase = str(payload.get("phase") or "light")
        store = demo_store(payload)
        DREAMING_SWEEP = run_dreaming_sweep(
            config=demo_config(),
            store=store,
            phase=phase,
            now_ms=_now_ms(),
            timezone=DEMO_TIMEZONE,
        )
        return _state_payload()
    except DemoPayloadError as exc:
        return _json_error(str(exc))
    except Exception as exc:
        return _json_error(f"dreaming run failed: {_safe_exception_message(exc, (_payload_api_key(payload),))}")


def _flush_latest_turn(engine: ChatEngine, store: SQLiteMemoryStore) -> dict[str, Any]:
    return _serialize_flush(
        run_memory_flush(
            config=demo_config(),
            store=store,
            engine=engine,
            transcript=CHAT_STATE.transcript_messages(),
            now_ms=_now_ms(),
            timezone=DEMO_TIMEZONE,
        )
    )


def _promote_short_term(store: SQLiteMemoryStore) -> dict[str, Any]:
    return _serialize_promotion(
        run_short_term_promotion(
            config=demo_config(),
            store=store,
            now_ms=_now_ms(),
            timezone=DEMO_TIMEZONE,
        )
    )


def _record_daily_flush_signal(flush: dict[str, Any] | None) -> None:
    if not flush:
        return
    parsed = flush.get("parsed")
    if not isinstance(parsed, dict) or not parsed.get("shouldWrite"):
        return
    record_daily_memory_flush(
        config=demo_config(),
        target=str(parsed.get("target") or ""),
        entry=str(parsed.get("entry") or ""),
        now_ms=_now_ms(),
    )


def _write_session_transcript(now_ms: int) -> None:
    local_date = _local_date(now_ms).isoformat()
    session_dir = DEMO_WORKSPACE / "memory" / ".dreams" / "session-corpus"
    session_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = session_dir / f"{local_date}.md"
    lines = [f"# Session transcript {local_date}", ""]
    for message in CHAT_STATE.transcript_messages():
        role = "User" if message.role == "user" else "Assistant"
        lines.append(f"[chat] {role}: {message.content.strip()}")
        lines.append("")
    transcript_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _chat_send_stream_events(payload: dict):
    try:
        message = str(payload.get("message", "")).strip()
        if not message:
            raise DemoPayloadError("message is required")
        engine = _chat_engine(payload)
        recall_query = message
        store = demo_store(payload)
        store.reindex(MemoryWorkspace(demo_config().workspace_dir))
        recall = memory_search(
            demo_config(),
            store,
            query=recall_query,
            max_results=5,
            min_score=0,
        )
        recall_results = recall.get("results", [])
        chat_recall_results = _filter_chat_auto_memory_results(recall_results)
        record_short_term_recalls(
            config=demo_config(),
            query=recall_query,
            results=chat_recall_results,
            now_ms=_now_ms(),
        )
        memory_context = _memory_context_from_results(chat_recall_results)
        full_response = []
        for chunk in engine.stream_complete(
            messages=_chat_messages(message),
            memory_context=memory_context,
        ):
            full_response.append(chunk)
            yield _sse("assistant_delta", {"text": chunk})
        turn = CHAT_STATE.add_turn(
            user_message=message,
            recall_query=recall_query,
            recall_results=chat_recall_results,
            assistant_response="".join(full_response),
            memory_context=memory_context,
        )
        if bool(payload.get("autoFlush", True)):
            turn.flush = _flush_latest_turn(engine, store)
            _record_daily_flush_signal(turn.flush)
        _write_session_transcript(_now_ms())
        yield _sse("final_state", _state_payload())
    except DemoPayloadError as exc:
        yield _sse("error", {"error": str(exc)})
    except Exception as exc:
        yield _sse(
            "error",
            {"error": f"chat send failed: {_safe_exception_message(exc, (_payload_api_key(payload),))}"},
        )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
