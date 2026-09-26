"""Heartbeat runs in the Lab over :mod:`memory_core.heartbeat` (runtime-only port, no scheduler).

``GET /api/lab/heartbeat`` shows the HEARTBEAT.md preflight, the parsed
``tasks:`` with their due state and the run history. ``POST
/api/lab/heartbeat/run`` runs one heartbeat now: ``prepare_heartbeat_turn``
(skip reasons ``empty-heartbeat-file`` and ``no-tasks-due`` make no model
call), the flush decision with ``is_heartbeat=True`` (``runtime_skip:heartbeat``),
the injected context for session kind ``heartbeat`` (PROACTIVE_PREFERENCES.md
included on the memory-core layout), the ``## Heartbeats`` system section, then the
same host tool loop as chat turns, so the model can read daily notes with
``memory_search``/``memory_get`` (critique high #3). The reply goes through
``strip_heartbeat_token(mode="heartbeat")``: delivered only when it carries an
alert. Task state is kept per Lab session and stamped after each completed run.

Demo-only: the virtual clock shifts heartbeat due checks only; the prompt's
current-time line, daily file dates and the flush use the real clock.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any

from demo.chat_engine import ChatEngine, ChatMessage
from demo.lab_chat import LOCK_TIMEOUT_SECONDS, assemble_messages
from demo.lab_events import sse_frame
from demo.lab_flush import flush_decision, update_token_snapshot
from demo.lab_prompt import PromptOptions, lab_workspace_context, prompt_view
from demo.lab_runtime import LAB_TIMEZONE, LabError, LabRuntime, safe_exception_message
from demo.lab_tools import LabToolbox, ToolLoopOutcome, public_write, run_tool_loop
from demo.transcript_context import select_transcript_context
from memory_core.bootstrap import append_cron_style_current_time_line
from memory_core.bootstrap._js import utf16_len
from memory_core.heartbeat import (
    HEARTBEAT_TRANSCRIPT_PROMPT,
    build_heartbeat_section_lines,
    is_heartbeat_content_effectively_empty,
    is_task_due,
    parse_duration_ms,
    parse_heartbeat_tasks,
    prepare_heartbeat_turn,
    resolve_heartbeat_interval_ms,
    resolve_heartbeat_prompt_for_system_prompt,
    strip_heartbeat_token,
)
from memory_core.prompt_section import build_prompt_section

HEARTBEAT_RUN_HISTORY = 20
MAX_CLOCK_OFFSET_MS = 30 * 24 * 60 * 60 * 1000
_TASK_ENTRY_RE = re.compile(r"^\s*- name:", re.MULTILINE)
LABELS = {
    "runtime": "runtime-only port · zamanlayıcı yok (elle çalıştırılır)",
    "clock": "sanal saat (demo-only): yalnız heartbeat vade hesabı; günlük dosya tarihleri ve flush gerçek saatle",
    "unparsed": "Lab çıkarımı: ayrıştırılmayan '- name:' satırı sayısı (parser sebep vermez)",
}


def _heartbeat_content(lab: LabRuntime) -> str | None:
    path = lab.root / lab.layout.heartbeat_file
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None


def _proactive_state(lab: LabRuntime) -> str:
    name = "PROACTIVE_PREFERENCES.md"
    if name not in lab.layout.load_order:
        return "outside_layout"
    path = lab.root / name
    if not path.is_file():
        return "absent"
    return "injected" if path.read_text(encoding="utf-8", errors="replace").strip() else "empty"


def heartbeat_state(lab: LabRuntime) -> dict[str, Any]:
    content = _heartbeat_content(lab)
    now = lab.heartbeat_now_ms()
    state = lab.heartbeat_task_state or {}
    tasks = parse_heartbeat_tasks(content) if content is not None else []
    rows = []
    for task in tasks:
        last = state.get(task.name)
        try:
            interval_ms = parse_duration_ms(task.interval, default_unit="m")
        except ValueError:
            interval_ms = None
        rows.append(
            {
                "name": task.name,
                "interval": task.interval,
                "intervalMs": interval_ms,
                "prompt": task.prompt,
                "lastRunMs": last,
                "due": is_task_due(last, task.interval, now),
                "nextDueMs": (last + interval_ms) if last is not None and interval_ms is not None else None,
            }
        )
    preflight = prepare_heartbeat_turn(
        lab.root, now_ms=now, task_state=lab.heartbeat_task_state, layout=lab.layout
    )
    every = lab.settings.heartbeat_every
    return {
        "file": {
            "path": lab.layout.heartbeat_file,
            "exists": content is not None,
            "effectivelyEmpty": is_heartbeat_content_effectively_empty(content),
        },
        "every": every,
        "everyMs": resolve_heartbeat_interval_ms(every),
        "ackMaxChars": lab.settings.heartbeat_ack_max_chars,
        "lightContext": lab.settings.heartbeat_light_context,
        "tasks": rows,
        "unparsedTaskEntries": max(0, len(_TASK_ENTRY_RE.findall(content or "")) - len(tasks)),
        "preflight": {"skipReason": preflight.skip_reason, "dueTasks": [task.name for task in preflight.due_tasks]},
        "clock": {"nowMs": now, "offsetMs": lab.clock_offset_ms},
        "runs": list(reversed(lab.heartbeat_runs[-HEARTBEAT_RUN_HISTORY:])),
        "proactivePreferences": _proactive_state(lab),
        "sessionKey": lab.session("heartbeat").key,
        "labels": LABELS,
    }


def strip_payload(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("text")
    if not isinstance(text, str):
        raise LabError(400, "text must be a string", code="invalid_text")
    result = strip_heartbeat_token(text, mode="heartbeat", max_ack_chars=payload.get("ackMaxChars"))
    return {"shouldSkip": result.should_skip, "text": result.text, "didStrip": result.did_strip,
            "label": "yalnız ayrıştırıcı (model yok)"}


def set_clock(lab: LabRuntime, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("reset"):
        lab.clock_offset_ms = 0
    else:
        value = payload.get("offsetMs")
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise LabError(400, "offsetMs must be a number (or send reset: true)", code="invalid_offset")
        if abs(value) > MAX_CLOCK_OFFSET_MS:
            raise LabError(400, "offsetMs must stay within ±30 days", code="invalid_offset")
        lab.clock_offset_ms = int(value)
    result = {"nowMs": lab.heartbeat_now_ms(), "offsetMs": lab.clock_offset_ms}
    lab.bus.emit("clock.changed", summary=f"sanal saat {lab.clock_offset_ms // 60000:+d} dk", data=result)
    return result


def heartbeat_run_frames(
    lab: LabRuntime, payload: dict[str, Any], engine: ChatEngine | None, engine_error: LabError | None
) -> Iterator[str]:
    if not lab.lock.acquire(timeout=LOCK_TIMEOUT_SECONDS):
        yield sse_frame({"error": "another Lab operation is still running", "code": "busy"}, event="error")
        return
    try:
        yield from _run(lab, payload, engine, engine_error)
    finally:
        lab.lock.release()


def _run(
    lab: LabRuntime, payload: dict[str, Any], engine: ChatEngine | None, engine_error: LabError | None
) -> Iterator[str]:
    started = time.perf_counter()
    secrets = lab.secret_values(payload)
    light = payload.get("lightContext")
    light_context = lab.settings.heartbeat_light_context if light is None else bool(light)
    session = lab.session("heartbeat")
    now = lab.heartbeat_now_ms()
    run: dict[str, Any] = {
        "id": lab.allocate_heartbeat_run_id(),
        "ts": lab.now_ms(),
        "virtualNowMs": now,
        "lightContext": light_context,
        "sessionKey": session.key,
    }
    try:
        lab.ensure()
        turn = prepare_heartbeat_turn(lab.root, now_ms=now, task_state=lab.heartbeat_task_state, layout=lab.layout)
        decision = flush_decision(lab, session, turn.prompt, is_heartbeat=True)
        run["flush"] = decision
        lab.bus.emit("flush.decided", summary=f"flush kararı: {decision['reason']} (heartbeat)", data=decision)
        yield sse_frame({"decision": decision}, event="flush")
        if turn.skip_reason:
            run["skipped"] = turn.skip_reason
            run["ms"] = int((time.perf_counter() - started) * 1000)
            _record(lab, run)
            lab.bus.emit("heartbeat.skipped", summary=f"heartbeat atlandı: {turn.skip_reason} · model çağrısı yok",
                         data={"reason": turn.skip_reason, "runId": run["id"]})
            yield sse_frame({"reason": turn.skip_reason, "runId": run["id"]}, event="skipped")
            yield sse_frame({"run": run}, event="done")
            return
        if engine is None:
            error = engine_error or LabError(400, "no chat model key", code="no_api_key")
            yield sse_frame({**error.payload(), "redacted": True}, event="error")
            return

        embedding = lab.resolve_embedding(payload)
        mode = lab.default_search_mode(embedding)
        config = lab.config(mode=mode)
        store = lab.store(embedding, mode=mode)
        lab.reindex(store)
        options = PromptOptions(kind="heartbeat", context_mode="lightweight" if light_context else "full")
        wc = lab_workspace_context(lab, options, session=session)
        heartbeat_prompt = resolve_heartbeat_prompt_for_system_prompt(
            trigger="heartbeat", every=lab.settings.heartbeat_every
        )
        section = build_heartbeat_section_lines(heartbeat_prompt)
        toolbox = LabToolbox(lab, config, store, session, turn_id=None)
        tool_names = sorted(toolbox.names())
        memory_section = build_prompt_section(set(tool_names), citations_mode=config.citation_mode)
        # The host appends its own current-time line (appendCronStyleCurrentTimeLine).
        user_message = append_cron_style_current_time_line(turn.prompt or "", now_ms=lab.now_ms(), timezone=LAB_TIMEZONE)
        previous = [ChatMessage(role=item["role"], content=item["content"]) for item in session.messages]
        sent, _omitted = select_transcript_context([*previous, ChatMessage(role="user", content=user_message)], max_chars=24_000)
        messages = assemble_messages(
            system_sections=["\n".join(memory_section), "\n".join(line for line in section), wc.prompt_text],
            recall_lines=[],
            sent=sent,
        )
        view = prompt_view(lab, options, wc, extras={
            "heartbeatSection": section, "tools": tool_names, "messages": messages,
            "recall": {"lines": [], "memoryRecallSection": memory_section, "label": "demo-only"},
        })
        run.update({
            "userMessage": user_message,
            "systemSection": "\n".join(line for line in section if line),
            "files": [file["name"] for file in view["files"]],
            "dueTasks": [task.name for task in turn.due_tasks],
            "prompt": view,
        })
        lab.bus.emit("heartbeat.run", summary=f"heartbeat #{run['id']} · {len(turn.due_tasks)} görev",
                     data={"runId": run["id"], "dueTasks": run["dueTasks"], "files": run["files"]})
        yield sse_frame({"userMessage": user_message, "systemSection": run["systemSection"], "files": run["files"],
                         "bootstrapMode": view["bootstrapMode"], "tools": tool_names, "prompt": view}, event="prompt")
        lab.bus.emit("heartbeat.llm", summary=f"heartbeat modeli: {engine.model}",
                     data={"provider": getattr(engine, "provider", engine.name), "model": engine.model})
        outcome = ToolLoopOutcome()
        for event, data in run_tool_loop(engine, messages, toolbox, outcome):
            yield sse_frame(data, event=event)
            if event == "tool_result" and data.get("curation"):
                yield sse_frame(data["curation"], event="curation")
        reply = outcome.text
        stripped = strip_heartbeat_token(reply, mode="heartbeat", max_ack_chars=lab.settings.heartbeat_ack_max_chars)
        remainder = strip_heartbeat_token(reply, mode="message")
        result = {
            "shouldSkip": stripped.should_skip,
            "text": stripped.text,
            "didStrip": stripped.did_strip,
            "remainderChars": utf16_len(remainder.text),
            "delivered": not stripped.should_skip,
            "ackMaxChars": lab.settings.heartbeat_ack_max_chars,
        }
        lab.heartbeat_task_state = turn.next_task_state(lab.heartbeat_task_state)
        session.messages.append({"role": "user", "content": HEARTBEAT_TRANSCRIPT_PROMPT})
        session.messages.append({"role": "assistant", "content": reply})
        update_token_snapshot(session, outcome.usage, messages=outcome.messages, output_text=reply)
        run.update({
            "reply": reply,
            "decision": result,
            "engine": {"provider": getattr(engine, "provider", engine.name), "model": engine.model},
            "toolCalls": toolbox.calls,
            "curation": [public_write(write) for write in toolbox.curated],
            "taskState": lab.heartbeat_task_state,
            "ms": int((time.perf_counter() - started) * 1000),
        })
        _record(lab, run)
        lab.bus.emit(
            "heartbeat.decided",
            summary="heartbeat: teslim edildi" if result["delivered"] else "heartbeat: teslim edilmedi (ack)",
            data={"runId": run["id"], **result},
        )
        yield sse_frame(result, event="decision")
        yield sse_frame({"run": run}, event="done")
    except Exception as exc:
        message = f"heartbeat run failed: {safe_exception_message(exc, secrets)}"
        run.update({"error": message, "ms": int((time.perf_counter() - started) * 1000)})
        _record(lab, run)
        lab.bus.emit("error", summary=message, data={"runId": run["id"], "source": "heartbeat"})
        yield sse_frame({"error": message, "code": "heartbeat_failed", "redacted": True}, event="error")


def _record(lab: LabRuntime, run: dict[str, Any]) -> None:
    lab.heartbeat_runs.append(run)
    del lab.heartbeat_runs[:-HEARTBEAT_RUN_HISTORY]
