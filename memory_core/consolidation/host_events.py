"""The ``memory.recall.*`` host events, as the OpenClaw event store keeps them.

Port of the two recall events ``recordShortTermRecalls`` appends
(``extensions/memory-core/src/short-term-promotion-record.ts``: ``memory.recall.recorded``, line 381,
and ``memory.recall.skipped`` through ``buildMemoryRecallSkippedEvent``, line 115) and of their
storage normalization (``normalizeMemoryHostEventRecordForStorage``,
``src/memory-host-sdk/event-store.ts``): at most 10 results, the query cut to 2 KiB and every path
to 256 bytes (UTF-8, cut on UTF-16 units, an ellipsis appended), ``storageTruncated`` when anything
was cut, and the results dropped when the JSON would exceed 8 KiB.

memory-core has no event log: the host receives the stored form through an ``on_event`` callback
(the same callback as the ``memory.promotion.applied`` event of the deep phase). Upstream appends
the events to the SQLite plugin state; the oracle reads them back from there.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from memory_core.bootstrap._js import js_json_stringify, js_utf8_encode, utf16_len, utf16_slice

MAX_MEMORY_HOST_EVENT_JSON_BYTES = 8 * 1024
MAX_MEMORY_HOST_EVENT_ITEMS = 10
MAX_MEMORY_HOST_EVENT_TEXT_BYTES = 2 * 1024
MAX_MEMORY_HOST_EVENT_PATH_BYTES = 256
MAX_MEMORY_HOST_EVENT_TIMESTAMP_BYTES = 128

NON_SHORT_TERM_REASON = "non-short-term-memory-path"


def utf8_len(value: str) -> int:
    return len(js_utf8_encode(value))


def truncate_utf8(value: str, max_bytes: int) -> tuple[str, bool]:
    """``truncateUtf8`` of the event store: cut on UTF-16 units, append an ellipsis."""
    if utf8_len(value) <= max_bytes:
        return value, False
    low, high = 0, utf16_len(value)
    while low < high:
        middle = -(-(low + high) // 2)
        if utf8_len(utf16_slice(value, 0, middle)) <= max_bytes - 3:
            low = middle
        else:
            high = middle - 1
    end = low
    if low > 0:
        unit = utf16_slice(value, low - 1, low)
        if len(unit) == 1 and "\ud800" <= unit <= "\udbff":
            end = low - 1
    return f"{utf16_slice(value, 0, end)}…", True


def normalize_recall_event_for_storage(event: Mapping[str, Any]) -> dict[str, Any]:
    """``normalizeMemoryHostEventRecordForStorage`` for ``memory.recall.recorded`` and ``.skipped``."""
    skipped = event["type"] == "memory.recall.skipped"
    raw_results: Sequence[Mapping[str, Any]] = event["results"]
    timestamp, truncated = truncate_utf8(str(event["timestamp"]), MAX_MEMORY_HOST_EVENT_TIMESTAMP_BYTES)
    truncated = truncated or event.get("storageTruncated") is True
    query, query_cut = truncate_utf8(str(event["query"]), MAX_MEMORY_HOST_EVENT_TEXT_BYTES)
    truncated = truncated or query_cut or len(raw_results) > MAX_MEMORY_HOST_EVENT_ITEMS
    results: list[dict[str, Any]] = []
    for result in raw_results[:MAX_MEMORY_HOST_EVENT_ITEMS]:
        path, path_cut = truncate_utf8(str(result["path"]), MAX_MEMORY_HOST_EVENT_PATH_BYTES)
        truncated = truncated or path_cut
        item: dict[str, Any] = {
            "path": path,
            "startLine": result["startLine"],
            "endLine": result["endLine"],
            "score": result["score"],
        }
        if skipped:
            item["reason"] = NON_SHORT_TERM_REASON
        results.append(item)
    normalized: dict[str, Any]
    if skipped:
        normalized = {
            "type": "memory.recall.skipped",
            "timestamp": timestamp,
            "query": query,
            "reason": NON_SHORT_TERM_REASON,
            "eligibleResultCount": event["eligibleResultCount"],
            "skippedResultCount": event["skippedResultCount"],
            "results": results,
        }
    else:
        normalized = {
            "type": "memory.recall.recorded",
            "timestamp": timestamp,
            "query": query,
            "resultCount": event["resultCount"],
            "results": results,
        }
    if truncated:
        normalized["storageTruncated"] = True
    if utf8_len(js_json_stringify(normalized)) > MAX_MEMORY_HOST_EVENT_JSON_BYTES:
        normalized = {**normalized, "results": [], "storageTruncated": True}
    return normalized


def _line(value: Any) -> int:
    """``Math.max(1, Math.floor(value))`` for the numbers a hit carries (1 when it has none)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1
    if not math.isfinite(number):
        return 1
    return max(1, math.floor(number))


def _result_rows(
    hits: Sequence[Mapping[str, Any]], paths: Sequence[str], scores: Sequence[float]
) -> list[dict[str, Any]]:
    return [
        {
            "path": path,
            "startLine": _line(hit.get("startLine")),
            "endLine": _line(hit.get("endLine")),
            "score": score,
        }
        for hit, path, score in zip(hits, paths, scores, strict=True)
    ]


def build_recall_recorded_event(
    *,
    timestamp: str,
    query: str,
    admitted: Sequence[Mapping[str, Any]],
    paths: Sequence[str],
    scores: Sequence[float],
) -> dict[str, Any]:
    """The stored ``memory.recall.recorded`` event for the hits a recall admitted."""
    return normalize_recall_event_for_storage(
        {
            "type": "memory.recall.recorded",
            "timestamp": timestamp,
            "query": query,
            "resultCount": len(admitted),
            "results": _result_rows(admitted, paths, scores),
        }
    )


def build_recall_skipped_event(
    *,
    timestamp: str,
    query: str,
    eligible_result_count: int,
    skipped: Sequence[Mapping[str, Any]],
    paths: Sequence[str],
    scores: Sequence[float],
) -> dict[str, Any]:
    """The stored ``memory.recall.skipped`` event (``buildMemoryRecallSkippedEvent``)."""
    return normalize_recall_event_for_storage(
        {
            "type": "memory.recall.skipped",
            "timestamp": timestamp,
            "query": query,
            "eligibleResultCount": eligible_result_count,
            "skippedResultCount": len(skipped),
            "results": _result_rows(skipped, paths, scores),
        }
    )
