from copy import deepcopy

import pytest

from equivalence.heartbeat_scratch_acceptance import build_cases, family_complete, validate_registration


def test_scratch_outcome_requires_all_39_literal_inputs_and_bound_phase_receipts():
    cases = build_cases()
    assert len(cases) == 39
    assert sum(case["input"]["phases"] for case in cases) == 69
    validate_registration(cases)
    with pytest.raises(ValueError):
        validate_registration(cases[1:])
    altered = deepcopy(cases)
    altered[0]["input"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        validate_registration(altered)

    digest = "a" * 64
    rows = [{**case, "status": "matched", "runtimeEvidenceValidated": True, "heartbeatScratchEvidence": {
        "id": case["input"]["fixture"], "matches": True, "nativeSha256": digest, "sdkSha256": digest,
        "stdoutSha256": [{"native": digest, "sdk": digest} for _ in range(case["input"]["phases"])],
    }} for case in cases]
    assert family_complete(rows)
    assert not family_complete(rows[1:])
    rows[-1]["heartbeatScratchEvidence"]["stdoutSha256"].pop()
    assert not family_complete(rows)
