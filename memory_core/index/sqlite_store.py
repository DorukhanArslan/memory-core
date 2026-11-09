from __future__ import annotations

import dataclasses
from copy import deepcopy
import errno
import hashlib
import json
import math
import os
import sqlite3
import stat
import time
import unicodedata
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, TypeVar

from memory_core.cancellation import CancellationSignal
from memory_core.tools.deadline import MemorySearchDeadlineControl
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.consolidation.origins import IndexRevisionFence, MemoryIndexRevisionConflictError
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.index.chunking import MemoryChunk, chunk_markdown
from memory_core.index.embedding_limits import enforce_embedding_max_input_tokens
from memory_core.index.embedding_cache import (
    clear_memory_embedding_cache_identities,
    collect_memory_cached_embeddings,
    ensure_embedding_cache_schema,
    is_valid_memory_embedding,
    load_memory_embedding_cache,
    upsert_memory_embedding_cache,
    validate_memory_embedding_batch,
)
from memory_core.index.fts import bm25_rank_to_score, build_fts_query
from memory_core.bootstrap._js import js_json_stringify, js_trim, js_utf8_encode, locale_sort_key
from memory_core.index.cjk_chars import truncate_utf16_safe
from memory_core.index.hybrid import (
    HYBRID_METADATA_MISSING,
    HybridKeywordResult,
    HybridResult,
    HybridVectorResult,
    _project_score_multiplier,
    apply_importance_multiplier,
    apply_project_ranking,
    merge_hybrid_results,
    score_exact_path_tie_for_temporal_decay,
    select_hybrid_search_results,
)
from memory_core.index.keyword_search import (
    EXACT_PATH_CANDIDATE_LIMIT,
    SNIPPET_MAX_CHARS,
    KeywordHit,
    build_exact_path_candidate_patterns,
    keyword_hit_sort_key,
    limit_keyword_search_hits,
    merge_keyword_search_hits,
    normalized_literal_contains,
    prepare_exact_path_matcher,
    prepare_query_matchers,
    score_fallback_keyword_result,
)
from memory_core.index.identity import (
    DEFAULT_FTS_TOKENIZER,
    FTS_ONLY_MODEL,
    INDEX_SOURCES_TABLE,
    INDEX_SYNC_TABLE,
    MEMORY_CHUNKING_VERSION,
    MEMORY_INDEX_META_KEY,
    MEMORY_INDEX_PROVENANCE_VERSION,
    MEMORY_INDEX_META_TABLE,
    NO_PROVIDER_ID,
    parse_index_meta,
    resolve_configured_scope_hash,
    resolve_configured_sources_for_meta,
    resolve_memory_index_identity_state,
    resolve_memory_index_provider_identities,
)
from memory_core.index.keywords import extract_keywords
from memory_core.index.publication import (
    CHUNK_DETAILS_TABLE,
    CHUNK_PROVENANCE_TABLE,
    CHUNK_RECALL_TABLE,
    PreparedChunk,
    PreparedIndexRevision,
    PreparedSource,
    ensure_publication_schema,
    missing_metadata_sources,
    read_published_rows,
    write_prepared_index,
)
from memory_core.index.preparation import (
    classify_memory_path,
    extract_curated_entry_recall_metadata,
    resolve_chunk_provenance,
    strip_memory_annotation_carriers,
)
from memory_core.index.temporal_decay import (
    TemporalDecayConfig,
    apply_temporal_decay_to_hybrid_results,
)
from memory_core.index.vector import cosine_similarity, decode_memory_embedding
from memory_core.workspace import MemoryFile, MemoryWorkspace, workspace_index_lock

# OpenClaw caps per-keyword FTS fallback probes so long conversational queries
# cannot fan out into unbounded sqlite work (memory-core manager.ts).
KEYWORD_FALLBACK_SEARCH_TERM_LIMIT = 6
# manager-search-orchestration.ts SEARCH_CANDIDATE_UNIVERSE and src/agents/memory-search.ts
# DEFAULT_HYBRID_CANDIDATE_MULTIPLIER.
SEARCH_CANDIDATE_UNIVERSE = 200
HYBRID_CANDIDATE_MULTIPLIER = 4
VECTOR_FALLBACK_BATCH_SIZE = 256
_RecallCandidate = TypeVar("_RecallCandidate", KeywordHit, HybridVectorResult)

# Chunking recorded in the index identity (chunk_markdown defaults; upstream
# DEFAULT_CHUNK_TOKENS / DEFAULT_CHUNK_OVERLAP, src/agents/memory-search.ts).
CHUNK_TOKENS = 400
CHUNK_OVERLAP = 80
# memory-core always indexes memory files and session transcripts.
CONFIGURED_SOURCES = ("memory", "sessions")
# Native src/agents/memory-search.ts DEFAULT_CACHE_MAX_ENTRIES.
EMBEDDING_CACHE_MAX_ENTRIES = 50_000


class MemoryIndexSourceChangedError(RuntimeError):
    """A prepared source or index generation changed before publication."""


@dataclasses.dataclass(frozen=True)
class IndexSourceSnapshot:
    path: str
    source: str
    hash: str
    text: str
    mtime: float
    size: int
    kind: str = "markdown"
    canonical_path: str | None = None
    index_entry: Any | None = None


def _text_hash(text: str) -> str:
    return hashlib.sha256(js_utf8_encode(text)).hexdigest()


