"""Closed v3 input-only forget/index-fence family, awaiting reviewed registration.

This module reads literal inputs and authenticates their exact bytes. Importing
it executes no original owner, host, tool, producer or acceptance catalog.
Both original points require the same complete v3 family; no subset earns credit.
The original v1/v2 literals and captures remain separate immutable diagnostics.
V3 adds only explicit waits for already queued original search effects.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "forget-index-fence-v3-runtime"
REQUIREMENT = "forget.index-fence"
POINTS = ("forget.index-fence.outcomes", "forget.index-fence.boundaries")
MANIFEST = Path(__file__).resolve().parents[1] / "docs/forget_index_fence_v3_literals.json"
MANIFEST_SHA256 = 'acdcbfa022d43c9ab58dbfc43bfa1987798d5aa4a02f3f535bd44db2d449b01c'
CASE_HASHES = {
    'forget-index-fence-v3-shared-clean-dryrun-unresolved-promotion-controls': 'e80853d8cdc780eb06a577715d34c93e3fd51a536e73d33221122a7b3f33f9b7',
    'forget-index-fence-v3-shared-old-full-complete-forget': '8484e6cb552a05d4550d19c250d63b6983bc4fcae8e882da4ecf089c94a86678',
    'forget-index-fence-v3-split-old-full-complete-forget': 'cae43cd5ffbbaf2514abe76258c4a4b4866bcc9b0ef15a84b6dcca4ba063ba4d',
    'forget-index-fence-v3-unfenced-on-search-old-full-complete-forget': 'fb798a36b2309c8ceb421f397e07e67a5d4d367102bc3bbf16bce0410519e0d0',
    'forget-index-fence-v3-shared-postcheck-pending-forget': '959a7677379f513b3271b6d886258dc26429c7479532597634907bb0d0abcb15',
    'forget-index-fence-v3-split-postcheck-pending-forget': '3c07dedecf3f7faddaff2148d5c9afbe0e836a554d024eb4120f919830eafae2',
    'forget-index-fence-v3-shared-marker-commit-process-kill': 'b6aa0ac7f16c1648955ab197b924b6eab41494362c02c3732e508850e48e04a3',
    'forget-index-fence-v3-split-marker-commit-process-kill': '4ff9d176c30b2390020f715d1280b776010662e70f0b16ff47482d2e77eba114',
    'forget-index-fence-v3-unfenced-on-search-marker-commit-process-kill': 'b47372d03e8216b49e59e3e8d443b38d71d2df836d2013db4a02448de5e962e5',
    'forget-index-fence-v3-keyword-worker-before-forget-enrichment-after': '7f2b2fbd4a7cee358f095a58732f89633147a171c036b218912f13c520a95c50',
    'forget-index-fence-v3-stored-promotion-model-plan-before-forget': '22978effc4196cf8c4202387e4ea15188c31d89703635849216d1f09e493ac7d',
    'forget-index-fence-v3-direct-absent-at-plan-retained-source-other-session-forgotten': 'a28d02cc268762203bc31d13f00ce592ff1a296f9a516694c640ee9a05806115',
    'forget-index-fence-v3-repeat-existing-tombstone-old-full-pending': 'b0ab0dd957a78a530f22951261f5e8755204d576d914b4a425237247c6e58287',
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
            or manifest["kind"] != "forget-index-fence-v3-acceptance-literals"
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
        or str(case.get("id", "")).startswith("forget-index-fence-v3-")
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
