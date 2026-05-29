from __future__ import annotations

from memory_core.config import MemoryConfig
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.tools.citations import citation_label, clamp_text, source_label


def memory_search(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    *,
    query: str,
    max_results: int = 5,
    min_score: float = 0.0,
    corpus: str = "all",
) -> dict:
    sources_by_corpus = {
        "all": {"memory", "sessions"},
        "memory": {"memory"},
        "sessions": {"sessions"},
    }
    if corpus not in sources_by_corpus:
        return {"results": [], "disabled": True, "error": f"unsupported corpus: {corpus}"}

    try:
        results = store.search(
            query,
            max_results=max_results,
            min_score=min_score,
            sources=sources_by_corpus[corpus],
        )
        return {
            "results": [
                _serialize_result(config, item)
                for item in results
            ],
            "provider": store.embeddings.provider_id,
            "model": store.embeddings.model,
            "citations": config.citation_mode,
        }
    except Exception as exc:
        return {"results": [], "disabled": True, "error": str(exc)}


def _serialize_result(config: MemoryConfig, item) -> dict:
    snippet = clamp_text(item.snippet, max_chars=config.memory_get_max_chars)
    citation = citation_label(item.path, item.start_line, item.end_line)
    snippet_text = snippet.text
    if config.citation_mode == "on":
        snippet_text = f"{snippet.text.strip()}\n\nSource: {citation}"
    return {
        "corpus": item.source,
        "path": item.path,
        "startLine": item.start_line,
        "endLine": item.end_line,
        "score": item.score,
        "vectorScore": item.vector_score,
        "textScore": item.text_score,
        "snippet": snippet_text,
        "source": item.source,
        "citation": source_label(item.path, item.start_line, item.end_line),
        "truncated": snippet.truncated,
        "originalChars": snippet.original_chars,
    }
