"""Closed whole-host update/isolation family for the two original acceptance conditions."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "host-update-isolation-runtime"
REQUIREMENT = "host.update-isolation"
POINTS = ("host.update-isolation.outcomes", "host.update-isolation.boundaries")
CASE_HASHES = {'host-update-isolation-ascii': 'f2baee25788e38724908c1bab506906b246875926d98d1235e585cb6c8005393', 'host-update-isolation-unicode': '48a300945ad635e1e129f85c02729527ae300def9c46d75f0c2004258ec8ae01', 'host-update-isolation-write-refusal': '658b4988acd0fc3efe3710275476f4345ddc06c4ef8b2f4349de63ff30dbb320', 'host-update-isolation-publication-failure': 'ea32fd43d2f13f760b889513f1e228b5272390fdab080bb3ee45fa59fdc04bd2'}
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


def build_cases():
    path = Path(__file__).resolve().parents[1] / "docs/host_update_isolation_literals.json"
    manifest = json.loads(path.read_text(encoding="utf8"))
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
