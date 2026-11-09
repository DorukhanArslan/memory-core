"""Bounded execution evidence for the authenticated official release oracle.

Artifact archive verification remains the caller's responsibility before and
after the complete batch. This context owns process/thread tracing and retains
raw case diagnostics without presenting compiled files as TypeScript sources.
"""
from __future__ import annotations

from copy import deepcopy
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any

from equivalence.release_runtime import ReleaseRuntimeError, validate_release_sources
from equivalence.entry_provenance_profile import ENTRY_PROVENANCE_PROFILES, validate_entry_provenance_profile
from equivalence.atomic_publication_profile import ATOMIC_PUBLICATION_PROFILES, validate_atomic_publication_profile


ROOT = Path(__file__).resolve().parents[1]
MAX_TRACE_FILES = 512
MAX_TRACE_BYTES = 64 * 1024 * 1024
MAX_SINGLE_TRACE_BYTES = 8 * 1024 * 1024
MAX_DIAGNOSTIC_BYTES = 16 * 1024 * 1024
MAX_REJECTED_STREAM_BYTES = 4 * 1024 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TRACE = re.compile(r"([1-9][0-9]*)-([0-9]+)\.jsonl\Z")
_CONTEXT_ENV = "MEMORY_EQ_RELEASE_CONTEXT"
_FIXTURE_CAPTURE = re.compile(
    r"tmp/plugin-captures/[0-9a-f-]{36}/captures/openclaw-plugin-build-[A-Za-z0-9]{6}"
    r"/package-0/node_modules/equivalence/flush-execution\.mjs\Z"
)
_OPERATIONS = {
    "importance-project-runtime": (
        "importance-project-runtime.mjs", "dist/extensions/memory-core/manager-runtime.js", True,
    ),
    "exact-path-runtime": (
        "exact-path-runtime.mjs", "dist/extensions/memory-core/manager-runtime.js", False,
    ),
    "index-lifecycle-runtime": ("index-lifecycle.mjs", None, True),
    "flush-trigger-runtime": (
        "flush-runtime.mjs", "dist/agent-runner-memory-Cc4lCZcs.mjs", False,
    ),
    "flush-execution-runtime": (
        "flush-execution.mjs", "dist/agent-runner-memory-Cc4lCZcs.mjs", True,
    ),
    "search-contract-runtime": (
        "search-contract-runtime.mjs", "dist/tools-DotaQGXh.mjs", True,
    ),
    "search-contract-helper-runtime": (
        "search-contract-runtime.mjs", "dist/tools-DotaQGXh.mjs", False,
    ),
    "get-contract-runtime": (
        "get-contract-runtime.mjs", "dist/tools-DotaQGXh.mjs", False,
    ),
    "get-contract-helper-runtime": (
        "get-contract-runtime.mjs", "dist/tools-DotaQGXh.mjs", False,
    ),
    "deadline-partial-runtime": (
        "deadline-partial-runtime.mjs", "dist/tools-DotaQGXh.mjs", False,
    ),
    "deadline-partial-get-runtime": (
        "deadline-partial-runtime.mjs", "dist/tools-DotaQGXh.mjs", False,
    ),
    "session-contract-runtime": (
        "session-contract-runtime.mjs", "dist/extensions/memory-core/manager-runtime.js", True,
    ),
    "session-contract-helper-runtime": (
        "session-contract-runtime.mjs", "dist/session-ingestion-Dy5uAq-_.mjs", False,
    ),
    "transcript-boundary-runtime": (
        "transcript-boundary-runtime.mjs", "dist/session-files-DVVT4Ngb.mjs", False,
    ),
    "durable-session-runtime": (
        "durable-session-runtime.mjs", "dist/extensions/memory-core/manager-runtime.js", True,
    ),
    "turn-trust-runtime": (
        "turn-trust-runtime.mjs", "dist/agent-tools-HIqp3eTk.mjs", False,
    ),
    "workspace-isolation-runtime": (
        "workspace-isolation-runtime.mjs", "dist/extensions/memory-core/manager-runtime.js", True,
    ),
    "model-session-runtime": (
        "model-session-runtime.mjs", "dist/session-manager-a8MFS1Kk.mjs", False,
    ),
    "model-tool-result-runtime": (
        "model-tool-result-runtime.mjs", "dist/embedded-agent-tool-results-Bhhd5B_V.mjs", False,
    ),
    "trust-worker-runtime": (
        "trust-worker-profile-runtime.mjs", "dist/session-files-DVVT4Ngb.mjs", False,
    ),
    "model-tool-error-runtime": (
        "model-tool-error-runtime.mjs", "dist/tools-DotaQGXh.mjs", False,
    ),
    "entry-memory-publication-runtime": (
        "entry-provenance-runtime.mjs", "dist/extensions/memory-core/manager-runtime.js", True,
    ),
    "entry-session-publication-runtime": (
        "entry-provenance-runtime.mjs", "dist/extensions/memory-core/manager-runtime.js", True,
    ),
    "entry-provider-preparation-runtime": (
        "entry-provenance-runtime.mjs", "dist/manager-index-preparation-wXpJtJiU.mjs", False,
    ),
    "atomic-commit-runtime": (
        "atomic-publication-runtime.mjs", "dist/short-term-promotion-memory-write-DLJgScco.mjs", False,
    ),
    "atomic-append-runtime": (
        "atomic-publication-runtime.mjs", ("node_modules/@openclaw/fs-safe", "dist/root.js"), False,
    ),
    "atomic-bootstrap-runtime": (
        "atomic-publication-runtime.mjs", "dist/workspace-C0LMBmap.mjs", False,
    ),
}

MODEL_RUNTIME_OPERATIONS = frozenset({"model-session-runtime", "model-tool-result-runtime",
                                      "trust-worker-runtime", "model-tool-error-runtime"})


class RuntimeOracleError(ValueError):
    """The release process did not provide bounded authenticated execution evidence."""


