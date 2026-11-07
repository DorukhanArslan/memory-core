from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from memory_core.bootstrap._js import JS_SPACE_CLASS, js_trim, js_truthy
from memory_core.heartbeat import (
    HEARTBEAT_PROMPT,
    HEARTBEAT_TOKEN,
    is_heartbeat_user_message,
    is_silent_reply_payload_text,
)
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.session_entry import (
    SessionEntry,
    build_session_entry,
    is_cron_run_session_key,
    is_dreaming_narrative_session_store_key,
    parse_jsonl_records,
)

_NEWLINE_RUN_RE = re.compile(f"[{JS_SPACE_CLASS}]*\n+[{JS_SPACE_CLASS}]*")
_WHITESPACE_RUN_RE = re.compile(f"[{JS_SPACE_CLASS}]+")


@dataclass(frozen=True)
class SessionCorpusFile:
    rel_path: str
    abs_path: Path
    source: str = "sessions"
    # Classification belongs to the authoritative session-store entry, rather
    # than transcript text or a guessed meaning of the JSONL filename.
    session_key: str | None = None
    session_kind: str = "unknown"
    generated_by_dreaming_narrative: bool = False
    generated_by_cron_run: bool = False


class MemoryCoreSessionCorpus:
    def __init__(
        self,
        state_dir: Path,
        *,
        agent_id: str = "main",
        runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
        redact_text: Callable[[str], str] | None = None,
        is_forgotten: Callable[[str], bool] | None = None,
    ):
        # A forgotten session (a tombstone in the origins ledger) is never indexed again:
        # ``is_forgotten(session_id)`` (upstream: manager-session-sync-ops.ts filters the corpus
        # by ``listMemorySessionTombstones``).
        self.is_forgotten = is_forgotten
        self.state_dir = state_dir.resolve()
        self.agent_id = agent_id
        # Decides which heartbeat transcript row (HEARTBEAT_TRANSCRIPT_PROMPT) is
        # dropped; transcripts written by an OpenClaw runtime need
        # OPENCLAW_COMPAT_RUNTIME_IDENTITY.
        self.runtime_identity = runtime_identity
        # Host redaction of every indexed text (upstream: redactSensitiveText, mode tools).
        self.redact_text = redact_text

    @property
    def sessions_dir(self) -> Path:
        return self.state_dir / "agents" / self.agent_id / "sessions"

    def discover_files(self) -> list[SessionCorpusFile]:
        sessions = self._read_session_store()
        cron_generated_keys = _cron_generated_session_keys(sessions)
        files: list[SessionCorpusFile] = []
        summaries = [(key, value) for key, value in sessions.items()
                     if isinstance(value, dict) and isinstance(value.get("sessionFile"), str)]
        for session_key, entry in sorted(summaries, key=lambda item: item[1]["sessionFile"]):
            file_name = entry["sessionFile"]
            if "/" in file_name or "\\" in file_name or not file_name.endswith(".jsonl"):
                continue
            path = (self.sessions_dir / file_name).resolve()
            if not path.is_file() or not _is_inside(path, self.sessions_dir.resolve()):
                continue
            session_id = file_name[: -len(".jsonl")]
            if self.is_forgotten is not None and self.is_forgotten(session_id):
                continue
            files.append(
                SessionCorpusFile(
                    rel_path=f"sessions/{self.agent_id}/{session_id}.jsonl",
                    abs_path=path,
                    session_key=js_trim(session_key) or None,
                    **_classify_session_entry(session_key, entry, cron_generated_keys),
                )
            )
        return files

    def read_index_text(self, file: SessionCorpusFile) -> str:
        """Compatibility rendering; indexing uses :meth:`read_index_entry`.

        Existing consumers receive a final newline. That formatting sentinel
        is not part of the native indexed projection or its source hash.
        """
        entry = self.read_index_entry(file)
        return entry.content + ("\n" if entry.content else "")

    def read_index_entry(self, file: SessionCorpusFile) -> SessionEntry:
        """Retain the native projection, original line mapping and trust facts."""
        # Indexing follows OpenClaw memory ingestion (buildSessionEntry, ported in
        # memory_core.session_entry): every user/assistant message row in file order, including
        # abandoned and side-append branches (ingestion never calls the transcript-tree helpers),
        # rendered as "User:"/"Assistant:" lines with whitespace normalised, long lines wrapped
        # at 800 characters, and heartbeat, cron, exec-completion, silent-reply, inter-session,
        # recalled-memory and dreaming-narrative rows dropped, and every text redacted with
        # ``redactSensitiveText`` (memory_core.redact; ``redact_text`` extends it).
        try:
            seconds, nanos = divmod(file.abs_path.stat().st_mtime_ns, 1_000_000_000)
            mtime_ms = seconds * 1000 + nanos / 1_000_000
        except OSError:
            mtime_ms = 0
        return build_session_entry(
            records=parse_jsonl_records(file.abs_path.read_bytes().decode("utf-8", errors="replace")),
            mtime_ms=mtime_ms,
            session_key=file.session_key,
            session_kind=file.session_kind,
            generated_by_dreaming_narrative=file.generated_by_dreaming_narrative,
            generated_by_cron_run=file.generated_by_cron_run,
            # This corpus reads JSONL files. Native file entries have no live
            # SQLite reset cutoff; the host may supply one through MemoryFile.
            reset_recall_cutoff={"state": "absent"},
            runtime_identity=self.runtime_identity,
            redact_text=self.redact_text,
        )

    def _is_heartbeat_row(self, raw_text: str, role: str) -> bool:
        # Checks run on normalizeSessionText output (sanitizeSessionText at v2026.9.6), so
        # a heartbeat prompt followed by a newline and more text no longer matches.
        normalized = _normalize_session_text(raw_text)
        if role == "user" and is_heartbeat_user_message(
            {"role": role, "content": normalized},
            HEARTBEAT_PROMPT,
            runtime_identity=self.runtime_identity,
        ):
            return True
        if is_silent_reply_payload_text(normalized):
            return True
        return role == "assistant" and normalized == HEARTBEAT_TOKEN

    def _read_session_store(self) -> dict[str, Any]:
        path = self.sessions_dir / "sessions.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}


