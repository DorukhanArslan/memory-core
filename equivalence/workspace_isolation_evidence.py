"""Validate retained native workspace-owner observations without deciding parity.

The authenticated runtime supplies loaded modules and worker imports separately.
These guards ensure public results are complete observations of the real raw
owners; they never supply isolation outcomes, accepted hits or expected state.
"""
from __future__ import annotations

from pathlib import Path
from datetime import UTC, datetime
import hashlib
import json
import re

from equivalence.get_contract import map_get_fixture_paths
from equivalence.search_contract import _same_json, decode_search_tool_envelope
from equivalence.workspace_isolation_runtime_bindings import MEMORY_INDEX_WORKER_ARTIFACTS


OWNER_FIELDS = {"agentId", "workspace", "files", "published", "indexSources", "queries", "reads",
                "recallStore", "dailyIngestionState"}


def _require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _expected_configuration(value: dict, base: str) -> dict:
    explicit = value["config"]["layout"] == "explicit"
    agents = [{"id": owner["agentId"], **({"default": True} if index == 0 else {}),
               **({"workspace": str(Path(base) / owner["workspace"])} if explicit else {})}
              for index, owner in enumerate(value["owners"])]
    return {
        "agents": {"defaults": {"workspace": base if explicit else str(Path(base) / value["owners"][0]["workspace"])},
                   "list": agents},
        "logging": {"level": "silent", "consoleLevel": "silent", "file": str(Path(base) / "native.log")},
        "plugins": {"entries": {"memory-core": {"config": {"dreaming": {"enabled": False}}}}},
        "memory": {"search": {"enabled": True, "provider": "none", "fallback": "none", "sources": ["memory"],
                  "store": {"vector": {"enabled": False}},
                  "sync": {"onSessionStart": False, "onSearch": False, "watch": False},
                  "query": {"minScore": 0, "maxResults": 200, "hybrid": {"temporalDecay": {"enabled": False}}}}},
    }


def _sql_publication(sql: dict) -> tuple[list, list]:
    required = {"memory_index_chunks", "memory_index_sources", "memory_index_chunks_fts",
                "memory_index_chunk_provenance", "memory_index_chunk_recall_metadata"}
    _require(required <= set(sql), "Native workspace private index SQL was not retained")
    for table in sql.values():
        _require(set(table) == {"columns", "rows"} and isinstance(table["columns"], list)
                 and isinstance(table["rows"], list), "Native workspace private SQL lost its schema/rows")
        columns = {column["name"] for column in table["columns"]}
        _require(all(isinstance(row, dict) and set(row) == columns for row in table["rows"]),
                 "Native workspace private SQL lost actual row columns")
    chunks = sql["memory_index_chunks"]["rows"]
    provenance = {row["chunk_id"]: row for row in sql["memory_index_chunk_provenance"]["rows"]}
    recalls = {row["chunk_id"]: row for row in sql["memory_index_chunk_recall_metadata"]["rows"]}
    fts = {row["id"]: row for row in sql["memory_index_chunks_fts"]["rows"]}
    _require(len(fts) == len(chunks), "Native workspace FTS rows differ from actual chunks")
    published = []
    for chunk in sorted(chunks, key=lambda row: (row["source"], row["path"], row["start_line"],
                                                row["end_line"], row["text"], row["id"])):
        actual_fts = fts.get(chunk["id"], {})
        _require(chunk.get("model") == "fts-only" and chunk.get("embedding") == {"type": "bytes", "hex": ""},
                 "Native workspace changed the genuine provider-none index representation")
        _require(all(actual_fts.get(key) == chunk.get(key)
                     for key in ("id", "path", "source", "start_line", "end_line", "text", "model")),
                 "Native workspace FTS rows differ from actual chunks")
        recall, origin = recalls.get(chunk["id"], {}), provenance.get(chunk["id"], {})
        published.append({"path": chunk["path"], "source": chunk["source"],
                          "startLine": chunk["start_line"], "endLine": chunk["end_line"], "text": chunk["text"],
                          "importance": recall.get("importance"), "triggers": recall.get("triggers"),
                          "projectKey": recall.get("project_key"), "provenance": {
                              "originClass": origin.get("origin_class"), "sessionKind": origin.get("session_kind"),
                              "observedAt": origin.get("observed_at"), "supersedesKey": origin.get("supersedes_key"),
                          }})
    sources = [{"path": row["path"], "source": row["source"]}
               for row in sorted(sql["memory_index_sources"]["rows"], key=lambda row: (row["source"], row["path"]))]
    return published, sources


