"""Actual hybrid merge/selection owners with complete ordered result payloads.

Fixtures enter the public Python merger and selector directly. Native fixtures
call the unchanged pinned TypeScript owners. Storage annotation ingestion, full
manager orchestration and the separate importance/project contract are not
claimed by these candidate-level comparisons.
"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any


_NOW_MS = 1738368000000  # 2025-02-01T00:00:00Z
_DAY_MS = 86_400_000
_PROVENANCE = {
    "originClass": "owner", "sessionKind": "interactive", "observedAt": 1735689600000,
    "supersedesKey": "old-entry",
}
_PROFILE = (
    "Actual public hybrid candidate merger and selector, with complete ordered payloads, "
    "optional metadata, declared deterministic clocks/source mtimes and real fixture-owned "
    "workspace files. Native importance/project, decay and MMR dependencies execute unchanged. "
    "Tie-path ordering is paired over printable ASCII identities; Unicode snippets/metadata "
    "remain exact. The separate engine Unicode collation contract remains unverified. "
    "Storage annotation ingestion and full manager orchestration remain unverified."
)


def _vector(identifier: str, score: float = 0.8, **fields: Any) -> dict[str, Any]:
    return {
        "id": identifier, "path": f"memory/{identifier}.md", "startLine": 2,
        "endLine": 4, "source": "memory", "snippet": f"vector {identifier}",
        "vectorScore": score, **fields,
    }


def _keyword(identifier: str, score: float = 0.6, **fields: Any) -> dict[str, Any]:
    result = _vector(identifier, **fields)
    result.pop("vectorScore")
    result["textScore"] = score
    return result


def _result(identifier: str, score: float = 0.8, **fields: Any) -> dict[str, Any]:
    result = _vector(identifier, score, **fields)
    result.pop("id")
    return {"score": score, "textScore": 0.0, **result}


def _range(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("path", "startLine", "endLine", "source")}


def build_hybrid_scoring_cases() -> list[dict[str, Any]]:
    """Named numerical, metadata, ordering and selection boundary comparisons."""
    cases: list[dict[str, Any]] = []

    def add(name: str, kind: str = "merge", **arguments: Any) -> None:
        arguments = {"kind": kind, **arguments}
        if kind != "select":
            arguments = {"vector": [], "keyword": [], "vectorWeight": 0.7,
                         "textWeight": 0.3, **arguments}
        cases.append({
            "id": f"hybrid-{name}", "requirement": "retrieval.hybrid-scoring",
            "operation": "hybrid-scoring", "covers": [],
            "input": deepcopy(arguments), "driverScope": _PROFILE,
            "normalizationPolicy": (
                "No output normalization, score tolerance or field projection: compare complete "
                "ordered candidate/result JSON including optional metadata and absent-versus-null "
                "values. Workspace roots are private fixture locations; returned paths remain "
                "the original logical source identities. All numeric inputs are finite JSON."
            ),
        })

    add("empty")
    add("vector-only", vector=[_vector("b", 0.9), _vector("a", 0.6)])
    add("keyword-only", keyword=[_keyword("b", 0.9), _keyword("a", 0.6)])
    add("disjoint", vector=[_vector("a")], keyword=[_keyword("b")])
    add("overlap", vector=[_vector("same", 0.75)], keyword=[_keyword("same", 0.5)])
    add("duplicate-vector-id", vector=[_vector("same", 0.1), _vector("middle", 0.6),
                                       _vector("same", 0.9, snippet="replacement")])
    add("duplicate-keyword-id", keyword=[_keyword("same", 0.1), _keyword("middle", 0.6),
                                         _keyword("same", 0.9, snippet="replacement")])
    add("overlap-retains-vector-identity", vector=[_vector("same", path="memory/original.md")],
        keyword=[_keyword("same", path="sessions/replacement.jsonl", source="sessions",
                          startLine=70, endLine=90, snippet="keyword text")])
    for name, vector_weight, text_weight in (
        ("zero-weights", 0, 0), ("vector-weight-only", 1, 0),
        ("text-weight-only", 0, 1), ("unnormalized-weights", 2, 3),
        ("negative-vector-weight", -1, 0.5), ("fractional-weights", 0.1, 0.9),
    ):
        add(name, vector=[_vector("same", 0.35), _vector("vector", 0.9)],
            keyword=[_keyword("same", 0.8), _keyword("keyword", 0.5)],
            vectorWeight=vector_weight, textWeight=text_weight)
    add("stable-path-range-ties", vector=[
        _vector("z", 1, path="memory/b.md"),
        _vector("a", 1, path="memory/a.md", startLine=4, endLine=8),
        _vector("b", 1, path="memory/a.md", startLine=2, endLine=9),
        _vector("c", 1, path="memory/a.md", startLine=2, endLine=4),
        _vector("d", 1, path="memory/a.md", startLine=2, endLine=4, source="sessions"),
    ])
    add("exact-specificity-tiers", vector=[
        _vector("ordinary", 1), _vector("base", 0, exactPathSpecificity=1),
        _vector("relative", 0.1, exactPathSpecificity=2),
        _vector("full", 0, exactPathSpecificity=3),
    ])
    add("exact-content-before-path-only", vector=[
        _vector("path", 0, exactPathSpecificity=3),
        _vector("content", 0.1, exactPathSpecificity=3),
    ], keyword=[_keyword("like", 0, hasBodyMatch=True, rankingScore=0.3,
                         exactPathSpecificity=3)])
    add("keyword-body-flag-and-path-score", keyword=[
        _keyword("body", 0.4, hasBodyMatch=False, rankingScore=0.7, pathScore=0.9),
        _keyword("path", 0, hasBodyMatch=False, rankingScore=0.9, pathScore=0.8),
        _keyword("exact", 0, pathScore=1, exactPathSpecificity=3),
    ])
    add("like-private-rank-public-zero", keyword=[
        _keyword("low", 0, hasBodyMatch=True, rankingScore=0.1),
        _keyword("high", 0, hasBodyMatch=True, rankingScore=0.9),
        _keyword("no-body", 0, hasBodyMatch=False, rankingScore=1),
    ])
    add("overlap-empty-snippet", vector=[_vector("same")],
        keyword=[_keyword("same", snippet="")])
    add("overlap-whitespace-snippet", vector=[_vector("same")],
        keyword=[_keyword("same", snippet=" \t ")])
    add("media-vector-confidence", vector=[_vector("image", path="media/cat.png")],
        mediaPaths=["media/cat.png"])
    add("media-overlap-still-blends", vector=[_vector("image", path="media/cat.png")],
        keyword=[_keyword("image", path="media/cat.png")], mediaPaths=["media/cat.png"])
    add("media-zero-vector-weight", vector=[_vector("image", path="media/cat.png")],
        vectorWeight=0, textWeight=1, mediaPaths=["media/cat.png"])

    add("metadata-absent", vector=[_vector("plain")], keyword=[_keyword("keyword")])
    add("metadata-explicit-null", vector=[_vector(
        "nullable", importance=None, triggers=None, projectKey=None, provenance=None,
    )])
    add("metadata-zero-and-empty", vector=[_vector(
        "empty", importance=0, triggers="", projectKey="", provenance={},
    )])
    add("metadata-vector-wins", vector=[_vector(
        "same", importance=9, triggers="Çay ve hafıza", projectKey="alpha",
        snippet="source 😀\x00köprü", provenance=_PROVENANCE,
    )], keyword=[_keyword("same", importance=1, triggers="keyword", projectKey="beta",
                         provenance={**_PROVENANCE, "originClass": "untrusted"})])
    add("metadata-keyword-fills-missing", vector=[_vector("same")], keyword=[_keyword(
        "same", importance=8, triggers="keyword", projectKey="alpha", provenance=_PROVENANCE,
    )])
    add("metadata-keyword-fills-null", vector=[_vector(
        "same", importance=None, triggers=None, projectKey=None, provenance=None,
    )], keyword=[_keyword("same", importance=8, triggers="keyword", projectKey="alpha",
                         provenance=_PROVENANCE)])
    add("metadata-empty-values-are-retained", vector=[_vector(
        "same", importance=0, triggers="", projectKey="", provenance={},
    )], keyword=[_keyword("same", importance=8, triggers="replacement", projectKey="alpha",
                         provenance=_PROVENANCE)])
    add("metadata-keyword-null-kept", keyword=[_keyword(
        "nullable", importance=None, triggers=None, projectKey=None, provenance=None,
    )])
    add("importance-clamps-and-floors", vector=[
        _vector(f"importance-{i}", 0.8, importance=value)
        for i, value in enumerate((-3, 0, 1, 1.99, 5, 9.9, 10, 100))
    ])
    project_rows = [
        _vector("unscoped", 0.8), _vector("matching", 0.8, projectKey="alpha"),
        _vector("multiple", 0.8, projectKey=" alpha ; beta "),
        _vector("other", 0.8, projectKey="gamma"),
        _vector("whitespace", 0.8, projectKey=" ; \t ; "),
        _vector("invalid", 1, projectKey="alpha; !invalid-project-annotation"),
    ]
    add("project-no-active-keys", vector=project_rows)
    add("project-empty-active-keys", vector=project_rows, activeProjectKeys=[])
    add("project-active-subset", vector=project_rows, activeProjectKeys=["alpha", "alpha"])
    add("project-active-all", vector=project_rows, activeProjectKeys=["alpha", "beta"])
    add("project-exact-confidence-and-private-rank", vector=[
        _vector("a", 0.3, exactPathSpecificity=3, importance=10, projectKey="alpha"),
        _vector("b", 0.9, exactPathSpecificity=3, importance=1, projectKey="beta"),
        _vector("ordinary", 1, projectKey="alpha"),
    ], activeProjectKeys=["alpha"])

    dated = [_vector("old", 1, path="memory/2025-01-01.md"),
             _vector("fresh", 0.6, path="memory/2025-02-01.md"),
             _vector("evergreen", 0.4, path="MEMORY.md")]
    add("decay-date-composition", vector=dated, temporalDecay={"enabled": True, "halfLifeDays": 30},
        nowMs=_NOW_MS)
    add("decay-disabled-keeps-clock-neutral", vector=dated,
        temporalDecay={"enabled": False, "halfLifeDays": 1}, nowMs=_NOW_MS)
    add("decay-session-indexed-mtimes", vector=[
        _vector("old", 1, path="sessions/old.jsonl", source="sessions"),
        _vector("new", 0.6, path="sessions/new.jsonl", source="sessions"),
        _vector("missing", 0.5, path="sessions/missing.jsonl", source="sessions"),
    ], temporalDecay={"enabled": True}, nowMs=_NOW_MS,
        sessionSourceMtimes={"sessions/old.jsonl": _NOW_MS - 31 * _DAY_MS,
                             "sessions/new.jsonl": _NOW_MS + _DAY_MS})
    add("decay-fractional-session-mtime", vector=[
        _vector("fractional", 0.9, path="sessions/fractional.jsonl", source="sessions"),
    ], temporalDecay={"enabled": True}, nowMs=_NOW_MS,
        sessionSourceMtimes={"sessions/fractional.jsonl": _NOW_MS - _DAY_MS + 0.9})
    remote = [_vector("remote", 0.9, path="remote/report.md")]
    workspace_files = [{"path": "remote/report.md", "text": "source fixture",
                        "mtimeMs": _NOW_MS - 30 * _DAY_MS}]
    add("decay-workspace-stat", vector=remote, temporalDecay={"enabled": True}, nowMs=_NOW_MS,
        workspaceFiles=workspace_files)
    add("decay-empty-memory-map-is-authoritative", vector=remote,
        temporalDecay={"enabled": True}, nowMs=_NOW_MS, workspaceFiles=workspace_files,
        memorySourceMtimes={})
    add("decay-memory-map-overrides-stat", vector=remote,
        temporalDecay={"enabled": True}, nowMs=_NOW_MS, workspaceFiles=workspace_files,
        memorySourceMtimes={"remote/report.md": _NOW_MS - 15 * _DAY_MS})
    add("decay-map-selection-one-ulp-boundary", "merge-select", vector=remote,
        temporalDecay={"enabled": True}, nowMs=_NOW_MS, workspaceFiles=workspace_files,
        memorySourceMtimes={"remote/report.md": _NOW_MS - 15 * _DAY_MS},
        maxResults=1, minScore=0.44547727214752497)
    add("decay-date-and-evergreen-ignore-map", vector=dated,
        temporalDecay={"enabled": True}, nowMs=_NOW_MS,
        memorySourceMtimes={row["path"]: _NOW_MS - 1000 * _DAY_MS for row in dated})
    add("decay-exact-tier-recency", vector=[
        _vector("old", 1, path="memory/2025-01-01.md", exactPathSpecificity=3),
        _vector("fresh", 0, path="memory/2025-02-01.md", exactPathSpecificity=3),
    ], temporalDecay={"enabled": True}, nowMs=_NOW_MS)
    diverse = [_vector("one", 0.95, snippet="alpha beta gamma"),
               _vector("two", 0.9, snippet="alpha beta gamma"),
               _vector("three", 0.8, snippet="distant cedar mountain")]
    for value in (0, 0.5, 1):
        add(f"mmr-lambda-{value}", vector=diverse, mmr={"enabled": True, "lambda": value})
    add("mmr-exact-tier-barrier", vector=[
        _vector("exact-one", 0.95, snippet="same text", exactPathSpecificity=3),
        _vector("exact-two", 0.9, snippet="same text", exactPathSpecificity=3),
        _vector("ordinary", 1, snippet="different content"),
    ], mmr={"enabled": True, "lambda": 0})
    add("combined-ranking-passes", vector=[
        _vector("old", 0.95, path="memory/2025-01-01.md", snippet="alpha beta",
                importance=10, projectKey="alpha", provenance=_PROVENANCE),
        _vector("new", 0.7, path="memory/2025-02-01.md", snippet="alpha beta", projectKey="beta"),
        _vector("other", 0.6, snippet="different facts", importance=8, projectKey="alpha"),
    ], keyword=[_keyword("new", 0.6, triggers="declared trigger")],
        temporalDecay={"enabled": True}, nowMs=_NOW_MS,
        mmr={"enabled": True, "lambda": 0.5}, activeProjectKeys=["alpha"])

    qualifying = _result("strict", 0.5, vectorScore=0.5)
    lexical = _result("lexical", 0.1, vectorScore=0, textScore=0.4,
                      importance=8, triggers="kept", provenance=_PROVENANCE)
    vector_only = _result("under-vector", 0.2, vectorScore=0.8)
    add("select-empty", "select", merged=[], keyword=[], maxResults=3, minScore=0.5)
    add("select-threshold-equality", "select", merged=[qualifying, lexical],
        keyword=[], maxResults=3, minScore=0.5)
    add("select-below-threshold", "select", merged=[qualifying, lexical],
        keyword=[], maxResults=3, minScore=0.5000000000000001)
    add("select-zero-capacity", "select", merged=[qualifying, lexical],
        keyword=[_range(lexical)], maxResults=0, minScore=0.5)
    add("select-full-strict-window", "select", merged=[qualifying, lexical],
        keyword=[_range(lexical)], maxResults=1, minScore=0.5)
    add("select-spare-capacity-keyword-only", "select", merged=[vector_only, qualifying, lexical],
        keyword=[_range(lexical), _range(vector_only)], maxResults=3, minScore=0.5)
    add("select-spare-capacity-deduplication", "select", merged=[qualifying, lexical, lexical],
        keyword=[_range(lexical), _range(lexical)], maxResults=4, minScore=0.5)
    add("select-all-lexical-fallback", "select", merged=[vector_only, lexical,
        _result("negative", -0.1, vectorScore=0), _result("zero", 0, vectorScore=0)],
        keyword=[_range(row) for row in (vector_only, lexical, _result("negative"), _result("zero"))],
        maxResults=5, minScore=1)
    source_variant = {**lexical, "source": "sessions"}
    range_variant = {**lexical, "endLine": 99}
    add("select-source-and-range-identities", "select",
        merged=[qualifying, lexical, source_variant, range_variant],
        keyword=[_range(source_variant), _range(range_variant)], maxResults=5, minScore=0.5)
    add("select-retains-null-and-empty-metadata", "select", merged=[_result(
        "nullable", 1, importance=None, triggers="", projectKey=None, provenance={},
    )], keyword=[], maxResults=1, minScore=0)
    add("merge-select-spare-lexical", "merge-select", vector=[_vector("strict", 0.95)],
        keyword=[_keyword("lexical", 0, hasBodyMatch=True, rankingScore=0.8)],
        maxResults=3, minScore=0.5)
    add("merge-select-all-lexical", "merge-select", vector=[_vector("vector", 0.2)],
        keyword=[_keyword("lexical", 0.1, provenance=_PROVENANCE)], maxResults=3, minScore=1)
    add("merge-select-metadata-ranking", "merge-select", vector=project_rows,
        activeProjectKeys=["alpha"], maxResults=2, minScore=0.6)
    add("unicode-path-collation-diagnostic", vector=[
        _vector("sharp-s", 0.8, path="memory/ß.md"),
        _vector("ordinary-t", 0.8, path="memory/t.md"),
    ])
    cases[-1]["requirement"] = "engine.unicode-collation"
    cases[-1]["driverScope"] = (
        "Uncredited engine Unicode path-collation diagnostic through the actual hybrid merger. "
        "Tied non-ASCII paths are compared exactly; their ordering remains a visible difference."
    )
    cases[-1]["declaredDeviation"] = (
        "Python's existing locale_sort_key approximates native ICU collation for non-ASCII "
        "paths. This genuine tied sharp-s/t ordering comparison remains visible and uncredited; "
        "it is not normalized or converted to an expected failure."
    )
    payload_boundaries = {
        "metadata-absent", "metadata-explicit-null", "metadata-zero-and-empty",
        "metadata-vector-wins", "metadata-keyword-fills-missing", "metadata-keyword-fills-null",
        "metadata-empty-values-are-retained", "metadata-keyword-null-kept",
        "overlap-retains-vector-identity", "overlap-empty-snippet", "overlap-whitespace-snippet",
        "stable-path-range-ties",
    }
    for case in cases:
        if case["requirement"] != "retrieval.hybrid-scoring":
            continue
        kind = case["input"]["kind"]
        if kind != "select":
            case["covers"].append("retrieval.hybrid-scoring.outcomes")
        if kind != "merge" or case["id"].removeprefix("hybrid-") in payload_boundaries:
            case["covers"].append("retrieval.hybrid-scoring.boundaries")
    return cases


_KEYS = {
    "startLine": "start_line", "endLine": "end_line", "vectorScore": "vector_score",
    "textScore": "text_score", "exactPathSpecificity": "exact_path_specificity",
    "hasBodyMatch": "has_body_match", "rankingScore": "ranking_score", "pathScore": "path_score",
    "projectKey": "project_key",
}


def run_hybrid_scoring(arguments: dict[str, Any]) -> dict[str, Any]:
    """Arrange declared inputs and invoke the actual public Python operations."""
    from memory_core.index.hybrid import (
        HybridKeywordResult, HybridResult, HybridVectorResult,
        merge_hybrid_results, select_hybrid_search_results,
    )
    from memory_core.index.temporal_decay import TemporalDecayConfig

    value = deepcopy(arguments)
    kind = value["kind"]
    if kind not in {"merge", "select", "merge-select"}:
        raise ValueError(f"Unsupported hybrid scoring operation: {kind}")

    def construct(cls: type, row: dict[str, Any]) -> Any:
        return cls(**{_KEYS.get(key, key): item for key, item in row.items()})

    with tempfile.TemporaryDirectory(prefix="memory-hybrid-scoring-") as directory:
        root = Path(directory)
        for row in value.get("workspaceFiles", []):
            relative = Path(row["path"])
            if relative.is_absolute() or ".." in relative.parts or str(relative) == ".":
                raise ValueError("Hybrid workspace fixture path escaped its private root")
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(row.get("text", ""), encoding="utf-8")
            timestamp = row["mtimeMs"] / 1000
            os.utime(path, (timestamp, timestamp))
        if kind == "select":
            merged = [construct(HybridResult, row) for row in value["merged"]]
        else:
            decay = value.get("temporalDecay", {})
            mmr = value.get("mmr", {})
            media_paths = set(value.get("mediaPaths", []))
            merged = merge_hybrid_results(
                vector=[construct(HybridVectorResult, row) for row in value["vector"]],
                keyword=[construct(HybridKeywordResult, row) for row in value["keyword"]],
                vector_weight=value["vectorWeight"], text_weight=value["textWeight"],
                temporal_decay=TemporalDecayConfig(
                    enabled=decay.get("enabled", False), half_life_days=decay.get("halfLifeDays", 30),
                ),
                mmr_enabled=mmr.get("enabled", False), mmr_lambda=mmr.get("lambda", 0.7),
                now_ms=value.get("nowMs"),
                workspace_dir=str(root) if "workspaceFiles" in value else None,
                session_source_mtimes=value.get("sessionSourceMtimes"),
                memory_source_mtimes=value.get("memorySourceMtimes"),
                active_project_keys=value.get("activeProjectKeys"),
                is_non_text_media_path=media_paths.__contains__ if "mediaPaths" in value else None,
            )
        result = {} if kind == "select" else {"merged": [row.to_payload() for row in merged]}
        if kind != "merge":
            selected = select_hybrid_search_results(
                merged=merged,
                keyword=[SimpleNamespace(**{_KEYS.get(key, key): item for key, item in row.items()})
                         for row in value["keyword"]],
                max_results=value["maxResults"], min_score=value["minScore"],
            )
            result["selected"] = [row.to_payload() for row in selected]
        return result
