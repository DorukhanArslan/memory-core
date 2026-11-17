"""Independently check reopened original and SDK compaction against retained full-run artifacts."""
import hashlib
import json
from pathlib import Path
import subprocess


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _actors(trace, table, folder, raw, executable):
    from equivalence.compaction_assembly_native import AI, DRIVER, HARN, SQL

    roots = {item["phase"]: item["pid"] for item in raw["launches"]}
    if len(set(roots.values())) != 2 or set(roots) != {"seed", "reopen"}:
        raise ValueError("Compaction requires two different original processes")
    workers = {
        "seed": {"dist/config/sessions/disk-budget.worker.js"},
        "reopen": {"dist/infra/sqlite-store.worker.js", "dist/config/sessions/session-transcript.worker.js",
                   "dist/agents/embedded-agent-runner/provider-prompt-state.worker.js"},
    }
    identities = {(entry["pid"], entry["threadId"]): entry for entry in trace["bootstraps"]}
    files = sorted(folder.glob("trace-*.jsonl"))
    if len(identities) != len(trace["bootstraps"]) or len(files) != len(identities):
        raise ValueError("A native compaction actor was duplicated or omitted")
    observed_workers = {phase: set() for phase in roots}
    for file in files:
        head, *records = map(json.loads, file.read_bytes().splitlines())
        pid, tid = head["pid"], head["threadId"]
        actor = identities[(pid, tid)]
        phase = actor["phase"]
        parent = identities[(roots[phase], 0)]
        if (head != {k: v for k, v in actor.items() if k != "phase"} or head["node"] != executable
                or file.name != f"trace-{pid}-{tid}.jsonl" or parent["contextSha256"] != head["contextSha256"]
                or parent["ppid"] != head["ppid"] or pid != roots[phase]):
            raise ValueError("Unknown original assembly worker identity")
        names = {(table[str(record["load"])]["package"], table[str(record["load"])]["path"]) for record in records}
        if tid == 0:
            required = {("driver", DRIVER.name), ("node_modules/openclaw", SQL), ("node_modules/@openclaw/ai", AI),
                        ("node_modules/openai", "resources/responses/responses.mjs")}
            original = {"dist/tools-DotaQGXh.mjs"} if phase == "seed" else {
                HARN, "dist/admitted-run-context-hIkojwNE.mjs", "dist/context-engine-lifecycle-DC_XP7J3.mjs",
                "dist/extensions/memory-core/index.js", "dist/extensions/openai/index.js"}
            required.update(("node_modules/openclaw", name) for name in original)
            if Path(head["entry"]).name != DRIVER.name or not required <= names:
                raise ValueError("An original context, model transport, memory callback or harness owner is absent")
        else:
            [entry] = [name for name in workers[phase] if head["entry"].endswith("/node_modules/openclaw/" + name)]
            if ("node_modules/openclaw", entry) not in names:
                raise ValueError("Unobserved original session worker entry")
            observed_workers[phase].add(entry)
    if observed_workers != workers:
        raise ValueError("Missing original durable or provider preparation workers")


