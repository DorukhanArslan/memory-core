"""HTTP routes of the Lab: ``/api/lab/*`` (DESIGN §4.2) and the kept ``/api/*`` endpoints.

Routes stay thin: they validate input, call :mod:`demo.lab_runtime` (and the
modules next to it) and shape JSON. Errors are ``{error, code?}`` with a 4xx/5xx
status (:class:`~demo.lab_runtime.LabError`); keys are redacted before any
message leaves the server.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import StreamingResponse

from demo.chat_engine import ChatEngine, OpenAICompatibleChatEngine, ScriptedChatEngine
from demo.lab_chat import chat_turn_frames
from demo.lab_events import parse_last_event_id, stream_lab_events, unified_diff
from demo.lab_flush import flush_meter
from demo.lab_prompt import (
    PromptOptions,
    file_entries,
    lab_workspace_context,
    prompt_options,
    prompt_view,
)
from demo.lab_runtime import MINIMAL_PROMPT_KINDS
from demo.lab_tools import lab_curator
from demo.lab_runtime import (
    LAB_TIMEZONE,
    LabError,
    LabRuntime,
    summarize_turn,
    validate_id,
)
from demo.parity_results import (
    DEFAULT_ORACLE_REPO,
    PRODUCER_COMMANDS,
    default_results_path,
    load_parity_results,
    parse_parity_matrix,
)
from demo.workspace_context import workspace_layout_summary
from memory_core.bootstrap import trim_bootstrap_content
from memory_core.heartbeat import build_heartbeat_section_lines, resolve_heartbeat_prompt_for_system_prompt
from memory_core.prompt_section import build_prompt_section
from memory_core.tools.memory_get import MEMORY_GET_TOOL_NAME
from memory_core.tools.memory_search import MEMORY_SEARCH_TOOL_NAME
from memory_core.bootstrap._js import utf16_len
from memory_core.parity.upstream import LATEST_INSPECTED_COMMIT
from memory_core.workspace import MemoryWorkspace

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def lab_snapshot(lab: LabRuntime, *, kind: str = "main") -> dict[str, Any]:
    lab.ensure_exists()
    session = lab.session(kind)
    options = PromptOptions(kind=kind)
    wc = lab_workspace_context(lab, options, session=session)
    layout = lab.layout
    workspace = MemoryWorkspace(lab.root)
    return {
        "workspace": {
            "root": str(lab.root),
            "layout": lab.settings.layout,
            "layoutName": layout.name,
            "exists": lab.root.is_dir(),
        },
        "liveWorkspace": {"root": str(lab.live_root)},
        "pin": LATEST_INSPECTED_COMMIT,
        "timezone": LAB_TIMEZONE,
        "nowMs": lab.now_ms(),
        "today": lab.today(),
        "yesterday": lab.yesterday(),
        "clock": {"nowMs": lab.heartbeat_now_ms(), "offsetMs": lab.clock_offset_ms},
        "identityName": lab.identity_name(),
        "bootstrap": {
            "status": wc.bootstrap_status,
            "mode": wc.bootstrap_mode,
            "pendingFile": (lab.root / layout.bootstrap_file).exists(),
            **lab.setup_state(),
        },
        "session": session.public(),
        "sessions": {name: item.public() for name, item in lab.sessions.items()},
        "index": dict(lab.index_status),
        "flush": flush_meter(lab, session),
        "layoutOrder": workspace_layout_summary(layout),
        "memoryFiles": [file.rel_path for file in workspace.discover_memory_files()],
        "turns": lab.turn_summaries(),
        "lastEventId": lab.bus.last_id,
    }


def build_router(lab: LabRuntime) -> APIRouter:
    router = APIRouter(prefix="/api/lab")

    @router.get("/state")
    def state(sessionKind: str = Query("main")):  # noqa: N803 - query name is the contract
        return lab_snapshot(lab, kind=sessionKind)

    @router.get("/events")
    async def events(
        request: Request,
        lastEventId: str | None = Query(None),  # noqa: N803
        once: bool = Query(False),
    ):
        last = parse_last_event_id(request.headers.get("last-event-id") or lastEventId)
        return StreamingResponse(
            stream_lab_events(
                lab.bus, last_event_id=last, is_disconnected=request.is_disconnected, once=once
            ),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    @router.get("/files")
    def files(sessionKind: str = Query("main"), layout: str | None = Query(None)):  # noqa: N803
        lab.ensure_exists()
        return file_entries(lab, PromptOptions(kind=sessionKind, layout=layout))

    @router.get("/file")
    def read_file(path: str = Query(...)):
        lab.ensure_exists()
        return lab.read_file(path)

    @router.put("/file")
    def write_file(payload: dict = Body(...)):
        lab.ensure_exists()
        with lab.lock:
            return lab.write_file(payload.get("path"), payload.get("content"), payload.get("baseSha256"))

    @router.post("/file/diff-preview")
    def diff_preview(payload: dict = Body(...)):
        lab.ensure_exists()
        content = payload.get("content")
        if not isinstance(content, str):
            raise LabError(400, "content must be a string", code="invalid_content")
        path, target = lab.resolve_path(payload.get("path"), must_exist=False)
        before = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else None
        budget = None
        if "/" not in path and path in lab.layout.load_order:
            max_chars = lab.settings.max_chars
            trimmed = trim_bootstrap_content(content, path, max_chars)
            budget = {
                "maxChars": max_chars,
                "wouldTruncate": trimmed.truncated,
                "injectedAfter": utf16_len(trimmed.content),
                "rawAfter": trimmed.original_length,
            }
        return {
            "path": path,
            "diff": unified_diff(before, content, path),
            "charsBefore": utf16_len(before) if before is not None else 0,
            "charsAfter": utf16_len(content),
            "budget": budget,
        }

    @router.get("/diff")
    def diff(since: str = Query("reset")):
        lab.ensure_exists()
        return lab.diff_since(since)

    @router.post("/diff/mark")
    def diff_mark():
        lab.ensure_exists()
        return {"markId": lab.snapshots.mark()}

    @router.post("/diff/revert")
    def diff_revert(payload: dict = Body(...)):
        lab.ensure_exists()
        path, target = lab.resolve_path(payload.get("path"), must_exist=False)
        baseline, _ = lab.baseline_for(str(payload.get("since") or ""))
        current = lab.read_file(path)["sha256"] if target.is_file() else None
        base = payload.get("baseSha256", current)
        with lab.lock:
            if path in baseline:
                text = baseline[path].text
                if text is None:
                    raise LabError(400, f"{path} was binary or too large at the baseline", code="not_text")
                return lab.write_file(path, text, base, source="revert")
            return lab.write_file(path, None, base, source="revert", delete=True)

    @router.post("/workspace/reset")
    def workspace_reset(payload: dict = Body(default={})):
        mode = str(payload.get("mode") or "seeded")
        with lab.lock:
            lab.reset_workspace(mode, keep_memory=bool(payload.get("keepMemory", False)))
        return lab_snapshot(lab)

    @router.get("/turns/{turn_id}")
    def turn_detail(turn_id: str):
        if not turn_id.isdigit():
            raise LabError(400, "turnId must be a positive integer", code="invalid_id")
        detail = lab.turns.get(int(turn_id))
        if detail is None:
            raise LabError(404, f"turn {turn_id} not found", code="not_found")
        return detail

    @router.post("/prompt/preview")
    def prompt_preview(payload: dict = Body(default={})):
        """PromptView of the current disk state for a session kind (nothing is sent)."""
        lab.ensure_exists()
        options = prompt_options(payload)
        session = lab.sessions.get(options.kind)
        wc = lab_workspace_context(lab, options, session=session)
        return prompt_view(lab, options, wc, extras=preview_extras(lab, options.kind))

    @router.post("/chat/stream")
    def chat_stream(payload: dict = Body(...)):
        lab.ensure_exists()
        kind = str(payload.get("sessionKind") or "main")
        lab.session(kind)  # validates the kind
        reset = bool(payload.get("reset"))
        message = str(payload.get("message") or "").strip()
        if not message and not reset:
            raise LabError(400, "message is required", code="invalid_message")
        engine = resolve_chat_engine(lab, payload)
        return StreamingResponse(
            chat_turn_frames(lab, payload, engine, kind=kind, message=message, reset=reset),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    @router.post("/curation/revert")
    def curation_revert(payload: dict = Body(...)):
        lab.ensure_exists()
        write_id = validate_id(payload.get("writeId"), "writeId")
        write = next((item for item in lab.curated_writes if item["id"] == write_id), None)
        if write is None:
            raise LabError(404, f"curated write {write_id} not found", code="not_found")
        if write.get("refused"):
            raise LabError(400, "a refused write changed nothing", code="refused_write")
        if write.get("reverted"):
            raise LabError(409, f"{write_id} was already reverted", code="already_reverted")
        path, target = lab.resolve_path(write["path"], must_exist=False)
        current = lab.read_file(path) if target.is_file() else None
        current_sha = current["sha256"] if current else None
        if current_sha != write.get("afterSha256"):
            raise LabError(
                409,
                f"{path} changed after this curated write; revert refused",
                code="conflict",
                current={"sha256": current_sha, "content": current["content"]} if current else None,
            )
        with lab.lock:
            if write.get("before") is None:
                result = lab.write_file(path, None, current_sha, source="curation_revert", delete=True,
                                        enforce_flag=False)
            else:
                result = lab.write_file(path, write["before"], current_sha, source="curation_revert",
                                        enforce_flag=False)
        write["reverted"] = True
        lab.bus.emit(
            "curation.reverted",
            summary=f"{path} geri alındı ({write_id})",
            data={"writeId": write_id, "path": path},
        )
        return result

    @router.get("/parity")
    def parity():
        repo = Path(os.getenv("OPENCLAW_ORACLE_REPO") or DEFAULT_ORACLE_REPO)
        results_path = default_results_path()
        return {
            "pin": LATEST_INSPECTED_COMMIT,
            "oracleRepo": {"path": str(repo), "exists": repo.is_dir(), "head": _git_head(repo)},
            "node": _node_version(),
            "resultsPath": str(results_path),
            "results": load_parity_results(results_path),
            "matrix": parse_parity_matrix(),
            "commands": list(PRODUCER_COMMANDS),
        }

    return router


def offered_tool_names(lab: LabRuntime) -> list[str]:
    names = [MEMORY_SEARCH_TOOL_NAME, MEMORY_GET_TOOL_NAME]
    names.extend(definition["name"] for definition in lab_curator(lab).tool_definitions())
    return names


def preview_extras(lab: LabRuntime, kind: str) -> dict[str, Any]:
    tools = offered_tool_names(lab)
    minimal = kind in MINIMAL_PROMPT_KINDS
    memory_section = [] if minimal else build_prompt_section(set(tools), citations_mode="on")
    heartbeat_section = (
        build_heartbeat_section_lines(
            resolve_heartbeat_prompt_for_system_prompt(trigger="heartbeat", every=lab.settings.heartbeat_every),
            is_minimal=minimal,
        )
        if kind == "heartbeat"
        else []
    )
    return {
        "preview": True,
        "banner": "Önizleme: diskteki güncel durum, gönderilmedi",
        "tools": sorted(tools),
        "recall": {"lines": [], "memoryRecallSection": memory_section, "label": "demo-only"},
        "heartbeatSection": heartbeat_section,
        "startup": None,
        "flush": None,
    }


def resolve_chat_engine(lab: LabRuntime, payload: dict[str, Any]) -> ChatEngine:
    """The request's chat engine: a real OpenAI-compatible model, or the labelled script.

    Without a key there is no chat (no fake model): the request fails with
    ``no_api_key`` unless it explicitly asks for ``engine: "scripted"``.
    """
    engine = payload.get("engine")
    if engine == "scripted":
        return ScriptedChatEngine()
    if engine not in (None, "", "openai"):
        raise LabError(400, "engine must be 'openai' or 'scripted'", code="invalid_engine")
    chat = lab.resolve_chat(payload)
    if not chat.has_key:
        raise LabError(
            400,
            "no chat model key: set MEMORY_CORE_DEMO_OPENAI_API_KEY or send openai.apiKey "
            "(the Lab has no fake chat model; engine 'scripted' runs the pipeline without one)",
            code="no_api_key",
        )
    return OpenAICompatibleChatEngine(
        base_url=chat.base_url, api_key=chat.api_key, model=chat.model, timeout=60.0
    )


def _git_head(repo: Path) -> str | None:
    if not (repo / ".git").exists():
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None


def _node_version() -> dict[str, str] | None:
    node = shutil.which("node") or ("/opt/homebrew/bin/node" if Path("/opt/homebrew/bin/node").exists() else None)
    if node is None:
        return None
    try:
        completed = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    version = completed.stdout.strip()
    return {"version": version, "path": node} if version else None


def turn_summary(detail: dict[str, Any]) -> dict[str, Any]:
    return summarize_turn(detail)


def json_line(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


__all__ = ["build_router", "lab_snapshot", "turn_summary", "validate_id"]
