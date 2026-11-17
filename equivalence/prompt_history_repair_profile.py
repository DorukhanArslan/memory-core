"""Independent exact-case authority for genuine integrated history projection."""
from copy import deepcopy
import hashlib
from pathlib import Path

from equivalence.prompt_history_repair import (
    OPERATION, CASE_HASHES, POLICY, DRIVER_SCOPE, build_cases, canonical, validate_case, case_wire,
)
from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority

PROVIDER_ADAPTER_FILES = (
    "prompt-runtime-provider/index.mjs", "prompt-runtime-provider/openclaw.plugin.json",
)
PROVIDER_SOURCE_HASHES = {
    "prompt-runtime-provider/index.mjs": "30569e909a0efdd6a5162a85475935528f7c99394d37e891eb6ab777217d143f",
    "prompt-runtime-provider/openclaw.plugin.json": "118098ca3ea9ec4c0b5e5977ddc2ea7a8e6e3541753c817b4c0ab4de10f666c5",
}
POLICY_SHA256 = "354c67f4dc0ca90bb6e6d989d5a0a7ceb6b0404465891a04104dadac6056621e"
DRIVER_SCOPE_SHA256 = "2e3ce984de0537c4316b10a912eb3a8ce1e25556ad10c21b28ea5de4d23f5f16"


def case_bindings():
    if (hashlib.sha256(POLICY.encode()).hexdigest() != POLICY_SHA256
            or hashlib.sha256(DRIVER_SCOPE.encode()).hexdigest() != DRIVER_SCOPE_SHA256):
        raise ValueError("The complete frozen history-repair business definition changed")
    actual = {case["id"]: hashlib.sha256(case_wire(case)).hexdigest() for case in build_cases()}
    if actual != CASE_HASHES:
        raise ValueError("The complete frozen prompt-history-repair family changed")
    return actual


def validate_prompt_history_repair_profile(value):
    if (not isinstance(value, dict) or set(value) != {
        "kind", "operation", "inputKind", "nodeRuntime", "caseId", "caseBindings"}
            | {"policySha256", "driverScopeSha256"}
            or value["kind"] != "approved-prompt-history-repair-profile"
            or value["operation"] != OPERATION or value["inputKind"] != "prompt-history-repair"
            or canonical(value["caseBindings"]) != canonical(case_bindings())
            or value["policySha256"] != POLICY_SHA256
            or value["driverScopeSha256"] != DRIVER_SCOPE_SHA256
            or value["caseId"] not in CASE_HASHES):
        raise ValueError("Prompt history repair requires its distinct complete frozen capability")
    validate_model_node_authority(value["nodeRuntime"])
    return deepcopy(value)


def prepare_prompt_history_repair_profile(case, node: Path):
    validate_case(case)
    return validate_prompt_history_repair_profile({
        "kind": "approved-prompt-history-repair-profile", "operation": OPERATION,
        "inputKind": "prompt-history-repair", "nodeRuntime": prepare_model_node_authority(node),
        "caseId": case["id"], "caseBindings": case_bindings(),
        "policySha256": POLICY_SHA256, "driverScopeSha256": DRIVER_SCOPE_SHA256})