def replay_compaction(data, cases, args, runtime):
    from equivalence import compaction_assembly as family, compaction_assembly_native as original
    from equivalence.heartbeat_runtime_bindings import REFERENCE_COMMIT
    from equivalence.model_runtime_authority import prepare_model_node_authority

    wire = family.wire
    if wire(cases) != wire(family.build_cases()):
        raise ValueError("Missing frozen positive, cropped or wrong-model compaction control")
    root = args.report.resolve().parent / family.FAMILY
    authority = prepare_model_node_authority(args.node)
    if runtime["kind"] != "verified-release-runtime" or runtime["buildAttestation"]["commit"] != REFERENCE_COMMIT:
        raise ValueError("Incorrect original release for compaction")
    known = {(p["location"], f["path"]): f["sha256"] for p in runtime["packages"] for f in p["files"]}
    listed = {(f["package"], f["path"]): f["sha256"] for f in data["followupReleaseSources"]}
    owners = []
    for name in original.SOURCE_OWNERS:
        committed = subprocess.run(["git", "show", REFERENCE_COMMIT + ":" + name], cwd=args.reference,
                                   capture_output=True, timeout=10, check=True).stdout
        if (args.reference / name).read_bytes() != committed:
            raise ValueError("Original context assembly source changed")
        owners.append({"path": name, "sha256": _digest(committed)})
    results, attempts = [], set()
    for definition in cases:
        cid = definition["id"]
        capture = data["followupRows"][cid]
        row, native, sdk, reported_trace = (capture[key] for key in ("case", "native", "python", "trace"))
        if (any(record["id"] != cid for record in (row, native, sdk, reported_trace))
                or native["side"] != "native" or sdk["side"] != "python" or native.get("validationStatus") != "verified"
                or row["status"] != "matched" or row.get("runtimeEvidenceValidated") is not True
                or any(wire(row[key]) != wire(value) for key, value in definition.items())):
            raise ValueError("Missing verified original or SDK compaction row")
        trace = {k: v for k, v in reported_trace.items() if k != "id"}
        packet = {"id": cid, "nativeDirectory": native["evidenceDirectory"], "sdkDirectory": row["sdkEvidenceDirectory"],
                  "nativeRawSha256": native["sha256"], "sdkRawSha256": sdk["sha256"], "implementation": data["implementation"],
                  "traceSha256": _digest(wire(trace)), "nativePublicSha256": _digest(wire(row["openclaw"])),
                  "sdkPublicSha256": _digest(wire(row["python"]))}
        for side, diag, name in (("native", native, "native-raw.json"), ("sdk", sdk, "python-raw.json")):
            recorded = Path(packet[side + "Directory"])
            local = root / recorded.name
            if (not recorded.is_absolute() or ".." in recorded.parts or recorded.parent.name != root.name
                    or not recorded.name.startswith(side + "-attempt-") or local.resolve(strict=True) != local
                    or local.name in attempts or any(item.is_symlink() for item in local.rglob("*"))):
                raise ValueError("Unexpected, redirected or reused compaction attempt")
            attempts.add(local.name)
            if wire(json.loads((local / name).read_bytes())) != wire(diag["rawSnapshots"]):
                raise ValueError("Compaction diagnostic differs from its complete report")
        sdk_dir = root / Path(packet["sdkDirectory"]).name
        if json.loads((sdk_dir / "review.json").read_bytes()) != packet:
            raise ValueError("Compaction replay packet differs from its full report")
        [raw] = native["rawSnapshots"]
        if (raw["sourceOwners"] != owners or raw["driverSha256"] != _digest(original.DRIVER.read_bytes())
                or raw["preloadSha256"] != _digest(original.PRELOAD.read_bytes()) or set(raw["nodeRuntime"]) != set(authority)
                or any(raw["nodeRuntime"][k] != v for k, v in authority.items() if k != "execPath")):
            raise ValueError("Original compaction source or Node runtime differs from pinned evidence")
        native_dir = root / Path(packet["nativeDirectory"]).name / "context-assembly-original"
        if Path(raw["directory"]) != Path(packet["nativeDirectory"]) / native_dir.name:
            raise ValueError("Unexpected native compaction store location")
        table = json.loads((native_dir / "loaded-modules.json").read_bytes())
        identities = set()
        for item in table.values():
            identity = item["package"], item["path"]
            if identity in identities:
                raise ValueError("Duplicated original compaction module")
            identities.add(identity)
            if identity[0] == "driver":
                verified = identity[1] == original.DRIVER.name and item["sha256"] == raw["driverSha256"]
            else:
                verified = known.get(identity) == listed.get(identity) == item["sha256"]
            if not verified:
                raise ValueError("Compaction imported an unverified module")
        _actors(trace, table, native_dir, raw, raw["nodeRuntime"]["execPath"])
        n, s = family.replay(packet, root)
        if not wire(n) == wire(s) == wire(row["openclaw"]) == wire(row["python"]):
            raise ValueError("Compaction physical replay diverges from the declared full result")
        results.append({"id": cid, "publicMatch": True, "nativeRawSha256": native["sha256"], "sdkRawSha256": sdk["sha256"],
                        "releaseModules": len(trace["loaded"]), "providerInputItems": len(n["input"])})
    return results
