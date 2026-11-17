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
