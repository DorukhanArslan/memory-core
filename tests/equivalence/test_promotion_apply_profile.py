"""Capability tests use labelled transport, never actual native execution evidence."""
from copy import deepcopy
import hashlib

import pytest

from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME
from equivalence.promotion_apply_profile import (
    PROMOTION_APPLY_CASE_ID,
    PROMOTION_APPLY_CASE_WIRE_SHA256,
    PROMOTION_APPLY_OPERATION,
    promotion_apply_case_wire,
    validate_promotion_apply_input,
    validate_promotion_apply_profile,
)
from equivalence.promotion_apply_reconcile_fixtures import build_promotion_apply_reconcile_cases
from equivalence.runtime_oracle import ROOT, ReleaseOracleExecution, RuntimeOracleError


def _profile():
    return {"kind": "approved-promotion-apply-profile", "operation": PROMOTION_APPLY_OPERATION,
        "inputKind": "promotion-apply-reconcile", "caseWireSha256": PROMOTION_APPLY_CASE_WIRE_SHA256,
        "nodeRuntime": {"execPath": "/reviewed/node", **APPROVED_NODE_RUNTIME}}


def _transport(tmp_path):
    root = tmp_path / "runtime"
    root.mkdir()
    raw = b"// Labelled transport fixture, never actual native execution evidence.\n"
    (root / "manager.mjs").write_bytes(raw)
    config = {"runtimeRoot": str(root), "packages": [{"location": "node_modules/openclaw", "directory": str(root),
        "files": [{"path": "manager.mjs", "sha256": hashlib.sha256(raw).hexdigest()}]}]}
    adapters = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (ROOT / "equivalence").glob("*.mjs")}
    return config, adapters


def _failed_transport(case):
    return {"kind": "official-release-runtime-comparison", "sources": [], "results": [
        {"id": case["id"], "ok": False, "error": "Labelled transport only; actual owner was not invoked."}]}


def test_reviewed_literal_is_exact_and_contains_no_expected_result():
    case, = build_promotion_apply_reconcile_cases()
    assert case["id"] == PROMOTION_APPLY_CASE_ID and case["covers"] == []
    wire = promotion_apply_case_wire(case["input"])
    assert len(wire) == 1694 and hashlib.sha256(wire).hexdigest() == PROMOTION_APPLY_CASE_WIRE_SHA256
    assert validate_promotion_apply_input(case["input"]) == case["input"]
    assert case["input"]["directories"] == ["MEMORY.md"] and case["input"]["files"] == {}
    assert len(case["input"]["candidates"]) == 1
    assert "result" not in case["input"] and "error" not in case["input"]


@pytest.mark.parametrize("field", ("directories", "files", "recall", "candidates", "options", "nowMs", "kind"))
def test_changed_literal_needs_a_new_reviewed_wire(field):
    case, = build_promotion_apply_reconcile_cases()
    case["input"][field] = "unreviewed"
    with pytest.raises(ValueError, match="reviewed literal"):
        validate_promotion_apply_input(case["input"])


@pytest.mark.parametrize("field", ("kind", "operation", "inputKind", "caseWireSha256"))
def test_capability_cannot_borrow_another_profile_or_literal(field):
    profile = _profile()
    profile[field] = "unreviewed"
    with pytest.raises(ValueError, match="separate exact"):
        validate_promotion_apply_profile(profile)


@pytest.mark.parametrize("field", ("execPath", "sha256", "nodeVersion", "icuVersion", "unicodeVersion"))
def test_binary_authority_is_not_version_text_only(field):
    profile = _profile()
    profile["nodeRuntime"][field] = "unreviewed"
    with pytest.raises(ValueError, match="exact approved"):
        validate_promotion_apply_profile(profile)


@pytest.mark.parametrize("capability", (
    "entry_profile", "model_node_runtime", "turn_taint_source", "fixture_captures", "atomic_profile",
    "bootstrap_profile", "memory_budget_profile", "get_read_race_profile", "promotion_profile",
))
def test_apply_cannot_compose_independent_capabilities(capability):
    with pytest.raises(RuntimeOracleError, match="cannot borrow"):
        with ReleaseOracleExecution({}, {}, promotion_apply_profile=_profile(), **{capability: True}):
            raise AssertionError("No context may be established")


def test_apply_cannot_borrow_an_unpaired_atomic_checkpoint():
    with pytest.raises(RuntimeOracleError, match="atomic case binding cannot escape"):
        with ReleaseOracleExecution({}, {}, promotion_apply_profile=_profile(), atomic_case={"unreviewed": True}):
            raise AssertionError("No context may be established")


def test_context_retains_only_distinct_apply_authority(tmp_path):
    config, adapters = _transport(tmp_path)
    profile = _profile()
    expected = deepcopy(profile)
    with ReleaseOracleExecution(config, adapters, promotion_apply_profile=profile) as execution:
        profile["operation"] = "caller-mutated"
        assert execution._context["promotionApplyProfile"] == expected
        assert execution._context["approvedNodeRuntime"] == expected["nodeRuntime"]
        assert execution._context["approvedReferenceSources"] == execution._context["fixtureSourceCaptures"] == []
        assert "promotionRankingProfile" not in execution._context
        assert "memoryBudgetProfile" not in execution._context


def test_apply_operation_cannot_run_without_its_capability(tmp_path):
    config, adapters = _transport(tmp_path)
    case, = build_promotion_apply_reconcile_cases()
    with ReleaseOracleExecution(config, adapters) as execution:
        with pytest.raises(RuntimeOracleError, match="restricted to its exact original caller"):
            execution.collect(_failed_transport(case), [case])


@pytest.mark.parametrize("mutation", ("operation", "input", "id"))
def test_apply_context_rejects_changed_case_before_transport_collection(tmp_path, mutation):
    config, adapters = _transport(tmp_path)
    case, = build_promotion_apply_reconcile_cases()
    if mutation == "operation":
        case["operation"] = "search-contract-runtime"
    elif mutation == "input":
        case["input"]["directories"] = []
    else:
        case["id"] = "another-case"
    with ReleaseOracleExecution(config, adapters, promotion_apply_profile=_profile()) as execution:
        with pytest.raises((RuntimeOracleError, ValueError)):
            execution.collect(_failed_transport(case), [case])


def test_valid_capability_does_not_accept_failed_observation_transport(tmp_path):
    config, adapters = _transport(tmp_path)
    case, = build_promotion_apply_reconcile_cases()
    with ReleaseOracleExecution(config, adapters, promotion_apply_profile=_profile()) as execution:
        with pytest.raises(RuntimeOracleError, match="did not complete"):
            execution.collect(_failed_transport(case), [case])
