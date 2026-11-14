"""Labelled Python protocol fixtures only: no Node or original engine executes."""
from copy import deepcopy
import hashlib
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from equivalence import forget_index_fence_native as native
from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME


def _wire(case):
    return json.dumps({key: case[key] for key in ("id", "operation", "input")},
                      sort_keys=True, separators=(",", ":")).encode()


@pytest.fixture
def closed(monkeypatch):
    case = {"id": "labelled-no-engine-protocol", "operation": "forget-index-fence-runtime",
            "input": {"clock": {"nowMs": 1794614400000}, "actors": {"foreground": {"role": "fixture"}},
                      "gates": [], "steps": [{"operation": "original-sync", "actor": "foreground", "label": "s"}]}}
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
    monkeypatch.setattr(native, "_contract", lambda: contract)
    authority = {"execPath": "/labelled/no-engine/node", **APPROVED_NODE_RUNTIME}
    return case, recovery, authority


def test_profile_binds_every_actor_gate_and_declared_clock_without_running_node(closed):
    case, recovery, authority = closed
    profile = native.prepare_profile(case, authority)
    assert profile["actorClocks"] == {"coordinator": 1794614400000, "observer": 1794614400000,
                                      "foreground": 1794614400000}
    assert profile["acceptancePointsAwarded"] == 0
    assert profile["caseWireSha256"] == hashlib.sha256(_wire(case)).hexdigest()
    assert native.validate_profile(profile) == profile
    recovered = native.prepare_profile(recovery, authority)
    assert recovered["recoveryNowMs"] == 1794614460000
    assert "recoveryNowMs" not in profile


@pytest.mark.parametrize("attack", ["kind", "operation", "case", "wire", "actor", "clock", "gates", "credit", "credit-bool", "extra", "node"])
def test_profile_rejects_borrowed_or_widened_capabilities(closed, attack):
    case, _, authority = closed
    profile = native.prepare_profile(case, authority)
    if attack == "kind":
        profile["kind"] = "query-sync-cold-retry"
    elif attack == "operation":
        profile["operation"] = "query-sync-cold-retry-runtime"
    elif attack == "case":
        profile["caseId"] = "unapproved"
    elif attack == "wire":
        profile["caseWireSha256"] = "0" * 64
    elif attack == "actor":
        profile["actorClocks"]["borrowed"] = profile["actorClocks"]["coordinator"]
    elif attack == "clock":
        profile["actorClocks"]["foreground"] += 1
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
