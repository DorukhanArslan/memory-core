"""Offline adapter checks; native outcomes are established by the real oracle."""

from copy import deepcopy
import json

import pytest

from equivalence.index_identity import build_index_identity_cases, run_index_identity


def test_identity_cases_are_reproducible_and_do_not_claim_manager_admission():
    cases = build_index_identity_cases()
    assert cases == build_index_identity_cases()
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(case["requirement"] == "indexing.identity" for case in cases)
    assert all(case["covers"] == ["indexing.identity.outcomes"] for case in cases)
    assert {case["input"]["kind"] for case in cases} == {"state", "sources", "providers", "scope"}


def test_identity_adapter_preserves_inputs_and_standard_json_results():
    for case in build_index_identity_cases():
        before = deepcopy(case)
        json.dumps(run_index_identity(case["input"]), allow_nan=False)
        assert case == before


def test_identity_fixtures_retain_scope_provider_and_version_boundaries():
    names = {case["id"] for case in build_index_identity_cases()}
    assert {
        "identity-metadata-missing", "identity-matching-vector", "identity-provider-settings",
        "identity-source-order-duplicates", "identity-scope", "identity-tokenizer",
        "identity-chunk-type", "identity-new-provenance-old-chunker",
        "identity-old-provenance-new-chunker", "identity-version-hex-zero",
        "identity-version-empty-array", "identity-version-invalid-inf",
        "identity-provider-identities-endpoint-a", "identity-provider-identities-endpoint-b",
    }.issubset(names)


def test_unknown_identity_kind_is_a_failure():
    with pytest.raises(ValueError, match="Unsupported index identity operation"):
        run_index_identity({"kind": "unimplemented"})
