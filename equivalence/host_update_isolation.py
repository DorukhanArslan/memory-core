"""Closed whole-host update/isolation family for the two original acceptance conditions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "host-update-isolation-runtime"
REQUIREMENT = "host.update-isolation"
POINTS = ("host.update-isolation.outcomes", "host.update-isolation.boundaries")
CASE_HASHES = {'host-update-isolation-ascii': '03bea4c1977b6bddd1095fff2e348f65481e8dbf31585f40e7ff0acd02d4b290', 'host-update-isolation-unicode': '94c6f266e48c7cedee5447e19790a3dbe4ad08435453a0a0bfff7676cb1aae63', 'host-update-isolation-write-refusal': 'e9d7c0bc7447242718a736bbcdc62cf027caa77ce4cced3be9d809962c6fddf8', 'host-update-isolation-publication-failure': '35885ea502411889777c9c76e4f3b0ea043f0baf67a00e4cf0805ae8c3d774fc'}
FAULTS = ("source-hard-link-during-update", "index-publication-sidecar-symlink")


def case_wire(case):
    return json.dumps({key: case[key] for key in ("id", "operation", "input")},
                      sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def validate_case(case):
    if (not isinstance(case, dict) or set(case) != {"id", "operation", "requirement", "covers", "input"}
            or case.get("operation") != OPERATION or case.get("requirement") != REQUIREMENT
            or case.get("covers") != list(POINTS) or case.get("id") not in CASE_HASHES
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Host update acceptance requires an exact independently frozen whole-host literal")
    return deepcopy(case)


MANIFEST = Path(__file__).resolve().parents[1] / "docs/host_update_isolation_literals.json"


def build_cases(path=MANIFEST):
    manifest = json.loads(Path(path).read_text(encoding="utf8"))
    if (set(manifest) != {"kind", "acceptancePointsAwarded", "cases"}
            or manifest["kind"] != "host-update-isolation-acceptance-literals"
            or manifest["acceptancePointsAwarded"] != 0
            or [case["id"] for case in manifest["cases"]] != list(CASE_HASHES)):
        raise ValueError("Host update acceptance requires all four independently frozen literals")
    return [validate_case(case) for case in manifest["cases"]]


def validate_registration(cases):
    family = [case for case in cases if case.get("operation") == OPERATION
              or set(case.get("covers", ())) & set(POINTS)]
    if not family:
        return
    if len(family) != len(CASE_HASHES) or {case["id"] for case in family} != set(CASE_HASHES):
        raise ValueError("Both host update conditions require the complete four-case family atomically")
    for case in family:
        validate_case(case)
