"""Labelled delegation fixtures test gate routing, never original host behavior."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from equivalence import harness, release_runtime
from equivalence.cases import run_python
from equivalence.harness import HarnessError, _oracle
from equivalence.host_update_isolation import POINTS, build_cases
from equivalence.host_restart_bindings import CANONICAL_PUBLICATION_WORKER_ARTIFACTS, PRODUCER_WORKER_ROUTES
from equivalence.host_update_isolation_bindings import ADDITIONAL_REQUIRED_HOST_ARTIFACTS
from equivalence.host_update_isolation_native import (
    BOOTSTRAP_EVENT, COORDINATOR, ENTRY, NATIVE_KIND, PHASE_ACTORS, PRELOAD, PROFILE_KEY,
    required_host_artifacts, validate_traces,
)

ROOT = Path(__file__).resolve().parents[2]
RUNNER = "equivalence.host_update_isolation_native.run_native_case"


def test_host_update_requires_release_authority_before_dispatch(tmp_path, monkeypatch):
    dispatched = []
    monkeypatch.setattr(RUNNER, lambda *args, **kwargs: dispatched.append(args))
    with pytest.raises(HarnessError, match="authenticated release runtime"):
        _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
                [build_cases()[0]], 60)
    assert dispatched == []


@pytest.mark.parametrize("kind", ["official-release-host-restart-acceptance", "official-release-runtime-comparison"])
def test_other_or_generic_capability_cannot_claim_whole_host_update_acceptance(tmp_path, monkeypatch, kind):
    dispatched = []

    def fixture(*args, **kwargs):
        dispatched.append((args, kwargs))
        return {"kind": kind}

    monkeypatch.setattr("equivalence.harness.ROOT", tmp_path)
    monkeypatch.setattr(RUNNER, fixture)
    with pytest.raises(HarnessError, match="no retry") as failure:
        _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
                [build_cases()[0]], 60, release_runtime={"label": "unexecuted transport fixture"})
    assert len(dispatched) == 1
    assert failure.value.rejected_evidence["coverageCredit"] is False
    assert failure.value.rejected_evidence["caseIds"] == [build_cases()[0]["id"]]


def test_native_transport_retains_exact_result_and_actual_raw_file(tmp_path, monkeypatch):
    case = build_cases()[0]
    raw = [{"label": "unit transport fixture, not authenticated host evidence"}]
    result = {"kept": [0, False, None], "nested": {"value": "complete payload"}}
    trace = {"label": "unit trace fixture"}

    def fixture(selected, node, runtime, directory, *, timeout):
        assert selected == case and timeout == 60
        evidence = directory / "evidence"
        evidence.mkdir(parents=True)
        (evidence / "native-raw.json").write_text(json.dumps(raw))
        return {"kind": NATIVE_KIND, "results": [
            {"id": case["id"], "ok": True, "result": result}],
            "releaseSources": [{"label": "unit source fixture"}], "releaseTrace": trace,
            "runtimeDiagnostics": raw, "evidenceDirectory": str(directory)}

    monkeypatch.setattr("equivalence.harness.ROOT", tmp_path)
    monkeypatch.setattr(RUNNER, fixture)
    returned = _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
                       [case], 60, release_runtime={"label": "unit runtime fixture"})
    assert returned["kind"] == "official-release-runtime-comparison"
    assert returned["sources"] == []
    assert returned["results"] == [{"id": case["id"], "ok": True, "result": result}]
    assert returned["releaseTrace"] == trace
    assert returned["runtimeDiagnostics"][0]["rawSnapshots"] == raw
    assert returned["runtimeDiagnostics"][0]["validationStatus"] == "verified"
    assert Path(returned["evidenceDirectory"]).is_relative_to(tmp_path / ".equivalence-results/host-update-isolation")


def test_native_transport_rejects_a_raw_file_that_differs_from_the_returned_diagnostics(tmp_path, monkeypatch):
    case = build_cases()[0]

    def fixture(selected, node, runtime, directory, *, timeout):
        evidence = directory / "evidence"
        evidence.mkdir(parents=True)
        (evidence / "native-raw.json").write_text(json.dumps([{"label": "retained"}]))
        return {"kind": NATIVE_KIND, "results": [], "releaseSources": [], "releaseTrace": {},
                "runtimeDiagnostics": [{"label": "another capture"}], "evidenceDirectory": str(directory)}

    monkeypatch.setattr("equivalence.harness.ROOT", tmp_path)
    monkeypatch.setattr(RUNNER, fixture)
    with pytest.raises(HarnessError, match="no retry"):
        _oracle(tmp_path / "node", ROOT / "equivalence/release-oracle.mjs", tmp_path,
                [case], 60, release_runtime={"label": "unit runtime fixture"})


def test_sdk_dispatch_passes_frozen_input_to_actual_owner_with_evidence_directory(tmp_path, monkeypatch):
    case = build_cases()[0]
    calls = []
    result = {"label": "unit dispatch fixture"}

    def fixture(value, *, evidence_directory):
        calls.append((value, evidence_directory))
        return result

    monkeypatch.setattr("equivalence.host_update_isolation_sdk.run_host_update_isolation", fixture)
    assert run_python({**case, "_diagnosticDirectory": tmp_path}) is result
    assert calls == [(case["input"], tmp_path)]
    changed = build_cases()[0]
    changed["input"]["nowMs"] += 1
    with pytest.raises(ValueError):
        run_python({**changed, "_diagnosticDirectory": tmp_path})
    assert len(calls) == 1


def _labelled_trace_fixture(tmp_path, *, omit=None):
    """Synthetic process traces for the validator's owner rule; they are not host evidence."""
    package, entry = "node_modules/openclaw", "dist/extensions/memory-core/manager-runtime.js"
    worker_paths = sorted({path for route in PRODUCER_WORKER_ROUTES for path in route}
                          | set(CANONICAL_PUBLICATION_WORKER_ARTIFACTS))
    main_paths = list(dict.fromkeys((*required_host_artifacts(), entry)))

    def sha(text):
        return hashlib.sha256(text.encode()).hexdigest()

    runtime = {"runtimeRoot": "/labelled-fixture/runtime", "packages": [{"location": package, "files": [
        {"path": path, "sha256": sha(path)} for path in dict.fromkeys((*main_paths, *worker_paths))]}]}
    authority = {"execPath": "/labelled-fixture/node"}
    local = {str(ROOT / "equivalence" / name): sha(name)
             for name in (ENTRY, COORDINATOR, *PHASE_ACTORS, PRELOAD, "release-preload.mjs")}
    context = {"allowedLocal": [{"path": path, "sha256": digest} for path, digest in local.items()],
               "_sha256": sha("labelled context"), PROFILE_KEY: {"label": "labelled profile fixture"}}
    parent, coordinator, hosts = 200, 300, {"produce": 301, "update": 302}
    directory = tmp_path / "traces"
    directory.mkdir()

    def write(pid, thread, ppid, actors, releases):
        owner = {"pid": pid, "threadId": thread}
        rows = [{"event": "bootstrap", "runtime": authority, "ppid": ppid, "fetchDenied": True,
                 "providerMode": "none", "contextSha256": context["_sha256"],
                 "preloadSha256": local[str(ROOT / "equivalence/release-preload.mjs")],
                 "isMainThread": thread == 0, **owner},
                {"event": BOOTSTRAP_EVENT, "profile": context[PROFILE_KEY],
                 "preloadSha256": local[str(ROOT / "equivalence" / PRELOAD)], **owner}]
        rows += [{"event": "load", "kind": "oracle", "path": str(ROOT / "equivalence" / name),
                  "sha256": sha(name), **owner} for name in actors]
        rows += [{"event": "load", "kind": "release", "package": package, "path": path,
                  "sha256": sha(path), **owner} for path in releases]
        (directory / f"{pid}-{thread}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

    write(coordinator, 0, parent, (ENTRY, COORDINATOR), [])
    for label, pid in hosts.items():
        write(pid, 0, coordinator, PHASE_ACTORS, [path for path in main_paths if (label, path) != omit])
        write(pid, 1, coordinator, (), worker_paths)
    raw = {"coordinatorPid": coordinator, "coordinatorPpid": parent, "children": [
        {"label": label, "pid": pid, "executable": authority["execPath"],
         "request": {"runtimeRoot": runtime["runtimeRoot"]}} for label, pid in hosts.items()]}
    return (directory, context, runtime, authority), {
        "process_pid": coordinator, "coordinator_pid": parent, "raw": raw}


def test_declared_update_owners_are_the_enforced_host_owner_set(tmp_path):
    assert set(ADDITIONAL_REQUIRED_HOST_ARTIFACTS) <= set(required_host_artifacts())
    arguments, identities = _labelled_trace_fixture(tmp_path)
    accepted = validate_traces(*arguments, **identities)
    assert set(ADDITIONAL_REQUIRED_HOST_ARTIFACTS) <= {item["path"] for item in accepted["loaded"]}


@pytest.mark.parametrize("host", ["produce", "update"])
@pytest.mark.parametrize("artifact", ADDITIONAL_REQUIRED_HOST_ARTIFACTS)
def test_host_that_did_not_load_a_declared_update_owner_is_rejected(tmp_path, host, artifact):
    arguments, identities = _labelled_trace_fixture(tmp_path, omit=(host, artifact))
    with pytest.raises(ValueError, match="omitted declared original owners") as rejected:
        validate_traces(*arguments, **identities)
    assert artifact in str(rejected.value)


TRACE_ATTACKS = {
    "detached-coordinator": "detached from its actual parent",
    "foreign-coordinator-parent": "detached from its actual parent",
    "host-reused-a-process": "three distinct real coordinator/host process identities",
    "hosts-in-another-order": "three distinct real coordinator/host process identities",
    "no-traces": "Missing or excessive update process traces",
    "unknown-trace-name": "unowned or unknown update trace",
    "linked-trace": "unowned or unknown update trace",
    "truncated-trace": "Incomplete or excessive update trace",
    "foreign-runtime-authority": "Missing exact update process/worker authority",
    "fetch-not-denied": "Missing exact update process/worker authority",
    "provider-enabled": "Missing exact update process/worker authority",
    "foreign-context": "Missing exact update process/worker authority",
    "foreign-release-preload": "Missing exact update process/worker authority",
    "foreign-process": "Missing exact update process/worker authority",
    "missing-capability-attestation": "Missing independent update capability attestation",
    "repeated-capability-attestation": "Missing independent update capability attestation",
    "foreign-capability-profile": "Missing independent update capability attestation",
    "foreign-capability-preload": "Missing independent update capability attestation",
    "rejected-event": "Unknown, rejected or reassigned update trace event",
    "reassigned-event": "Unknown, rejected or reassigned update trace event",
    "unverified-original-import": "Unverified original import",
    "source-substitution": "cannot import source substitutions or unknown adapters",
    "unknown-adapter": "cannot import source substitutions or unknown adapters",
    "changed-adapter": "cannot import source substitutions or unknown adapters",
    "foreign-host-parent": "ancestry differs from the protected coordinator",
    "coordinator-without-role-adapter": "omitted its protected role adapter",
    "host-without-role-adapter": "omitted its protected role adapter",
    "foreign-runtime-location": "borrowed another runtime location or executable",
    "foreign-executable": "borrowed another runtime location or executable",
    "missing-worker-route": "original worker route did not execute",
    "missing-publication-worker": "did not publish through the canonical agent SQLite worker",
}


def _rewrite(trace, change):
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    rows = change(rows)
    trace.write_text("".join(json.dumps(row) + "\n" for row in rows))


@pytest.mark.parametrize("attack", sorted(TRACE_ATTACKS))
def test_trace_validator_rejects_each_missing_or_foreign_authority(tmp_path, attack):
    (directory, context, runtime, authority), identities = _labelled_trace_fixture(tmp_path)
    raw, update_main, update_worker = identities["raw"], directory / "302-0.jsonl", directory / "302-1.jsonl"
    coordinator_main = directory / "300-0.jsonl"

    def first(update):
        return lambda rows: [{**rows[0], **update}, *rows[1:]]

    def without(predicate):
        return lambda rows: [row for row in rows if not predicate(row)]

    def with_row(row):
        return lambda rows: [*rows, {"pid": rows[0]["pid"], "threadId": rows[0]["threadId"], **row}]

    route = PRODUCER_WORKER_ROUTES[0]
    only_canonical = sorted(set(CANONICAL_PUBLICATION_WORKER_ARTIFACTS)
                            - {path for item in PRODUCER_WORKER_ROUTES for path in item})
    if attack == "detached-coordinator":
        raw["coordinatorPid"] += 1000
    elif attack == "foreign-coordinator-parent":
        raw["coordinatorPpid"] += 1000
    elif attack == "host-reused-a-process":
        raw["children"][1]["pid"] = raw["children"][0]["pid"]
    elif attack == "hosts-in-another-order":
        raw["children"].reverse()
    elif attack == "no-traces":
        for trace in directory.iterdir():
            trace.unlink()
    elif attack == "unknown-trace-name":
        update_worker.rename(directory / "labelled-extra.jsonl")
    elif attack == "linked-trace":
        os.link(update_worker, tmp_path / "second-name.jsonl")
    elif attack == "truncated-trace":
        update_worker.write_text(update_worker.read_text().rstrip("\n"))
    elif attack == "foreign-runtime-authority":
        _rewrite(update_main, first({"runtime": {"execPath": "/another/node"}}))
    elif attack == "fetch-not-denied":
        _rewrite(update_main, first({"fetchDenied": False}))
    elif attack == "provider-enabled":
        _rewrite(update_main, first({"providerMode": "openai"}))
    elif attack == "foreign-context":
        _rewrite(update_main, first({"contextSha256": "0" * 64}))
    elif attack == "foreign-release-preload":
        _rewrite(update_main, first({"preloadSha256": "0" * 64}))
    elif attack == "foreign-process":
        _rewrite(update_worker, lambda rows: [{**row, "pid": 999} for row in rows])
        update_worker.rename(directory / "999-1.jsonl")
    elif attack == "missing-capability-attestation":
        _rewrite(update_main, without(lambda row: row["event"] == BOOTSTRAP_EVENT))
    elif attack == "repeated-capability-attestation":
        _rewrite(update_main, lambda rows: [*rows, next(row for row in rows if row["event"] == BOOTSTRAP_EVENT)])
    elif attack == "foreign-capability-profile":
        _rewrite(update_main, lambda rows: [{**row, "profile": {"label": "another profile"}}
                                            if row["event"] == BOOTSTRAP_EVENT else row for row in rows])
    elif attack == "foreign-capability-preload":
        _rewrite(update_main, lambda rows: [{**row, "preloadSha256": "0" * 64}
                                            if row["event"] == BOOTSTRAP_EVENT else row for row in rows])
    elif attack == "rejected-event":
        _rewrite(update_main, with_row({"event": "rejected", "kind": "network"}))
    elif attack == "reassigned-event":
        _rewrite(update_main, lambda rows: [*rows[:-1], {**rows[-1], "threadId": 7}])
    elif attack == "unverified-original-import":
        _rewrite(update_main, lambda rows: [*rows[:-1], {**rows[-1], "sha256": "0" * 64}])
    elif attack == "source-substitution":
        _rewrite(update_main, with_row({"event": "load", "kind": "source", "path": "src/agents/sessions/tools/edit.ts",
                                        "sha256": "0" * 64}))
    elif attack == "unknown-adapter":
        _rewrite(update_main, with_row({"event": "load", "kind": "oracle",
                                        "path": str(ROOT / "equivalence/host-restart-phase.mjs"), "sha256": "0" * 64}))
    elif attack == "changed-adapter":
        _rewrite(update_main, lambda rows: [{**row, "sha256": "0" * 64} if row.get("kind") == "oracle" else row
                                            for row in rows])
    elif attack == "foreign-host-parent":
        _rewrite(update_main, first({"ppid": 999}))
    elif attack == "coordinator-without-role-adapter":
        _rewrite(coordinator_main, without(lambda row: row.get("path", "").endswith("/" + COORDINATOR)))
    elif attack == "host-without-role-adapter":
        _rewrite(update_main, without(lambda row: row.get("path", "").endswith("/" + PHASE_ACTORS[1])))
    elif attack == "foreign-runtime-location":
        raw["children"][1]["request"]["runtimeRoot"] = "/another/runtime"
    elif attack == "foreign-executable":
        raw["children"][1]["executable"] = "/another/node"
    elif attack == "missing-worker-route":
        _rewrite(update_worker, without(lambda row: row.get("path") == route[0]))
    else:
        assert only_canonical, "the fixture needs an artifact that only the canonical publication worker loads"
        _rewrite(update_worker, without(lambda row: row.get("path") in only_canonical))
    with pytest.raises(ValueError, match=TRACE_ATTACKS[attack]):
        validate_traces(directory, context, runtime, authority, **identities)


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def labelled_suite(tmp_path, monkeypatch):
    """The real run_suite over the four frozen literals with labelled transports instead of hosts.

    Nothing here is host evidence. The transports return a fixed labelled result so that
    the suite's own pairing, validation marker and atomic crediting can be exercised.
    """
    from equivalence import flush_execution_bindings, flush_runtime_bindings, host_update_isolation_bindings
    from equivalence import host_update_isolation_evidence, model_runtime_authority

    checkout = tmp_path / "labelled-reference"
    checkout.mkdir()
    _git(checkout, "init", "-q")
    (checkout / "package.json").write_text(json.dumps({
        "version": "2026.9.9", "engines": {"node": ">=24.16.0 <25 || >=26.1.0"}}))
    _git(checkout, "add", ".")
    _git(checkout, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "Labelled update-harness fixture")
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"tag": "v2026.9.9", "commit": _git(checkout, "rev-parse", "HEAD"),
                                     "nodeMin": "24.16.0", "nodeRanges": ">=24.16.0 <25 || >=26.1.0"}))
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"schemaVersion": 1, "requirements": [
        {"id": "host.update-isolation", "required": True, "acceptance": [
            {"id": point, "description": "Labelled update condition."} for point in POINTS]},
        {"id": "indexing", "required": True, "acceptance": [
            {"id": "indexing.lifecycle", "description": "Labelled unrelated condition."}]},
    ]}))
    node = tmp_path / "node"
    node.write_text(f"#!{sys.executable}\nprint('v24.16.0')\n")
    node.chmod(0o700)
    unrelated = {"id": "labelled-unrelated-runtime", "requirement": "indexing", "operation": "index-lifecycle-runtime",
                 "input": {"provider": "none"}, "covers": ["indexing.lifecycle"]}
    cases = [unrelated, *build_cases()]
    config = {"kind": "labelled-runtime-fixture", "runtimeRoot": str(tmp_path / "runtime"),
              "reference": {"tag": "v2026.9.9"}, "buildAttestation": {"sourceBuildReproduced": False},
              "packages": [{"location": "node_modules/openclaw", "directory": "/owned/fixture",
                            "files": [{"path": "labelled.js", "sha256": "1" * 64}]}]}
    control = {"native": {}, "python": {}, "unverified": set(), "rejectedPairs": set(), "failingHosts": set(),
               "pairs": []}

    def result(case):
        return {"provider": "none", "label": "labelled result of " + case["id"]}

    def native(node_, script, checkout_, selected, timeout, **kwargs):
        case, = selected
        diagnostic = {"id": case["id"], "sha256": "2" * 64, "rawSnapshots": [{"raw": "labelled original capture"}]}
        if case["operation"] == "host-update-isolation-runtime":
            diagnostic["validationStatus"] = "unverified" if case["id"] in control["unverified"] else "verified"
        return {"kind": "official-release-runtime-comparison", "sources": [],
                "results": [{"id": case["id"], "ok": True, "result": control["native"].get(case["id"], result(case))}],
                "releaseSources": [{"package": "node_modules/openclaw", "path": "labelled.js", "sha256": "1" * 64}],
                "releaseTrace": {"kind": "labelled-trace-fixture", "protectedWorkerThreads": 1},
                "runtimeDiagnostics": [diagnostic]}

    def python(case):
        directory = case["_diagnosticDirectory"]
        directory.mkdir(parents=True)
        (directory / "python-raw.json").write_text(json.dumps([{"raw": "labelled SDK capture of " + case["id"]}]))
        if case["id"] in control["failingHosts"]:
            raise RuntimeError("labelled SDK host failure")
        return control["python"].get(case["id"], result(case))

    def pair(case, native_raw, sdk_raw, native_result, sdk_result):
        control["pairs"].append((case["id"], native_raw, sdk_raw, native_result, sdk_result))
        if case["id"] in control["rejectedPairs"]:
            raise ValueError("labelled custody rejection")
        return True

    monkeypatch.setattr(release_runtime, "prepare_release_runtime", lambda *_args: deepcopy(config))
    monkeypatch.setattr(harness, "_oracle", native)
    for module, name in ((flush_runtime_bindings, "prepare_flush_runtime_bindings"),
                         (flush_execution_bindings, "prepare_flush_execution_bindings"),
                         (host_update_isolation_bindings, "prepare_host_update_isolation_bindings")):
        monkeypatch.setattr(module, name, lambda *_args, name=name: {"kind": "labelled-owner-fixture", "name": name})
    monkeypatch.setattr(model_runtime_authority, "prepare_model_node_authority",
                        lambda *_args: {"kind": "labelled-node-fixture"})
    monkeypatch.setattr(host_update_isolation_evidence, "validate_pair", pair)
    options = {"checkout": checkout, "node": node, "reference_path": reference, "scope_path": scope,
               "cases": cases, "python_runner": python, "release_runtime_root": tmp_path / "runtime"}
    return options, control


