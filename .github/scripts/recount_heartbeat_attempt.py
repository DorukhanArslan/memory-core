"""Recount a completed run from its unmodified report and authenticated original scratch stdout."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path.cwd()
TMP = Path(os.environ["RUNNER_TEMP"])
SCRIPTS = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / ".github/scripts"), str(ROOT), str(ROOT / ".reference/previous-reader/.github/scripts")]
import assess_merged_comparison as assessor
from followup_seal import ACCEPTED, CATALOG_SHA, PREVIOUS_CATALOG_SHA, PRODUCT, check_seal
from heartbeat_119_guard import check_baseline_rows
from read_heartbeat_attempt import RAW, RESULTS, archive, read_review

SUMMARY = (14715736139, "memory-contract-remainder-summary", 263779,
           "2dda49ed3db30891e8d1424d5a5235d6e7b124c9cbcfdbb639d3267086b8f8e2")
FULL_HASH = "a8aca38ff3538b315994c0e623ab2ee7a7ea9b27713462bd74f93a6a7009f748"
FULL_BYTES = 1908668082
FILES = {"assessment.json", "capacity.json", "comparison.stderr.log", "forget-family-replay.json",
         "launch.json", "os-exit.json", "run-summary.json", "source-after.json", "source-seal.json"}
OP = "heartbeat-scratch-outcomes-runtime"
require = archive.require


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def restore_evidence():
    raw_zip, summary_zip = TMP / "original-44913992591.zip", TMP / "original-summary.zip"
    archive.download(SUMMARY, summary_zip)
    archive.download(RAW, raw_zip)
    local = ROOT / ".equivalence-results"
    summary = local / "summary"
    summary.mkdir(parents=True)
    with ZipFile(raw_zip) as raw, ZipFile(summary_zip) as small:
        require(set(small.namelist()) == FILES and len(small.namelist()) == len(FILES), "Summary inventory")
        for name in FILES:
            data = small.read(name)
            require(data == raw.read(f"{RESULTS}/summary/{name}"), "Independently uploaded summary differs")
            (summary/name).write_bytes(data)
        member = raw.getinfo(RESULTS + "/full.json")
        require(member.file_size == FULL_BYTES, "Full report size")
        with raw.open(member) as stream, (local/"full.json").open("xb") as out:
            shutil.copyfileobj(stream, out, 1024*1024)
        require(assessor.digest(local/"full.json") == FULL_HASH, "Original full report digest")
        read_review(raw)
    return local


def read_observed_rows(full):
    scratch = TMP / "scratch-retained"
    review = assessor.load(scratch/"original-review.json")
    receipts = {c["id"]: c for c in review["cases"]}
    seen = set()

    class ObservedReader(assessor.Reader):
        def top(self, consume):
            def rehydrate(key, value, array):
                if key == "cases" and array is True and value.get("operation") == OP:
                    fixture = value["input"]["fixture"]
                    require(fixture in receipts and fixture not in seen and
                            set(value).isdisjoint({"openclaw", "python"}) and
                            value["heartbeatScratchEvidence"] == receipts[fixture], "Missing original scratch receipt")
                    seen.add(fixture)
                    pair = assessor.load(scratch/(fixture + ".json"))
                    for side, result in pair.items():
                        require(hashlib.sha256(assessor.canonical(result)).hexdigest() == receipts[fixture][side+"Sha256"],
                                "Reopened scratch output hash")
                    value = {**value, "openclaw":pair["native"], "python":pair["sdk"]}
                consume(key, value, array)
            super().top(rehydrate)

    # The original strict parser, status checks, whole-value comparison, and EOF
    # guard all run. Only the external values omitted from the 39 rows are supplied.
    with patch.object(assessor, "Reader", ObservedReader):
        projection = assessor.project(full, *([frozenset()]*8))
    require(seen == set(receipts) and len(seen) == 39, "Incomplete scratch observation join")
    return projection


def main():
    require(assessor.ROOT == ROOT and git("rev-parse","HEAD") == archive.COMMIT, "Wrong measurement checkout")
    check_seal()
    local = restore_evidence()
    summary = local / "summary"
    seal = assessor.load(summary/"source-seal.json")
    after = assessor.load(summary/"source-after.json")
    assessor.source_unchanged(seal)
    require(after == {k:seal[k] for k in ("allTrackedFileHashes","implementation","adapters")}, "Source changed during measurement")
    require(seal["sdkGitTree"] == git("rev-parse","HEAD:memory_core") ==
            git("-C",str(ROOT/".reference/product-source"),"rev-parse","HEAD:memory_core")
            and git("-C",str(ROOT/".reference/product-source"),"rev-parse","HEAD") == PRODUCT, "Measured SDK product tree")
    original_assess = assessor.load(summary/"assessment.json")
    require(original_assess["status"] == "blocked" and original_assess["candidateAssessment"] is None and
            original_assess["errors"] == [{"type":"ValueError","message":"Mismatch omitted whole public values"}],
            "Different original assessor")
    data = read_observed_rows(local/"full.json")
    require(data["report"]["sha256"] == FULL_HASH and data["report"]["bytes"] == FULL_BYTES, "Changed full report")
    defs = assessor.build_cases()
    migration = assessor.definition_authority(defs, fif_version="v6")
    require(len(defs) == seal["registeredCases"] == 1662 and
            hashlib.sha256(assessor.canonical(defs)).hexdigest() == seal["catalogSha256"] == CATALOG_SHA and
            hashlib.sha256(assessor.canonical(defs[:1623])).hexdigest() == PREVIOUS_CATALOG_SHA and
            migration == data["definitionMigration"] == seal["definitionMigration"], "Frozen catalog")
    require(data["implementation"] == seal["implementation"] and data["adapterSha256"] == seal["adapters"] and
            data["reference"]["commit"] == "bcfc88812a35243893585dbeca87ca41b48272ca" and
            data["kind"] == "pinned-differential-acceptance" and data["mode"] == "full" and
            data["paidProviderCalls"] == 0 and not data["providerCredentialsForwarded"] and not data["errors"],
            "Full original execution identity")
    for key, name in (("reference","reference.json"),("scope","scope.json"),("sourceMap","source-map.json")):
        require(data["manifestSha256"][key] == assessor.digest(ROOT/"equivalence"/name), "Manifest changed")
    process = assessor.verify_process_exit(SimpleNamespace(seal=summary/"source-seal.json",
                                           node=Path(assessor.load(summary/"launch.json")["argv"][5])), data)
    metrics = assessor.recompute(data, defs, assessor.load(ROOT/"equivalence/scope.json")["requirements"])
    rows = data["cases"]
    check_baseline_rows(rows[:1623], ACCEPTED)
    require({p["id"]:p["verified"] for p in metrics["points"]} == ACCEPTED["recountedPoints"]
            and metrics["families"] == {**ACCEPTED["measuredFamilyGates"],OP:False} and
            metrics["verified"] == 118 and metrics["cases"] == {"matched":1644,"mismatched":18,"blocked":0},
            "Different historical decision")
    require(all(data[field] is metrics["families"][op] for op, (_,field,_) in assessor.FAMILIES.items()),
            "A named report family contradicts its recomputed gate")
    fif = assessor.load(summary/"forget-family-replay.json")
    require(fif["validCompleteBaseline"] and fif["finalAuthenticationPassed"] and fif["candidateFamilyMatched"]
            and len(fif["cases"]) == 13 and not fif["errors"] and fif["sourceReports"][0]["report"] == data["report"],
            "Missing original live forget replay")
    all_rows = [{**assessor.compact_case(row, d), **({"referenceMode":row["referenceMode"]} if "referenceMode" in row else {})}
                for row,d in zip(rows, defs, strict=True)]
    result = {"sourceRun":archive.RUN, "sourceCommit":archive.COMMIT, "product":PRODUCT, "reference":data["reference"],
              "sourceSeal":assessor.digest(summary/"source-seal.json"), "sourceAfter":assessor.digest(summary/"source-after.json"),
              "productSdk":seal["productSdk"], "sdkGitTree":seal["sdkGitTree"], "scopeSha256":seal["scopeSha256"],
              "catalogSha256":CATALOG_SHA, "prefixSha256":PREVIOUS_CATALOG_SHA, "rawArtifact":RAW, "summaryArtifact":SUMMARY,
              "process":process, "report":data["report"], "originalStatus":data["status"],"fullScopePassed":data["fullScopePassed"],
              "originalAssessment":original_assess, "originalForgetFamilyReplaySha256":assessor.digest(summary/"forget-family-replay.json"),
              "completeOriginalEof":True, "enginesReexecuted":False, "physicalFamilyBasis":
              "All 38 gates were recounted from the original full report and live validation receipts. The 39 scratch public pairs were independently rehydrated from the original native and SDK stdout. Other raw families were not physically replayed by this reader.",
              "newPointCredit":0, "metrics":metrics, "rows":all_rows, "requirements":data["requirements"],
              "mismatchIds":[r["id"] for r in rows if r["status"]=="mismatched"],
              "observedScratch":assessor.load(TMP/"scratch-retained/original-attempt.json"),
              "supplementalRun":os.environ["GITHUB_RUN_ID"], "supplementalCommit":os.environ["GITHUB_SHA"]}
    outfile = TMP/"heartbeat-historical-recount.json"
    outfile.write_bytes(assessor.canonical(result)+b"\n")
    print("RETAINED_RECOUNT " + json.dumps({"source":archive.RUN, "score":metrics["verified"],
          "cases":metrics["cases"], "gates":len(metrics["families"]), "scratchMatch":29,
          "sha256":assessor.digest(outfile), "bytes":outfile.stat().st_size}))


if __name__ == "__main__":
    main()
