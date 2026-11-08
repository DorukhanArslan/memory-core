"""Fixture integrity guards; actual native execution establishes equivalence."""
from copy import deepcopy
import json

import pytest

from equivalence.vector_scoring import build_vector_scoring_cases, run_vector_scoring


def test_vector_matrix_is_deterministic_unique_standard_json_and_explicit_cpu_profile():
    cases = build_vector_scoring_cases()
    assert cases == build_vector_scoring_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert all(case["requirement"] == "retrieval.vector-scoring" for case in cases)
    assert all("KNN remains unverified" in case["driverScope"] for case in cases)
    assert all(case["input"].get("backend", "scan") == "scan" for case in cases)


def test_vector_acceptance_credit_follows_scoring_and_full_ordered_identity_profiles():
    cases = {case["id"]: case for case in build_vector_scoring_cases()}
    outcomes = "retrieval.vector-scoring.outcomes"
    boundaries = "retrieval.vector-scoring.boundaries"
    assert {point for case in cases.values() for point in case["covers"]} == {outcomes, boundaries}
    assert all(case["covers"] == [outcomes] for case in cases.values()
               if case["input"]["kind"] == "cosine")
    assert cases["vector-empty-query"]["covers"] == [outcomes]
    assert cases["vector-tie-order-is-rowid-not-path"]["covers"] == [boundaries]
    assert cases["vector-signed-rowid-batch-boundary"]["covers"] == [outcomes, boundaries]
    assert cases["vector-external-wal-payload-snapshot"]["covers"] == [boundaries]
    assert cases["vector-abort-before-scan"]["covers"] == []
    assert cases["vector-abort-after-full-batch"]["covers"] == []


def test_vector_adapter_preserves_inputs_and_exact_json_outputs():
    for case in build_vector_scoring_cases():
        before = deepcopy(case)
        json.dumps(run_vector_scoring(case["input"]), allow_nan=False)
        assert case == before


def test_vector_matrix_exercises_actual_metadata_bounds_and_exact_signed_rowid_cursor():
    cases = {case["id"]: case["input"] for case in build_vector_scoring_cases()}
    sparse = cases["vector-signed-rowid-batch-boundary"]["rows"]
    assert len(sparse) > 256
    assert sparse[0]["rowid"] == str(-(2**63))
    assert sparse[-1]["rowid"] == str(2**63 - 1)
    assert len({row["rowid"] for row in sparse}) == len(sparse)
    assert cases["vector-model-aliases-filter-before-limit"]["providerModelAliases"] == [
        "alias-model", "alias-model", "",
    ]
    assert cases["vector-hydrate-before-batch-mutation"]["mutateAfterBatch"]["replaceRows"][0]["text"] == "replacement"
    assert cases["vector-external-wal-payload-snapshot"]["externalDuringScan"]["replaceRows"][0]["text"] == "replacement payload"


def test_external_snapshot_fixture_commits_the_external_writer_during_real_scoring():
    case = next(case for case in build_vector_scoring_cases()
                if case["id"] == "vector-external-wal-payload-snapshot")
    result = run_vector_scoring(case["input"])
    assert result["observations"] == {
        "scannedRowids": ["1"],
        "externalRows": [{"id": "chunk-0", "text": "replacement payload"}],
    }


@pytest.mark.parametrize("backend", ["knn", "invented-accelerator"])
def test_unverified_accelerator_does_not_fall_back_or_gain_acceptance_credit(backend):
    case = next(case for case in build_vector_scoring_cases() if case["input"]["kind"] == "search")
    with pytest.raises(ValueError, match="portable CPU"):
        run_vector_scoring({**case["input"], "backend": backend})


def test_unknown_vector_operation_is_an_error():
    with pytest.raises(ValueError, match="Unsupported vector scoring"):
        run_vector_scoring({"kind": "fabricated-vector-phase"})
