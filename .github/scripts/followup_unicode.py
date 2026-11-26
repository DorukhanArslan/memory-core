"""Reopen the pinned Unicode sources and wheel, and compare whole retained source returns."""
from __future__ import annotations

import hashlib

from equivalence import engine_unicode_collation as family
from equivalence.harness import _committed_digest
from equivalence.hybrid_scoring import build_hybrid_scoring_cases, run_hybrid_scoring
from equivalence.model_runtime_authority import prepare_model_node_authority
from equivalence.search_contract import _same_json

MEASURED_ORIGINAL = {'unicode-collation-generated': 'a31dd2ff9a2e71a94028201b4b5810f0f8bbf9c3e1b97b5d52b7d2097d68a0cb',
 'unicode-collation-named-order': 'ede165bbbc488cb3c27628ae37d3b182bfafe7939ddeafcc5de3f7f699011498',
 'unicode-collation-words-and-cuts': 'e7b478b52f4f8030edf5a217ad2336e09523d0824221ecc9e094bb9aeca97632'}


def same(left, right, message):
    if not _same_json(left, right):
        raise ValueError(message)


def sha(value):
    return hashlib.sha256(family._wire(value)).hexdigest()


def replay_unicode(data, cases, args, runtime):
    original = next(c for c in build_hybrid_scoring_cases() if c["id"] == family.DIAGNOSTIC)
    family.validate_registration([original, *cases])
    node = prepare_model_node_authority(args.node)
    if (node["nodeVersion"], node["icuVersion"], node["unicodeVersion"]) != ("v24.16.0", "78.3", "17.0"):
        raise ValueError("The original Unicode executable or data version changed")
    sources = data["unicodeSources"]
    if sorted(r["path"] for r in sources) != family.OWNERS:
        raise ValueError("An original Unicode owner is missing")
    for row in sources:
        path = args.reference / row["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"] or _committed_digest(args.reference, row["path"]) != row["sha256"]:
            raise ValueError("A loaded Unicode owner differs from its pinned source")
    same(data["unicodeSdkRuntime"], family.sdk_unicode_identity(), "The installed ICU libraries changed")
    same(sorted(data["unicodeSourceImports"]), sorted(c["id"] for c in cases), "Per-case source receipts changed")
    source_ids = data["referenceExecution"]["trackedTypeScriptCaseIds"]
    if any(source_ids.count(c["id"]) != 1 for c in [original, *cases]):
        raise ValueError("Unicode comparisons did not all execute the original TypeScript source")
    previous = data["unicodeTiePair"]
    tie_hashes = {side: sha(previous[side]) for side in ("openclaw", "python")}
    same(tie_hashes["openclaw"], family.PRIOR_NATIVE_F01_SHA256,
         "The entire tie result differs from the original authenticated native output")
    same(previous["python"], run_hybrid_scoring(original["input"]), "Unable to reproduce the SDK tie")
    tie_match = _same_json(previous["openclaw"], previous["python"])
    results = []
    for case in cases:
        cid = case["id"]
        row = data["followupRows"][cid]["case"]
        same({k: row[k] for k in case}, case, "The Unicode inputs, driver or covering points changed")
        if row.get("unicodeEvidenceValidated") is not True:
            raise ValueError("A Unicode source case lost its producer receipt")
        native, sdk = row["openclaw"], row["python"]
        family.validate_source_pair(case, data["unicodeSourceImports"][cid], sources,
                                    data["unicodeRuntime"], native, sdk)
        if sha(native) != MEASURED_ORIGINAL[cid]:
            raise ValueError("The complete original Unicode public output differs from the protected measurement")
        same(sdk, family.run_sdk(case["input"]), "The installed SDK could not reproduce its entire public output")
        results.append({"id": cid, "publicMatch": _same_json(native, sdk), "nativePublicSha256": sha(native),
                        "sdkPublicSha256": sha(sdk), "texts": len(native["texts"]),
                        "tiedHits": len(native["merge"]["merged"]),
                        "slices": sum(len(r["slices"]) for r in native["texts"]),
                        "truncations": sum(len(r["truncated"]) for r in native["texts"]),
                        "runtime": data["unicodeRuntime"], "previousTie": tie_hashes, "previousTiePublicMatch": tie_match})
    return results
