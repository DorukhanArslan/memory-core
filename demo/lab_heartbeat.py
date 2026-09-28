"""Heartbeat and automation in the Lab over the v2026.9.6 shape (runtime-only port, no scheduler).

``GET /api/lab/heartbeat`` shows the agent's heartbeat monitor scratch (the per-agent checklist
that replaced HEARTBEAT.md), the automation jobs with their due state and next run on the
virtual clock, the preflight and prompt the next heartbeat would get, a leftover HEARTBEAT.md
with its doctor findings, and the run history. ``PUT /api/lab/heartbeat/scratch`` writes or
unsets the scratch by compare-and-swap (upstream ``openclaw cron scratch``); a stale
``expectedRevision`` answers ``409 revision_conflict`` with the write result and the stored
scratch. ``POST
/api/lab/heartbeat/migrate`` runs both doctor migrations (HEARTBEAT.md into scratch, then its
``tasks:`` into automation jobs). ``POST /api/lab/heartbeat/legacy-file`` (demo-only) puts a
legacy HEARTBEAT.md with the caller's text at the Lab root, since nothing else in the Lab can
create a retired file, so the migration, its findings and its archive can be seen. ``POST
/api/lab/heartbeat/run`` runs one heartbeat now through the host kit: ``HostKit.heartbeat_prompt``
turns the due jobs at the virtual clock into scheduled tasks and builds the prompt (skip reason
``empty-heartbeat-file`` makes no model call and runs no ensure) and, unless skipped, the
injected context for session kind ``heartbeat`` (PROACTIVE_PREFERENCES.md included on the
memory-core layout); the same host tool loop as chat turns runs it, so the model can read daily
notes with ``memory_search``/``memory_get``. ``HeartbeatRun.complete`` reads the reply
(``NO_REPLY`` and a legacy ``HEARTBEAT_OK`` ack are not delivered) and reschedules the jobs whose
tasks went into the turn (a due job of another kind is the host's to run and stays due); then
``HostKit.after_turn`` reports the flush decision (``runtime_skip:heartbeat``: heartbeats never
flush). ``POST /api/lab/heartbeat/reply`` decides a typed reply without a model.

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
from demo.lab_flush import flush_view, transcript_byte_size, turn_usage
from demo.lab_prompt import PromptOptions, prompt_view
from demo.lab_runtime import (
    FILE_MAX_BYTES,
    LAB_TIME_FORMAT,
    LabError,
    LabRuntime,
    safe_exception_message,
)
from demo.lab_tools import LabToolbox, ToolLoopOutcome, public_write, run_tool_loop
from demo.transcript_context import select_transcript_context
from memory_core.automation import (
    AutomationJob,
    FileAutomationStore,
    is_heartbeat_task_job,
    is_job_due,
)
from memory_core.bootstrap._js import js_to_well_formed, js_utf8_encode, utf16_len
from memory_core.heartbeat import (
    DEFAULT_HEARTBEAT_ACK_MAX_CHARS,
    decide_heartbeat_reply,
    is_heartbeat_content_effectively_empty,
    is_silent_reply_payload_text,
    resolve_heartbeat_interval_ms,
    strip_heartbeat_token,
)
from memory_core.heartbeat_migration import (
    HEARTBEAT_MIGRATION_ARCHIVE_PARTS,
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
from memory_core.host import HeartbeatRun

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


def _turn_view(run: HeartbeatRun) -> dict[str, Any]:
    turn = run.turn
    return {
        "skipReason": turn.skip_reason,
        "prompt": turn.prompt,
        "message": turn.message,
        "dueTasks": [task.name for task in turn.scheduled_tasks],
        "dueJobs": [job.id for job in run.jobs],
        "hostDueJobs": [job.id for job in run.host_jobs],
        "scratchShown": turn.scratch_content is not None,
        "scratchRevision": turn.scratch_revision,
        "timeFormat": LAB_TIME_FORMAT,
    }


def heartbeat_preview(lab: LabRuntime) -> dict[str, Any]:
    """The prompt the next heartbeat would get (the prompt inspector's heartbeat kind).

    ``HostKit.heartbeat_prompt`` without the ensure, never completed: nothing is written.
    """
    run = lab.kit().heartbeat_prompt(
        lab.session("heartbeat").state, schedule_now_ms=lab.heartbeat_now_ms(), ensure=False
    )
    return _turn_view(run)


def _legacy_archives(lab: LabRuntime) -> list[str]:
    """Files under the migration archive (``<root>/.memory-core/backups/heartbeat-migration/``)."""
    archive = lab.root.joinpath(*HEARTBEAT_MIGRATION_ARCHIVE_PARTS)
    if not archive.is_dir():
        return []
    return sorted(
        path.relative_to(lab.root).as_posix() for path in archive.rglob("*") if path.is_file()
    )


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
        "legacyArchives": _legacy_archives(lab),
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
        # A stale compare-and-swap is an HTTP conflict; the body keeps the write result and the
        # stored scratch so the editor can offer "take stored" or "overwrite".
        raise LabError(
            409,
            f"heartbeat scratch changed: expected rev {expected}, current rev {result.current_revision}",
            code="revision_conflict",
            write=result.to_json(),
            scratch=view,
        )
    return {"write": result.to_json(), "scratch": view}


def write_legacy_file(lab: LabRuntime, payload: dict[str, Any]) -> dict[str, Any]:
    """Demo-only: write a legacy HEARTBEAT.md so the doctor migration has a file to move.

    v2026.9.6 never reads HEARTBEAT.md and the Lab editor refuses it (not a layout file). The
    text is the caller's (scenario S09 sends its ``tasks:`` block); an existing file is left
    alone (409), and the bytes are Node's UTF-8 (a lone surrogate becomes U+FFFD).
    """
    content = payload.get("content")
    if not isinstance(content, str):
        raise LabError(400, "content must be a string", code="invalid_content")
    data = js_utf8_encode(content)
    if len(data) > FILE_MAX_BYTES:
        raise LabError(400, "content is larger than 2 MiB", code="too_large")
    target = lab.root / LEGACY_HEARTBEAT_FILENAME
    if target.exists() or target.is_symlink():
        raise LabError(409, f"{LEGACY_HEARTBEAT_FILENAME} already exists", code="legacy_file_exists")
    with lab.tracked("heartbeat_legacy"):
        target.write_bytes(data)
    findings = [finding.to_json() for finding in heartbeat_md_migration_findings(lab.root)]
    result = {
        "path": LEGACY_HEARTBEAT_FILENAME,
        "bytes": len(data),
        "migrationFindings": [{**finding, "path": _relative(lab, finding["path"])} for finding in findings],
        "label": "demo-only",
    }
    lab.bus.emit(
        "heartbeat.legacy_file_written",
        summary=f"eski HEARTBEAT.md yazıldı (demo-only, {len(data)} bayt): doctor taşıması için",
        data=result,
    )
    return result


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
        embedding = lab.resolve_embedding(payload)
        index = lab.store(embedding, mode=lab.default_search_mode(embedding))
        kit = lab.kit(index)
        options = PromptOptions(kind="heartbeat", context_mode="lightweight" if light_context else "full")
        # The scripted engine calls no tools, so the kit offers none (as in chat turns).
        scripted = getattr(engine, "provider", "") == "scripted"
        with lab.lifecycle() as report:
            heartbeat = kit.heartbeat_prompt(
                session.state,
                context_mode=options.context_mode,  # type: ignore[arg-type]
                offer_tools=not scripted,
                schedule_now_ms=now,
            )
            if heartbeat.context is not None:
                report(heartbeat.context.workspace_init)
        turn = heartbeat.turn
        run["dueTasks"] = [task.name for task in turn.scheduled_tasks]
        run["hostDueJobs"] = [job.id for job in heartbeat.host_jobs]
        run["scratchRevision"] = turn.scratch_revision
        if heartbeat.context is None:
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

        lab.reindex(index)
        context = heartbeat.context
        wc = context.workspace
        toolbox = None if scripted else LabToolbox(lab, kit, session, turn_id=None)
        tool_names = sorted(tool["name"] for tool in context.tools)
        user_message = turn.message or ""
        previous = [ChatMessage(role=item["role"], content=item["content"]) for item in session.messages]
        sent, _omitted = select_transcript_context([*previous, ChatMessage(role="user", content=user_message)], max_chars=24_000)
        messages = assemble_messages(
            system_prompt=context.system_prompt,
            recall_lines=[],
            sent=sent,
        )
        view = prompt_view(lab, options, wc, extras={
            "heartbeatPrompt": _turn_view(heartbeat), "tools": tool_names, "messages": messages,
            "recall": {"lines": [], "memoryRecallSection": list(context.memory_recall), "label": "demo-only"},
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
        loop = ToolLoopOutcome()
        for event, data in run_tool_loop(engine, messages, toolbox, loop):
            yield sse_frame(data, event=event)
            if event == "tool_result" and data.get("curation"):
                yield sse_frame(data["curation"], event="curation")
        reply = loop.text
        usage = turn_usage(session, loop.usage, messages=loop.messages, output_text=reply)
        ended = lab.heartbeat_now_ms()
        outcome = heartbeat.complete(reply, usage=usage, ended_at_ms=ended)
        result = {
            **outcome.decision.to_json(),
            "delivered": outcome.decision.deliver,
            "silentReply": is_silent_reply_payload_text(reply),
            "replyChars": utf16_len(reply or ""),
        }
        if outcome.jobs_recorded:
            lab.bus.emit("automation.jobs_ran", summary=f"{len(outcome.jobs_recorded)} otomasyon işi çalıştı, sonraki vadeler güncellendi",
                         data={"jobs": [_job_view(job, ended) for job in outcome.jobs_recorded]})
        session.messages.extend(outcome.transcript)
        # After the run, as after a chat turn: heartbeat sessions never flush (runtime_skip).
        record = kit.after_turn(
            outcome.session,
            transcript=session.messages,
            usage=usage,
            context_window_tokens=lab.settings.effective_context_window_tokens,
            transcript_bytes=transcript_byte_size(session),
        )
        session.state = record.session
        session.last_turn = record
        run["flush"] = flush_view(lab, session, record)
        lab.bus.emit(
            "flush.decided", summary=f"flush kararı: {run['flush']['reason']} (heartbeat)", data=run["flush"]
        )
        yield sse_frame({"decision": run["flush"]}, event="flush")
        run.update({
            "reply": reply,
            "decision": result,
            "jobsRun": [job.id for job in outcome.jobs_recorded],
            "engine": {"provider": getattr(engine, "provider", engine.name), "model": engine.model},
            "toolCalls": toolbox.calls if toolbox is not None else [],
            "curation": [public_write(write) for write in toolbox.curated] if toolbox is not None else [],
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
