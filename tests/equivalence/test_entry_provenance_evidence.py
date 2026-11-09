"""Genuine original SQL/call captures reject altered identity and data transport."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.entry_provenance_evidence import (
    _embedding,
    validate_entry_observations,
    validate_entry_physical_state,
    validate_entry_provenance_raw,
)
from equivalence.get_contract import map_get_fixture_paths
from equivalence.runtime_oracle import RuntimeOracleError


@pytest.fixture(scope="module")
def original_development_captures():
    path = Path(__file__).parents[1] / "fixtures/entry-provenance-protected-captures.json.gz"
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    compressed = path.read_bytes()
    assert len(compressed) == manifest["gzipBytes"]
    assert hashlib.sha256(compressed).hexdigest() == manifest["gzipSha256"]
    original = gzip.decompress(compressed)
    assert len(original) == manifest["rawBytes"]
    assert hashlib.sha256(original).hexdigest() == manifest["rawSha256"] == "9e02ba6f86fa9589799981f2f466835c75caf182f10f42c3334b8bfb1371293e"
    capture = json.loads(original)
    results = {}
    for observation in capture["observations"]:
        original_native = observation["nativeJson"].encode()
        assert len(original_native) == observation["bytes"]
        assert hashlib.sha256(original_native).hexdigest() == observation["sha256"]
        native = json.loads(original_native)
        row, = native["results"]
        diagnostic, = native["runtimeDiagnostics"]
        raw, = diagnostic["rawSnapshots"]
        assert row["ok"] is True and row["id"] == diagnostic["id"]
        results[raw["kind"]] = {"raw": raw, "input": raw["input"], "public": row["result"]}
    assert len(results) == 3
    return results


def _raw(captures, kind):
    captured = captures[kind]
    return deepcopy(captured["raw"]), deepcopy(captured["input"]), deepcopy(captured["public"])


def test_actual_original_binary64_blob_decodes_without_float32_reinterpretation(original_development_captures):
    raw, _, _ = _raw(original_development_captures, "prepared-provider")
    table = next(table for table in raw["snapshots"][0]["physical"]["tables"] if table["name"] == "memory_index_chunks")
    original = table["rows"][0]["embedding"]
    assert original == {"type": "bytes", "hex": "000000000000f03f0000000000000000"}
    assert _embedding(original) == [1, 0]


def test_historical_first_failure_keeps_the_same_original_binary64_bytes():
    path = Path(__file__).parents[1] / "fixtures/entry-provenance-development-actual.json.gz"
    original = gzip.decompress(path.read_bytes())
    assert hashlib.sha256(original).hexdigest() == "b9ce6bb34a12f98463095bee1d5ea6d39e4bd7996555668b1ac5a8921eaed07b"
    capture = json.loads(original)
    row, = [row for row in capture["observations"] if row["case"]["input"]["kind"] == "prepared-provider"]
    raw, = json.loads(row["nativeRawJson"])
    table = next(table for table in raw["snapshots"][0]["physical"]["tables"] if table["name"] == "memory_index_chunks")
    assert table["rows"][0]["embedding"] == {"type": "bytes", "hex": "000000000000f03f0000000000000000"}
    assert _embedding(table["rows"][0]["embedding"]) == [1, 0]


@pytest.mark.parametrize("kind", ["published-memory", "prepared-provider", "session-projection"])
def test_complete_original_physical_sql_binds_every_canonical_column_and_order(original_development_captures, kind):
    raw, _, _ = _raw(original_development_captures, kind)
    for snapshot in raw["snapshots"]:
        validate_entry_physical_state(snapshot)


@pytest.mark.parametrize("kind", ["published-memory", "prepared-provider", "session-projection"])
def test_unchanged_actual_manager_calls_and_full_sources_bind_public_output(original_development_captures, kind):
    raw, value, public = _raw(original_development_captures, kind)
    validate_entry_observations(raw, value, public)


@pytest.mark.parametrize("tamper", ["hash", "canonical-id", "vector", "updated-at", "origin", "recall", "fts-text",
                                   "chunk-order", "fts-order", "physical-private-id", "missing-table", "missing-schema",
                                   "physical-hash", "physical-vector-carrier", "row-count", "schema-count",
                                   "shadow-row", "shadow-column", "no-read-transaction"])
def test_changed_canonical_or_full_physical_sql_is_rejected_without_repair(original_development_captures, tamper):
    raw, _, _ = _raw(original_development_captures, "prepared-provider")
    snapshot = raw["snapshots"][0]
    state = snapshot["state"]
    tables = {table["name"]: table for table in snapshot["physical"]["tables"]}
    if tamper == "hash":
        state["chunks"][0]["hash"] = "forged"
    elif tamper == "canonical-id":
        state["chunks"][0]["id"] = "salted-for-uniqueness"
    elif tamper == "vector":
        state["chunks"][0]["embedding"] = []
    elif tamper == "updated-at":
        state["chunks"][0]["updatedAt"] += 1
    elif tamper == "origin":
        state["chunks"][0]["provenance"]["originClass"] = "untrusted"
    elif tamper == "recall":
        state["chunks"][0]["recall"]["importance"] = 10
    elif tamper == "fts-text":
        state["fts"][0]["text"] = "repaired text"
    elif tamper == "chunk-order":
        state["chunks"].reverse()
    elif tamper == "fts-order":
        state["fts"].reverse()
    elif tamper == "physical-private-id":
        del tables["memory_index_sources"]["rows"][0]["id"]
    elif tamper == "missing-table":
        snapshot["physical"]["tables"] = [table for table in snapshot["physical"]["tables"] if table["name"] != "memory_index_chunks_fts_data"]
    elif tamper == "missing-schema":
        snapshot["physical"]["schema"] = snapshot["physical"]["schema"][1:]
    elif tamper == "physical-hash":
        tables["memory_index_chunks"]["rows"][0]["hash"] = "forged"
    elif tamper == "physical-vector-carrier":
        tables["memory_index_chunks"]["rows"][0]["embedding"] = "b'raw bytes were stringified'"
    elif tamper == "row-count":
        tables["memory_index_chunks"]["rowCount"] -= 1
    elif tamper == "schema-count":
        snapshot["physical"]["schemaCount"] -= 1
    elif tamper == "shadow-row":
        tables["memory_index_chunks_fts_data"]["rows"].pop()
    elif tamper == "shadow-column":
        del tables["memory_index_chunks_fts_data"]["rows"][0]["block"]
    else:
        snapshot["physical"]["snapshotTransaction"]["active"] = False
    with pytest.raises(RuntimeOracleError):
        validate_entry_physical_state(snapshot)


@pytest.mark.parametrize("tamper", ["literal-write", "force", "dropped-call", "extra-call", "no-close", "public-drop"])
def test_original_memory_api_requests_and_complete_return_cannot_be_rewritten(original_development_captures, tamper):
    raw, value, public = _raw(original_development_captures, "published-memory")
    if tamper == "literal-write":
        raw["calls"][0]["content"] = "different source"
    elif tamper == "force":
        next(call for call in raw["calls"] if call["operation"] == "sync")["request"]["force"] = True
    elif tamper == "dropped-call":
        raw["calls"].pop(2)
    elif tamper == "extra-call":
        raw["calls"].append(deepcopy(raw["calls"][-1]))
    elif tamper == "no-close":
        raw["calls"][-1]["completed"] = False
    else:
        del public["steps"][0]["state"]["provenance"]
    with pytest.raises(RuntimeOracleError):
        validate_entry_observations(raw, value, public)


@pytest.mark.parametrize("tamper", ["input-text", "input-carrier", "provider-limit", "missing-preparation",
                                   "missing-input", "kernel-return", "kernel-vector", "lost-entry-span",
                                   "dropped-fragment"])
def test_real_preparation_and_kernel_receipts_keep_full_inputs_returns_and_collisions(original_development_captures, tamper):
    raw, value, public = _raw(original_development_captures, "prepared-provider")
    if tamper == "input-text":
        raw["providerCalls"][0]["input"]["text"] = "different document"
    elif tamper == "input-carrier":
        raw["providerCalls"][0]["input"] = raw["providerCalls"][0]["input"]["text"]
    elif tamper == "provider-limit":
        raw["preparations"][0]["request"]["provider"]["maxInputTokens"] += 1
    elif tamper == "missing-preparation":
        raw["preparations"].clear()
    elif tamper == "missing-input":
        raw["providerCalls"].pop()
    elif tamper == "kernel-return":
        next(call for call in raw["calls"] if call["operation"] == "replaceRows")["returnedUndefined"] = False
    elif tamper == "kernel-vector":
        next(call for call in raw["calls"] if call["operation"] == "replaceRows")["embeddings"][0] = [0, 1]
    elif tamper == "lost-entry-span":
        chunk = next(chunk for chunk in raw["preparations"][0]["result"]["chunks"] if "entryEndLine" in chunk)
        del chunk["entryEndLine"]
    else:
        public["fragments"].pop()
    with pytest.raises(RuntimeOracleError):
        validate_entry_observations(raw, value, public)


@pytest.mark.parametrize("tamper", ["replace-records", "sync-target", "full-source", "cutoff", "source-options",
                                   "bare-fingerprint", "line-provenance-loss", "persisted-record"])
def test_session_replacements_original_reads_and_reset_evidence_remain_complete(original_development_captures, tamper):
    raw, value, public = _raw(original_development_captures, "session-projection")
    first_source = next(call for call in raw["calls"] if call["operation"] == "buildSessionEntry")
    if tamper == "replace-records":
        next(call for call in raw["calls"] if call["operation"] == "replaceTranscriptEvents")["events"] = []
    elif tamper == "sync-target":
        next(call for call in raw["calls"] if call["operation"] == "sync" and "sessions" in call["request"])["request"]["sessions"] = []
    elif tamper == "full-source":
        del first_source["entry"]["content"]
    elif tamper == "cutoff":
        first_source["resetRecallCutoff"] = {"state": "valid", "cutoffLine": 999}
    elif tamper == "source-options":
        first_source["options"]["sessionKey"] = "agent:main:direct:other"
    elif tamper == "bare-fingerprint":
        snapshot = raw["snapshots"][0]
        source = snapshot["state"]["sources"][0]
        source["hash"] = source["hash"].rsplit(":", 1)[-1]
        next(table for table in snapshot["physical"]["tables"] if table["name"] == "memory_index_sources")["rows"][0]["hash"] = source["hash"]
        public = map_get_fixture_paths({"provider": "none", "steps": [
            {key: snapshot[key] for key in ("label", "state", "sources")} for snapshot in raw["snapshots"]]}, raw["fixtureBase"])
    elif tamper == "line-provenance-loss":
        first_source["entry"]["lineProvenance"].pop()
    else:
        snapshot = raw["snapshots"][0]
        table = next(table for table in snapshot["physical"]["tables"] if table["name"] == "transcript_events")
        table["rows"][1]["event_json"] = '{}'
    with pytest.raises(RuntimeOracleError):
        validate_entry_observations(raw, value, public)


@pytest.fixture(scope="module")
def actual_transport_captures():
    path = Path(__file__).parents[1] / "fixtures/entry-provenance-protected-transport.json.gz"
    compressed = path.read_bytes()
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    assert len(compressed) == manifest["gzipBytes"]
    assert hashlib.sha256(compressed).hexdigest() == manifest["gzipSha256"]
    original = gzip.decompress(compressed)
    assert len(original) == manifest["rawBytes"]
    assert hashlib.sha256(original).hexdigest() == manifest["rawSha256"] == "054b2138b9c6e6b5302bf7a8c3f9fcd4f40f1ff978522c71d83ed7fb98731b6e"
    result = {}
    for observation in json.loads(original)["observations"]:
        for prefix in ("native", "case"):
            data = observation[prefix + "Json"].encode()
            assert len(data) == observation[prefix + "Bytes"]
            assert hashlib.sha256(data).hexdigest() == observation[prefix + "Sha256"]
        native = json.loads(observation["nativeJson"])
        case = json.loads(observation["caseJson"])
        assert case["covers"] == []
        result[case["input"]["kind"]] = {"native": native, "case": case}
    assert len(result) == 3
    return result


def _transport_replay(captures, kind, monkeypatch):
    from equivalence import runtime_oracle

    captured = deepcopy(captures[kind])
    native, case = captured["native"], captured["case"]
    context = native["releaseTrace"]["entryProvenanceTransport"]
    row, = native["results"]
    diagnostic, = native["runtimeDiagnostics"]
    raw, = diagnostic["rawSnapshots"]
    assert row["id"] == diagnostic["id"] == case["id"]
    # Replay the original historical local-root identity. No raw path, PID,
    # returned row or trace fact is rewritten to impersonate this checkout.
    monkeypatch.setattr(runtime_oracle, "ROOT", Path(context["adapterRoot"]))
    kwargs = {"runtime_root": context["runtimeRoot"], "bootstrap": context["bootstrap"],
        "release_by_pid": {int(pid): set(paths) for pid, paths in context["releaseByPid"].items()},
        "local_by_pid": {int(pid): set(paths) for pid, paths in context["localByPid"].items()},
        "worker_imports": context["workerImports"],
        "process_parents": {int(pid): parent for pid, parent in context["processParents"].items()}}
    return row, case, [raw], Path(raw["fixtureBase"]).parent, kwargs


@pytest.mark.parametrize("kind", ["published-memory", "prepared-provider", "session-projection"])
def test_exact_same_run_profile_validator_inputs_replay_without_reconstructed_native_fields(actual_transport_captures, kind, monkeypatch):
    row, case, diagnostic, directory, kwargs = _transport_replay(actual_transport_captures, kind, monkeypatch)
    validate_entry_provenance_raw(row, case, diagnostic, directory, **kwargs)


@pytest.mark.parametrize("kind", ["published-memory", "prepared-provider", "session-projection"])
def test_retained_original_trace_bytes_explain_every_recorded_caller_map(actual_transport_captures, kind):
    native = actual_transport_captures[kind]["native"]
    context = native["releaseTrace"]["entryProvenanceTransport"]
    local, release, parents, workers, bootstraps = {}, {}, {}, [], []
    release_hashes = {(row["package"], row["path"]): row["sha256"] for row in native["releaseSources"]}
    # This is a retention-consistency check. Published-byte authentication and
    # required same-thread artifact ownership remain the shared collector's job.
    for trace in context["rawProcessWorkerTraces"]:
        original = trace["text"].encode()
        assert len(original) == trace["bytes"]
        assert hashlib.sha256(original).hexdigest() == trace["sha256"]
        first, *events = [json.loads(line) for line in trace["text"].splitlines()]
        pid, thread = first["pid"], first["threadId"]
        assert trace["name"] == f"{pid}-{thread}.jsonl" and first["event"] == "bootstrap"
        assert first["fetchDenied"] is True and first["providerMode"] == "none"
        assert first["entryProfile"] == context["profile"]
        bootstraps.append({key: first[key] for key in ("pid", "threadId", "isMainThread", "runtime", "entryProfile")})
        if thread == 0:
            parents[str(pid)] = first["ppid"]
        for event in events:
            assert event["pid"] == pid and event["threadId"] == thread
            assert event["event"] in {"load", "resolve-native"}
            if event["kind"] == "release":
                assert release_hashes[(event["package"], event["path"])] == event["sha256"]
            if event["event"] != "load":
                continue
            if event["kind"] == "oracle" and thread == 0:
                local.setdefault(str(pid), set()).add(event["path"])
            elif event["kind"] == "release":
                if event["package"] == "node_modules/openclaw":
                    release.setdefault(str(pid), set()).add(event["path"])
                if thread > 0:
                    workers.append({key: event[key] for key in ("package", "path", "threadId", "pid")})
    assert context["bootstrap"] == bootstraps
    assert context["processParents"] == parents
    assert context["localByPid"] == {pid: sorted(paths) for pid, paths in local.items()}
    assert context["releaseByPid"] == {pid: sorted(paths) for pid, paths in release.items()}
    assert context["workerImports"] == workers


@pytest.mark.parametrize("tamper", ["not-ok", "wrong-profile", "changed-input", "missing-channel", "wrong-root",
                                   "wrong-parent", "missing-main", "wrong-node", "worker-node", "missing-local-owner",
                                   "missing-release", "wrong-clock", "scheduler-control", "performance-control",
                                   "different-provider", "public-drop"])
def test_actual_profile_guard_rejects_changed_process_runtime_inputs_or_full_payload(actual_transport_captures, tamper, monkeypatch):
    row, case, diagnostic, directory, kwargs = _transport_replay(actual_transport_captures, "published-memory", monkeypatch)
    raw, = diagnostic
    if tamper == "not-ok":
        row["ok"] = False
    elif tamper == "wrong-profile":
        case["operation"] = "entry-provider-preparation-runtime"
    elif tamper == "changed-input":
        raw["input"]["mtimeMs"] += 1
    elif tamper == "missing-channel":
        del raw["providerCalls"]
    elif tamper == "wrong-root":
        directory = directory / "other-source"
    elif tamper == "wrong-parent":
        raw["ppid"] += 1
    elif tamper == "missing-main":
        kwargs["bootstrap"] = [item for item in kwargs["bootstrap"] if item["isMainThread"] is not True]
    elif tamper == "wrong-node":
        raw["runtime"]["sha256"] = "0" * 64
    elif tamper == "worker-node":
        next(item for item in kwargs["bootstrap"] if item["isMainThread"] is not True)["runtime"]["icuVersion"] = "other"
    elif tamper == "missing-local-owner":
        paths = kwargs["local_by_pid"][raw["pid"]]
        paths.remove(next(path for path in paths if path.endswith("get-contract-runtime.mjs")))
    elif tamper == "missing-release":
        kwargs["release_by_pid"][raw["pid"]].clear()
    elif tamper == "wrong-clock":
        raw["clock"]["nowMs"] += 1
    elif tamper == "scheduler-control":
        raw["clock"]["setTimeoutUnchanged"] = False
    elif tamper == "performance-control":
        raw["clock"]["performanceNowUnchanged"] = False
    elif tamper == "different-provider":
        raw["config"]["memory"]["search"]["provider"] = "fabricated"
    else:
        del row["result"]["steps"][0]["state"]["recall"]
    with pytest.raises(RuntimeOracleError):
        validate_entry_provenance_raw(row, case, diagnostic, directory, **kwargs)
