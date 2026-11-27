"""Recount the original 128 conditions and inspect the next-open observations in one hosted report."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace


BASE_REVIEW = "45ac3284219ac82bcec99353c5d5b896bdbae5d7"
BASE_RUN = 45840190038
BASE_DIR = "independent-review/remaining-memory-conditions"
BASE_DECISION = "411c1163d761dccad92c3ca23cfade637d6fb0a0de493948c0b12411ccadb51e"
BASE_READER = "23a2d0a66982428998ae8926f75bcb2e2d72898673e05177dbcd486d3343e029"
OP = "interrupted-turn-recovery-runtime"
POINT = "recovery.failure-publication.boundaries"
STEMS = ("unchanged-chat", "edited-chat", "edited-new-write", "unwritten-new-write")
IDS = ["interrupted-turn-reopen-" + name for name in STEMS]
APPEND_SHA256 = "665bbc6c7f1c1576b95e7826e5a92bc098b056f9dddd926f22e34ea60f6c1d37"
PUBLISHERS = {
    "write": ("storage.atomic-writes.temp-file-fsync-eio", "storage.atomic-writes.rename-mutates-then-rejects"),
    "index": ("publication-commit-failure-reader-snapshot", "publication-post-commit-failure",
              "query-sync-boundaries-joined-failure-persistent-cold-recovery", "query-sync-boundaries-warm-failure-natural-retry"),
    "flush": ("flush-execution-cancel-before-write", "flush-execution-cancel-after-write",
              "flush-execution-model-failure-exhaustion", "flush-runtime-retry-exhaustion-and-next-cycle"),
    "consolidation": ("deep-consolidation-concurrent-edit", "dream-deep-report-publication-failure"),
    "diary": ("dream-diary-publisher-failure",),
    "forget": ("recovery-forget-before-marker", "recovery-forget-after-note"),
}
MISSING_TEXT = "[openclaw] missing tool result in session history; inserted synthetic error result for transcript repair."


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def baseline_blob(root, name, digest):
    blob = subprocess.check_output(["git", "-C", str(root), "show", f"{BASE_REVIEW}:{BASE_DIR}/{name}"])
    require(hashlib.sha256(blob).hexdigest() == digest, f"Wrong authenticated baseline source {name}")
    return blob


def baseline(root, folder):
    old = ModuleType("original_122_reviewer")
    exec(compile(baseline_blob(root, "review_remaining.py", BASE_READER), "review_remaining.py", "exec"), old.__dict__)
    decision = json.loads(baseline_blob(root, f"independent-{BASE_RUN}.json", BASE_DECISION))
    search_root = old.BASE_REVIEW + ":independent-review/search-retry/"
    search = old.module(old.immutable(root, search_root + "review_search.py", old.PREPARATION_SOURCE), "search_reviewer")
    reader = search.read_blob(root, "review.py")
    require(hashlib.sha256(reader).hexdigest() == old.PREVIOUS_READER, "Wrong predecessor evaluator")
    legacy = old.module(reader, "heartbeat_reviewer")
    prior, _ = legacy.load_previous(root)
    require(prior.artifact(folder, BASE_RUN, decision["measurement"], decision["archive"]["sha256"]) == decision["archive"],
            "Wrong original compact archive")
    source = prior.read(folder / "assessment.json")
    expected = {k: decision[k] for k in source["observedAssessment"]}
    require(source["report"] == decision["report"] and source["observedAssessment"] == expected
            and decision["conditions"] == 128 and decision["verified"] == 122
            and decision["registeredCases"] == len(source["projection"]["cases"]) == 1663,
            "Old assessment, original report and independent 122-point decision disagree")
    return old, legacy, prior, decision, source


def classify_boundary(case, value):
    """Characterize the actual whole caller output, including a genuine but incorrect result."""
    request = case["input"]
    first, followup = request["original"], request["followup"]
    old_file = first["content"] if request["cut"] == "after-write" else None
    surviving = request["externalEdit"] if request["externalEdit"] is not None else old_file
    write = followup["write"]
    missing = {"id": first["callId"], "isError": True, "content": [{"type": "text", "text": MISSING_TEXT}]}

    def stage(note, daily, results):
        return {"files": {"original": note, "independent": daily}, "originalCalls": [first["callId"]],
                "originalResults": results}

    def repairs_match(results):
        # bool is a subclass of int in Python. An actual error marker must be JSON true.
        return (isinstance(results, list) and len(results) == 1 and isinstance(results[0], dict)
                and results[0].get("isError") is True and results == [missing])

    return (isinstance(value, dict)
            and set(value) == {"cut", "reopen", "final", "firstModelOriginalResults", "newTurnToolCalls", "replies"}
            and value["cut"] == stage(old_file, None, [])
            and value["reopen"] == stage(surviving, None, [])
            and repairs_match(value["firstModelOriginalResults"])
            and value["newTurnToolCalls"] == ([write["callId"]] if write else [])
            and value["replies"] == [followup["reply"]]
            and isinstance(value["final"], dict)
            and "originalResults" in value["final"]
            and (value["final"]["originalResults"] == [] or repairs_match(value["final"]["originalResults"]))
            and value["final"] == stage(surviving, write["content"] if write else None, value["final"]["originalResults"]))


def interrupted_rows(old, legacy, prior, root, defs, proj, pairs, same_json, historical):
    compact = []
    evidence = {}
    for cell in proj["cases"]:
        row = dict(cell)
        if "interruptedTurnEvidence" in row:
            evidence[row["id"]] = row.pop("interruptedTurnEvidence")
        compact.append(row)
    rows, modes = legacy.reconstruct(root, prior, defs, {**proj, "cases": compact})
    new = rows[1663:]
    expected = [] if historical else IDS
    require([r["id"] for r in new] == expected and all(r["operation"] == OP and r["covers"] == [POINT] for r in new),
            "Wrong appended interrupted-turn cases")
    if not historical:
        require(prior.digest(prior.canonical(defs[1663:])) == APPEND_SHA256, "Unregistered interruption inputs")
    active = {r["id"] for r in new if r["status"] != "blocked"}
    require(set(pairs) == set(evidence) == active, "Extra or missing interruption whole results or physical packets")
    physical = {}
    directories = set()
    for row in new:
        cid = row["id"]
        if cid not in active:
            continue
        pair, receipt = pairs[cid], evidence[cid]
        hashes = old.public_pair(cid, pair, row, prior, same_json)
        require(receipt["id"] == cid and set(receipt) == {"id", "publicMatch", "nativeSha256", "sdkSha256", "directory"}
                and isinstance(receipt["directory"], str) and Path(receipt["directory"]).name == receipt["directory"]
                and receipt["directory"].startswith(cid + "-") and receipt["directory"] not in directories
                and all(prior.valid_hash(receipt[k]) for k in ("nativeSha256", "sdkSha256"))
                and row["runtimeEvidenceValidated"] is True and row["referenceMode"] == "authenticated-official-release"
                and receipt["publicMatch"] is (row["status"] == "matched"), "Invalid interruption receipt " + cid)
        directories.add(receipt["directory"])
        row.update(pair)
        row["interruptedTurnEvidence"] = receipt
        physical[cid] = {"receipt": receipt, "publicValueSha256": hashes,
                         "verifiedBoundary": {side: classify_boundary(row, observed) for side, observed in pair.items()},
                         "public": pair}
    return rows, modes, physical


def historical_pairs(audit, decision, source, rows, old, prior, same_json, historical):
    statuses = {item["id"]: item["status"] for item in rows}
    resolved = set(decision["previousMismatchWholeValues"]) - set(decision["mismatchedCaseIds"])
    previous = audit["previousMismatchPublicPairs"]
    retained = ({key: previous[key] for key in resolved} if historical else audit["resolvedHistoricalPublicPairs"])
    require(set(retained) == {cid for cid in resolved if statuses[cid] != "blocked"}, "Missing resolved historical outputs")
    if historical:
        previous = {k: v for k, v in previous.items() if k not in resolved}
    changes, reviewed = old.public_changes(source["projection"]["cases"], rows,
                                          {**audit, "previousMismatchPublicPairs": previous}, decision,
                                          prior, same_json, False)
    merged = {**previous, **retained}
    by_id = {r["id"]: r for r in rows}
    details = {}
    for cid, pair in retained.items():
        digests = old.public_pair(cid, pair, by_id[cid], prior, same_json)
        details[cid] = {"status": statuses[cid], "before": decision["previousMismatchWholeValues"][cid]["after"],
                        "after": digests}
    original_runtime = old.historical_runtime(rows, {**audit, "previousMismatchPublicPairs": merged}, prior)
    return changes, reviewed, details, original_runtime


def validate_physical(old, legacy, prior, baseline_dir, source, folder, audit, decision, rows, gates, sdk, physical):
    def receipt(key, row, replay):
        if key == OP:
            require(replay == physical[row["id"]]["receipt"], "Physical interruption replay differs from the original row")
        else:
            prior.specialized_receipt(key, row, replay)

    extended = SimpleNamespace(**{**vars(prior), "specialized_receipt": receipt})
    counts = old.full_replay(legacy, extended, folder, audit, rows, gates, sdk)
    require(prior.file_sha(folder / "forget-family-replay.json") == audit["fifReplaySha256"], "Forget replay digest")
    original = old.replay_inventory(baseline_dir, source, prior)
    current = old.replay_inventory(folder, audit, prior)
    require({k: len(ids) for k, ids in original.items()} == decision["physicalReplayCounts"]
            and sum(decision["physicalReplayCounts"].values()) == 223, "Wrong baseline physical replay inventory")
    require({k: v for k, v in current.items() if k != OP} == original
            and {k: len(ids) for k, ids in current.items()} == counts, "Previous physical replay identity, count or order")
    return counts


def run(args):
    root, folder, previous_dir = (getattr(args, key).resolve() for key in ("measurement", "summary", "previous_summary"))
    sys.path[:0] = [str(root), str(root / ".github/scripts")]
    from equivalence.cases import build_cases
    from equivalence.catalog_migration import definition_authority
    from equivalence.harness import _same_json
    import followup_seal as pin

    old, legacy, prior, before, source = baseline(root, previous_dir)
    archive = prior.artifact(folder, args.run, args.head, args.archive_sha256)
    audit, seal, after = [prior.read(folder / f"{k}.json") for k in ("assessment", "source-seal", "source-after")]
    prior.source(root, seal, after, args.head, pin)
    historical = args.run == BASE_RUN
    if historical:
        require(archive == before["archive"] and args.head == before["measurement"] and args.product == before["product"],
                "Baseline self-check requires the previous complete measurement")
    require(pin.PRODUCT == args.product and seal["scopeSha256"] == before["scopeSha256"] == prior.SCOPE,
            "Product or frozen scope")
    proj = audit["projection"]
    require(audit["completeReportParsed"] is True and audit["originalEnginesExecuted"] is False
            and proj["kind"] == "pinned-differential-acceptance" and proj["reference"] == before["reference"]
            and proj["reference"]["commit"] == prior.REFERENCE and proj["paidProviderCalls"] == 0
            and proj["providerCredentialsForwarded"] is False, "Incomplete or different original full comparison")
    for key, name in (("reference", "reference.json"), ("scope", "scope.json"), ("sourceMap", "source-map.json")):
        require(proj["manifestSha256"][key] == prior.file_sha(root / "equivalence" / name), "Manifest " + key)
    require(proj["casesSha256"] == prior.file_sha(root / "equivalence/cases.py"), "Original catalog source digest")
    end, terminal = old.original_process(folder, args.run, audit, proj, prior)
    defs = build_cases()
    require(len(defs) == seal["registeredCases"] == (1663 if historical else 1667)
            and prior.digest(prior.canonical(defs)) == seal["catalogSha256"] == pin.CATALOG_SHA
            and prior.digest(prior.canonical(defs[:1663])) == before["catalogSha256"]
            and definition_authority(defs, fif_version="v6") == seal["definitionMigration"], "Catalog definitions or prefix")
    if not historical:
        previous_comparison = {"decisionCommit": BASE_REVIEW, "runId": BASE_RUN, "verified": before["verified"],
                               "reportSha256": before["report"]["sha256"], "assessmentSha256": prior.file_sha(previous_dir / "assessment.json"),
                               "registeredCases": before["registeredCases"], "familyGates": before["families"]}
        require(previous_comparison == pin.PREVIOUS_COMPARISON == audit["previousComparison"]
                and seal["previousCatalog"] == {"registeredCases": before["registeredCases"], "sha256": before["catalogSha256"],
                                              "completePrefixUnchanged": True}, "Wrong comparison base")
        require(seal["definitionMigration"]["interruptedTurnRecoveryAppend"] == [
            {"index": i, "id": c["id"], "definitionSha256": prior.digest(prior.canonical(c))}
            for i, c in enumerate(defs[1663:], 1663)], "Changed order of registered new cases")

    rows, modes, physical = interrupted_rows(old, legacy, prior, root, defs, proj,
                                             audit.get("interruptedTurnPublicPairs", {}), _same_json, historical)
    scope = prior.read(root / "equivalence/scope.json")["requirements"]
    gates, points, contracts, missing, unresolved = legacy.recount_current(prior, defs, rows, proj, scope)
    require(set(gates) == set(before["families"]) | (set() if historical else {OP}), "Unexpected family inventory")
    prerequisites = {}
    if not historical:
        by_id = {r["id"]: r for r in rows[:1663]}
        for path, members in PUBLISHERS.items():
            prerequisites[path] = {}
            for cid in members:
                row = by_id[cid]
                fields = {k: row[k] for k in ("id", "requirement", "operation", "input", "covers")}
                # The whole 1663-definition prefix has already been bound to yesterday's genuine archive.
                mode = row.get("referenceMode")
                satisfied = (row["status"] == "matched" and (row["operation"] == "index-publication" or
                             mode == "authenticated-official-release") and (path != "forget" or row["runtimeEvidenceValidated"] is True))
                prerequisites[path][cid] = {"verified": satisfied, "status": row["status"], "referenceMode": mode,
                                            "definitionSha256": prior.digest(prior.canonical(fields))}
        original = "recovery-forget-interruption-runtime"
        outcomes = (gates[original] and all(v["verified"] for p in prerequisites.values() for v in p.values())
                    and len(physical) == len(IDS)
                    and all(p["receipt"]["publicMatch"] and all(p["verifiedBoundary"].values()) for p in physical.values()))
        require(gates[OP] is outcomes and points[POINT] is outcomes, "Whole interruption observations disagree with gate")
    states = Counter(r["status"] for r in rows)
    counts = {key: states[key] for key in ("matched", "mismatched", "blocked")}
    require(proj["summary"] == {**counts, "uncoveredAcceptance": len(missing)}, "Terminal case totals")
    for status, key in (("mismatched", "mismatchedCaseIds"), ("blocked", "blockedCaseIds")):
        require([r["id"] for r in rows if r["status"] == status] == terminal[key], "Terminal case identities")
    fields = ("id", "operation", "requirement", "covers", "publicValueSha256")
    require(audit["mismatchMetadata"] == [{k: r[k] for k in fields} for r in rows if r["status"] == "mismatched"],
            "Missing mismatch metadata")
    status = ("blocked" if counts["blocked"] or terminal["errors"] else "mismatched" if counts["mismatched"]
              else "incomplete" if missing else "passed")
    require(terminal["status"] == status, "Terminal status disagrees with observed rows")
    metrics = {"verified": sum(points.values()), "remaining": len(missing) + len(unresolved), "uncovered": len(missing),
               "registeredUnresolved": len(unresolved), "contracts": contracts, "cases": counts, "families": gates,
               "points": [{"id": k, "verified": v} for k, v in points.items()]}
    require(audit["observedAssessment"] == metrics, "Hosted and independent condition decisions differ")
    if audit.get("candidateAssessment") is not None:
        require(audit["candidateAssessment"] == metrics, "Hosted candidate assessment differs")
    if historical:
        require(all(before[k] == value for k, value in metrics.items()), "Previous 122 cannot be reproduced")
    counts_by_family = validate_physical(old, legacy, prior, previous_dir, source, folder, audit, before, rows, gates,
                                         pin.SDK_SHA, physical)
    changes, values, resolved, original_runtime = historical_pairs(audit, before, source, rows, old, prior, _same_json, historical)
    previous_points = {r["id"]: r["verified"] for r in before["points"]}
    require(list(previous_points) == list(points), "Previous point identity or order changed")
    gained = [k for k, value in points.items() if value and not previous_points[k]]
    lost = [k for k, value in points.items() if not value and previous_points[k]]
    delta = len(gained) - len(lost)
    require(metrics["verified"] == before["verified"] + delta, "Total disagrees with gained and lost conditions")
    if not historical:
        expected = {"decisionCommit": BASE_REVIEW, "decisionSha256": BASE_DECISION, "previousRun": BASE_RUN,
                    "previousVerified": before["verified"], "verified": metrics["verified"], "delta": delta,
                    "gained": gained, "lost": lost, "changedFamilyGates": {
                        k: {"before": v, "after": gates[k]} for k, v in before["families"].items() if v != gates[k]},
                    "newFamilyGates": {OP: gates[OP]}, "physicalReplayCounts": counts_by_family,
                    "originalRegisteredCases": 1663, "originalCaseStatusesNow": dict(Counter(r["status"] for r in rows[:1663])),
                    "originalCaseStatusChanges": changes,
                    "previousMismatchWholeValues": {cid: {k: val[k] for k in ("status", "before", "after")} for cid, val in values.items()},
                    "addedCases": [{"id": r["id"], "status": r["status"]} for r in rows[1663:]]}
        require(audit["changeSince122"] == expected and audit["deltaFromPreviousHosted"] == delta, "Hosted prior/fresh delta")
    require(prior.artifact(folder, args.run, args.head, args.archive_sha256) == archive, "Archive changed during review")
    return {"kind": "independent-full-scope-recount", "run": args.run, "measurement": args.head, "product": args.product,
            "reference": proj["reference"], "sdk": seal["productSdk"], "sdkTree": seal["sdkGitTree"],
            "scopeSha256": prior.SCOPE, "catalogSha256": seal["catalogSha256"], "archive": archive, "report": audit["report"],
            "conditions": len(points), "registeredCases": len(rows), "unchangedPrefix": 1663, **metrics,
            "netChange": delta, "gained": gained, "lost": lost, "uncoveredIds": missing, "unresolvedIds": unresolved,
            "changedOriginalCaseStatuses": changes, "previousMismatchWholeValues": values,
            "resolvedHistoricalWholeValues": resolved, "appendedCases": [{"id": r["id"], "status": r["status"], "covers": r["covers"]} for r in rows[1663:]],
            "interruptedTurnPrerequisites": prerequisites, "interruptedTurnObservations": physical, "mismatchedCaseIds": terminal["mismatchedCaseIds"], "blockedCaseIds": terminal["blockedCaseIds"],
            "fullScopePassed": terminal["fullScopePassed"], "terminalStatus": terminal["status"], "engineErrors": terminal["errors"],
            "actualReturnCode": end["actualReturnCode"], "elapsedSeconds": end["elapsedSeconds"],
            "physicalReplayCounts": counts_by_family, "originalRecoveryModes": modes, "historicalRuntimeChecks": original_runtime,
            "assessmentStatus": audit["status"], "assessmentErrors": audit["errors"], "baselineDecision": BASE_REVIEW,
            "reviewerSha256": prior.file_sha(Path(__file__))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("measurement", "summary", "previous-summary"):
        parser.add_argument("--" + key, type=Path, required=True)
    for key in ("head", "product", "archive-sha256"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--run", type=int, required=True)
    print(json.dumps(run(parser.parse_args()), indent=2, allow_nan=False))
