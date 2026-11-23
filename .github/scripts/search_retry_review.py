"""Compare a fresh measurement with the independently recounted 1,662-case run."""
import gzip
import hashlib
import json
from pathlib import Path

BASELINE_COMMIT = "5bd9ac41dfa66b7732a6898b6a4e02366dd836de"
BASELINE_SHA = "c1924395d9c08255680d0868db9ef95340f980a657951f48d6735585a42543a6"
RETRY_CASE = "query-sync-boundaries-warm-failure-natural-retry"


def previous_decision():
    raw = gzip.decompress(Path(__file__).with_name("baseline-118-heartbeat-home.json.gz").read_bytes())
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA:
        raise ValueError("Independent 1,662-case heartbeat review changed")
    return json.loads(raw)


def changes_since_heartbeat(metrics, data, catalog_sha, scope_sha):
    before = previous_decision()
    if (len(data["cases"]) != before["registeredCases"] or catalog_sha != before["catalogSha256"]
            or scope_sha != before["scopeSha256"]):
        raise ValueError("The 1,662-case catalog or fixed 128-condition scope changed")

    def changes(previous, current):
        if previous.keys() != current.keys():
            raise ValueError("A frozen condition or family identity changed")
        return {key: {"before": previous[key], "after": value}
                for key, value in current.items() if value != previous[key]}

    current_points = {item["id"]: item["verified"] for item in metrics["points"]}
    old_differences = set(before["mismatchedCaseIds"])
    mismatches = {row["id"] for row in data["cases"] if row["status"] == "mismatched"}
    return {"decision": BASELINE_COMMIT, "decisionSha256": BASELINE_SHA, "runId": before["runId"],
            "previousVerified": before["verified"], "delta": metrics["verified"] - before["verified"],
            "conditions": changes(before["recountedPoints"], current_points),
            "families": changes(before["measuredFamilyGates"], metrics["families"]),
            "newMismatches": sorted(mismatches - old_differences),
            "noLongerMismatched": sorted(old_differences - mismatches)}
