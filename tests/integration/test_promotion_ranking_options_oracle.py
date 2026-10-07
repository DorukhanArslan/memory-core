"""Rank options against the real pinned TS function, with one shared option batch.

The boundary entry comes from short-term-promotion-scoring.test.ts:199-218.
Tie fixtures change only identity, path and signal fields; no product text is invented.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.config import MemoryConfig
from memory_core.consolidation.promotion import (
    evaluate_short_term_promotion_candidates,
    rank_short_term_promotion_candidates,
)

NOW_MS = 1775210460000
NOW_ISO = "2026-04-03T10:01:00.000Z"
RELEVANCE_ONLY = {
    "frequency": 0, "relevance": 1, "diversity": 0,
    "recency": 0, "consolidation": 0, "conceptual": 0,
}
CASES = {
    "defaults": {},
    "include-promoted": {"includePromoted": True},
    "explicit-exclude-promoted": {"includePromoted": False},
    "relevance-only": {"weights": RELEVANCE_ONLY},
    "partial-weight": {"weights": {"relevance": 3}},
    "negative-weight": {"weights": {"frequency": -1, "recency": 2}},
    "zero-weights": {"weights": {key: 0 for key in RELEVANCE_ONLY}},
    "negative-weights": {"weights": {key: -2 for key in RELEVANCE_ONLY}},
    # JSON cannot encode NaN/Infinity. Math.max and Python float accept their text forms.
    "nan-weight": {"weights": {"relevance": "NaN"}, "minScore": 0.75},
    "infinite-weight": {"weights": {"relevance": "Infinity"}, "minScore": 0.75},
    "inclusive-boundary": {"weights": RELEVANCE_ONLY, "minScore": 0.75},
    "above-boundary": {"weights": RELEVANCE_ONLY, "minScore": 0.750001},
    "limited-ties": {"weights": RELEVANCE_ONLY, "limit": 2},
    "combined-options": {"weights": RELEVANCE_ONLY, "includePromoted": True, "limit": 3},
    "libm-score-boundary": {
        "weights": {**RELEVANCE_ONLY, "frequency": 1, "relevance": 0},
        "minScore": 0.45815690999132624,
    },
}


def _entry(key: str, **overrides: Any) -> dict[str, Any]:
    return {
        "key": key,
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


@pytest.fixture(scope="module")
def ranked_options(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("ranking-options")
    entries = [
        _entry("boundary"),
        _entry("tie-upper", path="memory/2026-04-01-A.md"),
        _entry("tie-accent", path="memory/2026-04-01-\u00e1.md"),
        _entry("tie-lower", path="memory/2026-04-01-a.md"),
        _entry("tie-recalls", recallCount=2, dailyCount=0, totalScore=1.5),
        _entry("promoted", promotedAt=NOW_ISO),
        _entry("phase-boost"),
        _entry("blocked", provenance={"originClass": "untrusted"}),
    ]
    recall = workspace / "memory/.dreams/short-term-recall.json"
    recall.parent.mkdir(parents=True)
    recall.write_text(
        json.dumps({"version": 1, "updatedAt": NOW_ISO, "entries": {e["key"]: e for e in entries}}),
        encoding="utf-8",
    )
    (recall.parent / "phase-signals.json").write_text(
        json.dumps({"version": 1, "updatedAt": NOW_ISO, "entries": {
            "phase-boost": {"key": "phase-boost", "lightHits": 3, "remHits": 3,
                            "lastLightAt": NOW_ISO, "lastRemAt": NOW_ISO},
        }}), encoding="utf-8",
    )
    oracle = OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=120)
    result = oracle.run({
        "operation": "rankShortTermPromotionCandidates",
        "workspaceDir": str(workspace), "nowMs": NOW_MS,
        "limit": 20, "minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0,
        "cases": [{"name": name, **options} for name, options in CASES.items()],
    })
    assert result["ok"] is True
    return workspace, {case["name"]: case["candidates"] for case in result["result"]["cases"]}


@pytest.mark.parametrize("name", CASES)
def test_real_openclaw_ranking_options(name: str, ranked_options, request: pytest.FixtureRequest):
    workspace, expected = ranked_options
    options = CASES[name]
    config = MemoryConfig(workspace_dir=workspace, store_path=workspace / "index.sqlite")
    python_options = {
        "config": config, "now_ms": NOW_MS, "min_score": options.get("minScore", 0),
        "min_recall_count": 0, "min_unique_queries": 0,
        "include_promoted": options.get("includePromoted", False), "weights": options.get("weights"),
    }
    candidates = rank_short_term_promotion_candidates(
        **python_options, limit=options.get("limit", 20),
    )
    evaluations = {e.key: e for e in evaluate_short_term_promotion_candidates(**python_options)}
    if name == "libm-score-boundary":
        python_frequency = evaluations["tie-recalls"].components["frequency"]
        ts_frequency = next(
            c["components"]["frequency"] for c in expected["relevance-only"]
            if c["key"] == "tie-recalls"
        )
        if ts_frequency < options["minScore"] <= python_frequency:
            # Mark only a measured platform-specific divergence. On a platform where
            # the two engines agree, the exact inclusion assertion must pass normally.
            request.node.add_marker(pytest.mark.xfail(
                strict=True, raises=AssertionError,
                reason="V8/Python log1p rounding changes this exact frequency-only score gate",
            ))
    assert len(candidates) == len(expected[name])
    for candidate, expected_candidate in zip(candidates, expected[name], strict=True):
        raw = candidate.to_json()
        raw["components"].pop("phaseBoost", None)
        expected_raw = dict(expected_candidate)
        # V8 and Python libm differ by ~1e-16 for log1p(2)/log1p(10). Keep order,
        # gates and nonnumeric fields exact; compare only score math at float precision.
        assert raw.pop("components") == pytest.approx(
            expected_raw.pop("components"), rel=1e-15, abs=1e-15,
        )
        assert raw.pop("score") == pytest.approx(expected_raw.pop("score"), rel=1e-15, abs=1e-15)
        assert raw == expected_raw
    assert "blocked" not in [c.key for c in candidates]
    assert all(evaluations[c.key].score == c.score for c in candidates)
    if name == "relevance-only":
        assert [c.key for c in candidates] == [
            "phase-boost", "tie-recalls", "tie-lower", "tie-upper", "tie-accent", "boundary",
        ]
    if name == "include-promoted":
        assert next(c.promoted_at for c in candidates if c.key == "promoted") == NOW_ISO
