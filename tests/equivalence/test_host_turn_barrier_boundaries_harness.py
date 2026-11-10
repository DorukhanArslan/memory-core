"""Labelled unit transport/gate doubles; these tests are not Native execution evidence."""
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import types

import pytest

from equivalence import harness, release_runtime
from equivalence.cases import build_cases as catalog, run_python
from equivalence.harness import HarnessError, _oracle
from equivalence.host_turn_barrier import POINTS as OUTCOME_POINTS, build_cases as outcome_cases
from equivalence.host_turn_barrier_boundaries import OPERATION, POINTS, build_cases
from equivalence.host_turn_barrier_boundaries_native import NATIVE_KIND
from equivalence.host_turn_barrier_native import NATIVE_KIND as OUTCOME_NATIVE_KIND


ROOT = Path(__file__).resolve().parents[2]
RUNNER = "equivalence.host_turn_barrier_boundaries_native.run_native_case"


def test_closed_six_cases_append_to_the_prior_catalog_and_keep_outcome_literals():
    cases = catalog()
    assert len(cases) == 1421 and cases[-6:] == build_cases()
    assert [case for case in cases if case["operation"] == "host-turn-barrier-runtime"] == outcome_cases()
    assert OUTCOME_POINTS == ("host.turn-barrier.outcomes",)
    assert POINTS == ("host.turn-barrier.boundaries",)


def test_native_authority_is_required_before_boundary_dispatch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(RUNNER, lambda *args, **kwargs: calls.append(args))
    with pytest.raises(HarnessError, match="authenticated release runtime"):
        _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path, [build_cases()[0]], 180)
    assert calls == []


@pytest.mark.parametrize("kind", [OUTCOME_NATIVE_KIND,
                                  "official-release-host-restart-acceptance",
                                  "official-release-host-update-isolation-acceptance",
                                  "official-release-runtime-comparison"])
def test_another_capability_cannot_supply_boundary_evidence(tmp_path, monkeypatch, kind):
    calls = []

    def fixture(*args, **kwargs):
        calls.append((args, kwargs))
        return {"kind": kind}

    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(RUNNER, fixture)
    with pytest.raises(HarnessError, match="no retry") as failure:
        _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
                [build_cases()[0]], 180, release_runtime={"label": "unit runtime fixture"})
    assert len(calls) == 1 and failure.value.code == "host-turn-barrier-boundaries-evidence-invalid"
    rejected = failure.value.rejected_evidence
    assert rejected["coverageCredit"] is False and rejected["caseIds"] == [build_cases()[0]["id"]]
    assert Path(rejected["retainedDirectory"]).is_relative_to(tmp_path / ".equivalence-results/host-turn-barrier-boundaries")


def test_transport_preserves_whole_public_result_trace_and_exact_raw_file_bytes(tmp_path, monkeypatch):
    case = build_cases()[0]
    raw = [{"label": "unit raw capture, not Native evidence", "values": [False, 0, None]}]
    wire = (json.dumps(raw, ensure_ascii=False, indent=2) + "\n").encode()
    result = {"warning": "kept", "debug": {"hits": 0}, "stale": False,
              "reply": {"text": "unchanged", "replyToId": "fixture-followup"},
              "dispatchResult": {"queuedFinal": True, "counts": {"tool": 0, "block": 0, "final": 1}}}
    trace = {"label": "unit trace fixture"}

    def fixture(selected, node, runtime, directory, *, timeout):
        assert selected == case and timeout == 180
        evidence = directory / "evidence"
        evidence.mkdir(parents=True)
        (evidence / "native-raw.json").write_bytes(wire)
        return {"kind": NATIVE_KIND, "results": [{"id": case["id"], "ok": True, "result": result}],
                "releaseSources": [], "releaseTrace": trace, "runtimeDiagnostics": raw,
                "evidenceDirectory": str(directory)}

    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(RUNNER, fixture)
    returned = _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
                       [case], 180, release_runtime={"label": "unit runtime fixture"})
    assert returned["results"] == [{"id": case["id"], "ok": True, "result": result}]
    assert returned["releaseTrace"] == trace
    assert returned["runtimeDiagnostics"] == [{"id": case["id"], "rawSnapshots": raw,
        "sha256": hashlib.sha256(wire).hexdigest(), "validationStatus": "verified"}]
    assert (Path(returned["evidenceDirectory"]) / "evidence/native-raw.json").read_bytes() == wire


