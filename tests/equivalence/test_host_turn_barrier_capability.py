"""Actual bootstrap denials and tampering of byte-copied retained Native traces.

Retained replay is labelled explicitly; it is neither a new Native execution
nor acceptance evidence. No source capture or successful tool result is forged.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from equivalence import host_turn_barrier, host_update_isolation
from equivalence.host_restart_native import digest
from equivalence.host_turn_barrier_evidence import _native
from equivalence.host_turn_barrier_native import (
    BOOTSTRAP_EVENT, ENTRY, LOCAL, PRELOAD, PROFILE_KEY, PROFILE_KIND, PROVIDER, validate_traces,
)
from equivalence.model_runtime_authority import prepare_model_node_authority

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CAPTURE = ROOT / "work/host-turn-barrier/attempt-002-development/host-turn-barrier-cold-ascii"


@pytest.fixture(scope="module")
def authority():
    node = Path(os.environ.get("MEMORY_EQ_NODE", ROOT / "work/node-v24.16.0-linux-x64/bin/node"))
    if not node.is_file():
        pytest.skip("The approved Node executable is required for actual turn-barrier bootstrap denials")
    return prepare_model_node_authority(node)


def _setup(tmp_path, authority, index=0):
    case = host_turn_barrier.build_cases()[index]
    for name in ("traces", "evidence", "state"):
        (tmp_path / name).mkdir()
    provider = ROOT / "equivalence" / PROVIDER
    context = {
        "schemaVersion": 1, "kind": "release-oracle-execution", "runtime": {"packages": []},
        "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": deepcopy(authority),
        PROFILE_KEY: {"kind": PROFILE_KIND, "operation": case["operation"], "caseId": case["id"],
                      "caseWireSha256": host_turn_barrier.CASE_HASHES[case["id"]],
                      "clockNowMs": case["input"]["nowMs"], "nodeRuntime": deepcopy(authority),
                      "acceptancePointsAwarded": 0},
        "allowedLocal": [{"path": str(ROOT / "equivalence" / name),
                          "sha256": digest(ROOT / "equivalence" / name)} for name in LOCAL],
        "traceDirectory": str(tmp_path / "traces"), "evidenceDirectory": str(tmp_path / "evidence"),
        "stateDirectory": str(tmp_path / "state"), "configPath": str(tmp_path / "state/openclaw.json"),
        "approvedReferenceSources": [], "fixtureSourceCaptures": [
            {"basename": "index.mjs", "capturePackage": "host-turn-barrier-provider",
             "sourcePath": str(provider), "sha256": digest(provider)}],
    }
    return case, context


def _invoke(tmp_path, authority, context, *arguments, stdin=""):
    path = tmp_path / "context.json"
    path.write_text(json.dumps(context), encoding="utf8")
    return subprocess.run([authority["execPath"], *arguments], input=stdin, capture_output=True,
                          text=True, timeout=15, env={
                              "PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
                              "MEMORY_EQ_RELEASE_CONTEXT": str(path),
                              "NODE_OPTIONS": f'--import={ROOT / "equivalence" / PRELOAD}',
                          })


def _bootstrap_rows(tmp_path):
    return [json.loads(line) for path in (tmp_path / "traces").glob("*.jsonl")
            for line in path.read_text().splitlines()]


@pytest.mark.parametrize("index", range(4))
def test_exact_bootstrap_admits_only_its_closed_literal_and_declared_clock(tmp_path, authority, index):
    case, context = _setup(tmp_path, authority, index)
    result = _invoke(tmp_path, authority, context, "--eval", "process.stdout.write(String(Date.now()))")
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(case["input"]["nowMs"])
    rows = _bootstrap_rows(tmp_path)
    own = next(row for row in rows if row["event"] == BOOTSTRAP_EVENT)
    assert own["profile"] == context[PROFILE_KEY]
    assert own["profile"]["acceptancePointsAwarded"] == 0
    assert own["clock"] == {"owner": "node:test", "apis": ["Date"], "nowMs": case["input"]["nowMs"],
                            "dateConstructorReplaced": True, "setTimeoutUnchanged": True,
                            "performanceNowUnchanged": True}
    assert not any(row.get("kind") == "release" for row in rows)


@pytest.mark.parametrize("attack", ["case-hash", "foreign-case", "foreign-profile", "extra-profile",
                                    "clock-time", "clock-scope", "self-awarded-credit", "operation",
                                    "node-sha", "node-version", "provider-package", "provider-source"])
def test_actual_bootstrap_rejects_changed_or_borrowed_capabilities(tmp_path, authority, attack):
    _, context = _setup(tmp_path, authority)
    profile = context[PROFILE_KEY]
    if attack == "case-hash":
        profile["caseWireSha256"] = "0" * 64
    elif attack == "foreign-case":
        foreign = host_update_isolation.build_cases()[0]
        profile.update(caseId=foreign["id"], caseWireSha256=host_update_isolation.CASE_HASHES[foreign["id"]])
    elif attack == "foreign-profile":
        context["hostUpdateIsolationProfile"] = context.pop(PROFILE_KEY)
    elif attack == "extra-profile":
        context["hostRestartSessionProfile"] = deepcopy(profile)
    elif attack == "clock-time":
        profile["clockNowMs"] += 1
    elif attack == "clock-scope":
        profile["clockScope"] = "main-thread-only"
    elif attack == "self-awarded-credit":
        profile["acceptancePointsAwarded"] = 1
    elif attack == "operation":
        profile["operation"] = "host-update-isolation-runtime"
    elif attack in {"node-sha", "node-version"}:
        key, value = ("sha256", "0" * 64) if attack == "node-sha" else ("nodeVersion", "v24.15.0")
        context["approvedNodeRuntime"][key] = value
        profile["nodeRuntime"][key] = value
    elif attack == "provider-package":
        context["fixtureSourceCaptures"][0]["capturePackage"] = "equivalence"
    else:
        context["fixtureSourceCaptures"][0]["sourcePath"] = str(ROOT / "equivalence/flush-execution.mjs")
    result = _invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')")
    assert result.returncode != 0 and result.stdout == ""
    assert not any(row.get("kind") == "release" for row in _bootstrap_rows(tmp_path))


def test_actual_entry_rejects_foreign_stdin_before_native_runtime_import(tmp_path, authority):
    _, context = _setup(tmp_path, authority)
    foreign = host_update_isolation.case_wire(host_update_isolation.build_cases()[0]).decode()
    result = _invoke(tmp_path, authority, context, str(ROOT / "equivalence" / ENTRY), stdin=foreign)
    assert result.returncode != 0
    returned = json.loads(result.stdout)
    assert returned["ok"] is False and "whole turn-barrier literal changed" in returned["error"]["message"]
    assert not any(row.get("kind") == "release" for row in _bootstrap_rows(tmp_path))


def test_actual_import_hook_refuses_unlisted_local_module(tmp_path, authority):
    _, context = _setup(tmp_path, authority)
    attacker = tmp_path / "untrusted.mjs"
    attacker.write_text("process.stdout.write('UNEXPECTED');", encoding="utf8")
    result = _invoke(tmp_path, authority, context, "--eval", f"import({json.dumps(attacker.as_uri())})")
    assert result.returncode != 0 and result.stdout == ""
    assert "Unverified whole-caller module" in result.stderr
    assert any(row.get("event") == "rejected" for row in _bootstrap_rows(tmp_path))


def test_actual_fetch_policy_denies_network_before_any_transport_request(tmp_path, authority):
    _, context = _setup(tmp_path, authority)
    result = _invoke(tmp_path, authority, context, "--eval", "fetch('https://fixture.invalid')")
    assert result.returncode != 0 and result.stdout == ""
    assert "Network disabled" in result.stderr
    assert any(row.get("event") == "network-denied" for row in _bootstrap_rows(tmp_path))


@pytest.fixture(scope="module")
def retained():
    directory = Path(os.environ.get("MEMORY_EQ_TURN_BARRIER_CAPTURE", DEFAULT_CAPTURE))
    if not (directory / "context.json").is_file():
        pytest.skip("Genuine retained turn-barrier Native capture unavailable; no substitute capture is generated")
    context_path = directory / "context.json"
    context = json.loads(context_path.read_text())
    context["_sha256"] = digest(context_path)
    raw = json.loads((directory / "evidence/native-raw.json").read_text())[0]
    result = json.loads((directory / "stdout.json").read_text())["result"]
    case = next(case for case in host_turn_barrier.build_cases() if case["id"] == context[PROFILE_KEY]["caseId"])
    traces = {p.name: p.read_bytes() for p in (directory / "traces").iterdir()}
    return {"directory": directory, "context": context, "raw": raw, "result": result, "case": case, "traces": traces}


def _trace_copy(tmp_path, retained):
    directory = tmp_path / "traces"
    directory.mkdir()
    for name, data in retained["traces"].items():
        (directory / name).write_bytes(data)
    return directory


def _validate(directory, retained, context=None):
    value = context or retained["context"]
    return validate_traces(directory, value, value["runtime"], value["approvedNodeRuntime"],
                           process_pid=retained["raw"]["pid"], parent_pid=retained["raw"]["ppid"])


def _mutate_first(directory, predicate, mutation):
    for path in sorted(directory.iterdir()):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            if predicate(row):
                mutation(row)
                path.write_text("".join(json.dumps(item) + "\n" for item in rows))
                return
    raise AssertionError("The genuine retained capture did not contain the requested attack target")


def test_exact_retained_trace_replays_without_new_native_execution(tmp_path, retained):
    directory = _trace_copy(tmp_path, retained)
    observed = _validate(directory, retained)
    assert len(observed["bootstraps"]) >= 2
    assert observed["fixtureCaptures"] and observed["loaded"]
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == retained["traces"]
    _native(retained["case"], retained["raw"], retained["result"])


@pytest.mark.parametrize("attack", ["process-id", "parent-id", "context-hash", "node-authority",
                                    "worker-clock", "worker-profile", "original-hash", "unknown-local",
                                    "provider-source", "proof-path", "unknown-event"])
def test_retained_real_trace_tampering_is_rejected(tmp_path, retained, attack):
    directory = _trace_copy(tmp_path, retained)
    if attack in {"process-id", "parent-id", "context-hash", "node-authority"}:
        def change(row):
            if attack == "process-id":
                row["pid"] += 1
            elif attack == "parent-id":
                row["ppid"] += 1
            elif attack == "context-hash":
                row["contextSha256"] = "0" * 64
            else:
                row["runtime"]["sha256"] = "0" * 64
        _mutate_first(directory, lambda row: row["event"] == "bootstrap", change)
    elif attack in {"worker-clock", "worker-profile"}:
        def change(row):
            if attack == "worker-clock":
                row["clock"]["setTimeoutUnchanged"] = False
            else:
                row["profile"]["caseWireSha256"] = "0" * 64
        _mutate_first(directory, lambda row: row["event"] == BOOTSTRAP_EVENT and row["threadId"] != 0, change)
    elif attack == "original-hash":
        _mutate_first(directory, lambda row: row.get("kind") == "release",
                      lambda row: row.update(sha256="0" * 64))
    elif attack == "unknown-local":
        _mutate_first(directory, lambda row: row.get("kind") == "oracle",
                      lambda row: row.update(path=str(tmp_path / "untrusted.mjs")))
    elif attack == "provider-source":
        _mutate_first(directory, lambda row: row.get("kind") == "fixture-capture",
                      lambda row: row.update(sourcePath=str(ROOT / "equivalence/flush-execution.mjs")))
    elif attack == "proof-path":
        _mutate_first(directory, lambda row: row.get("kind") == "fixture-capture",
                      lambda row: row.update(proofPath="../foreign-provider.mjs"))
    else:
        _mutate_first(directory, lambda row: row["event"] == "load",
                      lambda row: row.update(event="invented-admission"))
    with pytest.raises(ValueError):
        _validate(directory, retained)


@pytest.mark.parametrize("attack", ["bytes", "symlink", "hard-link"])
def test_actual_retained_provider_proof_must_keep_exact_bytes_and_own_inode(tmp_path, retained, attack):
    directory = _trace_copy(tmp_path, retained)
    evidence = tmp_path / "evidence"
    original_proofs = Path(retained["context"]["evidenceDirectory"]) / "fixture-source-captures"
    shutil.copytree(original_proofs, evidence / "fixture-source-captures")
    proof = next((evidence / "fixture-source-captures").glob("*.mjs"))
    if attack == "bytes":
        proof.write_bytes(proof.read_bytes() + b"\n// altered test copy\n")
    elif attack == "symlink":
        filename = proof.name
        proof.unlink()
        proof.symlink_to(original_proofs / filename)
    else:
        os.link(proof, tmp_path / "second-proof-link.mjs")
    context = deepcopy(retained["context"])
    context["evidenceDirectory"] = str(evidence)
    with pytest.raises(ValueError, match="retained exact provider source capture"):
        _validate(directory, retained, context)
    assert all(path.stat().st_nlink == 1 for path in original_proofs.iterdir())


@pytest.mark.parametrize("attack", ["pid-zero", "same-parent", "wrong-session", "different-input", "provided-operation"])
def test_genuine_raw_capture_cannot_borrow_another_request_or_bypass_admission(retained, attack):
    raw = deepcopy(retained["raw"])
    if attack == "pid-zero":
        raw["pid"] = 0
    elif attack == "same-parent":
        raw["ppid"] = raw["pid"]
    elif attack == "wrong-session":
        raw["scope"]["sessionKey"] = "agent:other:foreign"
    elif attack == "different-input":
        raw["request"]["identity"]["sessionId"] = "foreign-session"
    else:
        raw["turns"][0]["callInput"]["replyOperation"] = {"fixture": "admission-bypass"}
    with pytest.raises(ValueError):
        _native(retained["case"], raw, retained["result"])
