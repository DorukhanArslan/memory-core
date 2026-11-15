"""Recompute the three forget outcomes from retained complete physical evidence.

Only the SDK's exact, empty coordination file is private storage. Original
packets, byte records, SQL tables and reports are never rewritten.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath

from equivalence.forget_lineage_evidence import (
    _bytes, physical_snapshot, validate_native, validate_sdk,
)
from equivalence.forget_lineage_outcomes import validate_case
from equivalence.forget_lineage_profile import canonical

GUARD = "memory/.dreams/short-term-promotion.lock.guard"
STATE_FILES = {
    "memory/.dreams/short-term-recall.json", "memory/.dreams/phase-signals.json",
    "memory/.dreams/consolidation-preimages.json", "memory/.dreams/session-ingestion.json",
}
ORIGIN_FIELDS = {
    "entry_key": "entryKey", "agent_id": "agentId", "session_id": "sessionId",
    "session_key": "sessionKey", "origin_class": "originClass", "observed_at": "observedAt",
}
TOMBSTONE_FIELDS = {
    "session_id": "sessionId", "agent_id": "agentId", "reason": "reason", "created_at": "createdAt",
}


def _require(value, message):
    if not value:
        raise ValueError("forget outcome " + message)


def _equal(left, right, message):
    _require(canonical(left) == canonical(right), message)


def _relative(value):
    _require(isinstance(value, str) and value and "\\" not in value, "invalid owned relative path")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and ".." not in path.parts and path.as_posix() == value,
             "noncanonical owned relative path")
    return value


def _files(snapshot):
    _require(isinstance(snapshot, dict) and isinstance(snapshot.get("files"), dict)
             and isinstance(snapshot.get("databases"), dict), "incomplete physical tree")
    return {_relative(name): _bytes(record) for name, record in snapshot["files"].items()}


def _tables(snapshot, files):
    databases = snapshot["databases"]
    actual = {name for name, value in files.items() if value.startswith(b"SQLite format 3\x00")}
    _require(set(databases) == actual, "physical SQLite files and complete SQL captures disagree")
    for name, database in databases.items():
        _relative(name)
        schema, tables = database["schema"], database["tables"]
        _require(isinstance(schema, list) and isinstance(tables, dict), "incomplete SQLite capture")
        names = [row["name"] for row in schema if row["type"] == "table"]
        _require(len(names) == len(set(names)) and set(names) == set(tables), "SQLite schema lost a table")
        _require(all(isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
                     for rows in tables.values()), "invalid complete SQLite rows")
    return databases


def _rows(database, table, fields, agent):
    rows = database["tables"].get(table, [])
    _require(all(set(row) == set(fields) and row["agent_id"] == agent for row in rows),
             "origin or tombstone row lost a field or its agent scope")
    return [{target: row[source] for source, target in fields.items()} for row in rows]


def _empty_state(now):
    iso = datetime.fromtimestamp(now / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {"recall": {"version": 1, "updatedAt": iso, "entries": {}},
            "phase": {"version": 1, "updatedAt": iso, "entries": {}},
            "preimages": [], "ingestion": {"version": 3, "files": {}, "seenMessages": {}}}


def _state(case, raw, physical, observed, *, native, guard_present):
    _require(set(observed) == {"files", "recall", "phase", "preimages", "ingestion", "origins", "tombstones"},
             "the complete owner-state interface changed")
    if native:
        fixture, state = physical["fixture"], physical["state"]
        _equal(fixture["root"], raw["fixtureBase"], "Native physical fixture identity changed")
        _equal(state["root"], raw["stateDirectory"], "Native durable-state identity changed")
        _equal(_bytes(physical["config"]).decode("utf8").strip(),
               json.dumps(raw["config"], separators=(",", ":")), "Native complete config bytes changed")
        files, state_files = _files(fixture), _files(state)
        _tables(fixture, files)
        databases = _tables(state, state_files)
        _require("state/openclaw.sqlite" in databases, "Native plugin-state database is absent")
        plugin = databases["state/openclaw.sqlite"]["tables"]
        _require("plugin_state_entries" in plugin and plugin["plugin_state_entries"] == [],
                 "the first-three outcome scope acquired nonempty Native plugin state")
        database_path = "agents/main/agent/openclaw-agent.sqlite"
    else:
        _equal(physical["root"], raw["fixtureRoot"], "SDK physical fixture identity changed")
        files = _files(physical)
        databases = _tables(physical, files)
        database_path = "agents/main/memory.sqlite"
    _require(database_path in databases, "the actual origin/tombstone owner database is absent")
    workspace = {name.removeprefix("workspace/"): value for name, value in files.items()
                 if name.startswith("workspace/")}
    _require(not (STATE_FILES & workspace.keys()),
             "the first-three outcome scope acquired an unrepresented physical logical-state file")
    if native:
        _require(GUARD not in workspace, "Native unexpectedly acquired the SDK private guard")
    else:
        _require((GUARD in workspace) is guard_present, "the SDK private guard is missing or appears before commit")
        if guard_present:
            _require(workspace[GUARD] == b"", "the SDK private guard contains data")
    _equal(observed["files"], {name: payload.decode("utf8") for name, payload in workspace.items()},
           "whole public workspace files differ from actual physical bytes")
    expected = _empty_state(case["input"]["nowMs"])
    for key, value in expected.items():
        _equal(observed[key], value, "complete logical " + key + " differs from its empty physical owner")
    database = databases[database_path]
    origins = sorted(_rows(database, "memory_entry_origins", ORIGIN_FIELDS, "main"),
                     key=lambda row: (row["entryKey"], row["sessionId"]))
    tombstones = sorted(_rows(database, "memory_session_tombstones", TOMBSTONE_FIELDS, "main"),
                        key=lambda row: row["sessionId"])
    _equal(observed["origins"], {"main": origins}, "complete origins differ from actual SQL rows")
    _equal(observed["tombstones"], {"main": tombstones}, "complete tombstones differ from actual SQL rows")
    for name, other in databases.items():
        if name != database_path:
            _require(not other["tables"].get("memory_entry_origins", [])
                     and not other["tables"].get("memory_session_tombstones", []),
                     "lineage state was displaced into another database")


def _sdk_physical(raw, directory):
    captures = []
    for reference in raw["physical"]:
        path = Path(reference["path"])
        _require(path.is_absolute() and not path.is_symlink()
                 and path.resolve().is_relative_to(directory), "SDK capture escaped its exact directory")
        data = path.read_bytes()
        _equal(hashlib.sha256(data).hexdigest(), reference["sha256"], "SDK physical capture changed")
        captures.append(json.loads(data))
    return captures


def validate_pair(case, native_raw, sdk_raw, native_public, sdk_public, sdk_directory):
    """Return two complete packets with only the declared private guard projected."""
    validate_case(case)
    _require(isinstance(native_raw, dict) and isinstance(sdk_raw, dict), "each side needs its sole actual raw record")
    directory = Path(sdk_directory).resolve()
    _require(not (directory / "python-raw.json").is_symlink(), "SDK raw file is a symlink")
    _equal(json.loads((directory / "python-raw.json").read_text()), sdk_raw, "SDK supplied raw differs from disk")
    _equal(sdk_raw["fixtureRoot"], str(directory / "sdk-fixture"), "SDK raw fixture is from another run")
    _equal(native_raw["workspace"], str(Path(native_raw["fixtureBase"]) / "workspace"), "Native workspace changed")
    validate_native(case, native_public, [native_raw], Path(native_raw["fixtureBase"]).parent)
    validate_sdk(case, sdk_public, directory)
    for public in (native_public, sdk_public):
        _require(set(public) == {"kind", "provider", "acceptancePointsAwarded", "observations"}
                 and public["kind"] == "forget-lineage-tombstones" and public["provider"] == "none"
                 and type(public["acceptancePointsAwarded"]) is int and public["acceptancePointsAwarded"] == 0,
                 "the full original packet or zero-credit producer interface changed")
    for raw in (native_raw, sdk_raw):
        _equal(raw["input"], case["input"], "raw lost the exact common input")
        _require(len(raw["physical"]) == 4 and len(raw["operations"]) == 3, "an initial or operation capture is absent")
    native_physical = [physical_snapshot(value) for value in native_raw["physical"]]
    sdk_physical = _sdk_physical(sdk_raw, directory)
    for raw, public, captures, native in ((native_raw, native_public, native_physical, True),
                                         (sdk_raw, sdk_public, sdk_physical, False)):
        _require(len(public["observations"]) == 3, "a complete outcome observation is absent")
        _state(case, raw, captures[0], raw["initialState"], native=native, guard_present=False)
        _equal(raw["initialState"]["files"], case["input"]["files"], "initial actual files differ from literal facts")
        seeded = sorted(case["input"]["origins"], key=lambda row: (row["entryKey"], row["sessionId"]))
        _equal(raw["initialState"]["origins"], {"main": seeded}, "actual initial origins differ from literal facts")
        _equal(raw["initialState"]["tombstones"], {"main": []}, "a tombstone was supplied before actual forget")
        for index, (request, actual, observed) in enumerate(zip(case["input"]["operations"], raw["operations"],
                                                                public["observations"], strict=True)):
            _equal(request, actual["operation"], "actual operation changed")
            _equal(observed, actual["observed"], "whole public observation differs from original raw")
            _require(set(observed) == {"operation", "error", "report", "replay", "state"}
                     and observed["error"] is None and observed["replay"] is None
                     and isinstance(observed["report"], dict), "the required complete forget flow did not succeed")
            _equal(observed["operation"], request, "public operation differs from the driven request")
            _require(observed["report"].get("dryRun") is (index == 0), "preview/commit identity changed")
            if native:
                _equal(actual["returnValue"], {"type": "undefined"}, "actual CLI return changed")
                _equal(json.loads(_bytes(actual["stdout"])), observed["report"], "whole CLI JSON report changed")
            _state(case, raw, captures[index + 1], observed["state"], native=native, guard_present=index > 0)
        _equal(public["observations"][0]["state"], raw["initialState"], "preview changed durable content or lineage")
        _equal(public["observations"][1]["state"], public["observations"][2]["state"], "repeat changed durable content or lineage")
    projected_native, projected_sdk = deepcopy(native_public), deepcopy(sdk_public)
    for observed in projected_sdk["observations"][1:]:
        _require(observed["state"]["files"].pop(GUARD) == "", "private guard projection lost its actual empty bytes")
    return projected_native, projected_sdk