@pytest.mark.parametrize("tamper", ["changed", "boolean-for-integer", "duplicate", "symlink", "hardlink",
                                    "malformed", "oversized"])
def test_changed_or_unowned_native_raw_file_is_retained_but_rejected(tmp_path, monkeypatch, tamper):
    case, calls = build_cases()[0], []

    def fixture(selected, node, runtime, directory, *, timeout):
        calls.append(directory)
        evidence = directory / "evidence"
        evidence.mkdir(parents=True)
        raw = [{"label": "unit raw fixture", "value": True}]
        target = evidence / "native-raw.json"
        shown = deepcopy(raw)
        if tamper == "changed":
            shown[0]["label"] = "other bytes"
        elif tamper == "boolean-for-integer":
            shown[0]["value"] = 1
        elif tamper == "duplicate":
            shown.append(deepcopy(shown[0]))
            raw = deepcopy(shown)
        target.write_text(json.dumps(shown))
        if tamper == "symlink":
            other = target.with_name("other.json")
            target.rename(other)
            target.symlink_to(other)
        elif tamper == "hardlink":
            os.link(target, target.with_name("other.json"))
        elif tamper == "malformed":
            target.write_bytes(b"{")
        elif tamper == "oversized":
            with target.open("wb") as stream:
                stream.truncate(32 * 1024 * 1024 + 1)
        return {"kind": NATIVE_KIND, "results": [], "releaseSources": [], "releaseTrace": {},
                "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}

    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(RUNNER, fixture)
    with pytest.raises(HarnessError, match="no retry") as failure:
        _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
                [case], 180, release_runtime={"label": "unit runtime fixture"})
    assert len(calls) == 1 and failure.value.rejected_evidence["coverageCredit"] is False
    assert (calls[0] / "evidence/native-raw.json").exists()


@pytest.mark.parametrize("case,timeout", [(outcome_cases()[0], 180), (build_cases()[0], 181),
                                         (build_cases()[0], True), (build_cases()[0], float("nan"))])
def test_boundary_timeout_does_not_expand_an_old_capability(case, timeout, tmp_path):
    with pytest.raises(HarnessError) as failure:
        _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
                [case], timeout, release_runtime={"label": "unit runtime fixture"})
    assert failure.value.code == "timeout-invalid"


def test_sdk_route_requires_the_exact_literal_and_owned_diagnostic_directory(tmp_path, monkeypatch):
    case, calls, result = build_cases()[0], [], {"label": "unit SDK route fixture"}

    def fixture(value, *, evidence_directory):
        calls.append((value, evidence_directory))
        return result

    monkeypatch.setattr("equivalence.host_turn_barrier_boundaries_sdk.run_host_turn_barrier_boundaries_case", fixture)
    assert run_python({**case, "_diagnosticDirectory": tmp_path}) is result
    assert calls == [(case["input"], tmp_path)]
    changed = deepcopy(case)
    changed["input"]["nowMs"] += 1
    with pytest.raises(ValueError):
        run_python({**changed, "_diagnosticDirectory": tmp_path})
    assert len(calls) == 1


