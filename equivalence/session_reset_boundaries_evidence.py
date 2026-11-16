"""Bind reset-hook artifacts, trust and whole tool payloads to real owners.

The shared trust interface is a complete path-keyed map. Original ordered
reader rows, language outcomes, logs, SQL and publication receipts stay raw.
No detached-hook return is interpreted as a successful save.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
import stat

from equivalence.forget_lineage_evidence import _bytes, physical_snapshot
from equivalence.forget_lineage_outcomes_evidence import _files, _sdk_physical, _tables
from equivalence.search_contract import _same_json
from equivalence.search_contract import decode_search_tool_envelope

ROOT = Path(__file__).resolve().parents[1]
TRUST_FIELDS = {"fileHash", "originClass", "observedAt", "sessionId", "sessionKey"}


def _require(value, message):
    if not value:
        raise ValueError("session reset boundaries: " + message)


def _same(left, right, message):
    _require(_same_json(left, right), message)


def _sql(database):
    schema, tables = database["schema"], database["tables"]
    _require(isinstance(schema, list) and isinstance(tables, dict)
             and {row["name"] for row in schema if row["type"] == "table"} == set(tables)
             and all(isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
                     for rows in tables.values()), "a complete actual SQL snapshot is missing")
    return tables


def _trust(database, workspace, native):
    """Read complete physical trust rows without using a business normalizer."""
    tables = _sql(database)
    workspace_key = hashlib.sha256(workspace.encode()).hexdigest()
    if native:
        rows = [(row["entry_key"], json.loads(row["value_json"]))
                for row in tables["plugin_state_entries"]
                if row["plugin_id"] == "core:memory-artifact-provenance"
                and row["namespace"] == "workspace-files"]
    else:
        rows = [(row["store_key"], json.loads(row["value"]))
                for row in tables["memory_artifact_provenance"]]
    result = {}
    for key, value in rows:
        relative = value["relativePath"]
        _require(value["version"] == 1 and value["workspaceKey"] == workspace_key
                 and key == workspace_key + ":" + hashlib.sha256(relative.encode()).hexdigest()
                 and isinstance(value["reservationId"], str) and value["reservationId"]
                 and relative not in result, "a trust reservation lost its actual address or owner")
        _require(set(value) == {"version", "workspaceKey", "relativePath", "reservationId"}
                 | TRUST_FIELDS, "a complete trust record lost or gained a field")
        result[relative] = {field: value[field] for field in TRUST_FIELDS}
    return result


def _physical(raw, capture, native):
    if native:
        fixture, state = capture["fixture"], capture["state"]
        _same(fixture["root"], raw["fixtureBase"], "the actual Native fixture moved")
        _same(state["root"], raw["stateDirectory"], "the actual Native durable owner moved")
        _same(json.loads(_bytes(capture["config"])), raw["config"], "physical configuration differs")
        files, state_files = _files(fixture), _files(state)
        _tables(fixture, files)
        databases = _tables(state, state_files)
        trust_database = databases["state/openclaw.sqlite"]
    else:
        _same(capture["root"], raw["fixtureRoot"], "the actual SDK fixture moved")
        files = _files(capture)
        databases = _tables(capture, files)
        trust_database = databases["trust.sqlite"]
    return files, trust_database


def _state(raw, capture, observed, native):
    _require(set(observed) == {"files", "provenance", "toolCalls"},
             "the complete portable state interface changed")
    files, trust_database = _physical(raw, capture, native)
    artifacts = {name.removeprefix("workspace/"): data.decode("utf8")
                 for name, data in files.items() if name.startswith("workspace/memory/") and name.endswith(".md")}
    _same(observed["files"], artifacts, "the whole artifact map differs from actual physical bytes")
    _same(observed["provenance"], _trust(trust_database, raw["workspace"], native),
          "the whole public trust map differs from its actual SQL owner")
    for name, record in observed["provenance"].items():
        _require(name in artifacts and record["fileHash"] == hashlib.sha256(artifacts[name].encode()).hexdigest()
                 and record["originClass"] in {"agent", "untrusted"}
                 and type(record["observedAt"]) is int,
                 "a trust record is detached from its complete actual artifact")
    return files, trust_database


def _reader(raw, index, state, native):
    if native:
        captured = raw["states"][index]
        _same(captured["state"], state, "a complete original state read was rewritten")
        rows = captured["orderedProvenanceRows"]
        mapped = {row["relativePath"]: row["provenance"] for row in rows}
    else:
        read = raw["orderedProvenanceReads"][index]
        _same(read["owner"], "MemoryArtifactProvenanceStore.list", "a different actual trust reader was used")
        _same(read["arguments"], {"workspace_dir": raw["workspace"]}, "the actual trust reader changed workspace")
        rows = read["returnValue"]["value"]
        names = {"file_hash": "fileHash", "origin_class": "originClass", "observed_at": "observedAt",
                 "session_id": "sessionId", "session_key": "sessionKey"}
        _require(all(set(record) == set(names) for _path, record in rows),
                 "an actual ordered SDK public trust record lost fields")
        mapped = {path: {target: record[source] for source, target in names.items()} for path, record in rows}
    _require(len(mapped) == len(rows), "an actual ordered trust reader lost or duplicated a path")
    _same(mapped, state["provenance"], "the actual ordered public trust reader differs from its complete map")


def _temporary_schema(raw, rows, fault):
    """Bind the complete actual connection-local catalog, never a disk reopen."""
    definition = raw["auditDefinition"]
    statements = definition["statements"][1:]
    expected = {}
    for statement in statements:
        _require(statement.startswith("CREATE TEMP TRIGGER "), "an observer changed canonical main schema")
        expected[statement.split()[3]] = statement.replace("CREATE TEMP TRIGGER ", "CREATE TRIGGER ", 1)
    _require(len(expected) == 3, "a complete Native INSERT/UPDATE/DELETE observer is missing")
    if fault is not None:
        expected[fault["name"]] = fault["nativeSql"].replace("CREATE TEMP TRIGGER ", "CREATE TRIGGER ", 1)
    _require(isinstance(rows, list) and len(rows) == len(expected)
             and {row["name"] for row in rows} == set(expected), "the complete actual temporary catalog changed")
    for row in rows:
        _require(set(row) == {"type", "name", "tbl_name", "rootpage", "sql"}
                 and row["type"] == "trigger" and row["tbl_name"] == "plugin_state_entries" and row["rootpage"] == 0,
                 "an actual connection-local trigger lost catalog fields")
        # SQLite stores CREATE TEMP TRIGGER as CREATE TRIGGER in temp_schema.
        # The exact executed TEMP statement remains unchanged in its receipt.
        _same(row["sql"], expected[row["name"]], "a temporary trigger differs from its actual declared SQL")


def _wall_clock(case, raw):
    wall = raw["wallClock"]
    _same(wall["owner"], "memory_core.index.temporal_decay.datetime.now", "a different wall-clock seam was used")
    _same(wall["originalDatetimeOwner"], {"module": "datetime", "name": "datetime"},
          "the real datetime owner was already replaced before the fixture")
    ranking = {name: True for name in ("calculate_temporal_decay_multiplier", "apply_temporal_decay_to_score",
                                       "apply_temporal_decay_to_hybrid_results")}
    inherited = {name: True for name in ("fromtimestamp", "timestamp", "isoformat", "__new__", "__sub__")}
    _require(wall["originalDatetimeRestored"] is True, "the actual wall clock was not restored")
    _same(wall["rankingOwnersRestored"], ranking, "the real temporal-ranking owners were changed")
    times = [case["input"]["nowMs"], *(operation["nowMs"] for operation in case["input"]["operations"])]
    _require(len(wall["readings"]) == len(times), "an initial or per-operation real wall-clock read is missing")
    for index, (reading, now) in enumerate(zip(wall["readings"], times, strict=True)):
        _require(reading["requestedNowMs"] == reading["actualNowMs"] == now
                 and reading["phase"] == ("initial" if index == 0 else "operation")
                 and reading["operationIndex"] == (None if index == 0 else index - 1)
                 and reading["datetimeIsFixture"] is True
                 and int(datetime.fromisoformat(reading["returnedIso"]).timestamp() * 1000) == now,
                 "the actual ranking clock differs from the paired original operation time")
        _same(reading["inheritedMethodsUnchanged"], inherited, "the clock fixture changed datetime arithmetic")
        _same(reading["rankingOwnersUnchanged"], ranking, "the clock fixture replaced a ranking kernel")


def _sources(rows, workspace, physical_files):
    native = isinstance(rows, dict)
    _require(native or isinstance(rows, list), "whole physical source identities are missing")
    entries = rows.items() if native else ((row["path"], row) for row in rows)
    actual = {}
    for name, row in entries:
        _require(name not in actual, "a source identity was duplicated")
        _same(row["path"] if native else row["absolutePath"], str(Path(workspace) / name),
              "a source identity escaped the owned workspace")
        data = _bytes(row["bytes"])
        _require(int(row["identity"]["size"]) == len(data), "a source identity lost its actual size")
        actual[name] = data
    expected = {name.removeprefix("workspace/"): payload for name, payload in physical_files.items()
                if name.startswith("workspace/")}
    _same(actual, expected, "whole source witnesses differ from the complete physical workspace")


def _outcome(outcome):
    _require(isinstance(outcome, dict) and outcome.get("kind") in {"return", "throw"},
             "an actual language outcome is missing")
    field = "returnValue" if outcome["kind"] == "return" else "error"
    _require(set(outcome) == {"kind", field} and isinstance(outcome[field], dict),
             "an actual language outcome lost fields")
    if field == "returnValue":
        _require(isinstance(outcome[field].get("type"), str), "the actual returned type is missing")
    else:
        _require(all(isinstance(outcome[field].get(key), str) for key in ("name", "message")),
                 "a real exception lost its name or message")


def _tools(raw, index, operation, actual, before, after, native):
    previous, current = before["toolCalls"], after["toolCalls"]
    _same(current[:len(previous)], previous, "an earlier whole tool result was changed")
    added = current[len(previous):]
    if operation["op"] not in {"search", "get-all"}:
        _same(added, [], "a non-tool operation fabricated a tool result")
        return
    calls = ([row for row in raw["toolEnvelopes"] if row["operationIndex"] == index]
             if native else actual.get("toolCalls", []))
    _require(isinstance(calls, list) and len(calls) == len(added),
             "a real tool envelope was dropped or added")
    expected_tool = "memory_search" if operation["op"] == "search" else "memory_get"
    _require(len(added) == (1 if expected_tool == "memory_search" else len(after["files"])),
             "the complete actual search/get operation was not observed")
    if expected_tool == "memory_search":
        if native:
            drains = [row for row in raw["recallDrains"] if row["operationIndex"] == index]
            _require(len(drains) == 1, "the genuine post-search FIFO preparation barrier is missing")
            _same(drains[0]["importPath"], "dist/short-term-promotion-record-CEpBdgKW.mjs",
                  "the search settled a different original recall module")
            _same(drains[0]["preparationReturn"], {"type": "undefined"},
                  "the genuine original post-search barrier did not return normally")
        else:
            drain = calls[0]["recallDrain"]
            _same(drain["owner"], "MemorySearchTool.wait_for_recalls", "the real SDK recall drain is missing")
            _outcome(drain["apiOutcome"])
            _require(drain["apiOutcome"]["kind"] == "return", "the actual SDK recall drain failed")
    for call, receipt in zip(calls, added, strict=True):
        envelope = call["envelope"] if native else call["returnValue"]["value"]
        decoded = decode_search_tool_envelope(envelope)
        _same(decoded["details"] if native else decoded,
              call["decoded"] if native else call["decodedEnvelope"],
              "a whole real tool envelope differs from its decoded raw carrier")
        _same(receipt, {"tool": call["tool"], "arguments": call["arguments"],
                        "result": decoded["details"]},
              "a complete decoded tool business payload was rewritten")
        _same(receipt["tool"], expected_tool, "a different real tool was called")
        result = receipt["result"]
        if expected_tool == "memory_get":
            relative = receipt["arguments"]["path"]
            _require(relative in after["files"], "a get call did not read an actual saved artifact")
            # The profile requests the full small note from line one. Original
            # text and line ranges remain present in the complete tool result.
            _same(result["text"].rstrip("\n"), after["files"][relative].rstrip("\n"),
                  "the whole memory_get payload lost actual saved source text")
            _require(result.get("status") == "ok" and result["from"] == 1
                     and result["lines"] == len(result["text"].split("\n")),
                     "the actual artifact read lost its exact source lines")
        else:
            _require(isinstance(result.get("results"), list), "the whole search result list is missing")
            for hit in result["results"]:
                relative = hit["path"]
                _require(relative in after["files"] and type(hit["startLine"]) is int
                         and type(hit["endLine"]) is int and 1 <= hit["startLine"] <= hit["endLine"],
                         "an actual search hit lost its real source range")
                lines = after["files"][relative].replace("\r\n", "\n").split("\n")
                _require(hit["endLine"] <= len(lines), "an actual search range escaped saved bytes")
                citation = relative + "#L" + str(hit["startLine"])
                if hit["endLine"] != hit["startLine"]:
                    citation += "-L" + str(hit["endLine"])
                _same(hit["citation"], citation, "a search citation differs from the actual source line range")
                suffix = "\n\nSource: " + citation
                _require(hit["snippet"].endswith(suffix)
                         and hit["snippet"][:-len(suffix)] in "\n".join(lines[hit["startLine"] - 1:hit["endLine"]]),
                         "a whole search snippet is not grounded in its cited actual source lines")
    if expected_tool == "memory_get":
        _same([receipt["arguments"]["path"] for receipt in added], list(after["files"]),
              "get-all omitted or reordered actual artifacts")


def _hook(case, raw, index, request, actual, files, capture, native):
    profile = case["input"]["sessions"][request["session"]]
    if native:
        database_path = Path(raw["transcriptDatabasePath"])
        _require(database_path.is_relative_to(raw["fixtureBase"]), "the authoritative transcript database escaped its owner")
        relative = database_path.relative_to(raw["fixtureBase"]).as_posix()
        database = capture["fixture"]["databases"][relative]
        _same(raw["states"][index + 1]["rawSql"]["agent"], database,
              "the original transcript SQL read differs from its full physical database")
        rows = sorted((row for row in database["tables"]["transcript_events"]
                       if row["session_id"] == profile["sessionId"]), key=lambda row: row["seq"])
        _require(all(row["event_zstd"] is None and isinstance(row["event_json"], str) for row in rows),
                 "a frozen small transcript lost its original stored JSON")
        _same([json.loads(row["event_json"]) for row in rows], profile["events"],
              "the authoritative physical transcript differs from the literal input events")
        _same(actual["actualStoredEvents"], profile["events"],
              "the real original transcript store differs from literal host events")
        activation = actual["activation"]
        _require(activation["currentEntry"]["sessionId"] == profile["sessionId"]
                 and activation["scope"]["sessionId"] == profile["sessionId"],
                 "the original catalog activated a different ending session")
        event = actual["hookEvent"]
        _require(event["type"] == "command" and event["action"] == request["action"]
                 and event["sessionKey"] == case["input"]["sessionKey"]
                 and event["timestamp"]["epochMs"] == request["nowMs"]
                 and "previousSessionMemory" not in event["context"],
                 "the original hook received a supplied projection or a different command")
        _same(event["context"]["previousSessionEntry"], {"sessionId": profile["sessionId"]},
              "the hook captured a different ending session")
        calls = [call for call in raw["calls"] if call.get("operationIndex") == index]
        for owner in ("triggerInternalHook", "flushSessionMemoryWritesForTest"):
            _require(sum(call["operation"] == owner for call in calls) == 1,
                     "a real hook dispatch or sequential drain call is missing")
        reads = [call for call in calls if call["operation"] == "loadTranscriptEventsSync"]
        writes = [call for call in calls if call["operation"] == "replaceTranscriptEvents"]
        _require(len(reads) == len(writes) == 1, "an actual original transcript write/read call is missing")
        _same(writes[0]["arguments"], [activation["scope"], profile["events"]],
              "the actual original transcript writer received different events")
        _same(reads[0]["arguments"], [activation["scope"]], "the actual original reader changed scope")
        _same(reads[0]["returnValue"]["value"], actual["actualStoredEvents"],
              "the original raw transcript read was rewritten")
        _same(actual["hookEventAfter"], event, "the actual hook event was changed after dispatch")
        _same(actual["dispatchReturn"], {"type": "undefined"}, "the real detached dispatch return was changed")
        _same(actual["drainReturn"], {"type": "undefined"}, "the real drain return was changed")
    else:
        read = actual["sourceRead"]
        path = "host-transcripts/" + request["session"] + ".jsonl"
        payload = files[path]
        _same(_bytes(read["before"]["bytes"]), payload, "the persisted transcript read lost original bytes")
        _same(_bytes(read["after"]["bytes"]), payload, "the persisted transcript changed during capture")
        events = [json.loads(line) for line in payload.decode().split("\n") if line]
        _same(read["returnValue"], events, "the host transcript reader projected or changed raw events")
        _same(events, profile["events"], "the real host transcript differs from its input facts")
        arguments = actual["arguments"]
        _same(arguments["events"], events, "the real save owner received a preprojected transcript")
        _require(actual["owner"] == "save_session_memory" and arguments["session_id"] == profile["sessionId"]
                 and arguments["now_ms"] == request["nowMs"]
                 and arguments["session_key"] == case["input"]["sessionKey"],
                 "a different owner or ending session handled the real SDK save")


def _failure(case, raw, actual, before, after, database, native):
    from equivalence.session_reset_boundaries import EVIDENCE

    policy = EVIDENCE[case["id"]]
    _same(after, before, "a failed hook exposed an artifact, trust record or fabricated tool result")
    if native:
        _require(actual["apiOutcome"]["kind"] == "return", "the logged hook failure became an outer failure")
        prior = _bytes(actual["logBefore"]) if actual["logBefore"] is not None else b""
        current = _bytes(actual["logAfter"])
        _require(current.startswith(prior), "the original error log was truncated or rewritten")
        delta = current[len(prior):].decode("utf8")
        _require("Failed to save session memory" in delta and "stack" in delta,
                 "a real logged save failure with its stack is missing")
        audit_before, audit_after = actual["auditBefore"], actual["auditAfter"]
    else:
        _require(actual["apiOutcome"]["kind"] == "throw", "the genuine SDK save exception is missing")
        error = actual["apiOutcome"]["error"]
        _require(isinstance(error.get("traceback"), str) and error["traceback"],
                 "the genuine SDK exception traceback is missing")
        delta = error["message"]
        audit_before = actual["databasesBefore"]["trust"]["tables"]["reset_boundary_trust_audit"]
        audit_after = actual["databasesAfter"]["trust"]["tables"]["reset_boundary_trust_audit"]
    _same(audit_after[:len(audit_before)], audit_before, "earlier reservation audit rows were changed")
    _same(_sql(database)["reset_boundary_trust_audit"], audit_after,
          "the actual failure audit differs from physical SQL")
    new = audit_after[len(audit_before):]
    if policy["failureKind"] == "provenance-sqlite":
        if native:
            # The original store deliberately hides SQL cause text. Its actual
            # public error plus the exact installed trigger and unchanged audit
            # bind this failure without fabricating a private cause receipt.
            _require("PluginStateStoreError" in delta and "Failed to update plugin state entry." in delta,
                     "the genuine original provenance-store failure log is missing")
        else:
            _require("reset-trust-write-blocked" in delta, "the configured actual SQL abort did not occur")
        _same(new, [], "an aborted provenance transaction committed a reservation")
    else:
        if native:
            _require("EACCES" in delta, "the actual POSIX publication error is missing")
            mode = raw["operations"][0]["mode"]
            _require(stat.S_IMODE(int(mode["after"])) == 0o500 and mode["processUid"] != 0,
                     "the real permission fault did not use its declared non-root directory")
        else:
            _require(error.get("errno") == 13 and actual["modeBefore"]["mode"] == 0o500
                     and actual["modeBefore"]["effectiveUid"] != 0,
                     "the actual non-root publication PermissionError is missing")
        _require(len(new) == 2 and [row["event"] for row in new] == ["insert", "delete"]
                 and new[0]["store_key"] == new[1]["store_key"]
                 and new[0]["new_value"] == new[1]["old_value"]
                 and new[0]["old_value"] is None and new[1]["new_value"] is None,
                 "actual committed reservation followed by compensating rollback is missing")


def _operations(case, raw, public, captures, native):
    from equivalence.session_reset_boundaries import EVIDENCE

    policy = EVIDENCE[case["id"]]
    requests, operations, observations = case["input"]["operations"], raw["operations"], public["observations"]
    _require(public["provider"] == "none" and len(operations) == len(requests)
             and len(observations) == len(requests) and len(captures) == len(requests) + 1,
             "an actual operation or complete physical state was dropped")
    before = public["before"]
    previous_files, _database = _state(raw, captures[0], before, native)
    _same(raw["initialState"], before, "the complete actual initial read differs from the public state")
    _require(len(raw["states"] if native else raw["orderedProvenanceReads"]) == len(requests) + 1,
             "an actual complete ordered trust read was dropped")
    _reader(raw, 0, before, native)
    fault = None
    if native:
        _temporary_schema(raw, raw["states"][0]["temporarySchema"], fault)
    _same(before, {"files": case["input"]["files"], "provenance": {}, "toolCalls": []},
          "the real initial state differs from the frozen input facts")
    for index, (request, actual, observed) in enumerate(zip(requests, operations, observations, strict=True)):
        _same(actual["operation"], request, "the actual owner received different input facts")
        _same(observed, actual["observed"], "the public observation differs from its raw carrier")
        _same(observed["operation"], request, "the whole operation identity changed")
        after = observed["state"]
        files, database = _state(raw, captures[index + 1], after, native)
        _reader(raw, index + 1, after, native)
        if native:
            _same(actual["temporarySchemaBefore"], raw["states"][index]["temporarySchema"],
                  "the actual pre-operation temporary schema changed between observations")
            if request["op"] == "trust-failure":
                fault = request["fault"] if request["enabled"] else None
            _same(actual["temporarySchemaAfter"], raw["states"][index + 1]["temporarySchema"],
                  "the live post-operation temporary schema differs from its whole state read")
            _temporary_schema(raw, actual["temporarySchemaAfter"], fault)
        _sources(actual["sourcesBefore"], raw["workspace"], previous_files)
        _sources(actual["sourcesAfter"], raw["workspace"], files)
        _outcome(actual["apiOutcome"])
        _tools(raw, index, request, actual, before, after, native)
        if request["op"] == "hook":
            _hook(case, raw, index, request, actual, files, captures[index + 1], native)
            if policy.get("failedHookIndex") == index:
                _failure(case, raw, actual, before, after, database, native)
            else:
                added = set(after["files"]) - set(before["files"])
                _require(len(added) == 1 and added <= after["provenance"].keys(),
                         "a successful actual hook did not publish one tracked artifact")
                profile = case["input"]["sessions"][request["session"]]
                for name in added:
                    record = after["provenance"][name]
                    _require(record["observedAt"] == request["nowMs"]
                             and record["sessionId"] == profile["sessionId"]
                             and record["sessionKey"] == case["input"]["sessionKey"],
                             "the new trust record belongs to a different ending session or time")
        elif request["op"] == "search":
            receipt = after["toolCalls"][-1]
            _same(receipt["arguments"], {"query": request["query"], "maxResults": request["maxResults"],
                                        "minScore": request["minScore"]},
                  "the actual search owner received a different frozen query")
            results = receipt["result"]["results"]
            _require(bool(results) is (str(index) not in policy["negativeSearches"]),
                     "a declared positive or negative real recall invariant failed")
            if results:
                _require(any(hit["path"] not in public["before"]["files"] for hit in results),
                         "a positive recall found only a seeded unrelated artifact")
        elif request["op"] == "get-all":
            for call in after["toolCalls"][len(before["toolCalls"]):]:
                _same(call["arguments"], {"path": call["arguments"]["path"], "from": request["from"],
                                          "lines": request["lines"]},
                      "the actual get owner received a different frozen line request")
        if request["op"] != "hook" or policy.get("failedHookIndex") != index:
            _require(actual["apiOutcome"]["kind"] == "return", "an unexpected actual owner exception occurred")
        for name, text in before["files"].items():
            _same(after["files"].get(name), text, "a prior sequential artifact was overwritten")
        for name, record in before["provenance"].items():
            _same(after["provenance"].get(name), record, "a prior sequential trust record was overwritten")
        if request["op"] == "trust-failure":
            schema = actual["temporarySchemaAfter"] if native else database["schema"]
            trigger = [row for row in schema
                       if row["type"] == "trigger" and row["name"] == request["fault"]["name"]]
            _require(len(trigger) == int(request["enabled"]), "the declared actual SQL fault was not installed or removed")
            if trigger:
                statement = request["fault"]["nativeSql" if native else "sdkSql"]
                _same(trigger[0]["sql"], statement.replace("CREATE TEMP TRIGGER ", "CREATE TRIGGER ", 1),
                      "the actual SQL fault differs from its frozen literal")
                if native:
                    _same(actual["trigger"]["statement"], statement, "the actual TEMP fault statement was changed")
        if request["op"] == "sync":
            writes = actual["utimes"] if native else actual["mtimeWrites"]
            _require(len(writes) == len(after["files"]), "a declared physical mtime input was omitted")
            for write in writes:
                if not native:
                    _same(_bytes(write["before"]["bytes"]), _bytes(write["after"]["bytes"]),
                          "a metadata fixture rewrote source bytes")
                _same(write["after"]["mtimeNs"] if native else write["after"]["identity"]["mtimeNs"],
                      str(request["mtimeMs"] * 1_000_000),
                      "the actual source metadata differs from the declared input")
        before, previous_files = after, files
    final = observations[-1]["state"]
    created = set(final["files"]) - set(public["before"]["files"])
    _require(created and created <= final["provenance"].keys(),
             "a no-op or untracked save cannot verify this condition")
    saved = "\n".join(final["files"][name] for name in created)
    _require(all(token in saved for token in policy["requiredTokens"])
             and not any(token in saved for token in policy["excludedTokens"])
             and all(final["provenance"][name]["originClass"] == policy["newArtifactOrigin"] for name in created),
             "the saved source window or least-trusted origin invariant failed")
    searches = [call for call in final["toolCalls"] if call["tool"] == "memory_search"]
    gets = [call for call in final["toolCalls"] if call["tool"] == "memory_get"]
    _require(any(call["result"]["results"] for call in searches)
             and created <= {call["arguments"]["path"] for call in gets},
             "actual saved artifacts were never recalled and read")


def validate_native(case, public, snapshots, evidence):
    from equivalence.session_reset_boundaries import validate_case
    from equivalence.session_reset_boundaries_bindings import COMPILED_HASHES, REQUIRED_OBSERVED_OWNERS

    validate_case(case)
    _require(isinstance(snapshots, list) and len(snapshots) == 1, "one complete original capture is required")
    raw = snapshots[0]
    base = Path(raw["fixtureBase"])
    _require(base.is_absolute() and base.parent == Path(evidence)
             and base.name.startswith("native-session-reset-") and raw["closed"] is True,
             "the original capture lost its owned fixture or completion")
    _same(raw["input"], case["input"], "the complete original input differs")
    _same(raw["workspace"], str(base / "workspace"), "the original workspace escaped its fixture")
    seeds = raw["transcriptSeeds"]
    resolvers = [call for call in raw["calls"] if call["operation"] == "resolveSessionTranscriptDatabasePath"]
    _require(len(seeds) == len(resolvers) == len(case["input"]["sessions"]),
             "an original physical transcript owner resolution is missing")
    for seed, call, (name, session) in zip(seeds, resolvers, case["input"]["sessions"].items(), strict=True):
        scope = {"agentId": case["input"]["agentId"], "sessionId": session["sessionId"],
                 "sessionKey": case["input"]["sessionKey"], "storePath": raw["storePath"]}
        _require(seed["profile"] == name, "the original transcript profile order changed")
        _same(seed["scope"], scope, "a transcript owner resolved a different complete scope")
        _same(call["arguments"], [scope], "the real database path resolver received different arguments")
        _same(call["returnValue"]["value"], seed["databasePath"], "a real database resolver return was rewritten")
        _same(seed["databasePath"], raw["transcriptDatabasePath"], "a transcript selected a different physical database")
    expected = set(REQUIRED_OBSERVED_OWNERS)
    owners = raw["codeOwners"]
    _require({(row["modulePath"], row["exportName"], row["name"]) for row in owners} == expected
             and len(owners) == len(expected), "an actual original code owner is missing or duplicated")
    for row in owners:
        _same(row["compiledSha256"], COMPILED_HASHES[row["modulePath"]], "an original compiled owner changed")
        _same(row["functionSourceSha256"], hashlib.sha256(row["functionSource"].encode()).hexdigest(),
              "the full original function source receipt changed")
    _same(raw["output"], public, "the complete original output was rewritten")
    owner = raw["temporarySchemaOwner"]
    _require(owner["source"] == "stateHandle.db" and owner["databaseConstructor"] == "DatabaseSync"
             and owner["isOpen"] is True, "the live temporary schema lost its original connection owner")
    definition = raw["auditDefinition"]
    _same(owner["databasePath"], definition["databasePath"], "the live observer connection changed physical owner")
    _same(definition["temporarySchemaBefore"], [], "the fresh original connection had pre-existing temporary objects")
    _same(definition["temporarySchema"], raw["states"][0]["temporarySchema"],
          "the actual installed observer catalog differs from its initial state")
    _require(len(definition["receipts"]) == len(definition["statements"]) == 4,
             "an actual audit-table or TEMP-trigger creation receipt is missing")
    for statement, receipt in zip(definition["statements"], definition["receipts"], strict=True):
        _same(receipt, {"statement": statement, "returnValue": {"type": "undefined"}},
              "the original main connection did not execute the exact observer SQL")
    _same(raw["clock"], {"owner": "node:test", "apis": ["Date"], "nowMs": case["input"]["nowMs"],
          "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
          "the original clock changed scheduler ownership")
    config = raw["config"]
    _require(config["memory"]["search"]["provider"] == "none" and config["memory"]["citations"] == "auto"
             and config["hooks"]["internal"]["entries"]["session-memory"] == {"enabled": True, "llmSlug": False}
             and config["agents"]["defaults"]["userTimezone"] == case["input"]["timezone"],
             "the actual hook/provider/citation configuration changed")
    captures = [physical_snapshot(item) for item in raw["physical"]]
    _require(len(captures) == len(raw["operations"]) + 2,
             "the original initial, per-operation or closed physical capture is missing")
    _operations(case, raw, public, captures[:-1], True)
    _state(raw, captures[-1], public["observations"][-1]["state"], True)


def validate_pair(case, native_raw, sdk_raw, native_public, sdk_public, sdk_directory):
    validate_native(case, native_public, [native_raw], Path(native_raw["fixtureBase"]).parent)
    directory = Path(sdk_directory).resolve()
    path = directory / "python-raw.json"
    _require(not path.is_symlink(), "the actual SDK raw capture is a symbolic link")
    _same(json.loads(path.read_text()), [sdk_raw], "the entire supplied SDK raw capture differs from disk")
    _require(sdk_raw["fixtureRoot"] == str(directory / "sdk-fixture")
             and sdk_raw["workspace"] == str(directory / "sdk-fixture/workspace") and sdk_raw["closed"] is True,
             "the actual SDK fixture escaped its owned attempt")
    _same(sdk_raw["input"], case["input"], "the complete SDK input differs")
    _wall_clock(case, sdk_raw)
    _same(sdk_raw["schemaInitializationProvenanceRead"], {
        "owner": "MemoryArtifactProvenanceStore.list", "arguments": {"workspace_dir": sdk_raw["workspace"]},
        "returnValue": {"type": "list", "value": []}}, "the actual fresh-schema trust reader receipt changed")
    required = {"save_session_memory", "capture_session_memory_events", "get_recent_session_projection_from_events",
                "_write_session_memory_file", "_publish_new_file", "MemoryWriteProvenanceObserver.write",
                "MemoryArtifactProvenanceStore.record_write", "MemoryArtifactProvenanceStore.list",
                "SQLiteMemoryStore.reindex", "create_memory_search_tool", "create_memory_get_tool",
                "MemorySearchTool.wait_for_recalls"}
    _require(required == {owner["name"] for owner in sdk_raw["owners"]}
             and len(sdk_raw["owners"]) == len(required), "an actual SDK owner is missing or duplicated")
    clock = sdk_raw["clock"]
    _require(clock["requestedNowMs"] == clock["actualNowMs"] == case["input"]["nowMs"]
             and clock["clockFunctionReplaced"] is True and clock["originalClockRestored"] is True
             and clock["monotonicUnchanged"] is True and clock["sleepUnchanged"] is True,
             "the actual SDK clock changed scheduler ownership or was not restored")
    for owner in sdk_raw["owners"]:
        source = Path(owner["path"])
        _require(source.is_relative_to(ROOT / "memory_core") and not source.is_symlink(),
                 "an actual SDK owner escaped its source")
        _same(hashlib.sha256(source.read_bytes()).hexdigest(), owner["sha256"], "an SDK owner source changed")
    _operations(case, sdk_raw, sdk_public, _sdk_physical(sdk_raw, directory), False)
    return native_public, sdk_public
