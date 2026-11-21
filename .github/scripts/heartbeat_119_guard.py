"""Bind the new measurement to the complete independent 118-point decision."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path


POINT = "heartbeat.scratch.outcomes"
BASELINE_SHA256 = "143f6e7c69b2d39d65c369dcb95a40efe817aa9ae95bdaaf32f014c368c8c94e"


def baseline():
    raw = Path(__file__).with_name("baseline-118-review.json.gz").read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError("Independent baseline-118 review changed")
    return json.loads(gzip.decompress(raw))


def verify_previous_cases(metrics, data, prefix_size):
    accepted = baseline()
    if prefix_size != accepted["registeredCases"] or len(data["cases"]) != prefix_size + 39:
        raise ValueError("Expected 1,623 original cases and 39 scratch cases")
    before = accepted["recountedPoints"]
    current = {row["id"]: row["verified"] for row in metrics["points"]}
    if current != {**before, POINT: True} or metrics["verified"] != 119:
        raise ValueError("Previously accepted condition changed or the scratch outcome is incomplete")
    prior_families = accepted["measuredFamilyGates"]
    if metrics["families"] != {**prior_families, "heartbeat-scratch-outcomes-runtime": True}:
        raise ValueError("Previously accepted family changed or scratch family is incomplete")
    rows = data["cases"]
    cases = metrics["cases"]
    if any(row["covers"] != [POINT] or row["status"] != "matched" for row in rows[prefix_size:]):
        raise ValueError("A required scratch outcome is missing, differs, or claims another condition")
    differences = check_baseline_rows(rows[:prefix_size], accepted)
    if cases != {"matched": 1654, "mismatched": 8, "blocked": 0}:
        raise ValueError("Unexpected full case status counts")
    return {"baselineRun": accepted["runId"], "baselineReviewSha256": BASELINE_SHA256,
            "baselineReportSha256": accepted["reportSha256"], "preservedConditions": accepted["verified"],
            "preservedFamilyGates": len(prior_families), "preservedCaseDefinitions": prefix_size,
            "remainingDifferences": differences, "newPoint": POINT, "newMatchedCases": 39}


def check_baseline_rows(rows, accepted):
    if len(rows) != accepted["registeredCases"] or any(row["status"] not in {"matched", "mismatched"} for row in rows):
        raise ValueError("Incomplete baseline case coverage")
    differences = [row["id"] for row in rows if row["status"] == "mismatched"]
    if differences != accepted["wholeOutputAudit"]["open"]:
        raise ValueError("A previous case changed status")
    return differences
