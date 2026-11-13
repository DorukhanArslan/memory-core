"""Proposed closed query-sync boundary family; no runtime or scope credit here.

The literal byte seal and exact family are reviewed before any original host.
The outcome sibling keeps its original seven definitions independently closed.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

OPERATION = "query-sync-boundaries-runtime"
OUTCOME_OPERATION = "query-sync-outcomes-runtime"
REQUIREMENT = "indexing.query-sync"
POINTS = ("indexing.query-sync.boundaries",)
MANIFEST = Path(__file__).resolve().parents[1] / "docs/query_sync_boundaries_literals.json"
MANIFEST_SHA256 = '3c1c3183604c7d75f393eaf0b077e402102312eff1f26ea78242c903c1633939'
CASE_HASHES = {'query-sync-boundaries-clean-cold-repeat': '00cbfb8e3ad5d04e0879e00aee596791bd5f39fabaae3bdb79e416c64589c102', 'query-sync-boundaries-warm-force-unchanged': '8d7c9c217c33c0bbebaf974d0107df6984c2b3ec098d6cc33c7d0070804f1a27', 'query-sync-boundaries-joined-force-and-query': '206b2278b15383488743a6fb2cda924242e98396bec973e8655d401032f59f5f', 'query-sync-boundaries-joined-failure-persistent-cold-recovery': 'ab36c05321175afc4c2270df2b757d7f5dd766c7d5241e0235991db400bbd981', 'query-sync-boundaries-warm-failure-natural-retry': '75510a726cf7d398bc2292a5ae8a9219f8e00309abbef7bc0e4c62e8f7832013', 'query-sync-boundaries-typed-conflict-once-retry': '6fbb327e767dc3a98fa80f03e24c5103c447e47c5a7951e66e0214efbfc95b6a', 'query-sync-boundaries-typed-conflict-twice-exhaustion': 'faa4be9c79b3515d75f3d5545cdac27ce1824784f11cb35e77895260fa1600a2', 'query-sync-boundaries-newer-empty-public-refusal-cli-override': '4f349eaf0498dceec8dbd91304b747e98757d60655af24390d8153cb7be64f1c'}


def case_wire(case):
    return json.dumps({key: case[key] for key in ("id", "operation", "input")},
        sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def validate_case(case):
    if (not isinstance(case, dict)
            or set(case) != {"id", "operation", "requirement", "covers", "input"}
            or case.get("operation") != OPERATION or case.get("requirement") != REQUIREMENT
            or case.get("covers") != list(POINTS) or case.get("id") not in CASE_HASHES
            or hashlib.sha256(case_wire(case)).hexdigest() != CASE_HASHES[case["id"]]):
        raise ValueError("Query-sync boundaries require an exact independently frozen boundary literal")
    return deepcopy(case)


def build_cases(path=MANIFEST):
    payload = Path(path).read_bytes()
    if hashlib.sha256(payload).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Query-sync boundary literal manifest changed after its reviewed byte seal")
    manifest = json.loads(payload)
    if (set(manifest) != {"kind", "acceptancePointsAwarded", "cases"}
            or manifest["kind"] != "query-sync-boundaries-acceptance-literals"
            or type(manifest["acceptancePointsAwarded"]) is not int
            or manifest["acceptancePointsAwarded"] != 0
            or [case.get("id") for case in manifest["cases"]] != list(CASE_HASHES)):
        raise ValueError("Query-sync boundaries require the complete closed eight-member family")
    return [validate_case(case) for case in manifest["cases"]]


def family_members(cases):
    return [case for case in cases if case.get("operation") == OPERATION
        or str(case.get("id", "")).startswith("query-sync-boundaries-")
        or set(case.get("covers", ())) & set(POINTS)
        or case.get("requirement") == REQUIREMENT and case.get("operation") != OUTCOME_OPERATION]


def validate_registration(cases):
    family = family_members(cases)
    if not family:
        return
    if len(family) != len(CASE_HASHES) or [case.get("id") for case in family] != list(CASE_HASHES):
        raise ValueError("Query-sync boundaries require the complete eight-case family atomically")
    for case in family:
        validate_case(case)
