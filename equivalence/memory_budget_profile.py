"""Independent compiled-only authority for the two fixed #38 boundaries."""
from copy import deepcopy
from pathlib import Path

from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority


MEMORY_BUDGET_PROFILES = {"memory-budget-runtime": "memory-budget", "memory-budget-apply-runtime": "memory-budget-apply"}


def validate_memory_budget_input(value):
    if not isinstance(value, dict) or value.get("kind") not in MEMORY_BUDGET_PROFILES.values():
        raise ValueError("Unknown memory-budget input kind")
    fields = {"kind", "nowMs", "cases"} if value["kind"] == "memory-budget" else {
        "kind", "nowMs", "files", "recall", "candidates", "options"}
    if set(value) != fields:
        raise ValueError("A memory-budget input cannot borrow another runtime surface")
    if value["kind"] == "memory-budget-apply" and set(value["options"]) != {
            "timezone", "memoryFileMaxChars", "maxPriorEntryLossFraction", "minScore", "minRecallCount", "minUniqueQueries", "limit"}:
        raise ValueError("The ordinary budget apply profile cannot add model, host or general promotion options")


def validate_memory_budget_profile(value):
    if (not isinstance(value, dict) or set(value) != {"kind", "operation", "inputKind", "nodeRuntime"}
            or value["kind"] != "approved-memory-budget-profile" or value["operation"] not in MEMORY_BUDGET_PROFILES
            or value["inputKind"] != MEMORY_BUDGET_PROFILES[value["operation"]]):
        raise ValueError("Memory budget requires one explicit compiled-only operation capability")
    validate_model_node_authority(value["nodeRuntime"])
    return deepcopy(value)


def prepare_memory_budget_profile(operation: str, node: Path):
    if operation not in MEMORY_BUDGET_PROFILES:
        raise ValueError("An unrelated operation cannot borrow memory-budget authority")
    return validate_memory_budget_profile({"kind": "approved-memory-budget-profile", "operation": operation,
        "inputKind": MEMORY_BUDGET_PROFILES[operation], "nodeRuntime": prepare_model_node_authority(node)})
