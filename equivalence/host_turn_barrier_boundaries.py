"""Closed six-case family for the original host turn-barrier boundary condition.

Inputs and schedules are independently frozen; standalone probes award no credit.
The outcome family remains separate and retains its existing exact membership.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "host-turn-barrier-boundaries-runtime"
REQUIREMENT = "host.turn-barrier"
POINTS = ("host.turn-barrier.boundaries",)
CASE_HASHES = {
    'host-turn-barrier-boundaries-pending-ascii': '3fb13d571213c7758e29fb99124863f3c97781281a1120a0aa8d77c07c97961a',
    'host-turn-barrier-boundaries-target-open-unicode': '3b4d4db5499d772a64368c34418d178f3d77c8746c0b019b75881a49c6f3b290',
    'host-turn-barrier-boundaries-committed-ascii': '019816c79b7f5540a6d4894f0b0a6f01135fc9f6c8396827b39213fdf23048ea',
    'host-turn-barrier-boundaries-maintenance-refusal-unicode': '50eccd137544f5b277283e869edb346ccd0ccef1518b571c9d0f55dae3b18dd9',
    'host-turn-barrier-boundaries-foreground-refusal-ascii': 'e6917adf98d0937c884d299706fd8a00219c325c2cb2283e3965891e71508378',
    'host-turn-barrier-boundaries-publication-failure-unicode': '2eae19b1881e1e19c4f172bfb8ebc2ce6284928a845494b8344a99e327dd26a5',
}
MANIFEST = Path(__file__).resolve().parents[1] / "docs/host_turn_barrier_boundaries_literals.json"


def case_wire(case):
    return json.dumps({key: case[key] for key in ("id", "operation", "input")},
                      sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def validate_case(case):
    if (not isinstance(case, dict) or set(case) != {"id", "operation", "requirement", "covers", "input"}
            or case.get("operation") != OPERATION or case.get("requirement") != REQUIREMENT
            or case.get("covers") != list(POINTS) or case.get("id") not in CASE_HASHES
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Turn-barrier boundaries require an exact independently frozen six-case literal")
    return deepcopy(case)


def build_cases(path=MANIFEST):
    manifest = json.loads(Path(path).read_text(encoding="utf8"))
    if (set(manifest) != {"kind", "acceptancePointsAwarded", "cases"}
            or manifest["kind"] != "host-turn-barrier-boundaries-acceptance-literals"
            or manifest["acceptancePointsAwarded"] != 0
            or [case["id"] for case in manifest["cases"]] != list(CASE_HASHES)):
        raise ValueError("The boundary condition requires all six independently frozen literals")
    return [validate_case(case) for case in manifest["cases"]]


def validate_registration(cases):
    family = [case for case in cases if case.get("operation") == OPERATION
              or str(case.get("id", "")).startswith("host-turn-barrier-boundaries-")
              or set(case.get("covers", ())) & set(POINTS)]
    if not family:
        return
    if len(family) != len(CASE_HASHES) or {case["id"] for case in family} != set(CASE_HASHES):
        raise ValueError("The original turn-barrier boundary requires the complete six-case family atomically")
    for case in family:
        validate_case(case)
