"""Frozen managed-index host restart development inputs; never award acceptance credit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "host-restart-managed-runtime"
CASE_HASHES = {'host-restart-managed-memory-ascii': '85318392a2c1f24fb901a3b7a78ab8f594585dc043591b9d4fac2ea35ece7c31', 'host-restart-managed-memory-unicode': 'eebb928d61de1715fa9ab99053e535d4907557dd937f3c4e6e857e6886cb5b55', 'host-restart-managed-indexed-sessions': 'f9d30cccbd5f1889cc19b3f2155dadec1cbadb756f52067c07bc95ec0f362b49', 'host-restart-managed-get-failure': 'bfc58f0321ca253fb850826d5790a4fd8667d946a0106647acbdfae0369c7fff'}


def case_wire(case):
    return json.dumps({key: case[key] for key in ("id", "operation", "input")},
                      sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def validate_case(case):
    if (not isinstance(case, dict) or case.get("operation") != OPERATION
            or case.get("requirement") != "host.restart-recall" or case.get("covers") != []
            or case.get("id") not in CASE_HASHES
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Restart development requires an exact zero-credit literal")
    return deepcopy(case)


def build_cases():
    path = Path(__file__).resolve().parents[1] / "docs/host_restart_managed_literals.json"
    cases = json.loads(path.read_text(encoding="utf8"))["cases"]
    if [case["id"] for case in cases] != list(CASE_HASHES):
        raise ValueError("Restart development requires all distinct frozen literals")
    return [validate_case(case) for case in cases]