def read_index_source(file: MemoryFile) -> IndexSourceSnapshot | None:
    """Inspect one source without changing newline or invalid-UTF-8 semantics.

    Native ``buildFileEntry`` hashes the replacement-decoded text, retaining
    CRLF bytes in its string. Session projections supplied by the host are
    authoritative and must not be replaced with their raw JSONL file contents.
    The final component is opened without following symlinks and special files
    are never read, including a FIFO introduced after discovery.
    """
    index_entry = getattr(file, "index_entry", None)
    if file.index_text is not None or index_entry is not None:
        text = index_entry.content if index_entry is not None else file.index_text
        mtime = file.index_mtime_ms
        size = file.index_size
        if mtime is None or size is None:
            try:
                info = file.abs_path.stat()
                if mtime is None:
                    mtime = info.st_mtime_ns / 1_000_000
                if size is None:
                    size = info.st_size if index_entry is not None else len(js_utf8_encode(text))
            except (FileNotFoundError, NotADirectoryError):
                if mtime is None:
                    mtime = 0.0
                if size is None:
                    size = len(js_utf8_encode(text))
        source_hash = index_entry.hash if index_entry is not None else _text_hash(text)
        if file.source == "sessions" and index_entry is not None:
            revision = getattr(index_entry, "_extra", {}).get("revisionMs")
            if revision is not None:
                # SQLite mutation timestamps are positive millisecond numbers;
                # REAL-backed integral values use the same spelling as JS.
                revision_text = str(int(revision)) if isinstance(revision, float) and revision.is_integer() else str(revision)
                source_hash = f"sqlite:{revision_text}:{source_hash}"
        return IndexSourceSnapshot(
            file.rel_path, file.source,
            source_hash, text, mtime, size,
            index_entry=deepcopy(index_entry),
        )
    try:
        info = file.abs_path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(file.abs_path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                return None
            raw = stream.read()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as error:
        if error.errno == errno.ELOOP:
            return None
        raise
    text = raw.decode("utf-8", errors="replace")
    return IndexSourceSnapshot(
        file.rel_path, file.source, _text_hash(text), text, info.st_mtime_ns / 1_000_000, info.st_size,
    )


def validate_store_config(config: MemoryConfig, embeddings: EmbeddingProvider | None) -> Path:
    """Check everything that makes store construction raise, without side effects.

    Fail closed per the FeatureFlags contract: vector search with no embedding
    provider raises instead of silently falling back to FTS-only. Returns the
    resolved store path.
    """
    if config.effective_flags().vector_search and embeddings is None:
        raise ValueError(
            "vector_search is enabled but no embedding provider was given; "
            "pass an embedding provider or disable it via "
            "FeatureFlags(vector_search=False) for FTS-only mode"
        )
    return config.resolved_store_path()


class SQLiteMemoryStore:
    # Backends opting into the tool's partial-result callback implement the
    # same optional search keyword. Legacy backends need not accept it.
    supports_partial_results = True

    def __init__(
        self,
        config: MemoryConfig,
        embeddings: EmbeddingProvider | None,
        *,
        revision_fence: IndexRevisionFence | None = None,
        artifact_provenance: MemoryArtifactProvenanceStore | None = None,
    ):
        # The ``memory_index_state`` fence a rebuild is published against (see :meth:`reindex`);
        # assignable after construction, ``None`` (default) means no fence.
        self.revision_fence = revision_fence
        # Hosts may share their write observer's trust ledger with indexing.
        # Merely binding it must not create or read the provenance database.
        self.artifact_provenance = artifact_provenance
        self.path = validate_store_config(config, embeddings)
        self.config = config
        self.flags = config.effective_flags()
        self.embeddings = embeddings
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @contextmanager
    def _search_connection(self, signal: CancellationSignal | None) -> Iterator[sqlite3.Connection]:
        # A read-only connection the caller's signal can interrupt from another
        # thread (sqlite3 interrupt), closed when the search ends.
        db = self.connect()
        remove_listener = signal.add_listener(db.interrupt) if signal is not None else None
        try:
            # All lexical/path/vector probes and their identity gate use one
            # reader generation. An early partial keyword lease is released
            # before provider work; the final pass uses one complete generation.
            db.execute("BEGIN")
            yield db
        finally:
            if remove_listener is not None:
                remove_listener()
            db.close()

    def _init_schema(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL
                )
                """
            )
            db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(id UNINDEXED, text)"
            )
            # One row per indexed file, for path and filename matching (memory_index_paths_fts).
            db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS paths_fts USING fts5(path, source UNINDEXED)"
            )
            # memory-host-sdk memory-schema.ts. Stores created before this table
            # existed read as "index metadata is missing" until their next reindex.
            db.execute(
                f"CREATE TABLE IF NOT EXISTS {MEMORY_INDEX_META_TABLE} "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            ensure_embedding_cache_schema(db)
            # Source state is private to this Python schema. An empty source
            # still gets a row so later deletion/reopen decisions are sound.
            db.execute(
                f"CREATE TABLE IF NOT EXISTS {INDEX_SOURCES_TABLE} ("
                "source TEXT NOT NULL, path TEXT NOT NULL, hash TEXT NOT NULL, "
                "mtime REAL NOT NULL, size INTEGER NOT NULL, chunk_count INTEGER NOT NULL, "
                "PRIMARY KEY (source, path))"
            )
            # An internal generation protects selective publications even when
            # the host has not supplied a separate origins/revision fence.
            db.execute(
                f"CREATE TABLE IF NOT EXISTS {INDEX_SYNC_TABLE} ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), revision INTEGER NOT NULL, "
                "workspace TEXT, needs_rebuild INTEGER NOT NULL DEFAULT 0)"
            )
            db.execute(f"INSERT OR IGNORE INTO {INDEX_SYNC_TABLE}(id, revision) VALUES (1, 0)")
            ensure_publication_schema(db)

    def index_revision(self, *, db: sqlite3.Connection | None = None) -> int:
        """The private publication generation, checked like the native owner."""
        if db is None:
            with closing(self.connect()) as connection:
                return self.index_revision(db=connection)
        row = db.execute(f"SELECT revision FROM {INDEX_SYNC_TABLE} WHERE id=1").fetchone()
        if row is None or type(row[0]) is not int or abs(row[0]) > 2 ** 53 - 1:
            raise RuntimeError("Memory index revision is missing or invalid")
        return row[0]

    def read_published_index(self, *, db: sqlite3.Connection | None = None) -> dict:
        """Return complete published rows under one deferred read snapshot.

        A supplied connection may retain its transaction across publications;
        this method leaves that caller-owned snapshot and handle open.
        """
        if db is None:
            with closing(self.connect()) as connection:
                connection.execute("BEGIN")
                return self.read_published_index(db=connection)
        if not db.in_transaction:
            try:
                db.execute("BEGIN")
                return read_published_rows(db, self.index_revision(db=db))
            finally:
                db.rollback()
        return read_published_rows(db, self.index_revision(db=db))

    def publish_prepared_index(
        self,
        prepared: PreparedIndexRevision,
        expected_revision: int,
        *,
        on_begin: Callable[[sqlite3.Connection], None] | None = None,
        with_commit: Callable[[Callable[[], None]], None] | None = None,
        owner_check: Callable[[sqlite3.Connection], None] | None = None,
        expected_fence_revision: int | None = None,
    ) -> int:
        """Atomically publish prepared chunks, metadata and source state.

        The connection owns BEGIN IMMEDIATE through COMMIT. Hooks run inside
        that owner, permitting admission/commit services and failure injection
        without making partial rows visible to independent readers. Generated
        embedding cache entries are deliberately outside this transaction.
        """
        fence = self.revision_fence
        if fence is not None and expected_fence_revision is None:
            expected_fence_revision = fence.read()
        same_database = fence is not None and fence.same_database(self.path)
        with closing(self.connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                if on_begin is not None:
                    on_begin(db)
                if fence is not None:
                    if same_database:
                        fence.assert_unchanged_in(db, expected_fence_revision)
                    else:
                        fence.assert_unchanged(expected_fence_revision)
                if owner_check is not None:
                    owner_check(db)
                current_revision = self.index_revision(db=db)
                if isinstance(expected_revision, bool) or current_revision != expected_revision:
                    raise MemoryIndexRevisionConflictError(
                        "Memory index changed while full reindex was building "
                        f"(expected revision {expected_revision}, found {current_revision}); "
                        "retry the full reindex."
                    )
                write_prepared_index(db, prepared)
                db.execute(
                    f"UPDATE {INDEX_SYNC_TABLE} SET revision=revision+1, "
                    "workspace=?, needs_rebuild=0 WHERE id=1", (prepared.workspace,),
                )
                if fence is not None and same_database:
                    fence.bump_in(db)
                new_revision = self.index_revision(db=db)
                if with_commit is None:
                    db.commit()
                else:
                    with_commit(db.commit)
                    if db.in_transaction:
                        raise RuntimeError("Index publication did not commit")
            except BaseException:
                db.rollback()
                raise
        if fence is not None and not same_database:
            fence.bump()
        return new_revision

    def _index_provider(self) -> dict[str, str] | None:
        # The embedder only counts while vector search is on; otherwise the
        # index is FTS-only (provider none / model fts-only).
        if not self.flags.vector_search or self.embeddings is None:
            return None
        return {"id": self.embeddings.provider_id, "model": self.embeddings.model}

    def _provider_identities(self) -> list[dict[str, str]]:
        cache_key_data = getattr(self.embeddings, "cache_key_data", None)
        if callable(cache_key_data):
            cache_key_data = cache_key_data()
        aliases = getattr(self.embeddings, "index_identity_aliases", ())
        if callable(aliases):
            aliases = aliases()
        provider = self._index_provider()
        return resolve_memory_index_provider_identities(
            provider,
            cache_key_data=cache_key_data if provider is not None else None,
            aliases=aliases if provider is not None else (),
        )

    def _provider_key(self) -> str:
        return self._provider_identities()[0]["providerKey"]

    def read_index_meta(self, *, db: sqlite3.Connection | None = None) -> object:
        """The stored index identity JSON, or ``None`` (``readMeta``)."""
        if db is None:
            with closing(self.connect()) as connection:
                return self.read_index_meta(db=connection)
        row = db.execute(
            f"SELECT value FROM {MEMORY_INDEX_META_TABLE} WHERE key = ?",
            (MEMORY_INDEX_META_KEY,),
        ).fetchone()
        return parse_index_meta(row[0] if row else None)

    def _has_indexed_chunks(self) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is not None

    def index_identity(self, *, db: sqlite3.Connection | None = None) -> dict[str, Any]:
        """Whether the index matches this store's provider and settings.

        ``{"status": "valid"}``, or ``missing``/``mismatched`` with an upstream
        reason (``manager-reindex-state.ts`` ``resolveMemoryIndexIdentityState``).
        Searches return no hits and ``memory_search`` pauses until
        :meth:`reindex` writes fresh metadata.
        """
        if db is None:
            with closing(self.connect()) as connection:
                connection.execute("BEGIN")
                return self.index_identity(db=connection)
        return resolve_memory_index_identity_state(
            meta=self.read_index_meta(db=db),
            provider=self._index_provider(),
            provider_key=self._provider_key(),
            provider_key_known=True,
            configured_sources=resolve_configured_sources_for_meta(CONFIGURED_SOURCES),
            configured_scope_hash=resolve_configured_scope_hash(),
            chunk_tokens=CHUNK_TOKENS,
            chunk_overlap=CHUNK_OVERLAP,
            vector_ready=self._index_provider() is not None,
            has_indexed_chunks=db.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is not None,
            fts_tokenizer=DEFAULT_FTS_TOKENIZER,
        )

    def _build_index_meta(
        self, vector_dims: int | None, *, provider: dict[str, str] | None, provider_key: str,
    ) -> dict:
        # manager-sync-ops.ts nextMeta (same key order).
        meta = {
            "model": provider["model"] if provider is not None else FTS_ONLY_MODEL,
            "provider": provider["id"] if provider is not None else NO_PROVIDER_ID,
            "providerKey": provider_key,
            "sources": resolve_configured_sources_for_meta(CONFIGURED_SOURCES),
            "scopeHash": resolve_configured_scope_hash(),
            "chunkTokens": CHUNK_TOKENS,
            "chunkOverlap": CHUNK_OVERLAP,
            "chunkingVersion": MEMORY_CHUNKING_VERSION,
            "ftsTokenizer": DEFAULT_FTS_TOKENIZER,
            "provenanceVersion": MEMORY_INDEX_PROVENANCE_VERSION,
        }
        if provider is not None and vector_dims:
            meta["vectorDims"] = vector_dims
        return meta

    def reindex(self, workspace: MemoryWorkspace, *, force: bool = False) -> int:
        """Refresh changed sources and return the number of eligible files.

        ``force=True`` reparses all sources for explicit index repair, while
        still reusing valid provider-scoped cached embeddings. Every refresh
        discovers and replacement-decodes the current sources, as
        upstream source hashing does. Only matching source hashes under a valid
        index identity reuse existing chunks. Generated document embeddings are
        persisted separately after response/source/generation validation, so a
        later index publication failure can retain that valid reusable batch.

        Chunk/FTS/path/source/meta changes publish in one immediate transaction.
        The private generation prevents two selective publications from mixing
        prepared revisions. A supplied origins fence is checked in that same
        transaction when it shares this database; its separate-database gap is
        unchanged and remains documented on IndexRevisionFence.
        Cooperating curated write/refresh pairs and refreshes share a reentrant
        process-local workspace guard; raw filesystem and external-process
        changes are still checked rather than retried implicitly.
        """
        with workspace_index_lock(workspace.root):
            return self._reindex_locked(workspace, force=force)

    def _reindex_locked(self, workspace: MemoryWorkspace, *, force: bool) -> int:
        fence = self.revision_fence
        expected_fence = fence.read() if fence is not None else None
        same_database = fence is not None and fence.same_database(self.path)
        provider = self._index_provider()
        identities = self._provider_identities()
        provider_key = identities[0]["providerKey"]
        next_meta = self._build_index_meta(None, provider=provider, provider_key=provider_key)
        chunk_tokens, chunk_overlap = next_meta["chunkTokens"], next_meta["chunkOverlap"]
        workspace_root = str(workspace.root.resolve())
        with self.connect() as db:
            generation, previous_workspace, needs_rebuild = db.execute(
                f"SELECT revision, workspace, needs_rebuild FROM {INDEX_SYNC_TABLE} WHERE id = 1"
            ).fetchone()
            previous_source_rows = db.execute(
                f"SELECT source, path, hash, chunk_count, mtime, size FROM {INDEX_SOURCES_TABLE}"
            ).fetchall()
            previous_sources = {
                (source, path): (chunk_hash, chunk_count)
                for source, path, chunk_hash, chunk_count, _, _ in previous_source_rows
            }
            previous_source_metadata = {(source, path): (chunk_hash, mtime, size)
                                        for source, path, chunk_hash, _, mtime, size in previous_source_rows}
            previous_counts = {
                (source, path): count for source, path, count in db.execute(
                    "SELECT source, path, COUNT(*) FROM chunks GROUP BY source, path"
                )
            }
            metadata_missing = missing_metadata_sources(db)
        meta = self.read_index_meta()
        rebuild = (
            force or bool(needs_rebuild) or previous_workspace != workspace_root
            or self.index_identity()["status"] != "valid"
        )
        snapshots = self._read_source_snapshots(workspace)
        def content_hash(key, value):
            return value.rsplit(":", 1)[-1] if key[0] == "sessions" and value.startswith("sqlite:") else value

        changed = {
            key for key, entry in snapshots.items()
            if rebuild or key in metadata_missing
            or key not in previous_sources
            or previous_sources[key][1] != previous_counts.get(key, 0)
            or content_hash(key, previous_sources[key][0]) != content_hash(key, entry.hash)
        }
        removed = (set(previous_sources) | set(previous_counts)) - snapshots.keys()
        remaining_old = snapshots.keys() - changed
        active_dimensions = (
            meta.get("vectorDims") if provider is not None and isinstance(meta, dict)
            and any(previous_counts.get(key, 0) for key in remaining_old) else None
        )
        if active_dimensions is not None and (
            isinstance(active_dimensions, bool) or not isinstance(active_dimensions, int)
            or active_dimensions <= 0
        ):
            # A malformed legacy dimension cannot authorize mixing old vectors
            # with newly generated ones. Rebuild all sources instead.
            rebuild = True
            changed = set(snapshots)
            remaining_old = set()
            active_dimensions = None

        def assert_owner(db: sqlite3.Connection) -> None:
            if fence is not None:
                if same_database:
                    fence.assert_unchanged_in(db, expected_fence)
                else:
                    fence.assert_unchanged(expected_fence)
            revision = db.execute(
                f"SELECT revision FROM {INDEX_SYNC_TABLE} WHERE id = 1"
            ).fetchone()[0]
            if revision != generation:
                raise MemoryIndexSourceChangedError(
                    "Memory index changed while refresh was being prepared; retry the index refresh."
                )
            if (self._index_provider() != provider or self._provider_identities() != identities
                    or self._build_index_meta(None, provider=provider, provider_key=provider_key) != next_meta
                    or str(workspace.root.resolve()) != workspace_root):
                raise MemoryIndexSourceChangedError(
                    "Memory index owner changed while refresh was being prepared; retry the index refresh."
                )

        def assert_sources_current() -> None:
            # Prefer the established ledger diagnostic when forget changed the
            # revision, before another host projection could hide the cause.
            if fence is not None:
                fence.assert_unchanged(expected_fence)
            current = self._read_source_snapshots(workspace)
            if ({key: entry.hash for key, entry in current.items()}
                    != {key: entry.hash for key, entry in snapshots.items()}):
                raise MemoryIndexSourceChangedError(
                    "Memory source changed while refresh was being prepared; retry the index refresh."
                )

        metadata_updates = {key for key in snapshots.keys() - changed if key[0] == "sessions"
                            and previous_source_metadata.get(key) !=
                            (snapshots[key].hash, snapshots[key].mtime, snapshots[key].size)}

        def refresh_source_metadata(db):
            for key in metadata_updates:
                entry = snapshots[key]
                updated = db.execute(
                    f"UPDATE {INDEX_SOURCES_TABLE} SET hash=?,mtime=?,size=? "
                    "WHERE source=? AND path=? AND hash=?",
                    (entry.hash, entry.mtime, entry.size, key[0], key[1], previous_sources[key][0]),
                ).rowcount
                if updated != 1:
                    raise MemoryIndexSourceChangedError(
                        "Memory session source changed during metadata refresh; retry the index refresh."
                    )

        def assert_owner_and_refresh_metadata(db):
            assert_owner(db)
            refresh_source_metadata(db)

        if not rebuild and not changed and not removed:
            if metadata_updates:
                assert_sources_current()
            with self.connect() as db:
                if metadata_updates:
                    db.execute("BEGIN IMMEDIATE")
                assert_owner(db)
                if metadata_updates:
                    refresh_source_metadata(db)
                    db.execute(f"UPDATE {INDEX_SYNC_TABLE} SET revision=revision+1 WHERE id=1")
            return len(snapshots)

        prepared: dict[tuple[str, str], list[MemoryChunk]] = {
            key: self._prepare_source_chunks(entry, chunk_tokens, chunk_overlap)
            for key, entry in snapshots.items() if key in changed
        }
        if provider is not None:
            prepared = {key: enforce_embedding_max_input_tokens(self.embeddings, source_chunks)
                        for key, source_chunks in prepared.items()}
        chunks = [chunk for source_chunks in prepared.values() for chunk in source_chunks]
        embeddings: list[list[float]] = [[] for _ in chunks]
        if provider is not None and chunks:
            chunk_refs = [{"hash": _text_hash(chunk.text)} for chunk in chunks]
            with self.connect() as db:
                cached = load_memory_embedding_cache(
                    db, enabled=True, provider_identities=identities,
                    hashes=[entry["hash"] for entry in chunk_refs],
                )
            # Hits and new vectors must occupy one space, including across
            # providers' alias identities and a process restart.
            for chunk_hash, embedding in list(cached.items()):
                valid = (is_valid_memory_embedding(embedding) if active_dimensions is None
                         else is_valid_memory_embedding(embedding, active_dimensions))
                if not valid:
                    del cached[chunk_hash]
                elif active_dimensions is None:
                    active_dimensions = len(embedding)
            collected = collect_memory_cached_embeddings(chunk_refs, cached)
            embeddings = collected["embeddings"]
            missing = collected["missing"]
            if missing:
                generated = self.embeddings.embed_documents(
                    [chunks[item["index"]].text for item in missing]
                )
                try:
                    dimensions = validate_memory_embedding_batch(
                        generated, len(missing), dimensions=active_dimensions,
                    )
                except ValueError:
                    if (active_dimensions is not None and isinstance(generated, list)
                            and any(is_valid_memory_embedding(value)
                                    and len(value) != active_dimensions for value in generated)):
                        # Ambiguous dimensions cannot be borrowed on the next
                        # attempt. Preserve published rows, clear this space,
                        # and force a complete refresh on the explicit retry.
                        with self.connect() as db:
                            db.execute("BEGIN IMMEDIATE")
                            assert_owner(db)
                            clear_memory_embedding_cache_identities(db, identities)
                            db.execute(
                                f"UPDATE {INDEX_SYNC_TABLE} SET needs_rebuild = 1, "
                                "revision = revision + 1 WHERE id = 1"
                            )
                    raise
                active_dimensions = dimensions
                assert_sources_current()
                with self.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    assert_owner(db)
                    upsert_memory_embedding_cache(
                        db, enabled=True, provider=provider, provider_key=provider_key,
                        max_entries=EMBEDDING_CACHE_MAX_ENTRIES,
                        entries=[{"hash": chunk_refs[item["index"]]["hash"], "embedding": value}
                                 for item, value in zip(missing, generated, strict=True)],
                    )
                for item, value in zip(missing, generated, strict=True):
                    embeddings[item["index"]] = value

        assert_sources_current()
        has_chunks = bool(chunks) or any(previous_counts.get(key, 0) for key in remaining_old)
        vector_dims = active_dimensions if provider is not None and has_chunks else None
        published_meta = dict(next_meta)
        if vector_dims is not None:
            published_meta["vectorDims"] = vector_dims
        updated_at = time.time_ns() // 1_000_000
        sources = []
        offset = 0
        for key, source_chunks in prepared.items():
            entry = snapshots[key]
            published_chunks = []
            recorded = (
                self.artifact_provenance.read(
                    workspace_dir=workspace.root, relative_path=entry.canonical_path,
                )
                if self.artifact_provenance is not None and entry.source == "memory"
                and entry.canonical_path is not None else None
            )
            classification = classify_memory_path(
                entry.canonical_path or "", entry.source,
                recorded_origin=recorded.origin_class if recorded is not None else None,
            )
            source_lines = entry.text.replace("\r\n", "\n").split("\n") if entry.source == "memory" else []
            metadata_by_span = {}
            line_provenance = entry.index_entry.line_provenance if entry.index_entry is not None else None
            line_map = entry.index_entry.line_map if entry.index_entry is not None else None
            for chunk in source_chunks:
                provenance = resolve_chunk_provenance(
                    source=entry.source, path_origin_class=classification["originClass"],
                    mtime_ms=entry.mtime, start_line=chunk.start_line, end_line=chunk.end_line,
                    line_provenance=line_provenance,
                )
                span = (chunk.entry_start_line or chunk.start_line, chunk.entry_end_line or chunk.end_line)
                if span not in metadata_by_span:
                    metadata_by_span[span] = extract_curated_entry_recall_metadata(
                        source_lines=source_lines[span[0] - 1:span[1]],
                        curated_root=classification["curatedRoot"],
                        project_scope_eligible=entry.source == "memory" and entry.path.upper() != "USER.MD",
                    )
                start, end = chunk.start_line, chunk.end_line
                if line_map:
                    start = line_map[start - 1] if start <= len(line_map) and line_map[start - 1] is not None else start
                    end = line_map[end - 1] if end <= len(line_map) and line_map[end - 1] is not None else end
                chunk_hash = _text_hash(chunk.text)
                chunk_id = _text_hash(
                    f"{chunk.source}:{chunk.path}:{start}:{end}:{chunk_hash}:{next_meta['model']}"
                )
                published_chunks.append(PreparedChunk(
                    id=chunk_id, path=chunk.path, source=chunk.source,
                    start_line=start, end_line=end,
                    text=chunk.text, embedding=tuple(embeddings[offset]),
                    hash=chunk_hash, model=next_meta["model"], updated_at=updated_at,
                    provenance=provenance, recall=metadata_by_span[span],
                ))
                offset += 1
            sources.append(PreparedSource(entry.path, entry.source, entry.hash,
                                          entry.mtime, entry.size, tuple(published_chunks)))
        self.publish_prepared_index(
            PreparedIndexRevision(tuple(sources), js_json_stringify(published_meta),
                                  workspace=workspace_root, replace_all=bool(rebuild),
                                  removed_sources=tuple(removed)),
            generation, owner_check=assert_owner_and_refresh_metadata, expected_fence_revision=expected_fence,
        )
        return len(snapshots)

    @staticmethod
    def _prepare_source_chunks(entry: IndexSourceSnapshot, tokens: int, overlap: int) -> list[MemoryChunk]:
        content = strip_memory_annotation_carriers(entry.text) if entry.source == "memory" else entry.text
        options = {"source": entry.source, "target_tokens": tokens, "overlap_tokens": overlap,
                   "per_entry": entry.source == "memory" and entry.path.replace("\\", "/")
                   in ("MEMORY.md", "USER.md")}
        cutoff_index = -1
        if entry.source == "sessions" and entry.index_entry is not None:
            cutoff = entry.index_entry.reset_recall_cutoff
            cutoff_line = cutoff.get("cutoffLine") if cutoff.get("state") == "valid" else None
            if cutoff_line is not None:
                cutoff_index = next((index for index, line in enumerate(entry.index_entry.line_map)
                                     if line >= cutoff_line), -1)
        if cutoff_index <= 0:
            return [chunk for chunk in chunk_markdown(entry.path, content, **options)
                    if js_trim(chunk.text)]
        lines = content.split("\n")
        before = chunk_markdown(entry.path, "\n".join(lines[:cutoff_index]), **options)
        after = chunk_markdown(entry.path, "\n".join(lines[cutoff_index:]), **options)
        return [chunk for chunk in (
            *before, *(dataclasses.replace(chunk, start_line=chunk.start_line + cutoff_index,
                                          end_line=chunk.end_line + cutoff_index) for chunk in after),
        ) if js_trim(chunk.text)]

    @staticmethod
    def _read_source_snapshots(workspace: MemoryWorkspace) -> dict[tuple[str, str], IndexSourceSnapshot]:
        snapshots = {}
        for file in workspace.discover_indexable_files():
            entry = read_index_source(file)
            if entry is not None:
                if entry.source == "memory":
                    try:
                        canonical = file.abs_path.resolve(strict=True).relative_to(workspace.root).as_posix()
                    except (OSError, RuntimeError, ValueError):
                        canonical = None
                    entry = dataclasses.replace(entry, canonical_path=canonical)
                key = (entry.source, entry.path)
                if key in snapshots:
                    raise ValueError("Duplicate memory index source")
                snapshots[key] = entry
        return snapshots

    def count_chunks(self) -> int:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) FROM chunks").fetchone()
        return int(row[0])

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        min_score: float = 0.0,
        sources: set[str] | None = None,
        signal: CancellationSignal | None = None,
        active_project_keys: Sequence[str] | None = None,
        on_partial_results: Callable[[list[HybridResult] | None], None] | None = None,
        session_key: str | None = None,
        on_debug: Callable[[dict[str, Any]], None] | None = None,
        deadline_control: MemorySearchDeadlineControl | None = None,
    ) -> list[HybridResult]:
        """Search the index; ``signal`` aborts it at the next checkpoint.

        Returns no hits while :meth:`index_identity` is not valid (a store
        built with another provider/model/settings, or one never reindexed).
        Checkpoints mirror where OpenClaw's manager honours the tool's
        AbortSignal (``memory/manager.ts`` search, ``embedQueryWithRetry``):
        before and after the query embedding and between FTS probes; an abort
        also interrupts the open SQLite statement.

        Like ``manager-search-orchestration.ts`` one window of at least 200 candidates is
        ranked, then trimmed to ``max_results``: keyword hits (chunk text and file path, with
        exact-path tiers), vector hits, the hybrid merge with temporal decay and MMR, and the
        selection under ``min_score``.

        ``on_partial_results`` receives finalized memory-file keyword hits
        before query embedding; ``None`` invalidates an earlier snapshot.
        Session authority and managed-provider readiness belong to the host;
        their optional controls share the capable-backend call protocol.
        """
        del session_key, on_debug, deadline_control
        normalized = js_trim(query)
        if not normalized:
            return []
        _checkpoint(signal)
        # memory/manager.ts:680-685: no hits unless the index identity is valid.
        if self.index_identity()["status"] != "valid":
            if on_partial_results is not None:
                on_partial_results(None)
            return []
        def publish_partial(results: list[HybridResult] | None) -> None:
            if on_partial_results is not None:
                # Match the requested manager window and keep a caller from
                # mutating metadata used by the later complete result.
                on_partial_results(None if results is None else [
                    dataclasses.replace(deepcopy(result), source_mtime=HYBRID_METADATA_MISSING)
                    for result in results[:max_results]
                ])

        window = (SEARCH_CANDIDATE_UNIVERSE if active_project_keys
                  else max(SEARCH_CANDIDATE_UNIVERSE, max_results))
        results = self._search_candidates(
            normalized,
            max_results=window,
            min_score=min_score,
            sources=sources,
            signal=signal,
            active_project_keys=active_project_keys,
            on_partial_results=publish_partial if on_partial_results is not None else None,
        )
        return [dataclasses.replace(result, source_mtime=HYBRID_METADATA_MISSING)
                for result in results[:max_results]]

    def search_memory_keywords(
        self, query: str, *, max_results: int = 5, min_score: float = 0.0,
        active_project_keys: Sequence[str] | None = None,
    ) -> list[HybridResult]:
        """Memory-file keyword hits without the query embedding.

        This explicit helper excludes sessions and refuses a stale index. Tool
        partials instead come from ``search``'s pre-embedding publisher; the
        deadline path must not start another FTS query after its budget expires.
        """
        normalized = js_trim(query)
        if (
            not normalized
            or not self.flags.text_search
        ):
            return []
        window = (SEARCH_CANDIDATE_UNIVERSE if active_project_keys
                  else max(SEARCH_CANDIDATE_UNIVERSE, max_results))
        candidates = min(200, max(1, window * HYBRID_CANDIDATE_MULTIPLIER))
        with self._search_connection(None) as db:
            if self.index_identity(db=db)["status"] != "valid":
                return []
            hits = self._search_keyword_with_fallback(
                db, normalized, candidates, _source_filter_clause({"memory"}), None
            )
            hits = self.attach_recall_metadata(hits, db=db)
        return [dataclasses.replace(result, source_mtime=HYBRID_METADATA_MISSING)
                for result in self._finalize_keyword_only(
                    hits, min(window, max_results), min_score,
                    active_project_keys=active_project_keys,
                )[:max_results]]

    def read_recall_metadata(
        self, ids: Sequence[str], *, db: sqlite3.Connection | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Read current chunk-backed annotations; missing metadata never deletes a live hit."""
        if not ids:
            return {}
        if db is None:
            with self._search_connection(None) as connection:
                return self.read_recall_metadata(ids, db=connection)
        rows = db.execute(
            "SELECT c.id,r.importance,r.triggers,r.project_key,p.origin_class,p.session_kind,"
            "p.observed_at,p.supersedes_key FROM chunks c "
            f"LEFT JOIN {CHUNK_RECALL_TABLE} r ON r.chunk_id=c.id "
            f"LEFT JOIN {CHUNK_PROVENANCE_TABLE} p ON p.chunk_id=c.id "
            f"WHERE c.id IN ({','.join('?' for _ in ids)})", tuple(ids),
        )
        result: dict[str, dict[str, Any]] = {}
        for chunk_id, importance, triggers, project_key, origin, kind, observed, supersedes in rows:
            metadata = {"id": chunk_id, "importance": importance,
                        "triggers": triggers, "project_key": project_key}
            if (origin in {"owner", "agent", "untrusted", "system"}
                    and kind in {"interactive", "cron", "heartbeat", "subagent", "unknown"}
                    and isinstance(observed, (int, float)) and not isinstance(observed, bool)):
                provenance = {"originClass": origin, "sessionKind": kind, "observedAt": observed}
                if isinstance(supersedes, str) and js_trim(supersedes):
                    provenance["supersedesKey"] = supersedes
                metadata["provenance"] = provenance
            result[chunk_id] = metadata
        return result

    def attach_recall_metadata(
        self, candidates: Sequence[_RecallCandidate], *, db: sqlite3.Connection | None = None,
        include_memory_mtimes: bool = True, signal: CancellationSignal | None = None,
    ) -> list[_RecallCandidate]:
        """Enrich retained keyword/vector candidates in the same leased read generation."""
        if not candidates:
            return []
        if db is None:
            with self._search_connection(signal) as connection:
                return self.attach_recall_metadata(
                    candidates, db=connection, include_memory_mtimes=include_memory_mtimes,
                    signal=signal,
                )
        _checkpoint(signal)
        metadata = self.read_recall_metadata([candidate.id for candidate in candidates], db=db)
        live = [candidate for candidate in candidates if candidate.id in metadata]
        mtimes: dict[tuple[str, str], Any] = {}
        for source in ("memory", "sessions"):
            if source == "memory" and not include_memory_mtimes:
                continue
            paths = list(dict.fromkeys(candidate.path for candidate in live
                                       if candidate.source == source))
            if paths:
                mtimes.update(((source, path), mtime) for path, mtime in db.execute(
                    f"SELECT path,mtime FROM {INDEX_SOURCES_TABLE} WHERE source=? AND path IN "
                    f"({','.join('?' for _ in paths)})", (source, *paths),
                ))
        result = []
        for candidate in live:
            row = metadata[candidate.id]
            changes = {"source_mtime": mtimes.get((candidate.source, candidate.path),
                                                  HYBRID_METADATA_MISSING)}
            importance = row["importance"]
            if isinstance(importance, (int, float)) and not isinstance(importance, bool):
                changes["importance"] = importance
            for snake in ("triggers", "project_key"):
                value = row[snake]
                if isinstance(value, str) and js_trim(value):
                    changes[snake] = js_trim(value)
            if "provenance" in row:
                changes["provenance"] = row["provenance"]
            result.append(dataclasses.replace(candidate, **changes))
        _checkpoint(signal)
        return result

    @staticmethod
    def _source_mtimes(
        source: str, candidates: Sequence[Any],
    ) -> dict[str, float | None] | None:
        entries = [candidate for candidate in candidates if candidate.source == source]
        return ({candidate.path: (None if candidate.source_mtime is HYBRID_METADATA_MISSING
                                  else candidate.source_mtime) for candidate in entries}
                if entries else None)

    def search_vector_candidates(
        self,
        query_vec: Sequence[float],
        *,
        limit: int,
        provider_model: str | None = None,
        provider_model_aliases: Sequence[str] | None = None,
        sources: set[str] | None = None,
        snippet_max_chars: int = SNIPPET_MAX_CHARS,
        signal: CancellationSignal | None = None,
        db: sqlite3.Connection | None = None,
    ) -> list[HybridVectorResult]:
        """Return bounded CPU vector candidates before hybrid ranking.

        This is the ``searchVector`` fallback / ``searchChunksByEmbedding`` owner:
        filter actual per-chunk models and sources, scan by signed SQLite rowid,
        keep finite top-K scores and hydrate contenders before yielding. Equal
        scores retain rowid order. The ordinary search calls this same path under
        its identity gate and generation-wide read transaction; it additionally
        skips all-zero query vectors before calling the candidate owner.

        Without ``db``, this method owns a read transaction. A supplied connection
        retains its caller's existing transaction and lifetime, allowing lower
        level callers to choose their own snapshot ownership.
        """
        if not query_vec or limit <= 0:
            return []
        _checkpoint(signal)
        if provider_model is None:
            identities = self._provider_identities()
            provider_model = identities[0]["model"]
            if provider_model_aliases is None:
                provider_model_aliases = [identity["model"] for identity in identities[1:]]
        aliases = provider_model_aliases or ()
        models = list(dict.fromkeys([provider_model, *(alias for alias in aliases if alias)]))
        try:
            if db is not None:
                return self._search_vector_candidates(
                    db, query_vec, limit, models, sources, snippet_max_chars, signal
                )
            with self._search_connection(signal) as connection:
                return self._search_vector_candidates(
                    connection, query_vec, limit, models, sources, snippet_max_chars, signal
                )
        except sqlite3.OperationalError:
            # A signal may interrupt SQLite before the next bounded-scan checkpoint.
            _checkpoint(signal)
            raise

    @staticmethod
    def _search_vector_candidates(
        db: sqlite3.Connection,
        query_vec: Sequence[float],
        limit: int,
        models: list[str],
        sources: set[str] | None,
        snippet_max_chars: int,
        signal: CancellationSignal | None,
    ) -> list[HybridVectorResult]:
        source_filter = _source_filter_clause(sources)
        model_filter = (
            "d.model = ?" if len(models) == 1
            else f"d.model IN ({', '.join('?' for _ in models)})"
        )
        scan = (
            "SELECT c.rowid, c.embedding FROM chunks c "
            f"JOIN {CHUNK_DETAILS_TABLE} d ON d.chunk_id=c.id WHERE {model_filter}"
        )
        tail = source_filter.and_sql + " ORDER BY c.rowid ASC LIMIT ?"
        bounded_snippet = (
            type(snippet_max_chars) is int and 0 < snippet_max_chars <= 2 ** 53 - 1
        )
        projection = (
            "COALESCE(substr(CAST(c.text AS BLOB), 1, ?), CAST(c.text AS BLOB))"
            if bounded_snippet else "c.text"
        )
        payload_sql = (
            "SELECT c.id, c.path, c.start_line, c.end_line, c.source, "
            f"{projection} FROM chunks c WHERE c.rowid = ?"
        )
        text_encoding = db.execute("PRAGMA encoding").fetchone()[0].lower()
        top: list[HybridVectorResult] = []
        last_rowid: int | None = None
        while True:
            statement = scan + (" AND c.rowid > ?" if last_rowid is not None else "") + tail
            parameters = (
                *models, *((last_rowid,) if last_rowid is not None else ()),
                *source_filter.params, VECTOR_FALLBACK_BATCH_SIZE,
            )
            batch_size = 0
            with _vector_batch_snapshot(db), closing(db.execute(statement, parameters)) as cursor:
                # Keep SQLite's statement snapshot open while hydrating scored
                # contenders. Closing it first could join an old vector score
                # to a payload replaced by another connection in this batch.
                for rowid, embedding in cursor:
                    batch_size += 1
                    last_rowid = rowid
                    score = cosine_similarity(query_vec, decode_memory_embedding(embedding))
                    if not math.isfinite(score) or (
                        len(top) >= limit and score <= top[-1].vector_score
                    ):
                        continue
                    payload_parameters = (
                        *((snippet_max_chars * 4,) if bounded_snippet else ()), rowid,
                    )
                    payload = db.execute(payload_sql, payload_parameters).fetchone()
                    snippet = payload[5]
                    if isinstance(snippet, bytes):
                        snippet = snippet.decode(text_encoding, errors="replace")
                    result = HybridVectorResult(
                        id=payload[0], path=payload[1], start_line=payload[2], end_line=payload[3],
                        source=payload[4], snippet=truncate_utf16_safe(snippet, snippet_max_chars),
                        vector_score=score,
                    )
                    if len(top) < limit:
                        top.append(result)
                        if len(top) == limit:
                            top.sort(key=lambda item: -item.vector_score)
                    else:
                        top[-1] = result
                        top.sort(key=lambda item: -item.vector_score)
            if batch_size < VECTOR_FALLBACK_BATCH_SIZE:
                break
            # No SQLite iterator is held over the cooperative yield. Native uses
            # setImmediate; synchronous Python yields to its cancellation owner.
            time.sleep(0)
            _checkpoint(signal)
        top.sort(key=lambda item: -item.vector_score)
        return top

    def _search_candidates(
        self,
        query: str,
        *,
        max_results: int,
        min_score: float,
        sources: set[str] | None,
        signal: CancellationSignal | None,
        active_project_keys: Sequence[str] | None = None,
        on_partial_results: Callable[[list[HybridResult] | None], None] | None = None,
    ) -> list[HybridResult]:
        source_filter = _source_filter_clause(sources)
        candidates = min(200, max(1, max_results * HYBRID_CANDIDATE_MULTIPLIER))
        keyword: list[KeywordHit] = []
        vector_ready = self.flags.vector_search
        query_embedding: list[float] = []
        provider_identity = self._provider_identities() if vector_ready else None
        prepared_keyword: list[KeywordHit] | None = None
        prepared_revision: int | None = None
        if vector_ready and self.flags.text_search and on_partial_results is not None:
            # Publish actual FTS work before embedding can block. Release the
            # transaction while waiting so an uncooperative provider cannot
            # retain a read lock after the caller's deadline has elapsed.
            with self._search_connection(signal) as db:
                if (self._provider_identities() != provider_identity
                        or self.index_identity(db=db)["status"] != "valid"):
                    on_partial_results(None)
                    return []
                prepared_revision = self.index_revision(db=db)
                prepared_keyword = self._search_keyword_with_fallback(
                    db, query, candidates, source_filter, signal,
                )
                prepared_keyword = self.attach_recall_metadata(
                    prepared_keyword, db=db, signal=signal,
                )
                memory_hits = [hit for hit in prepared_keyword if hit.source == "memory"]
                partial = self._finalize_keyword_only(
                    memory_hits, max_results, min_score, active_project_keys=active_project_keys,
                ) if memory_hits else []
            _checkpoint(signal)
            if partial:
                on_partial_results(partial)
        if vector_ready:
            try:
                query_embedding = self.embeddings.embed_query(query)
                _checkpoint(signal)
            except BaseException:
                if on_partial_results is not None and not (signal is not None and signal.aborted):
                    on_partial_results(None)
                raise
            if self._provider_identities() != provider_identity:
                if on_partial_results is not None:
                    on_partial_results(None)
                return []
        with self._search_connection(signal) as db:
            if vector_ready and self._provider_identities() != provider_identity:
                if on_partial_results is not None:
                    on_partial_results(None)
                return []
            if self.index_identity(db=db)["status"] != "valid":
                if on_partial_results is not None:
                    on_partial_results(None)
                return []
            same_generation = (prepared_revision is not None
                               and self.index_revision(db=db) == prepared_revision)
            if (prepared_revision is not None and not same_generation
                    and on_partial_results is not None):
                on_partial_results(None)
            if db.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is None:
                return []
            if self.flags.text_search:
                if same_generation and prepared_keyword is not None:
                    keyword = prepared_keyword
                else:
                    keyword = self._search_keyword_with_fallback(
                        db, query, candidates, source_filter, signal
                    )
                    keyword = self.attach_recall_metadata(keyword, db=db, signal=signal)
            vector: list[HybridVectorResult] = []
            if vector_ready and any(value != 0 for value in query_embedding):
                match_exact_path = prepare_exact_path_matcher(query)
                vector = [
                    dataclasses.replace(item, exact_path_specificity=match_exact_path(item.path))
                    for item in self.search_vector_candidates(
                        query_embedding, limit=candidates, sources=sources, signal=signal, db=db,
                    )
                ]
                vector = self.attach_recall_metadata(vector, db=db, signal=signal)
        _checkpoint(signal)

        if not vector_ready:
            return self._finalize_keyword_only(
                keyword, max_results, min_score, active_project_keys=active_project_keys,
            )

        decay = TemporalDecayConfig(
            enabled=self.flags.temporal_decay,
            half_life_days=self.config.temporal_decay_half_life_days,
        )
        workspace_dir = str(self.config.workspace_dir)
        session_mtimes = self._source_mtimes("sessions", [*keyword, *vector])
        memory_mtimes = self._source_mtimes("memory", [*keyword, *vector])
        if not self.flags.text_search:
            # Vector-only mode mirrors OpenClaw's non-hybrid path: raw vector scores, decay,
            # a strict min-score filter, no keyword relaxation.
            decayed = apply_temporal_decay_to_hybrid_results(
                [
                    HybridResult(
                        path=item.path,
                        start_line=item.start_line,
                        end_line=item.end_line,
                        score=item.vector_score,
                        vector_score=item.vector_score,
                        text_score=0.0,
                        snippet=item.snippet,
                        source=item.source,
                        importance=item.importance,
                        triggers=item.triggers,
                        project_key=item.project_key,
                        provenance=item.provenance,
                        source_mtime=item.source_mtime,
                        _vector_id=item.id,
                        _retrieval_mode="vector",
                    )
                    for item in vector
                ],
                temporal_decay=decay,
                workspace_dir=workspace_dir,
                session_source_mtimes=session_mtimes,
                memory_source_mtimes=memory_mtimes,
            )
            return sorted(
                (item for item in apply_project_ranking(
                    apply_importance_multiplier(decayed),
                    list(active_project_keys) if active_project_keys is not None else None,
                ) if item.score >= min_score),
                key=lambda item: (
                    -item.score,
                    locale_sort_key(item.path),
                    item.start_line,
                    item.end_line,
                ),
            )[:max_results]

        merged = merge_hybrid_results(
            vector=vector,
            keyword=[
                HybridKeywordResult(
                    id=hit.id,
                    path=hit.path,
                    start_line=hit.start_line,
                    end_line=hit.end_line,
                    source=hit.source,
                    snippet=hit.snippet,
                    text_score=hit.text_score,
                    has_body_match=hit.has_body_match,
                    ranking_score=hit.score,
                    path_score=hit.path_score,
                    exact_path_specificity=hit.exact_path_specificity,
                    importance=hit.importance,
                    triggers=hit.triggers,
                    project_key=hit.project_key,
                    provenance=hit.provenance,
                )
                for hit in keyword
            ],
            vector_weight=self.config.vector_weight,
            text_weight=self.config.text_weight,
            workspace_dir=workspace_dir,
            temporal_decay=decay,
            mmr_enabled=self.flags.mmr,
            mmr_lambda=self.config.mmr_lambda,
            session_source_mtimes=session_mtimes,
            memory_source_mtimes=memory_mtimes,
            active_project_keys=list(active_project_keys) if active_project_keys is not None else None,
        )
        return select_hybrid_search_results(
            merged=merged, keyword=keyword, max_results=max_results, min_score=min_score
        )

    def _finalize_keyword_only(
        self, hits: list[KeywordHit], max_results: int, min_score: float, *,
        active_project_keys: Sequence[str] | None = None, now_ms: int | None = None,
    ) -> list[HybridResult]:
        """``finalizeKeywordOnlyResults``: decay, tier sort, strict then relaxed min score."""
        applies_decay = self.flags.temporal_decay
        inputs = hits
        if applies_decay:
            inputs = [
                dataclasses.replace(
                    hit,
                    score=score_exact_path_tie_for_temporal_decay(
                        hit.score if hit.has_body_match else 0.0
                    ),
                )
                if hit.exact_path_specificity > 0
                else hit
                for hit in hits
            ]
        decayed = apply_temporal_decay_to_hybrid_results(
            inputs,
            temporal_decay=TemporalDecayConfig(
                enabled=applies_decay,
                half_life_days=self.config.temporal_decay_half_life_days,
            ),
            workspace_dir=str(self.config.workspace_dir),
            session_source_mtimes=self._source_mtimes("sessions", hits),
            memory_source_mtimes=self._source_mtimes("memory", hits),
            now_ms=now_ms,
        )
        ranked = sorted(
            apply_project_ranking(
                apply_importance_multiplier(decayed),
                list(active_project_keys) if active_project_keys is not None else None,
            ), key=lambda hit: keyword_hit_sort_key(hit, prefer_exact_body=not applies_decay)
        )
        # Specificity and adjusted body relevance are preserved before the exact public
        # scores are normalized.
        ranked = [
            dataclasses.replace(hit, score=_project_score_multiplier(
                hit.project_key, set(active_project_keys) if active_project_keys else None,
            )) if hit.exact_path_specificity > 0 else hit
            for hit in ranked
        ]
        strict = [hit for hit in ranked if hit.score >= min_score]
        selected = strict[:max_results] if strict else [h for h in ranked if h.score >= 0][:max_results]
        return [
            HybridResult(
                path=hit.path,
                start_line=hit.start_line,
                end_line=hit.end_line,
                score=hit.score,
                vector_score=0.0,
                text_score=hit.text_score,
                snippet=hit.snippet,
                source=hit.source,
                importance=hit.importance,
                triggers=hit.triggers,
                project_key=hit.project_key,
                provenance=hit.provenance,
                source_mtime=hit.source_mtime,
                _retrieval_mode="keyword",
            )
            for hit in selected
        ]

    def _search_keyword_with_fallback(
        self,
        db: sqlite3.Connection,
        query: str,
        limit: int,
        source_filter: _SourceFilter,
        signal: CancellationSignal | None,
    ) -> list[KeywordHit]:
        """``searchKeywordWithFallback``: the full query, then per-keyword probes for a thin pool."""
        full = self._search_keyword(db, query, limit, source_filter)
        _checkpoint(signal)
        if len([hit for hit in full if hit.exact_path_specificity == 0]) >= limit:
            return full
        # Supplement a thin candidate pool for conversational queries, with the probes capped
        # so a long prompt cannot fan out into unbounded sqlite work.
        normalized_query = js_trim(query).lower()
        fallback_terms = [t for t in extract_keywords(query) if t != normalized_query][
            :KEYWORD_FALLBACK_SEARCH_TERM_LIMIT
        ]
        if not fallback_terms:
            return full
        strict_query = (build_fts_query(query) or "").lower()
        keyword_query = (build_fts_query(" ".join(fallback_terms)) or "").lower()
        if full and strict_query == keyword_query:
            # The expansion did not normalize an already-matching keyword query.
            return full
        result_sets = [full]
        for term in fallback_terms:
            _checkpoint(signal)
            result_sets.append(
                self._search_keyword(
                    db, term, limit, source_filter, exact_path_query=query, ranking_query=query
                )
            )
        return limit_keyword_search_hits(merge_keyword_search_hits(result_sets, query), limit)

    def _search_keyword(
        self,
        db: sqlite3.Connection,
        query: str,
        limit: int,
        source_filter: _SourceFilter,
        *,
        exact_path_query: str | None = None,
        ranking_query: str | None = None,
    ) -> list[KeywordHit]:
        if not self.flags.text_search or limit <= 0:
            return []
        exact_query = exact_path_query if exact_path_query is not None else query
        body = self._query_body_hits(db, query, limit, source_filter, ranking_query or query)
        paths = self._query_path_hits(db, query, exact_query, limit, source_filter)
        return limit_keyword_search_hits(merge_keyword_search_hits([body, paths], exact_query), limit)

    def _query_body_hits(
        self,
        db: sqlite3.Connection,
        query: str,
        limit: int,
        source_filter: _SourceFilter,
        ranking_query: str,
    ) -> list[KeywordHit]:
        fts_query = build_fts_query(query)
        if not fts_query:
            return []
        matchers = prepare_query_matchers(ranking_query)
        hits: list[KeywordHit] = []
        for row in db.execute(
            """
            SELECT c.id, c.path, c.start_line, c.end_line, c.source, c.text,
                   bm25(chunks_fts) AS rank
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.id
            WHERE chunks_fts MATCH ?"""
            + source_filter.and_sql
            + """
            ORDER BY rank
            LIMIT ?
            """,
            (fts_query, *source_filter.params, limit),
        ):
            text_score = bm25_rank_to_score(float(row[6]))
            hits.append(
                KeywordHit(
                    id=row[0],
                    path=row[1],
                    start_line=row[2],
                    end_line=row[3],
                    source=row[4],
                    snippet=truncate_utf16_safe(row[5], SNIPPET_MAX_CHARS),
                    score=score_fallback_keyword_result(
                        query_matchers=matchers, path=row[1], text=row[5], fts_score=text_score
                    ),
                    text_score=text_score,
                )
            )
        return hits

    def search_path_candidates(
        self,
        query: str,
        *,
        limit: int,
        exact_path_query: str | None = None,
        exact_path_limit: int | None = None,
        sources: set[str] | None = None,
        snippet_max_chars: int = SNIPPET_MAX_CHARS,
        db: sqlite3.Connection | None = None,
    ) -> list[KeywordHit]:
        """Return actual path candidates before body/hybrid merging.

        ``None`` leaves the exact-path budget implicit: ``limit`` bounds the
        entire result. An explicit budget reserves additional exact-path
        headroom. Ordinary search uses the same owner with an explicit budget
        of 200, inside its existing identity gate and generation transaction.
        A provided connection retains its caller's lifetime and transaction.
        """
        if limit <= 0:
            return []
        exact_query = query if exact_path_query is None else exact_path_query
        source_filter = _source_filter_clause(sources)
        if db is not None:
            return self._query_path_hits(
                db, query, exact_query, limit, source_filter,
                exact_path_limit=exact_path_limit, snippet_max_chars=snippet_max_chars,
            )
        with self._search_connection(None) as connection:
            return self._query_path_hits(
                connection, query, exact_query, limit, source_filter,
                exact_path_limit=exact_path_limit, snippet_max_chars=snippet_max_chars,
            )

    def _query_path_hits(
        self,
        db: sqlite3.Connection,
        query: str,
        exact_path_query: str,
        limit: int,
        source_filter: _SourceFilter,
        *,
        exact_path_limit: int | None = EXACT_PATH_CANDIDATE_LIMIT,
        snippet_max_chars: int = SNIPPET_MAX_CHARS,
    ) -> list[KeywordHit]:
        """``searchPathKeyword`` with bounded, live paths and coherent first chunks."""
        if limit <= 0:
            return []
        match_exact_path = prepare_exact_path_matcher(exact_path_query)
        db.create_function(
            "memory_exact_path_specificity", 1,
            lambda value: match_exact_path(value) if isinstance(value, str) else 0,
            deterministic=True,
        )
        db.create_function("memory_normalized_contains", 2, _normalized_contains, deterministic=True)
        explicit_headroom = exact_path_limit is not None
        exact_limit = max(0, math.floor(limit if exact_path_limit is None else exact_path_limit))
        patterns = build_exact_path_candidate_patterns(exact_path_query)
        plans = _path_plans(query)
        match_query, initial_terms, _ = plans[0] if plans else (None, [], query)
        path_filter = source_filter.and_sql.replace("c.source", "paths_fts.source")
        bounded_snippet = type(snippet_max_chars) is int and 0 < snippet_max_chars <= 2**53 - 1
        projection = (
            "COALESCE(substr(CAST(c.text AS BLOB), 1, ?), CAST(c.text AS BLOB))"
            if bounded_snippet else "c.text"
        )
        snippet_params = [snippet_max_chars * 4] if bounded_snippet else []
        encoding = db.execute("PRAGMA encoding").fetchone()[0].lower()

        def snippet(value: str | bytes) -> str:
            if isinstance(value, bytes):
                value = value.decode(encoding, errors="replace")
            return truncate_utf16_safe(value, snippet_max_chars)

        def terms_clause(terms: list[str]) -> str:
            return "".join(" AND memory_normalized_contains(paths_fts.path, ?) = 1" for _ in terms)

        # Retain live logical sources before LIMIT. The first-chunk projection
        # belongs to the same SQLite statement snapshot as path admission.
        first_chunk_join = (
            " JOIN chunks c ON c.id = (SELECT candidate.id FROM chunks candidate "
            "WHERE candidate.path = retained.path AND candidate.source = retained.source "
            "ORDER BY candidate.start_line, candidate.end_line, candidate.id LIMIT 1)"
        )
        live_clause = (
            " AND EXISTS (SELECT 1 FROM chunks live WHERE live.path = paths_fts.path "
            "AND live.source = paths_fts.source)"
        )

        def exact_rows(use_lexical: bool):
            if use_lexical:
                candidates = (
                    "candidates AS MATERIALIZED (SELECT paths_fts.path, paths_fts.source "
                    "FROM paths_fts WHERE "
                    + ("paths_fts MATCH ?" if match_query else "1=1")
                    + terms_clause(initial_terms) + path_filter + "), "
                    "pattern_candidates AS MATERIALIZED (SELECT path, source FROM candidates WHERE ("
                    + " OR ".join("path LIKE ? ESCAPE '\\'" for _ in patterns) + "))"
                )
                params = [*([match_query] if match_query else []), *initial_terms,
                          *source_filter.params, *patterns]
            else:
                candidates = (
                    "pattern_candidates AS MATERIALIZED (SELECT paths_fts.path, paths_fts.source "
                    "FROM paths_fts WHERE ("
                    + " OR ".join("paths_fts.path LIKE ? ESCAPE '\\'" for _ in patterns)
                    + ")" + path_filter + ")"
                )
                params = [*patterns, *source_filter.params]
            sql = (
                "WITH " + candidates + ", scored_paths AS MATERIALIZED ("
                "SELECT path, source, memory_exact_path_specificity(path) AS specificity "
                "FROM pattern_candidates), retained AS MATERIALIZED ("
                "SELECT path, source, specificity FROM scored_paths WHERE specificity > 0 "
                "AND EXISTS (SELECT 1 FROM chunks live WHERE live.path = scored_paths.path "
                "AND live.source = scored_paths.source) "
                "ORDER BY specificity DESC, path ASC, source ASC LIMIT ?) "
                "SELECT c.id, retained.path, retained.source, c.start_line, c.end_line, "
                + projection + ", retained.specificity FROM retained" + first_chunk_join
                + " ORDER BY retained.specificity DESC, retained.path ASC, retained.source ASC"
            )
            return db.execute(sql, [*params, exact_limit, *snippet_params]).fetchall()

        by_id: dict[str, KeywordHit] = {}
        if patterns and exact_limit > 0:
            lexical = exact_path_query.isascii() and (match_query is not None or bool(initial_terms))
            try:
                rows = exact_rows(lexical)
            except sqlite3.OperationalError:
                if not lexical:
                    raise
                rows = exact_rows(False)
            for identifier, path, source, first, last, text, specificity in rows:
                by_id[identifier] = KeywordHit(
                    id=identifier, path=path, start_line=first, end_line=last, source=source,
                    snippet=snippet(text), score=0.0, text_score=0.0, path_score=0.0,
                    exact_path_specificity=specificity, has_body_match=False,
                )
        if not any(match is not None or terms for match, terms, _ in plans):
            return list(by_id.values())

        def lexical_rows(match: str | None, terms: list[str], partition: str, result_limit: int):
            sql = (
                "WITH retained AS MATERIALIZED (SELECT paths_fts.path, paths_fts.source, "
                + ("bm25(paths_fts)" if match else "0") + " AS rank FROM paths_fts WHERE "
                + ("paths_fts MATCH ?" if match else "1=1") + terms_clause(terms)
                + path_filter + " AND memory_exact_path_specificity(paths_fts.path) "
                + (">" if partition == "exact" else "=") + " 0" + live_clause
                + " ORDER BY rank ASC, paths_fts.path ASC, paths_fts.source ASC LIMIT ?) "
                "SELECT c.id, retained.path, retained.source, c.start_line, c.end_line, "
                + projection + ", retained.rank FROM retained" + first_chunk_join
                + " ORDER BY retained.rank ASC, retained.path ASC, retained.source ASC"
            )
            params = [*([match] if match else []), *terms, *source_filter.params,
                      result_limit, *snippet_params]
            return db.execute(sql, params).fetchall()

        def load_partitions(match: str | None, terms: list[str]):
            return [
                *(lexical_rows(match, terms, "exact", exact_limit) if exact_limit > 0 else []),
                *lexical_rows(match, terms, "non-exact", limit),
            ]

        lexical_by_id: dict[str, KeywordHit] = {}
        for match, terms, plan_query in plans:
            if match is None and not terms:
                continue
            used_match = match is not None
            try:
                rows = load_partitions(match, terms)
            except sqlite3.OperationalError:
                if match is None:
                    raise
                fallback = list(dict.fromkeys([*_path_tokens(plan_query), *terms]))
                rows = load_partitions(None, fallback)
                used_match = False
            for identifier, path, source, first, last, text, rank in rows:
                path_score = bm25_rank_to_score(float(rank)) if used_match else 1.0
                existing = lexical_by_id.get(identifier)
                if existing is None:
                    lexical_by_id[identifier] = KeywordHit(
                        id=identifier, path=path, start_line=first, end_line=last, source=source,
                        snippet=snippet(text), score=path_score, text_score=0.0,
                        path_score=path_score, exact_path_specificity=match_exact_path(path),
                        has_body_match=False,
                    )
                else:
                    existing.path_score = max(existing.path_score, path_score)
                    existing.score = max(existing.score, path_score)
                    existing.exact_path_specificity = max(
                        existing.exact_path_specificity, match_exact_path(path)
                    )
        non_exact_count = 0
        for entry in sorted(lexical_by_id.values(), key=_path_hit_sort_key):
            if entry.exact_path_specificity > 0:
                exact = by_id.get(entry.id)
                if exact is not None:
                    exact.path_score = max(exact.path_score, entry.path_score)
                    exact.score = max(exact.score, entry.score)
                    exact.exact_path_specificity = max(
                        exact.exact_path_specificity, entry.exact_path_specificity
                    )
            elif non_exact_count < limit:
                by_id[entry.id] = entry
                non_exact_count += 1
        result_limit = exact_limit + limit if explicit_headroom else limit
        return sorted(by_id.values(), key=_path_hit_sort_key)[:result_limit]


def _path_hit_sort_key(hit: KeywordHit):
    # comparePathKeywordSearchResults
    return (
        -hit.exact_path_specificity,
        -hit.path_score if hit.exact_path_specificity == 0 else 0,
        locale_sort_key(hit.path),
        hit.start_line,
        locale_sort_key(hit.id),
    )


def _path_tokens(value: str) -> list[str]:
    """Literal path terms: Unicode letters, marks and numbers, plus underscore."""
    tokens: list[str] = []
    current: list[str] = []
    for character in value:
        if character == "_" or unicodedata.category(character)[0] in {"L", "M", "N"}:
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def _normalized_contains(value: object, term: object) -> int:
    return normalized_literal_contains(value, term)


def _path_plans(query: str) -> list[tuple[str | None, list[str], str]]:
    """``planPathKeywordSearch`` for the unicode61 tokenizer.

    The first plan is the FTS match of the query; for each canonical form a further plan
    matches the ASCII tokens and requires the non-ASCII ones as substrings (unicode61 matches
    whole tokens only).
    """
    plans: list[tuple[str | None, list[str], str]] = [(build_fts_query(query), [], query)]
    seen = {json.dumps([plans[0][0], []])}
    for form in dict.fromkeys(
        (unicodedata.normalize("NFC", query), unicodedata.normalize("NFD", query))
    ):
        tokens = [token for token in _path_tokens(form) if js_trim(token)]
        substring_terms = [token for token in tokens if not token.isascii()]
        if not substring_terms:
            continue
        ascii_tokens = [token for token in tokens if token.isascii()]
        match_query = (
            " AND ".join('"' + token.replace('"', "") + '"' for token in ascii_tokens)
            if ascii_tokens
            else None
        )
        key = json.dumps([match_query, substring_terms])
        if key not in seen:
            seen.add(key)
            plans.append((match_query, substring_terms, form))
    return plans


@contextmanager
def _vector_batch_snapshot(db: sqlite3.Connection) -> Iterator[None]:
    """Keep the last prefetched vector and its payload in one SQLite snapshot."""
    if db.in_transaction:
        yield
        return
    # CPython steps a cursor ahead before returning its current row. In a
    # caller-owned autocommit connection the final step could otherwise release
    # the batch snapshot before the last contender's payload is read. Native's
    # iterator retains that snapshot until its next call instead.
    db.execute("SAVEPOINT memory_vector_batch")
    try:
        yield
    except BaseException:
        db.execute("ROLLBACK TO memory_vector_batch")
        raise
    finally:
        db.execute("RELEASE memory_vector_batch")


def _checkpoint(signal: CancellationSignal | None) -> None:
    if signal is not None:
        signal.throw_if_aborted()


class _SourceFilter:
    def __init__(self, sources: set[str] | None):
        if not sources:
            self.sql = ""
            self.and_sql = ""
            self.params: tuple[str, ...] = ()
            return
        placeholders = ", ".join("?" for _ in sources)
        self.sql = f" WHERE source IN ({placeholders})"
        self.and_sql = f" AND c.source IN ({placeholders})"
        self.params = tuple(sorted(sources))


def _source_filter_clause(sources: set[str] | None) -> _SourceFilter:
    return _SourceFilter(sources)
