"""Closed authority for the actual manager with its deterministic embedder."""
from copy import deepcopy
import hashlib
from pathlib import Path

from equivalence.embedding_cache_lifecycle import OPERATION, CASE_HASHES, build_cases, canonical, validate_case, case_wire
from equivalence.model_runtime_authority import prepare_model_node_authority, validate_model_node_authority

PROVIDER_MODE = "deterministic-embedding-fixture"
PROVIDER_ADAPTER_FILES = (
    "embedding-cache-provider/index.mjs", "embedding-cache-provider/openclaw.plugin.json",
)
PROVIDER_SOURCE_HASHES = {
    "embedding-cache-provider/index.mjs": "c692c352828b05c43991f7c96a95119f6e83244e46839d5207431885cbe7701e",
    "embedding-cache-provider/openclaw.plugin.json": "66ea471ac56d24949725e50fe60c53395bd6b478d1f65b9e6d725544e32b2873",
}


def case_bindings():
    actual = {case["id"]: hashlib.sha256(case_wire(case)).hexdigest() for case in build_cases()}
    if actual != CASE_HASHES:
        raise ValueError("The complete frozen embedding-cache lifecycle family changed")
    return actual


def validate_embedding_cache_lifecycle_profile(value):
    if (not isinstance(value, dict) or set(value) != {
        "kind", "operation", "inputKind", "nodeRuntime", "caseId", "caseBindings"}
            or value["kind"] != "approved-embedding-cache-lifecycle-profile"
            or value["operation"] != OPERATION or value["inputKind"] != "embedding-cache-lifecycle"
            or canonical(value["caseBindings"]) != canonical(case_bindings())
            or value["caseId"] not in CASE_HASHES):
        raise ValueError("Embedding cache requires its independent complete frozen manager capability")
    validate_model_node_authority(value["nodeRuntime"])
    return deepcopy(value)


def prepare_embedding_cache_lifecycle_profile(case, node: Path):
    validate_case(case)
    return validate_embedding_cache_lifecycle_profile({
        "kind": "approved-embedding-cache-lifecycle-profile", "operation": OPERATION,
        "inputKind": "embedding-cache-lifecycle", "nodeRuntime": prepare_model_node_authority(node),
        "caseId": case["id"], "caseBindings": case_bindings()})
