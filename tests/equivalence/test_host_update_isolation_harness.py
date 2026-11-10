"""Labelled delegation fixtures test gate routing, never original host behavior."""
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.cases import run_python
from equivalence.harness import HarnessError, _oracle
from equivalence.host_update_isolation import build_cases
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
