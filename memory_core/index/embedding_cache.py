"""Persistent embedding reuse for the pinned OpenClaw cache contract.

The caller owns the connection and transaction. Cache writes do not publish an
index revision, and a caller can retain a valid generated batch even when later
index publication fails. Source freshness and generation checks belong to that
caller, not to this storage kernel.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import sqlite3
import struct
import time
from typing import Any

from memory_core.index.identity import UNDEFINED


MEMORY_EMBEDDING_CACHE_TABLE = "memory_embedding_cache"
EMBEDDING_CACHE_BATCH_SIZE = 400
MALFORMED_VECTOR_RESPONSE = (
    "memory embeddings: malformed vector response (count, dimensions, or coordinates)"
)


def ensure_embedding_cache_schema(db: sqlite3.Connection) -> None:
    """Create the derived cache without changing existing rows or committing."""
    db.execute(
        """CREATE TABLE IF NOT EXISTS memory_embedding_cache (
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            provider_key TEXT NOT NULL,
            hash TEXT NOT NULL,
            embedding BLOB NOT NULL,
            dims INTEGER,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (provider, model, provider_key, hash)
        ) STRICT"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_embedding_cache_updated_at "
        "ON memory_embedding_cache(updated_at)"
    )


def _finite_number(value: object) -> bool:
    # JavaScript booleans are not numeric coordinates. Large Python integers
    # which cannot inhabit a finite binary64 value are equally unusable.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def is_valid_memory_embedding(embedding: object, dimensions: object = UNDEFINED) -> bool:
    """Native ``isValidMemoryEmbedding``: nonempty finite array, strict size."""
    return (
        isinstance(embedding, list)
        and len(embedding) > 0
        and (dimensions is UNDEFINED
             or (not isinstance(dimensions, bool) and isinstance(dimensions, (int, float))
                 and len(embedding) == dimensions))
        and all(_finite_number(coordinate) for coordinate in embedding)
    )


def encode_memory_embedding(embedding: Sequence[float]) -> bytes:
    """Encode finite coordinates as host-independent little-endian binary64."""
    if not all(_finite_number(coordinate) for coordinate in embedding):
        raise ValueError("Memory embeddings require finite numeric coordinates")
    return b"".join(struct.pack("<d", coordinate) for coordinate in embedding)


def decode_memory_embedding(value: object) -> list[float]:
    """Corrupt derived vectors remain unusable instead of entering retrieval."""
    if not isinstance(value, (bytes, bytearray, memoryview)) or len(value) % 8:
        return []
    embedding = [coordinate[0] for coordinate in struct.iter_unpack("<d", value)]
    return embedding if all(math.isfinite(coordinate) for coordinate in embedding) else []


