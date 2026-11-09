"""Rejected transport diagnostics are retained, never authenticated or credited."""
from copy import deepcopy
import base64
import hashlib
import json
import shutil

import pytest

from equivalence import harness, runtime_oracle
from equivalence.harness import HarnessError
from equivalence.runtime_oracle import ReleaseOracleExecution, RuntimeOracleError


CASE = {"id": "rejected-case", "operation": "transcript-boundary-runtime", "input": {"literal": "fixture"}}
ORACLE = {"kind": "official-release-runtime-comparison", "sources": [], "results": [
    {"id": CASE["id"], "ok": True, "result": {"provider": "none", "untrusted": "original"}},
]}


def _execution(root):
    value = ReleaseOracleExecution.__new__(ReleaseOracleExecution)
    value.root = root
    value.evidence_directory = root / "evidence"
    value.trace_directory = root / "traces"
    value.evidence_directory.mkdir(parents=True)
    value.trace_directory.mkdir()
    value._entered = True
    return value


def _raw_path(execution):
    path = execution.evidence_directory / hashlib.sha256(CASE["id"].encode()).hexdigest() / "native-raw.json"
    path.parent.mkdir()
    return path


def test_collect_failure_captures_original_data_before_destructive_context_cleanup(tmp_path, monkeypatch):
    events, launches = [], []
    root = tmp_path / "owned-runtime"
    original_stdout = json.dumps(ORACLE)

    class Context(ReleaseOracleExecution):
        def __init__(self, *_args, **_kwargs):
            self.__dict__.update(_execution(root).__dict__)
            self.env = {"LABELLED_REVIEWED_CONTEXT": "owned"}

        def __enter__(self):
            events.append("entered")
            _raw_path(self).write_text('[{"actual":"rejected original bytes"}]')
            (self.trace_directory / "101-0.jsonl").write_text('{"event":"bootstrap","pid":101,"threadId":0}\n')
            (self.trace_directory / "101-7.jsonl").write_text('{"event":"load","pid":101,"threadId":7}\n')
            return self

        def collect(self, result, _cases):
            events.append("rejected")
            result["results"][0]["result"]["untrusted"] = "validator mutation"
            raise RuntimeOracleError("Literal boundary evidence was rejected")

        def __exit__(self, *_args):
            events.append("closed")
            self._entered = False
            shutil.rmtree(root)

    class Process:
        returncode = 0

        def communicate(self, _body, *, timeout):
            return original_stdout, "labelled native stderr\n"

    def launch(command, **kwargs):
        launches.append(command)
        assert "OPENROUTER_API_KEY" not in kwargs["env"]
        return Process()

    script = tmp_path / "runner.mjs"
    script.write_text("// labelled process fixture")
    monkeypatch.setenv("OPENROUTER_API_KEY", "AMBIENT_SECRET_MUST_NOT_APPEAR")
    monkeypatch.setattr(runtime_oracle, "ReleaseOracleExecution", Context)
    monkeypatch.setattr(harness.subprocess, "Popen", launch)
    with pytest.raises(HarnessError, match="Literal boundary evidence") as caught:
        harness._oracle(tmp_path / "node", script, tmp_path, [CASE], 10, release_runtime={})
    error = caught.value
    assert error.code == "runtime-evidence-invalid"
    assert events == ["entered", "rejected", "closed"] and len(launches) == 1
    assert not root.exists()
    capture = error.rejected_evidence
    assert capture["validationStatus"] == "rejected" and capture["authenticationStatus"] == "unverified"
    assert capture["oracleResult"] == ORACLE
    assert capture["stdout"]["text"] == original_stdout
    assert capture["stderr"]["text"] == "labelled native stderr\n"
    raw, = capture["caseDiagnostics"]
    assert raw["case"] == CASE and raw["rawSnapshots"] == [{"actual": "rejected original bytes"}]
    assert raw["text"] == '[{"actual":"rejected original bytes"}]'
    assert {trace["name"] for trace in capture["processWorkerTraces"]} == {"101-0.jsonl", "101-7.jsonl"}
    assert "AMBIENT_SECRET_MUST_NOT_APPEAR" not in json.dumps(capture)
    assert not {"releaseSources", "releaseTrace", "runtimeDiagnostics"} & capture.keys()


