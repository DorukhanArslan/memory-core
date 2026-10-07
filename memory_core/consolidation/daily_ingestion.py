"""Dreaming daily ingestion: the daily notes become ``daily`` recall signals.

Port of the daily half of ``extensions/memory-core/src/dreaming-phases.ts`` (OpenClaw v2026.9.6)
and of ``dreaming-ingestion-state.ts``:

- :func:`build_daily_ingestion_results` (``buildDailyIngestionResults``): the heading-aware
  chunker of one daily note (``buildDailySnippetChunks``: bullet lists keep their ancestors and
  continuation lines, loose paragraphs chunk up to four lines and 280 characters, managed Light and
  REM sleep blocks are stripped first) with the file's trust record
  (``resolveDailyFileProvenance``: an ``untrusted`` flush record is sticky, a record that matches the
  file's hash keeps its origin class, anything else is the owner's ``agent``);
- :func:`collect_daily_ingestion_batches` (``collectDailyIngestionBatches``): the dated files of the
  last ``lookback`` days, newest first, skipped while their ``(mtime, size)`` fingerprint and the
  dreaming day they were last ingested on are unchanged, under a per-sweep cap of
  ``max(20, 4 * limit)`` snippets;
- :func:`ingest_daily_memory_signals` (``ingestDailyMemorySignals``): records each batch as a
  ``daily`` signal (query ``__dreaming_daily__:<day>``) and stores the checkpoint;
- :func:`seed_historical_daily_memory_signals` (``seedHistoricalDailyMemorySignals``): the same for
  explicit files, with the ``dedupeByQueryPerDay`` rule.

The trust records come from the host's :class:`~memory_core.consolidation.artifact_provenance.MemoryArtifactProvenanceStore`
(written by the flush, see :mod:`memory_core.memory_write_provenance`); without one every note is
the owner's.

Deviations: upstream keeps the checkpoint in SQLite plugin state and holds its workspace lock
(``withMemoryWorkspaceLock``) around the whole ingestion; here the checkpoint is
``memory/.dreams/daily-ingestion.json`` (the legacy file name of the file-era store, written
atomically), the whole ingestion holds one per-workspace ingestion lock, and each batch is recorded
under the recall store's own lock. Dates use the host's timezone setting only for the ingestion
dreaming day, like upstream.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory_core.bootstrap._js import (
    JS_SPACE_CLASS,
    js_i_pattern,
    js_trim,
    js_utf8_encode,
    locale_compare,
    truncate_utf16_safe,
    utf16_len,
)
from memory_core.config import MemoryConfig
from memory_core.consolidation._util import write_json_atomic
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenance, MemoryArtifactProvenanceStore
from memory_core.consolidation.origins import MemoryEntryOriginLedger
from memory_core.consolidation.recall import record_short_term_recalls
from memory_core.workspace import workspace_file_lock

DAILY_INGESTION_SCORE = 0.62
DAILY_INGESTION_MAX_SNIPPET_CHARS = 280
DAILY_INGESTION_MIN_SNIPPET_CHARS = 8
DAILY_INGESTION_MAX_CHUNK_LINES = 4
DEFAULT_DAILY_INGESTION_LOOKBACK_DAYS = 14
DAILY_INGESTION_STATE_RELATIVE_PATH = Path("memory") / ".dreams" / "daily-ingestion.json"
INGESTION_LOCK_NAME = "memory/.dreams/ingestion"

_S = JS_SPACE_CLASS
_NOT_LINE_END = "[^\\n\\r\\u2028\\u2029]"  # JavaScript's "." without the s flag

DAILY_MEMORY_FILENAME_RE = re.compile(js_i_pattern(r"^(\d{4}-\d{2}-\d{2})(?:-[^/]+)?\.md\Z"))
_MEMORY_DAY_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_GENERIC_DAY_HEADING_RE = re.compile(
    js_i_pattern(
        r"^(?:(?:mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday)"
        r"(?:,\s+)?)?(?:(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept"
        r"|september|oct|october|nov|november|dec|december)\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?"
        r"|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{4}[/-]\d{2}[/-]\d{2})\Z"
    ).replace("\\s", f"[{_S}]")
)
_LIST_MATCH_RE = re.compile(rf"^([{_S}]*)(?:[-*+]|[0-9]+\.)[{_S}]+({_NOT_LINE_END}+)\Z")
_HEADING_RE = re.compile(rf"^#{{1,6}}[{_S}]+({_NOT_LINE_END}+)\Z")
_SPACE_RUN_RE = re.compile(f"[{_S}]+")
_LIST_NUMBER_PREFIX_RE = re.compile(f"^[0-9]+\\.[{_S}]+")
_LIST_BULLET_PREFIX_RE = re.compile(f"^[-*+][{_S}]+")
_HEADING_START_RE = re.compile(f"^#{{1,6}}[{_S}]+")
_LINE_SPLIT_RE = re.compile(r"\r?\n")

MANAGED_DAILY_DREAMING_BLOCKS = (
    ("## Light Sleep", "<!-- openclaw:dreaming:light:start -->", "<!-- openclaw:dreaming:light:end -->"),
    ("## REM Sleep", "<!-- openclaw:dreaming:rem:start -->", "<!-- openclaw:dreaming:rem:end -->"),
)


def _collapse(text: str) -> str:
    return _SPACE_RUN_RE.sub(" ", text)


# --- file names and days -----------------------------------------------------------------


@dataclass(frozen=True)
class DailyMemoryFile:
    file_name: str
    day: str
    canonical: bool


def parse_daily_memory_file_name(file_name: str) -> DailyMemoryFile | None:
    """``parseDailyMemoryFileName``."""
    match = DAILY_MEMORY_FILENAME_RE.match(file_name)
    if match is None:
        return None
    day = match.group(1)
    return DailyMemoryFile(file_name, day, file_name.lower() == f"{day}.md")


def _compare_daily_files_newest_first(left: DailyMemoryFile, right: DailyMemoryFile) -> int:
    if left.day != right.day:
        return -1 if left.day > right.day else 1
    if left.canonical != right.canonical:
        return -1 if left.canonical else 1
    return locale_compare(left.file_name, right.file_name)


def normalize_memory_day(value: object) -> str | None:
    """``normalizeMemoryDay``: a trimmed ``YYYY-MM-DD`` string or ``None``."""
    if not isinstance(value, str):
        return None
    day = js_trim(value)
    return day if _MEMORY_DAY_RE.match(day) else None


def _days_from_civil(year: int, month: int, day: int) -> int:
    year -= month <= 2
    era = (year if year >= 0 else year - 399) // 400
    yoe = year - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def day_end_ms(day: str) -> float:
    """``Date.parse(`${day}T23:59:59.999Z`)``: V8 accepts day 1 to 31 of any month, NaN otherwise."""
    year, month, date = int(day[0:4]), int(day[5:7]), int(day[8:10])
    if not (1 <= month <= 12 and 1 <= date <= 31):
        return math.nan
    return _days_from_civil(year, month, 1) * 86_400_000 + (date - 1) * 86_400_000 + 86_399_999


def calculate_lookback_cutoff_ms(now_ms: float, lookback_days: float) -> float:
    return now_ms - max(0, lookback_days) * 24 * 60 * 60 * 1000


def is_day_within_lookback(day: str, cutoff_ms: float) -> bool:
    day_ms = day_end_ms(day)
    return not math.isnan(day_ms) and day_ms >= cutoff_ms


def daily_ingestion_lookback_days(phase_lookback_days: float) -> float:
    """``dailyIngestionLookbackDays``: three-day recurrence gates need at least 14 days of history."""
    return max(DEFAULT_DAILY_INGESTION_LOOKBACK_DAYS, phase_lookback_days)


# --- the chunker -------------------------------------------------------------------------


def _normalize_daily_list_marker(line: str) -> str:
    return js_trim(_LIST_BULLET_PREFIX_RE.sub("", _LIST_NUMBER_PREFIX_RE.sub("", line, count=1), count=1))


def _is_generic_daily_heading(heading: str) -> bool:
    normalized = _collapse(js_trim(heading))
    if not normalized:
        return True
    lower = normalized.lower()
    if lower in ("today", "yesterday", "tomorrow", "morning", "afternoon", "evening", "night"):
        return True
    return _GENERIC_DAY_HEADING_RE.match(normalized) is not None


def _normalize_daily_heading(line: str) -> str | None:
    trimmed = js_trim(line)
    match = _HEADING_RE.match(trimmed)
    if match is None:
        return None
    heading = _normalize_daily_list_marker(match.group(1)) if match.group(1) else ""
    if not heading or DAILY_MEMORY_FILENAME_RE.match(heading) or _is_generic_daily_heading(heading):
        return None
    return _collapse(truncate_utf16_safe(heading, DAILY_INGESTION_MAX_SNIPPET_CHARS))


def _normalize_daily_snippet(line: str) -> str | None:
    trimmed = js_trim(line)
    if not trimmed or trimmed.startswith("#") or trimmed.startswith("<!--"):
        return None
    without_marker = _normalize_daily_list_marker(trimmed)
    if utf16_len(without_marker) < DAILY_INGESTION_MIN_SNIPPET_CHARS:
        return None
    return _collapse(truncate_utf16_safe(without_marker, DAILY_INGESTION_MAX_SNIPPET_CHARS))


def _build_daily_chunk_snippet(heading: str | None, chunk_lines: Sequence[str]) -> str:
    body = js_trim(" ".join(chunk_lines))
    prefixed = f"{heading}: {body}" if heading else body
    return js_trim(_collapse(truncate_utf16_snippet(prefixed)))


def truncate_utf16_snippet(value: str) -> str:
    return truncate_utf16_safe(value, DAILY_INGESTION_MAX_SNIPPET_CHARS)


def _build_daily_list_snippet(heading: str | None, ancestors: Sequence[str], snippet: str) -> str:
    body = " > ".join([*ancestors, snippet]).replace(": > ", ": ")
    return _build_daily_chunk_snippet(heading, [body])


@dataclass
class DailySnippetChunk:
    start_line: int
    end_line: int
    snippet: str
    identity_snippet: str | None = None


def build_daily_snippet_chunks(lines: Sequence[str], limit: int) -> list[DailySnippetChunk]:
    """``buildDailySnippetChunks``."""
    chunks: list[DailySnippetChunk] = []
    active_heading: str | None = None
    chunk_lines: list[str] = []
    chunk_start = 0
    chunk_end = 0
    list_ancestors: list[tuple[int, str]] = []

    def flush_chunk() -> None:
        nonlocal chunk_lines, chunk_start, chunk_end
        if not chunk_lines:
            chunk_start = 0
            chunk_end = 0
            return
        snippet = _build_daily_chunk_snippet(active_heading, chunk_lines)
        if utf16_len(snippet) >= DAILY_INGESTION_MIN_SNIPPET_CHARS:
            chunks.append(DailySnippetChunk(chunk_start, chunk_end, snippet))
        chunk_lines = []
        chunk_start = 0
        chunk_end = 0

    index = 0
    while index < len(lines):
        line = lines[index]
        heading = _normalize_daily_heading(line)
        if heading:
            flush_chunk()
            active_heading = heading
            list_ancestors = []
            index += 1
            continue
        trimmed = js_trim(line)
        if not trimmed or trimmed.startswith("<!--"):
            flush_chunk()
            list_ancestors = []
            index += 1
            continue
        list_match = _LIST_MATCH_RE.match(line)
        if list_match:
            flush_chunk()
            indent = len(list_match.group(1))
            list_text = _collapse(
                truncate_utf16_safe(_normalize_daily_list_marker(trimmed), DAILY_INGESTION_MAX_SNIPPET_CHARS)
            )
            if not list_text:
                list_ancestors = []
                index += 1
                continue
            while list_ancestors and list_ancestors[-1][0] >= indent:
                list_ancestors.pop()
            continuation_lines: list[str] = []
            end_index = index
            has_nested_child = False
            nested_child_index: int | None = None
            cursor = index + 1
            while cursor < len(lines):
                next_line = lines[cursor]
                next_trimmed = js_trim(next_line)
                if not next_trimmed:
                    next_content = cursor + 1
                    while next_content < len(lines) and not js_trim(lines[next_content]):
                        next_content += 1
                    loose = _LIST_MATCH_RE.match(lines[next_content]) if next_content < len(lines) else None
                    if loose and len(loose.group(1)) > indent:
                        has_nested_child = True
                        nested_child_index = next_content
                    break
                if next_trimmed.startswith("#") or next_trimmed.startswith("<!--"):
                    break
                next_list = _LIST_MATCH_RE.match(next_line)
                if next_list:
                    has_nested_child = len(next_list.group(1)) > indent
                    break
                continuation_lines.append(_collapse(next_trimmed))
                end_index = cursor
                cursor += 1
            claim_body = " ".join([list_text, *continuation_lines])
            contextual = _build_daily_list_snippet(active_heading, [text for _, text in list_ancestors], claim_body)
            is_container_only = has_nested_child and not continuation_lines and list_text.endswith(":")
            if not is_container_only and utf16_len(contextual) >= DAILY_INGESTION_MIN_SNIPPET_CHARS:
                chunks.append(DailySnippetChunk(index + 1, end_index + 1, contextual, contextual))
            list_ancestors.append((indent, claim_body))
            index = end_index if nested_child_index is None else nested_child_index - 1
            if len(chunks) >= limit:
                break
            index += 1
            continue

        list_ancestors = []
        snippet = _normalize_daily_snippet(line)
        if not snippet:
            flush_chunk()
            index += 1
            continue
        next_chunk_lines = [snippet] if not chunk_lines else [*chunk_lines, snippet]
        candidate = _build_daily_chunk_snippet(active_heading, next_chunk_lines)
        should_split = bool(chunk_lines) and (
            len(chunk_lines) >= DAILY_INGESTION_MAX_CHUNK_LINES
            or utf16_len(candidate) > DAILY_INGESTION_MAX_SNIPPET_CHARS
        )
        if should_split:
            flush_chunk()
        if not chunk_lines:
            chunk_start = index + 1
        chunk_lines.append(snippet)
        chunk_end = index + 1
        if len(chunks) >= limit:
            break
        index += 1

    flush_chunk()
    return chunks[: max(0, limit)]


def _find_managed_heading_index(lines: Sequence[str], start_index: int, heading: str) -> int | None:
    for index in range(start_index - 1, -1, -1):
        trimmed = js_trim(lines[index])
        if not trimmed:
            continue
        return index if trimmed == heading else None
    return None


def strip_managed_daily_dreaming_lines(lines: Sequence[str]) -> list[str]:
    """``stripManagedDailyDreamingLines``: blank the Light and REM sleep blocks the dreaming wrote."""
    by_start = {start: (heading, start, end) for heading, start, end in MANAGED_DAILY_DREAMING_BLOCKS}
    sanitized = list(lines)
    index = 0
    while index < len(sanitized):
        block = by_start.get(js_trim(sanitized[index]))
        if block is None:
            index += 1
            continue
        heading, _start, end_marker = block
        strip_until = -1
        for cursor in range(index + 1, len(sanitized)):
            line = sanitized[cursor]
            trimmed = js_trim(line)
            if trimmed == end_marker:
                strip_until = cursor
                break
            if line and (_HEADING_START_RE.match(trimmed) or trimmed in by_start):
                strip_until = cursor - 1
                break
        if strip_until < index:
            index += 1
            continue
        heading_index = _find_managed_heading_index(lines, index, heading)
        start_index = index if heading_index is None else heading_index
        for cursor in range(start_index, strip_until + 1):
            sanitized[cursor] = ""
        index = strip_until + 1
    return sanitized


def resolve_daily_file_provenance(
    *, current_hash: str, default_observed_at: float, recorded: MemoryArtifactProvenance | None
) -> dict[str, Any]:
    """``resolveDailyFileProvenance``: untracked notes are the owner's, a flush quarantine is sticky."""
    if recorded is not None and recorded.origin_class == "untrusted":
        return {"originClass": "untrusted", "observedAt": recorded.observed_at}
    if recorded is not None and recorded.file_hash == current_hash:
        return {"originClass": recorded.origin_class, "observedAt": recorded.observed_at}
    return {"originClass": "agent", "observedAt": default_observed_at}


