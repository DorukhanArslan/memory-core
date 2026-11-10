"""Real process/worker guards keep the update/isolation capability independently closed."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from equivalence import host_restart_session, host_update_isolation
from equivalence.host_restart_native import SESSION_LOCAL, digest
from equivalence.host_update_isolation_native import (
    BOOTSTRAP_EVENT, COORDINATOR, ENTRY, LOCAL, PRELOAD, PROFILE_KEY, PROFILE_KIND, run_native_case,
)
from equivalence.model_runtime_authority import prepare_model_node_authority


ROOT = Path(__file__).resolve().parents[2]
FAMILIES = {
    "update": (host_update_isolation, PROFILE_KEY, PRELOAD, LOCAL, PROFILE_KIND, "Update capability cannot borrow"),
    "restart": (host_restart_session, "hostRestartSessionProfile", "host-restart-session-preload.mjs", SESSION_LOCAL,
                "host-restart-session-acceptance", "Restart capability cannot borrow"),
}
BORROWING = [("update", "restart"), ("restart", "update")]


@pytest.fixture(scope="module")
def authority():
    node = Path(os.environ.get("MEMORY_EQ_NODE", ROOT / "work/node-v24.16.0-linux-x64/bin/node"))
    if not node.is_file():
        pytest.skip("The approved Node executable is required for actual update capability guards")
    return prepare_model_node_authority(node)


def _setup(tmp_path, authority, family="update", *, index=0):
    module, profile_key, _, local, kind, _ = FAMILIES[family]
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
    env = {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
           "MEMORY_EQ_RELEASE_CONTEXT": str(filename),
           "NODE_OPTIONS": f'--import={ROOT / "equivalence" / FAMILIES[family][2]}'}
    return subprocess.run([authority["execPath"], *arguments], input=stdin, env=env,
                          capture_output=True, text=True, timeout=15)


def _rows(tmp_path):
    return [json.loads(line) for path in sorted((tmp_path / "traces").glob("*.jsonl"))
            for line in path.read_text().splitlines()]


def _assert_rejected(tmp_path, result, family="update"):
    assert result.returncode != 0 and result.stdout == ""
    assert FAMILIES[family][5] in result.stderr
    assert not list((tmp_path / "traces").iterdir())


@pytest.mark.parametrize("index", range(4))
def test_new_preload_admits_exact_frozen_literal_without_self_awarding_credit(tmp_path, authority, index):
    case, context = _setup(tmp_path, authority, index=index)
    result = _invoke(tmp_path, authority, context, "update", "--eval", "process.stdout.write('ADMITTED')")
    assert result.returncode == 0 and result.stdout == "ADMITTED", result.stderr
    rows = _rows(tmp_path)
    receipts = [row for row in rows if row["event"] == BOOTSTRAP_EVENT]
    assert len(receipts) == 1
    assert receipts[0]["profile"] == context[PROFILE_KEY]
    assert receipts[0]["profile"]["caseId"] == case["id"]
    assert receipts[0]["profile"]["acceptancePointsAwarded"] == 0
    assert not any(row.get("kind") == "release" for row in rows)


@pytest.mark.parametrize(("target", "supplied"), BORROWING)
def test_update_and_restart_profile_contexts_cannot_borrow_each_other(tmp_path, authority, target, supplied):
    _, context = _setup(tmp_path, authority, supplied)
    result = _invoke(tmp_path, authority, context, target, "--eval", "process.stdout.write('UNEXPECTED')")
    _assert_rejected(tmp_path, result, target)


@pytest.mark.parametrize(("target", "supplied"), BORROWING)
def test_a_correct_foreign_case_hash_cannot_expand_either_family(tmp_path, authority, target, supplied):
    _, context = _setup(tmp_path, authority, target)
    module = FAMILIES[supplied][0]
    borrowed = module.build_cases()[0]
    context[FAMILIES[target][1]].update(caseId=borrowed["id"], caseWireSha256=module.CASE_HASHES[borrowed["id"]])
    result = _invoke(tmp_path, authority, context, target, "--eval", "process.stdout.write('UNEXPECTED')")
    _assert_rejected(tmp_path, result, target)


def test_new_entry_rejects_foreign_stdin_before_actual_runtime_import(tmp_path, authority):
    _, context = _setup(tmp_path, authority)
    borrowed = host_restart_session.case_wire(host_restart_session.build_cases()[0]).decode()
    result = _invoke(tmp_path, authority, context, "update", str(ROOT / "equivalence" / ENTRY), stdin=borrowed)
    assert result.returncode != 0
    returned = json.loads(result.stdout)
    assert returned["ok"] is False and "protected input binding" in returned["error"]["message"]
    assert not any(row.get("kind") == "release" for row in _rows(tmp_path))
    assert not any(row.get("path", "").endswith("/" + COORDINATOR) for row in _rows(tmp_path))


@pytest.mark.parametrize("mutation", ["fault-added", "fault-removed", "old-entry", "reader-prompt", "source-mtime",
                                      "lifecycle", "isolated-agent"])
def test_changed_case_with_self_consistent_hash_is_not_an_approved_literal(tmp_path, authority, mutation):
    case, context = _setup(tmp_path, authority, index=2 if mutation == "fault-removed" else 0)
    update = case["input"]["phases"][1]
    if mutation == "fault-added":
        update["fault"] = {"operation": "index-publication-sidecar-symlink"}
    elif mutation == "fault-removed":
        del update["fault"]
    elif mutation == "old-entry":
        update["update"]["old"] = case["input"]["phases"][0]["save"]["entries"][1]["text"]
    elif mutation == "reader-prompt":
        update["recalls"]["current"]["prompt"] += " The saved drink is supplied."
    elif mutation == "source-mtime":
        case["input"]["policy"]["sourceMtimeMs"] += 1
    elif mutation == "lifecycle":
        case["input"]["policy"]["indexLifecycle"] = "managed"
    else:
        case["input"]["identity"]["isolatedAgentId"] = case["input"]["identity"]["agentId"]
    context[PROFILE_KEY]["caseWireSha256"] = hashlib.sha256(host_update_isolation.case_wire(case)).hexdigest()
    result = _invoke(tmp_path, authority, context, "update", "--eval", "process.stdout.write('UNEXPECTED')")
    _assert_rejected(tmp_path, result)


@pytest.mark.parametrize("carrier", ["sibling", "casePath", "nested-casePath", "approvedReferenceSources",
                                     "fixtureSourceCaptures", "claimed-credit", "claimed-covers"])
def test_update_profile_rejects_other_capabilities_input_carriers_or_self_credit(tmp_path, authority, carrier):
    _, context = _setup(tmp_path, authority)
    if carrier == "sibling":
        context["hostRestartSessionProfile"] = {}
    elif carrier == "nested-casePath":
        context[PROFILE_KEY]["casePath"] = "full-producer-input.json"
    elif carrier == "claimed-credit":
        context[PROFILE_KEY]["acceptancePointsAwarded"] = 2
    elif carrier == "claimed-covers":
        context[PROFILE_KEY]["covers"] = list(host_update_isolation.POINTS)
    else:
        context[carrier] = [{}] if carrier in {"approvedReferenceSources", "fixtureSourceCaptures"} else {}
    result = _invoke(tmp_path, authority, context, "update", "--eval", "process.stdout.write('UNEXPECTED')")
    _assert_rejected(tmp_path, result)


def test_update_entry_rejects_changed_stdin_before_actor_import(tmp_path, authority):
    case, context = _setup(tmp_path, authority)
    case["input"]["phases"][1]["update"]["new"] += " An undeclared fact."
    result = _invoke(tmp_path, authority, context, "update", str(ROOT / "equivalence" / ENTRY),
                     stdin=host_update_isolation.case_wire(case).decode())
    assert result.returncode != 0
    assert "protected input binding" in json.loads(result.stdout)["error"]["message"]
    assert not any(row.get("path", "").endswith("/" + COORDINATOR) for row in _rows(tmp_path))


def test_update_preload_is_inherited_by_real_esm_worker(tmp_path, authority):
    _, context = _setup(tmp_path, authority, index=3)
    entry = str(ROOT / "equivalence/model-runtime-observation.mjs")
    script = ("const {Worker}=require('node:worker_threads'); const w=new Worker("
              + json.dumps(entry) + "); w.on('error',e=>{throw e;});")
    result = _invoke(tmp_path, authority, context, "update", "--eval", script)
    assert result.returncode == 0, result.stderr
    rows = _rows(tmp_path)
    bootstraps = [row for row in rows if row["event"] == "bootstrap"]
    receipts = [row for row in rows if row["event"] == BOOTSTRAP_EVENT]
    assert len(bootstraps) == len(receipts) == 2
    assert len({row["pid"] for row in receipts}) == 1 and len({row["threadId"] for row in receipts}) == 2
    assert {row["isMainThread"] for row in bootstraps} == {True, False}
    assert all(row["profile"] == context[PROFILE_KEY] for row in receipts)
    assert all(row["runtime"] == authority and row["fetchDenied"] and row["providerMode"] == "none"
               for row in bootstraps)


def test_python_update_transport_refuses_foreign_or_changed_literal_before_io(tmp_path):
    destination = tmp_path / "unadmitted"
    with pytest.raises(ValueError):
        run_native_case(host_restart_session.build_cases()[0], tmp_path / "unknown-node", {}, destination)
    changed = host_update_isolation.build_cases()[0]
    changed["input"]["nowMs"] += 1
    with pytest.raises(ValueError):
        run_native_case(changed, tmp_path / "unknown-node", {}, destination)
    assert not destination.exists()


def test_preload_map_matches_exact_new_family_without_restart_literals():
    source = (ROOT / "equivalence" / PRELOAD).read_text()
    for identifier, digest_ in host_update_isolation.CASE_HASHES.items():
        assert f'"{identifier}": "{digest_}"' in source
    for identifier in host_restart_session.CASE_HASHES:
        assert f'"{identifier}":' not in source
    restart = (ROOT / "equivalence/host-restart-session-preload.mjs").read_text()
    for identifier in host_update_isolation.CASE_HASHES:
        assert f'"{identifier}":' not in restart


def test_update_actors_are_separate_files_and_no_restart_actor_was_changed_to_admit_them():
    restart_actors = {"host-restart-runtime.mjs", "host-restart-phase.mjs", "host-restart-phase-cli.mjs"}
    assert not restart_actors.intersection(LOCAL)
    for name in restart_actors:
        assert "host-update-isolation" not in (ROOT / "equivalence" / name).read_text()


def test_fixture_listing_records_an_entry_that_vanishes_instead_of_failing_the_host(tmp_path, authority):
    """A detached original sync deletes its lease journal on its own schedule; the listing is diagnostic."""
    tree = tmp_path / "fixture"
    (tree / "state").mkdir(parents=True)
    (tree / "state/kept.sqlite").write_bytes(b"kept")
    (tree / "state/lease.sqlite-journal").write_bytes(b"released during the listing")
    (tree / "state/unreadable.sqlite").write_bytes(b"another failure")
    script = f"""
      import fs from "node:fs/promises";
      import {{ filesystemObservation }} from {json.dumps(str(ROOT / "equivalence" / "host-update-isolation-phase.mjs"))};
      const gone = Object.assign(new Error("ENOENT: no such file or directory"), {{ code: "ENOENT" }});
      const denied = Object.assign(new Error("EACCES: permission denied"), {{ code: "EACCES" }});
      const api = (failing, error) => ({{ readdir: fs.readdir, readFile: fs.readFile,
        lstat: name => name.endsWith(failing) ? Promise.reject(error) : fs.lstat(name) }});
      const listed = await filesystemObservation(process.argv[1], api("lease.sqlite-journal", gone));
      let refused = null;
      try {{ await filesystemObservation(process.argv[1], api("unreadable.sqlite", denied)); }} catch (error) {{ refused = error.code; }}
      process.stdout.write(JSON.stringify({{ listed, refused }}));
    """
    result = subprocess.run([authority["execPath"], "--input-type=module", "--eval", script, str(tree)],
                            env={"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    rows = {row["path"]: row for row in observed["listed"]}
    assert rows["state/lease.sqlite-journal"] == {"path": "state/lease.sqlite-journal", "kind": "vanished"}
    assert rows["state/kept.sqlite"]["kind"] == "file" and rows["state/kept.sqlite"]["sha256"] == hashlib.sha256(b"kept").hexdigest()
    assert rows["state"]["kind"] == "directory" and set(rows) == {
        "state", "state/kept.sqlite", "state/lease.sqlite-journal", "state/unreadable.sqlite"}
    # Any other failure is still a host failure.
    assert observed["refused"] == "EACCES"