def _git(directory, *args):
    return subprocess.run(["git", *args], cwd=directory, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture
def labelled_suite(tmp_path, monkeypatch):
    """Abstract doubles exercise the real harness, never claim original behavior."""
    from equivalence import flush_execution_bindings, flush_runtime_bindings
    from equivalence import host_turn_barrier_bindings, host_turn_barrier_boundaries_bindings
    from equivalence import host_turn_barrier_evidence, model_runtime_authority

    checkout = tmp_path / "reference"
    checkout.mkdir()
    _git(checkout, "init", "-q")
    (checkout / "package.json").write_text(json.dumps({"version": "2026.9.9",
        "engines": {"node": ">=24.16.0 <25 || >=26.1.0"}}))
    _git(checkout, "add", ".")
    _git(checkout, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "Labelled unit routing fixture")
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"tag": "v2026.9.9", "commit": _git(checkout, "rev-parse", "HEAD"),
        "nodeMin": "24.16.0", "nodeRanges": ">=24.16.0 <25 || >=26.1.0"}))
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"schemaVersion": 1, "requirements": [
        {"id": "host.turn-barrier", "required": True, "acceptance": [
            {"id": point, "description": "Labelled original point"} for point in (*OUTCOME_POINTS, *POINTS)]},
        {"id": "indexing", "required": True, "acceptance": [
            {"id": "indexing.lifecycle", "description": "Unrelated unit point"}]}]}))
    node = tmp_path / "node"
    node.write_text(f"#!{sys.executable}\nprint('v24.16.0')\n")
    node.chmod(0o700)
    unrelated = {"id": "labelled-unrelated", "requirement": "indexing", "operation": "index-lifecycle-runtime",
                 "input": {"provider": "none"}, "covers": ["indexing.lifecycle"]}
    cases = [unrelated, *outcome_cases(), *build_cases()]
    config = {"kind": "labelled-runtime", "runtimeRoot": str(tmp_path / "runtime"),
        "reference": {"tag": "v2026.9.9"}, "buildAttestation": {"sourceBuildReproduced": False},
        "packages": [{"location": "node_modules/openclaw", "directory": "/labelled-fixture",
            "files": [{"path": "labelled.js", "sha256": "1" * 64}]}]}
    control = {"python": {}, "unverified": set(), "rejectedPairs": set(), "failingHosts": set(), "largeCapture": None,
        "pairValues": {}, "pairs": [], "oracleCalls": [], "bindingsChanged": False, "nodeChanged": False}

    def result(case):
        return {"label": "unit result of " + case["id"], "values": [False, 0, None]}

    def native(node_, script, checkout_, selected, timeout, **kwargs):
        case, = selected
        control["oracleCalls"].append((case["id"], timeout))
        assert timeout == (180 if case["operation"] == OPERATION else
                           120 if case["operation"] == "host-turn-barrier-runtime" else 60)
        diagnostic = {"id": case["id"], "sha256": "2" * 64,
            "rawSnapshots": [{"raw": "labelled original capture"}]}
        if case["requirement"] == "host.turn-barrier":
            diagnostic["validationStatus"] = "unverified" if case["id"] in control["unverified"] else "verified"
        return {"kind": "official-release-runtime-comparison", "sources": [],
            "results": [{"id": case["id"], "ok": True, "result": result(case)}],
            "releaseSources": [{"package": "node_modules/openclaw", "path": "labelled.js", "sha256": "1" * 64}],
            "releaseTrace": {"kind": "unit-trace"}, "runtimeDiagnostics": [diagnostic]}

    def python(case):
        directory = case["_diagnosticDirectory"]
        directory.mkdir(parents=True)
        capture = {"raw": "unit SDK capture of " + case["id"]}
        if case["id"] == control["largeCapture"]:
            capture["padding"] = "x" * (16 * 1024 * 1024)
        (directory / "python-raw.json").write_text(json.dumps([capture]))
        if case["id"] in control["failingHosts"]:
            raise RuntimeError("labelled SDK host failure")
        return control["python"].get(case["id"], result(case))

    def pair(case, native_raw, sdk_raw, native_result, sdk_result):
        control["pairs"].append((case["id"], native_raw, sdk_raw, native_result, sdk_result))
        if case["id"] in control["rejectedPairs"]:
            raise ValueError("labelled custody rejection")
        return control["pairValues"].get(case["id"], True)

    monkeypatch.setattr(release_runtime, "prepare_release_runtime", lambda *_args: deepcopy(config))
    monkeypatch.setattr(harness, "_oracle", native)
    monkeypatch.setattr(harness, "_adapter_identity", lambda: {"unit-adapter": "3" * 64})
    monkeypatch.setattr(harness, "_implementation_identity", lambda: {"gitCommit": "4" * 40,
        "sourceSha256": "5" * 64, "sourceFiles": 1, "trackedWorkingTreeDirty": False})
    for module, name in ((flush_runtime_bindings, "prepare_flush_runtime_bindings"),
                         (flush_execution_bindings, "prepare_flush_execution_bindings"),
                         (host_turn_barrier_bindings, "prepare_host_turn_barrier_bindings")):
        monkeypatch.setattr(module, name, lambda *_args, name=name: {"label": name})
    binding_calls = node_calls = 0

    def bindings(*_args):
        nonlocal binding_calls
        binding_calls += 1
        return {"label": "changed" if binding_calls > 1 and control["bindingsChanged"] else "stable"}

    def node_authority(*_args):
        nonlocal node_calls
        node_calls += 1
        return {"label": "changed" if node_calls > 1 and control["nodeChanged"] else "stable"}

    monkeypatch.setattr(host_turn_barrier_boundaries_bindings, "prepare_host_turn_barrier_boundaries_bindings", bindings)
    monkeypatch.setattr(model_runtime_authority, "prepare_model_node_authority", node_authority)
    monkeypatch.setattr(host_turn_barrier_evidence, "validate_pair", pair)
    name = "equivalence.host_turn_barrier_boundaries_evidence"
    try:
        module = importlib.import_module(name)
        monkeypatch.setattr(module, "validate_pair", pair)
    except ModuleNotFoundError as error:
        if error.name != name:
            raise
        module = types.ModuleType(name)
        module.validate_pair = pair
        monkeypatch.setitem(sys.modules, name, module)
    return {"checkout": checkout, "node": node, "reference_path": reference, "scope_path": scope,
            "cases": cases, "python_runner": python, "release_runtime_root": tmp_path / "runtime"}, control


