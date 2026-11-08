"""Actual SDK source reads, callback errors and filesystem mutations retain evidence."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from equivalence.cases import run_python
from equivalence.get_contract import map_get_fixture_paths
from equivalence.transcript_boundary_fixtures import build_transcript_boundary_cases


def test_boundary_inputs_are_literal_deterministic_and_uncredited():
    cases = build_transcript_boundary_cases()
    assert cases == build_transcript_boundary_cases()
    assert len(cases) == len({case["id"] for case in cases}) == 8
    assert json.loads(json.dumps(cases, ensure_ascii=False, allow_nan=False)) == cases
    assert all(case["covers"] == [] for case in cases)
    assert [case["id"] for case in cases if case.get("diagnosticOnly")] == [
        "transcript-boundary-compressed-same-size-mtime-cache-diagnostic"]
    compressed = [case for case in cases if case["input"].get("fileName", "").endswith(".zst")]
    assert all(case["input"]["environmentFault"] == {"kind": "preferred-temp-root-unavailable"} for case in compressed)


@pytest.mark.parametrize("case", build_transcript_boundary_cases(), ids=lambda case: case["id"])
def test_actual_source_dispatch_retains_every_mutation_callback_and_complete_read(case, tmp_path):
    request = deepcopy(case)
    request["_diagnosticDirectory"] = tmp_path / "evidence"
    before = deepcopy(request)
    result = run_python(request)
    assert request == before
    raw, = json.loads((tmp_path / "evidence" / "python-raw.json").read_text())
    reads = [step for step in case["input"]["steps"] if step["op"] == "read"]
    assert len(raw["reads"]) == len(raw["sourceCaptures"]) == len(reads)
    observed = [read["result"] for read in raw["reads"]]
    assert result == map_get_fixture_paths({"provider": "none", "reads": observed}, raw["fixtureBase"])
    assert len(raw["mutations"]) == sum(step["op"] != "read" for step in case["input"]["steps"]) + ("initial" in case["input"])
    assert not Path(raw["fixtureBase"]).exists()
    for row in result["reads"]:
        if row.get("entry"):
            assert {"path", "absPath", "mtimeMs", "size", "hash", "content", "lineMap",
                    "messageTimestampsMs", "lineProvenance", "sessionKind"} <= row["entry"].keys()
        if "error" in row:
            assert row["error"] == {"name": "Error", "message": "Declared transcript observer failure", "code": "FIXTURE_OBSERVER"}


def test_observer_failure_keeps_storage_boundary_and_original_observed_message():
    results = {case["input"]["source"]: run_python(case)["reads"][0]
               for case in build_transcript_boundary_cases() if case["id"].endswith("observer-error")}
    assert results["jsonl"]["entry"] is None
    assert "error" in results["sqlite"]
    assert results["jsonl"]["observedMessages"] == results["sqlite"]["observedMessages"]
    assert results["sqlite"]["observedMessages"][0]["message"]["content"] == "Cedar root"


def test_cache_diagnostic_does_not_stale_the_sdk_or_invent_expected_reference_output():
    case, = [case for case in build_transcript_boundary_cases() if case.get("diagnosticOnly")]
    result = run_python(case)
    assert [read["entry"]["content"] for read in result["reads"]] == ["User: Cedar A.", "User: Cedar B."]
    assert case["covers"] == []
