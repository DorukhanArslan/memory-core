from copy import deepcopy

import pytest

from equivalence.cases import build_cases as catalog
from equivalence.flush_plan_target import BOUNDARY, build_cases, family_complete, validate_registration


def test_original_flush_cases_stay_unscored_and_only_the_complete_host_family_can_close_outcomes():
    rows = [r for r in catalog() if r["requirement"] == "flush.plan-target"]
    legacy = [r for r in rows if not r["covers"]]
    assert len(legacy) == 92
    validate_registration(rows)
    matched = [dict(r, status="matched", runtimeEvidenceValidated=True) for r in build_cases()]
    assert family_complete(legacy + matched)
    matched[-1]["runtimeEvidenceValidated"] = False
    assert not family_complete(legacy + matched)
    assert not family_complete(matched[:-1])
    revised = deepcopy(rows)
    revised[-1]["covers"].append(BOUNDARY)
    with pytest.raises(ValueError):
        validate_registration(revised)
    legacy[0]["input"] = {}
    with pytest.raises(ValueError):
        validate_registration(rows)


def test_boundary_append_keeps_old_outcome_credit_and_rejects_missing_preparation_evidence():
    from equivalence.flush_plan_target import (
        boundaries_complete, boundary_prerequisites_complete, build_boundary_cases,
    )

    full = catalog()
    cases = build_boundary_cases()
    assert full[-len(cases):] == cases
    with pytest.raises(ValueError, match="complete frozen host family"):
        validate_registration(cases[:-1])

    rows = [dict(case, status="matched", runtimeEvidenceValidated=True,
                 referenceMode="authenticated-official-release")
            for case in full if case["requirement"] == "flush.plan-target"]
    assert boundary_prerequisites_complete(rows)
    assert not boundaries_complete(rows)
    next(row for row in rows if row["covers"] == [])["status"] = "mismatched"
    assert family_complete(rows)
    assert not boundary_prerequisites_complete(rows)
