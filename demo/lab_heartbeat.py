"""Heartbeat and automation in the Lab over the v2026.9.6 shape (runtime-only port, no scheduler).

``GET /api/lab/heartbeat`` shows the agent's heartbeat monitor scratch (the per-agent checklist
that replaced HEARTBEAT.md), the automation jobs with their due state and next run on the
virtual clock, the preflight and prompt the next heartbeat would get, a leftover HEARTBEAT.md
with its doctor findings, and the run history. ``PUT /api/lab/heartbeat/scratch`` writes or
unsets the scratch by compare-and-swap (upstream ``openclaw cron scratch``). ``POST
/api/lab/heartbeat/migrate`` runs both doctor migrations (HEARTBEAT.md into scratch, then its
``tasks:`` into automation jobs). ``POST /api/lab/heartbeat/run`` runs one heartbeat now:
the due jobs become scheduled tasks, ``prepare_heartbeat_turn`` builds the prompt (skip reason
``empty-heartbeat-file`` makes no model call), the flush decision with ``is_heartbeat=True``
(``runtime_skip:heartbeat``), the injected context for session kind ``heartbeat``
(PROACTIVE_PREFERENCES.md included on the memory-core layout), then the same host tool loop as chat
turns, so the model can read daily notes with ``memory_search``/``memory_get``. The reply goes
through ``decide_heartbeat_reply`` (``NO_REPLY`` and a legacy ``HEARTBEAT_OK`` ack are not
delivered), and every due job is rescheduled from the run. ``POST /api/lab/heartbeat/reply``
decides a typed reply without a model.

Demo-only: the virtual clock shifts due checks, job runs and migrated anchors only; the
prompt's current-time lines, daily file dates and the flush use the real clock. Scratch and
jobs live in ``<workspace>/.memory-core/automation.json`` (``FileAutomationStore``).
"""

from __future__ import annotations

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
from memory_core.automation import (
    AutomationJob,
    FileAutomationStore,
    due_automation_jobs,
    heartbeat_scheduled_tasks,
    is_heartbeat_task_job,
    is_job_due,
    record_automation_job_run,
)
from memory_core.bootstrap._js import js_to_well_formed, js_utf8_encode, utf16_len
from memory_core.heartbeat import (
    DEFAULT_HEARTBEAT_ACK_MAX_CHARS,
    HEARTBEAT_TRANSCRIPT_PROMPT,
    HeartbeatTurn,
    decide_heartbeat_reply,
    is_heartbeat_content_effectively_empty,
    is_silent_reply_payload_text,
    prepare_heartbeat_turn,
    resolve_heartbeat_interval_ms,
    strip_heartbeat_token,
)
from memory_core.heartbeat_migration import (
    LEGACY_HEARTBEAT_FILENAME,
    heartbeat_md_migration_findings,
    heartbeat_task_migration_findings,
    migrate_heartbeat_md,
    migrate_heartbeat_tasks,
)
from memory_core.heartbeat_scratch import (
    CRON_JOB_SCRATCH_MAX_BYTES,
    HeartbeatScratchState,
    HeartbeatScratchTooLargeError,
)
from memory_core.prompt_section import build_prompt_section

HEARTBEAT_RUN_HISTORY = 20
HEARTBEAT_AGENT_ID = "main"
MAX_CLOCK_OFFSET_MS = 30 * 24 * 60 * 60 * 1000
LABELS = {
    "runtime": "runtime-only port · zamanlayıcı yok (elle çalıştırılır)",
    "clock": "sanal saat (demo-only): vade, iş çalıştırma ve taşıma çapaları; günlük dosya tarihleri, zaman satırı ve flush gerçek saatle",
    "store": "Lab deposu: .memory-core/automation.json (FileAutomationStore; upstream paylaşılan state DB'de tutar)",
    "scheduler": "zamanlayıcı host'ta: memory-core yalnız vadesi gelen işleri ve heartbeat istemini hesaplar",
}


def automation_store(lab: LabRuntime) -> FileAutomationStore:
    return FileAutomationStore(lab.root)