def load_memory_embedding_cache(
    db: sqlite3.Connection,
    *,
    enabled: bool,
    provider_identities: Sequence[Mapping[str, Any]],
    hashes: Sequence[str],
) -> dict[str, list[float]]:
    """Load the first available provider identity for each requested hash.

    A corrupt first identity deliberately wins as an empty, unusable entry;
    borrowing a later alias would conceal the need to regenerate that vector.
    The caller must also reconcile dimensions across the returned vectors.
    """
    if not enabled or not provider_identities or not hashes:
        return {}
    unresolved = dict.fromkeys(value for value in hashes if value)
    out: dict[str, list[float]] = {}
    for identity in provider_identities:
        if not unresolved:
            break
        remaining = list(unresolved)
        for start in range(0, len(remaining), EMBEDDING_CACHE_BATCH_SIZE):
            batch = remaining[start:start + EMBEDDING_CACHE_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            rows = db.execute(
                "SELECT hash, embedding, (dims IS NULL OR dims = length(embedding) / 8) "
                "AS dimensions_match FROM memory_embedding_cache "
                "WHERE provider = ? AND model = ? AND provider_key = ? "
                f"AND hash IN ({placeholders})",
                (identity["provider"], identity["model"], identity["providerKey"], *batch),
            )
            for chunk_hash, raw, dimensions_match in rows:
                embedding = decode_memory_embedding(raw)
                out[chunk_hash] = (
                    embedding if dimensions_match and is_valid_memory_embedding(embedding) else []
                )
                unresolved.pop(chunk_hash, None)
    return out


def clear_memory_embedding_cache_identities(
    db: sqlite3.Connection, identities: Sequence[Mapping[str, Any]],
) -> None:
    """Invalidate only the supplied vector spaces, leaving index rows alone."""
    for identity in identities:
        db.execute(
            "DELETE FROM memory_embedding_cache "
            "WHERE provider = ? AND model = ? AND provider_key = ?",
            (identity["provider"], identity["model"], identity["providerKey"]),
        )


def _cache_capacity(max_entries: object) -> int | None:
    if _finite_number(max_entries) and max_entries > 0:  # type: ignore[operator]
        return math.floor(max_entries)  # type: ignore[arg-type]
    return None


def upsert_memory_embedding_cache(
    db: sqlite3.Connection,
    *,
    enabled: bool,
    provider: Mapping[str, Any] | None,
    provider_key: str | None,
    entries: Sequence[Mapping[str, Any] | None],
    max_entries: object = None,
    now: int | None = None,
) -> None:
    """Retain last-occurrence entries, with native global oldest-row eviction.

    This storage kernel encodes each row as it is written. Provider response
    validation must happen before calling it: the native orchestration validates
    the complete generated batch first, while this function follows its caller's
    transaction boundaries on encoding/SQL failures.
    """
    if not enabled or provider is None or not provider_key or not entries:
        return
    seen: set[str] = set()
    unique: list[Mapping[str, Any]] = []
    for entry in reversed(entries):
        if entry is not None and entry["hash"] not in seen:
            seen.add(entry["hash"])
            unique.append(entry)
    unique.reverse()
    capacity = _cache_capacity(max_entries)
    # JavaScript slice(-0) starts at zero. Preserve the positive fractional
    # capacity boundary instead of silently changing the native kernel result.
    retained = unique if capacity in (None, 0) else unique[-capacity:]
    if not retained:
        return
    if capacity is not None:
        hashes = [entry["hash"] for entry in retained]
        for start in range(0, len(hashes), EMBEDDING_CACHE_BATCH_SIZE):
            batch = hashes[start:start + EMBEDDING_CACHE_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            db.execute(
                "DELETE FROM memory_embedding_cache "
                "WHERE provider = ? AND model = ? AND provider_key = ? "
                f"AND hash IN ({placeholders})",
                (provider["id"], provider["model"], provider_key, *batch),
            )
        db.execute(
            "DELETE FROM memory_embedding_cache WHERE rowid IN ("
            "SELECT rowid FROM memory_embedding_cache "
            "ORDER BY updated_at DESC, rowid DESC LIMIT -1 OFFSET ?)",
            (capacity - len(hashes),),
        )
    timestamp = time.time_ns() // 1_000_000 if now is None else now
    for entry in retained:
        embedding = entry.get("embedding")
        if embedding is None:
            embedding = []
        db.execute(
            "INSERT INTO memory_embedding_cache "
            "(provider, model, provider_key, hash, embedding, dims, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(provider, model, provider_key, hash) DO UPDATE SET "
            "embedding=excluded.embedding, dims=excluded.dims, updated_at=excluded.updated_at",
            (provider["id"], provider["model"], provider_key, entry["hash"],
             encode_memory_embedding(embedding), len(embedding), timestamp),
        )


def _chunk_hash(chunk: object) -> str | None:
    if isinstance(chunk, Mapping):
        return chunk.get("hash")
    return getattr(chunk, "hash", None)


def collect_memory_cached_embeddings(
    chunks: Sequence[Any], cached: Mapping[str, list[float]],
) -> dict[str, list]:
    """Place reusable vectors back at their chunk positions without mutation."""
    embeddings: list[list[float]] = [[] for _ in chunks]
    missing = []
    for index, chunk in enumerate(chunks):
        chunk_hash = _chunk_hash(chunk)
        hit = cached.get(chunk_hash) if chunk_hash else None
        if hit is not None and len(hit) > 0:
            embeddings[index] = hit
        elif chunk is not None:
            missing.append({"index": index, "chunk": chunk})
    return {"embeddings": embeddings, "missing": missing}


def validate_memory_embedding_batch(
    embeddings: object, expected_count: int, dimensions: int | None = None,
) -> int | None:
    """Reject an entire malformed provider response before any vector is cached.

    ``None`` here is the orchestration's unknown dimension, not an explicit
    JavaScript null size argument. Return the validated active dimension.
    """
    if not isinstance(embeddings, list) or len(embeddings) != expected_count:
        raise ValueError(MALFORMED_VECTOR_RESPONSE)
    if dimensions is None and embeddings:
        first = embeddings[0]
        dimensions = len(first) if isinstance(first, list) else None
    expected = UNDEFINED if dimensions is None else dimensions
    if not all(is_valid_memory_embedding(embedding, expected) for embedding in embeddings):
        raise ValueError(MALFORMED_VECTOR_RESPONSE)
    return dimensions
