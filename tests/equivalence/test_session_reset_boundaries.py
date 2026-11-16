"""Closed one-point family authority; no original or SDK business owner runs."""
from copy import deepcopy
import hashlib

import pytest

from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME
from equivalence.runtime_oracle import ReleaseOracleExecution, RuntimeOracleError
from equivalence.session_reset_boundaries import (
    CASE_HASHES, POINTS, build_cases, canonical, family_complete, validate_registration,
)
from equivalence.session_reset_boundaries_profile import (
    case_bindings, validate_session_reset_boundaries_profile,
)


def _profile():
    case = build_cases()[0]
    return {
        "kind": "approved-session-reset-boundaries-profile", "operation": case["operation"],
        "inputKind": "session-reset-boundaries", "caseId": case["id"], "caseBindings": case_bindings(),
        "nodeRuntime": {"execPath": "/approved/node", **APPROVED_NODE_RUNTIME},
    }


def test_exact_seven_case_authority_covers_only_the_original_boundary_point():
    cases = build_cases()
    validate_registration(cases)
    assert len(cases) == len(CASE_HASHES) == 7
    assert POINTS == ("sessions.reset-hook.boundaries",)
    assert all(case["covers"] == list(POINTS) for case in cases)
    assert hashlib.sha256(canonical(CASE_HASHES)).hexdigest() == (
        "6d2d4043125f71ae236fe4482af8e2aec408d9a63b0ea00de201d315daa500ae"
    )
    assert validate_session_reset_boundaries_profile(_profile()) == _profile()


def test_partial_mutated_duplicated_or_widened_registration_is_rejected():
    for mutation in ("missing", "input", "coverage", "duplicate", "order"):
        cases = deepcopy(build_cases())
        if mutation == "missing":
            cases.pop()
        elif mutation == "input":
            cases[0]["input"]["nowMs"] += 1
        elif mutation == "coverage":
            cases[0]["covers"].append("sessions.reset-hook.outcomes")
        elif mutation == "duplicate":
            cases.append(deepcopy(cases[0]))
        else:
            cases.reverse()
        with pytest.raises(ValueError):
            validate_registration(cases)


def test_credit_requires_every_frozen_case_matched_and_affirmatively_validated():
    baseline = [dict(case, status="matched", runtimeEvidenceValidated=True) for case in build_cases()]
    assert family_complete(baseline)
    assert {point for row in baseline for point in row["covers"]} == set(POINTS)
    for mutation in ("missing-validation", "false-validation", "mismatch", "missing-case"):
        rows = deepcopy(baseline)
        if mutation == "missing-validation":
            rows[-1].pop("runtimeEvidenceValidated")
        elif mutation == "false-validation":
            rows[-1]["runtimeEvidenceValidated"] = False
        elif mutation == "mismatch":
            rows[-1]["status"] = "mismatched"
        else:
            rows.pop()
        assert not family_complete(rows)
    assert not family_complete([])


def test_profile_rejects_changed_case_hash_operation_or_extra_authority():
    for mutation in ("case", "hash", "operation", "extra"):
        value = _profile()
        if mutation == "case":
            value["caseId"] = "session-reset-boundaries-unapproved"
        elif mutation == "hash":
            value["caseBindings"][value["caseId"]] = "0" * 64
        elif mutation == "operation":
            value["operation"] = "recall-signals-runtime"
        else:
            value["covers"] = ["sessions.reset-hook.outcomes"]
        with pytest.raises(ValueError):
            validate_session_reset_boundaries_profile(value)


def test_peer_profile_is_denied_before_context_creation_or_owner_import():
    for peer in ("embedding_cache_profile", "recall_signals_profile"):
        with pytest.raises(RuntimeOracleError, match="cannot borrow"):
            with ReleaseOracleExecution({}, {}, session_reset_boundaries_profile=_profile(), **{peer: {}}):
                raise AssertionError("Mixed authority reached original execution")


def test_legacy_fixture_capability_cannot_authorize_the_reset_hook_profile():
    with pytest.raises(RuntimeOracleError, match="cannot borrow"):
        with ReleaseOracleExecution({}, {}, session_reset_boundaries_profile=_profile(), fixture_captures=True):
            raise AssertionError("Legacy fixture authority reached original execution")
