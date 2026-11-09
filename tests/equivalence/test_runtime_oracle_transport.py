"""Release transport fault fixtures; these are not upstream behavioral evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import os
import shutil
import subprocess

import pytest

from equivalence.runtime_oracle import ReleaseOracleExecution, RuntimeOracleError, ROOT
from equivalence.release_runtime import ReleaseRuntimeError, validate_release_sources


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def transport(tmp_path):
    # A labelled package fixture exercises trace validation only. Actual
    # acceptance first authenticates official archives through release_runtime.
    runtime = tmp_path / "runtime/node_modules/openclaw"
    files = {
        "dist/extensions/memory-core/manager-runtime.js": b"// Labelled manager transport fixture.\n",
        "dist/extensions/memory-core/memory-index.worker.js": b"// Labelled worker transport fixture.\n",
        "dist/labelled-console-worker.mjs": b"console.log('worker retirement');\n",
        "dist/agent-runner-memory-Cc4lCZcs.mjs": b"// Labelled flush transport fixture.\n",
    }
    for relative, raw in files.items():
        path = runtime / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    config = {"kind": "labelled-release-transport-fixture", "runtimeRoot": str(runtime),
              "packages": [{"location": "node_modules/openclaw", "directory": str(runtime),
                            "files": [{"path": relative, "sha256": _hash(raw)}
                                      for relative, raw in files.items()]}]}
    adapters = {path.name: _hash(path.read_bytes()) for path in (ROOT / "equivalence").glob("*.mjs")}
    case = {"id": "labelled-transport", "operation": "index-lifecycle-runtime", "input": {}}
    result = {"kind": "official-release-runtime-comparison", "sources": [], "results": [
        {"id": case["id"], "ok": True, "result": {"provider": "none", "snapshots": []}},
    ]}
    with ReleaseOracleExecution(config, adapters) as execution:
        yield execution, config, case, result


def _bootstrap(execution, thread):
    return {"event": "bootstrap", "pid": 111, "threadId": thread,
            "isMainThread": thread == 0, "contextSha256": execution._context_digest,
            "preloadSha256": execution._preload_digest, "fetchDenied": True, "providerMode": "none"}


def _load(config, relative, thread):
    digest = next(item["sha256"] for item in config["packages"][0]["files"] if item["path"] == relative)
    return {"event": "load", "pid": 111, "threadId": thread, "kind": "release",
            "package": "node_modules/openclaw", "path": relative, "sha256": digest}


def _trace(execution, thread, events):
    path = execution.trace_directory / f"111-{thread}.jsonl"
    path.write_text("".join(json.dumps(event) + "\n" for event in events))
    return path


def _evidence(execution, case, data=None):
    directory = execution.evidence_directory / _hash(case["id"].encode())
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "native-raw.json"
    path.write_text(json.dumps([] if data is None else data))
    return path


def _valid(execution, config, case):
    local = [{"event": "load", "pid": 111, "threadId": 0, "kind": "oracle",
              "path": str((ROOT / "equivalence" / name).resolve()),
              "sha256": execution._locals[str((ROOT / "equivalence" / name).resolve())]}
             for name in ("release-oracle.mjs", "index-lifecycle.mjs")]
    _trace(execution, 0, [_bootstrap(execution, 0), *local,
                        _load(config, "dist/extensions/memory-core/manager-runtime.js", 0)])
    _trace(execution, 1, [_bootstrap(execution, 1),
                        _load(config, "dist/extensions/memory-core/memory-index.worker.js", 1)])
    _evidence(execution, case)


def test_context_uses_reviewed_preload_and_owned_state_without_runtime_credentials(transport, monkeypatch):
    execution, config, case, result = transport
    assert execution.env["NODE_OPTIONS"] == "--import=" + (ROOT / "equivalence/release-preload.mjs").as_uri()
    assert "HOME" not in execution.env and not any("API_KEY" in name for name in execution.env)
    assert Path(execution.env["OPENCLAW_STATE_DIR"]).is_relative_to(execution.root)
    logging = json.loads(Path(execution.env["OPENCLAW_CONFIG_PATH"]).read_text())["logging"]
    assert json.loads(Path(execution.env["OPENCLAW_CONFIG_PATH"]).read_text())["session"] == {
        "maintenance": {"mode": "warn"},
    }
    assert logging["level"] == logging["consoleLevel"] == "silent"
    assert Path(logging["file"]).is_relative_to(execution.root)
    assert config["kind"] == "labelled-release-transport-fixture"


def test_model_binary_capability_cannot_expand_an_existing_runtime_profile(transport):
    from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME

    execution, _config, case, result = transport
    execution.model_node_runtime = {"execPath": "/reviewed/node", **APPROVED_NODE_RUNTIME}
    with pytest.raises(RuntimeOracleError, match="restricted"):
        execution.collect(result, [case])


@pytest.mark.parametrize("operation", ("model-session-runtime", "model-tool-result-runtime", "trust-worker-runtime", "model-tool-error-runtime"))
def test_new_model_profiles_cannot_omit_the_reviewed_binary_capability(transport, operation):
    execution, _config, case, result = transport
    case["operation"] = operation
    with pytest.raises(RuntimeOracleError, match="restricted"):
        execution.collect(result, [case])


def test_model_binary_capability_does_not_grant_reference_source_imports(transport):
    from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME

    _execution, config, _case, _result = transport
    adapters = {path.name: _hash(path.read_bytes()) for path in (ROOT / "equivalence").glob("*.mjs")}
    authority = {"execPath": "/reviewed/node", **APPROVED_NODE_RUNTIME}
    with ReleaseOracleExecution(config, adapters, model_node_runtime=authority) as execution:
        assert execution._context["approvedNodeRuntime"] == authority
        assert execution._context["approvedReferenceSources"] == []
        assert execution._context["fixtureSourceCaptures"] == []


def test_real_preload_keeps_worker_console_on_stderr_and_denies_unreviewed_execution(transport):
    """An optional Node transport check; the labelled files are not parity evidence."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Optional real preload check requires Node 24 or newer.")
    version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout
    if int(version.lstrip("v").split(".")[0]) < 24:
        pytest.skip("Optional real preload check requires Node 24 or newer.")
    execution, _, _, _ = transport
    unreviewed = execution.root / "unreviewed.mjs"
    unreviewed.write_text('process.stdout.write("UNREVIEWED EXECUTED");\n')
    script = '''
import { Worker } from 'node:worker_threads';
console.log('parent log'); console.info('parent info'); console.debug('parent debug');
const worker = new Worker(new URL(WORKER_URL), {execArgv:[]});
await new Promise((resolve,reject) => {worker.once('error', reject);worker.once('exit',resolve);});
let fetchDenied=false,importDenied=false;
try { await fetch('https://example.invalid'); } catch { fetchDenied=true; }
try { await import(UNREVIEWED_URL); } catch { importDenied=true; }
process.stdout.write(JSON.stringify({fetchDenied,importDenied}));
'''.replace("UNREVIEWED_URL", json.dumps(unreviewed.as_uri())).replace(
        "WORKER_URL", json.dumps((Path(execution.config["runtimeRoot"]) / "dist/labelled-console-worker.mjs").as_uri()))
    result = subprocess.run([node, "--input-type=module", "--eval", script],
                            capture_output=True, text=True, timeout=15,
                            env={"PATH": os.defpath, "LANG": "en_US.UTF-8", "TZ": "UTC", **execution.env})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"fetchDenied": True, "importDenied": True}
    assert all(line in result.stderr for line in ("parent log", "parent info", "parent debug", "worker retirement"))
    assert "UNREVIEWED EXECUTED" not in result.stdout + result.stderr
    events = [json.loads(line) for path in execution.trace_directory.glob("*.jsonl")
              for line in path.read_text().splitlines()]
    assert any(row["event"] == "bootstrap" and row["threadId"] > 0 for row in events)
    assert any(row["event"] == "network-denied" for row in events)
    assert any(row["event"] == "rejected" for row in events)


