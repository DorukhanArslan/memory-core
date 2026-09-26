from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from memory_core.cancellation import CancellationSignal
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.index.chunking import MemoryChunk, chunk_markdown
from memory_core.index.fts import bm25_rank_to_score, build_fts_query
from memory_core.bootstrap._js import js_json_stringify
from memory_core.index.hybrid import (
    HybridKeywordResult,
    HybridResult,
    HybridVectorResult,
    merge_hybrid_results,
)
from memory_core.index.identity import (
    DEFAULT_FTS_TOKENIZER,
    FTS_ONLY_MODEL,
    MEMORY_INDEX_META_KEY,
    MEMORY_INDEX_META_TABLE,
    NO_PROVIDER_ID,
    parse_index_meta,
    resolve_configured_scope_hash,
    resolve_configured_sources_for_meta,
    resolve_memory_index_identity_state,
    resolve_memory_index_provider_identities,
)
from memory_core.index.keywords import extract_keywords
from memory_core.index.mmr import mmr_rerank
from memory_core.index.temporal_decay import (
    TemporalDecayConfig,
    apply_temporal_decay_to_hybrid_results,
)
from memory_core.index.vector import cosine_similarity
from memory_core.workspace import MemoryWorkspace

# OpenClaw caps per-keyword FTS fallback probes so long conversational queries
# cannot fan out into unbounded sqlite work (memory-core manager.ts).
KEYWORD_FALLBACK_SEARCH_TERM_LIMIT = 6

