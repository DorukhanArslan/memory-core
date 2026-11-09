"""The exact executable capability for three original atomic-write owners."""
from __future__ import annotations

from pathlib import Path

from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority

ATOMIC_PUBLICATION_PROFILES = {
    "atomic-commit-runtime": "commit",
    "atomic-append-runtime": "append",
    "atomic-bootstrap-runtime": "bootstrap",
}


def validate_atomic_publication_profile(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != {"kind", "operation", "inputKind", "nodeRuntime"}
            or value.get("kind") != "approved-atomic-publication-profile"
            or value.get("operation") not in ATOMIC_PUBLICATION_PROFILES
            or value.get("inputKind") != ATOMIC_PUBLICATION_PROFILES[value["operation"]]):
        raise ValueError("Atomic execution is restricted to its three declared original owners")
    return {**value, "nodeRuntime": validate_model_node_authority(value["nodeRuntime"])}


def prepare_atomic_publication_profile(operation: str, node: Path) -> dict:
    if operation not in ATOMIC_PUBLICATION_PROFILES:
        raise ValueError("An unrelated operation cannot borrow the atomic capability")
    return validate_atomic_publication_profile({
        "kind": "approved-atomic-publication-profile", "operation": operation,
        "inputKind": ATOMIC_PUBLICATION_PROFILES[operation],
        "nodeRuntime": prepare_model_node_authority(node),
    })
