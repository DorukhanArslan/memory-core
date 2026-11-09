"""Actual exclusive preload rejection, before any original Doctor imports."""
from __future__ import annotations

import hashlib
import base64
import json
import os
from pathlib import Path
import subprocess
from copy import deepcopy

import pytest

from equivalence.heartbeat_doctor_authority import NODE, validate_doctor_authority, prepare_doctor_authority
from equivalence.heartbeat_node_authority import validate_heartbeat_node_authority, prepare_heartbeat_node_authority
from equivalence.heartbeat_doctor_probe import (
    ROOT, CODEC_SHA256, _capture_process, _documents, _error, _validate_decoded_events, _validate_public_observation,
    build_doctor_cases, phase,
)
from equivalence.heartbeat_doctor_bindings import MANIFEST_SHA256

EXECUTABLE = Path("/workspace/openclaw-memory-bridge/node_modules/node/bin/node")


def _capability(kind="heartbeat-doctor-node-capability", profile="heartbeat-scratch-doctor"):
    return {"kind": kind, "profile": profile, "node": {"execPath": str(EXECUTABLE), **NODE}}


@pytest.mark.parametrize("kind,profile", [
    ("heartbeat-scratch-node-capability", "heartbeat-scratch-doctor"),
    ("heartbeat-doctor-node-capability", "heartbeat-scratch-store"),
    ("approved-entry-provenance-profile", "heartbeat-scratch-doctor"),
])
def test_doctor_authority_rejects_borrowed_kind_and_profile(kind, profile):
    with pytest.raises(ValueError):
        validate_doctor_authority(_capability(kind, profile))


def test_store_authority_rejects_its_dormant_doctor_label():
    with pytest.raises(ValueError):
        validate_heartbeat_node_authority(_capability("heartbeat-scratch-node-capability"))


@pytest.mark.parametrize("variable", ["MEMORY_EQ_DOCTOR_CONTEXT", "MEMORY_EQ_RELEASE_CONTEXT"])
def test_store_constructor_rejects_other_context_before_executable_access(monkeypatch, variable):
    monkeypatch.setenv(variable, "/unused-context")
    with pytest.raises(ValueError, match="contexts"):
        prepare_heartbeat_node_authority(Path("/nonexistent-node"), "heartbeat-scratch-store")


@pytest.mark.parametrize("variable", ["MEMORY_EQ_HEARTBEAT_CONTEXT", "MEMORY_EQ_RELEASE_CONTEXT"])
def test_doctor_constructor_rejects_other_context_before_executable_access(monkeypatch, variable):
    monkeypatch.setenv(variable, "/unused-context")
    with pytest.raises(ValueError, match="contexts"):
        prepare_doctor_authority(Path("/nonexistent-node"))


