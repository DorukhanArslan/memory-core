"""Actual Node admissions/denials for the independent six-schedule capability.

These tests exercise the actual preloads, entries and inherited worker clock.
They do not supply an original host observation or award acceptance credit.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

import pytest

from equivalence import host_turn_barrier as outcomes
from equivalence import host_turn_barrier_boundaries as boundaries
from equivalence.host_restart_native import digest
from equivalence import host_turn_barrier_native as old_native
from equivalence import host_turn_barrier_boundaries_native as native
from equivalence.model_runtime_authority import prepare_model_node_authority


ROOT = Path(__file__).resolve().parents[2]
FAMILIES = {"boundaries": (boundaries, native), "outcomes": (outcomes, old_native)}
TARGET = next(index for index, case in enumerate(boundaries.build_cases())
              if case["input"]["scenario"] == "target-open-preparation")


@pytest.fixture(scope="module")
def authority():
    executable = Path(os.environ.get("MEMORY_EQ_NODE", ROOT / "work/node-v24.16.0-linux-x64/bin/node"))
    if not executable.is_file():
        pytest.skip("The approved Node executable is required for genuine boundary capability guards")
    return prepare_model_node_authority(executable)


def _python_fixture():
    helper = ROOT / "equivalence" / native.LEASE_HELPER
    executable = Path(sys.executable).resolve(strict=True)
    return {"helper": {"path": str(helper), "sha256": digest(helper)},
            "python": {"execPath": str(executable), "sha256": digest(executable),
                       "version": platform.python_version()}}


def _setup(tmp_path, authority, *, family="boundaries", index=0):
    module, transport = FAMILIES[family]
    case = module.build_cases()[index]
    for name in ("traces", "evidence", "state"):
        (tmp_path / name).mkdir()
    names = transport.LOCAL
    lease = family == "boundaries" and index == TARGET
    if lease:
        names = (*names, native.LEASE_HELPER)
    provider = ROOT / "equivalence" / transport.PROVIDER
    context = {
        "schemaVersion": 1, "kind": "release-oracle-execution",
        "runtime": {"packages": [], "runtimeRoot": str(tmp_path / "unavailable-original-runtime")},
        "providerMode": "none", "fetchPolicy": "deny", "approvedNodeRuntime": deepcopy(authority),
        transport.PROFILE_KEY: {
            "kind": transport.PROFILE_KIND, "operation": case["operation"], "caseId": case["id"],
            "caseWireSha256": module.CASE_HASHES[case["id"]], "clockNowMs": case["input"]["nowMs"],
            "nodeRuntime": deepcopy(authority), "acceptancePointsAwarded": 0,
        },
        "allowedLocal": [{"path": str(ROOT / "equivalence" / name),
                          "sha256": digest(ROOT / "equivalence" / name)} for name in names],
        "traceDirectory": str(tmp_path / "traces"), "evidenceDirectory": str(tmp_path / "evidence"),
        "stateDirectory": str(tmp_path / "state"), "configPath": str(tmp_path / "state/openclaw.json"),
        "approvedReferenceSources": [], "fixtureSourceCaptures": [
            {"basename": "index.mjs", "capturePackage": "host-turn-barrier-provider",
             "sourcePath": str(provider), "sha256": digest(provider)}],
    }
    if family == "boundaries":
        context["leaseFixture"] = _python_fixture() if lease else None
    return case, context


def _invoke(tmp_path, authority, context, *arguments, family="boundaries", stdin=""):
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps(context), encoding="utf8")
    preload = ROOT / "equivalence" / FAMILIES[family][1].PRELOAD
    return subprocess.run([authority["execPath"], *arguments], input=stdin, text=True,
                          capture_output=True, timeout=15, env={
                              "PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC",
                              "MEMORY_EQ_RELEASE_CONTEXT": str(context_path),
                              "NODE_OPTIONS": f"--import={preload}",
                          })


def _rows(tmp_path):
    return [json.loads(line) for path in sorted((tmp_path / "traces").glob("*.jsonl"))
            for line in path.read_text().splitlines()]


def _no_original_or_actor(tmp_path):
    rows = _rows(tmp_path)
    assert not any(row.get("kind") == "release" for row in rows)
    assert not any(row.get("path", "").endswith("/" + native.ACTOR) for row in rows)


def _denied(result, tmp_path):
    assert result.returncode != 0 and result.stdout == "", result.stdout
    _no_original_or_actor(tmp_path)


@pytest.mark.parametrize("index", range(6))
def test_all_six_exact_literals_are_admitted_with_zero_credit_and_date_only_clock(tmp_path, authority, index):
    case, context = _setup(tmp_path, authority, index=index)
    result = _invoke(tmp_path, authority, context, "--eval", "process.stdout.write(String(Date.now()))")
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(case["input"]["nowMs"])
    rows = _rows(tmp_path)
    bootstrap = next(row for row in rows if row["event"] == "bootstrap")
    expected_python = ({**context["leaseFixture"]["python"], "implementation": sys.implementation.name}
                       if index == TARGET else None)
    assert bootstrap["leasePythonIdentity"] == expected_python
    receipt = next(row for row in rows if row["event"] == native.BOOTSTRAP_EVENT)
    assert receipt["profile"] == context[native.PROFILE_KEY]
    assert receipt["profile"]["acceptancePointsAwarded"] == 0
    assert receipt["clock"] == {"owner": "node:test", "apis": ["Date"], "nowMs": case["input"]["nowMs"],
                                "dateConstructorReplaced": True, "setTimeoutUnchanged": True,
                                "performanceNowUnchanged": True}
    assert (context["leaseFixture"] is not None) is (index == TARGET)
    _no_original_or_actor(tmp_path)


@pytest.mark.parametrize("attack", ["hash", "extra-profile", "clock", "clock-scope", "self-credit",
                                    "wrong-operation", "node-sha", "node-version", "node-profile",
                                    "source-substitution", "provider-package", "provider-source"])
def test_changed_authority_is_rejected_before_any_original_import(tmp_path, authority, attack):
    _, context = _setup(tmp_path, authority)
    profile = context[native.PROFILE_KEY]
    if attack == "hash":
        profile["caseWireSha256"] = "0" * 64
    elif attack == "extra-profile":
        context[old_native.PROFILE_KEY] = deepcopy(profile)
    elif attack == "clock":
        profile["clockNowMs"] += 1
    elif attack == "clock-scope":
        profile["clockScope"] = "main-thread-only"
    elif attack == "self-credit":
        profile["acceptancePointsAwarded"] = 1
    elif attack == "wrong-operation":
        profile["operation"] = outcomes.OPERATION
    elif attack in {"node-sha", "node-version"}:
        key, value = ("sha256", "0" * 64) if attack == "node-sha" else ("nodeVersion", "v24.15.0")
        profile["nodeRuntime"][key] = context["approvedNodeRuntime"][key] = value
    elif attack == "node-profile":
        profile["nodeRuntime"]["sha256"] = "0" * 64
    elif attack == "source-substitution":
        context["approvedReferenceSources"] = [{"path": "forged.ts", "sha256": "0" * 64}]
    elif attack == "provider-package":
        context["fixtureSourceCaptures"][0]["capturePackage"] = "equivalence"
    else:
        context["fixtureSourceCaptures"][0]["sourcePath"] = str(ROOT / "equivalence/flush-execution.mjs")
    _denied(_invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')"), tmp_path)


@pytest.mark.parametrize("attack", ["extra", "missing", "duplicate", "changed-hash"])
def test_the_new_local_authority_remains_an_exact_closed_set(tmp_path, authority, attack):
    _, context = _setup(tmp_path, authority)
    local = context["allowedLocal"]
    if attack == "extra":
        unowned = tmp_path / "unowned.mjs"
        unowned.write_text("process.stdout.write('UNEXPECTED')")
        local.append({"path": str(unowned), "sha256": digest(unowned)})
    elif attack == "missing":
        local.pop()
    elif attack == "duplicate":
        local[-1] = deepcopy(local[0])
    else:
        local[-1]["sha256"] = "0" * 64
    _denied(_invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')"), tmp_path)


@pytest.mark.parametrize(("target", "supplied"), [("boundaries", "outcomes"), ("outcomes", "boundaries")])
def test_neither_preload_accepts_the_other_full_profile(tmp_path, authority, target, supplied):
    _, context = _setup(tmp_path, authority, family=supplied)
    _denied(_invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')",
                    family=target), tmp_path)


@pytest.mark.parametrize("family", ["boundaries", "outcomes"])
def test_a_foreign_case_with_its_genuine_hash_cannot_expand_either_profile(tmp_path, authority, family):
    _, context = _setup(tmp_path, authority, family=family)
    target_module, transport = FAMILIES[family]
    foreign_module, _ = FAMILIES["outcomes" if family == "boundaries" else "boundaries"]
    foreign = foreign_module.build_cases()[0]
    context[transport.PROFILE_KEY].update(caseId=foreign["id"],
                                        caseWireSha256=foreign_module.CASE_HASHES[foreign["id"]])
    assert foreign["id"] not in target_module.CASE_HASHES
    _denied(_invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')",
                    family=family), tmp_path)


@pytest.mark.parametrize("family", ["boundaries", "outcomes"])
def test_each_profile_rejects_the_other_entry_before_loading_its_actor(tmp_path, authority, family):
    _, context = _setup(tmp_path, authority, family=family)
    foreign = FAMILIES["outcomes" if family == "boundaries" else "boundaries"][1]
    result = _invoke(tmp_path, authority, context, str(ROOT / "equivalence" / foreign.ENTRY), family=family)
    _denied(result, tmp_path)
    assert "Unverified whole-caller module" in result.stderr


@pytest.mark.parametrize("index", range(6))
def test_changed_input_with_a_self_consistent_hash_is_not_an_approved_case(tmp_path, authority, index):
    case, context = _setup(tmp_path, authority, index=index)
    case["input"]["followup"]["prompt"] += " The fact is injected."
    wire = boundaries.case_wire(case)
    context[native.PROFILE_KEY]["caseWireSha256"] = hashlib.sha256(wire).hexdigest()
    _denied(_invoke(tmp_path, authority, context, str(ROOT / "equivalence" / native.ENTRY),
                    stdin=wire.decode()), tmp_path)


@pytest.mark.parametrize("wire", ["changed", "foreign"])
def test_actual_entry_rejects_changed_stdin_before_actor_or_original_import(tmp_path, authority, wire):
    case, context = _setup(tmp_path, authority)
    if wire == "changed":
        case["input"]["nowMs"] += 1
        supplied = boundaries.case_wire(case)
    else:
        supplied = outcomes.case_wire(outcomes.build_cases()[0])
    result = _invoke(tmp_path, authority, context, str(ROOT / "equivalence" / native.ENTRY), stdin=supplied.decode())
    assert result.returncode != 0
    returned = json.loads(result.stdout)
    assert returned["ok"] is False and "literal changed" in returned["error"]["message"]
    _no_original_or_actor(tmp_path)


@pytest.mark.parametrize("index", [0, TARGET])
def test_real_esm_worker_inherits_only_the_date_fixture_and_keeps_real_timers(tmp_path, authority, index):
    case, context = _setup(tmp_path, authority, index=index)
    # The original workers are ESM. Execute an existing exact allowed ESM file,
    # without replacing source or adding an unreviewed worker to the capability.
    entry = (ROOT / "equivalence" / native.PROVIDER).as_uri()
    script = ("const {Worker}=require('node:worker_threads');const started=performance.now();"
              "const worker=new Worker(new URL(" + json.dumps(entry) + "));"
              "worker.once('error',error=>{throw error;});"
              "worker.once('exit',code=>setTimeout(()=>process.stdout.write(JSON.stringify({code,"
              "mainNow:Date.now(),constructed:new Date().getTime(),elapsed:performance.now()-started})),5));")
    result = _invoke(tmp_path, authority, context, "--eval", script)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["code"] == 0 and observed["elapsed"] > 0
    assert observed["mainNow"] == observed["constructed"] == case["input"]["nowMs"]
    receipts = [row for row in _rows(tmp_path) if row["event"] == native.BOOTSTRAP_EVENT]
    assert len(receipts) == 2 and len({row["threadId"] for row in receipts}) == 2
    for row in receipts:
        assert row["profile"] == context[native.PROFILE_KEY]
        assert row["clock"]["nowMs"] == case["input"]["nowMs"]
        assert row["clock"]["apis"] == ["Date"]
        assert row["clock"]["setTimeoutUnchanged"] is True
        assert row["clock"]["performanceNowUnchanged"] is True
    _no_original_or_actor(tmp_path)


@pytest.mark.parametrize("attack", ["missing", "null", "extra-key", "wrong-helper", "helper-sha",
                                    "unlisted-helper", "relocated-helper", "helper-alias", "python-relative",
                                    "python-sha", "python-alias", "python-version", "borrow-node", "unknown-version"])
def test_target_schedule_requires_its_owned_helper_and_actual_python_identity(tmp_path, authority, attack):
    _, context = _setup(tmp_path, authority, index=TARGET)
    fixture = context["leaseFixture"]
    if attack == "missing":
        del context["leaseFixture"]
    elif attack == "null":
        context["leaseFixture"] = None
    elif attack == "extra-key":
        fixture["sourceCapture"] = "another-script"
    elif attack == "wrong-helper":
        fixture["helper"]["path"] = str(ROOT / "equivalence/host_turn_barrier_boundaries.py")
        fixture["helper"]["sha256"] = digest(fixture["helper"]["path"])
    elif attack == "helper-sha":
        fixture["helper"]["sha256"] = "0" * 64
    elif attack == "unlisted-helper":
        context["allowedLocal"] = [row for row in context["allowedLocal"]
                                   if row["path"] != fixture["helper"]["path"]]
    elif attack == "relocated-helper":
        copy = tmp_path / "foreign/equivalence" / native.LEASE_HELPER
        copy.parent.mkdir(parents=True)
        copy.write_bytes(Path(fixture["helper"]["path"]).read_bytes())
        original = fixture["helper"]["path"]
        fixture["helper"]["path"] = str(copy)
        for row in context["allowedLocal"]:
            if row["path"] == original:
                row["path"] = str(copy)
    elif attack in {"helper-alias", "python-alias"}:
        section, field = ("helper", "path") if attack == "helper-alias" else ("python", "execPath")
        alias = tmp_path / "alias"
        alias.symlink_to(fixture[section][field])
        fixture[section][field] = str(alias)
    elif attack == "python-relative":
        fixture["python"]["execPath"] = "python"
    elif attack == "python-sha":
        fixture["python"]["sha256"] = "0" * 64
    elif attack == "python-version":
        fixture["python"]["version"] = "3.12.0" if platform.python_version().startswith("3.11.") else "3.11.0"
    elif attack == "borrow-node":
        fixture["python"].update(execPath=authority["execPath"], sha256=authority["sha256"])
    else:
        fixture["python"]["version"] = "3.10.99"
    result = _invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')")
    _denied(result, tmp_path)


@pytest.mark.parametrize("index", [0, 2, 3, 4, 5])
def test_other_schedules_cannot_borrow_the_physical_target_fixture(tmp_path, authority, index):
    _, context = _setup(tmp_path, authority, index=index)
    context["leaseFixture"] = _python_fixture()
    context["allowedLocal"].append(context["leaseFixture"]["helper"].copy())
    _denied(_invoke(tmp_path, authority, context, "--eval", "process.stdout.write('UNEXPECTED')"), tmp_path)


def test_unlisted_local_source_and_network_transport_are_denied(tmp_path, authority):
    _, context = _setup(tmp_path, authority)
    source = tmp_path / "unowned.mjs"
    source.write_text("process.stdout.write('UNEXPECTED')")
    result = _invoke(tmp_path, authority, context, "--eval", f"import({json.dumps(source.as_uri())})")
    _denied(result, tmp_path)
    assert "Unverified whole-caller module" in result.stderr
    result = _invoke(tmp_path, authority, context, "--eval", "fetch('https://fixture.invalid')")
    _denied(result, tmp_path)
    assert "Network disabled" in result.stderr
    assert any(row.get("event") == "network-denied" for row in _rows(tmp_path))
