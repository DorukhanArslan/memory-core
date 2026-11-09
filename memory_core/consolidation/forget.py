"""Memory forget: purge what a set of sessions left in memory, and tombstone them.

Port of ``forgetMemoryEntries`` and its helpers (OpenClaw v2026.9.6:
``extensions/memory-core/src/memory-forget.ts``, ``memory-forget-index-sources.ts``,
``memory-forget-curated-writes.ts``, ``memory-forget-report.ts``, ``memory-session-tombstones.ts`` and
``resolveMemorySessionTargets`` of ``src/plugin-sdk/memory-core-host-engine-sessions.ts``).

``forget_memory_entries`` selects sessions (ids or session keys, hook sources, participants, a
``since`` date), then:

1. plans the purge: the origin rows of the selected sessions name the promoted MEMORY.md entries to
   delete whole (an entry that other sessions also contributed to is reported as ``mixedLineage`` and
   deleted whole all the same); the session corpus lines that point at the sessions, the memory
   files' sections that mention them (headings and ``Session ID:`` rows), the recall entries whose
   path or snippet reference them, their phase signals, the session-ingestion checkpoints and
   seen-message scopes, the consolidation preimages (rewritten, their hash recomputed) and the index
   chunks and sources of every rewritten file (and of the sessions' own transcripts);
2. (``dry_run=False``) writes the tombstones and fences the index in one guarded transaction
   (:meth:`~memory_core.consolidation.origins.MemoryEntryOriginLedger.record_session_tombstones_if_lineage_current`:
   a lineage that changed since the plan makes the flow plan again), purges the index, then the phase
   signals, the recall store, the session-ingestion checkpoint and the preimages, commits the file
   rewrites (each checked against the content it was planned on) and finally deletes the origin rows;
   a tombstone is a promise that survives a failed purge, so a retry finishes the job. Everything runs
   under the workspace lock. Tombstoned sessions are never ingested again
   (:mod:`memory_core.consolidation.session_ingestion`), their recalls are dropped
   (:func:`~memory_core.consolidation.recall.record_short_term_recalls`) and a rebuild of the index
   that started before the forget fails at publication (``SQLiteMemoryStore.reindex`` with a
   ``revision_fence``).

The result is a :class:`MemoryForgetReport` (``to_json`` has upstream's field names). Deviations, each
forced by the package's host-injected design: the host supplies the session facts
(``instances`` and ``archives`` for the selectors, ``corpus_entries`` for the transcripts to
inspect: ``curatedWrites``, the excluded sessions); the state upstream keeps in SQLite plugin state is
the JSON files of this package; the index is the package's :class:`SQLiteMemoryStore` (chunks, a path
table, FTS, private source state and the persistent embedding cache). Native v2026.9.9 clears the
whole embedding cache for a selected session forget because cached vectors carry no source lineage;
the same policy applies here, including cache-only rows from an uncompleted index publication.
There is no separate vector table, so ``vectorRows`` remains 0, and chunk provenance cannot select
system-origin chunks; the origin ledger check before the index purge is a second read, not one transaction with it;
the memory files are listed with the package's ``list_memory_files`` plus the DREAMS files.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cmp_to_key
from contextlib import closing
from pathlib import Path
from typing import Any

from memory_core.atomic_publication import (
    MemoryWriteConflictError as MemoryWriteConflictError,
    commit_memory_content as _publish_memory_content,
    hash_memory_content as _hash_memory_content,
)
from memory_core.bootstrap._js import (
    JS_IU_WORD_CLASS,
    JS_SPACE_CLASS,
    js_iu_keyword_pattern,
    js_json_stringify,
    js_trim,
    js_trim_end,
    js_utf8_encode,
    locale_compare,
    utf16_len,
)
from memory_core.config import MemoryConfig
from memory_core.consolidation._util import iso_ms, write_json_atomic
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.consolidation.artifacts import DREAMS_FILENAMES, preimage_path, read_memory_preimages
from memory_core.consolidation.daily_ingestion import INGESTION_LOCK_NAME
from memory_core.consolidation.markers import PROMOTION_MARKER_PREFIXES
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger
from memory_core.consolidation.session_ingestion import (
    SESSION_CORPUS_RELATIVE_DIR,
    SessionCorpusEntry,
    SessionIngestionState,
    read_session_ingestion_state,
    write_session_ingestion_state,
)
from memory_core.consolidation.store import (
    memory_workspace_lock,
    phase_signal_store_path,
    read_phase_signal_store,
    read_recall_store,
    recall_store_lock,
    recall_store_path,
)
from memory_core.project_name import DIST_NAME
from memory_core.index.identity import INDEX_SOURCES_TABLE, INDEX_SYNC_TABLE
from memory_core.session_artifacts import parse_usage_counted_session_id_from_file_name
from memory_core.session_entry import (
    SessionEntry,
    build_session_entry,
    is_cron_run_session_key,
    is_dreaming_narrative_session_store_key,
    js_date_parse,
    parse_jsonl_records,
)
from memory_core.workspace import list_memory_files, workspace_file_lock

FORGET_MAX_ATTEMPTS = 16

_S = JS_SPACE_CLASS
_NOT_LINE_END = "[^\\n\\r\\u2028\\u2029]"
_PREFIXES = "|".join(re.escape(prefix) for prefix in PROMOTION_MARKER_PREFIXES)
PROMOTION_MARKER = re.compile(rf"^[{_S}]*<!--[{_S}]*(?:{_PREFIXES})([^\n]*?)[{_S}]*-->[{_S}]*\Z")
_LINEAGE_PREFIXES = "|".join(re.escape(p) for p in (f"{DIST_NAME}-memory-lineage:", "openclaw-memory-lineage:"))
LINEAGE_MARKER = re.compile(rf"^[{_S}]*<!--[{_S}]*(?:{_LINEAGE_PREFIXES})[^\n]*?-->[{_S}]*\Z")
_CONTINUATION_LINE = re.compile(rf"^[{_S}]+[^{_S}]")
_HEADING = re.compile(r"^(#{1,6})" + f"[{_S}]")
_ROW_INDENT = re.compile(rf"^([{_S}]*)[-*+][{_S}]")
_SESSION_ID_ROW_RE = re.compile(
    rf"(?<![{JS_IU_WORD_CLASS}]){js_iu_keyword_pattern('Session ID')}:[{_S}]*([^;{_S}]+)"
)
_CORPUS_SNIPPET_RE = re.compile(rf"^\[[^\]]+#L[0-9]+\][{_S}]*({_NOT_LINE_END}+)\Z")
_CORPUS_FILE_RE = re.compile(r"\.(?:txt|md)\Z", re.IGNORECASE | re.ASCII)
_CONSOLIDATION_HISTORY_RE = re.compile(
    r"^## Memory Consolidation History\r?$[\s\S]*^ {2}- `[+-] ", re.MULTILINE
)
_SPLIT_LINES = re.compile(r"\r?\n")


# --- selectors and targets -----------------------------------------------------------------


@dataclass(frozen=True)
class SessionInstance:
    """A session the host knows (upstream: a ``SessionTranscriptInstance`` of the SQLite session store)."""

    agent_id: str
    session_id: str
    session_key: str
    created_at: float
    hook_external_content_source: str | None = None
    channel: str | None = None
    account_id: str | None = None
    chat_type: str | None = None
    participants: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class SessionArchive:
    """A retained transcript archive (``loadArchivedSessions``)."""

    session_id: str
    session_key: str
    created_at: float


@dataclass(frozen=True)
class MemorySessionTarget:
    """``MemorySessionTarget``: a session selected for forgetting."""

    agent_id: str
    session_id: str
    resolution: str  # "live" | "archived" | "unresolved"
    session_key: str | None = None
    hook_external_content_source: str | None = None
    channel: str | None = None
    account_id: str | None = None
    chat_type: str | None = None
    created_at: float | None = None
    participants: tuple[Mapping[str, Any], ...] = ()


def _normalize_agent_id(value: str) -> str:
    return js_trim(value).lower()


def resolve_memory_session_targets(
    agent_id: str,
    *,
    session_ids: Sequence[str] = (),
    hook_sources: Sequence[str] = (),
    participants: Sequence[str] = (),
    since: str | float | None = None,
    instances: Sequence[SessionInstance] = (),
    archives: Sequence[SessionArchive] = (),
) -> list[MemorySessionTarget]:
    """``resolveMemorySessionTargets``: the selectors resolved against the host's sessions.

    A live session matches by id or key, by hook source or by participant id; a retained archive by
    session id; a session id nobody knows becomes an ``unresolved`` target (its tombstone still
    protects the future). ``since`` (an ISO date string or milliseconds) drops sessions created
    before it.
    """
    wanted_ids = list(dict.fromkeys(session_ids))
    wanted_sources = list(dict.fromkeys(hook_sources))
    wanted_participants = list(dict.fromkeys(participants))
    if not wanted_ids and not wanted_sources and not wanted_participants:
        return []
    since_ms: float | None
    if isinstance(since, str):
        since_ms = js_date_parse(since)
    else:
        since_ms = since
    if since_ms is not None and not math.isfinite(since_ms):
        raise ValueError(f"Invalid memory session date: {since}")
    resolved_selectors: set[str] = set()
    targets: dict[str, MemorySessionTarget] = {}

    def compare(left: SessionInstance, right: SessionInstance) -> int:
        if left.created_at != right.created_at:
            return -1 if left.created_at < right.created_at else 1
        return locale_compare(left.session_id, right.session_id)

    mine = [i for i in instances if _normalize_agent_id(i.agent_id) == _normalize_agent_id(agent_id)]
    for instance in sorted(mine, key=cmp_to_key(compare)):
        identities = list(instance.participants)
        source = instance.hook_external_content_source
        if (
            instance.session_id not in wanted_ids
            and instance.session_key not in wanted_ids
            and not (source and source in wanted_sources)
            and not any(identity.get("id") in wanted_participants for identity in identities)
        ):
            continue
        resolved_selectors.update((instance.session_id, instance.session_key))
        if since_ms is None or instance.created_at >= since_ms:
            targets[instance.session_id] = MemorySessionTarget(
                agent_id=instance.agent_id,
                session_id=instance.session_id,
                session_key=instance.session_key,
                resolution="live",
                hook_external_content_source=instance.hook_external_content_source,
                channel=instance.channel,
                account_id=instance.account_id,
                chat_type=instance.chat_type,
                created_at=instance.created_at,
                participants=tuple(identities),
            )
    for archive in archives:
        if archive.session_id not in wanted_ids:
            continue
        resolved_selectors.update((archive.session_id, archive.session_key))
        if archive.session_id in targets or (since_ms is not None and archive.created_at < since_ms):
            continue
        targets[archive.session_id] = MemorySessionTarget(
            agent_id=agent_id,
            session_id=archive.session_id,
            session_key=archive.session_key,
            resolution="archived",
            created_at=archive.created_at,
        )
    for session_id in wanted_ids:
        if session_id not in resolved_selectors:
            targets[session_id] = MemorySessionTarget(
                agent_id=agent_id, session_id=session_id, resolution="unresolved"
            )
    return list(targets.values())


# --- the report ----------------------------------------------------------------------------


@dataclass
class MemoryForgetReport:
    """``MemoryForgetReport`` (``to_json`` uses upstream's field names)."""

    agent_id: str
    dry_run: bool
    session_ids: list[str]
    participant_matches: list[dict[str, Any]]
    session_resolutions: list[dict[str, Any]]
    entry_keys: list[str]
    mixed_lineage_entry_keys: list[str]
    untargetable_entry_keys: list[str]
    curated_writes: list[dict[str, Any]]
    artifacts: dict[str, int]
    refusals: list[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "agentId": self.agent_id,
            "dryRun": self.dry_run,
            "sessionIds": self.session_ids,
            "participantMatches": self.participant_matches,
            "sessionResolutions": self.session_resolutions,
            "entryKeys": self.entry_keys,
            "mixedLineageEntryKeys": self.mixed_lineage_entry_keys,
            "untargetableEntryKeys": self.untargetable_entry_keys,
            "curatedWrites": self.curated_writes,
            "artifacts": self.artifacts,
            "refusals": self.refusals,
        }


def _utf16_key(value: str) -> bytes:
    return value.encode("utf-16-be", "surrogatepass")


def summarize_participant_matches(
    targets: Sequence[MemorySessionTarget], participants: Sequence[str] | None
) -> list[dict[str, Any]]:
    """``summarizeParticipantMatches``."""
    out = []
    for actor_id in sorted(dict.fromkeys(participants or ()), key=_utf16_key):
        identities: dict[str, Mapping[str, Any]] = {}
        for target in targets:
            for identity in target.participants:
                if identity.get("id") == actor_id:
                    identities.setdefault(js_json_stringify(dict(identity)), identity)
        out.append({"actorId": actor_id, "identities": [dict(i) for i in identities.values()]})
    return out


# --- text helpers --------------------------------------------------------------------------


def references_session(value: str, agent_id: str, session_ids: Iterable[str]) -> bool:
    """``referencesSession``: does ``value`` name one of the sessions of ``agent_id``?

    A path or scope such as ``sessions/<agent>/<id>[.jsonl[.reset.<stamp>]]`` or ``<agent>:<id>``, or a
    ``Session ID: <id>`` row; archive file names decode with the owner's grammar.
    """
    wanted = set(session_ids)
    agent = re.escape(agent_id)
    references = re.compile(
        rf"(?:^|[{_S}\[/:])(?:sessions/{agent}/|{agent}:(?!sessions/))([^{_S}\]#;:/]+)"
    )
    for match in references.finditer(value):
        reference = match.group(1)
        decoded = parse_usage_counted_session_id_from_file_name(reference)
        if (decoded if decoded is not None else reference) in wanted:
            return True
    return any(match.group(1) in wanted for match in _SESSION_ID_ROW_RE.finditer(value))


@dataclass
class _Scrubbed:
    content: str
    removed_entries: int
    removed_lines: int


def scrub_memory_content(
    *,
    content: str,
    entry_keys: set[str],
    session_ids: set[str],
    corpus_snippets: set[str],
    agent_id: str,
) -> _Scrubbed:
    """``scrubMemoryContent``: remove the promoted entries, corpus quotes and session sections."""
    lines = content.split("\n")
    snippets = list(corpus_snippets)
    removed_entries = 0
    removed_lines = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        marker = PROMOTION_MARKER.match(line)
        marker_key = js_trim(marker.group(1)) if marker else None
        if marker_key and marker_key in entry_keys:
            start = index - 1 if index > 0 and LINEAGE_MARKER.match(lines[index - 1]) else index
            end = index + 1
            if end < len(lines) and not PROMOTION_MARKER.match(lines[end]):
                end += 1
                while end < len(lines) and _CONTINUATION_LINE.match(lines[end]):
                    end += 1
            del lines[start:end]
            removed_entries += 1
            index = start
            continue
        if any(snippet in line for snippet in snippets):
            del lines[index]
            removed_lines += 1
            continue
        if not references_session(line, agent_id, session_ids):
            index += 1
            continue
        heading = _HEADING.match(line)
        row_indent_match = _ROW_INDENT.match(line)
        row_indent = len(row_indent_match.group(1)) if row_indent_match else None
        if not heading and not _SESSION_ID_ROW_RE.search(line):
            index += 1
            continue
        end = index + 1
        while end < len(lines):
            next_line = lines[end]
            next_heading = _HEADING.match(next_line)
            first_non_space = re.search(rf"[^{_S}]", next_line)
            indent_of_next = first_non_space.start() if first_non_space else -1
            if (
                (row_indent is not None and indent_of_next <= row_indent)
                or (next_heading and (not heading or len(next_heading.group(1)) <= len(heading.group(1))))
                or _SESSION_ID_ROW_RE.search(next_line)
            ):
                break
            end += 1
        del lines[index:end]
        removed_entries += 1
    return _Scrubbed("\n".join(lines), removed_entries, removed_lines)


def collect_transcript_writes(
    *,
    message: object,
    observed_at: int,
    workspace_dir: str | Path,
    writes: dict[str, dict[str, Any]],
) -> None:
    """``collectTranscriptWrites``: memory files the session's ``write``/``edit``/``apply_patch`` calls touched."""
    if not isinstance(message, Mapping) or message.get("role") != "assistant":
        return
    content = message.get("content")
    if not isinstance(content, list):
        return
    workspace = os.path.abspath(workspace_dir)
    for item in content:
        if not isinstance(item, Mapping):
            continue
        if item.get("type") not in ("toolCall", "tool_call", "tool_use") or item.get("name") not in (
            "apply_patch",
            "write",
            "edit",
        ):
            continue
        raw_arguments = item.get("arguments")
        if raw_arguments is None:
            raw_arguments = item.get("input")
        if isinstance(raw_arguments, str):
            try:
                raw_arguments = json.loads(raw_arguments)
            except ValueError:
                raw_arguments = {"input": raw_arguments} if item.get("name") == "apply_patch" else None
        args = raw_arguments if isinstance(raw_arguments, Mapping) else None
        if args is None:
            continue
        candidates: list[Any] = [args.get("path"), args.get("file_path"), args.get("filePath")]
        if item.get("name") == "apply_patch":
            patch = args.get("input") if isinstance(args.get("input"), str) else args.get("patch")
            if isinstance(patch, str):
                for match in re.finditer(
                    r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (.+)$", patch, re.MULTILINE
                ):
                    candidates.append(match.group(1))
            changes = args.get("changes")
            if isinstance(changes, list):
                for change in changes:
                    if isinstance(change, Mapping):
                        kind = change.get("kind")
                        candidates.append(change.get("path"))
                        candidates.append(kind.get("move_path") if isinstance(kind, Mapping) else None)
            elif isinstance(changes, Mapping):
                candidates.extend(changes.keys())
        cwd = args.get("cwd") if isinstance(args.get("cwd"), str) else workspace
        for candidate in candidates:
            if not isinstance(candidate, str) or not js_trim(candidate):
                continue
            absolute = os.path.normpath(os.path.join(workspace, cwd, candidate))
            relative = os.path.relpath(absolute, workspace)
            if relative == ".." or relative.startswith(".." + os.sep) or os.path.isabs(relative):
                continue
            relative = relative.replace("\\", "/")
            if (
                relative in ("MEMORY.md", "USER.md") or relative.startswith("memory/")
            ) and relative not in writes:
                writes[relative] = {"relativePath": relative, "observedAt": observed_at}


# --- the index -----------------------------------------------------------------------------


@dataclass
class IndexPlan:
    """``ForgetIndexPlan`` over index rows and unattributed embedding-cache state."""

    chunks: list[tuple[str, str, str]] = field(default_factory=list)  # (id, path, source)
    sources: list[tuple[str, str]] = field(default_factory=list)  # (path, source)
    fts_rows: int = 0
    embedding_cache_rows: int = 0
    purge_cache: bool = False


def _index_table_exists(db: Any, table: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def plan_memory_index(
    store: Any,
    *,
    agent_id: str,
    changed_paths: set[str],
    removed_paths: set[str],
    session_ids: set[str],
    excluded_session_ids: set[str],
    matches_memory: Callable[[str], bool],
) -> IndexPlan:
    """``planMemoryIndex``: indexed sources and cache rows selected for a purge."""
    if store is None:
        return IndexPlan()
    with closing(store.connect()) as db:
        rows = db.execute("SELECT id, path, source, text FROM chunks").fetchall()
        changed = set(changed_paths)
        # Another workspace agent may already have scrubbed the shared file; its remaining indexed
        # snapshot still owns evidence for this agent's purge.
        for _id, path, source, text in rows:
            if source == "memory" and matches_memory(text):
                changed.add(path)
        chunks = [
            (chunk_id, path, source)
            for chunk_id, path, source, _text in rows
            if path in changed
            or references_session(path, agent_id, session_ids)
            or (
                bool(session_ids)
                and source == "sessions"
                and references_session(path, agent_id, excluded_session_ids)
            )
        ]
        removed_session_paths = {path for _id, path, source in chunks if source == "sessions"}
        sources = [
            (path, source)
            for path, source in db.execute("SELECT path, source FROM paths_fts").fetchall()
            if path in removed_paths or (source == "sessions" and path in removed_session_paths)
        ]
        ids = [chunk_id for chunk_id, _path, _source in chunks]
        fts_rows = 0
        for start in range(0, len(ids), 500):
            batch = ids[start : start + 500]
            fts_rows += db.execute(
                f"SELECT COUNT(*) FROM chunks_fts WHERE id IN ({','.join('?' * len(batch))})", batch
            ).fetchone()[0]
        cache_rows = 0
        if session_ids and _index_table_exists(db, "memory_embedding_cache"):
            cache_rows = db.execute("SELECT COUNT(*) FROM memory_embedding_cache").fetchone()[0]
    return IndexPlan(chunks, sources, fts_rows, cache_rows, bool(session_ids))


def purge_memory_index(store: Any, plan: IndexPlan) -> bool:
    """Purge index rows and unattributed cache vectors in one transaction.

    A selected session forget clears the live cache even when its planned count
    is zero: an in-flight provider may have populated it after the plan. Advancing
    the private index generation prevents an older refresh from restoring those
    vectors or publishing chunks prepared before this purge.
    """
    if store is None or (not plan.chunks and not plan.sources and not plan.purge_cache):
        return False
    with closing(store.connect()) as db, db:
        # Own the write lock before clearing derived state and fencing its
        # next publisher. Older external stores need neither private table.
        db.execute("BEGIN IMMEDIATE")
        ids = [chunk_id for chunk_id, _path, _source in plan.chunks]
        for start in range(0, len(ids), 500):
            batch = ids[start : start + 500]
            marks = ",".join("?" * len(batch))
            db.execute(f"DELETE FROM chunks WHERE id IN ({marks})", batch)
            db.execute(f"DELETE FROM chunks_fts WHERE id IN ({marks})", batch)
        for path, source in plan.sources:
            db.execute("DELETE FROM paths_fts WHERE path = ? AND source = ?", (path, source))
        if _index_table_exists(db, INDEX_SOURCES_TABLE):
            affected = {*plan.sources, *((path, source) for _id, path, source in plan.chunks)}
            for path, source in affected:
                db.execute(
                    f"DELETE FROM {INDEX_SOURCES_TABLE} WHERE source = ? AND path = ?",
                    (source, path),
                )
        if plan.purge_cache and _index_table_exists(db, "memory_embedding_cache"):
            db.execute("DELETE FROM memory_embedding_cache")
        if _index_table_exists(db, INDEX_SYNC_TABLE):
            db.execute(
                f"UPDATE {INDEX_SYNC_TABLE} SET revision = revision + 1, "
                "needs_rebuild = 1 WHERE id = 1"
            )
    return True


# --- files ---------------------------------------------------------------------------------


def hash_memory_content(content: str) -> str:
    return hashlib.sha256(js_utf8_encode(content)).hexdigest()


def commit_memory_content(path: Path, *, expected_content: str, content: str | None, label: str) -> None:
    """``commitMemoryContent``: replace (or, with ``None``, remove) a file only if it still holds ``expected_content``."""
    _publish_memory_content(path, expected_content=expected_content, expected_hash=_hash_memory_content(expected_content),
                            content=content, temp_prefix=f".{path.name}.forget",
                            conflict_message=f"{label} changed before the memory forget rewrite could commit")


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace")


@dataclass
class _Rewrite:
    absolute_path: Path
    relative_path: str
    content: str
    remove: bool
    expected_content: str


# --- the flow ------------------------------------------------------------------------------


def _is_memory_session_indexable(
    *, generated_by_dreaming_narrative: bool, generated_by_cron_run: bool, session_kind: str | None,
    session_key: str | None = None, line_provenance: Sequence[Mapping[str, Any]] | None = None
) -> bool:
    """``isMemorySessionIndexable``."""
    if generated_by_dreaming_narrative or generated_by_cron_run or session_kind in ("cron", "heartbeat"):
        return False
    if session_key is not None and (
        is_dreaming_narrative_session_store_key(session_key)
        or is_cron_run_session_key(session_key)
        or session_key.endswith(":heartbeat")
    ):
        return False
    return not (
        line_provenance is not None
        and len(line_provenance) > 0
        and all(line.get("originClass") == "system" for line in line_provenance)
    )


def _selected_lineage_identity(
    origins: Sequence[MemoryEntryOrigin], session_ids: set[str], entry_keys: set[str]
) -> str:
    return json.dumps(
        [[o.entry_key, o.session_id] for o in origins if o.session_id in session_ids or o.entry_key in entry_keys]
    )


def _build_corpus_entry(
    entry: SessionCorpusEntry, on_message: Callable[[object, int], None] | None
) -> SessionEntry | None:
    try:
        info = os.stat(entry.session_file)
        text = Path(entry.session_file).read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None
    seconds, nanos = divmod(info.st_mtime_ns, 1_000_000_000)
    sqlite = entry.transcript_source == "sqlite"
    return build_session_entry(
        records=parse_jsonl_records(text),
        mtime_ms=seconds * 1000 + nanos / 1e6,
        session_kind=entry.session_kind or "unknown",
        generated_by_dreaming_narrative=bool(entry.generated_by_dreaming_narrative),
        generated_by_cron_run=bool(entry.generated_by_cron_run),
        reset_recall_cutoff=None if sqlite else {"state": "absent"},
        on_transcript_message=on_message,
    )


@dataclass
class _Context:
    targets: list[MemorySessionTarget]
    origins: list[MemoryEntryOrigin] | None = None
    selected_entry_keys: set[str] = field(default_factory=set)
    tombstoned: bool = False


def forget_memory_entries(
    *,
    config: MemoryConfig,
    agent_id: str,
    origins: MemoryEntryOriginLedger,
    session_ids: Sequence[str] | None = None,
    hook_sources: Sequence[str] | None = None,
    participants: Sequence[str] | None = None,
    since: str | float | None = None,
    instances: Sequence[SessionInstance] = (),
    archives: Sequence[SessionArchive] = (),
    corpus_entries: Callable[[str], Iterable[SessionCorpusEntry]] | None = None,
    artifact_provenance: MemoryArtifactProvenanceStore | None = None,
    store: Any = None,
    dry_run: bool = False,
    now_ms: int | None = None,
) -> MemoryForgetReport:
    """``forgetMemoryEntries``: purge the selected sessions' memory, tombstone them, report what changed.

    Needs at least one of ``session_ids`` (ids or session keys), ``hook_sources`` and ``participants``
    (``ValueError`` otherwise). ``store`` is the package's index: its chunks and path rows of the
    rewritten files are purged (and, with a ``revision_fence``, the revision moves so a rebuild prepared
    before the forget fails at publication); the caller reindexes afterwards to bring the rewritten files
    back. ``dry_run`` plans and reports without touching anything.
    """
    if not session_ids and not hook_sources and not participants:
        raise ValueError("memory forget requires a session, hook source, or participant selector")
    workspace = Path(config.workspace_dir)
    targets = resolve_memory_session_targets(
        agent_id,
        session_ids=session_ids or (),
        hook_sources=hook_sources or (),
        participants=participants or (),
        since=since,
        instances=instances,
        archives=archives,
    )
    context = _Context(targets)

    def run() -> MemoryForgetReport:
        for _attempt in range(FORGET_MAX_ATTEMPTS):
            report = _forget_workspace_memory(
                config=config,
                workspace=workspace,
                agent_id=agent_id,
                ledger=origins,
                participants=participants,
                corpus_entries=corpus_entries,
                artifact_provenance=artifact_provenance,
                store=store,
                dry_run=dry_run,
                now_ms=now_ms if now_ms is not None else int(time.time() * 1000),
                context=context,
            )
            if report is not None:
                return report
        raise RuntimeError("memory forget could not settle: the origin lineage kept changing")

    if dry_run:
        return run()
    # Replanning keeps the workspace owner; the recall store and the ingestion checkpoint are held
    # for the whole run (upstream's workspace lock covers them: recordings and ingestion wait).
    with (
        memory_workspace_lock(workspace),
        workspace_file_lock(workspace.resolve(), INGESTION_LOCK_NAME),
        recall_store_lock(workspace),
    ):
        return run()


def _forget_workspace_memory(
    *,
    config: MemoryConfig,
    workspace: Path,
    agent_id: str,
    ledger: MemoryEntryOriginLedger,
    participants: Sequence[str] | None,
    corpus_entries: Callable[[str], Iterable[SessionCorpusEntry]] | None,
    artifact_provenance: MemoryArtifactProvenanceStore | None,
    store: Any,
    dry_run: bool,
    now_ms: int,
    context: _Context,
) -> MemoryForgetReport | None:
    targets = context.targets
    session_ids = {target.session_id for target in targets}
    all_origins = context.origins if context.origins is not None else ledger.list(agent_id)
    for origin in all_origins:
        if origin.session_id in session_ids:
            context.selected_entry_keys.add(origin.entry_key)
    entry_keys = set(context.selected_entry_keys)
    lineage_identity = _selected_lineage_identity(all_origins, session_ids, entry_keys)
    all_origin_keys = {*entry_keys, *(o.entry_key for o in all_origins)}
    mixed_lineage = {
        o.entry_key for o in all_origins if o.entry_key in entry_keys and o.session_id not in session_ids
    }
    untargetable: set[str] = set()
    refusals: list[str] = []
    corpus_dir = workspace / SESSION_CORPUS_RELATIVE_DIR

    corpus_rewrites: list[_Rewrite] = []
    corpus_snippets: set[str] = set()
    removed_corpus_lines = 0
    try:
        corpus_files = sorted(
            entry.name for entry in os.scandir(corpus_dir) if entry.is_file(follow_symlinks=False)
        )
    except (FileNotFoundError, NotADirectoryError):
        corpus_files = []
    for name in corpus_files:
        if not _CORPUS_FILE_RE.search(name):
            continue
        absolute = corpus_dir / name
        content = _read_text(absolute)
        lines = content.split("\n")
        retained: list[str] = []
        for line in lines:
            if not references_session(line, agent_id, session_ids):
                retained.append(line)
                continue
            snippet_match = _CORPUS_SNIPPET_RE.match(js_trim_end(line))
            snippet = js_trim(snippet_match.group(1)) if snippet_match else None
            # Ingestion only admits snippets of at least 12 characters; shorter malformed corpus rows
            # must never trigger broad substring deletion.
            if snippet and utf16_len(snippet) >= 12:
                corpus_snippets.add(snippet)
        if len(retained) != len(lines):
            removed_corpus_lines += len(lines) - len(retained)
            rewritten = "\n".join(retained)
            corpus_rewrites.append(
                _Rewrite(
                    absolute,
                    absolute.relative_to(workspace).as_posix(),
                    rewritten,
                    not js_trim(rewritten),
                    content,
                )
            )

    def scrub(content: str) -> _Scrubbed:
        return scrub_memory_content(
            content=content,
            entry_keys=entry_keys,
            session_ids=session_ids,
            corpus_snippets=corpus_snippets,
            agent_id=agent_id,
        )

    memory_rewrites: list[_Rewrite] = []
    removed_memory_entries = 0
    removed_memory_lines = 0
    memory_files = list(list_memory_files(workspace))
    seen_paths = {os.path.realpath(p) for p in memory_files}
    for name in DREAMS_FILENAMES:
        candidate = workspace / name
        if candidate.is_file() and not candidate.is_symlink() and os.path.realpath(candidate) not in seen_paths:
            seen_paths.add(os.path.realpath(candidate))
            memory_files.append(candidate)
    for absolute in memory_files:
        # Corpus evidence must survive until every dependent artifact is clean.
        if absolute.parent == corpus_dir:
            continue
        content = _read_text(absolute)
        for line in _SPLIT_LINES.split(content):
            marker = PROMOTION_MARKER.match(line)
            key = js_trim(marker.group(1)) if marker else None
            if key and key not in all_origin_keys:
                untargetable.add(key)
        scrubbed = scrub(content)
        if _CONSOLIDATION_HISTORY_RE.search(scrubbed.content):
            refusals.append(
                f"Cannot trace historical consolidation highlights in {absolute.relative_to(workspace).as_posix()}; "
                "review them manually."
            )
        if scrubbed.content != content:
            memory_rewrites.append(
                _Rewrite(absolute, absolute.relative_to(workspace).as_posix(), scrubbed.content, False, content)
            )
            removed_memory_entries += scrubbed.removed_entries
            removed_memory_lines += scrubbed.removed_lines

    now_iso = iso_ms(now_ms)
    recall_path = recall_store_path(workspace)
    recall_store = read_recall_store(recall_path, now_ms)
    short_term_entries = [(key, value) for key, value in recall_store["entries"].items() if isinstance(value, dict)]
    phase_signals = read_phase_signal_store(phase_signal_store_path(workspace), now_ms)
    ingestion_state = read_session_ingestion_state(workspace)
    backups = read_memory_preimages(workspace)
    provenance_records = artifact_provenance.list(workspace) if artifact_provenance is not None else []
    session_keys = {target.session_key for target in targets}
    curated_writes: dict[str, dict[str, Any]] = {}
    for relative_path, record in provenance_records:
        if (
            record.session_id in session_ids
            if record.session_id
            else bool(record.session_key and record.session_key in session_keys)
        ):
            curated_writes[relative_path] = {"relativePath": relative_path, "observedAt": record.observed_at}

    def reference_text(value: dict[str, Any]) -> str:
        return f"{value.get('path')}\n{value.get('snippet')}"

    retained_short_term = []
    removed_short_term_keys: set[str] = set()
    for key, value in short_term_entries:
        if (
            key not in entry_keys
            and value.get("key") not in entry_keys
            and not references_session(reference_text(value), agent_id, session_ids)
        ):
            retained_short_term.append((key, value))
        else:
            removed_short_term_keys.add(key)
            if isinstance(value.get("key"), str):
                removed_short_term_keys.add(value["key"])
    removed_phase_signal_keys = [
        key
        for key in phase_signals["entries"]
        if key in entry_keys or key in removed_short_term_keys
    ]
    retained_seen = {
        scope: hashes
        for scope, hashes in ingestion_state.seen_messages.items()
        if not references_session(scope, agent_id, session_ids)
    }
    removed_seen_scopes = len(ingestion_state.seen_messages) - len(retained_seen)
    retained_file_states = {
        key: value
        for key, value in ingestion_state.files.items()
        if not references_session(key, agent_id, session_ids)
    }
    rewritten_backups = 0
    next_backups: list[dict[str, Any]] = []
    for backup in backups:
        scrubbed = scrub(str(backup.get("content", "")))
        if scrubbed.content == backup.get("content"):
            next_backups.append(backup)
            continue
        rewritten_backups += 1
        next_backups.append({**backup, "content": scrubbed.content, "contentHash": hash_memory_content(scrubbed.content)})

    excluded_session_ids: set[str] = set()
    for entry in corpus_entries(agent_id) if corpus_entries is not None else ():
        selected = entry.session_id in session_ids
        indexable = _is_memory_session_indexable(
            generated_by_dreaming_narrative=entry.generated_by_dreaming_narrative,
            generated_by_cron_run=entry.generated_by_cron_run,
            session_kind=entry.session_kind,
        )
        if not indexable:
            excluded_session_ids.add(entry.session_id)
            if not selected:
                continue
        if selected or (
            entry.artifact_kind == "archive-artifact" and (not entry.session_kind or entry.session_kind == "unknown")
        ):
            parsed = _build_corpus_entry(
                entry,
                (
                    (
                        lambda message, observed_at: collect_transcript_writes(
                            message=message,
                            observed_at=observed_at,
                            workspace_dir=workspace,
                            writes=curated_writes,
                        )
                    )
                    if selected
                    else None
                ),
            )
            if parsed is not None and not _is_memory_session_indexable(
                generated_by_dreaming_narrative=parsed.generated_by_dreaming_narrative,
                generated_by_cron_run=parsed.generated_by_cron_run,
                session_kind=parsed.session_kind,
                line_provenance=parsed.line_provenance,
            ):
                excluded_session_ids.add(entry.session_id)

    changed_paths = {rewrite.relative_path for rewrite in [*memory_rewrites, *corpus_rewrites]}
    index_plan = plan_memory_index(
        store,
        agent_id=agent_id,
        changed_paths=changed_paths,
        removed_paths={rewrite.relative_path for rewrite in corpus_rewrites if rewrite.remove},
        session_ids=session_ids,
        excluded_session_ids=excluded_session_ids,
        matches_memory=lambda content: scrub(content).content != content,
    )
    report = MemoryForgetReport(
        agent_id=agent_id,
        dry_run=dry_run,
        session_ids=sorted(session_ids, key=_utf16_key),
        participant_matches=summarize_participant_matches(targets, participants),
        session_resolutions=sorted(
            (
                {"sessionId": t.session_id, "sessionKey": t.session_key, "source": t.resolution}
                if t.session_key
                else {"sessionId": t.session_id, "source": t.resolution}
                for t in targets
            ),
            key=cmp_to_key(lambda a, b: locale_compare(a["sessionId"], b["sessionId"])),
        ),
        entry_keys=sorted(entry_keys, key=_utf16_key),
        mixed_lineage_entry_keys=sorted(mixed_lineage, key=_utf16_key),
        untargetable_entry_keys=sorted(untargetable, key=_utf16_key),
        curated_writes=sorted(
            curated_writes.values(), key=cmp_to_key(lambda a, b: locale_compare(a["relativePath"], b["relativePath"]))
        ),
        artifacts={
            "memoryFiles": len(memory_rewrites),
            "memoryEntries": removed_memory_entries,
            "memoryLines": removed_memory_lines,
            "sessionCorpusFiles": len(corpus_rewrites),
            "sessionCorpusLines": removed_corpus_lines,
            "indexChunks": len(index_plan.chunks),
            "indexSources": len(index_plan.sources),
            "ftsRows": index_plan.fts_rows,
            "vectorRows": 0,
            "embeddingCacheRows": index_plan.embedding_cache_rows,
            "shortTermEntries": len(short_term_entries) - len(retained_short_term),
            "seenHashScopes": removed_seen_scopes,
            "backups": rewritten_backups,
            "originRows": sum(1 for o in all_origins if o.entry_key in entry_keys),
        },
        refusals=refusals,
    )
    if dry_run or not session_ids:
        return report

    def lineage_is_current(current: list[MemoryEntryOrigin]) -> bool:
        if _selected_lineage_identity(current, session_ids, entry_keys) == lineage_identity:
            return True
        # Keep observed selected keys even if another workspace later removes their rows.
        context.origins = current
        for origin in current:
            if origin.session_id in session_ids:
                context.selected_entry_keys.add(origin.entry_key)
        return False

    if not context.tombstoned:
        marked = ledger.record_session_tombstones_if_lineage_current(
            agent_id, list(session_ids), is_current=lineage_is_current
        )
        if not marked:
            return None
        context.tombstoned = True
    # The marker has committed: a purge failure leaves it durable for the retry.
    if not lineage_is_current(ledger.list(agent_id)):
        return None
    if purge_memory_index(store, index_plan) and (index_plan.chunks or index_plan.sources):
        fence = getattr(store, "revision_fence", None)
        if fence is not None:
            # The chunk and source deletes bump the revision upstream (table triggers).
            fence.bump()
    if removed_phase_signal_keys:
        # Phase signals derive from recall rows: remove them first so a later failure leaves the
        # authoritative recall evidence for a retry.
        for key in removed_phase_signal_keys:
            del phase_signals["entries"][key]
        phase_signals["updatedAt"] = now_iso
        write_json_atomic(phase_signal_store_path(workspace), phase_signals)
    if len(retained_short_term) != len(short_term_entries):
        write_json_atomic(
            recall_path,
            {**recall_store, "entries": dict(retained_short_term)},
        )
    if removed_seen_scopes > 0 or len(retained_file_states) != len(ingestion_state.files):
        write_session_ingestion_state(workspace, SessionIngestionState(retained_file_states, retained_seen))
    if rewritten_backups > 0:
        write_json_atomic(preimage_path(workspace), {"version": 1, "entries": next_backups})
    for rewrite in [*memory_rewrites, *corpus_rewrites]:
        commit_memory_content(
            rewrite.absolute_path,
            expected_content=rewrite.expected_content,
            content=None if rewrite.remove else rewrite.content,
            label=rewrite.absolute_path.name,
        )
    ledger.delete(agent_id, list(entry_keys))
    return report
