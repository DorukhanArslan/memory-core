"""Exercise the real approved Node preload without granting any artifact authority.

These bootstrap/denial controls execute no memory algorithm and award no credit.
The separate genuine strict-two caller must prove original same-owner tool execution.
These tests do not establish cold recovery, dispatch counts or acceptance coverage.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import pytest

from equivalence.query_sync_cold_retry import build_cases, case_wire
from equivalence.query_sync_cold_retry_native import (
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


def invoke(node, context, *, wire=None, code=None):
    directory = Path(context["stateDirectory"]).parent
    filename = directory / "context.json"
    filename.write_text(json.dumps(context))
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
           "MEMORY_EQ_RELEASE_CONTEXT": str(filename),
           "NODE_OPTIONS": f"--import={ROOT / 'equivalence' / PRELOAD}",
           "OPENCLAW_STATE_DIR": context["stateDirectory"], "OPENCLAW_CONFIG_PATH": context["configPath"]}
    argv = [str(node), "--eval", code or "process.stdout.write(JSON.stringify({clock:Date.now(),probe:true}))"]
    if wire is not None:
        argv = [str(node), str(ROOT / "equivalence" / ENTRY)]
    started = time.monotonic_ns()
    process = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(wire, timeout=15)
    result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    (directory / "stdout.txt").write_bytes(stdout)
    (directory / "stderr.txt").write_bytes(stderr)
    (directory / "process.json").write_text(json.dumps({"pid": process.pid, "ppid": os.getpid(),
        "argv": argv, "environment": env, "startedAtNs": str(started),
        "finishedAtNs": str(time.monotonic_ns()), "returncode": process.returncode}))
    traces = [json.loads(line) for file in (directory / "traces").glob("*.jsonl")
              for line in file.read_bytes().splitlines()]
    return result, traces


@pytest.mark.parametrize("case_index", [0, 1])
def test_real_preload_accepts_exact_closed_bootstrap_with_no_original_authority(node, context, case_index):
    case = build_cases()[case_index]
    context = deepcopy(context)
    context[PROFILE_KEY].update(caseId=case["id"],
                                caseWireSha256=hashlib.sha256(case_wire(case)).hexdigest())
    result, traces = invoke(node, context)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"clock": 1794268800000, "probe": True}
    bootstrap = next(row for row in traces if row["event"] == "query-sync-cold-retry-bootstrap")
    assert bootstrap["clock"] == {"owner": "node:test", "apis": ["Date"], "nowMs": 1794268800000,
                                  "dateConstructorReplaced": True, "setTimeoutUnchanged": True,
                                  "performanceNowUnchanged": True}
    assert not any(row.get("kind") == "release" for row in traces)


@pytest.mark.parametrize("attack", ["missing-profile", "older-profile", "extra-profile",
                                  "outcomes-profile", "identity-profile", "extra-outcomes-profile",
                                  "extra-identity-profile", "outcomes-case", "identity-case",
                                  "kind", "operation",
                                  "case", "hash", "clock", "credit", "runtime-version", "runtime-hash",
                                  "node-executable", "icu", "unicode", "profile-binary", "extra-node-field",
                                  "reference-source", "provider-capture", "missing-local", "extra-local",
                                  "foreign-local", "outcomes-locals", "identity-locals",
                                  "changed-local", "duplicate-local", "config-owner",
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
    elif attack in {"outcomes-profile", "identity-profile"}:
        key = {"outcomes-profile": "querySyncOutcomesProfile",
               "identity-profile": "indexIdentityBoundariesProfile"}[attack]
        context[key] = context.pop(PROFILE_KEY)
        if attack == "outcomes-profile":
            context[key].update(kind="query-sync-outcomes", operation="query-sync-outcomes-runtime",
                                caseId="query-sync-outcomes-cold-existing-no-index",
                                caseWireSha256="2cfbdbda1abf050d61255b3fafe7c577d1d95ba532b6e69e12dd5773277f16c2")
        else:
            context[key].update(kind="index-identity-boundaries", operation="index-identity-boundaries-runtime",
                                caseId="index-identity-boundaries-matching",
                                caseWireSha256="05498bb4b7f614baaa8c26aa6ee41ee5d168f847fd1e05d852d19911baeaf8fd")
    elif attack in {"extra-outcomes-profile", "extra-identity-profile"}:
        key = {"extra-outcomes-profile": "querySyncOutcomesProfile",
               "extra-identity-profile": "indexIdentityBoundariesProfile"}[attack]
        context[key] = deepcopy(profile)
    elif attack in {"outcomes-case", "identity-case"}:
        profile["caseId"] = {"outcomes-case": "query-sync-outcomes-cold-existing-no-index",
                             "identity-case": "index-identity-boundaries-matching"}[attack]
        profile["caseWireSha256"] = {
            "outcomes-case": "2cfbdbda1abf050d61255b3fafe7c577d1d95ba532b6e69e12dd5773277f16c2",
            "identity-case": "05498bb4b7f614baaa8c26aa6ee41ee5d168f847fd1e05d852d19911baeaf8fd",
        }[attack]
    elif attack in {"kind", "operation", "case", "hash", "clock", "credit"}:
        key, value = {"kind": ("kind", "host-turn-barrier-outcomes"),
                      "operation": ("operation", "query-sync"), "case": ("caseId", "foreign-case"),
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
        context["allowedLocal"][-1]["path"] = str(ROOT / "equivalence/query-sync-outcomes-runtime.mjs")
    elif attack in {"outcomes-locals", "identity-locals"}:
        prefix = {"outcomes-locals": "query-sync-outcomes",
                  "identity-locals": "index-identity-boundaries"}[attack]
        context["allowedLocal"] = [
            {"path": str(ROOT / "equivalence" / f"{prefix}-{suffix}.mjs"),
             "sha256": hashlib.sha256((ROOT / "equivalence" / f"{prefix}-{suffix}.mjs").read_bytes()).hexdigest()}
            for suffix in ("entry", "preload", "runtime")
        ]
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


@pytest.mark.parametrize("attack", ["other-approved-case", "changed-query", "changed-second-query",
                                  "changed-fault", "changed-fault-order", "changed-owner-policy",
                                  "reopen-before-recovery", "sync-before-recovery",
                                  "wait-before-recovery", "extra-field", "changed-operation"])
def test_real_entry_rejects_changed_frozen_wire_before_actor_import(node, context, attack):
    case = build_cases()[1] if attack in {
        "changed-fault", "changed-fault-order", "reopen-before-recovery",
        "sync-before-recovery", "wait-before-recovery",
    } else build_cases()[0]
    context = deepcopy(context)
    context[PROFILE_KEY].update(caseId=case["id"],
                                caseWireSha256=hashlib.sha256(case_wire(case)).hexdigest())
    if attack == "other-approved-case":
        wire = case_wire(build_cases()[1])
    else:
        changed = deepcopy(case)
        if attack == "changed-query":
            changed["input"]["queries"]["first"]["query"] = "another-fact"
        elif attack == "changed-second-query":
            changed["input"]["queries"]["second"]["query"] = "another-fact"
        elif attack == "changed-fault":
            changed["input"]["fault"]["nativeTarget"] = "unresolved-database-journal"
        elif attack == "changed-fault-order":
            changed["input"]["steps"][1:3] = list(reversed(changed["input"]["steps"][1:3]))
        elif attack == "changed-owner-policy":
            changed["input"]["ownerPolicy"] = "allow a fresh owner for every query"
        elif attack in {"reopen-before-recovery", "sync-before-recovery", "wait-before-recovery"}:
            operation = {"reopen-before-recovery": "acquire-original-default-owner",
                         "sync-before-recovery": "explicit-sync",
                         "wait-before-recovery": "private-maintenance-wait"}[attack]
            changed["input"]["steps"].insert(5, {"operation": operation})
        elif attack == "extra-field":
            changed["input"]["expectedResult"] = {"status": "valid"}
        else:
            changed["operation"] = "query-sync"
        wire = case_wire(changed)
    result, traces = invoke(node, context, wire=wire)
    assert result.returncode != 0
    assert json.loads(result.stdout)["ok"] is False
    assert not any(row.get("path") == str(ROOT / "equivalence" / ACTOR) for row in traces)
    assert not any(row.get("kind") == "release" for row in traces)


def test_real_preload_refuses_hardlinked_reviewed_actor(node, context):
    # /tmp can be a different mount. The real extra link must share the source
    # filesystem rather than turning an unsupported fixture into a test skip.
    parent = ROOT / ".work"
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="query-sync-cold-retry-capability-hardlink-", dir=parent) as directory:
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


def test_real_preload_rejects_unapproved_dynamic_file_import(node, context, tmp_path):
    module = tmp_path / "foreign.mjs"
    module.write_text("export const value = 'unapproved';\n")
    result, traces = invoke(node, context, code=f"import({json.dumps(module.as_uri())})")
    assert result.returncode != 0 and not result.stdout
    assert any(row.get("event") == "rejected" for row in traces)
    assert not any(row.get("kind") == "release" for row in traces)


def test_real_preload_refuses_context_alias_before_bootstrap(node, context, tmp_path):
    original = tmp_path / "real-context.json"
    original.write_text(json.dumps(context))
    alias = tmp_path / "context.json"
    alias.symlink_to(original)
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath,
           "MEMORY_EQ_RELEASE_CONTEXT": str(alias), "TZ": "UTC", "LANG": "C.UTF-8",
           "NODE_OPTIONS": f"--import={ROOT / 'equivalence' / PRELOAD}"}
    process = subprocess.Popen([str(node), "--eval", "process.stdout.write('unexpected')"],
                               env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=15)
    (tmp_path / "alias-stdout.txt").write_bytes(stdout)
    (tmp_path / "alias-stderr.txt").write_bytes(stderr)
    (tmp_path / "alias-process.json").write_text(json.dumps({"pid": process.pid,
        "ppid": os.getpid(), "returncode": process.returncode}))
    assert process.returncode != 0 and not stdout
    assert not list((tmp_path / "traces").glob("*.jsonl"))


@pytest.mark.parametrize(("case_index", "expected"), [
    (0, ["first", "second"]),
    (1, ["faulted", "afterRemoval"]),
])
def test_actor_preserves_frozen_step_order_after_sorted_wire_transport(node, case_index, expected, tmp_path):
    """Exercise only the pure order selector; never open an original manager/host."""
    wire = case_wire(build_cases()[case_index])
    transported = json.loads(wire)
    assert list(transported["input"]["queries"]) == sorted(expected)
    if case_index == 1:
        assert list(transported["input"]["queries"]) != expected
    actor = (ROOT / "equivalence" / ACTOR).as_uri()
    code = ("import fs from 'node:fs';"
            f"import {{orderedPublicQueryLabels}} from {json.dumps(actor)};"
            "const input=JSON.parse(fs.readFileSync(0,'utf8')).input;"
            "process.stdout.write(JSON.stringify(orderedPublicQueryLabels(input)));")
    env = {"PATH": str(node.parent) + os.pathsep + os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}
    result = subprocess.run([str(node), "--input-type=module", "--eval", code],
                            input=wire, env=env, cwd=ROOT, capture_output=True, timeout=15)
    (tmp_path / "pure-order-stdout.txt").write_bytes(result.stdout)
    (tmp_path / "pure-order-stderr.txt").write_bytes(result.stderr)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected
