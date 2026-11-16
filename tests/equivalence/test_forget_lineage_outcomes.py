"""The complete fixed outcome family is required before coverage is credited."""
from copy import deepcopy

import pytest

from equivalence.forget_lineage_cases import build_cases as diagnostic_cases
from equivalence.forget_lineage_outcomes import (
    POINTS, build_cases, family_complete, validate_case, validate_registration,
)


def test_outcome_inputs_are_the_original_three_and_other_diagnostics_stay_uncredited():
    originals, outcomes = diagnostic_cases(), build_cases()
    assert len(outcomes) == 3
    assert all(case["covers"] == [] for case in originals)
    assert all(case["covers"] == list(POINTS) for case in outcomes)
    assert [(case["id"], case["operation"], case["input"]) for case in outcomes] == [
        (case["id"], case["operation"], case["input"]) for case in originals[:3]]
    validate_registration(outcomes)


@pytest.mark.parametrize("mutation", ["missing", "extra", "reorder", "input", "numeric-type", "policy", "coverage"])
def test_incomplete_or_changed_registration_cannot_gain_coverage(mutation):
    cases = build_cases()
    if mutation == "missing":
        cases.pop()
    elif mutation == "extra":
        cases.append(diagnostic_cases()[3])
    elif mutation == "reorder":
        cases.reverse()
    elif mutation == "input":
        cases[0]["input"]["operations"][0]["sessionIds"] = ["B"]
    elif mutation == "numeric-type":
        cases[0]["input"]["nowMs"] = float(cases[0]["input"]["nowMs"])
    elif mutation == "policy":
        cases[0]["normalizationPolicy"] = "omit any difference"
    else:
        cases[0]["covers"].append("forget.lineage-tombstones.boundaries")
    with pytest.raises(ValueError):
        validate_registration(cases)


@pytest.mark.parametrize("mutation", ["none", "missing", "mismatch", "blocked", "unverified", "changed"])
def test_point_needs_every_complete_pair_and_affirmative_raw_evidence(mutation):
    rows = [dict(deepcopy(case), status="matched", runtimeEvidenceValidated=True) for case in build_cases()]
    assert family_complete(rows)
    if mutation == "missing":
        rows.pop()
    elif mutation in {"mismatch", "blocked"}:
        rows[0]["status"] = mutation
    elif mutation == "unverified":
        rows[0]["runtimeEvidenceValidated"] = False
    elif mutation == "changed":
        rows[0]["input"]["origins"].pop()
    assert family_complete(rows) is (mutation == "none")


def test_an_unrelated_case_cannot_borrow_the_outcome_condition():
    case = deepcopy(diagnostic_cases()[4])
    case["covers"] = list(POINTS)
    with pytest.raises(ValueError):
        validate_case(case)
