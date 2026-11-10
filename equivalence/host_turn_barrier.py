"""Closed natural save/follow-up family for the original turn-barrier outcome.

The separate boundary condition is deliberately uncovered: optional maintenance
preemption, admitted-writer settlement and failure admission need other evidence.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "host-turn-barrier-runtime"
REQUIREMENT = "host.turn-barrier"
POINTS = ("host.turn-barrier.outcomes",)
CASE_HASHES = {
    "host-turn-barrier-cold-ascii": "f15b6b765b7998301945a42e5028a30cbc759fb8251c7e814b35778a88a06e66",
    "host-turn-barrier-warm-ascii": "a66a8fd95c63ece444cfa50d4c575de504ae1d05b9a9d3dcd5367809b93d0da3",
    "host-turn-barrier-cold-unicode": "76f267e1c678d0ec7ffac28e309bea3360bd31f75230ebf59c6f8a6bdec06a65",
    "host-turn-barrier-warm-unicode": "cf7ce1144290e45d8bffa4fc230bbb5fcd26569787bccf149282a66455468750",
}
MANIFEST = Path(__file__).resolve().parents[1] / "docs/host_turn_barrier_outcomes_literals.json"


def case_wire(case):
    return json.dumps({key: case[key] for key in ("id", "operation", "input")},
                      sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def validate_case(case):
    if (not isinstance(case, dict) or set(case) != {"id", "operation", "requirement", "covers", "input"}
            or case.get("operation") != OPERATION or case.get("requirement") != REQUIREMENT
            or case.get("covers") != list(POINTS) or case.get("id") not in CASE_HASHES
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Turn-barrier outcomes require an exact independently frozen natural-host literal")
    return deepcopy(case)


def build_cases(path=MANIFEST):
    manifest = json.loads(Path(path).read_text(encoding="utf8"))
    if (set(manifest) != {"kind", "acceptancePointsAwarded", "cases"}
            or manifest["kind"] != "host-turn-barrier-outcomes-acceptance-literals"
            or manifest["acceptancePointsAwarded"] != 0
            or [case["id"] for case in manifest["cases"]] != list(CASE_HASHES)):
        raise ValueError("The outcome requires all four frozen cold/warm ASCII/Unicode cases")
    return [validate_case(case) for case in manifest["cases"]]


def validate_registration(cases):
    family = [case for case in cases if case.get("requirement") == REQUIREMENT or case.get("operation") == OPERATION
              or set(case.get("covers", ())) & set(POINTS)]
    if not family:
        return
    if len(family) != len(CASE_HASHES) or {case["id"] for case in family} != set(CASE_HASHES):
        raise ValueError("The natural save/follow-up outcome requires the complete four-case family atomically")
    for case in family:
        validate_case(case)
