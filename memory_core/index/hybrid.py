from __future__ import annotations

from dataclasses import dataclass


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
class HybridResult:
    path: str
    start_line: int
    end_line: int
    score: float
    vector_score: float
    text_score: float
    snippet: str
    source: str


def merge_hybrid_results(
    *,
    vector: list[HybridVectorResult],
    keyword: list[HybridKeywordResult],
    vector_weight: float,
    text_weight: float,
) -> list[HybridResult]:
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
        HybridResult(
            path=str(entry["path"]),
            start_line=int(entry["start_line"]),
            end_line=int(entry["end_line"]),
            score=vector_weight * float(entry["vector_score"])
            + text_weight * float(entry["text_score"]),
            vector_score=float(entry["vector_score"]),
            text_score=float(entry["text_score"]),
            snippet=str(entry["snippet"]),
            source=str(entry["source"]),
        )
        for entry in by_id.values()
    ]

    return sorted(merged, key=lambda result: result.score, reverse=True)
