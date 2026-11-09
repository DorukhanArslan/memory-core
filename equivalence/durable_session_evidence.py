"""Bind fresh-process public results to protected original owners and raw IO."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from equivalence.durable_session_codec import map_durable_session_identities
from equivalence.durable_session_runtime_bindings import (
    APPEND_PHASE_ARTIFACTS, MEMORY_INDEX_WORKER_ARTIFACTS, REQUIRED_PHASE_ARTIFACTS, RANKING_DEFAULT_ARTIFACTS,
    METADATA_PROJECTION_ARTIFACTS, ROTATED_PRIVATE_FIELDS_ARTIFACTS,
)
from equivalence.get_contract import map_get_fixture_paths
from equivalence.search_contract import _same_json


def validate_durable_session_raw(row, case, diagnostic, evidence_directory, *, runtime_root,
                                 bootstrap, release_by_pid, local_by_pid, worker_imports, process_parents):
    from equivalence.runtime_oracle import RuntimeOracleError

    def require(condition, message):
        if not condition:
            raise RuntimeOracleError(message)

    value = case["input"]
    require(value.get("kind") == "durable" and isinstance(value.get("phases"), list)
            and [phase.get("label") for phase in value["phases"]] == ["write", "continue", "verify"],
            "Durable fixtures require three explicitly ordered process phases.")
    require(row["ok"] and isinstance(diagnostic, list) and len(diagnostic) == 1,
            "Durable evidence must retain every successful fresh process.")
    raw = diagnostic[0]
    require(isinstance(raw, dict) and set(raw) == {"fixtureBase", "kind", "coordinatorPid", "phases"}
            and raw["kind"] == "durable", "The durable coordinator raw schema changed.")
    base = raw["fixtureBase"]
    require(isinstance(base, str) and Path(base).is_absolute() and Path(base).parent == evidence_directory
            and re.fullmatch(r"native-durable-session-[A-Za-z0-9_-]+", Path(base).name),
            "Durable storage must belong to this exact isolated case.")
    records = raw["phases"]
    require(isinstance(records, list) and len(records) == 3,
            "Durability requires retained evidence from three fresh OS processes.")
    identity = {key: item for key, item in value.items() if key != "phases"}
    pids = [record.get("pid") for record in records]
    coordinator = raw["coordinatorPid"]
    require(all(type(pid) is int and pid > 0 for pid in [coordinator, *pids])
            and len(set([coordinator, *pids])) == 4,
            "Durable phases must use three distinct child PIDs and their genuine coordinator.")
    main_pids = {entry["pid"] for entry in bootstrap if entry["isMainThread"]}
    require({coordinator, *pids} <= main_pids
            and {entry["pid"] for entry in bootstrap} <= main_pids
            and all(process_parents.get(pid) == coordinator for pid in pids),
            "Every durable child OS process must inherit the trusted preload and retain its real parent.")
    for helper in main_pids - {coordinator, *pids}:
        require(process_parents.get(helper) in pids
                and "dist/infra/sqlite-integrity.worker.js" in release_by_pid.get(helper, set())
                and "dist/openclaw-agent-db-maintenance-DBuIm8El.mjs"
                in release_by_pid.get(process_parents.get(helper), set())
                and not local_by_pid.get(helper),
                "An incidental native process has no genuine protected SQLite integrity owner and phase lineage.")
    from equivalence.runtime_oracle import ROOT

    require({str(ROOT / "equivalence/release-oracle.mjs"),
             str(ROOT / "equivalence/durable-session-runtime.mjs"),
             str(ROOT / "equivalence/durable-session-codec.mjs")} <= local_by_pid.get(coordinator, set()),
            "The original coordinator and exact anchor codec must execute in the protected parent.")
    expected_snapshots, store_paths = [], []
    previous_finish = -1
    for index, (record, phase) in enumerate(zip(records, value["phases"], strict=True)):
        label, pid = phase["label"], record["pid"]
        require(set(record) == {"label", "pid", "request", "requestJson", "requestSha256", "startedAtNs",
                               "exit", "finishedAtNs", "stdout", "stderr", "raw"}
                and record["label"] == label and record["exit"] == {"code": 0, "signal": None},
                "A durable phase lost its actual successful process exit or identity.")
        start, finish = record["startedAtNs"], record["finishedAtNs"]
        require(isinstance(start, str) and start.isdigit() and isinstance(finish, str) and finish.isdigit()
                and previous_finish <= int(start) < int(finish),
                "Durable processes must exit before the following phase starts.")
        previous_finish = int(finish)
        request = {"input": identity, "phase": phase, "directory": base, "runtimeRoot": runtime_root}
        require(_same_json(record["request"], request) and isinstance(record["requestJson"], str)
                and _same_json(json.loads(record["requestJson"]), request)
                and hashlib.sha256(record["requestJson"].encode()).hexdigest() == record["requestSha256"],
                "A durable child received different inputs or a forwarded prior history.")
        require(isinstance(record["stdout"], str) and isinstance(record["stderr"], str),
                "Durable child stdout and stderr must remain retained.")
        output = json.loads(record["stdout"])
        require(isinstance(output, dict) and set(output) == {"result", "raw"}
                and _same_json(output["raw"], record["raw"]),
                "A child raw observation differs from its original complete stdout.")
        observed = record["raw"]
        require(isinstance(observed, dict) and observed.get("label") == label and observed.get("pid") == pid
                and observed.get("ppid") == coordinator and observed.get("fixtureBase") == base
                and _same_json(observed.get("request"), request),
                "A durable child raw observation forged another process, root or request.")
        clock = observed.get("clock")
        require(clock == {"owner": "node:test", "apis": ["Date"], "nowMs": phase.get("nowMs", value["nowMs"]),
                          "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
                "Only the genuine builtin Date clock may be controlled in a durable phase.")
        require(str(ROOT / "equivalence/durable-session-phase.mjs") in local_by_pid.get(pid, set())
                and str(ROOT / "equivalence/durable-session-phase-cli.mjs") in local_by_pid.get(pid, set())
                and str(ROOT / "equivalence/get-contract-runtime.mjs") in local_by_pid.get(pid, set()),
                "A fresh durable child did not execute its authenticated phase and owned-root codecs.")
        loaded = release_by_pid.get(pid, set())
        require(set(REQUIRED_PHASE_ARTIFACTS) <= loaded,
                "A durable process omitted its original persisted-read, branch, model-context or manager owner.")
        require(set(METADATA_PROJECTION_ARTIFACTS) <= loaded,
                "A durable getter omitted its actual canonical metadata or participant projection owner.")
        if phase.get("sessions"):
            require(set(ROTATED_PRIVATE_FIELDS_ARTIFACTS) <= loaded,
                    "A durable upsert omitted its actual generation-private-field and recovery-clear owner.")
        settings = observed.get("resolvedManagerSettings")
        require(isinstance(settings, dict)
                and set(RANKING_DEFAULT_ARTIFACTS) <= loaded
                and _same_json(settings.get("query", {}).get("hybrid", {}).get("temporalDecay"),
                               {"enabled": True, "halfLifeDays": 30})
                and settings.get("store", {}).get("databasePath") == str(
                    Path(base) / "state" / "agents" / value.get("agentId", "main") / "agent/openclaw-agent.sqlite"),
                "The actual resolved manager settings must retain the original enabled/30-day decay policy and store identity.")
        if phase.get("appendMessages"):
            require(set(APPEND_PHASE_ARTIFACTS) <= loaded,
                    "An append phase omitted its real message, header, mutation or anchor owner.")
        by_thread = {}
        for item in worker_imports:
            if item["pid"] == pid:
                by_thread.setdefault(item["threadId"], set()).add(item["path"])
        index_threads = [paths for paths in by_thread.values()
                         if set(MEMORY_INDEX_WORKER_ARTIFACTS) & paths]
        require(all(set(MEMORY_INDEX_WORKER_ARTIFACTS) <= paths for paths in index_threads)
                and (label == "verify" or bool(index_threads)),
                "Actual durable index work requires the wrapper and implementation in one protected child worker.")
        require(observed.get("syncRequest") == {"reason": "durable-session-reopen", "force": label != "verify"},
                "A reopen verification cannot force a publication or impersonate a write phase.")
        writes = observed.get("sessionWrites")
        appends = observed.get("appendWrites")
        require(isinstance(writes, list) and len(writes) == len(phase.get("sessions", []))
                and isinstance(appends, list) and len(appends) == len(phase.get("appendMessages", [])),
                "Every literal durable mutation must retain its actual accessor call and result.")
        if label == "verify":
            require(not writes and not appends, "The third process must perform zero catalog upserts or transcript appends.")
        paths = observed.get("storePaths")
        agent = value.get("agentId", "main")
        database_path = str(Path(base) / "state" / "agents" / agent / "agent/openclaw-agent.sqlite")
        catalog_path = str(Path(base) / "state" / "agents" / agent / "sessions/sessions.json")
        require(paths == {"databasePath": database_path, "catalogStorePath": catalog_path},
                "The declared store identity must be the original actual agent storage path.")
        for written, supplied in zip(writes, phase.get("sessions", []), strict=True):
            require(written.get("target") == {"agentId": agent, "storePath": catalog_path,
                                               "sessionKey": supplied.get("sessionKey", value["sessionKey"]),
                                               "sessionId": supplied["entry"]["sessionId"]}
                    and _same_json(written.get("entry"), supplied["entry"])
                    and ("events" in written) == ("events" in supplied)
                    and _same_json(written.get("events"), supplied.get("events"))
                    and isinstance(written.get("participantWrites"), list)
                    and len(written["participantWrites"]) == len(supplied.get("participants", [])),
                    "A durable catalog write changed literal metadata, events, participant count or session identity.")
        snapshot = observed.get("snapshot")
        require(isinstance(snapshot, dict) and snapshot.get("label") == label,
                "Every fresh process must retain its complete persisted snapshot.")
        public = {key: item for key, item in snapshot.items() if key not in {"sessionSql", "fullSql", "managerStatus"}}
        portable = map_get_fixture_paths(public, base)
        require(_same_json(output["result"], portable),
                "A durable child public snapshot differs from its original persisted observations.")
        require(isinstance(snapshot.get("sessionSql"), dict)
                and {"session_nodes", "session_windows", "transcript_events", "transcript_rewrite_watermarks",
                     "transcript_event_identities", "session_transcript_active_events"} <= snapshot["sessionSql"].keys(),
                "A durable snapshot must retain the actual complete catalog and transcript SQL tables.")
        for table in snapshot["sessionSql"].values():
            require(isinstance(table, dict) and set(table) == {"columns", "rows"}
                    and isinstance(table["columns"], list) and bool(table["columns"])
                    and isinstance(table["rows"], list), "Actual durable SQL schemas and rows cannot be omitted.")
        full_sql = snapshot.get("fullSql")
        require(isinstance(full_sql, dict) and set(full_sql) == {"chunks", "fts", "sources", "provenance", "recall"}
                and all(isinstance(item, list) for item in full_sql.values())
                and isinstance(observed.get("indexBeforeSync"), dict)
                and set(observed["indexBeforeSync"]) == set(full_sql),
                "Both actual pre-sync and post-sync persisted index rows must remain retained.")
        chunk_fields = ("id", "path", "source", "model", "start_line", "end_line", "text")
        chunk_rows = [{key: entry[key] for key in chunk_fields} for entry in full_sql["chunks"]]
        fts_rows = [{key: entry[key] for key in chunk_fields} for entry in full_sql["fts"]]
        require(_same_json(chunk_rows, fts_rows)
                and all(entry.get("embeddingHex") == "" for entry in full_sql["chunks"]),
                "Durable provider-none index evidence must retain matching persisted FTS and empty-vector chunk rows.")
        source_reads = observed.get("sourceReads")
        require(isinstance(source_reads, list) and len(source_reads) == len(snapshot["admitted"])
                and _same_json([entry["source"] for entry in source_reads], snapshot["admitted"])
                and _same_json([entry["result"] for entry in source_reads], snapshot["sourceEntries"]),
                "Every admitted durable source must reach the actual source reader with a retained result.")
        for source in source_reads:
            require(_same_json(source["result"]["source"], source["source"])
                    and all(source["options"].get(key) == source["source"].get(key)
                            for key in ("agentId", "sessionId", "sessionKey", "storePath", "updatedAtMs")),
                    "A durable source read swapped the actual current or retained session identity.")
        contexts = observed.get("contextRequests")
        require(isinstance(contexts, list) and len(contexts) == 1 + len(phase.get("identityReads", [])),
                "Every durable current-key read must retain its actual branch and model-visible continuation.")
        main_context = contexts[0]["result"]
        require(_same_json(main_context.get("entry"), snapshot.get("currentEntry"))
                and all(_same_json(main_context[key], snapshot[key]) for key in
                        ("events", "visibleEvents", "context", "modelMessages", "preludeFlags", "modelPreludeFlags"))
                and _same_json([entry["result"] for entry in contexts[1:]], snapshot["identityReads"]),
                "The raw model context or private current-key read differs from its public snapshot.")
        for original, supplied in zip(contexts, [{}, *phase.get("identityReads", [])], strict=True):
            requested = {"agentId": agent, "storePath": catalog_path,
                         "sessionKey": supplied.get("sessionKey", value["sessionKey"]),
                         **({"sessionId": supplied["sessionId"]} if "sessionId" in supplied else {}),
                         **({"id": supplied["id"]} if "id" in supplied else {})}
            require(original.get("input") == requested,
                    "A durable continuation read changed its literal current-key identity or reader scope.")
        require(len(observed.get("queries", [])) == len(phase.get("queries", [])),
                "Every durable recall query must retain its actual manager call.")
        for query, original, result in zip(phase.get("queries", []), observed["queries"], snapshot["queries"], strict=True):
            require(_same_json(original["input"], query)
                    and original["options"] == {"maxResults": query.get("maxResults", 200),
                                                "minScore": query.get("minScore", 0), "sources": ["sessions"]}
                    and _same_json(result, {"id": query["id"], "results": original["results"]}),
                    "A durable recall query changed its arguments or complete original result.")
        for original, append, result in zip(appends, phase.get("appendMessages", []), snapshot["appendResults"], strict=True):
            expected_options = {"eventId": append["eventId"], "message": append["message"],
                                "now": append.get("now", phase.get("nowMs", value["nowMs"])),
                                "cwd": append.get("cwd", str(Path(base) / "workspace")),
                                **({"parentId": append["parentId"]} if "parentId" in append else {}),
                                **({"appendIntent": append["appendIntent"]} if append.get("appendIntent") else {})}
            require(_same_json(original["options"], expected_options)
                    and original["target"]["sessionKey"] == append.get("sessionKey", value["sessionKey"])
                    and original["target"]["agentId"] == agent and original["target"]["storePath"] == catalog_path
                    and ("sessionId" not in append or original["target"]["sessionId"] == append["sessionId"])
                    and result["id"] == append["eventId"]
                    and _same_json({key: item for key, item in original.items() if key in {"result", "error"}},
                                   {key: item for key, item in result.items() if key != "id"}),
                    "A durable append result lost the exact real accessor arguments or complete anchor.")
        expected_snapshots.append(portable)
        store_paths.append(map_get_fixture_paths(database_path, base))
    expected = {"provider": "none", "phases": map_durable_session_identities(expected_snapshots, store_paths)}
    require(_same_json(row["result"], expected),
            "Durable public results differ from raw phase observations or opaque identity relationships.")
