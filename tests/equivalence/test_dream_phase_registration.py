import pytest

from equivalence.dream_phase_family import FAMILIES, evidence_family, report_key


def test_one_dream_phase_cannot_claim_or_erase_the_other_phases_points():
    light, rem = FAMILIES.values()
    rows = [dict(c, status="matched", runtimeEvidenceValidated=True)
            for phase in (light, rem) for c in phase.build_cases()]
    assert light.family_complete(rows)
    assert rem.family_complete(rows)
    rows[-1]["runtimeEvidenceValidated"] = False
    assert light.family_complete(rows)
    assert not rem.family_complete(rows)
    assert evidence_family(light.OPERATION) != evidence_family(rem.OPERATION)
    assert report_key(light.OPERATION, "Transport") != report_key(rem.OPERATION, "Transport")
    row = rows[-1].copy()
    row["operation"] = light.OPERATION
    with pytest.raises(ValueError):
        light.validate_case(row)
