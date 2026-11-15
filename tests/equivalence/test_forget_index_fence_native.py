"""Labelled Python protocol fixtures only: no Node or original engine executes."""
from copy import deepcopy
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zlib
from types import SimpleNamespace

import pytest

from equivalence import forget_index_fence_native as native
from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME


def _wire(case):
    return json.dumps({key: case[key] for key in ("id", "operation", "input")},
                      sort_keys=True, separators=(",", ":")).encode()


def _stored_event(row):
    """Labelled protocol bytes only; no engine output or expected API value."""
    raw = json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode()
    compressor = zlib.compressobj(wbits=-15)
    data = compressor.compress(raw) + compressor.flush()
    return json.dumps({"codec": native.PASSIVE_EVENT_CODEC, "rawBytes": len(raw),
                       "rawSha256": hashlib.sha256(raw).hexdigest(),
                       "dataBase64": base64.b64encode(data).decode()}) + "\n"


@pytest.fixture
def closed(monkeypatch):
    case = {"id": "labelled-no-engine-protocol", "operation": "forget-index-fence-v3-runtime",
            "input": {"clock": {"nowMs": 1794614400000, "sourceWriteClock": {
                "protocol": "owned-source-write-clock-v2", "ticksByCall": {"sync:s": {
                    "ordinal": 1, "actor": "foreground", "wallClockNowMs": 1794614400000,
                    "atimeMs": 1794528001000, "mtimeMs": 1794528001000}},
                "scope": "Labelled protocol only; no original source or engine executes",
                "boundaries": {"atomic": "before original rename", "inPlace": "before original close"}}},
                      "actors": {"foreground": {"role": "fixture"}},
                      "gates": [], "steps": [{"operation": "original-sync", "actor": "foreground", "label": "s"}]}}
    case["input"]["kind"] = "forget-index-fence-v3"
    case["input"]["observationPolicy"] = {"searchEffects": {
        "protocol": "original-search-effects-v3", "maxReferencesPerBarrier": 256}}
    recovery = deepcopy(case)
    recovery["id"] = "labelled-no-engine-recovery-protocol"
    recovery["input"]["clock"]["recoveryNowMs"] = case["input"]["clock"]["nowMs"] + 60000
    cases = [case, recovery]
    hashes = {item["id"]: hashlib.sha256(_wire(item)).hexdigest() for item in cases}

    def validate(value):
        if value not in cases:
            raise ValueError("Labelled input differs from the frozen protocol fixture")
        return deepcopy(value)

    contract = SimpleNamespace(build_cases=lambda: deepcopy(cases), validate_case=validate,
                               case_wire=_wire, CASE_HASHES=hashes)
    monkeypatch.setattr(native, "_contract", lambda *_args: contract)
    authority = {"execPath": "/labelled/no-engine/node", **APPROVED_NODE_RUNTIME}
    return case, recovery, authority


def test_profile_binds_every_actor_gate_and_declared_clock_without_running_node(closed):
    case, recovery, authority = closed
    profile = native.prepare_profile(case, authority)
    assert profile["actorClocks"] == {"coordinator": 1794614400000, "observer": 1794614400000,
                                      "foreground": 1794614400000}
    assert profile["acceptancePointsAwarded"] == 0
    assert profile["caseWireSha256"] == hashlib.sha256(_wire(case)).hexdigest()
    assert profile["sourceWriteClock"] == case["input"]["clock"]["sourceWriteClock"]
    assert profile["sourceWriteClock"] is not case["input"]["clock"]["sourceWriteClock"]
    assert profile["sourceWriteClock"]["ticksByCall"] is not case["input"]["clock"]["sourceWriteClock"]["ticksByCall"]
    assert native.validate_profile(profile) == profile
    recovered = native.prepare_profile(recovery, authority)
    assert recovered["recoveryNowMs"] == 1794614460000
    assert "recoveryNowMs" not in profile


