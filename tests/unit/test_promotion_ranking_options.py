"""Pinned rank options; fixture from short-term-promotion-scoring.test.ts:199-218."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.promotion import (
    PROMOTION_COMPONENT_WEIGHTS,
    evaluate_short_term_promotion_candidates,
    rank_short_term_promotion_candidates,
)

NOW_MS = 1775210460000  # 2026-04-03T10:01:00.000Z
NOW_ISO = "2026-04-03T10:01:00.000Z"
RELEVANCE_ONLY = {
    "frequency": 0,
    "relevance": 1,
    "diversity": 0,
    "recency": 0,
    "consolidation": 0,
    "conceptual": 0,
}


def _workspace(tmp_path: Path, **overrides: Any) -> MemoryConfig:
    entry = {
        "key": "boundary",
        "path": "memory/2026-04-01.md",
        "startLine": 1,
        "endLine": 1,
        "source": "memory",
        "snippet": "boundary durable note",
        "recallCount": 0,
        "dailyCount": 1,
        "groundedCount": 0,
        "totalScore": 0.75,
        "maxScore": 0.75,
        "firstRecalledAt": "2026-04-01T10:00:00.000Z",
        "lastRecalledAt": NOW_ISO,
        "queryHashes": ["query-a"],
        "userQueryHashes": ["query-a"],
        "recallDays": ["2026-04-03"],
        "conceptTags": [],
        **overrides,
    }
    recall = tmp_path / "memory/.dreams/short-term-recall.json"
    recall.parent.mkdir(parents=True)
    recall.write_text(
        json.dumps({"version": 1, "updatedAt": NOW_ISO, "entries": {entry["key"]: entry}}),
        encoding="utf-8",
    )
    return MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "index.sqlite")


def _rank(config: MemoryConfig, **options: Any):
    return rank_short_term_promotion_candidates(
        config=config,
        now_ms=NOW_MS,
        limit=options.pop("limit", 10),
        min_recall_count=0,
        min_unique_queries=0,
        **{"min_score": 0, **options},
    )


def test_include_promoted_retains_the_original_promotion_timestamp(tmp_path: Path):
    config = _workspace(tmp_path, promotedAt=NOW_ISO)
    assert _rank(config) == []
    candidates = _rank(config, include_promoted=True)
    assert [c.key for c in candidates] == ["boundary"]
    assert candidates[0].promoted_at == NOW_ISO
    evaluations = evaluate_short_term_promotion_candidates(
        config=config, now_ms=NOW_MS, min_score=0, min_recall_count=0,
        min_unique_queries=0, include_promoted=True,
    )
    assert [e.key for e in evaluations] == ["boundary"]


def test_relevance_only_weights_control_the_inclusive_score_gate(tmp_path: Path):
    config = _workspace(tmp_path)
    candidates = _rank(config, weights=RELEVANCE_ONLY, min_score=0.75)
    assert [c.score for c in candidates] == [0.75]
    assert _rank(config, weights=RELEVANCE_ONLY, min_score=0.750001) == []
    evaluations = evaluate_short_term_promotion_candidates(
        config=config, now_ms=NOW_MS, min_score=0.750001, min_recall_count=0,
        min_unique_queries=0, weights=RELEVANCE_ONLY,
    )
    assert evaluations[0].score == 0.75
    assert evaluations[0].reasons == ("score 0.750 < 0.750",)


@pytest.mark.parametrize("weights", [{"relevance": 3}, {"frequency": -1, "recency": 2}])
def test_partial_weights_merge_defaults_then_normalize(tmp_path: Path, weights: dict[str, float]):
    config = _workspace(tmp_path)
    candidate = _rank(config, weights=weights)[0]
    merged = {**PROMOTION_COMPONENT_WEIGHTS, **weights}
    total = sum(max(0, value) for value in merged.values())
    expected = sum(max(0, value) * candidate.components[key] / total for key, value in merged.items())
    assert candidate.score == pytest.approx(expected)


@pytest.mark.parametrize("weights", [{key: 0 for key in RELEVANCE_ONLY},
                                    {key: -2 for key in RELEVANCE_ONLY}])
def test_nonpositive_weights_restore_default_scores(tmp_path: Path, weights: dict[str, float]):
    config = _workspace(tmp_path)
    assert _rank(config, weights=weights) == _rank(config)


@pytest.mark.parametrize("weight", [float("nan"), float("inf")])
def test_nonfinite_weight_gate_uses_raw_score_before_output_clamping(tmp_path: Path, weight: float):
    # normalizeWeights permits nonfinite numbers. JS's NaN < minScore is false,
    # then rankShortTermPromotionCandidates clamps the returned candidate score to zero.
    config = _workspace(tmp_path)
    candidates = _rank(config, weights={"relevance": weight}, min_score=0.75)
    assert [c.score for c in candidates] == [0]


@pytest.mark.parametrize("path", ["MEMORY.md", "random.md", "memory/dreaming/2026-04-01.md"])
def test_rank_excludes_non_short_term_store_paths(tmp_path: Path, path: str):
    assert _rank(_workspace(tmp_path, path=path)) == []


@pytest.mark.parametrize("extension", ["md", "txt"])
def test_rank_preserves_transcript_turns_only_in_the_session_corpus(tmp_path: Path, extension: str):
    config = _workspace(
        tmp_path, path=f"memory/.dreams/session-corpus/2026-04-01.{extension}",
        snippet="User: Prefers cedar tea.\nAssistant: Recorded.",
    )
    candidates = _rank(config)
    assert [candidate.key for candidate in candidates] == ["boundary"]
    assert candidates[0].snippet == "User: Prefers cedar tea. Assistant: Recorded."


def test_rank_still_excludes_transcript_scaffolding_in_a_daily_file(tmp_path: Path):
    assert _rank(_workspace(tmp_path, snippet="User: Prefers cedar tea.")) == []


def test_rank_exposes_six_score_components_and_retains_phase_boost_in_evaluations(tmp_path: Path):
    config = _workspace(tmp_path)
    (tmp_path / "memory/.dreams/phase-signals.json").write_text(json.dumps({
        "version": 1, "updatedAt": NOW_ISO, "entries": {
            "boundary": {"key": "boundary", "lightHits": 3, "remHits": 3,
                         "lastLightAt": NOW_ISO, "lastRemAt": NOW_ISO},
        },
    }))
    candidate = _rank(config)[0]
    evaluation = evaluate_short_term_promotion_candidates(
        config=config, now_ms=NOW_MS, min_score=0, min_recall_count=0, min_unique_queries=0,
    )[0]
    assert set(candidate.components) == set(PROMOTION_COMPONENT_WEIGHTS)
    assert evaluation.components["phaseBoost"] > 0
    assert candidate.score == evaluation.score
    base_score = sum(PROMOTION_COMPONENT_WEIGHTS[key] * value
                     for key, value in candidate.components.items())
    assert candidate.score == pytest.approx(base_score + evaluation.components["phaseBoost"])


def test_frequency_only_score_keeps_the_original_binary64_threshold_decision(tmp_path: Path):
    config = _workspace(tmp_path, recallCount=2, dailyCount=0, totalScore=1.5)
    weights = {**RELEVANCE_ONLY, "frequency": 1, "relevance": 0}
    # Adjacent representable scores change admission, with no tolerance at the
    # frequency-only score gate.
    assert _rank(config, weights=weights, min_score=0.4581569099913262) == []
    candidates = _rank(config, weights=weights, min_score=0.45815690999132613)
    assert len(candidates) == 1
    assert candidates[0].components["frequency"] == 0.45815690999132613


@pytest.mark.parametrize(("limit", "expected"), [
    (-1, 0), (.5, 0), (1.9, 1), (None, 2), (True, 2),
    (float("inf"), 2), (float("nan"), 2), (10**1000, 2),
])
def test_rank_limit_matches_finite_floor_clamp_and_unbounded_options(tmp_path: Path, limit, expected):
    config = _workspace(tmp_path)
    filename = tmp_path / "memory/.dreams/short-term-recall.json"
    store = json.loads(filename.read_text())
    store["entries"]["second"] = {**store["entries"]["boundary"], "key": "second",
                                     "path": "memory/2026-04-02.md"}
    filename.write_text(json.dumps(store))
    assert len(_rank(config, limit=limit)) == expected
