"""Frozen zero-credit Host v3 business inputs and explicit environment policy.

These cases are deliberately absent from the registered catalog. Promotion is a
separate reviewed version migration; the old Host v1 definitions remain intact.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from equivalence import host_turn_barrier as legacy

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/host_turn_barrier_v3_literals.json"
CONTRACT = ROOT / "docs/host_turn_barrier_v3_environment.json"
MANIFEST_SHA256 = "ac55a8e9a56bf93b4c8694cbffa0ddfb118dc3568a46d7bb742b0f0e1e6bf94f"
CONTRACT_SHA256 = "dee164f3a52ea7a8ae839844790dd5ec1664f2a31bd4019077110065ec60eed2"
OPERATION = "host-turn-barrier-v3-runtime"
POINTS = ("host.turn-barrier.outcomes",)
CASE_HASHES = {
    "host-turn-barrier-v3-cold-ascii": "5daf83c8f0a4e2340cef1c052eec56e0dbea08363790c88e6ccc97273c94ef4e",
    "host-turn-barrier-v3-warm-ascii": "ccfe267de03bf4de8a380a22b3bb31fbe72e8242f0a796f454b3a5367689a8d7",
    "host-turn-barrier-v3-cold-unicode": "b14412f7213fa398f2c6f0ca3201e7ff2a248f0013fd05b32575685e933a8895",
    "host-turn-barrier-v3-warm-unicode": "5b85eed307c5f8a88ccccf3bb48cea32863c3778ae9da391fecd295b92c6af7c",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode()


def _read_frozen(path, expected):
    path = Path(path)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("A frozen Host v3 input changed")
    return json.loads(data)


def environment_contract():
    return _read_frozen(CONTRACT, CONTRACT_SHA256)


def case_wire(case):
    return canonical({key: case[key] for key in ("id", "operation", "input")})


def business_case(case):
    value = case["input"]["businessCase"]
    original = next((row for row in legacy.build_cases() if row["id"] == value.get("id")), None)
    if original is None or legacy.case_wire(original) != canonical(value):
        raise ValueError("Host v3 changed an original Host v1 business input")
    return deepcopy(original)


def validate_case(case, *, registered=False):
    environment_contract()
    if type(registered) is not bool:
        raise ValueError("Host v3 requires an explicit Boolean registration mode")
    expected_covers = list(POINTS) if registered else []
    if (not isinstance(case, dict)
            or set(case) != {"id", "operation", "requirement", "covers", "input"}
            or case.get("operation") != OPERATION or case.get("requirement") != legacy.REQUIREMENT
            or case.get("covers") != expected_covers or case.get("id") not in CASE_HASHES
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Host v3 requires one exact frozen zero-credit input")
    original = business_case(case)
    if (case["id"] != original["id"].replace("host-turn-barrier-", "host-turn-barrier-v3-", 1)
            or case["input"]["environment"]["contractSha256"] != CONTRACT_SHA256):
        raise ValueError("Host v3 lost its original business/environment binding")
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
            or value["kind"] != "host-turn-barrier-v3-zero-credit-literals"
            or type(value["version"]) is not int or value["version"] != 3
            or type(value["acceptancePointsAwarded"]) is not int or value["acceptancePointsAwarded"] != 0
            or value["candidateCoverage"] != list(POINTS)
            or value["environmentContractSha256"] != CONTRACT_SHA256
            or [row["id"] for row in value["cases"]] != list(CASE_HASHES)):
        raise ValueError("Host v3 requires its complete ordered frozen four-case manifest")
    return [validate_case(case) for case in value["cases"]]


def validate_registration(cases):
    """Check an explicitly promoted family; never add it to a catalog."""
    family = [case for case in cases if case.get("operation") == OPERATION
              or case.get("id") in CASE_HASHES]
    if not family:
        return
    expected = [registered_case(case) for case in build_cases()]
    if family != expected or any(case.get("id") in legacy.CASE_HASHES for case in cases):
        raise ValueError("Host v3 registration must be the exact covers-only four-case migration")
