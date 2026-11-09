"""Closed whole-host restart family for the two original acceptance conditions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "host-restart-session-runtime"
POINTS = ("host.restart-recall.outcomes", "host.restart-recall.boundaries")
CASE_HASHES = {'host-restart-session-memory-ascii': 'eafee7b0e98b6543cebaeff1523325796f83a4204a0d4eba03606255ccb383d4', 'host-restart-session-memory-unicode': '8cd6e9ff0c637d9449206e002b5cd89cdd21bff8a939d8018fcfa536442f5435', 'host-restart-session-indexed-sessions': '1ecac5a32934aceb2d5d3d9170e8a575f3c9ffb68fd0f59f155b1ce511011fa5', 'host-restart-session-get-failure': '4a2d28259018fd409f49dcb04e450e6946e95aa2abb7a949f2bdae5a0066bc8f'}


def case_wire(case):
    return json.dumps({key: case[key] for key in ("id", "operation", "input")},
                      sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def validate_case(case):
    if (not isinstance(case, dict) or set(case) != {"id", "operation", "requirement", "covers", "input"}
            or case.get("operation") != OPERATION or case.get("requirement") != "host.restart-recall"
            or case.get("covers") != list(POINTS) or case.get("id") not in CASE_HASHES
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Host restart acceptance requires an exact independently frozen whole-host literal")
    return deepcopy(case)


def build_cases():
    path = Path(__file__).resolve().parents[1] / "docs/host_restart_session_literals.json"
    manifest = json.loads(path.read_text(encoding="utf8"))
    if (set(manifest) != {"kind", "acceptancePointsAwarded", "cases"}
            or manifest["kind"] != "host-restart-session-acceptance-literals"
            or manifest["acceptancePointsAwarded"] != 0
            or [case["id"] for case in manifest["cases"]] != list(CASE_HASHES)):
        raise ValueError("Host restart acceptance requires all four independently frozen literals")
    return [validate_case(case) for case in manifest["cases"]]


def validate_registration(cases):
    family = [case for case in cases if case.get("operation") == OPERATION
              or set(case.get("covers", ())) & set(POINTS)]
    if not family:
        return
    if len(family) != len(CASE_HASHES) or {case["id"] for case in family} != set(CASE_HASHES):
        raise ValueError("Both host restart conditions require the complete four-case family atomically")
    for case in family:
        validate_case(case)
