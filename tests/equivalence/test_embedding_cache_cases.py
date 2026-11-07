"""Fixture guard checks; real equivalence comes from the pinned source runner."""
from copy import deepcopy
import json

import pytest

from equivalence.embedding_cache import build_embedding_cache_cases, run_embedding_cache


def test_cache_kernel_fixtures_are_unique_reproducible_and_explicitly_partial():
    cases = build_embedding_cache_cases()
    assert cases == build_embedding_cache_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert json.loads(json.dumps(cases, allow_nan=False)) == cases
    assert all(case["requirement"] == "indexing.embedding-cache" and case["covers"] == []
               for case in cases)


def test_cache_adapter_preserves_inputs_and_returns_standard_json():
    for case in build_embedding_cache_cases():
        before = deepcopy(case)
        json.dumps(run_embedding_cache(case["input"]), allow_nan=False)
        assert case == before


def test_cache_fixtures_exercise_large_lookups_and_real_reopen_rollback():
    cases = {case["id"]: case for case in build_embedding_cache_cases()}
    batched = cases["embedding-cache-batched-lookups"]["input"]["steps"]
    assert len(batched[0]["entries"]) == len(batched[1]["hashes"]) == 405
    assert len({entry["hash"] for entry in batched[0]["entries"]}) == 405
    assert {step["action"] for step in cases["embedding-cache-transaction-commit-reopen"]["input"]["steps"]} == {
        "begin", "put", "commit", "reopen", "load",
    }
    assert {step["action"] for step in cases["embedding-cache-invalid-write-rollback"]["input"]["steps"]} == {
        "put", "begin", "rollback", "load",
    }


def test_unknown_cache_kind_is_an_error_instead_of_a_match_placeholder():
    with pytest.raises(ValueError, match="Unsupported embedding cache operation"):
        run_embedding_cache({"kind": "invented-cache-phase"})
