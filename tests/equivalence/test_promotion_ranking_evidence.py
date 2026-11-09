"""Actual same-run original ranking captures guard complete data/authority."""

from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.promotion_ranking_evidence import validate_promotion_ranking_raw
from equivalence.runtime_oracle import RuntimeOracleError


@pytest.fixture(scope="module")
def actual_capture():
    path = Path(__file__).parents[1] / "fixtures/promotion-ranking-native-development.json.gz"
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    compressed = path.read_bytes()
    assert manifest["acceptanceProof"] is manifest["coverage"] is False
    assert len(compressed) == manifest["gzipBytes"]
    assert hashlib.sha256(compressed).hexdigest() == manifest["gzipSha256"]
    original = gzip.decompress(compressed)
    assert len(original) == manifest["rawBytes"]
    assert hashlib.sha256(original).hexdigest() == manifest["rawSha256"]
    capture = json.loads(original)
    assert capture["returncode"] == 0 and "rejected" not in capture and "error" not in capture
    assert json.loads(capture["stdout"]) == capture["originalResult"]
    assert capture["originalResult"]["results"] == capture["result"]["results"]
    return capture


def _replay(actual_capture):
    capture = deepcopy(actual_capture)
    native = capture["result"]
    transport = native["releaseTrace"]["promotionRankingTransport"]
    diagnostic = native["runtimeDiagnostics"][0]["rawSnapshots"]
    return (
        native["results"][0],
        capture["case"],
        diagnostic,
        Path(diagnostic[0]["fixtureBase"]).parent,
        {
            "runtime_root": transport["runtimeRoot"],
            "adapter_root": transport["adapterRoot"],
            "bootstrap": transport["bootstrap"],
            "release_by_pid": {int(k): set(v) for k, v in transport["releaseByPid"].items()},
            "local_by_pid": {int(k): set(v) for k, v in transport["localByPid"].items()},
            "worker_imports": transport["workerImports"],
            "process_parents": {int(k): v for k, v in transport["processParents"].items()},
        },
    )


def test_actual_complete_native_result_sql_and_same_run_producers_pass_without_reconstruction(
    actual_capture,
):
    row, case, diagnostic, directory, kwargs = _replay(actual_capture)
    validate_promotion_ranking_raw(row, case, diagnostic, directory, **kwargs)


def test_actual_original_trace_bytes_explain_every_same_run_worker_and_caller_map(actual_capture):
    native = actual_capture["result"]
    transport = native["releaseTrace"]["promotionRankingTransport"]
    release, local, parents, workers, bootstraps = {}, {}, {}, [], []
    hashes = {(row["package"], row["path"]): row["sha256"] for row in native["releaseSources"]}
    # The diagnostic's second direct file read stores name/hash/text; the
    # collector additionally records the actual byte count of the same bytes.
    assert transport["rawProcessWorkerTraces"] == [
        {**trace, "bytes": len(trace["text"].encode())} for trace in actual_capture["traceFiles"]
    ]
    for trace in transport["rawProcessWorkerTraces"]:
        original = trace["text"].encode()
        assert (
            len(original) == trace["bytes"]
            and hashlib.sha256(original).hexdigest() == trace["sha256"]
        )
        first, *events = map(json.loads, trace["text"].splitlines())
        pid, thread = first["pid"], first["threadId"]
        assert trace["name"] == f"{pid}-{thread}.jsonl"
        assert (
            first["event"] == "bootstrap"
            and first["fetchDenied"] is True
            and first["providerMode"] == "none"
        )
        assert first["promotionProfile"] == transport["profile"]
        bootstraps.append(
            {
                key: first[key]
                for key in ("pid", "threadId", "isMainThread", "runtime", "promotionProfile")
            }
        )
        if not thread:
            parents[str(pid)] = first["ppid"]
        for event in events:
            assert event["pid"] == pid and event["threadId"] == thread
            assert event["event"] in {"load", "resolve-native"}
            if event["kind"] == "release":
                assert hashes[(event["package"], event["path"])] == event["sha256"]
            if event["event"] != "load":
                continue
            if event["kind"] == "oracle" and not thread:
                local.setdefault(str(pid), set()).add(event["path"])
            if event["kind"] == "release":
                if event["package"] == "node_modules/openclaw":
                    release.setdefault(str(pid), set()).add(event["path"])
                if thread:
                    workers.append(
                        {key: event[key] for key in ("package", "path", "threadId", "pid")}
                    )
    assert transport["bootstrap"] == bootstraps
    assert transport["processParents"] == parents
    assert transport["localByPid"] == {pid: sorted(paths) for pid, paths in local.items()}
    assert transport["releaseByPid"] == {pid: sorted(paths) for pid, paths in release.items()}
    assert transport["workerImports"] == workers


