"""Exercise the real approved Node preload without granting any artifact authority.

These bootstrap/denial controls execute no memory algorithm and award no credit.
The separate genuine development caller proves original manager/worker execution.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import pytest

from equivalence.index_identity_boundaries import build_cases, case_wire
from equivalence.index_identity_boundaries_native import (
    ACTOR, ENTRY, LOCAL, PRELOAD, PROFILE_KEY, PROFILE_KIND, ROOT,
)
from equivalence.model_runtime_authority import prepare_model_node_authority


@pytest.fixture(scope="module")
def node():
    value = os.environ.get("MEMORY_EQ_NODE")
    if not value:
        pytest.skip("No explicitly approved Node supplied; no capability or acceptance credit")
    path = Path(value).resolve()
    prepare_model_node_authority(path)
    return path


@pytest.fixture
def context(tmp_path, node):
    authority = prepare_model_node_authority(node)
    case = build_cases()[0]
    for directory in ("traces", "evidence", "state", "empty-artifact-authority"):
        (tmp_path / directory).mkdir()
    return {"schemaVersion": 1, "kind": "release-oracle-execution", "providerMode": "none",
            "fetchPolicy": "deny", "approvedNodeRuntime": authority,
            "runtime": {"runtimeRoot": str(tmp_path / "empty-artifact-authority"), "packages": []},
            PROFILE_KEY: {"kind": PROFILE_KIND, "operation": case["operation"], "caseId": case["id"],
                          "caseWireSha256": hashlib.sha256(case_wire(case)).hexdigest(),
                          "clockNowMs": case["input"]["nowMs"], "nodeRuntime": authority,
                          "acceptancePointsAwarded": 0},
            "allowedLocal": [{"path": str(ROOT / "equivalence" / name),
                              "sha256": hashlib.sha256((ROOT / "equivalence" / name).read_bytes()).hexdigest()}
                             for name in LOCAL],
            "traceDirectory": str(tmp_path / "traces"), "evidenceDirectory": str(tmp_path / "evidence"),
            "stateDirectory": str(tmp_path / "state"), "configPath": str(tmp_path / "state/openclaw.json"),
            "approvedReferenceSources": [], "fixtureSourceCaptures": []}


def invoke(node, context, *, wire=None):
    directory = Path(context["stateDirectory"]).parent
    filename = directory / "context.json"
    filename.write_text(json.dumps(context))
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
           "MEMORY_EQ_RELEASE_CONTEXT": str(filename),
           "NODE_OPTIONS": f"--import={ROOT / 'equivalence' / PRELOAD}",
           "OPENCLAW_STATE_DIR": context["stateDirectory"], "OPENCLAW_CONFIG_PATH": context["configPath"]}
    argv = [str(node), "--eval", "process.stdout.write(JSON.stringify({clock:Date.now(),probe:true}))"]
    if wire is not None:
        argv = [str(node), str(ROOT / "equivalence" / ENTRY)]
    result = subprocess.run(argv, env=env, input=wire, capture_output=True, timeout=15)
    traces = [json.loads(line) for file in (directory / "traces").glob("*.jsonl")
              for line in file.read_bytes().splitlines()]
    return result, traces


def test_real_preload_accepts_exact_closed_bootstrap_with_no_original_authority(node, context):
    result, traces = invoke(node, context)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"clock": 1794268800000, "probe": True}
    bootstrap = next(row for row in traces if row["event"] == "index-identity-boundaries-bootstrap")
    assert bootstrap["clock"] == {"owner": "node:test", "apis": ["Date"], "nowMs": 1794268800000,
                                  "dateConstructorReplaced": True, "setTimeoutUnchanged": True,
                                  "performanceNowUnchanged": True}
    assert not any(row.get("kind") == "release" for row in traces)


@pytest.mark.parametrize("attack", ["missing-profile", "older-profile", "extra-profile", "kind", "operation",
                                  "case", "hash", "clock", "credit", "runtime-version", "runtime-hash",
                                  "node-executable", "icu", "unicode", "profile-binary", "extra-node-field",
                                  "reference-source", "provider-capture", "missing-local", "extra-local",
                                  "foreign-local", "changed-local", "duplicate-local", "config-owner",
                                  "policy-provider", "policy-fetch", "extra-context"])
def test_real_preload_rejects_foreign_capabilities_before_any_original_import(node, context, attack):
    context = deepcopy(context)
    profile = context[PROFILE_KEY]
    if attack == "missing-profile":
        del context[PROFILE_KEY]
    elif attack == "older-profile":
        context["hostTurnBarrierProfile"] = context.pop(PROFILE_KEY)
    elif attack == "extra-profile":
        context["hostRestartSessionProfile"] = deepcopy(profile)
    elif attack in {"kind", "operation", "case", "hash", "clock", "credit"}:
        key, value = {"kind": ("kind", "host-turn-barrier-outcomes"),
                      "operation": ("operation", "index-identity"), "case": ("caseId", "identity-matching-vector"),
                      "hash": ("caseWireSha256", "0" * 64), "clock": ("clockNowMs", 1794268800001),
                      "credit": ("acceptancePointsAwarded", 1)}[attack]
        profile[key] = value
    elif attack in {"runtime-version", "runtime-hash", "node-executable", "icu", "unicode"}:
        key, value = {"runtime-version": ("nodeVersion", "v25.2.1"), "runtime-hash": ("sha256", "0" * 64),
                      "node-executable": ("execPath", "/unknown/node"), "icu": ("icuVersion", "79.1"),
                      "unicode": ("unicodeVersion", "16.0")}[attack]
        context["approvedNodeRuntime"][key] = value
        profile["nodeRuntime"][key] = value
    elif attack == "profile-binary":
        profile["nodeRuntime"] = {**profile["nodeRuntime"], "sha256": "0" * 64}
    elif attack == "extra-node-field":
        context["approvedNodeRuntime"]["engine"] = "borrowed"
    elif attack == "reference-source":
        context["approvedReferenceSources"] = [{"path": "foreign.ts"}]
    elif attack == "provider-capture":
        context["fixtureSourceCaptures"] = [{"path": "foreign.mjs"}]
    elif attack == "missing-local":
        context["allowedLocal"].pop()
    elif attack == "extra-local":
        context["allowedLocal"].append({"path": str(ROOT / "equivalence/release-oracle.mjs"), "sha256": "0" * 64})
    elif attack == "foreign-local":
        context["allowedLocal"][-1]["path"] = str(ROOT / "equivalence/host-turn-barrier-runtime.mjs")
    elif attack == "changed-local":
        context["allowedLocal"][-1]["sha256"] = "0" * 64
    elif attack == "duplicate-local":
        context["allowedLocal"][-1] = deepcopy(context["allowedLocal"][0])
    elif attack == "config-owner":
        context["configPath"] = str(Path(context["stateDirectory"]) / "other.json")
    elif attack == "policy-provider":
        context["providerMode"] = "openai"
    elif attack == "policy-fetch":
        context["fetchPolicy"] = "allow"
    else:
        context["arbitraryModule"] = str(ROOT / "equivalence/release-oracle.mjs")
    result, traces = invoke(node, context)
    assert result.returncode != 0
    assert not result.stdout
    assert not any(row.get("kind") == "release" for row in traces)


@pytest.mark.parametrize("attack", ["other-approved-case", "changed-query", "extra-field", "changed-operation"])
def test_real_entry_rejects_changed_frozen_wire_before_actor_import(node, context, attack):
    case = build_cases()[0]
    if attack == "other-approved-case":
        wire = case_wire(build_cases()[1])
    else:
        changed = deepcopy(case)
        if attack == "changed-query":
            changed["input"]["search"]["query"] = "another-fact"
        elif attack == "extra-field":
            changed["input"]["expectedResult"] = {"status": "valid"}
        else:
            changed["operation"] = "index-identity"
        wire = case_wire(changed)
    result, traces = invoke(node, context, wire=wire)
    assert result.returncode != 0
    assert json.loads(result.stdout)["ok"] is False
    assert not any(row.get("path") == str(ROOT / "equivalence" / ACTOR) for row in traces)
    assert not any(row.get("kind") == "release" for row in traces)


def test_real_preload_refuses_hardlinked_reviewed_actor(node, context):
    # /tmp can be a different mount. The real extra link must share the source
    # filesystem rather than turning an unsupported fixture into a test skip.
    parent = ROOT / "work"
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="identity-capability-hardlink-", dir=parent) as directory:
        link = Path(directory) / "actor-copy.mjs"
        link.hardlink_to(ROOT / "equivalence" / ACTOR)
        try:
            result, traces = invoke(node, context)
        finally:
            link.unlink()
    assert result.returncode != 0 and not result.stdout
    assert not any(row.get("kind") == "release" for row in traces)


def test_real_preload_refuses_aliased_owned_trace_directory(node, context, tmp_path):
    traces = tmp_path / "traces"
    traces.rmdir()
    (tmp_path / "borrowed-traces").mkdir()
    traces.symlink_to(tmp_path / "borrowed-traces", target_is_directory=True)
    result, rows = invoke(node, context)
    assert result.returncode != 0 and not result.stdout
    assert not any(row.get("kind") == "release" for row in rows)
