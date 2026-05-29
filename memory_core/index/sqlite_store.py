from __future__ import annotations

import json
import sqlite3

from memory_core.config import MemoryConfig
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.index.chunking import MemoryChunk, chunk_markdown
from memory_core.index.fts import bm25_rank_to_score, build_fts_query
from memory_core.index.hybrid import (
    HybridKeywordResult,
    HybridResult,
    HybridVectorResult,
    merge_hybrid_results,
)
from memory_core.index.mmr import mmr_rerank
from memory_core.index.temporal_decay import (
    TemporalDecayConfig,
    apply_temporal_decay_to_hybrid_results,
)
from memory_core.index.vector import cosine_similarity
from memory_core.workspace import MemoryWorkspace


class SQLiteMemoryStore:
    def __init__(self, config: MemoryConfig, embeddings: EmbeddingProvider):
        self.config = config
        self.embeddings = embeddings
        self.path = config.resolved_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

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

    def reindex(self, workspace: MemoryWorkspace) -> int:
        files = workspace.discover_indexable_files()
        chunks: list[MemoryChunk] = []
        for file in files:
            text = file.abs_path.read_text(encoding="utf-8")
            chunks.extend(
                chunk_markdown(
                    file.rel_path,
                    text,
                    source=file.source,
                )
            )

        embeddings = (
            self.embeddings.embed_documents([chunk.text for chunk in chunks]) if chunks else []
        )

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
    ) -> list[HybridResult]:
        query_embedding = self.embeddings.embed_query(query)
        with self.connect() as db:
            source_filter = _source_filter_clause(sources)
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
            fts_query = build_fts_query(query)
            if fts_query:
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
                ):
                    keyword.append(
                        HybridKeywordResult(
                            id=row[0],
                            path=row[1],
                            start_line=row[2],
                            end_line=row[3],
                            source=row[4],
                            snippet=row[5],
                            text_score=bm25_rank_to_score(float(row[6])),
                        )
                    )

        merged = merge_hybrid_results(
            vector=vector,
            keyword=keyword,
            vector_weight=self.config.vector_weight,
            text_weight=self.config.text_weight,
        )
        decayed = apply_temporal_decay_to_hybrid_results(
            merged,
            temporal_decay=TemporalDecayConfig(
                enabled=self.config.temporal_decay_enabled,
                half_life_days=self.config.temporal_decay_half_life_days,
            ),
            workspace_dir=str(self.config.workspace_dir),
        )
        ranked = sorted(decayed, key=lambda item: item.score, reverse=True)
        if self.config.mmr_enabled:
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
