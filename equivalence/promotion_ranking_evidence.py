"""Authenticate rank-only observations without reproducing ranking decisions."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from equivalence.model_runtime_authority import validate_model_node_authority
from equivalence.promotion_ranking_bindings import (
    COMPILED_HASHES, PROMOTION_RANKING_OPERATION, PROMOTION_WORKER_ROUTE, validate_promotion_ranking_profile,
)
from equivalence.search_contract import _same_json


NAMESPACES = ("short-term-recall", "short-term-meta", "short-term-phase-signals")
KEYED_METHODS = ["observe", "compareAndApply", "register", "registerIfAbsent", "deleteIfEqual", "lookup", "lookupMany",
                 "consume", "delete", "entries", "entriesInKeyRange", "moveEntriesFrom", "count", "clear", "withCurrent",
                 "update", "deleteIf"]


def _require(condition, message):
    if not condition:
        from equivalence.runtime_oracle import RuntimeOracleError

        raise RuntimeOracleError(message)


def _same(left, right, message):
    _require(_same_json(left, right), message)


def _physical(value):
    """Check complete SELECT*/PRAGMA receipts, preserving every physical row."""
    _require(isinstance(value, dict) and set(value) == {"schema", "schemaCount", "tables", "snapshotTransaction"},
             "The ranking store lost a complete physical SQLite snapshot")
    _same(value["snapshotTransaction"], {"mode": "deferred", "active": True},
          "Ranking store schema/counts/rows were not observed in one actual deferred snapshot")
    schema, tables = value["schema"], value["tables"]
    _require(isinstance(schema, list) and type(value["schemaCount"]) is int and value["schemaCount"] == len(schema)
             and all(isinstance(row, dict) and set(row) == {"type", "name", "tbl_name", "sql"} for row in schema)
             and [(row["type"], row["name"]) for row in schema] == sorted((row["type"], row["name"]) for row in schema),
             "The ranking store omitted or reordered its actual full schema")
    names = [row["name"] for row in schema if row["type"] == "table"]
    _require(isinstance(tables, list) and [table.get("name") for table in tables] == names
             and len(set(names)) == len(names), "The ranking store omitted a complete physical table")
    by_table = {}
    for table in tables:
        _require(isinstance(table, dict) and set(table) == {"name", "columns", "rowCount", "rows"},
                 "A ranking SQLite table observation lost columns, counts or rows")
        columns, rows = table["columns"], table["rows"]
        _require(isinstance(columns, list) and columns and all(isinstance(column, dict)
                 and set(column) == {"cid", "name", "type", "notnull", "dflt_value", "pk"} for column in columns)
                 and len({column["name"] for column in columns}) == len(columns),
                 "A ranking physical PRAGMA column observation was dropped")
        _require(isinstance(rows, list) and type(table["rowCount"]) is int and table["rowCount"] == len(rows)
                 and all(isinstance(row, dict) and set(row) == {column["name"] for column in columns} for row in rows),
                 "Ranking physical row counts or complete SELECT* columns disagree")
        by_table[table["name"]] = rows
    _require("plugin_state_entries" in by_table and "schema_meta" in by_table
             and all(not rows for name, rows in by_table.items() if name not in {"plugin_state_entries", "schema_meta"}),
             "Rank-only execution wrote an unrelated host, manager, provider or maintenance table")
    return by_table["plugin_state_entries"]


def _store_snapshot(snapshot, workspace, database, writes):
    _require(isinstance(snapshot, dict) and set(snapshot) == {"label", "databasePath", "keyedRows", "physical"}
             and snapshot["databasePath"] == database, "The ranking store snapshot crossed its owned database")
    rows = _physical(snapshot["physical"])
    workspace_key = hashlib.sha256(workspace.encode()).hexdigest()
    decoded = {namespace: [] for namespace in NAMESPACES}
    for row in rows:
        _require(set(row) == {"plugin_id", "namespace", "entry_key", "value_json", "created_at", "expires_at"}
                 and row["plugin_id"] == "memory-core" and row["namespace"] in NAMESPACES
                 and row["expires_at"] is None and type(row["created_at"]) is int and row["created_at"] > 0,
                 "A ranking signal row changed plugin, namespace, expiry or original worker timestamp")
        wrapper = json.loads(row["value_json"])
        _require(isinstance(wrapper, dict) and set(wrapper) == {"version", "workspaceKey", "workspaceDir", "key", "value"}
                 and wrapper["version"] == 1 and wrapper["workspaceKey"] == workspace_key
                 and wrapper["workspaceDir"] == workspace and isinstance(wrapper["key"], str)
                 and row["entry_key"] == workspace_key + ":" + hashlib.sha256(wrapper["key"].encode()).hexdigest(),
                 "A physical plugin-state row escaped the actual owned workspace/key namespace")
        decoded[row["namespace"]].append({"key": row["entry_key"], "value": wrapper, "createdAt": row["created_at"]})
    # The real kernel's entries() order is created_at,entry_key. This is only a
    # SQL-to-receipt check, not a candidate ordering pass or comparison repair.
    expected = [{"namespace": namespace, "entries": sorted(decoded[namespace], key=lambda row: (row["createdAt"], row["key"]))}
                for namespace in NAMESPACES]
    _same(snapshot["keyedRows"], expected, "Actual keyed-store receipts differ from complete original physical SQL rows")
    raw_stores = {}
    for kind, namespace in (("recall", "short-term-recall"), ("phase", "short-term-phase-signals")):
        entries = {entry["value"]["key"]: entry["value"]["value"] for entry in expected[NAMESPACES.index(namespace)]["entries"]}
        _require(len(entries) == len(decoded[namespace]), "The physical ranking store duplicated a logical key")
        _same(entries, writes[kind]["argumentAfter"]["entries"],
              "Literal original store writes differ from their actual workspace-scoped physical entries")
        raw_stores[kind] = {"version": 1, "updatedAt": writes[kind]["argumentAfter"]["updatedAt"], "entries": entries}
    meta = {entry["value"]["key"]: entry["value"]["value"] for entry in decoded["short-term-meta"]}
    _same(meta, {kind: {"updatedAt": writes[kind]["argumentAfter"]["updatedAt"]} for kind in ("recall", "phase")},
          "Actual ranking metadata rows were detached from original write receipts")
    return raw_stores


def validate_promotion_ranking_raw(row, case, diagnostic, evidence_directory, *, runtime_root, bootstrap,
                                   release_by_pid, local_by_pid, worker_imports, process_parents, adapter_root):
    """Bind actual original API receipts, physical state and protected producers."""
    _require(isinstance(row, dict) and set(row) == {"id", "ok", "result"} and row["ok"] is True
             and row["id"] == case["id"] and case["operation"] == PROMOTION_RANKING_OPERATION,
             "Only the successful exact original ranking case may supply ranking evidence")
    _require(Path(runtime_root).is_absolute(), "Ranking requires its authenticated absolute published runtime root")
    _require(isinstance(diagnostic, list) and len(diagnostic) == 1 and isinstance(diagnostic[0], dict),
             "Ranking requires one complete original process observation")
    raw, value = diagnostic[0], case["input"]
    _require(set(raw) == {"kind", "fixtureBase", "workspace", "environment", "pid", "ppid", "runtime", "input", "clock",
                         "factoryCalls", "writes", "reads", "rankings", "snapshots", "closed", "databasePath", "output"},
             "Ranking observations lost an original raw field or retained a failed execution")
    _require(raw["kind"] == value["kind"] == "promotion-ranking" and raw["closed"] is True,
             "The genuine rank/store caller did not settle and close")
    _same(raw["input"], value, "The native ranking process received different literal input")
    base = Path(raw["fixtureBase"])
    workspace = str(base / "workspace")
    _require(base.is_absolute() and base.parent == evidence_directory
             and re.fullmatch(r"native-promotion-ranking-[A-Za-z0-9_-]+", base.name)
             and raw["workspace"] == workspace, "Ranking roots escaped the exact owned case fixture")
    environment = {"OPENCLAW_STATE_DIR": str(base / "state"), "OPENCLAW_CONFIG_PATH": str(base / "openclaw.json"),
                   "OPENCLAW_HOME": str(base)}
    _same(raw["environment"], environment, "Ranking plugin-state factory used an ambient host environment")
    database = str(base / "state/state/openclaw.sqlite")
    _require(raw["databasePath"] == database, "Ranking did not use its actual owned state database path")
    _same(raw["clock"], {"owner": "node:test", "apis": ["Date"], "nowMs": value["nowMs"],
          "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
          "Ranking changed scheduler ownership or omitted its main-thread Date-only clock")
    validate_model_node_authority(raw["runtime"])
    _require(isinstance(bootstrap, list) and bootstrap, "Ranking omitted protected process/worker bootstraps")
    profile = validate_promotion_ranking_profile(bootstrap[0].get("promotionProfile"))
    pid = raw["pid"]
    _require(type(pid) is int and pid > 0 and process_parents == {pid: raw["ppid"]}
             and {item["pid"] for item in bootstrap} == {pid}
             and len([item for item in bootstrap if item["isMainThread"]]) == 1
             and len([item for item in bootstrap if not item["isMainThread"]]) == 1
             and all(item.get("runtime") == raw["runtime"] and item.get("promotionProfile") == profile for item in bootstrap),
             "Ranking crossed a process, binary or unreviewed worker boundary")
    _require(set(COMPILED_HASHES) <= release_by_pid.get(pid, set()),
             "The genuine declared rank/store/physical-state owners did not execute")
    expected_local = {str(Path(adapter_root) / "equivalence" / name) for name in
                      ("release-oracle.mjs", "promotion-ranking-runtime.mjs", "model-runtime-observation.mjs")}
    _require(local_by_pid == {pid: expected_local}, "The ranking caller loaded an unrelated adapter or omitted its real caller")
    by_thread = {}
    for item in worker_imports:
        _require(item["pid"] == pid and item["package"] != "unverified", "A ranking worker forged its process authority")
        by_thread.setdefault(item["threadId"], set()).add(item["path"])
        if item["package"] == "node_modules/openclaw" and (".worker." in item["path"] or ".worker-" in item["path"]):
            _require(item["path"] in PROMOTION_WORKER_ROUTE, "Ranking started an unreviewed SQLite backend or worker")
    _require(len(by_thread) == 1 and all(set(PROMOTION_WORKER_ROUTE) <= paths for paths in by_thread.values()),
             "Ranking omitted the actual protected keyed-state worker/backend/kernel route")
    _require("dist/extensions/memory-core/manager-runtime.js" not in release_by_pid[pid],
             "This rank-only profile cannot construct a memory manager")
    calls = raw["factoryCalls"]
    _require(isinstance(calls, list) and calls and {call.get("options", {}).get("namespace") for call in calls} == set(NAMESPACES),
             "Original ranking did not acquire all actual keyed signal namespaces")
    _same([call["options"]["namespace"] for call in calls],
          ["short-term-recall", "short-term-meta", "short-term-phase-signals", "short-term-meta"] * (5 + len(value["queries"])),
          "An original seed/read/rank factory acquisition was dropped, inserted or reordered")
    for call in calls:
        _require(set(call) == {"pluginId", "options", "selectedOptions", "returnedMethods"}
                 and call["pluginId"] == "memory-core", "A ranking factory receipt lost its genuine plugin binding")
        options = {"namespace": call["options"]["namespace"], "maxEntries": 50_000}
        _same(call["options"], options, "Original dreaming state factory options were replaced")
        _same(call["selectedOptions"], {**options, "env": environment}, "The actual keyed factory escaped its owned environment")
        _same(call["returnedMethods"], KEYED_METHODS, "The genuine keyed factory return surface was substituted")
    _require(isinstance(raw["writes"], list) and len(raw["writes"]) == 2, "An original ranking seed write was omitted")
    writes = {}
    for call, kind, seed in zip(raw["writes"], ("recall", "phase"), (value["store"], value["phase"]), strict=True):
        _require(set(call) == {"kind", "workspace", "argumentBefore", "argumentAfter", "returnedUndefined"}
                 and call["kind"] == kind and call["workspace"] == workspace and call["returnedUndefined"] is True,
                 "An original seed writer lost its actual full call/void return")
        _same(call["argumentBefore"], seed, "The genuine seed writer received different literal store state")
        writes[kind] = call
    _require(len(raw["reads"]) == len(raw["snapshots"]) == 2, "Ranking omitted its complete before/after read and SQL state")
    now_iso = datetime.fromtimestamp(value["nowMs"] / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    public = row["result"]
    _require(set(public) == {"before", "queries", "after"}, "The complete rank-only public shape was projected or extended")
    for label, read, snapshot in zip(("before", "after"), raw["reads"], raw["snapshots"], strict=True):
        _require(isinstance(read, dict) and set(read) == {"label", "workspace", "nowIso", "recallInput", "phaseInput",
                 "normalizedRecall", "normalizedPhase", "recall", "phase"} and read["label"] == snapshot["label"] == label
                 and read["workspace"] == workspace and read["nowIso"] == now_iso,
                 "The genuine original store reader lost complete call/normalization observations")
        physical_inputs = _store_snapshot(snapshot, workspace, database, writes)
        for kind in ("recall", "phase"):
            _same(read[kind + "Input"], physical_inputs[kind], "Original raw-store reads differ from actual physical keyed rows")
            _require(list(read[kind + "Input"]["entries"]) == list(physical_inputs[kind]["entries"]),
                     "A raw store observation changed the original SQL-derived entry iteration order")
        _same(read["normalizedRecall"], read["recall"], "The genuine recall normalizer/retention owner differs from its public reader")
        _same(read["normalizedPhase"], read["phase"], "The genuine phase normalizer differs from its public reader")
        _same(public[label], {"recall": read["recall"], "phase": read["phase"]}, "Public ranking state differs from complete original read returns")
    _same(raw["snapshots"][0]["physical"], raw["snapshots"][1]["physical"], "Rank-only execution changed persisted host state")
    _require(len(raw["rankings"]) == len(value["queries"]) == len(public["queries"]), "An original ranking request/return was omitted")
    for query, observed, result in zip(value["queries"], raw["rankings"], public["queries"], strict=True):
        _require(set(observed) == {"label", "request", "candidates"} and observed["label"] == query["label"],
                 "An original ranking call lost its complete input/return identity")
        _require(not {"workspaceDir", "nowMs"} & query["options"].keys(), "Caller options attempted to override ranking ownership")
        _same(observed["request"], {**query["options"], "workspaceDir": workspace, "nowMs": value["nowMs"]},
              "Original rank received different literal options, workspace or clock")
        _same(result, {"label": query["label"], "candidates": observed["candidates"]},
              "The complete ordered original candidate return was dropped, sorted, rounded or projected")
    _same(raw["output"], public, "Native public ranking output differs from its complete original producer return")
