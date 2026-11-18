"""Reconstruct user-configured masking from source calls, six database images and fresh child output."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from pathlib import Path
import re
import sqlite3

from equivalence import configured_redaction as family
from equivalence.configured_redaction_evidence import engine_identity
from equivalence.harness import ROOT, _adapter_identity, _json, _same_json
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.model_runtime_bindings import prepare_model_session_runtime_bindings
from equivalence.model_runtime_evidence import validate_model_session_raw
from equivalence.redaction_policy_evidence import prepare_redaction_policy_source_bindings, validate_redaction_policy_source_execution
from equivalence.runtime_oracle import MAX_DIAGNOSTIC_BYTES, _owned_regular
from equivalence.secret_boundary_evidence import _read_child
from secret_boundary_native import require, runtime_actors


def _file(record, directory, name):
    path = directory / name
    require(record["path"] == str(path), "Configured recording names a different owned file")
    wire = _owned_regular(ROOT, path, MAX_DIAGNOSTIC_BYTES)
    require(len(wire) == record["bytes"] and sha256(wire).hexdigest() == record["sha256"],
            "Configured redaction file size or digest changed")
    return path, wire


def _capture(case, receipt, side):
    record = receipt["configuredRecording"]
    require(record["id"] == receipt["id"] == case["id"] and record["side"] == side,
            "Configured recording belongs to a different case or process")
    directory = Path(record["wire"]["path"]).parent
    require(directory.parent == ROOT / ".equivalence-results/configured-redaction"
            and directory.name.startswith(side + "-attempt-"),
            "Configured capture is outside its original private directory")
    _, wire = _file(record["wire"], directory, side + "-raw.json")
    payload = _json(wire.decode("utf-8"))
    if side != "source":
        require(receipt["side"] == side and receipt["sha256"] == record["wire"]["sha256"]
                and _same_json(payload, receipt["rawSnapshots"]) and len(payload) == 1,
                "On-disk configured output differs from its reported process")
        payload, = payload
    phases = ("write", "continue", "verify") if case["id"] == family.IDS[1] else ()
    require([row["phase"] for row in record["databases"]] == list(phases),
            "Expected exactly one database image per declared session phase")
    return payload, [(row, _file(row, directory, "configured-" + row["phase"] + ".sqlite")[0])
                     for row in record["databases"]]


def _database(path, native):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        db.row_factory = sqlite3.Row
        query = "SELECT name FROM sqlite_master WHERE type='table'"
        if native:
            query += " AND (name GLOB 'session_*' OR name GLOB 'transcript_*')"
        tables = {}
        for name, in db.execute(query + " ORDER BY name"):
            require(re.fullmatch(r"[a-z0-9_]+", name), "Unexpected session table name")
            rows = [{key: {"type": "bytes", "hex": val.hex()} if isinstance(val, bytes) else val
                     for key, val in dict(row).items()} for row in db.execute(f'SELECT * FROM "{name}"')]
            if native:
                columns = [dict(row) for row in db.execute(f'PRAGMA table_info("{name}")')]
                tables[name] = {"columns": columns, "rows": rows}
            else:
                tables[name] = rows
        return tables


def _read_images(record, images, *, native):
    before, after = ("sessionSqlBefore", "sessionSqlAfter") if native else ("beforeSql", "afterSql")
    states, receipts = [], []
    for phase, (entry, path) in zip(record["phases"], images, strict=True):
        state = _database(path, native)
        observation = phase["raw"]
        require(observation.get("phase", observation.get("label")) == entry["phase"]
                and _same_json(state, observation[after]), "Database differs from the actual child SQL")
        if states:
            require(_same_json(states[-1], observation[before]), "Fresh session failed to reopen the preceding state")
        states.append(state)
        receipts.append({"phase": entry["phase"], "sha256": entry["sha256"], "bytes": entry["bytes"],
                         "tables": len(state)})
    require(_same_json(states[-1], states[-2]), "Identity-only reread changed committed messages")
    return receipts


def _sdk(case, receipt, engine):
    record, images = _capture(case, receipt, "python")
    require(record["kind"] == ("model-session" if images else case["operation"]), "SDK capture changed its operation")
    coordinator = record["coordinatorPid"]
    inputs = case["input"]
    common = {k: v for k, v in inputs.items() if k not in {"kind", "phases"}}
    if images:
        require(_same_json(record["input"], inputs), "SDK configured session input changed")
        phases = inputs["phases"]
        identity = {k: common[k] for k in ("nowMs", "agentId", "sessionId", "sessionKey")}
        requests = [{"operation": case["operation"], "phase": phase, "directory": record["fixtureBase"],
                     "input": identity if phase["label"] == "verify" else common} for phase in phases]
        children = record["phases"]
    else:
        requests = [{"operation": case["operation"], "input": inputs}]
        children = record["children"]
    outputs, pids = [], set()
    for child, request in zip(children, requests, strict=True):
        result, raw = _read_child(child, request, coordinator)
        require(raw["request"] == request and raw["implementationRoot"] == str(ROOT)
                and _same_json(raw["output"], result) and raw["pid"] not in pids and raw["pid"] != coordinator,
                "SDK did not run its actual complete configured policy in fresh processes")
        if request.get("phase", {}).get("label") != "verify":
            require(raw["configuredRegexEngine"] == engine, "Configured SDK child loaded a different ECMAScript engine")
        if images:
            require(raw["storePaths"]["databasePath"] == str(Path(record["fixtureBase"]) / "session-catalog.sqlite")
                    and raw["label"] == result["phase"] == request["phase"]["label"],
                    "SDK session did not use the actual three-phase store")
        outputs.append(result)
        pids.add(raw["pid"])
    public = {"provider": "none", "phases": outputs} if images else outputs[0]
    return public, {"processes": len(pids), "streamSha256": receipt["sha256"],
                    "databases": _read_images(record, images, native=False) if images else []}


def _source(case, receipt, node, reference):
    response, _ = _capture(case, receipt, "source")
    record = receipt["configuredRecording"]
    require(_same_json(response["sourceExecution"], receipt["sourceExecution"]), "Original source process evidence changed")
    validate_redaction_policy_source_execution(response, case, node_authority=node,
        process_pid=record["pid"], coordinator_pid=record["ppid"], fixture_root=Path(record["fixtureRoot"]))
    for source in response["sources"]:
        path = reference / source["path"]
        require(path.resolve(strict=True) == path and sha256(path.read_bytes()).hexdigest() == source["sha256"],
                "Configured source process loaded a different original module")
    return response["results"][0]["result"], {"sourceOwners": len(response["sources"]),
            "streamSha256": record["wire"]["sha256"], "sourceCalls": len(receipt["sourceExecution"]["observations"][0]["calls"])}


def replay_configured_redaction(data, cases, args, runtime):
    require(_same_json(cases, family.build_cases()) and _same_json(data["adapterSha256"], _adapter_identity()),
            "Configured redaction replay needs the same original adapters and fixed two definitions")
    node = prepare_model_node_authority(args.node)
    require(_same_json(node, data["modelNodeAuthority"]) and _same_json(
            prepare_redaction_policy_source_bindings(args.reference), data["redactionPolicySourceBindings"])
            and _same_json(prepare_model_session_runtime_bindings(args.reference, Path(runtime["runtimeRoot"])),
                           data["modelSessionRuntimeBindings"]), "Configured source or session bindings changed")
    engine = engine_identity()
    require(engine["version"] == "0.18.0.2", "Configured matcher needs its pinned distribution")
    receipts = []
    for case in cases:
        capture = data["followupRows"][case["id"]]
        row = capture["case"]
        sdk, sdk_receipt = _sdk(case, capture["python"], engine)
        if case["id"] == family.IDS[0]:
            original, native_receipt = _source(case, capture["sourcePolicy"], node, args.reference)
        else:
            native, images = _capture(case, capture["native"], "native")
            trace = capture["trace"]
            require(trace["id"] == case["id"], "Different original model trace")
            actors = runtime_actors(trace, trace["configuredModelTraceFiles"], node, data["adapterSha256"],
                                    runtime, data["followupReleaseSources"])
            original = {"provider": "none", "phases": [_json(p["stdout"])["result"] for p in native["phases"]]}
            result = {"id": case["id"], "ok": True, "result": original}
            validate_model_session_raw(result, case, [native], Path(native["fixtureBase"]).parent,
                                       runtime_root=runtime["runtimeRoot"], **actors)
            native_receipt = {"streamSha256": capture["native"]["sha256"],
                              "processes": len(actors["process_parents"]),
                              "databases": _read_images(native, images, native=True)}
        require(row["status"] == "matched" and _same_json(original, row["openclaw"])
                and _same_json(sdk, row["python"]) and _same_json(original, sdk),
                "Whole configured redaction outputs differ from independently reopened evidence")
        receipts.append({"id": case["id"], "publicMatch": True, "original": native_receipt,
                         "sdk": sdk_receipt, "embeddedEngine": engine})
    return receipts
