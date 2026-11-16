"""Run one six-case diagnostic baseline; do not award acceptance points or retry."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from equivalence.forget_lineage_cases import build_cases  # noqa: E402
from equivalence.forget_lineage_profile import FAMILY_SHA256, canonical, case_bindings  # noqa: E402
from equivalence.forget_lineage_bindings import prepare_forget_lineage_bindings  # noqa: E402
from equivalence.forget_lineage_evidence import validate_sdk  # noqa: E402
from equivalence.forget_lineage_sdk import run_forget_lineage  # noqa: E402
from equivalence.harness import (  # noqa: E402
    _adapter_identity, _implementation_identity, _oracle, _validate_reference, HarnessError,
)
from equivalence.release_runtime import prepare_release_runtime  # noqa: E402


def write(path, value):
    with path.open("x", encoding="utf8") as stream:
        json.dump(value, stream, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--release-runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cases = build_cases()
    case_bindings()
    source, adapters = _implementation_identity(), _adapter_identity()
    if source["trackedWorkingTreeDirty"]:
        raise ValueError("Commit the diagnostic sources before starting original engines")
    assert source["sourceSha256"] == "a90d994bcf005a26a4e15bf40b2e9b95f47a7a8c31cd864ed2131021d9046990"
    target = json.loads((ROOT / "equivalence/reference.json").read_text())
    reference = _validate_reference(args.reference.resolve(), args.node.resolve(), target)
    runtime = prepare_release_runtime(args.reference.resolve(), args.release_runtime.resolve())
    bindings = prepare_forget_lineage_bindings(args.reference.resolve(), Path(runtime["runtimeRoot"]))
    if shutil.disk_usage(out).free < 512 * 1024**2:
        raise ValueError("Not enough owned free space; no original engine was started")
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
                "MEMORY_CORE_LIVE_OPENAI", "MEMORY_CORE_DEMO_OPENAI_API_KEY",
                "MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY", "OPENCLAW_ORACLE_REPO"):
        os.environ[key] = ""
    report = {"kind": "forget-lineage-first-baseline", "startedAt": datetime.now(timezone.utc).isoformat(),
              "implementation": source, "adapters": adapters, "reference": reference,
              "sourceBindings": bindings, "familySha256": FAMILY_SHA256, "definitions": cases,
              "acceptancePointsAwarded": 0, "fullScopePassed": False,
              "automaticRetry": False, "cases": []}
    write(out / "launch.json", {key: value for key, value in report.items() if key != "cases"})
    start = time.monotonic()
    for case in cases:
        row = {"id": case["id"], "status": "blocked", "covers": [], "errors": []}
        print(json.dumps({"caseStarted": case["id"]}), flush=True)
        try:
            native = _oracle(args.node.resolve(), ROOT / "equivalence/release-oracle.mjs",
                             args.reference.resolve(), [case], 120, release_runtime=runtime)
            write(out / (case["id"] + ".native.json"), native)
            actual = native["results"][0]
            if actual["ok"] is not True:
                raise ValueError("The original Native diagnostic did not complete")
            row["openclaw"] = actual["result"]
            directory = out / case["id"] / "sdk"
            row["python"] = run_forget_lineage(case["input"], directory)
            validate_sdk(case, row["python"], directory)
            row["status"] = "matched" if canonical(row["openclaw"]) == canonical(row["python"]) else "mismatched"
            row["runtimeEvidenceValidated"] = True
        except Exception as error:
            row["errors"].append({"type": type(error).__name__, "message": str(error)})
            if isinstance(error, HarnessError) and hasattr(error, "rejected_evidence"):
                row["rejectedEvidence"] = error.rejected_evidence
        report["cases"].append(row)
        write(out / (case["id"] + ".result.json"), row)
        print(json.dumps({"caseCompleted": case["id"], "status": row["status"]}), flush=True)
    if (source != _implementation_identity() or adapters != _adapter_identity()
            or case_bindings() != {case["id"]: hashlib.sha256(canonical({key: case[key] for key in
                ("id", "operation", "input")})).hexdigest() for case in cases}
            or runtime != prepare_release_runtime(args.reference.resolve(), args.release_runtime.resolve())
            or reference != _validate_reference(args.reference.resolve(), args.node.resolve(), target)):
        raise ValueError("Source, definitions, reference or runtime changed during the first baseline")
    report["summary"] = {status: sum(row["status"] == status for row in report["cases"])
                         for status in ("matched", "mismatched", "blocked")}
    report.update(finishedAt=datetime.now(timezone.utc).isoformat(), durationSeconds=time.monotonic()-start,
                  sourceUnchanged=True)
    write(out / "report.json", report)
    code = 2 if report["summary"]["blocked"] else 1 if report["summary"]["mismatched"] else 0
    write(out / "os-exit.json", {"actualReturnCode": code,
        "reportSha256": hashlib.sha256((out / "report.json").read_bytes()).hexdigest()})
    print(json.dumps({"summary": report["summary"], "acceptancePointsAwarded": 0,
                      "report": str(out / "report.json"), "actualReturnCode": code}), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
