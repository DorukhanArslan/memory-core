"""Labelled delegation fixtures test gate routing, never original host behavior."""
import json
from pathlib import Path

import pytest

from equivalence.cases import run_python
from equivalence.harness import HarnessError, _oracle
from equivalence.host_restart_session import build_cases

ROOT = Path(__file__).resolve().parents[2]


def test_host_restart_requires_release_authority_before_dispatch(tmp_path, monkeypatch):
    dispatched = []
    monkeypatch.setattr("equivalence.host_restart_native.run_native_session_case",
                        lambda *args, **kwargs: dispatched.append(args))
    with pytest.raises(HarnessError, match="authenticated release runtime"):
        _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
                [build_cases()[0]], 60)
    assert dispatched == []


@pytest.mark.parametrize("kind", ["official-release-host-restart-development", "official-release-runtime-comparison"])
def test_old_or_generic_capability_cannot_claim_whole_host_acceptance(tmp_path, monkeypatch, kind):
    dispatched = []

    def fixture(*args, **kwargs):
        dispatched.append((args, kwargs))
        return {"kind": kind}

    monkeypatch.setattr("equivalence.harness.ROOT", tmp_path)
    monkeypatch.setattr("equivalence.host_restart_native.run_native_session_case", fixture)
    with pytest.raises(HarnessError, match="no retry") as failure:
        _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
                [build_cases()[0]], 60, release_runtime={"label": "unexecuted transport fixture"})
    assert len(dispatched) == 1
    assert failure.value.rejected_evidence["coverageCredit"] is False


def test_native_transport_retains_exact_result_and_actual_raw_file(tmp_path, monkeypatch):
    case = build_cases()[0]
    raw = [{"label": "unit transport fixture, not authenticated host evidence"}]
    result = {"kept": [0, False, None], "nested": {"value": "complete payload"}}
    trace = {"label": "unit trace fixture"}

    def fixture(selected, node, runtime, directory, *, timeout):
        assert selected == case and timeout == 60
        evidence = directory / "evidence"
        evidence.mkdir(parents=True)
        (evidence / "native-raw.json").write_text(json.dumps(raw))
        return {"kind": "official-release-host-restart-acceptance", "results": [
            {"id": case["id"], "ok": True, "result": result}],
            "releaseSources": [{"label": "unit source fixture"}], "releaseTrace": trace,
            "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}

    monkeypatch.setattr("equivalence.harness.ROOT", tmp_path)
    monkeypatch.setattr("equivalence.host_restart_native.run_native_session_case", fixture)
    returned = _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
                       [case], 60, release_runtime={"label": "unit runtime fixture"})
    assert returned["kind"] == "official-release-runtime-comparison"
    assert returned["sources"] == []
    assert returned["results"] == [{"id": case["id"], "ok": True, "result": result}]
    assert returned["releaseTrace"] == trace
    assert returned["runtimeDiagnostics"][0]["rawSnapshots"] == raw


def test_sdk_dispatch_passes_frozen_input_to_actual_owner_with_evidence_directory(tmp_path, monkeypatch):
    case = build_cases()[0]
    calls = []
    result = {"label": "unit dispatch fixture"}

    def fixture(value, *, evidence_directory):
        calls.append((value, evidence_directory))
        return result

    monkeypatch.setattr("equivalence.host_restart_sdk.run_host_restart", fixture)
    assert run_python({**case, "_diagnosticDirectory": tmp_path}) is result
    assert calls == [(case["input"], tmp_path)]
    changed = build_cases()[0]
    changed["input"]["nowMs"] += 1
    with pytest.raises(ValueError):
        run_python({**changed, "_diagnosticDirectory": tmp_path})
    assert len(calls) == 1