def _point(report, point):
    requirement = next(item for item in report["requirements"] if item["id"] == "host.turn-barrier")
    return next(item for item in requirement["acceptance"] if item["id"] == point)


def test_both_closed_families_coexist_and_credit_only_their_own_point(labelled_suite):
    options, control = labelled_suite
    report, code = harness.run_suite(**options)
    assert code == 0 and report["status"] == "passed"
    assert _point(report, POINTS[0])["matchedCaseIds"] == [case["id"] for case in build_cases()]
    assert _point(report, OUTCOME_POINTS[0])["matchedCaseIds"] == [case["id"] for case in outcome_cases()]
    assert len(control["pairs"]) == 10
    assert all(row["runtimeEvidenceValidated"] is True for row in report["cases"] if row["requirement"] == "host.turn-barrier")


@pytest.mark.parametrize("index", range(6))
@pytest.mark.parametrize("failure", ["mismatch", "custody", "unverified", "failed-host", "false", "truthy-integer"])
def test_each_bad_boundary_member_withholds_all_boundary_credit_but_keeps_outcomes(labelled_suite, index, failure):
    options, control = labelled_suite
    victim = build_cases()[index]["id"]
    if failure == "mismatch":
        control["python"][victim] = {"label": "different unit result"}
    elif failure in {"false", "truthy-integer"}:
        control["pairValues"][victim] = False if failure == "false" else 1
    else:
        control[{"custody": "rejectedPairs", "unverified": "unverified", "failed-host": "failingHosts"}[failure]].add(victim)
    report, code = harness.run_suite(**options)
    assert code != 0
    assert _point(report, POINTS[0])["caseIds"] == [case["id"] for case in build_cases()]
    assert _point(report, POINTS[0])["matchedCaseIds"] == []
    assert _point(report, OUTCOME_POINTS[0])["matchedCaseIds"] == [case["id"] for case in outcome_cases()]
    row = next(row for row in report["cases"] if row["id"] == victim)
    assert row["status"] == ("mismatched" if failure == "mismatch" else "blocked")
    assert (row.get("runtimeEvidenceValidated") is True) is (failure == "mismatch")
    diagnostic = next(d for d in report["runtimeDiagnostics"] if d["id"] == victim and d["side"] == "python")
    assert diagnostic["validationStatus"] == ("verified" if failure == "mismatch" else
                                             "rejected" if failure == "failed-host" else "unverified")
    unrelated = next(item for item in report["requirements"] if item["id"] == "indexing")
    assert unrelated["acceptance"][0]["matchedCaseIds"] == ["labelled-unrelated"]


def test_bad_outcome_member_cannot_steal_a_complete_boundary_family(labelled_suite):
    options, control = labelled_suite
    control["rejectedPairs"].add(outcome_cases()[0]["id"])
    report, code = harness.run_suite(**options)
    assert code == 2
    assert _point(report, OUTCOME_POINTS[0])["matchedCaseIds"] == []
    assert _point(report, POINTS[0])["matchedCaseIds"] == [case["id"] for case in build_cases()]


