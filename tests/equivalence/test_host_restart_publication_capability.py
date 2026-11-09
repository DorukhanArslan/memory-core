"""Real publication/managed preloads keep four exact capability families apart."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from equivalence import host_restart, host_restart_managed, host_restart_policy, host_restart_publication
from equivalence.host_restart_native import LOCAL, MANAGED_LOCAL, POLICY_LOCAL, PUBLICATION_LOCAL, digest
from equivalence.model_runtime_authority import prepare_model_node_authority

ROOT = Path(__file__).resolve().parents[2]
FAMILIES = {
    "original": (host_restart, "hostRestartProfile", "host-restart", LOCAL),
    "policy": (host_restart_policy, "hostRestartPolicyProfile", "host-restart-policy", POLICY_LOCAL),
    "publication": (host_restart_publication, "hostRestartPublicationProfile", "host-restart-publication", PUBLICATION_LOCAL),
    "managed": (host_restart_managed, "hostRestartManagedProfile", "host-restart-managed", MANAGED_LOCAL),
}
NEW_FAMILIES = ("publication", "managed")
NEW_BORROWING = [(target, supplied) for target in NEW_FAMILIES for supplied in FAMILIES if target != supplied]
OLDER_BORROWING = [(target, supplied) for target in ("original", "policy") for supplied in NEW_FAMILIES]


@pytest.fixture(scope="module")
def authority():
    node = Path(os.environ.get("MEMORY_EQ_NODE", ROOT / "work/node-v24.16.0-linux-x64/bin/node"))
    if not node.is_file():
        pytest.skip("The approved Node executable is required for actual publication capability guards")
    return prepare_model_node_authority(node)


def _setup(tmp_path, authority, family, *, index=0):
    module, profile_key, stem, local = FAMILIES[family]
    case = module.build_cases()[index]
    (tmp_path / "traces").mkdir()
    context = {
        "schemaVersion": 1, "kind": "release-oracle-execution", "runtime": {"packages": []},
        "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
        profile_key: {
            "kind": "host-restart-recall-development" if family == "original" else stem + "-development",
            "operation": case["operation"], "caseId": case["id"],
            "caseWireSha256": module.CASE_HASHES[case["id"]],
            "nodeRuntime": authority, "acceptancePointsAwarded": 0,
        },
        "allowedLocal": [{"path": str(ROOT / "equivalence" / name),
                          "sha256": digest(ROOT / "equivalence" / name)} for name in local],
        "traceDirectory": str(tmp_path / "traces"), "evidenceDirectory": str(tmp_path / "evidence"),
        "stateDirectory": str(tmp_path / "state"), "configPath": str(tmp_path / "openclaw.json"),
        "approvedReferenceSources": [], "fixtureSourceCaptures": [],
    }
    return case, context


def _invoke(tmp_path, authority, context, family, *arguments, stdin=""):
    filename = tmp_path / "context.json"
    filename.write_text(json.dumps(context), encoding="utf8")
    stem = FAMILIES[family][2]
    env = {
        "PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
        "MEMORY_EQ_RELEASE_CONTEXT": str(filename),
        "NODE_OPTIONS": f'--import={ROOT / "equivalence" / (stem + "-preload.mjs")}',
    }
    return subprocess.run([authority["execPath"], *arguments], input=stdin, env=env,
                          capture_output=True, text=True, timeout=15)


def _rows(tmp_path):
    return [json.loads(line) for path in sorted((tmp_path / "traces").glob("*.jsonl"))
            for line in path.read_text().splitlines()]


def _assert_preload_rejection(tmp_path, result):
    assert result.returncode != 0 and result.stdout == ""
    assert "Restart capability cannot borrow" in result.stderr
    assert not list((tmp_path / "traces").iterdir())


@pytest.mark.parametrize("family", NEW_FAMILIES)
@pytest.mark.parametrize("index", range(4))
def test_actual_preload_admits_each_exact_new_literal_without_credit(tmp_path, authority, family, index):
    case, context = _setup(tmp_path, authority, family, index=index)
    result = _invoke(tmp_path, authority, context, family, "--eval", "process.stdout.write('ADMITTED')")
    assert result.returncode == 0 and result.stdout == "ADMITTED", result.stderr
    rows = _rows(tmp_path)
    receipts = [row for row in rows if row["event"] == FAMILIES[family][2] + "-bootstrap"]
    assert len(receipts) == 1
    assert receipts[0]["profile"] == context[FAMILIES[family][1]]
    assert receipts[0]["profile"]["caseId"] == case["id"]
    assert receipts[0]["profile"]["acceptancePointsAwarded"] == 0
    assert not any(row.get("kind") == "release" for row in rows)


@pytest.mark.parametrize(("target", "supplied"), NEW_BORROWING + OLDER_BORROWING)
def test_profile_context_borrowing_is_rejected_in_both_directions(tmp_path, authority, target, supplied):
    _, context = _setup(tmp_path, authority, supplied)
    result = _invoke(tmp_path, authority, context, target, "--eval", "process.stdout.write('UNEXPECTED')")
    _assert_preload_rejection(tmp_path, result)


@pytest.mark.parametrize(("target", "supplied"), NEW_BORROWING + OLDER_BORROWING)
def test_literal_id_and_its_correct_digest_cannot_cross_families(tmp_path, authority, target, supplied):
    _, context = _setup(tmp_path, authority, target)
    module = FAMILIES[supplied][0]
    borrowed = module.build_cases()[0]
    context[FAMILIES[target][1]].update(caseId=borrowed["id"], caseWireSha256=module.CASE_HASHES[borrowed["id"]])
    result = _invoke(tmp_path, authority, context, target, "--eval", "process.stdout.write('UNEXPECTED')")
    _assert_preload_rejection(tmp_path, result)


@pytest.mark.parametrize(("target", "supplied"), NEW_BORROWING)
def test_new_entries_reject_other_familys_actual_stdin_before_actor_imports(tmp_path, authority, target, supplied):
    _, context = _setup(tmp_path, authority, target)
    module = FAMILIES[supplied][0]
    wire = module.case_wire(module.build_cases()[0])
    entry = ROOT / "equivalence" / (FAMILIES[target][2] + "-entry.mjs")
    result = _invoke(tmp_path, authority, context, target, str(entry), stdin=wire.decode())
    assert result.returncode != 0
    returned = json.loads(result.stdout)
    assert returned["ok"] is False and "protected input binding" in returned["error"]["message"]
    rows = _rows(tmp_path)
    assert not any(row.get("kind") == "release" for row in rows)
    assert not any(row.get("path", "").endswith("/host-restart-runtime.mjs") for row in rows)


@pytest.mark.parametrize("family", NEW_FAMILIES)
@pytest.mark.parametrize("mutation", ["publication-owner", "source-mtime", "reader-prompt", "lifecycle-selector"])
def test_changed_wire_and_rehashed_profile_still_cannot_expand_authority(tmp_path, authority, family, mutation):
    case, context = _setup(tmp_path, authority, family)
    if mutation == "publication-owner":
        case["input"]["policy"]["producerPublication"]["operation"] = "replace-the-real-index-owner"
    elif mutation == "source-mtime":
        case["input"]["policy"]["sourceMtimeMs"] += 1000
    elif mutation == "reader-prompt":
        case["input"]["phases"][1]["recall"]["prompt"] += " The old answer is supplied."
    else:
        case["input"]["policy"]["indexLifecycle"] = "undeclared-lifecycle"
    wire = FAMILIES[family][0].case_wire(case)
    context[FAMILIES[family][1]]["caseWireSha256"] = hashlib.sha256(wire).hexdigest()
    result = _invoke(tmp_path, authority, context, family, "--eval", "process.stdout.write('UNEXPECTED')", stdin=wire.decode())
    _assert_preload_rejection(tmp_path, result)


@pytest.mark.parametrize("family", NEW_FAMILIES)
@pytest.mark.parametrize("carrier", ["hostRestartProfile", "hostRestartPolicyProfile", "sibling-profile",
                                     "casePath", "nested-casePath", "approvedReferenceSources", "fixtureSourceCaptures"])
def test_new_preloads_reject_mixed_capabilities_and_full_case_carriers(tmp_path, authority, family, carrier):
    _, context = _setup(tmp_path, authority, family)
    if carrier == "nested-casePath":
        context[FAMILIES[family][1]]["casePath"] = str(tmp_path / "producer-answer.json")
    elif carrier == "sibling-profile":
        sibling = "managed" if family == "publication" else "publication"
        context[FAMILIES[sibling][1]] = {}
    else:
        context[carrier] = [{}] if carrier in {"approvedReferenceSources", "fixtureSourceCaptures"} else {}
    result = _invoke(tmp_path, authority, context, family, "--eval", "process.stdout.write('UNEXPECTED')")
    _assert_preload_rejection(tmp_path, result)


@pytest.mark.parametrize("family", NEW_FAMILIES)
def test_approved_new_profile_rejects_changed_stdin_before_original_imports(tmp_path, authority, family):
    case, context = _setup(tmp_path, authority, family)
    changed = deepcopy(case)
    changed["input"]["phases"][0]["write"]["text"] += " An undeclared fact."
    entry = ROOT / "equivalence" / (FAMILIES[family][2] + "-entry.mjs")
    result = _invoke(tmp_path, authority, context, family, str(entry), stdin=FAMILIES[family][0].case_wire(changed).decode())
    assert result.returncode != 0
    returned = json.loads(result.stdout)
    assert returned["ok"] is False and "protected input binding" in returned["error"]["message"]
    assert not any(row.get("kind") == "release" for row in _rows(tmp_path))
    assert not any(row.get("path", "").endswith("/host-restart-runtime.mjs") for row in _rows(tmp_path))


@pytest.mark.parametrize("family", NEW_FAMILIES)
def test_exact_independent_new_preload_is_inherited_by_real_esm_worker(tmp_path, authority, family):
    _, context = _setup(tmp_path, authority, family, index=2)
    entry = str(ROOT / "equivalence/model-runtime-observation.mjs")
    script = ("const {Worker}=require('node:worker_threads'); const w=new Worker("
              + json.dumps(entry) + "); w.on('error',e=>{throw e;});")
    result = _invoke(tmp_path, authority, context, family, "--eval", script)
    assert result.returncode == 0, result.stderr
    rows = _rows(tmp_path)
    bootstraps = [row for row in rows if row["event"] == "bootstrap"]
    receipts = [row for row in rows if row["event"] == FAMILIES[family][2] + "-bootstrap"]
    assert len(bootstraps) == len(receipts) == 2
    assert len({row["pid"] for row in receipts}) == 1
    assert len({row["threadId"] for row in receipts}) == 2
    assert {row["isMainThread"] for row in bootstraps} == {True, False}
    assert all(row["profile"] == context[FAMILIES[family][1]] for row in receipts)
    assert all(row["runtime"] == authority for row in bootstraps)
    assert all(row["fetchDenied"] and row["providerMode"] == "none" for row in bootstraps)
    assert not any(row.get("kind") == "release" for row in rows)
