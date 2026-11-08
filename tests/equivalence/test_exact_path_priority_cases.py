"""Fixture integrity guards; only actual native comparisons establish parity."""
from collections import Counter
from copy import deepcopy
import json

import pytest

from equivalence.exact_path_priority import (
    build_exact_path_priority_cases,
    run_exact_path_priority,
)


def _cases():
    return {case["id"]: case for case in build_exact_path_priority_cases()}


def test_exact_path_matrix_is_deterministic_unique_standard_json_and_declared_scope():
    cases = build_exact_path_priority_cases()
    assert cases == build_exact_path_priority_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert {case["requirement"] for case in cases} == {"retrieval.exact-path-priority"}
    assert {point for case in cases for point in case["covers"]} == {
        "retrieval.exact-path-priority.outcomes", "retrieval.exact-path-priority.boundaries",
    }
    assert all("Full manager orchestration" in case["driverScope"] for case in cases)


def test_exact_path_credit_follows_real_query_admission_and_priority_boundaries():
    cases = _cases()
    outcomes = "retrieval.exact-path-priority.outcomes"
    boundaries = "retrieval.exact-path-priority.boundaries"
    assert cases["exact-path-matcher-full"]["covers"] == [outcomes]
    assert cases["exact-path-search-full-path"]["covers"] == [outcomes]
    assert cases["exact-path-merge-empty"]["covers"] == [outcomes]
    assert cases["exact-path-merge-full-basename-stem-tiers"]["covers"] == [outcomes, boundaries]
    assert cases["exact-path-merge-snippet-length-is-utf16"]["covers"] == [outcomes, boundaries]
    assert cases["exact-path-limit-cap-keeps-all-chunks-of-retained-path"]["covers"] == [boundaries]
    assert cases["exact-path-search-orphan-exact-paths-before-live-cap"]["covers"] == [outcomes, boundaries]
    assert cases["exact-path-pipeline-strong-vector-does-not-cross-exact-tier"]["covers"] == [outcomes, boundaries]
    assert all(outcomes not in case["covers"] for case in cases.values()
               if case["input"]["kind"] == "limit")


def test_source_and_compiled_families_keep_their_actual_owner_boundaries():
    cases = build_exact_path_priority_cases()
    operations = Counter(case["operation"] for case in cases)
    assert operations == {"exact-path-priority": 49, "exact-path-runtime": 15}
    for case in cases:
        private = case["input"]["kind"] in {"limit", "merge-limit"}
        assert (case["operation"] == "exact-path-runtime") == private
        assert "without claiming private manager premerge" in case["driverScope"]


def test_exact_path_adapter_preserves_every_input_and_standard_json_output():
    raw_fields = {"id", "path", "startLine", "endLine", "source", "snippet", "score",
                  "textScore", "pathScore", "exactPathSpecificity", "hasBodyMatch"}
    for case in build_exact_path_priority_cases():
        before = deepcopy(case)
        output = run_exact_path_priority(case["input"])
        assert case == before
        assert output == json.loads(json.dumps(output, allow_nan=False))
        if case["input"]["kind"] == "matcher":
            assert len(output["specificities"]) == len(case["input"]["paths"])
        elif "rows" in output:
            assert all(row.keys() == raw_fields for row in output["rows"])
            if case["operation"] == "exact-path-runtime":
                assert output["provider"] == "none"
        else:
            assert output.keys() == {"pathRows", "merged", "selected"}
            assert all(row.keys() == raw_fields for row in output["pathRows"])


def test_live_chunk_controls_place_orphans_before_limits_without_inventing_live_rows():
    cases = _cases()
    exact = cases["exact-path-search-orphan-exact-paths-before-live-cap"]["input"]
    assert len(exact["paths"]) == 202 and len(exact["chunks"]) == 1
    assert exact["exactPathLimit"] == 200
    assert exact["paths"][-1]["path"] == exact["chunks"][0]["path"]
    assert all(row["path"] < exact["chunks"][0]["path"] for row in exact["paths"][:-1])
    lexical = cases["exact-path-search-orphan-lexical-path-before-live-limit"]["input"]
    assert lexical["limit"] == 1 and len(lexical["paths"]) == 2
    assert lexical["paths"][0]["path"] != lexical["chunks"][0]["path"]
    assert lexical["paths"][1]["path"] == lexical["chunks"][0]["path"]


