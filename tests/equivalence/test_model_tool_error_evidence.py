"""Labelled transport fixtures prove rejection, never native execution."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME
from equivalence.model_runtime_evidence import ENVIRONMENT_KEYS
from equivalence.model_tool_error_bindings import REQUIRED_ERROR_ARTIFACTS
from equivalence.model_tool_error_evidence import validate_model_tool_error_raw
from equivalence.runtime_oracle import ROOT, RuntimeOracleError


def _error(message, **own):
    return {"name": "Error", "message": message, "own": {"message": message, "stack": "Error: " + message + "\n fixture stack", **own}}


@pytest.fixture
def packet(tmp_path):
    value = {"registeredSecrets": ["fixture-credential"], "patterns": ["CUST-[0-9]+"],
             "error": {"message": "request fixture-credential", "cause": {"message": "transport failed", "code": "ECONNRESET"}}}
    base = str(tmp_path / "native-model-error-labelled")
    runtime = {"execPath": "/fixture/node", **APPROVED_NODE_RUNTIME}
    request = {"input": value, "directory": base, "runtimeRoot": "/fixture/release"}
    before, after = {"revision": 0, "values": []}, {"revision": 1, "values": ["fixture-credential"]}
    original_error = _error(value["error"]["message"], cause=_error("transport failed", code="ECONNRESET"))
    invocations = []
    for name, params in (("get", {"path": "topic", "corpus": "wiki"}), ("search", {"query": "topic", "corpus": "wiki"})):
        payload = {"status": "unavailable", "error": "masked fixture failure", "fullExtra": [False, 7]}
        wire = {"content": [{"type": "text", "text": json.dumps(payload)}], "details": payload, "extra": {"preserved": True}}
        decoded = deepcopy(wire)
        decoded["content"][0]["text"] = payload
        invocations.append({"name": name, "callId": "diagnostic-" + name, "params": params,
            "definition": {"name": "memory_" + name, "parameters": {"type": "object"},
                           "execute": {"$type": "function", "name": "execute", "source": "labelled original execute fixture"}},
            "envelope": wire, "decoded": decoded})
    observed = {"kind": "model-tool-error", "pid": 22, "ppid": 11, "request": request, "runtime": runtime,
        "config": {"agents": {"defaults": {"workspace": str(Path(base) / "workspace")}},
                   "logging": {"level": "silent", "consoleLevel": "silent", "file": str(Path(base) / "native.log"), "redactPatterns": value["patterns"]},
                   "memory": {"search": {"enabled": True, "provider": "none", "fallback": "none", "sources": ["memory"]}}},
        "registry": {"before": before, "registrations": [{"secret": "fixture-credential", "before": before, "after": after}], "after": after},
        "error": original_error, "formatter": "masked complete fixture formatter",
        "requests": [{"tool": name, "query": query, "thrownErrorIsOriginal": True, "error": original_error}
                     for name, query in (("get", {"lookup": "topic", "agentId": "main"}), ("search", {"query": "topic", "agentId": "main"}))],
        "invocations": invocations}
    result = {"provider": "none", "formatter": observed["formatter"], "tools": [
        {"name": x["name"], "envelope": x["envelope"], "decoded": x["decoded"]} for x in invocations]}
    request_json = json.dumps(request)
    output = {"result": deepcopy(result), "raw": observed}
    child = {"pid": 22, "request": request, "requestJson": request_json,
             "requestSha256": hashlib.sha256(request_json.encode()).hexdigest(),
             "argv": ["/fixture/node", str(ROOT / "equivalence/model-tool-error-cli.mjs")],
             "environmentKeys": ENVIRONMENT_KEYS, "startedAtNs": "100", "finishedAtNs": "200",
             "exit": {"code": 0, "signal": None}, "stdout": json.dumps(output), "stderr": "", "raw": observed}
    raw = {"kind": "model-tool-error", "fixtureBase": base, "coordinatorPid": 11, "input": value, "runtime": runtime, "child": child}
    return {"row": {"ok": True, "result": deepcopy(result)}, "case": {"operation": "model-tool-error-runtime", "input": value},
            "diagnostic": [raw], "evidence_directory": tmp_path, "runtime_root": "/fixture/release",
            "bootstrap": [{"pid": pid, "isMainThread": True, "runtime": runtime} for pid in (11, 22)],
            "release_by_pid": {22: set(REQUIRED_ERROR_ARTIFACTS)},
            "local_by_pid": {11: {str(ROOT / "equivalence" / p) for p in ("release-oracle.mjs", "model-tool-error-runtime.mjs", "model-runtime-observation.mjs")},
                             22: {str(ROOT / "equivalence" / p) for p in ("model-tool-error-cli.mjs", "model-tool-error-phase.mjs", "model-runtime-observation.mjs", "search-contract-runtime.mjs")}},
            "process_parents": {22: 11}, "worker_imports": [], "_output": output}


def _run(packet):
    validate_model_tool_error_raw(**{k: v for k, v in packet.items() if not k.startswith("_")})


def _refresh(packet):
    packet["diagnostic"][0]["child"]["stdout"] = json.dumps(packet["_output"])


def test_complete_labelled_packet_is_accepted(packet):
    _run(packet)


@pytest.mark.parametrize("field", ["config", "registry", "error", "formatter", "requests", "invocations", "pid", "runtime", "request"])
def test_original_observation_channels_cannot_be_removed(packet, field):
    del packet["diagnostic"][0]["child"]["raw"][field]
    _refresh(packet)
    with pytest.raises((RuntimeOracleError, KeyError, ValueError)):
        _run(packet)


@pytest.mark.parametrize("fault", ["binary", "ppid", "extra-process", "unprotected", "wrong-script", "secret-env", "exit", "request-hash", "wire-raw"])
def test_actual_transport_and_bootstrap_authority_is_required(packet, fault):
    raw, child = packet["diagnostic"][0], packet["diagnostic"][0]["child"]
    if fault == "binary":
        raw["runtime"] = {**raw["runtime"], "sha256": "0" * 64}
    elif fault == "ppid":
        packet["process_parents"][22] = 33
    elif fault == "extra-process":
        packet["bootstrap"].append({"pid": 33, "isMainThread": True, "runtime": raw["runtime"]})
    elif fault == "unprotected":
        packet["bootstrap"].pop()
    elif fault == "wrong-script":
        child["argv"][1] = "/fixture/impostor.mjs"
    elif fault == "secret-env":
        child["environmentKeys"] = [*ENVIRONMENT_KEYS, "PROVIDER_API_KEY"]
    elif fault == "exit":
        child["exit"]["code"] = 1
    elif fault == "request-hash":
        child["requestSha256"] = "0" * 64
    elif fault == "wire-raw":
        child["stdout"] = json.dumps({"result": {}, "raw": {}})
    with pytest.raises((RuntimeOracleError, ValueError)):
        _run(packet)


@pytest.mark.parametrize("fault", ["cause", "code", "stack", "own-extra", "registry-offset", "registry-reset", "registration", "callback", "error-instance", "params", "carrier", "whole-envelope", "formatter", "definition"])
def test_original_error_registry_requests_and_complete_returns_are_bound(packet, fault):
    observed = packet["diagnostic"][0]["child"]["raw"]
    if fault == "cause":
        del observed["error"]["own"]["cause"]
    elif fault == "code":
        observed["error"]["own"]["cause"]["own"]["code"] = "OTHER"
    elif fault == "stack":
        observed["error"]["own"]["stack"] = "dropped"
    elif fault == "own-extra":
        observed["error"]["own"]["synthetic"] = "injected"
    elif fault == "registry-offset":
        observed["registry"]["before"] = {"revision": 1, "values": []}
    elif fault == "registry-reset":
        observed["registry"]["after"] = {"revision": 0, "values": []}
    elif fault == "registration":
        observed["registry"]["registrations"] = []
    elif fault == "callback":
        observed["requests"][0]["query"]["agentId"] = "peer"
    elif fault == "error-instance":
        observed["requests"][0]["thrownErrorIsOriginal"] = False
    elif fault == "params":
        observed["invocations"][0]["params"]["corpus"] = "all"
    elif fault == "carrier":
        observed["invocations"][0]["envelope"]["content"][0]["text"] = "{}"
    elif fault == "whole-envelope":
        del packet["row"]["result"]["tools"][0]["envelope"]["extra"]
    elif fault == "formatter":
        packet["row"]["result"]["formatter"] = "subset"
    elif fault == "definition":
        del observed["invocations"][0]["definition"]["execute"]
    _refresh(packet)
    with pytest.raises((RuntimeOracleError, KeyError, ValueError)):
        _run(packet)


@pytest.mark.parametrize("artifact", REQUIRED_ERROR_ARTIFACTS)
def test_every_real_error_tool_owner_must_execute(packet, artifact):
    packet["release_by_pid"][22].remove(artifact)
    with pytest.raises(RuntimeOracleError):
        _run(packet)
