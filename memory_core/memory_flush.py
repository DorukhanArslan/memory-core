"""OpenClaw pre-compaction memory flush: plan, runtime gate and session-entry state.

Ported from OpenClaw v2026.9.6 (``eb377ac59e6``):

- ``extensions/memory-core/src/flush-plan.ts`` ``buildMemoryFlushPlan``: the daily target,
  the prompts and the thresholds. The prompts, hints and defaults are script-extracted
  (``memory_core/_memory_flush_constants.py``). The reserve floor and the soft threshold derive
  from the context window (6b6f1969c11 #130072); the prompt/systemPrompt overrides
  (edecdbd05ef #111527) and the ``reserveTokensFloor`` knob (783a5d21cfc #111382) are gone.
- ``src/auto-reply/reply/memory-flush.ts``: ``resolveCompactionThreshold``,
  ``shouldRunMemoryFlush`` with a precomputed ``threshold`` (084d51d0c7b #152268) and the
  same-cycle guard on ``entry.memoryFlush.compactionCount`` (8ee1d046d33 #115299).
- ``src/auto-reply/reply/agent-runner-memory.ts`` ``runMemoryFlushIfNeeded``: the flush
  threshold, the transcript-size force path, the runtime skips and the ``memoryFlush``
  success/failure state.
- ``src/auto-reply/reply/memory-flush-session.ts`` ``ensureMemoryFlushTargetFile``: the empty
  target file created before the flush run.

The host supplies the context window, the token snapshot and the transcript size; memory-core
decides. Writes stay append-only to ``memory/YYYY-MM-DD.md`` (``memory_core.memory_paths``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import tzinfo
import math
import os
from pathlib import Path
import re
from typing import Any

from memory_core._memory_flush_constants import (
    DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR,
    DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES,
    DEFAULT_MEMORY_FLUSH_PROMPT,
    DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
    DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT,
    MAX_COMPACTION_RESERVE_RATIO,
    MAX_FLUSH_ERROR_LENGTH,
    MAX_FLUSH_FAILURES,
    MEMORY_FLUSH_APPEND_ONLY_HINT,
    MEMORY_FLUSH_INVALID_TARGET_ERROR,
    MEMORY_FLUSH_NO_REPLY_HINT_TEMPLATE,
    MEMORY_FLUSH_READ_ONLY_HINT,
    MEMORY_FLUSH_REQUIRED_HINTS,
    MEMORY_FLUSH_TARGET_HINT,
    MEMORY_FLUSH_TARGET_OUTSIDE_ERROR,
    SESSION_TOTAL_TOKENS_VERSION,
    SILENT_REPLY_TOKEN,
    UNIT_MULTIPLIERS,
)
from memory_core.bootstrap._js import format_js_error_message, js_trim, truncate_utf16_safe, utf16_len
from memory_core.current_time import (
    DEFAULT_TIME_FORMAT,
    format_current_time_line,
    resolve_date_timestamp_ms,
    resolve_user_timezone,
    utc_and_local_instants,
)
from memory_core.memory_paths import UnsafeMemoryPathError, validate_daily_memory_path
from memory_core.workspace import check_writable_memory_file, workspace_file_lock

__all__ = [
    "DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR",
    "DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES",
    "DEFAULT_MEMORY_FLUSH_PROMPT",
    "DEFAULT_MEMORY_FLUSH_SOFT_TOKENS",
    "DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT",
    "MAX_COMPACTION_RESERVE_RATIO",
    "MAX_FLUSH_ERROR_LENGTH",
    "MAX_FLUSH_FAILURES",
    "MEMORY_FLUSH_APPEND_ONLY_HINT",
    "MEMORY_FLUSH_READ_ONLY_HINT",
    "MEMORY_FLUSH_REQUIRED_HINTS",
    "MEMORY_FLUSH_TARGET_HINT",
    "SESSION_TOTAL_TOKENS_VERSION",
    "SILENT_REPLY_TOKEN",
    "MemoryFlushFailureOutcome",
    "MemoryFlushPlan",
    "MemoryFlushTriggerDecision",
    "UnsafeMemoryFlushTargetError",
    "append_current_time_line",
    "build_memory_flush_plan",
    "build_memory_flush_plan_from_config",
    "ensure_memory_flush_safety_hints",
    "ensure_memory_flush_target_file",
    "ensure_no_reply_hint",
    "explain_memory_flush_trigger",
    "followup_uses_cli_runtime",
    "format_current_time_line",
    "has_already_flushed_for_current_compaction",
    "record_memory_flush_failure",
    "record_memory_flush_success",
    "resolve_compaction_threshold",
    "resolve_effective_compaction_reserve_tokens",
    "resolve_fresh_session_total_tokens",
    "resolve_memory_flush_threshold",
    "should_force_memory_flush_by_transcript_size",
    "should_run_memory_flush",
    "should_run_memory_flush_trigger",
    "truncate_memory_flush_error_message",
    "validate_daily_memory_target",
]

# Kept for existing imports: flush-target and write-surface violations share
# one exception type and one validator (memory_core.memory_paths).
UnsafeMemoryFlushTargetError = UnsafeMemoryPathError


@dataclass(frozen=True)
class MemoryFlushPlan:
    """``MemoryFlushPlan`` of ``buildMemoryFlushPlan`` (flush-plan.ts)."""

    soft_threshold_tokens: int
    force_flush_transcript_bytes: int
    reserve_tokens_floor: int
    prompt: str
    system_prompt: str
    relative_path: str
    model: str | None = None


@dataclass(frozen=True)
class MemoryFlushFailureOutcome:
    """The session entry after one failed flush (``recordMemoryFlushFailure``).

    ``error`` is the truncated message upstream logs; it is not stored in the entry.
    """

    entry: dict[str, Any]
    failure_count: int
    exhausted: bool
    error: str


@dataclass(frozen=True)
class MemoryFlushTriggerDecision:
    should_flush: bool
    reason: str
    token_gate: bool = False
    transcript_size_gate: bool = False
    already_flushed: bool = False
    total_tokens: int | float | None = None
    threshold: int | None = None


# --- prompts (flush-plan.ts) ---------------------------------------------------------------


def ensure_no_reply_hint(text: str) -> str:
    """``ensureNoReplyHint``: append the NO_REPLY hint unless the token is present."""
    if SILENT_REPLY_TOKEN in text:
        return text
    return MEMORY_FLUSH_NO_REPLY_HINT_TEMPLATE.format(
        text=text, silent_reply_token=SILENT_REPLY_TOKEN
    )


def ensure_memory_flush_safety_hints(text: str) -> str:
    """``ensureMemoryFlushSafetyHints``: append each missing required hint.

    Upstream still wraps the default prompts with it; since the prompt overrides are gone
    (edecdbd05ef #111527) it never adds anything there.
    """
    next_text = text.strip()
    for hint in MEMORY_FLUSH_REQUIRED_HINTS:
        if hint not in next_text:
            next_text = f"{next_text}\n\n{hint}" if next_text else hint
    return next_text


def append_current_time_line(text: str, time_line: str) -> str:
    """``appendCurrentTimeLine`` (flush-plan.ts)."""
    trimmed = text.rstrip()
    if not trimmed:
        return time_line
    if "Current time:" in trimmed:
        return trimmed
    return f"{trimmed}\n{time_line}"


def validate_daily_memory_target(relative_path: str) -> str:
    return validate_daily_memory_path(relative_path)


# --- plan ------------------------------------------------------------------------------------


def resolve_effective_compaction_reserve_tokens(
    *, context_token_budget: int | float, reserve_tokens: int | float
) -> int:
    """Port of ``resolveEffectiveCompactionReserveTokens`` (src/agents/agent-compaction-constants.ts).

    Caps the reserve at a quarter of the window so prompts keep three quarters of it.
    """
    budget = max(1, math.floor(context_token_budget))
    return min(
        max(0, math.floor(reserve_tokens)),
        math.floor(budget * MAX_COMPACTION_RESERVE_RATIO),
    )


def build_memory_flush_plan(
    *,
    workspace_dir: object,
    now_ms: int | None = None,
    timezone: str = "UTC",
    soft_threshold_tokens: Any = DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
    force_flush_transcript_bytes: Any = DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES,
    model: str | None = None,
    context_window_tokens: Any = None,
    time_format: str = DEFAULT_TIME_FORMAT,
) -> MemoryFlushPlan:
    """Port of ``buildMemoryFlushPlan`` (extensions/memory-core/src/flush-plan.ts, v2026.9.6).

    ``soft_threshold_tokens``, ``force_flush_transcript_bytes`` and ``model`` stand for the
    ``agents.defaults.compaction.memoryFlush`` config keys that remain upstream. With a
    positive ``context_window_tokens`` (the model's window, supplied by the host) the reserve
    floor becomes ``min(20000, floor(window * 0.25))`` and the soft threshold
    ``min(soft, floor((window - reserve) / 2))`` (6b6f1969c11 #130072); without one they stay
    20000 and the configured soft threshold. ``time_format`` is the host's 12/24-hour format
    of the prompt's ``Current time:`` line (``memory_core.current_time``, which documents the
    host-format deviation).
    ``workspace_dir`` is unused, as upstream.

    ``now_ms`` follows ``resolveMemoryCoreNowMs`` (extensions/memory-core/src/time.ts): a
    missing, non-finite or out-of-``Date``-range (beyond ±8.64e15) value means the current
    time. Deviation: a ``Date``-valid instant outside the years 1-9999 raises ``ValueError``
    (Python dates stop there; upstream formats it), and before the year 1000 the unpadded
    upstream stamp (``memory/999-01-01.md``) fails the daily-path check.
    """
    del workspace_dir

    soft_threshold = _normalize_non_negative_int(soft_threshold_tokens)
    if soft_threshold is None:
        soft_threshold = DEFAULT_MEMORY_FLUSH_SOFT_TOKENS
    force_bytes = _parse_non_negative_byte_size(force_flush_transcript_bytes)
    if force_bytes is None:
        force_bytes = DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES
    reserve_tokens_floor = DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR
    window = _normalize_non_negative_int(context_window_tokens)
    if window is not None and window > 0:
        reserve_tokens_floor = resolve_effective_compaction_reserve_tokens(
            context_token_budget=window, reserve_tokens=reserve_tokens_floor
        )
        soft_threshold = min(soft_threshold, math.floor((window - reserve_tokens_floor) / 2))

    resolved_now_ms = resolve_date_timestamp_ms(now_ms)
    _, zone = resolve_user_timezone(timezone)
    date_stamp = _format_date_stamp_in_timezone(resolved_now_ms, zone)
    relative_path = validate_daily_memory_target(f"memory/{date_stamp}.md")
    time_line = format_current_time_line(resolved_now_ms, timezone, time_format)

    prompt_base = ensure_no_reply_hint(ensure_memory_flush_safety_hints(DEFAULT_MEMORY_FLUSH_PROMPT))
    system_prompt = ensure_no_reply_hint(
        ensure_memory_flush_safety_hints(DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT)
    )

    return MemoryFlushPlan(
        soft_threshold_tokens=soft_threshold,
        force_flush_transcript_bytes=force_bytes,
        reserve_tokens_floor=reserve_tokens_floor,
        prompt=append_current_time_line(prompt_base.replace("YYYY-MM-DD", date_stamp), time_line),
        system_prompt=system_prompt.replace("YYYY-MM-DD", date_stamp),
        relative_path=relative_path,
        model=_optional_text(model),
    )


def build_memory_flush_plan_from_config(
    *,
    workspace_dir: object,
    cfg: dict[str, Any] | None = None,
    now_ms: int | None = None,
    context_window_tokens: Any = None,
    time_format: str = DEFAULT_TIME_FORMAT,
) -> MemoryFlushPlan | None:
    """``buildMemoryFlushPlan({cfg, nowMs, contextWindowTokens})`` over an OpenClaw config dict.

    Reads ``agents.defaults.userTimezone`` and ``agents.defaults.compaction.memoryFlush``
    (``enabled``, ``softThresholdTokens``, ``forceFlushTranscriptBytes``, ``model``); the
    removed ``prompt``, ``systemPrompt`` and ``compaction.reserveTokensFloor`` keys are
    ignored like upstream ignores them, and so is ``agents.defaults.timeFormat`` (the host
    passes ``time_format``). ``enabled: false`` gives ``None``.
    """
    config = cfg or {}
    defaults = _record(_record(config.get("agents")).get("defaults"))
    memory_flush = _record(_record(defaults.get("compaction")).get("memoryFlush"))
    if memory_flush.get("enabled") is False:
        return None
    return build_memory_flush_plan(
        workspace_dir=workspace_dir,
        now_ms=now_ms,
        timezone=_optional_text(defaults.get("userTimezone")) or "UTC",
        soft_threshold_tokens=memory_flush.get("softThresholdTokens"),
        force_flush_transcript_bytes=memory_flush.get("forceFlushTranscriptBytes"),
        model=_optional_text(memory_flush.get("model")),
        context_window_tokens=context_window_tokens,
        time_format=time_format,
    )


# --- gate (memory-flush.ts) -----------------------------------------------------------------


def resolve_compaction_threshold(
    *,
    context_window_tokens: int | float,
    reserve_tokens_floor: int | float,
    minimum_threshold_tokens: int | float | None = None,
) -> int:
    """Port of ``resolveCompactionThreshold`` (src/auto-reply/reply/memory-flush.ts)."""
    context_window = max(1, math.floor(context_window_tokens))
    reserve_tokens = max(0, math.floor(reserve_tokens_floor))
    return max(0, context_window - reserve_tokens, math.floor(minimum_threshold_tokens or 0))


def resolve_memory_flush_threshold(
    *,
    context_window_tokens: int | float,
    reserve_tokens_floor: int | float,
    soft_threshold_tokens: int | float,
) -> int:
    """The early-flush threshold of ``runMemoryFlushIfNeeded``.

    agent-runner-memory.ts:1254-1260 (inline upstream, not exported): the compaction
    threshold of the plan's reserve minus the plan's soft margin, never below zero.
    """
    return max(
        0,
        resolve_compaction_threshold(
            context_window_tokens=context_window_tokens,
            reserve_tokens_floor=reserve_tokens_floor,
        )
        - max(0, math.floor(soft_threshold_tokens)),
    )


def resolve_fresh_session_total_tokens(entry: dict[str, Any] | None) -> int | float | None:
    """Port of ``resolveFreshSessionTotalTokens`` (src/config/sessions/types.ts:863-877).

    ``totalTokens`` counts only when ``totalTokensFresh`` is ``True`` and
    ``totalTokensVersion`` is ``SESSION_TOTAL_TOKENS_VERSION`` (the current prompt snapshot).
    """
    if not isinstance(entry, dict):
        return None
    total = entry.get("totalTokens")
    if not _is_number(total) or not _is_finite_number(total) or total < 0:
        return None
    version = entry.get("totalTokensVersion")
    if entry.get("totalTokensFresh") is not True or not (
        _is_number(version) and version == SESSION_TOTAL_TOKENS_VERSION
    ):
        return None
    return total


def should_run_memory_flush(
    *,
    entry: dict[str, Any] | None,
    threshold: int | float,
    token_count: int | float | None = None,
) -> bool:
    """Port of ``shouldRunMemoryFlush`` (memory-flush.ts, v2026.9.6).

    ``token_count`` is a fresh projected snapshot that wins over the entry's total.
    """
    # ``params.entry`` is truthy for any object in JS, so an empty dict still counts here.
    return bool(
        _should_run_preflight_compaction(entry=entry, token_count=token_count, threshold=threshold)
        and entry is not None
        and not has_already_flushed_for_current_compaction(entry)
    )


def _should_run_preflight_compaction(
    *, entry: dict[str, Any] | None, token_count: int | float | None, threshold: int | float
) -> bool:
    """``shouldRunPreflightCompaction`` (memory-flush.ts), the token half of the gate."""
    if entry is None:
        return False
    total_tokens = _resolve_gate_total_tokens(entry, token_count)
    return total_tokens is not None and total_tokens > 0 and threshold > 0 and total_tokens >= threshold


def has_already_flushed_for_current_compaction(entry: dict[str, Any]) -> bool:
    """Port of ``hasAlreadyFlushedForCurrentCompaction`` (memory-flush.ts, v2026.9.6).

    Reads ``entry.memoryFlush.compactionCount`` (8ee1d046d33 #115299); the pre-tag flat
    ``memoryFlushCompactionCount`` field is not read (upstream projects it into
    ``memoryFlush`` when it loads a stored entry, store-entry-shape.ts; memory-core leaves
    storage to the host).
    """
    compaction_count = entry.get("compactionCount")
    if compaction_count is None:
        compaction_count = 0
    memory_flush = entry.get("memoryFlush")
    last_flush_at = memory_flush.get("compactionCount") if isinstance(memory_flush, dict) else None
    # ``===``: both sides are numbers (a bool or string compactionCount never matches).
    return _is_number(last_flush_at) and _is_number(compaction_count) and last_flush_at == compaction_count


def should_force_memory_flush_by_transcript_size(
    *,
    transcript_byte_size: int | float | None,
    force_flush_transcript_bytes: int | float,
) -> bool:
    """``shouldForceFlushByTranscriptSize`` (agent-runner-memory.ts, inline)."""
    return (
        _is_number(transcript_byte_size)
        and _is_finite_number(transcript_byte_size)
        and _is_number(force_flush_transcript_bytes)
        and _is_finite_number(force_flush_transcript_bytes)
        and force_flush_transcript_bytes > 0
        and transcript_byte_size >= force_flush_transcript_bytes
    )


# --- runtime trigger (runMemoryFlushIfNeeded) ---------------------------------------------


def explain_memory_flush_trigger(
    *,
    entry: dict[str, Any] | None,
    plan: MemoryFlushPlan | None,
    context_window_tokens: int | float,
    token_count: int | float | None = None,
    transcript_byte_size: int | float | None = None,
    memory_flush_writable: bool = True,
    is_heartbeat: bool = False,
    is_cli: bool = False,
) -> MemoryFlushTriggerDecision:
    """The flush decision of ``runMemoryFlushIfNeeded`` (agent-runner-memory.ts:1188-1398).

    ``plan`` is the host's ``build_memory_flush_plan(..., context_window_tokens=...)`` for the
    same window, or ``None`` when the flush is disabled. The threshold is
    :func:`resolve_memory_flush_threshold` of the plan; the flush runs when
    :func:`should_run_memory_flush` holds or the transcript reached the plan's
    ``force_flush_transcript_bytes``, and never twice in one compaction cycle.
    """
    if not memory_flush_writable:
        return MemoryFlushTriggerDecision(False, "runtime_skip:not_writable")
    if is_heartbeat:
        return MemoryFlushTriggerDecision(False, "runtime_skip:heartbeat")
    if is_cli:
        return MemoryFlushTriggerDecision(False, "runtime_skip:cli")
    if plan is None:
        return MemoryFlushTriggerDecision(False, "disabled")
    if entry is None:
        return MemoryFlushTriggerDecision(False, "missing_entry")

    threshold = resolve_memory_flush_threshold(
        context_window_tokens=context_window_tokens,
        reserve_tokens_floor=plan.reserve_tokens_floor,
        soft_threshold_tokens=plan.soft_threshold_tokens,
    )
    total_tokens = _resolve_gate_total_tokens(entry, token_count)
    token_gate = _should_run_preflight_compaction(
        entry=entry, token_count=token_count, threshold=threshold
    )
    transcript_size_gate = should_force_memory_flush_by_transcript_size(
        transcript_byte_size=transcript_byte_size,
        force_flush_transcript_bytes=plan.force_flush_transcript_bytes,
    )
    already_flushed = has_already_flushed_for_current_compaction(entry)

    if already_flushed and (token_gate or transcript_size_gate):
        return MemoryFlushTriggerDecision(
            False,
            "already_flushed",
            token_gate=token_gate,
            transcript_size_gate=transcript_size_gate,
            already_flushed=True,
            total_tokens=total_tokens,
            threshold=threshold,
        )
    if token_gate:
        return MemoryFlushTriggerDecision(
            True,
            "token_threshold",
            token_gate=True,
            transcript_size_gate=transcript_size_gate,
            total_tokens=total_tokens,
            threshold=threshold,
        )
    if transcript_size_gate:
        return MemoryFlushTriggerDecision(
            True,
            "transcript_size",
            transcript_size_gate=True,
            total_tokens=total_tokens,
            threshold=threshold,
        )
    reason = "under_threshold" if total_tokens is not None else "missing_tokens"
    return MemoryFlushTriggerDecision(False, reason, total_tokens=total_tokens, threshold=threshold)


def should_run_memory_flush_trigger(
    *,
    entry: dict[str, Any] | None,
    plan: MemoryFlushPlan | None,
    context_window_tokens: int | float,
    token_count: int | float | None = None,
    transcript_byte_size: int | float | None = None,
    memory_flush_writable: bool = True,
    is_heartbeat: bool = False,
    is_cli: bool = False,
) -> bool:
    return explain_memory_flush_trigger(
        entry=entry,
        plan=plan,
        context_window_tokens=context_window_tokens,
        token_count=token_count,
        transcript_byte_size=transcript_byte_size,
        memory_flush_writable=memory_flush_writable,
        is_heartbeat=is_heartbeat,
        is_cli=is_cli,
    ).should_flush


# --- session-entry state (agent-runner-memory.ts) -----------------------------------------


def truncate_memory_flush_error_message(
    error: object, *, redact: Callable[[str], str] | None = None
) -> str:
    """``truncateMemoryFlushErrorMessage`` (agent-runner-memory.ts:295-300).

    The message is ``formatErrorMessage(err)``: an exception's message plus its ``__cause__``
    chain (`` | cause``, :func:`memory_core.bootstrap._js.format_js_error_message`), trimmed, else
    the plain string form; at most MAX_FLUSH_ERROR_LENGTH UTF-16 units. Upstream redacts it
    with ``redactSensitiveText``, which memory-core does not port: ``redact`` is the host's
    redactor, applied like upstream's (not to the blank-message fallback).
    """
    if isinstance(error, BaseException):
        formatted = format_js_error_message(error, redact=redact)
    else:
        formatted = error if isinstance(error, str) else str(error)
        formatted = redact(formatted) if redact is not None else formatted
    message = js_trim(formatted) or str(error)
    if utf16_len(message) > MAX_FLUSH_ERROR_LENGTH:
        return f"{truncate_utf16_safe(message, MAX_FLUSH_ERROR_LENGTH - 1)}…"
    return message


def record_memory_flush_success(
    entry: dict[str, Any],
    *,
    flushed_compaction_count: int | None = None,
) -> dict[str, Any]:
    """The entry after a successful flush (agent-runner-memory.ts:1517, 1665-1671).

    ``memoryFlush`` becomes ``{"kind": "succeeded", "compactionCount": n}`` for the cycle
    the flush ran in (``compactionCount`` before the flush unless given).
    """
    resolved_count = flushed_compaction_count
    if resolved_count is None:
        resolved_count = entry.get("compactionCount")
        if resolved_count is None:
            resolved_count = 0
    return {**entry, "memoryFlush": {"kind": "succeeded", "compactionCount": resolved_count}}


def record_memory_flush_failure(
    entry: dict[str, Any], *, error: object, redact: Callable[[str], str] | None = None
) -> MemoryFlushFailureOutcome:
    """The entry after one failed flush (``recordMemoryFlushFailure``, agent-runner-memory.ts:1699-1770).

    ``memoryFlush`` becomes ``{"kind": "failed", "compactionCount"?, "failureCount"}``
    (the last flushed cycle is kept, the count grows over consecutive failures). After
    MAX_FLUSH_FAILURES failures the cycle is marked ``succeeded`` for the current
    ``compactionCount``, so the same-cycle guard stops retries until the next compaction.
    ``redact`` is passed to :func:`truncate_memory_flush_error_message`.
    """
    truncated_error = truncate_memory_flush_error_message(error, redact=redact)
    current = entry.get("memoryFlush")
    current = current if isinstance(current, dict) else {}
    failed: dict[str, Any] = {"kind": "failed"}
    if "compactionCount" in current:
        failed["compactionCount"] = current["compactionCount"]
    previous = current.get("failureCount") if current.get("kind") == "failed" else 0
    failure_count = (previous if _is_number(previous) else 0) + 1
    failed["failureCount"] = failure_count
    next_entry = {**entry, "memoryFlush": failed}
    exhausted = failure_count >= MAX_FLUSH_FAILURES
    if exhausted:
        compaction_count = next_entry.get("compactionCount")
        next_entry["memoryFlush"] = {
            "kind": "succeeded",
            "compactionCount": 0 if compaction_count is None else compaction_count,
        }
    return MemoryFlushFailureOutcome(
        entry=next_entry,
        failure_count=failure_count,
        exhausted=exhausted,
        error=truncated_error,
    )


def ensure_memory_flush_target_file(
    root: str | os.PathLike[str],
    relative_path: str,
    *,
    assert_current: Callable[[], None] | None = None,
) -> Path:
    """Create the flush target empty before the flush run; returns its path.

    Port of ``ensureMemoryFlushTargetFile`` (src/auto-reply/reply/memory-flush-session.ts:64-96,
    called by agent-runner-memory.ts:1447-1451): a blank or absolute ``relative_path`` raises
    ``UnsafeMemoryPathError("Invalid memory flush target path")``, one that leaves ``root``
    ``... "Memory flush target path must stay inside the workspace"``; then the parent
    directories are created and the file is opened for append. So a flush that answers
    ``NO_REPLY`` still leaves the empty daily file, and ``memory/`` counts as setup evidence.
    ``assert_current`` is a prompt, synchronous host check that must raise to revoke authority;
    its return value is ignored. It runs before mkdir, after mkdir and after opening the file.
    The latter two checks run under the write lock, and the opened file is closed even when
    the final check raises. Check and filesystem exceptions propagate to the caller.
    Deviation (stricter than upstream): under the file's write lock, a symlinked or non-directory
    parent and a target that is a symlink, not a regular file or hard-linked are refused
    (``memory_core.workspace.check_writable_memory_file``), as the flush write refuses them.
    """
    relative = js_trim(relative_path) if isinstance(relative_path, str) else ""
    if not relative or os.path.isabs(relative):
        raise UnsafeMemoryPathError(MEMORY_FLUSH_INVALID_TARGET_ERROR)
    workspace_root = Path(root).resolve()
    target = Path(os.path.normpath(workspace_root / relative))
    inside = os.path.relpath(target, workspace_root).replace(os.sep, "/")
    if inside == "." or inside.startswith("..") or os.path.isabs(inside):
        raise UnsafeMemoryPathError(MEMORY_FLUSH_TARGET_OUTSIDE_ERROR)
    if assert_current is not None:
        assert_current()
    with workspace_file_lock(workspace_root, inside):
        check_writable_memory_file(workspace_root, inside)
        target.parent.mkdir(parents=True, exist_ok=True)
        if assert_current is not None:
            assert_current()
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags, 0o666)
        try:
            if assert_current is not None:
                assert_current()
        finally:
            os.close(descriptor)
    return target


def followup_uses_cli_runtime(
    *,
    provider: str | None,
    session_entry: dict[str, Any] | None = None,
    cli_providers: tuple[str, ...] | list[str] | set[str] = (),
    cli_runtime_bindings: tuple[tuple[str, str], ...] | list[tuple[str, str]] = (),
) -> bool:
    """Model OpenClaw's followupUsesCliRuntime CLI skip flag.

    A followup uses a CLI runtime when its provider is itself a CLI backend, or
    when the session entry pins a CLI runtime alias registered for that
    provider via agentRuntimeOverride.
    """
    provider_id = _normalize_provider_id(provider)
    if provider_id and any(_normalize_provider_id(item) == provider_id for item in cli_providers):
        return True
    runtime = _normalize_provider_id((session_entry or {}).get("agentRuntimeOverride"))
    if not provider_id or not runtime:
        return False
    return any(
        _normalize_provider_id(bound_provider) == provider_id
        and _normalize_provider_id(bound_runtime) == runtime
        for bound_provider, bound_runtime in cli_runtime_bindings
    )


def _normalize_provider_id(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _resolve_gate_total_tokens(entry: dict[str, Any], token_count: Any) -> int | float | None:
    positive = _resolve_positive_token_count(token_count)
    return positive if positive is not None else resolve_fresh_session_total_tokens(entry)


def _resolve_positive_token_count(value: Any) -> int | None:
    """``resolvePositiveTokenCount`` (memory-flush.ts)."""
    if not _is_number(value) or not _is_finite_number(value) or value <= 0:
        return None
    return math.floor(value)


def _normalize_non_negative_int(value: Any) -> int | None:
    """``normalizeNonNegativeInt`` (flush-plan.ts): a finite number, floored, not negative."""
    if not _is_number(value) or not _is_finite_number(value):
        return None
    number = math.floor(value)
    return number if number >= 0 else None


def _parse_non_negative_byte_size(value: Any) -> int | None:
    """Port of ``parseNonNegativeByteSize`` (src/config/byte-size.ts).

    A number is floored and must be a safe integer that is not negative; a string is a byte
    size for ``parseByteSize`` with bare numbers in bytes. Anything else, or a value upstream
    rejects, is ``None`` (the plan then keeps the default).
    """
    if _is_number(value):
        if not _is_finite_number(value):
            return None
        integer = math.floor(value)
        return integer if _is_safe_integer(integer) and integer >= 0 else None
    if isinstance(value, str):
        trimmed = js_trim(value)
        if not trimmed:
            return None
        try:
            parsed = _parse_byte_size(trimmed, default_unit="b")
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


# /^(\d+(?:\.\d+)?)([a-z]+)?$/ of parseByteSize: JS \d is ASCII only.
_BYTE_SIZE_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)([a-z]+)?")


def _parse_byte_size(raw: str, *, default_unit: str = "b") -> int:
    """Port of ``parseByteSize`` (src/cli/parse-bytes.ts); raises ``ValueError`` where it throws."""
    trimmed = js_trim(raw).lower()
    if not trimmed:
        raise ValueError(f"Invalid byte size (empty): {raw!r}")
    match = _BYTE_SIZE_RE.fullmatch(trimmed)
    if match is None:
        raise ValueError(f"Invalid byte size: {raw!r}")
    number = float(match.group(1))
    if not _is_finite_number(number) or number < 0:
        raise ValueError(f"Invalid byte size: {raw!r}")
    unit = js_trim(match.group(2) or default_unit).lower()
    multiplier = UNIT_MULTIPLIERS.get(unit)
    if not multiplier:
        raise ValueError(f'Invalid byte size (unknown unit "{unit}"): {raw!r}')
    size = _js_math_round(number * multiplier)
    # Validate the rounded byte count, as upstream does.
    if size is None or not _is_safe_integer(size):
        raise ValueError(f"Invalid byte size: {raw!r}")
    return size


_MAX_SAFE_INTEGER = 2**53 - 1


def _is_safe_integer(value: int) -> bool:
    """``Number.isSafeInteger`` of an already integral value."""
    return -_MAX_SAFE_INTEGER <= value <= _MAX_SAFE_INTEGER


def _js_math_round(value: float) -> int | None:
    """``Math.round``: the nearest integer, halves toward +Infinity (not banker's rounding).

    ``None`` for a non-finite value (``Math.round`` keeps it, and no such value is safe).
    """
    if not _is_finite_number(value):
        return None
    floor = math.floor(value)
    return floor + 1 if value - floor >= 0.5 else floor


def _is_number(value: Any) -> bool:
    """``typeof value === "number"``: bool is not a number."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_finite_number(value: int | float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _format_date_stamp_in_timezone(now_ms: int | float, zone: tzinfo) -> str:
    """``formatDateStampInTimezone`` (flush-plan.ts): en-US ``numeric`` year, 2-digit month/day."""
    _, local = utc_and_local_instants(now_ms, zone)
    return f"{local.year}-{local.month:02d}-{local.day:02d}"
