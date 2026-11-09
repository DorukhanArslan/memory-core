"""Run three exact whole-host restart development comparisons; awards no coverage.

Each invocation owns a new evidence directory. Failed attempts are retained;
the tool never retries, fetches dependencies or runs a paid provider.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from equivalence.model_runtime_authority import prepare_model_node_authority  # noqa: E402
from equivalence.host_restart_bindings import prepare_host_restart_runtime_bindings  # noqa: E402
from equivalence.host_restart import build_cases, CASE_HASHES  # noqa: E402
from equivalence.promotion_apply_family import differences  # noqa: E402
from equivalence.host_restart_sdk import run_host_restart  # noqa: E402
from equivalence.host_restart_evidence import replay_case  # noqa: E402
from equivalence.release_runtime import prepare_release_runtime  # noqa: E402
from equivalence.host_restart_native import run_native_case, digest, write_json  # noqa: E402
from memory_core.project_name import PACKAGE_NAME  # noqa: E402


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
    report = {"kind": "host-restart-recall-development", "acceptancePointsAwarded": 0,
              "covers": [], "fullScopePassed": False, "cases": [], "errors": []}
    try:
        node = args.node.resolve()
        authority = prepare_model_node_authority(node)
        runtime = prepare_release_runtime(args.reference.resolve(), args.release_runtime.resolve())
        bindings = prepare_host_restart_runtime_bindings(args.reference.resolve(), Path(runtime["runtimeRoot"]))
        report.update(node=authority, reference=runtime["reference"], initialOwnerBindings=bindings,
                      implementation=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                      sdkSourceHashes={str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / PACKAGE_NAME).rglob("*.py"))},
                      adapterHashes={str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / "equivalence").iterdir())
                                     if p.suffix in {".py", ".mjs"}},
                      collectorSha256=digest(Path(__file__)))
        literals = ROOT / "docs/host_restart_recall_literals.json"
        report["literalManifestSha256"] = digest(literals)
        for case in build_cases():
            if args.case and case["id"] not in args.case:
                continue
            directory = output / case["id"]
            row = {"id": case["id"], "covers": [], "status": "blocked"}
            report["cases"].append(row)
            try:
                native = run_native_case(case, node, runtime, directory)
                row["nativeEvidence"] = native["releaseTrace"]
                evidence = directory / "evidence"
                original = native["results"][0]["result"]
                sdk = run_host_restart(case["input"], evidence_directory=evidence)
                write_json(directory / "sdk-output.json", sdk)
                row["structuralReplay"] = replay_case(case, directory)
                row["differences"] = differences(original, sdk)
                row["status"] = "mismatch" if row["differences"] else "match"
            except Exception as error:
                row["error"] = {"name": type(error).__name__, "message": str(error)}
            row["artifacts"] = [{"path": str(p.relative_to(output)), "sha256": digest(p)}
                                for p in sorted(directory.rglob("*")) if p.is_file()]
            write_json(output / "report.json", report)
            print(json.dumps({"id": row["id"], "status": row["status"], "error": row.get("error"),
                              "differences": len(row.get("differences", []))}), flush=True)
        if prepare_host_restart_runtime_bindings(args.reference.resolve(), Path(runtime["runtimeRoot"])) != bindings:
            raise ValueError("Original owners changed during execution")
        if prepare_model_node_authority(node) != authority:
            raise ValueError("Executable changed during execution")
        prepare_release_runtime(args.reference.resolve(), args.release_runtime.resolve())
        for relative, expected in report["sdkSourceHashes"].items():
            if digest(ROOT / relative) != expected:
                raise ValueError("SDK changed during execution")
        for relative, expected in report["adapterHashes"].items():
            if digest(ROOT / relative) != expected:
                raise ValueError("Restart adapters changed during execution")
        if digest(Path(__file__)) != report["collectorSha256"]:
            raise ValueError("Collector changed during execution")
        if digest(literals) != report["literalManifestSha256"]:
            raise ValueError("The frozen literal manifest changed during execution")
        report["finalAuthenticationPassed"] = True
    except Exception as error:
        report["errors"].append({"name": type(error).__name__, "message": str(error)})
    report["summary"] = {status: sum(row["status"] == status for row in report["cases"])
                         for status in ("match", "mismatch", "blocked")}
    write_json(output / "report.json", report)
    print(json.dumps({"summary": report["summary"], "errors": report["errors"], "acceptancePointsAwarded": 0}))
    return 2 if report["errors"] or report["summary"]["blocked"] else 1 if report["summary"]["mismatch"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