def test_raw_total_limit_and_explicit_exact_headroom_share_identical_corpus():
    cases = _cases()
    default = deepcopy(cases["exact-path-search-default-total-limit"]["input"])
    explicit = deepcopy(cases["exact-path-search-explicit-exact-headroom"]["input"])
    assert explicit.pop("exactPathLimit") == 200
    assert explicit == default


def test_pipeline_body_candidates_are_source_backed_and_disjoint_from_path_projection():
    for case in build_exact_path_priority_cases():
        value = case["input"]
        if value["kind"] != "pipeline":
            continue
        output = run_exact_path_priority(value)
        path_ids = {row["id"] for row in output["pathRows"]}
        assert path_ids.isdisjoint(row["id"] for row in value["bodyRows"])
        chunks = {row["id"]: row for row in value["chunks"]}
        for row in value["bodyRows"]:
            source = chunks[row["id"]]
            assert all(row[key] == source[key] for key in
                       ("id", "path", "source", "startLine", "endLine"))


def test_exact_priority_controls_preserve_unicode_matching_and_utf16_length_inputs():
    cases = _cases()
    assert cases["exact-path-matcher-bom-trim"]["input"]["query"] == "\ufeffnote.md\ufeff"
    assert cases["exact-path-matcher-next-line-is-not-trim"]["input"]["query"].startswith("\u0085")
    assert cases["exact-path-search-unicode-simplefold-long-s"]["input"]["query"] == "ſ"
    assert cases["exact-path-search-unicode-simplefold-ligature"]["input"]["query"] == "ﬅ"
    assert cases["exact-path-search-unicode-dotless-i-does-not-match-i"]["input"]["query"] == "ı"
    sets = cases["exact-path-merge-snippet-length-is-utf16"]["input"]["resultSets"]
    assert [row["snippet"] for row in sets[0]] == ["ab", "abc", "ab"]
    assert [row["snippet"] for row in sets[1]] == ["😀", "😀x", "😀x"]


def test_runtime_dispatch_retains_genuine_constructed_merged_and_limited_evidence(tmp_path):
    from equivalence.cases import run_python

    case = deepcopy(_cases()["exact-path-merge-snippet-length-is-utf16"])
    original_input = deepcopy(case["input"])
    directory = tmp_path / "harness-owned-evidence"
    case["_diagnosticDirectory"] = directory
    result = run_python(case)
    assert case["input"] == original_input
    raw = json.loads((directory / "python-raw.json").read_text(encoding="utf-8"))
    assert isinstance(raw, list) and [step["phase"] for step in raw] == [
        "constructed", "merged", "limited",
    ]
    original = next(row for row in raw[0]["resultSets"][0] if row["id"] == "adversarial")
    merged = next(row for row in raw[1]["rows"] if row["id"] == "adversarial")
    assert original["snippet"] == "ab" and merged["snippet"] == "😀x"
    assert raw[-1]["rows"] == result["rows"]
    assert result["provider"] == "none"


@pytest.mark.parametrize("tokenizer", ["trigram", "invented"])
def test_unverified_path_tokenizer_is_rejected_instead_of_falling_back(tokenizer):
    value = deepcopy(_cases()["exact-path-search-full-path"]["input"])
    value["ftsTokenizer"] = tokenizer
    with pytest.raises(ValueError, match="unicode61"):
        run_exact_path_priority(value)


def test_unknown_exact_path_operation_is_rejected():
    with pytest.raises(ValueError, match="Unsupported exact-path"):
        run_exact_path_priority({"kind": "pretend-manager"})