def _scratch_view(state: HeartbeatScratchState) -> dict[str, Any]:
    scratch = state.scratch
    content = scratch.content if scratch is not None else None
    if scratch is None:
        status = "unset" if state.current_revision > 0 else "none"
    else:
        status = "empty" if is_heartbeat_content_effectively_empty(content) else "active"
    return {
        "agentId": HEARTBEAT_AGENT_ID,
        "status": status,
        "currentRevision": state.current_revision,
        "content": content,
        "bytes": len(js_utf8_encode(content)) if content is not None else 0,
        "maxBytes": CRON_JOB_SCRATCH_MAX_BYTES,
        "sourceSha256": scratch.source_sha256 if scratch is not None else None,
        "updatedAtMs": scratch.updated_at_ms if scratch is not None else None,
    }


def _job_view(job: AutomationJob, now_ms: int) -> dict[str, Any]:
    return {
        "id": job.id,
        "name": job.name,
        "displayName": job.display_name,
        "description": job.description,
        "declarationKey": job.declaration_key,
        "heartbeatTask": is_heartbeat_task_job(job),
        "enabled": job.enabled,
        "everyMs": job.every_ms,
        "anchorMs": job.anchor_ms,
        "prompt": job.text,
        "lastRunAtMs": job.last_run_at_ms,
        "nextRunAtMs": job.next_run_at_ms,
        "due": is_job_due(job, now_ms),
    }


def _proactive_state(lab: LabRuntime) -> str:
    name = "PROACTIVE_PREFERENCES.md"
    if name not in lab.layout.load_order:
        return "outside_layout"
    path = lab.root / name
    if not path.is_file():
        return "absent"
    return "injected" if path.read_text(encoding="utf-8", errors="replace").strip() else "empty"


def _prepare_turn(lab: LabRuntime, store: FileAutomationStore) -> tuple[HeartbeatTurn, list[AutomationJob]]:
    now = lab.heartbeat_now_ms()
    due = due_automation_jobs(store.list_jobs(agent_id=HEARTBEAT_AGENT_ID), now)
    turn = prepare_heartbeat_turn(
        now_ms=lab.now_ms(),
        scratch=store.read_scratch(HEARTBEAT_AGENT_ID),
        scheduled_tasks=heartbeat_scheduled_tasks(due),
        timezone=LAB_TIMEZONE,
    )
    return turn, due


def heartbeat_preview(lab: LabRuntime) -> dict[str, Any]:
    """The prompt the next heartbeat would get (the prompt inspector's heartbeat kind)."""
    turn, due = _prepare_turn(lab, automation_store(lab))
    return {
        "skipReason": turn.skip_reason,
        "prompt": turn.prompt,
        "message": turn.message,
        "dueTasks": [task.name for task in turn.scheduled_tasks],
        "dueJobs": [job.id for job in due],
        "scratchShown": turn.scratch_content is not None,
        "scratchRevision": turn.scratch_revision,
    }


def heartbeat_state(lab: LabRuntime) -> dict[str, Any]:
    store = automation_store(lab)
    now = lab.heartbeat_now_ms()
    legacy = lab.root / LEGACY_HEARTBEAT_FILENAME
    findings = [
        *(finding.to_json() for finding in heartbeat_md_migration_findings(lab.root)),
        *(finding.to_json() for finding in heartbeat_task_migration_findings(store)),
    ]
    every = lab.settings.heartbeat_every
    return {
        "scratch": _scratch_view(store.read_scratch(HEARTBEAT_AGENT_ID)),
        "jobs": [_job_view(job, now) for job in store.list_jobs(agent_id=HEARTBEAT_AGENT_ID)],
        # Rows list_jobs skips (a shape memory-core does not model, values the cron store refuses).
        "skippedJobRows": [row.to_json() for row in store.skipped_job_rows()],
        "legacyFile": {"path": LEGACY_HEARTBEAT_FILENAME, "exists": legacy.exists() or legacy.is_symlink()},
        "migrationFindings": [
            {**finding, "path": _relative(lab, finding["path"])} for finding in findings
        ],
        "every": every,
        "everyMs": resolve_heartbeat_interval_ms(every),
        # v2026.9.6 retired heartbeat.ackMaxChars; the ack limit is fixed.
        "ackLimit": DEFAULT_HEARTBEAT_ACK_MAX_CHARS,
        "lightContext": lab.settings.heartbeat_light_context,
        "preflight": heartbeat_preview(lab),
        "clock": {"nowMs": now, "offsetMs": lab.clock_offset_ms},
        "runs": list(reversed(lab.heartbeat_runs[-HEARTBEAT_RUN_HISTORY:])),
        "proactivePreferences": _proactive_state(lab),
        "sessionKey": lab.session("heartbeat").key,
        "store": ".memory-core/automation.json",
        "labels": LABELS,
    }