def test_failed_suite_attaches_rejected_diagnostics_without_any_success_or_credit(tmp_path, monkeypatch):
    captured = {"validationStatus": "rejected", "authenticationStatus": "unverified", "caseIds": [CASE["id"]],
                "oracleResult": deepcopy(ORACLE)}
    failure = HarnessError("runtime-evidence-invalid", "Labelled validator rejection")
    failure.rejected_evidence = captured

    def reject(*_args, **_kwargs):
        raise failure

    reference, scope = tmp_path / "reference.json", tmp_path / "scope.json"
    reference.write_text('{}')
    scope.write_text(json.dumps({"schemaVersion": 1, "requirements": [
        {"id": "bounded", "required": True, "acceptance": [{"id": "bounded.point", "description": "fixture"}]},
    ]}))
    monkeypatch.setattr(harness, "_validate_reference", lambda *_args: {})
    monkeypatch.setattr(harness, "_oracle", reject)
    report, code = harness.run_suite(checkout=tmp_path, node=tmp_path / "node", smoke=True,
        reference_path=reference, scope_path=scope,
        cases=[{"id": CASE["id"], "operation": "echo", "requirement": "bounded", "covers": ["bounded.point"], "input": {}}],
        python_runner=lambda _: pytest.fail("Rejected evidence cannot proceed to Python comparison"))
    assert code == 2 and report["status"] == "blocked" and report["fullScopePassed"] is False
    assert report["rejectedRuntimeEvidence"] == [captured]
    assert report["cases"] == [] and report["requirements"] == []
    assert not report.get("releaseTraces") and not report.get("runtimeDiagnostics")


@pytest.mark.parametrize("kind", ["file-symlink", "parent-symlink", "hardlink"])
def test_capture_never_reads_ambient_link_targets(tmp_path, kind):
    execution = _execution(tmp_path / "owned")
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    secret = ambient / "native-raw.json"
    secret.write_text('AMBIENT_SECRET_MUST_NOT_APPEAR')
    destination = _raw_path(execution)
    if kind == "file-symlink":
        destination.symlink_to(secret)
    elif kind == "parent-symlink":
        destination.parent.rmdir()
        destination.parent.symlink_to(ambient, target_is_directory=True)
    else:
        destination.hardlink_to(secret)
    capture = execution.capture_rejected(ORACLE, [CASE], stdout="{}", stderr="")
    assert capture["caseDiagnostics"][0]["captureStatus"] == "unavailable-or-unsafe"
    assert "AMBIENT_SECRET_MUST_NOT_APPEAR" not in json.dumps(capture)


def test_trace_directory_symlink_cannot_reveal_ambient_trace_names_or_contents(tmp_path):
    execution = _execution(tmp_path / "owned")
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    (ambient / "101-1.jsonl").write_text("AMBIENT_SECRET_MUST_NOT_APPEAR")
    execution.trace_directory.rmdir()
    execution.trace_directory.symlink_to(ambient, target_is_directory=True)
    capture = execution.capture_rejected(ORACLE, [CASE], stdout="{}", stderr="")
    assert capture["processWorkerTraces"] == []
    assert {"kind": "traces", "reason": "unavailable-or-unsafe"} in capture["omissions"]
    assert "AMBIENT_SECRET_MUST_NOT_APPEAR" not in json.dumps(capture)


def test_oversized_streams_and_owned_files_have_explicit_bounded_omissions(tmp_path, monkeypatch):
    execution = _execution(tmp_path / "owned")
    _raw_path(execution).write_bytes(b"x" * 9)
    (execution.trace_directory / "101-1.jsonl").write_bytes(b"t" * 9)
    monkeypatch.setattr(runtime_oracle, "MAX_REJECTED_STREAM_BYTES", 5)
    monkeypatch.setattr(runtime_oracle, "MAX_DIAGNOSTIC_BYTES", 8)
    monkeypatch.setattr(runtime_oracle, "MAX_SINGLE_TRACE_BYTES", 8)
    capture = execution.capture_rejected(ORACLE, [CASE], stdout="12345678", stderr="abcdef")
    assert capture["stdout"]["text"] == "12345" and capture["stdout"]["truncated"] is True
    assert capture["stderr"]["capturedBytes"] == 5 and capture["stderr"]["bytes"] == 6
    assert capture["oracleResult"] is None
    assert capture["caseDiagnostics"][0]["captureStatus"] == "unavailable-or-unsafe"
    assert capture["processWorkerTraces"][0]["captureStatus"] == "unavailable-or-unsafe"
    unicode_capture = execution.capture_rejected({}, [CASE], stdout="ab😀c", stderr="")
    assert unicode_capture["stdout"]["text"] == "ab"
    assert unicode_capture["stdout"]["capturedBytes"] == 2


def test_malformed_and_non_utf8_raw_remain_original_rejected_bytes(tmp_path):
    execution = _execution(tmp_path / "owned")
    filename = _raw_path(execution)
    filename.write_text("{incomplete-json")
    capture = execution.capture_rejected(ORACLE, [CASE], stdout="{}", stderr="")
    row = capture["caseDiagnostics"][0]
    assert row["text"] == "{incomplete-json" and row["parseStatus"] == "invalid-json"
    filename.write_bytes(b"\xff\x00\x80")
    capture = execution.capture_rejected(ORACLE, [CASE], stdout="{}", stderr="")
    row = capture["caseDiagnostics"][0]
    assert row["encoding"] == "base64" and base64.b64decode(row["data"]) == b"\xff\x00\x80"
    assert row["validationStatus"] == "unverified"