@pytest.mark.parametrize("which", ["only-boundaries", "only-outcomes"])
def test_one_family_never_completes_its_uncovered_sibling(labelled_suite, which):
    options, _ = labelled_suite
    operation = OPERATION if which == "only-boundaries" else "host-turn-barrier-runtime"
    options["cases"] = [case for case in options["cases"] if case["requirement"] != "host.turn-barrier" or case["operation"] == operation]
    report, code = harness.run_suite(**options)
    assert code == 1 and report["status"] == "incomplete"
    absent = OUTCOME_POINTS[0] if which == "only-boundaries" else POINTS[0]
    present = POINTS[0] if which == "only-boundaries" else OUTCOME_POINTS[0]
    assert _point(report, absent)["caseIds"] == _point(report, absent)["matchedCaseIds"] == []
    assert _point(report, present)["matchedCaseIds"]


@pytest.mark.parametrize("index", range(6))
def test_incomplete_registration_is_rejected_before_any_native_dispatch(labelled_suite, index):
    options, control = labelled_suite
    victim = build_cases()[index]["id"]
    options["cases"] = [case for case in options["cases"] if case["id"] != victim]
    report, code = harness.run_suite(**options)
    assert code == 2 and report["cases"] == [] and report["errors"][0]["code"] == "cases-invalid"
    assert control["oracleCalls"] == []


@pytest.mark.parametrize("tamper", ["unknown-same-requirement", "boundary-steals-outcome", "outcome-steals-boundary",
                                    "new-operation-on-old-literal", "changed-frozen-input"])
def test_shared_requirement_does_not_allow_unknown_or_forged_sibling_cases(labelled_suite, tamper):
    options, control = labelled_suite
    if tamper == "unknown-same-requirement":
        options["cases"].append({"id": "forged-host-row", "operation": "unknown-host-operation",
                                 "requirement": "host.turn-barrier", "covers": [], "input": {}})
    else:
        boundary = next(case for case in options["cases"] if case["operation"] == OPERATION)
        outcome = next(case for case in options["cases"] if case["operation"] == "host-turn-barrier-runtime")
        if tamper == "boundary-steals-outcome":
            boundary["covers"] = list(OUTCOME_POINTS)
        elif tamper == "outcome-steals-boundary":
            outcome["covers"] = list(POINTS)
        elif tamper == "new-operation-on-old-literal":
            outcome["operation"] = OPERATION
        else:
            boundary["input"]["nowMs"] += 1
    report, code = harness.run_suite(**options)
    assert code == 2 and report["cases"] == [] and report["errors"][0]["code"] == "cases-invalid"
    assert control["oracleCalls"] == []


@pytest.mark.parametrize("authority", ["bindingsChanged", "nodeChanged"])
def test_new_source_or_executable_change_invalidates_observations_before_comparison(labelled_suite, authority):
    options, control = labelled_suite
    options["cases"] = build_cases()
    control[authority] = True
    report, code = harness.run_suite(**options)
    assert code == 2 and report["status"] == "blocked" and report["cases"] == []
    assert report["errors"] and control["pairs"] == []


@pytest.mark.parametrize("side", ["new-boundary", "old-outcome"])
def test_larger_sdk_capture_is_admitted_only_by_the_new_boundary_profile(labelled_suite, side):
    options, control = labelled_suite
    victim = (build_cases() if side == "new-boundary" else outcome_cases())[0]["id"]
    control["largeCapture"] = victim
    report, code = harness.run_suite(**options)
    if side == "new-boundary":
        assert code == 0
        assert _point(report, POINTS[0])["matchedCaseIds"] == [case["id"] for case in build_cases()]
    else:
        assert code == 2
        assert _point(report, OUTCOME_POINTS[0])["matchedCaseIds"] == []
    diagnostic = next(item for item in report["runtimeDiagnostics"] if item["id"] == victim and item["side"] == "python")
    assert len(diagnostic["rawSnapshots"][0]["padding"]) == 16 * 1024 * 1024
    assert diagnostic["validationStatus"] == ("verified" if side == "new-boundary" else "rejected")
