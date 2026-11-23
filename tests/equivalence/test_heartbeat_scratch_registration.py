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


def test_mismatch_report_contains_both_reviewed_public_values_and_keeps_matched_rows_compact():
    from equivalence.heartbeat_scratch_acceptance import _digest, _report_row

    native = [{"returns": [{"changes": ["archived"]}], "snapshots": [{"source": {}}]}]
    sdk = [{"returns": [{"changes": ["copied"]}], "snapshots": [{"source": {"HEARTBEAT.md": "note"}}]}]
    receipt = {"matches": False, "openclaw": native, "python": sdk,
               "nativeSha256": _digest(native), "sdkSha256": _digest(sdk)}
    row = _report_row({"id": "mismatch"}, receipt)
    assert (row["openclaw"], row["python"]) == (native, sdk)
    assert not {"openclaw", "python"} & row["heartbeatScratchEvidence"].keys()
    assert "python" in receipt
    with pytest.raises(ValueError, match="reviewed projections"):
        _report_row({"id": "mismatch"}, {**receipt, "python": []})

    match = _report_row({"id": "match"}, {"matches": True, "nativeSha256": _digest(native), "sdkSha256": _digest(native)})
    assert not {"openclaw", "python"} & match.keys()
