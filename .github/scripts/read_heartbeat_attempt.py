"""Recover the recorded 39 scratch outcomes from one authenticated raw artifact."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / ".reference/previous-reader/.github/scripts")]
import restore_comparison_artifact as archive
from equivalence.heartbeat_scratch_outcomes import compare_doctor_outcomes

archive.RUN = 44913992591
archive.COMMIT = "31221e378e0cb315121cefa750a3b3dfe1c2a04c"
RAW = (14715449733, "memory-contract-remainder-raw-evidence", 2711527480,
       "35feceb5e96f047d70d0f2318aa0832378d58550506e438343bfa1a78f42b56d")
RESULTS = "home/runner/work/memory-core/memory-core/.equivalence-results"
sha = lambda data: hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode())


def read_review(package):
    names = package.namelist()
    archive.require(len(names) == len(set(names)), "Duplicate original evidence paths")
    prefix = RESULTS + "/heartbeat-scratch-outcomes/attempt-"
    [review_name] = [n for n in names if n.startswith(prefix) and n.endswith("/review.json")]
    await_root = str(PurePosixPath(review_name).parent)
    read = lambda member: json.loads(package.read(member))
    raw_review = read(review_name)
    archive.require(len(raw_review["cases"]) == 39 and raw_review["matches"] == 29, "Unexpected original scratch measurement")
    by_id = {r["id"]:r for r in raw_review["cases"]}
    verified = []
    target = Path(os.environ["RUNNER_TEMP"]) / "scratch-retained"
    target.mkdir()
    (target / "original-review.json").write_bytes(package.read(review_name))
    for family in ("store", "doctor"):
        base = await_root + "/" + family
        cases = read(base + "/cases.json")
        earlier = package.read(base + "/authentication-before.json")
        later = package.read(base + "/authentication-after.json")
        archive.require(earlier == later, "Producer authentication changed")
        (target / (family + "-authentication.json")).write_bytes(earlier)
        for case in cases:
            cid = case["id"]
            old = by_id[cid]
            observations = {"native": [], "sdk": []}
            for phase, pair in enumerate(old["stdoutSha256"]):
                for side in observations:
                    member = f"{base}/{cid}/{phase}/{side}.stdout.json"
                    raw = package.read(member)
                    archive.require(sha(raw) == pair[side], "Original stdout digest differs")
                    observations[side].append(json.loads(raw))
            archive.require(all(len(v) == len(case["phases"]) for v in observations.values()), "Phase count")
            if family == "doctor":
                observed = compare_doctor_outcomes(case, observations["native"], observations["sdk"])
            else:
                observed = {side: [p["result"] for p in captured] for side, captured in observations.items()}
            for side in observations:
                archive.require(old[side+"Sha256"] == digest(observed[side]), "Captured public bytes differ")
            if family == "doctor":
                archive.require(observed["matches"] is old["matches"], "Captured result status differs")
            output = {side: observed[side] for side in observations}
            (target / (cid + ".json")).write_text(json.dumps(output, ensure_ascii=True, separators=(",",":")))
            verified.append(cid)
            if not old["matches"]:
                print("SCRATCH_DIFFERENCE " + json.dumps({"id":cid,"first":old["firstDifference"],
                      "count":old["differenceCount"]},ensure_ascii=True), flush=True)
    archive.require(verified == list(by_id), "Original complete corpus order")
    report = read(RESULTS + "/summary/run-summary.json")
    archive.require(report["reportSha256"] == "a8aca38ff3538b315994c0e623ab2ee7a7ea9b27713462bd74f93a6a7009f748",
                    "Original stdout refers to a different suite")
    counts = {"run":archive.RUN, "measurement":archive.COMMIT, "rawArchive":RAW, "summary":report,
              "reviewMember":review_name,"reviewSha256":sha(package.read(review_name)), "observedCases":verified,
              "phases":sum(len(r["stdoutSha256"]) for r in raw_review["cases"]),"originalEnginesReexecuted":False}
    (target / "original-attempt.json").write_text(json.dumps(counts, indent=2))
    print("SCRATCH_READ " + json.dumps({"observed":len(verified),"matches":raw_review["matches"],
          "phases":counts["phases"],"reviewSha256":counts["reviewSha256"]}))


with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as td:
    packed=Path(td)/"original.zip"
    archive.download(RAW, packed)
    with ZipFile(packed) as recording:
        read_review(recording)