def _reject(tmp_path, preload, context, *, context_variable, additional=None, request_override=None):
    if not EXECUTABLE.exists():
        pytest.skip("The exact approved Node binary is not installed")
    assert hashlib.sha256(EXECUTABLE.read_bytes()).hexdigest() == NODE["sha256"]
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"kind": "heartbeat-doctor-sequence", "phase": 0, "input": phase("findings"),
                                   "fixtureDirectory": str(tmp_path / "fixture"), **(request_override or {})}))
    context = {**context, "requestPath": str(request), "requestSha256": hashlib.sha256(request.read_bytes()).hexdigest()}
    context_path = tmp_path / "context.json"; context_path.write_text(json.dumps(context))
    environment = {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC", "OPENAI_API_KEY": "", "OPENROUTER_API_KEY": "",
                   context_variable: str(context_path), **(additional or {})}
    result = subprocess.run([str(EXECUTABLE), "--import", str(ROOT / "equivalence" / preload), "--eval",
                             "process.stdout.write('UNEXPECTED_EXECUTION')"], env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "UNEXPECTED_EXECUTION" not in result.stderr
    return result.stderr


def _doctor_context(tmp_path):
    return {"kind": "heartbeat-doctor-execution", "providerMode": "none", "fetchPolicy": "deny",
            "capability": _capability(), "bindingsSha256": MANIFEST_SHA256, "codecSha256": CODEC_SHA256,
            "runtime": {}, "allowedLocal": [], "traceDirectory": str(tmp_path / "traces")}


@pytest.mark.parametrize("variable", ["MEMORY_EQ_HEARTBEAT_CONTEXT", "MEMORY_EQ_RELEASE_CONTEXT"])
def test_real_doctor_preload_rejects_mixed_contexts_before_original_imports(tmp_path, variable):
    error = _reject(tmp_path, "heartbeat-doctor-preload.mjs", _doctor_context(tmp_path),
                    context_variable="MEMORY_EQ_DOCTOR_CONTEXT", additional={variable: "/unused-foreign-context"})
    assert "cannot borrow" in error


def test_real_doctor_preload_rejects_unknown_capability_keys(tmp_path):
    context = _doctor_context(tmp_path)
    context["approvedReferenceSources"] = []
    error = _reject(tmp_path, "heartbeat-doctor-preload.mjs", context, context_variable="MEMORY_EQ_DOCTOR_CONTEXT")
    assert "cannot borrow" in error


def test_real_doctor_preload_rejects_store_kind_before_original_imports(tmp_path):
    context = _doctor_context(tmp_path)
    context["capability"]["kind"] = "heartbeat-scratch-node-capability"
    error = _reject(tmp_path, "heartbeat-doctor-preload.mjs", context, context_variable="MEMORY_EQ_DOCTOR_CONTEXT")
    assert "cannot borrow" in error


@pytest.mark.parametrize("request_override,reason", [
    ({"kind": "heartbeat-scratch-store"}, "exact literal bounded fixture"),
    ({"input": phase("runScheduler")}, "Undeclared Doctor operation"),
    ({"input": {**phase("findings"), "model": "unreviewed"}}, "exact literal bounded fixture"),
    ({"input": phase({"op": "repair", "gatewayCompletion": True})}, "unreviewed parameters"),
])
def test_real_doctor_preload_rejects_unreviewed_operation_and_input_before_imports(tmp_path, request_override, reason):
    error = _reject(tmp_path, "heartbeat-doctor-preload.mjs", _doctor_context(tmp_path),
                    context_variable="MEMORY_EQ_DOCTOR_CONTEXT", request_override=request_override)
    assert reason in error


@pytest.mark.parametrize("variable", ["MEMORY_EQ_DOCTOR_CONTEXT", "MEMORY_EQ_RELEASE_CONTEXT"])
def test_real_store_preload_rejects_mixed_contexts_before_original_imports(tmp_path, variable):
    error = _reject(tmp_path, "heartbeat-preload.mjs", {}, context_variable="MEMORY_EQ_HEARTBEAT_CONTEXT",
                    additional={variable: "/unused-foreign-context"})
    assert "cannot borrow" in error


def test_real_store_preload_rejects_old_doctor_profile_before_original_imports(tmp_path):
    context = {"kind": "heartbeat-scratch-execution", "providerMode": "none", "fetchPolicy": "deny",
               "capability": _capability("heartbeat-scratch-node-capability"), "runtime": {}, "allowedLocal": [],
               "traceDirectory": str(tmp_path / "traces")}
    error = _reject(tmp_path, "heartbeat-preload.mjs", context, context_variable="MEMORY_EQ_HEARTBEAT_CONTEXT")
    assert "explicit heartbeat scratch capability" in error


def test_doctor_documents_are_separate_fixed_authorities_and_no_scope_is_awarded():
    documents = _documents()
    assert documents["heartbeat-doctor-bindings.proposal.json"]["sha256"] == MANIFEST_SHA256
    assert documents["heartbeat-doctor-codec.proposal.json"]["sha256"] == CODEC_SHA256
    cases = build_doctor_cases()
    assert all(case["requirement"] == "heartbeat.scratch" and case["covers"] == [] for case in cases)


def _encoded_guard_fixture():
    # Deliberately synthetic guard inputs, never represented as captured evidence.
    blob = {"type": "Uint8Array", "base64": "AA=="}
    events = [
        {"event": "worker-send", "targetThreadId": 1,
         "message": {"type": "execute", "input": blob}},
        {"event": "worker-reply", "targetThreadId": 1,
         "message": {"value": blob, "preparation": blob}},
    ]
    rows = [{"trace": "guard.jsonl", "line": line, "event": event["event"],
             "messageType": event["message"].get("type", {"type": "undefined"}),
             "targetThreadId": 1, "field": field, "bytes": blob,
             "value": {"type": "unapproved.additional.command"}}
            for line, event in enumerate(events, 1) for field in ("input", "value", "preparation")
            if field in event["message"]]
    return {"guard.jsonl": events}, rows


def test_decode_guard_requires_every_original_encoded_transport_field_once():
    traces, rows = _encoded_guard_fixture()
    _validate_decoded_events(traces, rows)
    for omitted in range(len(rows)):
        with pytest.raises(ValueError, match="omitted"):
            _validate_decoded_events(traces, rows[:omitted] + rows[omitted + 1:])
    with pytest.raises(ValueError, match="duplicated or added"):
        _validate_decoded_events(traces, rows + [deepcopy(rows[0])])
    extra = {**rows[0], "trace": "unobserved.jsonl"}
    with pytest.raises(ValueError, match="duplicated or added"):
        _validate_decoded_events(traces, [*rows, extra])
    changed = deepcopy(rows)
    changed[0]["bytes"]["base64"] = "AQ=="
    with pytest.raises(ValueError, match="not bound"):
        _validate_decoded_events(traces, changed)


@pytest.mark.parametrize("input_value", [None, {}, {"type": "undefined"}, {"base64": 12}])
def test_decode_guard_rejects_execute_without_complete_encoded_input(input_value):
    traces, rows = _encoded_guard_fixture()
    traces["guard.jsonl"][0]["message"]["input"] = input_value
    with pytest.raises(ValueError, match="encoded input"):
        _validate_decoded_events(traces, rows)


def test_public_guard_binds_complete_operations_snapshots_and_envelope():
    request = phase("findings")
    raw = {"calls": [{"operation": {"op": "findings"}, "result": []}],
           "snapshots": [{"monitors": {}}, {"monitors": {"main": {"type": "undefined"}}}]}
    actual = {"kind": "heartbeat-doctor-observation", "covers": [], "raw": raw,
              "result": {"operations": [[]], "snapshots": deepcopy(raw["snapshots"])}}
    _validate_public_observation(actual, request)
    for key in ("kind", "covers", "raw", "result"):
        omitted = deepcopy(actual); del omitted[key]
        with pytest.raises(ValueError, match="envelope"):
            _validate_public_observation(omitted, request)
    for replacement in ([], raw["snapshots"][:1], [{"projected": True}, *raw["snapshots"][1:]]):
        changed = deepcopy(actual); changed["result"]["snapshots"] = replacement
        with pytest.raises(ValueError, match="snapshot"):
            _validate_public_observation(changed, request)
    changed = deepcopy(actual); changed["result"]["operations"] = []
    with pytest.raises(ValueError, match="snapshot"):
        _validate_public_observation(changed, request)
    changed = deepcopy(actual); changed["result"]["projected"] = True
    with pytest.raises(ValueError, match="envelope"):
        _validate_public_observation(changed, request)


@pytest.mark.parametrize("side", ["native", "sdk"])
def test_timeout_retains_exact_partial_bytes_and_serializable_original_error(tmp_path, monkeypatch, side):
    output, stderr = b'partial\x00\xff\r\n', b'failure\xfe\r\n'
    original = subprocess.TimeoutExpired(["synthetic-timeout-guard"], 60, output=output, stderr=stderr)
    original.nested = {"payload": [output, ValueError("nested original error")]}
    def timeout(*args, **kwargs):
        assert kwargs["capture_output"] is True
        assert "text" not in kwargs
        raise original
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        _capture_process(["synthetic-timeout-guard"], tmp_path, side, timeout=60)
    assert caught.value is original
    assert (tmp_path / (side + ".stdout.json")).read_bytes() == output
    assert (tmp_path / (side + ".stderr.log")).read_bytes() == stderr
    recorded = json.loads((tmp_path / (side + ".timeout.json")).read_bytes())
    rejection = json.loads(json.dumps({"error": _error(original)}))
    assert recorded["name"] == rejection["error"]["name"] == "TimeoutExpired"
    properties = recorded["ownProperties"]
    assert base64.b64decode(properties["output"]["base64"]) == output
    assert base64.b64decode(properties["stderr"]["base64"]) == stderr
    assert properties["nested"]["payload"][1]["name"] == "ValueError"
    assert properties["nested"]["payload"][1]["message"] == "nested original error"


@pytest.mark.parametrize("returncode", [0, 7])
def test_process_boundary_keeps_exact_bytes_before_actual_exit_status(tmp_path, monkeypatch, returncode):
    original = subprocess.CompletedProcess(["synthetic-process-guard"], returncode, b'{"raw":"\xff"}\r\n', b'\xfe\r\n')
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: original)
    if returncode:
        with pytest.raises(subprocess.CalledProcessError) as caught:
            _capture_process(original.args, tmp_path, "native")
        recorded = json.loads(json.dumps(_error(caught.value)))
        assert base64.b64decode(recorded["ownProperties"]["output"]["base64"]) == original.stdout
    else:
        assert _capture_process(original.args, tmp_path, "native") is original
    assert (tmp_path / "native.stdout.json").read_bytes() == original.stdout
    assert (tmp_path / "native.stderr.log").read_bytes() == original.stderr
