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

archive.RUN = 44927413199
archive.COMMIT = "6639e46da03d6f37dc144a826c26fa2f395a5fda"
SEAL = json.loads(Path(__file__).with_name("retained_44927413199_seal.json").read_bytes())
RAW = tuple(SEAL["raw"])
if RAW[1] != "memory-contract-remainder-raw-evidence":
    raise ValueError("Expected original raw evidence")
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
    archive.require(len(raw_review["cases"]) == 39 and raw_review["matches"] == sum(r["matches"] for r in raw_review["cases"]), "Unexpected original scratch measurement")
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
                    observation = json.loads(raw)
                    fixture = Path("/") / await_root / family / cid / (side + "-fixture")
                    if family == "doctor":
                        if side == "native":
                            archive.require(observation["raw"]["env"]["OPENCLAW_HOME"] == str(fixture / "home"), "Native runtime home")
                        else:
                            from equivalence.heartbeat_scratch_review import _check_doctor_sdk
                            _check_doctor_sdk(observation["raw"], case["phases"][phase], fixture)
                    observations[side].append(observation)
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
    archive.require(report["reportSha256"] == SEAL["fullReportSha256"],
                    "Original stdout refers to a different suite")
    counts = {"run":archive.RUN, "measurement":archive.COMMIT, "rawArchive":RAW, "summary":report,
              "reviewMember":review_name,"reviewSha256":sha(package.read(review_name)), "observedCases":verified,
              "phases":sum(len(r["stdoutSha256"]) for r in raw_review["cases"]),"originalEnginesReexecuted":False}
    (target / "original-attempt.json").write_text(json.dumps(counts, indent=2))
    print("SCRATCH_READ " + json.dumps({"observed":len(verified),"matches":raw_review["matches"],
          "phases":counts["phases"],"reviewSha256":counts["reviewSha256"]}))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(dir=os.environ["RUNNER_TEMP"]) as td:
        packed=Path(td)/"original.zip"
        archive.download(RAW, packed)
        with ZipFile(packed) as recording:
            read_review(recording)