def _validate_session_contract_raw(row: dict, case: dict, diagnostic: list,
                                   evidence_directory: Path | None = None) -> None:
    """Bind complete session results to actual accessors, SQL and tool envelopes."""
    from equivalence.get_contract import map_get_fixture_paths
    from equivalence.search_contract import _same_json, decode_search_tool_envelope

    if not row["ok"]:
        return
    if len(diagnostic) != 1 or not isinstance(diagnostic[0], dict):
        raise RuntimeOracleError("Session evidence requires one complete owned raw observation.")
    raw, arguments, public = diagnostic[0], case["input"], row["result"]
    if case["operation"] == "session-contract-helper-runtime":
        result = raw.get("result")
        if (set(raw) != {"result"} or not isinstance(result, dict)
                or not _same_json({"provider": "none", **result}, public)):
            raise RuntimeOracleError("Session helper results must retain their complete actual owner output.")
        if "configs" in arguments and (set(result) != {"policies"}
                or not isinstance(result["policies"], list)
                or len(result["policies"]) != len(arguments["configs"])):
            raise RuntimeOracleError("Every requested admission policy must execute its genuine helper.")
        return
    base = raw.get("fixtureBase")
    if (not isinstance(base, str) or evidence_directory is None or not Path(base).is_absolute()
            or Path(base).parent != evidence_directory
            or not re.fullmatch(r"native-session-fixture-[A-Za-z0-9_-]+", Path(base).name)
            or raw.get("constructorSkipped") is not False or raw.get("managerFixture") is not False):
        raise RuntimeOracleError("Session flows need owned fixtures and genuine manager construction.")
    if raw.get("clock") != {"owner": "node:test", "apis": ["Date"], "nowMs": arguments["nowMs"],
                            "dateConstructorReplaced": True, "setTimeoutUnchanged": True}:
        raise RuntimeOracleError("Session clocks require only the genuine Node Date fixture control.")
    selected = arguments.get("config", {})
    agent_id = arguments.get("agentId", "main")
    agent_ids = selected.get("agentIds", [agent_id])
    store_mode = selected.get("sessionStore")
    store_path = (str(Path(base) / "state/shared/sessions.json") if store_mode == "shared" else
                  str(Path(base) / "state/custom/{agentId}/sessions.json") if store_mode == "custom-template" else None)
    defaults = {"workspace": str(Path(base) / "workspace")}
    if "sandboxVisibility" in selected:
        defaults["sandbox"] = {"sessionToolsVisibility": selected["sandboxVisibility"]}
    expected_config = {
        "agents": {"defaults": defaults, "list": [{"id": item, **({"default": True} if item == agent_id else {})}
                                                   for item in agent_ids]},
        "logging": {"level": "silent", "consoleLevel": "silent", "file": str(Path(base) / "native.log")},
        "session": {**({"store": store_path} if store_path is not None else {}),
                    "maintenance": {"mode": "warn"}, **selected.get("session", {})},
        "tools": {"sessions": {"visibility": selected.get("visibility", "agent")}, **selected.get("tools", {})},
        "memory": {"search": {
            "enabled": True, "provider": "none", "fallback": "none", "sources": selected.get("sources", ["memory", "sessions"]),
            "rememberAcrossConversations": selected.get("rememberAcrossConversations", True),
            "experimental": {"sessionMemory": selected.get("configuredSessionMemory", True)},
            "store": {"vector": {"enabled": False}}, "sync": {"onSessionStart": False, "onSearch": False, "watch": False},
            "query": {"minScore": 0, "maxResults": 200, "hybrid": {"temporalDecay": {"enabled": False}}},
            **({"chunking": selected["chunking"]} if "chunking" in selected else {}),
        }},
    }
    if not _same_json(raw.get("config"), expected_config):
        raise RuntimeOracleError("Session fixture configuration differs from the complete selected host policy facts.")
    required_raw = {"fixtureBase", "constructorSkipped", "managerFixture", "sessionWrites", "gatewayRequests", "snapshots",
                    "lifecycle", "archiveWrites", "reads", "clock", "nativeEnvelopes", "queryErrors", "catalogRequests",
                    "managerAcquisitions", "queryRequests", "readRequests", "mutations", "config"}
    if set(raw) != required_raw:
        raise RuntimeOracleError("Session raw evidence lost an actual configuration, mutation or execution observation.")
    if set(public) != {"provider", "steps"} or public.get("provider") != "none":
        raise RuntimeOracleError("Session flow results require their complete provider-none step list.")
    steps = arguments.get("steps", [{"label": "initial"}])
    observations, snapshots = public.get("steps"), raw.get("snapshots")
    if (not isinstance(steps, list) or not isinstance(observations, list) or not isinstance(snapshots, list)
            or len(steps) != len(observations) or len(steps) != len(snapshots)
            or any(not isinstance(item, dict) for item in steps + observations + snapshots)):
        raise RuntimeOracleError("Every driven session step requires one full raw and public snapshot.")
    labels = [step.get("label") for step in steps]
    if any(not isinstance(label, str) for label in labels) or len(set(labels)) != len(labels):
        raise RuntimeOracleError("Session step labels must retain unique driven identities.")
    if (not isinstance(raw.get("managerAcquisitions"), list) or not raw["managerAcquisitions"]
            or raw["managerAcquisitions"][0].get("agentId") != arguments.get("agentId", "main")
            or not all(isinstance(item.get("status"), dict) for item in raw["managerAcquisitions"])):
        raise RuntimeOracleError("A session flow has no actual manager acquisition/status observation.")
    expected_catalog_requests = [{"agentId": arguments.get("agentId", "main"),
                                  "includeContentRevision": False,
                                  "includeRetainedSqlite": arguments.get("includeRetainedSqlite") is True}
                                 for _step in steps]
    if not _same_json(raw.get("catalogRequests"), expected_catalog_requests):
        raise RuntimeOracleError("Session discovery must execute the exact selected public corpus options.")
    actual_envelopes, actual_errors = raw.get("nativeEnvelopes"), raw.get("queryErrors")
    requests = raw.get("queryRequests")
    if not all(isinstance(items, list) for items in (actual_envelopes, actual_errors, requests, raw.get("reads"), raw.get("readRequests"))):
        raise RuntimeOracleError("Session queries and reads require complete original execution observations.")
    by_envelope, by_error = {}, {}
    for items, target in ((actual_envelopes, by_envelope), (actual_errors, by_error)):
        for item in items:
            if not isinstance(item, dict) or (item.get("step"), item.get("queryId")) in target:
                raise RuntimeOracleError("A session tool reply has a missing or duplicate operation identity.")
            target[(item.get("step"), item.get("queryId"))] = item
    if by_envelope.keys() & by_error.keys():
        raise RuntimeOracleError("A session query cannot claim both a success and a failure.")
    requested_queries, observed_reads = [], []
    expected_public_keys = {"label", "catalog", "admitted", "sourceEntries", "published", "indexSources",
                            "queries", "reads", "ingestionDecisions", "participantRecords"}
    for step, observed, snapshot in zip(steps, observations, snapshots, strict=True):
        if (set(observed) != expected_public_keys or snapshot.get("label") != step["label"]
                or observed.get("label") != step["label"]
                or set(snapshot) != expected_public_keys | {"fullSql", "sessionSql"}
                or not _same_json(map_get_fixture_paths({key: snapshot[key] for key in expected_public_keys}, base), observed)):
            raise RuntimeOracleError("A session result differs from its complete original persisted step snapshot.")
        sql = snapshot["fullSql"]
        if (not isinstance(sql, dict) or set(sql) != {"chunks", "sources", "provenance", "recall", "fts"}
                or any(not isinstance(value, list) for value in sql.values())
                or not isinstance(snapshot["sessionSql"], dict)):
            raise RuntimeOracleError("Session publication requires complete underlying index and catalog SQL.")
        fts_fields = ("id", "path", "source", "start_line", "end_line", "model", "text")
        if (any(not isinstance(item, dict) or not set(fts_fields) <= item.keys()
                for item in sql["fts"] + sql["chunks"])
                or not _same_json([{key: item[key] for key in fts_fields} for item in sql["fts"]],
                          [{key: item[key] for key in fts_fields} for item in sql["chunks"]])):
            raise RuntimeOracleError("The full persisted session FTS rows differ from their actual chunk identities and text.")
        catalog_tables = snapshot["sessionSql"]
        if (not {"session_nodes", "session_windows", "transcript_events", "session_participants",
                 "session_transcript_archives", "memory_session_tombstones"} <= catalog_tables.keys()
                or any(not isinstance(table, dict) or set(table) != {"columns", "rows"}
                       or not isinstance(table["columns"], list) or not table["columns"]
                       or not isinstance(table["rows"], list)
                       or any(set(record) != {column["name"] for column in table["columns"]}
                              for record in table["rows"])
                       for table in catalog_tables.values())):
            raise RuntimeOracleError("Session catalog SQL must retain real table columns and complete source rows.")
        provenance = {item["chunk_id"]: item for item in sql["provenance"]}
        recall = {item["chunk_id"]: item for item in sql["recall"]}
        published = []
        for chunk in sql["chunks"]:
            if not isinstance(chunk, dict) or chunk.get("embeddingHex") != "":
                raise RuntimeOracleError("The actual provider-none publication must retain its empty vectors.")
            p, r = provenance.get(chunk["id"], {}), recall.get(chunk["id"], {})
            published.append({"path": chunk["path"], "source": chunk["source"],
                              "startLine": chunk["start_line"], "endLine": chunk["end_line"], "text": chunk["text"],
                              "importance": r.get("importance"), "triggers": r.get("triggers"),
                              "projectKey": r.get("project_key"), "provenance": {
                                  "originClass": p.get("origin_class"), "sessionKind": p.get("session_kind"),
                                  "observedAt": p.get("observed_at"), "supersedesKey": p.get("supersedes_key")}})
        if (not _same_json(published, snapshot["published"])
                or not _same_json([{"path": item["path"], "source": item["source"]} for item in sql["sources"]], snapshot["indexSources"])):
            raise RuntimeOracleError("The complete logical session publication differs from actual persisted SQL rows.")
        if (not isinstance(snapshot["admitted"], list) or not isinstance(snapshot["sourceEntries"], list)
                or not _same_json([item.get("source") for item in snapshot["sourceEntries"]], snapshot["admitted"])):
            raise RuntimeOracleError("Every actual admitted source needs its full source projection and reset metadata.")
        queries = step.get("queries", [])
        if (not isinstance(snapshot["queries"], list) or len(snapshot["queries"]) != len(queries)
                or not isinstance(snapshot["reads"], list) or len(snapshot["reads"]) != len(step.get("reads", []))):
            raise RuntimeOracleError("Session step query/read counts differ from their driven operations.")
        for query, reply in zip(queries, snapshot["queries"], strict=True):
            identity = (step["label"], query["id"])
            requested_queries.append(identity)
            if (not isinstance(reply, dict) or reply.get("id") != query["id"]
                    or set(reply) not in ({"id", "candidates", "result"}, {"id", "candidates", "error"})):
                raise RuntimeOracleError("Session tool results lost their complete query identity or candidates.")
            if "result" in reply:
                original = by_envelope.get(identity)
                if (original is None or not _same_json(decode_search_tool_envelope(original.get("nativeEnvelope")), reply["result"])):
                    raise RuntimeOracleError("Session tool results differ from their complete original JSON envelopes.")
            elif identity not in by_error or not _same_json(by_error[identity].get("error"), reply["error"]):
                raise RuntimeOracleError("Session query errors lost their complete original native metadata.")
        for request, result in zip(step.get("reads", []), snapshot["reads"], strict=True):
            if not isinstance(result, dict) or result.get("id") != request["id"]:
                raise RuntimeOracleError("Current-key source read evidence lost a requested operation.")
            observed_reads.append({"step": step["label"], **result})
    if (len(requested_queries) != len(set(requested_queries)) or len(requests) != len(requested_queries)
            or set(requested_queries) != by_envelope.keys() | by_error.keys()
            or not _same_json(observed_reads, raw["reads"])):
        raise RuntimeOracleError("Session calls/reads were duplicated, dropped or detached from actual execution.")
    flat_queries = [(step["label"], query) for step in steps for query in step.get("queries", [])]
    for (label, query), request in zip(flat_queries, requests, strict=True):
        parameters = {"query": query["query"], "maxResults": query.get("maxResults", 200),
                      "minScore": query.get("minScore", 0), "corpus": query.get("corpus", "sessions")}
        options = request.get("toolOptions", {})
        if (request.get("step") != label or request.get("queryId") != query["id"]
                or not _same_json(request.get("parameters"), parameters)
                or options.get("agentId") != query.get("agentId", arguments.get("agentId", "main"))
                or any(not _same_json(options.get(native), query.get(native))
                       for native in ("conversationRecall", "sandboxed"))
                or not _same_json(options.get("agentSessionKey"), query.get("requesterSessionKey"))
                or not _same_json(options.get("config"), expected_config)):
            raise RuntimeOracleError("Session tools were not called with their complete genuine requester and query arguments.")
    requested_reads = [(step["label"], read) for step in steps for read in step.get("reads", [])]
    if len(raw["readRequests"]) != len(requested_reads):
        raise RuntimeOracleError("Current-session history requests were dropped from raw source access evidence.")
    for (label, request), actual, result in zip(requested_reads, raw["readRequests"], raw["reads"], strict=True):
        if (actual.get("step") != label or actual.get("readId") != request["id"]
                or not _same_json(actual.get("input"), request)):
            raise RuntimeOracleError("Source history access did not receive the complete requested host arguments.")
        guard, reader = actual.get("guard"), actual.get("reader")
        if guard is not None:
            sandbox_visibility = defaults.get("sandbox", {}).get("sessionToolsVisibility", "spawned")
            configured_visibility = expected_config["tools"].get("sessions", {}).get("visibility", "all")
            effective_visibility = ("tree" if request.get("sandboxed") is True and sandbox_visibility != "all"
                                    else configured_visibility)
            a2a = expected_config["tools"].get("agentToAgent", {})
            if (not isinstance(guard, dict) or guard.get("action") != "history"
                    or guard.get("requesterSessionKey") != request["requesterSessionKey"]
                    or guard.get("targetSessionKey") != request["targetSessionKey"]
                    or guard.get("requesterOwned") is not False
                    or guard.get("visibility") != effective_visibility
                    or not _same_json(guard.get("a2aPolicy"), {"enabled": a2a.get("enabled") is not False})
                    or not _same_json(guard.get("sessionReadScopeKey"), request.get("sessionReadScopeKey"))
                    or ("requesterAgentId" in request and guard.get("requesterAgentId") != request["requesterAgentId"])
                    or ("targetAgentId" in request and guard.get("targetAgentId") != request["targetAgentId"])):
                raise RuntimeOracleError("Source history guard arguments differ from their actual requester and target.")
        elif "error" not in result:
            raise RuntimeOracleError("A source history result bypassed its real authorization owner.")
        if reader is not None and (not isinstance(reader, dict) or guard is None
                or reader.get("agentId") != guard.get("targetAgentId")
                or reader.get("sessionKey") != request["targetSessionKey"]
                or reader.get("sessionId") != result.get("sessionId")):
            raise RuntimeOracleError("The source reader did not use the actual authorized current transcript identity.")
        if guard is not None:
            main_key = expected_config["session"].get("mainKey", "main")
            expected_main = ("global" if expected_config["session"].get("scope") == "global" else
                             f"agent:{guard['requesterAgentId']}:{main_key.strip().lower() or 'main'}")
            if request.get("sandboxed") is True and sandbox_visibility != "all":
                expected_main = None
            if not _same_json(guard.get("mainSessionKey"), expected_main):
                raise RuntimeOracleError("Current-session history read scope differs from its real selected main/sandbox context.")
        if "sessionId" in result and reader is None:
            raise RuntimeOracleError("A current transcript result has no actual native source-reader call.")
    writes = [*arguments.get("sessions", []), *(entry for step in steps for entry in step.get("sessions", []))]
    actual_writes = raw.get("sessionWrites")
    archives = [*arguments.get("archives", []), *(entry for step in steps for entry in step.get("archives", []))]
    if (not isinstance(actual_writes, list) or len(actual_writes) != len(writes)
            or not isinstance(raw.get("archiveWrites"), list) or len(raw["archiveWrites"]) != len(archives)):
        raise RuntimeOracleError("Session fixture writes and archive registry mutations were dropped from raw evidence.")

    def scope(entry: dict) -> dict:
        owner = entry.get("agentId", agent_id)
        store = (str(Path(base) / "state/shared/sessions.json") if store_mode == "shared" else
                 str(Path(base) / "state/custom" / owner / "sessions.json") if store_mode == "custom-template" else
                 str(Path(base) / "state/agents" / owner / "sessions/sessions.json"))
        identity = entry.get("sessionId", entry.get("entry", {}).get("sessionId"))
        return {"agentId": owner, "sessionKey": entry["sessionKey"], "storePath": store,
                **({"sessionId": identity} if identity is not None else {})}

    for requested, actual in zip(writes, actual_writes, strict=True):
        storage = actual.get("storage") if isinstance(actual, dict) else None
        if (not isinstance(actual, dict) or not _same_json(actual.get("target"), scope(requested))
                or not _same_json(actual.get("events"), requested.get("events"))
                or not isinstance(actual.get("transcript"), list)
                or "readBack" not in actual or not isinstance(actual.get("participantRecords"), dict)
                or not isinstance(actual.get("participants"), list)
                or len(actual["participants"]) != len(requested.get("participants", []))
                or not isinstance(storage, dict) or set(storage) != {"incognito", "databasePath", "pathExists"}
                or type(storage["incognito"]) is not bool or type(storage["pathExists"]) is not bool
                or not isinstance(storage["databasePath"], str)
                or not Path(storage["databasePath"]).is_relative_to(base)):
            raise RuntimeOracleError("Session metadata/events/participant writes lack their exact actual accessor arguments and readback.")
        if storage["databasePath"].endswith("/incognito-openclaw-agent.sqlite") and not storage["incognito"]:
            raise RuntimeOracleError("The actual private database route was detached from its genuine session-key classification.")
        if storage["incognito"]:
            if storage["pathExists"] or not storage["databasePath"].endswith("/incognito-openclaw-agent.sqlite"):
                raise RuntimeOracleError("Incognito source facts must use the actual process-held database sentinel without a disk file.")
            if "events" in requested and not _same_json(actual["transcript"], requested["events"]):
                raise RuntimeOracleError("The genuine volatile session accessor lost its actual private transcript records.")
            for snapshot in snapshots:
                if (any(entry.get("sessionKey") == requested["sessionKey"] for entry in snapshot["catalog"])
                        or any(entry.get("sessionKey") == requested["sessionKey"] for entry in snapshot["admitted"])
                        or any(row.get("session_key") == requested["sessionKey"]
                               for table in snapshot["sessionSql"].values() for row in table["rows"])):
                    raise RuntimeOracleError("Process-only session identity leaked into the ordinary persisted corpus or database.")
    expected_mutations = []
    for step in steps:
        for entry in step.get("replaceEvents", []):
            expected_mutations.append({"step": step["label"], "operation": "replaceEvents",
                                       "target": scope(entry), "events": entry["events"]})
        for entry in step.get("deleteSessions", []):
            expected_mutations.append({"step": step["label"], "operation": "deleteSession",
                                       "target": {**scope(entry), "archiveTranscript": False}})
        if step.get("forgetSessions"):
            expected_mutations.append({"step": step["label"], "operation": "tombstones",
                                       "ids": [entry if isinstance(entry, str) else entry["sessionId"]
                                               for entry in step["forgetSessions"]]})
    mutations = raw.get("mutations")
    if not isinstance(mutations, list) or len(mutations) != len(expected_mutations):
        raise RuntimeOracleError("A persisted session rewrite, deletion or tombstone mutation was omitted.")
    for expected, actual in zip(expected_mutations, mutations, strict=True):
        if (not isinstance(actual, dict) or any(not _same_json(actual.get(key), value) for key, value in expected.items())
                or not expected.keys() <= actual.keys() or actual.keys() - expected.keys() - {"result", "recorded"}):
            raise RuntimeOracleError("Session mutation evidence does not retain the original driven operation and arguments.")
    tombstones = [{key: value for key, value in mutation.items() if key != "step"}
                  for mutation in mutations if mutation["operation"] == "tombstones"]
    if not _same_json(raw.get("lifecycle"), tombstones):
        raise RuntimeOracleError("Session lifecycle observations were detached from actual persisted tombstones.")
    for requested, actual in zip(archives, raw["archiveWrites"], strict=True):
        owner = requested.get("agentId", agent_id)
        store = scope({"agentId": owner, "sessionKey": "archive-owner"})["storePath"]
        filename = str(Path(store).parent / requested["name"])
        if not isinstance(actual, dict) or actual.get("filename") != filename:
            raise RuntimeOracleError("An archive fixture escaped its actual selected owner path.")
        encoded = actual.get("descriptor", {}).get("bytes") if "identity" in requested else actual.get("bytes")
        if (not isinstance(encoded, dict) or set(encoded) != {"type", "data"} or encoded["type"] != "Buffer"
                or not isinstance(encoded["data"], list)
                or any(type(value) is not int or not 0 <= value <= 255 for value in encoded["data"])):
            raise RuntimeOracleError("An actual archive write has no complete original byte buffer.")
        data = bytes(encoded["data"])
        if "compressedBytes" in requested:
            if data != bytes(requested["compressedBytes"]):
                raise RuntimeOracleError("Actual compressed archive bytes differ from their shared literal fixture.")
        elif (not data.endswith(b"\n") or not _same_json(
                [json.loads(line) for line in data.decode("utf-8").splitlines()], requested["events"])):
            raise RuntimeOracleError("Actual JSONL archive bytes lost or changed an original literal event.")
        if "identity" in requested:
            descriptor = {"archiveName": requested["name"], "bytes": encoded,
                          "createdAt": requested["identity"].get("createdAt", arguments["nowMs"]),
                          "encoding": "zstd" if "compressedBytes" in requested else "identity", "sha256": _digest(data)}
            if not _same_json(actual.get("descriptor"), descriptor) or not isinstance(actual.get("rows"), list):
                raise RuntimeOracleError("Archive registry writes differ from the actual source bytes, encoding or identity facts.")
            identity = requested["identity"]
            plan = {"agentId": owner, "sessionId": identity["sessionId"], "reason": identity["reason"],
                    "archive": descriptor, "snapshot": {"sessionKey": identity["sessionKey"], "generation": identity["generation"]}}
            if not _same_json(actual.get("plan"), plan):
                raise RuntimeOracleError("Archive registry persistence did not receive the complete original owner/generation plan.")
        elif not _same_json(actual.get("bytes"), encoded):
            raise RuntimeOracleError("Unregistered archive bytes were replaced or omitted from actual source evidence.")


