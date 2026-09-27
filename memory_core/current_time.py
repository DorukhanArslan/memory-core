"""The ``Current time:`` prompt line, with one host time format for every caller.

Ported from OpenClaw v2026.9.6 (``eb377ac59e6``): ``src/agents/current-time.ts``
(``resolveCronStyleNow``, ``appendCronStyleCurrentTimeLine``) and the parts of
``src/agents/date-time.ts`` they use (``resolveUserTimezone``, ``resolveUserTimeFormat``,
``formatUserTime``), plus ``resolveDateTimestampMs``
(``packages/normalization-core/src/number-coercion.ts``). Upstream builds every such line
through ``resolveCronStyleNow``, among them the memory flush prompt
(``extensions/memory-core/src/flush-plan.ts``), the heartbeat Body
(``src/infra/heartbeat-runner-run.ts:78``) and the bare ``/new`` / ``/reset`` prompt
(``src/auto-reply/reply/session-reset-prompt.ts``). memory-core builds them all through
:func:`format_current_time_line`: ``memory_core.memory_flush.build_memory_flush_plan``,
``memory_core.heartbeat.prepare_heartbeat_turn`` and
``memory_core.bootstrap.startup.build_bare_session_reset_prompt`` call it.

Host time format (documented deviation; this is the one place that describes it). Since
edecdbd05ef (#111527) ``resolveCronStyleNow`` ignores the ``agents.defaults.timeFormat``
config and calls ``resolveUserTimeFormat(undefined)``, which detects the host OS's 12/24-hour
setting once per process (date-time.ts:42-51 and ``detectSystemTimeFormat``, :184-228: macOS
``defaults read -g AppleICUForce24HourTime``, Windows ``ShortTimePattern``, else ``Intl``
``hour12``). memory-core does not probe the OS. The host passes its format as ``time_format``
(:data:`TimeFormat`, ``"12"`` or ``"24"``, default :data:`DEFAULT_TIME_FORMAT` ``"24"``) and
every current-time line takes that one value: ``build_memory_flush_plan``,
``build_memory_flush_plan_from_config``, ``prepare_heartbeat_turn``,
``build_bare_session_reset_prompt`` and ``resolve_bare_session_reset_prompt_state`` accept
``time_format`` and pass it here unchanged. ``"auto"`` is refused (``ValueError``), because
memory-core cannot know the host's setting. The oracle ops ``flushPlan`` and
``heartbeatRunPrompt`` report the tag's detected format (``hostTimeFormat``) and the Python
side passes it on, so both compare the full line.

Other deviations: a blank or ``Intl``-invalid zone falls back to UTC, where upstream takes
the host zone; zones resolve through ``zoneinfo`` (IANA names) or as ECMA-402 offsets
(``+03:00``), not through ICU; a ``Date``-valid instant outside the years 1-9999 raises
``ValueError`` (Python dates stop there).
"""

from __future__ import annotations

import math
import re
import time
from datetime import UTC, datetime, timedelta, tzinfo
from datetime import timezone as fixed_offset_zone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memory_core.bootstrap._js import js_trim, js_trim_end

__all__ = [
    "DEFAULT_TIME_FORMAT",
    "TimeFormat",
    "append_cron_style_current_time_line",
    "format_current_time_line",
    "format_user_time",
    "resolve_date_timestamp_ms",
    "resolve_time_format",
    "resolve_user_timezone",
    "utc_and_local_instants",
]

TimeFormat = Literal["12", "24"]
"""The host's 12/24-hour format (``ResolvedTimeFormat`` of date-time.ts)."""

DEFAULT_TIME_FORMAT: TimeFormat = "24"


def resolve_time_format(time_format: str) -> TimeFormat:
    """``resolveUserTimeFormat`` with an explicit preference: ``"12"`` or ``"24"``.

    Upstream detects the host for anything else; memory-core refuses it (module docstring).
    """
    if time_format == "12":
        return "12"
    if time_format == "24":
        return "24"
    raise ValueError(f"time_format must be '12' or '24', got {time_format!r}")


# --- time zone (date-time.ts resolveUserTimezone) -------------------------------------------

# ECMA-402 offset time zone identifiers (``UTCOffset`` without seconds, as Node's Intl accepts
# them): ``+03``, ``+0300`` or ``+03:00``, hours 00-23, minutes 00-59; the sign may be U+2212.
_OFFSET_TIME_ZONE_RE = re.compile("([+\\-−])([01][0-9]|2[0-3])(?::?([0-5][0-9]))?")


def _offset_time_zone(name: str) -> tzinfo | None:
    match = _OFFSET_TIME_ZONE_RE.fullmatch(name)
    if match is None:
        return None
    sign = 1 if match.group(1) == "+" else -1
    minutes = int(match.group(2)) * 60 + int(match.group(3) or 0)
    return fixed_offset_zone(sign * timedelta(minutes=minutes))


def resolve_user_timezone(timezone: str) -> tuple[str, tzinfo]:
    """``resolveUserTimezone`` (src/agents/date-time.ts:27-39): (label, zone).

    The trimmed configured zone when ``Intl`` accepts it, an IANA name or an ECMA-402 offset
    such as ``+03:00`` (the label keeps the configured spelling, as upstream prints it).
    Deviation: a blank or unknown zone falls back to UTC, where upstream takes the host zone.
    """
    trimmed = js_trim(timezone) if isinstance(timezone, str) else ""
    if trimmed:
        offset = _offset_time_zone(trimmed)
        if offset is not None:
            return trimmed, offset
        try:
            return trimmed, ZoneInfo(trimmed)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return "UTC", ZoneInfo("UTC")


