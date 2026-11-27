"""Recount a complete OpenClaw measurement and audit the ordinary read-only flush preparation boundary."""
import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace

BASE_REVIEW = "95b108408409255cdf36c92ef627b50b0062440b"
BASE_DIR = "independent-review/interrupted-turn"
BASE_RUN = 45987128881
BASE_DECISION = "0dd1543d0b46f56080422bc945c22a2e1fff345040150a0d01694fbb7ee2121d"
BASE_READER = "b08c3af0626db5711365cbc200daad45c35c66ec7c18486be747029664a82cc1"
EXISTING = 1667
OP = "flush-plan-target-runtime"
POINT = "flush.plan-target.boundaries"
OUTCOME = "flush.plan-target.outcomes"
NEW_IDS = ["flush-plan-boundary-" + tag for tag in ("two-names-read-only", "single-name-read-only", "occupied-daily-directory")]
NEW_CATALOG_SHA = "468d7a01efc95c1c75cfb102e029f2b55a31c170fd41b08e42ff37f1a5ebde59"
NEW_UTF8_SHA = "c42563dd68dfae9f4c024034d67ecaa93a318759600a13a6a385df0782835c35"
LEGACY_UTF8_SHA = "dc23c90f17528f6e93699bcf884a61d234dd7a0a25fc535ce8be4395d72243cd"
HOST_UTF8_SHA = "9f267bf12f48571239cffdc724b3e85e5e5f6dd9ca7267eaedde170e0d2ab36c"
TARGET = "memory/2026-01-01.md"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utf8_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def pinned(root, name, digest):
    raw = subprocess.check_output(["git", "-C", root, "show", f"{BASE_REVIEW}:{BASE_DIR}/{name}"])
    require(hashlib.sha256(raw).hexdigest() == digest, "Pinned previous Git object differs: " + name)
    return raw


def load_previous(root, folder):
    predecessor = ModuleType("interrupted_turn_review")
    exec(compile(pinned(root, "review_interrupted_turn.py", BASE_READER), "review_interrupted_turn.py", "exec"), predecessor.__dict__)
    original = ModuleType("remaining_memory_review")
    blob = predecessor.baseline_blob(root, "review_remaining.py", predecessor.BASE_READER)
    exec(compile(blob, "review_remaining.py", "exec"), original.__dict__)
    search_dir = original.BASE_REVIEW + ":independent-review/search-retry/"
    search = original.module(original.immutable(root, search_dir + "review_search.py", original.PREPARATION_SOURCE), "retry")
    raw = search.read_blob(root, "review.py")
    require(hashlib.sha256(raw).hexdigest() == original.PREVIOUS_READER, "Predecessor source digest")
    legacy = original.module(raw, "heartbeat_review")
    prior, _ = legacy.load_previous(root)
    decision = json.loads(pinned(root, f"independent-{BASE_RUN}.json", BASE_DECISION))
    require(prior.artifact(folder, BASE_RUN, decision["measurement"], decision["archive"]["sha256"]) == decision["archive"],
            "Original 123 archive differs")
    audit = prior.read(folder / "assessment.json")
    require(audit["report"] == decision["report"] and len(audit["projection"]["cases"]) == decision["registeredCases"] == EXISTING
            and decision["conditions"] == 128 and decision["verified"] == 123
            and all(decision[k] == v for k, v in audit["observedAssessment"].items()),
            "Original 123 report and individually authenticated decision differ")
    return predecessor, original, legacy, prior, decision, audit


