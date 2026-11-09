"""Frozen whole-apply literals with separate development and strict registration.

This does not widen the original single-input capability. Development cases
retain empty coverage; registered claims must include the entire exact family.
The literal hashes bind host inputs, never expected operation results.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "promotion-apply-family-runtime"
ACCEPTANCE = ("promotion.apply-reconcile.outcomes", "promotion.apply-reconcile.boundaries")
CASE_HASHES = {
    "promotion-apply-authoritative-store-and-moved-source": "f8cfb6b12c5b22438dcab17420e781969753a9dac768943b0771d89560da25a4",
    "promotion-apply-mixed-authoritative-rejection-receipts": "035445f91f34c49149d3a5db914ad241b95fef15fc3083e45db80a4b6abf7f46",
    "promotion-apply-daily-file-quarantine": "962d7b1b414e4687ab0fbb2a3163cae9e014a8a6de6e0f3cb3243a4c76c3ef20",
    "promotion-apply-direct-candidate-without-stored-entry": "1efb4565c7a6eaa9c0ea9d42541922256701ace47f1bce0d4f3f38e5d34bc834",
    "promotion-apply-prelock-store-change": "4f55f99f9430a4f688ad1c7ac9dcbf626db7bec694a5384f4ca5396c5e1bc956",
    "promotion-apply-prelock-source-change": "d848b8b374976c8398de4c397ab9ea0e576ca3385ca035b10ec07c1885e781f9",
    "promotion-apply-prelock-marker-reconciliation": "62954ad5591378a27eaa48747268213b3148d43baa0583a7f1f4a6d3b9af5105",
    "promotion-apply-add-only-preimage-origin-and-dreams-publication": "c4fb4bbac7df8a72ea601527332e6035b53dd3cb37244607f8689669a27af231",
}


def case_wire(case):
    return json.dumps({k: case[k] for k in ("id", "operation", "input")},
                      sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def validate_case(case, *, registered=False):
    coverage = list(ACCEPTANCE) if registered else []
    if (not isinstance(case, dict) or case.get("operation") != OPERATION
            or case.get("covers") != coverage or case.get("requirement") != "promotion.apply-reconcile"
            or case.get("id") not in CASE_HASHES
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Family capability requires an exact separate literal with empty coverage")
    return deepcopy(case)


def validate_execution_case(case):
    return validate_case(case, registered=case.get("covers") == list(ACCEPTANCE))


def build_registered_cases():
    return [{**case, "covers": list(ACCEPTANCE)} for case in build_cases()]


def validate_registration(cases):
    claims = [case for case in cases if set(ACCEPTANCE).intersection(case.get("covers", []))]
    if not claims:
        return
    if len(claims) != len(CASE_HASHES) or {c["id"] for c in claims} != set(CASE_HASHES):
        raise ValueError("Promotion apply acceptance requires all eight exact whole-operation families")
    for case in claims:
        validate_case(case, registered=True)


def build_cases():
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "docs/promotion_apply_followup_literals.json").read_text())["cases"]
    if [c["id"] for c in cases] != list(CASE_HASHES):
        raise ValueError("The family manifest must retain all eight distinct literal inputs")
    return [validate_case(case) for case in cases]


def differences(left, right, path="$"):
    """Exact JSON comparison; preserve every difference, with no score/error repair."""
    from equivalence.search_contract import _same_json

    # JSON has one number type. Share the established comparator's exact
    # numeric equality, while retaining its strict bool/number distinction.
    if _same_json(left, right):
        return []
    if type(left) is not type(right):
        return [{"path": path, "native": left, "sdk": right}]
    if isinstance(left, dict):
        rows = []
        for key in sorted(left.keys() | right.keys()):
            child = f"{path}.{key}"
            if key not in left or key not in right:
                rows.append({"path": child, "nativePresent": key in left, "sdkPresent": key in right,
                             **({"native": left[key]} if key in left else {}),
                             **({"sdk": right[key]} if key in right else {})})
            else:
                rows.extend(differences(left[key], right[key], child))
        return rows
    if isinstance(left, list):
        if len(left) != len(right):
            return [{"path": path, "native": left, "sdk": right}]
        return [row for i, (a, b) in enumerate(zip(left, right))
                for row in differences(a, b, f"{path}[{i}]")]
    return [] if left == right else [{"path": path, "native": left, "sdk": right}]
