"""Hybrid merge and selection (OpenClaw ``extensions/memory-core/src/memory/hybrid.ts`` at v2026.9.6).

``merge_hybrid_results`` combines vector and keyword candidates by chunk id, weights them, applies
temporal decay and MMR, and keeps exact path matches (a query that names a file) in tiers above
everything else. ``select_hybrid_search_results`` applies the minimum score with the all-lexical
fallback. Not ported: importance multipliers and active-project ranking, which need curated-entry
annotations that memory-core's index does not store.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from memory_core.bootstrap._js import locale_sort_key
from memory_core.index.mmr import apply_mmr_to_hybrid_results
from memory_core.index.temporal_decay import (
    TemporalDecayConfig,
    apply_temporal_decay_to_hybrid_results,
)


@dataclass(frozen=True)
class HybridVectorResult:
    id: str
    path: str
    start_line: int
    end_line: int
    source: str
    snippet: str
    vector_score: float
    exact_path_specificity: int = 0


@dataclass(frozen=True)
class HybridKeywordResult:
    id: str
    path: str
    start_line: int
    end_line: int
    source: str
    snippet: str
    text_score: float
    has_body_match: bool | None = None
    ranking_score: float | None = None
    path_score: float = 0.0
    exact_path_specificity: int = 0


@dataclass(frozen=True)
class HybridResult:
    path: str
    start_line: int
    end_line: int
    score: float
    vector_score: float
    text_score: float
    snippet: str
    source: str


@dataclass
class _Entry:
    id: str
    path: str
    start_line: int
    end_line: int
    source: str
    snippet: str
    vector_score: float
    text_score: float = 0.0
    ranking_score: float = 0.0
    path_score: float = 0.0
    exact_path_specificity: int = 0
    has_body_match: bool = False
    has_vector: bool = False
    has_keyword: bool = False


@dataclass
class _Ranked:
    path: str
    start_line: int
    end_line: int
    score: float
    vector_score: float
    text_score: float
    exact_path_specificity: int
    content_score: float
    lexical_rank: float
    snippet: str
    source: str
    ranking_score: float = 0.0


def score_exact_path_tie_for_temporal_decay(content_score: float) -> float:
    """``scoreExactPathTieForTemporalDecay``."""
    return (1 + max(0.0, min(1.0, content_score))) / 2


def merge_hybrid_results(
    *,
    vector: list[HybridVectorResult],
    keyword: list[HybridKeywordResult],
    vector_weight: float,
    text_weight: float,
    workspace_dir: str | None = None,
    temporal_decay: TemporalDecayConfig | None = None,
    mmr_enabled: bool = False,
    mmr_lambda: float = 0.7,
    now_ms: int | None = None,
    is_non_text_media_path: Callable[[str], bool] | None = None,
    session_source_mtimes: Mapping[str, float | None] | None = None,
) -> list[HybridResult]:
    by_id: dict[str, _Entry] = {}
    for item in vector:
        by_id[item.id] = _Entry(
            id=item.id,
            path=item.path,
            start_line=item.start_line,
            end_line=item.end_line,
            source=item.source,
            snippet=item.snippet,
            vector_score=item.vector_score,
            exact_path_specificity=item.exact_path_specificity,
            has_vector=True,
        )
    for item in keyword:
        has_body = item.has_body_match if item.has_body_match is not None else item.text_score > 0
        ranking = item.ranking_score if item.ranking_score is not None else item.text_score
        existing = by_id.get(item.id)
        if existing is not None:
            existing.text_score = item.text_score
            existing.has_body_match = has_body
            existing.ranking_score = ranking
            existing.path_score = item.path_score
            existing.exact_path_specificity = max(
                existing.exact_path_specificity, item.exact_path_specificity
            )
            existing.has_keyword = True
            if item.snippet:
                existing.snippet = item.snippet
        else:
            by_id[item.id] = _Entry(
                id=item.id,
                path=item.path,
                start_line=item.start_line,
                end_line=item.end_line,
                source=item.source,
                snippet=item.snippet,
                vector_score=0.0,
                text_score=item.text_score,
                ranking_score=ranking,
                path_score=item.path_score,
                exact_path_specificity=item.exact_path_specificity,
                has_body_match=has_body,
                has_keyword=True,
            )

    decay = temporal_decay or TemporalDecayConfig()
    merged: list[_Ranked] = []
    for entry in by_id.values():
        # Exact specificity already carries path precedence. Body scores are the within-tier
        # signal; path BM25 only scores partial path-only hits.
        if entry.text_score > 0:
            keyword_score = entry.ranking_score
        elif entry.exact_path_specificity > 0:
            keyword_score = 0.0
        else:
            keyword_score = entry.path_score
        drop_media_text_signal = (
            entry.has_vector
            and not entry.has_keyword
            and vector_weight > 0
            and is_non_text_media_path is not None
            and is_non_text_media_path(entry.path)
        )
        content_score = (
            entry.vector_score
            if drop_media_text_signal
            else vector_weight * entry.vector_score + text_weight * keyword_score
        )
        # LIKE recall has no BM25 confidence: weight its private ranking signal through the
        # same passes, then restore public confidence before selection.
        lexical_rank = entry.ranking_score if entry.has_body_match and entry.text_score == 0 else 0.0
        if entry.exact_path_specificity > 0:
            if decay.enabled:
                ranking_score = score_exact_path_tie_for_temporal_decay(content_score)
            else:
                ranking_score = content_score if content_score > 0 else 1.0
        elif content_score == 0:
            ranking_score = lexical_rank
        else:
            ranking_score = content_score
        merged.append(
            _Ranked(
                path=entry.path,
                start_line=entry.start_line,
                end_line=entry.end_line,
                score=ranking_score,
                vector_score=entry.vector_score,
                text_score=entry.text_score,
                exact_path_specificity=entry.exact_path_specificity,
                content_score=content_score,
                lexical_rank=lexical_rank,
                snippet=entry.snippet,
                source=entry.source,
            )
        )

    # Component scores stay raw retrieval diagnostics; decay and MMR adjust the combined score
    # but cannot cross the exact-identifier tier.
    decayed = apply_temporal_decay_to_hybrid_results(
        merged,
        temporal_decay=decay,
        workspace_dir=workspace_dir,
        now_ms=now_ms,
        session_source_mtimes=session_source_mtimes,
    )
    rankable: list[_Ranked] = []
    for entry in decayed:
        # Exact tiers and recall-only LIKE hits keep their public confidence; their private
        # ranking score still includes every weighting pass.
        entry.ranking_score = entry.score
        if entry.exact_path_specificity > 0:
            entry.score = 1.0  # projectScoreMultiplier without an active project
        elif entry.content_score == 0:
            entry.score = 0.0
        rankable.append(entry)

    def compare_key(item: _Ranked):
        return (
            -item.ranking_score,
            -item.lexical_rank,
            locale_sort_key(item.path),
            item.start_line,
            item.end_line,
        )

    non_exact = sorted(
        (item for item in rankable if item.exact_path_specificity == 0),
        key=lambda item: (-item.score, *compare_key(item)),
    )

    def rerank_exact_group(entries: list[_Ranked]) -> list[_Ranked]:
        if not mmr_enabled:
            return entries
        for entry in entries:
            entry.score = entry.ranking_score
        reranked = apply_mmr_to_hybrid_results(entries, enabled=True, lambda_=mmr_lambda)
        for entry in reranked:
            entry.score = 1.0
        return reranked

    exact: list[_Ranked] = []
    for specificity in (3, 2, 1):
        tier = sorted(
            (item for item in rankable if item.exact_path_specificity == specificity),
            key=compare_key,
        )
        if decay.enabled:
            exact.extend(rerank_exact_group(tier))
            continue
        content_backed = [e for e in tier if e.content_score > 0 or e.lexical_rank > 0]
        path_only = [e for e in tier if not (e.content_score > 0) and e.lexical_rank == 0]
        exact.extend(rerank_exact_group(content_backed) + rerank_exact_group(path_only))
    ranked = exact + (
        apply_mmr_to_hybrid_results(non_exact, enabled=True, lambda_=mmr_lambda)
        if mmr_enabled
        else non_exact
    )
    return [
        HybridResult(
            path=item.path,
            start_line=item.start_line,
            end_line=item.end_line,
            score=item.score,
            vector_score=item.vector_score,
            text_score=item.text_score,
            snippet=item.snippet,
            source=item.source,
        )
        for item in ranked
    ]


def _range_key(item: object) -> str:
    return f"{item.source}:{item.path}:{item.start_line}:{item.end_line}"  # type: ignore[attr-defined]


def select_hybrid_search_results(
    *,
    merged: list[HybridResult],
    keyword: list,
    max_results: int,
    min_score: float,
) -> list[HybridResult]:
    """``selectHybridSearchResults``: the strict window, then lexical recall in spare capacity."""
    strict = [entry for entry in merged if entry.score >= min_score]
    selected = strict[:max_results]
    if not keyword or len(selected) == max_results:
        return selected
    keyword_keys = {_range_key(entry) for entry in keyword}
    if not strict:
        # The established all-lexical fallback when every weighted score is under the threshold.
        return [
            entry for entry in merged if entry.score >= 0 and _range_key(entry) in keyword_keys
        ][:max_results]
    # Strict recall owns the window. MMR-ranked keyword-only hits may use spare capacity but
    # never displace a qualifying result.
    seen = {_range_key(entry) for entry in selected}
    for entry in merged:
        if len(selected) == max_results:
            break
        key = _range_key(entry)
        if (
            entry.score < min_score
            and entry.vector_score == 0
            and key in keyword_keys
            and key not in seen
        ):
            seen.add(key)
            selected.append(entry)
    return selected


__all__ = [
    "HybridKeywordResult",
    "HybridResult",
    "HybridVectorResult",
    "merge_hybrid_results",
    "score_exact_path_tie_for_temporal_decay",
    "select_hybrid_search_results",
]