def _state_publication(snapshot: dict, workspace: str, now_ms: int, base: str) -> tuple[dict, dict]:
    plugin_sql = snapshot.get("pluginStateSql", [])
    _require(isinstance(plugin_sql, list) and any("plugin_state_entries" in row.get("fullSql", {})
             for row in plugin_sql), "Native maintenance/recall plugin-state SQLite was not retained")
    workspace_key = hashlib.sha256(workspace.replace("\\", "/").encode()).hexdigest()
    namespaces = {"short-term-recall": {}, "short-term-meta": {}, "dreaming-daily-ingestion": {}}
    seen = set()
    for database in plugin_sql:
        _require(Path(database["filename"]).is_relative_to(Path(base) / "state"),
                 "Native workspace plugin-state database escaped its owned state root")
        table = database.get("fullSql", {}).get("plugin_state_entries")
        if table is None:
            continue
        columns = {column["name"] for column in table["columns"]}
        for row in table["rows"]:
            _require(set(row) == columns, "Native plugin-state SQL lost actual row columns")
            if row.get("plugin_id") != "memory-core" or row.get("namespace") not in namespaces:
                continue
            payload = json.loads(row["value_json"])
            if payload.get("workspaceKey") != workspace_key:
                continue
            key = payload.get("key")
            _require(set(payload) == {"version", "workspaceKey", "workspaceDir", "key", "value"}
                     and payload["version"] == 1 and payload["workspaceDir"] == workspace and isinstance(key, str),
                     "Native workspace plugin-state scope differs from its original owner")
            identity = (row["namespace"], row["entry_key"])
            _require(identity not in seen and row["entry_key"] == workspace_key + ":" + hashlib.sha256(key.encode()).hexdigest(),
                     "Native workspace plugin-state key differs from its original workspace/key owner")
            seen.add(identity)
            namespaces[row["namespace"]][key] = payload["value"]
    now_iso = datetime.fromtimestamp(now_ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    meta = namespaces["short-term-meta"].get("recall", {})
    return ({"version": 1, "updatedAt": meta.get("updatedAt", now_iso), "entries": namespaces["short-term-recall"]},
            {"version": 1, "files": namespaces["dreaming-daily-ingestion"]})


def validate_workspace_isolation_workers(worker_imports: list[dict]) -> None:
    """Require both original index-wrapper/implementation in a protected thread."""
    by_thread: dict[tuple[int, int], set[str]] = {}
    for row in worker_imports:
        if isinstance(row.get("pid"), int) and isinstance(row.get("threadId"), int) and row["threadId"] > 0:
            by_thread.setdefault((row["pid"], row["threadId"]), set()).add(row.get("path"))
    _require(any(set(MEMORY_INDEX_WORKER_ARTIFACTS) <= paths for paths in by_thread.values()),
             "Workspace isolation requires the actual protected memory-index wrapper and implementation")


def validate_workspace_isolation_raw(
    case: dict, result: dict, diagnostic: list[dict], evidence_directory: Path | None = None,
) -> None:
    """Validate exact fixture ownership, complete snapshots and original envelopes."""
    _require(len(diagnostic) == 1 and isinstance(diagnostic[0], dict), "Missing native workspace raw evidence")
    raw = diagnostic[0]
    value = case["input"]
    _require(_same_json(raw.get("input"), value), "Native workspace instructions changed")
    base = raw.get("fixtureBase")
    _require(isinstance(base, str) and Path(base).is_absolute()
             and re.fullmatch(r"native-workspace-isolation-[A-Za-z0-9_-]+", Path(base).name),
             "Native workspace fixture has no exact owned root")
    if evidence_directory is not None:
        _require(Path(base).parent == Path(evidence_directory), "Native workspace root escaped its case evidence")
    _require(raw.get("kind") == "flow" and isinstance(raw.get("pid"), int) and raw["pid"] > 0,
             "Native workspace process identity is absent")
    clock = raw.get("clock", {})
    _require(clock == {"owner": "node:test", "apis": ["Date"], "nowMs": value["nowMs"],
                       "dateConstructorReplaced": True, "setTimeoutUnchanged": True,
                       "performanceNowUnchanged": True}, "Native workspace clock changed unsupported APIs")
    cfg = raw.get("configuration", {})
    _require(_same_json(cfg, _expected_configuration(value, base)),
             "Native workspace complete host configuration differs from the selected literal fixture")
    settings = cfg.get("memory", {}).get("search", {})
    _require(settings.get("provider") == settings.get("fallback") == "none"
             and settings.get("sources") == ["memory"], "Native workspace manager changed its provider/source boundary")
    _require(cfg.get("plugins", {}).get("entries", {}).get("memory-core", {}).get("config", {})
             .get("dreaming", {}).get("enabled") is False, "Background recall recording must remain disabled")
    owner_ids = [owner["agentId"] for owner in value["owners"]]
    _require([entry.get("id") for entry in cfg.get("agents", {}).get("list", [])] == owner_ids,
             "Native host configuration changed the declared owner roster")
    resolutions = raw.get("workspaceResolutions", [])
    _require([row.get("agentId") for row in resolutions] == owner_ids, "Native workspace resolutions are incomplete")
    resolved = {row["agentId"]: row["engineWorkspace"] for row in resolutions}
    for row in resolutions:
        requested = next(owner["workspace"] for owner in value["owners"] if owner["agentId"] == row["agentId"])
        expected_workspace = Path(base) / requested
        _require(isinstance(row.get("engineWorkspace"), str)
                 and expected_workspace.is_relative_to(base)
                 and row.get("requestedWorkspace") == row.get("engineWorkspace") == str(expected_workspace)
                 and row.get("hostWorkspace") == row["engineWorkspace"],
                 "The actual host/engine owners selected different workspace boundaries")
    acquisitions = raw.get("managerAcquisitions", [])
    expected_acquisitions = [(agent, "initial") for agent in owner_ids] + [
        (agent, step["label"]) for step in value["steps"] for agent in step.get("reopenAgents", [])
    ]
    _require([(row.get("agentId"), row.get("reason")) for row in acquisitions] == expected_acquisitions,
             "Native manager construction/reopen observations are incomplete")
    for row in acquisitions:
        status = row.get("status", {})
        _require(row.get("workspace") == resolved[row["agentId"]] == status.get("workspaceDir")
                 and row.get("settingsDatabasePath") == status.get("dbPath"),
                 "Native manager authority differs from its actual resolved configuration")
    expected_writes = [("initial", item) for item in value.get("files", [])] + [
        (step["label"], item) for step in value["steps"] for item in step.get("writes", [])
    ]
    writes = raw.get("writes", [])
    _require([(row.get("label"), row.get("input")) for row in writes] == expected_writes,
             "Native literal file-write requests changed")
    for row in writes:
        selected = resolved[row["input"]["agentId"]]
        _require(row.get("selectedWorkspace") == selected
                 and Path(row.get("filename", "")) == Path(selected) / row["input"]["path"],
                 "Native file write crossed its resolved owner")
    expected_removals = [(step["label"], item) for step in value["steps"] for item in step.get("removeFiles", [])]
    _require([(row.get("label"), row.get("input")) for row in raw.get("removals", [])] == expected_removals,
             "Native literal file-removal requests changed")
    for row in raw.get("removals", []):
        _require(Path(row.get("filename", "")) == Path(resolved[row["input"]["agentId"]]) / row["input"]["path"],
                 "Native file removal crossed its resolved owner")
    _require(_same_json(map_get_fixture_paths(raw.get("result"), base), result),
             "Native workspace public result differs from its complete raw observation")
    _require(set(result) == {"provider", "steps"} and result["provider"] == "none",
             "Native workspace public result changed its declared shape")
    snapshots = raw.get("snapshots", [])
    _require(len(snapshots) == len(value["steps"]) == len(result["steps"]), "Native workspace snapshots are incomplete")
    search_rows, get_rows = raw.get("nativeSearchEnvelopes", []), raw.get("nativeGetEnvelopes", [])
    _require(len(search_rows) == sum(len(step.get("queries", [])) for step in value["steps"]),
             "Native workspace lost original search envelopes")
    _require(len(get_rows) == sum(len(step.get("reads", [])) for step in value["steps"]),
             "Native workspace lost original read envelopes")
    for step, snapshot, public in zip(value["steps"], snapshots, result["steps"], strict=True):
        _require(snapshot.get("label") == public.get("label") == step["label"]
                 and set(public) == {"label", "owners"}, "Native workspace phase identity changed")
        _require([owner.get("agentId") for owner in snapshot.get("owners", [])] == owner_ids
                 and [owner.get("agentId") for owner in public.get("owners", [])] == owner_ids,
                 "A native workspace snapshot omitted a configured owner")
        for owner, transported in zip(snapshot["owners"], public["owners"], strict=True):
            _require(set(transported) == OWNER_FIELDS and OWNER_FIELDS <= set(owner),
                     "Native workspace logical owner fields were dropped")
            _require(owner["workspace"] == resolved[owner["agentId"]]
                     and owner.get("status", {}).get("workspaceDir") == owner["workspace"],
                     "A native snapshot crossed its selected manager boundary")
            _require(_same_json(map_get_fixture_paths({key: owner[key] for key in OWNER_FIELDS}, base), transported),
                     "Native workspace output changed an observed logical field")
            sql = owner.get("fullSql", {})
            actual_published, actual_sources = _sql_publication(sql)
            _require(_same_json(actual_published, owner["published"]) and _same_json(actual_sources, owner["indexSources"]),
                     "Native workspace logical publication detached from its actual complete private SQL")
            actual_recall, actual_daily = _state_publication(snapshot, owner["workspace"], value["nowMs"], base)
            _require(_same_json(actual_recall, owner["recallStore"]) and _same_json(actual_daily, owner["dailyIngestionState"]),
                     "Native workspace recall/maintenance readback detached from its actual scoped plugin-state SQL")
            queries = [query for query in step.get("queries", []) if query["agentId"] == owner["agentId"]]
            _require([query.get("id") for query in owner["queries"]] == [query["id"] for query in queries],
                     "Native workspace query identities changed")
            for request, observed in zip(queries, owner["queries"], strict=True):
                matches = [row for row in search_rows if row.get("label") == step["label"]
                           and _same_json(row.get("input"), request)]
                _require(len(matches) == 1, "A workspace query has no unique actual envelope")
                original = matches[0]
                _require(_same_json(original.get("candidates"), observed["candidates"])
                         and _same_json(decode_search_tool_envelope(original["envelope"]), observed["result"]),
                         "Workspace query candidates or complete transport differ from the actual owner")
            reads = [read for read in step.get("reads", []) if read["agentId"] == owner["agentId"]]
            _require([read.get("id") for read in owner["reads"]] == [read["id"] for read in reads],
                     "Native workspace read identities changed")
            for request, observed in zip(reads, owner["reads"], strict=True):
                matches = [row for row in get_rows if row.get("label") == step["label"]
                           and _same_json(row.get("input"), request)]
                _require(len(matches) == 1, "A workspace read has no unique actual envelope")
                original = matches[0]
                actual = ({"error": original["error"]} if "error" in original else
                          {"result": decode_search_tool_envelope(original["envelope"])})
                _require(_same_json({"id": request["id"], **actual}, observed),
                         "Workspace read lost original transport fields")
        plugin_sql = snapshot.get("pluginStateSql", [])
        _require(isinstance(plugin_sql, list) and any("plugin_state_entries" in row.get("fullSql", {})
                 for row in plugin_sql), "Native maintenance/recall plugin-state SQLite was not retained")
    expected_recalls = [(step["label"], query) for step in value["steps"]
                        for query in step.get("queries", []) if query.get("recordRecall")]
    recall_requests = raw.get("recallRequests", [])
    _require(len(expected_recalls) == len(recall_requests), "Native awaited recall requests are incomplete")
    for (label, query), row in zip(expected_recalls, recall_requests, strict=True):
        original = next(item for item in search_rows if item["label"] == label and _same_json(item["input"], query))
        _require(row.get("label") == label and row.get("agentId") == query["agentId"]
                 and _same_json(row.get("request"), {"workspaceDir": resolved[query["agentId"]],
                    "query": query["query"], "results": original["candidates"], "nowMs": value["nowMs"]}),
                 "Native recall input differs from the actual selected search evidence")
    expected_ledgers = [(step["label"], item) for step in value["steps"] for item in step.get("maintenanceWrites", [])]
    _require([(row.get("label"), row.get("input")) for row in raw.get("ledgerWrites", [])] == expected_ledgers,
             "Native literal maintenance checkpoint requests changed")
    for row in raw.get("ledgerWrites", []):
        _require(row.get("selectedWorkspace") == resolved[row["input"]["agentId"]],
                 "Native maintenance checkpoint crossed its resolved owner")
