"""The ``memory_search`` tool (OpenClaw ``extensions/memory-core/src/tools.ts``).

``createMemorySearchTool`` reads its params before any search work
(``readStringParam`` / ``readPositiveIntegerParam`` / ``readFiniteNumberParam``,
``src/agents/tools/common.ts``). Invalid input raises
:class:`~memory_core.tools.common.MemoryToolInputError`; a host tool loop turns it
into ``{"status": "error", "tool": "memory_search", "error": ...}`` with
``to_tool_error()``.

``corpus`` has no enum check in the tool itself (the schema enum
``memory|wiki|all|sessions`` in ``tools.shared.ts`` is enforced by the agent
loop's argument validation, which the host owns). An omitted or unknown corpus
searches every indexed source and skips supplements, as upstream.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from memory_core.config import MemoryConfig
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.supplements import MemoryCorpusResult, MemoryCorpusSupplement, sort_corpus_results
from memory_core.tools.citations import citation_label, clamp_text, source_label
from memory_core.tools.common import (
    MemoryToolInputError,
    as_tool_params_record,
    read_finite_number_param,
    read_positive_integer_param,
    read_string_param,
)

MEMORY_SEARCH_TOOL_NAME = "memory_search"

# Used when the caller omits maxResults/minScore. Upstream falls back to the
# agent's memorySearch.query config (6 / 0.35, src/agents/memory-search.ts);
# memory-core keeps its facade defaults (documented deviation).
DEFAULT_MEMORY_SEARCH_MAX_RESULTS = 5
DEFAULT_MEMORY_SEARCH_MIN_SCORE = 0.0
# tools.ts: `Math.max(1, maxResults ?? 10)` caps the merged memory+supplement list.
MEMORY_SEARCH_MERGE_DEFAULT_MAX_RESULTS = 10


@dataclass(frozen=True)
class MemorySearchParams:
    """Validated ``memory_search`` params; ``None`` means the caller omitted it."""

    query: str
    max_results: int | None
    min_score: float | None
    corpus: str | None


def read_memory_search_params(params: object) -> MemorySearchParams:
    """Read tool-call params exactly like ``createMemorySearchTool`` (tools.ts:402-412).

    Accepts camelCase keys and their snake_case aliases (``max_results``,
    ``min_score``) and strict numeric strings (``"5"``, ``"0.3"``). Raises
    :class:`MemoryToolInputError` with the upstream message on invalid input.
    """
    raw = as_tool_params_record(params)
    try:
        query = read_string_param(raw, "query", required=True)
        max_results = read_positive_integer_param(raw, "maxResults")
        min_score = read_finite_number_param(raw, "minScore")
        corpus = read_string_param(raw, "corpus")
    except MemoryToolInputError as error:
        error.tool = MEMORY_SEARCH_TOOL_NAME
        raise
    return MemorySearchParams(
        query=query,
        max_results=max_results,
        min_score=min_score,
        corpus=corpus,
    )


def execute_memory_search_tool(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    params: Mapping[str, Any] | None,
    *,
    supplements: list[MemoryCorpusSupplement] | None = None,
) -> dict:
    """Run ``memory_search`` on raw tool-call params (the model's arguments)."""
    parsed = read_memory_search_params(params)
    return _run_memory_search(config, store, parsed, supplements=supplements or [])


def memory_search(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    *,
    query: str,
    max_results: int | None = DEFAULT_MEMORY_SEARCH_MAX_RESULTS,
    min_score: float | None = DEFAULT_MEMORY_SEARCH_MIN_SCORE,
    corpus: str | None = "all",
    supplements: list[MemoryCorpusSupplement] | None = None,
) -> dict:
    """Python-call form of the tool; ``None`` for a param means "omitted"."""
    return execute_memory_search_tool(
        config,
        store,
        {"query": query, "maxResults": max_results, "minScore": min_score, "corpus": corpus},
        supplements=supplements,
    )


def _memory_sources_for_corpus(corpus: str | None) -> set[str] | None:
    if corpus == "sessions":
        return {"sessions"}
    if corpus == "memory":
        return {"memory"}
    return None


def _run_memory_search(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    params: MemorySearchParams,
    *,
    supplements: list[MemoryCorpusSupplement],
) -> dict:
    requested_corpus = params.corpus
    should_query_supplements = requested_corpus in {"wiki", "all"}
    should_query_memory = requested_corpus != "wiki"
    try:
        memory_results = []
        if should_query_memory:
            sources = _memory_sources_for_corpus(requested_corpus)
            hits = store.search(
                params.query,
                max_results=(
                    params.max_results
                    if params.max_results is not None
                    else DEFAULT_MEMORY_SEARCH_MAX_RESULTS
                ),
                min_score=(
                    params.min_score
                    if params.min_score is not None
                    else DEFAULT_MEMORY_SEARCH_MIN_SCORE
                ),
                sources=sources,
            )
            memory_results = [_serialize_result(config, item) for item in hits]
        supplement_results = (
            _search_supplements(
                supplements,
                query=params.query,
                max_results=params.max_results,
                corpus=requested_corpus,
            )
            if should_query_supplements
            else []
        )
        results = _merge_corpus_results(
            memory_results=memory_results,
            supplement_results=supplement_results,
            max_results=max(
                1,
                params.max_results
                if params.max_results is not None
                else MEMORY_SEARCH_MERGE_DEFAULT_MAX_RESULTS,
            ),
            balance_corpora=requested_corpus == "all",
        )
        # OpenClaw reports FTS-only mode as provider "none" / model "fts-only"
        # when no embedding provider is configured.
        embeddings = store.embeddings
        return {
            "results": results,
            "provider": embeddings.provider_id if embeddings is not None else "none",
            "model": embeddings.model if embeddings is not None else "fts-only",
            "citations": config.citation_mode,
        }
    except Exception as exc:
        return {"results": [], "disabled": True, "error": str(exc)}


def _search_supplements(
    supplements: list[MemoryCorpusSupplement],
    *,
    query: str,
    max_results: int | None,
    corpus: str | None,
) -> list[MemoryCorpusResult]:
    # tools.shared.ts searchMemoryCorpusSupplements.
    if corpus in {"memory", "sessions"}:
        return []
    limit = max(1, max_results if max_results is not None else MEMORY_SEARCH_MERGE_DEFAULT_MAX_RESULTS)
    results: list[MemoryCorpusResult] = []
    for supplement in supplements:
        results.extend(supplement.search(query=query, max_results=limit, corpus=corpus or ""))
    return sort_corpus_results(results)[:limit]
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
