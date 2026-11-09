from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME, validate_model_node_authority
from equivalence.model_runtime_bindings import REQUIRED_HELPER_ARTIFACTS, REQUIRED_SESSION_READ_ARTIFACTS, REQUIRED_SESSION_WRITE_ARTIFACTS
from equivalence.model_runtime_evidence import (
    ENVIRONMENT_KEYS, SQL_TABLES, _markers, _policy, _registry_journal, _sql, validate_model_session_raw, validate_model_tool_result_raw,
)
from equivalence.runtime_oracle import ROOT, RuntimeOracleError


def _protocol(tmp_path):
    base = str(tmp_path / "native-model-helper-fixture")
    runtime = {"execPath": "/approved/node", **APPROVED_NODE_RUNTIME}
    value = {"kind": "model-helper", "value": {"content": [{"type": "text", "text": "literal"}], "extra": [False, None]}}
    request = {"input": value, "directory": base, "runtimeRoot": "/original/runtime"}
    logging = {"level": "silent", "consoleLevel": "silent", "file": base + "/native.log"}
    result = {"sanitized": deepcopy(value["value"]), "arguments": deepcopy(value["value"])}
    identity = {"sanitizedOutputReuse": True, "originalInputReuse": False}
    observed = {"pid": 102, "ppid": 101, "request": request, "runtime": runtime, "config": {"logging": logging},
        "registry": [{"stage": stage, "snapshot": {"revision": 0, "values": []}} for stage in ("initial", "final")],
        "stages": [{"stage": "whole-sanitize", "input": value["value"], "output": result["sanitized"],
            "arguments": result["arguments"], "identity": identity,
            "policy": {"patterns": [], "fullContext": False, "registryRevision": 0}}],
        "result": result, "identity": identity}
    output = {"result": {"provider": "none", "result": result, "identity": identity}, "raw": observed}
    request_json = json.dumps(request)
    child = {"pid": 102, "request": request, "requestJson": request_json,
        "requestSha256": hashlib.sha256(request_json.encode()).hexdigest(),
        "argv": [runtime["execPath"], str(ROOT / "equivalence/model-tool-result-cli.mjs")],
        "environmentKeys": ENVIRONMENT_KEYS, "startedAtNs": "1", "finishedAtNs": "2", "exit": {"code": 0, "signal": None},
        "stdout": json.dumps(output), "stderr": "", "raw": observed}
    diagnostic = [{"kind": "model-helper", "fixtureBase": base, "coordinatorPid": 101, "input": value, "runtime": runtime, "child": child}]
    row = {"id": "helper", "ok": True, "result": deepcopy(output["result"])}
    case = {"id": "helper", "input": value}
    kwargs = {"runtime_root": "/original/runtime", "bootstrap": [
        {"pid": pid, "isMainThread": True, "runtime": runtime} for pid in (101, 102)],
        "release_by_pid": {102: set(REQUIRED_HELPER_ARTIFACTS)},
        "local_by_pid": {101: {str(ROOT / "equivalence" / name) for name in (
            "release-oracle.mjs", "model-tool-result-runtime.mjs", "model-runtime-observation.mjs")},
            102: {str(ROOT / "equivalence" / name) for name in (
            "model-tool-result-cli.mjs", "model-tool-result-phase.mjs", "model-runtime-observation.mjs")}},
        "process_parents": {102: 101}, "worker_imports": []}
    return row, case, diagnostic, kwargs


def _validate(tmp_path, packet):
    row, case, diagnostic, kwargs = packet
    return validate_model_tool_result_raw(row, case, diagnostic, tmp_path, **kwargs)


def test_complete_helper_transport_keeps_full_values_and_real_identity_observations(tmp_path):
    _validate(tmp_path, _protocol(tmp_path))


