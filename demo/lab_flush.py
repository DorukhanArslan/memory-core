"""Pre-turn memory flush for Lab sessions, in upstream order (D1).

Upstream ``runReplyAgent`` (``src/auto-reply/reply/agent-runner.ts:1585-1627``)
runs preflight compaction, then ``runMemoryFlushIfNeeded``
(``agent-runner-memory.ts:1051-1540``), then the main run. The Lab follows the
same order with the package pieces: ``build_memory_flush_plan`` for the target,
the prompts and (v2026.9.6) the reserve floor and soft threshold derived from the
context window, ``explain_memory_flush_trigger`` for the decision and
``record_memory_flush_success``/``record_memory_flush_failure`` for the
session entry's ``memoryFlush`` state. The flush turn itself (append-only to today's daily file
through the ``write`` tool) is :func:`demo.memory_flush.run_memory_flush`.

Host-side inputs and their Lab approximations (named in each payload):

- the token snapshot: the provider's ``usage.prompt_tokens`` of the previous
  turn (upstream ``totalTokens``, a fresh v1 snapshot: ``totalTokensFresh`` and
  ``totalTokensVersion``) plus its completion tokens plus
  ``estimatePromptTokensForMemoryFlush(prompt)``; without usage the Lab falls
  back to a chars/4 estimate and says so (``tokenSource``);
- the transcript size: the UTF-8 size of the session's JSON message lines
  (upstream reads the session JSONL file);
- the context window: the Lab setting, else upstream ``DEFAULT_CONTEXT_TOKENS``
  (200,000), since the Lab does not know the model's window;
- compaction: the Lab never compacts, so after one flush the session stays in
  the same compaction cycle and later turns report ``already_flushed`` until
  ``/new`` (known gap).
"""

from __future__ import annotations

import json
import math
from typing import Any

from demo.chat_engine import ChatEngine, ChatMessage
from demo.lab_runtime import LAB_TIMEZONE, LabRuntime, LabSession, redact_secrets, safe_exception_message
from demo.memory_flush import MemoryFlushRun, run_memory_flush
from memory_core.bootstrap._js import utf16_len
from memory_core.consolidation import record_daily_memory_flush
from memory_core.memory_flush import (
    DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR,
    DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
    SESSION_TOTAL_TOKENS_VERSION,
    MemoryFlushPlan,
    build_memory_flush_plan,
    explain_memory_flush_trigger,
    has_already_flushed_for_current_compaction,
    record_memory_flush_failure,
    record_memory_flush_success,
    resolve_fresh_session_total_tokens,
)

LAB_FORCED_REASON = "lab_forced"
NO_COMPACTION_NOTE = (
    "Lab never compacts: after a flush this session stays in the same compaction cycle "
    "(already_flushed) until /new (known gap)"
)


def estimate_prompt_tokens_for_memory_flush(prompt: str | None) -> int | None:
    """Port of ``estimatePromptTokensForMemoryFlush`` (agent-runner-memory.ts:178-189).

    ``estimateTokens`` of one user message: ``ceil(chars / 4)`` over UTF-16 units.
    """
    trimmed = (prompt or "").strip()
    if not trimmed:
        return None
    tokens = math.ceil(utf16_len(trimmed) / 4)
    return tokens if tokens > 0 else None


def transcript_byte_size(session: LabSession) -> int:
    return sum(len(json.dumps(message, ensure_ascii=False).encode("utf-8")) + 1 for message in session.messages)


def lab_flush_plan(lab: LabRuntime) -> MemoryFlushPlan:
    """The flush plan for the Lab's context window (upstream builds it per run with the window)."""
    return build_memory_flush_plan(
        workspace_dir=lab.root,
        now_ms=lab.now_ms(),
        timezone=LAB_TIMEZONE,
        context_window_tokens=lab.settings.effective_context_window_tokens,
    )


