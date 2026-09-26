"""One Lab chat turn: the stage pipeline behind ``POST /api/lab/chat/stream``.

Stages (streamed as ``stage`` events in this order): ``ensure``
(``initialize_agent_workspace``, upstream runs it on every reply), ``reindex``,
``recall`` (demo-only auto-recall, see below), ``prompt``
(``build_workspace_context`` for the session kind), ``stream`` (the host tool
loop of :mod:`demo.lab_tools`) and ``persist``. Other SSE events: ``turn_started``,
``recall``, ``prompt``, ``assistant_delta``, ``tool_call``, ``tool_result``,
``curation``, ``turn_done {turn, detail}`` and ``error``.

Demo-only parts, labelled in the payloads: the auto-recall (``memory_search`` on
the user message, only MEMORY.md and today's/yesterday's daily file reach the
prompt) and the transcript window (40 messages, 24,000 chars). Upstream has
neither; its model recalls through the memory tools, which the Lab offers too.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx

from demo.chat_engine import ChatEngine, ChatMessage
from demo.lab_events import diff_snapshots, sse_frame
from demo.lab_prompt import PromptOptions, lab_workspace_context, prompt_view
from demo.lab_runtime import (
    MINIMAL_PROMPT_KINDS,
    LabError,
    LabRuntime,
    LabSession,
    safe_exception_message,
    summarize_turn,
)
from demo.lab_tools import LabToolbox, ToolLoopOutcome, public_write, run_tool_loop
from demo.transcript_context import select_transcript_context
from memory_core.consolidation import record_short_term_recalls, undecorate_search_results
from memory_core.prompt_section import build_prompt_section
from memory_core.tools.memory_search import memory_search

TRANSCRIPT_MESSAGE_WINDOW = 40
TRANSCRIPT_CHAR_BUDGET = 24_000
AUTO_RECALL_MAX_RESULTS = 5
AUTO_RECALL_FILTER_REASON = "demo filtresi (MEMORY.md + bugün/dün)"
LOCK_TIMEOUT_SECONDS = 120


class TurnState:
    """Accumulates one turn's TurnDetail while the stages run."""

    def __init__(self, lab: LabRuntime, session: LabSession, *, user: str, engine: ChatEngine,
                 reset: bool = False) -> None:
        self.lab = lab
        self.session = session
        self.id = lab.allocate_turn_id()
        self.started = time.perf_counter()
        self.detail: dict[str, Any] = {
            "id": self.id,
            "sessionId": session.id,
            "sessionKey": session.key,
            "sessionKind": session.kind,
            "startedAt": lab.now_ms(),
            "ms": 0,
            "user": user,
            "assistant": "",
            "engine": {
                "provider": getattr(engine, "provider", engine.name),
                "model": engine.model,
                "scripted": getattr(engine, "provider", "") == "scripted",
            },
            "chips": [],
            "stages": [],
            "toolCalls": [],
            "curation": [],
            "diffs": [],
            "recall": None,
            "flush": None,
            "prompt": None,
            "reset": reset,
        }
        self.current: str | None = None
        self._stage_started = 0.0
        self.baseline = lab.snapshots.take()
        lab.snapshots.set_baseline(f"turn:{self.id}", self.baseline)

    def start(self, name: str) -> str:
        self.current = name
        self._stage_started = time.perf_counter()
        return sse_frame({"turnId": self.id, "name": name, "status": "running"}, event="stage")

    def finish(self, status: str = "ok", detail: str | None = None) -> str:
        entry: dict[str, Any] = {
            "name": self.current,
            "status": status,
            "ms": int((time.perf_counter() - self._stage_started) * 1000),
        }
        if detail:
            entry["detail"] = detail
        self.detail["stages"].append(entry)
        self.current = None
        return sse_frame({"turnId": self.id, **entry}, event="stage")

    def skip(self, name: str, reason: str) -> str:
        entry = {"name": name, "status": "skip", "ms": 0, "detail": reason}
        self.detail["stages"].append(entry)
        return sse_frame({"turnId": self.id, **entry}, event="stage")

    def close(self) -> None:
        self.detail["ms"] = int((time.perf_counter() - self.started) * 1000)
        current = self.lab.snapshots.take()
        diffs = []
        for change in diff_snapshots(self.baseline, current):
            sources = [
                record.source for record in self.lab.snapshots.changes
                if record.path == change["path"] and record.turn_id == self.id
            ]
            diffs.append({**change, "source": sources[-1] if sources else "other", "sources": sources})
        self.detail["diffs"] = diffs


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, LabError) and exc.code:
        return exc.code
    if isinstance(exc, httpx.HTTPStatusError):
        return f"provider_http_{exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "provider_timeout"
    if isinstance(exc, httpx.TransportError):
        return "provider_unreachable"
    return "turn_failed"


