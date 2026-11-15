"""Frozen zero-credit Host v4 business inputs and explicit environment policy.

These cases are deliberately absent from the registered catalog. Promotion is a
separate reviewed version migration; the old Host v1 definitions remain intact.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from equivalence import host_turn_barrier as legacy

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/host_turn_barrier_v4_literals.json"
CONTRACT = ROOT / "docs/host_turn_barrier_v4_environment.json"
MANIFEST_SHA256 = "4fd480fe36780423b49bcf064687db37101648fe03c2ff14661923487ac031c8"
CONTRACT_SHA256 = "124be0e13fbf71f99092e8a3ebadf5dec0aef8d2d01d6df49366a8c359abf49e"
OPERATION = "host-turn-barrier-v4-runtime"
POINTS = ("host.turn-barrier.outcomes",)
CASE_HASHES = {
    "host-turn-barrier-v4-cold-ascii": "4942a650229e64d74332f9bd970c757e36a99e34990d944431097dfdd361b0ba",
    "host-turn-barrier-v4-warm-ascii": "6c3c660a22b18751ce55ff788827bc3b32f3ebff0164dee30c6d78f7432b2bf8",
    "host-turn-barrier-v4-cold-unicode": "68cdbab5a3d82d4bf7757406024623e20a2024806832bd433153c4aced30cdb6",
    "host-turn-barrier-v4-warm-unicode": "314c621f07bd12ab992ac9b146f31f294ed4db97180508b85121771b3a754913",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode()


def _read_frozen(path, expected):
    path = Path(path)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("A frozen Host v4 input changed")
    return json.loads(data)


def environment_contract():
    return _read_frozen(CONTRACT, CONTRACT_SHA256)


def case_wire(case):
    return canonical({key: case[key] for key in ("id", "operation", "input")})


def business_case(case):
    value = case["input"]["businessCase"]
    original = next((row for row in legacy.build_cases() if row["id"] == value.get("id")), None)
    if original is None or legacy.case_wire(original) != canonical(value):
        raise ValueError("Host v4 changed an original Host v1 business input")
    return deepcopy(original)


def validate_case(case, *, registered=False):
    environment_contract()
    if type(registered) is not bool:
        raise ValueError("Host v4 requires an explicit Boolean registration mode")
    expected_covers = list(POINTS) if registered else []
    if (not isinstance(case, dict)
            or set(case) != {"id", "operation", "requirement", "covers", "input"}
            or case.get("operation") != OPERATION or case.get("requirement") != legacy.REQUIREMENT
            or case.get("covers") != expected_covers or case.get("id") not in CASE_HASHES
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Host v4 requires one exact frozen zero-credit input")
    original = business_case(case)
    if (case["id"] != original["id"].replace("host-turn-barrier-", "host-turn-barrier-v4-", 1)
            or case["input"]["environment"]["contractSha256"] != CONTRACT_SHA256):
        raise ValueError("Host v4 lost its original business/environment binding")
    return deepcopy(case)


def registered_case(probe):
    """Explicit reviewed covers-only transform; this registers nothing itself."""
    result = validate_case(probe)
    result["covers"] = list(business_case(result)["covers"])
    return validate_case(result, registered=True)


def build_cases():
    value = _read_frozen(MANIFEST, MANIFEST_SHA256)
    if (set(value) != {"kind", "version", "acceptancePointsAwarded", "candidateCoverage",
                       "environmentContractSha256", "cases"}
            or value["kind"] != "host-turn-barrier-v4-zero-credit-literals"
            or type(value["version"]) is not int or value["version"] != 4
            or type(value["acceptancePointsAwarded"]) is not int or value["acceptancePointsAwarded"] != 0
            or value["candidateCoverage"] != list(POINTS)
            or value["environmentContractSha256"] != CONTRACT_SHA256
            or [row["id"] for row in value["cases"]] != list(CASE_HASHES)):
        raise ValueError("Host v4 requires its complete ordered frozen four-case manifest")
    return [validate_case(case) for case in value["cases"]]


def validate_registration(cases):
    """Check an explicitly promoted family; never add it to a catalog."""
    family = [case for case in cases if case.get("operation") == OPERATION
              or case.get("id") in CASE_HASHES]
    if not family:
        return
    expected = [registered_case(case) for case in build_cases()]
    if family != expected or any(case.get("id") in legacy.CASE_HASHES for case in cases):
        raise ValueError("Host v4 registration must be the exact covers-only four-case migration")