def flush_decision(
    lab: LabRuntime, session: LabSession, prompt: str | None, *, is_heartbeat: bool = False
) -> dict[str, Any]:
    plan = lab_flush_plan(lab)
    entry = session.flush_entry
    window = lab.settings.effective_context_window_tokens
    estimate = estimate_prompt_tokens_for_memory_flush(prompt)
    persisted = resolve_fresh_session_total_tokens(entry)
    # resolveEffectivePromptTokens: fresh prompt snapshot + last output + prompt estimate.
    projected = (
        int(persisted) + int(session.last_output_tokens or 0) + int(estimate or 0)
        if persisted is not None and persisted > 0
        else None
    )
    size = transcript_byte_size(session)
    decision = explain_memory_flush_trigger(
        entry=entry,
        plan=plan,
        context_window_tokens=window,
        token_count=projected,
        transcript_byte_size=size,
        is_heartbeat=is_heartbeat,
    )
    memory_flush = entry.get("memoryFlush") if isinstance(entry.get("memoryFlush"), dict) else {}
    return {
        "shouldRun": decision.should_flush,
        "reason": decision.reason,
        "totalTokens": decision.total_tokens,
        "threshold": decision.threshold,
        "tokenGate": decision.token_gate,
        "transcriptSizeGate": decision.transcript_size_gate,
        "alreadyFlushed": decision.already_flushed,
        "contextWindowTokens": window,
        "contextWindowSource": "setting" if lab.settings.context_window_tokens else "upstream DEFAULT_CONTEXT_TOKENS",
        "reserveTokensFloor": plan.reserve_tokens_floor,
        "softThresholdTokens": plan.soft_threshold_tokens,
        # The terms before the window caps them (flush-plan.ts): the reserve floor and the soft
        # threshold the Lab configures (none, so upstream's default).
        "defaults": {
            "reserveTokensFloor": DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR,
            "softThresholdTokens": DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
        },
        "promptTokenEstimate": estimate,
        "persistedPromptTokens": persisted,
        "lastOutputTokens": session.last_output_tokens,
        "tokenSource": session.token_source,
        "transcriptBytes": size,
        "forceFlushTranscriptBytes": plan.force_flush_transcript_bytes,
        "compactionCount": entry.get("compactionCount", 0),
        "memoryFlush": memory_flush or None,
        "memoryFlushCompactionCount": memory_flush.get("compactionCount"),
        "memoryFlushFailureCount": memory_flush.get("failureCount", 0) if memory_flush.get("kind") == "failed" else 0,
        "target": plan.relative_path,
        "mode": "threshold",
        "note": NO_COMPACTION_NOTE,
    }


def flush_meter(lab: LabRuntime, session: LabSession) -> dict[str, Any]:
    """The gate meter between turns (no incoming prompt yet)."""
    return flush_decision(lab, session, None, is_heartbeat=session.kind == "heartbeat")


def serialize_flush_run(run: MemoryFlushRun, *, prompt: str, system_prompt: str) -> dict[str, Any]:
    parsed = run.parsed
    return {
        "target": run.target,
        "rawText": run.raw_text,
        "parsed": {
            "shouldWrite": parsed.should_write,
            "target": parsed.target,
            "entry": parsed.entry,
            "reason": parsed.reason,
            "error": parsed.error,
        },
        "wrote": parsed.should_write and parsed.error is None and bool(run.diff),
        "diff": run.diff,
        "indexedFiles": run.indexed_files,
        "chunks": run.chunks,
        "reindexError": run.reindex_error,
        "prompt": prompt,
        "systemPrompt": system_prompt,
    }


