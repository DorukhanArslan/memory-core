"""Guard rejection tests; synthetic evidence never establishes native parity."""
from copy import deepcopy

import pytest

from equivalence.get_contract import map_get_fixture_paths
from equivalence.workspace_isolation_evidence import (
    validate_workspace_isolation_raw,
    validate_workspace_isolation_workers,
)
from equivalence.workspace_isolation_runtime_bindings import MEMORY_INDEX_WORKER_ARTIFACTS


def _guard_input(tmp_path):
    base = str(tmp_path / "native-workspace-isolation-example")
    workspace = base + "/subjects/alice"
    db = base + "/state/agents/alice/agent/openclaw-agent.sqlite"
    value = {"kind": "flow", "nowMs": 1000, "config": {"layout": "explicit"},
             "owners": [{"agentId": "alice", "subjectId": "alice", "workspace": "subjects/alice"}],
             "steps": [{"label": "empty"}]}
    observable = {"agentId": "alice", "workspace": workspace, "files": [], "published": [],
                  "indexSources": [], "queries": [], "reads": [],
                  "recallStore": {"version": 1, "updatedAt": "1970-01-01T00:00:01.000Z", "entries": {}},
                  "dailyIngestionState": {"version": 1, "files": {}}}
    table = {"columns": [], "rows": []}
    status = {"workspaceDir": workspace, "dbPath": db}
    result = {"provider": "none", "steps": [{"label": "empty", "owners": [observable]}]}
    raw = {"kind": "flow", "pid": 123, "fixtureBase": base, "input": value,
        "clock": {"owner": "node:test", "apis": ["Date"], "nowMs": 1000,
                  "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
        "configuration": {"agents": {"list": [{"id": "alice"}]},
            "memory": {"search": {"provider": "none", "fallback": "none", "sources": ["memory"]}},
            "plugins": {"entries": {"memory-core": {"config": {"dreaming": {"enabled": False}}}}}},
        "workspaceResolutions": [{"agentId": "alice", "engineWorkspace": workspace, "hostWorkspace": workspace}],
        "managerAcquisitions": [{"agentId": "alice", "reason": "initial", "workspace": workspace,
                                  "settingsDatabasePath": db, "status": status}],
        "snapshots": [{"label": "empty", "owners": [{**observable, "status": status,
            "fullSql": {name: table for name in ("memory_index_chunks", "memory_index_sources", "memory_index_chunks_fts")}}],
            "pluginStateSql": [{"filename": base + "/state/openclaw.sqlite", "fullSql": {"plugin_state_entries": table}}]}],
        "result": result}
    return {"input": deepcopy(value)}, map_get_fixture_paths(result, base), [deepcopy(raw)]


def test_complete_retained_shape_is_accepted_by_raw_protocol_guard(tmp_path):
    case, result, raw = _guard_input(tmp_path)
    validate_workspace_isolation_raw(case, result, raw, tmp_path)


@pytest.mark.parametrize("change,expected", [
    (lambda raw: raw[0]["clock"].update(setTimeoutUnchanged=False), "clock"),
    (lambda raw: raw[0]["workspaceResolutions"][0].update(hostWorkspace="/other"), "different workspace"),
    (lambda raw: raw[0]["managerAcquisitions"][0].update(workspace="/other"), "manager authority"),
    (lambda raw: raw[0]["snapshots"][0]["owners"][0]["fullSql"].clear(), "private index SQL"),
    (lambda raw: raw[0]["snapshots"][0]["pluginStateSql"].clear(), "plugin-state SQLite"),
    (lambda raw: raw[0]["result"]["steps"][0]["owners"][0]["dailyIngestionState"].update(version=2), "public result"),
])
def test_missing_or_rewritten_actual_owner_evidence_is_rejected(tmp_path, change, expected):
    case, result, raw = _guard_input(tmp_path)
    change(raw)
    with pytest.raises(ValueError, match=expected):
        validate_workspace_isolation_raw(case, result, raw, tmp_path)


def test_declared_fixture_root_cannot_escape_its_case_evidence(tmp_path):
    case, result, raw = _guard_input(tmp_path)
    with pytest.raises(ValueError, match="escaped"):
        validate_workspace_isolation_raw(case, result, raw, tmp_path / "other")


def test_actual_index_wrapper_and_implementation_must_share_a_protected_worker_thread():
    wrapper, implementation = MEMORY_INDEX_WORKER_ARTIFACTS
    with pytest.raises(ValueError, match="protected memory-index"):
        validate_workspace_isolation_workers([
            {"pid": 9, "threadId": 1, "path": wrapper},
            {"pid": 9, "threadId": 2, "path": implementation},
        ])
    with pytest.raises(ValueError, match="protected memory-index"):
        validate_workspace_isolation_workers([{"pid": 9, "threadId": 0, "path": path}
                                              for path in MEMORY_INDEX_WORKER_ARTIFACTS])
    validate_workspace_isolation_workers([{"pid": 9, "threadId": 1, "path": path}
                                          for path in MEMORY_INDEX_WORKER_ARTIFACTS])
