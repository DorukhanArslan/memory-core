"""Real dispatch→write→stored-message provenance evidence survives a fresh process."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from equivalence.get_contract import map_get_fixture_paths
from equivalence.cases import run_python
from equivalence.turn_trust_fixtures import build_turn_trust_cases
from equivalence.turn_trust_runtime import run_turn_trust


@pytest.mark.parametrize("case", build_turn_trust_cases(), ids=lambda case: case["id"])
def test_actual_tools_and_fresh_storage_reopen_retain_complete_public_and_raw_records(case, tmp_path):
    value = deepcopy(case["input"])
    before = deepcopy(value)
    result = run_python({**case, "input": value, "_diagnosticDirectory": tmp_path / "evidence"})
    assert value == before
    raw, = json.loads((tmp_path / "evidence" / "python-raw.json").read_text())
    assert raw["coordinatorPid"] == os.getpid()
    assert raw["reopen"]["exitCode"] == 0
    reopened = json.loads(raw["reopen"]["stdout"])
    assert reopened["raw"] == raw["reopen"]["raw"]
    assert reopened["raw"]["pid"] != raw["coordinatorPid"]
    assert reopened["raw"]["ppid"] == raw["coordinatorPid"]
    assert Path(reopened["raw"]["implementationRoot"]) == Path(__file__).resolve().parents[2]
    assert reopened["raw"]["request"] == raw["reopen"]["request"]
    assert raw["sessionSql"] == reopened["raw"]["sessionSql"]
    assert {"memory_session_nodes", "memory_session_events", "memory_session_windows"} <= raw["sessionSql"].keys()
    expected = {"provider": "none", "turns": raw["turns"], **reopened["result"]}
    assert result == map_get_fixture_paths(expected, raw["fixtureBase"])
    assert len(result["storedEvents"]) == len(raw["appends"]) + 1
    assert result["storedEvents"][0]["type"] == "session" and result["storedEvents"][0]["version"] == 4
    assert [event["id"] for event in result["storedEvents"][1:]] == [entry["eventId"] for entry in raw["appends"]]
    assert raw["presentationObservations"] == [{
        "origin": "trusted-host-presentation", "turnId": turn["id"], "observation": observation,
        "before": False, "after": False,
    } for turn in case["input"]["turns"] for observation in turn.get("presentationObservations", [])]
    for turn in result["turns"]:
        for attempt in turn["attempts"]:
            observations, = [entry["observations"] for entry in raw["toolObservations"]
                             if entry["turnId"] == turn["id"] and entry["attemptId"] == attempt["id"]]
            assert all(entry["origin"] == "dispatched-tool" for entry in raw["toolObservations"])
            assert len(observations) == len(attempt["toolOutcomes"])
            for observation, outcome in zip(observations, attempt["toolOutcomes"], strict=True):
                assert observation["toolCallId"] == outcome["id"] and observation["toolName"] == outcome["name"]
                assert observation["arguments"] == outcome["input"]
                assert observation.get("result") == outcome.get("result")
                assert observation.get("error") == outcome.get("error")
    assert not Path(raw["fixtureBase"]).exists()


def test_network_result_taints_same_turn_retry_and_new_turn_is_clean_while_file_quarantine_persists():
    case = build_turn_trust_cases()[0]
    result = run_turn_trust(case["input"])
    tainted, clean = result["turns"]
    assert all(attempt["trust"] == {"tainted": True} for attempt in tainted["attempts"])
    assert clean["trust"] == {"tainted": False}
    records = {entry["relativePath"]: entry["provenance"] for entry in result["artifacts"]}
    assert records["memory/2026-11-10.md"]["originClass"] == "untrusted"
    assert records["memory/clean.md"]["originClass"] == "agent"
    later = tainted["attempts"][1]["messages"][-1]
    assert later["__openclaw"] == {"turnTainted": True}
    assert "__openclaw" not in clean["attempts"][0]["messages"][-1]
    source = result["sourceEntry"]
    assert any(line["originClass"] == "untrusted" for line in source["lineProvenance"])


def test_actual_network_error_taints_recovery_write_and_retains_its_complete_error():
    case = build_turn_trust_cases()[1]
    result = run_turn_trust(case["input"])
    nonowner, network = result["turns"]
    assert nonowner["trust"] == {"tainted": False}
    assert network["trust"] == {"tainted": True}
    error, = network["attempts"][0]["toolOutcomes"]
    assert error["error"] == {"name": "Error", "message": "Declared network fixture failure.", "code": "FIXTURE_NETWORK"}
    assert network["attempts"][0]["messages"][-1]["__openclaw"] == {"resultContentSource": "network"}
    records = {entry["relativePath"]: entry["provenance"] for entry in result["artifacts"]}
    assert records["memory/non-owner.md"]["originClass"] == records["memory/error.md"]["originClass"] == "untrusted"
