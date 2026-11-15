"""Closed family for the original forget selection outcome condition.

These are the unchanged first three inputs from the retained six-case baseline.
The remaining diagnostics stay uncredited. Private coordination storage remains
in complete raw evidence; it is not part of the portable memory result.
"""
from copy import deepcopy
import hashlib
import json

from equivalence.forget_lineage_cases import build_cases as diagnostic_cases

OPERATION = "forget-lineage-runtime"
REQUIREMENT = "forget.lineage-tombstones"
POINTS = ("forget.lineage-tombstones.outcomes",)
CASE_HASHES = {
    "forget-lineage-direct": "b3e22ea74c6da5e39b56e8969b07693737e3b56d4ad0eddb6dfd6300a6139e03",
    "forget-lineage-promoted-mixed": "e530815f1f8de8ffb43b42a4afa85a6a7fc2dcf4e53a33e2a354307f43a96b42",
    "forget-lineage-missing-origin": "1a4c936a79616320522d5691ce8083424f66c6326733278306fe241a9701f1c4",
}
POLICY = (
    "Complete preview, commit and repeated-commit reports, errors, memory files, "
    "origins, tombstones and logical state are compared. Only the SDK's exact "
    "empty memory/.dreams/short-term-promotion.lock.guard coordination inode is "
    "excluded from portable files after independently verifying its raw bytes "
    "and absent-before/present-after-commit lifecycle. All original results, "
    "physical files and SQL rows are retained unchanged. No other field allowance."
)
DRIVER_SCOPE = (
    "Original CLI forget and SDK forget owners, persisted session selectors, "
    "direct daily content, promoted and mixed-lineage entries, missing origins; "
    "preview followed by commit and repeated commit. No replay boundary credit."
)


def case_wire(case):
    return json.dumps({key: case[key] for key in ("id", "operation", "input")},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf8")


def build_cases():
    cases = diagnostic_cases()[:3]
    for case in cases:
        case.update(covers=list(POINTS), normalizationPolicy=POLICY, driverScope=DRIVER_SCOPE)
        if hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]:
            raise ValueError("Forget outcome inputs differ from the original frozen baseline")
    return cases


def validate_case(case):
    if not isinstance(case, dict) or not any(
            json.dumps(case, sort_keys=True, ensure_ascii=False, allow_nan=False)
            == json.dumps(original, sort_keys=True, ensure_ascii=False, allow_nan=False)
            for original in build_cases()):
        raise ValueError("Forget outcomes require one exact registered three-case member")
    return deepcopy(case)


def family_members(cases):
    return [case for case in cases if case.get("operation") == OPERATION
            or str(case.get("id", "")).startswith("forget-lineage-")
            or set(case.get("covers", ())) & set(POINTS)]


def validate_registration(cases):
    family = family_members(cases)
    if family:
        if [case.get("id") for case in family] != list(CASE_HASHES):
            raise ValueError("Forget outcomes require the complete unchanged three-case family atomically")
        for case in family:
            validate_case(case)


def family_complete(rows):
    family = family_members(rows)
    if len(family) != len(CASE_HASHES) or [row.get("id") for row in family] != list(CASE_HASHES):
        return False
    try:
        for row in family:
            validate_case({key: row[key] for key in (
                "id", "operation", "requirement", "covers", "input", "normalizationPolicy", "driverScope")})
        return all(row.get("status") == "matched" and row.get("runtimeEvidenceValidated") is True
                   for row in family)
    except (KeyError, TypeError, ValueError):
        return False
