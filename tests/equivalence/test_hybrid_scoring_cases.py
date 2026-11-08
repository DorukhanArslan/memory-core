"""Transport/fixture guards; the actual native comparison establishes equivalence."""
from copy import deepcopy
import json

import pytest

from equivalence.hybrid_scoring import build_hybrid_scoring_cases, run_hybrid_scoring


def test_hybrid_matrix_is_deterministic_unique_standard_json_and_declared_scope():
    cases = build_hybrid_scoring_cases()
    assert cases == build_hybrid_scoring_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert {case["input"]["kind"] for case in cases} == {"merge", "select", "merge-select"}
    assert all(case["operation"] == "hybrid-scoring" for case in cases)
    assert {case["requirement"] for case in cases} == {
        "retrieval.hybrid-scoring", "engine.unicode-collation",
    }
    assert all("full manager orchestration remain unverified" in case["driverScope"]
               for case in cases if case["requirement"] == "retrieval.hybrid-scoring")


def test_hybrid_acceptance_credit_follows_actual_merge_selection_and_payload_boundaries():
    cases = {case["id"]: case for case in build_hybrid_scoring_cases()}
    outcomes = "retrieval.hybrid-scoring.outcomes"
    boundaries = "retrieval.hybrid-scoring.boundaries"
    assert {point for case in cases.values() for point in case["covers"]} == {outcomes, boundaries}
    assert cases["hybrid-vector-only"]["covers"] == [outcomes]
    assert cases["hybrid-disjoint"]["covers"] == [outcomes]
    assert cases["hybrid-fractional-weights"]["covers"] == [outcomes]
    assert cases["hybrid-metadata-keyword-fills-null"]["covers"] == [outcomes, boundaries]
    assert cases["hybrid-select-source-and-range-identities"]["covers"] == [boundaries]
    assert cases["hybrid-select-all-lexical-fallback"]["covers"] == [boundaries]
    assert cases["hybrid-decay-map-selection-one-ulp-boundary"]["covers"] == [outcomes, boundaries]
    assert cases["hybrid-unicode-path-collation-diagnostic"]["covers"] == []
    assert all(outcomes not in case["covers"] for case in cases.values()
               if case["input"]["kind"] == "select")


def test_unicode_path_diagnostic_is_retained_exact_and_uncredited():
    diagnostic = next(case for case in build_hybrid_scoring_cases()
                      if case["id"] == "hybrid-unicode-path-collation-diagnostic")
    assert diagnostic["requirement"] == "engine.unicode-collation"
    assert diagnostic["covers"] == [] and diagnostic["declaredDeviation"]
    assert [row["path"] for row in diagnostic["input"]["vector"]] == ["memory/ß.md", "memory/t.md"]


def test_hybrid_adapter_preserves_inputs_and_returns_complete_standard_json_rows():
    required = {"path", "startLine", "endLine", "score", "vectorScore", "textScore", "snippet", "source"}
    optional = {"importance", "triggers", "projectKey", "provenance"}
    for case in build_hybrid_scoring_cases():
        before = deepcopy(case)
        result = run_hybrid_scoring(case["input"])
        assert case == before
        assert result == json.loads(json.dumps(result, allow_nan=False))
        assert all(required <= row.keys() <= required | optional
                   for rows in result.values() for row in rows)


def test_hybrid_select_transport_retains_explicit_null_and_empty_metadata():
    case = next(case for case in build_hybrid_scoring_cases()
                if case["id"] == "hybrid-select-retains-null-and-empty-metadata")
    result = run_hybrid_scoring(case["input"])
    assert result["selected"] == case["input"]["merged"]
    assert result["selected"][0]["importance"] is None
    assert result["selected"][0]["provenance"] == {}
    assert result["selected"][0]["triggers"] == ""


def test_hybrid_mtime_map_controls_share_actual_files_and_clock_inputs():
    cases = {case["id"]: deepcopy(case["input"]) for case in build_hybrid_scoring_cases()}
    missing = cases["hybrid-decay-workspace-stat"]
    empty = cases["hybrid-decay-empty-memory-map-is-authoritative"]
    override = cases["hybrid-decay-memory-map-overrides-stat"]
    assert empty.pop("memorySourceMtimes") == {}
    assert override.pop("memorySourceMtimes") == {"remote/report.md": 1737072000000}
    assert missing == empty == override
    assert missing["workspaceFiles"][0]["path"] == missing["vector"][0]["path"]


def test_hybrid_decay_selection_boundary_uses_the_observed_one_ulp_threshold():
    cases = {case["id"]: deepcopy(case["input"]) for case in build_hybrid_scoring_cases()}
    scoring = cases["hybrid-decay-memory-map-overrides-stat"]
    boundary = cases["hybrid-decay-map-selection-one-ulp-boundary"]
    assert boundary.pop("minScore") == 0.44547727214752497
    assert boundary.pop("maxResults") == 1
    assert boundary.pop("kind") == "merge-select"
    assert scoring.pop("kind") == "merge"
    assert boundary == scoring


def test_hybrid_metadata_matrix_exercises_absence_nullish_and_js_truthy_empty_objects():
    cases = {case["id"]: case["input"] for case in build_hybrid_scoring_cases()}
    absent = cases["hybrid-metadata-keyword-fills-missing"]["vector"][0]
    nullable = cases["hybrid-metadata-keyword-fills-null"]["vector"][0]
    empty = cases["hybrid-metadata-empty-values-are-retained"]["vector"][0]
    assert "importance" not in absent and "provenance" not in absent
    assert nullable["importance"] is None and nullable["provenance"] is None
    assert empty["importance"] == 0 and empty["triggers"] == ""
    assert empty["projectKey"] == "" and empty["provenance"] == {}


def test_hybrid_selector_matrix_preserves_source_and_range_identity_controls():
    case = next(case for case in build_hybrid_scoring_cases()
                if case["id"] == "hybrid-select-source-and-range-identities")
    regular, session, other_range = case["input"]["merged"][1:]
    assert regular["path"] == session["path"] == other_range["path"]
    assert regular["source"] != session["source"]
    assert regular["endLine"] != other_range["endLine"]
    assert len(case["input"]["keyword"]) == 2


@pytest.mark.parametrize("path", ["../escaped.md", "/tmp/escaped.md", "."])
def test_hybrid_workspace_fixture_rejects_paths_outside_its_private_root(path):
    with pytest.raises(ValueError, match="private root"):
        run_hybrid_scoring({
            "kind": "merge", "vector": [], "keyword": [], "vectorWeight": 1, "textWeight": 0,
            "workspaceFiles": [{"path": path, "text": "fixture", "mtimeMs": 0}],
        })


def test_unknown_hybrid_operation_is_an_error():
    with pytest.raises(ValueError, match="Unsupported hybrid scoring"):
        run_hybrid_scoring({"kind": "invented-operation"})
