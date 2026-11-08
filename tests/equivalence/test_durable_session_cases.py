"""Fresh-process storage/context evidence, without fixture-computed continuations."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from equivalence.cases import run_python
from equivalence.durable_session_codec import map_durable_session_identities
from equivalence.durable_session_fixtures import build_durable_session_cases
from equivalence.get_contract import map_get_fixture_paths


@pytest.mark.parametrize("case", build_durable_session_cases(), ids=lambda case: case["id"])
def test_three_actual_processes_reopen_persisted_state_and_retain_full_io(case, tmp_path):
    request = deepcopy(case)
    request["_diagnosticDirectory"] = tmp_path / "evidence"
    before = deepcopy(request)
    result = run_python(request)
    assert request == before
    raw, = json.loads((tmp_path / "evidence" / "python-raw.json").read_text())
    assert raw["coordinatorPid"] == os.getpid()
    records = raw["phases"]
    assert len(records) == len({record["pid"] for record in records}) == 3
    assert raw["coordinatorPid"] not in {record["pid"] for record in records}
    public, paths = [], []
    previous_finish = -1
    for record, phase in zip(records, case["input"]["phases"], strict=True):
        assert record["label"] == phase["label"]
        assert previous_finish < int(record["startedAtNs"]) < int(record["finishedAtNs"])
        previous_finish = int(record["finishedAtNs"])
        assert record["exit"] == {"code": 0, "signal": None}
        expected_request = {"input": {key: value for key, value in case["input"].items() if key != "phases"},
                            "phase": phase, "directory": raw["fixtureBase"]}
        assert record["request"] == json.loads(record["requestJson"]) == expected_request
        assert record["requestSha256"] == hashlib.sha256(record["requestJson"].encode()).hexdigest()
        wire = json.loads(record["stdout"])
        assert wire["raw"] == record["raw"]
        actual = record["raw"]
        assert actual["pid"] == record["pid"] and actual["ppid"] == raw["coordinatorPid"]
        assert actual["request"] == expected_request
        assert Path(actual["implementationRoot"]) == Path(__file__).resolve().parents[2]
        snapshot = actual["snapshot"]
        assert {"sessionSql", "fullSql", "events", "visibleEvents", "context", "modelMessages",
                "preludeFlags", "modelPreludeFlags", "appendResults", "sourceEntries", "identityReads"} <= snapshot.keys()
        expected_public = {key: value for key, value in snapshot.items() if key not in {"sessionSql", "fullSql"}}
        assert wire["result"] == map_get_fixture_paths(expected_public, raw["fixtureBase"])
        assert len(snapshot["context"]["messages"]) == len(snapshot["preludeFlags"])
        assert len(snapshot["modelMessages"]) == len(snapshot["modelPreludeFlags"])
        assert len(actual["appendWrites"]) == len(phase.get("appendMessages", []))
        assert len(actual["sourceReads"]) == len(snapshot["sourceEntries"])
        public.append(wire["result"])
        paths.append(map_get_fixture_paths(actual["storePaths"]["databasePath"], raw["fixtureBase"]))
    assert result == {"provider": "none", "phases": map_durable_session_identities(public, paths)}
    assert records[2]["raw"]["sessionWrites"] == records[2]["raw"]["appendWrites"] == []
    assert records[2]["raw"]["syncRequest"] == {"force": False}
    assert result["phases"][1]["events"] == result["phases"][2]["events"]
    assert result["phases"][1]["context"] == result["phases"][2]["context"]
    assert result["phases"][1]["activeAnchor"] == result["phases"][2]["activeAnchor"]
    assert not Path(raw["fixtureBase"]).exists()


def test_private_process_state_is_present_only_in_its_original_child():
    case, = [case for case in build_durable_session_cases() if "private" in case["id"]]
    output = run_python(case)
    private = [phase["identityReads"][0] for phase in output["phases"]]
    assert private[0]["entry"]["sessionId"] == "durable-private"
    assert len(private[0]["events"]) == 2
    assert all("entry" not in read and read["events"] == [] and read["context"]["messages"] == [] for read in private[1:])
    assert all(not query["results"] for phase in output["phases"] for query in phase["queries"] if query["id"] == "privatebasil")
