"""Bind the one apply diagnostic to original calls, files, SQL and producers.

This validator supplies no promotion, rehydration, rejection or expected-result
algorithm. Filesystem and SQLite captures are successive observations, not one
atomic cross-surface snapshot or a proof that no transient lock existed.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat

from equivalence.get_contract import map_get_fixture_paths
from equivalence.model_runtime_authority import validate_model_node_authority
from equivalence.promotion_apply_bindings import REQUIRED_ARTIFACTS, PROMOTION_WORKER_ROUTE
from equivalence.promotion_apply_profile import (
    PROMOTION_APPLY_CASE_ID,
    PROMOTION_APPLY_OPERATION,
    validate_promotion_apply_input,
    validate_promotion_apply_profile,
)
from equivalence.promotion_ranking_evidence import KEYED_METHODS
from equivalence.search_contract import _same_json


_STAT = {
    "dev",
    "mode",
    "nlink",
    "uid",
    "gid",
    "rdev",
    "blksize",
    "ino",
    "size",
    "blocks",
    "atimeMs",
    "mtimeMs",
    "ctimeMs",
    "birthtimeMs",
    "atimeNs",
    "mtimeNs",
    "ctimeNs",
    "birthtimeNs",
}
_FLAT = {"dev", "ino", "nlink", "size", "atimeNs", "mtimeNs", "ctimeNs", "birthtimeNs"}
_HEX = re.compile(r"(?:[0-9a-f]{2})*\Z")


def _require(condition, message):
    if not condition:
        from equivalence.runtime_oracle import RuntimeOracleError

        raise RuntimeOracleError(message)


def _same(left, right, message):
    _require(_same_json(left, right), message)


def _map_paths(value, prefix):
    return map_get_fixture_paths(value, prefix)


def _owned(base, name):
    _require(
        isinstance(name, str)
        and Path(name).is_absolute()
        and ".." not in Path(name).parts
        and Path(name).is_relative_to(base),
        "An apply observation borrowed an ambient path",
    )
    return Path(name)


def _tree(entries, base):
    _require(isinstance(entries, list) and entries, "The complete apply filesystem tree is missing")
    observed = {}
    for entry in entries:
        _require(isinstance(entry, dict), "A filesystem entry lost its original fields")
        pathname = str(_owned(base, entry["path"]))
        kind = entry["kind"]
        fields = {"path", "kind", "mode", "rawStat", *_FLAT}
        fields |= {"bytes"} if kind == "file" else {"target"} if kind == "symlink" else set()
        _require(
            set(entry) == fields
            and pathname not in observed
            and kind in {"file", "directory", "symlink", "other"},
            "A complete original filesystem entry was dropped, duplicated or projected",
        )
        info = entry["rawStat"]
        _require(
            isinstance(info, dict)
            and set(info) == _STAT
            and all(
                isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value)
                for value in info.values()
            )
            and type(entry["mode"]) is int
            and entry["mode"] == int(info["mode"])
            and all(entry[key] == info[key] for key in _FLAT),
            "Every actual BigIntStats property and flattened stat receipt is required",
        )
        mode = int(info["mode"])
        actual_kind = (
            "file"
            if stat.S_ISREG(mode)
            else "directory"
            if stat.S_ISDIR(mode)
            else "symlink"
            if stat.S_ISLNK(mode)
            else "other"
        )
        _require(kind == actual_kind, "A filesystem kind differs from its original lstat mode")
        if kind == "file":
            _require(
                isinstance(entry["bytes"], str)
                and _HEX.fullmatch(entry["bytes"])
                and len(bytes.fromhex(entry["bytes"])) == int(info["size"]),
                "Every regular file requires its complete original byte channel",
            )
        if kind == "symlink":
            _require(isinstance(entry["target"], str), "An actual symlink target was omitted")
        observed[pathname] = entry
    _require(
        str(base) in observed and observed[str(base)]["kind"] == "directory",
        "The actual owned fixture root is missing",
    )
    for pathname in observed:
        if pathname != str(base):
            parent = observed.get(str(Path(pathname).parent))
            _require(
                parent is not None and parent["kind"] == "directory",
                "A filesystem observation omitted an actual parent directory",
            )
    return observed


def _physical(databases, tree, base, database):
    _require(isinstance(databases, list) and databases, "Actual complete SQLite state is required")
    expected = {
        name for name, entry in tree.items() if entry["kind"] == "file" and name.endswith(".sqlite")
    }
    _require(
        len({item["path"] for item in databases}) == len(databases)
        and {item["path"] for item in databases} == expected
        and database in expected,
        "A physical SQLite database differs from the complete actual filesystem",
    )
    plugin_rows = []
    for item in databases:
        _owned(base, item["path"])
        _require(
            set(item) == {"path", "schema", "schemaCount", "snapshotTransaction", "tables"},
            "A physical SQLite capture lost its complete original channels",
        )
        _same(
            item["snapshotTransaction"],
            {"mode": "deferred", "active": True},
            "SQLite schema, rows and counts require the actual deferred snapshot",
        )
        schema, tables = item["schema"], item["tables"]
        _require(
            isinstance(schema, list)
            and type(item["schemaCount"]) is int
            and item["schemaCount"] == len(schema)
            and all(
                isinstance(row, dict) and set(row) == {"type", "name", "tbl_name", "sql"}
                for row in schema
            )
            and [(row["type"], row["name"]) for row in schema]
            == sorted((row["type"], row["name"]) for row in schema),
            "The complete original SQLite schema/count/order was altered",
        )
        names = [row["name"] for row in schema if row["type"] == "table"]
        _require(
            isinstance(tables, list)
            and [table["name"] for table in tables] == names
            and len(names) == len(set(names)),
            "An original SQLite table was omitted",
        )
        for table in tables:
            _require(
                set(table) == {"name", "columns", "rowCount", "rows"},
                "A SQLite table lost complete columns, rows or its count",
            )
            columns, rows = table["columns"], table["rows"]
            _require(
                isinstance(columns, list)
                and columns
                and all(
                    isinstance(column, dict)
                    and set(column) == {"cid", "name", "type", "notnull", "dflt_value", "pk"}
                    for column in columns
                )
                and len({column["name"] for column in columns}) == len(columns)
                and isinstance(rows, list)
                and type(table["rowCount"]) is int
                and table["rowCount"] == len(rows)
                and all(
                    isinstance(row, dict) and set(row) == {column["name"] for column in columns}
                    for row in rows
                ),
                "Actual SELECT*/PRAGMA/count receipts lost an original row or field",
            )
            if item["path"] == database and table["name"] == "plugin_state_entries":
                plugin_rows = rows
    _require(
        any(
            table["name"] == "plugin_state_entries"
            for item in databases
            if item["path"] == database
            for table in item["tables"]
        ),
        "The genuine plugin-state table was omitted",
    )
    return plugin_rows


def _store_and_events(rows, workspace):
    """Decode physical carriers only; never implement the recall normalizer."""
    workspace_key = hashlib.sha256(workspace.encode()).hexdigest()
    entries, metadata, events = {}, [], []
    for row in rows:
        _require(
            set(row)
            == {"plugin_id", "namespace", "entry_key", "value_json", "created_at", "expires_at"},
            "A physical plugin-state row lost one of its actual columns",
        )
        if row["plugin_id"] != "memory-core":
            continue
        value = json.loads(row["value_json"])
        if row["namespace"] in {"short-term-recall", "short-term-meta"}:
            _require(
                isinstance(value, dict)
                and set(value) == {"version", "workspaceKey", "workspaceDir", "key", "value"}
                and type(value["version"]) is int
                and value["version"] == 1
                and value["workspaceKey"] == workspace_key
                and value["workspaceDir"] == workspace
                and isinstance(value["key"], str)
                and row["entry_key"]
                == workspace_key + ":" + hashlib.sha256(value["key"].encode()).hexdigest(),
                "A physical recall/meta wrapper escaped its actual workspace or key",
            )
            if row["namespace"] == "short-term-recall":
                _require(value["key"] not in entries, "A complete recall entry was duplicated")
                entries[value["key"]] = value["value"]
            elif value["key"] == "recall":
                metadata.append(value["value"])
        elif row["namespace"] == "memory-host.events" and value.get("kind") == "event":
            _require(
                isinstance(value.get("event"), dict) and type(value.get("sequence")) is int,
                "A persisted host event lost its full original carrier or sequence",
            )
            events.append(value)
    _require(
        len(metadata) == 1 and isinstance(metadata[0], dict) and set(metadata[0]) == {"updatedAt"},
        "The actual canonical recall metadata was omitted",
    )
    return (
        {"version": 1, "updatedAt": metadata[0]["updatedAt"], "entries": entries},
        [item["event"] for item in sorted(events, key=lambda item: item["sequence"])],
    )


def _documents(tree, workspace, value):
    names = dict.fromkeys(
        [*value["files"], *(item["path"] for item in value["candidates"]), "MEMORY.md", "DREAMS.md"]
    )
    result = []
    for relative in names:
        entry = tree.get(str(Path(workspace) / relative))
        if entry is None:
            result.append({"path": relative, "exists": False, "kind": "missing"})
            continue
        observed = {"path": relative, "exists": True, "kind": entry["kind"]}
        if entry["kind"] == "file":
            observed.update(
                bytes=entry["bytes"], text=bytes.fromhex(entry["bytes"]).decode("utf-8", "replace")
            )
        if entry["kind"] == "symlink":
            observed["target"] = entry["target"]
        result.append(observed)
    return result


def _outcome(call, workspace, candidates):
    fields = {"operation", "request", "requestAfter"}
    _require(
        set(call) in (fields | {"result"}, fields | {"error"}),
        "The actual apply call must retain its whole return or whole original error",
    )
    if "error" in call:
        error = call["error"]
        _require(
            isinstance(error, dict)
            and isinstance(error.get("name"), str)
            and isinstance(error.get("message"), str)
            and (isinstance(error.get("stack"), str) or "value" in error),
            "The original apply error lost its stack/own-field or thrown-value carrier",
        )
        return {"error": error}
    result = call["result"]
    _require(
        isinstance(result, dict)
        and set(result)
        == {
            "memoryPath",
            "applied",
            "appended",
            "reconciledExisting",
            "appliedCandidates",
            "rejectedCandidates",
            "compactedSections",
            "compactedDates",
        }
        and result["memoryPath"] == str(Path(workspace) / "MEMORY.md")
        and all(
            type(result[key]) is int and result[key] >= 0
            for key in ("applied", "appended", "reconciledExisting", "compactedSections")
        )
        and isinstance(result["appliedCandidates"], list)
        and isinstance(result["rejectedCandidates"], list)
        and isinstance(result["compactedDates"], list)
        and result["applied"] == len(result["appliedCandidates"])
        and result["compactedSections"] == len(result["compactedDates"]),
        "The complete eight-field original apply return was projected or changed",
    )
    observed = list(result["appliedCandidates"])
    for item in result["rejectedCandidates"]:
        _require(
            isinstance(item, dict)
            and set(item) == {"candidate", "reason", "category"}
            and isinstance(item["reason"], str)
            and isinstance(item["category"], str),
            "A complete original rejection receipt was projected",
        )
        observed.append(item["candidate"])
    _require(
        all(isinstance(item, dict) and set(candidates[0]) <= set(item) for item in observed)
        and sorted(item["key"] for item in observed) == sorted(item["key"] for item in candidates),
        "A complete original candidate receipt was omitted or projected",
    )
    return {"result": result}


def validate_promotion_apply_raw(
    row,
    case,
    diagnostic,
    evidence_directory,
    *,
    runtime_root,
    bootstrap,
    release_by_pid,
    local_by_pid,
    worker_imports,
    process_parents,
    adapter_root,
):
    """Validate protected original observations, including an actual owner error."""
    from equivalence.runtime_oracle import RuntimeOracleError

    try:
        value = validate_promotion_apply_input(case["input"])
        _require(
            case["id"] == PROMOTION_APPLY_CASE_ID
            and case["operation"] == PROMOTION_APPLY_OPERATION
            and case["covers"] == []
            and isinstance(row, dict)
            and set(row) == {"id", "ok", "result"}
            and row["id"] == case["id"]
            and row["ok"] is True,
            "Only the exact successful protected transport may supply apply evidence",
        )
        _require(
            Path(runtime_root).is_absolute()
            and Path(adapter_root).is_absolute()
            and isinstance(diagnostic, list)
            and len(diagnostic) == 1
            and isinstance(diagnostic[0], dict),
            "Apply requires its authenticated roots and one complete native observation",
        )
        raw = diagnostic[0]
        _require(
            set(raw)
            == {
                "kind",
                "input",
                "fixtureBase",
                "workspace",
                "pid",
                "ppid",
                "runtime",
                "environment",
                "config",
                "clock",
                "setup",
                "factoryCalls",
                "calls",
                "snapshots",
                "closed",
                "databasePath",
                "output",
            }
            and raw["closed"] is True
            and raw["kind"] == value["kind"],
            "An original raw apply field was lost or observation/closure failed",
        )
        _same(raw["input"], value, "The native apply caller received another literal input")
        base = Path(raw["fixtureBase"])
        workspace, pid = str(base / "workspace"), raw["pid"]
        _require(
            base.is_absolute()
            and base.parent == Path(evidence_directory)
            and re.fullmatch(r"native-promotion-apply-[A-Za-z0-9_-]+", base.name)
            and raw["workspace"] == workspace,
            "Apply escaped its exact case-owned fixture",
        )
        environment = {
            "OPENCLAW_STATE_DIR": str(base / "state"),
            "OPENCLAW_CONFIG_PATH": str(base / "openclaw.json"),
            "OPENCLAW_HOME": str(base),
        }
        _same(
            raw["environment"],
            environment,
            "The actual apply backend used ambient state or configuration",
        )
        _same(
            raw["config"],
            {
                "agents": {"defaults": {"workspace": workspace}},
                "logging": {
                    "level": "silent",
                    "consoleLevel": "silent",
                    "file": str(base / "native.log"),
                },
            },
            "The original apply process used another complete configuration",
        )
        database = str(base / "state/state/openclaw.sqlite")
        _same(
            raw["databasePath"], database, "The actual database-path owner escaped its owned state"
        )
        _same(
            raw["clock"],
            {
                "owner": "node:test",
                "apis": ["Date"],
                "nowMs": value["nowMs"],
                "dateConstructorReplaced": True,
                "setTimeoutUnchanged": True,
                "performanceNowUnchanged": True,
            },
            "Apply changed a scheduler, performance clock or its declared Date-only clock",
        )
        validate_model_node_authority(raw["runtime"])
        _require(
            isinstance(bootstrap, list) and len(bootstrap) == 2,
            "Apply requires one protected main and one original worker",
        )
        profile = validate_promotion_apply_profile(bootstrap[0]["promotionApplyProfile"])
        _require(
            type(pid) is int
            and pid > 0
            and type(raw["ppid"]) is int
            and raw["ppid"] > 0
            and process_parents == {pid: raw["ppid"]}
            and all(
                set(item) == {"pid", "threadId", "isMainThread", "runtime", "promotionApplyProfile"}
                and item["pid"] == pid
                and item["runtime"] == raw["runtime"]
                and item["promotionApplyProfile"] == profile
                for item in bootstrap
            )
            and len(
                [
                    item
                    for item in bootstrap
                    if item["isMainThread"] is True and item["threadId"] == 0
                ]
            )
            == 1
            and len(
                [
                    item
                    for item in bootstrap
                    if item["isMainThread"] is False
                    and type(item["threadId"]) is int
                    and item["threadId"] > 0
                ]
            )
            == 1,
            "Apply crossed its actual PID, exact profile, binary or main/worker lineage",
        )
        _same(
            profile["nodeRuntime"],
            raw["runtime"],
            "The apply profile borrowed another actual executable",
        )
        _require(
            set(release_by_pid) == {pid}
            and set(REQUIRED_ARTIFACTS[PROMOTION_APPLY_OPERATION]) <= release_by_pid[pid],
            "The complete original apply/store/backend owner graph did not execute",
        )
        expected_local = {
            str(Path(adapter_root) / "equivalence" / name)
            for name in (
                "release-oracle.mjs",
                "promotion-apply-runtime.mjs",
                "model-runtime-observation.mjs",
            )
        }
        _same(
            local_by_pid,
            {pid: expected_local},
            "The apply caller omitted its actual adapter or loaded another adapter",
        )
        worker = next(item["threadId"] for item in bootstrap if item["isMainThread"] is False)
        _require(
            isinstance(worker_imports, list) and worker_imports,
            "Actual raw worker imports cannot be omitted",
        )
        routes = set()
        for item in worker_imports:
            _require(
                set(item) == {"pid", "threadId", "package", "path"}
                and item["pid"] == pid
                and item["threadId"] == worker
                and item["package"] != "unverified",
                "An original worker import borrowed another actual producer",
            )
            if ".worker." in item["path"] or ".worker-" in item["path"]:
                _require(
                    item["package"] == "node_modules/openclaw"
                    and item["path"] in PROMOTION_WORKER_ROUTE,
                    "Apply started an unreviewed carrier, backend or worker kernel",
                )
                routes.add(item["path"])
        _same(
            routes,
            set(PROMOTION_WORKER_ROUTE),
            "The actual original three-part state worker route was omitted",
        )
        _require(
            "dist/extensions/memory-core/manager-runtime.js" not in release_by_pid[pid],
            "This diagnostic cannot borrow memory-manager execution",
        )
        expected_namespaces = (
            ["short-term-recall", "short-term-meta"] * 2
            + ["short-term-locks"]
            + ["short-term-recall", "short-term-meta"] * 2
        )
        _same(
            [item["options"]["namespace"] for item in raw["factoryCalls"]],
            expected_namespaces,
            "An actual configured seed/read/workspace-lease factory acquisition was lost or reordered",
        )
        for item in raw["factoryCalls"]:
            options = {
                "namespace": item["options"]["namespace"],
                "maxEntries": 4096
                if item["options"]["namespace"] == "short-term-locks"
                else 50_000,
            }
            _require(
                set(item) == {"pluginId", "options", "selectedOptions", "returnedMethods"}
                and item["pluginId"] == "memory-core",
                "A real factory receipt lost its plugin identity",
            )
            _same(
                item["options"],
                options,
                "The genuine configured factory used another namespace/capacity",
            )
            _same(
                item["selectedOptions"],
                {**options, "env": environment},
                "The real factory escaped its owned environment",
            )
            _same(
                item["returnedMethods"],
                KEYED_METHODS,
                "A real factory return surface was substituted",
            )
        setup = raw["setup"]
        _require(
            len(setup) == len(value["directories"]) + len(value["files"]),
            "An actual fixture setup call was omitted",
        )
        for item, relative in zip(setup, value["directories"], strict=True):
            filename = str(Path(workspace) / relative)
            _require(
                set(item)
                in (
                    {"operation", "path", "recursive", "returnedUndefined"},
                    {"operation", "path", "recursive", "result"},
                )
                and item["operation"] == "mkdir"
                and item["path"] == filename
                and item["recursive"] is True
                and (item.get("returnedUndefined") is True or item.get("result") == filename),
                "The actual recursive mkdir result or owned directory setup was rewritten",
            )
        calls = raw["calls"]
        _same(
            [call["operation"] for call in calls],
            [
                "configureMemoryCoreDreamingState",
                "writeStore",
                "readStore",
                "readMemoryHostEventRecords",
                "applyShortTermPromotions",
                "readStore",
                "readMemoryHostEventRecords",
                "closePluginStateStoreSqliteHandles",
            ],
            "An actual original call was omitted, reordered or added",
        )
        _same(
            calls[0],
            {"operation": "configureMemoryCoreDreamingState", "returnedUndefined": True},
            "Original configuration lost its actual undefined return",
        )
        seed = calls[1]
        _require(
            set(seed)
            == {"operation", "workspaceDir", "argumentBefore", "argumentAfter", "returnedUndefined"}
            and seed["workspaceDir"] == workspace
            and seed["returnedUndefined"] is True,
            "The actual canonical seed call lost its complete input/return",
        )
        _same(
            seed["argumentBefore"],
            value["recall"],
            "The original seed received another literal recall store",
        )
        request = {
            "workspaceDir": workspace,
            "nowMs": value["nowMs"],
            "candidates": value["candidates"],
            **value["options"],
        }
        _same(
            calls[4]["request"],
            request,
            "The original apply owner received another complete request",
        )
        _same(
            calls[4]["requestAfter"],
            request,
            "The actual complete apply request-after receipt changed",
        )
        outcome = _outcome(calls[4], workspace, value["candidates"])
        _same(
            calls[-1],
            {"operation": "closePluginStateStoreSqliteHandles", "returnedUndefined": True},
            "The genuine SQLite close owner did not settle with its actual return",
        )
        snapshots = raw["snapshots"]
        _same(
            [item["label"] for item in snapshots],
            ["before", "settlement-before-readback", "after-readback"],
            "The actual settlement boundary or before/after observation was omitted",
        )
        decoded = []
        for item in snapshots:
            _require(
                set(item) == {"label", "fsTree", "physical"},
                "A complete physical snapshot field was omitted",
            )
            tree = _tree(item["fsTree"], base)
            rows = _physical(item["physical"], tree, base, database)
            stored, events = _store_and_events(rows, workspace)
            decoded.append((tree, stored, events))
        first_tree = decoded[0][0]
        config_file = first_tree.get(environment["OPENCLAW_CONFIG_PATH"], {})
        _require(config_file.get("kind") == "file", "The actual configuration file was omitted")
        _same(
            json.loads(bytes.fromhex(config_file["bytes"])),
            raw["config"],
            "The actual complete configuration bytes differ from the native config receipt",
        )
        for relative in value["directories"]:
            directory = str(Path(workspace) / relative)
            _require(
                first_tree.get(directory, {}).get("kind") == "directory"
                and not any(name.startswith(directory + "/") for name in first_tree),
                "The literal MEMORY fixture was not an actual observed empty directory",
            )
        for candidate in value["candidates"]:
            _require(
                str(Path(workspace) / candidate["path"]) not in first_tree,
                "The literal absent candidate source was prepopulated before apply",
            )
        _same(
            seed["argumentAfter"],
            decoded[0][1],
            "The actual seed-after receipt differs from physical canonical recall rows",
        )
        now_iso = (
            datetime.fromtimestamp(value["nowMs"] / 1000, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        reads = {}
        for label, read, event, state in (
            ("before", calls[2], calls[3], decoded[0]),
            ("after", calls[5], calls[6], decoded[2]),
        ):
            _require(
                set(read) == {"operation", "label", "workspaceDir", "nowIso", "result"}
                and read["label"] == label
                and read["workspaceDir"] == workspace
                and read["nowIso"] == now_iso,
                "An original recall reader lost its complete actual request",
            )
            _require(
                set(event) == {"operation", "label", "request", "result"}
                and event["label"] == label,
                "An original persisted-event reader lost its complete actual request",
            )
            _same(
                event["request"],
                {"workspaceDir": workspace, "env": environment},
                "An actual event read escaped the owned state",
            )
            _same(
                read["result"],
                state[1],
                "The original recall return differs from complete physical wrapper rows",
            )
            _same(
                event["result"],
                state[2],
                "The complete original event return differs from physical sequenced rows",
            )
            reads[label] = {
                "documents": _documents(state[0], workspace, value),
                "recall": read["result"],
                "eventRecords": event["result"],
            }
        expected = _map_paths({"provider": "none", "outcome": outcome, **reads}, str(base))
        _same(
            row["result"],
            expected,
            "The public apply result dropped or changed original outcome/readback fields",
        )
        _same(
            raw["output"],
            expected,
            "The native caller output differs from the complete retained public transport",
        )
    except RuntimeOracleError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        IndexError,
        StopIteration,
        OverflowError,
    ) as error:
        raise RuntimeOracleError(
            "Malformed or unauthenticated complete promotion-apply evidence"
        ) from error