@pytest.mark.parametrize("field", tuple(APPROVED_NODE_RUNTIME))
def test_wrong_actual_binary_or_unicode_runtime_is_rejected(field):
    value = {"execPath": "/approved/node", **APPROVED_NODE_RUNTIME}
    value[field] = "wrong"
    with pytest.raises(ValueError, match="approved"):
        validate_model_node_authority(value)


@pytest.mark.parametrize("scope", ("coordinator", "child", "thread"))
def test_every_actual_process_and_thread_must_attest_the_approved_binary(tmp_path, scope):
    packet = deepcopy(_protocol(tmp_path))
    if scope == "coordinator":
        packet[2][0]["runtime"]["nodeVersion"] = "v26.0.0"
    elif scope == "child":
        packet[2][0]["child"]["raw"]["runtime"]["sha256"] = "0" * 64
    else:
        packet[3]["bootstrap"].append({"pid": 102, "threadId": 1, "isMainThread": False})
    with pytest.raises((ValueError, RuntimeOracleError)):
        _validate(tmp_path, packet)


@pytest.mark.parametrize("field", (
    "request", "requestJson", "requestSha256", "argv", "environmentKeys", "exit", "stdout", "stderr", "raw",
))
def test_original_child_transport_channels_cannot_be_dropped(tmp_path, field):
    packet = deepcopy(_protocol(tmp_path))
    del packet[2][0]["child"][field]
    with pytest.raises(RuntimeOracleError):
        _validate(tmp_path, packet)


@pytest.mark.parametrize("field", ("config", "registry", "stages", "result", "identity", "runtime", "request"))
def test_full_raw_helper_channels_cannot_be_dropped(tmp_path, field):
    packet = deepcopy(_protocol(tmp_path))
    del packet[2][0]["child"]["raw"][field]
    with pytest.raises(RuntimeOracleError):
        _validate(tmp_path, packet)


@pytest.mark.parametrize("field", ("sanitizedOutputReuse", "originalInputReuse"))
def test_raw_input_cache_identity_is_a_visible_compared_behavior(tmp_path, field):
    packet = deepcopy(_protocol(tmp_path))
    packet[0]["result"]["identity"][field] = not packet[0]["result"]["identity"][field]
    with pytest.raises(RuntimeOracleError):
        _validate(tmp_path, packet)


def test_complete_outer_result_extra_fields_are_not_discarded(tmp_path):
    packet = deepcopy(_protocol(tmp_path))
    del packet[0]["result"]["result"]["sanitized"]["extra"]
    with pytest.raises(RuntimeOracleError):
        _validate(tmp_path, packet)


@pytest.mark.parametrize("mutation", ("ambient", "wrong_script", "failed_exit", "fake_parent", "unknown_child", "missing_owner", "overlap"))
def test_actual_process_authority_and_lifetimes_are_bound(tmp_path, mutation):
    packet = deepcopy(_protocol(tmp_path))
    child, kwargs = packet[2][0]["child"], packet[3]
    if mutation == "ambient":
        child["environmentKeys"] = [*ENVIRONMENT_KEYS, "OPENAI_API_KEY"]
    elif mutation == "wrong_script":
        child["argv"][1] = "/fake.mjs"
    elif mutation == "failed_exit":
        child["exit"]["code"] = 1
    elif mutation == "fake_parent":
        kwargs["process_parents"][102] = 103
    elif mutation == "unknown_child":
        kwargs["bootstrap"].append({"pid": 103, "isMainThread": True, "runtime": packet[2][0]["runtime"]})
    elif mutation == "missing_owner":
        kwargs["release_by_pid"][102].remove(next(iter(REQUIRED_HELPER_ARTIFACTS)))
    else:
        child["finishedAtNs"] = "0"
    with pytest.raises(RuntimeOracleError):
        _validate(tmp_path, packet)


@pytest.mark.parametrize("snapshot", ({"revision": 1, "values": []}, {"revision": 0, "values": ["ambient-credential"]}))
def test_registry_is_fresh_without_test_resets_or_revision_offsets(snapshot):
    with pytest.raises(RuntimeOracleError):
        _registry_journal([{"stage": "initial", "snapshot": snapshot}, {"stage": "final", "snapshot": snapshot}],
                          [("initial", None), ("final", None)])


