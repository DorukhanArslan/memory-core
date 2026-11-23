"""Recount the fixed registry directly from the authenticated complete-run projection."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types


AUDIT = "5bd9ac41dfa66b7732a6898b6a4e02366dd836de"
QUERY = "query-sync-boundaries-runtime"


def read_blob(root, path):
    return subprocess.check_output(["git", "-C", str(root), "show", f"{AUDIT}:independent-review/heartbeat-home/{path}"])


def review(root, folder, run, head, product, archive_sha):
    sys.path[:0] = [str(root), str(root / ".github/scripts")]
    from equivalence.cases import build_cases
    from equivalence.catalog_migration import definition_authority
    import followup_seal as pin

    legacy = types.ModuleType("review_heartbeat")
    legacy_code = read_blob(root, "review.py")
    exec(compile(legacy_code, f"{AUDIT}:review.py", "exec"), legacy.__dict__)
    prior, main = legacy.load_previous(root)
    check = legacy.require
    previous = json.loads(read_blob(root, "result.json"))
    check(prior.digest(legacy_code) == previous["reviewerSha256"], "Prior reviewer identity")
    archive = prior.artifact(folder, run, head, archive_sha)
    audit, seal, after = [prior.read(folder / f"{key}.json") for key in ("assessment", "source-seal", "source-after")]
    prior.source(root, seal, after, head, pin)
    check(pin.PRODUCT == product and seal["scopeSha256"] == prior.SCOPE, "Wrong product or parity scope")
    check(audit["completeReportParsed"] is True and audit["originalEnginesExecuted"] is False, "Incomplete EOF projection")
    proj = audit["projection"]
    check(proj["reference"]["commit"] == prior.REFERENCE and proj["paidProviderCalls"] == 0
          and proj["providerCredentialsForwarded"] is False, "Reference or provider settings")
    for key, file in (("reference", "reference.json"), ("scope", "scope.json"), ("sourceMap", "source-map.json")):
        check(proj["manifestSha256"][key] == prior.file_sha(root / "equivalence" / file), f"Manifest {key}")
    check(proj["casesSha256"] == prior.file_sha(root / "equivalence/cases.py"), "Case registry source")
    end, terminal = prior.process(folder, run, audit, proj)
    defs = build_cases()
    check(len(defs) == seal["registeredCases"] == 1662 and
          prior.digest(prior.canonical(defs)) == seal["catalogSha256"] == previous["catalogSha256"] == pin.CATALOG_SHA
          and prior.digest(prior.canonical(defs[:1623])) == main["catalogSha256"]
          and definition_authority(defs, fif_version="v6") == seal["definitionMigration"], "Changed case definitions")

    rows, modes = legacy.reconstruct(root, prior, defs, proj)
    scope = prior.read(root / "equivalence/scope.json")["requirements"]
    gates, points, contracts, missing, unresolved = legacy.recount_current(prior, defs, rows, proj, scope)
    check(set(gates) == set(previous["measuredFamilyGates"]), "Wrong collection of family gates")
    states = Counter(r["status"] for r in rows)
    counts = {key: states[key] for key in ("matched", "mismatched", "blocked")}
    check(proj["summary"] == {**counts, "uncoveredAcceptance": len(missing)}, "Terminal counts differ")
    for status, key in (("mismatched", "mismatchedCaseIds"), ("blocked", "blockedCaseIds")):
        check([r["id"] for r in rows if r["status"] == status] == terminal[key], "Terminal row identities differ")

    validate = prior.specialized_receipt
    def family_receipt(key, row, receipt):
        if key == legacy.OP:
            legacy.validate_scratch(row, receipt, prior.valid_hash)
        else:
            validate(key, row, receipt)
    prior.specialized_receipt = family_receipt
    physical = prior.replays(folder, audit, rows, gates, pin.SDK_SHA, prior.file_sha(folder / "forget-family-replay.json"))
    check(physical == previous["rawReplayCounts"], "Incomplete physical replay inventory")

    qrows = [r for r in rows if r["operation"] == QUERY]
    scratch = [r for r in rows if r["operation"] == legacy.OP]
    check(len(qrows) == 8 and all(r["referenceMode"] == "authenticated-official-release"
          and r["runtimeEvidenceValidated"] is True for r in qrows), "Unauthenticated query cases")
    check(len(scratch) == 39 and sum(r["input"]["phases"] for r in scratch) == 69, "Missing heartbeat examples or phases")
    metrics = {"verified": sum(points.values()), "remaining": len(missing) + len(unresolved),
               "uncovered": len(missing), "registeredUnresolved": len(unresolved), "contracts": contracts,
               "cases": counts, "families": gates, "points": [{"id": k, "verified": v} for k, v in points.items()]}
    if audit["candidateAssessment"] is not None:
        check(audit["candidateAssessment"] == metrics, "Hosted candidate and independent recount differ")
    for field in ("observedAssessment", "observedMetrics"):
        if field in audit:
            check(audit[field] == metrics, "Hosted observation and independent recount differ")
    prior_points = previous["recountedPoints"]
    mismatched = terminal["mismatchedCaseIds"]
    check(prior.artifact(folder, run, head, archive_sha) == archive, "Artifact changed during review")
    return {"run": run, "measurement": head, "product": product, "reference": proj["reference"],
            "sdk": seal["productSdk"], "sdkTree": seal["sdkGitTree"], "catalogSha256": seal["catalogSha256"],
            "scopeSha256": seal["scopeSha256"], "archive": archive, "report": audit["report"],
            "registeredCases": len(rows), "conditions": len(points), **metrics,
            "netChange": metrics["verified"] - sum(prior_points.values()),
            "gained": [p for p in points if points[p] and not prior_points[p]],
            "lost": [p for p in points if not points[p] and prior_points[p]],
            "missing": missing, "unresolved": unresolved,
            "terminalStatus": terminal["status"], "osExit": end["actualReturnCode"], "elapsedSeconds": end["elapsedSeconds"],
            "fullScopePassed": terminal["fullScopePassed"], "engineErrors": terminal["errors"],
            "mismatchedCaseIds": mismatched, "originalEightOnly": mismatched == main["wholeOutputAudit"]["open"],
            "queryCases": {r["id"]: r["status"] for r in qrows},
            "heartbeatCases": len(scratch), "heartbeatMatched": sum(r["status"] == "matched" for r in scratch),
            "heartbeatPairedPhases": sum(r["input"]["phases"] for r in scratch),
            "appendedPhysicalReplays": physical, "originalRecoveryModes": modes,
            "assessmentStatus": audit["status"], "assessmentErrors": audit["errors"],
            "previousIndependentDecision": AUDIT, "reviewerSha256": prior.file_sha(Path(__file__))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measurement", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--archive-sha256", required=True)
    args = parser.parse_args()
    value = review(args.measurement.resolve(), args.summary.resolve(), args.run,
                   args.head, args.product, args.archive_sha256)
    print(json.dumps(value, indent=2, allow_nan=False))
