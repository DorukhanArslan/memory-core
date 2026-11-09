"""Actual independent policy preload rejects cross-family and carrier attacks."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from equivalence.host_restart import CASE_HASHES as ORIGINAL_HASHES
from equivalence.host_restart import build_cases as original_cases
from equivalence.host_restart import case_wire as original_wire
from equivalence.host_restart_native import LOCAL, POLICY_LOCAL, digest
from equivalence.host_restart_policy import CASE_HASHES, build_cases, case_wire
from equivalence.model_runtime_authority import prepare_model_node_authority

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def authority():
    node = Path(os.environ.get("MEMORY_EQ_NODE", ROOT / "work/node-v24.16.0-linux-x64/bin/node"))
    if not node.is_file():
        pytest.skip("The approved Node executable is required for actual policy preload guards")
    return prepare_model_node_authority(node)


def _setup(tmp_path, authority, *, policy=True, index=0):
    case = (build_cases() if policy else original_cases())[index]
    hashes = CASE_HASHES if policy else ORIGINAL_HASHES
    names = POLICY_LOCAL if policy else LOCAL
    profile_key = "hostRestartPolicyProfile" if policy else "hostRestartProfile"
    (tmp_path / "traces").mkdir()
    context = {
        "schemaVersion": 1, "kind": "release-oracle-execution", "runtime": {"packages": []},
        "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
        profile_key: {
            "kind": "host-restart-policy-development" if policy else "host-restart-recall-development",
            "operation": case["operation"], "caseId": case["id"],
            "caseWireSha256": hashes[case["id"]], "nodeRuntime": authority,
            "acceptancePointsAwarded": 0,
        },
        "allowedLocal": [
            {"path": str(ROOT / "equivalence" / name), "sha256": digest(ROOT / "equivalence" / name)}
            for name in names
        ],
        "traceDirectory": str(tmp_path / "traces"), "evidenceDirectory": str(tmp_path / "evidence"),
        "stateDirectory": str(tmp_path / "state"), "configPath": str(tmp_path / "openclaw.json"),
        "approvedReferenceSources": [], "fixtureSourceCaptures": [],
    }
    return case, context


def _invoke(tmp_path, authority, context, *arguments, policy=True, stdin=""):
    filename = tmp_path / "context.json"
    filename.write_text(json.dumps(context), encoding="utf8")
    preload = "host-restart-policy-preload.mjs" if policy else "host-restart-preload.mjs"
    env = {
        "PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
        "MEMORY_EQ_RELEASE_CONTEXT": str(filename),
        "NODE_OPTIONS": f'--import={ROOT / "equivalence" / preload}',
    }
    return subprocess.run([authority["execPath"], *arguments], input=stdin, env=env,
                          capture_output=True, text=True, timeout=15)


def _rows(tmp_path):
    return [json.loads(line) for path in sorted((tmp_path / "traces").glob("*.jsonl"))
            for line in path.read_text().splitlines()]


def _rejected_before_preload_imports(tmp_path, result):
    assert result.returncode != 0 and result.stdout == ""
    assert "Restart capability cannot borrow" in result.stderr
    assert not list((tmp_path / "traces").iterdir())


@pytest.mark.parametrize("index", range(4))
def test_actual_preload_admits_only_each_exact_zero_credit_policy_case(tmp_path, authority, index):
    case, context = _setup(tmp_path, authority, index=index)
    result = _invoke(tmp_path, authority, context, "--eval", "process.stdout.write('ADMITTED')")
    assert result.returncode == 0 and result.stdout == "ADMITTED", result.stderr
    rows = _rows(tmp_path)
    receipts = [row for row in rows if row["event"] == "host-restart-policy-bootstrap"]
    assert len(receipts) == 1
    assert receipts[0]["profile"] == context["hostRestartPolicyProfile"]
    assert receipts[0]["profile"]["caseId"] == case["id"]
    assert receipts[0]["profile"]["acceptancePointsAwarded"] == 0
    assert not any(row.get("kind") == "release" for row in rows)


@pytest.mark.parametrize("policy_preload", [True, False])
def test_old_and_policy_preloads_reject_each_others_profile_context(tmp_path, authority, policy_preload):
    _, context = _setup(tmp_path, authority, policy=not policy_preload)
    result = _invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')",
                     policy=policy_preload)
    _rejected_before_preload_imports(tmp_path, result)


@pytest.mark.parametrize("policy", [True, False])
def test_old_and_policy_profiles_cannot_borrow_each_others_literal_identity(tmp_path, authority, policy):
    _, context = _setup(tmp_path, authority, policy=policy)
    borrowed = (original_cases() if policy else build_cases())[0]
    hashes = ORIGINAL_HASHES if policy else CASE_HASHES
    profile = context["hostRestartPolicyProfile" if policy else "hostRestartProfile"]
    profile.update(caseId=borrowed["id"], caseWireSha256=hashes[borrowed["id"]])
    result = _invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')", policy=policy)
    _rejected_before_preload_imports(tmp_path, result)


@pytest.mark.parametrize("policy", [True, False])
def test_both_entries_reject_the_other_familys_stdin_before_actor_imports(tmp_path, authority, policy):
    _, context = _setup(tmp_path, authority, policy=policy)
    borrowed = (original_cases() if policy else build_cases())[0]
    wire = original_wire(borrowed) if policy else case_wire(borrowed)
    entry = "host-restart-policy-entry.mjs" if policy else "host-restart-entry.mjs"
    result = _invoke(tmp_path, authority, context, str(ROOT / "equivalence" / entry),
                     policy=policy, stdin=wire.decode())
    assert result.returncode != 0
    returned = json.loads(result.stdout)
    assert returned["ok"] is False and "protected input binding" in returned["error"]["message"]
    rows = _rows(tmp_path)
    assert not any(row.get("kind") == "release" for row in rows)
    assert not any(row.get("path", "").endswith("/host-restart-runtime.mjs") for row in rows)


@pytest.mark.parametrize("mutation", ["source-policy", "source-mtime", "recall-prompt", "writer-ack"])
def test_modified_case_and_rehashed_input_cannot_widen_policy_preload(tmp_path, authority, mutation):
    case, context = _setup(tmp_path, authority)
    if mutation == "source-policy":
        case["input"]["policy"]["rememberAcrossConversations"] = True
    elif mutation == "source-mtime":
        case["input"]["policy"]["sourceMtimeMs"] += 1000
    elif mutation == "recall-prompt":
        case["input"]["phases"][1]["recall"]["prompt"] += " The answer is supplied."
    else:
        case["input"]["phases"][0]["saveAck"] += " Changed."
    wire = case_wire(case)
    context["hostRestartPolicyProfile"]["caseWireSha256"] = hashlib.sha256(wire).hexdigest()
    result = _invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')", stdin=wire.decode())
    _rejected_before_preload_imports(tmp_path, result)


@pytest.mark.parametrize("field", ["hostRestartProfile", "promotionApplyFamilyProfile", "casePath",
                                   "approvedReferenceSources", "fixtureSourceCaptures"])
def test_policy_preload_rejects_mixed_capabilities_and_full_case_carriers(tmp_path, authority, field):
    _, context = _setup(tmp_path, authority)
    context[field] = [{}] if field in {"approvedReferenceSources", "fixtureSourceCaptures"} else {}
    result = _invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')")
    _rejected_before_preload_imports(tmp_path, result)


def test_policy_profile_cannot_hide_a_full_case_path_inside_its_own_envelope(tmp_path, authority):
    _, context = _setup(tmp_path, authority)
    context["hostRestartPolicyProfile"]["casePath"] = str(tmp_path / "producer-with-answer.json")
    result = _invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')")
    _rejected_before_preload_imports(tmp_path, result)


def test_policy_entry_rejects_changed_stdin_with_an_approved_profile(tmp_path, authority):
    case, context = _setup(tmp_path, authority)
    changed = deepcopy(case)
    changed["input"]["phases"][0]["write"]["text"] += " An undeclared fact."
    result = _invoke(tmp_path, authority, context, str(ROOT / "equivalence/host-restart-policy-entry.mjs"),
                     stdin=case_wire(changed).decode())
    assert result.returncode != 0
    returned = json.loads(result.stdout)
    assert returned["ok"] is False and "protected input binding" in returned["error"]["message"]
    assert not any(row.get("kind") == "release" for row in _rows(tmp_path))
    assert not any(row.get("path", "").endswith("/host-restart-runtime.mjs") for row in _rows(tmp_path))


def test_independent_policy_preload_is_inherited_by_a_real_esm_worker(tmp_path, authority):
    _, context = _setup(tmp_path, authority, index=2)
    entry = str(ROOT / "equivalence/model-runtime-observation.mjs")
    script = ("const {Worker}=require('node:worker_threads'); const w=new Worker("
              + json.dumps(entry) + "); w.on('error',e=>{throw e;});")
    result = _invoke(tmp_path, authority, context, "--eval", script)
    assert result.returncode == 0, result.stderr
    rows = _rows(tmp_path)
    bootstraps = [row for row in rows if row["event"] == "bootstrap"]
    receipts = [row for row in rows if row["event"] == "host-restart-policy-bootstrap"]
    assert len(bootstraps) == len(receipts) == 2
    assert len({row["pid"] for row in receipts}) == 1
    assert len({row["threadId"] for row in receipts}) == 2
    assert {row["isMainThread"] for row in bootstraps} == {True, False}
    assert all(row["profile"] == context["hostRestartPolicyProfile"] for row in receipts)
    assert all(row["runtime"] == authority for row in bootstraps)
    assert all(row["fetchDenied"] and row["providerMode"] == "none" for row in bootstraps)
    assert not any(row.get("kind") == "release" for row in rows)
