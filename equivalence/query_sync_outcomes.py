"""Closed real-owner family for the original query-sync outcome condition.

Inputs are fixed before paired execution. Actual public seed, first and reopened
results remain distinct; original owner close supplies the completion boundary.
Standalone probes and source inventory do not award acceptance conditions.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "query-sync-outcomes-runtime"
REQUIREMENT = "indexing.query-sync"
POINTS = ("indexing.query-sync.outcomes",)
CASE_HASHES = {'query-sync-outcomes-cold-existing-no-index': '2cfbdbda1abf050d61255b3fafe7c577d1d95ba532b6e69e12dd5773277f16c2',
 'query-sync-outcomes-cold-empty-then-add': '1bf92fb4e5c924792d0df44a682912ccc00a36a8712531b65946cbdee8d56eef',
 'query-sync-outcomes-warm-unchanged': '32d6d1acdccb7129db779729182d22bd767b0235787d7c54ad6e7ac56bd4840e',
 'query-sync-outcomes-warm-edit': '5fa326d5745fe5bbdea3826d1b66a539acf02901814a65af2d89934129664b59',
 'query-sync-outcomes-warm-delete': 'c28686e39f9739b397a0b3ae3e9879d2a624ef12123c81a6d0b7b5d0b79da7b9',
 'query-sync-outcomes-warm-rename': 'df6bd13ac9792f7f5f4aef86d78833a9909e3a36fbdaa412ba57c5301e41cc5e',
 'query-sync-outcomes-warm-touch-same-bytes': '05fd6486cc377ac469b1c08616be55612b9c1330e79d7117f8e625b01ce143de'}
MANIFEST = Path(__file__).resolve().parents[1] / "docs/query_sync_outcomes_literals.json"


def case_wire(case):
    return json.dumps({key: case[key] for key in ("id", "operation", "input")},
                      sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def validate_case(case):
    if (not isinstance(case, dict)
            or set(case) != {"id", "operation", "requirement", "covers", "input"}
            or case.get("operation") != OPERATION or case.get("requirement") != REQUIREMENT
            or case.get("covers") != list(POINTS) or case.get("id") not in CASE_HASHES
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Query-sync outcomes require an exact independently frozen seven-case literal")
    return deepcopy(case)


def build_cases(path=MANIFEST):
    manifest = json.loads(Path(path).read_text(encoding="utf8"))
    if (not isinstance(manifest, dict)
            or set(manifest) != {"kind", "acceptancePointsAwarded", "cases"}
            or manifest["kind"] != "query-sync-outcomes-acceptance-literals"
            or type(manifest["acceptancePointsAwarded"]) is not int
            or manifest["acceptancePointsAwarded"] != 0
            or not isinstance(manifest["cases"], list)
            or any(not isinstance(case, dict) for case in manifest["cases"])
            or [case.get("id") for case in manifest["cases"]] != list(CASE_HASHES)):
        raise ValueError("The original query-sync outcome condition requires all seven independently frozen literals")
    return [validate_case(case) for case in manifest["cases"]]


def family_members(cases):
    return [case for case in cases if case.get("operation") == OPERATION
            or (case.get("requirement") == REQUIREMENT
                and case.get("operation") != "query-sync-boundaries-runtime")
            or str(case.get("id", "")).startswith("query-sync-outcomes-")
            or set(case.get("covers", ())) & set(POINTS)]


def validate_registration(cases):
    family = family_members(cases)
    if not family:
        return
    if len(family) != len(CASE_HASHES) or [case.get("id") for case in family] != list(CASE_HASHES):
        raise ValueError("The original query-sync outcome condition requires the complete seven-case family atomically")
    for case in family:
        validate_case(case)
