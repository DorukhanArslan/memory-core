"""Frozen producer-publication host restart development inputs; never award acceptance credit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "host-restart-publication-runtime"
CASE_HASHES = {'host-restart-publication-memory-ascii': 'a9abc2c074286701c82f687ebd906102589164c19b9d9c0dbc503073ccbcb7b7', 'host-restart-publication-memory-unicode': 'b375edb367f6820d99a9398db9e384cf640819ae7fd246766c45d955f93b4c5b', 'host-restart-publication-indexed-sessions': '3121b9952df01cee2e8b9cb0e8492600f560e3c87af51e632e56c71970050bd1', 'host-restart-publication-get-failure': '05fbc5db48c37efeac4a15b38d5291f4203fcc318e70ea4131ac5b05351261ba'}


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
    path = Path(__file__).resolve().parents[1] / "docs/host_restart_publication_literals.json"
    cases = json.loads(path.read_text(encoding="utf8"))["cases"]
    if [case["id"] for case in cases] != list(CASE_HASHES):
        raise ValueError("Restart development requires all distinct frozen literals")
    return [validate_case(case) for case in cases]
