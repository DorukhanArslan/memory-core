"""Real coordinator and explicit Host V4 adapters with labelled transport doubles."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from equivalence import harness, model_runtime_authority, release_runtime
from equivalence.cases import run_python
from equivalence.forget_index_fence_v6 import build_cases as fif_cases
from equivalence.host_turn_barrier_v4 import build_cases, registered_case

ROOT = Path(__file__).resolve().parents[2]


def _registered():
    return [registered_case(case) for case in build_cases()]


def test_host_v4_python_route_requires_explicit_authorities_and_preserves_whole_frozen_case(monkeypatch, tmp_path):
    module = ModuleType("equivalence.host_turn_barrier_v4_sdk")
    calls = []
    module.run_host_turn_barrier_v4_case = lambda *args, **kwargs: calls.append((args, kwargs)) or {"labelled": "whole result"}
    monkeypatch.setitem(sys.modules, module.__name__, module)
    case = _registered()[0]
    with pytest.raises(ValueError, match="explicit authenticated Native authorities"):
        run_python(case)
    assert calls == []
    authorities = {"node": tmp_path / "labelled-node", "runtime": {"labelled": "authenticated-runtime"},
                   "reference_root": tmp_path / "labelled-reference"}
    supplied = {**deepcopy(case), "_diagnosticDirectory": tmp_path / "actual-directory",
                "_hostTurnBarrierV4Authorities": authorities}
    assert run_python(supplied) == {"labelled": "whole result"}
    assert calls == [((case,), {**authorities, "evidence_directory": tmp_path / "actual-directory", "registered": True})]
    assert case == _registered()[0] and "_hostTurnBarrierV4Authorities" not in case


@pytest.mark.parametrize("change", [None, "host-public-mismatch", "unaffirmed-custody", "changed-retained-host-file"])
def test_actual_coordinator_retains_all_seventeen_whole_pairs_and_independent_atomic_gates(monkeypatch, tmp_path, change):
    """The doubles are labelled; this test produces no original acceptance evidence."""
    reference = {"tag": "UNIT_REFERENCE_ONLY", "commit": "1" * 40}
    runtime = {"runtimeRoot": str(tmp_path / "unit-runtime"), "packages": [], "reference": reference}
    node = tmp_path / "unit-node"
    checkout = tmp_path / "unit-reference"
    declarations = {"label": "UNIT_BINDINGS_ONLY", "sourceBuildReproduced": False}
    for name, function in (("equivalence.forget_index_fence_bindings", "prepare_forget_index_fence_bindings"),
                           ("equivalence.host_turn_barrier_bindings", "prepare_host_turn_barrier_bindings")):
        module = ModuleType(name)
        setattr(module, function, lambda *args: deepcopy(declarations))
        monkeypatch.setitem(sys.modules, name, module)
    native_fif = ModuleType("equivalence.forget_index_fence_native")
    native_fif.NATIVE_KIND = "UNIT_FIF_NATIVE_ONLY"
    native_host = ModuleType("equivalence.host_turn_barrier_v4_native")
    native_host.NATIVE_KIND = "UNIT_V4_NATIVE_ONLY"
    legacy_native = ModuleType("equivalence.host_turn_barrier_native")
    legacy_native.NATIVE_KIND = "UNIT_LEGACY_NATIVE_ONLY"
    checked = []
    guard_fif = ModuleType("equivalence.forget_index_fence_evidence")
    guard_fif.validate_pair = lambda *args, **kwargs: True
    guard_host = ModuleType("equivalence.host_turn_barrier_v4_evidence")
    def validate_host(case, *args, **kwargs):
        checked.append((case, kwargs))
        assert kwargs["approved_node"] == node and kwargs["approved_runtime"] == runtime
        assert kwargs["approved_reference"] == checkout and kwargs["approved_source_root"] == tmp_path
        assert kwargs["registered"] is True
        assert kwargs["native_directory"].is_relative_to(tmp_path / ".equivalence-results/host-turn-barrier-v4")
        assert kwargs["sdk_directory"].is_relative_to(tmp_path / ".equivalence-results/host-turn-barrier-v4")
        return 1 if change == "unaffirmed-custody" else True
    guard_host.validate_pair = validate_host
    for module in (native_fif, native_host, legacy_native, guard_fif, guard_host):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    (tmp_path / "equivalence").mkdir()
    (tmp_path / "equivalence/release-oracle.mjs").write_text("// UNIT_ONLY, never executed\n")
    monkeypatch.setattr(harness, "_validate_reference", lambda *args: deepcopy(reference))
    monkeypatch.setattr(harness, "_implementation_identity", lambda: {"sourceSha256": "2" * 64})
    monkeypatch.setattr(harness, "_adapter_identity", lambda: {"UNIT_ADAPTER_ONLY": "3" * 64})
    monkeypatch.setattr(model_runtime_authority, "prepare_model_node_authority", lambda *args: {"label": "UNIT_NODE_ONLY"})
    monkeypatch.setattr(release_runtime, "prepare_release_runtime", lambda *args: deepcopy(runtime))
    cases = _registered() + fif_cases()
    dispatched = []
    first_sdk_file = None
    def result(case):
        return {"provider": "none", "calls": {"UNIT_WHOLE": {"id": case["id"], "extra": [False, 0, None],
                    "warning": "full warning", "action": "whole action\nsecond line"}},
                "snapshots": {"UNIT_WHOLE": {"rows": [["all", "physical", "fields"]]}}}
    def native(case, selected_node, selected_runtime, directory, *, timeout, checkout=None, reference_root=None, registered=None):
        dispatched.append(case["id"])
        assert selected_node == node and selected_runtime == runtime
        is_host = case["operation"] == "host-turn-barrier-v4-runtime"
        if is_host:
            assert reference_root == globals_checkout and registered is True
        raw = [{"label": "UNIT_NATIVE_CAPTURE_ONLY", "caseId": case["id"]}]
        (directory / "evidence").mkdir(parents=True)
        (directory / "evidence/native-raw.json").write_text(json.dumps(raw) + "\n")
        return {"kind": native_host.NATIVE_KIND if is_host else native_fif.NATIVE_KIND,
                "results": [{"id": case["id"], "ok": True, "result": result(case)}], "releaseSources": [],
                "releaseTrace": {"label": "UNIT_TRACE_ONLY"}, "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}
    globals_checkout = checkout
    native_fif.run_native_case = native
    native_host.run_native_case = native
    def sdk(case):
        nonlocal first_sdk_file
        directory = case["_diagnosticDirectory"]
        assert directory.is_relative_to(tmp_path / ".equivalence-results")
        directory.mkdir(parents=True, exist_ok=True)
        if case["operation"] == "host-turn-barrier-v4-runtime":
            assert case["_hostTurnBarrierV4Authorities"] == {"node": node, "runtime": runtime, "reference_root": checkout}
        (directory / "python-raw.json").write_text('[{"label":"UNIT_SDK_CAPTURE_ONLY"}]\n')
        if case["id"] == cases[0]["id"]:
            first_sdk_file = directory / "python-raw.json"
        elif change == "changed-retained-host-file" and case["id"] == cases[1]["id"]:
            first_sdk_file.write_text('[ {"label":"ALTERED_AFTER_ACTUAL_GUARD"} ]\n')
        value = result(case)
        if change == "host-public-mismatch" and case["id"] == cases[0]["id"]:
            value["calls"]["UNIT_WHOLE"]["extra"].append("actual whole delta")
        return value
    report, code = harness.run_suite(checkout=checkout, node=node, smoke=True, cases=cases, python_runner=sdk,
        reference_path=ROOT / "equivalence/reference.json", scope_path=ROOT / "equivalence/scope.json")
    if change == "changed-retained-host-file":
        assert code == 2 and report["errors"][0]["code"] == "runtime-evidence-changed"
        assert report["cases"][0]["status"] == "blocked"
        assert report["cases"][0]["runtimeEvidenceValidated"] is False
        return
    assert not report["errors"], report["errors"]
    assert len(report["cases"]) == 17 and dispatched == [case["id"] for case in cases]
    assert len(checked) == 4
    assert code == (2 if change == "unaffirmed-custody" else 1 if change else 0)
    for case, row in zip(cases, report["cases"], strict=True):
        is_host = case["operation"] == "host-turn-barrier-v4-runtime"
        if is_host and change == "unaffirmed-custody":
            assert row["status"] == "blocked" and "runtimeEvidenceValidated" not in row
            continue
        assert row["openclaw"] == result(case)
        assert row["python"]["calls"]["UNIT_WHOLE"]["warning"] == "full warning"
        assert row["python"]["snapshots"] == result(case)["snapshots"]
        assert row["runtimeEvidenceValidated"] is True
    requirements = {row["id"]: row for row in report["requirements"]}
    host_point = next(point for point in requirements["host.turn-barrier"]["acceptance"] if point["id"].endswith(".outcomes"))
    assert host_point["matchedCaseIds"] == ([] if change else [case["id"] for case in cases[:4]])
    assert all(len(point["matchedCaseIds"]) == 13 for point in requirements["forget.index-fence"]["acceptance"])
    assert report["fullScopePassed"] is False


@pytest.mark.parametrize("outcome_version", ["legacy", "v4"])
def test_known_outcome_sibling_does_not_consume_the_six_boundary_members(outcome_version):
    from equivalence.host_turn_barrier import build_cases as legacy_cases
    from equivalence.host_turn_barrier_boundaries import build_cases as boundary_cases

    outcomes = legacy_cases() if outcome_version == "legacy" else _registered()
    definitions = outcomes + boundary_cases()
    rows = [dict(case, status="matched", runtimeEvidenceValidated=True) for case in definitions]
    assert len(rows) == 10
    assert harness._host_turn_barrier_family_complete(rows) is True
    assert harness._host_turn_barrier_boundaries_family_complete(rows) is True
    scope = json.loads((ROOT / "equivalence/scope.json").read_text())
    harness._validate_scope(scope, definitions)
    rows[0]["status"] = "mismatched"
    assert harness._host_turn_barrier_family_complete(rows) is False
    assert harness._host_turn_barrier_boundaries_family_complete(rows) is True
    rows[0]["status"] = "matched"
    rows[-1]["runtimeEvidenceValidated"] = False
    assert harness._host_turn_barrier_family_complete(rows) is True
    assert harness._host_turn_barrier_boundaries_family_complete(rows) is False


@pytest.mark.parametrize("unknown_operation", ["unknown-host-operation", "host-turn-barrier-v3-runtime", "host-turn-barrier-v5-runtime"])
def test_only_explicit_known_outcome_operations_are_excluded_from_boundary_selection(unknown_operation):
    from equivalence.host_turn_barrier_boundaries import build_cases as boundary_cases

    foreign = {"id": "unknown-host-sibling", "operation": unknown_operation,
               "requirement": "host.turn-barrier", "covers": [], "input": {}}
    definitions = _registered() + boundary_cases() + [foreign]
    rows = [dict(case, status="matched", runtimeEvidenceValidated=True) for case in definitions]
    assert harness._host_turn_barrier_boundaries_family_complete(rows) is False
    assert harness._host_turn_barrier_family_complete(rows) is False
    scope = json.loads((ROOT / "equivalence/scope.json").read_text())
    with pytest.raises(harness.HarnessError) as failure:
        harness._validate_scope(scope, definitions)
    assert failure.value.code == "cases-invalid"


def test_known_outcome_operation_cannot_hide_a_forged_boundary_claim():
    from equivalence.host_turn_barrier_boundaries import POINTS, build_cases as boundary_cases

    rows = [dict(case, status="matched", runtimeEvidenceValidated=True) for case in _registered() + boundary_cases()]
    rows[0]["covers"] = list(POINTS)
    assert harness._host_turn_barrier_boundaries_family_complete(rows) is False


def test_ci_retains_only_owned_host_v4_execution_roots_and_explains_artifact_layout():
    workflow = (ROOT / ".github/workflows/equivalence.yml").read_text()
    retention = next(step for step in workflow.split("      - name: ") if "Retain results, including failed acceptance runs" in step)
    assert ".equivalence-results/host-turn-barrier-v4/**" in retention
    assert retention.count("/var/tmp/memory-host-v4-*/**") == 1
    assert "/var/tmp/**" not in retention and "/var/tmp/*/**" not in retention
    assert "common\n          # filesystem ancestor" in retention
    assert "assuming the archive root is the repository root" in retention
    assert "include-hidden-files: true" in retention
