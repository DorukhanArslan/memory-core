"""Bind entry publication outputs to complete original SQL and call receipts."""
from __future__ import annotations

import json
from pathlib import Path
import re
import struct

from equivalence.get_contract import map_get_fixture_paths
from equivalence.model_runtime_authority import validate_model_node_authority
from equivalence.search_contract import _same_json


ENTRY_PROFILES = {
    "entry-memory-publication-runtime": "published-memory",
    "entry-session-publication-runtime": "session-projection",
    "entry-provider-preparation-runtime": "prepared-provider",
}


def _require(condition, message):
    if not condition:
        from equivalence.runtime_oracle import RuntimeOracleError

        raise RuntimeOracleError(message)


def _same(left, right, message):
    _require(_same_json(left, right), message)


def _embedding(value):
    _require(isinstance(value, dict) and set(value) == {"type", "hex"} and value["type"] == "bytes"
             and isinstance(value["hex"], str) and re.fullmatch(r"(?:[0-9a-f]{16})*", value["hex"]),
             "An actual SQLite embedding BLOB lost bytes or its typed carrier")
    data = bytes.fromhex(value["hex"])
    return list(struct.unpack("<" + "d" * (len(data) // 8), data))


def validate_entry_physical_state(snapshot):
    """Validate the declared SQL column/vector codec, never chunk decisions.

    Sorting here reconstructs each declared SQL ORDER BY from SELECT * rows;
    it is used only to reject wrong output order, never to repair a result.
    """
    physical, state = snapshot["physical"], snapshot["state"]
    _require(isinstance(physical, dict) and set(physical) == {"schema", "schemaCount", "tables", "snapshotTransaction"}
             and isinstance(physical["schema"], list) and isinstance(physical["tables"], list),
             "Full original physical schema and every table are required")
    _same(physical["snapshotTransaction"], {"mode": "deferred", "active": True},
          "Schema/counts/columns/rows were not observed inside the genuine deferred read snapshot")
    schema = physical["schema"]
    _require(type(physical["schemaCount"]) is int and physical["schemaCount"] == len(schema),
             "The independent actual SQLite schema count differs from its complete returned schema")
    _require(all(isinstance(row, dict) and set(row) == {"type", "name", "tbl_name", "sql"} for row in schema)
             and [(row["type"], row["name"]) for row in schema] == sorted((row["type"], row["name"]) for row in schema),
             "The original ordered complete SQLite schema was dropped or altered")
    names = [row["name"] for row in schema if row["type"] == "table"]
    tables = physical["tables"]
    _require(len(names) == len(set(names)) and [table.get("name") for table in tables] == names
             and all(isinstance(table, dict) and set(table) == {"name", "columns", "rowCount", "rows"} and isinstance(table["rows"], list)
                     and all(isinstance(row, dict) for row in table["rows"]) for table in tables),
             "A physical table, FTS shadow table or full row channel was omitted")
    for table in tables:
        columns = table["columns"]
        _require(isinstance(columns, list) and columns
                 and all(isinstance(column, dict) and set(column) == {"cid", "name", "type", "notnull", "dflt_value", "pk"}
                         and isinstance(column["name"], str) for column in columns)
                 and len({column["name"] for column in columns}) == len(columns),
                 "An actual PRAGMA table_info column or complete column observation was dropped")
        _require(type(table["rowCount"]) is int and table["rowCount"] == len(table["rows"])
                 and all(set(row) == {column["name"] for column in columns} for row in table["rows"]),
                 "An independent actual row count/column declaration differs from complete SELECT * records")
    by_table = {table["name"]: table["rows"] for table in tables}

    def records(table, columns):
        rows = by_table[table]
        _require(all(set(row) == set(columns) for row in rows),
                 "A complete original SQL row lost or invented a physical column")
        return rows

    chunks = records("memory_index_chunks", ("chunk_rowid", "id", "path", "source", "start_line", "end_line",
                                               "text", "hash", "model", "updated_at", "embedding"))
    sources = records("memory_index_sources", ("id", "path", "source", "hash", "mtime", "size"))
    origins = records("memory_index_chunk_provenance", ("chunk_id", "origin_class", "session_kind", "observed_at", "supersedes_key"))
    recall = records("memory_index_chunk_recall_metadata", ("chunk_id", "importance", "triggers", "project_key"))
    fts = records("memory_index_chunks_fts", ("id", "text", "path", "source", "start_line", "end_line", "model"))
    paths = records("memory_index_paths_fts", ("path", "source"))
    provenance = [{"chunkId": row["chunk_id"], "originClass": row["origin_class"], "sessionKind": row["session_kind"],
                   "observedAt": row["observed_at"], "supersedesKey": row["supersedes_key"]}
                  for row in sorted(origins, key=lambda row: row["chunk_id"])]
    annotations = [{"chunkId": row["chunk_id"], "importance": row["importance"], "triggers": row["triggers"],
                    "projectKey": row["project_key"]} for row in sorted(recall, key=lambda row: row["chunk_id"])]
    _require(len({row["id"] for row in chunks}) == len(chunks), "Canonical published chunk IDs were duplicated or repaired")
    by_origin = {row["chunkId"]: {key: value for key, value in row.items() if key != "chunkId"} for row in provenance}
    by_recall = {row["chunkId"]: {key: value for key, value in row.items() if key != "chunkId"} for row in annotations}
    expected_chunks = [{"id": row["id"], "path": row["path"], "source": row["source"],
        "startLine": row["start_line"], "endLine": row["end_line"], "text": row["text"], "hash": row["hash"],
        "model": row["model"], "updatedAt": row["updated_at"], "embedding": _embedding(row["embedding"]),
        "provenance": by_origin[row["id"]], "recall": by_recall[row["id"]]}
        for row in sorted(chunks, key=lambda row: row["id"])]
    expected = {
        "sources": [{key: row[key] for key in ("path", "source", "hash", "mtime", "size")}
                    for row in sorted(sources, key=lambda row: (row["source"], row["path"]))],
        "chunks": expected_chunks, "provenance": provenance, "recall": annotations,
        "details": [{"chunkId": row["id"], "hash": row["hash"], "model": row["model"], "updatedAt": row["updated_at"]}
                    for row in sorted(chunks, key=lambda row: row["id"])],
        "fts": [{"id": row["id"], "text": row["text"], "path": row["path"], "source": row["source"],
                 "startLine": row["start_line"], "endLine": row["end_line"], "model": row["model"]}
                for row in sorted(fts, key=lambda row: (row["id"], row["text"]))],
        "paths": sorted(paths, key=lambda row: (row["source"], row["path"])),
    }
    _same(state, expected, "Complete public canonical state differs from actual full physical SQL rows")
    return by_table


def validate_entry_observations(raw, value, public):
    """Bind complete public output to actual literal write/read/prepare receipts."""
    base = raw["fixtureBase"]
    calls = raw["calls"]
    _require(isinstance(calls, list) and isinstance(raw["snapshots"], list)
             and isinstance(raw["preparations"], list) and isinstance(raw["providerCalls"], list),
             "Entry provenance lost an ordered original observation channel")
    position = 0

    def take(operation):
        nonlocal position
        _require(position < len(calls), "An actual original API call was omitted")
        call = calls[position]
        position += 1
        _require(isinstance(call, dict) and call.get("operation") == operation,
                 "Original write/read/publication API order was changed")
        return call

    def writes(files):
        for relative, text in (files or {}).items():
            _same(take("write"), {"operation": "write", "relative": relative, "content": text, "mtimeMs": value["mtimeMs"]},
                  "An original file write changed its literal path, bytes or timestamp")

    def scope(item=None):
        item = item or {}
        return {"agentId": "main", "storePath": str(Path(base) / "state/agents/main/sessions/sessions.json"),
                "sessionKey": item.get("sessionKey", value.get("sessionKey")),
                "sessionId": item.get("entry", {}).get("sessionId", item.get("sessionId", value.get("sessionId")))}

    def replacement(events, target):
        _same(take("replaceTranscriptEvents"), {"operation": "replaceTranscriptEvents", "target": target,
              "events": events, "returnedUndefined": True}, "The genuine transcript replacement lost its literal records or actual return")

    for item in value.get("sessions", []):
        _same(take("upsertSessionEntry"), {"operation": "upsertSessionEntry", "target": scope(item), "entry": item["entry"],
              "returnedUndefined": True}, "The original session upsert lost complete input or its actual return")
        replacement(item["events"], scope(item))
    writes(value.get("files"))
    acquired = take("get")
    _require(set(acquired) == {"operation", "cfg", "agentId", "purpose", "status"}
             and acquired["agentId"] == "main" and acquired["purpose"] == "cli" and isinstance(acquired["status"], dict),
             "The real public manager acquisition/status observation is incomplete")
    _same(acquired["cfg"], raw["config"], "The genuine manager received a different configuration")
    if value["kind"] == "prepared-provider":
        writes({value["path"]: value["content"]})
        _require(len(raw["preparations"]) == len(raw["snapshots"]) == 1,
                 "The original exported preparation or actual kernel publication was omitted")
        prepared = raw["preparations"][0]
        _require(set(prepared) == {"request", "result"}, "The complete original preparation request/return was dropped")
        request, result = prepared["request"], prepared["result"]
        _require(set(request) == {"entry", "source", "content", "pathClassification", "chunking", "hardMaxInputTokens", "provider"}
                 and set(result) == {"contentHash", "chunks"}, "The original preparation changed its complete typed boundary")
        for key in ("content", "chunking", "hardMaxInputTokens", "provider"):
            _same(request[key], value[key], "The original preparer received different literal provider/content options")
        entry = request["entry"]
        _require(set(entry) == {"path", "absPath", "mtimeMs", "size", "hash", "kind"}
                 and entry["path"] == value["path"] and entry["absPath"] == str(Path(base) / "workspace" / value["path"])
                 and entry["mtimeMs"] == value["mtimeMs"] and entry["kind"] == "markdown" and request["source"] == "memory",
                 "The actual file-entry/source identity changed before preparation")
        _same(entry["hash"], result["contentHash"], "The immutable read's content hash was replaced before publication")
        _require(isinstance(result["chunks"], list) and len(raw["providerCalls"]) == len(result["chunks"]),
                 "An actual prepared input or literal external embedding receipt was omitted")
        embeddings = []
        for chunk, call in zip(result["chunks"], raw["providerCalls"], strict=True):
            fields = {"startLine", "endLine", "text", "hash", "embeddingInput", "provenance", "importance", "triggers", "projectKey"}
            _require(isinstance(chunk, dict) and set(chunk) in (fields, fields | {"entryStartLine", "entryEndLine"}),
                     "An original prepared chunk lost hashes, ranges, provenance or recall fields")
            _same(chunk["embeddingInput"], {"text": chunk["text"]}, "This declared provider profile requires the actual native text-input variant")
            _same(call, {"input": chunk["embeddingInput"], "result": value["embeddingVector"]},
                  "The full original embedding-input representation or literal returned vector changed")
            embeddings.append(call["result"])
        kernel = take("replaceRows")
        _same(kernel, {"operation": "replaceRows", "header": {"entry": {"path": entry["path"], "hash": result["contentHash"],
              "mtimeMs": entry["mtimeMs"], "size": entry["size"]}, "source": "memory", "model": value["provider"]["model"],
              "now": value["nowMs"], "vectorReady": False}, "chunks": result["chunks"], "embeddings": embeddings,
              "returnedUndefined": True}, "The genuine kernel lost its complete prepared request/transaction return")
        snapshot = raw["snapshots"][0]
        _require(set(snapshot) == {"state", "physical"}, "The kernel publication lost a complete SQL observation")
        validate_entry_physical_state(snapshot)
        fragments = []
        for chunk in result["chunks"]:
            matches = [row for row in snapshot["state"]["chunks"] if row["startLine"] == chunk["startLine"]
                       and row["endLine"] == chunk["endLine"] and row["hash"] == chunk["hash"] and row["text"] == chunk["text"]]
            _require(len(matches) == 1, "An original prepared fragment lost its observed canonical SQL identity")
            row = matches[0]
            provenance = chunk["provenance"]
            _require(isinstance(provenance, dict) and set(provenance) in (
                {"originClass", "sessionKind", "observedAt"}, {"originClass", "sessionKind", "observedAt", "supersedesKey"}),
                "An original prepared provenance object lost or invented fields")
            _same(row["provenance"], {"originClass": provenance["originClass"], "sessionKind": provenance["sessionKind"],
                "observedAt": provenance["observedAt"], "supersedesKey": provenance.get("supersedesKey")},
                "The genuine kernel changed an actual prepared provenance field")
            _same(row["recall"], {"importance": chunk["importance"], "triggers": chunk["triggers"], "projectKey": chunk["projectKey"]},
                "The genuine kernel changed an actual original entry's recall annotation")
            fragments.append({"id": row["id"], "startLine": chunk["startLine"], "endLine": chunk["endLine"],
                **({"entryStartLine": chunk["entryStartLine"], "entryEndLine": chunk["entryEndLine"]} if "entryStartLine" in chunk else {}),
                "text": chunk["text"], "hash": chunk["hash"], "provenance": row["provenance"], "recall": row["recall"]})
        expected = {"provider": "none", "contentHash": result["contentHash"], "fragments": fragments, "state": snapshot["state"]}
    else:
        _same(raw["preparations"], [], "Public manager execution invented an exported-helper preparation result")
        _same(raw["providerCalls"], [], "A provider-none manager invented embedding execution")
        _require(len(raw["snapshots"]) == len(value["steps"]), "An actual public sync/read phase was dropped")
        steps = []
        events = value.get("sessions", [{}])[0].get("events")
        for step, snapshot in zip(value["steps"], raw["snapshots"], strict=True):
            writes(step.get("write"))
            if "events" in step:
                events = step["events"]
                replacement(events, scope())
            _same(take("markMemoryWatchDirty"), {"operation": "markMemoryWatchDirty", "label": step["label"]},
                  "The genuine dirty owner call was dropped or relabelled")
            request = {"reason": "entry-provenance-fixture", "force": step.get("force", False),
                       **({"sessions": step["syncSessions"]} if "syncSessions" in step else {})}
            _same(take("sync"), {"operation": "sync", "request": request, "returnedUndefined": True, "label": step["label"]},
                  "The actual public sync lost its exact force, target, phase or return receipt")
            _require(set(snapshot) == {"label", "state", "sources", "physical"} and snapshot["label"] == step["label"]
                     and isinstance(snapshot["sources"], list), "A complete public manager/read phase changed")
            tables = validate_entry_physical_state(snapshot)
            if value["kind"] == "session-projection":
                records = [row for row in tables["transcript_events"] if row["session_id"] == value["sessionId"]]
                _require([row["seq"] for row in records] == list(range(len(events)))
                         and all(row["event_zstd"] is None and isinstance(row["event_json"], str) for row in records),
                         "The actual literal transcript replacement lost complete ordered ordinary records")
                _same([json.loads(row["event_json"]) for row in records], events,
                      "The actual persisted transcript differs from shared complete literal records")
                _require(bool(snapshot["sources"]), "The actual session source was not read")
                for source in snapshot["sources"]:
                    call = take("buildSessionEntry")
                    _same({key: call[key] for key in ("source", "entry", "resetRecallCutoff")}, source,
                          "Full source entry, line provenance or persisted reset cutoff was changed")
                    _require(set(call) == {"operation", "source", "options", "entry", "resetRecallCutoff"},
                             "The source read lost its original complete options or return")
                    actual_source = source["source"]
                    entry = source["entry"]
                    _require(isinstance(entry, dict) and set(entry) == {"path", "absPath", "mtimeMs", "revisionMs", "size", "hash", "content", "lineMap", "messageTimestampsMs", "lineProvenance", "sessionKind"}
                             and len(entry["lineMap"]) == len(entry["messageTimestampsMs"]) == len(entry["lineProvenance"]),
                             "A complete original session entry lost source ranges, timestamps or line provenance")
                    indexed = [row for row in snapshot["state"]["sources"] if row["source"] == "sessions" and row["path"] == entry["path"]]
                    _require(len(indexed) == 1 and indexed[0]["hash"].startswith("sqlite:")
                             and indexed[0]["hash"].rsplit(":", 1)[-1] == entry["hash"]
                             and float(indexed[0]["hash"].split(":")[1]) == entry["revisionMs"],
                             "The actual indexed SQLite fingerprint was detached from the complete original source read")
                    _same(call["options"], {"generatedByDreamingNarrative": False, "generatedByCronRun": False,
                        "sessionKind": actual_source["sessionKind"], **scope(), "updatedAtMs": actual_source["updatedAtMs"]},
                        "The genuine source reader received another session identity or policy option")
            else:
                _same(snapshot["sources"], [], "A memory-only profile invented session projection execution")
            steps.append({key: snapshot[key] for key in ("label", "state", "sources")})
        expected = {"provider": "none", "steps": steps}
    _same(take("close"), {"operation": "close", "completed": True}, "The actual public manager did not complete its close")
    _require(position == len(calls), "Original API calls were added or hidden after settlement")
    _same(public, map_get_fixture_paths(expected, base), "The complete public result differs from original SQL/read/preparation receipts")


def validate_entry_provenance_raw(row, case, diagnostic, evidence_directory, *, runtime_root, bootstrap,
                                  release_by_pid, local_by_pid, worker_imports, process_parents):
    """Transport guards; artifact and exact worker-owner checks remain shared."""
    del worker_imports
    from equivalence.runtime_oracle import ROOT, RuntimeOracleError

    try:
        value = case["input"]
        _require(ENTRY_PROFILES.get(case["operation"]) == value.get("kind"), "An entry operation crossed its declared native profile")
        _require(row.get("ok") is True and isinstance(diagnostic, list) and len(diagnostic) == 1,
                 "Entry provenance requires its actual successful complete execution")
        raw = diagnostic[0]
        _require(isinstance(raw, dict) and set(raw) == {"kind", "fixtureBase", "input", "config", "pid", "ppid", "runtime",
                 "calls", "snapshots", "preparations", "providerCalls", "clock"} and raw["kind"] == value["kind"],
                 "The entry profile lost a complete original observation channel")
        _same(raw["input"], value, "The actual original entry profile received different literal inputs")
        base = raw["fixtureBase"]
        _require(isinstance(base, str) and Path(base).is_absolute() and Path(base).parent == evidence_directory
                 and re.fullmatch(r"native-entry-provenance-[A-Za-z0-9_-]+", Path(base).name),
                 "Entry provenance escaped its exact owned source root")
        pid = raw["pid"]
        _require(type(pid) is int and pid > 0 and type(raw["ppid"]) is int and process_parents.get(pid) == raw["ppid"]
                 and any(item.get("pid") == pid and item.get("isMainThread") is True for item in bootstrap),
                 "The actual entry producer bypassed its protected process lineage")
        runtime = validate_model_node_authority(raw["runtime"])
        for item in bootstrap:
            _same(item.get("runtime"), runtime, "An entry process or worker used another Node/ICU/Unicode binary")
        _require({str(ROOT / ("equivalence/" + name)) for name in (
            "release-oracle.mjs", "entry-provenance-runtime.mjs", "get-contract-runtime.mjs", "model-runtime-observation.mjs")}
            <= local_by_pid.get(pid, set()) and bool(release_by_pid.get(pid))
            and isinstance(runtime_root, str) and Path(runtime_root).is_absolute(),
            "The actual entry runtime, canonical codec or genuine release source did not execute")
        now = value.get("nowMs", (value.get("steps") or [{}])[0].get("nowMs"))
        _same(raw["clock"], {"owner": "node:test", "apis": ["Date"], "nowMs": now, "dateConstructorReplaced": True,
              "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
              "Entry provenance controlled an undeclared scheduling or performance clock")
        config = {"agents": {"defaults": {"workspace": str(Path(base) / "workspace")}},
            "logging": {"level": "silent", "consoleLevel": "silent", "file": str(Path(base) / "native.log")},
            "session": {"maintenance": {"mode": "warn"}}, "memory": {"search": {"enabled": True, "provider": "none", "fallback": "none",
                "sources": ["sessions"] if value["kind"] == "session-projection" else ["memory"], "rememberAcrossConversations": True,
                "experimental": {"sessionMemory": True}, "store": {"vector": {"enabled": False}}}}}
        _same(raw["config"], config, "The actual entry manager used another provider, corpus, source root or host configuration")
        validate_entry_observations(raw, value, row["result"])
    except RuntimeOracleError:
        raise
    except (KeyError, ValueError, TypeError, AttributeError, IndexError, struct.error) as error:
        raise RuntimeOracleError("Malformed or unauthenticated complete entry provenance evidence") from error
