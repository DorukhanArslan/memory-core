"""Capability tests only; labelled files never stand in for native execution."""
from copy import deepcopy
import hashlib

import pytest

from equivalence.bootstrap_discovery_profile import (
    APPROVED_BOOTSTRAP_NODE, validate_bootstrap_discovery_profile,
)
from equivalence.runtime_oracle import ROOT, ReleaseOracleExecution, RuntimeOracleError


def _profile():
    return {"kind": "approved-bootstrap-discovery-profile", "operation": "bootstrap-discovery-runtime",
        "inputKind": "workspace-bootstrap", "nodeRuntime": {"execPath": "/reviewed/node", **APPROVED_BOOTSTRAP_NODE}}


@pytest.mark.parametrize("field", ("sha256", "nodeVersion", "icuVersion", "unicodeVersion", "execPath"))
def test_bootstrap_executable_authority_rejects_drift(field):
    profile = _profile()
    profile["nodeRuntime"][field] = "unreviewed"
    with pytest.raises(ValueError):
        validate_bootstrap_discovery_profile(profile)


@pytest.mark.parametrize("field", ("kind", "operation", "inputKind", "extra"))
def test_unrelated_scopes_cannot_borrow_bootstrap_capability(field):
    profile = _profile()
    profile[field] = "unreviewed"
    with pytest.raises(ValueError):
        validate_bootstrap_discovery_profile(profile)


def _context(tmp_path):
    directory = tmp_path / "runtime"
    directory.mkdir()
    config = {"runtimeRoot": str(directory), "packages": []}
    adapters = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "equivalence").glob("*.mjs")}
    return config, adapters


@pytest.mark.parametrize("option", ("fixture", "source"))
def test_bootstrap_cannot_borrow_dynamic_or_source_capabilities(tmp_path, option):
    config, adapters = _context(tmp_path)
    kwargs = {"fixture_captures": True} if option == "fixture" else {"turn_taint_source": {"unreviewed": True}}
    with pytest.raises(RuntimeOracleError, match="cannot borrow"):
        with ReleaseOracleExecution(config, adapters, bootstrap_profile=_profile(), **kwargs):
            pass


def test_bootstrap_context_retains_explicit_scope_without_source_authority(tmp_path):
    config, adapters = _context(tmp_path)
    profile = _profile()
    with ReleaseOracleExecution(config, adapters, bootstrap_profile=profile) as execution:
        assert execution._context["bootstrapDiscoveryProfile"] == profile
        assert execution._context["approvedReferenceSources"] == []
        assert execution._context["fixtureSourceCaptures"] == []
        result = {"kind": "official-release-runtime-comparison", "sources": [], "results": [
            {"id": "labelled", "ok": True, "result": {"provider": "none"}}]}
        case = {"id": "labelled", "operation": "bootstrap-discovery-runtime", "input": {"kind": "wrong-kind"}}
        with pytest.raises(RuntimeOracleError, match="different bootstrap input"):
            execution.collect(deepcopy(result), [case])