def build_daily_ingestion_results(
    *,
    raw: str,
    path: str,
    limit: int,
    default_observed_at: float,
    recorded: MemoryArtifactProvenance | None = None,
) -> list[dict[str, Any]]:
    """``buildDailyIngestionResults``: the search-result rows of one daily note's chunks."""
    provenance = resolve_daily_file_provenance(
        current_hash=hashlib.sha256(js_utf8_encode(raw)).hexdigest(),
        default_observed_at=default_observed_at,
        recorded=recorded,
    )
    chunks = build_daily_snippet_chunks(strip_managed_daily_dreaming_lines(_LINE_SPLIT_RE.split(raw)), limit)
    results: list[dict[str, Any]] = []
    for chunk in chunks:
        row: dict[str, Any] = {
            "path": path,
            "startLine": chunk.start_line,
            "endLine": chunk.end_line,
            "score": DAILY_INGESTION_SCORE,
            "snippet": chunk.snippet,
            "source": "memory",
            "provenance": {**provenance, "sessionKind": "unknown"},
        }
        if chunk.identity_snippet:
            row["identitySnippet"] = chunk.identity_snippet
        results.append(row)
    return results


# --- the checkpoint ----------------------------------------------------------------------


def _js_number(value: object) -> float:
    """``Number(value)`` for the JSON values a checkpoint holds."""
    if isinstance(value, bool):
        return float(value)
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = js_trim(value)
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return math.nan
    return math.nan


