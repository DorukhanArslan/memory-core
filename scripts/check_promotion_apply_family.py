"""Run eight exact whole-apply development comparisons; awards no coverage.

Each invocation owns a new evidence directory. Failed attempts are retained;
the tool never retries, fetches dependencies or runs a paid provider.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from equivalence.model_runtime_authority import prepare_model_node_authority  # noqa: E402
from equivalence.promotion_apply_bindings import prepare_promotion_apply_bindings, PROMOTION_WORKER_ROUTE  # noqa: E402
from equivalence.promotion_apply_family import build_cases, differences, CASE_HASHES  # noqa: E402
from equivalence.promotion_apply_family_sdk import run_family_sdk  # noqa: E402
from equivalence.promotion_apply_family_evidence import replay_case  # noqa: E402
from equivalence.release_runtime import prepare_release_runtime, validate_release_sources  # noqa: E402

LOCAL = ("promotion-apply-family-entry.mjs", "promotion-apply-family-preload.mjs",
         "promotion-apply-family-runtime.mjs", "promotion-apply-family-observers.mjs",
         "release-preload.mjs", "model-runtime-observation.mjs")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n", encoding="utf8")


def validate_traces(directory, context, runtime, authority):
    """Authenticate actual thread/import receipts; no behavioral expected output."""
    seen, bootstraps, workers = {}, [], {}
    packages = {(p["location"], f["path"]): f["sha256"] for p in runtime["packages"] for f in p["files"]}
    locals_ = {entry["path"]: entry["sha256"] for entry in context["allowedLocal"]}
    for trace in sorted(directory.glob("*.jsonl")):
        content = trace.read_bytes()
        if len(content) > 8 * 1024 * 1024 or not content.endswith(b"\n"):
            raise ValueError("Incomplete or excessive worker trace")
        rows = [json.loads(line) for line in content.splitlines()]
        first = rows[0]
        if (first.get("event") != "bootstrap" or first.get("runtime") != authority
                or first.get("fetchDenied") is not True or first.get("providerMode") != "none"
                or first.get("contextSha256") != context["_sha256"]
                or first.get("preloadSha256") != locals_[str(ROOT / "equivalence/release-preload.mjs")]
                or trace.name != f'{first["pid"]}-{first["threadId"]}.jsonl'):
            raise ValueError("Missing exact process/worker authority")
        bootstraps.append(first)
        family_bootstraps = [row for row in rows if row.get("event") == "promotion-family-bootstrap"]
        if (len(family_bootstraps) != 1 or family_bootstraps[0].get("profile") != context["promotionApplyFamilyProfile"]
                or family_bootstraps[0].get("preloadSha256") != locals_[str(ROOT / "equivalence/promotion-apply-family-preload.mjs")]):
            raise ValueError("Missing independent family capability attestation")
        for row in rows[1:]:
            if row.get("pid") != first["pid"] or row.get("threadId") != first["threadId"]:
                raise ValueError("Trace changed producer identity")
            if row["event"] in {"rejected", "network-denied"}:
                raise ValueError("Rejected import or runtime network attempt")
            if row["event"] in {"load", "resolve-native"}:
                if row["kind"] == "release":
                    key = row["package"], row["path"]
                    if packages.get(key) != row["sha256"]:
                        raise ValueError("Unverified original import")
                    seen[key] = {"package": key[0], "path": key[1], "sha256": row["sha256"]}
                    if first["threadId"] != 0:
                        workers.setdefault(first["threadId"], set()).add(row["path"])
                elif row["kind"] == "oracle":
                    if locals_.get(row["path"]) != row["sha256"]:
                        raise ValueError("Unverified adapter import")
                else:
                    raise ValueError("The family cannot import source substitutions")
    mains = [first for first in bootstraps if first["isMainThread"]]
    if (len(bootstraps) < 2 or len(mains) != 1 or mains[0].get("ppid") != os.getpid()
            or any(first["pid"] != mains[0]["pid"] for first in bootstraps)):
        raise ValueError("Missing main process or protected original worker")
    if not any(set(PROMOTION_WORKER_ROUTE) <= loaded for loaded in workers.values()):
        raise ValueError("The actual three-part plugin-state worker route did not execute")
    validate_release_sources(runtime, list(seen.values()), required_entry="dist/short-term-promotion-MX1vHJuE.mjs")
    return {"bootstraps": bootstraps, "loaded": list(seen.values()),
            "traces": [{"path": str(p), "sha256": digest(p)} for p in sorted(directory.glob("*.jsonl"))]}


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
    report = {"kind": "promotion-apply-family-development", "acceptancePointsAwarded": 0,
              "covers": [], "fullScopePassed": False, "cases": [], "errors": []}
    try:
        node = args.node.resolve()
        authority = prepare_model_node_authority(node)
        runtime = prepare_release_runtime(args.reference.resolve(), args.release_runtime.resolve())
        bindings = prepare_promotion_apply_bindings(args.reference.resolve(), Path(runtime["runtimeRoot"]))
        report.update(node=authority, reference=runtime["reference"], initialOwnerBindings=bindings,
                      implementation=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                      sdkSourceHashes={str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / "memory_core").rglob("*.py"))},
                      adapterHashes={str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / "equivalence").iterdir())
                                     if p.suffix in {".py", ".mjs"}},
                      collectorSha256=digest(Path(__file__)))
        for case in build_cases():
            if args.case and case["id"] not in args.case:
                continue
            directory = output / case["id"]
            directory.mkdir()
            traces, evidence = directory / "traces", directory / "evidence"
            traces.mkdir()
            evidence.mkdir()
            case_path = directory / "case.json"
            write_json(case_path, case)
            profile = {"kind": "promotion-apply-family-development", "operation": case["operation"],
                       "casePath": str(case_path), "caseFileSha256": digest(case_path),
                       "caseWireSha256": CASE_HASHES[case["id"]], "nodeRuntime": authority, "acceptancePointsAwarded": 0}
            context = {"schemaVersion": 1, "kind": "release-oracle-execution", "runtime": runtime,
                       "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
                       "promotionApplyFamilyProfile": profile,
                       "allowedLocal": [{"path": str(ROOT / "equivalence" / name), "sha256": digest(ROOT / "equivalence" / name)} for name in LOCAL],
                       "traceDirectory": str(traces), "evidenceDirectory": str(evidence),
                       "stateDirectory": str(directory / "state"), "configPath": str(directory / "openclaw.json"),
                       "approvedReferenceSources": [], "fixtureSourceCaptures": []}
            context_path = directory / "context.json"
            write_json(context_path, context)
            env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
                   "NODE_OPTIONS": f'--import={ROOT / "equivalence/promotion-apply-family-preload.mjs"}',
                   "MEMORY_EQ_RELEASE_CONTEXT": str(context_path)}
            row = {"id": case["id"], "covers": [], "status": "blocked"}
            report["cases"].append(row)
            try:
                with (directory / "stdout.json").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
                    process = subprocess.run([str(node), str(ROOT / "equivalence/promotion-apply-family-entry.mjs")],
                                             env=env, cwd=ROOT, stdout=stdout, stderr=stderr, timeout=120)
                row["returncode"] = process.returncode
                native = json.loads((directory / "stdout.json").read_text())
                if not native.get("ok") or process.returncode:
                    raise ValueError(f'Native observation failed: {native.get("error")}')
                row["nativeEvidence"] = validate_traces(traces, {**context, "_sha256": digest(context_path)}, runtime, authority)
                sdk = run_family_sdk(case, evidence)
                write_json(directory / "sdk-output.json", sdk)
                row["structuralReplay"] = replay_case(case, directory)
                row["differences"] = differences(native["result"], sdk)
                row["status"] = "mismatch" if row["differences"] else "match"
            except Exception as error:
                row["error"] = {"name": type(error).__name__, "message": str(error)}
            row["artifacts"] = [{"path": str(p.relative_to(output)), "sha256": digest(p)}
                                for p in sorted(directory.rglob("*")) if p.is_file()]
            write_json(output / "report.json", report)
            print(json.dumps({"id": row["id"], "status": row["status"], "error": row.get("error"),
                              "differences": len(row.get("differences", []))}), flush=True)
        if prepare_promotion_apply_bindings(args.reference.resolve(), Path(runtime["runtimeRoot"])) != bindings:
            raise ValueError("Original owners changed during execution")
        if prepare_model_node_authority(node) != authority:
            raise ValueError("Executable changed during execution")
        prepare_release_runtime(args.reference.resolve(), args.release_runtime.resolve())
        for relative, expected in report["sdkSourceHashes"].items():
            if digest(ROOT / relative) != expected:
                raise ValueError("SDK changed during execution")
        for relative, expected in report["adapterHashes"].items():
            if digest(ROOT / relative) != expected:
                raise ValueError("Family adapters changed during execution")
        if digest(Path(__file__)) != report["collectorSha256"]:
            raise ValueError("Collector changed during execution")
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
