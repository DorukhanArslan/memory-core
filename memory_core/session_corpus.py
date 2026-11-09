from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

from memory_core.bootstrap._js import JS_SPACE_CLASS, js_trim, js_truthy
from memory_core.heartbeat import (
    HEARTBEAT_PROMPT,
    HEARTBEAT_TOKEN,
    is_heartbeat_user_message,
    is_silent_reply_payload_text,
)
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.redact import capture_sensitive_text_redaction_snapshot, create_sensitive_text_redactor
from memory_core.secret_registry import get_secret_redaction_registry_revision
from memory_core.session_artifacts import (
    is_session_archive_artifact_name,
    is_usage_counted_session_transcript_file_name,
    parse_usage_counted_session_id_from_file_name,
)
from memory_core.session_catalog import MemorySessionCatalog, normalize_session_agent_id
from memory_core.session_visibility import is_incognito_session_key
from memory_core.tools.common import MemoryToolError
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
    session_id: str | None = None
    artifact_kind: str = "active-session"
    transcript_source: str = "file"
    store_path: str | None = None
    updated_at_ms: float | None = None
    index_size: int | None = None
    revision_ms: float | None = None


def is_memory_session_indexable(
    entry: Mapping[str, Any], archived_session_key: str | None = None,
) -> bool:
    """Native manager admission, distinct from catalog enumeration and ingestion policy."""
    if (entry.get("generatedByDreamingNarrative") or entry.get("generatedByCronRun")
            or entry.get("sessionKind") in {"cron", "heartbeat"}):
        return False
    if archived_session_key is not None and (
        is_dreaming_narrative_session_store_key(archived_session_key)
        or is_cron_run_session_key(archived_session_key)
        or archived_session_key.endswith(":heartbeat")
    ):
        return False
    lines = entry.get("lineProvenance")
    return not (isinstance(lines, list) and lines
                and all(line.get("originClass") == "system" for line in lines))


