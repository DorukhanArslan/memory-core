"""Canonical in-memory recall/phase views used by promotion.

Ports ``normalizeShortTermRecallStore`` and ``normalizeShortTermPhaseSignalStore``
from the pinned original memory plugin. These views do not rewrite the JSON
extension stores. Explicit malformed primitive provenance is treated as untrusted,
a deliberately stricter admission policy than the original primitive-value path.
"""
from __future__ import annotations

import math
import re
from typing import Any

from memory_core.bootstrap._js import JS_SPACE, js_trim
from memory_core.consolidation._util import clamp_score, iso_ms
from memory_core.consolidation.concepts import MAX_CONCEPT_TAGS, derive_concept_tags
from memory_core.consolidation.policy import _UNDEFINED, _js_number
from memory_core.consolidation.recall import (
    MAX_QUERY_HASHES,
    MAX_RECALL_DAYS,
    is_contaminated_dreaming_snippet,
    normalize_memory_path,
    normalize_project_key_list,
)
from memory_core.consolidation.store import truncate_short_term_snippet
from memory_core.session_entry import js_date_parse


_CORPUS_PATH = re.compile(r"(?:^|/)memory/\.dreams/session-corpus/[0-9]{4}-[0-9]{2}-[0-9]{2}\.(?:md|txt)$")
_ISO_DAY = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})")


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _entries(value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, list):
        return [(str(index), item) for index, item in enumerate(value)]
    if not isinstance(value, dict):
        return []
    # Object.entries visits array-index properties before other string keys.
    indexed, other = [], []
    for key, item in value.items():
        key = str(key)
        if re.fullmatch(r"0|[1-9][0-9]*", key) and len(key) <= 10 and int(key) < 2**32 - 1:
            indexed.append((key, item))
        else:
            other.append((key, item))
    return sorted(indexed, key=lambda item: int(item[0])) + other


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(js_trim(item) for item in value if isinstance(item, str) and js_trim(item)))


def _count(value: Any) -> int | float:
    number = _js_number(value)
    if math.isnan(number) or number == 0:
        return 0
    return max(0, math.floor(number) if math.isfinite(number) else number)


def _finite_count(value: Any) -> int:
    number = _js_number(value)
    return max(0, math.floor(number)) if math.isfinite(number) else 0


def _nonblank(value: Any) -> str | None:
    return js_trim(value) or None if isinstance(value, str) else None


def _provenance(entry: dict[str, Any], last_recalled_at: str, now_iso: str) -> dict[str, Any] | None:
    raw = entry.get("provenance", _UNDEFINED)
    if raw is _UNDEFINED or raw is None:
        return None
    # Object-shaped metadata follows the original canonical owner. Explicit
    # malformed primitive metadata fails closed instead of losing its taint.
    value = _record(raw)
    origin = value.get("originClass")
    kind = value.get("sessionKind")
    observed_at = value.get("observedAt")
    observed_number = _js_number(observed_at) if type(observed_at) in (int, float) else math.nan
    fallback = js_date_parse(last_recalled_at)
    if not math.isfinite(fallback):
        fallback = js_date_parse(now_iso)
    result = {
        "originClass": origin if origin in ("owner", "agent", "system", "untrusted") else "untrusted",
        "sessionKind": kind if kind in ("interactive", "cron", "heartbeat", "subagent", "unknown") else "unknown",
        "observedAt": observed_number if math.isfinite(observed_number) else fallback,
    }
    supersedes = _nonblank(value.get("supersedesKey"))
    if supersedes:
        result["supersedesKey"] = supersedes
    return result