def test_complete_trace_retains_raw_diagnostics_and_worker_authority(transport):
    execution, config, case, result = transport
    _valid(execution, config, case)
    raw = [{"label": "fixture", "raw": {"provenance": [{"originClass": "untrusted"}]}}]
    _evidence(execution, case, raw)
    before = deepcopy(result)
    enriched = execution.collect(result, [case])
    assert result == before
    assert len(enriched["releaseSources"]) == 2
    assert enriched["sources"] == []
    assert enriched["releaseTrace"]["protectedWorkerThreads"] == 1
    assert enriched["releaseTrace"]["networkFetchDenied"] is True
    assert enriched["runtimeDiagnostics"][0]["rawSnapshots"] == raw


def test_reference_process_requires_both_main_and_native_worker_preloads(transport):
    execution, config, case, result = transport
    with pytest.raises(RuntimeOracleError, match="missing"):
        execution.collect(result, [case])
    _valid(execution, config, case)
    (execution.trace_directory / "111-1.jsonl").unlink()
    with pytest.raises(RuntimeOracleError, match="worker"):
        execution.collect(result, [case])


def _flush_trace(execution, config, adapter="flush-runtime.mjs"):
    local = [{"event": "load", "pid": 111, "threadId": 0, "kind": "oracle",
              "path": str((ROOT / "equivalence" / name).resolve()),
              "sha256": execution._locals[str((ROOT / "equivalence" / name).resolve())]}
             for name in ("release-oracle.mjs", adapter)]
    return [_bootstrap(execution, 0), *local,
            _load(config, "dist/agent-runner-memory-Cc4lCZcs.mjs", 0)]


