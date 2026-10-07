from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from memory_core.cancellation import CancellationSignal
from memory_core.config import MemoryConfig
from memory_core.consolidation.origins import IndexRevisionFence
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.index.chunking import MemoryChunk, chunk_markdown
from memory_core.index.fts import bm25_rank_to_score, build_fts_query
from memory_core.bootstrap._js import js_json_stringify, js_trim, locale_sort_key
from memory_core.index.cjk_chars import truncate_utf16_safe
from memory_core.index.hybrid import (
    HybridKeywordResult,
    HybridResult,
    HybridVectorResult,
    merge_hybrid_results,
    score_exact_path_tie_for_temporal_decay,
    select_hybrid_search_results,
)
from memory_core.index.keyword_search import (
    EXACT_PATH_CANDIDATE_LIMIT,
    SNIPPET_MAX_CHARS,
    KeywordHit,
    keyword_hit_sort_key,
    limit_keyword_search_hits,
    merge_keyword_search_hits,
    prepare_exact_path_matcher,
    prepare_query_matchers,
    score_fallback_keyword_result,
)
from memory_core.index.identity import (
    DEFAULT_FTS_TOKENIZER,
    FTS_ONLY_MODEL,
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
from memory_core.index.temporal_decay import (
    TemporalDecayConfig,
    apply_temporal_decay_to_hybrid_results,
)
from memory_core.index.vector import cosine_similarity
from memory_core.workspace import MemoryWorkspace

# OpenClaw caps per-keyword FTS fallback probes so long conversational queries
# cannot fan out into unbounded sqlite work (memory-core manager.ts).
KEYWORD_FALLBACK_SEARCH_TERM_LIMIT = 6
# manager-search-orchestration.ts SEARCH_CANDIDATE_UNIVERSE and src/agents/memory-search.ts
# DEFAULT_HYBRID_CANDIDATE_MULTIPLIER.
SEARCH_CANDIDATE_UNIVERSE = 200
HYBRID_CANDIDATE_MULTIPLIER = 4

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
    def __init__(
        self,
        config: MemoryConfig,
        embeddings: EmbeddingProvider | None,
        *,
        revision_fence: IndexRevisionFence | None = None,
    ):
        # The ``memory_index_state`` fence a rebuild is published against (see :meth:`reindex`);
        # assignable after construction, ``None`` (default) means no fence.
        self.revision_fence = revision_fence
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

    def index_identity(self) -> dict[str, Any]:
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
            "chunkingVersion": MEMORY_CHUNKING_VERSION,
            "ftsTokenizer": DEFAULT_FTS_TOKENIZER,
            "provenanceVersion": MEMORY_INDEX_PROVENANCE_VERSION,
        }
        if provider is not None and vector_dims:
            meta["vectorDims"] = vector_dims
        return meta

    def reindex(self, workspace: MemoryWorkspace) -> int:
        """Rebuild the index from every discovered file; returns the files indexed.

        Markdown is decoded like upstream ``buildFileEntry``
        (``packages/memory-host-sdk/src/host/internal.ts:292-304``):
        ``Buffer.toString("utf-8")`` replaces invalid bytes, so an AppleDouble
        ``._*.md`` or a Latin-1 note never fails the reindex, and a file that
        vanished after discovery is skipped (upstream returns ``null``).

        With a ``revision_fence`` (:class:`~memory_core.consolidation.origins.IndexRevisionFence`) the
        rebuild is published like upstream's (``manager-sync-ops.ts``, ``publishMemoryDatabaseTables``):
        the ``memory_index_state`` revision is read before anything is built and compared again in the
        publication transaction, so a forget (a session tombstone) or any other index mutation in between
        raises :class:`~memory_core.consolidation.origins.MemoryIndexRevisionConflictError` and leaves the
        published index untouched (the caller retries); a successful publication bumps the revision (the
        index tables' triggers upstream), which fails a rebuild that was prepared before it. See the fence
        for what is atomic when the index lives in another file than the ledger.
        """
        fence = self.revision_fence
        expected_revision = fence.read() if fence is not None else None
        files = workspace.discover_indexable_files()
        chunks: list[MemoryChunk] = []
        indexed_files = 0
        for file in files:
            if file.index_text is not None:
                text = file.index_text
            else:
                try:
                    text = file.abs_path.read_text(encoding="utf-8", errors="replace")
                except FileNotFoundError:
                    continue
            indexed_files += 1
            chunks.extend(
                chunk_markdown(
                    file.rel_path,
                    text,
                    source=file.source,
                    target_tokens=CHUNK_TOKENS,
                    overlap_tokens=CHUNK_OVERLAP,
                    # manager-index-preparation.ts: the curated files chunk per entry.
                    per_entry=file.source == "memory"
                    and file.rel_path.replace("\\", "/") in ("MEMORY.md", "USER.md"),
                )
            )

        if self.flags.vector_search and chunks:
            embeddings = self.embeddings.embed_documents([chunk.text for chunk in chunks])
        else:
            embeddings = [[] for _ in chunks]

        vector_dims = len(embeddings[0]) if embeddings and embeddings[0] else None
        same_database = fence is not None and fence.same_database(self.path)
        if fence is not None and not same_database:
            fence.assert_unchanged(expected_revision)
        with self.connect() as db:
            if fence is not None and same_database:
                # The publication transaction owns the write lock before the revision is compared.
                db.execute("BEGIN IMMEDIATE")
                fence.assert_unchanged_in(db, expected_revision)
            db.execute("DELETE FROM chunks")
            db.execute("DELETE FROM chunks_fts")
            db.execute("DELETE FROM paths_fts")
            db.executemany(
                "INSERT INTO paths_fts(path, source) VALUES (?, ?)",
                sorted({(chunk.path, chunk.source) for chunk in chunks}),
            )
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
            if fence is not None and same_database:
                fence.bump_in(db)
        if fence is not None and not same_database:
            fence.bump()

        return indexed_files

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

        Like ``manager-search-orchestration.ts`` one window of at least 200 candidates is
        ranked, then trimmed to ``max_results``: keyword hits (chunk text and file path, with
        exact-path tiers), vector hits, the hybrid merge with temporal decay and MMR, and the
        selection under ``min_score``.
        """
        normalized = js_trim(query)
        if not normalized:
            return []
        _checkpoint(signal)
        # memory/manager.ts:680-685: no hits unless the index identity is valid.
        if self.index_identity()["status"] != "valid":
            return []
        window = max(SEARCH_CANDIDATE_UNIVERSE, max_results)
        results = self._search_candidates(
            normalized,
            max_results=window,
            min_score=min_score,
            sources=sources,
            signal=signal,
        )
        return results[:max_results]

    def search_memory_keywords(
        self, query: str, *, max_results: int = 5, min_score: float = 0.0
    ) -> list[HybridResult]:
        """Memory-file keyword hits without the query embedding.

        What ``memory_search`` returns as a partial result when semantic retrieval
        misses its deadline (OpenClaw's ``onPartialResults`` of the memory manager):
        FTS only, session transcripts excluded, nothing when keyword search is off or
        the index identity is not valid.
        """
        normalized = js_trim(query)
        if (
            not normalized
            or not self.flags.text_search
            or self.index_identity()["status"] != "valid"
        ):
            return []
        window = max(SEARCH_CANDIDATE_UNIVERSE, max_results)
        candidates = min(200, max(1, window * HYBRID_CANDIDATE_MULTIPLIER))
        with self._search_connection(None) as db:
            hits = self._search_keyword_with_fallback(
                db, normalized, candidates, _source_filter_clause({"memory"}), None
            )
        return self._finalize_keyword_only(hits, max_results, min_score)[:max_results]

    def _search_candidates(
        self,
        query: str,
        *,
        max_results: int,
        min_score: float,
        sources: set[str] | None,
        signal: CancellationSignal | None,
    ) -> list[HybridResult]:
        source_filter = _source_filter_clause(sources)
        candidates = min(200, max(1, max_results * HYBRID_CANDIDATE_MULTIPLIER))
        keyword: list[KeywordHit] = []
        vector_ready = self.flags.vector_search
        query_embedding: list[float] = []
        if vector_ready:
            query_embedding = self.embeddings.embed_query(query)
            _checkpoint(signal)
        with self._search_connection(signal) as db:
            if db.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is None:
                return []
            if self.flags.text_search:
                keyword = self._search_keyword_with_fallback(
                    db, query, candidates, source_filter, signal
                )
            vector: list[HybridVectorResult] = []
            if vector_ready and any(value != 0 for value in query_embedding):
                match_exact_path = prepare_exact_path_matcher(query)
                rows = db.execute(
                    "SELECT id, path, start_line, end_line, source, text, embedding FROM chunks"
                    + source_filter.sql,
                    source_filter.params,
                ).fetchall()
                scored = [
                    HybridVectorResult(
                        id=row[0],
                        path=row[1],
                        start_line=row[2],
                        end_line=row[3],
                        source=row[4],
                        snippet=truncate_utf16_safe(row[5], SNIPPET_MAX_CHARS),
                        vector_score=cosine_similarity(query_embedding, json.loads(row[6])),
                        exact_path_specificity=match_exact_path(row[1]),
                    )
                    for row in rows
                ]
                scored.sort(key=lambda item: -item.vector_score)
                vector = scored[:candidates]
        _checkpoint(signal)

        if not vector_ready:
            return self._finalize_keyword_only(keyword, max_results, min_score)

        decay = TemporalDecayConfig(
            enabled=self.flags.temporal_decay,
            half_life_days=self.config.temporal_decay_half_life_days,
        )
        workspace_dir = str(self.config.workspace_dir)
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
                    )
                    for item in vector
                ],
                temporal_decay=decay,
                workspace_dir=workspace_dir,
            )
            return sorted(
                (item for item in decayed if item.score >= min_score),
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
                )
                for hit in keyword
            ],
            vector_weight=self.config.vector_weight,
            text_weight=self.config.text_weight,
            workspace_dir=workspace_dir,
            temporal_decay=decay,
            mmr_enabled=self.flags.mmr,
            mmr_lambda=self.config.mmr_lambda,
        )
        return select_hybrid_search_results(
            merged=merged, keyword=keyword, max_results=max_results, min_score=min_score
        )

    def _finalize_keyword_only(
        self, hits: list[KeywordHit], max_results: int, min_score: float
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
        )
        ranked = sorted(
            decayed, key=lambda hit: keyword_hit_sort_key(hit, prefer_exact_body=not applies_decay)
        )
        # Specificity and adjusted body relevance are preserved before the exact public
        # scores are normalized.
        ranked = [
            dataclasses.replace(hit, score=1.0) if hit.exact_path_specificity > 0 else hit
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

    def _first_chunk(self, db: sqlite3.Connection, path: str, source: str):
        return db.execute(
            "SELECT id, start_line, end_line, text FROM chunks WHERE path = ? AND source = ? "
            "ORDER BY start_line, end_line, id LIMIT 1",
            (path, source),
        ).fetchone()

    def _query_path_hits(
        self,
        db: sqlite3.Connection,
        query: str,
        exact_path_query: str,
        limit: int,
        source_filter: _SourceFilter,
    ) -> list[KeywordHit]:
        """``searchPathKeyword``: exact file, basename and stem matches, then partial path hits."""
        if limit <= 0:
            return []
        match_exact_path = prepare_exact_path_matcher(exact_path_query)
        db.create_function("memory_exact_path_specificity", 1, match_exact_path, deterministic=True)
        db.create_function("memory_normalized_contains", 2, _normalized_contains, deterministic=True)
        where = source_filter.sql
        exact_rows = []
        for path, source in db.execute(f"SELECT path, source FROM paths_fts{where}", source_filter.params):
            specificity = match_exact_path(path)
            if specificity > 0:
                exact_rows.append((specificity, path, source))
        exact_rows.sort(key=lambda row: (-row[0], row[1], row[2]))
        by_id: dict[str, KeywordHit] = {}
        for specificity, path, source in exact_rows[:EXACT_PATH_CANDIDATE_LIMIT]:
            chunk = self._first_chunk(db, path, source)
            if chunk is None:
                continue
            by_id[chunk[0]] = KeywordHit(
                id=chunk[0],
                path=path,
                start_line=chunk[1],
                end_line=chunk[2],
                source=source,
                snippet=truncate_utf16_safe(chunk[3], SNIPPET_MAX_CHARS),
                score=0.0,
                text_score=0.0,
                path_score=0.0,
                exact_path_specificity=specificity,
                has_body_match=False,
            )

        lexical_by_id: dict[str, KeywordHit] = {}
        for match_query, terms in _path_plans(query):
            if match_query is None and not terms:
                continue
            for partition in ("exact", "non-exact"):
                part_limit = EXACT_PATH_CANDIDATE_LIMIT if partition == "exact" else limit
                clause = " AND memory_exact_path_specificity(path) " + (">" if partition == "exact" else "=") + " 0"
                filters = "".join(" AND memory_normalized_contains(path, ?) = 1" for _ in terms)
                sql = (
                    "SELECT path, source, "
                    + ("bm25(paths_fts)" if match_query else "0")
                    + " AS rank FROM paths_fts WHERE "
                    + ("paths_fts MATCH ?" if match_query else "1=1")
                    + filters
                    + source_filter.and_sql.replace("c.source", "source")
                    + clause
                    + " ORDER BY rank ASC, path ASC, source ASC LIMIT ?"
                )
                params = [*( [match_query] if match_query else []), *terms, *source_filter.params, part_limit]
                for path, source, rank in db.execute(sql, params).fetchall():
                    chunk = self._first_chunk(db, path, source)
                    if chunk is None:
                        continue
                    path_score = bm25_rank_to_score(float(rank)) if match_query else 1.0
                    existing = lexical_by_id.get(chunk[0])
                    if existing is None:
                        lexical_by_id[chunk[0]] = KeywordHit(
                            id=chunk[0],
                            path=path,
                            start_line=chunk[1],
                            end_line=chunk[2],
                            source=source,
                            snippet=truncate_utf16_safe(chunk[3], SNIPPET_MAX_CHARS),
                            score=path_score,
                            text_score=0.0,
                            path_score=path_score,
                            exact_path_specificity=match_exact_path(path),
                            has_body_match=False,
                        )
                        continue
                    existing.path_score = max(existing.path_score, path_score)
                    existing.score = max(existing.score, path_score)
        non_exact_count = 0
        for entry in sorted(lexical_by_id.values(), key=_path_hit_sort_key):
            if entry.exact_path_specificity > 0:
                exact = by_id.get(entry.id)
                if exact is None:
                    continue
                exact.path_score = max(exact.path_score, entry.path_score)
                exact.score = max(exact.score, entry.score)
                exact.exact_path_specificity = max(
                    exact.exact_path_specificity, entry.exact_path_specificity
                )
                continue
            if non_exact_count >= limit:
                continue
            by_id[entry.id] = entry
            non_exact_count += 1
        # Exact filenames get bounded headroom on top of `limit`.
        return sorted(by_id.values(), key=_path_hit_sort_key)[: EXACT_PATH_CANDIDATE_LIMIT + limit]


def _path_hit_sort_key(hit: KeywordHit):
    # comparePathKeywordSearchResults
    return (
        -hit.exact_path_specificity,
        -hit.path_score if hit.exact_path_specificity == 0 else 0,
        locale_sort_key(hit.path),
        hit.start_line,
        locale_sort_key(hit.id),
    )


_PATH_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def _normalized_contains(value: object, term: object) -> int:
    if not isinstance(value, str) or not isinstance(term, str):
        return 0
    return int(
        unicodedata.normalize("NFC", term).lower() in unicodedata.normalize("NFC", value).lower()
    )


def _path_plans(query: str) -> list[tuple[str | None, list[str]]]:
    """``planPathKeywordSearch`` for the unicode61 tokenizer.

    The first plan is the FTS match of the query; for each canonical form a further plan
    matches the ASCII tokens and requires the non-ASCII ones as substrings (unicode61 matches
    whole tokens only).
    """
    plans: list[tuple[str | None, list[str]]] = [(build_fts_query(query), [])]
    seen = {json.dumps([plans[0][0], []])}
    for form in dict.fromkeys(
        (unicodedata.normalize("NFC", query), unicodedata.normalize("NFD", query))
    ):
        tokens = [
            token
            for token in _PATH_TOKEN_RE.findall(form)
            if token.strip()
        ]
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
            plans.append((match_query, substring_terms))
    return plans


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