def _transcript_window(session: LabSession, user: str) -> tuple[list[ChatMessage], list[ChatMessage]]:
    previous = [ChatMessage(role=item["role"], content=item["content"]) for item in session.messages]
    visible = previous[-TRANSCRIPT_MESSAGE_WINDOW:] if TRANSCRIPT_MESSAGE_WINDOW > 0 else []
    omitted = previous[: max(0, len(previous) - len(visible))]
    sent, budget_omitted = select_transcript_context(
        [*visible, ChatMessage(role="user", content=user)], max_chars=TRANSCRIPT_CHAR_BUDGET
    )
    return sent, [*omitted, *budget_omitted]


def auto_recall(lab: LabRuntime, config, store, query: str, *, turn_id: int) -> dict[str, Any]:
    """Demo-only auto-recall: search the user message, keep MEMORY.md and today/yesterday."""
    result = memory_search(config, store, query=query, max_results=AUTO_RECALL_MAX_RESULTS, min_score=0)
    hits = result.get("results") or []
    allowed = {lab.layout.memory_file, f"memory/{lab.today()}.md", f"memory/{lab.yesterday()}.md"}
    used = [hit for hit in hits if str(hit.get("path") or "") in allowed]
    filtered = [
        {"path": hit.get("path"), "reason": AUTO_RECALL_FILTER_REASON}
        for hit in hits if str(hit.get("path") or "") not in allowed
    ]
    if used:
        with lab.tracked("recall", turn_id=turn_id):
            # Upstream records the raw hits (tools.ts queueShortTermRecallTracking gets
            # rawResults); the citation-decorated snippets only feed the prompt.
            record_short_term_recalls(
                config=config, query=query, results=undecorate_search_results(used), now_ms=lab.now_ms()
            )
    lines = []
    for hit in used:
        snippet = str(hit.get("snippet") or "").strip()
        if snippet:
            lines.append(f"{hit.get('citation') or hit.get('path')}: {snippet}")
    return {
        "query": query,
        "results": hits,
        "used": [str(hit.get("path")) for hit in used],
        "filtered": filtered,
        "lines": lines,
        "unavailable": bool(result.get("unavailable")),
        "error": result.get("error"),
        "warning": result.get("warning"),
        "action": result.get("action"),
        "label": "demo-only",
    }


