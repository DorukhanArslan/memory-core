"""Frozen source-policy host restart development inputs; never award acceptance credit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "host-restart-policy-runtime"
CASE_HASHES = {'host-restart-policy-memory-ascii': '1a0344bdf3122292b8826e61fa872126336ec0fd702df6aaf7ebe7cf134be7c3', 'host-restart-policy-memory-unicode': '11f2e9f9c2c630b86524ea9562fbe97f6ff18ed5b31c01fb2501fbf0c9df3aa8', 'host-restart-policy-indexed-sessions': '467500cf9c27e7a3e34e5eb37f73bcd462e3bf4e71c204b22272b9d3e53e7824', 'host-restart-policy-get-failure': '619ccf906f456cbd40f18ab10098adfd715d2f55699736b014162a6a7dbfd710'}


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
    path = Path(__file__).resolve().parents[1] / "docs/host_restart_policy_literals.json"
    cases = json.loads(path.read_text(encoding="utf8"))["cases"]
    if [case["id"] for case in cases] != list(CASE_HASHES):
        raise ValueError("Restart development requires all distinct frozen literals")
    return [validate_case(case) for case in cases]