def _validate_deadline_partial_raw(row: dict, case: dict, diagnostic: list,
                                 evidence_directory: Path | None = None) -> None:
    """Bind every compared effect to complete original provider/tool observations."""
    from equivalence.search_contract import _same_json, decode_search_tool_envelope

    if not row["ok"]:
        return
    public = row["result"]
    if (set(public) != {"provider", "calls", "memoryDispatches", "wikiDispatches", "lanes", "clockSteps"}
            or len(diagnostic) != 1 or not isinstance(diagnostic[0], dict)):
        raise RuntimeOracleError("Controlled deadline results require complete raw effects and call envelopes.")
    raw, arguments = diagnostic[0], case["input"]
    real_get = case.get("operation") == "deadline-partial-get-runtime"
    if real_get:
        fixture_base = raw.get("fixtureBase")
        if (raw.get("toolName") != "memory_get" or raw.get("managerFixture") is not False
                or raw.get("constructorSkipped") is not False
                or raw.get("managerAcquisition") != "not-required" or raw.get("indexManagerConstructed") is not False
                or any(raw.get(name) != [] for name in ("managerGets", "statusReads", "closes"))
                or not isinstance(fixture_base, str) or evidence_directory is None
                or Path(fixture_base).parent != evidence_directory
                or not re.fullmatch(r"deadline-get-fixture-[A-Za-z0-9_-]+", Path(fixture_base).name)):
            raise RuntimeOracleError("Real get deadline fixtures require their owned files and no manager override.")
    elif (raw.get("managerFixture") is not True or raw.get("constructorSkipped") is not True
          or raw.get("managerGetRestoredBeforeExit") is not True):
        raise RuntimeOracleError("Controlled manager acquisition must be explicit and restore its actual owner.")
    expected_driver = {"kind": "node-test-mock-timers", "apis": ["Date", "setTimeout"],
                       "dateReplaced": True, "setTimeoutReplaced": True, "clearTimeoutReplaced": True,
                       "initialDateNow": arguments.get("startMs"),
                       "initialPerformanceNow": arguments.get("startMs"), "performanceNowMatchesDateNow": True}
    if not _same_json(raw.get("timerDriver"), expected_driver):
        raise RuntimeOracleError("The real Node timer APIs and performance clock were not observed under control.")
    commands = arguments.get("commands")
    if not isinstance(commands, list) or not all(isinstance(value, dict) for value in commands):
        raise RuntimeOracleError("Controlled deadline fixtures require ordered explicit commands.")
    call_ids = [command.get("id") for command in commands if command.get("op") == "call"]
    originals, replies = raw.get("nativeEnvelopes"), public.get("calls")
    if (not all(isinstance(value, str) for value in call_ids) or len(set(call_ids)) != len(call_ids)
            or not isinstance(originals, list) or not isinstance(replies, list)
            or len(originals) != len(call_ids) or len(replies) != len(call_ids)
            or any(not isinstance(value, dict) for value in originals + replies)
            or [value.get("id") for value in replies] != call_ids
            or {value.get("id") for value in originals} != set(call_ids)):
        raise RuntimeOracleError("Every requested controlled tool call needs its original raw reply.")
    original_by_id = {value["id"]: value for value in originals}
    for reply in replies:
        original = original_by_id[reply["id"]]
        if (set(reply) not in ({"id", "result"}, {"id", "error"})
                or set(original) != {*reply, "time"}):
            raise RuntimeOracleError("Controlled tool replies changed their original payload/error identity.")
        observed = {"id": original["id"], **(
            {"result": decode_search_tool_envelope(original["result"])} if "result" in reply
            else {"error": original["error"]})}
        if not _same_json(observed, reply):
            raise RuntimeOracleError("Controlled tool replies differ from their complete raw envelopes.")
    plugin_ids = [value["pluginId"] for value in arguments.get("supplements", [])]
    if len(set(plugin_ids)) != len(plugin_ids):
        raise RuntimeOracleError("Controlled supplement fixtures require unique plugin identities.")
    lanes = {name: [] for name in ["memory", *("wiki:" + value for value in plugin_ids)]}
    events = raw.get("globalEvents")
    if not isinstance(events, list):
        raise RuntimeOracleError("Controlled provider effects require their untouched global observations.")
    for event in events:
        if not isinstance(event, dict) or event.get("lane") not in lanes:
            raise RuntimeOracleError("A controlled provider event lost its declared backend identity.")
        lanes[event["lane"]].append({key: value for key, value in event.items() if key != "lane"})
    if real_get and (lanes["memory"] or public["memoryDispatches"] != []):
        raise RuntimeOracleError("Real get reads cannot substitute controlled memory-manager provider callbacks.")
    memory = [event["args"] for event in lanes["memory"] if event.get("event") == "start"]
    wiki = {plugin: [event["args"] for event in lanes["wiki:" + plugin] if event.get("event") == "start"]
            for plugin in plugin_ids}
    if (not _same_json(lanes, public["lanes"]) or not _same_json(memory, public["memoryDispatches"])
            or not _same_json(wiki, public["wikiDispatches"])):
        raise RuntimeOracleError("Compared provider lanes must retain every original argument, event and time.")
    steps, cuts, outcome_cuts = raw.get("clockSteps"), raw.get("clockObservationCuts"), raw.get("clockOutcomeCuts")
    clear_events, clear_cuts = raw.get("timerClears"), raw.get("clockClearCuts")
    if (not isinstance(steps, list) or not isinstance(cuts, list) or not isinstance(outcome_cuts, list)
            or len(steps) != len(commands) or len(cuts) != len(commands) or len(outcome_cuts) != len(commands)
            or not _same_json(steps, public["clockSteps"])):
        raise RuntimeOracleError("Every controlled clock action and barrier needs its full original observation.")
    if (not isinstance(clear_events, list) or not isinstance(clear_cuts, list)
            or len(clear_cuts) != len(commands)):
        raise RuntimeOracleError("Actual timer cancellation observations must be retained for every command.")
    derived = {"time", "dispatchCounts", "activeCounts", "abortCounts", "settledCalls", "timerClearCount"}
    previous_cut = previous_outcome_cut = previous_clear_cut = 0
    for command, step, cut, outcome_cut, clear_cut in zip(commands, steps, cuts, outcome_cuts, clear_cuts, strict=True):
        if (not isinstance(step, dict) or any(key in command for key in derived)
                or not _same_json(command, {key: value for key, value in step.items() if key not in derived})
                or type(cut) is not int or not previous_cut <= cut <= len(events)
                or type(outcome_cut) is not int or not previous_outcome_cut <= outcome_cut <= len(originals)
                or type(clear_cut) is not int or not previous_clear_cut <= clear_cut <= len(clear_events)):
            raise RuntimeOracleError("Controlled action identities or observation boundaries changed.")
        previous_cut, previous_outcome_cut, previous_clear_cut = cut, outcome_cut, clear_cut
        if "timerClears" in command:
            if (step.get("timerClearCount") != clear_cut or clear_cut < command["timerClears"]):
                raise RuntimeOracleError("Timer cancellation barriers require actual owner cancellation calls.")
        elif "timerClearCount" in step:
            raise RuntimeOracleError("Private timer counts require an explicitly declared command observation.")
        if command.get("op") not in {"barrier", "tick", "set-time", "pause", "resume", "settle"}:
            continue
        prefix = events[:cut]
        dispatches, active, aborted = {}, {}, {}
        for name in lanes:
            lane_events = [event for event in prefix if event["lane"] == name]
            starts = [event for event in lane_events if event.get("event") == "start"]
            finishes = [event for event in lane_events if event.get("event") in {"fulfilled", "rejected"}]
            dispatches[name] = len(starts)
            active[name] = len(starts) - len(finishes)
            aborted[name] = len({event["invocation"] for event in lane_events if event.get("event") == "abort"})
        settled = {value["id"] for value in originals[:outcome_cut]}
        if (not _same_json(step.get("dispatchCounts"), dispatches) or not _same_json(step.get("activeCounts"), active)
                or not _same_json(step.get("abortCounts"), aborted)
                or step.get("settledCalls") != [value for value in call_ids if value in settled]):
            raise RuntimeOracleError("Provider admission, active work, aborts or settlements lost their causal observations.")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(raw: bytes | str):
    def invalid(_value):
        raise ValueError("non-finite JSON")
    return json.loads(raw, parse_constant=invalid)


