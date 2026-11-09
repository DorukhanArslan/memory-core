"""Frozen whole-host restart development inputs; never award acceptance credit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "host-restart-recall-runtime"
CASE_HASHES = {'host-restart-ascii-recall': 'b64ab1b162aa4c81e5713bc51469972b3cb78460206763389b6fd62e84583e91', 'host-restart-unicode-recall': 'c1e13ac38870951148306f924931fb76f0bfd9324bb34cfa3cb04e8fa3fab0bd', 'host-restart-source-replaced-before-get': '72a5d40610a87b53687c432385fc1dc21173f1d99f2fc9e3ce480f6517a3d15d'}


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
    path = Path(__file__).resolve().parents[1] / "docs/host_restart_recall_literals.json"
    cases = json.loads(path.read_text(encoding="utf8"))["cases"]
    if [case["id"] for case in cases] != list(CASE_HASHES):
        raise ValueError("Restart development requires all distinct frozen literals")
    return [validate_case(case) for case in cases]