def rows_from_report(p, old, legacy, prior, root, defs, audit, same_json, historical):
    proj = audit["projection"]
    compact = proj["cases"]
    require(len(compact) == len(defs) and [r["id"] for r in compact] == [d["id"] for d in defs], "Missing, repeated or reordered cases")

    def observed(compact_rows, definitions):
        result = []
        for r, d in zip(compact_rows, definitions, strict=True):
            missing = r.get("omittedDefinitionFields", [])
            require(set(missing) <= ({"diagnosticOnly", "fixtureSource"} & d.keys()) and missing == sorted(set(missing)),
                    "Unexpected original definition field omission")
            result.append({k: v for k, v in d.items() if k not in missing})
        return prior.digest(prior.canonical(result))

    require(observed(compact, defs) == proj["observedDefinitionsSha256"], "Observed original definitions differ")
    first = {**proj, "cases": compact[:EXISTING], "observedDefinitionsSha256": observed(compact[:EXISTING], defs[:EXISTING])}
    rows, modes, interrupted = p.interrupted_rows(old, legacy, prior, root, defs[:EXISTING], first,
                                                  audit["interruptedTurnPublicPairs"], same_json, False)
    extra = []
    for i, row in enumerate(compact[EXISTING:], EXISTING):
        require(set(row) <= {"id", "status", "runtimeEvidenceValidated", "referenceMode", "publicValueSha256"}
                and row["status"] in {"matched", "mismatched", "blocked"}, "Invalid compact flush row")
        extra.append({**defs[i], **row})
    require([r["id"] for r in extra] == ([] if historical else NEW_IDS), "Unexpected appended inputs")
    pairs = audit.get("flushBoundaryPublicPairs", {})
    require(set(pairs) == {r["id"] for r in extra if r["status"] != "blocked"}, "Expected all retained whole flush outputs")
    for r in extra:
        if r["id"] in pairs:
            old.public_pair(r["id"], pairs[r["id"]], r, prior, same_json)
            require(r["referenceMode"] == "authenticated-official-release" and r["runtimeEvidenceValidated"] is True,
                    "Missing original native or SDK flush evidence")
            r.update(pairs[r["id"]])
    if not historical:
        old_controls = [r for r in rows if r["requirement"] == "flush.plan-target" and r["status"] != "blocked"]
        original_pairs = audit["flushPrerequisitePublicPairs"]
        require(set(original_pairs) == {r["id"] for r in old_controls}, "Missing/excess original flush outputs")
        for r in old_controls:
            pair = original_pairs[r["id"]]
            old.public_pair(r["id"], pair, r, prior, same_json)
            r.update(pair)
    return rows + extra, modes, interrupted


def interrupted_gate(p, gates, physical, rows):
    indexed = {r["id"]: r for r in rows}
    for job, ids in p.PUBLISHERS.items():
        for ident in ids:
            row = indexed[ident]
            if (row["status"] != "matched" or (row["operation"] != "index-publication" and
                row.get("referenceMode") != "authenticated-official-release") or
                (job == "forget" and row.get("runtimeEvidenceValidated") is not True)):
                return False
    return (gates["recovery-forget-interruption-runtime"] and len(physical) == 4
            and all(v["receipt"]["publicMatch"] and all(v["verifiedBoundary"].values()) for v in physical.values()))


def expected_files(case):
    value = case["input"]
    files = {}
    for directory in value["directories"]:
        files[directory] = {"kind": "directory"}
    pair = value.get("readOnlyAlias")
    for path, data in value["files"].items():
        file = {"kind": "file", "base64": base64.b64encode(data.encode()).decode("ascii")}
        files[path] = file
        for parent in Path(path).parents:
            if parent != Path("."):
                files[str(parent)] = {"kind": "directory"}
        if pair and path == pair["target"]:
            file["linkedAs"] = sorted(pair.values())
            files[pair["alias"]] = dict(file)
    return files


