"""Independent post-run assessment of the explicit scheduled memory task."""
import hashlib
import json
from pathlib import Path


def replay_jobs(data, cases, args, runtime):
    if cases and cases[0]["operation"] == "automation-job-outcomes-runtime":
        return replay_job_outcomes(data, cases, args, runtime)

    from equivalence.automation_job_state import build_cases, wire
    from equivalence.automation_job_state_evidence import validate_native
    from equivalence.automation_job_state_native import DRIVER, PRELOAD, _source_bindings
    from equivalence.automation_job_state_replay import make_packet, replay
    from equivalence.heartbeat_dependency import CRONER

    if wire(cases) != wire(build_cases()):
        raise ValueError("Missing or altered frozen scheduled-task definition")
    [definition] = cases
    cid = definition["id"]
    captured = data["followupRows"][cid]
    row, native, sdk, trace = (captured[k] for k in ("case", "native", "python", "trace"))
    if (row.get("runtimeEvidenceValidated") is not True or row["status"] != "matched"
            or native.get("validationStatus") != "verified" or wire(row["openclaw"]) != wire(row["python"])):
        raise ValueError("Scheduled memory task lacks a validated public match")
    [raw] = native["rawSnapshots"]
    validate_native(definition, raw, row["openclaw"])
    if (raw["sourceBindings"]["owners"] != _source_bindings(args.reference)
            or raw["dependency"]["integrity"] != CRONER["integrity"]
            or raw["release"] != {k: runtime[k] for k in ("buildAttestation", "lockfileSha256", "manifestSha256")}
            or raw["driverSha256"] != hashlib.sha256(DRIVER.read_bytes()).hexdigest()
            or raw["preloadSha256"] != hashlib.sha256(PRELOAD.read_bytes()).hexdigest()):
        raise ValueError("Scheduled memory task source, release or adapter identity changed")
    files = {(p["location"], entry["path"]): entry["sha256"]
             for p in runtime["packages"] for entry in p["files"]}
    if not trace["loaded"] or any(files.get((item["package"], item["path"])) != item["sha256"]
                                  for item in trace["loaded"]):
        raise ValueError("Unverified module in the original scheduled memory task")
    expected = make_packet(row, native, trace, sdk["sha256"], data["implementation"])
    root = args.report.resolve().parent / "automation-job-state"
    sdk_dir = root / Path(expected["sdkDirectory"]).name
    packet = json.loads((sdk_dir / "review.json").read_bytes())
    if wire(packet) != wire(expected):
        raise ValueError("The compact scheduler packet differs from the full report")
    proofs = replay(packet, root)
    sdk_raw = json.loads((sdk_dir / "python-raw.json").read_bytes())
    if wire(sdk_raw) != wire(sdk["rawSnapshots"]):
        raise ValueError("The SDK raw evidence differs from the full report")
    return [{"id": cid, "publicMatch": True, "nativeRawSha256": packet["stdoutSha256"],
             "sdkRawSha256": packet["sdkSha256"], "durableReceipts": proofs["callbacks"],
             "drives": proofs["drives"], "releaseModules": len(trace["loaded"])}]