def test_compiled_profile_rejects_forged_private_full_context_mark():
    with pytest.raises(RuntimeOracleError):
        _policy({"patterns": [], "fullContext": True, "registryRevision": 0}, {})


@pytest.mark.parametrize("markers", ([], [{"index": 0, "type": "text", "prepared": "true", "text": "actual"}],
                                     [{"index": 0, "type": "text", "prepared": True, "text": "replacement"}]))
def test_original_prepared_marker_vector_retains_boolean_identity_and_text(markers):
    with pytest.raises(RuntimeOracleError):
        _markers(markers, {"content": [{"type": "text", "text": "actual"}]})


def test_raw_sql_cannot_be_replaced_with_an_empty_descriptor():
    with pytest.raises(RuntimeOracleError):
        _sql({}, [], "session")


def test_approved_node_authority_has_no_unreviewed_extra_capability():
    with pytest.raises(ValueError):
        validate_model_node_authority({"execPath": "/approved/node", **APPROVED_NODE_RUNTIME, "VITEST": "1"})


def test_fatal_diagnostics_keep_original_non_enumerable_nested_causes_and_stacks():
    node = Path("/workspace/openclaw-memory-bridge/node_modules/node/bin/node")
    if not node.is_file():
        pytest.skip("The exact reviewed Node executable is unavailable for this transport-only check")
    script = """import {modelError} from './equivalence/model-runtime-observation.mjs';
const cause = new Error('literal inner cause');
Object.defineProperty(cause,'code',{value:'ORIGINAL_CODE',enumerable:false});
const error = new Error('literal outer failure',{cause});
process.stdout.write(JSON.stringify({...modelError(error),aggregate:modelError(new AggregateError([cause],'literal aggregate'))}));"""
    process = subprocess.run([str(node), "--input-type=module", "--eval", script], cwd=ROOT,
                             check=True, capture_output=True, text=True, env={"LANG": "C.UTF-8", "TZ": "UTC"})
    value = json.loads(process.stdout)
    assert value["message"] == "literal outer failure"
    assert value["cause"]["message"] == "literal inner cause"
    assert value["cause"]["code"] == "ORIGINAL_CODE"
    assert value["stack"].startswith("Error: literal outer failure")
    assert value["cause"]["stack"].startswith("Error: literal inner cause")
    assert isinstance(value["aggregate"]["errors"], list)
    assert value["aggregate"]["errors"][0]["code"] == "ORIGINAL_CODE"


def test_original_stream_bytes_survive_every_forced_utf8_chunk_boundary():
    node = Path("/workspace/openclaw-memory-bridge/node_modules/node/bin/node")
    if not node.is_file():
        pytest.skip("The reviewed Node executable is unavailable for this transport check")
    script = """import {PassThrough} from 'node:stream';
import {observeModelChildStreams} from './equivalence/model-runtime-observation.mjs';
const text='prefix 😀𐐀 İ é suffix'; const bytes=Buffer.from(text);
for(let cut=1;cut<bytes.length;cut++){
  const child={stdout:new PassThrough(),stderr:new PassThrough()};
  const read=observeModelChildStreams(child);
  for(const stream of [child.stdout,child.stderr]){
    stream.write(bytes.subarray(0,cut));stream.end(bytes.subarray(cut));
  }
  const observed=read();if(observed.stdout!==text||observed.stderr!==text)throw Error('lost original UTF-8 bytes');
}
process.stdout.write(JSON.stringify({cuts:bytes.length-1,exact:true}));"""
    process = subprocess.run([str(node), "--input-type=module", "--eval", script], cwd=ROOT,
                             check=True, capture_output=True, text=True, env={"LANG": "C.UTF-8", "TZ": "UTC"})
    assert json.loads(process.stdout)["exact"] is True


