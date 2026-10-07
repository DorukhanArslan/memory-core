"""Dreaming session ingestion: the live session transcripts become ``daily`` recall signals.

Port of ``extensions/memory-core/src/session-ingestion.ts`` and the session half of
``dreaming-phases.ts`` (``collectSessionIngestionBatches``, ``ingestSessionTranscriptSignals``,
OpenClaw v2026.9.6), over transcripts the host supplies:

- :func:`scan_session_ingestion_source` (``scanSessionIngestionSource``): one transcript is exported
  to ``User:``/``Assistant:`` lines (:func:`memory_core.session_entry.build_session_entry`), the lines
  past the per-file cursor are cut into messages (at least 12 characters, 280 at most), tagged with the
  day of their timestamp in the dreaming timezone, skipped when their hash was seen before
  (``sha1(scope \\n ts:<ms>|line:<n> \\n snippet)``) and returned with the file's new fingerprint; an
  unchanged transcript is skipped by its ``(mtime, size, hash)`` checkpoint, and an append is found
  through the prefix hash of the previous snapshot;
- :func:`session_exclusion_reason` (``sessionExclusionReason``): a forgotten session (a tombstone in the
  origins ledger, :mod:`memory_core.consolidation.origins`) is never ingested again, nor one the
  admission policy (``memoryPolicy.excludeSessions``) names;
- :func:`collect_session_ingestion_batches` and :func:`ingest_session_transcript_signals`: the
  sweep over the host's corpus entries (only ``interactive`` ``active-session`` entries, never a
  compaction checkpoint) with a per-sweep cap of 240 messages and a per-file cap of 12 to 80, the day
  files appended to ``memory/.dreams/session-corpus/<day>.txt`` (:func:`append_session_corpus_lines`)
  and every day recorded as a ``daily`` signal (query ``__dreaming_sessions__:<day>``, score 0.58),
  each hit carrying its ``sessionOrigin`` so the origins ledger learns the lineage.

Deviations: the host supplies the corpus (:class:`SessionCorpusEntry`; upstream enumerates its SQLite
session store, ``listSessionTranscriptCorpusEntriesForAgent``) and the session metadata of the
admission policy (``load_session_metadata``; upstream ``loadMemorySessionMetadata``); transcripts are
JSONL files (``transcriptSource: "file"``); the checkpoint is ``memory/.dreams/session-ingestion.json``
(the legacy file name of the file-era store, version 3) instead of SQLite plugin state; one
per-workspace ingestion lock replaces the workspace lock.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from memory_core.bootstrap._js import JS_SPACE_CLASS, js_trim, js_utf8_encode, truncate_utf16_safe, utf16_len
from memory_core.config import MemoryConfig
from memory_core.consolidation._util import write_json_atomic
from memory_core.consolidation.daily_ingestion import (
    INGESTION_LOCK_NAME,
    calculate_lookback_cutoff_ms,
    is_day_within_lookback,
    normalize_memory_day,
)
from memory_core.consolidation.origins import MemoryEntryOriginLedger
from memory_core.consolidation.recall import record_short_term_recalls
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.session_entry import (
    SessionEntry,
    build_session_entry,
    matches_session_entry_prefix_hash,
    parse_jsonl_records,
)
from memory_core.workspace import workspace_file_lock

SESSION_CORPUS_RELATIVE_DIR = "memory/.dreams/session-corpus"
SESSION_INGESTION_STATE_RELATIVE_PATH = Path("memory") / ".dreams" / "session-ingestion.json"
SESSION_INGESTION_SCORE = 0.58
SESSION_INGESTION_MAX_MESSAGES_PER_SWEEP = 240
SESSION_INGESTION_MAX_MESSAGES_PER_FILE = 80
SESSION_INGESTION_MIN_MESSAGES_PER_FILE = 12
SESSION_INGESTION_MIN_SNIPPET_CHARS = 12
SESSION_INGESTION_MAX_SNIPPET_CHARS = 280
SESSION_INGESTION_MAX_TRACKED_SCOPES = 2048
SESSION_INGESTION_MAX_TRACKED_MESSAGES_PER_SESSION = 4096

_WHITESPACE_RUN_RE = re.compile(f"[{JS_SPACE_CLASS}]+")
_CHECKPOINT_TRANSCRIPT_RE = re.compile(r"\.checkpoint\..+\.jsonl\Z", re.IGNORECASE | re.ASCII)

DayDisposition = Literal["include", "skip", "block"]
ScanStatus = Literal["absent", "excluded", "unavailable", "unchanged", "scanned"]


# --- data ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionCorpusEntry:
    """The part of ``SessionTranscriptCorpusEntry`` ingestion reads (a JSONL transcript the host owns)."""

    agent_id: str
    session_id: str
    session_file: str
    session_key: str | None = None
    session_kind: str | None = "interactive"
    artifact_kind: str = "active-session"
    # "sqlite": the host's session store owns the transcript (upstream: the agent's SQLite store; the
    # logical path is ``sessions/<agent>/<id>``, the scope carries it and the reset-recall cutoff is
    # read from the events). "file": a JSONL transcript file (``sessions/<agent>/<file>``).
    transcript_source: str = "file"
    store_path: str | None = None
    updated_at_ms: float | None = None
    generated_by_dreaming_narrative: bool = False
    generated_by_cron_run: bool = False


@dataclass(frozen=True)
class SessionAdmissionPolicy:
    """``SessionAdmissionPolicy`` (``memoryPolicy.excludeSessions``)."""

    hook_external_content_sources: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    chat_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionIngestionSource:
    agent_id: str
    absolute_path: str
    foreign: bool
    session_path: str
    state_key: str
    scope: str
    build_options: Mapping[str, Any]
    session_origin: Mapping[str, str] | None = None
    legacy_scope: str | None = None


@dataclass
class SessionIngestionFileState:
    mtime_ms: int
    size: int
    content_hash: str
    line_count: int
    last_content_line: int
    excluded_reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mtimeMs": self.mtime_ms,
            "size": self.size,
            "contentHash": self.content_hash,
            "lineCount": self.line_count,
            "lastContentLine": self.last_content_line,
        }
        if self.excluded_reason:
            out["excludedReason"] = self.excluded_reason
        return out


@dataclass
class SessionIngestionState:
    files: dict[str, SessionIngestionFileState] = field(default_factory=dict)
    seen_messages: dict[str, list[str]] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "version": 3,
            "files": {key: value.to_json() for key, value in self.files.items()},
            "seenMessages": {key: list(value) for key, value in self.seen_messages.items()},
        }


@dataclass(frozen=True)
class SessionIngestionCandidate:
    day: str
    snippet: str
    rendered: str
    provenance: Mapping[str, Any]
    content_index: int
    hash: str
    line_number: int
    scope: str
    state_key: str
    session_origin: Mapping[str, str] | None = None


@dataclass
class SessionIngestionScan:
    status: ScanStatus
    candidates: list[SessionIngestionCandidate]
    file_state: SessionIngestionFileState | None = None
    progress_block_index: int | None = None
    scanned_end_index: int = 0


# --- paths --------------------------------------------------------------------------------


def extract_agent_id_from_sessions_dir(sessions_dir: str) -> str | None:
    parts = [part for part in re.split(r"[\\/]", sessions_dir) if part]
    if len(parts) < 3 or parts[-1] != "sessions" or parts[-3] != "agents" or not parts[-2]:
        return None
    return parts[-2]


def extract_agent_id_from_session_path(abs_path: str) -> str | None:
    """``extractAgentIdFromSessionPath``: the nearest canonical ``agents/<id>/sessions`` ancestor."""
    current = os.path.dirname(os.path.abspath(abs_path))
    while True:
        if os.path.basename(current) == "sessions":
            agent_id = extract_agent_id_from_sessions_dir(current)
            if agent_id:
                return agent_id
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def session_path_for_file(abs_path: str) -> str:
    """``sessionPathForFile``: ``sessions/<agent>/<file>`` (``sessions/<file>`` outside an agent directory)."""
    agent_id = extract_agent_id_from_session_path(abs_path)
    parts = ["sessions", *([agent_id] if agent_id else []), os.path.basename(abs_path)]
    return "/".join(parts)


def build_session_scope(agent_id: str, session_id: str) -> str:
    return f"{agent_id}:{session_id}"


def session_path_from_corpus(entry: SessionCorpusEntry) -> str:
    """``sessionPathFromCorpus``."""
    if entry.transcript_source == "sqlite":
        return f"sessions/{entry.agent_id}/{entry.session_id}"
    return session_path_for_file(entry.session_file)


def session_ingestion_state_key_from_corpus(entry: SessionCorpusEntry) -> str:
    return f"{entry.agent_id}:{session_path_from_corpus(entry)}"


def session_ingestion_source_from_corpus(entry: SessionCorpusEntry) -> SessionIngestionSource | None:
    """``sessionIngestionSourceFromCorpus``: only interactive sessions are ingested."""
    session_path = session_path_from_corpus(entry)
    if entry.session_kind != "interactive":
        return None
    sqlite = entry.transcript_source == "sqlite"
    origin: dict[str, str] = {"agentId": entry.agent_id, "sessionId": entry.session_id}
    if entry.session_key:
        origin["sessionKey"] = entry.session_key
    options: dict[str, Any] = {"sessionKind": "interactive"}
    if sqlite:
        options["agentId"] = entry.agent_id
        options["sessionId"] = entry.session_id
    if entry.session_key:
        options["sessionKey"] = entry.session_key
    if entry.store_path:
        options["storePath"] = entry.store_path
    if entry.updated_at_ms is not None:
        options["updatedAtMs"] = entry.updated_at_ms
    if entry.generated_by_dreaming_narrative:
        options["generatedByDreamingNarrative"] = True
    if entry.generated_by_cron_run:
        options["generatedByCronRun"] = True
    return SessionIngestionSource(
        agent_id=entry.agent_id,
        absolute_path=entry.session_file,
        foreign=False,
        session_path=session_path,
        state_key=f"{entry.agent_id}:{session_path}",
        scope=f"{entry.agent_id}:{session_path}" if sqlite else build_session_scope(entry.agent_id, entry.session_id),
        session_origin=origin,
        build_options=options,
        legacy_scope=build_session_scope(entry.agent_id, entry.session_id) if sqlite else None,
    )


def foreign_session_ingestion_source(agent_id: str, archive_file: str) -> SessionIngestionSource:
    """``foreignSessionIngestionSource``: a caller-supplied archive; its provenance is never trusted."""
    absolute = os.path.abspath(archive_file)
    normalized = absolute.replace("\\", "/")
    return SessionIngestionSource(
        agent_id=agent_id,
        absolute_path=absolute,
        foreign=True,
        session_path=session_path_for_file(absolute),
        state_key=f"session-backfill:{normalized}",
        scope=f"archive:{agent_id}:{normalized}",
        build_options={"sessionKind": "interactive"},
    )


# --- admission ----------------------------------------------------------------------------


def resolve_admission_policy(plugin_config: Mapping[str, Any] | None) -> SessionAdmissionPolicy | None:
    """``resolveAdmissionPolicy``: ``memoryPolicy.excludeSessions`` of the plugin config."""
    policy_config = plugin_config.get("memoryPolicy") if plugin_config else None
    exclusions = policy_config.get("excludeSessions") if isinstance(policy_config, Mapping) else None
    if not isinstance(exclusions, Mapping):
        return None

    def values(key: str) -> tuple[str, ...]:
        raw = exclusions.get(key)
        if not isinstance(raw, list):
            return ()
        return tuple(text for text in (js_trim(str(item)) for item in raw if isinstance(item, str)) if text)

    policy = SessionAdmissionPolicy(
        values("hookExternalContentSources"), values("channels"), values("chatTypes")
    )
    return policy if (policy.hook_external_content_sources or policy.channels or policy.chat_types) else None


MetadataLoader = Callable[[Mapping[str, str], str | None], Mapping[str, Any] | None]


def session_exclusion_reason(
    source: SessionIngestionSource,
    policy: SessionAdmissionPolicy | None = None,
    forgotten_session_ids: set[str] | None = None,
    *,
    origins: MemoryEntryOriginLedger | None = None,
    load_session_metadata: MetadataLoader | None = None,
) -> str | None:
    """``sessionExclusionReason``: ``forgotten`` (a tombstone) or the admission policy's ``kind:value``."""
    if not source.session_origin:
        return None
    agent_id = source.session_origin["agentId"]
    session_id = source.session_origin["sessionId"]
    if forgotten_session_ids is not None:
        forgotten = session_id in forgotten_session_ids
    elif origins is not None:
        forgotten = bool(origins.list_session_tombstones(agent_id, [session_id]))
    else:
        forgotten = False
    if forgotten:
        return "forgotten"
    if policy is None or load_session_metadata is None:
        return None
    metadata = load_session_metadata(source.session_origin, source.build_options.get("storePath"))
    if not metadata:
        return None
    hook_source = metadata.get("hookExternalContentSource")
    if hook_source and hook_source in policy.hook_external_content_sources:
        return f"hookExternalContentSource:{hook_source}"
    channel = metadata.get("channel")
    if channel and channel in policy.channels:
        return f"channel:{channel}"
    chat_type = metadata.get("chatType")
    return f"chatType:{chat_type}" if chat_type and chat_type in policy.chat_types else None