@dataclass
class DailyIngestionFileState:
    mtime_ms: int
    size: int
    last_dreaming_day_ingested: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"mtimeMs": self.mtime_ms, "size": self.size}
        if self.last_dreaming_day_ingested:
            out["lastDreamingDayIngested"] = self.last_dreaming_day_ingested
        return out


@dataclass
class DailyIngestionState:
    files: dict[str, DailyIngestionFileState] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"version": 1, "files": {key: value.to_json() for key, value in self.files.items()}}


def normalize_daily_ingestion_state(raw: object) -> DailyIngestionState:
    """``normalizeDailyIngestionState``."""
    files_raw = raw.get("files") if isinstance(raw, Mapping) else None
    state = DailyIngestionState()
    if not isinstance(files_raw, Mapping):
        return state
    for key, value in files_raw.items():
        if not isinstance(value, Mapping) or not isinstance(key, str) or not js_trim(key):
            continue
        mtime_ms, size = _js_number(value.get("mtimeMs")), _js_number(value.get("size"))
        if not math.isfinite(mtime_ms) or mtime_ms < 0 or not math.isfinite(size) or size < 0:
            continue
        state.files[key] = DailyIngestionFileState(
            math.floor(mtime_ms), math.floor(size), normalize_memory_day(value.get("lastDreamingDayIngested"))
        )
    return state


