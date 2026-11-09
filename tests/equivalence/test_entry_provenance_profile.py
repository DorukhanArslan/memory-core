"""Capability protocol checks; labelled files are not a native behavior oracle."""
from copy import deepcopy
import hashlib

import pytest

from equivalence.entry_provenance_profile import ENTRY_PROVENANCE_PROFILES, validate_entry_provenance_profile
from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME
from equivalence.runtime_oracle import ROOT, ReleaseOracleExecution, RuntimeOracleError, MODEL_RUNTIME_OPERATIONS


def _profile(operation="entry-memory-publication-runtime"):
    return {"kind": "approved-entry-provenance-profile", "operation": operation,
            "inputKind": ENTRY_PROVENANCE_PROFILES[operation], "nodeRuntime": {"execPath": "/reviewed/node", **APPROVED_NODE_RUNTIME}}


def _transport(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    raw = b"// Labelled transport fixture, never native execution evidence.\n"
    path = root / "manager.mjs"
    path.write_bytes(raw)
    config = {"runtimeRoot": str(root), "packages": [{"location": "node_modules/openclaw", "directory": str(root),
                "files": [{"path": "manager.mjs", "sha256": hashlib.sha256(raw).hexdigest()}]}]}
    adapters = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "equivalence").glob("*.mjs")}
    return config, adapters


@pytest.mark.parametrize("operation", ENTRY_PROVENANCE_PROFILES)
def test_each_entry_profile_keeps_its_original_kind_and_binary_authority(operation):
    value = _profile(operation)
    assert validate_entry_provenance_profile(value) == value
    assert operation not in MODEL_RUNTIME_OPERATIONS


@pytest.mark.parametrize("field", ("sha256", "nodeVersion", "icuVersion", "unicodeVersion", "execPath"))
def test_entry_binary_authority_cannot_be_forged(field):
    profile = _profile()
    profile["nodeRuntime"][field] = "unreviewed"
    with pytest.raises(ValueError):
        validate_entry_provenance_profile(profile)


@pytest.mark.parametrize("mutation", ("operation", "inputKind", "kind", "extra"))
def test_unrelated_operations_and_input_kinds_cannot_borrow_entry_scope(mutation):
    profile = _profile()
    if mutation == "extra":
        profile["sourceCapability"] = True
    else:
        profile[mutation] = "unreviewed"
    with pytest.raises(ValueError):
        validate_entry_provenance_profile(profile)


@pytest.mark.parametrize("capability", ("model", "source", "capture"))
def test_entry_profile_cannot_combine_model_or_source_execution_capabilities(tmp_path, capability):
    config, adapters = _transport(tmp_path)
    options = {"entry_profile": _profile()}
    if capability == "model":
        options["model_node_runtime"] = _profile()["nodeRuntime"]
    elif capability == "source":
        options["turn_taint_source"] = {"unreviewed": True}
    else:
        options["fixture_captures"] = True
    with pytest.raises(RuntimeOracleError, match="cannot borrow"):
        with ReleaseOracleExecution(config, adapters, **options):
            pass


def test_entry_context_retains_complete_explicit_scope_without_source_permission(tmp_path):
    config, adapters = _transport(tmp_path)
    profile = _profile()
    with ReleaseOracleExecution(config, adapters, entry_profile=profile) as execution:
        assert execution._context["entryProvenanceProfile"] == profile
        assert execution._context["approvedNodeRuntime"] == profile["nodeRuntime"]
        assert execution._context["approvedReferenceSources"] == []
        assert execution._context["fixtureSourceCaptures"] == []


@pytest.mark.parametrize("operation", ENTRY_PROVENANCE_PROFILES)
def test_profile_drift_is_rejected_before_any_native_success_claim(tmp_path, operation):
    config, adapters = _transport(tmp_path)
    profile = _profile(operation)
    case = {"id": "labelled-entry", "operation": operation, "input": {"kind": "wrong-profile"}}
    result = {"kind": "official-release-runtime-comparison", "sources": [], "results": [
        {"id": case["id"], "ok": True, "result": {"provider": "none"}}]}
    with ReleaseOracleExecution(config, adapters, entry_profile=profile) as execution:
        with pytest.raises(RuntimeOracleError, match="cannot impersonate"):
            execution.collect(deepcopy(result), [case])
