"""Explicit compiled-only entry profiles and their exact executable authority."""
from copy import deepcopy
from pathlib import Path

from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority


ENTRY_PROVENANCE_PROFILES = {
    "entry-memory-publication-runtime": "published-memory",
    "entry-session-publication-runtime": "session-projection",
    "entry-provider-preparation-runtime": "prepared-provider",
}


def validate_entry_provenance_profile(value):
    if (not isinstance(value, dict) or set(value) != {"kind", "operation", "inputKind", "nodeRuntime"}
            or value["kind"] != "approved-entry-provenance-profile"
            or value["operation"] not in ENTRY_PROVENANCE_PROFILES
            or value["inputKind"] != ENTRY_PROVENANCE_PROFILES[value["operation"]]):
        raise ValueError("Entry provenance requires one explicit reviewed compiled profile")
    validate_model_node_authority(value["nodeRuntime"])
    return deepcopy(value)


def prepare_entry_provenance_profile(operation: str, node: Path):
    if operation not in ENTRY_PROVENANCE_PROFILES:
        raise ValueError("An unrelated operation cannot borrow the entry profile capability")
    return validate_entry_provenance_profile({"kind": "approved-entry-provenance-profile", "operation": operation,
        "inputKind": ENTRY_PROVENANCE_PROFILES[operation], "nodeRuntime": prepare_model_node_authority(node)})
