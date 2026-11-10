"""Run the closed six-case boundary family before the complete catalog gate.

Every invocation owns new retained evidence. It never retries a case, repairs
an observed field, downloads dependencies or awards acceptance credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from equivalence.harness import _adapter_identity, _implementation_identity  # noqa: E402
from equivalence.host_restart_native import digest, write_json  # noqa: E402
from equivalence.host_turn_barrier_boundaries import CASE_HASHES, MANIFEST, POINTS, build_cases  # noqa: E402
from equivalence.host_turn_barrier_boundaries_bindings import prepare_host_turn_barrier_boundaries_bindings  # noqa: E402
from equivalence.host_turn_barrier_boundaries_evidence import replay_case  # noqa: E402
from equivalence.host_turn_barrier_boundaries_native import run_native_case  # noqa: E402
from equivalence.host_turn_barrier_boundaries_sdk import run_host_turn_barrier_boundaries_case  # noqa: E402
from equivalence.model_runtime_authority import prepare_model_node_authority  # noqa: E402
from equivalence.promotion_apply_family import differences  # noqa: E402
from equivalence.release_runtime import prepare_release_runtime  # noqa: E402


def artifacts(directory, root):
    rows = []
    if not directory.exists():
        return rows
    for path in sorted(directory.rglob("*")):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            rows.append({"path": str(path.relative_to(root)), "kind": "symlink", "target": str(path.readlink())})
        elif stat.S_ISREG(info.st_mode):
            rows.append({"path": str(path.relative_to(root)), "kind": "file", "bytes": info.st_size,
                         "sha256": digest(path)})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--release-runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=tuple(CASE_HASHES), action="append")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"kind": "host-turn-barrier-boundaries-comparison", "acceptancePointsAwarded": 0,
        "covers": [], "candidateCoverage": list(POINTS), "fullScopePassed": False, "cases": [], "errors": []}
    try:
        node = args.node.resolve()
        authority = prepare_model_node_authority(node)
        runtime = prepare_release_runtime(args.reference.resolve(), args.release_runtime.resolve())
        bindings = prepare_host_turn_barrier_boundaries_bindings(args.reference.resolve(), Path(runtime["runtimeRoot"]))
        implementation, adapters = _implementation_identity(), _adapter_identity()
        report.update(node=authority, reference=runtime["reference"], initialOwnerBindings=bindings,
            implementationIdentity=implementation, adapterHashes=adapters, collectorSha256=digest(Path(__file__)),
            literalManifestSha256=digest(MANIFEST))
        for case in build_cases():
            if args.case and case["id"] not in args.case:
                continue
            directory = output / case["id"]
            row = {"id": case["id"], "covers": case["covers"], "status": "blocked"}
            report["cases"].append(row)
            try:
                native = run_native_case(case, node, runtime, directory, timeout=180)
                row["nativeEvidence"] = native["releaseTrace"]
                sdk = run_host_turn_barrier_boundaries_case(case["input"], evidence_directory=directory / "evidence")
                write_json(directory / "sdk-output.json", sdk)
                row["structuralReplay"] = replay_case(case, directory)
                row["differences"] = differences(native["results"][0]["result"], sdk)
                row["status"] = "mismatch" if row["differences"] else "match"
            except Exception as error:
                row["error"] = {"name": type(error).__name__, "message": str(error)}
            row["artifacts"] = artifacts(directory, output)
            write_json(output / "report.json", report)
            print(json.dumps({"id": row["id"], "status": row["status"], "error": row.get("error"),
                "differences": len(row.get("differences", []))}), flush=True)
        if prepare_host_turn_barrier_boundaries_bindings(args.reference.resolve(), Path(runtime["runtimeRoot"])) != bindings:
            raise ValueError("Original owner identities changed during execution")
        if prepare_model_node_authority(node) != authority:
            raise ValueError("The actual Node executable changed during execution")
        prepare_release_runtime(args.reference.resolve(), args.release_runtime.resolve())
        if _implementation_identity() != implementation or _adapter_identity() != adapters:
            raise ValueError("The SDK or protected adapters changed during execution")
        if digest(Path(__file__)) != report["collectorSha256"] or digest(MANIFEST) != report["literalManifestSha256"]:
            raise ValueError("The collector or frozen literal manifest changed during execution")
        report["finalAuthenticationPassed"] = True
    except Exception as error:
        report["errors"].append({"name": type(error).__name__, "message": str(error)})
    report["summary"] = {status: sum(row["status"] == status for row in report["cases"])
                         for status in ("match", "mismatch", "blocked")}
    report["candidateFamilyMatched"] = (report.get("finalAuthenticationPassed") is True and not report["errors"]
        and len(report["cases"]) == len(CASE_HASHES) and report["summary"]["match"] == len(CASE_HASHES))
    encoded = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    (output / "report.json").write_text(encoded)
    print(json.dumps({"summary": report["summary"], "errors": report["errors"], "acceptancePointsAwarded": 0,
                      "reportSha256": hashlib.sha256(encoded.encode()).hexdigest()}))
    return 2 if report["errors"] or report["summary"]["blocked"] else 1 if report["summary"]["mismatch"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
