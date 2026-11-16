"""Independent closed capability for the durable forget/admission boundary."""
from copy import deepcopy
import hashlib
from pathlib import Path

from equivalence.forget_boundaries import OPERATION, CASE_HASHES, build_cases, canonical, validate_case, case_wire
from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority


def case_bindings():
    cases = build_cases()
    actual = {case["id"]: hashlib.sha256(case_wire(case)).hexdigest() for case in cases}
    if actual != CASE_HASHES:
        raise ValueError("The durable forget/admission family changed")
    return actual


def validate_forget_boundaries_profile(value):
    if (not isinstance(value, dict) or set(value) != {
        "kind", "operation", "inputKind", "nodeRuntime", "caseId", "caseBindings"}
            or value["kind"] != "approved-forget-boundaries-profile"
            or value["operation"] != OPERATION or value["inputKind"] != "forget-lineage-tombstones"
            or canonical(value["caseBindings"]) != canonical(case_bindings())
            or value["caseId"] not in CASE_HASHES):
        raise ValueError("Forget boundaries require their distinct exact capability")
    validate_model_node_authority(value["nodeRuntime"])
    return deepcopy(value)


def prepare_forget_boundaries_profile(case, node: Path):
    validate_case(case)
    return validate_forget_boundaries_profile({
        "kind": "approved-forget-boundaries-profile", "operation": OPERATION,
        "inputKind": "forget-lineage-tombstones", "nodeRuntime": prepare_model_node_authority(node),
        "caseId": case["id"], "caseBindings": case_bindings()})