def replay_job_outcomes(data, cases, args, runtime):
    import os
    import subprocess
    import tempfile
    from equivalence import automation_job_dreaming as dreaming, automation_job_outcomes as outcomes
    from equivalence import automation_job_outcomes_native as scheduled
    from equivalence.automation_job_outcomes_replay import replay
    from equivalence.heartbeat_dependency import prepare_heartbeat_dependency
    from equivalence.heartbeat_runtime_bindings import REFERENCE_COMMIT
    from equivalence.model_runtime_authority import prepare_model_node_authority

    wire = outcomes.wire
    if wire(cases) != wire(outcomes.build_cases()):
        raise ValueError("Incomplete ordered scheduling, migration and dreaming definitions")
    root = args.report.resolve().parent / "automation-job-outcomes"
    if root.resolve(strict=True) != root:
        raise ValueError("Unexpected automation outcomes evidence directory")
    authenticated = {(p["location"], f["path"]): f["sha256"] for p in runtime["packages"] for f in p["files"]}
    reported = {(f["package"], f["path"]): f["sha256"] for f in data["followupReleaseSources"]}
    cache = Path(runtime["runtimeRoot"]).parents[2]
    archive = Path(os.environ.get("MEMORY_EQ_CRONER_ARCHIVE", cache / "heartbeat-dependencies/archives/croner-10.0.1.tgz"))
    with tempfile.TemporaryDirectory(prefix="review-automation-croner-") as private:
        dependency = prepare_heartbeat_dependency(args.reference, Path(private), archive, install=True)
    locked = {item["path"]: item["sha256"] for item in dependency["files"]}
    authority = prepare_model_node_authority(args.node)
    proof, directories = [], set()
    for case in cases:
        cid, kind = case["id"], case["input"]["kind"]
        capture = data["followupRows"][cid]
        row, native, sdk, full_trace = (capture[k] for k in ("case", "native", "python", "trace"))
        if (any(x["id"] != cid for x in (row, native, sdk, full_trace))
                or any(wire(row.get(k)) != wire(v) for k, v in case.items())
                or native["side"] != "native" or sdk["side"] != "python"
                or row.get("runtimeEvidenceValidated") is not True or row["status"] != "matched"
                or native.get("validationStatus") != "verified"):
            raise ValueError("Automation outcome lacks a complete original/SDK case")
        records = [Path(native["evidenceDirectory"]), Path(row["sdkEvidenceDirectory"])]
        for record, prefix in zip(records, ("native-attempt-", "sdk-attempt-"), strict=True):
            if (not record.is_absolute() or ".." in record.parts or record.parent.name != root.name
                    or not record.name.startswith(prefix) or record.name in directories):
                raise ValueError("Unexpected or reused automation outcome attempt")
            directories.add(record.name)
        native_dir, sdk_dir = (root / path.name for path in records)
        if (any(path.resolve(strict=True) != path for path in (native_dir, sdk_dir))
                or any(item.is_symlink() for folder in (native_dir, sdk_dir) for item in folder.rglob("*"))):
            raise ValueError("Automation outcome attempt contains redirected files")
        driver = dreaming.DRIVER if kind == "dreaming" else scheduled.DRIVER
        owners = dreaming.SOURCE if kind == "dreaming" else scheduled.OWNERS
        source_hashes = []
        for name in owners:
            committed = subprocess.run(["git", "show", REFERENCE_COMMIT + ":" + name], cwd=args.reference,
                                       capture_output=True, timeout=10, check=True).stdout
            if (args.reference / name).read_bytes() != committed:
                raise ValueError("Modified original scheduling source")
            source_hashes.append({"path": name, "sha256": hashlib.sha256(committed).hexdigest()})
        [raw] = native["rawSnapshots"]
        if (raw["sourceBindings"] != source_hashes
                or raw["dependency"] != {k: dependency[k] for k in raw["dependency"]}
                or set(raw["dependency"]) != {"name", "version", "integrity", "filesSha256", "archiveSha256"}
                or raw["release"] != {k: runtime[k] for k in ("buildAttestation", "lockfileSha256", "manifestSha256")}
                or raw["driverSha256"] != hashlib.sha256(driver.read_bytes()).hexdigest()
                or raw["preloadSha256"] != hashlib.sha256(scheduled.PRELOAD.read_bytes()).hexdigest()
                or set(raw["node"]) != set(authority) or any(raw["node"][k] != v for k, v in authority.items() if k != "execPath")):
            raise ValueError("Unverified job outcome source, package, runtime, dependency or adapter")
        trace = {k: v for k, v in full_trace.items() if k != "id"}
        packet = json.loads((sdk_dir / "review.json").read_bytes())
        expected = {"id": cid, "nativeDirectory": str(records[0]), "sdkDirectory": str(records[1]),
                    "implementation": data["implementation"], "nativeRawSha256": native["sha256"],
                    "sdkRawSha256": sdk["sha256"], "traceSha256": hashlib.sha256(wire(trace)).hexdigest()}
        for side, directory in (("native", native_dir), ("sdk", sdk_dir)):
            expected[side + "PublicSha256"] = hashlib.sha256((directory / "public.json").read_bytes()).hexdigest()
        if packet != expected:
            raise ValueError("Outcome review packet disagrees with its full report")
        for diagnostic, file in ((native, native_dir / "native-raw.json"), (sdk, sdk_dir / "python-raw.json")):
            if wire(json.loads(file.read_bytes())) != wire(diagnostic["rawSnapshots"]):
                raise ValueError("Job outcome diagnostics changed after capture")
        subdir = "managed-dreaming" if kind == "dreaming" else "task-outcomes-" + kind
        table = json.loads((native_dir / subdir / "modules.json").read_bytes())
        source_seen = set()
        for entry in table.values():
            package, path, sha = (entry[k] for k in ("package", "path", "sha256"))
            if package == "driver":
                ok = path == "driver" and sha == raw["driverSha256"]
            elif package == dependency["location"]:
                ok = locked.get(path) == sha
            else:
                ok = authenticated.get((package, path)) == reported.get((package, path)) == sha
            if not ok or (package, path) in source_seen:
                raise ValueError("Unknown, altered or duplicate original outcome module")
            source_seen.add((package, path))
        _verify_outcome_actors(trace, table, native_dir, records[0], raw["node"]["execPath"], kind)
        n, s = replay(packet, root)
        if not wire(n) == wire(s) == wire(row["openclaw"]) == wire(row["python"]):
            raise ValueError("Physical job outcome replay differs from public outputs")
        proof.append({"id": cid, "publicMatch": True, "nativeRawSha256": packet["nativeRawSha256"],
                      "sdkRawSha256": packet["sdkRawSha256"], "originalInvocations": len(trace["traces"]),
                      "releaseModules": sum(entry["package"] not in {"driver", dependency["location"]} for entry in table.values())})
    return proof


