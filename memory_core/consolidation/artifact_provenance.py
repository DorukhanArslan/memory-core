"""Trust records of workspace memory files: which daily notes the flush quarantined.

Port of OpenClaw v2026.9.6 ``src/memory/memory-artifact-provenance.ts``: for each workspace memory
file (``MEMORY.md``, ``memory.md``, ``USER.md``, ``users/<id>/USER.md`` and ``memory/*.md`` except
``memory/dreaming/`` and ``memory/.dreams/``) the store holds the hash of the content last written
by a trusted writer, its origin class (``agent`` or ``untrusted``) and when it was observed.
:func:`MemoryArtifactProvenanceStore.record_write` keeps ``agent`` only while the file still has
the content the previous trusted write left; any other writer (or an edit in between) downgrades it
to ``untrusted``, and that stays sticky across later writes. The promotion apply stage reads the
records through :meth:`MemoryArtifactProvenanceStore.list` and treats every candidate of an
``untrusted`` daily file as untrusted (``withDailyFileQuarantine``, see
:func:`with_daily_file_quarantine`).

Upstream keeps the records in a SQLite-backed plugin-state keyed store
(``core:memory-artifact-provenance`` / ``workspace-files``, at most 50,000 entries, new keys
rejected when full). Here the store is a small SQLite file of the host's choosing with the same
key (``<sha256 of the physical workspace path>:<sha256 of the relative path>``), the same record
shape and the same rejection of new keys when full; the file format is not shared with OpenClaw.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import uuid
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

ArtifactOriginClass = Literal["agent", "untrusted"]

MEMORY_ARTIFACT_PROVENANCE_MAX_ENTRIES = 50_000

_USER_FILE_RE = re.compile(r"^users/[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}/USER\.md$")
_HASH_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class MemoryArtifactProvenance:
    """``MemoryArtifactProvenance``: the trust record of one file."""

    file_hash: str
    origin_class: ArtifactOriginClass
    observed_at: int
    session_id: str | None = None
    session_key: str | None = None


class MemoryArtifactProvenanceFullError(Exception):
    """The store is at its entry limit and refuses a new file (``overflowPolicy: "reject-new"``)."""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()


def normalize_workspace_key(workspace_dir: str | Path) -> str:
    """``normalizeWorkspaceKey``: the physical workspace path, so symlink aliases share records."""
    resolved = os.path.abspath(workspace_dir)
    try:
        canonical = os.path.realpath(resolved, strict=True)
    except FileNotFoundError:
        canonical = resolved
    normalized = canonical.replace("\\", "/")
    return normalized.lower() if sys.platform == "win32" else normalized


def normalize_memory_artifact_relative_path(relative_path: str) -> str | None:
    """``normalizeMemoryArtifactRelativePath``: the tracked form of a path, ``None`` when not tracked."""
    normalized = relative_path.replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return None
    if normalized in ("MEMORY.md", "memory.md", "USER.md") or _USER_FILE_RE.match(normalized):
        return normalized
    if not normalized.startswith("memory/") or not normalized.endswith(".md"):
        return None
    if normalized.startswith(("memory/dreaming/", "memory/.dreams/")):
        return None
    return normalized


class MemoryArtifactProvenanceStore:
    """The trust records of every workspace of a host, in one SQLite file."""

    def __init__(
        self, path: str | Path, *, max_entries: int = MEMORY_ARTIFACT_PROVENANCE_MAX_ENTRIES
    ) -> None:
        self.path = Path(path)
        self.max_entries = max_entries

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        db.execute(
            "CREATE TABLE IF NOT EXISTS memory_artifact_provenance "
            "(store_key TEXT NOT NULL PRIMARY KEY, value TEXT NOT NULL) STRICT"
        )
        return db

    @staticmethod
    def _address(workspace_dir: str | Path, relative_path: str) -> tuple[str, str, str] | None:
        relative = normalize_memory_artifact_relative_path(relative_path)
        if relative is None:
            return None
        workspace_key = _sha256(normalize_workspace_key(workspace_dir))
        return workspace_key, relative, f"{workspace_key}:{_sha256(relative)}"

    @staticmethod
    def _normalize(raw: str | None, workspace_key: str, relative: str) -> dict[str, Any] | None:
        """``normalizeStoredProvenance``: a record that does not describe this address reads as absent."""
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except ValueError:
            return None
        if (
            not isinstance(value, dict)
            or value.get("version") != 1
            or value.get("workspaceKey") != workspace_key
            or value.get("relativePath") != relative
            or not isinstance(value.get("fileHash"), str)
            or not _HASH_RE.match(value["fileHash"])
            or value.get("originClass") not in ("agent", "untrusted")
            or not isinstance(value.get("observedAt"), int)
            or isinstance(value.get("observedAt"), bool)
            or not isinstance(value.get("reservationId"), str)
            or not value["reservationId"]
        ):
            return None
        return value

    @staticmethod
    def _public(stored: dict[str, Any]) -> MemoryArtifactProvenance:
        return MemoryArtifactProvenance(
            file_hash=stored["fileHash"],
            origin_class=stored["originClass"],
            observed_at=stored["observedAt"],
            session_id=stored.get("sessionId") or None,
            session_key=stored.get("sessionKey") or None,
        )

    def record_write(
        self,
        *,
        workspace_dir: str | Path,
        relative_path: str,
        content_before: str,
        content_after: str,
        origin_class: ArtifactOriginClass,
        observed_at: int,
        session_id: str | None = None,
        session_key: str | None = None,
    ) -> Callable[[], None] | None:
        """``recordMemoryArtifactWriteProvenance``: record a write, return its rollback.

        The record stays ``agent`` only when the writer is trusted and the file had no record or
        its previous ``agent`` record still matches ``content_before``. ``None`` for an untracked
        path. The rollback restores the previous record (or removes the new one) unless a later
        write replaced it.
        """
        address = self._address(workspace_dir, relative_path)
        if address is None:
            return None
        workspace_key, relative, store_key = address
        reservation_id = str(uuid.uuid4())
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT value FROM memory_artifact_provenance WHERE store_key = ?", (store_key,)
                ).fetchone()
                raw_previous = row[0] if row else None
                previous = self._normalize(raw_previous, workspace_key, relative)
                trusted = origin_class == "agent" and (
                    previous is None
                    or (previous["originClass"] == "agent" and previous["fileHash"] == _sha256(content_before))
                )
                record = {
                    "version": 1,
                    "workspaceKey": workspace_key,
                    "relativePath": relative,
                    "fileHash": _sha256(content_after),
                    "originClass": "agent" if trusted else "untrusted",
                    "observedAt": observed_at,
                    **({"sessionId": session_id} if session_id else {}),
                    **({"sessionKey": session_key} if session_key else {}),
                    "reservationId": reservation_id,
                }
                if row is None:
                    (count,) = db.execute("SELECT count(*) FROM memory_artifact_provenance").fetchone()
                    if count >= self.max_entries:
                        raise MemoryArtifactProvenanceFullError(
                            "memory artifact provenance store is full"
                        )
                db.execute(
                    "INSERT INTO memory_artifact_provenance (store_key, value) VALUES (?, ?) "
                    "ON CONFLICT (store_key) DO UPDATE SET value = excluded.value",
                    (store_key, json.dumps(record)),
                )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

        def rollback() -> None:
            with closing(self._connect()) as rollback_db:
                rollback_db.execute("BEGIN IMMEDIATE")
                try:
                    current = rollback_db.execute(
                        "SELECT value FROM memory_artifact_provenance WHERE store_key = ?",
                        (store_key,),
                    ).fetchone()
                    current_value = None
                    if current is not None:
                        try:
                            current_value = json.loads(current[0])
                        except ValueError:
                            current_value = None
                    owned = isinstance(current_value, dict) and current_value.get("reservationId") == reservation_id
                    if owned and previous is not None:
                        rollback_db.execute(
                            "UPDATE memory_artifact_provenance SET value = ? WHERE store_key = ?",
                            (raw_previous, store_key),
                        )
                    elif owned:
                        rollback_db.execute(
                            "DELETE FROM memory_artifact_provenance WHERE store_key = ?", (store_key,)
                        )
                    rollback_db.execute("COMMIT")
                except BaseException:
                    rollback_db.execute("ROLLBACK")
                    raise

        return rollback

    def clear(self, *, workspace_dir: str | Path, relative_path: str, content_before: str) -> None:
        """``clearMemoryArtifactProvenance``: forget the record while it still matches ``content_before``."""
        address = self._address(workspace_dir, relative_path)
        if address is None:
            return
        _workspace_key, _relative, store_key = address
        expected = _sha256(content_before)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT value FROM memory_artifact_provenance WHERE store_key = ?", (store_key,)
                ).fetchone()
                if row is not None:
                    try:
                        value = json.loads(row[0])
                    except ValueError:
                        value = None
                    if isinstance(value, dict) and value.get("fileHash") == expected:
                        db.execute(
                            "DELETE FROM memory_artifact_provenance WHERE store_key = ?", (store_key,)
                        )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def read(self, *, workspace_dir: str | Path, relative_path: str) -> MemoryArtifactProvenance | None:
        """``readMemoryArtifactProvenance``: the record of one file, ``None`` when absent or unreadable."""
        address = self._address(workspace_dir, relative_path)
        if address is None:
            return None
        workspace_key, relative, store_key = address
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT value FROM memory_artifact_provenance WHERE store_key = ?", (store_key,)
            ).fetchone()
        stored = self._normalize(row[0] if row else None, workspace_key, relative)
        return self._public(stored) if stored else None

    def list(self, workspace_dir: str | Path) -> list[tuple[str, MemoryArtifactProvenance]]:
        """``listMemoryArtifactProvenance``: ``(relative path, record)`` of every readable record of the workspace."""
        workspace_key = _sha256(normalize_workspace_key(workspace_dir))
        prefix = f"{workspace_key}:"
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT store_key, value FROM memory_artifact_provenance ORDER BY store_key"
            ).fetchall()
        records: list[tuple[str, MemoryArtifactProvenance]] = []
        for store_key, raw in rows:
            if not store_key.startswith(prefix):
                continue
            try:
                relative = json.loads(raw).get("relativePath")
            except (ValueError, AttributeError):
                continue
            if not isinstance(relative, str):
                continue
            stored = self._normalize(raw, workspace_key, relative)
            if stored is not None:
                records.append((relative, self._public(stored)))
        return records


def daily_file_quarantine_by_path(
    records: list[tuple[str, MemoryArtifactProvenance]],
) -> dict[str, MemoryArtifactProvenance]:
    """The ``dailyProvenanceByPath`` map of the apply stage (later records win, like ``new Map``)."""
    return {relative.replace("\\", "/"): record for relative, record in records}


def with_daily_file_quarantine(candidate: Any, provenance_by_path: dict[str, MemoryArtifactProvenance]) -> Any:
    """``withDailyFileQuarantine``: every candidate of an ``untrusted`` daily file turns ``untrusted``.

    Sticky at the file boundary: a trusted line of a quarantined file cannot promote either. The
    candidate's session kind is kept and ``observedAt`` becomes the record's.
    """
    record = provenance_by_path.get(candidate.path.replace("\\", "/"))
    if record is None or record.origin_class != "untrusted":
        return candidate
    provenance = candidate.provenance or {}
    session_kind = provenance.get("sessionKind")
    return replace(
        candidate,
        provenance={
            "originClass": "untrusted",
            "sessionKind": session_kind if session_kind is not None else "unknown",
            "observedAt": record.observed_at,
        },
    )