def _session_protocol(tmp_path):
    """Labelled transport facts, never an upstream behavioral oracle."""
    base = str(tmp_path / "native-model-session-fixture")
    runtime = {"execPath": "/approved/node", **APPROVED_NODE_RUNTIME}
    identity = {"nowMs": 1000, "agentId": "main", "sessionId": "fixture", "sessionKey": "agent:main:dm:fixture"}
    config_input = {"systemPrompt": "literal fixture", "model": {"id": "literal", "provider": "fixture", "api": "fixture"}}
    phases = [{"label": name, **({"prompt": "literal", "responses": [{}]} if name != "verify" else {})}
              for name in ("write", "continue", "verify")]
    value = {"kind": "model-session", **identity, **config_input, "phases": phases}
    logging = {"level": "silent", "consoleLevel": "silent", "file": base + "/native.log"}
    cfg = {"agents": {"defaults": {"workspace": base + "/workspace"}}, "logging": logging,
           "session": {"maintenance": {"mode": "warn"}}}
    scope = {**{key: identity[key] for key in ("agentId", "sessionId", "sessionKey")},
             "storePath": base + "/state/agents/main/sessions/sessions.json"}
    coordinator = {"kind": "model-session", "fixtureBase": base, "coordinatorPid": 101, "input": value, "runtime": runtime, "phases": []}
    row = {"id": "session", "ok": True, "result": {"provider": "none", "phases": []}}
    kwargs = {"runtime_root": "/original/runtime", "bootstrap": [{"pid": 101, "isMainThread": True, "runtime": runtime}],
              "release_by_pid": {}, "local_by_pid": {101: {str(ROOT / "equivalence" / name) for name in (
                  "release-oracle.mjs", "model-session-runtime.mjs", "model-runtime-observation.mjs")}},
              "process_parents": {}, "worker_imports": []}
    for index, phase in enumerate(phases):
        label, pid = phase["label"], 102 + index
        request = {"input": {**identity, **(config_input if label != "verify" else {})}, "phase": phase,
                   "directory": base, "runtimeRoot": "/original/runtime"}
        schemas = {name: {"columns": [{"name": "labelled_column"}], "rows": []} for name in SQL_TABLES}
        context = {"messages": [], "model": None, "thinkingLevel": "off"}
        observed = {"phase": label, "pid": pid, "ppid": 101, "request": request, "runtime": runtime,
            "configBytes": json.dumps(cfg), "config": cfg, "clock": {"owner": "node:test", "apis": ["Date"], "nowMs": 1000,
                "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
            "registry": [{"stage": stage, "snapshot": {"revision": 0, "values": []}} for stage in
                         (["initial", "final"] if label == "verify" else ["initial", "provider-fixture-auth", "final"])],
            "stages": [], "events": [], "contexts": [], "executions": [], "persisted": [], "applicationWrites": [],
            "scope": scope, "before": [], "after": [], "entries": [], "currentEntry": {}, "context": context, "modelMessages": [],
            "databasePath": base + "/state/agents/main/agent/openclaw-agent.sqlite", "sessionSqlBefore": schemas, "sessionSqlAfter": schemas}
        if label == "write":
            observed["applicationWrites"] = [{"target": scope, "entry": {"sessionId": "fixture", "updatedAt": 1000}, "returnedUndefined": True}]
        if label != "verify":
            workspace = base + "/workspace"
            observed.update(guardRequest={"config": cfg, "onMessagePersisted": True},
                providerRegistration={"provider": "fixture", "api": "fixture", "streamSimple": True},
                createRequest={"cwd": workspace, "agentDir": workspace, "model": config_input["model"],
                    "settingsInput": {"compaction": {"enabled": False}, "retry": {"enabled": False}},
                    "loaderInput": {"cwd": workspace, "agentDir": workspace, "noExtensions": True, "noSkills": True,
                        "noPromptTemplates": True, "noThemes": True, "noContextFiles": True, "systemPrompt": config_input["systemPrompt"]},
                    "noTools": "builtin", "customTools": [{"name": "lookup", "label": "Lookup", "description": "Return a declared synthetic fixture result.",
                        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}]},
                prompt="literal", responsesConsumed=1, activeToolNames=["lookup"],
                contexts=[{"model": config_input["model"], "context": {"messages": []}, "options": {}}])
        result = {"phase": label, "providerMessages": [[]] if label != "verify" else [], "toolExecutions": [],
                  "persistedMessages": [], "storedMessages": [], "modelContext": context, "modelMessages": []}
        request_json = json.dumps(request)
        coordinator["phases"].append({"label": label, "pid": pid, "request": request, "requestJson": request_json,
            "requestSha256": hashlib.sha256(request_json.encode()).hexdigest(),
            "argv": [runtime["execPath"], str(ROOT / "equivalence/model-session-phase-cli.mjs")], "environmentKeys": ENVIRONMENT_KEYS,
            "startedAtNs": str(1 + index * 2), "finishedAtNs": str(2 + index * 2), "exit": {"code": 0, "signal": None},
            "stdout": json.dumps({"result": result, "raw": observed}), "stderr": "", "raw": observed})
        row["result"]["phases"].append(result)
        kwargs["bootstrap"].append({"pid": pid, "isMainThread": True, "runtime": runtime})
        kwargs["process_parents"][pid] = 101
        kwargs["release_by_pid"][pid] = set(REQUIRED_SESSION_READ_ARTIFACTS) | (set(REQUIRED_SESSION_WRITE_ARTIFACTS) if label != "verify" else set())
        kwargs["local_by_pid"][pid] = {str(ROOT / "equivalence" / name) for name in (
            "model-session-phase-cli.mjs", "model-session-phase.mjs", "model-runtime-observation.mjs")}
    return row, {"input": value}, [coordinator], kwargs


def _validate_session(tmp_path, packet):
    row, case, diagnostic, kwargs = packet
    validate_model_session_raw(row, case, diagnostic, tmp_path, **kwargs)


def test_labelled_three_process_transport_is_bound_without_a_context_algorithm_copy(tmp_path):
    _validate_session(tmp_path, _session_protocol(tmp_path))


@pytest.mark.parametrize("mutation", ("forwarded_history", "verify_secret", "same_pid", "overlap", "missing_sql", "missing_context",
                                     "verify_append", "fake_scope", "omitted_write_owner", "changed_public_context"))
def test_fresh_session_authority_and_complete_persisted_context_cannot_be_forged(tmp_path, mutation):
    packet = deepcopy(_session_protocol(tmp_path))
    records = packet[2][0]["phases"]
    if mutation == "forwarded_history":
        records[1]["request"]["input"]["history"] = ["fabricated"]
    elif mutation == "verify_secret":
        records[2]["request"]["input"]["registeredSecrets"] = ["fixture-secret"]
    elif mutation == "same_pid":
        records[1]["pid"] = records[0]["pid"]
    elif mutation == "overlap":
        records[1]["startedAtNs"] = "1"
    elif mutation == "missing_sql":
        del records[2]["raw"]["sessionSqlAfter"]
    elif mutation == "missing_context":
        del records[1]["raw"]["context"]
    elif mutation == "verify_append":
        records[2]["raw"]["persisted"] = [{"role": "assistant", "content": "fake"}]
    elif mutation == "fake_scope":
        records[0]["raw"]["scope"]["sessionId"] = "different"
    elif mutation == "omitted_write_owner":
        packet[3]["release_by_pid"][102].remove(next(iter(REQUIRED_SESSION_WRITE_ARTIFACTS)))
    else:
        packet[0]["result"]["phases"][2]["modelContext"] = {"messages": ["replacement"]}
    with pytest.raises(RuntimeOracleError):
        _validate_session(tmp_path, packet)
