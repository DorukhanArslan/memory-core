"""Bind the closed replay-admission family to complete retained owner evidence.

Only the exact empty SDK coordination guard is projected. Native undefined and
SDK None remain distinct raw returns for the declared optional admission reason.
"""
from copy import deepcopy
import json
from pathlib import Path

from equivalence.forget_boundaries import validate_case
from equivalence.forget_lineage_evidence import _bytes, physical_snapshot, validate_native, validate_sdk
from equivalence.forget_lineage_outcomes_evidence import GUARD, _equal, _require, _sdk_physical, _state


def _catalog(case, physical, native):
    databases = physical["state"]["databases"] if native else physical["databases"]
    path = "agents/main/agent/openclaw-agent.sqlite" if native else "agents/main/sessions/catalog.sqlite"
    _require(path in databases, "replay source catalog is absent")
    tables = databases[path]["tables"]
    names = ("session_windows", "session_nodes", "transcript_events") if native else (
        "memory_session_windows", "memory_session_nodes", "memory_session_events")
    _require(all(name in tables for name in names), "replay source catalog lost an actual table")
    expected = sorted((row["sessionId"], row["sessionKey"]) for row in case["input"]["sessions"])
    _equal(sorted((row["session_id"], row["session_key"]) for row in tables[names[0]]), expected,
           "retained source catalog identities differ from the literal sessions")
    _equal(sorted({row["session_id"] for row in tables[names[2]]}), ["A", "B"],
           "both actual source transcripts must remain present")
    if not native:
        _require(all(row["agent"] == "main" for name in names for row in tables[name]),
                 "SDK source catalog escaped its main-agent scope")
    return {name: tables[name] for name in names}


def _admission(case, raw, actual, observed, native, committed, catalog):
    rows = actual["admission"]
    _require(isinstance(rows, list) and len(rows) == 2, "actual A/B admission calls are incomplete")
    decisions = []
    for session, row in zip(case["input"]["sessions"], rows, strict=True):
        identifier, key = session["sessionId"], session["sessionKey"]
        reason = "forgotten" if committed and identifier == "A" else None
        origin = {"agentId": "main", "sessionId": identifier, "sessionKey": key}
        options = {"sessionKind": "interactive", "agentId": "main", "sessionId": identifier,
                   "sessionKey": key, "updatedAtMs": case["input"]["nowMs"]}
        scope = "main:sessions/main/" + identifier
        if native:
            _require(set(row) == {"entry", "source", "arguments", "returnValue"},
                     "the complete Native admission call carrier changed")
            entry = row["entry"]
            for field, value in {"agentId": "main", "sessionId": identifier, "sessionKey": key,
                                 "sessionFile": key, "artifactKind": "active-session",
                                 "transcriptSource": "sqlite", "sessionKind": "interactive",
                                 "updatedAtMs": case["input"]["nowMs"]}.items():
                _equal(entry[field], value, "actual Native corpus identity changed: " + field)
            store = Path(entry["storePath"])
            _require(store.is_absolute() and store.parent == Path(raw["stateDirectory"]) / "agents/main/sessions",
                     "Native source store escaped its actual main-agent state")
            _require(not entry.get("generatedByDreamingNarrative") and not entry.get("generatedByCronRun"),
                     "the interactive source acquired another exclusion")
            options["storePath"] = entry["storePath"]
            source = {"agentId": "main", "absolutePath": key, "foreign": False,
                      "sessionPath": "sessions/main/" + identifier, "stateKey": scope, "scope": scope,
                      "sessionOrigin": origin, "legacyScope": "main:" + identifier, "buildOptions": options}
            _equal(row["arguments"], [source], "Native admission did not receive only its actual source")
            returned = {"type": "string", "value": reason} if reason else {"type": "undefined"}
        else:
            _require(set(row) == {"source", "returnValue"}, "the complete SDK admission call carrier changed")
            window = next(row for row in catalog["memory_session_windows"] if row["session_id"] == identifier)
            options["updatedAtMs"] = window["transcript_updated_at"]
            source = {"agent_id": "main", "absolute_path": str(Path(raw["fixtureRoot"]) /
                      "agents/main/sessions" / (identifier + ".jsonl")), "foreign": False,
                      "session_path": "sessions/main/" + identifier, "state_key": scope, "scope": scope,
                      "session_origin": origin, "legacy_scope": "main:" + identifier, "build_options": options}
            returned = reason
        _equal(row["source"], source, "whole actual admission source differs from its retained catalog identity")
        _equal(row["returnValue"], returned, "actual optional admission return differs from the durable tombstone")
        decisions.append({"agentId": "main", "sessionId": identifier, "reason": reason})
    _equal(observed["replay"], {"admission": decisions}, "whole public admission differs from actual A/B returns")


