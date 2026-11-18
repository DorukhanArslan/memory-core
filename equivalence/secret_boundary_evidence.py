"""Reopen the SDK subprocess output and saved session used by the redaction boundary callers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

from equivalence import secret_boundary_inputs as family


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _members(rows):
    return [r for r in rows if r.get("id") in {family.WHOLE_ID, family.CHUNKED_ID, family.SESSION_ID, family.ERROR_ID}
            or family.POINTS[0] in r.get("covers", ())]


def validate_registration(definitions):
    members = _members(definitions)
    if members and family.canonical(members) != family.canonical(family.build_cases()):
        raise ValueError("The four declared secret boundary callers must run together and in order")


def family_complete(rows):
    members = _members(rows)
    expected = family.build_cases()
    return len(members) == len(expected) and all(
        all(family.canonical(row.get(k)) == family.canonical(v) for k, v in case.items())
        and row.get("status") == "matched" and row.get("secretBoundaryEvidenceValidated") is True
        for row, case in zip(members, expected, strict=True))


def _read_child(record, request, coordinator):
    wire = record["requestJson"].encode()
    _require(record["request"] == json.loads(wire) == request
             and hashlib.sha256(wire).hexdigest() == record["requestSha256"], "SDK caller request changed")
    # The memory tools' child records subprocess.returncode directly. The
    # redaction and session children also store a separate signal field.
    expected_exit = {"code": 0, "signal": None} if "operation" in request else {"code": 0}
    _require(record["exit"] == expected_exit, "SDK child did not complete")
    if "operation" in request:
        _require(int(record["finishedAtNs"]) > int(record["startedAtNs"]), "SDK child timestamps disagree")
    packet = json.loads(record["stdout"])
    raw = packet["raw"]
    _require(type(record["pid"]) is int and raw["pid"] == record["pid"] and raw["ppid"] == coordinator,
             "The actual SDK child process identity changed")
    _require(record.get("raw", raw) == raw and record.get("observation", packet) == packet,
             "SDK process bytes differ from the recorded observation")
    return packet["result"], raw


def _read_catalog(path):
    _require(path.is_file() and not path.is_symlink(), "SDK session catalog is missing")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {name: [dict(r) for r in db.execute('SELECT * FROM "' + name.replace('"', '""') + '"')]
                for name in names}


def _session(case, packet, directory):
    inputs = case["input"]
    public, diagnostics, pids = [], [], set()
    common = {k: v for k, v in inputs.items() if k not in {"phases", "kind"}}
    for record, phase in zip(packet["phases"], inputs["phases"], strict=True):
        identity = {k: common[k] for k in ("nowMs", "agentId", "sessionId", "sessionKey")}
        request = {"operation": case["operation"], "phase": phase, "directory": packet["fixtureBase"],
                   "input": identity if phase["label"] == "verify" else common}
        result, raw = _read_child(record, request, packet["coordinatorPid"])
        _require(raw["output"] == result and result["phase"] == phase["label"], "SDK session output changed")
        public.append(result)
        diagnostics.append(raw)
        pids.add(raw["pid"])
    catalog = directory / "session/session-catalog.sqlite"
    _require(len(pids) == len(public) == 3 and Path(packet["fixtureBase"]).parent.name == directory.name
             and all(Path(r["storePaths"]["databasePath"]) == Path(packet["fixtureBase"]) / catalog.name
                     for r in diagnostics), "The three SDK processes did not reopen the same catalog")
    last = diagnostics[-1]
    _require(_read_catalog(catalog) == last["afterSql"] == last["beforeSql"] == diagnostics[1]["afterSql"]
             and public[-1]["storedMessages"] == public[1]["storedMessages"],
             "Committed rows differ after the identity-only SDK restart")
    effects = [s["stage"] for s in diagnostics[0]["stages"]]
    _require(effects == ["before-live-listeners", "after-live-listeners", "first-persistence-cap",
                         "before-message-write-policy", "final-persistence-cap", "committed-message",
                         "after-write-settlement"], "The model/listener/storage order changed")
    return {"provider": "none", "phases": public}, {
        "processes": len(pids), "writeStages": effects, "verifiedStoredMessages": len(public[-1]["storedMessages"])}


def replay_sdk(case, packet, directory):
    """Return the public value reconstructed from the original SDK child stdout and durable data."""
    op, inputs = case["operation"], case["input"]
    if case["id"] == family.SESSION_ID:
        return _session(case, packet, directory)
    if case["id"] == family.ERROR_ID:
        request = {"input": inputs, "directory": str(Path(packet["fixtureBase"]) / "fixture")}
        result, raw = _read_child(packet["child"], request, packet["coordinatorPid"])
        _require(raw["input"] == inputs and len(raw["requests"]) == len(raw["invocations"]) == 2
                 and [t["name"] for t in result["tools"]] == ["get", "search"],
                 "SDK error profile did not dispatch both real tools")
        _require(all(v not in json.dumps(result) for v in inputs["registeredSecrets"]),
                 "A synthetic registered literal reached the public SDK error result")
        return result, {"toolInvocations": len(raw["requests"])}
    _require(len(packet["children"]) == 1, "The SDK source caller must run in a fresh child")
    result, raw = _read_child(packet["children"][0], {"operation": op, "input": inputs}, packet["coordinatorPid"])
    fields = ("explicitSensitiveText", "toolText", "modelText")
    crossing = case["id"] == family.CHUNKED_ID
    _require(raw["output"] == result and all(("BOUNDARY-1234" in result["result"][name]) is crossing
             and "BOUNDARY-9876" not in result["result"][name] for name in fields),
             "Whole and chunked scans must distinguish both fixed boundary controls")
    return result, {"sourceUtf16Units": len(inputs["text"].encode("utf-16-le")) // 2,
                    "splitMarkerSurvived": crossing}
