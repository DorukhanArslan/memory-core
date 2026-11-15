"""Closed input-only forget/index-fence family, awaiting reviewed registration.

This module reads literal inputs and authenticates their exact bytes. Importing
it executes no original owner, host, tool, producer or acceptance catalog.
Both original points require the same complete family; no subset earns credit.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "forget-index-fence-runtime"
REQUIREMENT = "forget.index-fence"
POINTS = ("forget.index-fence.outcomes", "forget.index-fence.boundaries")
MANIFEST = Path(__file__).resolve().parents[1] / "docs/forget_index_fence_literals.json"
MANIFEST_SHA256 = '3e2e1590dde362027f0910efc2653822b19bb74a27e9b56e9c9cda4637fc3682'
CASE_HASHES = {
    'forget-index-fence-shared-clean-dryrun-unresolved-promotion-controls': '3c6f2bd032e85accd26cf98c0aac2a645cdb44f51db192b597a54f64fc4f10fc',
    'forget-index-fence-shared-old-full-complete-forget': 'a50a4ba713d0dcc1dfc61de5bf71dc66a53501c66db8e9c6a6350bfa1bfb0aad',
    'forget-index-fence-split-old-full-complete-forget': '43aa72fd2f30bfcfaf2c773d02f38e2f681cce79b8ab41eaf15d749530291563',
    'forget-index-fence-unfenced-on-search-old-full-complete-forget': '0a44f139e39d2e6088475b3a279f3bfc48dbd3744765d7bf5b83f77280e0ba76',
    'forget-index-fence-shared-postcheck-pending-forget': '15301b52e2c21a39184dca488d1461bb588d37e837361f2fc2239f1467cfd276',
    'forget-index-fence-split-postcheck-pending-forget': '52e6b235cdbcd0304a677de3f69b032be9453470ea8fdb3c7b870ea27c1f48be',
    'forget-index-fence-shared-marker-commit-process-kill': '3b8411319dff5a22c171545f1ceafcc6c72ca8856373ca4faf01cf15d471b850',
    'forget-index-fence-split-marker-commit-process-kill': 'ede638ba25b32ce6285bd2cfe4085c838f2a4dae7bf133ebe8f94b4ee429a7f8',
    'forget-index-fence-unfenced-on-search-marker-commit-process-kill': 'd2d79892afd9b7a12fa3d10f2307a9ba215ebaaa42aa796b6addf9507b1b1df5',
    'forget-index-fence-keyword-worker-before-forget-enrichment-after': '6f18402d42c354682a18a77d39b7136bb5f4dab0220d3cdbcf4bc6c1d62b8c9b',
    'forget-index-fence-stored-promotion-model-plan-before-forget': '285755a010826810830b0711678d54522a69beaf30b1f4034e7b2793d8def747',
    'forget-index-fence-direct-absent-at-plan-retained-source-other-session-forgotten': '25d61b2395527a2cb7b4d59234ce353b65e91510e6edd8413aa3648c5f336dae',
    'forget-index-fence-repeat-existing-tombstone-old-full-pending': '32991073589bed868e38493b3b74ff32bd9951c3fddb75de5e12785b61f34de9',
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
            or manifest["kind"] != "forget-index-fence-acceptance-literals"
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
        or str(case.get("id", "")).startswith("forget-index-fence-")
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
