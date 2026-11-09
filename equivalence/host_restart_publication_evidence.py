"""Genuine producer rebuild and committed transcript publication custody."""
import json
from pathlib import Path

from equivalence.host_restart_evidence import require
from equivalence.host_restart_policy_evidence import _validate_policy_capture
from equivalence.promotion_apply_family import differences


def _validate_native_notifications(phase, fixture_base):
    updates = phase["transcriptUpdates"]
    persistence = [entry for session in phase["sessions"] for entry in session["persistence"]]
    require(len(updates) == len(persistence) and updates, "Actual committed transcript updates were lost")
    versions = phase["transcriptUpdateVersions"]
    require(versions["afterClose"] - versions["beforeRegistration"] == len(updates), "Transcript update version custody changed")
    for index, (entry, observed) in enumerate(zip(persistence, updates)):
        require(entry["method"] == "appendSessionTranscriptMessageByIdentityStrict", "The host bypassed its original commit/publication owner")
        commit, params = entry["result"]["result"], entry["params"]
        require(entry["event"]["type"] == "message_end" and params["message"] == entry["event"]["message"]
                and params["updateMode"] == "inline" and params["config"] == phase["config"], "The genuine persisted event or publication mode changed")
        require(observed["version"] == entry["versionAfter"] == entry["versionBefore"] + 1
                and observed["version"] == versions["beforeRegistration"] + index + 1
                and entry["updateOffsetBefore"] == index and entry["updateOffsetAfter"] == index + 1,
                "Publication versions/offsets did not follow exactly one consecutive real commit")
        update, anchor, scope = observed["update"], commit["anchor"], entry["scope"]
        require(update["target"] == scope and all(anchor[key] == scope[key] == params[key] for key in ("agentId", "sessionId", "sessionKey")),
                "The committed anchor and normalized update have different owners")
        require(update["messageId"] == commit["messageId"] == params["eventId"]
                and update["messageSeq"] == anchor["rawSeq"] and update["message"] == commit["message"],
                "The normalized notification did not come from its actual committed message sequence")
        physical = Path(fixture_base) / "state/agents" / scope["agentId"] / "agent/openclaw-agent.sqlite"
        require(Path(anchor["storePath"]) == physical, "The commit borrowed a different physical transcript database")
        snapshot = phase["snapshots"][-1]
        owner = next(item for item in snapshot["memory"] if item["agentId"] == scope["agentId"])
        tables = {table["name"]: table["rows"] for table in owner["sql"]["tables"]}
        rows = [row for row in tables["transcript_events"] if row["session_id"] == scope["sessionId"] and row["seq"] == anchor["rawSeq"]]
        identities = [row for row in tables["transcript_event_identities"] if row["session_id"] == scope["sessionId"] and row["seq"] == anchor["rawSeq"]]
        require(len(rows) == len(identities) == 1, "The committed notification lost its actual persisted SQLite row")
        persisted = json.loads(rows[0]["event_json"])
        require(persisted["type"] == "message" and persisted["id"] == identities[0]["event_id"] == anchor["entryId"] == commit["messageId"]
                and persisted["message"] == commit["message"], "The actual persisted transcript differs from its committed anchor or notification")
        transcript = next(item for item in snapshot["transcript"] if item["scope"] == scope)
        require(sum(event == persisted for event in transcript["events"]) == 1, "Original transcript readback did not return the actual committed event")


def _validate_publication_capture(case, raw, result, *, native, managed=False, session_managed=False):
    base = _validate_policy_capture(case, raw, result, native=native, publication=True, managed=managed,
                                    session_managed=session_managed)
    value = case["input"]
    require(value["policy"]["producerPublication"] == {"operation": "force-rebuild-after-source-metadata"},
            "The producer publication stage is not the frozen actual rebuild")
    phases = raw["children"] if native else raw["phases"]
    for ordinal, record in enumerate(phases):
        phase = record["output" if native else "observation"]["raw"]
        if native:
            _validate_native_notifications(phase, raw["fixtureBase"])
            syncs = [item for item in phase["maintenance"] if item["operation"] == "sync"]
            if ordinal == 0:
                require(len(syncs) == 1 and syncs[0]["request"] == {"reason": "host-restart-producer-publication", "force": True}
                        and syncs[0]["returnedUndefined"], "Missing actual original producer force publication")
                require(syncs[0]["status"]["custom"]["indexIdentity"]["status"] == "valid", "The original force publication did not establish an owned index")
            else:
                require(syncs == [], "The restarted host performed an undeclared controller repair")
        else:
            publications = [turn["producerPublication"] for turn in phase["turns"] if "producerPublication" in turn]
            if ordinal == 0:
                require(len(publications) == 1, "The producer did not retain exactly one real forced publication")
                publication = publications[0]
                require(publication["request"] == {"force": True}
                        and type(publication["returned"]) is int
                        and publication["returned"] == len(publication["publishedAfter"]["sources"]), "The actual SDK force return is not bound to published sources")
                require(publication["publishedAfter"]["revision"] == publication["publishedBefore"]["revision"] + 1,
                        "The SDK force stage did not publish a real subsequent revision")
                before, after = publication["sourceBefore"], publication["sourceAfter"]
                require(before["source"] == after["source"] and all(before["stat"][key] == after["stat"][key] for key in ("dev", "ino", "mode", "nlink", "size", "mtimeNs")),
                        "The force rebuild replaced or retimed its produced source")
            else:
                require(publications == [], "The restarted SDK controller performed an undeclared force rebuild")
        public = record["output" if native else "observation"]["result"]
        for read in public["reads"]:
            if read["session"] != "isolated":
                require(read["search"]["results"][0]["provenance"]["observedAt"] == value["policy"]["sourceMtimeMs"],
                        "The genuine producer rebuild did not publish the declared physical source timestamp")
    return {**base, "producerForcePublicationPassed": True,
            "committedTranscriptNotificationsPassed": True if native else None}


def validate_capture(case, raw, result, *, native):
    return _validate_publication_capture(case, raw, result, native=native)


def replay_case(case, directory):
    directory = Path(directory)
    native = json.loads((directory / "evidence/native-raw.json").read_text())[0]
    sdk = json.loads((directory / "evidence/python-raw.json").read_text())[0]
    original = json.loads((directory / "stdout.json").read_text())["result"]
    implementation = json.loads((directory / "sdk-output.json").read_text())
    return {"native": validate_capture(case, native, original, native=True),
            "sdk": validate_capture(case, sdk, implementation, native=False),
            "structuralCustodyPassed": True, "differences": differences(original, implementation),
            "acceptancePointsAwarded": 0}