def observed_flush(case, public):
    """Check what the caller and the next open actually saw; a legitimate disagreement returns False."""
    value = case["input"]
    failed = case["id"] == NEW_IDS[-1]
    if set(public) != {"provider", "plans", "selection", "candidates", "files", "outcome", "stamp", "replies"}:
        return False
    if (public["provider"] != "none" or public["files"] != expected_files(case) or len(public["plans"]) != 2
            or public["plans"][0] != public["plans"][1]):
        return False
    reserve = min(20_000, value["contextWindowTokens"] // 4)
    threshold = min(60_000, (value["contextWindowTokens"] - reserve) // 2)
    for plan in public["plans"]:
        if (plan.get("relativePath") != TARGET or plan.get("softThresholdTokens") != threshold
                or plan.get("reserveTokensFloor") != reserve or plan.get("forceFlushTranscriptBytes") != 2_097_152
                or any(not isinstance(plan.get(field), str) or not plan[field] or "NO_REPLY" not in plan[field]
                       or TARGET not in plan[field] or value["flush"][field] in plan[field] for field in ("prompt", "systemPrompt"))):
            return False
    if failed:
        return (public["candidates"] == [] and public["replies"] == [] and public["selection"] is None
                and public["outcome"] == "failed" and public["stamp"]["kind"] == "failed")
    return (public["outcome"] == "completed" and public["stamp"]["kind"] == "succeeded" and public["replies"] == ["NO_REPLY"]
            and public["candidates"] == [{"provider": "fixture-memory-model", "model": "scripted-model"}]
            and public["selection"]["provider"] == "fixture-memory-model" and public["selection"]["model"] == "scripted-model")


def observed_boundaries(prior, rows, audit):
    group = audit["appendedFamilyReplays"][POINT]
    indexed = {r["id"]: r for r in rows[EXISTING:]}
    require(group["gate"] == "flushPlanTargetBoundariesComplete" and group["scopePoints"] == [POINT]
            and [r["id"] for r in group["cases"]] == NEW_IDS, "Missing read-only flush case receipts")
    recorded = {}
    for replay in group["cases"]:
        cid = replay["id"]
        row = indexed[cid]
        answers = replay["modelReplies"]
        witnesses = replay["aliasWitnesses"]
        tools = replay["toolResults"]
        require(replay["validated"] is True and replay["publicMatch"] is (row["status"] == "matched")
                and min(replay["nativeRawFileBytes"], replay["sdkRawFileBytes"], replay["protectedWorkerThreads"],
                        replay["fixtureSourceCaptures"]) > 0
                and all(prior.valid_hash(replay[k]) for k in ("nativeRawSha256", "sdkRawSha256", "originalStdoutSha256", "originalStderrSha256"))
                and replay["outcome"] == row["openclaw"]["outcome"]
                and replay["selectedModelCandidates"] == len(row["python"]["candidates"])
                and replay["nativeModelAttempts"] == len(answers["openclaw"])
                and set(answers) == set(witnesses) == set(tools) == {"openclaw", "python"}, "Incomplete or disconnected physical receipt " + cid)
        verified = {}
        for side in ("openclaw", "python"):
            value = row[side]
            provider_calls = answers[side]
            raw_answers = [block.get("text") for message in provider_calls for block in message["content"] if block["type"] == "text"]
            require(raw_answers == value["replies"], "Whole reply differs from actual provider's emitted message")
            regular_note = True
            phases = witnesses[side]
            if cid == NEW_IDS[0]:
                require(len(phases) == 2 + len(provider_calls), "Original setup/model-entry/final alias identities missing")
                for phase in phases:
                    require(set(phase) == {"alias", "target"}, "Missing one of the two registered entry identities")
                    for entry in phase.values():
                        require(set(entry) == {"dev", "ino", "nlink"} and all(
                            isinstance(entry[k], str) and entry[k].isascii() and entry[k].isdecimal() for k in ("dev", "ino"))
                                and type(entry["nlink"]) is int, "Malformed physical file identity")
                regular_note = (all(phase == phases[0] and phase["target"] == phase["alias"] for phase in phases)
                                and int(phases[0]["target"]["ino"]) > 0 and phases[0]["target"]["nlink"] == 2)
            else:
                require(phases == [], "Unexpected two-name witness on regular or occupied control")
            expected_calls = 0 if cid == NEW_IDS[-1] else 1
            silent = (len(provider_calls) == expected_calls and all(
                msg.get("role") == "assistant" and msg.get("content") == [{"type": "text", "text": "NO_REPLY"}] for msg in provider_calls))
            verified[side] = observed_flush(row, value) and regular_note and silent and tools[side] == []
        recorded[cid] = {"status": row["status"], "verifiedBoundary": verified, "publicValueSha256": row["publicValueSha256"],
                         "receipt": replay, "public": {side: row[side] for side in ("openclaw", "python")}}
    return recorded


def archived_replays(p, old, legacy, prior, before_dir, before, source, folder, audit, rows, gates, sdk, interrupted, historical):
    def specialized(key, row, replay):
        if key == p.OP:
            require(replay == interrupted[row["id"]]["receipt"], "Interrupted-turn physical replay changed")
        else:
            prior.specialized_receipt(key, row, replay)

    extended = SimpleNamespace(**{**vars(prior), "specialized_receipt": specialized})
    counts = old.full_replay(legacy, extended, folder, audit, rows, gates, sdk)
    require(prior.file_sha(folder / "forget-family-replay.json") == audit["fifReplaySha256"], "Independent forget replay")
    old_ids = old.replay_inventory(before_dir, source, prior)
    ids = old.replay_inventory(folder, audit, prior)
    require({k: len(v) for k, v in old_ids.items()} == before["physicalReplayCounts"] and sum(map(len, old_ids.values())) == 227,
            "Original physical replay inventory")
    require({k: v for k, v in ids.items() if k != POINT} == old_ids and {k: len(v) for k, v in ids.items()} == counts,
            "Previous ordered physical replays changed")
    if not historical:
        require(ids[POINT] == NEW_IDS, "Missing new physical replay controls")
    return counts


def inspect_legacy(prior, rows, defs, audit, historical):
    selected = [(r, d) for r, d in zip(rows, defs, strict=True) if d["requirement"] == "flush.plan-target"]
    diagnostic = [(r, d) for r, d in selected if d["operation"] != OP]
    host = [(r, d) for r, d in selected if d["covers"] == [OUTCOME]]
    require(Counter(d["operation"] for r, d in diagnostic) == {"flush-contract": 70, "flush-target": 22}
            and all(d["covers"] == [] for r, d in diagnostic) and utf8_digest([d for r, d in diagnostic]) == LEGACY_UTF8_SHA
            and len(host) == 13 and utf8_digest([d for r, d in host]) == HOST_UTF8_SHA, "Existing flush authority or zero-credit cases changed")
    require(all(r.get("referenceMode") == "authenticated-official-release" and r.get("runtimeEvidenceValidated") is True
                for r, d in host if r["status"] == "matched"), "Original 13 flush observations must have authenticated real runtime")
    replayed = audit["appendedFamilyReplays"][OP]["cases"]
    require([r["id"] for r in replayed] == [r["id"] for r, d in host], "Original host replay order")
    for original, (r, d) in zip(replayed, host, strict=True):
        require(original["validated"] is True and original["publicMatch"] is (r["status"] == "matched")
                and min(original["nativeRawFileBytes"], original["sdkRawFileBytes"], original["fixtureSourceCaptures"]) > 0
                and all(prior.valid_hash(original[k]) for k in ("nativeRawSha256", "sdkRawSha256", "originalStdoutSha256", "originalStderrSha256"))
                and original["outcome"] in {"completed", "failed", "skipped"}
                and original["protectedWorkerThreads"] >= 0
                and original["nativeModelAttempts"] >= original["selectedModelCandidates"] >= 0, "Original automatic physical receipt")
    digests = {}
    old_host_digests = {}
    if not historical:
        for target, controls in ((digests, diagnostic), (old_host_digests, host)):
            for row, _ in controls:
                if row["status"] != "blocked":
                    # Each public pair has already been read, hashed and bound to the real report before scoring.
                    target[row["id"]] = row["publicValueSha256"]
    return {"diagnostics": dict(Counter(r["status"] for r, _ in diagnostic)), "automatic": dict(Counter(r["status"] for r, _ in host)),
            "diagnosticDefinitionsSha256": LEGACY_UTF8_SHA, "automaticDefinitionsSha256": HOST_UTF8_SHA,
            "diagnosticWholeResultPairsRead": len(digests), "automaticWholeResultPairsRead": len(old_host_digests),
            "diagnosticWholeResultDigestsSha256": utf8_digest(digests) if digests else None,
            "automaticWholeResultDigestsSha256": utf8_digest(old_host_digests) if old_host_digests else None}


def review(args):
    root, folder, base = (getattr(args, k).resolve() for k in ("measurement", "summary", "previous_summary"))
    sys.path[:0] = [str(root), str(root / ".github/scripts")]
    from equivalence.cases import build_cases
    from equivalence.catalog_migration import definition_authority
    from equivalence.harness import _same_json
    import followup_seal as pin

    p, old, legacy, prior, before, source = load_previous(root, base)
    historical = args.run == BASE_RUN
    archive = prior.artifact(folder, args.run, args.head, args.archive_sha256)
    audit, seal, after = [prior.read(folder / (name + ".json")) for name in ("assessment", "source-seal", "source-after")]
    prior.source(root, seal, after, args.head, pin)
    require(pin.PRODUCT == args.product and seal["scopeSha256"] == before["scopeSha256"] == prior.SCOPE, "Wrong product or immutable scope")
    if historical:
        require(before["archive"] == archive and before["product"] == args.product and before["measurement"] == args.head,
                "Need original 123 measurement and archive")
    proj = audit["projection"]
    require(audit["completeReportParsed"] is True and audit["originalEnginesExecuted"] is False and proj["kind"] == "pinned-differential-acceptance"
            and proj["reference"] == before["reference"] and proj["reference"]["commit"] == prior.REFERENCE
            and proj["paidProviderCalls"] == 0 and proj["providerCredentialsForwarded"] is False, "Original reference, providers or full-report parsing")
    for k, name in (("reference", "reference.json"), ("scope", "scope.json"), ("sourceMap", "source-map.json")):
        require(proj["manifestSha256"][k] == prior.file_sha(root / "equivalence" / name), "Original manifest " + k)
    require(proj["casesSha256"] == prior.file_sha(root / "equivalence/cases.py"), "Registered sources")
    end, term = old.original_process(folder, args.run, audit, proj, prior)
    defs = build_cases()
    require(len(defs) == seal["registeredCases"] == (EXISTING if historical else EXISTING + len(NEW_IDS))
            and prior.digest(prior.canonical(defs)) == pin.CATALOG_SHA == seal["catalogSha256"]
            and prior.digest(prior.canonical(defs[:EXISTING])) == before["catalogSha256"]
            and definition_authority(defs, fif_version="v6") == seal["definitionMigration"], "Changed catalog or migration")
    if not historical:
        previous_info = {"decisionCommit": BASE_REVIEW, "runId": BASE_RUN, "verified": before["verified"],
                         "reportSha256": before["report"]["sha256"], "assessmentSha256": prior.file_sha(base / "assessment.json"),
                         "registeredCases": EXISTING, "familyGates": before["families"]}
        require(previous_info == audit["previousComparison"] == pin.PREVIOUS_COMPARISON
                and seal["previousCatalog"] == {"registeredCases": EXISTING, "sha256": before["catalogSha256"], "completePrefixUnchanged": True}
                and utf8_digest(defs[EXISTING:]) == NEW_UTF8_SHA and seal["catalogSha256"] == NEW_CATALOG_SHA
                and seal["definitionMigration"]["flushPlanTargetBoundaryAppend"] == [
                    {"index": n, "id": row["id"], "definitionSha256": prior.digest(prior.canonical(row))}
                    for n, row in enumerate(defs[EXISTING:], EXISTING)]
                and all(r["covers"] == [POINT] and r["operation"] == OP for r in defs[EXISTING:]), "Frozen current inputs or previous source")
    rows, modes, interrupted = rows_from_report(p, old, legacy, prior, root, defs, audit, _same_json, historical)
    scope = prior.read(root / "equivalence/scope.json")["requirements"]
    gates, points, contracts, missing, unresolved = legacy.recount_current(prior, defs, rows, proj, scope)
    require(set(gates) == set(before["families"]) | (set() if historical else {POINT}), "Unexpected family inventory")
    require(gates[p.OP] is points[p.POINT] is interrupted_gate(p, gates, interrupted, rows), "Interrupted-turn observations and predecessor gate")
    counts_by_family = archived_replays(p, old, legacy, prior, base, before, source, folder, audit, rows, gates, pin.SDK_SHA, interrupted, historical)
    prior_flush = inspect_legacy(prior, rows, defs, audit, historical)
    flush = {} if historical else observed_boundaries(prior, rows, audit)
    if not historical:
        good = (prior_flush["diagnostics"] == {"matched": 92} and prior_flush["automatic"] == {"matched": 13} and gates[OP]
                and len(flush) == 3 and all(f["status"] == "matched" and all(f["verifiedBoundary"].values()) for f in flush.values()))
        require(points[POINT] is gates[POINT] is good, "Independent physical evidence and full flush condition disagree")
    states = Counter(r["status"] for r in rows)
    counts = {k: states[k] for k in ("matched", "mismatched", "blocked")}
    require(proj["summary"] == {**counts, "uncoveredAcceptance": len(missing)}, "Terminal row counts")
    for status, key in (("mismatched", "mismatchedCaseIds"), ("blocked", "blockedCaseIds")):
        require([r["id"] for r in rows if r["status"] == status] == term[key], "Terminal exceptional case identities")
    fields = ("id", "operation", "requirement", "covers", "publicValueSha256")
    require(audit["mismatchMetadata"] == [{k: r[k] for k in fields} for r in rows if r["status"] == "mismatched"],
            "Mismatch public hashes or definition details")
    status = ("blocked" if counts["blocked"] or term["errors"] else "mismatched" if counts["mismatched"] else "incomplete" if missing else "passed")
    require(term["status"] == status, "Terminal status vs. row results")
    metrics = {"verified": sum(points.values()), "remaining": len(missing) + len(unresolved), "uncovered": len(missing),
               "registeredUnresolved": len(unresolved), "contracts": contracts, "cases": counts, "families": gates,
               "points": [{"id": k, "verified": v} for k, v in points.items()]}
    require(audit["observedAssessment"] == metrics, "Hosted observation and independent decisions differ")
    require(audit.get("candidateAssessment") in (None, metrics), "Candidate assessment differs")
    if historical:
        require(all(before[k] == v for k, v in metrics.items()), "Previous individual 123 decisions cannot be reproduced")
    combined = {**before["previousMismatchWholeValues"], **before["resolvedHistoricalWholeValues"]}
    previous = {**before, "previousMismatchWholeValues": combined}
    changes, values, resolved, historical_runtime = p.historical_pairs(audit, previous, source, rows, old, prior, _same_json, False)
    previous_points = {r["id"]: r["verified"] for r in before["points"]}
    require(list(previous_points) == list(points), "Legacy point identity/order")
    gained = [k for k, current in points.items() if current and not previous_points[k]]
    lost = [k for k, current in points.items() if not current and previous_points[k]]
    delta = len(gained) - len(lost)
    require(metrics["verified"] == before["verified"] + delta, "Points gained and lost")
    if not historical:
        expected = {"decisionCommit": BASE_REVIEW, "decisionSha256": BASE_DECISION, "previousRun": BASE_RUN,
                    "previousVerified": before["verified"], "verified": metrics["verified"], "delta": delta,
                    "gained": gained, "lost": lost, "changedFamilyGates": {
                        k: {"before": v, "after": gates[k]} for k, v in before["families"].items() if v != gates[k]},
                    "newFamilyGates": {POINT: gates[POINT]}, "physicalReplayCounts": counts_by_family,
                    "originalRegisteredCases": EXISTING, "originalCaseStatusesNow": dict(Counter(r["status"] for r in rows[:EXISTING])),
                    "originalCaseStatusChanges": changes, "previousMismatchWholeValues": {
                        cid: {k: v[k] for k in ("status", "before", "after")} for cid, v in values.items()},
                    "addedCases": [{"id": r["id"], "status": r["status"]} for r in rows[EXISTING:]]}
        require(audit["changeSince123"] == expected and audit["deltaFromPreviousHosted"] == delta, "Observed delta vs independent decision vector")
    require(prior.artifact(folder, args.run, args.head, args.archive_sha256) == archive, "Archive changed during verification")
    return {"kind": "independent-full-scope-recount", "run": args.run, "measurement": args.head, "product": args.product,
            "reference": proj["reference"], "sdk": seal["productSdk"], "sdkTree": seal["sdkGitTree"], "scopeSha256": prior.SCOPE,
            "catalogSha256": seal["catalogSha256"], "archive": archive, "report": audit["report"], "conditions": len(points),
            "registeredCases": len(rows), "unchangedPrefix": EXISTING, **metrics, "netChange": delta, "gained": gained, "lost": lost,
            "uncoveredIds": missing, "unresolvedIds": unresolved, "changedOriginalCaseStatuses": changes, "previousMismatchWholeValues": values,
            "resolvedHistoricalWholeValues": resolved, "appendedCases": [{"id": r["id"], "status": r["status"], "covers": r["covers"]} for r in rows[EXISTING:]],
            "flushPrerequisites": prior_flush, "flushBoundaryObservations": flush, "interruptedTurnObservations": interrupted,
            "mismatchedCaseIds": term["mismatchedCaseIds"], "blockedCaseIds": term["blockedCaseIds"], "fullScopePassed": term["fullScopePassed"],
            "terminalStatus": status, "engineErrors": term["errors"], "actualReturnCode": end["actualReturnCode"], "elapsedSeconds": end["elapsedSeconds"],
            "physicalReplayCounts": counts_by_family, "originalRecoveryModes": modes, "historicalRuntimeChecks": historical_runtime,
            "assessmentStatus": audit["status"], "assessmentErrors": audit["errors"], "baselineDecision": BASE_REVIEW,
            "reviewerSha256": prior.file_sha(Path(__file__))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("measurement", "summary", "previous-summary"):
        parser.add_argument("--" + key, type=Path, required=True)
    for key in ("head", "product", "archive-sha256"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--run", type=int, required=True)
    print(json.dumps(review(parser.parse_args()), indent=2, allow_nan=False))
