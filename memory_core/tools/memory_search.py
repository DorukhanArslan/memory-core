from __future__ import annotations

from memory_core.config import MemoryConfig
from memory_core.index.sqlite_store import SQLiteMemoryStore


def memory_search(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    *,
    query: str,
    max_results: int = 5,
    min_score: float = 0.0,
    corpus: str = "memory",
) -> dict:
    if corpus != "memory":
        return {"results": [], "disabled": True, "error": f"unsupported corpus: {corpus}"}

    try:
        results = store.search(query, max_results=max_results, min_score=min_score)
        return {
            "results": [
                {
                    "corpus": "memory",
                    "path": item.path,
                    "startLine": item.start_line,
                    "endLine": item.end_line,
                    "score": item.score,
                    "vectorScore": item.vector_score,
                    "textScore": item.text_score,
                    "snippet": item.snippet,
                    "source": item.source,
                }
                for item in results
            ],
            "provider": store.embeddings.provider_id,
            "model": store.embeddings.model,
        }
    except Exception as exc:
        return {"results": [], "disabled": True, "error": str(exc)}