def _relative(lab: LabRuntime, path: str) -> str:
    prefix = str(lab.root) + "/"
    return path[len(prefix) :] if path.startswith(prefix) else path


def write_scratch(lab: LabRuntime, payload: dict[str, Any]) -> dict[str, Any]:
    content = payload.get("content")
    if content is not None and not isinstance(content, str):
        raise LabError(400, "content must be a string (or null to unset)", code="invalid_content")
    expected = payload.get("expectedRevision")
    if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int) or expected < 0):
        raise LabError(400, "expectedRevision must be a non-negative integer", code="invalid_revision")
    if content is not None:
        # The store keeps the well-formed text (a lone surrogate becomes U+FFFD, as upstream's
        # SQLite row); the Lab sends that text, so its JSON answer and events stay encodable.
        content = js_to_well_formed(content)
    store = automation_store(lab)
    try:
        result = store.write_scratch(
            HEARTBEAT_AGENT_ID, content, expected_revision=expected, now_ms=lab.now_ms()
        )
    except HeartbeatScratchTooLargeError as error:
        raise LabError(400, str(error), code="scratch_too_large") from error
    view = _scratch_view(store.read_scratch(HEARTBEAT_AGENT_ID))
    if result.ok:
        summary = (
            f"heartbeat scratch kaldırıldı (rev {result.current_revision})"
            if content is None
            else f"heartbeat scratch yazıldı (rev {result.current_revision}, {view['bytes']} bayt)"
        )
        lab.bus.emit("heartbeat.scratch_written", summary=summary, data={"write": result.to_json(), "scratch": view})
    else:
        lab.bus.emit(
            "heartbeat.scratch_conflict",
            summary=f"heartbeat scratch çakışması: rev {expected} beklendi, güncel {result.current_revision}",
            data={"write": result.to_json()},
        )
    return {"write": result.to_json(), "scratch": view}


def migrate(lab: LabRuntime) -> dict[str, Any]:
    """Both doctor migrations on the Lab workspace (HEARTBEAT.md -> scratch, tasks: -> jobs)."""
    store = automation_store(lab)
    with lab.tracked("heartbeat_migration"):
        scratch = migrate_heartbeat_md(lab.root, store, now_ms=lab.now_ms())
    tasks = migrate_heartbeat_tasks(store, now_ms=lab.heartbeat_now_ms())
    payload = {
        "scratch": {"changes": list(scratch.changes), "warnings": list(scratch.warnings)},
        "tasks": {
            "changes": list(tasks.changes),
            "warnings": list(tasks.warnings),
            "jobs": [job.id for job in tasks.jobs],
        },
    }
    changes = [*scratch.changes, *tasks.changes]
    warnings = [*scratch.warnings, *tasks.warnings]
    if changes:
        summary = " · ".join(changes)
    elif warnings:
        summary = "heartbeat taşınamadı: " + warnings[0]
    else:
        summary = "taşınacak HEARTBEAT.md veya scratch görevi yok"
    lab.bus.emit("heartbeat.migrated", summary=summary, data=payload)
    return payload


