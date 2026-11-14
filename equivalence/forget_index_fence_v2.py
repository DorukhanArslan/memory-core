"""Closed v2 input-only forget/index-fence family, awaiting reviewed registration.

This module reads literal inputs and authenticates their exact bytes. Importing
it executes no original owner, host, tool, producer or acceptance catalog.
Both original points require the same complete v2 family; no subset earns credit.
The original v1 literals and captures remain separate immutable diagnostics.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "forget-index-fence-v2-runtime"
REQUIREMENT = "forget.index-fence"
POINTS = ("forget.index-fence.outcomes", "forget.index-fence.boundaries")
MANIFEST = Path(__file__).resolve().parents[1] / "docs/forget_index_fence_v2_literals.json"
MANIFEST_SHA256 = 'c562fca43a1ec7fbb320da55cd2c0bb2201ab1392230c2398cccdf82a9111854'
CASE_HASHES = {
    'forget-index-fence-v2-shared-clean-dryrun-unresolved-promotion-controls': '1b9acfda1c62857b998cdcd0ecda553d454eab908fa21113eb47bdce9862a35f',
    'forget-index-fence-v2-shared-old-full-complete-forget': 'df0166e9b6206c3c9358fae34b74a62ceacffe89767b193067329f6773638180',
    'forget-index-fence-v2-split-old-full-complete-forget': '5f8ae8105407367ada19c9f426c28c4dec584b8c30e8cc55282f828e5d6fb84d',
    'forget-index-fence-v2-unfenced-on-search-old-full-complete-forget': 'bdbe5dade86046563655d13645f8f7513f624e5cbc8c6fb81146ad456421103d',
    'forget-index-fence-v2-shared-postcheck-pending-forget': 'b28624082be718f339fc1c49c25371c0a5824bd9d0f27680d134feefea0e7133',
    'forget-index-fence-v2-split-postcheck-pending-forget': '3ab64950bbabaac2f6da2535e6ab1a72f98cf90869dd935f2e29d5709ac75acd',
    'forget-index-fence-v2-shared-marker-commit-process-kill': '0c9860ab427b19a7b9bff71dacd969d57277a99fc5243ca21d1b37dada4992d2',
    'forget-index-fence-v2-split-marker-commit-process-kill': 'fbf87d499b7dcc11b034db752c96a88818504062fbe45540496e33bdc8297a72',
    'forget-index-fence-v2-unfenced-on-search-marker-commit-process-kill': '54bcd55182af74d9d40adbc1785b61a1948c89261f10eae3df9aa3a6c77e64e2',
    'forget-index-fence-v2-keyword-worker-before-forget-enrichment-after': 'b11017ccae3ba4124c67f8f1c5c8a5819c82fb0d4e61ee42b468d013e1e290e3',
    'forget-index-fence-v2-stored-promotion-model-plan-before-forget': '2d04f44d937ae8a33ca14775e620d9ecc998eec455a970f7d3558aa1a16085e1',
    'forget-index-fence-v2-direct-absent-at-plan-retained-source-other-session-forgotten': '4a44ef7d5325e52f2a37c5e306d8d1e3aeb3f88dd0dc3b42d50c70fce5714a9b',
    'forget-index-fence-v2-repeat-existing-tombstone-old-full-pending': '6b099a8cf96a2bf407b19f4452c63e0e5b64c509c0f902f952eb68abb1b3336f',
}
INPUT_KEYS = frozenset({
    "kind", "profile", "scenario", "clock", "identity", "storageProfile",
    "config", "toolOptions", "actors", "sessionFacts", "initialFiles",
    "recallCalls", "seedActions", "queries", "forgetCalls", "syncs",
    "promotions", "gates", "steps", "observationPolicy",
    "comparisonPolicy", "counterPolicy",
})


def case_wire(case):
    """Bind independent inputs, without making product results part of a case."""
    return json.dumps(
        {key: case[key] for key in ("id", "operation", "input")},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False,
    ).encode()


def validate_case(case):
    if (not isinstance(case, dict)
            or set(case) != {"id", "operation", "requirement", "covers", "input"}
            or case.get("operation") != OPERATION
            or case.get("requirement") != REQUIREMENT
            or case.get("covers") != list(POINTS)
            or case.get("id") not in CASE_HASHES
            or not isinstance(case.get("input"), dict)
            or set(case["input"]) != INPUT_KEYS
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Forget/index-fence requires an exact independently frozen input literal")
    return deepcopy(case)


def build_cases(path=MANIFEST):
    payload = Path(path).read_bytes()
    if hashlib.sha256(payload).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Forget/index-fence literal manifest changed after its reviewed byte seal")
    manifest = json.loads(payload)
    if (not isinstance(manifest, dict)
            or set(manifest) != {"kind", "acceptancePointsAwarded", "cases"}
            or manifest["kind"] != "forget-index-fence-v2-acceptance-literals"
            or type(manifest["acceptancePointsAwarded"]) is not int
            or manifest["acceptancePointsAwarded"] != 0
            or not isinstance(manifest["cases"], list)
            or [case.get("id") for case in manifest["cases"]] != list(CASE_HASHES)):
        raise ValueError("Forget/index-fence requires its complete closed thirteen-member family")
    return [validate_case(case) for case in manifest["cases"]]


def family_members(cases):
    """Catch every prospective claim, including attempts to rename the operation."""
    return [
        case for case in cases
        if case.get("operation") == OPERATION
        or str(case.get("id", "")).startswith("forget-index-fence-v2-")
        or set(case.get("covers", ())) & set(POINTS)
        or case.get("requirement") == REQUIREMENT
    ]


def validate_registration(cases):
    """Authenticate a prospective registration; this function registers nothing."""
    family = family_members(cases)
    if not family:
        return
    if (len(family) != len(CASE_HASHES)
            or [case.get("id") for case in family] != list(CASE_HASHES)):
        raise ValueError("Both forget/index-fence points require all thirteen exact cases atomically")
    for case in family:
        validate_case(case)
