"""Collect one new, unretried paired forget/index-fence packet.

Each engine owns a separate retained directory. Custody is checked before
public parity; this standalone diagnostic never awards acceptance points.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from equivalence import forget_index_fence_v2, forget_index_fence_v3, forget_index_fence_v4, forget_index_fence_v5  # noqa: E402
from equivalence.forget_index_fence_bindings import prepare_forget_index_fence_bindings  # noqa: E402
from equivalence.forget_index_fence_evidence import replay_case  # noqa: E402
from equivalence.forget_index_fence_native import run_native_case  # noqa: E402
from equivalence.forget_index_fence_sdk import run_forget_index_fence_sdk_case  # noqa: E402
from equivalence.harness import _adapter_identity, _implementation_identity  # noqa: E402
from equivalence.host_restart_native import digest, write_json  # noqa: E402
from equivalence.model_runtime_authority import prepare_model_node_authority  # noqa: E402
from equivalence.promotion_apply_family import differences  # noqa: E402
from equivalence.release_runtime import prepare_release_runtime  # noqa: E402


def artifacts(directory, root):
    rows = []
    for path in sorted(directory.rglob("*")):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            rows.append({"path": str(path.relative_to(root)), "kind": "symlink", "target": str(path.readlink())})
        elif stat.S_ISREG(info.st_mode):
            rows.append({"path": str(path.relative_to(root)), "kind": "file", "bytes": info.st_size,
                         "sha256": digest(path)})
    return rows


def error_record(error):
    return {"name": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    versions = {"v2": forget_index_fence_v2, "v3": forget_index_fence_v3, "v4": forget_index_fence_v4,
                "v5": forget_index_fence_v5}
    parser.add_argument("--version", choices=tuple(versions), default="v2")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--release-runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=tuple(case_id for version in versions.values()
                                               for case_id in version.CASE_HASHES), action="append",
                        help="Select cases in this explicit order; repeated IDs are rejected")
    parser.add_argument("--stop-on-blocked", action="store_true",
                        help="Retain the first invalid measurement and stop; ordinary mismatches continue")
    parser.add_argument("--defer-custody", action="store_true",
                        help="Capture originals only; retain blocked status and award no credit until independent replay")
    args = parser.parse_args(argv)
    frozen = versions[args.version]
    CASE_HASHES, MANIFEST, POINTS, build_cases = frozen.CASE_HASHES, frozen.MANIFEST, frozen.POINTS, frozen.build_cases
    if args.case and any(case_id not in CASE_HASHES for case_id in args.case):
        parser.error("Selected cases must belong to the explicitly selected input version")
    if args.case and len(set(args.case)) != len(args.case):
        parser.error("Each independently frozen case may be selected only once")
    if args.defer_custody and args.stop_on_blocked:
        parser.error("Deferred custody remains blocked and cannot be combined with --stop-on-blocked")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"kind": f"forget-index-fence-{args.version}-comparison", "acceptancePointsAwarded": 0,
              "covers": [], "candidateCoverage": list(POINTS), "fullScopePassed": False,
              "cases": [], "errors": []}
    try:
        node, reference = args.node.resolve(), args.reference.resolve()
        authority = prepare_model_node_authority(node)
        runtime = prepare_release_runtime(reference, args.release_runtime.resolve())
        bindings = prepare_forget_index_fence_bindings(reference, Path(runtime["runtimeRoot"]))
        implementation, adapters = _implementation_identity(), _adapter_identity()
        report.update(node=authority, reference=runtime["reference"], initialOwnerBindings=bindings,
                      implementationIdentity=implementation, adapterHashes=adapters,
                      collectorSha256=digest(Path(__file__)), literalManifestSha256=digest(MANIFEST))
        write_json(output / "report.json", report)
        available = {case["id"]: case for case in build_cases()}
        ordered = [available[case_id] for case_id in (args.case or CASE_HASHES)]
        report["execution"] = {"caseOrder": [case["id"] for case in ordered],
                               "inputVersion": args.version,
                               "stopOnBlocked": args.stop_on_blocked,
                               "deferCustody": args.defer_custody}
        for case in ordered:
            directory = output / case["id"]
            directory.mkdir()
            native_directory, sdk_directory = directory / "native", directory / "sdk/evidence"
            row = {"id": case["id"], "covers": [], "candidateCoverage": case["covers"], "status": "blocked"}
            report["cases"].append(row)
            native_result = sdk_result = None
            try:
                native = run_native_case(case, node, runtime, native_directory, timeout=180, checkout=reference)
                native_result = native["results"][0]["result"]
                row["nativeEvidence"] = native["releaseTrace"]
            except Exception as error:
                row["nativeError"] = error_record(error)
            try:
                sdk_result = run_forget_index_fence_sdk_case(case["input"], evidence_directory=sdk_directory)
                write_json(directory / "sdk-output.json", sdk_result)
            except Exception as error:
                row["sdkError"] = error_record(error)
            if native_result is not None and sdk_result is not None:
                if args.defer_custody:
                    row["custodyPending"] = True
                else:
                    try:
                        row["structuralReplay"] = replay_case(case, native_directory, sdk_directory,
                                                            approved_node=node, approved_sdk_root=ROOT,
                                                            approved_reference=reference,
                                                            **({"approved_adapter_root": ROOT}
                                                               if args.version != "v2" else {}))
                        if args.version == "v5" and (
                                not isinstance(row["structuralReplay"], dict)
                                or row["structuralReplay"].get("validated") is not True
                                or type(row["structuralReplay"].get("publicMatch")) is not bool
                                or type(row["structuralReplay"].get("acceptancePointsAwarded")) is not int
                                or row["structuralReplay"]["acceptancePointsAwarded"] != 0):
                            raise ValueError("V5 requires affirmative independent zero-credit custody before comparison")
                        row["differences"] = differences(native_result, sdk_result)
                        if (args.version == "v5"
                                and row["structuralReplay"]["publicMatch"] is not (not row["differences"])):
                            raise ValueError("V5 independent custody parity differs from the whole actual results")
                        row["status"] = "mismatch" if row["differences"] else "match"
                    except Exception as error:
                        row["custodyError"] = error_record(error)
            row["artifacts"] = artifacts(directory, output)
            write_json(output / "report.json", report)
            print(json.dumps({"id": row["id"], "status": row["status"],
                              "errors": {key: row[key]["message"] for key in
                                         ("nativeError", "sdkError", "custodyError") if key in row},
                              "differences": len(row.get("differences", []))}), flush=True)
            if args.stop_on_blocked and row["status"] == "blocked":
                report["stoppedAfterBlockedCase"] = row["id"]
                break
        if prepare_forget_index_fence_bindings(reference, Path(runtime["runtimeRoot"])) != bindings:
            raise ValueError("Original owner identities changed during execution")
        if prepare_model_node_authority(node) != authority:
            raise ValueError("The actual Node executable changed during execution")
        prepare_release_runtime(reference, args.release_runtime.resolve())
        if _implementation_identity() != implementation or _adapter_identity() != adapters:
            raise ValueError("The SDK or protected adapters changed during execution")
        if digest(Path(__file__)) != report["collectorSha256"] or digest(MANIFEST) != report["literalManifestSha256"]:
            raise ValueError("The collector or frozen literal manifest changed during execution")
        report["finalAuthenticationPassed"] = True
    except Exception as error:
        report["errors"].append(error_record(error))
    report["summary"] = {status: sum(row["status"] == status for row in report["cases"])
                         for status in ("match", "mismatch", "blocked")}
    report["candidateFamilyMatched"] = (report.get("finalAuthenticationPassed") is True
        and not report["errors"] and len(report["cases"]) == len(CASE_HASHES)
        and {row["id"] for row in report["cases"]} == set(CASE_HASHES)
        and report["summary"]["match"] == len(CASE_HASHES))
    encoded = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    (output / "report.json").write_text(encoded)
    print(json.dumps({"summary": report["summary"], "errors": report["errors"], "acceptancePointsAwarded": 0,
                      "reportSha256": hashlib.sha256(encoded.encode()).hexdigest()}))
    return 2 if report["errors"] or report["summary"]["blocked"] else 1 if report["summary"]["mismatch"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
