"""Exact six-case, zero-credit authority for the first forget/lineage baseline."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from equivalence.forget_lineage_cases import OPERATION, build_cases, validate_case
from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority

FAMILY_SHA256 = "f969f52453664edcc52c4a8f4ac25f47817cc5b02f786e602348c66939c8209d"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf8")


def case_sha256(case):
    return hashlib.sha256(canonical({key: case[key] for key in ("id", "operation", "input")})).hexdigest()


def case_bindings():
    cases = build_cases()
    bindings = {case["id"]: case_sha256(case) for case in cases}
    if len(cases) != len(bindings) or len(cases) != 6 or hashlib.sha256(canonical(bindings)).hexdigest() != FAMILY_SHA256:
        raise ValueError("The six forget/lineage inputs differ from their frozen authority")
    return bindings


def validate_forget_lineage_profile(value):
    if (not isinstance(value, dict) or set(value) != {
        "kind", "operation", "inputKind", "nodeRuntime", "caseId", "caseBindings"}
            or value["kind"] != "approved-forget-lineage-profile"
            or value["operation"] != OPERATION or value["inputKind"] != "forget-lineage-tombstones"
            or value["caseBindings"] != case_bindings() or value["caseId"] not in value["caseBindings"]):
        raise ValueError("Forget/lineage requires its exact independent six-case capability")
    validate_model_node_authority(value["nodeRuntime"])
    return deepcopy(value)


def prepare_forget_lineage_profile(case, node: Path):
    validate_case(case)
    return validate_forget_lineage_profile({
        "kind": "approved-forget-lineage-profile", "operation": OPERATION,
        "inputKind": "forget-lineage-tombstones", "nodeRuntime": prepare_model_node_authority(node),
        "caseId": case["id"], "caseBindings": case_bindings()})
