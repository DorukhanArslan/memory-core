"""Actual whole-host owners and adversarial restart evidence replays."""
from copy import deepcopy
import json

import pytest

from equivalence.host_restart_managed import build_cases as managed_cases
from equivalence.host_restart_sdk import run_host_restart
from equivalence.host_restart_session import build_cases
from equivalence.host_restart_session_evidence import validate_capture


@pytest.fixture(scope="module")
def captures(tmp_path_factory):
    root = tmp_path_factory.mktemp("real-session-managed-hosts")
    rows = []
    for case in build_cases():
        directory = root / case["id"]
        result = run_host_restart(case["input"], evidence_directory=directory)
        raw = json.loads((directory / "python-raw.json").read_text())[0]
        rows.append((case, raw, result))
    return rows


@pytest.mark.parametrize("index", range(4))
def test_actual_shared_host_session_custody(captures, index):
    case, raw, result = captures[index]
    evidence = validate_capture(case, raw, result, native=False)
    assert evidence["sharedSessionOwnerCustodyPassed"]
    assert evidence["sessionPublicationCustodyPassed"]
    assert evidence["truthfulReadinessPassed"]
    assert evidence["acceptancePointsAwarded"] == 0


@pytest.mark.parametrize("attack", [
    "separate-fresh-store", "false-owner-reuse", "aliased-owner-object", "extra-owner",
    "foreign-catalog", "eager-startup", "lost-read", "wrong-read-parent", "unpinned-read",
    "lost-journal", "scripted-flush", "foreign-session-target", "wrong-session-scope",
    "unclosed-owner", "active-close", "uncancelled-timer", "lost-postcommit",
    "future-postcommit-revision", "foreign-postcommit-generation", "changed-catalog-row",
    "invented-ready", "false-ready-status", "dropped-marker-domain", "cleared-pending-marker",
    "borrowed-marker-readback", "writer-prompt-in-reader", "invented-owner-ready", "rewritten-outcome-status",
])
def test_rejects_self_consistent_owner_queue_and_readiness_substitutions(captures, attack):
    case, original, result = captures[2]
    raw = deepcopy(original)
    producer = raw["phases"][0]["observation"]["raw"]
    reader = raw["phases"][1]["observation"]["raw"]
    acquired = producer["ownerAcquisitions"][0]
    fresh = producer["opens"][1]
    call = reader["turns"][0]["toolCalls"][0]
    after = call["managedLifecycleAfter"]
    close = reader["closeReceipts"][0]
    controller = close["after"]["sessionPublication"]
    if attack == "separate-fresh-store":
        fresh["sessionManagedOwner"]["storeId"] += 1
    elif attack == "false-owner-reuse":
        fresh["ownerReused"] = False
    elif attack == "aliased-owner-object":
        acquired["storeId"] = acquired["kitId"]
    elif attack == "extra-owner":
        producer["ownerAcquisitions"].append(deepcopy(acquired))
    elif attack == "foreign-catalog":
        acquired["paths"]["catalog"] += ".borrowed"
    elif attack == "eager-startup":
        acquired["managedLifecycleAfterConstruction"]["sessionPublication"]["notStarted"] = False
    elif attack == "lost-read":
        after["sessionReadAdmissions"] = []
        after["sessionReadAdmissionCount"] = 0
    elif attack == "wrong-read-parent":
        after["sessionReadAdmissions"][-1]["operationId"] += 1000
    elif attack == "unpinned-read":
        after["sessionReadAdmissions"][-1]["revision"] = 0
    elif attack == "lost-journal":
        controller["jobsTruncated"] = True
    elif attack == "scripted-flush":
        controller["jobs"][0]["reason"] = "explicit-flush"
    elif attack == "foreign-session-target":
        controller["pendingPaths"].append("sessions/foreign/borrowed.jsonl")
    elif attack == "wrong-session-scope":
        next(row for row in close["after"]["operations"]
             if row["name"] == "reindex-sources" and row["request"]["sources"] == ["sessions"])["request"]["sources"] = ["memory"]
    elif attack == "unclosed-owner":
        close["after"]["closed"] = False
    elif attack == "active-close":
        close["after"]["activeOperations"] = 1
    elif attack == "uncancelled-timer":
        controller["timerPending"] = True
    elif attack == "lost-postcommit":
        acquired["transcriptChanges"].pop()
    elif attack == "future-postcommit-revision":
        acquired["transcriptChanges"][-1]["catalog_revision"] += 1000
    elif attack == "foreign-postcommit-generation":
        acquired["transcriptChanges"][0]["generation"] = "borrowed-generation"
    elif attack == "changed-catalog-row":
        rows = producer["snapshots"][-1]["catalog"]["tables"]["memory_session_events"]
        row = next(row for row in rows if row["seq"] == 2)
        event = json.loads(row["event_json"])
        event["message"]["content"] = "An operator supplied this answer."
        row["event_json"] = json.dumps(event)
    elif attack == "invented-ready":
        reader["turns"][0]["outcomeReady"] = not reader["turns"][0]["outcomeReady"]
    elif attack == "false-ready-status":
        producer["turns"][0]["sessionPublicationAfterTurn"]["indexStatus"] = "ready"
    elif attack == "dropped-marker-domain":
        marker = producer["turns"][0]["lifecycleAfterTurn"]
        marker["needsIndex"] = not (marker["needsMemoryIndex"] or marker["needsSessionIndex"])
    elif attack == "cleared-pending-marker":
        marker = producer["turns"][0]["lifecycleAfterTurn"]
        marker.update(needsIndex=False, needsMemoryIndex=False, needsSessionIndex=False)
    elif attack == "borrowed-marker-readback":
        marker = producer["snapshots"][-1]["continuations"][0]["continuation"]["entry"]["sdkHostLifecycle"]
        marker["needsIndex"] = not marker["needsIndex"]
    elif attack == "writer-prompt-in-reader":
        reader["turns"][0]["modelInput"]["injectedFact"] = case["input"]["phases"][0]["savePrompt"]
    elif attack == "invented-owner-ready":
        publication = producer["turns"][0]["sessionPublicationAfterTurn"]
        publication["ready"] = not publication["ready"]
    elif attack == "rewritten-outcome-status":
        producer["turns"][0]["outcome"]["publication"]["indexStatus"] = "ready"
    for child in raw["phases"]:
        child["stdout"] = json.dumps(child["observation"], ensure_ascii=False)
    with pytest.raises(ValueError):
        validate_capture(case, raw, result, native=False)


def test_historical_managed_literal_cannot_borrow_acceptance_validator(captures):
    _, raw, result = captures[0]
    with pytest.raises(ValueError, match="independently frozen"):
        validate_capture(managed_cases()[0], raw, result, native=False)


def test_new_literal_cannot_borrow_historical_managed_validator(captures):
    from equivalence.host_restart_managed_evidence import validate_capture as historical_validator

    case, raw, result = captures[0]
    with pytest.raises(ValueError):
        historical_validator(case, raw, result, native=False)