def _verify_outcome_actors(trace, table, local, recorded, executable, kind):
    from equivalence import automation_job_outcomes_native as scheduled, automation_job_dreaming as dreaming

    required = dreaming.MAIN if kind == "dreaming" else scheduled.MAIN | (
        scheduled.MIGRATION if kind == "migration" else {"dist/service-u8zoxec7.mjs"})
    entry = dreaming.DRIVER.name if kind == "dreaming" else scheduled.DRIVER.name
    seen_loads, stages = set(), set()
    for run in trace["traces"]:
        folder = local / Path(run["directory"]).relative_to(recorded)
        if folder in stages or folder.resolve(strict=True) != folder or not folder.is_relative_to(local):
            raise ValueError("Unexpected or repeated job outcome invocation")
        stages.add(folder)
        actors = run["actors"]
        [main] = [a["bootstrap"] for a in actors if a["role"] == "main"]
        if len({a["file"] for a in actors}) != len(actors) or {a["file"] for a in actors} != {f.name for f in folder.glob("load-*.jsonl")}:
            raise ValueError("An original outcome actor was duplicated or omitted")
        if not any(a["role"] == "worker" for a in actors):
            raise ValueError("Missing original state worker")
        for actor in actors:
            head, role = actor["bootstrap"], actor["role"]
            file = folder / actor["file"]
            if (head["node"] != executable or head["event"] != "bootstrap" or head["contextSha256"] != main["contextSha256"]
                    or file.name != f"load-{head['pid']}-{head['threadId']}.jsonl" or file.parent != folder):
                raise ValueError("Unexpected original scheduled process identity")
            lines = file.read_bytes().splitlines()
            records = [json.loads(line)["load"] for line in lines[1:]]
            if any(type(i) is not int or str(i) not in table for i in records):
                raise ValueError("Unknown outcome import record")
            seen_loads.update(str(i) for i in records)
            names = {(table[str(i)]["package"], table[str(i)]["path"]) for i in records}
            if role == "main":
                expected = {("node_modules/openclaw", p) for p in required} | {("driver", "driver"), ("node_modules/croner", "dist/croner.js")}
                ok = head["threadId"] == 0 and Path(head["entry"]).name == entry and expected <= names
            else:
                routes = {"worker": {scheduled.WRITE_ENTRY}, "location": {scheduled.READ_ENTRY}}
                if kind == "migration":
                    routes["session-maintenance"] = {"dist/config/sessions/disk-budget.worker.js",
                                                     "dist/config/sessions/session-accessor.sqlite-archive.worker.js"}
                if kind == "dreaming":
                    routes["cron-inspection"] = {"dist/cron/store/read-only.worker.js"}
                ok = any(head["entry"].endswith("/" + p) and ("node_modules/openclaw", p) in names
                         for p in routes.get(role, ()))
                ok = ok and ((head["pid"] != main["pid"] and head["ppid"] == main["pid"] and head["threadId"] == 0)
                             if role == "location" else (head["pid"] == main["pid"] and head["threadId"] > 0))
                if role == "worker":
                    ok = ok and ("node_modules/openclaw", scheduled.WRITE_OWNER) in names
            if not ok:
                raise ValueError("Missing original outcome entry or invalid worker lineage")
    if seen_loads != set(table):
        raise ValueError("The outcome module table contains unused or absent imports")
