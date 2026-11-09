"""Real SDK producer rebuilds and adversarial notification/SQLite custody guards."""
from copy import deepcopy
import json

import pytest

from equivalence.host_restart_publication import build_cases
from equivalence.host_restart_publication_evidence import validate_capture, _validate_native_notifications
from equivalence.host_restart_sdk import run_host_restart


@pytest.fixture(scope="module")
def captures(tmp_path_factory):
    root = tmp_path_factory.mktemp("actual-producer-publication")
    rows = []
    for case in build_cases():
        directory = root / case["id"]
        result = run_host_restart(case["input"], evidence_directory=directory)
        raw = json.loads((directory / "python-raw.json").read_text())[0]
        rows.append((case, raw, result))
    return rows


@pytest.mark.parametrize("index", range(4))
def test_actual_producer_rebuild_publishes_physical_timestamp(captures, index):
    case, raw, result = captures[index]
    assert validate_capture(case, raw, result, native=False)["producerForcePublicationPassed"]
    for phase in result["phases"]:
        for read in phase["reads"]:
            if read["search"]["results"]:
                assert read["search"]["results"][0]["provenance"]["observedAt"] == case["input"]["policy"]["sourceMtimeMs"]


@pytest.mark.parametrize("attack", ["missing-force", "force-false", "fake-revision", "fake-count", "source-replaced", "reader-force"])
def test_rejects_altered_producer_publication_receipts(captures, attack):
    case, original, result = captures[0]
    raw = deepcopy(original)
    writer = raw["phases"][0]["observation"]["raw"]["turns"][0]
    publication = writer["producerPublication"]
    if attack == "missing-force":
        del writer["producerPublication"]
    elif attack == "force-false":
        publication["request"]["force"] = False
    elif attack == "fake-revision":
        publication["publishedAfter"]["revision"] = publication["publishedBefore"]["revision"]
    elif attack == "fake-count":
        publication["returned"] += 1
    elif attack == "source-replaced":
        publication["sourceAfter"]["stat"]["ino"] += 1
    elif attack == "reader-force":
        raw["phases"][1]["observation"]["raw"]["turns"][0]["producerPublication"] = publication
    for child in raw["phases"]:
        child["stdout"] = json.dumps(child["observation"], ensure_ascii=False)
    with pytest.raises(ValueError):
        validate_capture(case, raw, result, native=False)


def _guard_example():
    # Structural guard inputs alone never count as authenticated execution.
    scope = {"agentId": "main", "sessionId": "one", "sessionKey": "agent:main:one", "storePath": "/owned/state/agents/main/sessions/sessions.json"}
    message = {"role": "user", "content": "An actual event body."}
    event = {"type": "message", "id": "m1", "message": message}
    commit = {"appended": True, "messageId": "m1", "message": message,
              "anchor": {**scope, "storePath": "/owned/state/agents/main/agent/openclaw-agent.sqlite", "rawSeq": 1, "entryId": "m1"}}
    entry = {"scope": scope, "method": "appendSessionTranscriptMessageByIdentityStrict",
        "params": {**scope, "message": message, "eventId": "m1", "config": {}, "updateMode": "inline"},
        "event": {"type": "message_end", "message": message}, "result": {"kind": "result", "result": commit},
        "versionBefore": 0, "versionAfter": 1, "updateOffsetBefore": 0, "updateOffsetAfter": 1}
    return {"config": {}, "sessions": [{"persistence": [entry]}],
        "transcriptUpdates": [{"version": 1, "update": {"target": scope, "messageSeq": 1, "messageId": "m1", "message": message}}],
        "transcriptUpdateVersions": {"beforeRegistration": 0, "afterClose": 1},
        "snapshots": [{"memory": [{"agentId": "main", "sql": {"tables": [
            {"name": "transcript_events", "rows": [{"session_id": "one", "seq": 1, "event_json": json.dumps(event)}]},
            {"name": "transcript_event_identities", "rows": [{"session_id": "one", "seq": 1, "event_id": "m1"}]}]}}],
            "transcript": [{"scope": scope, "events": [event]}]}]}


def test_notification_guard_checks_a_committed_sqlite_readback():
    _validate_native_notifications(_guard_example(), "/owned")


@pytest.mark.parametrize("attack", ["duplicate-version", "skipped-offset", "wrong-sequence", "wrong-owner", "forged-message", "missing-sql", "wrong-sql-id", "missing-readback"])
def test_notification_guard_rejects_self_consistent_transport_forgery(attack):
    phase = deepcopy(_guard_example())
    entry = phase["sessions"][0]["persistence"][0]
    update = phase["transcriptUpdates"][0]
    snapshot = phase["snapshots"][0]
    if attack == "duplicate-version":
        duplicate = deepcopy(entry)
        duplicate.update(updateOffsetBefore=1, updateOffsetAfter=2)
        phase["sessions"][0]["persistence"].append(duplicate)
        phase["transcriptUpdates"].append(deepcopy(update))
        phase["transcriptUpdateVersions"]["afterClose"] = 2
    elif attack == "skipped-offset":
        entry.update(updateOffsetBefore=2, updateOffsetAfter=3)
    elif attack == "wrong-sequence":
        update["update"]["messageSeq"] = 2
    elif attack == "wrong-owner":
        update["update"]["target"] = {**update["update"]["target"], "sessionId": "another"}
    elif attack == "forged-message":
        message = {"role": "user", "content": "A forged event."}
        update["update"]["message"] = message
        entry["result"]["result"]["message"] = message
    elif attack == "missing-sql":
        snapshot["memory"][0]["sql"]["tables"][0]["rows"] = []
    elif attack == "wrong-sql-id":
        snapshot["memory"][0]["sql"]["tables"][1]["rows"][0]["event_id"] = "other"
    elif attack == "missing-readback":
        snapshot["transcript"][0]["events"] = []
    with pytest.raises(ValueError):
        _validate_native_notifications(phase, "/owned")