def read_daily_ingestion_state(workspace_dir: str | Path) -> DailyIngestionState:
    path = Path(workspace_dir) / DAILY_INGESTION_STATE_RELATIVE_PATH
    try:
        return normalize_daily_ingestion_state(json.loads(path.read_text("utf-8")))
    except (OSError, ValueError):
        return DailyIngestionState()


def write_daily_ingestion_state(workspace_dir: str | Path, state: DailyIngestionState) -> None:
    write_json_atomic(Path(workspace_dir) / DAILY_INGESTION_STATE_RELATIVE_PATH, state.to_json())


# --- collection and recording ------------------------------------------------------------


@dataclass
class DailyIngestionBatch:
    day: str
    results: list[dict[str, Any]]


@dataclass
class DailyIngestionCollection:
    batches: list[DailyIngestionBatch]
    next_state: DailyIngestionState
    changed: bool


def _fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    return max(0, info.st_mtime_ns // 1_000_000), max(0, info.st_size)


def _read_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def collect_daily_ingestion_batches(
    *,
    workspace_dir: str | Path,
    lookback_days: float,
    limit: int,
    now_ms: float,
    ingestion_dreaming_day: str,
    state: DailyIngestionState,
    provenance_by_path: Mapping[str, MemoryArtifactProvenance] | None = None,
) -> DailyIngestionCollection:
    """``collectDailyIngestionBatches``."""
    workspace = Path(workspace_dir)
    provenance = provenance_by_path or {}
    memory_dir = workspace / "memory"
    cutoff = calculate_lookback_cutoff_ms(now_ms, lookback_days)
    try:
        entries = [entry for entry in os.scandir(memory_dir) if entry.is_file(follow_symlinks=False)]
    except (FileNotFoundError, NotADirectoryError):
        entries = []
    candidates = []
    for entry in entries:
        file = parse_daily_memory_file_name(entry.name)
        if file is not None and is_day_within_lookback(file.day, cutoff):
            candidates.append(file)
    from functools import cmp_to_key

    files = sorted(candidates, key=cmp_to_key(_compare_daily_files_newest_first))

    batches: list[DailyIngestionBatch] = []
    current_paths = {f"memory/{file.file_name}" for file in files}
    # A bounded sweep keeps the checkpoints of current files it never reaches.
    next_files = {key: value for key, value in state.files.items() if key in current_paths}
    changed = False
    total_cap = max(20, limit * 4)
    per_file_cap = max(6, -(-total_cap // max(1, len(files))))
    total = 0
    for file in files:
        relative_path = f"memory/{file.file_name}"
        file_path = memory_dir / file.file_name
        fingerprint = _fingerprint(file_path)
        if fingerprint is None:
            next_files.pop(relative_path, None)
            continue
        current = DailyIngestionFileState(fingerprint[0], fingerprint[1])
        next_files[relative_path] = current
        previous = state.files.get(relative_path)
        unchanged = previous is not None and previous.mtime_ms == current.mtime_ms and previous.size == current.size
        previous_day = normalize_memory_day(previous.last_dreaming_day_ingested if previous else None)
        if unchanged and previous_day == ingestion_dreaming_day:
            next_files[relative_path] = DailyIngestionFileState(current.mtime_ms, current.size, previous_day)
            continue
        changed = True
        raw = _read_text(file_path)
        if not raw:
            continue
        results = build_daily_ingestion_results(
            raw=raw,
            path=relative_path,
            limit=min(per_file_cap, total_cap - total),
            default_observed_at=current.mtime_ms,
            recorded=provenance.get(relative_path),
        )
        if not results:
            continue
        batches.append(DailyIngestionBatch(file.day, results))
        total += len(results)
        next_files[relative_path] = DailyIngestionFileState(current.mtime_ms, current.size, ingestion_dreaming_day)
        if total >= total_cap:
            break
    if not changed and set(state.files) != set(next_files):
        changed = True
    return DailyIngestionCollection(batches, DailyIngestionState(next_files), changed)


def provenance_by_path(
    store: MemoryArtifactProvenanceStore | None, workspace_dir: str | Path
) -> dict[str, MemoryArtifactProvenance]:
    """``listMemoryArtifactProvenance`` as the ``relativePath -> record`` map ingestion reads."""
    if store is None:
        return {}
    return dict(store.list(workspace_dir))


def ingest_daily_memory_signals(
    *,
    config: MemoryConfig,
    now_ms: int,
    lookback_days: float,
    limit: int,
    timezone: str | None = None,
    provenance: MemoryArtifactProvenanceStore | None = None,
    origins: MemoryEntryOriginLedger | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> DailyIngestionCollection:
    """``ingestDailyMemorySignals``: record the changed daily notes as ``daily`` recall signals."""
    from memory_core.consolidation.promotion import format_memory_dreaming_day

    workspace = Path(config.workspace_dir)
    with workspace_file_lock(workspace.resolve(), INGESTION_LOCK_NAME):
        state = read_daily_ingestion_state(workspace)
        day_bucket = format_memory_dreaming_day(now_ms, timezone)
        collected = collect_daily_ingestion_batches(
            workspace_dir=workspace,
            lookback_days=lookback_days,
            limit=limit,
            now_ms=now_ms,
            ingestion_dreaming_day=day_bucket,
            state=state,
            provenance_by_path=provenance_by_path(provenance, workspace),
        )
        for batch in collected.batches:
            record_short_term_recalls(
                config=config,
                query=f"__dreaming_daily__:{batch.day}",
                results=batch.results,
                now_ms=now_ms,
                signal_type="daily",
                # The checkpoint already prevents duplicate unchanged files; file days stay the
                # recurrence buckets, so a later changed-file ingestion still adds a signal.
                dedupe_by_query_per_day=False,
                day_bucket=batch.day,
                timezone=timezone,
                origins=origins,
                on_event=on_event,
            )
        if collected.changed:
            write_daily_ingestion_state(workspace, collected.next_state)
    return collected


@dataclass(frozen=True)
class HistoricalSeedResult:
    imported_file_count: int
    imported_signal_count: int
    skipped_paths: list[str]


def resolve_workspace_memory_relative_path(workspace_dir: str | Path, file_path: str | Path) -> str:
    """``resolveWorkspaceMemoryRelativePath``: workspace-relative, else ``memory/<basename>``."""
    relative = os.path.relpath(file_path, workspace_dir).replace("\\", "/")
    if relative and relative != ".." and not relative.startswith("../"):
        return relative
    return f"memory/{os.path.basename(file_path)}"


def seed_historical_daily_memory_signals(
    *,
    config: MemoryConfig,
    file_paths: Sequence[str],
    limit: int,
    now_ms: int,
    timezone: str | None = None,
    provenance: MemoryArtifactProvenanceStore | None = None,
    origins: MemoryEntryOriginLedger | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> HistoricalSeedResult:
    """``seedHistoricalDailyMemorySignals``: import explicit daily notes with the per-day dedupe rule."""
    from functools import cmp_to_key

    from memory_core.consolidation.promotion import format_memory_dreaming_day

    normalized = list(dict.fromkeys(js_trim(path) for path in file_paths if js_trim(path)))
    if not normalized:
        return HistoricalSeedResult(0, 0, [])
    workspace = Path(config.workspace_dir)
    with workspace_file_lock(workspace.resolve(), INGESTION_LOCK_NAME):
        by_path = provenance_by_path(provenance, workspace)
        resolved = []
        for file_path in normalized:
            file_name = os.path.basename(file_path)
            file = parse_daily_memory_file_name(file_name)
            relative = resolve_workspace_memory_relative_path(workspace, file_path) if file else ""
            resolved.append((file_path, file, relative))

        def compare(left: tuple[str, DailyMemoryFile | None, str], right: tuple[str, DailyMemoryFile | None, str]) -> int:
            if left[1] and right[1]:
                return _compare_daily_files_newest_first(left[1], right[1])
            if left[1]:
                return -1
            if right[1]:
                return 1
            return locale_compare(left[0], right[0])

        resolved.sort(key=cmp_to_key(compare))
        valid = [entry for entry in resolved if entry[1] is not None]
        skipped = [entry[0] for entry in resolved if entry[1] is None]
        total_cap = max(20, limit * 4)
        per_file_cap = max(6, -(-total_cap // max(1, len(valid))))
        imported_signals = 0
        imported_files = 0
        for file_path, file, relative in valid:
            if imported_signals >= total_cap:
                break
            assert file is not None
            absolute = Path(file_path) if os.path.isabs(file_path) else Path(os.path.abspath(file_path))
            try:
                raw = absolute.read_bytes().decode("utf-8", errors="replace")
            except FileNotFoundError:
                skipped.append(file_path)
                continue
            if not raw:
                continue
            results = build_daily_ingestion_results(
                raw=raw,
                path=relative,
                limit=min(per_file_cap, total_cap - imported_signals),
                default_observed_at=now_ms,
                recorded=by_path.get(relative),
            )
            if not results:
                continue
            record_short_term_recalls(
                config=config,
                query=f"__dreaming_daily__:{file.day}",
                results=results,
                now_ms=now_ms,
                signal_type="daily",
                dedupe_by_query_per_day=True,
                day_bucket=format_memory_dreaming_day(now_ms, timezone),
                timezone=timezone,
                origins=origins,
                on_event=on_event,
            )
            imported_signals += len(results)
            imported_files += 1
    return HistoricalSeedResult(imported_files, imported_signals, skipped)
