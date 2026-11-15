"""Real harness/driver mode integration; labelled infrastructure, no original execution."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from equivalence import harness
from equivalence import host_turn_barrier_v4 as frozen
from equivalence import host_turn_barrier_v4_evidence as evidence
from equivalence import host_turn_barrier_v4_native as native

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def labelled_native_transport(tmp_path, monkeypatch):
    """Keep real input, driver, context, binary wire and admission code.

    Only external Node/source qualification, physical execution allocation,
    Popen/original business output and original trace qualification are doubled.
    These labelled bytes are never genuine engine or acceptance evidence.
    """
    node = tmp_path / "labelled-node-never-executed"
    node.write_bytes(b"UNIT_NONEXECUTABLE_NODE_QUALIFICATION_DOUBLE")
    reference = tmp_path / "labelled-reference"
    reference.mkdir()
    authority = {"execPath": str(node), "label": "UNIT_NODE_AUTHORITY_NO_ORIGINAL_EXECUTION"}
    runtime = {"packages": [], "label": "UNIT_RUNTIME_NO_ORIGINAL_EXECUTION"}
    state = {"launches": [], "allocations": [], "communications": [], "raw": [], "next": 0}
    public = {"warning": "UNIT_WHOLE_WARNING", "corpora": [],
              "whole": {"false": False, "zero": 0, "null": None, "unicode": "雪"}}

    def allocate(capture, engine):
        assert engine == "native"
        root = tmp_path / ("labelled-execution-" + str(state["next"]))
        state["next"] += 1
        root.mkdir()
        for role in ("cwd", "state"):
            (root / role).mkdir()
        mapping = {"version": 4, "engine": engine, "executionRoot": str(root), "captureRoot": str(capture),
                   **{role: str(root / role) for role in ("cwd", "state", "workspace")}}
        state["allocations"].append(deepcopy(mapping))
        return mapping

    def environment(mapping, *, source_root, executable, context_path):
        assert source_root == native.ROOT and Path(executable) == node
        return {"UNIT_NO_ORIGINAL_EXECUTION": "true", "MEMORY_EQ_RELEASE_CONTEXT": str(context_path)}

    def git_context(mapping, *, path, **kwargs):
        native.write_exclusive(path, {"label": "UNIT_GIT_QUALIFICATION_NO_ORIGINAL_EXECUTION"})

    class LabelledProcess:
        pid = 424242
        returncode = 0

        def __init__(self, argv, **kwargs):
            assert argv == [str(node), str(native.ROOT / "equivalence" / native.ENTRY)]
            assert kwargs["stdin"] == native.subprocess.PIPE
            assert kwargs["env"]["UNIT_NO_ORIGINAL_EXECUTION"] == "true"
            self.context = json.loads(Path(kwargs["env"]["MEMORY_EQ_RELEASE_CONTEXT"]).read_text())
            self.stdout = kwargs["stdout"]
            state["launches"].append({"argv": argv, "cwd": kwargs["cwd"], "context": self.context})

        def communicate(self, wire, *, timeout):
            case = json.loads(wire)
            assert wire == frozen.case_wire(case)
            state["communications"].append({"wire": wire, "timeout": timeout, "case": case})
            mapping = state["allocations"][-1]
            raw = {"label": "UNIT_BUSINESS_NO_ORIGINAL_EXECUTION", "pid": self.pid, "ppid": os.getpid(),
                   "fixtureBase": mapping["state"], "input": frozen.business_case(case)["input"],
                   "result": deepcopy(public), "config": {"agents": {"defaults": {}}}}
            destination = Path(self.context["evidenceDirectory"]) / "native-raw.json"
            native.write_json(destination, [raw])
            self.stdout.write(json.dumps({"id": case["id"], "ok": True, "result": public}).encode() + b"\n")
            state["raw"].append(raw)

    monkeypatch.setattr(native, "prepare_model_node_authority", lambda selected: deepcopy(authority))
    monkeypatch.setattr(native, "allocate_execution", allocate)
    monkeypatch.setattr(native, "expected_environment", environment)
    monkeypatch.setattr(native, "prepare_git_probe", git_context)
    monkeypatch.setattr(native, "path_observation", lambda mapping: {"UNIT_PATH_QUALIFICATION": dict(mapping)})
    monkeypatch.setattr(native.subprocess, "Popen", LabelledProcess)
    monkeypatch.setattr(native, "validate_traces", lambda *args, **kwargs: {
        "loaded": [], "fixtureCaptures": [], "traces": [], "label": "UNIT_TRACE_QUALIFICATION_NO_ORIGINAL_EXECUTION"})
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    return {"node": node, "reference": reference, "authority": authority, "runtime": runtime,
            "state": state, "public": public, "tmp": tmp_path, "environment": environment}


def test_real_registered_harness_dispatch_uses_real_driver_120_bound_and_v4_kind(labelled_native_transport):
    packet = labelled_native_transport
    case = frozen.registered_case(frozen.build_cases()[0])
    returned = harness._oracle(packet["node"], ROOT / "equivalence/release-oracle.mjs", packet["reference"],
        [case], 120, release_runtime=packet["runtime"])
    assert returned["kind"] == "official-release-runtime-comparison"
    assert returned["results"] == [{"id": case["id"], "ok": True, "result": packet["public"]}]
    assert packet["state"]["communications"] == [{"wire": frozen.case_wire(case), "timeout": 120, "case": {key: case[key] for key in ("id", "operation", "input")}}]
    capture = Path(returned["evidenceDirectory"])
    process = json.loads((capture / "process.json").read_text())
    context = json.loads((capture / "host-v4-environment-context.json").read_text())
    assert process["timeoutSeconds"] == 120 and context["registered"] is True
    assert context["case"] == case and context["caseWireSha256"] == frozen.CASE_HASHES[case["id"]]
    assert len(packet["state"]["launches"]) == 1
    assert returned["runtimeDiagnostics"][0]["validationStatus"] == "verified"  # Labelled admission only.


@pytest.mark.parametrize("registered,timeout", [(True, 120), (False, 180), (True, None), (False, None)])
def test_real_native_driver_preserves_each_explicit_mode_and_default(labelled_native_transport, registered, timeout):
    packet = labelled_native_transport
    case = frozen.build_cases()[0]
    if registered:
        case = frozen.registered_case(case)
    capture = packet["tmp"] / "real-driver-capture"
    returned = native.run_native_case(case, packet["node"], packet["runtime"], capture,
        reference_root=packet["reference"], timeout=timeout, registered=registered)
    expected = 120 if registered else 180
    assert returned["kind"] == "official-release-host-turn-barrier-v4-outcomes"
    assert packet["state"]["communications"] == [{"wire": frozen.case_wire(case), "timeout": expected, "case": {key: case[key] for key in ("id", "operation", "input")}}]
    assert json.loads((capture / "process.json").read_text())["timeoutSeconds"] == expected
    assert json.loads((capture / "host-v4-environment-context.json").read_text())["registered"] is registered


@pytest.mark.parametrize("registered,timeout", [(True, 180), (False, 120), (True, 121), (False, 181),
                                              (True, 120.0), (False, 180.0), (True, True), (False, "180")])
def test_real_driver_rejects_swapped_or_untyped_bounds_before_allocation_or_popen(labelled_native_transport, registered, timeout):
    packet = labelled_native_transport
    case = frozen.build_cases()[0]
    if registered:
        case = frozen.registered_case(case)
    capture = packet["tmp"] / "must-not-exist"
    with pytest.raises(ValueError):
        native.run_native_case(case, packet["node"], packet["runtime"], capture,
            reference_root=packet["reference"], timeout=timeout, registered=registered)
    assert not capture.exists()
    assert packet["state"]["allocations"] == packet["state"]["launches"] == []


@pytest.mark.parametrize("registered", [None, 0, 1, "true", "probe"])
def test_real_driver_rejects_unknown_registration_mode_before_allocation_or_popen(labelled_native_transport, registered):
    packet = labelled_native_transport
    capture = packet["tmp"] / "must-not-exist"
    with pytest.raises(ValueError):
        native.run_native_case(frozen.build_cases()[0], packet["node"], packet["runtime"], capture,
            reference_root=packet["reference"], registered=registered)
    assert not capture.exists()
    assert packet["state"]["allocations"] == packet["state"]["launches"] == []


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("tamper", [None, "swapped-bound", "float-bound"])
def test_real_consumer_checks_actual_driver_mode_before_later_environment_qualification(
        labelled_native_transport, monkeypatch, registered, tamper):
    packet = labelled_native_transport
    case = frozen.build_cases()[0]
    if registered:
        case = frozen.registered_case(case)
    capture = packet["tmp"] / "consumer-capture"
    native.run_native_case(case, packet["node"], packet["runtime"], capture,
        reference_root=packet["reference"], registered=registered)
    process_path = capture / "process.json"
    process = json.loads(process_path.read_text())
    if tamper == "swapped-bound":
        process["timeoutSeconds"] = 180 if registered else 120
    elif tamper == "float-bound":
        process["timeoutSeconds"] = float(process["timeoutSeconds"])
    native.write_json(process_path, process)
    monkeypatch.setattr(evidence, "validate_mapping", lambda mapping: dict(mapping))
    monkeypatch.setattr(evidence, "expected_environment", packet["environment"])

    class LabelledConsumerModeBoundary(Exception):
        """Stop after the real context/process/deadline checks, before original qualification."""

    def stop_after_mode(*args, **kwargs):
        raise LabelledConsumerModeBoundary("UNIT_MODE_CHECK_PASSED_NO_ORIGINAL_ENVIRONMENT_CREDIT")
    monkeypatch.setattr(evidence, "validate_path_observation", stop_after_mode)
    expected = ValueError if tamper else LabelledConsumerModeBoundary
    with pytest.raises(expected):
        evidence._native_environment(case, packet["state"]["raw"][0], packet["public"], capture,
            node=packet["authority"], runtime=packet["runtime"], reference=packet["reference"], registered=registered)


def test_real_coordinator_dispatches_all_four_frozen_registered_cases_through_real_native_driver(
        labelled_native_transport, monkeypatch):
    from equivalence import host_turn_barrier_bindings, model_runtime_authority, release_runtime

    packet = labelled_native_transport
    reference = {"tag": "UNIT_REFERENCE_ONLY", "commit": "a" * 40}
    packet["runtime"].update(runtimeRoot=str(packet["tmp"] / "unit-runtime"), reference=reference)
    (packet["tmp"] / "equivalence").mkdir()
    (packet["tmp"] / "equivalence/release-oracle.mjs").write_text("// UNIT_SCRIPT_NEVER_EXECUTED\n")
    monkeypatch.setattr(harness, "_validate_reference", lambda *args: deepcopy(reference))
    monkeypatch.setattr(harness, "_implementation_identity", lambda: {"sourceSha256": "a" * 64})
    monkeypatch.setattr(harness, "_adapter_identity", lambda: {"UNIT_ADAPTER_ONLY": "b" * 64})
    monkeypatch.setattr(model_runtime_authority, "prepare_model_node_authority", lambda *args: deepcopy(packet["authority"]))
    monkeypatch.setattr(release_runtime, "prepare_release_runtime", lambda *args: deepcopy(packet["runtime"]))
    monkeypatch.setattr(host_turn_barrier_bindings, "prepare_host_turn_barrier_bindings",
                        lambda *args: {"label": "UNIT_BINDINGS_NO_ORIGINAL_EXECUTION"})
    monkeypatch.setattr(evidence, "validate_pair", lambda *args, **kwargs: True)
    cases = [frozen.registered_case(case) for case in frozen.build_cases()]
    def labelled_sdk(case):
        directory = case["_diagnosticDirectory"]
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "python-raw.json").write_text('[{"label":"UNIT_SDK_NO_ORIGINAL_EXECUTION"}]\n')
        return deepcopy(packet["public"])
    report, code = harness.run_suite(checkout=packet["reference"], node=packet["node"], cases=cases,
        python_runner=labelled_sdk, smoke=True, reference_path=ROOT / "equivalence/reference.json",
        scope_path=ROOT / "equivalence/scope.json")
    assert code == 0 and report["errors"] == [], report["errors"]
    actual = packet["state"]["communications"]
    assert [item["case"] for item in actual] == [{key: case[key] for key in ("id", "operation", "input")} for case in cases]
    assert [item["timeout"] for item in actual] == [120] * 4
    assert [item["wire"] for item in actual] == [frozen.case_wire(case) for case in cases]
    assert all(row["status"] == "matched" and row["runtimeEvidenceValidated"] is True for row in report["cases"])
    assert report["fullScopePassed"] is False  # Labelled smoke never establishes acceptance.
