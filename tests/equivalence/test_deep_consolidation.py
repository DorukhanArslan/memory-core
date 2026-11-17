"""A deep claim needs its own complete registered inputs and physical evidence."""
from copy import deepcopy

import pytest

from equivalence.deep_consolidation import build_cases, family_complete, validate_registration
from equivalence.promotion_apply_family import build_registered_cases


def test_deep_family_cannot_borrow_add_only_evidence_or_omit_fallbacks():
    cases = build_cases()
    validate_registration([*build_registered_cases(), *cases])
    for broken in (cases[:-1], [*cases[:1], *cases], list(reversed(cases))):
        with pytest.raises(ValueError):
            validate_registration(broken)
    rows = [dict(case, status="matched", runtimeEvidenceValidated=True) for case in cases]
    assert family_complete(rows)
    assert not family_complete([*rows[:-1], build_registered_cases()[-1]])
    tampered = deepcopy(rows)
    tampered[1]["input"]["originSeeds"].clear()
    assert not family_complete(tampered)
    rows[-1]["runtimeEvidenceValidated"] = False
    assert not family_complete(rows)