# --- the scan -----------------------------------------------------------------------------


def _collapse(text: str) -> str:
    return _WHITESPACE_RUN_RE.sub(" ", text)


def normalize_session_corpus_snippet(value: str) -> str:
    return truncate_utf16_safe(js_trim(_collapse(value)), SESSION_INGESTION_MAX_SNIPPET_CHARS)


def hash_session_message_id(value: str) -> str:
    return hashlib.sha1(js_utf8_encode(value)).hexdigest()


@dataclass(frozen=True)
class SessionFileEntry:
    """The part of ``SessionFileEntry`` a scan reads (``mtime_ms`` and ``size`` are the file's)."""

    entry: SessionEntry
    mtime_ms: float
    size: int


def _stat_fingerprint(path: str) -> tuple[int, int] | None:
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return None
    mtime_ms = info.st_mtime_ns // 1_000_000
    return max(0, mtime_ms), info.st_size


def build_session_file_entry(
    source: SessionIngestionSource,
    *,
    redact_text: Callable[[str], str] | None = None,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> SessionFileEntry | None:
    """``buildSessionEntry`` of a JSONL transcript file (``None`` when it cannot be read)."""
    try:
        info = os.stat(source.absolute_path)
        text = Path(source.absolute_path).read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None
    seconds, nanos = divmod(info.st_mtime_ns, 1_000_000_000)
    mtime_ms = seconds * 1000 + nanos / 1e6
    options = source.build_options
    entry = build_session_entry(
        records=parse_jsonl_records(text),
        mtime_ms=mtime_ms,
        session_kind=options.get("sessionKind") or "unknown",
        # The host's flags are authoritative for a file transcript; the key never classifies it.
        generated_by_dreaming_narrative=bool(options.get("generatedByDreamingNarrative")),
        generated_by_cron_run=bool(options.get("generatedByCronRun")),
        reset_recall_cutoff=None if options.get("agentId") else {"state": "absent"},
        redact_text=redact_text,
        runtime_identity=runtime_identity,
    )
    return SessionFileEntry(entry, mtime_ms, info.st_size)


def scan_session_ingestion_source(
    *,
    source: SessionIngestionSource,
    previous: SessionIngestionFileState | None = None,
    seen_messages: Mapping[str, Sequence[str]],
    timezone: str | None = None,
    max_candidates: int | None = None,
    verify_content: bool = False,
    accept_provenance: Callable[[Mapping[str, Any]], bool] | None = None,
    classify_day: Callable[[str], DayDisposition],
    build_entry: Callable[[SessionIngestionSource], SessionFileEntry | None] | None = None,
) -> SessionIngestionScan:
    """``scanSessionIngestionSource``."""
    from memory_core.consolidation.promotion import format_memory_dreaming_day

    def empty(status: ScanStatus, file_state: SessionIngestionFileState | None = None) -> SessionIngestionScan:
        return SessionIngestionScan(
            status, [], file_state, scanned_end_index=file_state.last_content_line if file_state else 0
        )

    fingerprint = _stat_fingerprint(source.absolute_path)
    if fingerprint is None:
        return empty("absent")
    if (
        not verify_content
        and previous is not None
        and previous.mtime_ms == fingerprint[0]
        and previous.size == fingerprint[1]
        and len(previous.content_hash) > 0
        and previous.last_content_line >= previous.line_count
    ):
        return empty("unchanged", previous)
    built = (build_entry or build_session_file_entry)(source)
    if built is None:
        # Transient failures collapse to None; the stat above owns absence, so keep the checkpoint.
        return empty("unavailable", previous)
    entry = built.entry
    file_mtime = math.floor(max(0, built.mtime_ms))
    file_size = math.floor(max(0, built.size))
    lines = entry.content.split("\n") if entry.content else []
    terminal = SessionIngestionFileState(file_mtime, file_size, js_trim(entry.hash), len(lines), len(lines))
    if entry.generated_by_dreaming_narrative or entry.generated_by_cron_run:
        return empty("excluded", terminal)
    if (
        previous is not None
        and previous.mtime_ms == file_mtime
        and previous.size == file_size
        and previous.content_hash == terminal.content_hash
        and previous.line_count == len(lines)
        and previous.last_content_line >= len(lines)
    ):
        return empty("unchanged", previous)
    previous_matches = (
        previous is not None
        and len(previous.content_hash) > 0
        and (
            (previous.line_count == len(lines) and previous.content_hash == terminal.content_hash)
            or (
                previous.line_count < len(lines)
                and matches_session_entry_prefix_hash(entry, previous.line_count, previous.content_hash)
            )
        )
    )
    start_index = max(0, min(previous.last_content_line if previous else 0, len(lines))) if previous_matches else 0
    seen = set(seen_messages.get(source.scope, ()))
    legacy_seen = set(seen_messages.get(source.legacy_scope, ())) if source.legacy_scope else None
    candidates: list[SessionIngestionCandidate] = []
    progress_block_index: int | None = None
    scanned_end_index = start_index
    for index in range(start_index, len(lines)):
        if max_candidates is not None and len(candidates) >= max_candidates:
            break
        scanned_end_index = index + 1
        snippet = normalize_session_corpus_snippet(lines[index])
        if utf16_len(snippet) < SESSION_INGESTION_MIN_SNIPPET_CHARS:
            continue
        line_number = entry.line_map[index] if index < len(entry.line_map) else index + 1
        timestamp_ms = entry.message_timestamps_ms[index] if index < len(entry.message_timestamps_ms) else 0
        parsed = (
            entry.line_provenance[index]
            if index < len(entry.line_provenance)
            else {
                "originClass": "untrusted",
                "sessionKind": "interactive",
                "observedAt": timestamp_ms or built.mtime_ms,
            }
        )
        # Foreign JSONL is caller-controlled; only canonical stores authenticate provenance.
        provenance = {**parsed, "originClass": "untrusted"} if source.foreign else parsed
        if accept_provenance is not None and not accept_provenance(provenance):
            continue
        day = format_memory_dreaming_day(timestamp_ms or built.mtime_ms, timezone)
        disposition = classify_day(day)
        if disposition != "include":
            if disposition == "block" and progress_block_index is None:
                progress_block_index = index
            continue
        basis = f"ts:{math.floor(timestamp_ms)}" if timestamp_ms > 0 else f"line:{line_number}"
        message_hash = hash_session_message_id(f"{source.scope}\n{basis}\n{snippet}")
        legacy_hash = (
            hash_session_message_id(f"{source.legacy_scope}\n{basis}\n{snippet}") if source.legacy_scope else None
        )
        if message_hash in seen or (legacy_hash and legacy_seen is not None and legacy_hash in legacy_seen):
            continue
        candidates.append(
            SessionIngestionCandidate(
                day=day,
                snippet=snippet,
                rendered=truncate_utf16_safe(
                    f"[{source.agent_id}/{source.session_path}#L{line_number}] {snippet}",
                    SESSION_INGESTION_MAX_SNIPPET_CHARS + 64,
                ),
                provenance=provenance,
                content_index=index,
                hash=message_hash,
                line_number=line_number,
                scope=source.scope,
                state_key=source.state_key,
                session_origin=source.session_origin,
            )
        )
        seen.add(message_hash)
    return SessionIngestionScan(
        "scanned",
        candidates,
        SessionIngestionFileState(
            terminal.mtime_ms, terminal.size, terminal.content_hash, terminal.line_count, scanned_end_index
        ),
        progress_block_index,
        scanned_end_index,
    )


def merge_tracked_message_hashes(existing: Iterable[str], additions: Iterable[str]) -> list[str]:
    merged = list(dict.fromkeys([*existing, *additions]))
    return merged[-SESSION_INGESTION_MAX_TRACKED_MESSAGES_PER_SESSION:]


def _utf16_key(value: str) -> bytes:
    return value.encode("utf-16-be", "surrogatepass")


def trim_tracked_session_scopes(seen_messages: Mapping[str, list[str]]) -> dict[str, list[str]]:
    keep = set(sorted(seen_messages, key=_utf16_key)[-SESSION_INGESTION_MAX_TRACKED_SCOPES:])
    return {scope: hashes for scope, hashes in seen_messages.items() if scope in keep}


# --- the checkpoint -----------------------------------------------------------------------


def _js_number(value: object) -> float:
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


def normalize_session_ingestion_state(raw: object) -> SessionIngestionState:
    """``normalizeSessionIngestionState``."""
    record = raw if isinstance(raw, Mapping) else {}
    state = SessionIngestionState()
    files_raw = record.get("files")
    if isinstance(files_raw, Mapping):
        for key, value in files_raw.items():
            if not isinstance(value, Mapping) or not js_trim(str(key)):
                continue
            mtime_ms, size = _js_number(value.get("mtimeMs")), _js_number(value.get("size"))
            if not math.isfinite(mtime_ms) or mtime_ms < 0 or not math.isfinite(size) or size < 0:
                continue
            line_count_raw = _js_number(value.get("lineCount"))
            last_raw = _js_number(value.get("lastContentLine"))
            line_count = math.floor(line_count_raw) if math.isfinite(line_count_raw) and line_count_raw >= 0 else 0
            last_content_line = math.floor(last_raw) if math.isfinite(last_raw) and last_raw >= 0 else 0
            reason = value.get("excludedReason")
            state.files[key] = SessionIngestionFileState(
                math.floor(mtime_ms),
                math.floor(size),
                js_trim(value["contentHash"]) if isinstance(value.get("contentHash"), str) else "",
                line_count,
                min(line_count, last_content_line),
                js_trim(reason) if isinstance(reason, str) and js_trim(reason) else None,
            )
    seen_raw = record.get("seenMessages")
    if isinstance(seen_raw, Mapping):
        for scope, value in seen_raw.items():
            if not js_trim(str(scope)) or not isinstance(value, list):
                continue
            unique = dict.fromkeys(entry for entry in value if isinstance(entry, str))
            normalized = [text for text in (js_trim(entry) for entry in unique) if text]
            normalized = normalized[-SESSION_INGESTION_MAX_TRACKED_MESSAGES_PER_SESSION:]
            if normalized:
                state.seen_messages[scope] = normalized
    return state


def read_session_ingestion_state(workspace_dir: str | Path) -> SessionIngestionState:
    path = Path(workspace_dir) / SESSION_INGESTION_STATE_RELATIVE_PATH
    try:
        return normalize_session_ingestion_state(json.loads(path.read_text("utf-8")))
    except (OSError, ValueError):
        return SessionIngestionState()


def write_session_ingestion_state(workspace_dir: str | Path, state: SessionIngestionState) -> None:
    write_json_atomic(Path(workspace_dir) / SESSION_INGESTION_STATE_RELATIVE_PATH, state.to_json())


# --- the session corpus -------------------------------------------------------------------


def append_session_corpus_text(file_path: str | Path, content: str, *, workspace_dir: str | Path | None = None) -> int:
    """``appendSessionCorpusText``: append to a corpus file (symlinked parents refused), return the lines it held."""
    path = Path(file_path)
    if workspace_dir is not None:
        current = Path(workspace_dir)
        for part in path.relative_to(workspace_dir).parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise OSError(f"{part} is a symlink; session corpus writes never follow symlinks")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = path.read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        existing = ""
    normalized = existing.replace("\r\n", "\n")
    existing_lines = (
        len((normalized[:-1] if normalized.endswith("\n") else normalized).split("\n")) if normalized else 0
    )
    if path.is_symlink():
        raise OSError(f"{path.name} is a symlink; session corpus writes never follow symlinks")
    with path.open("ab") as handle:
        handle.write(content.encode("utf-8", "surrogatepass"))
    return existing_lines


def append_session_corpus_lines(
    *, workspace_dir: str | Path, day: str, lines: Sequence[SessionIngestionCandidate]
) -> list[dict[str, Any]]:
    """``appendSessionCorpusLines``: add the day's rendered lines, return their search-result rows."""
    if not lines:
        return []
    relative = f"{SESSION_CORPUS_RELATIVE_DIR}/{day}.txt"
    absolute = Path(workspace_dir) / SESSION_CORPUS_RELATIVE_DIR / f"{day}.txt"
    content = "".join(f"{entry.rendered}\n" for entry in lines)
    existing_lines = append_session_corpus_text(absolute, content, workspace_dir=workspace_dir)
    results: list[dict[str, Any]] = []
    for index, entry in enumerate(lines):
        row: dict[str, Any] = {
            "path": relative,
            "startLine": existing_lines + index + 1,
            "endLine": existing_lines + index + 1,
            "score": SESSION_INGESTION_SCORE,
            "snippet": entry.snippet,
            "source": "memory",
            "provenance": dict(entry.provenance),
        }
        if entry.session_origin:
            row["sessionOrigin"] = dict(entry.session_origin)
        results.append(row)
    return results


# --- the sweep ----------------------------------------------------------------------------


@dataclass
class SessionIngestionBatch:
    day: str
    results: list[dict[str, Any]]


@dataclass
class SessionIngestionCollection:
    batches: list[SessionIngestionBatch]
    next_state: SessionIngestionState
    changed: bool


def collect_session_ingestion_batches(
    *,
    workspace_dir: str | Path,
    agent_ids: Sequence[str] | None,
    corpus_entries: Callable[[str], Iterable[SessionCorpusEntry]],
    lookback_days: float,
    now_ms: float,
    timezone: str | None = None,
    state: SessionIngestionState,
    admission_policy: SessionAdmissionPolicy | None = None,
    origins: MemoryEntryOriginLedger | None = None,
    load_session_metadata: MetadataLoader | None = None,
    redact_text: Callable[[str], str] | None = None,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> SessionIngestionCollection:
    """``collectSessionIngestionBatches``: scan the sources of ``agent_ids`` (``None``: no workspace agents)."""
    if agent_ids is None:
        next_state = SessionIngestionState()
        return SessionIngestionCollection(
            [], next_state, json.dumps(next_state.to_json()) != json.dumps(state.to_json())
        )
    cutoff = calculate_lookback_cutoff_ms(now_ms, lookback_days)
    batch_by_day: dict[str, list[SessionIngestionCandidate]] = {}
    # A bounded sweep keeps the checkpoints of sources it never reaches; only a source that was
    # discovered and then proved absent is removed.
    next_files = dict(state.files)
    next_seen: dict[str, list[str]] = {scope: list(hashes) for scope, hashes in state.seen_messages.items()}
    sources: list[SessionIngestionSource] = []
    for agent_id in agent_ids:
        known_state_keys: set[str] = set()
        forgotten = (
            {tombstone.session_id for tombstone in origins.list_session_tombstones(agent_id)}
            if origins is not None
            else set()
        )
        for entry in corpus_entries(agent_id):
            known_state_keys.add(session_ingestion_state_key_from_corpus(entry))
            source = session_ingestion_source_from_corpus(entry)
            if source is None:
                continue
            # Dreaming learns only from the live corpus; retained archives stay for memory_search.
            if entry.artifact_kind != "active-session" or _CHECKPOINT_TRANSCRIPT_RE.search(
                os.path.basename(entry.session_file)
            ):
                continue
            excluded = session_exclusion_reason(
                source,
                admission_policy,
                forgotten,
                load_session_metadata=load_session_metadata,
            )
            if excluded:
                # Record the exclusion before any content is read; the empty fingerprint makes
                # removing the policy re-admit the session.
                next_files[source.state_key] = SessionIngestionFileState(
                    math.floor(entry.updated_at_ms or 0), 0, "", 0, 0, excluded
                )
                continue
            sources.append(source)
        # A complete enumeration proves which owned checkpoints are stale; foreign backfill
        # checkpoints belong to a separate lifecycle.
        for state_key in list(next_files):
            if state_key.startswith(f"{agent_id}:") and state_key not in known_state_keys:
                del next_files[state_key]
    from functools import cmp_to_key

    from memory_core.bootstrap._js import locale_compare

    def compare(left: SessionIngestionSource, right: SessionIngestionSource) -> int:
        if left.agent_id != right.agent_id:
            return locale_compare(left.agent_id, right.agent_id)
        return locale_compare(left.session_path, right.session_path)

    sorted_sources = sorted(sources, key=cmp_to_key(compare))
    total_cap = SESSION_INGESTION_MAX_MESSAGES_PER_SWEEP
    remaining = total_cap
    per_file_cap = min(
        SESSION_INGESTION_MAX_MESSAGES_PER_FILE,
        max(SESSION_INGESTION_MIN_MESSAGES_PER_FILE, -(-total_cap // max(1, len(sorted_sources)))),
    )
    for source in sorted_sources:
        if remaining <= 0:
            break
        file_cap = max(1, min(per_file_cap, remaining))
        scan = scan_session_ingestion_source(
            source=source,
            previous=state.files.get(source.state_key),
            seen_messages=next_seen,
            timezone=timezone,
            max_candidates=file_cap,
            classify_day=lambda day: "include" if is_day_within_lookback(day, cutoff) else "skip",
            build_entry=lambda src: build_session_file_entry(
                src, redact_text=redact_text, runtime_identity=runtime_identity
            ),
        )
        if scan.status == "absent":
            next_files.pop(source.state_key, None)
            continue
        if scan.file_state is not None:
            next_files[source.state_key] = scan.file_state
        if scan.status != "scanned":
            continue
        for candidate in scan.candidates:
            batch_by_day.setdefault(candidate.day, []).append(candidate)
        if scan.candidates:
            next_seen[source.scope] = merge_tracked_message_hashes(
                next_seen.get(source.scope, []), [candidate.hash for candidate in scan.candidates]
            )
            remaining -= len(scan.candidates)
    trimmed_seen = trim_tracked_session_scopes(next_seen)
    batches: list[SessionIngestionBatch] = []
    for day in sorted(batch_by_day):
        day_lines = batch_by_day[day]
        if not day_lines:
            continue
        results = append_session_corpus_lines(workspace_dir=workspace_dir, day=day, lines=day_lines)
        if results:
            batches.append(SessionIngestionBatch(day, results))
    next_state = SessionIngestionState(next_files, trimmed_seen)
    return SessionIngestionCollection(
        batches, next_state, json.dumps(next_state.to_json()) != json.dumps(state.to_json())
    )


def ingest_session_transcript_signals(
    *,
    config: MemoryConfig,
    agent_ids: Sequence[str] | None,
    corpus_entries: Callable[[str], Iterable[SessionCorpusEntry]],
    lookback_days: float,
    now_ms: int,
    timezone: str | None = None,
    admission_policy: SessionAdmissionPolicy | None = None,
    origins: MemoryEntryOriginLedger | None = None,
    load_session_metadata: MetadataLoader | None = None,
    redact_text: Callable[[str], str] | None = None,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> SessionIngestionCollection:
    """``ingestSessionTranscriptSignals``: record each day's new transcript messages as ``daily`` signals."""
    from memory_core.consolidation.promotion import format_memory_dreaming_day

    workspace = Path(config.workspace_dir)
    with workspace_file_lock(workspace.resolve(), INGESTION_LOCK_NAME):
        state = read_session_ingestion_state(workspace)
        collected = collect_session_ingestion_batches(
            workspace_dir=workspace,
            agent_ids=agent_ids,
            corpus_entries=corpus_entries,
            lookback_days=lookback_days,
            now_ms=now_ms,
            timezone=timezone,
            state=state,
            admission_policy=admission_policy,
            origins=origins,
            load_session_metadata=load_session_metadata,
            redact_text=redact_text,
            runtime_identity=runtime_identity,
        )
        ingestion_day = format_memory_dreaming_day(now_ms, timezone)
        for batch in collected.batches:
            record_short_term_recalls(
                config=config,
                query=f"__dreaming_sessions__:{batch.day}",
                results=batch.results,
                now_ms=now_ms,
                signal_type="daily",
                dedupe_by_query_per_day=True,
                day_bucket=ingestion_day,
                timezone=timezone,
                origins=origins,
                on_event=on_event,
            )
        if collected.changed:
            write_session_ingestion_state(workspace, collected.next_state)
    return collected


__all__ = [
    "SessionAdmissionPolicy",
    "SessionCorpusEntry",
    "SessionIngestionSource",
    "append_session_corpus_lines",
    "collect_session_ingestion_batches",
    "ingest_session_transcript_signals",
    "normalize_memory_day",
    "read_session_ingestion_state",
    "resolve_admission_policy",
    "scan_session_ingestion_source",
    "session_exclusion_reason",
    "write_session_ingestion_state",
]
