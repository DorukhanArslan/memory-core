from copy import deepcopy

import pytest

from equivalence.dream_light import build_cases, family_complete, validate_registration


def test_light_points_require_every_exact_operation_and_verified_capture():
    rows = [dict(row, status="matched", runtimeEvidenceValidated=True) for row in build_cases()]
    assert family_complete(rows)
    assert not family_complete(rows[:-1])
    reordered = deepcopy(rows)
    reordered[0], reordered[1] = reordered[1], reordered[0]
    assert not family_complete(reordered)
    rows[0]["runtimeEvidenceValidated"] = False
    assert not family_complete(rows)


def test_light_cannot_borrow_coverage_or_substitute_a_source_file():
    rows = build_cases()
    rows[0]["input"]["files"].clear()
    with pytest.raises(ValueError):
        validate_registration(rows)
    rows = build_cases()
    rows[0]["covers"].pop()
    with pytest.raises(ValueError):
        validate_registration(rows)
