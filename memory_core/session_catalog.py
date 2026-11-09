"""Persisted host authority for session metadata and transcript generations.

This catalog uses an SDK-owned SQLite schema. Hosts write metadata and events
through its methods; memory consumers read coherent snapshots rather than
guessing ownership or reset state from transcript filenames.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
import json
import hashlib
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import threading
from typing import Any
from uuid import uuid4

from memory_core.bootstrap._js import js_json_stringify, js_trim, js_truthy, js_utf8_encode
from memory_core.project_name import DIST_NAME
from memory_core.redact import LoggingConfig
from memory_core.session_entry import resolve_session_reset_recall_cutoff
from memory_core.session_transcript_append import (
    SqliteTranscriptMutationConflictError,
    TranscriptTurnAdmissionConflictError,
    can_forward_project_event,
    message_idempotency_key,
    messages_match_for_replay,
    redact_message_for_storage,
    resolve_message_append_parent,
    timestamp_ms_to_iso,
)
from memory_core.session_visibility import is_incognito_session_key, resolve_session_agent_id
from memory_core.tools.common import MemoryToolError
from memory_core.transcript_tree import UNSET, select_visible_transcript_events


@dataclass
class _ProcessCatalog:
    uri: str
    keeper: sqlite3.Connection
    lock: Any


_process_catalogs: dict[tuple[int, str, str], _ProcessCatalog] = {}
_process_catalogs_lock = threading.RLock()


class _ProcessConnection(sqlite3.Connection):
    _owner_lock: Any = None

    def close(self) -> None:
        owner = self._owner_lock
        self._owner_lock = None
        try:
            super().close()
        finally:
            if owner is not None:
                owner.release()


def normalize_session_agent_id(value: str | None) -> str:
    normalized = js_trim(value or "").lower()
    normalized = re.sub(r"[^a-z0-9_-]+", "-", normalized).strip("-")[:64]
    return normalized or "main"


def _normalize_store_key(value: str) -> str:
    """Fold structural key bytes while retaining provider-owned peer IDs."""
    raw = js_trim(value)
    spans = []
    for match in re.finditer(r"(^|:)signal:group:([^:]+)", raw, re.I | re.ASCII):
        spans.append((match.start(2), match.end(2), True))
    matrix = re.match(r"^(?:(?:agent:[^:]*:)+:*)?matrix:(?:channel|group):", raw, re.I | re.ASCII)
    if matrix is not None and matrix.end() < len(raw):
        start = matrix.end()
        marker = raw[start:].lower().rfind(":thread:")
        if marker < 0:
            spans.append((start, len(raw), False))
        else:
            spans.append((start, start + marker, False))
            thread = start + marker + len(":thread:")
            if thread < len(raw):
                spans.append((thread, len(raw), False))
    result, cursor = "", 0
    for start, end, trim in sorted(spans, key=lambda span: span[0]):
        if end <= start or start < cursor:
            continue
        result += js_trim(raw[cursor:start]).lower()
        result += js_trim(raw[start:end]) if trim else raw[start:end]
        cursor = end
    return result + js_trim(raw[cursor:]).lower()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def _finite(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _transcript_event_id(event: object) -> str | None:
    value = event.get("id") if isinstance(event, Mapping) else None
    return (js_trim(value) or None) if isinstance(value, str) else None


def _internal_key(key: str) -> bool:
    end = key.find(":", 6)
    return key.startswith("agent:") and end >= 0 and key[end + 1:].startswith("internal-session-effects:")


def _participant_namespace(identity: Mapping[str, Any]) -> str:
    kind = identity["type"]
    names = {
        "profile": ("type",), "agent": ("type",),
        "remote": ("type", "pluginId", "domain", "idKind"),
        "observation": ("type", "pluginId", "accountId", "senderKind"),
    }.get(kind, ("type", "actorType", "source"))
    # JSON.stringify omits absent own properties; null namespace fields stay null.
    return js_json_stringify({name: identity[name] for name in names if name in identity})


def _read_participant_identity(namespace: str, actor_id: str) -> dict[str, Any]:
    decoded = json.loads(namespace)
    if not isinstance(decoded, dict):
        raise MemoryToolError("Session participant identity is invalid; run openclaw doctor --fix.")
    identity = {**decoded, "id": actor_id}
    kind = identity.get("type")

    def nonempty(name: str) -> bool:
        return isinstance(identity.get(name), str) and len(identity[name]) > 0

    valid = False
    if kind in {"profile", "agent"}:
        valid = set(identity) == {"type", "id"} and nonempty("id")
    elif kind == "remote":
        valid = set(identity) == {"type", "pluginId", "domain", "idKind", "id"} and all(
            nonempty(name) for name in ("pluginId", "domain", "idKind", "id")
        )
    elif kind == "observation":
        valid = set(identity) == {"type", "pluginId", "accountId", "senderKind", "id"} and (
            all(identity.get(name) is None or nonempty(name) for name in ("pluginId", "accountId"))
            and identity.get("senderKind") in {"human", "bot", "unknown"} and nonempty("id")
        )
    elif kind == "legacy":
        valid = set(identity) == {"type", "actorType", "source", "id"} and (
            isinstance(identity.get("actorType"), str) and isinstance(actor_id, str)
            and (identity.get("source") is None or isinstance(identity.get("source"), str))
        )
    if not valid:
        raise MemoryToolError("Session participant identity is invalid; run openclaw doctor --fix.")
    return identity


def _source_created_at(entry: Mapping[str, Any], updated_at: float) -> float:
    for value in (entry.get("sessionStartedAt"), entry.get("startedAt"),
                  entry.get("updatedAt"), updated_at):
        if _finite(value) and value >= 0:
            return value
    return updated_at


def _source_delivery_facts(entry: Mapping[str, Any]) -> tuple[str | None, str | None]:
    delivery = entry.get("delivery")
    if not isinstance(delivery, Mapping) or delivery.get("kind") != "external":
        return None, None
    context, origin = delivery.get("context"), delivery.get("origin")
    context = context if isinstance(context, Mapping) else {}
    origin = origin if isinstance(origin, Mapping) else {}
    channel = context.get("channel")
    if channel is None:
        channel = origin.get("provider")

    def text(value: object) -> str | None:
        return (js_trim(value) or None) if isinstance(value, str) else None

    return text(channel), text(context.get("accountId"))


def _bound_window_provenance(
    entry: Mapping[str, Any], known: bool, acp_owned: bool,
) -> tuple[int, int, str | None, str | None]:
    plugin = entry.get("pluginOwnerId")
    plugin = (js_trim(plugin) or None) if isinstance(plugin, str) else None
    hook = entry.get("hookExternalContentSource")
    hook = "webhook" if hook == "email" else hook
    hook = hook if isinstance(hook, str) and hook in {"gmail", "webhook"} else None
    return int(known), int(acp_owned or js_truthy(entry.get("acp"))), plugin, hook


def _resolve_window_provenance(
    db: sqlite3.Connection, agent: str, session_id: str,
    bound: tuple[int, int, str | None, str | None], previous_session_id: object,
) -> tuple[int, int, str | None, str | None]:
    existing = db.execute(
        "SELECT provenance_known,acp_owned,plugin_owner_id,hook_external_content_source "
        "FROM memory_session_windows WHERE agent=? AND session_id=?", (agent, session_id),
    ).fetchone()
    if existing is None:
        return bound
    if not existing["provenance_known"] and (
        previous_session_id == session_id or db.execute(
            "SELECT 1 FROM memory_session_events WHERE agent=? AND session_id=? LIMIT 1",
            (agent, session_id),
        ).fetchone() is not None
    ):
        return 0, 0, None, None
    if existing["provenance_known"]:
        return (
            1, int(bool(existing["acp_owned"]) or bool(bound[1])),
            bound[2] if bound[2] is not None else existing["plugin_owner_id"],
            bound[3] if bound[3] is not None else existing["hook_external_content_source"],
        )
    return bound


def _window_entry(row: sqlite3.Row) -> dict[str, Any]:
    entry = json.loads(row["entry_json"])
    if row["provenance_known"]:
        if row["plugin_owner_id"]:
            entry["pluginOwnerId"] = row["plugin_owner_id"]
        if row["hook_external_content_source"] in {"gmail", "webhook"}:
            entry["hookExternalContentSource"] = row["hook_external_content_source"]
    return entry


def _project_session_participants(
    db: sqlite3.Connection, agent: str, session_key: str, entry: Mapping[str, Any],
) -> dict[str, Any]:
    """Project current-entry side facts from the actual participant table.

    Native canonical entry reads discard authored participant projections. The
    optional read projection supplies identities/count only when real rows exist;
    aggregate counters and timestamps remain on the separate record API.
    """
    projected = {key: value for key, value in entry.items() if key not in {"participants", "participantCount"}}
    participants = [{"identity": _read_participant_identity(row["identity_namespace"], row["actor_id"])}
                    for row in db.execute(
                        "SELECT identity_namespace,actor_id FROM memory_session_participants "
                        "WHERE agent=? AND session_key=? ORDER BY first_prompted_at,actor_id,identity_namespace",
                        (agent, session_key),
                    )]
    if participants:
        projected["participants"] = participants
        projected["participantCount"] = len(participants)
    return projected


def _clear_rotated_session_generation_fields(
    previous: Mapping[str, Any], replacement: dict[str, Any],
) -> None:
    """Apply the public session-store upsert's persisted rotation clear patch."""
    if not any(field in replacement and replacement[field] != previous.get(field, UNSET)
               for field in ("sessionId", "lifecycleRevision")):
        return
    # SESSION_ENTRY_PRIVATE_CLEAR_PATCH + MAIN_SESSION_RECOVERY_CLEAR_PATCH.
    # Delivery adoption identity deliberately remains outside the recovery clear.
    for field in ("activeWriterRunId", "lastRunId", "lifecycleRunId", "mainRestartRecovery",
                  "pendingProjectGitUrl", "pendingWorktree", "sessionDiffBaselineCapture",
                  "transcriptByteCompactionLatch", "restartRecoveryRuns"):
        replacement.pop(field, None)
    replacement["abortedLastRun"] = False


