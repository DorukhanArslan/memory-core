"""Endpoints kept from the first Lab (DESIGN §4.1): ``/api/seed``, ``/api/reindex``,
``/api/search``, ``/api/get``, ``/api/prompt-preview``, ``/api/parity/trace``, the
consolidation sweeps and the live SDK task. Thin adapters over the package, like
:mod:`demo.lab_api`.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

from starlette.concurrency import iterate_in_threadpool

from demo.chat_engine import OpenAICompatibleChatEngine
from demo.lab_consolidation import run_audit, run_dreaming, run_promotion, run_repair
from demo.lab_events import sse_frame
from demo.lab_flush import LAB_FORCED_REASON, flush_decision, forced_flush_blocked, run_flush_turn
from demo.lab_runtime import (
    LabError,
    LabRuntime,
    optional_text,
    redact_payload,
    redact_secrets,
    safe_exception_message,
    validate_id,
)
from demo.live_task_demo import (
    DEFAULT_LIVE_TASK_SESSION_ID,
    DEFAULT_LIVE_TASK_SUBJECT_ID,
    LiveTaskDemoState,
)
from demo.parity_trace import build_parity_trace
from memory_core.live import LIVE_TURN_FAILED
from memory_core.prompt_section import build_prompt_section
from memory_core.tools.memory_get import memory_get
from memory_core.tools.common import MemoryToolInputError
from memory_core.tools.memory_search import (
    MEMORY_SEARCH_TOOL_COOLDOWN_MS,
    MEMORY_SEARCH_TOOL_TIMEOUT_MS,
    execute_memory_search_tool,
    memory_search_tool_cooldown_key,
    memory_search_tool_cooldown_remaining,
)

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _optional_int(value: Any, name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise LabError(400, f"{name} must be an integer", code="invalid_number") from exc


def build_kept_router(lab: LabRuntime) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/seed")
    def seed():
        with lab.locked():
            lab.reset_workspace("seeded")
        return {"ok": True}

    @router.post("/reindex")
    def reindex(payload: dict = Body(default={})):
        lab.ensure_exists()
        embedding = lab.resolve_embedding(payload)
        store = lab.store(embedding, mode=payload.get("mode"))
        try:
            result = lab.reindex(store)
        except Exception as exc:
            raise LabError(
                502,
                f"reindex failed: {safe_exception_message(exc, lab.secret_values(payload))}",
                code="reindex_failed",
                redacted=True,
            ) from exc
        return {**result, "mode": payload.get("mode") or lab.default_search_mode(embedding),
                "embeddings": embedding.public()}

    @router.post("/get")
    def get_memory(payload: dict = Body(...)):
        lab.ensure_exists()
        return memory_get(
            lab.config(),
            path=str(payload.get("path", "MEMORY.md")),
            from_line=_optional_int(payload.get("from"), "from"),
            lines=_optional_int(payload.get("lines"), "lines"),
        )

    @router.post("/prompt-preview")
    def prompt_preview(payload: dict = Body(...)):
        tools = payload.get("tools", [])
        if not isinstance(tools, list):
            raise LabError(400, "tools must be a list", code="invalid_payload")
        mode = str(payload.get("citationsMode") if payload.get("citationsMode") is not None else "on")
        if mode not in {"on", "off"}:
            raise LabError(400, "citationsMode must be 'on' or 'off'", code="invalid_payload")
        return {"lines": build_prompt_section({str(tool) for tool in tools}, citations_mode=mode)}

    @router.post("/parity/trace")
    def parity_trace(payload: dict | None = Body(default=None)):
        del payload
        return build_parity_trace()

    @router.post("/search")
    def search(payload: dict = Body(...)):
        """The memory_search contract for the playground (DESIGN §4.1, changed).

        ``mode`` picks ``FeatureFlags(vector_search, text_search)``: hybrid, vector or
        text. Without a real embedding endpoint the Lab is FTS-only (Q9): text works,
        hybrid/vector answer 400 ``fts_only`` and no embedder is ever built.
        """
        lab.ensure_exists()
        return run_search(lab, payload)

    @router.post("/memory/promote")
    def memory_promote(payload: dict = Body(default={})):
        lab.ensure_exists()
        with lab.locked():
            return run_promotion(lab, payload)

    @router.get("/memory/audit")
    def memory_audit():
        lab.ensure_exists()
        return run_audit(lab)

    @router.post("/memory/repair")
    def memory_repair(payload: dict | None = Body(default=None)):
        del payload
        lab.ensure_exists()
        with lab.locked():
            return run_repair(lab)

    @router.post("/dreaming/run")
    def dreaming_run(payload: dict = Body(default={})):
        lab.ensure_exists()
        with lab.locked():
            return run_dreaming(lab, payload)

    @router.post("/chat/flush")
    def chat_flush(payload: dict = Body(default={})):
        """``/flush``: run the flush turn now (Lab action, reason ``lab_forced``).

        It skips only the token gate: like upstream's forced-by-size path it still
        honours the same-compaction guard, so a second ``/flush`` reports
        ``already_flushed`` and writes nothing.
        """
        from demo.lab_api import resolve_chat_engine

        lab.ensure_exists()
        session = lab.session(str(payload.get("sessionKind") or "main"))
        engine = resolve_chat_engine(lab, payload)
        if getattr(engine, "provider", "") == "scripted":
            raise LabError(400, "the flush turn needs a model; the scripted engine has none", code="no_api_key")
        trigger = flush_decision(lab, session, None)
        if forced_flush_blocked(session):
            decision = {"shouldRun": False, "reason": "already_flushed", "trigger": trigger}
            lab.bus.emit("flush.decided", summary="flush kararı: already_flushed (/flush)", data=decision)
            return {"decision": decision, "flush": None, "entry": session.flush_entry}
        decision = {"shouldRun": True, "reason": LAB_FORCED_REASON, "trigger": trigger}
        lab.bus.emit("flush.decided", summary="flush kararı: lab_forced (/flush)", data=decision)
        embedding = lab.resolve_embedding(payload)
        store = lab.store(embedding)
        with lab.locked():
            run = run_flush_turn(
                lab, session, engine, store, turn_id=None, reason=LAB_FORCED_REASON,
                secrets=lab.secret_values(payload),
            )
        return {"decision": decision, "flush": run, "entry": session.flush_entry}

    _add_live_task_routes(router, lab)
    return router


# --- live SDK task (demo/live_task_demo.py over memory_core.live) ---------------------------


def serialize_live_state(lab: LabRuntime, state: LiveTaskDemoState, payload: dict | None = None) -> dict[str, Any]:
    chat = lab.resolve_chat(payload or {})
    return {
        "workflow": state.workflow,
        "transcript": state.transcript,
        "workspace": state.workspace,
        "tracePath": state.trace_path,
        "subjectMemoryFiles": state.subject_memory_files,
        "workspaceInjectedFiles": state.identity_files,
        # Which engine a turn would use now: the .env key applies too, so a keyless
        # page still gets the real model when the server has a key.
        "engine": {
            "mode": "llm" if chat.has_key else "scripted",
            "keySource": chat.key_source,
            "model": chat.model if chat.has_key else "workflow-script",
        },
    }


def _live_ids(payload: dict[str, Any]) -> tuple[str, str]:
    session_id = optional_text(payload.get("sessionId")) or DEFAULT_LIVE_TASK_SESSION_ID
    subject_id = optional_text(payload.get("subjectId")) or DEFAULT_LIVE_TASK_SUBJECT_ID
    return validate_id(session_id, "sessionId"), validate_id(subject_id, "subjectId")


def live_engine(lab: LabRuntime, payload: dict[str, Any]) -> OpenAICompatibleChatEngine | None:
    chat = lab.resolve_chat(payload)
    if not chat.has_key:
        return None
    return OpenAICompatibleChatEngine(base_url=chat.base_url, api_key=chat.api_key, model=chat.model)


def _add_live_task_routes(router: APIRouter, lab: LabRuntime) -> None:
    @router.post("/live-task/reset")
    def live_task_reset(payload: dict = Body(default={})):
        session_id, subject_id = _live_ids(payload)
        return serialize_live_state(
            lab, lab.live_task.reset(session_id=session_id, subject_id=subject_id), payload
        )

    @router.get("/live-task/state")
    def live_task_state():
        return serialize_live_state(lab, lab.live_task.state())

    @router.post("/live-task/turn-stream")
    def live_task_turn_stream(payload: dict = Body(...)):
        session_id, subject_id = _live_ids(payload)
        message = str(payload.get("message", "")).strip()
        if not message:
            raise LabError(400, "message is required", code="invalid_message")
        return stream_response(_live_turn_frames(lab, payload, session_id, subject_id, message))

    @router.post("/live-task/summary")
    def live_task_summary(payload: dict = Body(default={})):
        session_id, subject_id = _live_ids(payload)
        secrets = lab.secret_values(payload)
        engine = live_engine(lab, payload)
        try:
            summary = lab.live_task.record_summary(
                session_id=session_id,
                subject_id=subject_id,
                transcript=optional_text(payload.get("transcript")),
                summary_llm=engine.raw_chat_text if engine is not None else None,
            )
        except Exception as exc:
            raise LabError(
                502,
                f"live task summary failed: {safe_exception_message(exc, secrets)}",
                code="live_summary_failed",
                redacted=True,
            ) from exc
        lab.bus.emit(
            "live.session_summary",
            summary=f"canlı özet: {'yazıldı' if summary.get('wrote') else 'yazılmadı'}",
            data={"wrote": summary.get("wrote"), "path": summary.get("path"),
                  "skipReason": summary.get("skip_reason")},
        )
        return {"summary": summary, "state": serialize_live_state(lab, lab.live_task.state(), payload)}


async def _live_engine_stream(engine: OpenAICompatibleChatEngine, messages: list[dict[str, str]]):
    yield {"type": "llm", "provider": "openai", "model": engine.model}
    async for chunk in iterate_in_threadpool(engine.raw_chat_stream(messages)):
        yield chunk


async def _live_turn_frames(
    lab: LabRuntime, payload: dict[str, Any], session_id: str, subject_id: str, message: str
):
    secrets = lab.secret_values(payload)
    try:
        engine = live_engine(lab, payload)
        llm = (lambda messages: _live_engine_stream(engine, messages)) if engine is not None else None
        async for event in lab.live_task.stream_turn(
            session_id=session_id, subject_id=subject_id, user_utterance=message, llm=llm
        ):
            if event["type"] == LIVE_TURN_FAILED and event["data"].get("error"):
                # The SDK yields str(exc) unredacted; the browser must not see a key.
                error = redact_secrets(event["data"]["error"], secrets)
                event = {**event, "data": {**event["data"], "error": error}}
            lab.bus.emit(
                f"live.{event['type']}",
                summary=f"canlı: {event['type']}",
                data={"elapsed_ms": event.get("elapsed_ms"), "text": event.get("text") or ""},
            )
            yield sse_frame(event, event=str(event["type"]))
        yield sse_frame(serialize_live_state(lab, lab.live_task.state(), payload), event="live_task_state")
    except Exception as exc:
        yield error_frame(f"live task turn failed: {safe_exception_message(exc, secrets)}", code="live_turn_failed")


def cooldown_payload(lab: LabRuntime, config, store) -> dict[str, Any] | None:
    remaining = memory_search_tool_cooldown_remaining(memory_search_tool_cooldown_key(config, store))
    if remaining is None:
        return None
    remaining_ms, error = remaining
    return {"remainingMs": int(remaining_ms), "until": lab.now_ms() + int(remaining_ms), "error": error}


def run_search(lab: LabRuntime, payload: dict[str, Any]) -> dict[str, Any]:
    embedding = lab.resolve_embedding(payload)
    mode = str(payload.get("mode") or lab.default_search_mode(embedding))
    store = lab.store(embedding, mode=mode)
    config = lab.config(mode=mode)
    secrets = lab.secret_values(payload)
    cooldown = cooldown_payload(lab, config, store)
    reindexed = False
    reindex_error = None
    if cooldown is not None:
        lab.bus.emit(
            "search.cooldown",
            summary=f"memory_search soğumada: {cooldown['remainingMs'] // 1000} sn",
            data={"mode": mode, **cooldown},
        )
    elif lab.index_is_stale(store) or store.index_identity().get("status") != "valid":
        try:
            lab.reindex(store)
            reindexed = True
        except Exception as exc:  # the search below reports the failure like upstream
            reindex_error = safe_exception_message(exc, secrets)
    params = {key: payload[key] for key in ("query", "maxResults", "minScore", "corpus") if key in payload}
    started = time.perf_counter()
    try:
        result = execute_memory_search_tool(config, store, params)
    except MemoryToolInputError as error:
        raise LabError(400, str(error), code="tool_input_error", toolError=error.to_tool_error()) from error
    ms = int((time.perf_counter() - started) * 1000)
    if result.get("unavailable"):
        lab.bus.emit(
            "search.unavailable",
            summary=f"memory_search kullanılamıyor: {redact_secrets(str(result.get('error')), secrets)}",
            data={"mode": mode, "warning": result.get("warning"), "action": result.get("action")},
        )
    else:
        lab.bus.emit(
            "search.completed",
            summary=f"memory_search ({mode}): {len(result.get('results') or [])} sonuç · {ms} ms",
            data={"mode": mode, "hits": len(result.get("results") or []), "ms": ms},
        )
    return redact_payload({
        **result,
        "mode": mode,
        "flags": {"vectorSearch": mode != "text", "textSearch": mode != "vector"},
        "identity": store.index_identity(),
        "cooldown": cooldown_payload(lab, config, store),
        "ms": ms,
        "embeddings": embedding.public(),
        "reindexed": reindexed,
        "reindexError": reindex_error,
        "redacted": True,
    }, secrets)


def index_status(lab: LabRuntime, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    embedding = lab.resolve_embedding(payload or {})
    mode = lab.default_search_mode(embedding)
    store = lab.store(embedding, mode=mode)
    config = lab.config(mode=mode)
    return redact_payload({
        **lab.index_status,
        "mode": mode,
        "identity": store.index_identity(),
        "embeddings": embedding.public(),
        "cooldown": cooldown_payload(lab, config, store),
        "deadlineMs": MEMORY_SEARCH_TOOL_TIMEOUT_MS,
        "cooldownMs": MEMORY_SEARCH_TOOL_COOLDOWN_MS,
        "stale": lab.index_is_stale(store),
    }, lab.secret_values(payload))


def stream_response(frames) -> StreamingResponse:
    return StreamingResponse(frames, media_type="text/event-stream", headers=SSE_HEADERS)


def error_frame(message: str, *, code: str | None = None, **extra: Any) -> str:
    body: dict[str, Any] = {"error": message, "redacted": True}
    if code:
        body["code"] = code
    body.update(extra)
    return sse_frame(body, event="error")


__all__ = ["build_kept_router", "error_frame", "optional_text", "stream_response"]
