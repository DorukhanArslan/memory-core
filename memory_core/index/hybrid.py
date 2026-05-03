from __future__ import annotations

from dataclasses import dataclass

from memory_core.index.mmr import mmr_rerank
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


@dataclass(frozen=True)
class HybridKeywordResult:
    id: str
    path: str
    start_line: int
    end_line: int
    source: str
    snippet: str
    text_score: float


@dataclass(frozen=True)
class HybridMergedResult:
    id: str
    path: str
    start_line: int
    end_line: int
    source: str
    snippet: str
    score: float
    vector_score: float
    text_score: float


def merge_hybrid_results(
    *,
    vector: list[HybridVectorResult],
    keyword: list[HybridKeywordResult],
    vector_weight: float,
    text_weight: float,
    mmr_enabled: bool = False,
    mmr_lambda: float = 0.7,
    temporal_decay: TemporalDecayConfig | None = None,
    workspace_dir: str | None = None,
    now_ms: int | None = None,
) -> list[HybridMergedResult]:
    by_id: dict[str, dict[str, object]] = {}

    for result in vector:
        by_id[result.id] = {
            "id": result.id,
            "path": result.path,
            "start_line": result.start_line,
            "end_line": result.end_line,
            "source": result.source,
            "snippet": result.snippet,
            "vector_score": result.vector_score,
            "text_score": 0.0,
        }

    for result in keyword:
        existing = by_id.get(result.id)
        if existing is not None:
            existing["text_score"] = result.text_score
            if result.snippet:
                existing["snippet"] = result.snippet
        else:
            by_id[result.id] = {
                "id": result.id,
                "path": result.path,
                "start_line": result.start_line,
                "end_line": result.end_line,
                "source": result.source,
                "snippet": result.snippet,
                "vector_score": 0.0,
                "text_score": result.text_score,
            }

    merged = [
        HybridMergedResult(
            id=str(entry["id"]),
            path=str(entry["path"]),
            start_line=int(entry["start_line"]),
            end_line=int(entry["end_line"]),
            source=str(entry["source"]),
            snippet=str(entry["snippet"]),
            score=vector_weight * float(entry["vector_score"])
            + text_weight * float(entry["text_score"]),
            vector_score=float(entry["vector_score"]),
            text_score=float(entry["text_score"]),
        )
        for entry in by_id.values()
    ]

    decayed = apply_temporal_decay_to_hybrid_results(
        merged,
        temporal_decay=temporal_decay,
        workspace_dir=workspace_dir,
        now_ms=now_ms,
    )
    sorted_results = sorted(decayed, key=lambda result: result.score, reverse=True)

    if not mmr_enabled:
        return sorted_results

    mmr_items = [
        {
            "id": f"{result.path}:{result.start_line}:{index}",
            "score": result.score,
            "content": result.snippet,
            "result": result,
        }
        for index, result in enumerate(sorted_results)
    ]
    return [item["result"] for item in mmr_rerank(mmr_items, enabled=True, lambda_=mmr_lambda)]
