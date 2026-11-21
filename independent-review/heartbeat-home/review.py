"""Review the single measurement from its authenticated compact GitHub artifact."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types


RUN = 44927413199
HEAD = "6639e46da03d6f37dc144a826c26fa2f395a5fda"
PRODUCT = "f040ac1852a878672ff6f6ede85ebee393a8ffd6"
PREVIOUS_DECISION = "34b52d79f6082e061b8f1ce47a6ca27d407fb391"
POINT = "heartbeat.scratch.outcomes"
OP = "heartbeat-scratch-outcomes-runtime"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def blob(root, rev, name):
    return subprocess.check_output(["git", "-C", root, "show", f"{rev}:{name}"])


def load_previous(root):
    helper = blob(root, PREVIOUS_DECISION, "independent-review/review_remainder.py")
    decision = blob(root, PREVIOUS_DECISION, "independent-review/root-review.json.gz")
    require(hashlib.sha256(helper).hexdigest() == "7fae1db9b73c0b3289af299cb117f480ba1aedd1d556823843befb4f3f16f280",
            "Wrong previously reviewed evaluator")
    require(hashlib.sha256(decision).hexdigest() == "143f6e7c69b2d39d65c369dcb95a40efe817aa9ae95bdaaf32f014c368c8c94e",
            "Wrong 118-point decision")
    prior = types.ModuleType("independent_118_reviewer")
    exec(compile(helper, f"{PREVIOUS_DECISION}:independent-review/review_remainder.py", "exec"), prior.__dict__)
    return prior, json.loads(gzip.decompress(decision))


def reconstruct(root, prior, definitions, projected):
    # The original compact parser remains responsible for every original column.
    bodies = []
    scratch, modes = {}, {}
    for row in projected["cases"]:
        item = dict(row)
        if "heartbeatScratchEvidence" in item:
            scratch[row["id"]] = item.pop("heartbeatScratchEvidence")
        if "referenceMode" in item:
            mode = item.pop("referenceMode")
            require(mode in {"authenticated-official-release", "authenticated-mixed-original-source-and-release",
                             "authenticated-all-source-redaction-policy"}, "Unrecognized observed reference mode")
            modes[row["id"]] = mode
        bodies.append(item)
    rows = prior.reconstruct(definitions, {**projected, "cases": bodies})
    require(set(scratch) == {r["id"] for r in rows if r["operation"] == OP} and len(scratch) == 39,
            "Missing or unexpected heartbeat receipts")
    from equivalence import recovery_failure
    needed = set().union(*recovery_failure.OTHER_PUBLISHERS.values(),
                         {c["id"] for c in recovery_failure.build_cases()})
    recovery_modes = {}
    for row in rows:
        cid = row["id"]
        if cid in modes:
            row["referenceMode"] = modes[cid]
        if cid in scratch:
            require(row["referenceMode"] == "authenticated-official-release", "Unauthenticated scratch case")
            row["heartbeatScratchEvidence"] = scratch[cid]
        if cid in needed and row["operation"] != "index-publication":
            require(row["referenceMode"] == "authenticated-official-release", "Wrong original dependency mode")
            recovery_modes[cid] = row["referenceMode"]
    require(len(recovery_modes) == 9, "Incomplete reference modes from original full-report rows")
    return rows, recovery_modes


def validate_scratch(row, item, valid_hash):
    receipt = row["heartbeatScratchEvidence"]
    require(item == {"id": row["id"], "publicMatch": True, "receipt": receipt}
            and set(receipt) == {"id", "matches", "stdoutSha256", "nativeSha256", "sdkSha256"}
            and receipt["matches"] is True and receipt["id"] == row["input"]["fixture"]
            and row["runtimeEvidenceValidated"] is True and row["covers"] == [POINT]
            and valid_hash(receipt["nativeSha256"]) and receipt["nativeSha256"] == receipt["sdkSha256"]
            and len(receipt["stdoutSha256"]) == row["input"]["phases"], row["id"])
    for pair in receipt["stdoutSha256"]:
        require(set(pair) == {"native", "sdk"} and all(map(valid_hash, pair.values())), "Phase hashes")


def recount_current(prior, definitions, rows, projection, scope):
    """Count the observed vector even if a previously accepted family now fails."""
    from followup_families import FAMILIES, family_key
    groups, gates, point_gates = {}, {}, defaultdict(set)
    for op in sorted(prior.LEGACY | {"prompt-history-repair-runtime", "deep-consolidation-runtime", "engine.numeric-boundaries"}):
        criterion = "requirement" if op == "engine.numeric-boundaries" else "operation"
        flag = "numericEvidenceValidated" if op == "engine.numeric-boundaries" else "runtimeEvidenceValidated"
        members = [r for r in rows if r[criterion] == op]
        require(members, "Missing legacy family")
        groups[op] = members
        gates[op] = all(r["status"] == "matched" and r.get(flag) is True for r in members)
    for key, (family, field, _) in FAMILIES.items():
        candidates = [definition for definition in definitions if family_key(definition) == key]
        require(candidates == family.build_cases(), "Different suite membership: " + key)
        members = [r for r in rows if family_key(r) == key]
        groups[key] = members
        gates[key] = family.family_complete(rows)
        require(projection["catalogFamilyGates"][field] is gates[key], "Wrong reported group flag: " + key)
    for key, members in groups.items():
        for row in members:
            for point in row["covers"]:
                point_gates[point].add(key)
    outcomes, contracts, missing, unresolved = {}, Counter(), [], []
    for expected, reported in zip(scope, projection["requirements"], strict=True):
        require(expected["id"] == reported["id"] and expected["required"] == reported["required"], "Wrong contract")
        members = [r for r in rows if r["requirement"] == expected["id"]]
        require(len(members) == reported["registeredCases"], "Wrong contract case count")
        finished = 0
        for point, row in zip(expected["acceptance"], reported["acceptance"], strict=True):
            key = point["id"]
            require(key == row["id"] and key not in outcomes, "Wrong point")
            covered = [m for m in members if key in m["covers"]]
            good = [m["id"] for m in covered if m["status"] == "matched" and all(gates[g] for g in point_gates[key])]
            require(row["caseIds"] == [m["id"] for m in covered] and row["matchedCaseIds"] == good,
                    "Wrong point coverage: " + key)
            passed = bool(covered) and len(good) == len(covered)
            outcomes[key] = passed
            finished += passed
            if not passed:
                (unresolved if covered else missing).append(key)
        contracts["complete" if finished == len(expected["acceptance"]) else "partial" if finished else "pending"] += 1
    require(len(outcomes) == 128 and sum(contracts.values()) == 64, "Incomplete fixed scope")
    return gates, outcomes, dict(contracts), missing, unresolved


def review(root, folder, old_folder, archive_sha):
    sys.path[:0] = [str(root), str(root / ".github/scripts")]
    from equivalence.cases import build_cases
    from equivalence.catalog_migration import definition_authority
    import followup_seal as pin
    prior, decision = load_previous(root)
    remote = prior.artifact(folder, RUN, HEAD, archive_sha)
    old = prior.artifact(old_folder, decision["runId"], decision["comparisonCommit"], decision["remoteSummary"]["sha256"])
    require(old == decision["remoteSummary"], "Wrong previous remote summary")
    old_assessment = prior.read(old_folder / "assessment.json")
    seal, after, audit = [prior.read(folder / name) for name in ("source-seal.json", "source-after.json", "assessment.json")]
    prior.source(root, seal, after, HEAD, pin)
    require(pin.PRODUCT == PRODUCT and seal["scopeSha256"] == prior.SCOPE, "Unapproved product or scope")
    require(audit["status"] == "blocked" and audit["errors"] == [{"type": "ValueError", "message":"Previously accepted condition changed or the scratch outcome is incomplete"}] and audit["completeReportParsed"] is True
            and audit["historicalVerifiedConditions"] == 118 and audit["originalEnginesExecuted"] is False,
            "New candidate assessment did not finish")
    proj = audit["projection"]
    require(proj["reference"] == old_assessment["projection"]["reference"] and proj["reference"]["commit"] == prior.REFERENCE
            and proj["paidProviderCalls"] == 0 and proj["providerCredentialsForwarded"] is False, "Original reference")
    for key, name in (("reference","reference.json"), ("scope","scope.json"), ("sourceMap","source-map.json")):
        require(proj["manifestSha256"][key] == prior.file_sha(root / "equivalence" / name), key)
    require(proj["casesSha256"] == prior.file_sha(root / "equivalence/cases.py"), "Catalog source changed")
    end, term = prior.process(folder, RUN, audit, proj)
    defs = build_cases()
    require(len(defs) == seal["registeredCases"] == 1662 and
            prior.digest(prior.canonical(defs[:1623])) == decision["catalogSha256"] and
            prior.digest(prior.canonical(defs)) == seal["catalogSha256"] == pin.CATALOG_SHA and
            definition_authority(defs, fif_version="v6") == seal["definitionMigration"], "Exact frozen case definitions")
    rows, modes = reconstruct(root, prior, defs, proj)
    gates, points, contracts, uncovered, unresolved = recount_current(
        prior, defs, rows, proj, prior.read(root / "equivalence/scope.json")["requirements"])
    lost = "indexing.query-sync.boundaries"
    query = "query-sync-boundaries-warm-failure-natural-retry"
    require(gates == {**decision["measuredFamilyGates"], OP: True, "query-sync-boundaries-runtime": False}
            and points == {**decision["recountedPoints"], POINT: True, lost: False}, "Unexpected gain or loss")
    counts = dict(Counter(r["status"] for r in rows))
    counts.setdefault("blocked", 0)
    require(counts == {"matched": 1653, "mismatched": 9, "blocked": 0}
            and proj["summary"] == {**counts, "uncoveredAcceptance": len(uncovered)}
            and not term["blockedCaseIds"], "Unexpected complete case totals")
    expected = {"verified": sum(points.values()), "remaining": len(uncovered)+len(unresolved),
                "uncovered": len(uncovered), "registeredUnresolved": len(unresolved), "contracts": contracts,
                "cases": counts, "families": gates, "points": [{"id": k, "verified": v} for k,v in points.items()]}
    require(audit["candidateAssessment"] is None and "deltaFromPreviousHosted" not in audit and
            expected["verified"] == 118 and len(unresolved) == 3 and len(uncovered) == 7,
            "The rejected candidate was not a 119-point measurement")
    old_rows = old_assessment["projection"]["cases"]
    require([(r["id"],r["status"]) for r in rows[:1623]] == [(r["id"], "mismatched" if r["id"] == query else r["status"]) for r in old_rows],
            "A further previously observed case status changed")
    changes = {}
    for row, before in zip(rows[:1623], old_rows, strict=True):
        if row["id"] != query and row["status"] == "mismatched" and row["publicValueSha256"] != before["publicValueSha256"]:
            require(row["id"] == prior.WARM and row["covers"] == [] and
                    row["publicValueSha256"]["python"] == before["publicValueSha256"]["python"], "Unexpected whole output change")
            changes[row["id"]] = [before["publicValueSha256"], row["publicValueSha256"]]
    diffs = [r["id"] for r in rows if r["status"] == "mismatched"]
    require([i for i in diffs if i != query] == decision["wholeOutputAudit"]["open"] and diffs == term["mismatchedCaseIds"], "Unexpected other mismatches")
    # Extend the immutable per-family reader with exactly the one new receipt format.
    previous_check = prior.specialized_receipt
    def check_family(family, definition, receipt):
        if family == OP:
            validate_scratch(definition, receipt, prior.valid_hash)
        else:
            previous_check(family, definition, receipt)
    prior.specialized_receipt = check_family
    physical = prior.replays(folder, audit, rows, gates, pin.SDK_SHA, prior.file_sha(folder / "forget-family-replay.json"))
    require(physical == {**decision["rawReplayCounts"], OP: 39}, "Unexpected physical replay inventory")
    require(prior.artifact(folder, RUN, HEAD, archive_sha) == remote, "Artifact changed during review")
    new = [r for r in rows if r["operation"] == OP]
    return {"kind": "independent-review-of-failed-119-target", "measurement": HEAD, "product": PRODUCT,
            "sdkGitTree": seal["sdkGitTree"], "sdk": seal["productSdk"], "runId": RUN, "summaryArtifact": remote,
            "reference": prior.REFERENCE, "catalogSha256": pin.CATALOG_SHA, "scopeSha256": prior.SCOPE,
            "originalCaseDefinitionsUnchanged": 1623, "cases": counts, "registeredCases": len(rows),
            "requiredConditions": len(points), "verified": sum(points.values()), "netGain": 0, "newPoint": POINT, "reopenedPoint": lost, "newMismatch": query,
            "heartbeatPhases": sum(r["input"]["phases"] for r in new), "contracts": contracts,
            "uncoveredIds": uncovered, "unresolvedIds": unresolved, "mismatchedCaseIds": diffs,
            "unchangedOldFamilyGates": sum(gates[k] is v for k,v in decision["measuredFamilyGates"].items()), "measuredFamilyGates": gates,
            "recountedPoints": points, "rawReplayCounts": physical, "wholeOutputChanges": changes,
            "originalRecoveryModesFromCompleteReport": modes,
            "fullScopePassed": proj["fullScopePassed"], "actualReturnCode": end["actualReturnCode"],
            "elapsedSeconds": end["elapsedSeconds"], "fullReport": audit["report"], "largeRawArchiveDownloaded": False,
            "reviewerSha256": prior.file_sha(Path(__file__)), "previousDecision": PREVIOUS_DECISION}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurement", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--previous-summary", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    args = parser.parse_args()
    result = review(args.measurement.resolve(), args.summary.resolve(), args.previous_summary.resolve(), args.archive_sha256)
    print(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False))
