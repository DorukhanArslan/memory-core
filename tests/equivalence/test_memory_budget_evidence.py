"""Replay authentic protected development returns; no fresh acceptance credit."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.memory_budget_evidence import validate_memory_budget_raw
from equivalence.memory_budget_bindings import NATIVE_ARTIFACTS
from equivalence.runtime_oracle import RuntimeOracleError


@pytest.fixture(scope="module")
def captures():
    path = Path(__file__).parents[1] / "fixtures/memory-budget-protected-development.json.gz"
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    compressed = path.read_bytes()
    assert len(compressed) == manifest["gzipBytes"]
    assert hashlib.sha256(compressed).hexdigest() == manifest["gzipSha256"]
    original = gzip.decompress(compressed)
    assert len(original) == manifest["rawBytes"]
    assert hashlib.sha256(original).hexdigest() == manifest["rawSha256"] == "bce1562930c79f24aa5ae29f68e1ba33825e1d4343f8d4a802ccfc908e1842f9"
    result = {}
    for item in json.loads(original)["observations"]:
        for prefix in ("native", "case"):
            data = item[prefix + "Json"].encode()
            assert len(data) == item[prefix + "Bytes"]
            assert hashlib.sha256(data).hexdigest() == item[prefix + "Sha256"]
        native, case = json.loads(item["nativeJson"]), json.loads(item["caseJson"])
        assert case["covers"] == []
        result[case["input"]["kind"]] = {"native": native, "case": case}
    return result


def _replay(captures, kind, monkeypatch):
    from equivalence import runtime_oracle

    capture = deepcopy(captures[kind])
    native, case = capture["native"], capture["case"]
    context = native["releaseTrace"]["memoryBudgetTransport"]
    row, = native["results"]
    diagnostic, = native["runtimeDiagnostics"]
    assert context["actualReturnedRow"] == row
    raw, = diagnostic["rawSnapshots"]
    assert row["ok"] is True and row["id"] == case["id"] == diagnostic["id"]
    # Historical local-owner identity is supplied to the path guard, without
    # rewriting the original captured native paths, PIDs or returned fields.
    monkeypatch.setattr(runtime_oracle, "ROOT", Path(context["adapterRoot"]))
    kwargs = {"runtime_root": context["runtimeRoot"], "bootstrap": context["bootstrap"],
        "release_by_pid": {int(pid): set(paths) for pid, paths in context["releaseByPid"].items()},
        "local_by_pid": {int(pid): set(paths) for pid, paths in context["localByPid"].items()},
        "process_parents": {int(pid): parent for pid, parent in context["processParents"].items()},
        "worker_imports": context["workerImports"]}
    return row, case, [raw], Path(raw["fixtureBase"]).parent, kwargs


@pytest.mark.parametrize("kind", ["memory-budget", "memory-budget-apply"])
def test_complete_original_rows_and_actual_transport_inputs_pass(captures, kind, monkeypatch):
    row, case, diagnostic, directory, kwargs = _replay(captures, kind, monkeypatch)
    validate_memory_budget_raw(row, case, diagnostic, directory, **kwargs)


@pytest.mark.parametrize("kind", ["memory-budget", "memory-budget-apply"])
def test_retained_actual_trace_bytes_explain_all_original_owner_and_process_maps(captures, kind):
    native = captures[kind]["native"]
    context = native["releaseTrace"]["memoryBudgetTransport"]
    local, release, parents, workers, bootstrap = {}, {}, {}, [], []
    hashes = {(row["package"], row["path"]): row["sha256"] for row in native["releaseSources"]}
    for trace in context["rawProcessWorkerTraces"]:
        content = trace["text"].encode()
        assert len(content) == trace["bytes"] and hashlib.sha256(content).hexdigest() == trace["sha256"]
        first, *events = [json.loads(line) for line in trace["text"].splitlines()]
        pid, thread = first["pid"], first["threadId"]
        assert trace["name"] == f"{pid}-{thread}.jsonl" and first["budgetProfile"] == context["profile"]
        assert first["fetchDenied"] is True and first["providerMode"] == "none"
        bootstrap.append({key: first[key] for key in ("pid", "threadId", "isMainThread", "runtime", "budgetProfile")})
        if thread == 0:
            parents[str(pid)] = first["ppid"]
        for event in events:
            assert event["pid"] == pid and event["threadId"] == thread
            assert event["event"] in {"load", "resolve-native"}
            if event["event"] == "resolve-native":
                # Native resolutions are authenticated separately by the
                # shared loader; they are not falsely called ESM load records.
                assert NATIVE_ARTIFACTS[(event["package"], event["path"])] == event["sha256"]
            elif event["kind"] == "release":
                assert hashes[(event["package"], event["path"])] == event["sha256"]
            if event["event"] != "load":
                continue
            if event["kind"] == "oracle" and thread == 0:
                local.setdefault(str(pid), set()).add(event["path"])
            elif event["kind"] == "release":
                if event["package"] == "node_modules/openclaw":
                    release.setdefault(str(pid), set()).add(event["path"])
                if thread > 0:
                    workers.append({key: event[key] for key in ("package", "path", "threadId", "pid")})
    assert context["bootstrap"] == bootstrap
    assert context["processParents"] == parents
    assert context["localByPid"] == {pid: sorted(paths) for pid, paths in local.items()}
    assert context["releaseByPid"] == {pid: sorted(paths) for pid, paths in release.items()}
    assert context["workerImports"] == workers


@pytest.mark.parametrize("tamper", ["not-ok", "operation", "input", "node", "parent", "local-owner", "original-owner",
                                   "foreign-root", "clock", "scheduler", "configuration", "state-root", "public-drop"])
def test_process_input_clock_and_complete_public_transport_cannot_be_forged(captures, tamper, monkeypatch):
    row, case, diagnostic, directory, kwargs = _replay(captures, "memory-budget", monkeypatch)
    raw, = diagnostic
    if tamper == "not-ok":
        row["ok"] = False
    elif tamper == "operation":
        case["operation"] = "memory-budget-apply-runtime"
    elif tamper == "input":
        raw["input"]["nowMs"] += 1
    elif tamper == "node":
        raw["runtime"]["sha256"] = "0" * 64
    elif tamper == "parent":
        raw["ppid"] += 1
    elif tamper == "local-owner":
        paths = kwargs["local_by_pid"][raw["pid"]]
        paths.remove(next(path for path in paths if path.endswith("get-contract-runtime.mjs")))
    elif tamper == "original-owner":
        kwargs["release_by_pid"][raw["pid"]].remove("dist/memory-budget-BodJnew-.mjs")
    elif tamper == "foreign-root":
        directory = directory / "other"
    elif tamper == "clock":
        raw["clock"]["nowMs"] += 1
    elif tamper == "scheduler":
        raw["clock"]["setTimeoutUnchanged"] = False
    elif tamper == "configuration":
        raw["config"]["logging"]["level"] = "other"
    elif tamper == "state-root":
        raw["ownedEnvironment"]["OPENCLAW_STATE_DIR"] += "/other"
    else:
        row["result"]["cases"].pop()
    with pytest.raises(RuntimeOracleError):
        validate_memory_budget_raw(row, case, diagnostic, directory, **kwargs)


@pytest.mark.parametrize("tamper", ["literal-bytes", "literal-limit", "result-field", "dropped-call", "added-call"])
def test_actual_compaction_arguments_and_complete_returns_are_bound(captures, tamper, monkeypatch):
    row, case, diagnostic, directory, kwargs = _replay(captures, "memory-budget", monkeypatch)
    raw, = diagnostic
    if tamper == "literal-bytes":
        raw["calls"][0]["params"]["newSection"] = "other source bytes"
    elif tamper == "literal-limit":
        raw["calls"][0]["params"]["budgetChars"] += 1
    elif tamper == "result-field":
        del raw["calls"][0]["result"]["droppedDates"]
    elif tamper == "dropped-call":
        raw["calls"].pop()
    else:
        raw["calls"].append(deepcopy(raw["calls"][-1]))
    with pytest.raises(RuntimeOracleError):
        validate_memory_budget_raw(row, case, diagnostic, directory, **kwargs)


@pytest.mark.parametrize("tamper", ["factory", "store-input", "apply-options", "apply-candidate", "return-field",
                                   "candidate-field", "candidate-components", "file-bytes", "recall-row", "recall-meta",
                                   "event-row", "sql-row", "sql-column", "sql-table", "sql-schema", "sql-transaction", "fs-tree", "fs-stat", "fs-stat-field"])
def test_apply_receipts_files_and_all_physical_sql_channels_are_preserved(captures, tamper, monkeypatch):
    row, case, diagnostic, directory, kwargs = _replay(captures, "memory-budget-apply", monkeypatch)
    raw, = diagnostic
    calls = {call["operation"]: call for call in raw["calls"]}
    table = next(table for database in raw["physical"] for table in database["tables"] if table["name"] == "plugin_state_entries")
    if tamper == "factory":
        raw["keyedStoreRequests"].clear()
    elif tamper == "store-input":
        calls["writeStore"]["valueBefore"]["entries"].clear()
    elif tamper == "apply-options":
        calls["applyShortTermPromotions"]["request"]["memoryFileMaxChars"] += 1
    elif tamper == "apply-candidate":
        calls["applyShortTermPromotions"]["request"]["candidates"][0]["snippet"] = "invented source"
    elif tamper == "return-field":
        del calls["applyShortTermPromotions"]["result"]["reconciledExisting"]
    elif tamper == "candidate-field":
        del calls["applyShortTermPromotions"]["result"]["appliedCandidates"][0]["firstRecalledAt"]
    elif tamper == "candidate-components":
        del calls["applyShortTermPromotions"]["result"]["appliedCandidates"][0]["components"]["consolidation"]
    elif tamper == "file-bytes":
        next(file for file in raw["files"] if file["path"].endswith("/workspace/MEMORY.md"))["bytes"] = "00"
    elif tamper in {"recall-row", "recall-meta", "event-row"}:
        namespace = {"recall-row": "short-term-recall", "recall-meta": "short-term-meta", "event-row": "memory-host.events"}[tamper]
        actual = next(record for record in table["rows"] if record["namespace"] == namespace)
        value = json.loads(actual["value_json"])
        if tamper == "recall-row":
            value["value"]["snippet"] = "invented saved entry"
        elif tamper == "recall-meta":
            value["value"]["updatedAt"] = "other revision"
        else:
            value["event"]["applied"] += 1
        actual["value_json"] = json.dumps(value)
    elif tamper == "sql-row":
        table["rows"].pop()
    elif tamper == "sql-column":
        del table["rows"][0]["entry_key"]
    elif tamper == "sql-table":
        raw["physical"][0]["tables"].pop()
    elif tamper == "sql-schema":
        raw["physical"][0]["schema"].pop()
    elif tamper == "sql-transaction":
        raw["physical"][0]["snapshotTransaction"]["active"] = False
    elif tamper == "fs-tree":
        raw["fsTree"].remove(next(item for item in raw["fsTree"] if item["kind"] == "file"))
    elif tamper == "fs-stat":
        next(item for item in raw["fsTree"] if item["kind"] == "file")["size"] = "0"
    else:
        del raw["fsTree"][0]["ino"]
    with pytest.raises(RuntimeOracleError):
        validate_memory_budget_raw(row, case, diagnostic, directory, **kwargs)