def reply_payload(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("text")
    if not isinstance(text, str):
        raise LabError(400, "text must be a string", code="invalid_text")
    decision = decide_heartbeat_reply(text)
    legacy = strip_heartbeat_token(text, mode="heartbeat")
    return {
        **decision.to_json(),
        "delivered": decision.deliver,
        "silentReply": is_silent_reply_payload_text(text),
        "legacyAck": {"shouldSkip": legacy.should_skip, "text": legacy.text, "didStrip": legacy.did_strip},
        "label": "yalnız karar kuralı (model yok)",
    }


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
        store = automation_store(lab)
        turn, due = _prepare_turn(lab, store)
        run["dueTasks"] = [task.name for task in turn.scheduled_tasks]
        run["scratchRevision"] = turn.scratch_revision
        decision = flush_decision(lab, session, turn.message, is_heartbeat=True)
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
        index = lab.store(embedding, mode=mode)
        lab.reindex(index)
        options = PromptOptions(kind="heartbeat", context_mode="lightweight" if light_context else "full")
        wc = lab_workspace_context(lab, options, session=session)
        toolbox = LabToolbox(lab, config, index, session, turn_id=None)
        tool_names = sorted(toolbox.names())
        memory_section = build_prompt_section(set(tool_names), citations_mode=config.citation_mode)
        user_message = turn.message or ""
        previous = [ChatMessage(role=item["role"], content=item["content"]) for item in session.messages]
        sent, _omitted = select_transcript_context([*previous, ChatMessage(role="user", content=user_message)], max_chars=24_000)
        messages = assemble_messages(
            system_sections=["\n".join(memory_section), wc.prompt_text],
            recall_lines=[],
            sent=sent,
        )
        view = prompt_view(lab, options, wc, extras={
            "heartbeatPrompt": heartbeat_preview(lab), "tools": tool_names, "messages": messages,
            "recall": {"lines": [], "memoryRecallSection": memory_section, "label": "demo-only"},
        })
        run.update({
            "userMessage": user_message,
            "scratchShown": turn.scratch_content is not None,
            "files": [file["name"] for file in view["files"]],
            "prompt": view,
        })
        lab.bus.emit("heartbeat.run", summary=f"heartbeat #{run['id']} · {len(turn.scheduled_tasks)} görev",
                     data={"runId": run["id"], "dueTasks": run["dueTasks"], "files": run["files"]})
        yield sse_frame({"userMessage": user_message, "scratchShown": run["scratchShown"], "files": run["files"],
                         "bootstrapMode": view["bootstrapMode"], "tools": tool_names, "prompt": view}, event="prompt")
        lab.bus.emit("heartbeat.llm", summary=f"heartbeat modeli: {engine.model}",
                     data={"provider": getattr(engine, "provider", engine.name), "model": engine.model})
        outcome = ToolLoopOutcome()
        for event, data in run_tool_loop(engine, messages, toolbox, outcome):
            yield sse_frame(data, event=event)
            if event == "tool_result" and data.get("curation"):
                yield sse_frame(data["curation"], event="curation")
        reply = outcome.text
        reply_decision = decide_heartbeat_reply(reply)
        result = {
            **reply_decision.to_json(),
            "delivered": reply_decision.deliver,
            "silentReply": is_silent_reply_payload_text(reply),
            "replyChars": utf16_len(reply or ""),
        }
        ended = lab.heartbeat_now_ms()
        ran = [record_automation_job_run(job, started_at_ms=now, ended_at_ms=ended) for job in due]
        if ran:
            store.save_jobs(ran)
            lab.bus.emit("automation.jobs_ran", summary=f"{len(ran)} otomasyon işi çalıştı, sonraki vadeler güncellendi",
                         data={"jobs": [_job_view(job, ended) for job in ran]})
        session.messages.append({"role": "user", "content": HEARTBEAT_TRANSCRIPT_PROMPT})
        session.messages.append({"role": "assistant", "content": reply})
        update_token_snapshot(session, outcome.usage, messages=outcome.messages, output_text=reply)
        run.update({
            "reply": reply,
            "decision": result,
            "jobsRun": [job.id for job in ran],
            "engine": {"provider": getattr(engine, "provider", engine.name), "model": engine.model},
            "toolCalls": toolbox.calls,
            "curation": [public_write(write) for write in toolbox.curated],
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