def _regular(path: Path, limit: int) -> bytes:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit
            or path.is_symlink()):
        raise RuntimeOracleError("Runtime evidence is not an independent bounded regular file.")
    return path.read_bytes()


def _relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeOracleError("Runtime evidence has an invalid artifact path.")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise RuntimeOracleError("Runtime evidence has an invalid artifact path.")
    return value


def _owned_directory(root: Path, path: Path) -> int:
    relative = path.relative_to(root)
    if ".." in relative.parts or not all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY")):
        raise RuntimeOracleError("Rejected diagnostic capture has no safe owned path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root, flags)
    try:
        for part in relative.parts:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        return directory
    except BaseException:
        os.close(directory)
        raise


def _owned_regular(root: Path, path: Path, limit: int) -> bytes:
    """Read only a bounded ordinary file through an anchored owned directory.

    Rejected diagnostics have no authenticated provenance. Never follow their
    symlinks into ambient files, including when an intermediate directory is
    replaced between validation and capture.
    """
    relative = path.relative_to(root)
    if not relative.parts or ".." in relative.parts or not hasattr(os, "O_NOFOLLOW"):
        raise RuntimeOracleError("Rejected diagnostic capture has no safe owned path")
    directory = _owned_directory(root, path.parent)
    descriptor = None
    try:
        descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise RuntimeOracleError("Rejected diagnostics are not independent bounded regular files")
        chunks, remaining = [], limit + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > limit:
            raise RuntimeOracleError("Rejected diagnostics exceeded their capture bound")
        return raw
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


class ReleaseOracleExecution:
    """One fresh provider-none process with a trusted preload inherited by workers."""

    def __init__(self, config: dict, adapter_hashes: dict[str, str], *, fixture_captures: bool = False,
                 turn_taint_source: dict | None = None, model_node_runtime: dict | None = None,
                 entry_profile: dict | None = None, atomic_profile: dict | None = None):
        self.config = deepcopy(config)
        self.adapter_hashes = dict(adapter_hashes)
        self.fixture_captures = fixture_captures
        self.turn_taint_source = deepcopy(turn_taint_source)
        self.model_node_runtime = deepcopy(model_node_runtime)
        self.entry_profile = deepcopy(entry_profile)
        self.atomic_profile = deepcopy(atomic_profile)
        self.env: dict[str, str] = {}
        self._temporary = None
        self._entered = False

    def __enter__(self):
        try:
            if self.entry_profile is not None:
                self.entry_profile = validate_entry_provenance_profile(self.entry_profile)
                if self.model_node_runtime is not None or self.turn_taint_source is not None or self.fixture_captures or self.atomic_profile is not None:
                    raise RuntimeOracleError("Entry provenance cannot borrow model, source-owner or fixture-source capabilities.")
            if self.atomic_profile is not None:
                self.atomic_profile = validate_atomic_publication_profile(self.atomic_profile)
                if any((self.entry_profile is not None, self.model_node_runtime is not None,
                        self.turn_taint_source is not None, self.fixture_captures)):
                    raise RuntimeOracleError("Atomic publication cannot borrow model, entry, source or fixture capabilities.")
            if self.model_node_runtime is not None:
                from equivalence.model_runtime_authority import validate_model_node_authority

                self.model_node_runtime = validate_model_node_authority(self.model_node_runtime)
            if self.turn_taint_source is not None:
                from equivalence.turn_trust_source_authority import validate_turn_taint_source_authority

                self.turn_taint_source = validate_turn_taint_source_authority(self.turn_taint_source)
            runtime_root = Path(self.config["runtimeRoot"])
            if not runtime_root.is_absolute() or not runtime_root.is_dir():
                raise RuntimeOracleError("An authenticated absolute release runtime is required.")
            package_map = {}
            for package in self.config["packages"]:
                location = _relative(package["location"])
                directory = Path(package["directory"])
                if not directory.is_absolute() or not directory.is_dir() or directory.is_symlink():
                    raise RuntimeOracleError("A release package root is invalid.")
                for entry in package["files"]:
                    relative = _relative(entry["path"])
                    digest = entry["sha256"]
                    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
                        raise RuntimeOracleError("A release package digest is invalid.")
                    key = (location, relative)
                    if key in package_map:
                        raise RuntimeOracleError("Release package evidence must be unique.")
                    package_map[key] = digest
            self._packages = package_map
            self._locals = {}
            for name, digest in self.adapter_hashes.items():
                if Path(name).name != name:
                    raise RuntimeOracleError("Oracle adapter identities must use plain filenames.")
                if not name.endswith(".mjs"):
                    continue
                path = ROOT / "equivalence" / name
                if not isinstance(digest, str) or not _HASH.fullmatch(digest):
                    raise RuntimeOracleError("An oracle adapter digest is invalid.")
                if _digest(_regular(path, MAX_DIAGNOSTIC_BYTES)) != digest:
                    raise RuntimeOracleError("An oracle adapter changed before release execution.")
                self._locals[str(path.resolve())] = digest
            required = {"release-preload.mjs", "release-oracle.mjs", "index-lifecycle.mjs"}
            if not required <= {Path(path).name for path in self._locals}:
                raise RuntimeOracleError("Release execution requires all reviewed oracle adapters.")
            self._temporary = tempfile.TemporaryDirectory(prefix="memory-release-oracle-")
            self.root = Path(self._temporary.name)
            self.trace_directory = self.root / "traces"
            self.evidence_directory = self.root / "evidence"
            self.trace_directory.mkdir()
            self.evidence_directory.mkdir()
            self.context_path = self.root / "context.json"
            self.state_directory = self.root / "state"
            self.config_path = self.root / "openclaw.json"
            self.config_path.write_text(json.dumps({"session": {"maintenance": {"mode": "warn"}}, "logging": {
                "level": "silent", "consoleLevel": "silent", "file": str(self.root / "runtime.log"),
            }}), encoding="utf-8")
            self._context = {
                "schemaVersion": 1, "kind": "release-oracle-execution",
                "runtime": self.config,
                "allowedLocal": [{"path": path, "sha256": digest}
                                 for path, digest in sorted(self._locals.items())],
                "traceDirectory": str(self.trace_directory),
                "evidenceDirectory": str(self.evidence_directory),
                "stateDirectory": str(self.state_directory), "configPath": str(self.config_path),
                "providerMode": "none", "fetchPolicy": "deny",
                "fixtureSourceCaptures": [],
                "approvedReferenceSources": [self.turn_taint_source] if self.turn_taint_source else [],
            }
            if self.model_node_runtime is not None:
                self._context["approvedNodeRuntime"] = self.model_node_runtime
            if self.entry_profile is not None:
                self._context["approvedNodeRuntime"] = self.entry_profile["nodeRuntime"]
                self._context["entryProvenanceProfile"] = self.entry_profile
            if self.atomic_profile is not None:
                self._context["approvedNodeRuntime"] = self.atomic_profile["nodeRuntime"]
                self._context["atomicPublicationProfile"] = self.atomic_profile
            if self.fixture_captures:
                fixture = str((ROOT / "equivalence/flush-execution.mjs").resolve())
                if fixture not in self._locals:
                    raise RuntimeOracleError("Fixture captures require the reviewed flush execution adapter.")
                self._context["fixtureSourceCaptures"] = [{
                    "sourcePath": fixture, "sha256": self._locals[fixture],
                    "basename": "flush-execution.mjs",
                }]
            raw = (json.dumps(self._context, separators=(",", ":"), allow_nan=False) + "\n").encode()
            self.context_path.write_bytes(raw)
            self.context_path.chmod(0o600)
            self._context_digest = _digest(raw)
            preload = ROOT / "equivalence/release-preload.mjs"
            self._preload_digest = self._locals[str(preload.resolve())]
            self.env = {
                "NODE_OPTIONS": "--import=" + preload.as_uri(),
                _CONTEXT_ENV: str(self.context_path),
                "OPENCLAW_STATE_DIR": str(self.state_directory),
                "OPENCLAW_CONFIG_PATH": str(self.config_path),
            }
            self._entered = True
            return self
        except (OSError, KeyError, TypeError, ValueError) as error:
            if self._temporary is not None:
                self._temporary.cleanup()
            if isinstance(error, RuntimeOracleError):
                raise
            raise RuntimeOracleError("The release oracle execution context could not be prepared.") from None

    def __exit__(self, *_exception):
        self._entered = False
        if self._temporary is not None:
            self._temporary.cleanup()

    def collect(self, result: dict, cases: list[dict]) -> dict:
        """Validate all observed threads and retain case raw state in the report."""
        if not self._entered:
            raise RuntimeOracleError("Release execution evidence requires an active owned context.")
        try:
            return self._collect(result, cases)
        except (OSError, KeyError, TypeError, ValueError, ReleaseRuntimeError) as error:
            if isinstance(error, RuntimeOracleError):
                raise
            raise RuntimeOracleError("The release oracle returned invalid execution evidence.") from None

    def capture_rejected(
        self, result: object, cases: list[dict], *, stdout: str, stderr: str,
    ) -> dict:
        """Detach bounded original diagnostics before the temporary tree closes.

        Nothing returned here passed execution validation. This separate
        diagnostic object must never populate authenticated sources, successful
        runtime diagnostics or case coverage.
        """
        capture: dict[str, Any] = {"validationStatus": "rejected", "authenticationStatus": "unverified",
                   "kind": "rejected-release-runtime-diagnostics", "caseIds": [],
                   "oracleResult": None, "stdout": None, "stderr": None,
                   "caseDiagnostics": [], "processWorkerTraces": [], "omissions": []}

        def stream(text: str) -> dict:
            raw = text.encode("utf-8")
            # Keep an exact UTF-8 prefix, without inventing a replacement
            # character when the byte bound splits an original code point.
            captured = raw[:MAX_REJECTED_STREAM_BYTES].decode("utf-8", errors="ignore")
            prefix = captured.encode("utf-8")
            return {"bytes": len(raw), "sha256": _digest(raw), "capturedBytes": len(prefix),
                    "truncated": len(prefix) != len(raw), "text": captured}

        capture["stdout"], capture["stderr"] = stream(stdout), stream(stderr)

        def artifact(raw: bytes) -> dict:
            record = {"bytes": len(raw), "sha256": _digest(raw)}
            try:
                record["text"] = raw.decode("utf-8")
            except UnicodeError:
                record.update(encoding="base64", data=base64.b64encode(raw).decode("ascii"))
            return record
        try:
            serialized = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(serialized) > MAX_REJECTED_STREAM_BYTES:
                raise ValueError("result bound")
            capture["oracleResult"] = _json(serialized)
        except (TypeError, ValueError, UnicodeError):
            capture["omissions"].append({"kind": "oracleResult", "reason": "invalid-or-excessive"})
        if not self._entered:
            capture["omissions"].append({"kind": "ownedFiles", "reason": "context-inactive"})
            return capture
        remaining_diagnostics = MAX_DIAGNOSTIC_BYTES
        for case in cases[:MAX_TRACE_FILES]:
            identifier = case.get("id")
            if not isinstance(identifier, str):
                capture["omissions"].append({"kind": "case", "reason": "invalid-identity"})
                continue
            capture["caseIds"].append(identifier)
            name = _digest(identifier.encode("utf-8")) + "/native-raw.json"
            record = {"id": identifier, "operation": case.get("operation"), "path": name,
                      "validationStatus": "unverified"}
            try:
                request = json.dumps(case, ensure_ascii=False, allow_nan=False).encode("utf-8")
                if len(request) > MAX_REJECTED_STREAM_BYTES:
                    raise ValueError("case bound")
                record["case"] = _json(request)
                record["caseSha256"] = _digest(request)
            except (TypeError, ValueError, UnicodeError):
                record["caseCaptureStatus"] = "invalid-or-excessive"
            try:
                raw = _owned_regular(self.root, self.evidence_directory / name, remaining_diagnostics)
                remaining_diagnostics -= len(raw)
                record.update(artifact(raw))
                try:
                    record["rawSnapshots"] = _json(raw)
                except (ValueError, UnicodeError):
                    record["parseStatus"] = "invalid-json"
            except (OSError, ValueError, UnicodeError):
                record["captureStatus"] = "unavailable-or-unsafe"
            capture["caseDiagnostics"].append(record)
        if len(cases) > MAX_TRACE_FILES:
            capture["omissions"].append({"kind": "cases", "reason": "count-limit", "omitted": len(cases) - MAX_TRACE_FILES})
        try:
            directory = _owned_directory(self.root, self.trace_directory)
            try:
                with os.scandir(directory) as listing:
                    traces: list[str] = []
                    for entry in listing:
                        if len(traces) >= MAX_TRACE_FILES:
                            capture["omissions"].append({"kind": "traces", "reason": "count-limit"})
                            break
                        traces.append(entry.name)
            finally:
                os.close(directory)
            total = 0
            for name in sorted(traces):
                if not _TRACE.fullmatch(name):
                    capture["omissions"].append({"kind": "trace", "reason": "invalid-identity"})
                    continue
                record = {"name": name, "validationStatus": "unverified"}
                try:
                    raw = _owned_regular(self.root, self.trace_directory / name,
                                         min(MAX_SINGLE_TRACE_BYTES, MAX_TRACE_BYTES - total))
                    total += len(raw)
                    record.update(artifact(raw))
                except (OSError, ValueError, UnicodeError):
                    record["captureStatus"] = "unavailable-or-unsafe"
                capture["processWorkerTraces"].append(record)
        except (OSError, ValueError):
            capture["omissions"].append({"kind": "traces", "reason": "unavailable-or-unsafe"})
        return capture

    def _collect(self, result: dict, cases: list[dict]) -> dict:
        if (not isinstance(result, dict) or result.get("kind") != "official-release-runtime-comparison"
                or result.get("sources") != [] or len(cases) != 1
                or not isinstance(result.get("results"), list) or len(result["results"]) != 1):
            raise RuntimeOracleError("Release oracle comparisons require one fresh isolated case.")
        case = cases[0]
        row = result["results"][0]
        operation = case.get("operation")
        if (self.atomic_profile is not None) is not (operation in ATOMIC_PUBLICATION_PROFILES):
            raise RuntimeOracleError("The atomic capability is restricted to its three declared original owners.")
        if self.atomic_profile is not None:
            validate_atomic_publication_profile(self.atomic_profile)
            if self.atomic_profile["operation"] != operation or self.atomic_profile["inputKind"] != case.get("input", {}).get("kind"):
                raise RuntimeOracleError("Atomic commit, append and bootstrap profiles cannot impersonate one another.")
        if (self.entry_profile is not None) is not (operation in ENTRY_PROVENANCE_PROFILES):
            raise RuntimeOracleError("The entry capability is restricted to its three explicit compiled profiles.")
        if self.entry_profile is not None:
            validate_entry_provenance_profile(self.entry_profile)
            if self.entry_profile["operation"] != operation or self.entry_profile["inputKind"] != case.get("input", {}).get("kind"):
                raise RuntimeOracleError("Entry memory, session and provider-preparation profiles cannot impersonate one another.")
        if (self.model_node_runtime is not None) is not (operation in MODEL_RUNTIME_OPERATIONS):
            raise RuntimeOracleError("The approved model binary capability is restricted to its declared compiled boundary profiles.")
        if (self.turn_taint_source is not None) is not (operation == "turn-trust-runtime"):
            raise RuntimeOracleError("The single source-owner capability is restricted to the declared mixed turn-trust profile.")
        if self.turn_taint_source is not None:
            from equivalence.turn_trust_source_authority import validate_turn_taint_source_authority

            validate_turn_taint_source_authority(self.turn_taint_source)
        search_profile_kinds = {"search-contract-runtime": {"tool"},
                                "search-contract-helper-runtime": {"definition", "prepare-arguments"}}
        if (operation in search_profile_kinds
                and case.get("input", {}).get("kind") not in search_profile_kinds[operation]):
            raise RuntimeOracleError("Search fixtures must use their narrowly declared helper or whole-tool profile.")
        get_profile_kinds = {"get-contract-runtime": "tool", "get-contract-helper-runtime": "definition"}
        if operation in get_profile_kinds and case.get("input", {}).get("kind") != get_profile_kinds[operation]:
            raise RuntimeOracleError("Get fixtures must use their narrowly declared definition or whole-tool profile.")
        if operation in {"deadline-partial-runtime", "deadline-partial-get-runtime"} and case.get("input", {}).get("kind") != "tool":
            raise RuntimeOracleError("Controlled deadline fixtures must use the dedicated whole-tool profile.")
        if (operation == "deadline-partial-runtime" and case["input"].get("toolName") not in {None, "memory_search"}
                or operation == "deadline-partial-get-runtime" and case["input"].get("toolName") != "memory_get"):
            raise RuntimeOracleError("Deadline search and real-file get profiles cannot impersonate each other.")
        session_kinds = {"session-contract-runtime": "flow", "session-contract-helper-runtime": "admission-policy"}
        session_kinds.update({"transcript-boundary-runtime": "boundary", "durable-session-runtime": "durable",
                              "turn-trust-runtime": "turn-trust"})
        if operation in session_kinds and case.get("input", {}).get("kind") != session_kinds[operation]:
            raise RuntimeOracleError("Session admission helpers cannot impersonate genuine persisted session flows.")
        if operation == "workspace-isolation-runtime" and case.get("input", {}).get("kind") != "flow":
            raise RuntimeOracleError("Workspace isolation requires its actual multi-owner runtime profile.")
        if (not isinstance(row, dict) or operation not in _OPERATIONS
                or row.get("id") != case.get("id") or type(row.get("ok")) is not bool
                or set(row) != ({"id", "ok", "result"} if row["ok"] else {"id", "ok", "error"})):
            raise RuntimeOracleError("The release oracle returned an unexpected case identity.")
        if row["ok"] and (not isinstance(row["result"], dict) or row["result"].get("provider") != "none"):
            raise RuntimeOracleError("Release memory fixtures require provider none.")
        if operation == "turn-trust-runtime" and not row["ok"]:
            raise RuntimeOracleError("The real turn-trust caller did not complete its registered execution and persistence flow.")
        if operation in {*MODEL_RUNTIME_OPERATIONS, *ENTRY_PROVENANCE_PROFILES, *ATOMIC_PUBLICATION_PROFILES} and not row["ok"]:
            raise RuntimeOracleError("The real model boundary caller did not complete its declared original execution and output transport.")
        if _digest(_regular(self.context_path, MAX_TRACE_BYTES)) != self._context_digest:
            raise RuntimeOracleError("The owned release execution configuration changed.")
        for path, digest in self._locals.items():
            if _digest(_regular(Path(path), MAX_DIAGNOSTIC_BYTES)) != digest:
                raise RuntimeOracleError("An oracle adapter changed during release execution.")
        traces = sorted(self.trace_directory.iterdir())
        if not traces or len(traces) > MAX_TRACE_FILES:
            raise RuntimeOracleError("The release oracle returned missing or excessive thread traces.")
        total = 0
        loaded, bootstrap, worker_imports, local_imports, captures = {}, [], [], set(), {}
        release_by_pid, local_by_pid, process_parents = {}, {}, {}
        atomic_loaded_by_pid, atomic_native_by_pid = {}, {}
        reference_source_imports = []
        entry_trace_files = []
        for trace in traces:
            filename = _TRACE.fullmatch(trace.name)
            if filename is None:
                raise RuntimeOracleError("A release thread trace has an invalid identity.")
            raw = _regular(trace, MAX_SINGLE_TRACE_BYTES)
            if self.entry_profile is not None:
                entry_trace_files.append({"name": trace.name, "bytes": len(raw), "sha256": _digest(raw),
                                          "text": raw.decode("utf-8")})
            total += len(raw)
            if total > MAX_TRACE_BYTES or not raw.endswith(b"\n"):
                raise RuntimeOracleError("Release thread traces are excessive or incomplete.")
            events = [_json(line) for line in raw.splitlines()]
            if (not events or any(not isinstance(event, dict) for event in events)
                    or events[0].get("event") != "bootstrap"):
                raise RuntimeOracleError("A runtime thread bypassed its trusted preload.")
            pid, thread = int(filename[1]), int(filename[2])
            first = events[0]
            if (first.get("pid") != pid or first.get("threadId") != thread
                    or first.get("isMainThread") is not (thread == 0)
                    or first.get("contextSha256") != self._context_digest
                    or first.get("preloadSha256") != self._preload_digest
                    or first.get("fetchDenied") is not True or first.get("providerMode") != "none"):
                raise RuntimeOracleError("Runtime thread bootstrap protection was not attested.")
            node_authority = (self.model_node_runtime
                              or (self.entry_profile["nodeRuntime"] if self.entry_profile is not None else None)
                              or (self.atomic_profile["nodeRuntime"] if self.atomic_profile is not None else None))
            if node_authority is not None and first.get("runtime") != node_authority:
                raise RuntimeOracleError("The actual native process or worker omitted its approved model binary authority.")
            if self.entry_profile is not None and first.get("entryProfile") != self.entry_profile:
                raise RuntimeOracleError("The actual entry process or worker omitted its exact compiled profile authority.")
            if self.atomic_profile is not None and first.get("atomicProfile") != self.atomic_profile:
                raise RuntimeOracleError("The actual atomic process omitted its exact compiled profile authority.")
            bootstrap.append({"pid": pid, "threadId": thread, "isMainThread": thread == 0,
                              **({"runtime": first["runtime"]} if node_authority is not None else {}),
                              **({"entryProfile": first["entryProfile"]} if self.entry_profile is not None else {})})
            if self.atomic_profile is not None:
                bootstrap[-1]["atomicProfile"] = first["atomicProfile"]
            if thread == 0:
                process_parents[pid] = first.get("ppid")
            for event in events[1:]:
                if event.get("pid") != pid or event.get("threadId") != thread:
                    raise RuntimeOracleError("A runtime trace forged another thread identity.")
                if event.get("event") in {"rejected", "network-denied"}:
                    raise RuntimeOracleError("The runtime attempted an unverified import or network request.")
                if event.get("event") not in {"load", "resolve-native"}:
                    raise RuntimeOracleError("The runtime returned an unsupported trace event.")
                kind, path, digest = event.get("kind"), event.get("path"), event.get("sha256")
                if kind == "oracle":
                    if self._locals.get(path) != digest:
                        raise RuntimeOracleError("An oracle import did not match its reviewed adapter.")
                    if event["event"] == "load" and thread == 0:
                        local_imports.add(path)
                        local_by_pid.setdefault(pid, set()).add(path)
                elif kind == "reference-source":
                    approved = self.turn_taint_source
                    if (operation != "turn-trust-runtime" or approved is None or path != approved["path"]
                            or digest != approved["sha256"] or event.get("relativePath") != approved["relativePath"]
                            or event.get("referenceCommit") != approved["referenceCommit"] or thread != 0):
                        raise RuntimeOracleError("A reference source import escaped its exact mixed-profile authority.")
                    if event["event"] == "load":
                        reference_source_imports.append({"path": path, "relativePath": approved["relativePath"],
                            "sha256": digest, "referenceCommit": approved["referenceCommit"], "pid": pid, "threadId": thread})
                elif kind == "fixture-capture":
                    source = event.get("sourcePath")
                    capture = event.get("capturePath")
                    proof = event.get("proofPath")
                    if (not self.fixture_captures or case.get("operation") != "flush-execution-runtime"
                            or source != str((ROOT / "equivalence/flush-execution.mjs").resolve())
                            or path != source or self._locals.get(source) != digest
                            or not isinstance(capture, str) or not _FIXTURE_CAPTURE.fullmatch(capture)):
                        raise RuntimeOracleError("A fixture source capture has no reviewed owner.")
                    expected_proof = "fixture-source-captures/" + _digest(
                        (capture + "\0" + digest).encode()
                    ) + ".mjs"
                    if proof != expected_proof:
                        raise RuntimeOracleError("A fixture source capture has invalid retained proof.")
                    proof_directory = self.evidence_directory / "fixture-source-captures"
                    if (proof_directory.is_symlink() or not proof_directory.is_dir()
                            or proof_directory.resolve() != proof_directory):
                        raise RuntimeOracleError("A fixture source capture proof escaped its owned directory.")
                    proof_bytes = _regular(self.evidence_directory / proof, MAX_DIAGNOSTIC_BYTES)
                    if _digest(proof_bytes) != digest:
                        raise RuntimeOracleError("A retained fixture source capture changed its bytes.")
                    if event["event"] == "load":
                        captures[capture] = {
                            "sourcePath": source, "capturePath": capture, "sha256": digest,
                            "proofPath": proof, "proofSha256": _digest(proof_bytes),
                            "bytes": len(proof_bytes),
                        }
                elif kind == "release":
                    key = (event.get("package"), path)
                    if self._packages.get(key) != digest:
                        raise RuntimeOracleError("A runtime import is not an authenticated release file.")
                    if event["event"] == "load":
                        atomic_loaded_by_pid.setdefault((pid, thread), set()).add(key)
                        loaded[key] = {"package": key[0], "path": key[1], "sha256": digest}
                        if key[0] == "node_modules/openclaw":
                            release_by_pid.setdefault(pid, set()).add(key[1])
                        if thread > 0:
                            worker_imports.append({"package": key[0], "path": key[1],
                                                   "threadId": thread, "pid": pid})
                    elif event["event"] == "resolve-native":
                        atomic_native_by_pid.setdefault((pid, thread), set()).add(key)
                else:
                    raise RuntimeOracleError("A runtime import has an unknown authority.")
        if not any(item["isMainThread"] for item in bootstrap):
            raise RuntimeOracleError("The release main process did not execute its trusted preload.")
        adapter, required_owner, requires_worker = _OPERATIONS[operation]
        if not {str((ROOT / "equivalence" / name).resolve())
                for name in ("release-oracle.mjs", adapter)} <= local_imports:
            raise RuntimeOracleError("The reviewed release runner and case adapter did not execute.")
        if operation in {"deadline-partial-runtime", "deadline-partial-get-runtime"} and not {
            str((ROOT / "equivalence" / name).resolve())
            for name in ("deadline-partial.mjs", "search-contract-runtime.mjs")
        } <= local_imports:
            raise RuntimeOracleError("The actual controlled timer and complete envelope codec owners did not execute.")
        if operation in {"session-contract-runtime", "workspace-isolation-runtime"} and not {
            str((ROOT / "equivalence" / name).resolve())
            for name in ("search-contract-runtime.mjs", "get-contract-runtime.mjs")
        } <= local_imports:
            raise RuntimeOracleError("Session results require the original full-envelope and exact owned-root transport codecs.")
        if operation == "workspace-isolation-runtime":
            from equivalence.workspace_isolation_runtime_bindings import REQUIRED_LOADED_ARTIFACTS
            from equivalence.workspace_isolation_evidence import validate_workspace_isolation_workers

            if any(("node_modules/openclaw", owner) not in loaded for owner in REQUIRED_LOADED_ARTIFACTS):
                raise RuntimeOracleError("The actual declared workspace/file/index/recall/checkpoint owners did not execute.")
            validate_workspace_isolation_workers(worker_imports)
        required_key = required_owner if isinstance(required_owner, tuple) else ("node_modules/openclaw", required_owner)
        if required_owner is not None and required_key not in loaded:
            message = ("The actual native runtime owner did not execute."
                       if operation in {"exact-path-runtime", "importance-project-runtime"}
                       else "The actual native flush runtime owner did not execute.")
            raise RuntimeOracleError(message)
        if operation == "importance-project-runtime":
            from equivalence.importance_project_runtime_bindings import COMPILED_HASHES

            if any(("node_modules/openclaw", owner) not in loaded for owner in COMPILED_HASHES):
                raise RuntimeOracleError("The actual native preparation, metadata and ranking owners did not execute.")
        if operation in {"search-contract-runtime", "search-contract-helper-runtime"}:
            from equivalence.search_contract_runtime_bindings import REQUIRED_LOADED_ARTIFACTS_BY_PROFILE

            if any(("node_modules/openclaw", owner) not in loaded
                   for owner in REQUIRED_LOADED_ARTIFACTS_BY_PROFILE[operation]):
                raise RuntimeOracleError("The actual declared native search-tool owners did not execute.")
        if operation in {"get-contract-runtime", "get-contract-helper-runtime"}:
            from equivalence.get_contract_runtime_bindings import REQUIRED_LOADED_ARTIFACTS_BY_PROFILE

            if any(("node_modules/openclaw", owner) not in loaded
                   for owner in REQUIRED_LOADED_ARTIFACTS_BY_PROFILE[operation]):
                raise RuntimeOracleError("The actual declared native get-tool owners did not execute.")
        if operation in {"deadline-partial-runtime", "deadline-partial-get-runtime"}:
            from equivalence.deadline_partial_runtime_bindings import REQUIRED_LOADED_ARTIFACTS_BY_PROFILE

            if any(("node_modules/openclaw", owner) not in loaded
                   for owner in REQUIRED_LOADED_ARTIFACTS_BY_PROFILE[operation]):
                raise RuntimeOracleError("The actual native deadline/cooldown/corpus owners did not execute.")
        if operation in {"session-contract-runtime", "session-contract-helper-runtime"}:
            from equivalence.session_admission_runtime_bindings import (
                REQUIRED_LOADED_ARTIFACTS_BY_PROFILE, MEMORY_INDEX_WORKER_ARTIFACTS,
            )

            if any(("node_modules/openclaw", owner) not in loaded
                   for owner in REQUIRED_LOADED_ARTIFACTS_BY_PROFILE[operation]):
                raise RuntimeOracleError("The genuine declared native session flow/helper owners did not execute.")
            if operation == "session-contract-runtime":
                by_thread = {}
                for item in worker_imports:
                    by_thread.setdefault((item["pid"], item["threadId"]), set()).add(item["path"])
                if not any(set(MEMORY_INDEX_WORKER_ARTIFACTS) <= paths for paths in by_thread.values()):
                    raise RuntimeOracleError("Session publication requires its real memory-index wrapper and implementation in one protected worker.")
        if operation == "transcript-boundary-runtime":
            from equivalence.transcript_boundary_runtime_bindings import REQUIRED_BOUNDARY_ARTIFACTS

            if any(("node_modules/openclaw", owner) not in loaded for owner in REQUIRED_BOUNDARY_ARTIFACTS):
                raise RuntimeOracleError("The original transcript boundary reader and projection owners did not execute.")
        if case.get("operation") == "flush-execution-runtime" and not captures:
            raise RuntimeOracleError("The native provider loader did not execute a reviewed fixture source capture.")
        if operation == "flush-execution-runtime" and (
            "node_modules/openclaw", "dist/extensions/memory-core/manager-runtime.js"
        ) not in loaded:
            raise RuntimeOracleError("The actual native memory manager did not execute during flush comparison.")
        if requires_worker and not any(
            item["path"].endswith("/memory-index.worker.js") for item in worker_imports
        ):
            raise RuntimeOracleError("The actual native memory worker did not inherit runtime protection.")
        release_sources = [loaded[key] for key in sorted(loaded)]
        if required_owner is None:
            validate_release_sources(self.config, release_sources)
        else:
            validate_release_sources(self.config, release_sources, required_entry=required_owner)
        case_hash = _digest(case["id"].encode("utf-8"))
        evidence = self.evidence_directory / case_hash / "native-raw.json"
        raw = _regular(evidence, MAX_DIAGNOSTIC_BYTES)
        diagnostic = _json(raw)
        if not isinstance(diagnostic, list):
            raise RuntimeOracleError("Native lifecycle diagnostics must retain raw snapshot rows.")
        entry_transport = None
        if operation in ENTRY_PROVENANCE_PROFILES:
            from equivalence.entry_provenance_evidence import validate_entry_provenance_raw
            from equivalence.entry_provenance_bindings import COMPILED_HASHES as ENTRY_ARTIFACTS
            from equivalence.session_admission_runtime_bindings import MEMORY_INDEX_WORKER_ARTIFACTS

            if any(("node_modules/openclaw", owner) not in loaded for owner in ENTRY_ARTIFACTS):
                raise RuntimeOracleError("The original entry preparation/publication/hash/limit/annotation owners did not execute.")
            entry_pid = diagnostic[0].get("pid") if diagnostic and isinstance(diagnostic[0], dict) else None
            if operation != "entry-provider-preparation-runtime":
                by_thread = {}
                for item in worker_imports:
                    if item["pid"] == entry_pid:
                        by_thread.setdefault(item["threadId"], set()).add(item["path"])
                if not any(set(MEMORY_INDEX_WORKER_ARTIFACTS) <= paths for paths in by_thread.values()):
                    raise RuntimeOracleError("Public entry publication requires its actual memory-index wrapper and implementation in one protected worker.")
            if operation == "entry-session-publication-runtime":
                from equivalence.transcript_boundary_runtime_bindings import (
                    REQUIRED_BOUNDARY_ARTIFACTS, SQLITE_BOUNDARY_ARTIFACTS, TRANSCRIPT_WORKER_ARTIFACTS,
                    TRANSCRIPT_WORKER_PARENT_ARTIFACTS,
                )

                if not set((*REQUIRED_BOUNDARY_ARTIFACTS, *SQLITE_BOUNDARY_ARTIFACTS,
                            *TRANSCRIPT_WORKER_PARENT_ARTIFACTS)) <= release_by_pid.get(entry_pid, set()):
                    raise RuntimeOracleError("Session entry publication omitted its actual SQLite/source/provenance/reset reader owners.")
                if not any(item["pid"] == entry_pid and item["path"] in TRANSCRIPT_WORKER_ARTIFACTS for item in worker_imports):
                    raise RuntimeOracleError("The declared worker-backed session projection did not execute its genuine protected transcript reader.")

            # Preserve the actual caller observations BEFORE delegating to any
            # profile guard; these are never recreated from known owner lists.
            entry_transport = {"kind": "actual-entry-profile-validator-inputs", "adapterRoot": str(ROOT),
                "runtimeRoot": self.config["runtimeRoot"], "profile": deepcopy(self.entry_profile),
                "bootstrap": deepcopy(bootstrap), "processParents": deepcopy(process_parents),
                "releaseByPid": {str(pid): sorted(paths) for pid, paths in release_by_pid.items()},
                "localByPid": {str(pid): sorted(paths) for pid, paths in local_by_pid.items()},
                "workerImports": deepcopy(worker_imports), "rawProcessWorkerTraces": deepcopy(entry_trace_files)}
            validate_entry_provenance_raw(row, case, diagnostic, evidence.parent, runtime_root=self.config["runtimeRoot"],
                bootstrap=bootstrap, release_by_pid=release_by_pid, local_by_pid=local_by_pid,
                worker_imports=worker_imports, process_parents=process_parents)
        if operation in {"model-session-runtime", "model-tool-result-runtime"}:
            from equivalence.model_runtime_evidence import validate_model_session_raw, validate_model_tool_result_raw

            validator = (validate_model_session_raw if operation == "model-session-runtime" else validate_model_tool_result_raw)
            validator(row, case, diagnostic, evidence.parent, runtime_root=self.config["runtimeRoot"], bootstrap=bootstrap,
                      release_by_pid=release_by_pid, local_by_pid=local_by_pid, process_parents=process_parents,
                      worker_imports=worker_imports)
        if operation == "trust-worker-runtime":
            from equivalence.trust_worker_profile_evidence import validate_trust_worker_profile_raw

            validate_trust_worker_profile_raw(row, case, diagnostic, evidence.parent, runtime_root=self.config["runtimeRoot"],
                bootstrap=bootstrap, release_by_pid=release_by_pid, local_by_pid=local_by_pid,
                process_parents=process_parents, worker_imports=worker_imports)
        if operation in ATOMIC_PUBLICATION_PROFILES:
            from equivalence.atomic_publication_bindings import REQUIRED_ARTIFACTS_BY_OPERATION, NATIVE_BINDING_OWNER
            from equivalence.atomic_publication_evidence import AtomicEvidenceError, validate_atomic_publication_raw

            if len(diagnostic) != 1 or not isinstance(diagnostic[0], dict) or len(bootstrap) != 1 or worker_imports:
                raise RuntimeOracleError("Atomic publication needs its single genuine protected process and complete raw IO.")
            actor = (diagnostic[0].get("pid"), diagnostic[0].get("threadId"))
            if actor != (bootstrap[0]["pid"], 0):
                raise RuntimeOracleError("Atomic raw observations came from a different process or thread.")
            owners = atomic_loaded_by_pid.get(actor, set())
            binaries = atomic_native_by_pid.get(actor, set())
            for owner in REQUIRED_ARTIFACTS_BY_OPERATION[operation]:
                if owner not in owners and not (owner == NATIVE_BINDING_OWNER and owner in binaries):
                    raise RuntimeOracleError("An actual atomic owner or default native binary escaped its authenticated process.")
            try:
                validate_atomic_publication_raw(case, row["result"], diagnostic[0], evidence_directory=evidence.parent)
            except AtomicEvidenceError as error:
                raise RuntimeOracleError(str(error)) from error
        if operation == "model-tool-error-runtime":
            from equivalence.model_tool_error_evidence import validate_model_tool_error_raw

            validate_model_tool_error_raw(row, case, diagnostic, evidence.parent, runtime_root=self.config["runtimeRoot"],
                bootstrap=bootstrap, release_by_pid=release_by_pid, local_by_pid=local_by_pid,
                process_parents=process_parents, worker_imports=worker_imports)
        if operation == "transcript-boundary-runtime":
            from equivalence.transcript_boundary_evidence import validate_transcript_boundary_raw

            validate_transcript_boundary_raw(row, case, diagnostic, evidence.parent,
                                            release_by_pid=release_by_pid, worker_imports=worker_imports)
        if operation == "durable-session-runtime":
            from equivalence.durable_session_evidence import validate_durable_session_raw

            validate_durable_session_raw(row, case, diagnostic, evidence.parent,
                                        runtime_root=self.config["runtimeRoot"], bootstrap=bootstrap,
                                        release_by_pid=release_by_pid, local_by_pid=local_by_pid,
                                        worker_imports=worker_imports, process_parents=process_parents)
        if operation == "turn-trust-runtime":
            from equivalence.turn_trust_evidence import validate_turn_trust_raw

            validate_turn_trust_raw(row, case, diagnostic, evidence.parent,
                                   approved_source=self.turn_taint_source,
                                   reference_source_imports=reference_source_imports, bootstrap=bootstrap,
                                   release_by_pid=release_by_pid, local_by_pid=local_by_pid,
                                   process_parents=process_parents, worker_imports=worker_imports)
        if operation in {"deadline-partial-runtime", "deadline-partial-get-runtime"}:
            _validate_deadline_partial_raw(row, case, diagnostic, evidence.parent)
        if operation == "workspace-isolation-runtime" and row["ok"]:
            from equivalence.workspace_isolation_evidence import validate_workspace_isolation_raw

            validate_workspace_isolation_raw(case, row["result"], diagnostic, evidence.parent)
        if operation in {"session-contract-runtime", "session-contract-helper-runtime"}:
            _validate_session_contract_raw(row, case, diagnostic, evidence.parent)
            if operation == "session-contract-runtime" and row["ok"]:
                from equivalence.session_admission_runtime_bindings import (
                    HOSTED_GATEWAY_ARTIFACTS, ARCHIVE_READ_ARTIFACTS, ARCHIVE_PERSIST_ARTIFACTS,
                    PARTICIPANT_ARTIFACTS, INCOGNITO_ARTIFACTS,
                )

                requests = diagnostic[0].get("gatewayRequests")
                if not isinstance(requests, list):
                    raise RuntimeOracleError("Session Gateway observations must retain the complete actual request list.")
                if case["input"].get("gateway") is True and not requests:
                    raise RuntimeOracleError("The requested hosted session lookup never reached its genuine Gateway owner.")
                if requests and any(("node_modules/openclaw", owner) not in loaded for owner in HOSTED_GATEWAY_ARTIFACTS):
                    raise RuntimeOracleError("Hosted session authorization lacks its actual projection, dispatch and Gateway handler owners.")
                arguments = case["input"]
                steps = arguments.get("steps", [])
                archives = [*arguments.get("archives", []), *(entry for step in steps for entry in step.get("archives", []))]
                writes = [*arguments.get("sessions", []), *(entry for step in steps for entry in step.get("sessions", []))]
                required = set(ARCHIVE_READ_ARTIFACTS) if archives else set()
                if any("identity" in entry for entry in archives):
                    required.update(ARCHIVE_PERSIST_ARTIFACTS)
                if any(entry.get("participants") for entry in writes):
                    required.update(PARTICIPANT_ARTIFACTS)
                if any(entry["storage"]["incognito"] for entry in diagnostic[0]["sessionWrites"]):
                    required.update(INCOGNITO_ARTIFACTS)
                if any(("node_modules/openclaw", owner) not in loaded for owner in required):
                    raise RuntimeOracleError("Actual session archive or participant operations lack their original read/write owners.")
        if operation == "get-contract-runtime" and case["input"]["kind"] == "tool" and row["ok"]:
            from equivalence.get_contract_runtime_bindings import READ_RUNTIME_ARTIFACTS
            from equivalence.search_contract import _same_json, decode_search_tool_envelope

            public_steps = row["result"].get("steps")
            if (not isinstance(public_steps, list) or not isinstance(case["input"].get("steps"), list)
                    or len(public_steps) != len(case["input"]["steps"]) or len(diagnostic) != 1
                    or not isinstance(diagnostic[0], dict) or diagnostic[0].get("kind") != "tool"
                    or not isinstance(diagnostic[0].get("nativeEnvelopes"), list)
                    or len(diagnostic[0]["nativeEnvelopes"]) != len(public_steps)):
                raise RuntimeOracleError("Get-tool results require every original raw operation envelope.")
            portable_paths = case["input"].get("normalizeFixturePaths") is True
            if portable_paths:
                from equivalence.get_contract import map_get_fixture_paths

                fixture_base = diagnostic[0].get("fixtureBase")
                if (not isinstance(fixture_base, str) or not Path(fixture_base).is_absolute()
                        or Path(fixture_base).parent != evidence.parent
                        or not re.fullmatch(r"native-get-fixture-[A-Za-z0-9_-]+", Path(fixture_base).name)):
                    raise RuntimeOracleError("Get-tool path aliases require the exact owned case fixture base.")
            raw_requests = diagnostic[0].get("requests")
            if portable_paths:
                raw_requests = map_get_fixture_paths(raw_requests, fixture_base)
            if not _same_json(raw_requests, row["result"].get("requests")):
                raise RuntimeOracleError("Get-tool provider requests differ from retained raw observations.")
            for index, (original, public) in enumerate(zip(diagnostic[0]["nativeEnvelopes"], public_steps, strict=True)):
                if (not isinstance(original, dict) or original.get("index") != index
                        or not isinstance(public, dict) or set(public) not in ({"result"}, {"error"})
                        or set(original) != {"index", *public}):
                    raise RuntimeOracleError("Get-tool raw and public operation identities differ.")
                observed = ({"result": decode_search_tool_envelope(original["result"])}
                            if "result" in public else {"error": original["error"]})
                if portable_paths:
                    observed = map_get_fixture_paths(observed, fixture_base)
                if not _same_json(observed, public):
                    raise RuntimeOracleError("Get-tool public payload differs from its complete raw envelope.")
            if any("result" in step for step in public_steps) and any(
                ("node_modules/openclaw", owner) not in loaded for owner in READ_RUNTIME_ARTIFACTS
            ):
                raise RuntimeOracleError("A returned get-tool envelope has no actual native read runtime.")
        if operation == "flush-execution-runtime" and not any(
            isinstance(row, dict) and isinstance(row.get("modelCalls"), list) and row["modelCalls"]
            for row in diagnostic
        ):
            raise RuntimeOracleError("The scripted provider did not observe an actual native model callback.")
        answer = deepcopy(result)
        answer["releaseSources"] = release_sources
        if captures:
            answer["fixtureCaptures"] = [captures[key] for key in sorted(captures)]
        answer["releaseTrace"] = {"kind": "authenticated-process-thread-trace",
                                  "threads": bootstrap, "protectedWorkerThreads": sum(
                                      not item["isMainThread"] for item in bootstrap),
                                  "loadedReleaseFiles": len(release_sources),
                                  "networkFetchDenied": True, "provider": "none",
                                  "nativeBinaryPolicy": "all artifact bytes authenticated before and after execution"}
        answer["runtimeDiagnostics"] = [{"id": case["id"], "sha256": _digest(raw),
                                          "rawSnapshots": _json(raw) if self.entry_profile is not None else diagnostic}]
        if entry_transport is not None:
            answer["releaseTrace"]["entryProvenanceTransport"] = entry_transport
        if self.turn_taint_source is not None:
            if len(reference_source_imports) != 1:
                raise RuntimeOracleError("The mixed profile must actually load its sole original source owner exactly once.")
            answer["releaseTrace"]["mixedReferenceSourceImports"] = reference_source_imports
        return answer
