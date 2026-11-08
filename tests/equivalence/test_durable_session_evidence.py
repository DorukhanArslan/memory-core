"""Transport guards exercise protocol authority, not a transcript algorithm."""
from copy import deepcopy
import hashlib
import json

import pytest

from equivalence.durable_session_codec import map_durable_session_identities
from equivalence.durable_session_evidence import validate_durable_session_raw
from equivalence.durable_session_runtime_bindings import (
    MEMORY_INDEX_WORKER_ARTIFACTS, REQUIRED_PHASE_ARTIFACTS,
)
from equivalence.runtime_oracle import ROOT, RuntimeOracleError


def _fixture(tmp_path):
    base = tmp_path / "native-durable-session-ABCDEF"
    runtime_root = "/authenticated/openclaw"
    value = {"kind": "durable", "nowMs": 1000, "agentId": "main",
             "sessionKey": "agent:main:dm:one", "sessionId": "one",
             "phases": [{"label": label} for label in ("write", "continue", "verify")]}
    case = {"input": value}
    raw = {"fixtureBase": str(base), "kind": "durable", "coordinatorPid": 100, "phases": []}
    snapshots = []
    release = {}
    local = {100: {str(ROOT / "equivalence" / name) for name in
                   ("release-oracle.mjs", "durable-session-runtime.mjs", "durable-session-codec.mjs")}}
    bootstrap = [{"pid": pid, "isMainThread": True} for pid in (100, 101, 102, 103)]
    workers = []
    for index, phase in enumerate(value["phases"]):
        pid = 101 + index
        release[pid] = set(REQUIRED_PHASE_ARTIFACTS)
        local[pid] = {str(ROOT / "equivalence" / name) for name in
                      ("durable-session-phase.mjs", "durable-session-phase-cli.mjs", "get-contract-runtime.mjs")}
        if index < 2:
            workers += [{"pid": pid, "threadId": 1, "path": owner} for owner in MEMORY_INDEX_WORKER_ARTIFACTS]
        context = {"events": [], "visibleEvents": [], "context": {"messages": [], "model": None, "thinkingLevel": "off"},
                   "modelMessages": [], "preludeFlags": [], "modelPreludeFlags": []}
        snapshot = {"label": phase["label"], "instances": [], "catalog": [], "admitted": [], "sourceEntries": [],
                    "participantRecords": {}, **deepcopy(context), "identityReads": [], "appendResults": [],
                    "published": [], "indexSources": [], "queries": []}
        sql = {"chunks": [], "fts": [], "sources": [], "provenance": [], "recall": []}
        request = {"input": {key: item for key, item in value.items() if key != "phases"}, "phase": phase,
                   "directory": str(base), "runtimeRoot": runtime_root}
        observed = {"label": phase["label"], "pid": pid, "ppid": 100, "fixtureBase": str(base), "request": request,
                    "clock": {"owner": "node:test", "apis": ["Date"], "nowMs": 1000, "dateConstructorReplaced": True,
                              "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
                    "sessionWrites": [], "appendWrites": [], "sourceReads": [],
                    "contextRequests": [{"input": {"agentId": "main",
                                                    "storePath": str(base / "state/agents/main/sessions/sessions.json"),
                                                    "sessionKey": value["sessionKey"]},
                                         "result": deepcopy(context)}], "queries": [],
                    "syncRequest": {"reason": "durable-session-reopen", "force": index != 2},
                    "indexBeforeSync": deepcopy(sql),
                    "storePaths": {"databasePath": str(base / "state/agents/main/agent/openclaw-agent.sqlite"),
                                   "catalogStorePath": str(base / "state/agents/main/sessions/sessions.json")},
                    "snapshot": {**deepcopy(snapshot), "managerStatus": {}, "fullSql": deepcopy(sql),
                                 "sessionSql": {name: {"columns": [{"name": "id"}], "rows": []} for name in
                                                ("session_nodes", "session_windows", "transcript_events",
                                                 "transcript_rewrite_watermarks", "transcript_event_identities",
                                                 "session_transcript_active_events")}}}
        request_json = json.dumps(request)
        raw["phases"].append({"label": phase["label"], "pid": pid, "request": request,
                              "requestJson": request_json,
                              "requestSha256": hashlib.sha256(request_json.encode()).hexdigest(),
                              "startedAtNs": str(1 + index * 2), "finishedAtNs": str(2 + index * 2),
                              "exit": {"code": 0, "signal": None}, "stdout": json.dumps({"result": snapshot, "raw": observed}),
                              "stderr": "", "raw": observed})
        snapshots.append(snapshot)
    row = {"ok": True, "result": {"provider": "none", "phases": snapshots}}
    kwargs = {"runtime_root": runtime_root, "bootstrap": bootstrap, "release_by_pid": release,
              "local_by_pid": local, "worker_imports": workers,
              "process_parents": {100: 99, 101: 100, 102: 100, 103: 100}}
    return row, case, [raw], tmp_path, kwargs


def _validate(fixture):
    row, case, raw, directory, kwargs = fixture
    validate_durable_session_raw(row, case, raw, directory, **kwargs)


def _recapture(fixture):
    for record in fixture[2][0]["phases"]:
        old = json.loads(record["stdout"])
        record["stdout"] = json.dumps({"result": old["result"], "raw": record["raw"]})


def test_three_real_phase_protocol_and_false_force_verify(tmp_path):
    _validate(_fixture(tmp_path))


@pytest.mark.parametrize("field", ["setTimeoutUnchanged", "performanceNowUnchanged", "dateConstructorReplaced"])
def test_each_child_clock_retains_real_timers(tmp_path, field):
    fixture = _fixture(tmp_path)
    fixture[2][0]["phases"][1]["raw"]["clock"][field] = False
    _recapture(fixture)
    with pytest.raises(RuntimeOracleError, match="Date clock"):
        _validate(fixture)


@pytest.mark.parametrize("phase", [0, 1, 2])
def test_missing_or_forged_phase_parent_is_rejected(tmp_path, phase):
    fixture = _fixture(tmp_path)
    fixture[-1]["process_parents"][101 + phase] = 999
    with pytest.raises(RuntimeOracleError, match="real parent"):
        _validate(fixture)


@pytest.mark.parametrize("phase", [0, 1])
def test_wrapper_and_implementation_are_required_in_the_same_child_thread(tmp_path, phase):
    fixture = _fixture(tmp_path)
    target = next(entry for entry in fixture[-1]["worker_imports"] if entry["pid"] == 101 + phase)
    target["threadId"] = 2
    with pytest.raises(RuntimeOracleError, match="one protected child worker"):
        _validate(fixture)


def test_verify_fast_path_needs_no_invented_index_worker(tmp_path):
    fixture = _fixture(tmp_path)
    assert not any(item["pid"] == 103 for item in fixture[-1]["worker_imports"])
    _validate(fixture)


def test_worker_only_unknown_process_has_no_authenticated_parent(tmp_path):
    fixture = _fixture(tmp_path)
    fixture[-1]["bootstrap"].append({"pid": 999, "isMainThread": False})
    with pytest.raises(RuntimeOracleError, match="real parent"):
        _validate(fixture)


def test_protected_integrity_process_has_exact_entry_and_phase_lineage(tmp_path):
    fixture = _fixture(tmp_path)
    kwargs = fixture[-1]
    kwargs["bootstrap"].append({"pid": 104, "isMainThread": True})
    kwargs["process_parents"][104] = 103
    kwargs["release_by_pid"][104] = {"dist/infra/sqlite-integrity.worker.js"}
    kwargs["release_by_pid"][103].add("dist/openclaw-agent-db-maintenance-DBuIm8El.mjs")
    _validate(fixture)
    kwargs["process_parents"][104] = 999
    with pytest.raises(RuntimeOracleError, match="integrity owner and phase lineage"):
        _validate(fixture)


def test_unknown_additional_native_process_cannot_satisfy_phase_authority(tmp_path):
    fixture = _fixture(tmp_path)
    kwargs = fixture[-1]
    kwargs["bootstrap"].append({"pid": 104, "isMainThread": True})
    kwargs["process_parents"][104] = 103
    kwargs["release_by_pid"][104] = set(REQUIRED_PHASE_ARTIFACTS)
    with pytest.raises(RuntimeOracleError, match="integrity owner and phase lineage"):
        _validate(fixture)


@pytest.mark.parametrize("mutation", ["exit", "overlap", "request", "stdout", "pid", "verify-force", "sql", "context", "fts"])
def test_original_process_wire_sql_and_context_cannot_be_substituted(tmp_path, mutation):
    fixture = _fixture(tmp_path)
    records = fixture[2][0]["phases"]
    if mutation == "exit":
        records[0]["exit"]["code"] = 1
    elif mutation == "overlap":
        records[1]["startedAtNs"] = "1"
    elif mutation == "request":
        records[0]["requestJson"] = "{}"
    elif mutation == "stdout":
        records[0]["stdout"] = "{}"
    elif mutation == "pid":
        records[1]["pid"] = records[0]["pid"]
    elif mutation == "verify-force":
        records[2]["raw"]["syncRequest"]["force"] = True
    elif mutation == "sql":
        records[1]["raw"]["snapshot"]["sessionSql"] = {}
    elif mutation == "context":
        records[1]["raw"]["contextRequests"] = []
    elif mutation == "fts":
        records[1]["raw"]["snapshot"]["fullSql"]["chunks"] = [
            {"id": "one", "path": "sessions/main/one.jsonl", "source": "sessions", "model": "fts-only",
             "start_line": 1, "end_line": 1, "text": "body", "embeddingHex": ""}]
    if mutation != "stdout":
        _recapture(fixture)
    with pytest.raises(RuntimeOracleError):
        _validate(fixture)


def test_anchor_codec_preserves_equality_across_reopen_and_user_data():
    first, second = "a" * 32, "b" * 32
    anchor = {"generation": first, "storePath": "$FIXTURE/db", "agentId": "main"}
    phases = [{"appendResults": [{"result": {"anchor": anchor}}],
               "events": [{"generation": first, "storePath": "$FIXTURE/db"}]},
              {"appendResults": [], "activeAnchor": deepcopy(anchor)},
              {"appendResults": [], "activeAnchor": {**anchor, "generation": second}}]
    result = map_durable_session_identities(phases, ["$FIXTURE/db"] * 3)
    assert result[0]["appendResults"][0]["result"]["anchor"]["generation"] == "$GENERATION/1"
    assert result[1]["activeAnchor"]["generation"] == "$GENERATION/1"
    assert result[2]["activeAnchor"]["generation"] == "$GENERATION/2"
    assert result[0]["events"] == phases[0]["events"]
    assert phases[0]["appendResults"][0]["result"]["anchor"]["generation"] == first


@pytest.mark.parametrize("field,value", [("generation", "arbitrary"), ("storePath", "$FIXTURE/other"), ("agentId", None)])
def test_codec_requires_actual_recognized_producer_anchor(field, value):
    anchor = {"generation": "a" * 32, "storePath": "$FIXTURE/db", "agentId": "main", field: value}
    with pytest.raises(ValueError, match="recognized producer"):
        map_durable_session_identities([{"appendResults": [{"result": {"anchor": anchor}}]}], ["$FIXTURE/db"])
