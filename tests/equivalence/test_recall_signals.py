"""Frozen recording authority and credit guards; no original owner executes."""
from copy import deepcopy

import pytest

from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME
from equivalence.recall_signals import CASE_HASHES, POINTS, build_cases, family_complete, validate_registration
from equivalence.recall_signals_profile import case_bindings, validate_recall_signals_profile
from equivalence.runtime_oracle import ReleaseOracleExecution, RuntimeOracleError


def _profile():
    case = build_cases()[0]
    return {"kind": "approved-recall-signals-profile", "operation": case["operation"],
            "inputKind": "recall-signals", "caseId": case["id"], "caseBindings": case_bindings(),
            "nodeRuntime": {"execPath": "/approved/node", **APPROVED_NODE_RUNTIME}}


def test_complete_frozen_family_is_the_only_declared_two_point_authority():
    cases = build_cases()
    validate_registration(cases)
    assert len(cases) == len(CASE_HASHES) == 6
    assert POINTS == ("promotion.recall-signals.outcomes", "promotion.recall-signals.boundaries")
    assert validate_recall_signals_profile(_profile()) == _profile()
    assert family_complete([dict(case, status="matched", runtimeEvidenceValidated=True) for case in cases])


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "input", "coverage", "order"])
def test_partial_changed_or_widened_registration_is_rejected(mutation):
    cases = deepcopy(build_cases())
    if mutation == "missing":
        cases.pop()
    elif mutation == "duplicate":
        cases.append(deepcopy(cases[-1]))
    elif mutation == "input":
        cases[0]["input"]["nowMs"] += 1
    elif mutation == "coverage":
        cases[0]["covers"].append("promotion.ranking-gates.outcomes")
    else:
        cases.reverse()
    with pytest.raises(ValueError):
        validate_registration(cases)


@pytest.mark.parametrize("mutation", ["missing-flag", "false-flag", "blocked", "missing-case"])
def test_matches_without_the_whole_affirmatively_validated_family_earn_no_credit(mutation):
    rows = [dict(case, status="matched", runtimeEvidenceValidated=True) for case in build_cases()]
    if mutation == "missing-flag":
        rows[-1].pop("runtimeEvidenceValidated")
    elif mutation == "false-flag":
        rows[-1]["runtimeEvidenceValidated"] = False
    elif mutation == "blocked":
        rows[-1]["status"] = "blocked"
    else:
        rows.pop()
    assert not family_complete(rows)
    assert not family_complete([])


@pytest.mark.parametrize("mutation", ["case", "hash"])
def test_profile_rejects_an_unapproved_case_or_changed_frozen_hash(mutation):
    value = _profile()
    if mutation == "case":
        value["caseId"] = "recall-signals-unapproved"
    else:
        value["caseBindings"][value["caseId"]] = "0" * 64
    with pytest.raises(ValueError):
        validate_recall_signals_profile(value)


@pytest.mark.parametrize("other", ["entry_profile", "forget_boundaries_profile"])
def test_mixed_capability_is_rejected_before_original_context_or_import(other):
    with pytest.raises(RuntimeOracleError, match="cannot borrow"):
        with ReleaseOracleExecution({}, {}, recall_signals_profile=_profile(), **{other: {}}):
            raise AssertionError("Mixed authority reached original execution")
