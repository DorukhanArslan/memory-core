from itertools import permutations

import pytest

from equivalence.dream_phase_family import FAMILIES, evidence_family, report_key


@pytest.mark.parametrize(("independent", "checked"), permutations(FAMILIES.values(), 2))
def test_one_dream_phase_cannot_claim_or_erase_the_other_phases_points(independent, checked):
    rows = [dict(c, status="matched", runtimeEvidenceValidated=True)
            for phase in (independent, checked) for c in phase.build_cases()]
    assert independent.family_complete(rows)
    assert checked.family_complete(rows)
    rows[-1]["runtimeEvidenceValidated"] = False
    assert independent.family_complete(rows)
    assert not checked.family_complete(rows)
    assert evidence_family(independent.OPERATION) != evidence_family(checked.OPERATION)
    assert report_key(independent.OPERATION, "Transport") != report_key(checked.OPERATION, "Transport")
    row = rows[-1].copy()
    row["operation"] = independent.OPERATION
    with pytest.raises(ValueError):
        independent.validate_case(row)
