"""Compare the independently sealed compact runs and inspect the warm-retry public responses."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types


DECISION = "5bd9ac41dfa66b7732a6898b6a4e02366dd836de"
REVIEW_SHA = "ad558a02524ec0b2eb12ff297984c0e9917f2f56f3417a4025efc0ec5b0cbe45"
DECISION_SHA = "c1924395d9c08255680d0868db9ef95340f980a657951f48d6735585a42543a6"
QUERY = "query-sync-boundaries-warm-failure-natural-retry"
WARM = "flush-execution-warm-index-first-recall"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decision_file(root, name, sha):
    path = f"{DECISION}:independent-review/heartbeat-home/{name}"
    data = subprocess.check_output(["git", "-C", str(root), "show", path])
    require(hashlib.sha256(data).hexdigest() == sha, f"Different archived {name}")
    return data


def load_decisions(root):
    verified_source = decision_file(root, "review.py", REVIEW_SHA)
    latest = json.loads(decision_file(root, "result.json", DECISION_SHA))
    receipt_reader = types.ModuleType("previous_heartbeat_reader")
    exec(compile(verified_source, f"{DECISION}:review.py", "exec"), receipt_reader.__dict__)
    earlier_reader, earlier = receipt_reader.load_previous(root)
    require(latest["reviewerSha256"] == REVIEW_SHA and latest["newMismatch"] == QUERY
            and latest["previousDecision"] == receipt_reader.PREVIOUS_DECISION, "Unexpected decision chain")
    return earlier_reader, earlier, latest


def authenticated_previous(prior, earlier, latest, folder):
    old_archive = prior.artifact(folder, latest["runId"], latest["measurement"], latest["summaryArtifact"]["sha256"])
    require(old_archive == latest["summaryArtifact"], "Different previous summary artifact")
    audit = prior.read(folder / "assessment.json")
    rows = audit["projection"]["cases"]
    require(audit["report"] == latest["fullReport"] and len(rows) == latest["registeredCases"], "Previous projection")
    historical = [row["id"] for row in rows if row["status"] == "mismatched"]
    require(historical == latest["mismatchedCaseIds"]
            and [cid for cid in historical if cid != QUERY] == earlier["wholeOutputAudit"]["open"],
            "Previous mismatch inventory does not reproduce both decisions")
    return rows


def compare_rows(before, current):
    status_changes = {}
    old_mismatch_changes = {}
    for old, new in zip(before, current, strict=True):
        cid = new["id"]
        require(old["id"] == cid, f"Different case order at {cid}")
        if old["status"] != new["status"]:
            status_changes[cid] = {"before": old["status"], "after": new["status"]}
        if old["status"] == "mismatched" and cid != QUERY:
            a, b = old["publicValueSha256"], new.get("publicValueSha256")
            if a != b:
                old_mismatch_changes[cid] = {"before": a, "after": b}
    return status_changes, old_mismatch_changes


def check_query_pair(pair, row, previous_native_sha, *, canonical, same_json):
    require(row["referenceMode"] == "authenticated-official-release" and row["runtimeEvidenceValidated"] is True,
            "Missing official query validation")
    require(set(pair) == {"openclaw", "python"}, "Both original public outputs are required")
    digests = {side: hashlib.sha256(canonical(value)).hexdigest() for side, value in pair.items()}
    require(row["publicValueSha256"] == digests, "Query public outputs differ from the sealed row")
    matched = same_json(pair["openclaw"], pair["python"])
    require(row["status"] == ("matched" if matched else "mismatched"), "Whole query result and row disagree")
    behavior = {}
    for side, result in pair.items():
        searches = result["searches"]
        behavior[side] = {
            phase: {"results": len(searches[phase]["results"]), "stale": searches[phase].get("stale", False),
                    "warning": searches[phase].get("warning"),
                    "firstSnippet": next((hit["snippet"] for hit in searches[phase]["results"]), None)}
            for phase in ("failedNatural", "retryNatural", "reopened")
        }
    return {"matched": matched, "wholePublicSha256": digests,
            "nativeBytesMatchPreviousFullRun": previous_native_sha == digests["openclaw"], "searches": behavior}


def review(args):
    root = args.measurement.resolve()
    sys.path[:0] = [str(root), str(root / ".github/scripts")]
    from equivalence.harness import _same_json
    prior, earlier, latest = load_decisions(root)
    previous_rows = authenticated_previous(prior, earlier, latest, args.previous_summary.resolve())
    folder = args.summary.resolve()
    source = prior.artifact(folder, args.run, args.head, args.archive_sha256)
    audit = prior.read(folder / "assessment.json")
    seal = prior.read(folder / "source-seal.json")
    require(seal["productSourceCommit"] == args.product and seal["catalogSha256"] == latest["catalogSha256"]
            and audit["completeReportParsed"] is True, "Unapproved product/catalog or incomplete report")
    rows = audit["projection"]["cases"]
    status, values = compare_rows(previous_rows, rows)
    before = next(r for r in previous_rows if r["id"] == QUERY)
    after = next(r for r in rows if r["id"] == QUERY)
    pair = audit["warmRetryPublicPair"]
    q = check_query_pair(pair, after, before["publicValueSha256"]["openclaw"], canonical=prior.canonical, same_json=_same_json)
    unexpected = [cid for cid, change in values.items() if cid != WARM or change["after"] is None
                  or change["before"]["python"] != change["after"]["python"]]
    require(prior.artifact(folder, args.run, args.head, args.archive_sha256) == source, "Summary changed during review")
    return {"kind": "warm-retry-whole-public-audit", "run": args.run, "measurement": args.head, "product": args.product,
            "summary": source, "report": audit["report"], "previousDecision": DECISION,
            "previousSummary": latest["summaryArtifact"], "registeredCases": len(rows), "changedStatuses": status,
            "otherHistoricalMismatchWholePublicChanges": values, "unexpectedHistoricalPublicChanges": unexpected,
            "previousQueryWholePublicSha256": before["publicValueSha256"], "currentQuery": q,
            "onlyWarmRetryStatusImproved": status == {QUERY: {"before": "mismatched", "after": "matched"}},
            "reviewerSha256": prior.file_sha(Path(__file__))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("measurement", "summary", "previous-summary"):
        parser.add_argument("--" + key, type=Path, required=True)
    for key in ("head", "product", "archive-sha256"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--run", type=int, required=True)
    print(json.dumps(review(parser.parse_args()), indent=2, allow_nan=False))
