"""Calendar schedules for explicit host-driven memory jobs."""
from __future__ import annotations

from bisect import bisect_left
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from functools import lru_cache
import hashlib
import math
import os
import re
from typing import TYPE_CHECKING, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from memory_core.bootstrap._js import js_trim, js_utf8_encode
from memory_core.current_time import _offset_time_zone

if TYPE_CHECKING:
    from memory_core.automation import AutomationJob

_MAX_TIMESTAMP = 8_640_000_000_000_000
_MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
_WEEKDAYS = "SUN MON TUE WED THU FRI SAT".split()
_ALIASES = {"@YEARLY": "0 0 1 1 *", "@ANNUALLY": "0 0 1 1 *", "@MONTHLY": "0 0 1 * *",
            "@WEEKLY": "0 0 * * 0", "@DAILY": "0 0 * * *", "@MIDNIGHT": "0 0 * * *",
            "@HOURLY": "0 * * * *"}
_ISO = re.compile(r"^(?!-000000)([+-][0-9]{6}|[0-9]{4})-([0-9]{2})-([0-9]{2})(?:T([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.([0-9]+))?)?(Z|[+-][0-9]{2}:?[0-9]{2})?)?$", re.I)


def absolute_time_ms(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    raw = js_trim(value)
    if re.fullmatch("[0-9]+", raw):
        digits = raw.lstrip("0")
        if not digits or len(digits) > 16:
            return None
        number = int(digits)
        return number if number <= _MAX_TIMESTAMP else None
    match = _ISO.fullmatch(raw)
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(x or 0) for x in match.groups()[:6])
    fraction, offset = match.groups()[6:]
    cycle, year_in_cycle = divmod(year, 400)
    try:
        local_date = date(2000 + year_in_cycle, month, day)
    except ValueError:
        return None
    if (hour > 24 or minute >= 60 or second >= 60
            or hour == 24 and (minute or second or (fraction or "").strip("0"))):
        return None
    days = (local_date - date(1970, 1, 1)).days + (cycle - 5) * 146097
    minutes = (days * 24 + hour) * 60 + minute
    if offset and offset.upper() != "Z":
        digits = offset[1:].replace(":", "")
        hours, mins = int(digits[:2]), int(digits[2:])
        if hours > 23 or mins >= 60:
            return None
        minutes -= (1 if offset.startswith("+") else -1) * (hours * 60 + mins)
    stamp = (minutes * 60 + second) * 1000 + int((fraction or "0")[:3].ljust(3, "0"))
    return stamp if abs(stamp) <= _MAX_TIMESTAMP else None


def canonical_absolute_time(value: object) -> str | None:
    """Normalize a one-shot to the persisted JS ISO form, including signed six-digit years."""
    stamp = absolute_time_ms(value)
    if stamp is None:
        return None
    days, within_day = divmod(stamp, 86_400_000)
    anchor = date(2000, 1, 1)
    cycles, day_of_cycle = divmod(days - (anchor - date(1970, 1, 1)).days, 146_097)
    equivalent = anchor + timedelta(days=day_of_cycle)
    year = equivalent.year + 400 * cycles
    year_text = f"{year:04d}" if 0 <= year <= 9999 else f"{year:+07d}"
    hour, remainder = divmod(within_day, 3_600_000)
    minute, remainder = divmod(remainder, 60_000)
    second, ms = divmod(remainder, 1000)
    return f"{year_text}-{equivalent.month:02d}-{equivalent.day:02d}T{hour:02d}:{minute:02d}:{second:02d}.{ms:03d}Z"


def valid_calendar_schedule(schedule: Mapping[str, object]) -> bool:
    kind = schedule.get("kind")
    if kind == "at":
        return absolute_time_ms(schedule.get("at")) is not None
    stagger = schedule.get("staggerMs", 0)
    return (kind == "cron" and isinstance(schedule.get("expr"), str) and bool(js_trim(schedule["expr"]))
            and type(stagger) in {int, float} and 0 <= stagger <= _MAX_TIMESTAMP and int(stagger) == stagger)


def _values(token: str, low: int, high: int, *, field_length: int | None = None) -> tuple[int, ...]:
    """Expand a Croner numeric field. A step needs a wildcard or a closed range."""
    size = field_length or high - low + 1
    result: set[int] = set()
    for part in token.split(","):
        match = re.fullmatch(r"([*?]|[0-9]+(?:-[0-9]+)?)(?:/([0-9]+))?", part)
        if match is None:
            raise ValueError(f"Invalid cron field {token!r}")
        expression, stride = match.groups()
        step = int(stride) if stride else 1
        if expression in {"*", "?"}:
            start, end = low, high
        else:
            lower, dash, upper = expression.partition("-")
            if stride and not dash:
                raise ValueError(f"Numeric-prefixed cron step {part!r} requires a range")
            start, end = int(lower), int(upper) if dash else int(lower)
        if not 1 <= step <= size or not low <= start <= end <= high:
            raise ValueError(f"Invalid cron field {token!r}")
        result.update(range(start, end + 1, step))
    return tuple(sorted(result))


