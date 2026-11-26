"""Run one full comparison against the approved product source; never retry it."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from equivalence.cases import build_cases  # noqa: E402
from equivalence.catalog_migration import definition_authority  # noqa: E402
from equivalence.harness import _adapter_identity, _implementation_identity  # noqa: E402

from followup_seal import (CATALOG_SHA, PREVIOUS_CASES, PREVIOUS_CATALOG_SHA, PRODUCT,
                           REGISTERED_CASES, SCOPE_SHA, SDK_FILES, SDK_SHA, check_seal)

OUT = ROOT / ".equivalence-results"
SUMMARY = OUT / "summary"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def write(name, value):
    with (SUMMARY / name).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def inventory():
    return {name: digest(ROOT / name) for name in git("ls-files").splitlines()}


def main():
    check_seal()
    SUMMARY.mkdir(parents=True, exist_ok=False)
    product_root = ROOT / ".reference/product-source"
    assert git("rev-parse", "HEAD", cwd=product_root) == PRODUCT
    assert not git("status", "--porcelain", "--untracked-files=no")
    assert git("rev-parse", "HEAD:memory_core") == git("rev-parse", "HEAD:memory_core", cwd=product_root)
    implementation = _implementation_identity()
    assert implementation["sourceSha256"] == SDK_SHA and implementation["sourceFiles"] == SDK_FILES
    cases = build_cases()
    canonical = json.dumps(cases, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    assert len(cases) == REGISTERED_CASES and REGISTERED_CASES >= PREVIOUS_CASES and hashlib.sha256(canonical.encode()).hexdigest() == CATALOG_SHA
    prefix = json.dumps(cases[:PREVIOUS_CASES], sort_keys=True, ensure_ascii=True,
                        separators=(",", ":"), allow_nan=False).encode()
    assert hashlib.sha256(prefix).hexdigest() == PREVIOUS_CATALOG_SHA
    assert digest(ROOT / "equivalence/scope.json") == SCOPE_SHA
    tracked, adapters = inventory(), _adapter_identity()
    seal = {"kind": "approved-product-comparison-source-seal", "implementation": implementation,
            "productSourceCommit": PRODUCT, "productSdk": {"sourceSha256": SDK_SHA, "sourceFiles": SDK_FILES},
            "sdkGitTree": git("rev-parse", "HEAD:memory_core"), "allTrackedFileHashes": tracked,
            "adapters": adapters, "scopeSha256": SCOPE_SHA, "catalogSha256": CATALOG_SHA,
            "registeredCases": len(cases), "definitionMigration": definition_authority(cases, fif_version="v6"),
            "previousCatalog": {"registeredCases": PREVIOUS_CASES, "sha256": PREVIOUS_CATALOG_SHA,
                                "completePrefixUnchanged": True},
            "sdkBytesEqualProductSource": True, "sealedAt": datetime.now(timezone.utc).isoformat()}
    write("source-seal.json", seal)
    scratch = Path(os.environ["RUNNER_TEMP"]) / ("memory-core-once-" + os.environ["GITHUB_RUN_ID"])
    scratch.mkdir(exist_ok=False)
    free = shutil.disk_usage(scratch).free
    write("capacity.json", {"freeBytesAfterDependencies": free, "requiredFreeBytes": 15 * 1024**3,
                            "scratch": str(scratch), "thresholdIsNotAnUpperBound": True})
    assert free >= 15 * 1024**3, "Insufficient free disk; no original engine was started"
    env = dict(os.environ, TMPDIR=str(scratch))
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY",
                "MEMORY_CORE_LIVE_OPENAI", "MEMORY_CORE_DEMO_OPENAI_API_KEY",
                "MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY", "OPENCLAW_ORACLE_REPO"):
        env[key] = ""
    env.pop("NODE_PATH", None)
    node = str(Path(shutil.which("node")).resolve())
    argv = [sys.executable, "scripts/check_equivalence.py", "--reference", ".reference/openclaw",
            "--node", node, "--release-runtime", ".reference/release-runtime",
            "--report", ".equivalence-results/full.json"]
    started = time.monotonic()
    launch = {"kind": "single-full-comparison-launch", "argv": argv, "cwd": str(ROOT),
              "startedAt": datetime.now(timezone.utc).isoformat(), "tmpdir": str(scratch),
              "sourceSealSha256": digest(SUMMARY / "source-seal.json"), "automaticRetry": False}
    with (SUMMARY / "run-summary.json").open("xb") as stdout, (SUMMARY / "comparison.stderr.log").open("xb") as stderr:
        process = subprocess.Popen(argv, cwd=ROOT, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        write("launch.json", {**launch, "pid": process.pid})
        while process.poll() is None:
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                print(json.dumps({"comparisonRunning": True, "elapsedSeconds": round(time.monotonic() - started),
                                  "freeBytes": shutil.disk_usage(scratch).free}), flush=True)
    code = process.returncode
    write("os-exit.json", {**launch, "actualReturnCode": code,
                           "finishedAt": datetime.now(timezone.utc).isoformat(),
                           "elapsedSeconds": time.monotonic() - started,
                           "stdoutSha256": digest(SUMMARY / "run-summary.json"),
                           "stderrSha256": digest(SUMMARY / "comparison.stderr.log"),
                           "fullReportSha256": digest(OUT / "full.json") if (OUT / "full.json").is_file() else None})
    after = {"implementation": _implementation_identity(), "adapters": _adapter_identity(),
             "allTrackedFileHashes": inventory()}
    write("source-after.json", after)
    assert after == {key: seal[key] for key in after}, "Source changed during the full comparison"
    print(json.dumps({"actualReturnCode": code, "sourceUnchanged": True}), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