def _session_file_names(store: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for value in store.values():
        if isinstance(value, dict) and isinstance(value.get("sessionFile"), str):
            names.append(value["sessionFile"])
    return names


def _cron_generated_session_keys(store: dict[str, Any]) -> set[str]:
    """Native corpus cron lineage, including pruned parents and cycle guards."""
    generated: set[str] = set()
    cache: dict[str, bool] = {}
    resolving: set[str] = set()

    def resolve(key: str) -> bool:
        if is_cron_run_session_key(key):
            cache[key] = True
            generated.add(key)
            return True
        if key in cache:
            return cache[key]
        if key in resolving:
            return False
        resolving.add(key)
        entry = store.get(key)
        parents = dict.fromkeys(
            js_trim(value) for name in ("parentSessionKey", "spawnedBy")
            if isinstance(entry, dict) and isinstance(value := entry.get(name), str) and js_trim(value)
        )
        result = any(is_cron_run_session_key(parent) or resolve(parent) for parent in parents)
        resolving.remove(key)
        cache[key] = result
        if result:
            generated.add(key)
        return result

    for key, entry in store.items():
        if isinstance(entry, dict):
            resolve(key)
    return generated


def _classify_session_entry(key: str, entry: dict, cron_keys: set[str]) -> dict[str, Any]:
    """Classify only facts supplied by a registered session-store row."""
    spawned_by = entry.get("spawnedBy")
    dreaming = is_dreaming_narrative_session_store_key(key) or (
        isinstance(spawned_by, str) and is_dreaming_narrative_session_store_key(spawned_by)
    )
    cron = key in cron_keys
    heartbeat_base = entry.get("heartbeatIsolatedBaseSessionKey")
    if cron:
        kind = "cron"
    elif isinstance(heartbeat_base, str) and js_trim(heartbeat_base):
        kind = "heartbeat"
    elif dreaming or js_truthy(spawned_by) or ":subagent:" in key:
        kind = "subagent"
    else:
        kind = "interactive"
    return {"session_kind": kind, "generated_by_dreaming_narrative": dreaming,
            "generated_by_cron_run": cron}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    return entries


def _normalize_session_text(value: str) -> str:
    return js_trim(_WHITESPACE_RUN_RE.sub(" ", _NEWLINE_RUN_RE.sub(" ", value)))


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts)


def _is_inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
