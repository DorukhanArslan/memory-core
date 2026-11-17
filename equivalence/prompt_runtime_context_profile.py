"""Independent exact-case authority for genuine memory/runtime model composition."""
from copy import deepcopy
import hashlib
from pathlib import Path

from equivalence.prompt_runtime_context import (
    OPERATION, CASE_HASHES, build_cases, canonical, validate_case, case_wire,
)
from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority

PROVIDER_ADAPTER_FILES = (
    "prompt-runtime-provider/index.mjs", "prompt-runtime-provider/openclaw.plugin.json",
)
PROVIDER_SOURCE_HASHES = {
    "prompt-runtime-provider/index.mjs": "30569e909a0efdd6a5162a85475935528f7c99394d37e891eb6ab777217d143f",
    "prompt-runtime-provider/openclaw.plugin.json": "118098ca3ea9ec4c0b5e5977ddc2ea7a8e6e3541753c817b4c0ab4de10f666c5",
}


def case_bindings():
    actual = {case["id"]: hashlib.sha256(case_wire(case)).hexdigest() for case in build_cases()}
    if actual != CASE_HASHES:
        raise ValueError("The complete frozen prompt-runtime-context family changed")
    return actual


def validate_prompt_runtime_context_profile(value):
    if (not isinstance(value, dict) or set(value) != {
        "kind", "operation", "inputKind", "nodeRuntime", "caseId", "caseBindings"}
            or value["kind"] != "approved-prompt-runtime-context-profile"
            or value["operation"] != OPERATION or value["inputKind"] != "prompt-runtime-context"
            or canonical(value["caseBindings"]) != canonical(case_bindings())
            or value["caseId"] not in CASE_HASHES):
        raise ValueError("Prompt runtime context requires its distinct complete frozen capability")
    validate_model_node_authority(value["nodeRuntime"])
    return deepcopy(value)


def prepare_prompt_runtime_context_profile(case, node: Path):
    validate_case(case)
    return validate_prompt_runtime_context_profile({
        "kind": "approved-prompt-runtime-context-profile", "operation": OPERATION,
        "inputKind": "prompt-runtime-context", "nodeRuntime": prepare_model_node_authority(node),
        "caseId": case["id"], "caseBindings": case_bindings()})
