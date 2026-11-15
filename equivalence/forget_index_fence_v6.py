"""Closed v6 input-only forget/index-fence family, awaiting reviewed registration.

This module reads literal inputs and authenticates their exact bytes. Importing
it executes no original owner, host, tool, producer or acceptance catalog.
Both original points require the same complete v6 family; no subset earns credit.
The original v1/v2/v3/v4/v5 inputs and captures remain separate immutable diagnostics.
V6 reuses V5 watcher controls, V3 search effects and V2 source clocks.
Only its keyword member moves the existing selectedWatch join before capture.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "forget-index-fence-v6-runtime"
REQUIREMENT = "forget.index-fence"
POINTS = ("forget.index-fence.outcomes", "forget.index-fence.boundaries")
MANIFEST = Path(__file__).resolve().parents[1] / "docs/forget_index_fence_v6_literals.json"
MANIFEST_SHA256 = 'ce4ee37230a9a814d7f8440e7e9cc513ae5140ee2980aa01c45480493ef4998d'
CASE_HASHES = {
    'forget-index-fence-v6-shared-clean-dryrun-unresolved-promotion-controls': '2d05f5be1e5da3e675579e38a89b293653ea5c287d186e62ce7be334891df2a4',
    'forget-index-fence-v6-shared-old-full-complete-forget': 'ed530bee612593465cff0f8f8c1d383b4ed81747fdaea395f3465aab3748b000',
    'forget-index-fence-v6-split-old-full-complete-forget': '10a26d8c9005092f786daf5840666bea7677493671d9fc807bdb96c75ee08e7a',
    'forget-index-fence-v6-unfenced-on-search-old-full-complete-forget': '82a888ddf922e20e275d56d25bbe07a0a65a04539109e3ec3b435553ced208be',
    'forget-index-fence-v6-shared-postcheck-pending-forget': 'd2b960811d1560851f4e8d1dc055d34e5e83f94ead5a3a6fd2a810c5d84a0ef3',
    'forget-index-fence-v6-split-postcheck-pending-forget': 'ce09aaa948cfb090be2bed3d2ec744fb19ce7f19da958cfaaa52d0682195ae3c',
    'forget-index-fence-v6-shared-marker-commit-process-kill': '0e491fa0ccbc2751293eb79e7b9c5ae3e5462a8bf790926d5ddcd5393311af79',
    'forget-index-fence-v6-split-marker-commit-process-kill': '41b2b5924fe2ee6968167cc1eebc3f78ead770ed6ede8e91ab87a47fcd2782ca',
    'forget-index-fence-v6-unfenced-on-search-marker-commit-process-kill': '28d8ac401d55910a49ec64ce6843eddb695af19a827311c7c580638fdc4c35a4',
    'forget-index-fence-v6-keyword-worker-before-forget-enrichment-after': '41e8ea017af70dc81ba10699eed0f9f2f132cf191e4800fb25bc5e26db8a7bff',
    'forget-index-fence-v6-stored-promotion-model-plan-before-forget': '0378e25807f610e53d7dbdf86dfe47666ef13e99629519a97c131a77ca37d046',
    'forget-index-fence-v6-direct-absent-at-plan-retained-source-other-session-forgotten': '98ef003c03d5c9402a8696b876412661d0091ff069c3c289bf45d0737dcf0b08',
    'forget-index-fence-v6-repeat-existing-tombstone-old-full-pending': 'be5242d87f8a1501d4b730216c54ecb955b6ac1b92cb62bd61e8398bc6776f24',
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
            or manifest["kind"] != "forget-index-fence-v6-acceptance-literals"
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
        or str(case.get("id", "")).startswith("forget-index-fence-v6-")
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
