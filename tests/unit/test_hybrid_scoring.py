"""Regressions for metadata-aware hybrid ranking and selection."""
from copy import deepcopy
import os

import pytest

from memory_core.index.hybrid import (
    HYBRID_METADATA_MISSING,
    HybridKeywordResult,
    HybridResult,
    HybridVectorResult,
    merge_hybrid_results,
    select_hybrid_search_results,
)
from memory_core.index.temporal_decay import DAY_MS, TemporalDecayConfig


def vector(identifier="v", score=1.0, **metadata):
    return HybridVectorResult(identifier, f"{identifier}.md", 1, 2, "memory", identifier,
                              score, **metadata)


def keyword(identifier="k", score=1.0, **metadata):
    return HybridKeywordResult(identifier, f"{identifier}.md", 3, 4, "sessions", identifier,
                               score, **metadata)


def merge(vectors=(), keywords=(), **options):
    return merge_hybrid_results(vector=list(vectors), keyword=list(keywords),
                                vector_weight=1.0, text_weight=0.0, **options)


def test_missing_annotations_and_explicit_null_are_distinct_observable_payloads():
    absent = merge([vector()])[0].to_payload()
    assert set(absent) == {"path", "startLine", "endLine", "score", "vectorScore", "textScore",
                           "snippet", "source"}
    null = merge([vector(importance=None, triggers=None, project_key=None, provenance=None)])[0]
    assert {key: value for key, value in null.to_payload().items()
            if key in {"importance", "triggers", "projectKey"}} == {
                "importance": None, "triggers": None, "projectKey": None,
            }
    assert "provenance" not in null.to_payload()
    assert deepcopy(HYBRID_METADATA_MISSING) is HYBRID_METADATA_MISSING


def test_overlap_keeps_vector_identity_but_uses_keyword_snippet_and_fills_nullish_annotations():
    original = vector("same", importance=None, triggers="", project_key=None, provenance={})
    text = keyword("same", 0.4, importance=10, triggers="fallback", project_key="one",
                   provenance={"origin": "keyword"})
    result = merge([original], [text], active_project_keys=["one"])[0]
    assert (result.path, result.source, result.start_line, result.end_line) == (
        "same.md", "memory", 1, 2,
    )
    assert result.snippet == "same"
    assert result.importance == 10 and result.triggers == "" and result.project_key == "one"
    assert result.provenance == {}  # Empty objects are truthy in the native owner.
    assert result.score == 1.4375
    assert original.importance is None and text.triggers == "fallback"


def test_zero_and_empty_annotations_are_not_replaced_by_keyword_metadata():
    result = merge([vector("a", importance=0, triggers="", project_key="")], [
        keyword("a", importance=10, triggers="changed", project_key="other"),
    ], active_project_keys=["other"])[0]
    assert (result.importance, result.triggers, result.project_key) == (0, "", "")
    assert result.score == 0.8


@pytest.mark.parametrize("importance,score", [
    (None, 1.0), (-10, 0.8), (1.9, 0.8), (9.9, 1.2), (10, 1.25), (99, 1.25),
])
def test_importance_floor_and_bounds_adjust_combined_score_only(importance, score):
    result = merge([vector(score=1.0, importance=importance)])[0]
    assert result.score == score
    assert result.vector_score == 1.0 and result.text_score == 0.0
    assert result.importance == importance


@pytest.mark.parametrize("project,active,score", [
    ("one", ["one"], 1.15), ("one", ["two"], 0.9),
    (" one ; two ", ["one", "two"], 1.15), ("one;two", ["one"], 0.9),
    (" ; \ufeff ", ["one"], 1.15), ("one", [], 1.0), (None, ["one"], 1.0),
])
def test_active_project_match_requires_every_stored_key(project, active, score):
    result = merge([vector(project_key=project)], active_project_keys=active)[0]
    assert result.score == score
    assert result.project_key == project


@pytest.mark.parametrize("active", [None, [], ["one"]])
def test_invalid_stored_project_annotation_is_excluded_even_without_an_active_project(active):
    results = merge([
        vector("bad", project_key="one; \ufeff!invalid-project-annotation "), vector("good"),
    ], active_project_keys=active)
    assert [result.path for result in results] == ["good.md"]


def test_exact_path_tiers_keep_project_confidence_after_mmr_and_weighting():
    results = merge([
        vector("exact-active", 0.1, exact_path_specificity=3, importance=1, project_key="one"),
        vector("exact-other", 0.8, exact_path_specificity=3, importance=10, project_key="two"),
        vector("body", 8.0),
    ], active_project_keys=["one"], mmr_enabled=True, mmr_lambda=1.0)
    assert [result.path for result in results] == ["exact-other.md", "exact-active.md", "body.md"]
    assert [result.score for result in results] == [0.9, 1.15, 8.0]
    assert [result.vector_score for result in results] == [0.8, 0.1, 8.0]


