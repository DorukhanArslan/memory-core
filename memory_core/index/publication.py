"""Prepared index rows shared by ordinary refresh and atomic publication.

Preparation owns source inspection, chunking, embedding and trust decisions.
Publication preserves those explicit facts, including provenance and recall
metadata, as one SQLite revision. It does not invent those decisions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import sqlite3

from memory_core.bootstrap._js import js_utf8_encode
from memory_core.index.identity import INDEX_SOURCES_TABLE, MEMORY_INDEX_META_KEY


CHUNK_DETAILS_TABLE = "memory_index_chunk_details"
CHUNK_PROVENANCE_TABLE = "memory_index_chunk_provenance"
CHUNK_RECALL_TABLE = "memory_index_chunk_recall_metadata"


@dataclass(frozen=True)
class ChunkProvenance:
    origin_class: str = "untrusted"
    session_kind: str = "unknown"
    observed_at: int = 0
    supersedes_key: str | None = None


@dataclass(frozen=True)
class ChunkRecallMetadata:
    importance: int | None = None
    # The native owner stores TEXT. Parsing configured trigger expressions is
    # preparation/ranking work, so publication retains the supplied bytes.
    triggers: str | None = None
    project_key: str | None = None


@dataclass(frozen=True)
class PreparedChunk:
    id: str
    path: str
    source: str
    start_line: int
    end_line: int
    text: str
    embedding: tuple[float, ...]
    hash: str
    model: str
    updated_at: int
    provenance: ChunkProvenance = field(default_factory=ChunkProvenance)
    recall: ChunkRecallMetadata = field(default_factory=ChunkRecallMetadata)

    def __post_init__(self) -> None:
        object.__setattr__(self, "embedding", tuple(self.embedding))


@dataclass(frozen=True)
class PreparedSource:
    path: str
    source: str
    hash: str
    mtime: float
    size: int
    chunks: tuple[PreparedChunk, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "chunks", tuple(self.chunks))


@dataclass(frozen=True)
class PreparedIndexRevision:
    sources: tuple[PreparedSource, ...]
    metadata_json: str
    workspace: str | None = None
    replace_all: bool = True
    removed_sources: tuple[tuple[str, str], ...] = ()
    metadata_key: str = MEMORY_INDEX_META_KEY

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "removed_sources", tuple(tuple(key) for key in self.removed_sources))


def ensure_publication_schema(db: sqlite3.Connection) -> None:
    """Add metadata owners without changing the existing seven-column chunks.

    Legacy rows have no trustworthy observation timestamp or origin. Backfill
    that absence explicitly and invalidate their source fingerprints so normal
    refresh replaces them through the prepared publication path.
    """
    db.execute(
        f"CREATE TABLE IF NOT EXISTS {CHUNK_DETAILS_TABLE} ("
        "chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE, "
        "hash TEXT NOT NULL, model TEXT NOT NULL, updated_at INTEGER NOT NULL) STRICT"
    )
    db.execute(
        f"CREATE TABLE IF NOT EXISTS {CHUNK_PROVENANCE_TABLE} ("
        "chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE, "
        "origin_class TEXT NOT NULL CHECK (origin_class IN ('owner','agent','untrusted','system')), "
        "session_kind TEXT NOT NULL CHECK (session_kind IN "
        "('interactive','cron','heartbeat','subagent','unknown')), "
        "observed_at INTEGER NOT NULL, supersedes_key TEXT) STRICT"
    )
    db.execute(
        f"CREATE TABLE IF NOT EXISTS {CHUNK_RECALL_TABLE} ("
        "chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE, "
        "importance INTEGER CHECK (importance IS NULL OR importance BETWEEN 1 AND 10), "
        "triggers TEXT, project_key TEXT) STRICT"
    )
    missing = db.execute(
        "SELECT c.id, c.path, c.source, c.text FROM chunks c "
        f"LEFT JOIN {CHUNK_DETAILS_TABLE} d ON d.chunk_id=c.id "
        f"LEFT JOIN {CHUNK_PROVENANCE_TABLE} p ON p.chunk_id=c.id "
        f"LEFT JOIN {CHUNK_RECALL_TABLE} r ON r.chunk_id=c.id "
        "WHERE d.chunk_id IS NULL OR p.chunk_id IS NULL OR r.chunk_id IS NULL"
    ).fetchall()
    for chunk_id, path, source, text in missing:
        db.execute(f"UPDATE {INDEX_SOURCES_TABLE} SET hash='' WHERE source=? AND path=?", (source, path))
        db.execute(
            f"INSERT OR IGNORE INTO {CHUNK_DETAILS_TABLE} VALUES (?, ?, ?, ?)",
            (chunk_id, hashlib.sha256(js_utf8_encode(text)).hexdigest(), "legacy-unknown", 0),
        )
        db.execute(
            f"INSERT OR IGNORE INTO {CHUNK_PROVENANCE_TABLE} VALUES (?, 'untrusted', 'unknown', 0, NULL)",
            (chunk_id,),
        )
        db.execute(f"INSERT OR IGNORE INTO {CHUNK_RECALL_TABLE} VALUES (?, NULL, NULL, NULL)", (chunk_id,))


def missing_metadata_sources(db: sqlite3.Connection) -> set[tuple[str, str]]:
    return set(db.execute(
        "SELECT DISTINCT c.source, c.path FROM chunks c "
        f"LEFT JOIN {CHUNK_DETAILS_TABLE} d ON d.chunk_id=c.id "
        f"LEFT JOIN {CHUNK_PROVENANCE_TABLE} p ON p.chunk_id=c.id "
        f"LEFT JOIN {CHUNK_RECALL_TABLE} r ON r.chunk_id=c.id "
        "WHERE d.chunk_id IS NULL OR p.chunk_id IS NULL OR r.chunk_id IS NULL"
    ))


def write_prepared_index(db: sqlite3.Connection, prepared: PreparedIndexRevision) -> None:
    """Write one complete/selected revision inside the caller's transaction."""
    keys = [(entry.source, entry.path) for entry in prepared.sources]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate prepared memory source")
    if prepared.replace_all:
        db.execute("DELETE FROM chunks")
        db.execute("DELETE FROM chunks_fts")
        db.execute("DELETE FROM paths_fts")
        db.execute(f"DELETE FROM {INDEX_SOURCES_TABLE}")
        # Foreign keys remove owned rows. Clear pre-existing orphans too, as
        # full native publication replaces every derived metadata table.
        for table in (CHUNK_DETAILS_TABLE, CHUNK_PROVENANCE_TABLE, CHUNK_RECALL_TABLE):
            db.execute(f"DELETE FROM {table}")
    else:
        db.execute("DELETE FROM chunks_fts WHERE id NOT IN (SELECT id FROM chunks)")
        for table in (CHUNK_DETAILS_TABLE, CHUNK_PROVENANCE_TABLE, CHUNK_RECALL_TABLE):
            db.execute(f"DELETE FROM {table} WHERE chunk_id NOT IN (SELECT id FROM chunks)")
        for source, path in set(keys) | set(prepared.removed_sources):
            db.execute(
                "DELETE FROM chunks_fts WHERE id IN "
                "(SELECT id FROM chunks WHERE source=? AND path=?)", (source, path),
            )
            db.execute("DELETE FROM chunks WHERE source=? AND path=?", (source, path))
            db.execute("DELETE FROM paths_fts WHERE source=? AND path=?", (source, path))
            db.execute(f"DELETE FROM {INDEX_SOURCES_TABLE} WHERE source=? AND path=?", (source, path))
    for entry in prepared.sources:
        # Empty sources are still eligible file/path search inputs upstream.
        db.execute("INSERT INTO paths_fts(path, source) VALUES (?, ?)", (entry.path, entry.source))
        for chunk in entry.chunks:
            if (chunk.path, chunk.source) != (entry.path, entry.source):
                raise ValueError("Prepared chunk does not belong to its source")
            db.execute(
                "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chunk.id, chunk.path, chunk.start_line, chunk.end_line, chunk.source,
                 chunk.text, json.dumps(list(chunk.embedding), allow_nan=False)),
            )
            db.execute("INSERT INTO chunks_fts(id, text) VALUES (?, ?)", (chunk.id, chunk.text))
            db.execute(f"INSERT INTO {CHUNK_DETAILS_TABLE} VALUES (?, ?, ?, ?)",
                       (chunk.id, chunk.hash, chunk.model, chunk.updated_at))
            p, r = chunk.provenance, chunk.recall
            db.execute(f"INSERT INTO {CHUNK_PROVENANCE_TABLE} VALUES (?, ?, ?, ?, ?)",
                       (chunk.id, p.origin_class, p.session_kind, p.observed_at, p.supersedes_key))
            db.execute(f"INSERT INTO {CHUNK_RECALL_TABLE} VALUES (?, ?, ?, ?)",
                       (chunk.id, r.importance, r.triggers, r.project_key))
        db.execute(f"INSERT INTO {INDEX_SOURCES_TABLE} VALUES (?, ?, ?, ?, ?, ?)",
                   (entry.source, entry.path, entry.hash, entry.mtime, entry.size, len(entry.chunks)))
    db.execute(
        "INSERT INTO memory_index_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (prepared.metadata_key, prepared.metadata_json),
    )