def assemble_messages(
    *,
    system_sections: list[str],
    recall_lines: list[str],
    sent: list[ChatMessage],
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system_text = "\n\n".join(section.strip() for section in system_sections if section and section.strip())
    if system_text:
        messages.append({"role": "system", "content": system_text})
    if recall_lines:
        messages.append({"role": "system", "content": "Memory context:\n" + "\n".join(recall_lines)})
    messages.extend({"role": message.role, "content": message.content} for message in sent)
    return messages


def build_chips(lab: LabRuntime, turn: TurnState, *, truncation_shown: bool, truncated: int) -> list[dict[str, Any]]:
    detail = turn.detail
    chips: list[dict[str, Any]] = []
    recall = detail.get("recall")
    if recall is not None:
        chips.append({"type": "recall", "label": f"recall {len(recall['used'])}", "count": len(recall["used"])})
    names: dict[str, int] = {}
    for call in detail["toolCalls"]:
        names[call["name"]] = names.get(call["name"], 0) + 1
    for name, count in names.items():
        chips.append({"type": "tool", "label": f"{name} ×{count}", "count": count})
    for write in detail["curation"]:
        if write.get("refused"):
            chips.append({"type": "refused", "label": f"{write['path']} reddedildi", "target": write["path"],
                          "source": "curation", "extension": True, "detail": write.get("reason")})
            continue
        sign = {"removed": "−1", "replaced": "~1", "superseded": "~1", "set": "~1", "cleared": "−1"}.get(
            write.get("action") or "", "+1"
        )
        daily = write["path"] == f"memory/{lab.today()}.md"
        chips.append({"type": "write", "label": f"{'günlük' if daily else write['path']} {sign}",
                      "target": write["path"], "source": "curation", "extension": True})
    flush = detail.get("flush")
    if flush:
        decision = flush.get("decision") or {}
        run = flush.get("run")
        if run and run.get("wrote"):
            chips.append({"type": "flush", "label": "flush → günlük", "target": run.get("target"), "source": "flush"})
        elif decision:
            chips.append({"type": "flush_skip", "label": f"flush: {decision.get('reason')}", "source": "flush"})
    for event in lab.bus.recent(400):
        if event.get("turnId") == turn.id and event["type"] == "bootstrap.completed":
            chips.append({"type": "bootstrap", "label": "bootstrap tamamlandı"})
            break
    if truncation_shown:
        chips.append({"type": "truncation", "label": "kırpma", "count": truncated})
    if detail.get("startup"):
        chips.append({"type": "startup", "label": f"başlangıç bağlamı {len(detail['startup'].get('files') or [])}",
                      "count": len(detail["startup"].get("files") or [])})
    if detail.get("failedStage"):
        chips.append({"type": "error", "label": f"hata: {detail['failedStage']}"})
    return chips


def chat_turn_frames(
    lab: LabRuntime,
    payload: dict[str, Any],
    engine: ChatEngine,
    *,
    kind: str,
    message: str,
    reset: bool = False,
) -> Iterator[str]:
    """SSE frames of one turn; holds the Lab lock for the whole turn."""
    if not lab.lock.acquire(timeout=LOCK_TIMEOUT_SECONDS):
        yield sse_frame({"error": "another Lab operation is still running", "code": "busy"}, event="error")
        return
    try:
        yield from _run_turn(lab, payload, engine, kind=kind, message=message, reset=reset)
    finally:
        lab.lock.release()


def _run_turn(
    lab: LabRuntime,
    payload: dict[str, Any],
    engine: ChatEngine,
    *,
    kind: str,
    message: str,
    reset: bool,
) -> Iterator[str]:
    secrets = lab.secret_values(payload)
    session = lab.session(kind)
    scripted = getattr(engine, "provider", "") == "scripted"
    turn = TurnState(lab, session, user=message, engine=engine, reset=reset)
    detail = turn.detail
    yield sse_frame(
        {"turnId": turn.id, "sessionId": session.id, "sessionKey": session.key, "sessionKind": kind,
         "engine": detail["engine"]},
        event="turn_started",
    )
    lab.bus.emit("chat.turn.started", summary=f"tur #{turn.id} · {kind}", data={"sessionKey": session.key},
                 turn_id=turn.id)
    truncation_shown = False
    truncated = 0
    try:
        yield turn.start("ensure")
        init = lab.ensure(turn_id=turn.id)
        yield turn.finish(detail=f"bootstrap {init.bootstrap_status}")

        embedding = lab.resolve_embedding(payload)
        mode = lab.default_search_mode(embedding)
        config = lab.config(mode=mode)
        store = lab.store(embedding, mode=mode)
        yield turn.start("reindex")
        index = lab.reindex(store, turn_id=turn.id)
        yield turn.finish(detail=f"{index['indexedFiles']} dosya · {index['chunks']} parça · {mode}")

        if kind in MINIMAL_PROMPT_KINDS or reset:
            reason = "sıfırlama turu" if reset else f"{kind}: minimal prompt, demo auto-recall kapalı"
            yield turn.skip("recall", reason)
            recall = None
        else:
            yield turn.start("recall")
            recall = auto_recall(lab, config, store, message, turn_id=turn.id)
            detail["recall"] = recall
            lab.bus.emit(
                "recall.completed",
                summary=f"recall {len(recall['used'])} / {len(recall['results'])} isabet",
                data={"query": message, "used": recall["used"], "hits": len(recall["results"]),
                      "filtered": recall["filtered"], "unavailable": recall["unavailable"]},
                turn_id=turn.id,
            )
            yield sse_frame({"turnId": turn.id, **recall}, event="recall")
            yield turn.finish(detail=f"{len(recall['used'])} prompt'a girdi")

        yield turn.start("prompt")
        options = PromptOptions(kind=kind)
        wc = lab_workspace_context(lab, options, session=session)
        truncation_shown = wc.prompt_warning.warning_shown
        truncated = len(wc.analysis.truncated_files)
        toolbox = None if scripted else LabToolbox(lab, config, store, session, turn.id)
        tool_names = sorted(toolbox.names()) if toolbox is not None else []
        memory_section = (
            build_prompt_section(set(tool_names), citations_mode=config.citation_mode)
            if kind not in MINIMAL_PROMPT_KINDS else []
        )
        user_content = message
        sent, omitted = _transcript_window(session, user_content)
        messages = assemble_messages(
            system_sections=["\n".join(memory_section), wc.prompt_text],
            recall_lines=(recall or {}).get("lines") or [],
            sent=sent,
        )
        view = prompt_view(
            lab,
            options,
            wc,
            extras={
                "recall": {
                    "lines": (recall or {}).get("lines") or [],
                    "memoryRecallSection": memory_section,
                    "label": "demo-only",
                },
                "tools": tool_names,
                "transcript": {"sent": len(sent), "omitted": len(omitted),
                               "window": TRANSCRIPT_MESSAGE_WINDOW, "charBudget": TRANSCRIPT_CHAR_BUDGET,
                               "label": "demo-only"},
                "messages": messages,
                "startup": None,
                "flush": None,
            },
        )
        detail["prompt"] = view
        lab.bus.emit(
            "prompt.assembled",
            summary=f"prompt · {sum(len(item['content'] or '') for item in messages)} karakter · {len(view['files'])} dosya",
            data={"files": [file["name"] for file in view["files"]], "tools": tool_names,
                  "bootstrapMode": view["bootstrapMode"]},
            turn_id=turn.id,
        )
        yield sse_frame({"turnId": turn.id, **view}, event="prompt")
        yield turn.finish(detail=f"{len(view['files'])} dosya · araçlar {len(tool_names)}")

        yield turn.start("stream")
        outcome = ToolLoopOutcome()
        for event, data in run_tool_loop(engine, messages, toolbox, outcome):
            yield sse_frame({"turnId": turn.id, **data}, event=event)
            if event == "tool_result" and data.get("curation"):
                yield sse_frame({"turnId": turn.id, **data["curation"]}, event="curation")
        detail["assistant"] = outcome.text
        detail["toolLoop"] = {"rounds": outcome.rounds, "capped": outcome.capped, "usage": outcome.usage,
                              "usageTotal": outcome.usage_total}
        if toolbox is not None:
            detail["toolCalls"] = toolbox.calls
            detail["curation"] = [public_write(write) for write in toolbox.curated]
        yield turn.finish(
            detail=f"{outcome.rounds} tur · {len(detail['toolCalls'])} araç çağrısı"
            + (" · sınır" if outcome.capped else "")
        )

        yield turn.start("persist")
        _persist(lab, session, turn, wc, user_content, outcome)
        yield turn.finish()
        turn.close()
        detail["chips"] = build_chips(lab, turn, truncation_shown=truncation_shown, truncated=truncated)
        lab.store_turn(detail)
        session.turn_ids.append(turn.id)
        lab.bus.emit(
            "chat.turn.completed",
            summary=f"tur #{turn.id} tamam · {detail['ms']} ms",
            data={"ms": detail["ms"], "chips": detail["chips"]},
            turn_id=turn.id,
        )
        yield sse_frame({"turn": summarize_turn(detail), "detail": detail}, event="turn_done")
    except GeneratorExit:
        _fail(lab, turn, "stopped by the client", code="stopped")
        raise
    except Exception as exc:
        message_text = f"chat send failed: {safe_exception_message(exc, secrets)}"
        code = _error_code(exc)
        _fail(lab, turn, message_text, code=code)
        yield sse_frame(
            {"error": message_text, "code": code, "stage": detail.get("failedStage"), "turnId": turn.id,
             "redacted": True},
            event="error",
        )


def _fail(lab: LabRuntime, turn: TurnState, message: str, *, code: str) -> None:
    detail = turn.detail
    if turn.current is not None:
        detail["failedStage"] = turn.current
        detail["stages"].append({"name": turn.current, "status": "fail", "ms": 0, "detail": message})
        turn.current = None
    detail["error"] = {"error": message, "code": code, "redacted": True}
    turn.close()
    detail["chips"] = build_chips(lab, turn, truncation_shown=False, truncated=0)
    lab.store_turn(detail)
    lab.bus.emit(
        "chat.turn.failed",
        summary=f"tur #{turn.id} başarısız: {detail.get('failedStage') or code}",
        data={"stage": detail.get("failedStage"), "code": code, "error": message},
        turn_id=turn.id,
    )


def _persist(lab: LabRuntime, session: LabSession, turn: TurnState, wc, user_content: str,
             outcome: ToolLoopOutcome) -> None:
    session.messages.append({"role": "user", "content": turn.detail.get("transcriptUser") or user_content})
    session.messages.append({"role": "assistant", "content": outcome.text})
    session.seen_truncation_signatures = list(wc.prompt_warning.warning_signatures_seen)
    if wc.record_completed_bootstrap_turn:
        session.completed_bootstrap_turn = True
    del lab
