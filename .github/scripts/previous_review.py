"""Compare observations with the independently reviewed 122/128 decision."""
from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


REVIEW_COMMIT = "45ac3284219ac82bcec99353c5d5b896bdbae5d7"
DECISION_SHA = "411c1163d761dccad92c3ca23cfade637d6fb0a0de493948c0b12411ccadb51e"
# The four outstanding pairs come from mismatchMetadata in the authenticated assessment.
ASSESSMENT_SHA = "6be305de2bcc272f5186f9bb091d57bbb954deb761aae5fef4bcb7e5511c4994"
EVIDENCE_SHA = "9a41ebd8654ad230933da09e8b88f8b3bd9a021540d74afb020fb493251e5415"
RETRY_CASE = "query-sync-boundaries-warm-failure-natural-retry"


# Names of the original replay sections in the retained all-family assessment.
REPLAY_SECTIONS = {
    "host-turn-barrier-v4-runtime": "hostReplays",
    "forget-lineage-runtime": "lineageReplays",
    "forget-boundaries-runtime": "boundaryReplays",
    "recall-signals-runtime": "recallReplays",
    "embed-cache-lifecycle-runtime": "embeddingCacheReplays",
    "session-reset-boundaries-runtime": "sessionResetBoundariesReplays",
    "prompt-runtime-context-runtime": "promptRuntimeContextReplays",
    "prompt-history-repair-runtime": "promptHistoryRepairReplays",
    "engine.numeric-boundaries": "engineNumericReplays",
    "deep-consolidation-runtime": "deepConsolidationReplays",
}


def replay_ids(assessment, forget):
    groups = {key: assessment[section] for key, section in REPLAY_SECTIONS.items()}
    groups["forget-index-fence-v6-runtime"] = forget["cases"]
    for key, replay in assessment["appendedFamilyReplays"].items():
        if key in groups:
            raise ValueError(f"Duplicate physical replay family {key}")
        groups[key] = replay["cases"]
    ids = {key: [receipt["id"] for receipt in group] for key, group in groups.items()}
    if any(len(value) != len(set(value)) for value in ids.values()):
        raise ValueError("Duplicate physical replay of a case within one family")
    return ids


def load_baseline():
    decision_bytes = gzip.decompress(Path(__file__).with_name("baseline-122.json.gz").read_bytes())
    evidence_bytes = gzip.decompress(Path(__file__).with_name("baseline-122-evidence.json.gz").read_bytes())
    if hashlib.sha256(decision_bytes).hexdigest() != DECISION_SHA or hashlib.sha256(evidence_bytes).hexdigest() != EVIDENCE_SHA:
        raise ValueError("The previous decision or its original public-value hashes changed")
    decision, evidence = json.loads(decision_bytes), json.loads(evidence_bytes)
    hashes = evidence["mismatchHashes"]
    if list(hashes) != decision["mismatchedCaseIds"] or decision["cases"]["blocked"] != 0:
        raise ValueError("The previous case statuses do not agree with its original public-result pairs")
    for status, pairs in (("mismatched", hashes), ("matched", evidence["resolvedHistoricalHashes"])):
        expected = {cid: item["after"] for cid, item in decision["previousMismatchWholeValues"].items()
                    if item["status"] == status}
        if pairs != expected:
            raise ValueError("The historical public-value pairs disagree with the independent decision")
    if ({key: len(ids) for key, ids in evidence["originalReplayIds"].items()} != decision["physicalReplayCounts"]
            or evidence["summaryZipSha256"] != decision["archive"]["sha256"]
            or evidence["assessmentSha256"] != ASSESSMENT_SHA):
        raise ValueError("The previous physical replay inventory or archive identity changed")
    return decision, evidence


def changed_decisions(previous, current):
    if not previous.keys() <= current.keys():
        raise ValueError("A previously scored condition or family disappeared")
    if any(type(value) is not bool for value in (*previous.values(), *current.values())):
        raise ValueError("Every prior and current decision must be boolean")
    return {key: {"before": old, "after": current[key]} for key, old in previous.items() if current[key] != old}


def compare_with_baseline(metrics, rows, physical):
    """The caller has already authenticated the scope and every frozen case definition."""
    before, evidence = load_baseline()
    old_hashes = evidence["mismatchHashes"]
    for key, old_ids in evidence["originalReplayIds"].items():
        retained = set(old_ids)
        if [case_id for case_id in physical.get(key, []) if case_id in retained] != old_ids:
            raise ValueError(f"Missing, duplicated or reordered previous physical replay in {key}")
    if len(rows) < before["registeredCases"] or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Missing or duplicate case in the complete measurement")
    old_points = {item["id"]: item["verified"] for item in before["points"]}
    now_points = {item["id"]: item["verified"] for item in metrics["points"]}
    if set(now_points) != set(old_points) or len(now_points) != before["conditions"]:
        raise ValueError("The frozen 128-condition scope changed")
    point_changes = changed_decisions(old_points, now_points)
    family_changes = changed_decisions(before["families"], metrics["families"])
    if (sum(old_points.values()) != before["verified"] or sum(now_points.values()) != metrics["verified"]
            or len(old_points) != len(metrics["points"])):
        raise ValueError("Point totals disagree with individually observed decisions")

    original_rows = rows[:before["registeredCases"]]
    original_ids = {row["id"] for row in original_rows}
    if not old_hashes.keys() <= original_ids:
        raise ValueError("A case that differed in the original catalog disappeared")
    status_changes = {}
    current_statuses = Counter()
    prior_pairs = {}
    for row in original_rows:
        case_id = row["id"]
        status = row["status"]
        if status not in {"matched", "mismatched", "blocked"}:
            raise ValueError(f"Unknown status on original case {case_id}")
        old = "mismatched" if case_id in old_hashes else "matched"
        current_statuses[status] += 1
        if status != old:
            status_changes[case_id] = {"before": old, "after": status}
        if case_id in old_hashes:
            pair = row.get("publicValueSha256")
            if status != "blocked" and (not isinstance(pair, dict) or set(pair) != {"openclaw", "python"}):
                raise ValueError(f"Original public outputs missing for previously mismatched case {case_id}")
            prior_pairs[case_id] = {"status": status, "before": old_hashes[case_id], "after": pair}
    return {
        "decisionCommit": REVIEW_COMMIT, "decisionSha256": DECISION_SHA, "previousRun": before["run"],
        "previousVerified": before["verified"], "verified": metrics["verified"],
        "delta": metrics["verified"] - before["verified"],
        "gained": [i for i, change in point_changes.items() if change["after"]],
        "lost": [i for i, change in point_changes.items() if not change["after"]],
        "changedFamilyGates": family_changes,
        "newFamilyGates": {key: passed for key, passed in metrics["families"].items() if key not in before["families"]},
        "physicalReplayCounts": {key: len(ids) for key, ids in physical.items()},
        "originalRegisteredCases": len(original_rows), "originalCaseStatusesNow": dict(current_statuses),
        "originalCaseStatusChanges": status_changes, "previousMismatchWholeValues": prior_pairs,
        "addedCases": [{"id": row["id"], "status": row["status"]} for row in rows[len(original_rows):]],
    }
