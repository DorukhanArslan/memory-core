"""Independent exact-case authority for original recall-recording owners."""
from copy import deepcopy
import hashlib
from pathlib import Path

from equivalence.recall_signals import OPERATION, CASE_HASHES, build_cases, canonical, validate_case, case_wire
from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority


def case_bindings():
    actual = {case["id"]: hashlib.sha256(case_wire(case)).hexdigest() for case in build_cases()}
    if actual != CASE_HASHES:
        raise ValueError("The complete frozen recall-signals family changed")
    return actual


def validate_recall_signals_profile(value):
    if (not isinstance(value, dict) or set(value) != {
        "kind", "operation", "inputKind", "nodeRuntime", "caseId", "caseBindings"}
            or value["kind"] != "approved-recall-signals-profile"
            or value["operation"] != OPERATION or value["inputKind"] != "recall-signals"
            or canonical(value["caseBindings"]) != canonical(case_bindings())
            or value["caseId"] not in CASE_HASHES):
        raise ValueError("Recall signals require their distinct complete frozen capability")
    validate_model_node_authority(value["nodeRuntime"])
    return deepcopy(value)


def prepare_recall_signals_profile(case, node: Path):
    validate_case(case)
    return validate_recall_signals_profile({
        "kind": "approved-recall-signals-profile", "operation": OPERATION,
        "inputKind": "recall-signals", "nodeRuntime": prepare_model_node_authority(node),
        "caseId": case["id"], "caseBindings": case_bindings()})
