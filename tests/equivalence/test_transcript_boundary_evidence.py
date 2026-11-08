"""Non-executing wire fixtures test evidence rejection, never native equivalence."""
from copy import deepcopy
import hashlib

import pytest

from equivalence.get_contract import map_get_fixture_paths
from equivalence.runtime_oracle import RuntimeOracleError
from equivalence.transcript_boundary_evidence import validate_transcript_boundary_raw
from equivalence.transcript_boundary_runtime_bindings import (
    ARCHIVE_ARTIFACTS, REQUIRED_BOUNDARY_ARTIFACTS, SQLITE_BOUNDARY_ARTIFACTS,
    TRANSCRIPT_WORKER_ARTIFACTS, TRANSCRIPT_WORKER_PARENT_ARTIFACTS,
)

_NOW = 1794000000000


def _fixture(tmp_path, *, source="jsonl", compressed=False, observer=False):
    base = str(tmp_path / "native-transcript-boundary-fixture")
    filename = "boundary.jsonl" + (".reset.2026-11-09T00-00-00Z.zst" if compressed else "")
    physical = base + "/state/agents/main/sessions/" + filename
    event = {"type": "message", "id": "u1", "message": {"role": "user", "content": "A"}}
    input = {"kind": "boundary", "source": source, "nowMs": _NOW,
             "steps": [{"op": "read", "label": "first"}]}
    scope = {"agentId": "main", "sessionId": "boundary", "sessionKey": "agent:main:dm:boundary",
             "storePath": base + "/state/agents/main/sessions/sessions.json"}
    literal = list(b'{"type":"message"}\n')
    input["initial"] = {"events": [event]} if source == "sqlite" else {"rawBytes": literal}
    options = {"sessionKind": "interactive"}
    if source == "sqlite":
        options.update(scope)
        options["updatedAtMs"] = _NOW
    if observer:
        input["observer"] = True
        options["onTranscriptMessage"] = True
    identity = scope["sessionKey"] if source == "sqlite" else physical
    entry = {"path": "sessions/main/" + filename, "absPath": identity,
             "mtimeMs": _NOW, "size": len(literal), "hash": "a" * 64, "content": "User: A",
             "lineMap": [1], "messageTimestampsMs": [0], "lineProvenance": [{"originClass": "owner"}],
             "sessionKind": "interactive"}
    result = {"label": "first", "entry": entry, "resetRecallCutoff": {"state": "absent"},
              "observedMessages": [{"message": event["message"], "timestampMs": _NOW}] if observer else []}
    raw = {"fixtureBase": base, "kind": "boundary", "source": source,
           "constructorSkipped": True, "managerFixture": False, "indexManagerConstructed": False,
           "clock": {"owner": "node:test", "apis": ["Date"], "nowMs": _NOW,
                     "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
           "mutations": [{"op": "initial", "input": input["initial"]}], "writeCalls": [],
           "reads": [{"request": {"absPath": identity, "options": options}, "result": result}],
           "sourceCaptures": [], "cacheCaptures": [],
           "observerCalls": [{"readIndex": 0, "message": event["message"], "timestampMs": _NOW}] if observer else [],
           "environmentFault": {"input": None, "calls": [], "restored": []}}
    loaded = set(REQUIRED_BOUNDARY_ARTIFACTS)
    workers = []
    if source == "sqlite":
        raw["sourceCaptures"] = [{"scope": scope, "entry": {"sessionId": "boundary", "updatedAt": _NOW}, "events": [event]}]
        raw["writeCalls"] = [{"request": {"scope": deepcopy(scope), "events": deepcopy([event])},
                              "capture": deepcopy(raw["sourceCaptures"][0])}]
        loaded.update(SQLITE_BOUNDARY_ARTIFACTS)
        if not observer:
            loaded.update(TRANSCRIPT_WORKER_PARENT_ARTIFACTS)
            workers = [{"package": "node_modules/openclaw", "pid": 101, "threadId": 2, "path": path}
                       for path in {*TRANSCRIPT_WORKER_ARTIFACTS, "dist/session-files-DVVT4Ngb.mjs",
                                    "dist/session-accessor.sqlite-read-BsSfe2AE.mjs"}]
    else:
        raw["sourceCaptures"] = [{"filename": physical, "bytes": literal,
                                  "stat": {"dev": "27", "ino": "123", "mode": "33152", "size": str(len(literal)),
                                           "mtimeNs": str(_NOW * 1_000_000), "ctimeNs": str(_NOW * 1_000_000)}}]
    if compressed:
        input["fileName"] = filename
        input["environmentFault"] = {"kind": "preferred-temp-root-unavailable"}
        raw["environmentFault"] = {"input": input["environmentFault"], "restored": [True],
                                   "calls": [{"readIndex": 0, "operation": "lstatSync", "path": "/tmp/openclaw", "code": "EACCES"}]}
        cache_path = (base + "/tmp/openclaw-1000/session-archive-read-cache/"
                      + hashlib.sha256(physical.encode()).hexdigest()[:32] + f"-{len(literal)}-{_NOW}.jsonl")
        decoded = b'{"type":"message"}\n'
        raw["cacheCaptures"] = [{"label": "first", "root": base + "/tmp", "files": [
            {"path": cache_path, "size": len(decoded), "bytes": list(decoded), "sha256": hashlib.sha256(decoded).hexdigest()}]}]
        loaded.update(ARCHIVE_ARTIFACTS)
    row = {"ok": True, "result": map_get_fixture_paths({"provider": "none", "reads": [result]}, base)}
    return row, {"input": input}, [raw], {"release_by_pid": {101: loaded}, "worker_imports": workers}


def _validate(fixture, directory):
    row, case, raw, kwargs = fixture
    validate_transcript_boundary_raw(row, case, raw, directory, **kwargs)


@pytest.mark.parametrize("source,compressed,observer", [
    ("jsonl", False, False), ("jsonl", True, False), ("jsonl", False, True),
    ("sqlite", False, False), ("sqlite", False, True),
])
def test_complete_nonexecuting_transport_shapes_are_accepted(tmp_path, source, compressed, observer):
    _validate(_fixture(tmp_path, source=source, compressed=compressed, observer=observer), tmp_path)


@pytest.mark.parametrize("mutation", [
    lambda f: f[0]["result"]["reads"][0]["entry"].pop("lineProvenance"),
    lambda f: f[2][0]["sourceCaptures"][0]["bytes"].append(1),
    lambda f: f[2][0]["sourceCaptures"][0]["stat"].update(mtimeNs="1"),
    lambda f: f[2][0]["clock"].update(setTimeoutUnchanged=False),
    lambda f: f[2][0].update(fixtureBase="/tmp/native-transcript-boundary-unowned"),
    lambda f: f[2][0]["mutations"][0].update(input={"rawBytes": []}),
    lambda f: f[2][0]["reads"][0]["request"]["options"].update(sessionKind="cron"),
    lambda f: f[3]["release_by_pid"][101].clear(),
    lambda f: f[2][0]["reads"].__setitem__(0, None),
])
def test_complete_source_transport_tampering_is_rejected(tmp_path, mutation):
    fixture = _fixture(tmp_path)
    mutation(fixture)
    with pytest.raises(RuntimeOracleError):
        _validate(fixture, tmp_path)


def test_observer_trace_cannot_be_dropped_with_public_reply(tmp_path):
    fixture = _fixture(tmp_path, observer=True)
    fixture[2][0]["reads"][0]["result"]["observedMessages"] = []
    fixture[0]["result"]["reads"][0]["observedMessages"] = []
    with pytest.raises(RuntimeOracleError, match="observer"):
        _validate(fixture, tmp_path)


@pytest.mark.parametrize("mutation", [
    lambda f: f[2][0]["cacheCaptures"][0]["files"][0].update(path="/tmp/openclaw/cache.jsonl"),
    lambda f: f[2][0]["cacheCaptures"][0]["files"][0].update(sha256="b" * 64),
    lambda f: f[2][0]["cacheCaptures"][0].update(files=[]),
    lambda f: f[2][0]["environmentFault"].update(restored=[False]),
    lambda f: f[2][0]["environmentFault"]["calls"][0].update(path="/tmp/unowned"),
    lambda f: f[3]["release_by_pid"][101].difference_update(ARCHIVE_ARTIFACTS),
])
def test_archive_fallback_and_materialization_tampering_is_rejected(tmp_path, mutation):
    fixture = _fixture(tmp_path, compressed=True)
    mutation(fixture)
    with pytest.raises(RuntimeOracleError):
        _validate(fixture, tmp_path)


@pytest.mark.parametrize("mutation", [
    lambda f: f[2][0]["sourceCaptures"][0]["events"].clear(),
    lambda f: f[2][0]["sourceCaptures"][0]["scope"].update(sessionId="other"),
    lambda f: f[3]["worker_imports"].clear(),
    lambda f: f[3]["worker_imports"][0].update(threadId=3),
    lambda f: f[3]["release_by_pid"][101].difference_update(TRANSCRIPT_WORKER_PARENT_ARTIFACTS),
])
def test_sqlite_source_and_specific_worker_identity_tampering_is_rejected(tmp_path, mutation):
    fixture = _fixture(tmp_path, source="sqlite")
    mutation(fixture)
    with pytest.raises(RuntimeOracleError):
        _validate(fixture, tmp_path)


def test_file_error_remains_null_and_sqlite_error_keeps_all_public_properties(tmp_path):
    fixture = _fixture(tmp_path)
    result = fixture[2][0]["reads"][0]["result"]
    result.pop("entry")
    result.pop("resetRecallCutoff")
    result["error"] = {"name": "Error", "message": "failure", "code": "SQLITE_CORRUPT", "errno": 11}
    fixture[0]["result"]["reads"] = map_get_fixture_paths([result], fixture[2][0]["fixtureBase"])
    with pytest.raises(RuntimeOracleError, match="File read errors"):
        _validate(fixture, tmp_path)
    fixture = _fixture(tmp_path, source="sqlite", observer=True)
    result = fixture[2][0]["reads"][0]["result"]
    result.pop("entry")
    result.pop("resetRecallCutoff")
    result["error"] = {"name": "Error", "message": "failure", "code": "SQLITE_CORRUPT", "errno": 11}
    fixture[0]["result"]["reads"] = map_get_fixture_paths([result], fixture[2][0]["fixtureBase"])
    _validate(fixture, tmp_path)
    fixture[0]["result"]["reads"][0]["error"].pop("errno")
    with pytest.raises(RuntimeOracleError, match="complete original source replies"):
        _validate(fixture, tmp_path)


def test_missing_source_cannot_invent_surviving_success(tmp_path):
    fixture = _fixture(tmp_path)
    fixture[1]["input"].pop("initial")
    raw = fixture[2][0]
    raw["mutations"] = []
    raw["sourceCaptures"] = [{"filename": raw["sourceCaptures"][0]["filename"],
                              "error": {"name": "Error", "message": "missing", "code": "ENOENT"}}]
    with pytest.raises(RuntimeOracleError, match="missing physical source"):
        _validate(fixture, tmp_path)
    result = raw["reads"][0]["result"]
    result["entry"] = None
    result.pop("resetRecallCutoff")
    fixture[0]["result"]["reads"] = map_get_fixture_paths([result], raw["fixtureBase"])
    _validate(fixture, tmp_path)


def test_unknown_native_entry_metadata_must_be_preserved(tmp_path):
    fixture = _fixture(tmp_path)
    fixture[2][0]["reads"][0]["result"]["entry"]["futureNativeMetadata"] = {"field": [1, 2]}
    with pytest.raises(RuntimeOracleError, match="complete original source replies"):
        _validate(fixture, tmp_path)
    fixture[0]["result"] = map_get_fixture_paths(
        {"provider": "none", "reads": [fixture[2][0]["reads"][0]["result"]]}, fixture[2][0]["fixtureBase"])
    _validate(fixture, tmp_path)


def test_actual_writer_input_and_transformed_persisted_source_remain_distinct(tmp_path):
    fixture = _fixture(tmp_path, source="sqlite")
    # A literal duplicate identity is supplied to the genuine writer. This wire
    # fixture gives its independently observed stored result, without replaying
    # or asserting the private deduplication algorithm in the evidence guard.
    duplicate = {"type": "leaf", "id": "u1"}
    fixture[1]["input"]["initial"]["events"].append(duplicate)
    fixture[2][0]["writeCalls"][0]["request"]["events"].append(deepcopy(duplicate))
    _validate(fixture, tmp_path)
    assert len(fixture[2][0]["writeCalls"][0]["request"]["events"]) == 2
    assert len(fixture[2][0]["sourceCaptures"][0]["events"]) == 1


@pytest.mark.parametrize("mutation", [
    lambda f: f[2][0]["writeCalls"].clear(),
    lambda f: f[2][0]["writeCalls"][0]["request"]["events"].clear(),
    lambda f: f[2][0]["writeCalls"][0]["request"]["scope"].update(sessionId="other"),
    lambda f: f[2][0]["writeCalls"][0]["capture"]["events"].clear(),
    lambda f: f[2][0]["writeCalls"][0]["capture"]["entry"].update(unretainedNativeMetadata=True),
    lambda f: f[2][0]["writeCalls"][0].pop("capture"),
])
def test_literal_writer_request_and_actual_stored_source_chain_cannot_be_substituted(tmp_path, mutation):
    fixture = _fixture(tmp_path, source="sqlite")
    mutation(fixture)
    with pytest.raises(RuntimeOracleError):
        _validate(fixture, tmp_path)