@dataclass(frozen=True)
class SessionTranscriptInstance:
    agent_id: str
    session_key: str
    session_id: str
    entry: dict[str, Any]
    provenance_known: bool
    acp_owned: bool
    updated_at_ms: float


@dataclass(frozen=True)
class SessionTranscriptArchive:
    archive_name: str
    session_id: str
    session_key: str | None
    path: Path
    agent_id: str


@dataclass(frozen=True)
class SessionTranscriptSnapshot:
    events: tuple[object, ...]
    session_key: str
    updated_at_ms: float
    revision: int
    size_bytes: int
    mutation_at_ms: float


@dataclass(frozen=True)
class SessionCatalogSnapshot:
    entries: dict[str, dict[str, Any]]
    instances: tuple[SessionTranscriptInstance, ...]
    archives: tuple[SessionTranscriptArchive, ...]
    forgotten_session_ids: frozenset[str]
    revision: int


class MemorySessionCatalog:
    """An agent-scoped durable catalog, independent of OpenClaw's binary schema.

    Separate catalog instances may share one database file; every query and
    mutation retains its explicit agent namespace. Transcript reads intentionally
    do not enforce memory tombstones: source-history authorization is a separate
    host guard, while tombstones remove entries from the memory corpus.
    """

    def __init__(
        self, path: str | Path, *, agent_id: str = "main", store_path: str | Path | None = None,
        shared_store: bool = False, main_key: str = "main", session_scope: str = "per-sender",
        clock_ms: Callable[[], float] | None = None,
        default_agent_id: str | None = None,
        profile_aliases: Callable[[str], Sequence[str]] | None = None,
    ) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.agent_id = normalize_session_agent_id(agent_id)
        self.store_path = Path(store_path).resolve() if store_path is not None else self.path.parent / "sessions.json"
        self.shared_store = shared_store
        self.main_key = js_trim(main_key).lower() or "main"
        self.session_scope = session_scope
        self.default_agent_id = normalize_session_agent_id(default_agent_id) if default_agent_id is not None else self.agent_id
        self._clock = clock_ms or (lambda: time.time() * 1000)
        self._profile_aliases = profile_aliases
        self._catalog_owner_path = self.path
        self._memory_uri: str | None = None
        self._memory_lock: Any = None
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS memory_session_catalog_state(
                    agent TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS memory_session_nodes(
                    agent TEXT NOT NULL, session_key TEXT NOT NULL, entry_json TEXT NOT NULL,
                    PRIMARY KEY(agent,session_key));
                CREATE TABLE IF NOT EXISTS memory_session_windows(
                    agent TEXT NOT NULL, session_id TEXT NOT NULL, session_key TEXT NOT NULL,
                    entry_json TEXT NOT NULL, provenance_known INTEGER NOT NULL,
                    acp_owned INTEGER NOT NULL, updated_at REAL NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                    transcript_updated_at REAL,
                    transcript_observed_at REAL,
                    mutation_at REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL DEFAULT 0,
                    plugin_owner_id TEXT,
                    hook_external_content_source TEXT,
                    PRIMARY KEY(agent,session_id));
                CREATE TABLE IF NOT EXISTS memory_session_events(
                    agent TEXT NOT NULL, session_id TEXT NOT NULL, seq INTEGER NOT NULL,
                    event_json TEXT NOT NULL, byte_size INTEGER NOT NULL,
                    PRIMARY KEY(agent,session_id,seq));
                CREATE TABLE IF NOT EXISTS memory_session_transcript_state(
                    agent TEXT NOT NULL, session_id TEXT NOT NULL, generation TEXT NOT NULL,
                    projection_dirty INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(agent,session_id));
                CREATE TABLE IF NOT EXISTS memory_session_archives(
                    agent TEXT NOT NULL, archive_name TEXT NOT NULL, session_id TEXT NOT NULL,
                    session_key TEXT, path TEXT NOT NULL, PRIMARY KEY(agent,archive_name));
                CREATE TABLE IF NOT EXISTS memory_session_tombstones(
                    agent TEXT NOT NULL, session_id TEXT NOT NULL, PRIMARY KEY(agent,session_id));
                CREATE TABLE IF NOT EXISTS memory_session_participants(
                    agent TEXT NOT NULL, session_key TEXT NOT NULL,
                    identity_namespace TEXT NOT NULL, actor_id TEXT NOT NULL,
                    contribution_count INTEGER NOT NULL, first_prompted_at REAL,
                    last_prompted_at REAL,
                    PRIMARY KEY(agent,session_key,identity_namespace,actor_id));
            """)
            if "created_at" not in {row["name"] for row in db.execute("PRAGMA table_info(memory_session_windows)")}:
                db.execute("ALTER TABLE memory_session_windows ADD COLUMN created_at REAL NOT NULL DEFAULT 0")
                db.execute("UPDATE memory_session_windows SET created_at=updated_at")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(memory_session_windows)")}
            if "transcript_observed_at" not in columns:
                db.execute("ALTER TABLE memory_session_windows ADD COLUMN transcript_observed_at REAL")
                db.execute("UPDATE memory_session_windows SET transcript_observed_at="
                           "COALESCE(transcript_updated_at,updated_at)")
            for column in ("plugin_owner_id", "hook_external_content_source"):
                if column not in columns:
                    db.execute(f"ALTER TABLE memory_session_windows ADD COLUMN {column} TEXT")
            if not {"plugin_owner_id", "hook_external_content_source"} <= columns:
                for row in db.execute("SELECT agent,session_id,entry_json,provenance_known,acp_owned FROM memory_session_windows").fetchall():
                    source = _bound_window_provenance(
                        json.loads(row["entry_json"]), bool(row["provenance_known"]), bool(row["acp_owned"]),
                    )
                    db.execute(
                        "UPDATE memory_session_windows SET plugin_owner_id=?,hook_external_content_source=? "
                        "WHERE agent=? AND session_id=?", (source[2], source[3], row["agent"], row["session_id"]),
                    )
            db.execute("INSERT OR IGNORE INTO memory_session_catalog_state(agent) VALUES(?)", (self.agent_id,))
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        if self._memory_uri is not None:
            self._memory_lock.acquire()
            try:
                db = sqlite3.connect(self._memory_uri, uri=True, timeout=30, factory=_ProcessConnection)
                db._owner_lock = self._memory_lock
            except BaseException:
                self._memory_lock.release()
                raise
        else:
            db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _process_catalog(self, agent: str, *, create: bool = False) -> MemorySessionCatalog | None:
        identity = (os.getpid(), str(self._catalog_owner_path), agent)
        with _process_catalogs_lock:
            owner = _process_catalogs.get(identity)
            if owner is None and not create:
                return None
            sentinel = self._catalog_owner_path.with_name("incognito-openclaw-agent.sqlite")
            if sentinel.exists():
                error = MemoryToolError(
                    f"Incognito agent database sentinel path already exists: {sentinel}. "
                    "This filename is reserved for in-memory incognito state; move or rename the file and retry."
                )
                error.name = "IncognitoAgentDatabasePathCollisionError"
                error.path = str(sentinel)
                raise error
            if owner is None:
                digest = hashlib.sha256(repr(identity).encode()).hexdigest()
                uri = f"file:{DIST_NAME}-incognito-{digest}?mode=memory&cache=shared"
                owner = _ProcessCatalog(uri, sqlite3.connect(uri, uri=True, check_same_thread=False), threading.RLock())
            view = object.__new__(type(self))
            view.__dict__.update(self.__dict__)
            view.path, view.store_path = sentinel, sentinel
            view.agent_id, view.default_agent_id, view.shared_store = agent, agent, False
            view._memory_uri, view._memory_lock = owner.uri, owner.lock
            if identity not in _process_catalogs:
                try:
                    view._initialize_schema()
                except BaseException:
                    owner.keeper.close()
                    raise
                _process_catalogs[identity] = owner
            return view

    def _key_catalog(self, session_key: str | None, *, create: bool = False) -> MemorySessionCatalog | None:
        if self._memory_uri is not None or not is_incognito_session_key(session_key):
            return self
        return self._process_catalog(resolve_session_agent_id(session_key), create=create)

    def _session_key(self, value: str | None) -> str | None:
        if value is None:
            return None
        key = _normalize_store_key(value)
        if not key or key in {"global", "unknown"} or key.startswith("agent:"):
            return key
        return f"agent:{self.agent_id}:{key}"

    def _transcript_catalog(
        self, session_id: str, session_key: str | None, *, write_fallback: bool = False,
    ) -> MemorySessionCatalog | None:
        if self._memory_uri is not None or session_key is not None:
            return self._key_catalog(session_key)
        if not write_fallback:
            return self
        matches = []
        with closing(self._connect()) as db:
            if db.execute("SELECT 1 FROM memory_session_windows WHERE agent=? AND session_id=?",
                          (self.agent_id, session_id)).fetchone() is not None:
                matches.append(self)
        with _process_catalogs_lock:
            agents = [agent for pid, path, agent in _process_catalogs
                      if pid == os.getpid() and path == str(self._catalog_owner_path)]
        for agent in agents:
            if agent != self.agent_id:
                continue
            catalog = self._process_catalog(agent)
            if catalog is not None:
                with closing(catalog._connect()) as db:
                    if db.execute("SELECT 1 FROM memory_session_windows WHERE agent=? AND session_id=?",
                                  (agent, session_id)).fetchone() is not None:
                        matches.append(catalog)
        if len(matches) > 1:
            raise ValueError("Transcript identity is ambiguous; supply its session_key")
        return matches[0] if matches else None

    def get_session_entry(
        self, session_key: str, *, agent_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Read one current entry, including an explicitly addressed process-only key."""
        catalog = self._key_catalog(session_key)
        if catalog is None:
            return None
        if catalog is not self:
            return catalog.get_session_entry(session_key, agent_id=catalog.agent_id)
        session_key = self._session_key(session_key)
        agent = self._scope(agent_id)
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            row = db.execute("SELECT entry_json FROM memory_session_nodes WHERE agent=? AND session_key=?",
                             (agent, session_key)).fetchone()
            return _project_session_participants(db, agent, session_key, json.loads(row[0])) if row is not None else None

    def _changed(self, db: sqlite3.Connection) -> None:
        db.execute("UPDATE memory_session_catalog_state SET revision=revision+1 WHERE agent=?", (self.agent_id,))

    def _scope(self, agent_id: str | None) -> str:
        if agent_id is not None and normalize_session_agent_id(agent_id) != self.agent_id:
            raise ValueError("Session transcript belongs to a different catalog agent")
        return self.agent_id

    def now_ms(self) -> float:
        """Current host activity time used by live catalog consumers."""
        return self._clock()

    def upsert_session(
        self, session_key: str, entry: Mapping[str, Any], *,
        provenance_known: bool = True, acp_owned: bool = False,
    ) -> None:
        """Replace one current metadata row, retaining earlier transcript windows."""
        if not isinstance(session_key, str) or not isinstance(entry, Mapping):
            raise TypeError("Session keys and metadata must be strings and mappings")
        catalog = self._key_catalog(session_key, create=True)
        if catalog is not self:
            return catalog.upsert_session(
                session_key, entry, provenance_known=provenance_known, acp_owned=acp_owned,
            )
        session_key = self._session_key(session_key)
        data = json.loads(_json(dict(entry)))
        data.setdefault("delivery", {"kind": "none"})
        if "updatedAt" not in data:
            data["updatedAt"] = self._clock()
        session_id = js_trim(data["sessionId"]) if isinstance(data.get("sessionId"), str) else ""
        updated_at = data.get("updatedAt") if _finite(data.get("updatedAt")) else 0
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT entry_json FROM memory_session_nodes WHERE agent=? AND session_key=?",
                (self.agent_id, session_key),
            ).fetchone()
            previous_entry = json.loads(previous[0]) if previous is not None else {}
            previous_id = previous_entry.get("sessionId")
            if previous is not None:
                _clear_rotated_session_generation_fields(previous_entry, data)
            if self._memory_uri is not None and is_incognito_session_key(session_key) and "createdAt" not in data:
                previous_updated = previous_entry.get("updatedAt")
                data["createdAt"] = previous_updated if previous_updated is not None else self._clock()
            provenance = _resolve_window_provenance(
                db, self.agent_id, session_id,
                _bound_window_provenance(data, provenance_known, acp_owned), previous_id,
            ) if session_id else None
            db.execute("INSERT INTO memory_session_nodes VALUES(?,?,?) ON CONFLICT(agent,session_key) "
                       "DO UPDATE SET entry_json=excluded.entry_json", (self.agent_id, session_key, _json(data)))
            if session_id:
                observed = db.execute("SELECT transcript_updated_at FROM memory_session_windows "
                                      "WHERE agent=? AND session_id=?", (self.agent_id, session_id)).fetchone()
                observed_at = observed[0] if observed is not None and observed[0] is not None else updated_at
                db.execute("INSERT INTO memory_session_windows(agent,session_id,session_key,entry_json,provenance_known,acp_owned,updated_at,revision,mutation_at,created_at,plugin_owner_id,hook_external_content_source,transcript_observed_at) VALUES(?,?,?,?,?,?,?,0,?,?,?,?,?) "
                           "ON CONFLICT(agent,session_id) DO UPDATE SET entry_json=excluded.entry_json, "
                           "updated_at=excluded.updated_at,transcript_observed_at=excluded.transcript_observed_at "
                           "WHERE memory_session_windows.session_key=excluded.session_key",
                           (self.agent_id, session_id, session_key, _json(data), provenance[0],
                            provenance[1], updated_at, self._clock(),
                            _source_created_at(data, updated_at), provenance[2], provenance[3], observed_at))
                db.execute(
                    "UPDATE memory_session_windows SET provenance_known=?,acp_owned=?,plugin_owner_id=?,"
                    "hook_external_content_source=? WHERE agent=? AND session_id=?",
                    (*provenance, self.agent_id, session_id),
                )
            self._changed(db)

    def retain_transcript(
        self, session_key: str, entry: Mapping[str, Any], *,
        provenance_known: bool, acp_owned: bool = False,
    ) -> None:
        """Restore a recorded historical window without making it the active session."""
        catalog = self._key_catalog(session_key, create=True)
        if catalog is not self:
            return catalog.retain_transcript(
                session_key, entry, provenance_known=provenance_known, acp_owned=acp_owned,
            )
        session_key = self._session_key(session_key)
        data = json.loads(_json(dict(entry)))
        session_id = js_trim(data.get("sessionId", ""))
        if not session_id:
            raise ValueError("A retained transcript requires a sessionId")
        updated_at = data.get("updatedAt") if _finite(data.get("updatedAt")) else 0
        provenance = _bound_window_provenance(data, provenance_known, acp_owned)
        with closing(self._connect()) as db, db:
            observed = db.execute("SELECT transcript_updated_at FROM memory_session_windows "
                                  "WHERE agent=? AND session_id=?", (self.agent_id, session_id)).fetchone()
            observed_at = observed[0] if observed is not None and observed[0] is not None else updated_at
            db.execute("INSERT INTO memory_session_windows(agent,session_id,session_key,entry_json,provenance_known,acp_owned,updated_at,revision,mutation_at,created_at,plugin_owner_id,hook_external_content_source,transcript_observed_at) VALUES(?,?,?,?,?,?,?,0,?,?,?,?,?) "
                       "ON CONFLICT(agent,session_id) DO UPDATE SET session_key=excluded.session_key, "
                       "entry_json=excluded.entry_json,provenance_known=excluded.provenance_known, "
                       "acp_owned=excluded.acp_owned,updated_at=excluded.updated_at,"
                       "transcript_observed_at=excluded.transcript_observed_at,"
                       "plugin_owner_id=excluded.plugin_owner_id,hook_external_content_source=excluded.hook_external_content_source",
                       (self.agent_id, session_id, session_key, _json(data), provenance[0], provenance[1], updated_at, self._clock(),
                        _source_created_at(data, updated_at), provenance[2], provenance[3], observed_at))
            self._changed(db)

    def _write_events(
        self, session_id: str, events: Sequence[object], *, replace: bool,
        updated_at_ms: float | None, session_key: str | None = None,
    ) -> None:
        serialized = [_json(event) for event in events]
        if not serialized and not replace:
            return
        catalog = self._transcript_catalog(session_id, session_key, write_fallback=True)
        if catalog is None:
            raise ValueError("Transcript identity is not registered in this catalog")
        if catalog is not self:
            return catalog._write_events(
                session_id, events, replace=replace, updated_at_ms=updated_at_ms,
                session_key=session_key,
            )
        session_key = self._session_key(session_key)
        with closing(self._connect()) as db, db:
            window = db.execute("SELECT mutation_at,session_key,transcript_updated_at,transcript_observed_at "
                                "FROM memory_session_windows WHERE agent=? AND session_id=?",
                                (self.agent_id, session_id)).fetchone()
            if window is None:
                raise ValueError("Transcript identity is not registered in this catalog")
            if session_key is not None and window["session_key"] != session_key:
                active = db.execute(
                    "SELECT entry_json FROM memory_session_nodes WHERE agent=? AND session_key=?",
                    (self.agent_id, session_key),
                ).fetchone()
                if active is None or json.loads(active[0]).get("sessionId") != session_id:
                    raise ValueError("Transcript identity does not belong to the requested session_key")
            previous = db.execute(
                "SELECT event_json,byte_size FROM memory_session_events WHERE agent=? AND session_id=? ORDER BY seq",
                (self.agent_id, session_id),
            ).fetchall()
            # The native SQL identity owner keeps the first row for a nonempty,
            # trimmed event ID. Unidentified rows remain distinct physical rows.
            seen = set() if replace else {
                identity for row in previous
                if (identity := _transcript_event_id(json.loads(row["event_json"]))) is not None
            }
            admitted = []
            for event, text in zip(events, serialized, strict=True):
                identity = _transcript_event_id(event)
                if identity is not None:
                    if identity in seen:
                        continue
                    seen.add(identity)
                admitted.append((event, text))
            events = [event for event, _text in admitted]
            serialized = [text for _event, text in admitted]
            if not serialized and not replace:
                return
            if replace and not serialized and not previous and db.execute(
                "SELECT 1 FROM memory_session_transcript_state WHERE agent=? AND session_id=?",
                (self.agent_id, session_id),
            ).fetchone() is None:
                return
            if replace:
                db.execute("DELETE FROM memory_session_events WHERE agent=? AND session_id=?", (self.agent_id, session_id))
            start = db.execute("SELECT COALESCE(MAX(seq),0) FROM memory_session_events WHERE agent=? AND session_id=?",
                               (self.agent_id, session_id)).fetchone()[0]
            db.executemany("INSERT INTO memory_session_events VALUES(?,?,?,?,?)", [
                (self.agent_id, session_id, start + index + 1, text,
                 len(js_utf8_encode(js_json_stringify(events[index]))))
                for index, text in enumerate(serialized)
            ])
            if serialized or replace:
                state = db.execute(
                    "SELECT generation,projection_dirty FROM memory_session_transcript_state WHERE agent=? AND session_id=?",
                    (self.agent_id, session_id),
                ).fetchone()
                if serialized or state is not None:
                    generation = uuid4().hex if replace or state is None else state[0]
                    if replace:
                        dirty = len(previous) + len(serialized) > 4000 or (
                            sum(row["byte_size"] for row in previous)
                            + sum(len(js_utf8_encode(js_json_stringify(event))) for event in events)
                        ) > 4 * 1024 * 1024
                    else:
                        dirty = bool(state["projection_dirty"]) if state is not None else bool(previous)
                        prefix = [json.loads(row["event_json"]) for row in previous]
                        for event in events:
                            dirty |= not can_forward_project_event(prefix, event)
                            prefix.append(event)
                    db.execute(
                        "INSERT INTO memory_session_transcript_state VALUES(?,?,?,?) "
                        "ON CONFLICT(agent,session_id) DO UPDATE SET generation=excluded.generation,projection_dirty=excluded.projection_dirty",
                        (self.agent_id, session_id, generation, int(dirty)),
                    )
            now = self._clock()
            mutation_at = max(window[0] + 1, now)
            activity_at = updated_at_ms if updated_at_ms is not None else now
            if _finite(activity_at) and activity_at >= 0:
                activity_at = max(math.floor(activity_at),
                                  (window["transcript_updated_at"] if window["transcript_updated_at"] is not None else -1) + 1,
                                  (window["transcript_observed_at"] if window["transcript_observed_at"] is not None else -1) + 1)
            else:
                activity_at = window["transcript_updated_at"]
            db.execute("UPDATE memory_session_windows SET revision=revision+1,transcript_updated_at=?,mutation_at=? WHERE agent=? AND session_id=?",
                       (activity_at, mutation_at, self.agent_id, session_id))
            self._changed(db)

    def append_events(
        self, session_id: str, events: Sequence[object], *, updated_at_ms: float | None = None,
        session_key: str | None = None,
    ) -> None:
        self._write_events(session_id, events, replace=False, updated_at_ms=updated_at_ms,
                           session_key=session_key)

    def replace_events(
        self, session_id: str, events: Sequence[object], *, updated_at_ms: float | None = None,
        session_key: str | None = None,
    ) -> None:
        self._write_events(session_id, events, replace=True, updated_at_ms=updated_at_ms,
                           session_key=session_key)

    def _message_anchor(
        self, db: sqlite3.Connection, session_id: str, session_key: str,
        events: list[Any], event: Mapping[str, Any], seq: int,
    ) -> dict[str, Any] | None:
        state = db.execute(
            "SELECT generation,projection_dirty FROM memory_session_transcript_state "
            "WHERE agent=? AND session_id=?", (self.agent_id, session_id),
        ).fetchone()
        if state is None or state["projection_dirty"]:
            return None
        messages = [record for record in select_visible_transcript_events(events)
                    if isinstance(record, dict) and record.get("type") != "session"
                    and "message" in record]
        position = next((index for index, record in enumerate(messages)
                         if record is event), None)
        if position is None:
            return None
        anchor = {
            "agentId": self.agent_id, "sessionId": session_id, "sessionKey": session_key,
            "storePath": str(self.path), "generation": state["generation"],
            "entryId": event["id"], "rawSeq": seq - 1,
            "effectiveParentId": event.get("parentId"), "activeMessagePosition": position,
        }
        key = message_idempotency_key(event.get("message"))
        if key:
            anchor["idempotencyKey"] = key
        return anchor

    def append_message(
        self, session_id: str, message: Any, *, session_key: str,
        event_id: str | None = None, parent_id: Any = UNSET, now_ms: float | None = None,
        cwd: str | None = None, append_intent: str | None = None,
        expected_mutation_at: Any = UNSET, logging_config: LoggingConfig | None = None,
    ) -> dict[str, Any]:
        """Append one ordinary JSON agent message in a single durable transaction.

        Header creation, redaction, admission-key replay, parent selection and
        the resulting identity share the write lock. ``append_events`` remains
        the raw transcript import API. This owner does not orchestrate pending
        inputs, media migration, provider replay or live writer-run fences.
        """
        catalog = self._transcript_catalog(session_id, session_key, write_fallback=True)
        if catalog is None:
            raise ValueError("Transcript identity is not registered in this catalog")
        if catalog is not self:
            return catalog.append_message(
                session_id, message, session_key=session_key, event_id=event_id,
                parent_id=parent_id, now_ms=now_ms, cwd=cwd, append_intent=append_intent,
                expected_mutation_at=expected_mutation_at, logging_config=logging_config,
            )
        if parent_id is not UNSET and parent_id is not None and not isinstance(parent_id, str):
            raise TypeError("parent_id must be a string, null, or omitted")
        session_key = self._session_key(session_key)
        persisted = json.loads(_json(redact_message_for_storage(message, logging_config)))
        admission_key = message_idempotency_key(message)
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            window = db.execute(
                "SELECT * FROM memory_session_windows WHERE agent=? AND session_id=?",
                (self.agent_id, session_id),
            ).fetchone()
            if window is None or window["session_key"] != session_key:
                raise ValueError("Transcript identity does not belong to the requested session_key")
            before = window["transcript_updated_at"]
            if expected_mutation_at is not UNSET:
                matches = (before is None if expected_mutation_at is None else
                           _finite(expected_mutation_at) and before == expected_mutation_at)
                if not matches:
                    raise SqliteTranscriptMutationConflictError(session_id)
            records = db.execute(
                "SELECT seq,event_json FROM memory_session_events WHERE agent=? AND session_id=? ORDER BY seq",
                (self.agent_id, session_id),
            ).fetchall()
            events = [json.loads(row["event_json"]) for row in records]

            def replay(index: int, key: str) -> dict[str, Any]:
                event = events[index]
                if not messages_match_for_replay(event.get("message"), persisted):
                    raise TranscriptTurnAdmissionConflictError(key)
                result = {
                    "appended": False, "effectiveParentId": event.get("parentId"),
                    "message": event.get("message"), "messageId": event["id"],
                }
                anchor = self._message_anchor(db, session_id, session_key, events, event, records[index]["seq"])
                if anchor is not None:
                    result["anchor"] = anchor
                return result

            if admission_key:
                for index, event in enumerate(events):
                    if isinstance(event, dict) and message_idempotency_key(event.get("message")) == admission_key:
                        return replay(index, admission_key)
            identifier = event_id if event_id is not None else str(uuid4())
            for index, event in enumerate(events):
                if isinstance(event, dict) and isinstance(event.get("id"), str) and js_trim(event["id"]) == identifier:
                    if "message" not in event:
                        raise RuntimeError(f"SQLite transcript append did not insert message {identifier}.")
                    return replay(index, admission_key or f"event:{identifier}")

            state = db.execute(
                "SELECT generation,projection_dirty FROM memory_session_transcript_state WHERE agent=? AND session_id=?",
                (self.agent_id, session_id),
            ).fetchone()
            generation = state["generation"] if state is not None else uuid4().hex
            dirty = bool(state["projection_dirty"]) if state is not None else bool(events)
            clock = self._clock()
            seq = records[-1]["seq"] if records else 0
            mutation = before

            def insert(event: dict[str, Any]) -> None:
                nonlocal seq, mutation
                seq += 1
                text = _json(event)
                db.execute("INSERT INTO memory_session_events VALUES(?,?,?,?,?)", (
                    self.agent_id, session_id, seq, text,
                    len(js_utf8_encode(js_json_stringify(event))),
                ))
                events.append(event)
                mutation = max(clock, (mutation if mutation is not None else -1) + 1,
                               (window["transcript_observed_at"] if window["transcript_observed_at"] is not None else -1) + 1)

            if not events:
                insert({"type": "session", "version": 4, "id": session_id,
                        "timestamp": timestamp_ms_to_iso(clock), "cwd": cwd if cwd is not None else os.getcwd()})
            parent = resolve_message_append_parent(events, parent_id, append_intent)
            event = {"type": "message", "id": identifier, "parentId": parent,
                     "timestamp": timestamp_ms_to_iso(now_ms if now_ms is not None else clock),
                     "message": persisted}
            dirty |= not can_forward_project_event(events, event)
            insert(event)
            db.execute(
                "INSERT INTO memory_session_transcript_state VALUES(?,?,?,?) "
                "ON CONFLICT(agent,session_id) DO UPDATE SET generation=excluded.generation,projection_dirty=excluded.projection_dirty",
                (self.agent_id, session_id, generation, int(dirty)),
            )
            db.execute(
                "UPDATE memory_session_windows SET revision=revision+1,transcript_updated_at=?,mutation_at=?,updated_at=? "
                "WHERE agent=? AND session_id=?",
                (mutation, mutation, now_ms if now_ms is not None else clock, self.agent_id, session_id),
            )
            self._changed(db)
            result = {"appended": True, "effectiveParentId": parent,
                      "message": persisted, "messageId": identifier}
            anchor = self._message_anchor(db, session_id, session_key, events, event, seq)
            if anchor is not None:
                result["anchor"] = anchor
            return result

    def read_anchor(
        self, session_id: str, entry_id: str, *, session_key: str,
    ) -> dict[str, Any] | None:
        """Read a certified active-message identity in the current SQLite snapshot."""
        catalog = self._transcript_catalog(session_id, session_key)
        if catalog is None:
            return None
        if catalog is not self:
            return catalog.read_anchor(session_id, entry_id, session_key=session_key)
        session_key = self._session_key(session_key)
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            window = db.execute(
                "SELECT session_key FROM memory_session_windows WHERE agent=? AND session_id=?",
                (self.agent_id, session_id),
            ).fetchone()
            if window is None or window[0] != session_key:
                return None
            records = db.execute(
                "SELECT seq,event_json FROM memory_session_events WHERE agent=? AND session_id=? ORDER BY seq",
                (self.agent_id, session_id),
            ).fetchall()
            events = [json.loads(row["event_json"]) for row in records]
            for index, event in enumerate(events):
                if isinstance(event, dict) and event.get("id") == entry_id:
                    return self._message_anchor(db, session_id, session_key, events, event, records[index]["seq"])
            return None

    def remove_session(self, session_key: str) -> None:
        catalog = self._key_catalog(session_key)
        if catalog is None:
            return
        if catalog is not self:
            return catalog.remove_session(session_key)
        session_key = self._session_key(session_key)
        with closing(self._connect()) as db, db:
            db.execute("DELETE FROM memory_session_nodes WHERE agent=? AND session_key=?", (self.agent_id, session_key))
            db.execute("DELETE FROM memory_session_participants WHERE agent=? AND session_key=?", (self.agent_id, session_key))
            self._changed(db)

    def record_participant(
        self, session_key: str, record: Mapping[str, Any], *, agent_id: str | None = None,
    ) -> str | None:
        """Record a prompted identity without granting transcript visibility.

        ``profile_aliases`` is an optional trusted profile-registry reader. Alias
        observations update the first retained alias row while preserving its ID.
        """
        identity = record["identity"]
        actor_id = identity.get("id")
        if not actor_id or (identity.get("type") == "agent" and actor_id == record.get("sessionAgentId")):
            return None
        catalog = self._key_catalog(session_key, create=True)
        if catalog is not self:
            return catalog.record_participant(session_key, record, agent_id=catalog.agent_id)
        session_key = self._session_key(session_key)
        agent = self._scope(agent_id)
        namespace = _participant_namespace(identity)
        # Node's SQLite bindings replace unmatched UTF-16 surrogate code units.
        bound_actor_id = js_utf8_encode(actor_id).decode("utf-8")
        prompted_at = record.get("promptedAt")
        if prompted_at is None:
            prompted_at = self._clock()
        aliases = None
        if identity.get("type") == "profile":
            aliases = {actor_id, *(self._profile_aliases(actor_id) if self._profile_aliases else ())}
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT actor_id,contribution_count,first_prompted_at,last_prompted_at "
                "FROM memory_session_participants WHERE agent=? AND session_key=? "
                "AND identity_namespace=? AND actor_id=?",
                (agent, session_key, namespace, bound_actor_id),
            ).fetchone()
            if existing is not None and existing["actor_id"] != actor_id:
                existing = None
            if existing is None and aliases and len(aliases) > 1:
                existing = next((row for row in db.execute(
                    "SELECT actor_id,contribution_count,first_prompted_at,last_prompted_at "
                    "FROM memory_session_participants WHERE agent=? AND session_key=? "
                    "AND identity_namespace=? ORDER BY actor_id", (agent, session_key, namespace),
                ) if row["actor_id"] in aliases), None)
            if existing is None:
                count = db.execute(
                    "SELECT COUNT(*) FROM memory_session_participants WHERE agent=? AND session_key=?",
                    (agent, session_key),
                ).fetchone()[0]
                if count >= 32:
                    return "capped"
                count, first, last = 1, prompted_at, prompted_at
            else:
                count = existing["contribution_count"] + 1
                first = (None if existing["first_prompted_at"] is None else
                         min(existing["first_prompted_at"], prompted_at))
                last = (prompted_at if existing["last_prompted_at"] is None else
                        max(existing["last_prompted_at"], prompted_at))
            db.execute(
                "INSERT INTO memory_session_participants VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(agent,session_key,identity_namespace,actor_id) DO UPDATE SET "
                "contribution_count=excluded.contribution_count,first_prompted_at=excluded.first_prompted_at,"
                "last_prompted_at=excluded.last_prompted_at",
                (agent, session_key, namespace, existing["actor_id"] if existing else bound_actor_id,
                 count, first, last),
            )
            self._changed(db)
            return "updated" if existing is not None else "inserted"

    def list_participants(
        self, session_key: str | None = None, *, agent_id: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return full persisted participant aggregates in the native SQL order."""
        catalog = self._key_catalog(session_key)
        if catalog is None:
            return {}
        if catalog is not self:
            return catalog.list_participants(session_key, agent_id=catalog.agent_id)
        session_key = self._session_key(session_key)
        agent = self._scope(agent_id)
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            sql = "SELECT * FROM memory_session_participants WHERE agent=?"
            parameters: tuple[Any, ...] = (agent,)
            if session_key:
                sql += " AND session_key=?"
                parameters += (session_key,)
            sql += " ORDER BY session_key,first_prompted_at,actor_id,identity_namespace"
            result: dict[str, list[dict[str, Any]]] = {}
            for row in db.execute(sql, parameters):
                result.setdefault(row["session_key"], []).append({
                    "identity": _read_participant_identity(row["identity_namespace"], row["actor_id"]),
                    "contributionCount": row["contribution_count"],
                    "firstPromptedAt": row["first_prompted_at"], "lastPromptedAt": row["last_prompted_at"],
                })
            return result

    def record_archive(
        self, archive_name: str, session_id: str, *, session_key: str | None = None,
        path: str | Path | None = None,
    ) -> None:
        catalog = self._key_catalog(session_key, create=True)
        if catalog is not self:
            return catalog.record_archive(archive_name, session_id, session_key=session_key, path=path)
        session_key = self._session_key(session_key)
        archive_path = Path(path).resolve() if path is not None else self.store_path.parent / archive_name
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO memory_session_archives VALUES(?,?,?,?,?) ON CONFLICT(agent,archive_name) "
                       "DO UPDATE SET session_id=excluded.session_id,session_key=excluded.session_key,path=excluded.path",
                       (self.agent_id, archive_name, session_id, session_key, str(archive_path)))
            self._changed(db)

    def tombstone_session(self, session_id: str, *, session_key: str | None = None) -> None:
        catalog = self._transcript_catalog(session_id, session_key)
        if catalog is None:
            catalog = self._key_catalog(session_key, create=True)
        if catalog is not self:
            return catalog.tombstone_session(session_id, session_key=session_key)
        session_key = self._session_key(session_key)
        with closing(self._connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO memory_session_tombstones VALUES(?,?)", (self.agent_id, session_id))
            self._changed(db)

    def snapshot(self) -> SessionCatalogSnapshot:
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            entries = {row["session_key"]: json.loads(row["entry_json"]) for row in db.execute(
                "SELECT session_key,entry_json FROM memory_session_nodes WHERE agent=? ORDER BY session_key", (self.agent_id,)
            ) if not _internal_key(row["session_key"])}
            instances = tuple(SessionTranscriptInstance(
                self.agent_id, row["session_key"], row["session_id"], _window_entry(row),
                bool(row["provenance_known"]), bool(row["acp_owned"]), row["transcript_updated_at"],
            ) for row in db.execute("SELECT * FROM memory_session_windows WHERE agent=? AND transcript_updated_at IS NOT NULL "
                                   "ORDER BY transcript_updated_at DESC,session_id", (self.agent_id,))
                              if not _internal_key(row["session_key"]))
            archives = tuple(SessionTranscriptArchive(
                row["archive_name"], row["session_id"], row["session_key"], Path(row["path"]), self.agent_id,
            ) for row in db.execute("SELECT * FROM memory_session_archives WHERE agent=? ORDER BY archive_name", (self.agent_id,)))
            forgotten = frozenset(row[0] for row in db.execute(
                "SELECT session_id FROM memory_session_tombstones WHERE agent=?", (self.agent_id,)
            ))
            revision = db.execute("SELECT revision FROM memory_session_catalog_state WHERE agent=?", (self.agent_id,)).fetchone()[0]
            return SessionCatalogSnapshot(entries, instances, archives, forgotten, revision)

    def list_transcript_instances(
        self, *, session_id: str | None = None, include_all_windows: bool = False,
    ) -> list[dict[str, Any]]:
        """Project persisted current/retained windows through the host history contract.

        Retained instances carry window-owned classification fields, while the
        current incarnation additionally carries its complete current entry.
        The raw ``snapshot`` remains the catalog's internal admission authority.
        """
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            current_entries = {row["session_key"]: _project_session_participants(
                db, self.agent_id, row["session_key"], json.loads(row["entry_json"]),
            ) for row in db.execute(
                "SELECT session_key,entry_json FROM memory_session_nodes WHERE agent=?", (self.agent_id,),
            )}
            sql = "SELECT * FROM memory_session_windows WHERE agent=?"
            parameters: tuple[Any, ...] = (self.agent_id,)
            if not include_all_windows:
                sql += " AND transcript_updated_at IS NOT NULL"
            if session_id is not None:
                sql += " AND session_id=?"
                parameters += (session_id,)
            sql += " ORDER BY transcript_updated_at DESC,session_id"
            result = []
            for row in db.execute(sql, parameters):
                key = row["session_key"]
                if not include_all_windows and _internal_key(key):
                    continue
                recorded = json.loads(row["entry_json"])
                current = current_entries.get(key)
                exact = current is not None and current.get("sessionId") == row["session_id"]
                known = bool(row["provenance_known"])
                updated = row["transcript_updated_at"] if row["transcript_updated_at"] is not None else row["updated_at"]
                entry = dict(current) if exact else {}
                entry.update(sessionId=row["session_id"], updatedAt=updated)
                for field in ("parentSessionKey", "spawnedBy"):
                    if js_truthy(recorded.get(field)):
                        entry[field] = recorded[field]
                        if field == "spawnedBy":
                            entry["spawnDepth"] = 1
                chat_type = recorded.get("chatType")
                chat_type = chat_type if isinstance(chat_type, str) and chat_type in {"direct", "group", "channel"} else None
                if chat_type:
                    entry["chatType"] = chat_type
                if known and row["plugin_owner_id"]:
                    entry["pluginOwnerId"] = row["plugin_owner_id"]
                hook = row["hook_external_content_source"]
                hook = hook if hook in {"gmail", "webhook"} else None
                if known and hook:
                    entry["hookExternalContentSource"] = hook
                exact_hook = current.get("hookExternalContentSource") if exact else None
                if exact_hook is None:
                    exact_hook = "gmail" if known and hook == "gmail" else None
                channel, account = _source_delivery_facts(recorded)
                result.append({
                    "agentId": resolve_session_agent_id(key, self.agent_id),
                    "acpOwned": bool(row["acp_owned"]) or bool(exact and js_truthy(current.get("acp"))),
                    "entry": entry, "provenanceKnown": known,
                    "sessionId": row["session_id"], "sessionKey": key, "updatedAtMs": updated,
                    "sourceMetadata": {"createdAt": row["created_at"], "channel": channel,
                                       "accountId": account, "chatType": chat_type,
                                       "hookExternalContentSource": exact_hook},
                })
            return result

    def read_transcript(
        self, session_id: str, *, agent_id: str | None = None, session_key: str | None = None,
    ) -> SessionTranscriptSnapshot | None:
        catalog = self._transcript_catalog(session_id, session_key)
        if catalog is None:
            return None
        if catalog is not self:
            return catalog.read_transcript(session_id, agent_id=catalog.agent_id,
                                           session_key=session_key)
        session_key = self._session_key(session_key)
        agent = self._scope(agent_id)
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM memory_session_windows WHERE agent=? AND session_id=?", (agent, session_id)).fetchone()
            if row is None:
                return None
            if session_key is not None:
                active = db.execute("SELECT entry_json FROM memory_session_nodes WHERE agent=? AND session_key=?", (agent, session_key)).fetchone()
                owns_active = active is not None and json.loads(active[0]).get("sessionId") == session_id
                if not owns_active and row["session_key"] != session_key:
                    return None
            records = db.execute("SELECT event_json,byte_size FROM memory_session_events WHERE agent=? AND session_id=? ORDER BY seq",
                                 (agent, session_id)).fetchall()
            return SessionTranscriptSnapshot(tuple(json.loads(record[0]) for record in records),
                                             row["session_key"], row["transcript_updated_at"] if row["transcript_updated_at"] is not None else row["updated_at"], row["revision"],
                                             sum(record[1] for record in records) + max(0, len(records) - 1),
                                             row["mutation_at"])

    def read_reset_cutoff(
        self, session_id: str, *, agent_id: str | None = None, session_key: str | None = None,
    ) -> dict[str, Any]:
        transcript = self.read_transcript(session_id, agent_id=agent_id, session_key=session_key)
        return resolve_session_reset_recall_cutoff(list(transcript.events)) if transcript is not None else {"state": "invalid"}

    def read_continuation(
        self, session_id: str, *, session_key: str, agent_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Reconstruct continuation from one committed transcript/metadata snapshot.

        This is raw host context acquisition. A caller exposing a session to
        another actor must still apply the session visibility policy. It does
        not run a model, a turn barrier or the memory-flush scheduler.
        """
        from memory_core.session_context import (
            build_session_context, convert_to_llm, is_session_history_prelude,
        )

        catalog = self._transcript_catalog(session_id, session_key)
        if catalog is None:
            return None
        if catalog is not self:
            return catalog.read_continuation(session_id, session_key=session_key,
                                             agent_id=catalog.agent_id)
        session_key = self._session_key(session_key)
        agent = self._scope(agent_id)
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            window = db.execute(
                "SELECT * FROM memory_session_windows WHERE agent=? AND session_id=?",
                (agent, session_id),
            ).fetchone()
            if window is None or window["session_key"] != session_key:
                return None
            active = db.execute(
                "SELECT entry_json FROM memory_session_nodes WHERE agent=? AND session_key=?",
                (agent, session_key),
            ).fetchone()
            records = db.execute(
                "SELECT seq,event_json FROM memory_session_events WHERE agent=? AND session_id=? ORDER BY seq",
                (agent, session_id),
            ).fetchall()
            state = db.execute(
                "SELECT generation FROM memory_session_transcript_state WHERE agent=? AND session_id=?",
                (agent, session_id),
            ).fetchone()
            events = [json.loads(row["event_json"]) for row in records]
            visible = select_visible_transcript_events(events)
            context = build_session_context(visible)
            llm_messages = convert_to_llm(context["messages"])
            return {
                "entry": _project_session_participants(db, agent, session_key, json.loads(active[0])) if active is not None else None,
                "instanceEntry": json.loads(window["entry_json"]), "events": events,
                "visibleEvents": visible, "context": context, "llmMessages": llm_messages,
                "historyPrelude": [is_session_history_prelude(message) for message in context["messages"]],
                "modelHistoryPrelude": [is_session_history_prelude(message) for message in llm_messages],
                "version": {"rawSeq": records[-1]["seq"] - 1 if records else None,
                            "generation": state["generation"] if state is not None else None,
                            "updatedAt": window["transcript_updated_at"]},
            }

    def load_session_metadata(self, origin: Mapping[str, str], store_path: str | None = None) -> dict[str, Any] | None:
        catalog = self._key_catalog(origin.get("sessionKey"))
        if catalog is None:
            return None
        if catalog is not self:
            return catalog.load_session_metadata(
                {**origin, "agentId": catalog.agent_id}, str(catalog.store_path),
            )
        origin = {**origin, **({"sessionKey": self._session_key(origin["sessionKey"])} if "sessionKey" in origin else {})}
        self._scope(origin.get("agentId"))
        if store_path is not None and Path(store_path).resolve() != self.store_path:
            raise ValueError("Session metadata belongs to a different catalog store")
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            row = db.execute(
                "SELECT * FROM memory_session_windows WHERE agent=? AND session_id=?",
                (self.agent_id, origin.get("sessionId")),
            ).fetchone()
            if row is None or (origin.get("sessionKey") and row["session_key"] != origin["sessionKey"]):
                return None
            parts = row["session_key"].split(":", 2)
            owner = normalize_session_agent_id(parts[1]) if len(parts) == 3 and parts[0] == "agent" else self.agent_id
            if owner != self.agent_id:
                return None
            recorded = json.loads(row["entry_json"])
            active = db.execute(
                "SELECT entry_json FROM memory_session_nodes WHERE agent=? AND session_key=?",
                (self.agent_id, row["session_key"]),
            ).fetchone()
            current = json.loads(active[0]) if active is not None else {}
            exact = current.get("sessionId") == row["session_id"]
            channel, account = _source_delivery_facts(recorded)
            chat_type = recorded.get("chatType")
            chat_type = chat_type if isinstance(chat_type, str) and chat_type in {"direct", "group", "channel"} else None
            hook = current.get("hookExternalContentSource") if exact else None
            if hook is None:
                hook = "gmail" if row["provenance_known"] and row["hook_external_content_source"] == "gmail" else None
            return {
                "agentId": self.agent_id, "sessionId": row["session_id"],
                "sessionKey": row["session_key"], "resolution": "live",
                "createdAt": row["created_at"], "channel": channel, "accountId": account,
                "chatType": chat_type, "hookExternalContentSource": hook, "participants": [],
            }
