"""The Lab host's side of the memory flush: the gate view, the flush run and ``/flush``.

``HostKit.after_turn`` decides the flush after the reply (v2026.9.6 session maintenance, decision
Q1) and hands over a ``FlushRequest``; the kit's ``request_flush`` is ``/flush`` (a labelled Lab
extension, decision Q6). What stays here is what a host keeps: the provider usage it passes as
``TurnUsage`` (a labelled chars/4 estimate when the provider sends none), the transcript size
(the UTF-8 size of the session's JSON message lines; upstream reads the session JSONL file), the
flush run over the Lab's chat engine (the host's model: the request's messages and tool through
the Lab tool loop, then ``complete``), its events, and the view of the gate for the status bar,
the prompt inspector and the SSE ``flush`` frames. The Lab never compacts, so after one flush a
session stays in the same compaction cycle (``already_flushed``) until ``/new`` (known gap).
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

from demo.chat_engine import ChatEngine
from demo.lab_runtime import (
    LAB_TIME_FORMAT,
    LabRuntime,
    LabSession,
    redact_secrets,
    safe_exception_message,
)
from demo.lab_settings import flush_settings
from demo.lab_tools import (
    ToolLoopOutcome,
    finish_call,
    preview_arguments,
    redact_tool_diagnostics,
    run_tool_loop,
)
from memory_core.bootstrap._js import utf16_len
from memory_core.host import FlushRequest, TurnRecord, TurnUsage
from memory_core.memory_flush import (
    MemoryFlushFailureOutcome,
    has_already_flushed_for_current_compaction,
    resolve_fresh_session_total_tokens,
)

NO_COMPACTION_NOTE = (
    "Lab never compacts: after a flush this session stays in the same compaction cycle "
    "(already_flushed) until /new (known gap)"
)
FORCED_FLUSH_LABEL = (
    "Lab extension (decision Q6): HostKit.request_flush, outside the token gate; upstream has "
    "no forced flush"
)


def transcript_byte_size(session: LabSession) -> int:
    return sum(
        len(json.dumps(message, ensure_ascii=False).encode("utf-8")) + 1
        for message in session.messages
    )


def turn_usage(
    session: LabSession, usage: dict[str, Any] | None, *, messages: list[dict[str, Any]], output_text: str
) -> TurnUsage:
    """The turn's usage for the kit: the provider's, else a chars/4 estimate (labelled)."""
    prompt_tokens = (usage or {}).get("promptTokens")
    completion_tokens = (usage or {}).get("completionTokens")
    if isinstance(prompt_tokens, int) and prompt_tokens > 0:
        session.token_source = "provider usage"
        return TurnUsage(
            prompt_tokens, completion_tokens if isinstance(completion_tokens, int) else None
        )
    session.token_source = "estimate (chars/4; provider sent no usage)"
    chars = sum(utf16_len(str(message.get("content") or "")) for message in messages)
    return TurnUsage(
        max(1, math.ceil(chars / 4)), math.ceil(utf16_len(output_text) / 4) if output_text else 0
    )


def flush_view(lab: LabRuntime, session: LabSession, record: TurnRecord | None) -> dict[str, Any]:
    """The flush gate as the Lab shows it.

    The terms of the Lab's current window (reserve and soft threshold derive from it), the
    decision of ``record`` (a turn's ``HostKit.after_turn``; ``None`` before the first turn) and
    the session's current ``memoryFlush`` state. The status bar shows it between turns.
    """
    settings = lab.settings
    terms = flush_settings(settings.context_window_tokens, settings.effective_context_window_tokens)
    entry = dict(session.state.entry)
    memory_flush = entry.get("memoryFlush") if isinstance(entry.get("memoryFlush"), dict) else {}
    decision = record.flush_decision if record is not None else None
    return {
        "shouldRun": decision.should_flush if decision is not None else False,
        "reason": decision.reason if decision is not None else None,
        "totalTokens": decision.total_tokens if decision is not None else None,
        "threshold": terms["threshold"],
        "tokenGate": decision.token_gate if decision is not None else False,
        "transcriptSizeGate": decision.transcript_size_gate if decision is not None else False,
        "alreadyFlushed": has_already_flushed_for_current_compaction(entry),
        "contextWindowTokens": terms["effectiveContextWindowTokens"],
        "contextWindowSource": (
            "setting" if settings.context_window_tokens else "upstream DEFAULT_CONTEXT_TOKENS"
        ),
        "reserveTokensFloor": terms["reserveTokensFloor"],
        "softThresholdTokens": terms["softThresholdTokens"],
        # The terms before the window caps them (flush-plan.ts): upstream's defaults.
        "defaults": terms["defaults"],
        "persistedPromptTokens": resolve_fresh_session_total_tokens(entry),
        "lastOutputTokens": session.state.last_output_tokens,
        "tokenSource": session.token_source,
        "transcriptBytes": transcript_byte_size(session),
        "forceFlushTranscriptBytes": (
            record.flush_plan.force_flush_transcript_bytes if record is not None else None
        ),
        "compactionCount": entry.get("compactionCount", 0),
        "memoryFlush": memory_flush or None,
        "memoryFlushCompactionCount": memory_flush.get("compactionCount"),
        "memoryFlushFailureCount": (
            memory_flush.get("failureCount", 0) if memory_flush.get("kind") == "failed" else 0
        ),
        "target": record.flush_plan.relative_path if record is not None else None,
        "timeFormat": LAB_TIME_FORMAT,
        "timeFormatSource": "host-supplied (upstream detects the host's 12/24-hour format)",
        "mode": "threshold",
        "order": "after the reply (v2026.9.6 session maintenance)",
        "note": NO_COMPACTION_NOTE,
    }


def flush_meter(lab: LabRuntime, session: LabSession) -> dict[str, Any]:
    """The gate meter between turns: :func:`flush_view` of the session's last turn."""
    return flush_view(lab, session, session.last_turn)


def request_view(request: FlushRequest) -> dict[str, Any]:
    """What the flush turn gets: the prompt inspector's Flush section."""
    return {
        "reason": request.reason,
        "target": request.target,
        "systemPrompt": request.messages[0]["content"],
        "prompt": request.messages[-1]["content"],
        "transcriptMessages": len(request.messages) - 2,
        "tools": [tool["name"] for tool in request.tools],
    }


def report_failure(
    lab: LabRuntime,
    failure: MemoryFlushFailureOutcome,
    *,
    error_text: str,
    secrets: tuple[str, ...],
    turn_id: int | None,
) -> dict[str, Any]:
    """The payload and event of one failed flush (a strike; three mark the cycle flushed)."""
    payload = {
        "error": f"memory flush failed: {redact_secrets(error_text, secrets)}",
        "message": redact_secrets(failure.error, secrets),
        "failureCount": failure.failure_count,
        "exhausted": failure.exhausted,
        "redacted": True,
    }
    lab.bus.emit(
        "flush.exhausted" if failure.exhausted else "flush.failed",
        summary=f"flush başarısız ({failure.failure_count}/3)",
        data=payload,
        turn_id=turn_id,
    )
    return payload


class FlushToolbox:
    """The flush run's one tool (``FlushRequest.tools``) for the Lab tool loop."""

    def __init__(self, request: FlushRequest, *, secrets: tuple[str, ...] = ()) -> None:
        self.request = request
        self.secrets = secrets
        self.calls: list[dict[str, Any]] = []

    def definitions(self) -> list[dict[str, Any]]:
        return list(self.request.tools)

    def dispatch(self, call_id: str, name: str, raw_arguments: str) -> dict[str, Any]:
        started = time.perf_counter()
        record = {"id": call_id, "name": name, "arguments": preview_arguments(raw_arguments)}
        result = redact_tool_diagnostics(self.request.dispatch(name, raw_arguments), self.secrets)
        finish_call(record, result, started)
        self.calls.append(record)
        return record


def run_flush(
    lab: LabRuntime,
    session: LabSession,
    engine: ChatEngine,
    request: FlushRequest,
    *,
    turn_id: int | None,
    secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Run one flush request with the Lab's model and record it in the session.

    The request's messages and write tool go through the Lab tool loop; the reply is never
    delivered and never enters the transcript. ``complete`` then stamps the session's
    ``memoryFlush`` state (success, or a strike with the cause chain, redacted with the Lab's
    key values and the builtin diagnostic redaction policy).
    """
    toolbox = FlushToolbox(request, secrets=secrets)
    loop = ToolLoopOutcome()
    error: Exception | None = None
    with lab.tracked("flush", turn_id=turn_id) as changes:
        try:
            messages = [dict(message) for message in request.messages]
            for _event in run_tool_loop(engine, messages, toolbox, loop, secrets=secrets):
                pass
        except Exception as exc:
            error = exc
    outcome = request.complete(
        session.state, error=error, redact=lambda text: redact_secrets(text, secrets)
    )
    session.state = outcome.session
    result: dict[str, Any] = {
        **request_view(request),
        "wrote": outcome.wrote,
        "entries": list(outcome.entries),
        "reply": loop.text,
        "rounds": loop.rounds,
        "toolCalls": toolbox.calls,
        "diff": next((change["diff"] for change in changes if change["path"] == request.target), ""),
    }
    if outcome.failure is not None:
        result["error"] = report_failure(
            lab,
            outcome.failure,
            error_text=safe_exception_message(error, secrets),
            secrets=secrets,
            turn_id=turn_id,
        )
    elif outcome.wrote:
        lab.bus.emit(
            "flush.written",
            summary=f"flush → {request.target}",
            data={"target": request.target, "reason": request.reason, "entries": len(outcome.entries)},
            turn_id=turn_id,
        )
    else:
        lab.bus.emit(
            "flush.no_write",
            summary="flush yazmadı: ekleme yok",
            data={"target": request.target, "reason": request.reason, "reply": loop.text},
            turn_id=turn_id,
        )
    return result