def read_published_rows(db: sqlite3.Connection, revision: int) -> dict:
    """Read all published state, retaining separate metadata/orphan evidence."""
    def records(sql: str, names: tuple[str, ...]) -> list[dict]:
        return [dict(zip(names, row, strict=True)) for row in db.execute(sql)]

    provenance = records(
        f"SELECT chunk_id,origin_class,session_kind,observed_at,supersedes_key FROM {CHUNK_PROVENANCE_TABLE} ORDER BY chunk_id",
        ("chunkId", "originClass", "sessionKind", "observedAt", "supersedesKey"),
    )
    recall = records(
        f"SELECT chunk_id,importance,triggers,project_key FROM {CHUNK_RECALL_TABLE} ORDER BY chunk_id",
        ("chunkId", "importance", "triggers", "projectKey"),
    )
    details = records(
        f"SELECT chunk_id,hash,model,updated_at FROM {CHUNK_DETAILS_TABLE} ORDER BY chunk_id",
        ("chunkId", "hash", "model", "updatedAt"),
    )
    by_provenance = {row["chunkId"]: row for row in provenance}
    by_recall = {row["chunkId"]: row for row in recall}
    by_details = {row["chunkId"]: row for row in details}
    chunks = records("SELECT id,path,source,start_line,end_line,text,embedding FROM chunks ORDER BY id",
                     ("id", "path", "source", "startLine", "endLine", "text", "embedding"))
    for chunk in chunks:
        chunk["embedding"] = json.loads(chunk["embedding"])
        for collection in (by_details,):
            chunk.update({key: value for key, value in collection.get(chunk["id"], {}).items() if key != "chunkId"})
        chunk["provenance"] = {key: value for key, value in by_provenance.get(chunk["id"], {}).items() if key != "chunkId"}
        chunk["recall"] = {key: value for key, value in by_recall.get(chunk["id"], {}).items() if key != "chunkId"}
    return {
        "revision": revision,
        "sources": records(f"SELECT path,source,hash,mtime,size FROM {INDEX_SOURCES_TABLE} ORDER BY source,path",
                           ("path", "source", "hash", "mtime", "size")),
        "chunks": chunks,
        "fts": records("SELECT f.id,f.text,c.path,c.source,c.start_line,c.end_line,d.model FROM chunks_fts f "
                       "LEFT JOIN chunks c ON c.id=f.id "
                       f"LEFT JOIN {CHUNK_DETAILS_TABLE} d ON d.chunk_id=f.id ORDER BY f.id,f.text",
                       ("id", "text", "path", "source", "startLine", "endLine", "model")),
        "paths": records("SELECT path,source FROM paths_fts ORDER BY source,path", ("path", "source")),
        "provenance": provenance, "recall": recall, "details": details,
        "meta": records("SELECT key,value FROM memory_index_meta ORDER BY key", ("key", "value")),
    }
