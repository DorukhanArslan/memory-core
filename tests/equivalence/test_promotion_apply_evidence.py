"""Synthetic structural guard challenges, never native behavior/capture evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from equivalence.get_contract import map_get_fixture_paths
from equivalence.model_runtime_authority import APPROVED_NODE_RUNTIME
from equivalence.promotion_apply_bindings import (
    PROMOTION_APPLY_OPERATION,
    REQUIRED_ARTIFACTS,
    PROMOTION_WORKER_ROUTE,
)
from equivalence.promotion_apply_evidence import validate_promotion_apply_raw
from equivalence.promotion_apply_profile import PROMOTION_APPLY_CASE_WIRE_SHA256
from equivalence.promotion_apply_reconcile_fixtures import build_promotion_apply_reconcile_cases
from equivalence.promotion_ranking_evidence import KEYED_METHODS
from equivalence.runtime_oracle import RuntimeOracleError


def _synthetic_transport(owner_error=False):
    """A labelled carrier tests rejection logic, not original runtime execution."""
    case = build_promotion_apply_reconcile_cases()[0]
    value = case["input"]
    base = Path("/synthetic/evidence/native-promotion-apply-labelled")
    workspace, database = str(base / "workspace"), str(base / "state/state/openclaw.sqlite")
    environment = {
        "OPENCLAW_STATE_DIR": str(base / "state"),
        "OPENCLAW_CONFIG_PATH": str(base / "openclaw.json"),
        "OPENCLAW_HOME": str(base),
    }
    config = {
        "agents": {"defaults": {"workspace": workspace}},
        "logging": {"level": "silent", "consoleLevel": "silent", "file": str(base / "native.log")},
    }
    runtime = {"execPath": "/reviewed/node", **APPROVED_NODE_RUNTIME}
    profile = {
        "kind": "approved-promotion-apply-profile",
        "operation": PROMOTION_APPLY_OPERATION,
        "inputKind": value["kind"],
        "nodeRuntime": runtime,
        "caseWireSha256": PROMOTION_APPLY_CASE_WIRE_SHA256,
    }
    calls = [
        {"operation": "configureMemoryCoreDreamingState", "returnedUndefined": True},
        {
            "operation": "writeStore",
            "workspaceDir": workspace,
            "argumentBefore": deepcopy(value["recall"]),
            "argumentAfter": deepcopy(value["recall"]),
            "returnedUndefined": True,
        },
    ]
    reads = {}
    for label in ("before", "after"):
        reads[label] = {
            "documents": [
                {"path": value["candidates"][0]["path"], "exists": False, "kind": "missing"},
                {"path": "MEMORY.md", "exists": True, "kind": "directory"},
                {"path": "DREAMS.md", "exists": False, "kind": "missing"},
            ],
            "recall": deepcopy(value["recall"]),
            "eventRecords": [],
        }
    request = {
        "workspaceDir": workspace,
        "nowMs": value["nowMs"],
        "candidates": deepcopy(value["candidates"]),
        **value["options"],
    }
    if owner_error:
        outcome = {
            "error": {
                "name": "SyntheticGuardError",
                "message": "Labelled, never thrown by native",
                "stack": "SyntheticGuardError: labelled fixture",
                "code": "ESTATIC",
                "extra": {"kept": 1},
                "cause": {
                    "name": "Error",
                    "message": "Labelled nested cause",
                    "stack": "Error: labelled cause",
                },
            }
        }
    else:
        outcome = {
            "result": {
                "memoryPath": workspace + "/MEMORY.md",
                "applied": 0,
                "appended": 0,
                "reconciledExisting": 0,
                "appliedCandidates": [],
                "rejectedCandidates": [
                    {
                        "candidate": deepcopy(value["candidates"][0]),
                        "reason": "Synthetic guard receipt",
                        "category": "Synthetic guard label",
                    }
                ],
                "compactedSections": 0,
                "compactedDates": [],
            }
        }
    for label in ("before", "after"):
        calls.extend(
            [
                {
                    "operation": "readStore",
                    "label": label,
                    "workspaceDir": workspace,
                    "nowIso": "2026-05-26T16:00:00.000Z",
                    "result": deepcopy(value["recall"]),
                },
                {
                    "operation": "readMemoryHostEventRecords",
                    "label": label,
                    "request": {"workspaceDir": workspace, "env": environment},
                    "result": [],
                },
            ]
        )
        if label == "before":
            calls.append(
                {
                    "operation": "applyShortTermPromotions",
                    "request": deepcopy(request),
                    "requestAfter": deepcopy(request),
                    **deepcopy(outcome),
                }
            )
    calls.append({"operation": "closePluginStateStoreSqliteHandles", "returnedUndefined": True})
    workspace_key = hashlib.sha256(workspace.encode()).hexdigest()
    rows = []
    for namespace, entries in (
        ("short-term-recall", value["recall"]["entries"]),
        ("short-term-meta", {"recall": {"updatedAt": value["recall"]["updatedAt"]}}),
    ):
        for key, item in entries.items():
            wrapper = {
                "version": 1,
                "workspaceKey": workspace_key,
                "workspaceDir": workspace,
                "key": key,
                "value": item,
            }
            rows.append(
                {
                    "plugin_id": "memory-core",
                    "namespace": namespace,
                    "entry_key": workspace_key + ":" + hashlib.sha256(key.encode()).hexdigest(),
                    "value_json": json.dumps(wrapper),
                    "created_at": 1,
                    "expires_at": None,
                }
            )
    names = ["plugin_id", "namespace", "entry_key", "value_json", "created_at", "expires_at"]
    columns = [
        {"cid": index, "name": name, "type": "TEXT", "notnull": 0, "dflt_value": None, "pk": 0}
        for index, name in enumerate(names)
    ]
    physical = [
        {
            "path": database,
            "schema": [
                {
                    "type": "table",
                    "name": "plugin_state_entries",
                    "tbl_name": "plugin_state_entries",
                    "sql": "Labelled synthetic schema, never executed",
                }
            ],
            "schemaCount": 1,
            "snapshotTransaction": {"mode": "deferred", "active": True},
            "tables": [
                {
                    "name": "plugin_state_entries",
                    "columns": columns,
                    "rowCount": len(rows),
                    "rows": rows,
                }
            ],
        }
    ]
    tree = []

    def entry(path, kind, content=b""):
        mode = 0o40700 if kind == "directory" else 0o100600
        info = {
            key: "0"
            for key in (
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
            )
        }
        info.update(
            mode=str(mode), dev="1", ino=str(len(tree) + 1), nlink="1", size=str(len(content))
        )
        flat = {
            key: info[key]
            for key in (
                "dev",
                "ino",
                "nlink",
                "size",
                "atimeNs",
                "mtimeNs",
                "ctimeNs",
                "birthtimeNs",
            )
        }
        tree.append(
            {
                "path": str(path),
                "kind": kind,
                "mode": mode,
                "rawStat": info,
                **flat,
                **({"bytes": content.hex()} if kind == "file" else {}),
            }
        )

    for path in (
        base,
        base / "state",
        base / "state/state",
        base / "workspace",
        base / "workspace/MEMORY.md",
    ):
        entry(path, "directory")
    entry(database, "file", b"Labelled bytes, not an executable or actual SQLite capture")
    entry(base / "openclaw.json", "file", json.dumps(config).encode())
    namespaces = (
        ["short-term-recall", "short-term-meta"] * 2
        + ["short-term-locks"]
        + ["short-term-recall", "short-term-meta"] * 2
    )
    factories = []
    for namespace in namespaces:
        options = {
            "namespace": namespace,
            "maxEntries": 4096 if namespace == "short-term-locks" else 50_000,
        }
        factories.append(
            {
                "pluginId": "memory-core",
                "options": options,
                "selectedOptions": {**options, "env": environment},
                "returnedMethods": list(KEYED_METHODS),
            }
        )
    output = map_get_fixture_paths({"provider": "none", "outcome": outcome, **reads}, str(base))
    raw = {
        "kind": value["kind"],
        "input": deepcopy(value),
        "fixtureBase": str(base),
        "workspace": workspace,
        "pid": 123,
        "ppid": 122,
        "runtime": runtime,
        "environment": environment,
        "config": config,
        "clock": {
            "owner": "node:test",
            "apis": ["Date"],
            "nowMs": value["nowMs"],
            "dateConstructorReplaced": True,
            "setTimeoutUnchanged": True,
            "performanceNowUnchanged": True,
        },
        "setup": [
            {
                "operation": "mkdir",
                "path": workspace + "/MEMORY.md",
                "recursive": True,
                "result": workspace + "/MEMORY.md",
            }
        ],
        "factoryCalls": factories,
        "calls": calls,
        "snapshots": [
            {"label": label, "fsTree": deepcopy(tree), "physical": deepcopy(physical)}
            for label in ("before", "settlement-before-readback", "after-readback")
        ],
        "closed": True,
        "databasePath": database,
        "output": deepcopy(output),
    }
    bootstrap = [
        {
            "pid": 123,
            "threadId": thread,
            "isMainThread": thread == 0,
            "runtime": deepcopy(runtime),
            "promotionApplyProfile": deepcopy(profile),
        }
        for thread in (0, 1)
    ]
    kwargs = {
        "runtime_root": "/synthetic/node_modules/openclaw",
        "adapter_root": "/synthetic/adapter",
        "bootstrap": bootstrap,
        "release_by_pid": {123: set(REQUIRED_ARTIFACTS[PROMOTION_APPLY_OPERATION])},
        "local_by_pid": {
            123: {
                "/synthetic/adapter/equivalence/" + name
                for name in (
                    "release-oracle.mjs",
                    "promotion-apply-runtime.mjs",
                    "model-runtime-observation.mjs",
                )
            }
        },
        "worker_imports": [
            {"pid": 123, "threadId": 1, "package": "node_modules/openclaw", "path": path}
            for path in PROMOTION_WORKER_ROUTE
        ],
        "process_parents": {123: 122},
    }
    return {"id": case["id"], "ok": True, "result": output}, case, [raw], base.parent, kwargs


def _validate(carrier):
    row, case, diagnostic, directory, kwargs = carrier
    validate_promotion_apply_raw(row, case, diagnostic, directory, **kwargs)


@pytest.mark.parametrize("owner_error", [False, True])
def test_labelled_complete_transport_passes_only_structural_guards(owner_error):
    _validate(_synthetic_transport(owner_error))


@pytest.mark.parametrize(
    "tamper",
    [
        "transport-error",
        "case",
        "wire",
        "raw-field",
        "pid",
        "profile",
        "node",
        "extra-worker",
        "missing-worker-route",
        "foreign-worker",
        "foreign-worker-pid",
        "missing-artifact",
        "extra-adapter",
        "factory-namespace",
        "lease-capacity",
        "factory-method",
        "factory-env",
        "setup-return",
        "drop-call",
        "request",
        "request-after",
        "return-field",
        "candidate-field",
        "public-return",
        "close",
        "snapshot-label",
        "raw-stat",
        "flat-stat",
        "file-bytes",
        "config-bytes",
        "directory-kind",
        "directory-child",
        "missing-parent",
        "sql-column",
        "sql-row-count",
        "sql-transaction",
        "physical-recall",
        "recall-read",
        "event-read",
        "seed-after",
        "output",
        "scheduler",
    ],
)
def test_labelled_mutations_cannot_keep_structural_authority(tamper):
    carrier = _synthetic_transport()
    row, case, diagnostic, _directory, kwargs = carrier
    raw = diagnostic[0]
    if tamper == "transport-error":
        row["ok"] = False
    elif tamper == "case":
        case["id"] = "unreviewed"
    elif tamper == "wire":
        case["input"]["options"]["limit"] += 1
    elif tamper == "raw-field":
        raw["expectedOutcome"] = {}
    elif tamper == "pid":
        raw["pid"] += 1
    elif tamper == "profile":
        kwargs["bootstrap"][0]["promotionApplyProfile"]["operation"] = "unreviewed"
    elif tamper == "node":
        kwargs["bootstrap"][1]["runtime"]["sha256"] = "unreviewed"
    elif tamper == "extra-worker":
        kwargs["bootstrap"].append(deepcopy(kwargs["bootstrap"][1]))
    elif tamper == "missing-worker-route":
        kwargs["worker_imports"].pop()
    elif tamper == "foreign-worker":
        kwargs["worker_imports"][0]["path"] = "dist/unreviewed.worker.js"
    elif tamper == "foreign-worker-pid":
        kwargs["worker_imports"][0]["pid"] += 1
    elif tamper == "missing-artifact":
        kwargs["release_by_pid"][123].remove(
            next(iter(REQUIRED_ARTIFACTS[PROMOTION_APPLY_OPERATION]))
        )
    elif tamper == "extra-adapter":
        kwargs["local_by_pid"][123].add("/synthetic/adapter/equivalence/unreviewed.mjs")
    elif tamper == "factory-namespace":
        raw["factoryCalls"][4]["options"]["namespace"] = "unreviewed"
    elif tamper == "lease-capacity":
        raw["factoryCalls"][4]["options"]["maxEntries"] = 50_000
    elif tamper == "factory-method":
        raw["factoryCalls"][0]["returnedMethods"].pop()
    elif tamper == "factory-env":
        raw["factoryCalls"][0]["selectedOptions"]["env"]["OPENAI_API_KEY"] = "synthetic"
    elif tamper == "setup-return":
        raw["setup"][0]["result"] = "/ambient"
    elif tamper == "drop-call":
        raw["calls"].pop(3)
    elif tamper == "request":
        raw["calls"][4]["request"]["limit"] = 6
    elif tamper == "request-after":
        raw["calls"][4]["requestAfter"].pop("candidates")
    elif tamper == "return-field":
        raw["calls"][4]["result"].pop("reconciledExisting")
    elif tamper == "candidate-field":
        raw["calls"][4]["result"]["rejectedCandidates"][0]["candidate"].pop("components")
    elif tamper == "public-return":
        row["result"]["outcome"]["result"]["rejectedCandidates"][0]["reason"] = "forged"
    elif tamper == "close":
        raw["closed"] = False
    elif tamper == "snapshot-label":
        raw["snapshots"][1]["label"] = "after"
    elif tamper == "raw-stat":
        raw["snapshots"][0]["fsTree"][0]["rawStat"].pop("atimeMs")
    elif tamper == "flat-stat":
        raw["snapshots"][0]["fsTree"][0]["ino"] = "999"
    elif tamper == "file-bytes":
        raw["snapshots"][0]["fsTree"][-1]["bytes"] = "00"
    elif tamper == "config-bytes":
        entry = raw["snapshots"][0]["fsTree"][-1]
        original = bytes.fromhex(entry["bytes"])
        entry["bytes"] = original.replace(b"silent", b"loud!!").hex()
    elif tamper == "directory-kind":
        raw["snapshots"][0]["fsTree"][4]["kind"] = "file"
    elif tamper == "directory-child":
        entry = deepcopy(raw["snapshots"][0]["fsTree"][-1])
        entry["path"] = raw["workspace"] + "/MEMORY.md/hidden"
        raw["snapshots"][0]["fsTree"].append(entry)
    elif tamper == "missing-parent":
        raw["snapshots"][0]["fsTree"].pop(2)
    elif tamper == "sql-column":
        raw["snapshots"][0]["physical"][0]["tables"][0]["columns"].pop()
    elif tamper == "sql-row-count":
        raw["snapshots"][0]["physical"][0]["tables"][0]["rowCount"] += 1
    elif tamper == "sql-transaction":
        raw["snapshots"][0]["physical"][0]["snapshotTransaction"]["active"] = False
    elif tamper == "physical-recall":
        raw["snapshots"][0]["physical"][0]["tables"][0]["rows"][0]["value_json"] = "{}"
    elif tamper == "recall-read":
        raw["calls"][2]["result"]["entries"] = {}
    elif tamper == "event-read":
        raw["calls"][3]["result"] = [{"type": "synthetic-omitted-event"}]
    elif tamper == "seed-after":
        raw["calls"][1]["argumentAfter"]["entries"] = {}
    elif tamper == "output":
        raw["output"]["provider"] = "unreviewed"
    elif tamper == "scheduler":
        raw["clock"]["setTimeoutUnchanged"] = False
    with pytest.raises(RuntimeOracleError):
        _validate(carrier)


@pytest.mark.parametrize("tamper", ["error-stack", "error-cause", "error-extra", "error-vs-result"])
def test_full_original_owner_error_is_preserved_inside_successful_transport(tamper):
    carrier = _synthetic_transport(owner_error=True)
    row, _case, diagnostic, _directory, _kwargs = carrier
    raw = diagnostic[0]
    if tamper == "error-stack":
        raw["calls"][4]["error"].pop("stack")
    elif tamper == "error-cause":
        row["result"]["outcome"]["error"].pop("cause")
    elif tamper == "error-extra":
        row["result"]["outcome"]["error"].pop("extra")
    else:
        row["result"]["outcome"] = {"result": {}}
    with pytest.raises(RuntimeOracleError):
        _validate(carrier)