def test_flush_trace_requires_its_own_reviewed_adapter_and_native_owner_without_index_worker(transport):
    execution, config, case, result = transport
    case["operation"] = "flush-trigger-runtime"
    _trace(execution, 0, _flush_trace(execution, config))
    _evidence(execution, case, [{"outcome": "skipped", "entry": {"totalTokensFresh": False}}])
    enriched = execution.collect(result, [case])
    assert enriched["releaseTrace"]["protectedWorkerThreads"] == 0
    assert enriched["releaseSources"][0]["path"] == "dist/agent-runner-memory-Cc4lCZcs.mjs"
    assert enriched["runtimeDiagnostics"][0]["rawSnapshots"][0]["outcome"] == "skipped"


def test_flush_source_validation_cannot_relax_the_default_manager_or_select_arbitrary_artifacts(transport):
    _, config, _, _ = transport
    owner = "dist/agent-runner-memory-Cc4lCZcs.mjs"
    event = _load(config, owner, 0)
    source = {key: event[key] for key in ("package", "path", "sha256")}
    validate_release_sources(config, [source], required_entry=owner)
    with pytest.raises(ReleaseRuntimeError, match="required real runtime entry"):
        validate_release_sources(config, [source])
    with pytest.raises(ReleaseRuntimeError, match="reviewed runtime entry"):
        validate_release_sources(config, [source], required_entry="dist/labelled-console-worker.mjs")


@pytest.mark.parametrize("missing", ["runner", "manager", "worker"])
def test_flush_execution_requires_the_actual_runner_manager_and_protected_index_worker(transport, missing):
    previous, config, case, result = transport
    case["operation"] = "flush-execution-runtime"
    with ReleaseOracleExecution(config, previous.adapter_hashes, fixture_captures=True) as execution:
        # A labelled trace fixture supplies valid capture/model proof so each
        # negative fails for its missing real owner, not for disabled captures.
        # Real Node capture imports are exercised in test_fixture_provider_capture.
        source = str((ROOT / "equivalence/flush-execution.mjs").resolve())
        digest = execution._locals[source]
        capture = (
            "tmp/plugin-captures/00000000-0000-4000-8000-000000000001/captures/"
            "openclaw-plugin-build-abc123/package-0/node_modules/equivalence/flush-execution.mjs"
        )
        proof_relative = "fixture-source-captures/" + _hash((capture + "\0" + digest).encode()) + ".mjs"
        proof = execution.evidence_directory / proof_relative
        proof.parent.mkdir()
        proof.write_bytes(Path(source).read_bytes())
        events = _flush_trace(execution, config, "flush-execution.mjs")
        events.append(_load(config, "dist/extensions/memory-core/manager-runtime.js", 0))
        events.append({"event": "load", "kind": "fixture-capture", "pid": 111, "threadId": 0,
                       "path": source, "sourcePath": source, "sha256": digest,
                       "capturePath": capture, "proofPath": proof_relative})
        omitted_path = {
            "runner": "dist/agent-runner-memory-Cc4lCZcs.mjs",
            "manager": "dist/extensions/memory-core/manager-runtime.js",
        }.get(missing)
        if omitted_path is not None:
            events = [event for event in events if event.get("path") != omitted_path]
        _trace(execution, 0, events)
        if missing != "worker":
            _trace(execution, 1, [_bootstrap(execution, 1),
                                _load(config, "dist/extensions/memory-core/memory-index.worker.js", 1)])
        _evidence(execution, case, [{"modelCalls": [{"labelledTransportFixture": True}]}])
        expected = {
            "runner": "actual native flush runtime owner",
            "manager": "actual native memory manager",
            "worker": "actual native memory worker",
        }[missing]
        with pytest.raises(RuntimeOracleError, match=expected):
            execution.collect(result, [case])


@pytest.mark.parametrize("missing", ["adapter", "owner", "bootstrap"])
def test_flush_runtime_cannot_reuse_an_index_trace_or_omit_its_authority(transport, missing):
    execution, config, case, result = transport
    case["operation"] = "flush-trigger-runtime"
    events = _flush_trace(execution, config)
    if missing == "adapter":
        events = [event for event in events if not str(event.get("path", "")).endswith("flush-runtime.mjs")]
    elif missing == "owner":
        events = [event for event in events if not str(event.get("path", "")).endswith("agent-runner-memory-Cc4lCZcs.mjs")]
        events.append(_load(config, "dist/extensions/memory-core/manager-runtime.js", 0))
    else:
        events.pop(0)
    _trace(execution, 0, events)
    _evidence(execution, case)
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


