"""Guards for retained transcript fixtures; native proof lives in strict reports."""
from copy import deepcopy
import json

from equivalence.session_projection import (
    build_prospective_session_projection_cases,
    build_session_projection_cases,
    run_session_projection,
)


def test_retained_session_cases_are_stable_and_credit_only_projection_outcomes():
    cases = build_prospective_session_projection_cases()
    supported = build_session_projection_cases()
    for catalog, builder in ((cases, build_prospective_session_projection_cases),
                             (supported, build_session_projection_cases)):
        assert catalog == builder()
        assert len({case["id"] for case in catalog}) == len(catalog)
        assert json.loads(json.dumps(catalog, allow_nan=False)) == catalog
        assert all(case["requirement"] == "sessions.transcript-filtering" for case in catalog)
        assert all(case["covers"] == ([] if case["input"].get("resetOnly") else
                                     ["sessions.transcript-filtering.outcomes"])
                   for case in catalog)
    assert len(cases) == 79
    assert supported == cases
    assert sum(bool(case["covers"]) for case in supported) == 73
    assert sum(bool(case["input"].get("resetOnly")) for case in supported) == 6
    assert sum("legacy-corpus" in case["id"] for case in cases) == 15
    assert sum("legacy-recent" in case["id"] for case in cases) == 19
    assert sum("legacy-raw-tree" in case["id"] for case in cases) == 26
    assert any("failed-and-mirrored" in case["id"] for case in cases)
    assert sum("-archive-ordinals" in case["id"] for case in cases) == 2
    names = {case["id"] for case in cases}
    assert {f"session-projection-{name}" for name in (
        "indexes-all-branches-in-file-order", "indexes-side-append-entries-in-file-order",
        "keeps-file-order-without-leaf-controls",
    )}.issubset(names)

    # These are stored input facts, not copied legacy expected projections.
    rows = []
    for case in cases:
        for line in case["input"].get("jsonl", "").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    messages = [row["message"] for row in rows if isinstance(row, dict)
                and isinstance(row.get("message"), dict)]
    assert {message.get("role") for message in messages}.issuperset({"user", "assistant", "tool"})
    assert any(message.get("stopReason") == "error" for message in messages)
    assert any(message.get("model") == "delivery-mirror" for message in messages)
    assert {message.get("provenance", {}).get("sourceTool") for message in messages
            if isinstance(message.get("provenance"), dict)}.issuperset({"heartbeat", "memory_search"})


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
