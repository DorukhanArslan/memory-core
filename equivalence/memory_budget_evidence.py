"""Bind genuine budget returns to complete inputs, source files and SQLite state."""
import json
from pathlib import Path
import re

from equivalence.get_contract import map_get_fixture_paths
from equivalence.memory_budget_bindings import REQUIRED_ARTIFACTS
from equivalence.model_runtime_authority import validate_model_node_authority
from equivalence.memory_budget_profile import MEMORY_BUDGET_PROFILES, validate_memory_budget_input
from equivalence.search_contract import _same_json


def _require(condition, message):
    if not condition:
        from equivalence.runtime_oracle import RuntimeOracleError

        raise RuntimeOracleError(message)


def _same(left, right, message):
    _require(_same_json(left, right), message)


def validate_memory_budget_observations(raw, value, public):
    """No compaction, candidate, marker, score or hash algorithm is repeated."""
    calls = raw["calls"]
    base = Path(raw["fixtureBase"])
    workspace = str(base / "workspace")
    if value["kind"] == "memory-budget":
        _require(len(calls) == len(value["cases"]), "An original compact-helper invocation was dropped or added")
        rows = []
        for call, item in zip(calls, value["cases"], strict=True):
            _require(set(call) == {"operation", "params", "result"} and call["operation"] == "compactMemoryForBudget",
                "The ordinary helper profile omitted its complete successful return")
            _same(call["params"], item["params"], "The actual compact helper received different literal bytes or limits")
            result = call["result"]
            _require(isinstance(result, dict) and set(result) == {"compacted", "droppedDates"}
                and isinstance(result["compacted"], str) and isinstance(result["droppedDates"], list),
                "The complete original compact-helper result changed shape")
            rows.append({"id": item["id"], "result": result})
        _require(set(raw["constants"]) == {"defaultMemoryFileMaxChars"}, "An actual exported budget constant was omitted")
        expected = {"provider": "none", **raw["constants"], "cases": rows}
    else:
        position = 0

        def take(operation):
            nonlocal position
            _require(position < len(calls) and calls[position].get("operation") == operation,
                "A real store/apply/read callback was dropped, invented or reordered")
            call = calls[position]
            position += 1
            return call

        for relative, text in value["files"].items():
            _same(take("write"), {"operation": "write", "path": str(base / "workspace" / relative), "text": text},
                "An actual source file changed its literal initial path or bytes")
        _same(take("configureMemoryCoreDreamingState"), {"operation": "configureMemoryCoreDreamingState",
            "factory": "createPluginStateKeyedStore", "pluginId": "memory-core", "returnedUndefined": True},
            "The real keyed-store registration or actual configuration result was lost")
        seed = take("writeStore")
        _require(set(seed) == {"operation", "workspaceDir", "valueBefore", "valueAfter", "returnedUndefined"}
            and seed["workspaceDir"] == workspace and seed["returnedUndefined"] is True,
            "The complete original store seed request or return is missing")
        _same(seed["valueBefore"], value["recall"], "The real store seed received another literal recall state")
        applied = take("applyShortTermPromotions")
        _require(set(applied) == {"operation", "request", "result"}, "The complete ordinary apply return was dropped")
        _same(applied["request"], {"workspaceDir": workspace, "nowMs": value["nowMs"],
            "candidates": value["candidates"], **value["options"]}, "The genuine apply owner received different complete candidates or policy")
        result = applied["result"]
        _require(isinstance(result, dict) and set(result) == {"memoryPath", "applied", "appended", "reconciledExisting",
            "appliedCandidates", "rejectedCandidates", "compactedSections", "compactedDates"},
            "The full original apply return lost candidate, rejection or reconciliation fields")
        mandatory = {"key", "path", "startLine", "endLine", "source", "snippet", "recallCount", "dailyCount",
            "groundedCount", "signalCount", "avgScore", "maxScore", "uniqueQueries", "firstRecalledAt", "lastRecalledAt",
            "ageDays", "score", "recallDays", "conceptTags", "components"}
        _require(isinstance(result["appliedCandidates"], list) and isinstance(result["rejectedCandidates"], list)
            and result["applied"] == len(result["appliedCandidates"])
            and result["compactedSections"] == len(result["compactedDates"]),
            "Complete original apply counts/candidate/date arrays disagree")
        candidates = list(result["appliedCandidates"])
        for rejection in result["rejectedCandidates"]:
            _require(set(rejection) == {"candidate", "reason", "category"}
                and isinstance(rejection["reason"], str) and isinstance(rejection["category"], str),
                "An original rejected candidate lost its complete category/reason payload")
            candidates.append(rejection["candidate"])
        for candidate in candidates:
            _require(isinstance(candidate, dict) and mandatory <= set(candidate)
                and set(candidate["components"]) == {"frequency", "relevance", "diversity", "recency", "consolidation", "conceptual"},
                "A complete original candidate lost observable source, score, component or history fields")
        store = take("readStore")
        events = take("readMemoryHostEventRecords")
        _require(set(store) == set(events) == {"operation", "workspaceDir", "result"}
            and store["workspaceDir"] == events["workspaceDir"] == workspace and position == len(calls),
            "Original persisted recall/event readbacks or additional source calls were hidden")
        requests = raw["keyedStoreRequests"]
        _require(isinstance(requests, list) and requests, "The genuine keyed-store factory never executed")
        for request in requests:
            _require(set(request) == {"pluginId", "request"} and request["pluginId"] == "memory-core"
                and isinstance(request["request"].get("namespace"), str)
                and request["request"]["env"]["OPENCLAW_STATE_DIR"] == raw["ownedEnvironment"]["OPENCLAW_STATE_DIR"]
                and request["request"]["env"]["OPENCLAW_CONFIG_PATH"] == raw["ownedEnvironment"]["OPENCLAW_CONFIG_PATH"]
                and not any(name in request["request"]["env"] for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY")),
                "Actual keyed-store factory arguments escaped the owned state or forwarded provider credentials")
        files = raw["files"]
        _require(isinstance(files, list) and len({row["path"] for row in files}) == len(files)
            and all(set(row) == {"path", "bytes"} and Path(row["path"]).is_relative_to(base)
                and re.fullmatch(r"(?:[0-9a-f]{2})*", row["bytes"]) for row in files),
            "A complete owned raw source/binary file was dropped or changed type")
        by_file = {row["path"]: bytes.fromhex(row["bytes"]) for row in files}
        fs_tree = raw["fsTree"]
        stat_fields = {"path", "kind", "mode", "dev", "ino", "nlink", "size", "mtimeNs", "ctimeNs"}
        _require(isinstance(fs_tree, list) and fs_tree and len({row["path"] for row in fs_tree}) == len(fs_tree)
            and all(set(row) == stat_fields | ({"target"} if row["kind"] == "symlink" else set())
                and type(row["mode"]) is int and Path(row["path"]).is_relative_to(base)
                and all(isinstance(row[key], str) and re.fullmatch(r"-?[0-9]+", row[key])
                    for key in ("dev", "ino", "nlink", "size", "mtimeNs", "ctimeNs")) for row in fs_tree)
            and {row["path"] for row in fs_tree if row["kind"] == "file"} == set(by_file)
            and all(int(row["size"]) == len(by_file[row["path"]]) for row in fs_tree if row["kind"] == "file"),
            "The actual complete filesystem tree and original file-byte channels disagree")
        documents = []
        for relative in dict.fromkeys([*value["files"], "MEMORY.md", "DREAMS.md"]):
            content = by_file.get(str(base / "workspace" / relative))
            documents.append({"path": relative, "exists": content is not None,
                **({"bytes": content.hex(), "text": content.decode("utf-8", "replace")} if content is not None else {})})
        physical = raw["physical"]
        _require(isinstance(physical, list) and physical, "The actual persisted plugin-state SQL was omitted")
        state_rows = []
        for database in physical:
            _require(set(database) == {"path", "schema", "schemaCount", "snapshotTransaction", "tables"}
                and Path(database["path"]).is_relative_to(base) and database["path"] in by_file,
                "Complete original SQLite schema, transaction and tables are required")
            _same(database["snapshotTransaction"], {"mode": "deferred", "active": True},
                "Physical counts/schema/rows were not captured in the real deferred read transaction")
            _require(type(database["schemaCount"]) is int and database["schemaCount"] == len(database["schema"]),
                "Actual schema-count receipt differs from its complete schema")
            names = [row["name"] for row in database["schema"] if row["type"] == "table"]
            _same([table["name"] for table in database["tables"]], names, "An actual SQLite table or shadow table was omitted")
            for table in database["tables"]:
                _require(set(table) == {"name", "columns", "rowCount", "rows"}
                    and type(table["rowCount"]) is int and table["rowCount"] == len(table["rows"])
                    and table["columns"] and all(set(row) == {column["name"] for column in table["columns"]}
                        for row in table["rows"]), "A complete physical column, row or count receipt was altered")
                if table["name"] == "plugin_state_entries":
                    state_rows.extend(table["rows"])
        recall_entries, metadata, actual_events = {}, [], []
        for row in state_rows:
            if row["plugin_id"] != "memory-core":
                continue
            decoded = json.loads(row["value_json"])
            if row["namespace"] == "short-term-recall" and decoded.get("workspaceDir") == workspace:
                recall_entries[decoded["key"]] = decoded["value"]
            elif row["namespace"] == "short-term-meta" and decoded.get("workspaceDir") == workspace and decoded["key"] == "recall":
                metadata.append(decoded["value"])
            elif row["namespace"] == "memory-host.events" and decoded.get("kind") == "event":
                actual_events.append(decoded)
        _require(len(metadata) == 1, "The actual recall revision metadata was lost")
        _same(store["result"], {"version": 1, "updatedAt": metadata[0]["updatedAt"], "entries": recall_entries},
            "The complete public recall state differs from actual persisted entry/metadata JSON")
        _same(events["result"], [row["event"] for row in sorted(actual_events, key=lambda row: row["sequence"])],
            "The complete returned promotion events differ from their actual persisted sequence")
        expected = {"provider": "none", "result": result, "documents": documents, "recall": store["result"], "eventRecords": events["result"]}
    _same(public, map_get_fixture_paths(expected, str(base)), "The complete public budget result differs from original calls/files/SQL")


def validate_memory_budget_raw(row, case, diagnostic, evidence_directory, *, runtime_root, bootstrap,
                              release_by_pid, local_by_pid, process_parents, worker_imports):
    from equivalence.runtime_oracle import ROOT, RuntimeOracleError

    del worker_imports
    try:
        value = case["input"]
        validate_memory_budget_input(value)
        _require(row.get("ok") is True and MEMORY_BUDGET_PROFILES.get(case["operation"]) == value["kind"]
            and isinstance(diagnostic, list) and len(diagnostic) == 1, "A genuine successful budget profile is required")
        raw = diagnostic[0]
        fields = {"kind", "input", "fixtureBase", "pid", "ppid", "runtime", "config", "ownedEnvironment", "clock", "calls"}
        fields |= {"constants"} if value["kind"] == "memory-budget" else {"keyedStoreRequests", "physical", "files", "fsTree"}
        _require(isinstance(raw, dict) and set(raw) == fields and raw["kind"] == value["kind"],
            "A complete original budget observation channel was lost")
        _same(raw["input"], value, "The actual original profile received different literal inputs")
        base = Path(raw["fixtureBase"])
        _require(base.is_absolute() and base.parent == evidence_directory and re.fullmatch(r"native-memory-budget-[A-Za-z0-9_-]+", base.name),
            "Original budget execution escaped its exact owned evidence root")
        pid = raw["pid"]
        _require(type(pid) is int and pid > 0 and process_parents.get(pid) == raw["ppid"]
            and any(item["pid"] == pid and item["isMainThread"] is True for item in bootstrap),
            "The actual budget producer bypassed its protected process lineage")
        _require(set(REQUIRED_ARTIFACTS[case["operation"]]) <= release_by_pid.get(pid, set()),
            "The actual budget/apply/store/publication owners did not execute in the protected producer")
        runtime = validate_model_node_authority(raw["runtime"])
        for item in bootstrap:
            _same(item.get("runtime"), runtime, "A budget process or worker used a different Node/ICU/Unicode binary")
        _require({str(ROOT / "equivalence" / name) for name in ("release-oracle.mjs", "memory-budget-runtime.mjs", "get-contract-runtime.mjs")}
            <= local_by_pid.get(pid, set()) and release_by_pid.get(pid) and Path(runtime_root).is_absolute(),
            "The genuine original budget producer or complete result codec did not execute")
        _same(raw["ownedEnvironment"], {"OPENCLAW_STATE_DIR": str(base / "state"), "OPENCLAW_CONFIG_PATH": str(base / "config.json")},
            "The original budget profile used foreign state or configuration")
        _same(raw["config"], {"logging": {"level": "silent", "consoleLevel": "silent", "file": str(base / "native.log")}},
            "The actual original budget configuration changed")
        _same(raw["clock"], {"owner": "node:test", "apis": ["Date"], "nowMs": value["nowMs"],
            "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
            "The original budget profile controlled another clock or scheduling capability")
        validate_memory_budget_observations(raw, value, row["result"])
    except RuntimeOracleError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as error:
        raise RuntimeOracleError("Malformed or unauthenticated complete memory-budget evidence") from error
