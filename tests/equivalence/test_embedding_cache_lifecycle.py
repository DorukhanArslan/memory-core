"""Frozen family and independent provider authority; no original owner executes."""
from copy import deepcopy
import hashlib

import pytest

from equivalence.embedding_cache_lifecycle import (
    CASE_HASHES, POINTS, build_cases, canonical, family_complete, validate_registration,
)
from equivalence.embedding_cache_lifecycle_profile import (
    case_bindings, validate_embedding_cache_lifecycle_profile,
)
from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME
from equivalence.runtime_oracle import ReleaseOracleExecution, RuntimeOracleError


def _profile():
    case = build_cases()[0]
    return {
        "kind": "approved-embedding-cache-lifecycle-profile", "operation": case["operation"],
        "inputKind": "embedding-cache-lifecycle", "caseId": case["id"],
        "caseBindings": case_bindings(),
        "nodeRuntime": {"execPath": "/approved/node", **APPROVED_NODE_RUNTIME},
    }


def test_complete_frozen_family_is_the_only_declared_two_point_authority():
    cases = build_cases()
    validate_registration(cases)
    assert len(cases) == len(CASE_HASHES) == 8
    assert POINTS == ("indexing.embedding-cache.outcomes", "indexing.embedding-cache.boundaries")
    assert hashlib.sha256(canonical(CASE_HASHES)).hexdigest() == (
        "3856a25129df0b84e9b49906b8f08b462290bd9ddd1720ddfb2ca6f5429d1790"
    )
    assert validate_embedding_cache_lifecycle_profile(_profile()) == _profile()
    assert family_complete([
        dict(case, status="matched", runtimeEvidenceValidated=True) for case in cases
    ])


@pytest.mark.parametrize("mutation", ["missing", "input", "coverage"])
def test_partial_changed_or_widened_registration_is_rejected(mutation):
    cases = deepcopy(build_cases())
    if mutation == "missing":
        cases.pop()
    elif mutation == "input":
        cases[0]["input"]["nowMs"] += 1
    else:
        cases[0]["covers"].append("promotion.recall-signals.outcomes")
    with pytest.raises(ValueError):
        validate_registration(cases)


def test_matches_without_the_whole_affirmatively_validated_family_earn_no_credit():
    rows = [dict(case, status="matched", runtimeEvidenceValidated=True) for case in build_cases()]
    rows[-1].pop("runtimeEvidenceValidated")
    assert not family_complete(rows)
    assert not family_complete([])


@pytest.mark.parametrize("mutation", ["case", "hash"])
def test_profile_rejects_an_unapproved_case_or_changed_frozen_hash(mutation):
    value = _profile()
    if mutation == "case":
        value["caseId"] = "embedding-cache-lifecycle-unapproved"
    else:
        value["caseBindings"][value["caseId"]] = "0" * 64
    with pytest.raises(ValueError):
        validate_embedding_cache_lifecycle_profile(value)


def test_peer_profile_is_rejected_before_original_context_or_import():
    with pytest.raises(RuntimeOracleError, match="cannot borrow"):
        with ReleaseOracleExecution(
            {}, {}, embedding_cache_profile=_profile(), recall_signals_profile={},
        ):
            raise AssertionError("Mixed authority reached original execution")


def test_legacy_fixture_source_capability_cannot_authorize_the_new_provider():
    with pytest.raises(RuntimeOracleError, match="cannot borrow"):
        with ReleaseOracleExecution(
            {}, {}, embedding_cache_profile=_profile(), fixture_captures=True,
        ):
            raise AssertionError("Legacy fixture authority reached original execution")


def test_provider_source_requires_its_independently_frozen_digest_before_import(tmp_path):
    with pytest.raises(RuntimeOracleError, match="independently frozen bytes"):
        with ReleaseOracleExecution(
            {"runtimeRoot": str(tmp_path), "packages": []},
            {"embedding-cache-provider/index.mjs": "0" * 64},
            embedding_cache_profile=_profile(),
        ):
            raise AssertionError("Changed provider source reached original execution")
