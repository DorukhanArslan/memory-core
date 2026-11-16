"""One complete end-to-end family for the original durable admission boundary.

The input contains facts and driven operations only. It never supplies forgotten
IDs or an admission result to either implementation.
"""
from copy import deepcopy
import hashlib
import json

from equivalence.forget_lineage_cases import build_cases as diagnostic_cases

OPERATION = "forget-boundaries-runtime"
REQUIREMENT = "forget.lineage-tombstones"
POINTS = ("forget.lineage-tombstones.boundaries",)
CASE_HASHES = {"forget-boundaries-session-replay": "6294fe19877e905f0e47ba6abc2e6c094437d73a0b29096e8f769d8a047a7db8"}
POLICY = (
    "Complete reports, memory files, origins, tombstones and admission decisions "
    "are compared before preview, after actual forget and after durable owner "
    "reopen/repetition. An absent optional exclusion reason is represented as "
    "JSON null; Native undefined and SDK None remain unchanged in raw owner "
    "returns. Only the verified exact empty SDK coordination inode is private "
    "storage, under the already reviewed outcome rule. All physical bytes and "
    "SQL captures remain retained. No grounded writer or backfill result is driven."
)
DRIVER_SCOPE = (
    "Actual original forget CLI, persisted A/B session catalogs and origin "
    "ledgers, original session-corpus/source/exclusion owners and SDK counterparts. "
    "Reopen reads durable databases in the same process, not a fresh host process. "
    "Independent B is a positive admission control; no full ingestion scan claim."
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf8")


def case_wire(case):
    return canonical({key: case[key] for key in ("id", "operation", "input")})


def build_cases():
    value = deepcopy(diagnostic_cases()[0]["input"])
    admit = {"op": "admission", "agentIds": ["main"]}
    value["operations"] = [deepcopy(admit), {"op": "forget", "sessionIds": ["A"], "dryRun": True},
                           deepcopy(admit), {"op": "forget", "sessionIds": ["A"]},
                           {"op": "reopen"}, deepcopy(admit),
                           {"op": "forget", "sessionIds": ["A"]},
                           {"op": "reopen"}, deepcopy(admit)]
    case = {"id": "forget-boundaries-session-replay", "operation": OPERATION,
            "requirement": REQUIREMENT, "covers": list(POINTS), "input": value,
            "normalizationPolicy": POLICY, "driverScope": DRIVER_SCOPE}
    if hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]:
        raise ValueError("Forget boundary input differs from its frozen authority")
    return [case]


def validate_case(case):
    if not isinstance(case, dict) or canonical(case) != canonical(build_cases()[0]):
        raise ValueError("Forget boundaries require their exact end-to-end admission case")
    return deepcopy(case)


def validate_input(value):
    if canonical(value) != canonical(build_cases()[0]["input"]):
        raise ValueError("Forget boundaries require the complete frozen input")


def family_members(cases):
    return [case for case in cases if case.get("operation") == OPERATION
            or str(case.get("id", "")).startswith("forget-boundaries-")
            or set(case.get("covers", ())) & set(POINTS)]


def validate_registration(cases):
    family = family_members(cases)
    if family:
        if len(family) != 1:
            raise ValueError("Forget boundaries require their complete family exactly once")
        validate_case(family[0])


def family_complete(rows):
    family = family_members(rows)
    if len(family) != 1:
        return False
    try:
        row = family[0]
        validate_case({key: row[key] for key in (
            "id", "operation", "requirement", "covers", "input", "normalizationPolicy", "driverScope")})
        return row.get("status") == "matched" and row.get("runtimeEvidenceValidated") is True
    except (KeyError, TypeError, ValueError):
        return False