# --- timestamps (number-coercion.ts resolveDateTimestampMs) ---------------------------------

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# MAX_DATE_TIMESTAMP_MS (packages/normalization-core/src/number-coercion.ts): TimeClip's limit.
_MAX_DATE_TIMESTAMP_MS = 8_640_000_000_000_000


def _date_now_ms() -> int:
    """``Date.now()``."""
    return time.time_ns() // 1_000_000


def _is_finite_number(value: Any) -> bool:
    """``typeof value === "number" && Number.isFinite(value)``: bool is not a number."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and value == value
        and value not in (float("inf"), float("-inf"))
    )


def resolve_date_timestamp_ms(now_ms: Any) -> int | float:
    """``resolveDateTimestampMs`` (number-coercion.ts), which ``resolveMemoryCoreNowMs``
    (extensions/memory-core/src/time.ts) also applies: a ``Date``-valid timestamp, else now."""
    if _is_finite_number(now_ms) and abs(now_ms) <= _MAX_DATE_TIMESTAMP_MS:
        return now_ms
    return _date_now_ms()


def utc_and_local_instants(now_ms: int | float, zone: tzinfo) -> tuple[datetime, datetime]:
    """(UTC, local) of ``new Date(now_ms)``: TimeClip truncates toward zero.

    Raises ``ValueError`` outside the years 1-9999, where Python dates stop.
    """
    try:
        instant = _EPOCH + timedelta(milliseconds=math.trunc(now_ms))
        return instant, instant.astimezone(zone)
    except OverflowError as exc:
        raise ValueError(
            f"now_ms {now_ms!r} falls outside the years 1-9999 that Python dates support"
        ) from exc


# --- the line (date-time.ts formatUserTime, current-time.ts resolveCronStyleNow) ------------

_EN_US_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_EN_US_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
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


def format_user_time(local: datetime, time_format: str = DEFAULT_TIME_FORMAT) -> str:
    """``formatUserTime`` (date-time.ts:247-290): en-US parts, ``h23`` or ``h12`` cycle.

    The names are fixed en-US strings (``strftime`` would follow the process locale).
    """
    day = local.day
    if resolve_time_format(time_format) == "24":
        time_part = f"{local.hour:02d}:{local.minute:02d}"
    else:
        hour = local.hour % 12 or 12
        time_part = f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"
    return (
        f"{_EN_US_WEEKDAYS[local.weekday()]}, {_EN_US_MONTHS[local.month - 1]} "
        f"{day}{_ordinal_suffix(day)}, {local.year} - {time_part}"
    )


def format_current_time_line(
    now_ms: int | float, timezone: str = "UTC", time_format: str = DEFAULT_TIME_FORMAT
) -> str:
    """The two-line ``timeLine`` of ``resolveCronStyleNow`` (current-time.ts:23-32).

    ``Current time: <formatUserTime> (<zone>)`` and ``Reference UTC: YYYY-MM-DD HH:MM UTC``.
    The zone resolves like :func:`resolve_user_timezone`, a non-finite or out-of-``Date``-range
    ``now_ms`` means the current time, and ``time_format`` is the host's 12/24-hour format
    (the deviation in the module docstring).
    """
    resolved_format = resolve_time_format(time_format)
    label, zone = resolve_user_timezone(timezone)
    instant, local = utc_and_local_instants(resolve_date_timestamp_ms(now_ms), zone)
    # Date.prototype.toISOString sliced to minutes: a 4-digit zero-padded year.
    utc_time = (
        f"{instant.year:04d}-{instant.month:02d}-{instant.day:02d} "
        f"{instant.hour:02d}:{instant.minute:02d} UTC"
    )
    return f"Current time: {format_user_time(local, resolved_format)} ({label})\nReference UTC: {utc_time}"


# current-time.ts:52-53 CURRENT_TIME_LINE_RE (JS \d is ASCII; `.` excludes line breaks).
_CURRENT_TIME_LINE_RE = re.compile(
    r"^Current time: .+? \([^)]+\)\nReference UTC: [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2} UTC$",
    re.MULTILINE,
)
_THREE_NEWLINES_RE = re.compile(r"\n{3,}")
_BLANK_BEFORE_TIME_RE = re.compile(r"\n\n+(?=Current time:)")


def append_cron_style_current_time_line(
    text: str,
    *,
    now_ms: int | float,
    timezone: str = "UTC",
    time_format: str = DEFAULT_TIME_FORMAT,
) -> str:
    """Port of ``appendCronStyleCurrentTimeLine`` (current-time.ts:58-80).

    Appends a fresh :func:`format_current_time_line` block, or refreshes the first block the
    helper injected earlier and drops the others (#44993).
    """
    base = js_trim_end(text)
    if not base:
        return base
    time_line = format_current_time_line(now_ms, timezone, time_format)
    if not _CURRENT_TIME_LINE_RE.search(base):
        return f"{base}\n{time_line}"
    replaced = False

    def refresh(_match: re.Match[str]) -> str:
        nonlocal replaced
        if replaced:
            return ""
        replaced = True
        return time_line

    refreshed = _CURRENT_TIME_LINE_RE.sub(refresh, base)
    refreshed = _BLANK_BEFORE_TIME_RE.sub("\n", _THREE_NEWLINES_RE.sub("\n\n", refreshed))
    return js_trim_end(refreshed)
