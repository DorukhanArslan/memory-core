"""Reopen four complete heartbeat outcomes from the streamed full comparison."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from followup_dreams import digest, require


def attempts(native, sdk_path, root, seen):
    folders = []
    for path, prefix in ((Path(native["evidenceDirectory"]), "native-attempt-"),
                         (Path(sdk_path), "sdk-attempt-")):
        require(path.is_absolute() and ".." not in path.parts and path.parent.name == root.name
                and path.name.startswith(prefix) and path.name not in seen, "Unexpected or reused heartbeat recording")
        seen.add(path.name)
        folder = root / path.name
        require(folder.is_dir() and folder.resolve(strict=True) == folder
                and not any(p.is_symlink() for p in folder.rglob("*")), "Redirected heartbeat recording")
        folders.append(folder)
    return folders


def replay_heartbeat_outcomes(data, cases, args, runtime):
    from equivalence import heartbeat_turn_outcomes as family, heartbeat_turn_outcomes_native as original
    from equivalence.heartbeat_dependency import prepare_heartbeat_dependency
    from equivalence.heartbeat_turn_outcomes_replay import replay
    from equivalence.model_runtime_authority import prepare_model_node_authority

    wire = family.wire
    require(wire(cases) == wire(family.build_cases()), "Incomplete ordered heartbeat outcome definitions")
    root = args.report.resolve().parent / "heartbeat-turn-outcomes"
    require(root.resolve(strict=True) == root, "Unexpected heartbeat evidence root")
    bindings = original._source_bindings(args.reference)
    release = {k: runtime[k] for k in ("buildAttestation", "lockfileSha256", "manifestSha256")}
    require(runtime["kind"] == "verified-release-runtime" and release["buildAttestation"]["commit"]
            == bindings["referenceCommit"], "Heartbeat outcomes require the pinned original release")
    cache = Path(runtime["runtimeRoot"]).parents[2]
    archive = Path(os.environ.get("MEMORY_EQ_CRONER_ARCHIVE", cache / "heartbeat-dependencies/archives/croner-10.0.1.tgz"))
    with tempfile.TemporaryDirectory(prefix="review-heartbeat-croner-") as temp:
        dependency = prepare_heartbeat_dependency(args.reference, Path(temp), archive, install=True)
    locked = {r["path"]: r["sha256"] for r in dependency["files"]}
    dep_seal = {k: dependency[k] for k in ("name", "version", "integrity", "archiveSha256", "filesSha256")}
    authority = prepare_model_node_authority(args.node)
    repo_modules = {(p["location"], m["path"]): m["sha256"] for p in runtime["packages"] for m in p["files"]}
    listed = {(m["package"], m["path"]): m["sha256"] for m in data["followupReleaseSources"]}
    require(len(listed) == len(data["followupReleaseSources"]), "Duplicated release module in the full report")
    adapters = {"driver": digest(original.DRIVER.read_bytes()), "clock": digest(original.CLOCK.read_bytes())}
    used = set()
    checks = []
    for case in cases:
        cid = case["id"]
        capture = data["followupRows"][cid]
        pair, native, sdk, full_trace = (capture[k] for k in ("case", "native", "python", "trace"))
        require(all(row["id"] == cid for row in (pair, native, sdk, full_trace))
                and all(wire(pair[k]) == wire(v) for k, v in case.items())
                and pair["referenceMode"] == "authenticated-official-release" and pair["status"] == "matched"
                and pair["runtimeEvidenceValidated"] is True and native["validationStatus"] == "verified"
                and native["side"] == "native" and sdk["side"] == "python", "Unverified heartbeat comparison")
        n_dir, s_dir = attempts(native, pair["sdkEvidenceDirectory"], root, used)
        trace = {k: v for k, v in full_trace.items() if k != "id"}
        packet = {"id": cid, "nativeDirectory": n_dir.name, "sdkDirectory": s_dir.name,
                  "nativeRawSha256": native["sha256"], "sdkRawSha256": sdk["sha256"],
                  "nativePublicSha256": digest(wire(pair["openclaw"])), "sdkPublicSha256": digest(wire(pair["python"])),
                  "traceSha256": digest(wire(trace)), "implementation": data["implementation"]}
        require(wire(json.loads((s_dir / "review.json").read_bytes())) == wire(packet),
                "Heartbeat review packet disagrees with the full report")
        for diag, path in ((native, n_dir / "native-raw.json"), (sdk, s_dir / "python-raw.json")):
            payload = path.read_bytes()
            require(digest(payload) == diag["sha256"] and wire(json.loads(payload)) == wire(diag["rawSnapshots"]),
                    "Heartbeat diagnostic differs from its recorded bytes")
        [raw] = native["rawSnapshots"]
        require(raw["sourceBindings"] == bindings and raw["dependency"] == dep_seal and raw["release"] == release
                and Path(trace["driverPath"]).name == original.DRIVER.name and trace["nodePath"] == raw["node"]["execPath"]
                and set(raw["node"]) == set(authority) and all(raw["node"][k] == v for k, v in authority.items()
                                                                if k != "execPath")
                and wire(trace) == wire(raw["evidence"]), "Heartbeat source, dependency, Node or trace identity changed")
        folder = n_dir / cid
        table = json.loads((folder / "modules.json").read_bytes())
        observed = set()
        for item in table.values():
            package, path, sha = (item[k] for k in ("package", "path", "sha256"))
            if package == "driver":
                ok = sha == adapters.get(path)
            elif package == dependency["location"]:
                ok = sha == locked.get(path)
            else:
                ok = sha == repo_modules.get((package, path)) == listed.get((package, path))
            require(isinstance(sha, str) and len(sha) == 64 and ok and (package, path) not in observed,
                    "Unauthenticated or repeated heartbeat module")
            observed.add((package, path))
        drives = replay(packet, root)
        require(drives == len(case["input"]["steps"]), "The complete heartbeat drives were not reopened")
        checks.append({"id": cid, "publicMatch": True, "drives": drives, "nativeRawSha256": native["sha256"],
                       "sdkRawSha256": sdk["sha256"], "releaseModules": len(observed),
                       "originalActors": len(trace["actors"]), "sqliteStoresReopened": len(raw["physical"]),
                       "modelCalls": sum(len(turn["calls"]) for turn in raw["steps"]),
                       "deliveries": sum(len(turn["sends"]) for turn in raw["steps"])})
    return checks
