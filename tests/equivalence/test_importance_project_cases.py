"""Fixture/transport integrity; actual native execution establishes equivalence."""
from copy import deepcopy
import json

import pytest

from equivalence.importance_project import build_importance_project_cases, run_importance_project


def _case(identifier):
    return next(case for case in build_importance_project_cases()
                if case["id"] == "importance-project-" + identifier)


def test_matrix_is_deterministic_unique_json_and_explicitly_bounded():
    cases = build_importance_project_cases()
    assert cases == build_importance_project_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert {case["input"]["kind"] for case in cases} == {
        "modifiers", "hybrid", "prepare", "recall", "stored-search",
    }
    assert all(case["requirement"] == "retrieval.importance-project" and set(case["covers"]) <= {
        "retrieval.importance-project.outcomes", "retrieval.importance-project.boundaries",
    }
               for case in cases)
    assert all("automatic trigger/project candidate admission remain unverified" in case["driverScope"]
               for case in cases)
    assert all(case["operation"] == ("importance-project-runtime"
               if case["input"]["kind"] == "stored-search" else "importance-project") for case in cases)


def test_reviewed_coverage_requires_stored_pipeline_and_keeps_empty_diagnostic_uncredited():
    cases = build_importance_project_cases()
    outcomes = [case for case in cases if "retrieval.importance-project.outcomes" in case["covers"]]
    boundaries = [case for case in cases if "retrieval.importance-project.boundaries" in case["covers"]]
    assert len(outcomes) == 53
    assert len(boundaries) == 25
    assert _case("modifiers-empty")["covers"] == []
    assert {case["input"]["kind"] for case in outcomes} == {
        "modifiers", "hybrid", "prepare", "recall", "stored-search",
    }
    assert sum(case["input"]["kind"] == "stored-search" for case in outcomes) == 8
    assert sum(case["input"]["kind"] == "stored-search" for case in boundaries) == 6
    assert all(case["input"]["kind"] not in {"prepare", "recall"} for case in boundaries)
    assert "retrieval.importance-project.boundaries" in _case("hybrid-decay-before-importance-project")["covers"]
    assert "retrieval.importance-project.boundaries" in _case("hybrid-mmr-after-modifiers")["covers"]


def test_all_actual_sdk_adapters_preserve_inputs_and_return_standard_json():
    for case in build_importance_project_cases():
        before = deepcopy(case)
        result = run_importance_project(case["input"])
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        assert case == before


def test_raw_reader_keeps_live_chunks_without_owned_metadata_and_excludes_absent_chunks():
    case = _case("recall-missing-chunk-is-excluded")
    rows = run_importance_project(case["input"])["rows"]
    assert rows == [{"id": "one", "importance": None, "triggers": None, "project_key": None}]


def test_reader_keeps_raw_annotation_and_nonblank_supersedes_bytes():
    annotations = run_importance_project(_case("recall-raw-annotation-whitespace-retained")["input"])
    assert annotations["rows"][0]["triggers"] == "  tea ; cedar  "
    assert annotations["rows"][0]["project_key"] == " alpha ; beta "
    provenance = run_importance_project(_case("recall-nonblank-supersedes-bytes-retained")["input"])
    assert provenance["rows"][0]["provenance"]["supersedesKey"] == " old-key "


def test_preparation_retains_all_annotation_fields_and_entry_ranges():
    result = run_importance_project(_case("prepare-all-annotations")["input"])["prepared"]
    assert set(result) == {"contentHash", "chunks"}
    assert len(result["chunks"]) == 1
    row = result["chunks"][0]
    assert {"text", "hash", "embeddingInput", "startLine", "endLine", "entryStartLine", "entryEndLine",
            "importance", "triggers", "projectKey", "provenance"} <= set(row)
    assert row["embeddingInput"] == {"text": row["text"]}
    assert row["importance"] == 10
    assert row["triggers"] == "tea; cedar"
    assert row["projectKey"] == "alpha"


def test_native_style_public_keyword_payload_is_full_and_keeps_internal_mtime_private():
    value = run_importance_project(_case("stored-triggers-provenance-and-user-scope")["input"])
    assert value["provider"] == "none"
    rows = value["steps"][0]["rows"]
    assert rows
    assert all({"path", "startLine", "endLine", "score", "textScore", "snippet", "source"} <= set(row)
               for row in rows)
    assert all(not {"sourceMtime", "source_mtime", "vectorScore", "id"} & set(row) for row in rows)
    assert any(row.get("triggers") == "tea; Çay 😀" for row in rows)
    assert all("provenance" in row for row in rows)


def test_stored_pipeline_retains_update_and_reopen_without_provider_calls():
    value = run_importance_project(_case("stored-annotations-update-and-reopen")["input"])
    before, changed, reopened = value["steps"]
    assert before["published"][0]["importance"] == 1
    assert changed["published"][0]["importance"] == 10
    assert changed["published"] == reopened["published"]
    assert changed["rows"] == reopened["rows"]


def test_runtime_evidence_retains_actual_full_private_publication_and_public_result(tmp_path):
    case = _case("stored-neutral-preservation")
    result = run_importance_project(case["input"], evidence_directory=tmp_path)
    raw = json.loads((tmp_path / "python-raw.json").read_text())
    assert isinstance(raw, list) and len(raw) == len(result["steps"])
    assert raw[0]["results"] == result["steps"][0]
    assert all("id" in row and "updatedAt" in row for row in raw[0]["published"]["chunks"])
    assert all(not {"id", "updatedAt"} & set(row) for row in result["steps"][0]["published"])


def test_unverified_clocked_runtime_does_not_silently_fall_back():
    arguments = deepcopy(_case("stored-neutral-preservation")["input"])
    arguments["temporalDecay"]["enabled"] = True
    with pytest.raises(ValueError, match="clock-neutral"):
        run_importance_project(arguments)


def test_unverified_prepare_provider_enforcement_is_explicitly_rejected():
    arguments = deepcopy(_case("prepare-neutral-entry")["input"])
    arguments["provider"] = {"id": "fixture-provider", "maxInputTokens": 10}
    with pytest.raises(ValueError, match="embedding enforcement"):
        run_importance_project(arguments)


def test_unknown_operation_is_an_error():
    with pytest.raises(ValueError, match="Unsupported importance/project operation"):
        run_importance_project({"kind": "invented"})