def run_flush_turn(
    lab: LabRuntime,
    session: LabSession,
    engine: ChatEngine,
    store: Any,
    *,
    turn_id: int | None,
    reason: str,
    secrets: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Run the flush turn and update the session entry like upstream (success or strike)."""
    plan = lab_flush_plan(lab)
    transcript = [ChatMessage(role=item["role"], content=item["content"]) for item in session.messages]
    try:
        with lab.tracked("flush", turn_id=turn_id):
            run = run_memory_flush(
                config=lab.config(mode=_mode(store)),
                store=store,
                engine=engine,
                transcript=transcript,
                now_ms=lab.now_ms(),
                timezone=LAB_TIMEZONE,
            )
    except Exception as exc:
        # The SDK formats the cause chain and truncates it like upstream; the Lab's key values
        # are the redactor (upstream's redactSensitiveText is not ported).
        outcome = record_memory_flush_failure(
            session.flush_entry, error=exc, redact=lambda text: redact_secrets(text, secrets)
        )
        session.flush_entry = outcome.entry
        error = {
            "error": f"memory flush failed: {safe_exception_message(exc, secrets)}",
            "message": outcome.error,
            "failureCount": outcome.failure_count,
            "exhausted": outcome.exhausted,
            "redacted": True,
        }
        lab.bus.emit(
            "flush.failed" if not outcome.exhausted else "flush.exhausted",
            summary=f"flush başarısız ({outcome.failure_count}/3)",
            data=error,
            turn_id=turn_id,
        )
        return {"reason": reason, "error": error, "wrote": False, "prompt": plan.prompt,
                "systemPrompt": plan.system_prompt, "target": plan.relative_path}
    session.flush_entry = record_memory_flush_success(session.flush_entry)
    result = serialize_flush_run(run, prompt=plan.prompt, system_prompt=plan.system_prompt)
    result["reason"] = reason
    if result["wrote"]:
        with lab.tracked("recall", turn_id=turn_id):
            record_daily_memory_flush(
                config=lab.config(mode=_mode(store)),
                target=result["parsed"]["target"],
                entry=result["parsed"]["entry"],
                now_ms=lab.now_ms(),
            )
        lab.bus.emit(
            "flush.written",
            summary=f"flush → {result['target']}",
            data={"target": result["target"], "reason": reason},
            turn_id=turn_id,
        )
    else:
        lab.bus.emit(
            "flush.no_write",
            summary=f"flush yazmadı: {result['parsed']['reason']}",
            data={"target": result["target"], "reason": result["parsed"]["reason"],
                  "rawText": result["rawText"]},
            turn_id=turn_id,
        )
    return result


def update_token_snapshot(session: LabSession, usage: dict[str, Any] | None, *, messages: list[dict[str, Any]],
                          output_text: str) -> None:
    """After a turn: the provider's usage, else a chars/4 estimate (labelled)."""
    prompt_tokens = (usage or {}).get("promptTokens")
    completion_tokens = (usage or {}).get("completionTokens")
    if isinstance(prompt_tokens, int) and prompt_tokens > 0:
        session.flush_entry["totalTokens"] = prompt_tokens
        session.flush_entry["totalTokensFresh"] = True
        session.flush_entry["totalTokensVersion"] = SESSION_TOTAL_TOKENS_VERSION
        session.last_output_tokens = completion_tokens if isinstance(completion_tokens, int) else None
        session.token_source = "provider usage"
        return
    chars = sum(utf16_len(str(message.get("content") or "")) for message in messages)
    session.flush_entry["totalTokens"] = max(1, math.ceil(chars / 4))
    session.flush_entry["totalTokensFresh"] = True
    session.flush_entry["totalTokensVersion"] = SESSION_TOTAL_TOKENS_VERSION
    session.last_output_tokens = math.ceil(utf16_len(output_text) / 4) if output_text else 0
    session.token_source = "estimate (chars/4; provider sent no usage)"


def forced_flush_blocked(session: LabSession) -> bool:
    return has_already_flushed_for_current_compaction(session.flush_entry)


def _mode(store: Any) -> str:
    name = getattr(getattr(store, "path", None), "stem", "lab-text")
    return name.removeprefix("lab-") if name.startswith("lab-") else "text"