class MemoryCoreSessionCorpus:
    def __init__(
        self,
        state_dir: Path,
        *,
        agent_id: str = "main",
        runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
        redact_text: Callable[[str], str] | None = None,
        is_forgotten: Callable[[str], bool] | None = None,
        catalog: MemorySessionCatalog | None = None,
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
        if catalog is not None and catalog.agent_id != normalize_session_agent_id(agent_id):
            raise ValueError("Session catalog belongs to a different agent")
        self.catalog = catalog

    @property
    def sessions_dir(self) -> Path:
        return self.state_dir / "agents" / self.agent_id / "sessions"

    def discover_files(self) -> list[SessionCorpusFile]:
        if self.catalog is not None:
            return self._discover_catalog_files()
        sessions = self._read_session_store()
        cron_generated_keys = _cron_generated_session_keys(sessions)
        files: list[SessionCorpusFile] = []
        summaries = [(key, value) for key, value in sessions.items()
                     if isinstance(value, dict) and isinstance(value.get("sessionFile"), str)]
        for session_key, entry in sorted(summaries, key=lambda item: item[1]["sessionFile"]):
            if is_incognito_session_key(session_key):
                continue
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

    def _canonical_key(self, key: str) -> str:
        raw = js_trim(key)
        catalog = self.catalog
        if catalog.shared_store:
            return raw
        aliases = {"main", catalog.main_key}
        for agent in {"main", catalog.agent_id}:
            aliases.update({f"agent:{agent}:main", f"agent:{agent}:{catalog.main_key}"})
        if raw in aliases:
            return "global" if catalog.session_scope == "global" else f"agent:{catalog.agent_id}:{catalog.main_key}"
        return raw

    def _owner_for_key(self, key: str) -> str:
        raw = self._canonical_key(key)
        if raw[:6].lower() == "agent:":
            end = raw.find(":", 6)
            if end < 0 or not js_trim(raw[6:end]) or not raw[end + 1:] or raw[end + 1:].startswith(":"):
                raise MemoryToolError("Malformed agent session key; refusing default-agent resolution.")
            return normalize_session_agent_id(raw[6:end])
        return self.catalog.default_agent_id if self.catalog.shared_store else self.catalog.agent_id

    def _archive_files(self) -> list[Path]:
        dirs = dict.fromkeys((self.catalog.store_path.parent.resolve(), self.sessions_dir.resolve()))
        seen: set[Path] = set()
        files = []
        for directory in dirs:
            try:
                candidates = sorted(directory.iterdir(), key=lambda entry: os.fsencode(entry.name))
            except FileNotFoundError:
                continue
            for path in candidates:
                if (path.is_symlink() or not path.is_file()
                        or not is_session_archive_artifact_name(path.name)
                        or not is_usage_counted_session_transcript_file_name(path.name)):
                    continue
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    files.append(path)
        return files

    def discover_entries(
        self, *, include_retained_sqlite: bool = False, include_content_revision: bool = False,
    ) -> list[dict[str, Any]]:
        """Enumerate authoritative active, retained and archive identities before index admission."""
        if self.catalog is None:
            raise ValueError("Authoritative corpus enumeration requires a session catalog")
        catalog = self.catalog
        artifacts = self._archive_files()
        # Read ownership after filesystem preparation, retaining the captured
        # catalog/store scope while observing the latest committed metadata.
        snapshot = catalog.snapshot()
        summaries = {
            key: value for key, value in snapshot.entries.items()
            if not is_incognito_session_key(key) and not (key.startswith("agent:") and ":" in key[6:]
                    and key[key.find(":", 6) + 1:].startswith("internal-session-effects:"))
        }
        lineage = {instance.session_key: instance.entry for instance in snapshot.instances}
        lineage.update(summaries)
        cron_keys = _cron_generated_session_keys(lineage)
        active: dict[str, dict[str, Any]] = {}
        owners: dict[str, str] = {}

        def classified(key: str, data: dict[str, Any]) -> dict[str, Any]:
            classification = _classify_session_entry(key, data, cron_keys)
            return {
                "sessionKind": classification["session_kind"],
                **({"generatedByDreamingNarrative": True} if classification["generated_by_dreaming_narrative"] else {}),
                **({"generatedByCronRun": True} if classification["generated_by_cron_run"] else {}),
            }

        def revision(agent: str, session_id: str, key: str) -> dict[str, Any]:
            if not include_content_revision:
                return {}
            transcript = catalog.read_transcript(session_id, agent_id=agent, session_key=key or None)
            return {"contentRevision": f"sqlite:{transcript.revision}:{len(transcript.events)}:{transcript.size_bytes}"} if transcript is not None else {}

        for key, data in summaries.items():
            raw_id = data.get("sessionId")
            session_id = js_trim(raw_id) if isinstance(raw_id, str) else ""
            if not session_id:
                continue
            owner = self._owner_for_key(key)
            owners[session_id] = owner
            if owner != catalog.agent_id:
                continue
            session_key = js_trim(key)
            updated = data.get("updatedAt")
            active[session_id] = {
                "agentId": owner, "artifactKind": "active-session", "sessionFile": session_key,
                "sessionId": session_id, "transcriptSource": "sqlite", "storePath": str(catalog.store_path),
                **({"sessionKey": session_key} if session_key else {}),
                **({"updatedAtMs": updated} if isinstance(updated, int | float) and not isinstance(updated, bool) and math.isfinite(updated) else {}),
                **classified(key, data), **revision(owner, session_id, session_key),
            }
        entries = list(active.values())
        if include_retained_sqlite:
            for instance in snapshot.instances:
                if (is_incognito_session_key(instance.session_key)
                        or instance.session_id in active or not instance.provenance_known or instance.acp_owned
                        or js_truthy(instance.entry.get("acp")) or js_truthy(instance.entry.get("pluginOwnerId"))
                        or js_truthy(instance.entry.get("hookExternalContentSource"))):
                    continue
                owner = self._owner_for_key(instance.session_key)
                if owner != catalog.agent_id:
                    continue
                key = self._canonical_key(instance.session_key)
                entries.append({
                    "agentId": owner, "artifactKind": "retained-session", "sessionFile": key,
                    "sessionId": instance.session_id, "storePath": str(catalog.store_path),
                    "transcriptSource": "sqlite", "updatedAtMs": instance.updated_at_ms,
                    **({"sessionKey": key} if key else {}), **classified(key, instance.entry),
                    **revision(owner, instance.session_id, key),
                })
        archive_identities = {archive.archive_name: archive for archive in snapshot.archives}
        for path in artifacts:
            archived = archive_identities.get(path.name)
            session_id = archived.session_id if archived is not None else parse_usage_counted_session_id_from_file_name(path.name)
            if not session_id:
                continue
            owner = owners.get(session_id)
            if owner is not None and owner != catalog.agent_id:
                continue
            if owner is None and archived is None and catalog.shared_store:
                continue
            primary = active.get(session_id) or {}
            entry = {
                "agentId": catalog.agent_id, "artifactKind": "archive-artifact",
                "sessionFile": str(path), "sessionId": session_id,
                "sessionKind": primary.get("sessionKind", "unknown"),
                **{key: True for key in ("generatedByDreamingNarrative", "generatedByCronRun") if primary.get(key)},
            }
            if archived is not None:
                entry["storePath"] = str(catalog.store_path)
                if archived.session_key:
                    entry["sessionKey"] = archived.session_key
            if include_content_revision:
                info = path.stat()
                entry["contentRevision"] = f"file:{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}"
            entries.append(entry)
        return entries

    def discover_admitted_entries(self) -> list[dict[str, Any]]:
        """Manager-admitted catalog rows, preserving the complete source identities."""
        entries = self.discover_entries()
        snapshot = self.catalog.snapshot()
        forgotten = snapshot.forgotten_session_ids
        archived = {item.archive_name: item for item in snapshot.archives}
        admitted = []
        for entry in entries:
            session_id = entry["sessionId"]
            if session_id in forgotten or (self.is_forgotten is not None and self.is_forgotten(session_id)):
                continue
            archive = archived.get(Path(entry["sessionFile"]).name) if entry["artifactKind"] == "archive-artifact" else None
            if is_memory_session_indexable(entry, archive.session_key if archive is not None else None):
                admitted.append(entry)
        return admitted

    def _discover_catalog_files(self) -> list[SessionCorpusFile]:
        files = []
        for entry in self.discover_admitted_entries():
            session_id = entry["sessionId"]
            sqlite = entry.get("transcriptSource") == "sqlite"
            if sqlite:
                transcript = self.catalog.read_transcript(session_id, agent_id=entry["agentId"], session_key=entry.get("sessionKey"))
                if transcript is None:
                    continue
                relative = f"sessions/{entry['agentId']}/{session_id}.jsonl"
                mtime, size = entry.get("updatedAtMs", transcript.updated_at_ms), transcript.size_bytes
                revision_ms = transcript.mutation_at_ms
            else:
                absolute = Path(entry["sessionFile"])
                parts = absolute.parts
                owner = next((parts[index + 1] for index, part in enumerate(parts[:-2])
                              if part == "agents" and parts[index + 2] == "sessions"), None)
                relative = "/".join(("sessions", *((owner,) if owner else ()), absolute.name))
                info = absolute.stat()
                mtime, size, revision_ms = info.st_mtime_ns / 1_000_000, info.st_size, None
            files.append(SessionCorpusFile(
                relative, Path(entry["sessionFile"]), session_key=entry.get("sessionKey"),
                session_kind=entry["sessionKind"],
                generated_by_dreaming_narrative=entry.get("generatedByDreamingNarrative", False),
                generated_by_cron_run=entry.get("generatedByCronRun", False),
                session_id=session_id, artifact_kind=entry["artifactKind"],
                transcript_source="sqlite" if sqlite else "file", store_path=entry.get("storePath"),
                updated_at_ms=mtime, index_size=size, revision_ms=revision_ms,
            ))
        return files

    def read_index_text(self, file: SessionCorpusFile) -> str:
        """Compatibility rendering; indexing uses :meth:`read_index_entry`.

        Existing consumers receive a final newline. That formatting sentinel
        is not part of the native indexed projection or its source hash.
        """
        entry = self.read_index_entry(file)
        if entry is None:
            return ""
        return entry.content + ("\n" if entry.content else "")

    def read_index_entry(
        self, file: SessionCorpusFile, *,
        on_transcript_message: Callable[[object, int], None] | None = None,
    ) -> SessionEntry | None:
        """Return a complete projection, or absence for an unreadable file.

        File/archive failures follow the native source reader's nullable result.
        Errors from an identity-backed SQLite accessor remain operational errors.
        """
        # Indexing follows OpenClaw memory ingestion (buildSessionEntry, ported in
        # memory_core.session_entry): every user/assistant message row in file order, including
        # abandoned and side-append branches (ingestion never calls the transcript-tree helpers),
        # rendered as "User:"/"Assistant:" lines with whitespace normalised, long lines wrapped
        # at 800 characters, and heartbeat, cron, exec-completion, silent-reply, inter-session,
        # recalled-memory and dreaming-narrative rows dropped, and every text redacted with
        # ``redactSensitiveText`` (memory_core.redact; ``redact_text`` extends it).
        if file.transcript_source == "sqlite":
            if self.catalog is None or file.session_id is None:
                raise ValueError("SQLite transcript projection requires its authoritative catalog")
            # The native background SQLite task receives one exact-secret
            # snapshot and may publish only while its registry revision holds.
            # Observers, host callbacks and process-local incognito sources keep
            # their live in-process policy, just like the native callback path.
            guarded = (
                on_transcript_message is None and self.redact_text is None
                and not is_incognito_session_key(file.session_key or "")
                and self.catalog._memory_uri is None
            )
            for _attempt in range(2 if guarded else 1):
                redaction = capture_sensitive_text_redaction_snapshot() if guarded else None
                snapshot = self.catalog.read_transcript(file.session_id, session_key=file.session_key)
                entry = None if snapshot is None else build_session_entry(
                    events=snapshot.events,
                    mtime_ms=file.updated_at_ms if file.updated_at_ms is not None else snapshot.updated_at_ms,
                    session_key=file.session_key, session_kind=file.session_kind,
                    generated_by_dreaming_narrative=file.generated_by_dreaming_narrative,
                    generated_by_cron_run=file.generated_by_cron_run,
                    runtime_identity=self.runtime_identity,
                    redact_text=create_sensitive_text_redactor(redaction) if redaction else self.redact_text,
                    apply_default_redaction=not guarded,
                    on_transcript_message=on_transcript_message,
                )
                if redaction and redaction.registry_revision != get_secret_redaction_registry_revision():
                    continue
                if entry is not None:
                    entry._extra.update({
                        "path": file.rel_path, "absPath": str(file.abs_path),
                        "mtimeMs": file.updated_at_ms if file.updated_at_ms is not None else snapshot.updated_at_ms,
                        "revisionMs": snapshot.mutation_at_ms, "size": snapshot.size_bytes,
                    })
                return entry
            raise MemoryToolError("Session transcript redaction changed during preparation; retry the operation.")
        try:
            return self._read_file_index_entry(file, on_transcript_message=on_transcript_message)
        except Exception:
            return None

    def _read_file_index_entry(
        self, file: SessionCorpusFile, *,
        on_transcript_message: Callable[[object, int], None] | None = None,
    ) -> SessionEntry | None:
        info = file.abs_path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return None
        seconds, nanos = divmod(info.st_mtime_ns, 1_000_000_000)
        mtime_ms = seconds * 1000 + nanos / 1_000_000
        file_size = info.st_size
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(file.abs_path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                return None
            raw = stream.read()
        if file.abs_path.name.endswith(".zst"):
            from memory_core.session_archive_codec import decode_session_transcript_bytes

            raw = decode_session_transcript_bytes(raw, compressed=True)
        entry = build_session_entry(
            records=parse_jsonl_records(raw.decode("utf-8", errors="replace")),
            mtime_ms=mtime_ms,
            session_key=file.session_key,
            session_kind=file.session_kind,
            generated_by_dreaming_narrative=file.generated_by_dreaming_narrative,
            generated_by_cron_run=file.generated_by_cron_run,
            # This corpus reads JSONL files. Native file entries have no live
            # SQLite reset cutoff; the host may supply one through MemoryFile.
            reset_recall_cutoff={"state": "absent"},
            allow_record_cron_classification=file.artifact_kind == "archive-artifact",
            runtime_identity=self.runtime_identity,
            redact_text=self.redact_text,
            on_transcript_message=on_transcript_message,
        )
        entry._extra.update({
            "path": file.rel_path, "absPath": str(file.abs_path), "mtimeMs": mtime_ms,
            "size": file_size,
        })
        return entry

    def read_source_entry(
        self, file: SessionCorpusFile, *,
        on_transcript_message: Callable[[object, int], None] | None = None,
    ) -> dict[str, Any] | None:
        """Build the complete native-shaped source projection from actual stored state."""
        entry = self.read_index_entry(file, on_transcript_message=on_transcript_message)
        if entry is None:
            return None
        return {
            **entry._extra, "hash": entry.hash, "content": entry.content,
            "lineMap": entry.line_map, "messageTimestampsMs": entry.message_timestamps_ms,
            "lineProvenance": entry.line_provenance, "sessionKind": entry.session_kind,
            **({"generatedByDreamingNarrative": True} if entry.generated_by_dreaming_narrative else {}),
            **({"generatedByCronRun": True} if entry.generated_by_cron_run else {}),
        }

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
