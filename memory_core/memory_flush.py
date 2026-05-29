"""OpenClaw-style pre-compaction memory flush planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SILENT_REPLY_TOKEN = "NO_REPLY"
DEFAULT_MEMORY_FLUSH_SOFT_TOKENS = 4000
DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES = 2 * 1024 * 1024
DEFAULT_PI_COMPACTION_RESERVE_TOKENS_FLOOR = 20_000

MEMORY_FLUSH_TARGET_HINT = (
    "Store durable memories only in memory/YYYY-MM-DD.md (create memory/ if needed)."
)
MEMORY_FLUSH_APPEND_ONLY_HINT = (
    "If memory/YYYY-MM-DD.md already exists, APPEND new content only and do not overwrite "
    "existing entries."
)
MEMORY_FLUSH_READ_ONLY_HINT = (
    "Treat workspace bootstrap/reference files such as MEMORY.md, DREAMS.md, SOUL.md, TOOLS.md, "
    "and AGENTS.md as read-only during this flush; never overwrite, replace, or edit them."
)
MEMORY_FLUSH_REQUIRED_HINTS = (
    MEMORY_FLUSH_TARGET_HINT,
    MEMORY_FLUSH_APPEND_ONLY_HINT,
    MEMORY_FLUSH_READ_ONLY_HINT,
)

DEFAULT_MEMORY_FLUSH_PROMPT = " ".join(
    [
        "Pre-compaction memory flush.",
        MEMORY_FLUSH_TARGET_HINT,
        MEMORY_FLUSH_READ_ONLY_HINT,
        MEMORY_FLUSH_APPEND_ONLY_HINT,
        "Do NOT create timestamped variant files (e.g., YYYY-MM-DD-HHMM.md); always use the "
        "canonical YYYY-MM-DD.md filename.",
        f"If nothing to store, reply with {SILENT_REPLY_TOKEN}.",
    ],
)

DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT = " ".join(
    [
        "Pre-compaction memory flush turn.",
        "The session is near auto-compaction; capture durable memories to disk.",
        MEMORY_FLUSH_TARGET_HINT,
        MEMORY_FLUSH_READ_ONLY_HINT,
        MEMORY_FLUSH_APPEND_ONLY_HINT,
        f"You may reply, but usually {SILENT_REPLY_TOKEN} is correct.",
    ],
)

_DAILY_MEMORY_TARGET_RE = re.compile(r"^memory/\d{4}-\d{2}-\d{2}\.md$")


class UnsafeMemoryFlushTargetError(ValueError):
    """Raised when a memory flush target is not the canonical daily memory file."""


@dataclass(frozen=True)
class MemoryFlushPlan:
    soft_threshold_tokens: int
    force_flush_transcript_bytes: int
    reserve_tokens_floor: int
    prompt: str
    system_prompt: str
    relative_path: str
    model: str | None = None


def ensure_no_reply_hint(text: str) -> str:
    if SILENT_REPLY_TOKEN in text:
        return text
    return f"{text}\n\nIf no user-visible reply is needed, start with {SILENT_REPLY_TOKEN}."


def ensure_memory_flush_safety_hints(text: str) -> str:
    next_text = text.strip()
    for hint in MEMORY_FLUSH_REQUIRED_HINTS:
        if hint not in next_text:
            next_text = f"{next_text}\n\n{hint}" if next_text else hint
    return next_text


def append_current_time_line(text: str, time_line: str) -> str:
    trimmed = text.rstrip()
    if not trimmed:
        return time_line
    if "Current time:" in trimmed:
        return trimmed
    return f"{trimmed}\n{time_line}"


def validate_daily_memory_target(relative_path: str) -> str:
    if not _DAILY_MEMORY_TARGET_RE.fullmatch(relative_path):
        raise UnsafeMemoryFlushTargetError(
            f"memory flush target must be memory/YYYY-MM-DD.md: {relative_path}",
        )
    return relative_path


def build_memory_flush_plan(
    *,
    workspace_dir: object,
    now_ms: int | None = None,
    timezone: str = "UTC",
    prompt: str | None = None,
    system_prompt: str | None = None,
    soft_threshold_tokens: int = DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
    force_flush_transcript_bytes: int = DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES,
    reserve_tokens_floor: int = DEFAULT_PI_COMPACTION_RESERVE_TOKENS_FLOOR,
    model: str | None = None,
) -> MemoryFlushPlan:
    del workspace_dir

    resolved_now_ms = now_ms if now_ms is not None else int(datetime.now(tz=UTC).timestamp() * 1000)
    user_timezone = _resolve_timezone(timezone)
    date_stamp = _format_date_stamp_in_timezone(resolved_now_ms, user_timezone)
    relative_path = validate_daily_memory_target(f"memory/{date_stamp}.md")
    time_line = _format_current_time_line(resolved_now_ms, user_timezone)

    prompt_base = ensure_no_reply_hint(
        ensure_memory_flush_safety_hints((prompt or DEFAULT_MEMORY_FLUSH_PROMPT).strip()),
    )
    system_prompt_base = ensure_no_reply_hint(
        ensure_memory_flush_safety_hints(
            (system_prompt or DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT).strip(),
        ),
    )

    return MemoryFlushPlan(
        soft_threshold_tokens=_normalize_non_negative_int(soft_threshold_tokens),
        force_flush_transcript_bytes=_normalize_non_negative_int(force_flush_transcript_bytes),
        reserve_tokens_floor=_normalize_non_negative_int(reserve_tokens_floor),
        prompt=append_current_time_line(prompt_base.replace("YYYY-MM-DD", date_stamp), time_line),
        system_prompt=system_prompt_base.replace("YYYY-MM-DD", date_stamp),
        relative_path=relative_path,
        model=_optional_text(model),
    )


def build_memory_flush_plan_from_config(
    *,
    workspace_dir: object,
    cfg: dict[str, Any] | None = None,
    now_ms: int | None = None,
) -> MemoryFlushPlan | None:
    config = cfg or {}
    defaults = _record(_record(config.get("agents")).get("defaults"))
    compaction = _record(defaults.get("compaction"))
    memory_flush = _record(compaction.get("memoryFlush"))
    if memory_flush.get("enabled") is False:
        return None
    return build_memory_flush_plan(
        workspace_dir=workspace_dir,
        now_ms=now_ms,
        timezone=_optional_text(defaults.get("userTimezone")) or "UTC",
        prompt=_optional_text(memory_flush.get("prompt")),
        system_prompt=_optional_text(memory_flush.get("systemPrompt")),
        soft_threshold_tokens=_normalize_non_negative_int_or_default(
            memory_flush.get("softThresholdTokens"), DEFAULT_MEMORY_FLUSH_SOFT_TOKENS
        ),
        force_flush_transcript_bytes=_parse_non_negative_byte_size_or_default(
            memory_flush.get("forceFlushTranscriptBytes"),
            DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES,
        ),
        reserve_tokens_floor=_normalize_non_negative_int_or_default(
            compaction.get("reserveTokensFloor"), DEFAULT_PI_COMPACTION_RESERVE_TOKENS_FLOOR
        ),
        model=_optional_text(memory_flush.get("model")),
    )


def _normalize_non_negative_int(value: int) -> int:
    return max(0, int(value))


def _normalize_non_negative_int_or_default(value: Any, default: int) -> int:
    if not isinstance(value, int | float) or not _is_finite_number(value):
        return default
    return _normalize_non_negative_int(int(value))


def _parse_non_negative_byte_size_or_default(value: Any, default: int) -> int:
    parsed = _parse_non_negative_byte_size(value)
    return default if parsed is None else parsed


def _parse_non_negative_byte_size(value: Any) -> int | None:
    if isinstance(value, int | float) and _is_finite_number(value):
        parsed = int(value)
        return parsed if parsed >= 0 else None
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)([a-zA-Z]+)?\s*", value)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "b").lower()
    multipliers = {
        "b": 1,
        "kb": 1024,
        "k": 1024,
        "mb": 1024**2,
        "m": 1024**2,
        "gb": 1024**3,
        "g": 1024**3,
        "tb": 1024**4,
        "t": 1024**4,
    }
    multiplier = multipliers.get(unit)
    if multiplier is None:
        return None
    return round(number * multiplier)


def _is_finite_number(value: int | float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_timezone(timezone: str) -> str:
    trimmed = timezone.strip()
    if not trimmed:
        return "UTC"
    try:
        ZoneInfo(trimmed)
    except ZoneInfoNotFoundError:
        return "UTC"
    return trimmed


def _format_date_stamp_in_timezone(now_ms: int, timezone: str) -> str:
    instant = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    local = instant.astimezone(ZoneInfo(timezone))
    return local.strftime("%Y-%m-%d")


def _format_current_time_line(now_ms: int, timezone: str) -> str:
    instant = datetime.fromtimestamp(now_ms / 1000, tz=UTC)
    local = instant.astimezone(ZoneInfo(timezone))
    formatted_time = _format_user_time_24h(local)
    utc_time = instant.strftime("%Y-%m-%d %H:%M UTC")
    return f"Current time: {formatted_time} ({timezone})\nReference UTC: {utc_time}"


def _format_user_time_24h(local: datetime) -> str:
    day = local.day
    return (
        f"{local.strftime('%A')}, {local.strftime('%B')} {day}{_ordinal_suffix(day)}, "
        f"{local.year} - {local.strftime('%H:%M')}"
    )


def _ordinal_suffix(day: int) -> str:
    if 11 <= day <= 13:
        return "th"
    match day % 10:
        case 1:
            return "st"
        case 2:
            return "nd"
        case 3:
            return "rd"
        case _:
            return "th"
