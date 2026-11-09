"""Actual exclusive preload rejection, before any original Doctor imports."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from equivalence.heartbeat_doctor_authority import NODE, validate_doctor_authority, prepare_doctor_authority
from equivalence.heartbeat_node_authority import validate_heartbeat_node_authority, prepare_heartbeat_node_authority
from equivalence.heartbeat_doctor_probe import ROOT, CODEC_SHA256, _documents, build_doctor_cases, phase
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