@pytest.mark.parametrize("change", [
    "context-hash", "preload-hash", "network-policy", "provider-policy", "thread-identity",
    "missing-bootstrap", "rejected-import", "network-attempt", "forged-package", "forged-hash",
    "unapproved-local", "unsupported-event", "truncated-trace",
])
def test_missing_or_forged_thread_protection_blocks_acceptance(transport, change):
    execution, config, case, result = transport
    _valid(execution, config, case)
    events = [_bootstrap(execution, 1),
              _load(config, "dist/extensions/memory-core/memory-index.worker.js", 1)]
    if change == "context-hash":
        events[0]["contextSha256"] = "0" * 64
    elif change == "preload-hash":
        events[0]["preloadSha256"] = "0" * 64
    elif change == "network-policy":
        events[0]["fetchDenied"] = False
    elif change == "provider-policy":
        events[0]["providerMode"] = "remote"
    elif change == "thread-identity":
        events[1]["pid"] = 999
    elif change == "missing-bootstrap":
        events.pop(0)
    elif change == "rejected-import":
        events[1]["event"] = "rejected"
    elif change == "network-attempt":
        events[1]["event"] = "network-denied"
    elif change == "forged-package":
        events[1]["package"] = "node_modules/unverified"
    elif change == "forged-hash":
        events[1]["sha256"] = "0" * 64
    elif change == "unapproved-local":
        events[1].update(kind="oracle", path="/unapproved/adapter.mjs")
    elif change == "unsupported-event":
        events[1]["event"] = "trust-me"
    trace = _trace(execution, 1, events)
    if change == "truncated-trace":
        trace.write_bytes(trace.read_bytes().rstrip(b"\n"))
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


def test_owned_context_cannot_change_during_execution(transport):
    execution, config, case, result = transport
    _valid(execution, config, case)
    execution.context_path.write_text("{}")
    with pytest.raises(RuntimeOracleError, match="configuration changed"):
        execution.collect(result, [case])


def test_verified_package_imports_cannot_replace_the_reviewed_case_adapter(transport):
    execution, config, case, result = transport
    _valid(execution, config, case)
    _trace(execution, 0, [_bootstrap(execution, 0),
                        _load(config, "dist/extensions/memory-core/manager-runtime.js", 0)])
    with pytest.raises(RuntimeOracleError, match="adapter did not execute"):
        execution.collect(result, [case])


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "unknown-name"])
def test_trace_files_must_be_owned_independent_regular_files(transport, kind):
    execution, config, case, result = transport
    _valid(execution, config, case)
    target = execution.trace_directory / "111-1.jsonl"
    saved = execution.root / "saved-trace.jsonl"
    target.rename(saved)
    if kind == "symlink":
        target.symlink_to(saved)
    elif kind == "hardlink":
        os.link(saved, target)
    elif kind == "directory":
        target.mkdir()
    else:
        saved.rename(execution.trace_directory / "unattributed.jsonl")
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])


def test_runtime_raw_diagnostics_are_required_and_shape_preserved(transport):
    execution, config, case, result = transport
    _valid(execution, config, case)
    evidence = _evidence(execution, case)
    evidence.unlink()
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, [case])
    _evidence(execution, case, {"discarded": "not a raw snapshot array"})
    with pytest.raises(RuntimeOracleError, match="raw snapshot"):
        execution.collect(result, [case])


@pytest.mark.parametrize("change", ["two-cases", "foreign-case", "provider", "ts-sources", "wrong-kind"])
def test_release_transport_does_not_admit_other_authority_or_shared_case_processes(transport, change):
    execution, config, case, result = transport
    _valid(execution, config, case)
    cases = [case]
    if change == "two-cases":
        cases.append(dict(case, id="second-case"))
    elif change == "foreign-case":
        result["results"][0]["id"] = "other"
    elif change == "provider":
        result["results"][0]["result"]["provider"] = "remote"
    elif change == "ts-sources":
        result["sources"] = [{"path": "fabricated.ts", "sha256": "0" * 64}]
    else:
        result["kind"] = "pinned-source-comparison"
    with pytest.raises(RuntimeOracleError):
        execution.collect(result, cases)


def test_a_changed_or_absent_adapter_blocks_process_context_creation(transport):
    execution, config, case, result = transport
    hashes = dict(execution.adapter_hashes)
    hashes["release-preload.mjs"] = "0" * 64
    with pytest.raises(RuntimeOracleError, match="changed before"):
        with ReleaseOracleExecution(config, hashes):
            pass
    hashes.pop("release-preload.mjs")
    with pytest.raises(RuntimeOracleError, match="reviewed oracle adapters"):
        with ReleaseOracleExecution(config, hashes):
            pass
