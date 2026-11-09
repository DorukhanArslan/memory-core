"""The memory-entry origins ledger: which sessions a promoted MEMORY.md entry came from.

Port of OpenClaw v2026.9.6 ``extensions/memory-core/src/memory-entry-origins.ts`` and the SQLite
half of ``packages/memory-host-sdk/src/memory-entry-origins.ts``: the ``memory_entry_origins``
table (``entry_key, agent_id, session_id`` key; ``session_key``, ``origin_class``,
``observed_at``), recording, listing and deleting rows, :func:`reserve_memory_entry_origins`
(a merged or superseding entry inherits the sessions of every parent entry; the returned
callback rolls the new rows back) and :func:`prune_memory_entry_origins` (drops the rows of keys
that no longer appear in MEMORY.md, a preimage, the recall store, a DREAMS.md diary or an
indexed MEMORY chunk).

The ledger is a real SQLite database written through the standard library's ``sqlite3``, with
upstream's DDL, ``STRICT`` table and conflict rule (``ON CONFLICT DO NOTHING``), so a file written
by either implementation reads in the other. Where the database lives is the host's decision
(upstream: one ``openclaw-agent.sqlite`` per agent in the state directory), hence the
``path_for_agent`` callable. The session tombstones (``memory_session_tombstones``: a forgotten
session is never ingested again) and the ``memory_index_state`` revision fence (a counter every
tombstone bumps, so an index rebuild prepared before the forget is rejected at publication, see
:class:`MemoryIndexRevisionConflictError`) live in the same database. Upstream's agent database
always carries ``memory_index_state``; here :meth:`MemoryEntryOriginLedger.record_session_tombstones`
creates it (seeded at revision 0) when the host's index has not. The index publication that consults
the fence (``publishMemoryDatabaseTables``) is :meth:`SQLiteMemoryStore.reindex` with an
:class:`IndexRevisionFence`, and the forget flow that writes the tombstones is
:mod:`memory_core.consolidation.forget` (it uses :meth:`record_session_tombstones_if_lineage_current`,
upstream's guarded ``marked`` transaction).

Reads never create the database or the table (upstream: ``withOpenClawAgentDatabaseReadOnly`` and
``tableExists``); recording creates both. A ``memory_index_chunks`` table in the same database is
read by pruning the way upstream reads the agent index; without it (or without a database) no
indexed key is retained and pruning proceeds, which upstream does when the database is absent.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable, Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from memory_core.bootstrap._js import js_trim
from memory_core.consolidation.markers import PROMOTION_MARKER_PREFIXES, extract_promotion_markers
from memory_core.runtime_identity import RuntimeIdentity

OriginClass = Literal["owner", "agent", "untrusted", "system"]

_SCHEMA = """CREATE TABLE IF NOT EXISTS memory_entry_origins (
    entry_key TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    session_key TEXT,
    origin_class TEXT NOT NULL CHECK (origin_class IN ('owner', 'agent', 'untrusted', 'system')),
    observed_at INTEGER NOT NULL,
    PRIMARY KEY (entry_key, agent_id, session_id)
  ) STRICT"""

# ``reserveMemoryEntryOrigins`` reads the marker line above a prior entry with this exact pattern
# (one prefix there; both here, like every other reader).
_MARKER_LINE_RE = re.compile(
    r"^<!--\s*(?:" + "|".join(re.escape(prefix) for prefix in PROMOTION_MARKER_PREFIXES) + r")([^\n]*?)\s*-->$"
)


_TOMBSTONE_SCHEMA = """CREATE TABLE IF NOT EXISTS memory_session_tombstones (
      session_id TEXT NOT NULL PRIMARY KEY,
      agent_id TEXT NOT NULL,
      reason TEXT NOT NULL,
      created_at INTEGER NOT NULL
    ) STRICT"""

_INDEX_STATE_SCHEMA = """CREATE TABLE IF NOT EXISTS memory_index_state (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      revision INTEGER NOT NULL
    ) STRICT"""

# Four bindings per row stay below SQLite's historical 999-variable default.
TOMBSTONE_INSERT_BATCH_SIZE = 128


class MemoryIndexRevisionConflictError(Exception):
    """``MemoryIndexRevisionConflictError``: the index changed while a full reindex was building."""


@dataclass(frozen=True)
class MemorySessionTombstone:
    """``MemorySessionTombstone``: a session whose memory was forgotten."""

    session_id: str
    agent_id: str
    reason: str
    created_at: int


@dataclass(frozen=True)
class MemoryEntryOrigin:
    """``MemoryEntryOrigin``: one session that contributed to one promoted entry."""

    entry_key: str
    agent_id: str
    session_id: str
    session_key: str | None
    origin_class: OriginClass
    observed_at: int


class ConsolidationOriginOperation(Protocol):
    """The part of a consolidation operation :func:`reserve_memory_entry_origins` reads."""

    @property
    def candidate_key(self) -> str: ...

    @property
    def action(self) -> str: ...

    @property
    def prior_entries(self) -> Sequence[str]: ...


def _row_to_origin(row: sqlite3.Row | tuple) -> MemoryEntryOrigin:
    return MemoryEntryOrigin(
        entry_key=row[0],
        agent_id=row[1],
        session_id=row[2],
        session_key=row[3],
        origin_class=row[4],
        observed_at=row[5],
    )


class MemoryEntryOriginLedger:
    """The origins ledger of a set of agents; ``path_for_agent`` names each agent's database."""

    def __init__(
        self,
        path_for_agent: Callable[[str], str | Path],
        *,
        indexed_promotion_keys: Callable[[str], set[str] | None] | None = None,
    ) -> None:
        self._path_for_agent = path_for_agent
        self._indexed_promotion_keys = indexed_promotion_keys

    # -- connections --------------------------------------------------------------------

    def database_path(self, agent_id: str) -> Path:
        return Path(self._path_for_agent(agent_id))

    def _open_write(self, agent_id: str) -> sqlite3.Connection:
        path = self.database_path(agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path, isolation_level=None, timeout=30)
        db.execute(_SCHEMA)
        return db

    def _open_read(self, agent_id: str) -> sqlite3.Connection | None:
        path = self.database_path(agent_id)
        if not path.exists():
            return None
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None, timeout=30)

    @staticmethod
    def _table_exists(db: sqlite3.Connection, name: str) -> bool:
        return (
            db.execute("SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = ?", (name,)).fetchone()
            is not None
        )

    # -- reads --------------------------------------------------------------------------

    def list(
        self,
        agent_id: str,
        *,
        session_ids: Sequence[str] | None = None,
        entry_keys: Sequence[str] | None = None,
    ) -> list[MemoryEntryOrigin]:
        """``listMemoryEntryOrigins``: rows ordered by ``entry_key`` then ``session_id``."""
        if session_ids is not None and len(session_ids) == 0:
            return []
        if entry_keys is not None and len(entry_keys) == 0:
            return []
        db = self._open_read(agent_id)
        if db is None:
            return []
        with closing(db):
            if not self._table_exists(db, "memory_entry_origins"):
                return []
            return self._read(db, agent_id, session_ids, entry_keys)

    @staticmethod
    def _read(
        db: sqlite3.Connection,
        agent_id: str,
        session_ids: Sequence[str] | None,
        entry_keys: Sequence[str] | None,
    ) -> list[MemoryEntryOrigin]:
        sql = (
            "SELECT entry_key, agent_id, session_id, session_key, origin_class, observed_at "
            "FROM memory_entry_origins WHERE agent_id = ?"
        )
        params: list[object] = [agent_id]
        # Binding counts are bounded the way upstream's callers bound them; chunk long lists.
        if session_ids is not None:
            sql += f" AND session_id IN ({','.join('?' * len(session_ids))})"
            params.extend(session_ids)
        if entry_keys is not None:
            sql += f" AND entry_key IN ({','.join('?' * len(entry_keys))})"
            params.extend(entry_keys)
        sql += " ORDER BY entry_key ASC, session_id ASC"
        return [_row_to_origin(row) for row in db.execute(sql, params)]

    # -- writes -------------------------------------------------------------------------

    def record(
        self,
        agent_id: str,
        origins: Sequence[MemoryEntryOrigin],
        *,
        entry_key: str | None = None,
    ) -> list[MemoryEntryOrigin]:
        """``recordMemoryEntryOrigins``: insert new rows, return the ones actually added.

        ``entry_key`` re-keys every origin onto one entry (how a merged entry inherits its
        parents' sessions). An existing ``(entry_key, agent_id, session_id)`` row is kept.
        """
        if not origins:
            return []
        with closing(self._open_write(agent_id)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                added: list[MemoryEntryOrigin] = []
                for origin in origins:
                    if origin.agent_id != agent_id:
                        raise ValueError("memory entry origin belongs to another agent")
                    key = entry_key if entry_key is not None else origin.entry_key
                    cursor = db.execute(
                        "INSERT INTO memory_entry_origins "
                        "(entry_key, agent_id, session_id, session_key, origin_class, observed_at) "
                        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (entry_key, agent_id, session_id) DO NOTHING",
                        (
                            key,
                            origin.agent_id,
                            origin.session_id,
                            origin.session_key,
                            origin.origin_class,
                            origin.observed_at,
                        ),
                    )
                    if cursor.rowcount == 1:
                        added.append(
                            MemoryEntryOrigin(
                                key,
                                origin.agent_id,
                                origin.session_id,
                                origin.session_key,
                                origin.origin_class,
                                origin.observed_at,
                            )
                        )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return added

    def delete(
        self,
        agent_id: str,
        entry_keys: Sequence[str],
        session_ids: Sequence[str] | None = None,
    ) -> int:
        """``deleteMemoryEntryOrigins``: remove the rows of ``entry_keys`` (and ``session_ids``)."""
        if not entry_keys or (session_ids is not None and len(session_ids) == 0):
            return 0
        reader = self._open_read(agent_id)
        if reader is None:
            return 0
        with closing(reader):
            if not self._table_exists(reader, "memory_entry_origins"):
                return 0
            if not self._read(reader, agent_id, session_ids, list(entry_keys)):
                return 0
        with closing(self._open_write(agent_id)) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                sql = (
                    "DELETE FROM memory_entry_origins WHERE agent_id = ? "
                    f"AND entry_key IN ({','.join('?' * len(entry_keys))})"
                )
                params: list[object] = [agent_id, *entry_keys]
                if session_ids is not None:
                    sql += f" AND session_id IN ({','.join('?' * len(session_ids))})"
                    params.extend(session_ids)
                removed = db.execute(sql, params).rowcount
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return removed

    # -- session tombstones and the index revision fence ---------------------------------

    def list_session_tombstones(
        self, agent_id: str, session_ids: Sequence[str] | None = None
    ) -> list[MemorySessionTombstone]:
        """``listMemorySessionTombstones``: the agent's tombstones ordered by session id."""
        if session_ids is not None and len(session_ids) == 0:
            return []
        db = self._open_read(agent_id)
        if db is None:
            return []
        with closing(db):
            if not self._table_exists(db, "memory_session_tombstones"):
                return []
            sql = (
                "SELECT session_id, agent_id, reason, created_at FROM memory_session_tombstones "
                "WHERE agent_id = ?"
            )
            params: list[object] = [agent_id]
            if session_ids is not None:
                sql += f" AND session_id IN ({','.join('?' * len(session_ids))})"
                params.extend(session_ids)
            sql += " ORDER BY session_id ASC"
            return [MemorySessionTombstone(*row) for row in db.execute(sql, params)]

    def record_session_tombstones(
        self,
        agent_id: str,
        session_ids: Sequence[str],
        *,
        reason: str = "forgotten",
        created_at: int | None = None,
    ) -> int:
        """``recordMemorySessionTombstonesInDatabase``: tombstone sessions, return how many were new.

        One immediate transaction. A recorded tombstone bumps the index revision, so a rebuild
        prepared before this call fails :meth:`assert_index_revision` (the fence holds even when
        the shadow index has no published chunks yet). Already tombstoned sessions are kept.
        """
        unique = list(dict.fromkeys(session_ids))
        if not unique:
            return 0
        stamp = int(time.time() * 1000) if created_at is None else created_at
        with closing(self._open_write(agent_id)) as db:
            db.execute(_TOMBSTONE_SCHEMA)
            db.execute(_INDEX_STATE_SCHEMA)
            db.execute("INSERT OR IGNORE INTO memory_index_state (id, revision) VALUES (1, 0)")
            db.execute("BEGIN IMMEDIATE")
            try:
                recorded = 0
                for start in range(0, len(unique), TOMBSTONE_INSERT_BATCH_SIZE):
                    for session_id in unique[start : start + TOMBSTONE_INSERT_BATCH_SIZE]:
                        recorded += db.execute(
                            "INSERT INTO memory_session_tombstones (session_id, agent_id, reason, created_at) "
                            "VALUES (?, ?, ?, ?) ON CONFLICT (session_id) DO NOTHING",
                            (session_id, agent_id, reason, stamp),
                        ).rowcount
                if recorded > 0:
                    db.execute("UPDATE memory_index_state SET revision = revision + 1 WHERE id = 1")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return recorded

    def record_session_tombstones_if_lineage_current(
        self,
        agent_id: str,
        session_ids: Sequence[str],
        *,
        is_current: Callable[[list[MemoryEntryOrigin]], bool],
        reason: str = "forgotten",
        created_at: int | None = None,
    ) -> bool:
        """The forget flow's guarded tombstone write (``memory-forget.ts``, the ``marked`` transaction).

        One immediate transaction: the agent's origin rows are read inside it, ``is_current`` decides
        whether the lineage the forget planned against still holds (``False`` rolls back and returns
        ``False``: the caller plans again), the sessions are tombstoned and the index revision is bumped
        (:meth:`record_session_tombstones` bumps when a tombstone is new; a session that was already
        tombstoned still bumps, so every forget fences a rebuild that started before it).
        """
        unique = list(dict.fromkeys(session_ids))
        stamp = int(time.time() * 1000) if created_at is None else created_at
        with closing(self._open_write(agent_id)) as db:
            db.execute(_TOMBSTONE_SCHEMA)
            db.execute(_INDEX_STATE_SCHEMA)
            db.execute("INSERT OR IGNORE INTO memory_index_state (id, revision) VALUES (1, 0)")
            db.execute("BEGIN IMMEDIATE")
            try:
                origins = (
                    self._read(db, agent_id, None, None)
                    if self._table_exists(db, "memory_entry_origins")
                    else []
                )
                if not is_current(origins):
                    db.execute("ROLLBACK")
                    return False
                recorded = 0
                for start in range(0, len(unique), TOMBSTONE_INSERT_BATCH_SIZE):
                    for session_id in unique[start : start + TOMBSTONE_INSERT_BATCH_SIZE]:
                        recorded += db.execute(
                            "INSERT INTO memory_session_tombstones (session_id, agent_id, reason, created_at) "
                            "VALUES (?, ?, ?, ?) ON CONFLICT (session_id) DO NOTHING",
                            (session_id, agent_id, reason, stamp),
                        ).rowcount
                db.execute("UPDATE memory_index_state SET revision = revision + 1 WHERE id = 1")
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        return True

    def index_revision(self, agent_id: str) -> int | None:
        """``readMemoryDatabaseRevision``: the index revision, ``None`` without a database or state row."""
        db = self._open_read(agent_id)
        if db is None:
            return None
        with closing(db):
            if not self._table_exists(db, "memory_index_state"):
                return None
            row = db.execute("SELECT revision FROM memory_index_state WHERE id = 1").fetchone()
        return row[0] if row is not None else None

    def bump_index_revision(self, agent_id: str) -> None:
        """The revision bump of an index mutation (upstream's triggers on the index tables)."""
        with closing(self._open_write(agent_id)) as db:
            db.execute(_INDEX_STATE_SCHEMA)
            db.execute("INSERT OR IGNORE INTO memory_index_state (id, revision) VALUES (1, 0)")
            db.execute("UPDATE memory_index_state SET revision = revision + 1 WHERE id = 1")

    def assert_index_revision(self, agent_id: str, expected_revision: int) -> None:
        """The publication fence: raise :class:`MemoryIndexRevisionConflictError` when the index moved on."""
        live = self.index_revision(agent_id)
        if live is None:
            raise ValueError("Memory index revision is missing or invalid")
        if live != expected_revision:
            raise MemoryIndexRevisionConflictError(_conflict_message(expected_revision, live))

    def revision_fence(self, agent_id: str) -> IndexRevisionFence:
        """The fence an index passes to :class:`~memory_core.index.sqlite_store.SQLiteMemoryStore`."""
        return IndexRevisionFence(self, agent_id)

    # -- the index ----------------------------------------------------------------------

    def indexed_promotion_keys(self, agent_id: str, *, identity: RuntimeIdentity | None = None) -> set[str] | None:
        """Promotion keys inside the agent's indexed MEMORY chunks, ``None`` when it has no database.

        Upstream reads ``memory_index_chunks`` (``source = 'memory'``, text containing a promotion
        marker) of the agent's database; the host can supply its own reader instead.
        """
        if self._indexed_promotion_keys is not None:
            # This callback is the host's opaque source authority. Its selected
            # keys cannot be re-filtered without its underlying source text.
            return self._indexed_promotion_keys(agent_id)
        db = self._open_read(agent_id)
        if db is None:
            return None
        with closing(db):
            if not self._table_exists(db, "memory_index_chunks"):
                return set()
            keys: set[str] = set()
            prefixes = PROMOTION_MARKER_PREFIXES if identity is None else (identity.promotion_marker_prefix,)
            for (text,) in db.execute(
                "SELECT text FROM memory_index_chunks WHERE source = 'memory' AND ("
                + " OR ".join("text LIKE ?" for _ in prefixes)
                + ")",
                [f"%{prefix}%" for prefix in prefixes],
            ):
                keys.update(extract_promotion_markers(text, identity=identity))
            return keys


class IndexRevisionFence:
    """The ``memory_index_state`` revision fence of one agent, for an index that publishes a rebuild.

    Upstream's full reindex (``manager-sync-ops.ts``) reads the database revision before it builds the
    shadow index (:meth:`read`) and publishes it in one immediate transaction that first compares the
    live revision (``publishMemoryDatabaseTables``): a forget that tombstoned a session, or any other
    index mutation, in between bumps the revision and the publication fails with
    :class:`MemoryIndexRevisionConflictError`. :class:`~memory_core.index.sqlite_store.SQLiteMemoryStore`
    takes a fence (``revision_fence=``) and does the same around :meth:`SQLiteMemoryStore.reindex`.

    When the index lives in the ledger's own database file (``same_database``) the check and the bump
    run on the index's connection, inside its publication transaction (atomic, like upstream); for a
    separate index file the check runs just before the publication transaction and the bump just after
    it (a forget landing between them is not fenced: a labelled deviation).
    """

    def __init__(self, ledger: MemoryEntryOriginLedger, agent_id: str) -> None:
        self._ledger = ledger
        self.agent_id = agent_id

    @property
    def database_path(self) -> Path:
        return self._ledger.database_path(self.agent_id)

    def same_database(self, path: str | Path) -> bool:
        try:
            return self.database_path.resolve() == Path(path).resolve()
        except OSError:
            return False

    def read(self) -> int | None:
        """The live revision, ``None`` while the database or its state row does not exist."""
        return self._ledger.index_revision(self.agent_id)

    def assert_unchanged(self, expected: int | None) -> None:
        """Raise :class:`MemoryIndexRevisionConflictError` when the revision is not ``expected``."""
        live = self.read()
        if live != expected:
            raise MemoryIndexRevisionConflictError(_conflict_message(expected, live))

    def assert_unchanged_in(self, db: sqlite3.Connection, expected: int | None) -> None:
        """:meth:`assert_unchanged` on the index's own connection (``same_database``)."""
        db.execute(_INDEX_STATE_SCHEMA)
        row = db.execute("SELECT revision FROM memory_index_state WHERE id = 1").fetchone()
        live = row[0] if row is not None else None
        if live != expected:
            raise MemoryIndexRevisionConflictError(_conflict_message(expected, live))

    def bump(self) -> None:
        self._ledger.bump_index_revision(self.agent_id)

    def bump_in(self, db: sqlite3.Connection) -> None:
        db.execute(_INDEX_STATE_SCHEMA)
        db.execute("INSERT OR IGNORE INTO memory_index_state (id, revision) VALUES (1, 0)")
        db.execute("UPDATE memory_index_state SET revision = revision + 1 WHERE id = 1")


def _conflict_message(expected: int | None, live: int | None) -> str:
    return (
        "Memory index changed while full reindex was building "
        f"(expected revision {expected}, found {live}); retry the full reindex."
    )


def reserve_memory_entry_origins(
    ledger: MemoryEntryOriginLedger,
    *,
    agent_ids: Iterable[str],
    previous_memory: str,
    operations: Sequence[ConsolidationOriginOperation],
) -> Callable[[], None]:
    """``reserveMemoryEntryOrigins``: give each candidate the sessions of its parents; return the rollback.

    The parents of an operation are its candidate key and the key of the marker line above each of
    its prior entries in ``previous_memory``. Agents are visited in sorted order. A failure rolls
    back what was reserved and re-raises; the returned callback rolls back a successful reserve
    (newest first), removing only the rows this call added.
    """
    previous_lines = previous_memory.replace("\r\n", "\n").split("\n")
    operation_parents = []
    for operation in operations:
        parent_keys = {operation.candidate_key}
        for entry in operation.prior_entries:
            entry_index = next(
                (index for index, line in enumerate(previous_lines) if js_trim(line) == entry), -1
            )
            # previousLines[-1] and previousLines[-2] are undefined in JavaScript, not the last lines.
            marker = js_trim(previous_lines[entry_index - 1]) if entry_index - 1 >= 0 else None
            match = _MARKER_LINE_RE.fullmatch(marker) if marker is not None else None
            parent_key = js_trim(match.group(1)) if match else ""
            if parent_key:
                parent_keys.add(parent_key)
        operation_parents.append((operation, parent_keys))
    affected_keys = list(dict.fromkeys(key for _op, keys in operation_parents for key in keys))
    reservations: list[tuple[str, list[str], list[str]]] = []

    def rollback() -> None:
        for agent_id, entry_keys, session_ids in reversed(reservations):
            ledger.delete(agent_id, entry_keys, session_ids)

    try:
        for agent_id in sorted(set(agent_ids)):
            origins = ledger.list(agent_id, entry_keys=affected_keys)
            for operation, parent_keys in operation_parents:
                added = ledger.record(
                    agent_id,
                    [origin for origin in origins if origin.entry_key in parent_keys],
                    entry_key=operation.candidate_key,
                )
                if added:
                    reservations.append(
                        (agent_id, [operation.candidate_key], [origin.session_id for origin in added])
                    )
    except BaseException:
        rollback()
        raise
    return rollback


def prune_memory_entry_origins(
    ledger: MemoryEntryOriginLedger,
    *,
    workspace_dir: str | Path,
    agent_ids: Iterable[str],
    entry_keys: Iterable[str],
    retained_entry_keys: set[str] | frozenset[str],
    identity: RuntimeIdentity | None = None,
) -> None:
    """``pruneMemoryEntryOrigins``: drop the rows of ``entry_keys`` nothing retains any more.

    Retained: ``retained_entry_keys``, every key of the workspace's DREAMS.md / dreams.md diaries
    (so a diary keeps its origins through backup rotation) and, per agent, every key an indexed
    MEMORY chunk of that agent's index still carries. Callers hold the workspace lock.
    """
    from memory_core.consolidation.artifacts import DREAMS_FILENAMES, read_dreams_file

    keys = [key for key in dict.fromkeys(entry_keys) if key not in retained_entry_keys]
    if not keys:
        return
    diary_keys: set[str] = set()
    for name in DREAMS_FILENAMES:
        diary_keys.update(extract_promotion_markers(read_dreams_file(Path(workspace_dir) / name), identity=identity))
    for agent_id in dict.fromkeys(agent_ids):
        indexed = (ledger.indexed_promotion_keys(agent_id) if identity is None
                   else ledger.indexed_promotion_keys(agent_id, identity=identity))
        ledger.delete(
            agent_id,
            [
                key
                for key in keys
                if key not in diary_keys and not (indexed is not None and key in indexed)
            ],
        )
