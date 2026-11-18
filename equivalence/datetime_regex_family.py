"""Frozen public clock, stored promotion date and configured regex comparisons."""
from __future__ import annotations

import hashlib
import json

from equivalence.promotion_ranking_fixtures import NOW_ISO, NOW_MS, RELEVANCE_ONLY, _entry, _query


REQUIREMENT = "engine.datetime-regex"
POINTS = (REQUIREMENT + ".outcomes",)
CLOCK = "engine-datetime-clock"
CLOCK_OWNERS = ["src/agents/current-time.ts", "src/agents/date-time.ts"]
DEFINITION_SHA256 = "18d82997193f9edf310c96219ccfe31da80828db4300590946d0f194528b5cc5"


def _row(name, operation, arguments, scope):
    return {"id": "engine-datetime-" + name, "requirement": REQUIREMENT, "operation": operation,
            "covers": list(POINTS), "input": arguments, "driverScope": scope,
            "normalizationPolicy": "Compare complete public outputs, including all timestamp, ordering, "
            "compiler, text and diagnostic fields. Host time format and fallback zone are explicit inputs."}


def _clock(name, instants):
    return _row(name, CLOCK, {"kind": "current-time", "hostTimezone": "UTC", "hostTimeFormat": "12",
                "text": "Meeting note\nCurrent time: earlier (UTC)\nReference UTC: 2025-01-15 12:00 UTC",
                "instants": [{"iso": iso, "zone": zone} for iso, zone in instants]},
                "Original current-time prompt and refresh, original 12/24-hour formatting, "
                "and production SDK clock under the same explicit host preferences.")


def _regex(name, source, flags, text):
    return _row(name, "redaction-policy-source", {
        "kind": "source-policy", "mode": "tools", "fullContext": False,
        "patterns": [f"/{source}/{flags}"], "directRegex": {"source": source, "flags": flags},
        "text": text, "value": {"note": text}, "registeredSecrets": [], "declaredRegistryValues": [],
        "message": {"role": "toolResult", "toolCallId": "clock-fixture", "toolName": "calendar",
                    "content": [{"type": "text", "text": text}], "timestamp": 1000}},
        "Fresh ordinary source policy and SDK compiler, whole caller text, structured value, "
        "model and transcript results. Each call receives only synthetic calendar labels.")


def _rank():
    days = ["2024-02-28", "2024-02-29", "2024-03-01"]
    stamps = {
        "utc": "2026-04-02T10:01:00.000Z", "east": "2026-04-02T15:46:00.000+05:45",
        "west": "2026-04-02T06:01:00.000-04:00", "old": "2026-04-02T10:00:59.999Z",
        "rfc": "Thu, 02 Apr 2026 10:00:59 GMT", "invalid": "not a date",
    }
    entries = {key: _entry(key, path=f"memory/2026-04-02-{key}.md", lastRecalledAt=stamp,
                           recallDays=days) for key, stamp in stamps.items()}
    return _row("stored-date-admission", "promotion-ranking-runtime", {"kind": "promotion-ranking",
        "nowMs": NOW_MS, "store": {"version": 1, "updatedAt": NOW_ISO, "entries": entries},
        "phase": {"version": 1, "updatedAt": NOW_ISO, "entries": {}}, "queries": [
            _query("all", weights=RELEVANCE_ONLY), _query("at-most-one-day", maxAgeDays=1, weights=RELEVANCE_ONLY),
            _query("today-only", maxAgeDays=0, weights=RELEVANCE_ONLY)]},
        "Persist the six timestamp spellings, then invoke the original and SDK ranking owners "
        "with three age limits. Compare complete ordered candidates and before/after observations.")


def _definitions():
    return [
        _clock("dst-jump-and-fold", [
            ("2026-03-08T06:59:59.999Z", "America/New_York"), ("2026-03-08T07:00:00.000Z", "America/New_York"),
            ("2026-11-01T05:30:00.000Z", "America/New_York"), ("2026-11-01T06:30:00.000Z", "America/New_York")]),
        _clock("offset-midnight-and-host-zone", [
            ("2024-02-29T18:14:59.999Z", "+05:45"), ("2024-02-29T18:15:00.000Z", "+05:45"),
            ("2026-01-01T02:00:00.000Z", "-03:30"), ("2026-01-01T02:00:00.000Z", "Unknown/Calendar")]),
        _rank(),
        _regex("regex-global-multiline-case", r"^(slot: )([a-z]+)$", "im", "Slot: Cedar\nunchanged\nSLOT: MAPLE"),
        _regex("regex-unicode-dotall", r"(tag:)(.+?)(?=;)", "gsu", "tag:🌿\ncedar; keep tag:oak;"),
    ]


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def build_cases():
    cases = _definitions()
    if hashlib.sha256(wire(cases)).hexdigest() != DEFINITION_SHA256:
        raise ValueError("The fixed date/regex input or scope changed")
    return cases


def members(cases):
    return [row for row in cases if row.get("requirement") == REQUIREMENT or row.get("operation") == CLOCK
            or set(POINTS).intersection(row.get("covers", ()))]


def validate_registration(cases):
    rows = members(cases)
    if rows and wire(rows) != wire(build_cases()):
        raise ValueError("Date/regex outcomes require every ordered fixed case")


def family_complete(cases):
    rows = members(cases)
    definitions = build_cases()
    return len(rows) == len(definitions) and all(
        row.get("status") == "matched" and row.get("datetimeRegexValidated") is True
        and wire({k: row.get(k) for k in definition}) == wire(definition)
        for row, definition in zip(rows, definitions))


def run_clock(arguments):
    from datetime import UTC, datetime, timedelta
    from memory_core.current_time import (
        append_cron_style_current_time_line,
        format_user_time,
        resolve_cron_style_now,
        resolve_user_timezone,
        utc_and_local_instants,
    )
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    observations = []
    for instant in arguments["instants"]:
        delta = datetime.fromisoformat(instant["iso"]) - epoch
        now_ms = delta // timedelta(milliseconds=1)
        label, zone = resolve_user_timezone(instant["zone"], host_timezone=arguments["hostTimezone"])
        _, local = utc_and_local_instants(now_ms, zone)
        observations.append({"iso": instant["iso"], "timestampMs": now_ms,
            "resolved": resolve_cron_style_now(now_ms, instant["zone"], arguments["hostTimeFormat"],
                                                host_timezone=arguments["hostTimezone"]),
            "twelveHour": format_user_time(local, "12"), "twentyFourHour": format_user_time(local, "24"),
            "refreshed": append_cron_style_current_time_line(arguments["text"], now_ms=now_ms, timezone=label,
                                                             time_format=arguments["hostTimeFormat"])})
    return {"hostTimezone": arguments["hostTimezone"], "hostTimeFormat": arguments["hostTimeFormat"], "instants": observations}
