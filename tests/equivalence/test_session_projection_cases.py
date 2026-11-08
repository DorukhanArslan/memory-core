"""Guards for retained transcript fixtures; native proof lives in strict reports."""
from copy import deepcopy
import json

from equivalence.session_projection import (
    build_prospective_session_projection_cases,
    build_session_projection_cases,
    run_session_projection,
)


def test_retained_session_cases_are_stable_and_leave_full_contract_open():
    cases = build_prospective_session_projection_cases()
    supported = build_session_projection_cases()
    for catalog, builder in ((cases, build_prospective_session_projection_cases),
                             (supported, build_session_projection_cases)):
        assert catalog == builder()
        assert len({case["id"] for case in catalog}) == len(catalog)
        assert json.loads(json.dumps(catalog, allow_nan=False)) == catalog
        assert all(case["requirement"] == "sessions.transcript-filtering" and case["covers"] == []
                   for case in catalog)
    assert len(cases) == 79
    assert len(supported) == 6
    assert supported == [case for case in cases if case["input"].get("resetOnly")]
    assert sum("legacy-corpus" in case["id"] for case in cases) == 15
    assert sum("legacy-raw-tree" in case["id"] for case in cases) == 26
    assert any("failed-and-mirrored" in case["id"] for case in cases)
    assert sum("-archive-ordinals" in case["id"] for case in cases) == 2
    assert any("all-branches-in-file-order" in case["id"] for case in cases)


def test_session_projection_preserves_raw_line_coordinates_and_inputs():
    for case in build_prospective_session_projection_cases():
        before = deepcopy(case)
        result = run_session_projection(case["input"])
        json.dumps(result, allow_nan=False)
        assert case == before
        if case["input"].get("resetOnly"):
            assert set(result) == {"resolvedResetCutoff"}
            continue
        entry = result["entry"]
        assert len(entry["lineMap"]) == len(entry["lineProvenance"]) == len(entry["messageTimestampsMs"])
        assert entry["resetRecallCutoff"] == {"state": "absent"}
    malformed = next(case for case in build_prospective_session_projection_cases()
                     if case["id"] == "session-projection-legacy-corpus-01")
    assert run_session_projection(malformed["input"])["entry"]["lineMap"] == [4]
