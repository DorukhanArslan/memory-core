"""The exact executable capability for three original atomic-write owners."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json

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


def validate_atomic_case_binding(value: dict) -> dict:
    if (not isinstance(value, dict) or set(value) != {"id", "operation", "inputJson", "inputSha256"}
            or not isinstance(value["id"], str) or not value["id"].startswith("storage.atomic-writes.")
            or value["operation"] not in ATOMIC_PUBLICATION_PROFILES
            or not isinstance(value["inputJson"], str) or len(value["inputJson"].encode("utf-8")) > 4 * 1024 * 1024
            or hashlib.sha256(value["inputJson"].encode("utf-8")).hexdigest() != value["inputSha256"]):
        raise ValueError("The atomic checkpoint requires its exact case and literal input binding")
    arguments = json.loads(value["inputJson"])
    if arguments.get("kind") != ATOMIC_PUBLICATION_PROFILES[value["operation"]] or arguments.get("version") != 1:
        raise ValueError("The atomic checkpoint cannot borrow another owner or fixture kind")
    return dict(value)


def prepare_atomic_case_binding(case: dict) -> dict:
    serialized = json.dumps(case["input"], ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return validate_atomic_case_binding({"id": case["id"], "operation": case["operation"],
        "inputJson": serialized, "inputSha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest()})