def validate_pair(case, native_raw, sdk_raw, native_public, sdk_public, sdk_directory):
    """Return complete packets with only the independently checked guard projected."""
    validate_case(case)
    _require(isinstance(native_raw, dict) and isinstance(sdk_raw, dict), "each side needs its sole actual raw record")
    directory = Path(sdk_directory).resolve()
    _require(not (directory / "python-raw.json").is_symlink(), "SDK raw file is a symlink")
    _equal(json.loads((directory / "python-raw.json").read_text()), sdk_raw, "SDK supplied raw differs from disk")
    _equal(sdk_raw["fixtureRoot"], str(directory / "sdk-fixture"), "SDK raw fixture is from another run")
    _equal(native_raw["workspace"], str(Path(native_raw["fixtureBase"]) / "workspace"), "Native workspace changed")
    validate_native(case, native_public, [native_raw], Path(native_raw["fixtureBase"]).parent)
    validate_sdk(case, sdk_public, directory)
    captures = ([physical_snapshot(row) for row in native_raw["physical"]], _sdk_physical(sdk_raw, directory))
    for raw, public, physical, native in ((native_raw, native_public, captures[0], True),
                                         (sdk_raw, sdk_public, captures[1], False)):
        _require(set(public) == {"kind", "provider", "acceptancePointsAwarded", "observations"}
                 and public["kind"] == "forget-lineage-tombstones" and public["provider"] == "none"
                 and type(public["acceptancePointsAwarded"]) is int and public["acceptancePointsAwarded"] == 0,
                 "the whole original zero-credit producer packet changed")
        _equal(raw["input"], case["input"], "raw lost the exact common input")
        _require(len(physical) == 10 and len(raw["operations"]) == len(public["observations"]) == 9,
                 "an initial or operation capture is absent")
        _state(case, raw, physical[0], raw["initialState"], native=native, guard_present=False)
        _equal(raw["initialState"]["files"], case["input"]["files"], "initial files differ from literal facts")
        _equal(raw["initialState"]["origins"], {"main": sorted(case["input"]["origins"],
               key=lambda row: (row["entryKey"], row["sessionId"]))}, "initial lineage differs from literal facts")
        _equal(raw["initialState"]["tombstones"], {"main": []}, "a tombstone was supplied before actual forget")
        catalog = _catalog(case, physical[0], native)
        previous = raw["initialState"]
        for index, (request, actual, observed) in enumerate(zip(case["input"]["operations"], raw["operations"],
                                                                public["observations"], strict=True)):
            _equal(actual["operation"], request, "actual operation changed")
            _equal(actual["observed"], observed, "whole public observation differs from original raw")
            _require(set(observed) == {"operation", "error", "report", "replay", "state"}
                     and observed["error"] is None, "a required complete operation failed")
            _equal(observed["operation"], request, "public operation differs from the driven request")
            _state(case, raw, physical[index + 1], observed["state"], native=native, guard_present=index >= 3)
            _equal(_catalog(case, physical[index + 1], native), catalog, "forget/replay changed retained source catalogs")
            if request["op"] == "admission":
                _require(observed["report"] is None, "admission acquired a forget report")
                _admission(case, raw, actual, observed, native, index >= 3, catalog)
            elif request["op"] == "forget":
                _require(observed["replay"] is None and isinstance(observed["report"], dict),
                         "the complete forget report is absent")
                _require(observed["report"].get("dryRun") is (index == 1), "preview/commit identity changed")
                if native:
                    _equal(actual["returnValue"], {"type": "undefined"}, "actual CLI return changed")
                    _equal(json.loads(_bytes(actual["stdout"])), observed["report"], "whole CLI JSON report changed")
            else:
                _require(request["op"] == "reopen" and observed["report"] is None and observed["replay"] is None,
                         "reopen acquired an invented result")
            if index != 3:
                _equal(observed["state"], previous, "admission, preview, reopen or repeat changed durable memory")
            previous = observed["state"]
        committed = public["observations"][3]["state"]
        _equal(committed["origins"], {"main": [row for row in case["input"]["origins"]
               if row["entryKey"] == "note-b"]}, "committed lineage did not retain only independent B")
        _equal(committed["tombstones"], {"main": [{"sessionId": "A", "agentId": "main", "reason": "forgotten",
               "createdAt": case["input"]["nowMs"]}]}, "actual forget did not persist the exact A tombstone")
        memory, daily = committed["files"]["MEMORY.md"], committed["files"]["memory/2026-11-10.md"]
        _require("note-a" not in memory and "note-ab" not in memory and "shared-ab" not in memory
                 and "Only meeting B." in memory and "A private direct section." not in daily
                 and "Keep B's separate section." in daily, "A deletion or independent B retention is unproved")
    calls = [row for row in native_raw["calls"] if row["operation"] == "listSessionTranscriptCorpusEntriesForAgent"]
    _require(len(calls) == 4, "actual Native corpus enumeration is incomplete")
    for call, index in zip(calls, (0, 2, 5, 8), strict=True):
        _equal(call["arguments"], ["main", {"includeRetainedSqlite": True}], "actual corpus request changed")
        _equal(call["returnValue"], {"type": "object", "value": [row["entry"] for row in
               native_raw["operations"][index]["admission"]]}, "admission sources differ from the actual corpus return")
    projected_native, projected_sdk = deepcopy(native_public), deepcopy(sdk_public)
    for observed in projected_sdk["observations"][3:]:
        _require(observed["state"]["files"].pop(GUARD) == "", "guard projection lost its actual empty bytes")
    return projected_native, projected_sdk