@pytest.mark.parametrize(
    "tamper",
    [
        "not-ok",
        "wrong-op",
        "input",
        "raw-field",
        "workspace",
        "database",
        "environment",
        "close",
        "date",
        "scheduler",
        "performance",
        "node",
        "worker-node",
        "parent",
        "missing-main",
        "extra-worker",
        "missing-owner",
        "missing-adapter",
        "extra-adapter",
        "missing-worker-kernel",
        "extra-backend",
        "factory-plugin",
        "drop-factory",
        "extra-factory",
        "factory-env",
        "factory-cap",
        "factory-method",
        "write-input",
        "write-return",
        "drop-write",
        "read-input",
        "normalizer",
        "phase-normalizer",
        "query-options",
        "query-clock",
        "candidate-score",
        "candidate-order",
        "candidate-field",
        "public-state",
        "extra-public",
        "output",
        "schema-count",
        "missing-table",
        "row-count",
        "missing-column",
        "sql-plugin",
        "sql-workspace",
        "sql-key",
        "sql-value",
        "sql-expiry",
        "keyed-order",
        "read-transaction",
        "after-state",
    ],
)
def test_actual_profile_rejects_detached_full_fields_sql_calls_and_process_authority(
    actual_capture, tamper
):
    row, case, diagnostic, directory, kwargs = _replay(actual_capture)
    raw = diagnostic[0]
    snapshot = raw["snapshots"][0]
    table = next(
        table for table in snapshot["physical"]["tables"] if table["name"] == "plugin_state_entries"
    )
    if tamper == "not-ok":
        row["ok"] = False
    elif tamper == "wrong-op":
        case["operation"] = "index-lifecycle-runtime"
    elif tamper == "input":
        raw["input"]["nowMs"] += 1
    elif tamper == "raw-field":
        del raw["factoryCalls"]
    elif tamper == "workspace":
        raw["workspace"] += "-other"
    elif tamper == "database":
        raw["databasePath"] += "-other"
    elif tamper == "environment":
        raw["environment"]["OPENCLAW_HOME"] = "/ambient"
    elif tamper == "close":
        raw["closed"] = False
    elif tamper == "date":
        raw["clock"]["nowMs"] += 1
    elif tamper == "scheduler":
        raw["clock"]["setTimeoutUnchanged"] = False
    elif tamper == "performance":
        raw["clock"]["performanceNowUnchanged"] = False
    elif tamper == "node":
        raw["runtime"]["sha256"] = "0" * 64
    elif tamper == "worker-node":
        kwargs["bootstrap"][1]["runtime"]["icuVersion"] = "other"
    elif tamper == "parent":
        raw["ppid"] += 1
    elif tamper == "missing-main":
        kwargs["bootstrap"].pop(0)
    elif tamper == "extra-worker":
        kwargs["bootstrap"].append(deepcopy(kwargs["bootstrap"][1]))
    elif tamper == "missing-owner":
        kwargs["release_by_pid"][raw["pid"]].clear()
    elif tamper == "missing-adapter":
        kwargs["local_by_pid"][raw["pid"]].clear()
    elif tamper == "extra-adapter":
        kwargs["local_by_pid"][raw["pid"]].add("/unrelated.mjs")
    elif tamper == "missing-worker-kernel":
        kwargs["worker_imports"] = [
            item
            for item in kwargs["worker_imports"]
            if item["path"] != "dist/plugin-state.worker-Bt1nfP3u.mjs"
        ]
    elif tamper == "extra-backend":
        kwargs["worker_imports"].append(
            {
                "pid": raw["pid"],
                "threadId": 1,
                "package": "node_modules/openclaw",
                "path": "dist/state/other.worker.js",
            }
        )
    elif tamper == "drop-factory":
        raw["factoryCalls"].pop()
    elif tamper == "extra-factory":
        raw["factoryCalls"].append(deepcopy(raw["factoryCalls"][-1]))
    elif tamper == "factory-plugin":
        raw["factoryCalls"][0]["pluginId"] = "other"
    elif tamper == "factory-env":
        raw["factoryCalls"][0]["selectedOptions"]["env"] = {}
    elif tamper == "factory-cap":
        raw["factoryCalls"][0]["options"]["maxEntries"] = 1
    elif tamper == "factory-method":
        raw["factoryCalls"][0]["returnedMethods"].pop()
    elif tamper == "write-input":
        raw["writes"][0]["argumentBefore"]["updatedAt"] = "different"
    elif tamper == "write-return":
        raw["writes"][0]["returnedUndefined"] = False
    elif tamper == "drop-write":
        raw["writes"].pop()
    elif tamper == "read-input":
        raw["reads"][0]["recallInput"]["entries"].clear()
    elif tamper == "normalizer":
        raw["reads"][0]["normalizedRecall"]["entries"].clear()
    elif tamper == "phase-normalizer":
        raw["reads"][0]["normalizedPhase"]["updatedAt"] = "different"
    elif tamper == "query-options":
        raw["rankings"][0]["request"]["minScore"] = 1
    elif tamper == "query-clock":
        raw["rankings"][0]["request"]["nowMs"] += 1
    elif tamper == "candidate-score":
        row["result"]["queries"][0]["candidates"][0]["score"] += 1e-15
    elif tamper == "candidate-order":
        row["result"]["queries"][0]["candidates"].reverse()
    elif tamper == "candidate-field":
        del row["result"]["queries"][0]["candidates"][0]["components"]
    elif tamper == "public-state":
        row["result"]["before"]["recall"]["entries"].clear()
    elif tamper == "extra-public":
        row["result"]["provider"] = "none"
    elif tamper == "output":
        raw["output"]["queries"].pop()
    elif tamper == "schema-count":
        snapshot["physical"]["schemaCount"] -= 1
    elif tamper == "missing-table":
        snapshot["physical"]["tables"].pop()
    elif tamper == "row-count":
        table["rowCount"] -= 1
    elif tamper == "missing-column":
        del table["rows"][0]["created_at"]
    elif tamper == "sql-plugin":
        table["rows"][0]["plugin_id"] = "other"
    elif tamper == "sql-expiry":
        table["rows"][0]["expires_at"] = 1
    elif tamper in {"sql-workspace", "sql-key", "sql-value"}:
        wrapper = json.loads(table["rows"][0]["value_json"])
        if tamper == "sql-workspace":
            wrapper["workspaceDir"] = "/ambient"
        elif tamper == "sql-key":
            wrapper["key"] = "forged"
        else:
            wrapper["value"]["recallCount"] += 1
        table["rows"][0]["value_json"] = json.dumps(wrapper)
    elif tamper == "keyed-order":
        snapshot["keyedRows"][0]["entries"].reverse()
    elif tamper == "read-transaction":
        snapshot["physical"]["snapshotTransaction"]["active"] = False
    else:
        raw["snapshots"][1]["physical"]["tables"][0]["rowCount"] += 1
    with pytest.raises((RuntimeOracleError, ValueError)):
        validate_promotion_ranking_raw(row, case, diagnostic, directory, **kwargs)
