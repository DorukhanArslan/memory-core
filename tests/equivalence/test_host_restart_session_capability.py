"""Real process/worker guards keep the new session capability independently closed."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from equivalence import (
    host_restart,
    host_restart_managed,
    host_restart_policy,
    host_restart_publication,
    host_restart_session,
)
from equivalence.host_restart_native import (
    LOCAL,
    MANAGED_LOCAL,
    POLICY_LOCAL,
    PUBLICATION_LOCAL,
    SESSION_LOCAL,
    _lane,
    digest,
    run_native_session_case,
)
from equivalence.model_runtime_authority import prepare_model_node_authority


ROOT = Path(__file__).resolve().parents[2]
FAMILIES = {
    "original": (host_restart, "hostRestartProfile", "host-restart", LOCAL,
                 "host-restart-recall-development"),
    "policy": (host_restart_policy, "hostRestartPolicyProfile", "host-restart-policy", POLICY_LOCAL,
               "host-restart-policy-development"),
    "publication": (host_restart_publication, "hostRestartPublicationProfile", "host-restart-publication",
                    PUBLICATION_LOCAL, "host-restart-publication-development"),
    "managed": (host_restart_managed, "hostRestartManagedProfile", "host-restart-managed", MANAGED_LOCAL,
                "host-restart-managed-development"),
    "session": (host_restart_session, "hostRestartSessionProfile", "host-restart-session", SESSION_LOCAL,
                "host-restart-session-acceptance"),
}
OLD_FAMILIES = tuple(name for name in FAMILIES if name != "session")
BORROWING = [("session", name) for name in OLD_FAMILIES] + [(name, "session") for name in OLD_FAMILIES]


@pytest.fixture(scope="module")
def authority():
    node = Path(os.environ.get("MEMORY_EQ_NODE", ROOT / "work/node-v24.16.0-linux-x64/bin/node"))
    if not node.is_file():
        pytest.skip("The approved Node executable is required for actual session capability guards")
    return prepare_model_node_authority(node)


def _setup(tmp_path, authority, family="session", *, index=0):
    module, profile_key, _, local, kind = FAMILIES[family]
    case = module.build_cases()[index]
    (tmp_path / "traces").mkdir()
    context = {
        "schemaVersion": 1, "kind": "release-oracle-execution", "runtime": {"packages": []},
        "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": authority,
        profile_key: {
            "kind": kind, "operation": case["operation"], "caseId": case["id"],
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
    env = {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
           "MEMORY_EQ_RELEASE_CONTEXT": str(filename),
           "NODE_OPTIONS": f'--import={ROOT / "equivalence" / (stem + "-preload.mjs")}' }
    return subprocess.run([authority["execPath"], *arguments], input=stdin, env=env,
                          capture_output=True, text=True, timeout=15)


def _rows(tmp_path):
    return [json.loads(line) for path in sorted((tmp_path / "traces").glob("*.jsonl"))
            for line in path.read_text().splitlines()]


def _assert_rejected(tmp_path, result):
    assert result.returncode != 0 and result.stdout == ""
    assert "Restart capability cannot borrow" in result.stderr
    assert not list((tmp_path / "traces").iterdir())


@pytest.mark.parametrize("index", range(4))
def test_new_preload_admits_exact_frozen_literal_without_self_awarding_credit(tmp_path, authority, index):
    case, context = _setup(tmp_path, authority, index=index)
    result = _invoke(tmp_path, authority, context, "session", "--eval", "process.stdout.write('ADMITTED')")
    assert result.returncode == 0 and result.stdout == "ADMITTED", result.stderr
    rows = _rows(tmp_path)
    receipts = [row for row in rows if row["event"] == "host-restart-session-bootstrap"]
    assert len(receipts) == 1
    assert receipts[0]["profile"] == context["hostRestartSessionProfile"]
    assert receipts[0]["profile"]["caseId"] == case["id"]
    assert receipts[0]["profile"]["acceptancePointsAwarded"] == 0
    assert not any(row.get("kind") == "release" for row in rows)


@pytest.mark.parametrize(("target", "supplied"), BORROWING)
def test_new_and_old_profile_contexts_cannot_borrow_each_other(tmp_path, authority, target, supplied):
    _, context = _setup(tmp_path, authority, supplied)
    result = _invoke(tmp_path, authority, context, target, "--eval", "process.stdout.write('UNEXPECTED')")
    _assert_rejected(tmp_path, result)


@pytest.mark.parametrize(("target", "supplied"), BORROWING)
def test_a_correct_foreign_case_hash_cannot_expand_any_family(tmp_path, authority, target, supplied):
    _, context = _setup(tmp_path, authority, target)
    module = FAMILIES[supplied][0]
    borrowed = module.build_cases()[0]
    context[FAMILIES[target][1]].update(caseId=borrowed["id"], caseWireSha256=module.CASE_HASHES[borrowed["id"]])
    result = _invoke(tmp_path, authority, context, target, "--eval", "process.stdout.write('UNEXPECTED')")
    _assert_rejected(tmp_path, result)


@pytest.mark.parametrize("family", OLD_FAMILIES)
def test_new_entry_rejects_foreign_stdin_before_actual_runtime_import(tmp_path, authority, family):
    _, context = _setup(tmp_path, authority)
    module = FAMILIES[family][0]
    borrowed = module.case_wire(module.build_cases()[0]).decode()
    result = _invoke(tmp_path, authority, context, "session",
                     str(ROOT / "equivalence/host-restart-session-entry.mjs"), stdin=borrowed)
    assert result.returncode != 0
    returned = json.loads(result.stdout)
    assert returned["ok"] is False and "protected input binding" in returned["error"]["message"]
    assert not any(row.get("kind") == "release" for row in _rows(tmp_path))
    assert not any(row.get("path", "").endswith("/host-restart-runtime.mjs") for row in _rows(tmp_path))


@pytest.mark.parametrize("mutation", ["lifecycle", "publication", "reader-prompt", "source-mtime"])
def test_changed_case_with_self_consistent_hash_is_not_an_approved_literal(tmp_path, authority, mutation):
    case, context = _setup(tmp_path, authority)
    if mutation == "lifecycle":
        case["input"]["policy"]["indexLifecycle"] = "managed"
    elif mutation == "publication":
        case["input"]["policy"]["producerPublication"]["operation"] = "undeclared-repair"
    elif mutation == "reader-prompt":
        case["input"]["phases"][1]["recall"]["prompt"] += " The saved drink is supplied."
    else:
        case["input"]["policy"]["sourceMtimeMs"] += 1
    context["hostRestartSessionProfile"]["caseWireSha256"] = hashlib.sha256(host_restart_session.case_wire(case)).hexdigest()
    result = _invoke(tmp_path, authority, context, "session", "--eval", "process.stdout.write('UNEXPECTED')")
    _assert_rejected(tmp_path, result)


@pytest.mark.parametrize("carrier", ["sibling", "casePath", "nested-casePath", "approvedReferenceSources",
                                     "fixtureSourceCaptures", "claimed-credit", "claimed-covers"])
def test_session_profile_rejects_other_capabilities_producer_carriers_or_self_credit(tmp_path, authority, carrier):
    _, context = _setup(tmp_path, authority)
    if carrier == "sibling":
        context["hostRestartManagedProfile"] = {}
    elif carrier == "nested-casePath":
        context["hostRestartSessionProfile"]["casePath"] = "full-producer-input.json"
    elif carrier == "claimed-credit":
        context["hostRestartSessionProfile"]["acceptancePointsAwarded"] = 2
    elif carrier == "claimed-covers":
        context["hostRestartSessionProfile"]["covers"] = list(host_restart_session.POINTS)
    else:
        context[carrier] = [{}] if carrier in {"approvedReferenceSources", "fixtureSourceCaptures"} else {}
    result = _invoke(tmp_path, authority, context, "session", "--eval", "process.stdout.write('UNEXPECTED')")
    _assert_rejected(tmp_path, result)


def test_session_entry_rejects_changed_stdin_before_actor_import(tmp_path, authority):
    case, context = _setup(tmp_path, authority)
    case["input"]["phases"][0]["write"]["text"] += " An undeclared fact."
    result = _invoke(tmp_path, authority, context, "session",
                     str(ROOT / "equivalence/host-restart-session-entry.mjs"),
                     stdin=host_restart_session.case_wire(case).decode())
    assert result.returncode != 0
    assert "protected input binding" in json.loads(result.stdout)["error"]["message"]
    assert not any(row.get("path", "").endswith("/host-restart-runtime.mjs") for row in _rows(tmp_path))


def test_session_preload_is_inherited_by_real_esm_worker(tmp_path, authority):
    _, context = _setup(tmp_path, authority, index=2)
    entry = str(ROOT / "equivalence/model-runtime-observation.mjs")
    script = ("const {Worker}=require('node:worker_threads'); const w=new Worker("
              + json.dumps(entry) + "); w.on('error',e=>{throw e;});")
    result = _invoke(tmp_path, authority, context, "session", "--eval", script)
    assert result.returncode == 0, result.stderr
    rows = _rows(tmp_path)
    bootstraps = [row for row in rows if row["event"] == "bootstrap"]
    receipts = [row for row in rows if row["event"] == "host-restart-session-bootstrap"]
    assert len(bootstraps) == len(receipts) == 2
    assert len({row["pid"] for row in receipts}) == 1 and len({row["threadId"] for row in receipts}) == 2
    assert {row["isMainThread"] for row in bootstraps} == {True, False}
    assert all(row["profile"] == context["hostRestartSessionProfile"] for row in receipts)
    assert all(row["runtime"] == authority and row["fetchDenied"] and row["providerMode"] == "none"
               for row in bootstraps)


def test_python_session_transport_uses_its_own_lane_and_refuses_foreign_literal_before_io(tmp_path):
    assert _lane(True, True, session_managed=True) == (
        "hostRestartSessionProfile", "host-restart-session-bootstrap",
        "host-restart-session-preload.mjs", "host-restart-session-entry.mjs",
        "host-restart-session-acceptance", SESSION_LOCAL,
    )
    for args in ((False, False, False, True), (True, False, False, True), (True, True, True, True)):
        with pytest.raises(ValueError):
            _lane(*args)
    destination = tmp_path / "unadmitted"
    with pytest.raises(ValueError):
        run_native_session_case(host_restart_managed.build_cases()[0], tmp_path / "unknown-node", {}, destination)
    assert not destination.exists()


def test_preload_map_matches_exact_new_family_without_old_literals():
    source = (ROOT / "equivalence/host-restart-session-preload.mjs").read_text()
    for identifier, digest_ in host_restart_session.CASE_HASHES.items():
        assert f'"{identifier}": "{digest_}"' in source
    for name in OLD_FAMILIES:
        for identifier in FAMILIES[name][0].CASE_HASHES:
            assert f'"{identifier}":' not in source
