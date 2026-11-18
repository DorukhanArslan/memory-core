"""Finish the frozen comparison's assessment from its two authenticated artifacts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from restore_comparison_artifact import COMMIT, RAW, REPORT, RUN, SUMMARY, TEMPORARY, WORKSPACE, require

TOOL_ROOT = Path(__file__).resolve().parent
FROZEN_TOOLS = WORKSPACE / ".github/scripts"
ORIGINAL = WORKSPACE / ".equivalence-results/summary"
FULL = ORIGINAL.parent / "full.json"
OUTPUT = TEMPORARY / "corrected-summary"
STAGES = {
    "replay_hosts": "hostReplays", "replay_lineage": "lineageReplays", "replay_boundaries": "boundaryReplays",
    "replay_recall": "recallReplays", "replay_cache": "embeddingCacheReplays", "replay_reset": "sessionResetBoundariesReplays",
    "replay_prompt": "promptRuntimeContextReplays",
}
HISTORY = "promptHistoryRepairReplays"
FILES = {"assessment.json", "capacity.json", "comparison.stderr.log", "forget-family-replay.json", "launch.json",
         "os-exit.json", "run-summary.json", "source-after.json", "source-seal.json"}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        stream.write("\n")


def artifact(value):
    return {"id": value[0], "bytes": value[2], "sha256": value[3]}


def reuse_completed(assessor, previous):
    used = {}

    def reader(field):
        def resume(data, cases, args, *, history=False):
            key = HISTORY if history else field
            original = previous[key]
            require(key not in used and [row["id"] for row in original] == [case["id"] for case in cases]
                    and all(row.get("validated") is True and row.get("publicMatch") is True for row in original)
                    and data["report"]["sha256"] == REPORT["sha256"], "Incomplete original replay for " + key)
            used[key] = [row["id"] for row in original]
            return original
        return resume

    for function, field in STAGES.items():
        setattr(assessor, function, reader(field))
    return used


def main():
    run = int(os.environ["GITHUB_RUN_ID"])
    head = os.environ["GITHUB_SHA"]
    require(run != RUN and WORKSPACE == Path.cwd() == WORKSPACE.resolve() and TOOL_ROOT.parent.parent ==
            WORKSPACE / ".reference/review-source", "Unexpected supplemental or original checkout")
    def git(folder):
        return subprocess.check_output(["git", "-C", str(folder), "rev-parse", "HEAD"], text=True).strip()

    require(git(WORKSPACE) == COMMIT and git(TOOL_ROOT) == head, "Unexpected source revision")
    scratch = read(TEMPORARY / "restoration.json")
    require(scratch["artifactId"] == RAW[0] and scratch["archive"] == {"bytes": RAW[2], "sha256": RAW[3]}
            and scratch["summaryArtifact"] == artifact(SUMMARY) and scratch["restorationView"] == "complete"
            and FULL.stat().st_size == REPORT["bytes"] and sha(FULL) == REPORT["sha256"], "Incomplete restoration")
    require({path.name for path in ORIGINAL.iterdir()} == FILES, "Unexpected original summary inventory")
    originals = {name: sha(ORIGINAL / name) for name in sorted(FILES)}
    seal, previous = read(ORIGINAL / "source-seal.json"), read(ORIGINAL / "assessment.json")
    exit_record = read(ORIGINAL / "os-exit.json")
    require(exit_record["actualReturnCode"] == 1 and exit_record["fullReportSha256"] == REPORT["sha256"]
            and previous["status"] == "blocked" and previous["candidateAssessment"] is None
            and previous["completeReportParsed"] is True and previous["report"]["sha256"] == REPORT["sha256"]
            and previous["errors"] == [{"type": "SessionAdmissionRuntimeBindingError",
                                       "message": "A session runtime owner escaped its reviewed tree."}],
            "Unexpected original comparison or assessment status")
    sys.path[:0] = [str(FROZEN_TOOLS), str(WORKSPACE)]
    import assess_merged_comparison as assessor
    import followup_families
    import replay_archived_dreams
    import replay_archived_flush
    from equivalence import flush_plan_target
    from retained_recovery_reference_modes import read_recovery_reference_modes

    frozen = FROZEN_TOOLS / "assess_merged_comparison.py"
    require(Path(assessor.__file__).resolve() == frozen and sha(frozen) == seal["allTrackedFileHashes"][
        ".github/scripts/assess_merged_comparison.py"], "Unexpected frozen assessor")
    used = reuse_completed(assessor, previous)
    replay_archived_dreams.configure()
    family, gate, _ = followup_families.FAMILIES[flush_plan_target.OPERATION]
    followup_families.FAMILIES[flush_plan_target.OPERATION] = family, gate, replay_archived_flush.replay_flush
    OUTPUT.mkdir(exist_ok=False)
    output = OUTPUT / "assessment.json"
    node = shutil.which("node")
    require(node is not None and str(Path(node).resolve()) == exit_record["argv"][5], "Changed Node path")
    argv = [str(frozen), "--reference", str(WORKSPACE / ".reference/openclaw"), "--node", str(Path(node).resolve()),
            "--release-runtime", str(WORKSPACE / ".reference/release-runtime"), "--report", str(FULL),
            "--seal", str(ORIGINAL / "source-seal.json"), "--fif-replay", str(ORIGINAL / "forget-family-replay.json"),
            "--output", str(output)]
    invocation = [sys.executable, *sys.argv]
    code, modes = 2, {}
    try:
        modes = read_recovery_reference_modes(FULL, previous["projection"]["cases"])
        sys.argv = argv
        code = assessor.main()
        if code == 0 and (set(used) != set(STAGES.values()) | {HISTORY} or read(output)["status"] != "assessed"):
            code = 2
            raise ValueError("The original positive replay stages were not fully authenticated")
    finally:
        if not output.exists():
            write(output, {"status": "blocked", "errors": [{"message": traceback.format_exc(limit=5)}]})
        require(sha(FULL) == REPORT["sha256"] and all(sha(ORIGINAL / name) == digest for name, digest in originals.items()),
                "Original measurement or hosted summary changed during replay")
        review_sources = {p.name: sha(p) for p in sorted(TOOL_ROOT.glob("*.py"))
                          if p.name in {"restore_comparison_artifact.py", "retained_recovery_reference_modes.py",
                              "review_retained_memory.py"} or p.name.startswith("replay_archived_")}
        record = {"kind":"retained-measurement-assessment","fullComparisonExecuted":False,
                  "boundedFrozenAssessorReplays":True, "original":{"runId":RUN,"head":COMMIT,
                  "rawArtifact":artifact(RAW),"summaryArtifact":artifact(SUMMARY),"report":REPORT,
                  "summaryFiles":originals,"assessorSha256":sha(frozen),"comparisonReturnCode":exit_record["actualReturnCode"]},
                  "review":{"runId":run,"head":head,"assessorReturnCode":code,"assessmentSha256":sha(output),
                  "argv":invocation,"assessorArgv":[sys.executable,*argv],"assessorInvocation":"in-process","restoration":scratch,"recoveryReferenceModes":modes,
                  "sourceSha256":review_sources,"reusedOriginalStages":used,
                  "archiveAdapters":["dream-light-runtime","dream-rem-runtime","dream-deep-runtime",
                                     "dream-diary-publication-runtime",flush_plan_target.OPERATION]}}
        write(OUTPUT / "replay-receipt.json", record)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
