"""Closed v4 input-only forget/index-fence family, awaiting reviewed registration.

This module reads literal inputs and authenticates their exact bytes. Importing
it executes no original owner, host, tool, producer or acceptance catalog.
Both original points require the same complete v4 family; no subset earns credit.
The original v1/v2/v3 inputs and captures remain separate immutable diagnostics.
V4 fixes the supported sync profile; the V3 queued-effects protocol is unchanged.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "forget-index-fence-v4-runtime"
REQUIREMENT = "forget.index-fence"
POINTS = ("forget.index-fence.outcomes", "forget.index-fence.boundaries")
MANIFEST = Path(__file__).resolve().parents[1] / "docs/forget_index_fence_v4_literals.json"
MANIFEST_SHA256 = 'd8945f9d1bf1aadc5b33c83a6a8a250e13ecefd4d51698e5cf170b8e8d8b6fd2'
CASE_HASHES = {
    'forget-index-fence-v4-shared-clean-dryrun-unresolved-promotion-controls': '7771c6d04b4eb6fb3203aecb7edc733f2b9ee507d2b434c4fc4d4d1a2ab9c5ad',
    'forget-index-fence-v4-shared-old-full-complete-forget': 'c471fe4367a6efa908e2f364d8aea307215fb29a672b50c022df352e211494f2',
    'forget-index-fence-v4-split-old-full-complete-forget': '8606fa125a9ff1ea3f0ddabdc4791ca5f29a5d61ff3a5c4cf3ca1b3c3268289f',
    'forget-index-fence-v4-unfenced-on-search-old-full-complete-forget': 'cdb385a63e1210907e955d8336fc25011b55882656c6ce5d8c42653489018310',
    'forget-index-fence-v4-shared-postcheck-pending-forget': '22288ca76a30e9beb3be5e60b5071217b9fd4e09e6cbe02ff06343adfb67d8a6',
    'forget-index-fence-v4-split-postcheck-pending-forget': '537d3e16b35f056683a917f08e03423f2cdaaa6f8600919bef4e9e0de74bdc65',
    'forget-index-fence-v4-shared-marker-commit-process-kill': '92794024ce1fd1de0e33b6a245107a959d615c08fe5cf317b913ddbc5427a39e',
    'forget-index-fence-v4-split-marker-commit-process-kill': 'ab685413990ac529b50e258914655418bad859c6f60383b64a529467d550be68',
    'forget-index-fence-v4-unfenced-on-search-marker-commit-process-kill': 'a02bae1e9a35c25d271de47f2f31275c830e006bed65db8f986b2aa71e3cb278',
    'forget-index-fence-v4-keyword-worker-before-forget-enrichment-after': 'a6b380b07213696094f0cfcb88e74eccb50ae0bfb2328dd6fb157543d74c8001',
    'forget-index-fence-v4-stored-promotion-model-plan-before-forget': 'ff99601c5fdd375690291f1ad52f9e56b5244fa048518cf711c93d76ad657a3b',
    'forget-index-fence-v4-direct-absent-at-plan-retained-source-other-session-forgotten': 'fae07da335b69936216316b8bd4b90fd82faf7bd00bc366cb4e526e7282260cd',
    'forget-index-fence-v4-repeat-existing-tombstone-old-full-pending': '4ca62c88948ceacf778a3bd5f03829e6a0c1a88e3991570f856b6ba9a0535c70',
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
            or manifest["kind"] != "forget-index-fence-v4-acceptance-literals"
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
        or str(case.get("id", "")).startswith("forget-index-fence-v4-")
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
