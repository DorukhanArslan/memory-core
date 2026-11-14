"""Closed v5 input-only forget/index-fence family, awaiting reviewed registration.

This module reads literal inputs and authenticates their exact bytes. Importing
it executes no original owner, host, tool, producer or acceptance catalog.
Both original points require the same complete v5 family; no subset earns credit.
The original v1/v2/v3/v4 inputs and captures remain separate immutable diagnostics.
V5 declares positive watcher readiness/delivery/settlement controls; V3 search
effects and V2 source clocks remain separate unchanged protocols.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "forget-index-fence-v5-runtime"
REQUIREMENT = "forget.index-fence"
POINTS = ("forget.index-fence.outcomes", "forget.index-fence.boundaries")
MANIFEST = Path(__file__).resolve().parents[1] / "docs/forget_index_fence_v5_literals.json"
MANIFEST_SHA256 = 'a1da290cb134aca47678f97b7e2e182a48b746863857a3e3f5c9365db02aae83'
CASE_HASHES = {
    'forget-index-fence-v5-shared-clean-dryrun-unresolved-promotion-controls': '501eafdb98cd3a43723b90797edd7cd94913c38266fe257f66a9b8c84ae346c5',
    'forget-index-fence-v5-shared-old-full-complete-forget': 'a82f2179e67bbfc8049fd9474afc55426abc16ff5565d12c08dec27fa53ef294',
    'forget-index-fence-v5-split-old-full-complete-forget': '5c6774d2d629e408dc5475882f6f99538c443ae3f8bac98fdc40d9db85903eea',
    'forget-index-fence-v5-unfenced-on-search-old-full-complete-forget': 'd8ed3c7c235b1ea487ca347782cf35eae3e5ac671e8abe6b127a6bdf96504117',
    'forget-index-fence-v5-shared-postcheck-pending-forget': '3680808de2cb65507b836f2b3b9f6d6bf6068725c7a6f4b50091c94fb4c68690',
    'forget-index-fence-v5-split-postcheck-pending-forget': '8d407798781efdc21a8bf720796423107ffdabd109ea56d6e328ba42a200192f',
    'forget-index-fence-v5-shared-marker-commit-process-kill': 'b209de1acd2ed0784c6155157535d2dfc566a374b3dc38e1a4f52af30e9aae83',
    'forget-index-fence-v5-split-marker-commit-process-kill': '9b73bee08dfdc62ee37f6e94ae3a8b48c0ca7ad429f40dfedf5b4f2b49872e1b',
    'forget-index-fence-v5-unfenced-on-search-marker-commit-process-kill': '132fd64957494daaf82d87a27862e9c1595252c49e30f03b5ee24e777c7fe329',
    'forget-index-fence-v5-keyword-worker-before-forget-enrichment-after': '73d22414857d1eac5b526604d7e7ec0c73d5ddc6d36b16fef4038802e04b2f22',
    'forget-index-fence-v5-stored-promotion-model-plan-before-forget': '1b4968b19b84fa74faa31301b6c14f9a8cb37e182e68633fb94bbdf05377036c',
    'forget-index-fence-v5-direct-absent-at-plan-retained-source-other-session-forgotten': '6d90512bef66e38214078a0f3f125fd63548888cc160c02faa2e5b8cf0e9623d',
    'forget-index-fence-v5-repeat-existing-tombstone-old-full-pending': '986401f4bd6df92976bb28c217500d5a2e7502f815a238dfd0f6f1bcac8c2b88',
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
            or manifest["kind"] != "forget-index-fence-v5-acceptance-literals"
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
        or str(case.get("id", "")).startswith("forget-index-fence-v5-")
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
