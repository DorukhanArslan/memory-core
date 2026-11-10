"""Labelled transport fixtures test routing and credit, never native behavior."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from equivalence import harness, release_runtime
from equivalence.cases import run_python
from equivalence.harness import HarnessError, _oracle
from equivalence.host_turn_barrier import POINTS, build_cases
from equivalence.host_turn_barrier_native import NATIVE_KIND

ROOT = Path(__file__).resolve().parents[2]
RUNNER = "equivalence.host_turn_barrier_native.run_native_case"


def test_native_authority_is_required_before_dispatch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(RUNNER, lambda *args, **kwargs: calls.append(args))
    with pytest.raises(HarnessError, match="authenticated release runtime"):
        _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path, [build_cases()[0]], 60)
    assert calls == []


@pytest.mark.parametrize("kind", ["official-release-host-restart-acceptance",
                                  "official-release-host-update-isolation-acceptance",
                                  "official-release-runtime-comparison"])
def test_another_capability_cannot_supply_the_natural_host_capture(tmp_path, monkeypatch, kind):
    calls = []

    def fixture(*args, **kwargs):
        calls.append((args, kwargs))
        return {"kind": kind}

    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(RUNNER, fixture)
    with pytest.raises(HarnessError, match="no retry") as error:
        _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
                [build_cases()[0]], 60, release_runtime={"label": "transport unit fixture"})
    assert len(calls) == 1
    assert error.value.code == "host-turn-barrier-evidence-invalid"
    assert error.value.rejected_evidence["coverageCredit"] is False


def test_transport_keeps_the_complete_result_and_its_actual_raw_bytes(tmp_path, monkeypatch):
    case = build_cases()[0]
    raw = [{"label": "unit raw transport fixture, not native evidence"}]
    result = {"all": [False, 0, None], "debug": {"searchMs": 0}, "provenance": {"observedAt": 123}}
    trace = {"label": "unit trace fixture"}

    def fixture(selected, node, runtime, directory, *, timeout):
        assert selected == case and timeout == 60
        evidence = directory / "evidence"
        evidence.mkdir(parents=True)
        (evidence / "native-raw.json").write_text(json.dumps(raw))
        return {"kind": NATIVE_KIND, "results": [{"id": case["id"], "ok": True, "result": result}],
            "releaseSources": [], "releaseTrace": trace, "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}

    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(RUNNER, fixture)
    returned = _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
        [case], 60, release_runtime={"label": "transport unit fixture"})
    assert returned["results"] == [{"id": case["id"], "ok": True, "result": result}]
    assert returned["releaseTrace"] == trace
    assert returned["runtimeDiagnostics"] == [{"id": case["id"],
        "sha256": hashlib.sha256(json.dumps(raw).encode()).hexdigest(),
        "rawSnapshots": raw, "validationStatus": "verified"}]
    assert Path(returned["evidenceDirectory"]).is_relative_to(tmp_path / ".equivalence-results/host-turn-barrier")


@pytest.mark.parametrize("tamper", ["different-raw", "duplicate-raw", "symlink", "hardlink"])
def test_transport_rejects_changed_or_unowned_actual_capture(tmp_path, monkeypatch, tamper):
    case = build_cases()[0]
    raw = [{"label": "unit raw fixture"}]

    def fixture(selected, node, runtime, directory, *, timeout):
        evidence = directory / "evidence"
        evidence.mkdir(parents=True)
        target = evidence / "native-raw.json"
        target.write_text(json.dumps(raw if tamper != "different-raw" else [{"label": "changed"}]))
        if tamper == "symlink":
            original = target.with_name("other.json")
            target.rename(original)
            target.symlink_to(original)
        elif tamper == "hardlink":
            import os
            os.link(target, target.with_name("other.json"))
        elif tamper == "duplicate-raw":
            raw.append(deepcopy(raw[0]))
            target.write_text(json.dumps(raw))
        return {"kind": NATIVE_KIND, "results": [], "releaseSources": [], "releaseTrace": {},
                "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}

    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(RUNNER, fixture)
    with pytest.raises(HarnessError, match="no retry"):
        _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
            [case], 60, release_runtime={"label": "transport unit fixture"})


def test_sdk_dispatch_uses_the_frozen_case_and_owned_diagnostics(tmp_path, monkeypatch):
    case = build_cases()[0]
    calls, result = [], {"label": "unit SDK dispatch fixture"}

    def fixture(value, *, evidence_directory):
        calls.append((value, evidence_directory))
        return result

    monkeypatch.setattr("equivalence.host_turn_barrier_sdk.run_host_turn_barrier_case", fixture)
    assert run_python({**case, "_diagnosticDirectory": tmp_path}) is result
    assert calls == [(case["input"], tmp_path)]
    changed = deepcopy(case)
    changed["input"]["nowMs"] += 1
    with pytest.raises(ValueError):
        run_python({**changed, "_diagnosticDirectory": tmp_path})
    assert len(calls) == 1


def test_adapter_identity_includes_minimal_provider_bytes_and_metadata(tmp_path, monkeypatch):
    directory = tmp_path / "equivalence"
    provider = directory / "host-turn-barrier-provider"
    provider.mkdir(parents=True)
    (directory / "ordinary.py").write_text("labelled fixture")
    (provider / "index.mjs").write_text("labelled provider fixture")
    (provider / "openclaw.plugin.json").write_text('{}')
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    before = harness._adapter_identity()
    assert set(before) == {"ordinary.py", "host-turn-barrier-provider/index.mjs",
                           "host-turn-barrier-provider/openclaw.plugin.json"}
    for name in ("index.mjs", "openclaw.plugin.json"):
        file = provider / name
        original = file.read_text()
        file.write_text(original + " ")
        assert harness._adapter_identity() != before
        file.write_text(original)
    assert harness._adapter_identity() == before


def _git(directory, *args):
    return subprocess.run(["git", *args], cwd=directory, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture
def labelled_suite(tmp_path, monkeypatch):
    """Wire abstract fixture rows through the real gate; no execution claim is made."""
    from equivalence import flush_execution_bindings, flush_runtime_bindings, host_turn_barrier_bindings
    from equivalence import host_turn_barrier_evidence, model_runtime_authority

    checkout = tmp_path / "reference"
    checkout.mkdir()
    _git(checkout, "init", "-q")
    (checkout / "package.json").write_text(json.dumps({"version": "2026.9.9",
        "engines": {"node": ">=24.16.0 <25 || >=26.1.0"}}))
    _git(checkout, "add", ".")
    _git(checkout, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "Labelled routing fixture")
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"tag": "v2026.9.9", "commit": _git(checkout, "rev-parse", "HEAD"),
        "nodeMin": "24.16.0", "nodeRanges": ">=24.16.0 <25 || >=26.1.0"}))
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"schemaVersion": 1, "requirements": [
        {"id": "host.turn-barrier", "required": True, "acceptance": [
            {"id": point, "description": "Labelled original point"} for point in
            (*POINTS, "host.turn-barrier.boundaries")]},
        {"id": "indexing", "required": True, "acceptance": [
            {"id": "indexing.lifecycle", "description": "Unrelated labelled point"}]}]}))
    node = tmp_path / "node"
    node.write_text(f"#!{sys.executable}\nprint('v24.16.0')\n")
    node.chmod(0o700)
    unrelated = {"id": "labelled-unrelated", "requirement": "indexing", "operation": "index-lifecycle-runtime",
        "input": {"provider": "none"}, "covers": ["indexing.lifecycle"]}
    cases = [unrelated, *build_cases()]
    config = {"kind": "labelled-runtime", "runtimeRoot": str(tmp_path / "runtime"),
        "reference": {"tag": "v2026.9.9"}, "buildAttestation": {"sourceBuildReproduced": False},
        "packages": [{"location": "node_modules/openclaw", "directory": "/owned/fixture",
            "files": [{"path": "labelled.js", "sha256": "1" * 64}]}]}
    control = {"native": {}, "python": {}, "unverified": set(), "rejectedPairs": set(),
        "failingHosts": set(), "falsePairs": set(), "pairs": [], "bindingsChanged": False}

    def result(case):
        return {"provider": "none", "label": "labelled result of " + case["id"]}

    def native(node_, script, checkout_, selected, timeout, **kwargs):
        case, = selected
        assert timeout == (120 if case["operation"] == "host-turn-barrier-runtime" else 60)
        diagnostic = {"id": case["id"], "sha256": "2" * 64,
            "rawSnapshots": [{"raw": "labelled original capture"}]}
        if case["operation"] == "host-turn-barrier-runtime":
            diagnostic["validationStatus"] = "unverified" if case["id"] in control["unverified"] else "verified"
        return {"kind": "official-release-runtime-comparison", "sources": [],
            "results": [{"id": case["id"], "ok": True, "result": control["native"].get(case["id"], result(case))}],
            "releaseSources": [{"package": "node_modules/openclaw", "path": "labelled.js", "sha256": "1" * 64}],
            "releaseTrace": {"kind": "labelled-trace"}, "runtimeDiagnostics": [diagnostic]}

    def python(case):
        directory = case["_diagnosticDirectory"]
        directory.mkdir(parents=True)
        (directory / "python-raw.json").write_text(json.dumps([{"raw": "labelled SDK capture of " + case["id"]}]))
        if case["id"] in control["failingHosts"]:
            raise RuntimeError("labelled SDK host failure")
        return control["python"].get(case["id"], result(case))

    def pair(case, native_raw, sdk_raw, native_result, sdk_result):
        control["pairs"].append((case["id"], native_raw, sdk_raw, native_result, sdk_result))
        if case["id"] in control["rejectedPairs"]:
            raise ValueError("labelled custody rejection")
        return case["id"] not in control["falsePairs"]

    monkeypatch.setattr(release_runtime, "prepare_release_runtime", lambda *_args: deepcopy(config))
    monkeypatch.setattr(harness, "_oracle", native)
    monkeypatch.setattr(harness, "_adapter_identity", lambda: {"labelled-adapter": "3" * 64})
    monkeypatch.setattr(harness, "_implementation_identity", lambda: {"gitCommit": "4" * 40,
        "sourceSha256": "5" * 64, "sourceFiles": 1, "trackedWorkingTreeDirty": False})
    for module, name in ((flush_runtime_bindings, "prepare_flush_runtime_bindings"),
                         (flush_execution_bindings, "prepare_flush_execution_bindings")):
        monkeypatch.setattr(module, name, lambda *_args, name=name: {"label": name})
    count = 0

    def bindings(*_args):
        nonlocal count
        count += 1
        return {"label": "changed" if count > 1 and control["bindingsChanged"] else "stable"}

    monkeypatch.setattr(host_turn_barrier_bindings, "prepare_host_turn_barrier_bindings", bindings)
    monkeypatch.setattr(model_runtime_authority, "prepare_model_node_authority", lambda *_args: {"label": "node fixture"})
    monkeypatch.setattr(host_turn_barrier_evidence, "validate_pair", pair)
    return {"checkout": checkout, "node": node, "reference_path": reference, "scope_path": scope,
        "cases": cases, "python_runner": python, "release_runtime_root": tmp_path / "runtime"}, control


def _point(report, point):
    requirement = next(item for item in report["requirements"] if item["id"] == "host.turn-barrier")
    return next(item for item in requirement["acceptance"] if item["id"] == point)


def test_complete_validated_outcome_never_credits_the_boundary(labelled_suite):
    options, control = labelled_suite
    report, code = harness.run_suite(**options)
    family = [case["id"] for case in build_cases()]
    assert code == 1 and report["status"] == "incomplete" and report["fullScopePassed"] is False
    assert _point(report, POINTS[0])["matchedCaseIds"] == family
    assert _point(report, "host.turn-barrier.boundaries")["caseIds"] == []
    assert _point(report, "host.turn-barrier.boundaries")["matchedCaseIds"] == []
    assert [pair[0] for pair in control["pairs"]] == family
    assert all(row["runtimeEvidenceValidated"] is True for row in report["cases"] if row["id"] in family)


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("failure", ["mismatch", "custody", "unverified", "failed-host", "false-custody"])
def test_each_bad_member_leaves_the_outcome_uncredited_and_other_points_independent(labelled_suite, index, failure):
    options, control = labelled_suite
    family = [case["id"] for case in build_cases()]
    victim = family[index]
    if failure == "mismatch":
        control["python"][victim] = {"label": "different result"}
    else:
        control[{"custody": "rejectedPairs", "unverified": "unverified",
                 "failed-host": "failingHosts", "false-custody": "falsePairs"}[failure]].add(victim)
    report, code = harness.run_suite(**options)
    assert code != 0
    assert _point(report, POINTS[0])["caseIds"] == family
    assert _point(report, POINTS[0])["matchedCaseIds"] == []
    assert _point(report, "host.turn-barrier.boundaries")["matchedCaseIds"] == []
    unrelated = next(item for item in report["requirements"] if item["id"] == "indexing")
    assert unrelated["acceptance"][0]["matchedCaseIds"] == ["labelled-unrelated"]
    row = next(row for row in report["cases"] if row["id"] == victim)
    assert row["status"] == ("mismatched" if failure == "mismatch" else "blocked")
    assert (row.get("runtimeEvidenceValidated") is True) is (failure == "mismatch")
    diagnostic = next(item for item in report["runtimeDiagnostics"] if item["id"] == victim and item["side"] == "python")
    assert diagnostic["validationStatus"] == ("verified" if failure == "mismatch" else
        "rejected" if failure == "failed-host" else "unverified")


def test_source_binding_change_invalidates_the_entire_observation(labelled_suite):
    options, control = labelled_suite
    control["bindingsChanged"] = True
    report, code = harness.run_suite(**options)
    assert code == 2 and report["status"] == "blocked"
    assert report["cases"] == []
    assert report["errors"] and control["pairs"] == []