# Chunking recorded in the index identity (chunk_markdown defaults; upstream
# DEFAULT_CHUNK_TOKENS / DEFAULT_CHUNK_OVERLAP, src/agents/memory-search.ts).
CHUNK_TOKENS = 400
CHUNK_OVERLAP = 80
# memory-core always indexes memory files and session transcripts.
CONFIGURED_SOURCES = ("memory", "sessions")


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
    def __init__(self, config: MemoryConfig, embeddings: EmbeddingProvider | None):
        self.path = validate_store_config(config, embeddings)
        self.config = config
        self.flags = config.effective_flags()
        self.embeddings = embeddings
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    @contextmanager
    def _search_connection(self, signal: CancellationSignal | None) -> Iterator[sqlite3.Connection]:
        # A read-only connection the caller's signal can interrupt from another
        # thread (sqlite3 interrupt), closed when the search ends.
        db = self.connect()
        remove_listener = signal.add_listener(db.interrupt) if signal is not None else None
        try:
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
            # memory-host-sdk memory-schema.ts. Stores created before this table
            # existed read as "index metadata is missing" until their next reindex.
            db.execute(
                f"CREATE TABLE IF NOT EXISTS {MEMORY_INDEX_META_TABLE} "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )

    def _index_provider(self) -> dict[str, str] | None:
        # The embedder only counts while vector search is on; otherwise the
        # index is FTS-only (provider none / model fts-only).
        if not self.flags.vector_search or self.embeddings is None:
            return None
        return {"id": self.embeddings.provider_id, "model": self.embeddings.model}

    def _provider_key(self) -> str:
        cache_key_data = getattr(self.embeddings, "cache_key_data", None)
        if callable(cache_key_data):
            cache_key_data = cache_key_data()
        provider = self._index_provider()
        return resolve_memory_index_provider_identities(
            provider,
            cache_key_data=cache_key_data if provider is not None else None,
        )[0]["providerKey"]

    def read_index_meta(self) -> object:
        """The stored index identity JSON, or ``None`` (``readMeta``)."""
        with self.connect() as db:
            row = db.execute(
                f"SELECT value FROM {MEMORY_INDEX_META_TABLE} WHERE key = ?",
                (MEMORY_INDEX_META_KEY,),
            ).fetchone()
        return parse_index_meta(row[0] if row else None)

    def _has_indexed_chunks(self) -> bool:
        with self.connect() as db:
            return db.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is not None

    def index_identity(self) -> dict[str, str]:
        """Whether the index matches this store's provider and settings.

        ``{"status": "valid"}``, or ``missing``/``mismatched`` with an upstream
        reason (``manager-reindex-state.ts`` ``resolveMemoryIndexIdentityState``).
        Searches return no hits and ``memory_search`` pauses until
        :meth:`reindex` writes fresh metadata.
        """
        return resolve_memory_index_identity_state(
            meta=self.read_index_meta(),
            provider=self._index_provider(),
            provider_key=self._provider_key(),
            provider_key_known=True,
            configured_sources=resolve_configured_sources_for_meta(CONFIGURED_SOURCES),
            configured_scope_hash=resolve_configured_scope_hash(),
            chunk_tokens=CHUNK_TOKENS,
            chunk_overlap=CHUNK_OVERLAP,
            vector_ready=self._index_provider() is not None,
            has_indexed_chunks=self._has_indexed_chunks(),
            fts_tokenizer=DEFAULT_FTS_TOKENIZER,
        )

    def _build_index_meta(self, vector_dims: int | None) -> dict:
        # manager-sync-ops.ts nextMeta (same key order).
        provider = self._index_provider()
        meta = {
            "model": provider["model"] if provider is not None else FTS_ONLY_MODEL,
            "provider": provider["id"] if provider is not None else NO_PROVIDER_ID,
            "providerKey": self._provider_key(),
            "sources": resolve_configured_sources_for_meta(CONFIGURED_SOURCES),
            "scopeHash": resolve_configured_scope_hash(),
            "chunkTokens": CHUNK_TOKENS,
            "chunkOverlap": CHUNK_OVERLAP,
            "ftsTokenizer": DEFAULT_FTS_TOKENIZER,
        }
        if provider is not None and vector_dims:
            meta["vectorDims"] = vector_dims
        return meta

    def reindex(self, workspace: MemoryWorkspace) -> int:
        files = workspace.discover_indexable_files()
        chunks: list[MemoryChunk] = []
        for file in files:
            text = file.index_text if file.index_text is not None else file.abs_path.read_text(encoding="utf-8")
            chunks.extend(
                chunk_markdown(
                    file.rel_path,
                    text,
                    source=file.source,
                    target_tokens=CHUNK_TOKENS,
                    overlap_tokens=CHUNK_OVERLAP,
                )
            )

        if self.flags.vector_search and chunks:
            embeddings = self.embeddings.embed_documents([chunk.text for chunk in chunks])
        else:
            embeddings = [[] for _ in chunks]

        vector_dims = len(embeddings[0]) if embeddings and embeddings[0] else None
        with self.connect() as db:
            db.execute("DELETE FROM chunks")
            db.execute("DELETE FROM chunks_fts")
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                db.execute(
                    "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk.id,
                        chunk.path,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.source,
                        chunk.text,
                        json.dumps(embedding),
                    ),
                )
                db.execute(
                    "INSERT INTO chunks_fts(id, text) VALUES (?, ?)",
                    (chunk.id, chunk.text),
                )
            # Fresh identity in the same transaction as the chunks (writeMeta).
            db.execute(
                f"INSERT INTO {MEMORY_INDEX_META_TABLE} (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (MEMORY_INDEX_META_KEY, js_json_stringify(self._build_index_meta(vector_dims))),
            )

        return len(files)

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
    ) -> list[HybridResult]:
        """Search the index; ``signal`` aborts it at the next checkpoint.

        Returns no hits while :meth:`index_identity` is not valid (a store
        built with another provider/model/settings, or one never reindexed).
        Checkpoints mirror where OpenClaw's manager honours the tool's
        AbortSignal (``memory/manager.ts`` search, ``embedQueryWithRetry``):
        before and after the query embedding and between FTS probes; an abort
        also interrupts the open SQLite statement.
        """
        source_filter = _source_filter_clause(sources)
        _checkpoint(signal)
        # memory/manager.ts:680-685: no hits unless the index identity is valid.
        if self.index_identity()["status"] != "valid":
            return []

        if not self.flags.vector_search:
            return self._search_keyword_only(
                query,
                max_results=max_results,
                min_score=min_score,
                source_filter=source_filter,
                signal=signal,
            )

        query_embedding = self.embeddings.embed_query(query)
        _checkpoint(signal)
        with self._search_connection(signal) as db:
            rows = db.execute(
                "SELECT id, path, start_line, end_line, source, text, embedding FROM chunks"
                + source_filter.sql,
                source_filter.params,
            ).fetchall()
            vector = [
                HybridVectorResult(
                    id=row[0],
                    path=row[1],
                    start_line=row[2],
                    end_line=row[3],
                    source=row[4],
                    snippet=row[5],
                    vector_score=cosine_similarity(query_embedding, json.loads(row[6])),
                )
                for row in rows
            ]

            keyword: list[HybridKeywordResult] = []
            if self.flags.text_search:
                keyword = self._query_keyword_hits_with_fallback(
                    db, query, source_filter, signal
                )
        _checkpoint(signal)

        if not self.flags.text_search:
            # Vector-only mode mirrors OpenClaw's non-hybrid path: raw vector
            # scores, strict min-score filter, no keyword relaxation.
            ranked_vector = sorted(vector, key=lambda item: item.vector_score, reverse=True)
            return [
                HybridResult(
                    path=item.path,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    score=item.vector_score,
                    vector_score=item.vector_score,
                    text_score=0.0,
                    snippet=item.snippet,
                    source=item.source,
                )
                for item in ranked_vector
                if item.vector_score >= min_score
            ][:max_results]

        merged = merge_hybrid_results(
            vector=vector,
            keyword=keyword,
            vector_weight=self.config.vector_weight,
            text_weight=self.config.text_weight,
        )
        decayed = apply_temporal_decay_to_hybrid_results(
            merged,
            temporal_decay=TemporalDecayConfig(
                enabled=self.flags.temporal_decay,
                half_life_days=self.config.temporal_decay_half_life_days,
            ),
            workspace_dir=str(self.config.workspace_dir),
        )
        ranked = sorted(decayed, key=lambda item: item.score, reverse=True)
        if self.flags.mmr:
            by_key = {
                _mmr_key(item): item
                for item in ranked
            }
            reranked = mmr_rerank(
                [
                    {
                        "id": key,
                        "score": item.score,
                        "content": item.snippet,
                    }
                    for key, item in by_key.items()
                ],
                enabled=True,
                lambda_=self.config.mmr_lambda,
            )
            ranked = [by_key[str(item["id"])] for item in reranked]

        strict = [item for item in ranked if item.score >= min_score]
        if strict or not keyword:
            return strict[:max_results]

        keyword_keys = {
            f"{item.source}:{item.path}:{item.start_line}:{item.end_line}"
            for item in keyword
        }
        return [
            item
            for item in ranked
            if _mmr_key(item) in keyword_keys and item.score >= 0
        ][:max_results]

    def _search_keyword_only(
        self,
        query: str,
        *,
        max_results: int,
        min_score: float,
        source_filter: _SourceFilter,
        signal: CancellationSignal | None = None,
    ) -> list[HybridResult]:
        # OpenClaw FTS-only mode ("provider: none"): keyword hits keep their
        # full text score (no text-weight scaling), temporal decay still
        # applies, and an empty strict pass relaxes the min-score to 0.
        with self._search_connection(signal) as db:
            keyword = self._query_keyword_hits_with_fallback(db, query, source_filter, signal)
        _checkpoint(signal)
        results = [
            HybridResult(
                path=item.path,
                start_line=item.start_line,
                end_line=item.end_line,
                score=item.text_score,
                vector_score=0.0,
                text_score=item.text_score,
                snippet=item.snippet,
                source=item.source,
            )
            for item in keyword
        ]
        decayed = apply_temporal_decay_to_hybrid_results(
            results,
            temporal_decay=TemporalDecayConfig(
                enabled=self.flags.temporal_decay,
                half_life_days=self.config.temporal_decay_half_life_days,
            ),
            workspace_dir=str(self.config.workspace_dir),
        )
        ranked = sorted(decayed, key=lambda item: item.score, reverse=True)
        strict = [item for item in ranked if item.score >= min_score]
        if strict:
            return strict[:max_results]
        return [item for item in ranked if item.score >= 0][:max_results]

    def _query_keyword_hits_with_fallback(
        self,
        db: sqlite3.Connection,
        query: str,
        source_filter: _SourceFilter,
        signal: CancellationSignal | None = None,
    ) -> list[HybridKeywordResult]:
        full_query_hits = self._query_keyword_hits(db, query, source_filter)
        if full_query_hits:
            return full_query_hits

        # OpenClaw broadens recall for conversational queries when the exact
        # AND query is too strict: probe each extracted keyword separately
        # (capped), then dedupe preferring the higher text score. Upstream
        # additionally tie-breaks equal text scores by a boosted lexical score;
        # memory-core keeps raw FTS text scores by design (see
        # _search_keyword_only), so the text-score preference is the only
        # ranking signal here.
        fallback_terms = [term for term in extract_keywords(query) if term != query]
        fallback_terms = fallback_terms[:KEYWORD_FALLBACK_SEARCH_TERM_LIMIT]
        if not fallback_terms:
            return []

        result_sets = []
        for term in fallback_terms:
            _checkpoint(signal)
            result_sets.append(self._query_keyword_hits(db, term, source_filter))
        return _merge_keyword_search_hits(result_sets)

    def _query_keyword_hits(
        self,
        db: sqlite3.Connection,
        query: str,
        source_filter: _SourceFilter,
    ) -> list[HybridKeywordResult]:
        fts_query = build_fts_query(query)
        if not fts_query:
            return []
        return [
            HybridKeywordResult(
                id=row[0],
                path=row[1],
                start_line=row[2],
                end_line=row[3],
                source=row[4],
                snippet=row[5],
                text_score=bm25_rank_to_score(float(row[6])),
            )
            for row in db.execute(
                """
                SELECT c.id, c.path, c.start_line, c.end_line, c.source, c.text,
                       bm25(chunks_fts) AS rank
                FROM chunks_fts
                JOIN chunks c ON c.id = chunks_fts.id
                WHERE chunks_fts MATCH ?""" + source_filter.and_sql + """
                ORDER BY rank
                """,
                (fts_query, *source_filter.params),
            )
        ]


def _checkpoint(signal: CancellationSignal | None) -> None:
    if signal is not None:
        signal.throw_if_aborted()


def _merge_keyword_search_hits(
    result_sets: list[list[HybridKeywordResult]],
) -> list[HybridKeywordResult]:
    merged: dict[str, HybridKeywordResult] = {}
    for results in result_sets:
        for result in results:
            existing = merged.get(result.id)
            if existing is None or result.text_score > existing.text_score:
                merged[result.id] = result
    return sorted(merged.values(), key=lambda item: item.text_score, reverse=True)


def _mmr_key(item: HybridResult) -> str:
    return f"{item.source}:{item.path}:{item.start_line}:{item.end_line}"


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
