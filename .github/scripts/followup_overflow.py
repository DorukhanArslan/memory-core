"""Reopen every original/SDK overflow dispatch, real tool output and durable transcript."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from followup_heartbeat_outcomes import attempts
from followup_dreams import require


def replay_overflow(data, cases, args, runtime):
    from equivalence import provider_overflow_cases as family, provider_overflow_native as original
    from equivalence.model_runtime_authority import prepare_model_node_authority
    from equivalence.provider_overflow_replay import replay

    wire = family.wire
    root = args.report.resolve().parent / "provider-overflow"
    require(root.resolve(strict=True) == root and wire(cases) == wire(family.build_cases()), "Unrecognized overflow family")
    source = []
    for path in original.SOURCE:
        payload = subprocess.check_output(["git", "show", original.REFERENCE_COMMIT + ":" + path], cwd=args.reference)
        require(payload == (args.reference / path).read_bytes(), "Pinned original overflow source changed")
        source.append({"path": path, "sha256": original.digest(payload)})
    authority = prepare_model_node_authority(args.node)
    release = {k: runtime[k] for k in ("buildAttestation", "lockfileSha256", "manifestSha256")}
    require(runtime["kind"] == "verified-release-runtime" and release["buildAttestation"]["commit"]
            == original.REFERENCE_COMMIT, "Unsealed original overflow release")
    release_files = [(str(Path(p["directory"]) / f["path"]), f["sha256"], p["location"], f["path"])
                     for p in runtime["packages"] for f in p["files"]]
    listed = {(r["package"], r["path"]): r["sha256"] for r in data["followupReleaseSources"]}
    require(len(listed) == len(data["followupReleaseSources"]), "Duplicate original module")
    drivers = (original.DRIVER, original.ASSEMBLY, original.CHECKPOINT, original.PLUGIN)
    fixtures = [(p.relative_to(original.DIR), original.digest(p.read_bytes())) for p in drivers]
    modules_by_index = {str(i): {"package": package, "path": path, "sha256": sha}
                        for i, (_, sha, package, path) in enumerate(release_files)}
    modules_by_index.update({str(i): {"package": "driver", "path": relative.name, "sha256": sha}
                             for i, (relative, sha) in enumerate(fixtures, start=len(release_files))})
    official_paths = [entry[:2] for entry in release_files]
    seen, checked = set(), []
    for case in cases:
        identifier = case["id"]
        capture = data["followupRows"][identifier]
        row, native, sdk, trace = (capture[k] for k in ("case", "native", "python", "trace"))
        require(all(r["id"] == identifier for r in (row, native, sdk, trace))
                and all(wire(row[k]) == wire(v) for k, v in case.items()) and row["referenceMode"] == "authenticated-official-release"
                and native["validationStatus"] == "verified" and native["side"] == "native" and sdk["side"] == "python"
                and row["runtimeEvidenceValidated"] is True, "Overflow row lost its producer observations")
        ndir, sdir = attempts(native, row["sdkEvidenceDirectory"], root, seen)
        packet = {"id": identifier, "nativeDirectory": ndir.name, "sdkDirectory": sdir.name, "nativeRawSha256": native["sha256"],
                  "sdkRawSha256": sdk["sha256"], "original": row["openclaw"], "sdk": row["python"],
                  "implementation": data["implementation"]}
        require(wire(json.loads((sdir / "review.json").read_bytes())) == wire(packet), "Changed overflow replay inputs")
        for folder, filename, diag in ((ndir, "native-raw.json", native), (sdir, "python-raw.json", sdk)):
            raw_bytes = (folder / filename).read_bytes()
            require(original.digest(raw_bytes) == diag["sha256"] and wire(json.loads(raw_bytes)) == wire(diag["rawSnapshots"]),
                    "Overflow report differs from the retained producer bytes")
        [raw] = native["rawSnapshots"]
        require(raw["sources"] == source and raw["release"] == release and set(authority) == set(raw["node"])
                and all(raw["node"][k] == v for k, v in authority.items() if k != "execPath")
                and trace == {"id": identifier, "phases": raw["phases"], "receipts": raw["receipts"],
                              "moduleAuthoritySha256": raw["moduleAuthoritySha256"]}, "Overflow process seal differs")
        modules = json.loads((ndir / "modules.json").read_bytes())
        capture_root = Path(native["evidenceDirectory"])
        adapter_root = Path(raw["phases"][0]["driver"]).parent
        fixture_paths = [(str(adapter_root / relative), sha) for relative, sha in fixtures]
        full_authority = {"files": official_paths + fixture_paths, "trace": str(capture_root / "trace"),
                          "fixture": str(adapter_root / original.PLUGIN.relative_to(original.DIR)),
                          "state": str(capture_root / "state")}
        require(original.digest(wire(full_authority)) == raw["moduleAuthoritySha256"], "Changed overflow process module authority")
        for index, item in modules.items():
            key = (item["package"], item["path"])
            require(modules_by_index.get(index) == item and (key[0] == "driver" or listed.get(key) == item["sha256"]),
                    "Unexpected overflow module index, bytes or release owner")
        pair = replay(packet, root)
        actual = pair["original"]
        equal = wire(actual) == wire(pair["sdk"])
        require(row["status"] == ("matched" if equal else "mismatched"), "Overflow verdict does not follow from the physical outputs")
        checked.append({"id": identifier, "publicMatch": equal, "nativeRawSha256": native["sha256"],
                        "sdkRawSha256": sdk["sha256"], "dispatchOrder": [call["kind"] for call in actual["dispatches"]],
                        "preflight": actual["preflight"], "terminal": actual["terminal"]["kind"],
                        "midturn": actual["midturn"], "durableAdmissions": actual["durableUserAdmissions"],
                        "realToolCalls": len(actual["tools"]), "committedCompactions": actual["compactionsCommitted"],
                        "sqliteSnapshotsReopened": len(raw["phases"]), "originalActors": len(raw["receipts"])})
    return checked