def test_memory_timestamp_map_is_authoritative_even_empty_and_does_not_replace_evergreen_dates(tmp_path):
    now = 1_800_000_000_000
    age = now - 30 * DAY_MS
    remote = tmp_path / "remote.md"
    remote.write_text("old")
    os.utime(remote, ns=(age * 1_000_000, age * 1_000_000))
    item = vector("remote")
    config = dict(workspace_dir=str(tmp_path), now_ms=now,
                  temporal_decay=TemporalDecayConfig(enabled=True, half_life_days=30))
    assert merge([item], **config)[0].score == 0.5
    assert merge([item], **config, memory_source_mtimes={})[0].score == 1.0
    assert merge([item], **config, memory_source_mtimes={"remote.md": now})[0].score == 1.0
    evergreen = HybridVectorResult("root", "MEMORY.md", 1, 1, "memory", "root", 1.0)
    assert merge([evergreen], **config, memory_source_mtimes={"MEMORY.md": age})[0].score == 1.0


@pytest.mark.parametrize("source", ["memory", "sessions"])
def test_indexed_timestamp_uses_native_integer_millisecond_time_clip(source):
    now = 1_800_000_000_000
    age = now - 30 * DAY_MS
    item = HybridVectorResult("remote", "remote.md", 1, 2, source, "text", 1.0)
    options = {"memory_source_mtimes" if source == "memory" else "session_source_mtimes":
               {"remote.md": age + 0.9}}
    assert merge([item], now_ms=now, temporal_decay=TemporalDecayConfig(enabled=True),
                 **options)[0].score == 0.5


@pytest.mark.parametrize("mtime", [8.64e15 + 1, -8.64e15 - 1])
def test_invalid_native_date_range_does_not_raise_or_decay_the_candidate(mtime):
    assert merge([vector("remote")], now_ms=1_800_000_000_000,
                 temporal_decay=TemporalDecayConfig(enabled=True),
                 memory_source_mtimes={"remote.md": mtime})[0].score == 1.0


def test_native_decay_keeps_a_one_ulp_below_threshold_result_out_of_the_strict_window():
    # Actual native Math.exp(-LN2/2) is the lower binary64 neighbor of the
    # platform libm value. That bit affects admission, not just display.
    now = 1_738_368_000_000
    merged = merge_hybrid_results(
        vector=[vector("remote", 0.9)], keyword=[], vector_weight=0.7, text_weight=0.3,
        now_ms=now, temporal_decay=TemporalDecayConfig(enabled=True),
        memory_source_mtimes={"remote.md": now - 15 * DAY_MS},
    )
    assert merged[0].score == 0.4454772721475249
    assert select_hybrid_search_results(merged=merged, keyword=[], max_results=1,
                                        min_score=0.44547727214752497) == []


def test_selector_preserves_explicit_null_metadata_and_identity_of_selected_objects():
    original = HybridResult("same.md", 1, 2, 0.8, 0.8, 0.0, "text", "memory",
                            importance=None, triggers=None, project_key=None, provenance=None)
    selected = select_hybrid_search_results(merged=[original], keyword=[],
                                           max_results=1, min_score=0.8)
    assert selected[0] is original
    assert {key: selected[0].to_payload()[key]
            for key in ("importance", "triggers", "projectKey", "provenance")} == {
                "importance": None, "triggers": None, "projectKey": None, "provenance": None,
            }


def test_selector_strict_window_owns_capacity_and_lexical_identity_includes_source():
    strict = HybridResult("same.md", 1, 2, 0.8, 0.8, 0.0, "strict", "memory")
    lexical = HybridResult("same.md", 1, 2, 0.1, 0.0, 0.1, "lexical", "sessions")
    duplicate = HybridResult("same.md", 1, 2, 0.0, 0.0, 0.0, "duplicate", "memory")
    selected = select_hybrid_search_results(merged=[lexical, strict, duplicate],
                                           keyword=[lexical, duplicate], max_results=2,
                                           min_score=0.5)
    assert selected == [strict, lexical]


def test_selector_all_lexical_fallback_excludes_negative_scores_but_keeps_zero():
    negative = HybridResult("negative.md", 1, 1, -0.1, 0.0, 0.0, "negative", "memory")
    zero = HybridResult("zero.md", 1, 1, 0.0, 0.0, 0.0, "zero", "memory")
    assert select_hybrid_search_results(merged=[negative, zero], keyword=[negative, zero],
                                        max_results=2, min_score=0.5) == [zero]
