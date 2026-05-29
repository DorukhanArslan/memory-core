from __future__ import annotations

from memory_core.config import MemoryConfig
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.supplements import MemoryCorpusResult, MemoryCorpusSupplement, sort_corpus_results
from memory_core.tools.citations import citation_label, clamp_text, source_label


def memory_search(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    *,
    query: str,
    max_results: int = 5,
    min_score: float = 0.0,
    corpus: str = "all",
    supplements: list[MemoryCorpusSupplement] | None = None,
) -> dict:
    sources_by_corpus = {
        "all": {"memory", "sessions"},
        "memory": {"memory"},
        "sessions": {"sessions"},
        "wiki": set(),
    }
    if corpus not in sources_by_corpus:
        return {"results": [], "disabled": True, "error": f"unsupported corpus: {corpus}"}

    try:
        memory_results = []
        if corpus != "wiki":
            memory_results = [
                _serialize_result(config, item)
                for item in store.search(
                    query,
                    max_results=max_results,
                    min_score=min_score,
                    sources=sources_by_corpus[corpus],
                )
            ]
        supplement_results = _search_supplements(
            supplements or [],
            query=query,
            max_results=max_results,
            corpus=corpus,
        )
        results = _merge_corpus_results(
            memory_results=memory_results,
            supplement_results=supplement_results,
            max_results=max_results,
            balance_corpora=corpus == "all",
        )
        return {
            "results": results,
            "provider": store.embeddings.provider_id,
            "model": store.embeddings.model,
            "citations": config.citation_mode,
        }
    except Exception as exc:
        return {"results": [], "disabled": True, "error": str(exc)}


def _search_supplements(
    supplements: list[MemoryCorpusSupplement],
    *,
    query: str,
    max_results: int,
    corpus: str,
) -> list[MemoryCorpusResult]:
    if corpus in {"memory", "sessions"}:
        return []
    results: list[MemoryCorpusResult] = []
    for supplement in supplements:
        results.extend(supplement.search(query=query, max_results=max_results, corpus=corpus))
    return sort_corpus_results(results)[:max(1, max_results)]


def _merge_corpus_results(
    *,
    memory_results: list[dict],
    supplement_results: list[MemoryCorpusResult],
    max_results: int,
    balance_corpora: bool,
) -> list[dict]:
    sorted_memory = _sort_tool_results(memory_results)
    sorted_supplements = _sort_tool_results([dict(item) for item in supplement_results])
    if not balance_corpora or not sorted_memory or not sorted_supplements:
        return _sort_tool_results([*sorted_memory, *sorted_supplements])[:max_results]

    per_corpus_cap = _ceil_div(max_results, 2)
    selected_memory = sorted_memory[:per_corpus_cap]
    selected_supplements = sorted_supplements[:per_corpus_cap]
    selected = [*selected_memory, *selected_supplements]
    if len(selected) < max_results:
        selected.extend(
            _sort_tool_results(
                [
                    *sorted_memory[len(selected_memory):],
                    *sorted_supplements[len(selected_supplements):],
                ]
            )[: max_results - len(selected)]
        )
    return _sort_tool_results(selected)[:max_results]


def _sort_tool_results(results: list[dict]) -> list[dict]:
    return sorted(results, key=lambda item: (-float(item.get("score", 0)), item.get("path", "")))


def _ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)


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
