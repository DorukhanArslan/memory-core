"""Closed, independent replay-admission authority; no memory owner executes here."""
from copy import deepcopy

import pytest

from equivalence.forget_boundaries import build_cases, family_complete, validate_case, validate_registration
from equivalence.forget_boundaries_profile import case_bindings, validate_forget_boundaries_profile
from equivalence.forget_lineage_profile import FAMILY_SHA256, case_bindings as diagnostic_bindings
from equivalence.forget_lineage_sdk import run_forget_lineage
from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME
from equivalence.runtime_oracle import ReleaseOracleExecution, RuntimeOracleError


def profile():
    case = build_cases()[0]
    return {"kind": "approved-forget-boundaries-profile", "operation": case["operation"],
            "inputKind": case["input"]["kind"], "caseId": case["id"], "caseBindings": case_bindings(),
            "nodeRuntime": {"execPath": "/approved/node", **APPROVED_NODE_RUNTIME}}


def test_frozen_boundary_uses_real_admission_without_supplying_tombstones_or_backfill():
    case = build_cases()[0]
    validate_case(case)
    validate_registration([case])
    assert validate_forget_boundaries_profile(profile()) == profile()
    assert "tombstones" not in case["input"]
    assert [op["op"] for op in case["input"]["operations"]] == [
        "admission", "forget", "admission", "forget", "reopen", "admission", "forget", "reopen", "admission"]
    assert not any("backfill" in op or "forgottenSessionIds" in op for op in case["input"]["operations"])
    assert len(diagnostic_bindings()) == 6
    assert FAMILY_SHA256 == "f969f52453664edcc52c4a8f4ac25f47817cc5b02f786e602348c66939c8209d"


@pytest.mark.parametrize("mutation", ["selector", "number-type", "operation", "policy", "coverage", "duplicate"])
def test_changed_or_partial_definition_cannot_gain_boundary_credit(mutation):
    case = deepcopy(build_cases()[0])
    if mutation == "selector":
        case["input"]["operations"][3]["sessionIds"] = ["B"]
    elif mutation == "number-type":
        case["input"]["nowMs"] = float(case["input"]["nowMs"])
    elif mutation == "operation":
        case["operation"] = "forget-lineage-runtime"
    elif mutation == "policy":
        case["normalizationPolicy"] = "discard differences"
    elif mutation == "coverage":
        case["covers"].append("forget.lineage-tombstones.outcomes")
    if mutation == "duplicate":
        with pytest.raises(ValueError):
            validate_registration([case, deepcopy(case)])
    else:
        with pytest.raises(ValueError):
            validate_case(case)


@pytest.mark.parametrize("mutation", ["caseId", "caseBindings", "operation", "kind", "nodeRuntime"])
def test_boundary_capability_rejects_changed_identity_or_binary(mutation):
    value = profile()
    value[mutation] = {} if mutation in {"caseBindings", "nodeRuntime"} else "unapproved"
    with pytest.raises(ValueError):
        validate_forget_boundaries_profile(value)


def test_capability_cannot_borrow_existing_lineage_or_entry_profile():
    for extra in ({"forget_lineage_profile": {}}, {"entry_profile": {}}):
        with pytest.raises(RuntimeOracleError, match="cannot borrow"):
            with ReleaseOracleExecution({}, {}, forget_boundaries_profile=profile(), **extra):
                raise AssertionError("Mixed authority reached original execution")


def test_original_sdk_entry_rejects_new_input_before_running_owners(tmp_path):
    with pytest.raises(ValueError, match="exact common six-case"):
        run_forget_lineage(build_cases()[0]["input"], tmp_path / "must-not-exist")
    assert not (tmp_path / "must-not-exist").exists()


def test_complete_point_needs_the_whole_frozen_case_and_affirmative_evidence():
    case = dict(build_cases()[0], status="matched", runtimeEvidenceValidated=True)
    assert family_complete([case])
    assert not family_complete([])
    assert not family_complete([case, deepcopy(case)])
    for key, value in (("status", "blocked"), ("status", "mismatched"), ("runtimeEvidenceValidated", False)):
        assert not family_complete([{**case, key: value}])
    changed = deepcopy(case)
    changed["input"]["origins"].pop()
    assert not family_complete([changed])
