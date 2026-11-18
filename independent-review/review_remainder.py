"""Recount the fixed scope from the authenticated small Actions artifact for the third cumulative comparison."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

BASE = Path("/workspace/memory-core/work/prompt-runtime-context/acceptance/recheck/full-44137396647")
BASE_REPORT = "080d8a69437fcc44db824583b5a7fb3b834be1c575220a7a000a5a28455a2dd4"
BASE_ASSESSMENT = "20af968622ab7a29339d6a11bd9cf4c363099f1bba87d3907328b64b1f9cd701"
BASE_CATALOG = "96bf1edb8fe29618d1b62792d1ffbf58423cd16f804eb490ba3f0a7c6c187ebb"
SCOPE = "a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9"
REFERENCE = "bcfc88812a35243893585dbeca87ca41b48272ca"
FILES = {"assessment.json", "capacity.json", "comparison.stderr.log", "forget-family-replay.json",
         "launch.json", "os-exit.json", "run-summary.json", "source-after.json", "source-seal.json"}
PREVIOUS_CATALOG = "d0a2b6324abc29306c635f600a46f2105b8c02585f39d9aa88e87100fddab030"
EXPECTED_FIXES = {
    "hybrid-unicode-path-collation-diagnostic",
    "redaction-policy-letter-mixed-i-engine-diagnostic", "redaction-policy-letter-repeated-capture-engine-diagnostic",
    "redaction-policy-unsupported-valid-general-property", "redaction-policy-unsupported-valid-v-direct-compiler",
    "model-session-configured-letter-mixed-i-engine-diagnostic", "model-session-configured-letter-capture-reset-engine-diagnostic",
}
F01 = "hybrid-unicode-path-collation-diagnostic"
F01_SDK = "1cee3224f3ab57e567fb26b7e0c553800fcea3634ca23087569f39a231f1044f"
DATE_DIAGNOSTIC = "engine-datetime-unverified-legacy-grammar"
DATE_PAIR = {"openclaw":"2894a4e3507c76c6ae0262b13b5627903bcb966471bcd7df529f0a1c81afdb49",
             "python":"6e70c4b4022bb834969d2d37855927adbeab4cd06c4503907cf57a8156941fe7"}
DATE_PROBES = [
    {"probe":"-000000-01-01","openclaw":{"status":"accepted","value":978307200000},
     "python":{"status":"rejected","value":1600000000001},"comparison":"mismatched","sdkGrammar":None},
    {"probe":"January 32 2026","openclaw":{"status":"rejected","value":1600000000002},
     "python":{"status":"rejected","value":1600000000002},"comparison":"uncovered","sdkGrammar":None},
]
WARM = "flush-execution-warm-index-first-recall"
LEGACY = {"host-restart-session-runtime", "host-update-isolation-runtime", "host-turn-barrier-boundaries-runtime",
          "index-identity-boundaries-runtime", "query-sync-outcomes-runtime", "query-sync-boundaries-runtime",
          "host-turn-barrier-v4-runtime", "forget-index-fence-v6-runtime", "forget-lineage-runtime",
          "forget-boundaries-runtime", "recall-signals-runtime", "embed-cache-lifecycle-runtime",
          "session-reset-boundaries-runtime", "prompt-runtime-context-runtime"}


def require(value, label):
    if not value:
        raise ValueError(label)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    from equivalence.strict_report_reader import _object, _constant, _finite
    item = json.loads(path.read_bytes(), object_pairs_hook=_object, parse_constant=_constant)
    _finite(item)
    return item


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


def artifact(folder, run_id, head, remote_sha, *, artifact_name="memory-contract-remainder-summary", files=FILES):
    # The caller supplies this checksum from the GitHub Actions artifact metadata.
    envelope = read(folder.parent / (folder.name + "-envelope.json"))
    meta = envelope["artifact"]
    require(meta["workflow_run"]["id"] == run_id and meta["workflow_run"]["head_sha"] == head
            and meta["name"] == artifact_name and meta["id"] > 0
            and meta["workflow_run"]["repository_id"] == meta["workflow_run"]["head_repository_id"] == 1393816346,
            "Wrong Actions artifact")
    archive = folder.parent / (folder.name + ".zip")
    require(re.fullmatch("[a-f0-9]{64}", remote_sha) and meta["digest"] == "sha256:" + remote_sha
            and file_sha(archive) == remote_sha and archive.stat().st_size == meta["size_in_bytes"], "Archive digest")
    with zipfile.ZipFile(archive) as z:
        require(len(z.namelist()) == len(files) and set(z.namelist()) == files, "Unexpected artifact inventory")
        for name in files:
            require((folder / name).resolve(strict=True) == folder / name
                    and (folder / name).read_bytes() == z.read(name), name)
    return {"id": meta["id"], "sha256": remote_sha, "bytes": archive.stat().st_size}


def source(root, seal, after, head, pin):
    require(git(root, "rev-parse", "HEAD") == head and not git(root, "status", "--porcelain", "--untracked-files=no"),
            "Select a clean checkout of the actual workflow commit")
    require(seal["kind"] == "approved-product-comparison-source-seal" and seal["productSourceCommit"] == pin.PRODUCT
            and seal["sdkBytesEqualProductSource"] is True and seal["implementation"] ==
            {"gitCommit": head, "trackedWorkingTreeDirty": False, "sourceFiles": pin.SDK_FILES,
             "sourceSha256": pin.SDK_SHA}, "Remote product identity")
    require(seal["productSdk"] == {k: seal["implementation"][k] for k in ("sourceSha256", "sourceFiles")}
            and seal["sdkGitTree"] == git(root, "rev-parse", head + ":memory_core")
            == git(root, "rev-parse", pin.PRODUCT + ":memory_core"), "Product and comparator SDK Git trees differ")
    require(set(after) == {"adapters", "implementation", "allTrackedFileHashes"}
            and after == {k: seal[k] for k in after}, "Source changed during the original comparison")
    tracked = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"]).decode().split("\0")[:-1]
    require(set(tracked) == set(seal["allTrackedFileHashes"]), "Tracked inventory")
    for item in tracked:
        path = root / item
        require(path.resolve(strict=True) == path and file_sha(path) == seal["allTrackedFileHashes"][item], item)
    from equivalence.harness import _adapter_identity, _implementation_identity
    require(_adapter_identity() == seal["adapters"] and _implementation_identity() == seal["implementation"],
            "Local adapter or SDK identity")
    sdk = hashlib.sha256()
    files = sorted((root / "memory_core").rglob("*.py"))
    for path in files:
        sdk.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    require(len(files) == pin.SDK_FILES and sdk.hexdigest() == pin.SDK_SHA, "All Python source bytes")


def process(folder, run_id, assessment, projection):
    launch, end, term = (read(folder / (name + ".json")) for name in ("launch", "os-exit", "run-summary"))
    report = assessment["report"]
    require(launch["kind"] == "single-full-comparison-launch" and launch["automaticRetry"] is False
            and type(launch["pid"]) is int and launch["pid"] > 0 and Path(launch["tmpdir"]).name == f"memory-core-once-{run_id}"
            and launch["sourceSealSha256"] == file_sha(folder / "source-seal.json")
            and all(end[k] == v for k, v in launch.items() if k != "pid"), "Actual single-comparison launch")
    argv = launch["argv"]
    require(len(argv) == 10 and argv[1:5] == ["scripts/check_equivalence.py", "--reference", ".reference/openclaw", "--node"]
            and Path(argv[5]).name == "node" and argv[6:] == ["--release-runtime", ".reference/release-runtime",
            "--report", ".equivalence-results/full.json"], "Original command")
    require(Path(report["path"]) == Path(launch["cwd"]) / term["report"]
            and term["report"] == argv[-1] and 0 < report["bytes"] and report["sha256"] == end["fullReportSha256"]
            == term["reportSha256"], "Full-report bytes, path or digest")
    require(assessment["comparisonProcess"] == {"pid": launch["pid"], "actualReturnCode": end["actualReturnCode"],
            "stdoutSha256": file_sha(folder / "run-summary.json"), "stderrSha256": file_sha(folder / "comparison.stderr.log"),
            "reportBytes": report["bytes"], "reportSha256": report["sha256"]}, "Hosted process replay")
    for name in ("stdoutSha256", "stderrSha256"):
        require(end[name] == assessment["comparisonProcess"][name], name)
    fields = ("mode", "status", "summary", "errors", "fullScopePassed")
    require(all(term[k] == projection[k] for k in fields) and term["status"] == "mismatched"
            and term["mode"] == "full" and not term["errors"] and term["fullScopePassed"] is False
            and end["actualReturnCode"] == 1 and end["elapsedSeconds"] > 0
            and datetime.fromisoformat(end["finishedAt"]) >= datetime.fromisoformat(launch["startedAt"]), "OS exit and stdout")
    return end, term


def reconstruct(defs, projection):
    compact = projection["cases"]
    require(len(compact) == len(defs) and len({c["id"] for c in compact}) == len(defs), "Missing/duplicate cases")
    observed, rows = [], []
    for case, receipt in zip(defs, compact, strict=True):
        require(receipt["id"] == case["id"] and receipt["status"] in {"matched", "mismatched", "blocked"},
                f"Ordered case status {case['id']}")
        omit = receipt.get("omittedDefinitionFields", [])
        require(omit == sorted(set(omit)) and set(omit) <= ({"diagnosticOnly", "fixtureSource"} & case.keys()),
                "Unexpected omitted definition fields")
        values = {k: v for k, v in case.items() if k not in omit}
        require(all(k in {"id","status","publicValueSha256","omittedDefinitionFields","datetimeBoundaryEvidence"} or k.endswith("EvidenceValidated") or k == "datetimeRegexValidated"
                    for k in receipt), "Unexpected compact case fields")
        require(all(type(v) is bool for k,v in receipt.items() if k.endswith("EvidenceValidated") or k == "datetimeRegexValidated"), "Invalid evidence flag")
        if "datetimeBoundaryEvidence" in receipt:
            require(case["id"].startswith("engine-datetime-boundary-") or case["id"] == DATE_DIAGNOSTIC,
                    "Foreign classified calendar evidence")
        pair = receipt.get("publicValueSha256")
        if pair is not None:
            # JSON numeric equality accepts equivalent integer and floating spellings; their serialized digests can differ.
            require(set(pair) == {"openclaw", "python"} and all(re.fullmatch("[a-f0-9]{64}", h) for h in pair.values())
                    and (receipt["status"] == "matched" or pair["openclaw"] != pair["python"]), "Whole-public pair hash")
        observed.append(values)
        rows.append({**values, **receipt})
    require(digest(canonical(observed)) == projection["observedDefinitionsSha256"], "Reported definition bytes differ")
    return rows


def recount(rows, defs, projection, scope, previous_families):
    from followup_families import FAMILIES, family_key
    require(set(previous_families) == LEGACY and all(previous_families.values()), "Accepted baseline gates")
    gate_points = defaultdict(set)
    gates = {}
    for op in sorted(LEGACY | {"prompt-history-repair-runtime", "deep-consolidation-runtime", "engine.numeric-boundaries"}):
        members = [r for r in rows if r["requirement"] == op] if op == "engine.numeric-boundaries" else [r for r in rows if r["operation"] == op]
        require(members, "Missing prior family " + op)
        flag = "numericEvidenceValidated" if op == "engine.numeric-boundaries" else "runtimeEvidenceValidated"
        gates[op] = all(r["status"] == "matched" and r.get(flag) is True for r in members)
        for row in members:
            for point in row["covers"]:
                gate_points[point].add(op)
    named_legacy = {"forget-lineage-runtime": "forgetLineageOutcomesFamilyComplete",
                    "forget-boundaries-runtime": "forgetBoundariesFamilyComplete",
                    "recall-signals-runtime": "recallSignalsFamilyComplete",
                    "embed-cache-lifecycle-runtime": "embeddingCacheFamilyComplete",
                    "session-reset-boundaries-runtime": "sessionResetBoundariesFamilyComplete",
                    "prompt-runtime-context-runtime": "promptRuntimeContextFamilyComplete",
                    "prompt-history-repair-runtime": "promptHistoryRepairFamilyComplete",
                    "engine.numeric-boundaries": "engineNumericFamilyComplete",
                    "deep-consolidation-runtime": "deepConsolidationFamilyComplete"}
    for operation, field in named_legacy.items():
        require(projection["catalogFamilyGates"][field] is gates[operation], "Reported legacy gate " + operation)
    for key, (family, field, _) in FAMILIES.items():
        subset = [c for c in defs if family_key(c) == key]
        require(canonical(subset) == canonical(family.build_cases()), "Incomplete frozen followup " + key)
        gates[key] = family.family_complete(rows)
        require(projection["catalogFamilyGates"][field] is gates[key], "Reported followup gate "+key)
        for case in subset:
            for point in case["covers"]:
                gate_points[point].add(key)
    require(all(gates[k] is prior for k, prior in previous_families.items()), "Previously accepted gate changed")
    reqs = projection["requirements"]
    require(len(reqs) == len(scope) == 64, "Fixed 64-contract scope")
    counters, outcomes, grouped, open_uncovered, open_registered = Counter(), {}, {}, [], []
    for req, actual in zip(scope, reqs, strict=True):
        require((actual["id"],actual["required"]) == (req["id"],req["required"]), "Contract identity")
        selected = [r for r in rows if r["requirement"] == req["id"]]
        require(len(selected) == actual["registeredCases"], "Contract case count " + req["id"])
        completed = []
        for spec, result in zip(req["acceptance"], actual["acceptance"], strict=True):
            p = spec["id"]
            require(p == result["id"] and p not in outcomes, "Acceptance point identity")
            covering = [r for r in selected if p in r["covers"]]
            matched = [r["id"] for r in covering if r["status"] == "matched" and all(gates[k] for k in gate_points[p])]
            require(result["caseIds"] == [r["id"] for r in covering] and result["matchedCaseIds"] == matched, p)
            outcomes[p] = bool(covering) and len(covering) == len(matched)
            completed.append(outcomes[p])
            if not outcomes[p]:
                (open_registered if covering else open_uncovered).append(p)
        count = sum(completed)
        status = "complete" if count == len(completed) else "partial" if count else "pending"
        grouped[req["id"]] = {"verified": count, "total": len(completed), "status": status}
        counters[status] += 1
    require(len(outcomes) == 128, "Fixed acceptance count")
    return gates, outcomes, grouped, dict(counters), open_uncovered, open_registered


def replays(folder, assessment, rows, gates, sdk, independent_fif_sha=None):
    from followup_families import FAMILIES, family_key
    legacy = [("host-turn-barrier-v4-runtime", "hostReplays", 4), ("forget-lineage-runtime", "lineageReplays", 3),
              ("forget-boundaries-runtime", "boundaryReplays", 1), ("recall-signals-runtime", "recallReplays", 6),
              ("embed-cache-lifecycle-runtime", "embeddingCacheReplays", 8),
              ("session-reset-boundaries-runtime", "sessionResetBoundariesReplays", 7),
              ("prompt-runtime-context-runtime", "promptRuntimeContextReplays", 10),
              ("prompt-history-repair-runtime", "promptHistoryRepairReplays", 8),
              ("engine.numeric-boundaries", "engineNumericReplays", 4),
              ("deep-consolidation-runtime", "deepConsolidationReplays", 7)]
    by_group = {}
    for op, field, count in legacy:
        selected = [r for r in rows if r["requirement" if op == "engine.numeric-boundaries" else "operation"] == op]
        evidence = assessment[field]
        require(len(selected) == len(evidence) == count, field)
        for row, raw in zip(selected, evidence, strict=True):
            require(raw["id"] == row["id"] and raw["validated"] is True and raw["publicMatch"] is True, field)
            if "actualOperations" in raw and "operations" in row["input"]:
                require(raw["actualOperations"] == len(row["input"]["operations"]), raw["id"])
            if field in {"promptRuntimeContextReplays", "promptHistoryRepairReplays"}:
                require(raw["nativeOnDiskRawReopened"] is True and raw["nativeRawFileBytes"] > 0 and
                        raw["nativeRawFileSha256"] == raw["nativeCollectorRawSha256"], raw["id"])
            if field == "engineNumericReplays":
                if row["operation"] == "engine-numeric-boundaries":
                    require(raw["probes"] == len(row["input"]["probes"]) and raw["publicValueSha256"]
                            == row["publicValueSha256"], raw["id"])
                else:
                    require(raw["rawWireHashesReproduced"] is True and raw["candidateCounts"] == [3,2,1,0,1], raw["id"])
            if field == "deepConsolidationReplays":
                require(all(raw[k] is True for k in ("nativeOnDiskRawReopened", "sdkOnDiskRawReopened",
                                                      "physicalStateRebuilt")), raw["id"])
            for key, val in raw.items():
                if key.endswith("Sha256") and isinstance(val, str):
                    require(re.fullmatch("[a-f0-9]{64}", val), "Invalid retained raw checksum")
        by_group[op] = count
    fif = read(folder / "forget-family-replay.json")
    [fif_report] = fif["sourceReports"]
    fif_ids = [r["id"] for r in rows if r["operation"] == "forget-index-fence-v6-runtime"]
    require(fif["finalAuthenticationPassed"] is True and fif["validCompleteBaseline"] is True
            and fif["candidateFamilyMatched"] == gates["forget-index-fence-v6-runtime"] and not fif["errors"]
            and file_sha(folder / "forget-family-replay.json") == (independent_fif_sha or assessment["fifReplaySha256"])
            and fif_report["report"] == assessment["report"] and fif_report["fixedAcceptancePoints"] == 128
            and fif_report["registeredCases"] == len(rows) and fif["authority"]["sdk"]["sourceSha256"] == sdk
            and [r["id"] for r in fif["cases"]] == fif_ids and len(fif_ids) == 13, "Complete retained forget replay")
    by_group["forget-index-fence-v6-runtime"] = len(fif_ids)
    combined = set()
    require(set(FAMILIES) == set(assessment["appendedFamilyReplays"]), "Appended family inventory")
    for key, (family, field, _) in FAMILIES.items():
        measurements = assessment["appendedFamilyReplays"][key]
        selected = [r for r in rows if family_key(r) == key]
        cases = measurements["cases"]
        require(measurements["gate"] == field and measurements["passed"] is gates[key]
                and measurements["scopePoints"] == sorted({p for r in selected for p in r["covers"]}), key)
        require([r["id"] for r in selected] == [r["id"] for r in cases]
                == [r["id"] for r in family.build_cases()], key)
        for row, item in zip(selected, cases, strict=True):
            require(item["publicMatch"] is (row["status"] == "matched") and item["id"] not in combined, "Invalid appended replay " + item["id"])
            combined.add(item["id"])
            # Most families expose native/SDK raw digest pairs. The four corpus/flush controls store
            # per-source or raw-trace digests, with their own independent archived reconstruction.
            if "nativeRawSha256" in item:
                require(all(re.fullmatch("[a-f0-9]{64}", item[k]) for k in ("nativeRawSha256", "sdkRawSha256")),
                        "Raw receipt digests " + item["id"])
            elif key == "heartbeat.turn-decisions.boundaries":
                if "sourceSha256" in item:
                    require(item["opensPerSide"] == 2 and re.fullmatch("[a-f0-9]{64}", item["sourceSha256"]), item["id"])
                else:
                    require(item["drives"] == 3 and set(item["rawDigests"]) == {"native","python"}
                            and all(re.fullmatch("[a-f0-9]{64}", h) for h in item["rawDigests"].values()), item["id"])
            else:
                specialized_receipt(key, row, item)
            if "sdkOnDiskRawReopened" in item:
                require(item["sdkOnDiskRawReopened"] is True and item["nativeOnDiskRawReopened"] is True, item["id"])
            if key == "heartbeat-turn-outcomes-runtime":
                require(item["drives"] == len(row["input"]["steps"]) and item["sqliteStoresReopened"] == 2
                        and item["originalActors"] >= 7, item["id"])
        by_group[key] = len(cases)
    require(combined == {r["id"] for r in rows[1519:]}, "Every post-1519 definition needs a bound replay")
    return by_group


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value) is not None


def specialized_receipt(family, definition, receipt):
    """Original source-only, configured, and bounded redaction families have distinct physical receipts."""
    cid = definition["id"]
    if cid == DATE_DIAGNOSTIC or cid.startswith("engine-datetime-boundary-"):
        from equivalence.datetime_boundary_evidence import PUBLIC_DIGESTS
        require(receipt["publicValueSha256"] == definition["publicValueSha256"] == PUBLIC_DIGESTS[cid]
                and canonical(receipt["classification"]) == canonical(definition["datetimeBoundaryEvidence"])
                and receipt["coverage"] == definition["covers"], "Changed measured date-boundary caller")
        cells = definition["datetimeBoundaryEvidence"]
        if cid == DATE_DIAGNOSTIC:
            require(cells == DATE_PROBES and not definition["covers"] and receipt["publicMatch"] is False,
                    "Legacy grammar difference is missing or was credited")
        else:
            require(receipt["publicMatch"] and cells and all(c["comparison"] == "matched"
                    and c["openclaw"] == c["python"] for c in cells), "Missing accepted date boundary cells")
    elif family == "engine-unicode-collation":
        from followup_unicode import MEASURED_ORIGINAL
        public = definition["publicValueSha256"]
        require(receipt["previousTie"] == {"openclaw": "5557cac38760fa4dfada60946a7009a3c9c021ba550297aaa6ba0677b2c00471",
                                          "python": F01_SDK}
                and receipt["nativePublicSha256"] == MEASURED_ORIGINAL[cid]
                and public == {"openclaw": receipt["nativePublicSha256"], "python": receipt["sdkPublicSha256"]}
                and receipt["texts"] > 0, "Invalid original Unicode ordering or text receipt")
    elif family == "engine.datetime-regex":
        if definition["operation"] == "engine-datetime-clock":
            from equivalence.datetime_regex_family import CLOCK_OWNERS
            require(receipt["owners"] == CLOCK_OWNERS and receipt["instants"] == len(definition["input"]["instants"]),
                    "Invalid original datetime observations")
        elif definition["operation"] == "promotion-ranking-runtime":
            require(receipt["validated"] is True and receipt["rawWireHashesReproduced"] is True
                    and valid_hash(receipt["sdkRawSha256"]) and valid_hash(receipt["nativeCollectorRawSha256"])
                    and bool(receipt["rawTraceSha256"]) and all(map(valid_hash, receipt["rawTraceSha256"])),
                    "Invalid original persisted timestamp ranking")
        else:
            require(receipt["exactCompilerCompared"] is True and receipt["nativeCalls"] > 0 and
                    all(valid_hash(receipt[k]) for k in ("sdkRawSha256", "sdkStderrSha256", "sdkStdoutSha256")),
                    "Invalid original configured compiler output")
    elif family == "trust.secret-redaction.boundaries":
        native = receipt["native"]
        require(valid_hash(receipt["sdkFileSha256"]) and receipt["sdk"]
                and all(valid_hash(native[k]) for k in ("originalStdoutSha256", "originalStderrSha256")),
                "Missing redaction boundary process stream")
        if definition["operation"] == "redaction-policy-source":
            require(native["boundedSourceOwners"] > 0 and native["originalCalls"] > 0
                    and native["utf16Units"] in (32768, 32769), "Missing bounded source scan")
        else:
            require(valid_hash(native["nativeRawSha256"]) and native["nativeRawBytes"] > 0
                    and native["protectedProcesses"] >= 2, "Missing original boundary process")
    elif family == "trust.configured-redaction.outcomes":
        native, sdk, engine = receipt["original"], receipt["sdk"], receipt["embeddedEngine"]
        require(engine["distribution"] == "quickjs-ng" and engine["version"] == "0.18.0.2"
                and set(engine["files"]) == {"engine","wrapper"}
                and all(valid_hash(f["sha256"]) for f in engine["files"].values())
                and valid_hash(native["streamSha256"]) and valid_hash(sdk["streamSha256"]),
                "Missing configured-redaction process bytes")
        if definition["operation"] == "redaction-policy-source":
            require(native["sourceOwners"] > 0 and native["sourceCalls"] > 0 and sdk["processes"] == 1
                    and sdk["databases"] == [], "Missing configured source policy")
        else:
            require(native["processes"] >= 3 and sdk["processes"] == 3, "Missing original configured session processes")
            for side in (native, sdk):
                images = side["databases"]
                require([d["phase"] for d in images] == ["write","continue","verify"]
                        and all(valid_hash(d["sha256"]) and d["bytes"] > 0 and d["tables"] > 0 for d in images),
                        "Missing original configured session SQLite")
    else:
        raise ValueError("Missing specific original evidence for " + cid)


def mismatch_audit(baseline, assessment, rows, independent_f14=None):
    from retained_assessment import F14
    previous = {r["id"]: r["publicValueSha256"] for r in baseline["projection"]["cases"] if r["status"] == "mismatched"}
    current = {r["id"]: r for r in rows}
    require(len(previous) == 14 and EXPECTED_FIXES <= previous.keys(), "Missing accepted mismatch")
    open_ids = [r["id"] for r in rows if r["status"] == "mismatched"]
    new_differences = []
    if DATE_DIAGNOSTIC in current:
        row = current[DATE_DIAGNOSTIC]
        require(row["operation"] == "session-projection" and row["requirement"] == "engine.datetime-regex"
                and row["covers"] == [] and row["status"] == "mismatched" and row["publicValueSha256"] == DATE_PAIR
                and row["datetimeBoundaryEvidence"] == DATE_PROBES, "Changed uncredited calendar diagnosis")
        new_differences.append(DATE_DIAGNOSTIC)
    require(set(open_ids) == (previous.keys() - EXPECTED_FIXES) | set(new_differences),
            "Unapproved change to the set of differences")
    require(assessment["mismatchMetadata"] == [{key: current[i][key] for key in
            ("id","operation","requirement","covers","publicValueSha256")} for i in open_ids], "Mismatch metadata changed")
    changes, sdk_changes, native_changes = {}, [], []
    for cid, before in previous.items():
        row = current[cid]
        after = row["publicValueSha256"]
        require(set(after) == {"openclaw","python"} and all(map(valid_hash, after.values())), cid)
        if cid in EXPECTED_FIXES:
            expected = {"openclaw": before["openclaw"], "python": F01_SDK if cid == F01 else before["openclaw"]}
            require(row["status"] == "matched" and after == expected and before["python"] != after["python"],
                    "Resolved case has a different whole original or SDK output: " + cid)
        elif cid == F14 and independent_f14:
            require(row["covers"] == [independent_f14["condition"]] and row["status"] == "mismatched"
                    and after["openclaw"] == before["openclaw"] == independent_f14["nativeSha256"]
                    and before["python"] == independent_f14["sdkBeforeSha256"] and after["python"] == independent_f14["sdkAfterSha256"]
                    and independent_f14["matched"] is False and independent_f14["pointsAwarded"] == 0,
                    "Unexpected change to the known open ranking diagnostic")
        elif cid == WARM:
            require(after["python"] == before["python"] and row["covers"] == [], "Changed credited or SDK warm flush")
        else:
            require(after == before, "Unexpected whole public result change: " + cid)
        if after != before:
            changes[cid] = {"before": before, "after": after}
        if after["python"] != before["python"]:
            sdk_changes.append(cid)
        if after["openclaw"] != before["openclaw"]:
            native_changes.append(cid)
    host = assessment["previousMismatchPublicHashReview"]
    require(changes == assessment["previousMismatchPublicHashChanges"]
            and len(host["sdkChangedCaseIds"]) == len(set(host["sdkChangedCaseIds"])) == len(sdk_changes)
            and set(host["sdkChangedCaseIds"]) == set(sdk_changes) == EXPECTED_FIXES | ({F14} if independent_f14 else set())
            and host["nativeChangedCaseIds"] == host["allowedUncreditedNativeWarmFlushChanges"] == native_changes
            and host["otherChangedCaseIds"] == ([F14] if independent_f14 else []) and host["allSdkWholePublicHashesUnchanged"] is False
            and host["resolvedCaseIds"] == sorted(EXPECTED_FIXES), "Independent whole-public hash audit disagrees")
    return {"resolved": sorted(EXPECTED_FIXES), "open": open_ids, "changes": changes, "newUncreditedDifferences": new_differences,
            "uncreditedWarmFlushNativeChanges": native_changes}


def require_assessed(assessment):
    require(assessment.get("status") == "assessed" and assessment.get("completeReportParsed") is True
            and isinstance(assessment.get("candidateAssessment"), dict) and assessment.get("errors") == [],
            "The hosted assessment is blocked or incomplete; no acceptance score")


def configure(parser):
    parser.add_argument("directory", type=Path)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--head", required=True, help="Comparison head from GitHub workflow metadata")
    parser.add_argument("--artifact-sha256", required=True, help="ZIP digest from GitHub metadata")
    parser.add_argument("--compare", type=Path, default=Path("/tmp/memory-core-next-compare"))
    parser.add_argument("--accepted-baseline", type=Path, default=BASE,
                        help="Directory containing the original 84-point assessment.json and root-review.json")
    parser.add_argument("--supplement", type=Path, help="Decoded separately authenticated assessor-only artifact")
    parser.add_argument("--supplement-run-id", type=int)
    parser.add_argument("--supplement-head")
    parser.add_argument("--supplement-sha256")
    parser.add_argument("--f14-reproduction", type=Path, help="Exact before/after SDK reproductions of the still-open diagnostic")
    return parser


def review(args):
    folder, root = args.directory.resolve(strict=True), args.compare.resolve(strict=True)
    require(re.fullmatch("[0-9a-f]{40}", args.head) and git(root, "rev-parse", "HEAD") == args.head,
            "The local checkout must match the GitHub run head")
    sys.path[:0] = [str(root), str(root / ".github/scripts")]
    import followup_seal as pin
    from equivalence.cases import build_cases
    from equivalence.catalog_migration import definition_authority
    pin.check_seal()
    remote = artifact(folder, args.run_id, args.head, args.artifact_sha256)
    original_assessment = read(folder / "assessment.json")
    supplement = None
    supplied = (args.supplement, args.supplement_run_id, args.supplement_head, args.supplement_sha256)
    require(all(v is not None for v in supplied) or all(v is None for v in supplied),
            "Use all four supplemental artifact identity arguments together")
    if args.supplement is None:
        require(args.f14_reproduction is None, "The independent final disposition needs the authenticated second artifact")
        audit = original_assessment
    else:
        from retained_assessment import verify_supplement
        audit, supplement = verify_supplement(args, folder, remote, original_assessment, root)
    independent = supplement and supplement.get("independentFinalDisposition")
    if not independent:
        require_assessed(audit)
    require(set(pin.EXPECTED_RESOLUTIONS) == EXPECTED_FIXES and len(pin.EXPECTED_RESOLUTIONS) == 7,
            "Unexpected or duplicate approved whole-output resolution")
    baseline_dir = args.accepted_baseline.resolve(strict=True)
    require(file_sha(baseline_dir / "assessment.json") == BASE_ASSESSMENT, "Last verified 84-point baseline")
    baseline = read(baseline_dir / "assessment.json")
    prior = baseline["candidateAssessment"]
    require(baseline["completeReportParsed"] is True and baseline["status"] == "assessed" and prior["verified"] == 84
            and baseline["report"]["sha256"] == BASE_REPORT, "Baseline report authority")
    prior_review = read(baseline_dir / "root-review.json")
    require(prior_review["verified"] == 84 and prior_review["sourceAndExitBindingsVerified"] is True
            and prior_review["reportSha256"] == BASE_REPORT
            and prior_review["allSummaryFileHashes"]["assessment.json"] == BASE_ASSESSMENT, "Prior independent acceptance")
    previous = pin.PREVIOUS_COMPARISON
    require(previous == {"runId": 44137396647, "verified": 84, "registeredCases": 1500,
            "assessmentSha256": BASE_ASSESSMENT, "reportSha256": BASE_REPORT, "familyGates": prior["families"],
            "warmFlushNativeSha256": next(r["publicValueSha256"]["openclaw"] for r in baseline["projection"]["cases"]
                                        if r["id"] == WARM)}, "Sealed previous accepted measurement")
    seal, after = (read(folder / name) for name in ("source-seal.json","source-after.json"))
    source(root, seal, after, args.head, pin)
    require(audit["kind"] == "approved-product-complete-eof-candidate-assessment"
            and audit["status"] == ("blocked" if independent else "assessed")
            and audit["completeReportParsed"] is True and audit["historicalVerifiedConditions"] == 84
            and audit["originalEnginesExecuted"] is False and audit["previousComparison"] == previous,
            "Hosted complete EOF assessment is blocked or differs from last accepted baseline")
    proj = audit["projection"]
    require(proj["kind"] == "pinned-differential-acceptance" and proj["mode"] == "full" and not proj["errors"]
            and proj["paidProviderCalls"] == 0 and proj["providerCredentialsForwarded"] is False
            and proj["reference"] == baseline["projection"]["reference"] and proj["reference"]["commit"] == REFERENCE,
            "Pinned original reference or exposure")
    for key, name in (("reference","reference.json"), ("scope","scope.json"), ("sourceMap","source-map.json")):
        require(proj["manifestSha256"][key] == file_sha(root / "equivalence" / name), "Manifest "+key)
    require(proj["casesSha256"] == file_sha(root / "equivalence/cases.py")
            and proj["manifestSha256"]["scope"] == seal["scopeSha256"] == SCOPE == pin.SCOPE_SHA, "Fixed scope / adapter")
    ended, terminal = process(folder, args.run_id, audit, proj)
    defs = build_cases()
    require(len(defs) == seal["registeredCases"] == pin.REGISTERED_CASES and len(defs) > 1592
            and digest(canonical(defs)) == pin.CATALOG_SHA == seal["catalogSha256"]
            and canonical(definition_authority(defs, fif_version="v6")) == canonical(seal["definitionMigration"])
            and digest(canonical(defs[:1500])) == BASE_CATALOG and pin.PREVIOUS_CASES == 1592
            and digest(canonical(defs[:1592])) == pin.PREVIOUS_CATALOG_SHA == PREVIOUS_CATALOG and seal["previousCatalog"] == {
            "registeredCases":1592, "sha256":pin.PREVIOUS_CATALOG_SHA,"completePrefixUnchanged":True}, "Frozen case catalog")
    from followup_families import FAMILIES, family_key
    first_families = LEGACY | {"deep-consolidation-runtime", "engine.numeric-boundaries", "prompt-history-repair-runtime"} | {
        family_key(c) for c in defs[:1592] if family_key(c) in FAMILIES}
    require(len(first_families) == 29, "First 1,592 definitions lost their 29 family gates")
    rows = reconstruct(defs, proj)
    if supplement is not None:
        from retained_assessment import restore_recovery_modes
        restore_recovery_modes(rows, supplement["recoveryReferenceModes"])
    old_rows = baseline["projection"]["cases"]
    require(len(old_rows) == 1500 and [(r["id"],r["status"]) for r in rows[:1500]]
            == [(r["id"], "matched" if r["id"] in EXPECTED_FIXES else r["status"]) for r in old_rows], "A previously accepted case changed status")
    scope = read(root / "equivalence/scope.json")["requirements"]
    gates, points, grouped, contracts, uncovered, unresolved = recount(rows, defs, proj, scope, prior["families"])
    counts = {s: sum(r["status"] == s for r in rows) for s in ("matched","mismatched","blocked")}
    score = sum(points.values())
    require(counts["mismatched"] == 7 + int(any(r["id"] == DATE_DIAGNOSTIC for r in defs)) and counts["blocked"] == 0 and sum(counts.values()) == len(rows)
            and proj["summary"] == {**counts, "uncoveredAcceptance":len(uncovered)} and proj["fullScopePassed"] is False
            and (independent or audit["fullScopePassed"] is False) and terminal["blockedCaseIds"] == []
            and terminal["mismatchedCaseIds"] == [r["id"] for r in rows if r["status"] == "mismatched"], "Measured statuses")
    measured = {"verified":score,"remaining":128-score,"uncovered":len(uncovered),"registeredUnresolved":len(unresolved),
                "contracts":contracts,"cases":counts,"families":gates,"points":[{"id":k,"verified":v} for k,v in points.items()]}
    if independent:
        require(audit["candidateAssessment"] is None and independent["condition"] in unresolved
                and points[independent["condition"]] is False and "deltaFromPreviousHosted" not in audit,
                "The open diagnostic received credit or the refused assessor issued a candidate score")
    else:
        require(audit["candidateAssessment"] == measured and audit["deltaFromPreviousHosted"] == audit["deltaFromHistorical84"]
                == score-84, "Independent 128-point recount differs from the hosted projection")
    before = {p["id"]: p["verified"] for p in prior["points"]}
    changes = [p for p, passed in points.items() if passed and not before[p]]
    require(len(points) == len(before) == 128 and all(points[k] for k,v in before.items() if v)
            and len(changes) == score - prior["verified"] and set(changes) <=
            {p for c in defs[1500:] for p in c["covers"]} |
            {p for row in rows if row["id"] in EXPECTED_FIXES for p in row["covers"]},
            "Point changes lack registered, matched coverage or a previous pass regressed")
    fif_sha = None
    if independent:
        from retained_assessment import ORIGINAL_FIF
        fif_sha = ORIGINAL_FIF
    by_group = replays(folder, audit, rows, gates, pin.SDK_SHA, fif_sha)
    hash_review = mismatch_audit(baseline, audit, rows, independent)
    if independent:
        source(root, seal, after, args.head, pin)
        require(artifact(folder, args.run_id, args.head, args.artifact_sha256) == remote,
                "The immutable original summary changed during independent review")
    return {**({"supplementalAssessment":supplement} if supplement is not None else {}),
        "kind":"independent-memory-remainder-128-point-review","runId":args.run_id,"comparisonCommit":args.head,
        "productSourceCommit":pin.PRODUCT, "sdkGitTree":seal["sdkGitTree"], "productSdk":seal["productSdk"],
        "sourceAndExitBindingsVerified":True, "remoteSummary":remote,"completeReportEofParsedInFrozenCiAssessor":True,
        "localFullReportDownloaded":False,"originalEnginesExecutedByReview":False,"reportSha256":audit["report"]["sha256"],
        "reportBytes":audit["report"]["bytes"],"registeredCases":len(defs),"catalogSha256":pin.CATALOG_SHA,
        "verified":score,"remaining":128-score,"netGain":score-84,"uncovered":len(uncovered),"registeredUnresolved":len(unresolved),
        "contracts":contracts,"caseCounts":counts,"atomicFamilyCount":len(gates),"pointChanges":changes,"contractCounts":grouped,
        "uncoveredIds":uncovered,"unresolvedIds":unresolved,"rawReplayCounts":by_group,
        "previousAcceptedScore":prior["verified"], "previousAcceptedRunId":previous["runId"],
        "previousAcceptedCases":len(old_rows), "previousAcceptedGates":prior["families"], "first1592RemeasuredGates":{k:gates[k] for k in sorted(first_families)}, "measuredFamilyGates":gates,
        "recountedPoints":points, "wholeOutputAudit":hash_review, "previousDefinitionPrefixCases":1592,
        "previousDefinitionPrefixSha256":PREVIOUS_CATALOG, "interveningBlockedRuns":[44189169478,44206756377],
        "fullScopePassed":False,"actualReturnCode":ended["actualReturnCode"],"elapsedSeconds":ended["elapsedSeconds"],
        "finishedAt":ended["finishedAt"],"rootReviewScriptSha256":file_sha(Path(__file__)),
        "allSummaryFileHashes":{n:file_sha(folder/n) for n in sorted(FILES)}}


if __name__ == "__main__":
    print(json.dumps(review(configure(argparse.ArgumentParser(description=__doc__)).parse_args()), indent=2))