def normalize_short_term_recall_store(raw: Any, now_ms: int) -> dict[str, Any]:
    """Return the complete canonical recall view without mutating ``raw``."""
    now_iso = iso_ms(now_ms)
    record = _record(raw)
    entries = {}
    for map_key, value in _entries(record.get("entries")):
        if not isinstance(value, dict | list):
            continue
        entry = _record(value)
        path = normalize_memory_path(entry["path"]) if isinstance(entry.get("path"), str) else ""
        start, end = (_js_number(entry.get(key, _UNDEFINED)) for key in ("startLine", "endLine"))
        if not path or not all(math.isfinite(line) and line.is_integer() for line in (start, end)) or entry.get("source") != "memory":
            continue
        start, end = int(start), int(end)
        recall, daily, grounded = (_count(entry.get(key, _UNDEFINED)) for key in ("recallCount", "dailyCount", "groundedCount"))
        total_score = _js_number(entry.get("totalScore", _UNDEFINED))
        total_score = max(0, total_score) if not math.isnan(total_score) else 0
        max_score = clamp_score(_js_number(entry.get("maxScore", _UNDEFINED)))
        first_at = entry["firstRecalledAt"] if isinstance(entry.get("firstRecalledAt"), str) else now_iso
        last_at = entry["lastRecalledAt"] if isinstance(entry.get("lastRecalledAt"), str) else now_iso
        claim = _nonblank(entry.get("claimHash"))
        project = normalize_project_key_list(entry.get("projectKey"))
        snippet = re.sub(JS_SPACE + "+", " ", js_trim(entry["snippet"])) if isinstance(entry.get("snippet"), str) else ""
        if snippet and is_contaminated_dreaming_snippet(snippet, allow_transcript_turn_snippet=bool(_CORPUS_PATH.search(path))):
            continue
        query_hashes = _strings(entry.get("queryHashes"))[:MAX_QUERY_HASHES]
        user_hashes = (_strings(entry["userQueryHashes"])[:MAX_QUERY_HASHES] if isinstance(entry.get("userQueryHashes"), list)
                       else query_hashes.copy() if daily == 0 and grounded == 0 else None)
        days = [match.group(1) for day in entry.get("recallDays", [])
                if isinstance(day, str) and (match := _ISO_DAY.match(js_trim(day)))] if isinstance(entry.get("recallDays"), list) else []
        concepts = (_strings([js_trim(tag).lower() if isinstance(tag, str) else tag for tag in entry["conceptTags"]])[:MAX_CONCEPT_TAGS]
                    if isinstance(entry.get("conceptTags"), list) else derive_concept_tags(path, snippet))
        provenance = _provenance(entry, last_at, now_iso)
        key = map_key or f"memory:{path}:{start}:{end}" + (":" + claim if claim else "")
        normalized = {"key": key, "path": path, "startLine": start, "endLine": end, "source": "memory",
            "snippet": truncate_short_term_snippet(snippet), "recallCount": recall, "dailyCount": daily,
            "groundedCount": grounded, "totalScore": total_score, "maxScore": max_score,
            "firstRecalledAt": first_at, "lastRecalledAt": last_at, "queryHashes": query_hashes,
            **({"userQueryHashes": user_hashes} if user_hashes is not None else {}),
            "recallDays": days[-MAX_RECALL_DAYS:], "conceptTags": concepts,
            **({"provenance": provenance} if provenance is not None else {}),
            **({"claimHash": claim} if claim else {}), **({"projectKey": project} if project else {}),
            **({"promotedAt": entry["promotedAt"]} if isinstance(entry.get("promotedAt"), str) and entry["promotedAt"] else {})}
        entries[key] = normalized
    return {"version": 1, "updatedAt": record["updatedAt"] if isinstance(record.get("updatedAt"), str) else now_iso, "entries": entries}


def normalize_short_term_phase_signal_store(raw: Any, now_ms: int) -> dict[str, Any]:
    """Keep positive phase signals for scoring, including old signals and omitted fields."""
    now_iso = iso_ms(now_ms)
    record = _record(raw)
    if not isinstance(record.get("entries"), dict):
        return {"version": 1, "updatedAt": now_iso, "entries": {}}
    entries = {}
    for map_key, value in _entries(record["entries"]):
        if not isinstance(value, dict):
            continue
        key = _nonblank(value.get("key")) or map_key
        light = _finite_count(value.get("lightHits", _UNDEFINED))
        rem = _finite_count(value.get("remHits", _UNDEFINED))
        if light == 0 and rem == 0:
            continue
        result = {"key": key, "lightHits": light, "remHits": rem}
        for name in ("lastLightAt", "lastRemAt", "lastRemConsideredAt"):
            stamp = _nonblank(value.get(name))
            if stamp:
                result[name] = stamp
        entries[key] = result
    return {"version": 1, "updatedAt": _nonblank(record.get("updatedAt")) or now_iso, "entries": entries}