def _points(report):
    requirement, = [item for item in report["requirements"] if item["id"] == "host.update-isolation"]
    return {point["id"]: (point["caseIds"], point["matchedCaseIds"]) for point in requirement["acceptance"]}


def _row(report, case_id):
    return next(row for row in report["cases"] if row["id"] == case_id)


def test_suite_credits_both_points_only_for_four_matched_and_validated_cases(labelled_suite):
    options, control = labelled_suite
    family = [case["id"] for case in build_cases()]
    report, code = harness.run_suite(**options)
    assert code == 0 and report["status"] == "passed", report["errors"]
    assert _points(report) == {point: (family, family) for point in POINTS}
    assert all(_row(report, case_id)["runtimeEvidenceValidated"] is True for case_id in family)
    # The pairing guard received each literal with both engines' own captures and results.
    assert [entry[0] for entry in control["pairs"]] == family
    for case_id, native_raw, sdk_raw, native_result, sdk_result in control["pairs"]:
        assert native_raw == {"raw": "labelled original capture"}
        assert sdk_raw == {"raw": "labelled SDK capture of " + case_id}
        assert native_result == sdk_result == {"provider": "none", "label": "labelled result of " + case_id}
    python_side = [item for item in report["runtimeDiagnostics"] if item["side"] == "python" and item["id"] in family]
    assert [item["validationStatus"] for item in python_side] == ["verified"] * 4
    assert "runtimeEvidenceValidated" not in _row(report, "labelled-unrelated-runtime")


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("failure", ["mismatched", "custody-rejected", "original-unverified", "sdk-host-failed"])
def test_one_failing_member_leaves_both_points_without_any_credit(labelled_suite, index, failure):
    options, control = labelled_suite
    family = [case["id"] for case in build_cases()]
    victim = family[index]
    if failure == "mismatched":
        control["python"][victim] = {"provider": "none", "label": "a different labelled result"}
    elif failure == "custody-rejected":
        control["rejectedPairs"].add(victim)
    elif failure == "original-unverified":
        control["unverified"].add(victim)
    else:
        control["failingHosts"].add(victim)
    report, code = harness.run_suite(**options)
    row = _row(report, victim)
    assert code != 0 and report["status"] == ("mismatched" if failure == "mismatched" else "blocked")
    assert row["status"] == ("mismatched" if failure == "mismatched" else "blocked")
    # Three members still match, and neither point lists any of them.
    assert [_row(report, case_id)["status"] for case_id in family if case_id != victim] == ["matched"] * 3
    assert _points(report) == {point: (family, []) for point in POINTS}
    unrelated, = [item for item in report["requirements"] if item["id"] == "indexing"]
    assert unrelated["acceptance"][0]["matchedCaseIds"] == ["labelled-unrelated-runtime"]
    if failure == "mismatched":
        assert row["runtimeEvidenceValidated"] is True
        return
    # A capture that was not admitted never carries the validation marker.
    assert "runtimeEvidenceValidated" not in row
    statuses = [item["validationStatus"] for item in report["runtimeDiagnostics"]
                if item["side"] == "python" and item["id"] == victim]
    assert statuses == (["rejected"] if failure == "sdk-host-failed" else ["unverified"])
    assert row["evidenceError"]["message"] == {
        "custody-rejected": "labelled custody rejection",
        "original-unverified": "Host update requires one authenticated original and SDK capture",
        "sdk-host-failed": "labelled SDK host failure"}[failure]
    if failure == "original-unverified":
        assert victim not in [entry[0] for entry in control["pairs"]]


def test_failed_sdk_host_keeps_its_own_record_as_rejected_evidence(labelled_suite):
    options, control = labelled_suite
    victim = build_cases()[3]["id"]
    control["failingHosts"].add(victim)
    report, _ = harness.run_suite(**options)
    retained, = [item for item in report["runtimeDiagnostics"] if item["side"] == "python" and item["id"] == victim]
    assert retained["validationStatus"] == "rejected"
    assert retained["rawSnapshots"] == [{"raw": "labelled SDK capture of " + victim}]
    assert retained["sha256"] == hashlib.sha256(json.dumps(retained["rawSnapshots"]).encode()).hexdigest()