@pytest.mark.parametrize("attack", ["kind", "operation", "v1-kind", "v1-operation", "case", "wire", "actor", "clock", "source-clock", "missing-source-clock", "source-clock-extra", "source-clock-bool", "search-effects", "missing-search-effects", "gates", "credit", "credit-bool", "extra", "node"])
def test_profile_rejects_borrowed_or_widened_capabilities(closed, attack):
    case, _, authority = closed
    profile = native.prepare_profile(case, authority)
    if attack == "kind":
        profile["kind"] = "query-sync-cold-retry"
    elif attack == "operation":
        profile["operation"] = "query-sync-cold-retry-runtime"
    elif attack == "v1-kind":
        profile["kind"] = "forget-index-fence"
    elif attack == "v1-operation":
        profile["operation"] = "forget-index-fence-runtime"
    elif attack == "case":
        profile["caseId"] = "unapproved"
    elif attack == "wire":
        profile["caseWireSha256"] = "0" * 64
    elif attack == "actor":
        profile["actorClocks"]["borrowed"] = profile["actorClocks"]["coordinator"]
    elif attack == "clock":
        profile["actorClocks"]["foreground"] += 1
    elif attack == "source-clock":
        profile["sourceWriteClock"]["ticksByCall"]["sync:s"]["mtimeMs"] += 1000
    elif attack == "missing-source-clock":
        del profile["sourceWriteClock"]
    elif attack == "source-clock-extra":
        profile["sourceWriteClock"]["privateWriteOrdinalFallback"] = True
    elif attack == "source-clock-bool":
        profile["sourceWriteClock"]["ticksByCall"]["sync:s"]["ordinal"] = True
    elif attack == "search-effects":
        profile["searchEffects"]["maxReferencesPerBarrier"] = True
    elif attack == "missing-search-effects":
        del profile["searchEffects"]
    elif attack == "gates":
        profile["gates"] = [{"name": "undeclared"}]
    elif attack == "credit":
        profile["acceptancePointsAwarded"] = 1
    elif attack == "credit-bool":
        profile["acceptancePointsAwarded"] = False
    elif attack == "extra":
        profile["workerReplacement"] = True
    else:
        profile["nodeRuntime"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        native.validate_profile(profile)


def test_transport_contract_import_is_v3_only_without_a_v1_fallback(monkeypatch):
    calls = []
    sentinel = object()
    monkeypatch.setattr(native, "import_module", lambda name: calls.append(name) or sentinel)
    assert native._contract() is sentinel
    assert calls == ["equivalence.forget_index_fence_v3"]
    assert native.PROFILE_KEY == "forgetIndexFenceV3Profile"
    assert native.BOOTSTRAP_EVENT == "forget-index-fence-v3-bootstrap"
    assert native.PROFILE_KIND == "forget-index-fence-v3"
    assert native.NATIVE_KIND == "official-release-forget-index-fence-v3"


def test_additive_v4_dispatch_is_closed_and_retains_v3_control_protocol(monkeypatch):
    calls = []
    monkeypatch.setattr(native, "import_module", lambda name: calls.append(name) or name)
    assert native._contract("forget-index-fence-v3-runtime") == "equivalence.forget_index_fence_v3"
    assert native._contract("forget-index-fence-v4-runtime") == "equivalence.forget_index_fence_v4"
    assert native._contract("forget-index-fence-v5-runtime") == "equivalence.forget_index_fence_v5"
    assert native._contract("forget-index-fence-v6-runtime") == "equivalence.forget_index_fence_v6"
    with pytest.raises(ValueError, match="Unknown"):
        native._contract("forget-index-fence-v7-runtime")
    assert len(calls) == 4
    assert native.PROFILE_KEY == "forgetIndexFenceV3Profile"
    assert native.BOOTSTRAP_EVENT == "forget-index-fence-v3-bootstrap"


def test_mixed_literal_kind_is_rejected_before_contract_import(closed, monkeypatch):
    case, _, _ = closed
    case = deepcopy(case)
    case["input"]["kind"] = "forget-index-fence-v4"
    monkeypatch.setattr(native, "_contract", lambda *_args: pytest.fail("A mixed version imported its contract"))
    with pytest.raises(ValueError, match="mixed or unknown"):
        native._validated_case(case)


def test_profile_copies_the_entire_literal_source_clock_without_shared_nested_values(closed):
    case, _, authority = closed
    original = deepcopy(case)
    profile = native.prepare_profile(case, authority)
    profile["sourceWriteClock"]["boundaries"]["atomic"] = "changed control"
    profile["sourceWriteClock"]["ticksByCall"]["sync:s"]["atimeMs"] += 1
    assert case == original


def test_v5_closed_profiles_bind_whole_watcher_policy_without_original_execution():
    from equivalence.forget_index_fence_v5 import build_cases

    authority = {"execPath": "/labelled/no-engine/node", **APPROVED_NODE_RUNTIME}
    for case in build_cases():
        profile = native.prepare_profile(case, authority)
        assert profile["watchEffects"] == case["input"]["observationPolicy"]["watchEffects"]
        assert profile["watchEffects"] is not case["input"]["observationPolicy"]["watchEffects"]
        assert native.validate_profile(profile) == profile
        profile["watchEffects"]["maxReferencesPerBarrier"] = True
        with pytest.raises(ValueError, match="differs"):
            native.validate_profile(profile)


def test_sealed_v3_family_has_exact_literal_clock_profiles_without_original_execution():
    from equivalence import forget_index_fence_v3 as contract

    authority = {"execPath": "/labelled/no-engine/node", **APPROVED_NODE_RUNTIME}
    cases = contract.build_cases()
    assert len(cases) == 13
    for case in cases:
        profile = native.prepare_profile(case, authority)
        assert profile["searchEffects"] == case["input"]["observationPolicy"]["searchEffects"]
        assert profile["searchEffects"] is not case["input"]["observationPolicy"]["searchEffects"]
        assert profile["sourceWriteClock"] == case["input"]["clock"]["sourceWriteClock"]
        assert native.validate_profile(profile) == profile


def test_sealed_v4_profiles_keep_whole_policy_and_v3_diagnostics_without_running_node():
    from equivalence import forget_index_fence_v3 as v3, forget_index_fence_v4 as v4
    authority = {"execPath": "/labelled/no-engine/node", **APPROVED_NODE_RUNTIME}
    for contract in (v3, v4):
        for case in contract.build_cases():
            profile = native.prepare_profile(case, authority)
            assert profile["kind"] == case["input"]["kind"]
            assert profile["operation"] == case["operation"]
            assert profile["caseId"] == case["id"]
            assert profile["searchEffects"] == case["input"]["observationPolicy"]["searchEffects"]
            assert native.validate_profile(profile) == profile


def test_changed_input_is_denied_before_executable_authentication_or_process_launch(closed, monkeypatch, tmp_path):
    case, _, _ = closed
    changed = deepcopy(case)
    changed["input"]["gates"] = [{"name": "unapproved"}]
    calls = []
    monkeypatch.setattr(native, "prepare_model_node_authority", lambda *_: calls.append("node"))
    monkeypatch.setattr(native.subprocess, "Popen", lambda *_a, **_k: calls.append("process"))
    with pytest.raises(ValueError, match="frozen protocol"):
        native.run_native_case(changed, tmp_path / "absent-node", {}, tmp_path / "attempt")
    assert calls == []
    assert not (tmp_path / "attempt").exists()


def _seal(value):
    wire = json.dumps(value, separators=(",", ":"))
    return {"serializedJSON": wire, "sha256": hashlib.sha256(wire.encode()).hexdigest()}


@pytest.fixture
def labelled_trace(closed, monkeypatch, tmp_path):
    """Synthetic custody protocol, explicitly not a genuine original capture."""
    case, _, authority = closed
    for name in ("traces", "state", "evidence", "gates"):
        (tmp_path / name).mkdir()
    profile = native.prepare_profile(case, authority)
    runtime = {"runtimeRoot": "/labelled/no-engine/release", "packages": [
        {"location": "node_modules/openclaw", "files": [
            {"path": "dist/labelled-main.mjs", "sha256": "1" * 64},
            {"path": "dist/labelled-worker.mjs", "sha256": "2" * 64},
        ]},
    ]}
    context = {"schemaVersion": 1, "kind": "release-oracle-execution", "runtime": runtime,
               "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
               native.PROFILE_KEY: profile, "allowedLocal": native._local_authority(),
               "traceDirectory": str(tmp_path / "traces"), "evidenceDirectory": str(tmp_path / "evidence"),
               "stateDirectory": str(tmp_path / "state"), "configPath": str(tmp_path / "state/openclaw.json"),
               "gateDirectory": str(tmp_path / "gates"), "approvedReferenceSources": [], "fixtureSourceCaptures": [],
               "_sha256": "a" * 64}
    request = {"kind": "forget-index-fence-child", "actor": "foreground", "instance": 1,
               "caseId": case["id"], "input": case["input"], "runtimeRoot": runtime["runtimeRoot"],
               "fixtureBase": context["stateDirectory"], "configPath": context["configPath"],
               "evidenceDirectory": context["evidenceDirectory"]}
    command = {"id": 1, "operation": "original-sync", "label": "s", "wallClockNowMs": case["input"]["clock"]["nowMs"]}
    raw = {"schemaVersion": 1, "kind": "forget-index-fence-native-capture", "engine": "native",
           "caseId": case["id"], "input": case["input"], "fixtureBase": context["stateDirectory"],
           "pid": 101, "ppid": 99, "result": {"labelledProtocolOnly": True}, "completed": True,
           "allChildrenReaped": True, "gates": [], "snapshots": [],
           "steps": [{"step": case["input"]["steps"][0], "startedAtNs": "100", "finishedAtNs": "500"}],
           "children": [{"actor": "foreground", "instance": 1, "pid": 102, "ppid": 101,
                         "argv": [authority["execPath"], str(native.ROOT / "equivalence" / native.ENTRY)],
                         "request": request, "requestSeal": _seal(request),
                         "ready": {"type": "ready", "actor": "foreground", "instance": 1, "pid": 102, "ppid": 101},
                         "startedAtNs": "150", "finishedAtNs": "600", "reapedAtNs": "700",
                         "stdout": "", "stderr": "", "exit": {"code": 0, "signal": None},
                         "commands": [{"id": 1, "operation": "original-sync", "label": "s", "request": command,
                                       "requestSeal": _seal(command), "startedAtNs": "200"}]}]}
    monkeypatch.setattr(native, "_ALWAYS_MAIN_ARTIFACTS", ())
    monkeypatch.setattr(native, "REQUIRED_MAIN_ARTIFACTS_BY_ROUTE", {"manager": ("dist/labelled-main.mjs",)})
    monkeypatch.setattr(native, "REQUIRED_WORKER_ARTIFACTS_BY_ROUTE", {
        "preparation": ("dist/labelled-worker.mjs",), "publication": ("dist/labelled-worker.mjs",),
        "state": ("dist/labelled-worker.mjs",),
    })
    # This fixture intentionally supplies no release byte/execution authority.
    # Real runs use the unchanged independent release validator.
    monkeypatch.setattr(native, "validate_release_sources", lambda *_a, **_k: None)
    locals_ = {item["path"]: item["sha256"] for item in context["allowedLocal"]}
    files = {}
    for pid, ppid, actor, thread in ((101, 99, "coordinator", 0), (102, 101, "foreground", 0), (102, 101, "foreground", 7)):
        identity = {"pid": pid, "ppid": ppid, "actor": actor, "threadId": thread,
                    "instance": 0 if pid == 101 else 1}
        rows = [{"event": "bootstrap", **identity, "isMainThread": thread == 0, "runtime": authority,
                 "contextSha256": context["_sha256"], "preloadSha256": locals_[str(native.ROOT / "equivalence" / native.PRELOAD)],
                 "fetchDenied": True, "providerMode": "none"},
                {"event": native.BOOTSTRAP_EVENT, **identity, "profile": profile,
                 "clock": {"owner": "node:test", "apis": ["Date"], "nowMs": profile["actorClocks"][actor],
                           "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True}}]
        if thread == 0:
            rows.extend({"event": "load", **identity, "kind": "oracle", "path": str(native.ROOT / "equivalence" / name),
                         "sha256": locals_[str(native.ROOT / "equivalence" / name)]} for name in (native.ENTRY, native.ACTOR))
        rows.append({"event": "load", **identity, "kind": "oracle",
                     "path": str(native.ROOT / "equivalence" / native.SOURCE_CLOCK),
                     "sha256": locals_[str(native.ROOT / "equivalence" / native.SOURCE_CLOCK)]})
        if pid == 102:
            rows.append({"event": "load", **identity, "kind": "release", "package": "node_modules/openclaw",
                         "path": "dist/labelled-main.mjs" if thread == 0 else "dist/labelled-worker.mjs",
                         "sha256": ("1" if thread == 0 else "2") * 64})
        files[f"{pid}-{thread}.jsonl"] = rows
    return {"case": case, "context": context, "runtime": runtime, "authority": authority,
            "raw": raw, "files": files, "directory": tmp_path / "traces"}


def _validate(labelled):
    for name, rows in labelled["files"].items():
        (labelled["directory"] / name).write_text("".join(json.dumps(row) + "\n" for row in rows))
    raw = labelled["raw"]
    native.validate_raw([raw], labelled["case"], raw["result"], labelled["context"], process_pid=101, parent_pid=99)
    return native.validate_traces(labelled["directory"], labelled["context"], labelled["runtime"], labelled["authority"],
                                  process_pid=101, parent_pid=99, raw=raw)


def test_labelled_multiprocess_protocol_keeps_separate_mains_and_worker_roles(labelled_trace):
    trace = _validate(labelled_trace)
    assert {(row["pid"], row["threadId"]) for row in trace["bootstraps"]} == {(101, 0), (102, 0), (102, 7)}
    assert len(trace["loaded"]) == 2


@pytest.mark.parametrize("stream", ["101-0.jsonl", "102-0.jsonl", "102-7.jsonl"])
@pytest.mark.parametrize("attack", ["missing", "changed-hash", "resolved-only"])
def test_every_process_and_worker_requires_its_actual_fourth_local_module_load(labelled_trace, stream, attack):
    value = labelled_trace
    source_clock = str(native.ROOT / "equivalence" / native.SOURCE_CLOCK)
    rows = value["files"][stream]
    clock_row = next(row for row in rows if row.get("path") == source_clock)
    if attack == "missing":
        rows.remove(clock_row)
    elif attack == "changed-hash":
        clock_row["sha256"] = "0" * 64
    else:
        clock_row["event"] = "resolve-native"
    with pytest.raises(ValueError):
        _validate(value)


def test_trace_context_does_not_accept_the_v1_profile_key(labelled_trace):
    value = labelled_trace
    value["context"]["forgetIndexFenceProfile"] = value["context"].pop(native.PROFILE_KEY)
    with pytest.raises(ValueError):
        native.validate_traces(value["directory"], value["context"], value["runtime"], value["authority"],
                               process_pid=101, parent_pid=99, raw=value["raw"])


@pytest.mark.parametrize("attack", ["ppid", "actor", "clock", "worker-context", "missing-worker", "release-hash", "unknown-event", "child-pid", "child-request", "child-seal", "not-reaped", "step", "result", "incomplete", "gate", "coordinator-instance", "main-instance", "worker-instance", "event-instance", "boolean-instance"])
def test_labelled_trace_rejects_detached_process_worker_source_and_reap_custody(labelled_trace, attack):
    value = labelled_trace
    raw = value["raw"]
    if attack == "ppid":
        value["files"]["102-0.jsonl"][0]["ppid"] = 88
    elif attack == "coordinator-instance":
        value["files"]["101-0.jsonl"][0]["instance"] = 1
    elif attack == "main-instance":
        value["files"]["102-0.jsonl"][0]["instance"] = 2
    elif attack == "worker-instance":
        value["files"]["102-7.jsonl"][0]["instance"] = 2
    elif attack == "event-instance":
        value["files"]["102-7.jsonl"][-1]["instance"] = 2
    elif attack == "boolean-instance":
        value["files"]["102-7.jsonl"][0]["instance"] = True
    elif attack == "actor":
        value["files"]["102-7.jsonl"][0]["actor"] = "coordinator"
    elif attack == "clock":
        value["files"]["102-7.jsonl"][1]["clock"]["nowMs"] += 1
    elif attack == "worker-context":
        value["files"]["102-7.jsonl"][0]["contextSha256"] = "0" * 64
    elif attack == "missing-worker":
        value["files"].pop("102-7.jsonl")
    elif attack == "release-hash":
        value["files"]["102-7.jsonl"][-1]["sha256"] = "0" * 64
    elif attack == "unknown-event":
        row = deepcopy(value["files"]["102-7.jsonl"][-1])
        row["event"] = "substituted-result"
        value["files"]["102-7.jsonl"].append(row)
    elif attack == "child-pid":
        raw["children"][0]["pid"] = 101
    elif attack == "child-request":
        raw["children"][0]["request"]["caseId"] = "borrowed"
    elif attack == "child-seal":
        raw["children"][0]["requestSeal"]["sha256"] = "0" * 64
    elif attack == "not-reaped":
        raw["children"][0].pop("reapedAtNs")
    elif attack == "step":
        raw["steps"] = []
    elif attack == "result":
        raw["completed"] = False
    elif attack == "incomplete":
        raw["allChildrenReaped"] = False
    else:
        row = deepcopy(value["files"]["102-7.jsonl"][-1])
        row.update(event="fence-gate-enter", name="unowned-gate")
        value["files"]["102-7.jsonl"].append(row)
    with pytest.raises(ValueError):
        _validate(value)


def _launch_stub(closed, monkeypatch, tmp_path, *, timeout=False):
    case, _, authority = closed
    node = tmp_path / "labelled-node"
    node.write_text("Labelled protocol executable: never executed\n")
    authority = {**authority, "execPath": str(node)}
    calls = []
    monkeypatch.setattr(native, "prepare_model_node_authority", lambda *_: (calls.append("authority") or deepcopy(authority)))
    monkeypatch.setattr(native, "prepare_forget_index_fence_bindings", lambda *_: {"kind": "labelled-nonexecuting-declarations"})
    killed = []
    monkeypatch.setattr(native.os, "killpg", lambda pid, signal: killed.append((pid, signal)))

    class NoEngineProcess:
        pid = 321
        returncode = None

        def __init__(self, argv, **options):
            self.options = options
            self.count = 0
            calls.append((argv, options))
            options["stdout"].write(json.dumps({"id": case["id"], "ok": False, "error": {"message": "labelled failure"}}).encode())
            options["stderr"].write(b"labelled original-stream slot; no engine executed\n")

        def communicate(self, wire=None, *, timeout=None):
            self.count += 1
            if self.count == 1 and globals_timeout:
                raise subprocess.TimeoutExpired("labelled-protocol-only", timeout)
            self.returncode = -9 if globals_timeout else 2
            return None, None

    globals_timeout = timeout
    monkeypatch.setattr(native.subprocess, "Popen", NoEngineProcess)
    return case, node, calls, killed


@pytest.mark.parametrize("timeout", [False, True])
def test_launcher_retains_complete_failure_and_rechecks_bytes_without_retry(closed, monkeypatch, tmp_path, timeout):
    case, node, calls, killed = _launch_stub(closed, monkeypatch, tmp_path, timeout=timeout)
    attempt = tmp_path / "attempt"
    with pytest.raises(ValueError, match="retained without retry"):
        native.run_native_case(case, node, {"runtimeRoot": str(tmp_path), "packages": []}, attempt,
                               checkout=tmp_path, timeout=1)
    record = json.loads((attempt / "process.json").read_text())
    context = json.loads((attempt / "context.json").read_text())
    assert record["pid"] == 321 and record["parentPid"] == os.getpid()
    assert record["protectedBytesUnchanged"] is True and record["retryAllowed"] is False
    assert record["returncode"] == (-9 if timeout else 2)
    assert (attempt / "stdout.json").read_bytes() and (attempt / "stderr.log").read_bytes()
    assert (attempt / "request.json").read_bytes() == _wire(case)
    assert set(context) == native._CONTEXT_KEYS
    assert context["configPath"] == str(attempt / "state/openclaw.json")
    assert context["gateDirectory"] == str(attempt / "gates")
    assert record["environment"]["MEMORY_EQ_FIF_ACTOR"] == "coordinator"
    assert sum(isinstance(item, tuple) for item in calls) == 1
    assert calls.count("authority") == 2
    assert bool(killed) is timeout


def test_worker_accepts_only_declared_later_recovery_phase_while_main_startup_stays_exact(labelled_trace, closed):
    value = labelled_trace
    recovery = closed[1]
    profile = native.prepare_profile(recovery, value["authority"])
    value["case"] = recovery
    value["context"][native.PROFILE_KEY] = profile
    value["raw"].update(caseId=recovery["id"], input=recovery["input"])
    child = value["raw"]["children"][0]
    child["request"].update(caseId=recovery["id"], input=recovery["input"])
    child["requestSeal"] = _seal(child["request"])
    for rows in value["files"].values():
        rows[1]["profile"] = profile
    value["files"]["102-7.jsonl"][1]["clock"]["nowMs"] = profile["recoveryNowMs"]
    _validate(value)
    value["files"]["102-0.jsonl"][1]["clock"]["nowMs"] = profile["recoveryNowMs"]
    with pytest.raises(ValueError, match="declared Date-only"):
        _validate(value)


@pytest.fixture
def labelled_integrity_child(labelled_trace):
    """Source-qualified synthetic OS child: no process or original code runs."""
    value = labelled_trace
    context, authority = value["context"], value["authority"]
    runtime = value["runtime"]
    published = runtime["packages"][0]["files"]
    published.extend({"path": path, "sha256": digest}
                     for path, digest in native._INTEGRITY_ARTIFACT_HASHES.items())
    creator = {"pid": 102, "ppid": 101, "threadId": 7, "actor": "foreground", "instance": 1}
    entry = native._source_child_record(native._INTEGRITY_ENTRY, context)
    caller = native._source_child_record(native._INTEGRITY_CALLER, context)
    options = {"execArgv": [], "serialization": "advanced", "stdio": ["ignore", "ignore", "ignore", "ipc"],
               "timeout": {"privateType": "undefined"}, "killSignal": "SIGKILL"}
    launch = {"event": "original-child-spawn", **creator, "sequence": 1, "atNs": "210", "callLabel": "s",
              "launchId": "102:7:original-child-1", "method": "fork", "childPid": 103,
              "executable": authority["execPath"], "argv": [authority["execPath"], entry["absolutePath"]],
              "modulePath": entry["absolutePath"], "execArgv": [], "cwd": str(native.ROOT),
              "wallClockNowMs": context[native.PROFILE_KEY]["actorClocks"]["foreground"],
              "originalStack": f"Labelled protocol stack\n    at assertSqliteIntegrityWithProcess ({caller['absolutePath']}:172:17)",
              "sourceCaller": caller, "sourceEntrypoint": entry, "returnedChildRef": "labelled-process-ref-1",
              "request": {"originalArgs": {"v8Hex": "ff0f00"}, "options": {"v8Hex": "ff0f00"},
                          "argumentsJSON": [{"privateType": "URL", "href": Path(entry["absolutePath"]).as_uri()}, [], options],
                          "optionsJSON": options},
              "environment": {"MEMORY_EQ_RELEASE_CONTEXT": str(Path(context["traceDirectory"]).parent / "context.json"),
                              "MEMORY_EQ_FIF_ACTOR": "foreground", "MEMORY_EQ_FIF_INSTANCE": "1",
                              "MEMORY_EQ_FIF_CLOCK_NOW_MS": str(context[native.PROFILE_KEY]["actorClocks"]["foreground"]),
                              "NODE_OPTIONS": f'--import={native.ROOT / "equivalence" / native.PRELOAD}',
                              "OPENCLAW_STATE_DIR": context["stateDirectory"], "OPENCLAW_CONFIG_PATH": context["configPath"],
                              "HOME": context["stateDirectory"], "OPENCLAW_HOME": context["stateDirectory"]}}
    identity = {key: {"privateType": "bigint", "value": number}
                for key, number in (("dev", "1"), ("ino", "2"), ("size", "3"))}
    request = {"pathname": str(Path(context["stateDirectory"]) / "agents/main/agent.sqlite"),
               "databaseLabel": "Labelled no-engine check", "identity": identity, "busyTimeoutMs": 5000,
               "tables": {"privateType": "undefined"}, "reuse": True}
    rows = [launch]

    def message(direction, body, *, line=None):
        sequence = len(rows) + 1
        row = {"event": "original-child-message", **creator, "sequence": sequence, "atNs": str(210 + sequence),
               "callLabel": "s", "launchId": launch["launchId"], "childPid": 103,
               "direction": direction, "message": {"v8Hex": "ff0f00"}, "messageJSON": body}
        if line is not None:
            row["originalStack"] = f"Labelled source send\n at {caller['absolutePath']}:{line}:20"
        rows.append(row)

    message("parent-to-child", request, line=293)
    for phase in ("opening", "checking", "closing"):
        message("child-to-parent", {"type": "phase", "phase": phase})
    message("child-to-parent", {"ok": True, "checkElapsedMs": 0.5})
    message("parent-to-child", {"type": "close"}, line=73)
    for event in ("original-child-os-exit", "original-child-exit"):
        sequence = len(rows) + 1
        rows.append({"event": event, **creator, "sequence": sequence, "atNs": str(210 + sequence),
                     "callLabel": "s", "launchId": launch["launchId"], "childPid": 103,
                     "code": 0, "signal": None, "spawnSequence": launch["sequence"]})
    (Path(context["evidenceDirectory"]) / "102-7-events.jsonl").write_text(
        "".join(_stored_event(row) for row in rows))
    value["childReceiptRows"] = rows
    value["childReceiptFile"] = Path(context["evidenceDirectory"]) / "102-7-events.jsonl"
    value["files"]["102-7.jsonl"].append({"event": "load", **creator, "kind": "release",
                                           "package": caller["package"], "path": caller["path"], "sha256": caller["sha256"]})
    identity = {"pid": 103, "ppid": 102, "threadId": 0, "actor": "foreground", "instance": 1}
    local = {item["path"]: item["sha256"] for item in context["allowedLocal"]}
    value["files"]["103-0.jsonl"] = [
        {"event": "bootstrap", **identity, "isMainThread": True, "runtime": authority,
         "contextSha256": context["_sha256"], "preloadSha256": local[str(native.ROOT / "equivalence" / native.PRELOAD)],
         "fetchDenied": True, "providerMode": "none"},
        {"event": native.BOOTSTRAP_EVENT, **identity, "profile": context[native.PROFILE_KEY],
         "clock": {"owner": "node:test", "apis": ["Date"], "nowMs": launch["wallClockNowMs"],
                   "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True}},
        {"event": "load", **identity, "kind": "oracle", "path": str(native.ROOT / "equivalence" / native.SOURCE_CLOCK),
         "sha256": local[str(native.ROOT / "equivalence" / native.SOURCE_CLOCK)]},
        *[{"event": "load", **identity, "kind": "release", "package": "node_modules/openclaw", "path": path,
           "sha256": native._INTEGRITY_ARTIFACT_HASHES[path]} for path in native._INTEGRITY_CHILD_ARTIFACTS],
    ]
    return value


def _write_child_receipts(value):
    value["childReceiptFile"].write_text("".join(_stored_event(row) for row in value["childReceiptRows"]))


def test_original_integrity_child_requires_source_receipts_native_graph_and_real_close(labelled_integrity_child):
    value = labelled_integrity_child
    trace = _validate(value)
    children = trace["originalChildren"]
    assert len(children["processes"]) == 1
    assert children["processes"][0]["spawn"]["childPid"] == 103
    assert children["processes"][0]["checks"][0]["phases"] == ["opening", "checking", "closing"]
    assert children["receiptFiles"][0]["sha256"] == hashlib.sha256(value["childReceiptFile"].read_bytes()).hexdigest()
    assert {row["pid"] for row in trace["bootstraps"]} == {101, 102, 103}


@pytest.mark.parametrize("attack", ["no-receipts", "unknown-child", "unapproved-method", "unapproved-entry",
                                  "unapproved-caller", "changed-entry-hash", "changed-caller-hash", "wrong-call-site",
                                  "creator-thread", "executable", "argv", "environment", "clock", "fork-options",
                                  "fork-arguments", "v8-carrier", "message-path", "message-identity", "message-call-site",
                                  "phase-order", "phase-incomplete", "reply-before-request", "no-result", "no-close-request",
                                  "no-native-close", "nonzero-exit", "signalled-close", "close-before-message",
                                  "missing-native-entry", "missing-native-dependency", "missing-caller-import",
                                  "wrong-child-parent", "wrong-child-instance", "local-actor-import", "missing-source-clock"])
def test_unqualified_or_detached_original_os_children_fail_closed(labelled_integrity_child, attack):
    value = labelled_integrity_child
    rows, files = value["childReceiptRows"], value["files"]
    spawn = rows[0]
    if attack == "no-receipts":
        value["childReceiptFile"].unlink()
    elif attack == "unknown-child":
        rows[-1]["childPid"] = 104
    elif attack == "unapproved-method":
        spawn["method"] = "spawn"
    elif attack == "unapproved-entry":
        spawn["modulePath"] = "/unreviewed/child.js"
    elif attack == "unapproved-caller":
        spawn["sourceCaller"]["path"] = "dist/unreviewed.mjs"
    elif attack == "changed-entry-hash":
        spawn["sourceEntrypoint"]["sha256"] = "0" * 64
    elif attack == "changed-caller-hash":
        spawn["sourceCaller"]["sha256"] = "0" * 64
    elif attack == "wrong-call-site":
        spawn["originalStack"] = spawn["originalStack"].replace(":172:", ":173:")
    elif attack == "creator-thread":
        for row in rows:
            row["threadId"] = 8
        value["childReceiptFile"] = value["childReceiptFile"].with_name("102-8-events.jsonl")
    elif attack == "executable":
        spawn["executable"] = "/unapproved/node"
    elif attack == "argv":
        spawn["argv"].insert(1, "--eval=unexpected()")
    elif attack == "environment":
        spawn["environment"]["NODE_OPTIONS"] += " --import=/unapproved.mjs"
    elif attack == "clock":
        spawn["wallClockNowMs"] += 1
    elif attack == "fork-options":
        spawn["request"]["optionsJSON"]["serialization"] = "json"
    elif attack == "fork-arguments":
        spawn["request"]["argumentsJSON"][1] = ["undeclared"]
    elif attack == "v8-carrier":
        rows[1]["message"] = {"v8Hex": "not-v8-hex"}
    elif attack == "message-path":
        rows[1]["messageJSON"]["pathname"] = "/unowned/source.sqlite"
    elif attack == "message-identity":
        rows[1]["messageJSON"]["identity"]["ino"] = 2
    elif attack == "message-call-site":
        rows[1]["originalStack"] = rows[1]["originalStack"].replace(":293:", ":294:")
    elif attack == "phase-order":
        rows[2]["messageJSON"]["phase"] = "checking"
    elif attack == "phase-incomplete":
        rows[4]["messageJSON"]["phase"] = "checking"
    elif attack == "reply-before-request":
        rows[1]["direction"] = "child-to-parent"
    elif attack == "no-result":
        rows[5]["messageJSON"] = {"type": "phase", "phase": "closing"}
    elif attack == "no-close-request":
        rows.pop(6)
    elif attack == "no-native-close":
        rows.pop()
    elif attack == "nonzero-exit":
        rows[-1]["code"] = 1
    elif attack == "signalled-close":
        rows[-1]["signal"] = "SIGKILL"
    elif attack == "close-before-message":
        rows[-1]["sequence"] = 2
    elif attack == "missing-native-entry":
        files["103-0.jsonl"] = [row for row in files["103-0.jsonl"] if row.get("path") != native._INTEGRITY_ENTRY]
    elif attack == "missing-native-dependency":
        files["103-0.jsonl"] = [row for row in files["103-0.jsonl"] if row.get("path") != "dist/sqlite-integrity-CkZDPF4-.mjs"]
    elif attack == "missing-caller-import":
        files["102-7.jsonl"] = [row for row in files["102-7.jsonl"] if row.get("path") != native._INTEGRITY_CALLER]
    elif attack == "wrong-child-parent":
        files["103-0.jsonl"][0]["ppid"] = 101
    elif attack == "wrong-child-instance":
        files["103-0.jsonl"][0]["instance"] = 2
    elif attack == "missing-source-clock":
        files["103-0.jsonl"] = [row for row in files["103-0.jsonl"]
                                if row.get("path") != str(native.ROOT / "equivalence" / native.SOURCE_CLOCK)]
    else:
        files["103-0.jsonl"].append(deepcopy(files["102-0.jsonl"][2]))
        files["103-0.jsonl"][-1].update(pid=103, ppid=102)
    if attack != "no-receipts":
        _write_child_receipts(value)
    with pytest.raises(ValueError):
        _validate(value)


@pytest.mark.parametrize("wire", ['{"event":"original-child-exit","event":"other"}', '{"elapsed":NaN}', '{"elapsed":Infinity}'])
def test_original_child_receipt_json_rejects_ambiguous_or_nonfinite_bytes(wire):
    with pytest.raises(ValueError):
        native._child_receipt_json(wire)
