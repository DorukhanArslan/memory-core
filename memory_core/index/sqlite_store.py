from __future__ import annotations

import json
import sqlite3

from memory_core.config import MemoryConfig
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.index.chunking import MemoryChunk, chunk_markdown
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
        files = workspace.discover_memory_files()
        chunks: list[MemoryChunk] = []
        for file in files:
            text = file.abs_path.read_text(encoding="utf-8")
            chunks.extend(chunk_markdown(file.rel_path, text))

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
