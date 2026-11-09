"""Pending budget routes exercise real SDK persistence without granting credit."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

import pytest

from equivalence.cases import build_cases, run_python
from equivalence.get_contract import map_get_fixture_paths
from equivalence.memory_budget_fixtures import build_memory_budget_cases
from equivalence.memory_budget_profile import prepare_memory_budget_profile, validate_memory_budget_input, validate_memory_budget_profile
from equivalence.runtime_oracle import ReleaseOracleExecution, RuntimeOracleError


NODE = Path("/workspace/openclaw-memory-bridge/node_modules/node/bin/node")


def _profile(operation):
    if not NODE.is_file():
        pytest.skip("The exact approved Node binary is unavailable; no runtime authority is substituted")
    return prepare_memory_budget_profile(operation, NODE)


def test_default_catalog_and_sdk_dispatch_retain_all_complete_pending_boundaries():
    cases = build_memory_budget_cases()
    default = {case["id"]: case for case in build_cases()}
    assert len(cases) == 13 and all(case["covers"] == [] for case in cases)
    assert all(default[case["id"]] == case for case in cases)
    mutated = deepcopy(cases)
    mutated[0]["input"]["cases"][0]["params"]["newSection"] = "different literal"
    assert build_memory_budget_cases() == cases


@pytest.mark.parametrize("case", build_memory_budget_cases(), ids=lambda case: case["id"])
def test_real_sdk_route_preserves_complete_raw_returns_and_persisted_results(case, tmp_path):
    case = {**case, "_diagnosticDirectory": str(tmp_path)}
    result = run_python(case)
    raw, = json.loads((tmp_path / "python-raw.json").read_text())
    assert raw["input"] == case["input"]
    assert raw["calls"] and result["provider"] == "none"
    if case["input"]["kind"] == "memory-budget":
        assert len(result["cases"]) == len(case["input"]["cases"])
        assert len(raw["calls"]) == len(result["cases"])
        return
    call = next(call for call in raw["calls"] if call["operation"] == "run_short_term_promotion")
    assert {"evaluated_candidates", "outcome", "diff", "indexed_files", "chunks", "rejected_candidates"} <= set(call["ownReturn"])
    assert raw["physical"] and raw["files"]
    assert map_get_fixture_paths(raw["eventRecords"], raw["fixtureBase"]) == result["eventRecords"]
    applied = result["result"]
    if case["id"].endswith("compact"):
        assert applied["compactedSections"] > 0 and applied["appended"] == 1
    elif case["id"].endswith("defer"):
        assert applied["appended"] == 0 and applied["rejectedCandidates"][0]["category"] == "memory budget"
        assert result["documents"][0]["text"] == case["input"]["files"]["MEMORY.md"]
    elif case["id"] == "memory-budget-reconcile" or "js-bom-space" in case["id"]:
        assert applied["applied"] == applied["reconciledExisting"] == 1 and applied["appended"] == 0
        assert result["documents"][0]["text"] == case["input"]["files"]["MEMORY.md"]
    else:
        assert applied["appended"] == 1


@pytest.mark.parametrize("operation", ["memory-budget-runtime", "memory-budget-apply-runtime"])
def test_exact_node_profile_rejects_operation_kind_binary_and_undeclared_capability_changes(operation):
    profile = _profile(operation)
    assert validate_memory_budget_profile(profile) == profile
    for name, value in (("operation", "entry-memory-publication-runtime"), ("inputKind", "other"), ("kind", "model-profile")):
        changed = {**profile, name: value}
        with pytest.raises(ValueError):
            validate_memory_budget_profile(changed)
    with pytest.raises(ValueError):
        validate_memory_budget_profile({**profile, "sourceFallbackAllowed": True})
    changed = deepcopy(profile)
    changed["nodeRuntime"]["icuVersion"] = "other"
    with pytest.raises(ValueError):
        validate_memory_budget_profile(changed)


@pytest.mark.parametrize("capability", ["entry_profile", "model_node_runtime", "turn_taint_source", "fixture_captures"])
def test_independent_budget_capability_cannot_borrow_another_execution_lane(capability):
    profile = _profile("memory-budget-runtime")
    with pytest.raises(RuntimeOracleError, match="cannot borrow"):
        with ReleaseOracleExecution({}, {}, memory_budget_profile=profile, **{capability: True}):
            raise AssertionError("No execution context may be created")


@pytest.mark.parametrize("option", ["consolidation", "agentId", "subagent", "workspaceDir", "providers"])
def test_the_declared_apply_boundary_cannot_add_an_unreviewed_execution_surface(option):
    case = next(case for case in build_memory_budget_cases() if case["operation"] == "memory-budget-apply-runtime")
    case["input"]["options"][option] = {}
    with pytest.raises(ValueError, match="cannot add"):
        validate_memory_budget_input(case["input"])


def test_actual_budget_cli_flushes_a_large_unicode_envelope_before_exit(tmp_path):
    runtime = Path("/workspace/openclaw-memory-bridge/node_modules/openclaw")
    if not NODE.is_file() or not (runtime / "dist/memory-budget-BodJnew-.mjs").is_file():
        pytest.skip("The exact original optional runtime is unavailable")
    content = "\u6f22\U0001f600" * 131_072 + "end"
    value = {"kind": "memory-budget", "nowMs": 1779811200000, "cases": [{"id": "large-real-envelope", "params": {
        "existingMemory": content, "newSection": "", "budgetChars": 0}}]}
    request = {"input": value, "runtimeConfig": {"runtimeRoot": str(runtime), "evidenceDirectory": str(tmp_path)}}
    result = subprocess.run([str(NODE), "--no-warnings", "equivalence/memory-budget-runtime.mjs"],
        input=json.dumps(request, ensure_ascii=True), text=True, capture_output=True, timeout=60,
        cwd=Path(__file__).parents[2], env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"})
    assert result.returncode == 0
    native = json.loads(result.stdout)
    assert native["ok"] is True
    assert native["result"]["cases"] == [{"id": "large-real-envelope", "result": {"compacted": content, "droppedDates": []}}]