@dataclass(frozen=True)
class _DaySelector:
    days: frozenset[int]
    nearest: frozenset[int]
    last_day: bool
    last_weekday: bool
    weekdays: frozenset[int]
    nth_weekdays: frozenset[tuple[int, str]]
    all_dom: bool
    all_dow: bool
    and_days: bool

    def matches(self, day: date, last: int) -> bool:
        dom = day.day in self.days or self.last_day and day.day == last
        if self.last_weekday:
            weekday = day.replace(day=last).weekday()
            dom |= day.day == last - max(0, weekday - 4)
        for number in self.nearest:
            if number <= last:
                weekday = day.replace(day=number).weekday()
                chosen = number
                if weekday == 5:
                    chosen += 2 if number == 1 else -1
                if weekday == 6:
                    chosen += -2 if number == last else 1
                dom |= day.day == chosen
        if self.all_dow:
            return dom
        weekday = (day.weekday() + 1) % 7
        dow = (weekday in self.weekdays or (weekday, str((day.day - 1) // 7 + 1)) in self.nth_weekdays
               or (day.day + 7 > last and (weekday, "L") in self.nth_weekdays))
        return dom and dow if self.and_days or self.all_dom else dom or dow


def _name_numbers(field: str, names: list[str], first: int) -> str:
    for number, name in enumerate(names, first):
        field = field.replace(name, str(number))
    return field


def _days(dom: str, dow: str) -> _DaySelector:
    original_dom = dom
    last_weekday = dom == "LW"
    last_day = "L" in dom and not last_weekday
    if last_weekday:
        dom = ""
    elif last_day:
        dom = dom.replace("L", "")
    days, nearest = set(), set()
    for term in dom.split(","):
        if not term and (last_day or last_weekday):
            continue
        if re.fullmatch(r"[0-9]+W", term):
            nearest.update(_values(term[:-1], 1, 31))
        else:
            days.update(_values(term, 1, 31))
    and_days = dow.startswith("+")
    dow = dow.removeprefix("+")
    # At the end of a range Sunday is 7, so FRI-SUN includes Saturday.
    dow = _name_numbers(dow.replace("-SUN", "-7"), _WEEKDAYS, 0)
    weekdays, nth = set(), set()
    for term in dow.split(","):
        selector, marker, occurrence = term.partition("#")
        if not marker and selector.endswith("L"):
            selector, marker, occurrence = selector[:-1], "#", "L"
        # Croner's wildcard array has seven entries. A literal 7 aliases Sunday.
        maximum = 6 if selector.startswith(("*", "?")) else 7
        values = {number % 7 for number in _values(selector, 0, maximum, field_length=7)}
        if marker:
            if occurrence not in {"1", "2", "3", "4", "5", "L"}:
                raise ValueError(f"Invalid weekday occurrence {term!r}")
            nth.update((number, occurrence) for number in values)
        else:
            weekdays.update(values)
    # Croner records literal stars before expanding question marks for the DOM/DOW rule.
    return _DaySelector(frozenset(days), frozenset(nearest), last_day, last_weekday, frozenset(weekdays),
                        frozenset(nth), original_dom == "*", dow == "*", and_days)


@dataclass(frozen=True)
class _CalendarPattern:
    seconds: tuple[int, ...]
    minutes: tuple[int, ...]
    hours: tuple[int, ...]
    months: tuple[int, ...]
    years: range | tuple[int, ...]
    days: _DaySelector


@lru_cache(maxsize=128)
def _parse_cron(expr: str) -> _CalendarPattern:
    text = js_trim(expr).upper()
    fields = _ALIASES.get(text, text).split()
    if len(fields) == 5:
        fields.insert(0, "0")
    if len(fields) == 6:
        fields.append("*")
    if len(fields) != 7:
        raise ValueError("Cron requires five, six or seven fields")
    sec, minute, hour, dom, month, dow, year = fields
    if any(part.startswith(("*/", "?/")) for part in year.split(",")):
        raise ValueError("Cron wildcard year steps start at the invalid year zero")
    years: range | tuple[int, ...]
    if year == "*":
        years = range(1, 3000)  # Croner's wildcard-year search horizon.
    elif year == "?":
        years = range(1, 10_000)
    else:
        years = _values(year, 1, 9999, field_length=10_000)
    months = _values(_name_numbers(month, _MONTHS, 1), 1, 12)
    return _CalendarPattern(_values(sec, 0, 59), _values(minute, 0, 59), _values(hour, 0, 23),
                            months, years, _days(dom, dow))


@lru_cache(maxsize=1)
def _zone_names() -> dict[str, str]:
    return {name.lower(): name for name in available_timezones()}


def _local_zone(name: object) -> tzinfo:
    label = js_trim(name) if isinstance(name, str) else ""
    if not label:
        label = os.environ.get("TZ", "").lstrip(":")
    if label:
        fixed = _offset_time_zone(label)
        if fixed is not None:
            return fixed
        try:
            return ZoneInfo(label)
        except ZoneInfoNotFoundError:
            canonical = _zone_names().get(label.lower())
            if canonical is None:
                raise ValueError(f"Unknown cron timezone {label!r}") from None
            return ZoneInfo(canonical)
    try:
        with open("/etc/localtime", "rb") as stream:
            return ZoneInfo.from_file(stream)
    except OSError:
        return datetime.now().astimezone().tzinfo or timezone.utc


def _next_cron(expr: str, tz: object, now_ms: float) -> int | None:
    zone = _local_zone(tz)
    if ":" in expr:
        # Croner also accepts a one-time ISO datetime as its expression.
        if not _ISO.fullmatch(expr):
            raise ValueError(f"Invalid cron datetime {expr!r}")
        instant = datetime.fromisoformat(expr.replace("z", "Z"))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=zone)
        stamp = int(instant.timestamp()) * 1000  # CronDate has whole-second precision here.
        return stamp if stamp > now_ms else None
    pattern = _parse_cron(expr)
    try:
        current = datetime.fromtimestamp(now_ms / 1000, zone)
    except (OverflowError, ValueError, OSError):
        if now_ms >= 0:
            return None
        current = datetime.min.replace(tzinfo=zone)
    for year in pattern.years[bisect_left(pattern.years, current.year):]:
        for month in pattern.months:
            if (year, month) < (current.year, current.month):
                continue
            last = monthrange(year, month)[1]
            first = current.day if (year, month) == (current.year, current.month) else 1
            for number in range(first, last + 1):
                local_date = date(year, month, number)
                if not pattern.days.matches(local_date, last):
                    continue
                today = local_date == current.date()
                for hour in pattern.hours:
                    if today and hour < current.hour:
                        continue
                    for minute in pattern.minutes:
                        if today and hour == current.hour and minute < current.minute:
                            continue
                        for second in pattern.seconds:
                            local = datetime.combine(local_date, time(hour, minute, second), zone)
                            stamp = int(local.timestamp()) * 1000
                            if stamp <= now_ms:
                                continue
                            # Repeated wall times use the first occurrence. Gaps fail this round trip.
                            if datetime.fromtimestamp(stamp / 1000, zone).replace(tzinfo=None) == local.replace(tzinfo=None):
                                return stamp
    return None


def _stagger(schedule: dict, expr: str) -> int:
    raw = schedule.get("staggerMs")
    if isinstance(raw, str):
        text = js_trim(raw)
        if re.fullmatch(r"[+]?[0-9]+", text):
            digits = text.lstrip("+0")
            raw = int(digits or "0") if len(digits) <= 16 else None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if raw <= 0 and raw != -math.inf:
            return 0
        if 0 < raw <= _MAX_TIMESTAMP:
            return math.floor(raw)
    fields = expr.split()
    if len(fields) == 6 and fields[0] == "0":
        fields = fields[1:]
    if len(fields) == 5 and fields[0] == "0":
        hours = fields[1].split(",")
        if (all(re.fullmatch(r"(?:[0-9]+(?:-[0-9]+)?|[*?])(?:/[0-9]+)?", part) for part in hours)
                and any(part.startswith(("*", "?")) for part in hours)):
            return 300_000
    return 0


def next_calendar_run(job: AutomationJob, now_ms: float) -> int | None:
    schedule = job.calendar_schedule or {}
    if schedule.get("kind") == "at":
        stamp = absolute_time_ms(schedule.get("at"))
        if stamp is None or stamp == job.runtime_state.get("forcePreservedNextRunAtMs"):
            return stamp
        last_status = job.runtime_state.get("lastRunStatus") or job.runtime_state.get("lastStatus")
        if last_status == "ok" and job.last_run_at_ms and stamp <= job.last_run_at_ms:
            return None
        return stamp
    expr = schedule.get("expr")
    if not isinstance(expr, str) or not expr.strip() or not math.isfinite(now_ms):
        return None
    stagger = _stagger(schedule, expr)
    offset = int.from_bytes(hashlib.sha256(js_utf8_encode(job.id)).digest()[:4], "big") % stagger if stagger and stagger > 1 else 0
    cursor = max(0, now_ms - offset) if offset else now_ms
    for _ in range(4):
        next_at = _next_cron(js_trim(expr), schedule.get("tz"), cursor)
        if next_at is None:
            return None
        shifted = next_at + offset
        if now_ms < shifted <= _MAX_TIMESTAMP:
            return shifted
        cursor = max(cursor + 1, next_at + 1000)
    return None
