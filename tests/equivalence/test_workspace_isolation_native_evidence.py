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
        "configuration": {"agents": {"defaults": {"workspace": base},
                                     "list": [{"id": "alice", "default": True, "workspace": workspace}]},
            "logging": {"level": "silent", "consoleLevel": "silent", "file": base + "/native.log"},
            "memory": {"search": {"enabled": True, "provider": "none", "fallback": "none", "sources": ["memory"],
                                  "store": {"vector": {"enabled": False}},
                                  "sync": {"onSessionStart": False, "onSearch": False, "watch": False},
                                  "query": {"minScore": 0, "maxResults": 200,
                                            "hybrid": {"temporalDecay": {"enabled": False}}}}},
            "plugins": {"entries": {"memory-core": {"config": {"dreaming": {"enabled": False}}}}}},
        "workspaceResolutions": [{"agentId": "alice", "requestedWorkspace": workspace,
                                  "engineWorkspace": workspace, "hostWorkspace": workspace}],
        "managerAcquisitions": [{"agentId": "alice", "reason": "initial", "workspace": workspace,
                                  "settingsDatabasePath": db, "status": status}],
        "snapshots": [{"label": "empty", "owners": [{**observable, "status": status,
            "fullSql": {name: table for name in ("memory_index_chunks", "memory_index_sources", "memory_index_chunks_fts",
                                                "memory_index_chunk_provenance", "memory_index_chunk_recall_metadata")}}],
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


@pytest.mark.parametrize("mutation", ["configuration", "both-resolvers-outside-root", "requested-root"])
def test_complete_real_configuration_and_all_workspace_resolutions_remain_bound_to_input(tmp_path, mutation):
    case, result, raw = _guard_input(tmp_path)
    if mutation == "configuration":
        raw[0]["configuration"]["memory"]["search"]["query"]["maxResults"] = 1
    elif mutation == "both-resolvers-outside-root":
        raw[0]["workspaceResolutions"][0].update(engineWorkspace="/other", hostWorkspace="/other")
    else:
        raw[0]["workspaceResolutions"][0]["requestedWorkspace"] = "/other"
    with pytest.raises(ValueError, match="configuration|different workspace"):
        validate_workspace_isolation_raw(case, result, raw, tmp_path)


@pytest.mark.parametrize("field,value,error", [
    ("published", [{"path": "MEMORY.md"}], "actual complete private SQL"),
    ("indexSources", [{"path": "MEMORY.md", "source": "memory"}], "actual complete private SQL"),
    ("recallStore", {"version": 1, "updatedAt": "1970-01-01T00:00:01.000Z", "entries": {"invented": {}}},
     "actual scoped plugin-state SQL"),
    ("dailyIngestionState", {"version": 1, "files": {"memory/file.md": {"mtimeMs": 1000, "size": 3}}},
     "actual scoped plugin-state SQL"),
])
def test_consistent_public_and_raw_view_forgery_cannot_detach_real_private_state(tmp_path, field, value, error):
    case, result, raw = _guard_input(tmp_path)
    raw[0]["snapshots"][0]["owners"][0][field] = deepcopy(value)
    raw[0]["result"]["steps"][0]["owners"][0][field] = deepcopy(value)
    result["steps"][0]["owners"][0][field] = deepcopy(value)
    with pytest.raises(ValueError, match=error):
        validate_workspace_isolation_raw(case, result, raw, tmp_path)
