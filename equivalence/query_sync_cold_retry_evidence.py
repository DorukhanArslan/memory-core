"""Independent custody checks for the two zero-credit cold retry probes.

An honestly captured difference is a result, not a guard failure.  This module
authenticates each engine independently; it never predicts a retry count or
repairs an unavailable public response.  It awards no acceptance coverage.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from equivalence.host_turn_barrier_evidence import _same, require
from equivalence.query_sync_cold_retry import validate_case
from equivalence.release_runtime import validate_release_sources
from equivalence.query_sync_outcomes_evidence import (
    NATIVE_METHODS, _decode_v8, _finite, _implementation_bindings, _interval,
    _one, _physical_sql, _private_markers, _published_sources, _returned_hits,
    _source_entries,
)

ROOT = Path(__file__).resolve().parents[1]
STAGES = ("initial", "afterClose")


def _expected(case):
    return {path: (text, case["input"]["initialSourceMtimeMs"])
            for path, text in case["input"]["initialFiles"].items()}


def _owned_file(filename, root):
    path, root = Path(filename), Path(root)
    require(path.is_absolute() and path.is_relative_to(root) and path.is_file()
            and not path.is_symlink() and path.resolve() == path,
            "cold-retry durable evidence escaped its actual owned directory")
    return path


def _validate_result(case, result):
    validate_case(case)
    labels = list(case["input"]["queries"])
    require(isinstance(result, dict) and set(result) == {"provider", "searches", "dispatches", "sources"}
            and result["provider"] == "none" and _finite(result)
            and list(result["searches"]) == list(result["dispatches"]) == labels
            and set(result["sources"]) == set(STAGES),
            "cold-retry complete common public wire is missing or was extended")
    for label in labels:
        details, counts = result["searches"][label], result["dispatches"][label]
        require(isinstance(details, dict) and isinstance(details.get("results"), list)
                and isinstance(counts, dict) and set(counts) == {"managerSearches", "bootstrapAttempts"}
                and all(type(value) is int and value >= 0 for value in counts.values()),
                "cold-retry actual public details or dispatch counters are incomplete")
    expected = _expected(case)
    for stage in STAGES:
        _source_entries(result["sources"][stage], sorted(expected), expected)
    return True


def _chronology(raw):
    rows = raw["events"]
    require(isinstance(rows, list) and rows
            and [row["sequence"] for row in rows] == list(range(1, len(rows) + 1))
            and all(type(row["sequence"]) is int and isinstance(row["event"], str)
                    and isinstance(row["atNs"], str) and row["atNs"].isdigit() for row in rows),
            "cold-retry actual event sequence is missing, duplicated or reordered")
    times = [int(row["atNs"]) for row in rows]
    require(times == sorted(times) and times[0] > 0,
            "cold-retry actual monotonic observations were reordered")
    return {row["sequence"]: row for row in rows}


def _sources(case, raw, result, events, *, native):
    require(set(raw["sourceStages"]) == set(STAGES), "cold-retry actual source stage omitted")
    for label in STAGES:
        stage = raw["sourceStages"][label]
        start, end = _interval(stage, events, "source-read-enter", "source-read-return", "source interval detached")
        require(events[start]["label"] == events[end]["label"] == label
                and _same(stage["common"], result["sources"][label]),
                "cold-retry returned source bytes differ from their original read")
        records = stage["records" if native else "entries"]
        require(len(records) == len(stage["common"]), "cold-retry physical source records omitted")
        for record, common in zip(records, stage["common"], strict=True):
            require(record["absolutePath"] == str(Path(raw["fixtureBase"]) / "workspace" / common["path"])
                    and all(_same(record[key], common[key]) for key in ("path", "kind", "text", "hex", "sha256")),
                    "cold-retry source byte carrier was borrowed from another file")
            if native:
                info = record["stat"]
                require(info["size"]["value"] == str(common["size"])
                        and int(info["mtimeNs"]["value"]) / 1_000_000 == common["mtimeMs"]
                        and info["nlink"]["value"] == "1"
                        and int(info["mode"]["value"]) & 0o170000 == 0o100000,
                        "cold-retry Native source stat is not an independent actual file")
            else:
                before, after = record["statBefore"], record["statAfter"]
                require(all(before[key] == after[key] for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns"))
                        and after["st_size"] == common["size"] and after["st_nlink"] == 1
                        and after["st_mtime_ns"] / 1_000_000 == common["mtimeMs"]
                        and after["st_mode"] & 0o170000 == 0o100000
                        and _owned_file(record["byteFile"], raw["fixtureBase"]).read_bytes().hex() == common["hex"],
                        "cold-retry SDK physical source bytes/stat were detached")


def _sql(row, raw, *, native, missing=False):
    # Missing cold databases are a legitimate initial observation, not a
    # successful published generation.  The generic populated SQL guard is
    # reused only after confirming the actual serialized payload exists.
    encoded = row["serializedJSON"]
    decoded = json.loads(encoded)
    require(hashlib.sha256(encoded.encode()).hexdigest() == row["sha256"]
            and all(key in row and _same(value, row[key]) for key, value in decoded.items()),
            "cold-retry physical SQL bytes/hash were detached from actual rows")
    absent = row.get("exists") is False if native else row.get("absent") is True
    if absent:
        require(missing and not row.get("schema") and not row.get("tables"),
                "cold-retry a required actual physical database is missing")
    else:
        _physical_sql(row, native=native)
    if not native:
        require(json.loads(_owned_file(row["file"], raw["fixtureBase"]).read_text()) == decoded,
                "cold-retry durable SQL carrier differs from original read")


def _generation(case, row, output, raw, *, native):
    _sql(row, raw, native=native)
    tables = row["tables"]
    source_table = "memory_index_sources" if native else "memory_core_index_sources"
    chunk_table = "memory_index_chunks" if native else "chunks"
    if tables[source_table]:
        _published_sources(row, _expected(case), native=native)
    else:
        require(not tables[chunk_table] and not tables["memory_index_chunk_provenance"]
                and not tables["memory_index_chunk_recall_metadata"],
                "cold-retry an empty actual source generation retains unrelated chunks")
    if output is None:
        return
    for hit in output["results"]:
        chunk = _one(tables[chunk_table], lambda value: value["path"] == hit["path"]
                     and value["source"] == hit["source"] and value["start_line"] == hit["startLine"]
                     and value["end_line"] == hit["endLine"], "cold-retry public hit lacks its actual pinned SQL chunk")
        provenance = _one(tables["memory_index_chunk_provenance"],
                          lambda value: value["chunk_id"] == chunk["id"], "cold-retry hit provenance missing")
        expected = {"originClass": provenance["origin_class"], "sessionKind": provenance["session_kind"],
                    "observedAt": provenance["observed_at"]}
        if provenance["supersedes_key"] is not None:
            expected["supersedesKey"] = provenance["supersedes_key"]
        require(hit["snippet"].strip() in chunk["text"] and _same(hit.get("provenance"), expected),
                "cold-retry public snippet/provenance differs from its original read generation")
    require(bool(output["results"]) is bool(tables[chunk_table]),
            "cold-retry public hit absence differs from the actual matching fixture generation")


def _owners(case, raw, events, *, native):
    require(len(raw["owners"]) == 1, "cold-retry reopened, replaced or omitted the actual live owner")
    owner_id, owner = next(iter(raw["owners"].items()))
    if native:
        require(raw["ownerNames"] == {"foreground": owner_id} and raw["foregroundOwnerId"] == owner_id
                and owner["purpose"] == "default" and owner["providerInitializedAtAcquisition"] is False
                and owner["settings"]["provider"] == "none"
                and owner["settings"]["sources"] == ["memory"],
                "cold-retry Native original owner/policy was substituted")
        acquisitions = raw["facadeCalls"]
        require(len(acquisitions) == 1 and acquisitions[0]["label"] == "foreground"
                and acquisitions[0]["ownerId"] == owner_id and acquisitions[0]["error"] is None,
                "cold-retry Native original facade acquired a hidden additional owner")
        _interval(acquisitions[0], events, "original-facade-enter", "original-facade-return", "facade interval detached")
        close = _one(raw["methodCalls"], lambda row: row["method"] == "close", "actual Native close omitted")
        require(raw["runtimeCloseAllInvoked"] is raw["runtimeCloseAllReturned"] is True
                and raw["finalManagerStates"] == [{"ownerId": owner_id, "purpose": "default", "closed": True, "closing": True}],
                "cold-retry Native original closeAll/manager custody omitted")
    else:
        require(owner_id == "owner-1" and owner["constructorName"] == "ManagedSQLiteMemoryStore"
                and len(raw["ownerAcquisitions"]) == 1,
                "cold-retry SDK original managed owner was substituted")
        acquisition = raw["ownerAcquisitions"][0]
        _interval(acquisition, events, "original-open-enter", "original-open-return", "constructor interval detached")
        require(acquisition["ownerId"] == owner_id and acquisition["objectId"] == owner["objectId"]
                and acquisition["workspaceIsExactOwner"] is acquisition["catalogIsExactOwner"] is True,
                "cold-retry SDK original owner/workspace/catalog identity was detached")
        config = owner["config"]
        require(config["workspace_dir"] == str(Path(raw["fixtureBase"]) / "workspace")
                and config["store_path"] == owner["indexPath"]
                and config["agent_id"] == case["input"]["identity"]["agentId"]
                and config["citation_mode"] == "off" and config["session_search"] is False
                and config["flags"]["vector_search"] is False
                and owner["sdkPolicy"]["memoryPublication"] == "on-search",
                "cold-retry SDK actual managed configuration was replaced")
        close = owner["close"]
        _interval(close, events, "original-close-enter", "original-close-return", "actual close interval detached")
        lifecycle = close["lifecycle"]
        require(close["closed"] is True and close["returned"] is None
                and lifecycle["closed"] is True and lifecycle["activeOperations"] == 0
                and not any(lifecycle[key] for key in ("operationJournalTruncated", "repairJournalTruncated", "sessionReadJournalTruncated"))
                and lifecycle["memoryPublication"]["active"] is False
                and lifecycle["memoryPublication"]["jobsTruncated"] is False
                and all(row["state"] in {"completed", "failed"} for row in lifecycle["operations"])
                and _same(raw["finalLifecycle"], lifecycle),
                "cold-retry SDK original close omitted or left active admitted work")
    require("error" not in close, "cold-retry original close failed")
    return owner_id, close


def _tools(case, raw, result, events, owner_id, close, *, native):
    labels = list(case["input"]["queries"])
    require(list(raw["toolCalls"]) == labels
            and sum(row["event"] == "actual-tool-enter" for row in events.values()) == len(labels)
            and sum(row["event"] == "actual-tool-return" for row in events.values()) == len(labels),
            "cold-retry prescribed original public calls were omitted or added")
    for label in labels:
        tool = raw["toolCalls"][label]
        start, end = _interval(tool, events, "actual-tool-enter", "actual-tool-return", "public tool interval detached")
        require(events[start]["label"] == events[end]["label"] == label and "error" not in tool
                and _same(tool["args"], case["input"]["queries"][label])
                and end < close["enterSeq"], "cold-retry original tool input/close order was changed")
        envelope = tool["envelope"]
        require(isinstance(envelope, dict) and isinstance(envelope["content"], list) and envelope["content"]
                and envelope["content"][0]["type"] == "text"
                and _same(json.loads(envelope["content"][0]["text"]), envelope["details"])
                and _same(envelope["details"], result["searches"][label]),
                "cold-retry entire original public envelope/details/text were changed")
        if native:
            require(_same(json.loads(tool["nativeEnvelopeSerializedJSON"]), envelope)
                    and set(tool["nativeDetailsOwnKeys"]) == set(envelope["details"]) | set(tool["nativeDetailsUndefinedOwnKeys"])
                    and set(tool["nativeDetailsUndefinedOwnKeys"]).isdisjoint(envelope["details"]),
                    "cold-retry Native public serialization/own fields were lost")
            getters = [row for row in raw["originalGetCalls"] if row["activeTool"] == label]
            require(getters, "cold-retry Native tool skipped its actual original owner getter")
            for getter in getters:
                _interval(getter, events, "original-get-enter", "original-get-return", "original getter interval detached")
                require(getter["ownerId"] == owner_id and getter["returnedIsExactSampledOwner"] is True
                        and getter["receiverIsOriginalClass"] is True and getter["requestedPurpose"] == "default"
                        and start < getter["enterSeq"] < getter["returnSeq"] < end,
                        "cold-retry Native public query switched or reopened its original owner")
        else:
            carrier = tool["envelopeFile"]
            payload = _owned_file(carrier["path"], raw["fixtureBase"]).read_bytes()
            require(len(payload) == carrier["bytes"] and hashlib.sha256(payload).hexdigest() == carrier["sha256"]
                    and _same(json.loads(payload), envelope), "cold-retry durable original public envelope changed")
            binding = _one(raw["toolBindings"], lambda row: row["label"] == label, "actual SDK tool binding omitted")
            require(binding["ownerId"] == owner_id and tool["ownerId"] == owner_id
                    and binding["storeObjectId"] == raw["owners"][owner_id]["objectId"]
                    and all(binding[key] is True for key in ("storeIsExactObservedOwner", "configIsExactOwnerConfig", "contextStatusIsNone", "refreshStoreIsNone")),
                    "cold-retry SDK public tool replaced owner/config/status or installed refresh")
        calls = [row for row in raw["originalSearchCalls"] if row["activeTool"] == label]
        require(calls, "cold-retry original public search did not dispatch an actual manager search")
        for call in calls:
            _interval(call, events, "original-search-enter", "original-search-return", "actual search interval detached")
            require(call["ownerId"] == owner_id and call["receiverIsExactObservedOwner"] is True
                    and start < call["enterSeq"] < call["returnSeq"] < end
                    and call["query"] == case["input"]["queries"][label]["query"],
                    "cold-retry manager dispatch was borrowed from another receiver/query/interval")
        if "error" not in calls[-1]:
            _returned_hits(calls[-1], result["searches"][label], native=native)
        else:
            require(not result["searches"][label]["results"] and result["searches"][label].get("unavailable") is True,
                    "cold-retry caught actual search error was presented as a successful result")
    first, second = (raw["toolCalls"][label] for label in labels)
    require(first["returnSeq"] < second["enterSeq"], "cold-retry second query was admitted before first actual return")
    gap = [row for seq, row in events.items() if first["returnSeq"] < seq < second["enterSeq"]]
    allowed = {"actual-tool-binding"}
    if "fault" in case["input"]:
        allowed |= ({"fault-remove-enter", "fault-remove-return", "fault-syscall-enter", "fault-syscall-return"}
                    if native else {"physical-fault-remove-enter", "physical-fault-remove-return"})
    require(all(row["event"] in allowed for row in gap),
            "cold-retry inserted a sync, read, status, wait, query or reopen between actual returns")
    return raw["toolCalls"]


def _entry_identity(entry, *, native):
    if native:
        identity = entry["identity"]
        return identity["device"], identity["inode"], identity["nlink"], identity["mode"]
    info = entry["stat"]
    return info["st_dev"], info["st_ino"], info["st_nlink"], info["st_mode"]


def _fault(case, raw, events, owner_id, tools, *, native):
    present = "fault" in case["input"]
    faults = ([raw["fault"]] if raw.get("fault") is not None else []) if native else raw["faults"]
    require(len(faults) == int(present), "cold-retry physical fault missing or added to clean control")
    if not present:
        require(not raw.get("faultSyscalls"), "cold-retry clean control mutated publication sidecars")
        return
    fault = faults[0]
    owner = raw["owners"][owner_id]
    db = owner["settings"]["store"]["databasePath"] if native else owner["indexPath"]
    sidecar = db + (".reindex-lock.sqlite" if native else "-journal")
    target = str(Path(raw["fixtureBase"]) / case["input"]["fault"]["target"])
    require(fault["kind"] == case["input"]["fault"]["kind"]
            and fault["sidecar" if native else "path"] == sidecar and fault["target"] == target
            and Path(sidecar).is_relative_to(Path(raw["fixtureBase"]))
            and fault["targetParentBefore"]["kind"] == "missing",
            "cold-retry fault targeted another owner, sidecar or an existing target")
    initial = fault["initial" if native else "before"]
    armed, before = fault["armed"], fault["beforeRemoval"]
    restored = fault["restored" if native else "afterRemoval"]
    link_key = "target" if native else "linkTarget"
    require(initial["kind"] in {"missing", "file"}
            and armed["kind"] == before["kind"] == "symlink"
            and armed["path"] == before["path"] == sidecar
            and armed[link_key] == before[link_key] == target
            and _entry_identity(armed, native=native) == _entry_identity(before, native=native)
            and _entry_identity(armed, native=native)[2] == 1
            and _entry_identity(armed, native=native)[3] & 0o170000 == 0o120000
            and fault["afterUnlink"]["kind"] == "missing",
            "cold-retry actual owned dangling symlink/inode was not preserved until unlink")
    if native:
        require(fault["ownerId"] == owner_id and fault["dbPath"] == db
                and all(fault[key]["kind"] == "missing" for key in
                        ("targetBefore", "targetAfterArm", "targetBeforeRemoval", "backupBefore", "backupAfterRestore"))
                and fault["removed"] is True and fault["emergencyRemoval"] is False,
                "cold-retry Native refusal was ineffective or removed only during teardown")
        names = ("fault-arm-enter", "fault-arm-return", "fault-remove-enter", "fault-remove-return")
        calls = raw["faultSyscalls"]
        for call in calls:
            _interval(call, events, "fault-syscall-enter", "fault-syscall-return", "physical syscall interval detached")
            require(events[call["enterSeq"]]["method"] == events[call["returnSeq"]]["method"] == call["method"]
                    and _same(events[call["enterSeq"]]["args"], call["args"]),
                    "cold-retry fault syscall arguments were relabelled")
        for method, args in (("symlinkSync", [target, sidecar]), ("unlinkSync", [sidecar])):
            call = _one(calls, lambda row: row["method"] == method, "actual physical symlink/unlink receipt missing")
            require(call["args"] == args and "error" not in call,
                    "cold-retry original fault syscall failed or changed paths")
        expected_methods = {"lstatSync", "realpathSync", "readFileSync", "readlinkSync", "renameSync", "symlinkSync", "unlinkSync"}
        require(all(call["method"] in expected_methods for call in calls)
                and len(calls) == sum(row["event"] == "fault-syscall-enter" for row in events.values())
                == sum(row["event"] == "fault-syscall-return" for row in events.values()),
                "cold-retry physical syscall receipts were dropped or invented")
    else:
        require(fault["actualFollowError"]["name"] == "FileNotFoundError"
                and fault["actualFollowError"]["errno"] == 2
                and fault["savedAfterRemoval"]["kind"] == "missing"
                and not fault.get("removedDuringTeardown"),
                "cold-retry SDK symlink did not physically refuse access or lacked natural removal")
        names = ("physical-fault-arm-enter", "physical-fault-arm-return", "physical-fault-remove-enter", "physical-fault-remove-return")
    _interval({"enterSeq": fault["armEnterSeq"], "returnSeq": fault["armReturnSeq"]}, events, *names[:2], "fault arm interval detached")
    _interval({"enterSeq": fault["removeEnterSeq"], "returnSeq": fault["removeReturnSeq"]}, events, *names[2:], "fault removal interval detached")
    first, second = (tools[label] for label in case["input"]["queries"])
    require(fault["armEnterSeq"] < fault["armReturnSeq"] < first["enterSeq"]
            < first["returnSeq"] < fault["removeEnterSeq"] < fault["removeReturnSeq"] < second["enterSeq"],
            "cold-retry fault did not surround exactly the first actual public call")
    if initial["kind"] == "file":
        renamed = fault["backupAfterRename" if native else "renamedOriginal"]
        require(renamed["kind"] == restored["kind"] == "file"
                and _entry_identity(initial, native=native) == _entry_identity(renamed, native=native)
                == _entry_identity(restored, native=native)
                and initial["hex"] == renamed["hex"] == restored["hex"]
                and initial["sha256"] == renamed["sha256"] == restored["sha256"]
                == hashlib.sha256(bytes.fromhex(initial["hex"])).hexdigest(),
                "cold-retry preserved real sidecar was not restored with its original bytes/inode")
    else:
        require(restored["kind"] == "missing", "cold-retry fault removal retained an invented sidecar")


def _sdk_calls(case, raw, result, events, owner_id, tools):
    lifecycle = raw["owners"][owner_id]["close"]["lifecycle"]
    methods = raw["methodCalls"] + raw["backgroundCalls"] + raw["readAdmissions"]
    require(len(methods) == sum(row["event"] == "original-method-enter" for row in events.values())
            == sum(row["event"] == "original-method-return" for row in events.values()),
            "cold-retry SDK omitted original method/reader/publication receipts")
    for call in methods:
        start, end = _interval(call, events, "original-method-enter", "original-method-return", "SDK method interval detached")
        require(call["receiverIsExactObservedOwner"] is True and call["ownerId"] == owner_id
                and events[start]["method"] == events[end]["method"] == call["method"]
                and end < raw["owners"][owner_id]["close"]["returnSeq"]
                and call["method"] in {"reindex", "reindex_sources", "_submit_memory_publication", "_run_memory_publication", "_on_search_snapshot"},
                "cold-retry SDK original receiver/method/settlement was substituted")
    for label, tool in tools.items():
        searches = [row for row in raw["originalSearchCalls"] if row["activeTool"] == label]
        operation_ids = {number for row in searches for number in row["managedSearchOperationIds"]}
        operations = [row for row in lifecycle["operations"] if row["id"] in operation_ids]
        require(len(operations) == len(operation_ids) == len(searches)
                and all(row["name"] == "search" and row["query"] == case["input"]["queries"][label]["query"]
                        and row["state"] in {"completed", "failed"} for row in operations),
                "cold-retry SDK searches lost their actual original operation journal")
        repairs = [row for row in lifecycle["repairs"] if row["reason"] == "search-bootstrap"
                   and row["searchOperationId"] in operation_ids]
        reindexes = [row for row in raw["methodCalls"] if row["method"] == "reindex"
                     and row["parentOperationId"] in operation_ids]
        require(len(repairs) == len(reindexes)
                and all(tool["enterSeq"] < row["enterSeq"] < row["returnSeq"] < tool["returnSeq"]
                        and row["activeTool"] == label and row["workspaceIsExactOwner"] is True for row in reindexes),
                "cold-retry SDK bootstrap count was detached from real original reindex entries")
        derived = {"managerSearches": len(searches), "bootstrapAttempts": len(repairs)}
        require(_same(result["dispatches"][label], derived)
                and _same(raw["dispatchDerivations"][label], {
                    "searchCallIds": [row["id"] for row in searches],
                    "managedSearchOperationIds": sorted(operation_ids),
                    "repairIds": [row["id"] for row in repairs],
                    "reindexCallIds": [row["id"] for row in reindexes]}),
                "cold-retry SDK public counters differ from actual receiver-qualified dispatches")
        for repair, reindex in zip(repairs, reindexes, strict=True):
            require(repair["state"] == ("failed" if "error" in reindex else "completed")
                    and repair["searchOperationId"] == reindex["parentOperationId"]
                    and repair["force"] == reindex["options"].get("force", False),
                    "cold-retry SDK repair error/state/force was detached from actual publication")
        reads = [row for row in raw["readAdmissions"] if row["activeTool"] == label]
        for read in reads:
            pinned = read["pinnedSnapshot"]
            require(read["method"] == "_on_search_snapshot" and "error" not in read
                    and tool["enterSeq"] < read["enterSeq"] < read["returnSeq"] < tool["returnSeq"]
                    and pinned["ownerId"] == owner_id and pinned["activeTool"] == label
                    and pinned["inTransactionBefore"] is pinned["inTransactionAfter"] is True
                    and pinned["sameActualConnectionPassedToOriginal"] is True
                    and pinned["readRevision"] == read["readRevision"]
                    and [row for row in pinned["databases"] if row[1] == "main"] == [[0, "main", pinned["dbPath"]]],
                    "cold-retry SDK read generation was borrowed from another owner/connection")
            _generation(case, pinned, result["searches"][label], raw, native=False)
            require(pinned["tables"]["memory_core_index_sync"][0]["revision"] == read["readRevision"],
                    "cold-retry SDK pinned generation revision differs from actual SQL")
        if result["searches"][label]["results"]:
            require(reads, "cold-retry SDK successful public hits lack original pinned reader")
    if "fault" in case["input"]:
        first = next(iter(tools))
        failed = [row for row in raw["methodCalls"] if row["method"] == "reindex"
                  and row["activeTool"] == first and "error" in row]
        require(failed and all(row["error"].get("sqlite_errorcode") == 14
                              or "open" in row["error"].get("message", "").lower() for row in failed)
                and result["searches"][first].get("unavailable") is True
                and not result["searches"][first]["results"],
                "cold-retry SDK physical refusal never affected original bootstrap/public unavailability")


def _native_process(case, raw, *, approved_node=None):
    directory = Path(raw["fixtureBase"]).parent
    context_path, process_path = directory / "context.json", directory / "process.json"
    context, process = json.loads(context_path.read_text()), json.loads(process_path.read_text())
    require(process["pid"] == raw["pid"] and process["parentPid"] == raw["ppid"]
            and process["returncode"] == 0 and process["contextPath"] == str(context_path)
            and process["contextSha256"] == hashlib.sha256(context_path.read_bytes()).hexdigest()
            and process["requestSha256"] == hashlib.sha256(Path(process["requestPath"]).read_bytes()).hexdigest()
            and _same(json.loads(Path(process["requestPath"]).read_text()), {key: case[key] for key in ("id", "operation", "input")})
            and int(process["startedAtNs"]) < int(raw["events"][0]["atNs"])
            <= int(raw["events"][-1]["atNs"]) < int(process["finishedAtNs"]),
            "query-sync Native actual PID/request/context/process interval changed")
    require(context["stateDirectory"] == raw["fixtureBase"] and context["fetchPolicy"] == "deny"
            and context["providerMode"] == "none" and process["argv"][0] == context["approvedNodeRuntime"]["execPath"]
            and process["environment"]["OPENCLAW_STATE_DIR"] == raw["fixtureBase"]
            and process["environment"]["MEMORY_EQ_RELEASE_CONTEXT"] == str(context_path)
            and set(process["environment"]) == {"PATH", "LANG", "TZ", "NODE_OPTIONS", "MEMORY_EQ_RELEASE_CONTEXT", "OPENCLAW_STATE_DIR", "OPENCLAW_CONFIG_PATH"},
            "query-sync Native actual executable/environment/source fixture was substituted")
    returned = json.loads(Path(process["stdoutPath"]).read_text())
    require(returned["id"] == case["id"] and returned["ok"] is True and _same(returned["result"], raw["result"]),
            "query-sync Native actual stdout dropped complete public results")
    local = {row["path"]: row["sha256"] for row in context["allowedLocal"]}
    require(set(local) == {str(ROOT / "equivalence" / f"query-sync-cold-retry-{name}.mjs")
                           for name in ("entry", "preload", "runtime")}
            and process["cwd"] == str(ROOT),
            "cold-retry Native context supplied an unreviewed local program")
    for filename, digest in local.items():
        require(Path(filename).is_file() and hashlib.sha256(Path(filename).read_bytes()).hexdigest() == digest,
                "query-sync Native protected actor bytes changed after actual execution")
    expected = {(package["location"], file["path"]): file["sha256"]
                for package in context["runtime"]["packages"] for file in package["files"]}
    threads, main, worker, oracle = set(), set(), set(), set()
    for path in sorted(Path(context["traceDirectory"]).glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        require(rows and rows[0]["event"] == "bootstrap", "query-sync Native actual import trace lacks bootstrap")
        first = rows[0]
        require(first["pid"] == raw["pid"] and first["ppid"] == raw["ppid"]
                and first["runtime"] == context["approvedNodeRuntime"] and first["fetchDenied"] is True
                and first["contextSha256"] == process["contextSha256"]
                and first["isMainThread"] is (first["threadId"] == 0)
                and path.name == f'{raw["pid"]}-{first["threadId"]}.jsonl',
                "query-sync Native imported worker belongs to another actual process/binary")
        require(first["threadId"] not in threads, "query-sync Native duplicated actual worker import trace")
        threads.add(first["threadId"])
        own = [row for row in rows if row["event"] == "query-sync-cold-retry-bootstrap"]
        require(len(own) == 1 and own[0]["clock"]["apis"] == ["Date"]
                and own[0]["clock"]["nowMs"] == case["input"]["nowMs"]
                and own[0]["clock"]["setTimeoutUnchanged"] is True
                and own[0]["clock"]["performanceNowUnchanged"] is True,
                "query-sync Native actual workers changed timer or Date-only profile")
        for row in rows[1:]:
            require(row["pid"] == raw["pid"] and row["threadId"] == first["threadId"],
                    "query-sync Native actual import trace changed worker identity")
            if row["event"] == "query-sync-cold-retry-bootstrap":
                continue
            require(row["event"] in {"load", "resolve-native"}, "query-sync Native actual import trace added unknown operation")
            if row.get("kind") == "oracle":
                require(local.get(row["path"]) == row["sha256"], "query-sync Native unapproved actor executed")
                oracle.add(row["path"])
            else:
                require(row.get("kind") == "release" and expected.get((row["package"], row["path"])) == row["sha256"],
                        "query-sync Native actual imported engine source bytes changed")
                (main if first["isMainThread"] else worker).add(row["path"])
    require(0 in threads and len(threads) > 1 and set(local) - {str(Path(process["cwd"]) / "equivalence/query-sync-cold-retry-preload.mjs")} <= oracle
            and {"dist/extensions/memory-core/manager-runtime.js", "dist/tools-DotaQGXh.mjs"} <= main
            and "dist/sqlite-worker-store-D6Kl0iv0.mjs" in worker,
            "query-sync Native actual public manager/tool/read/publication workers did not execute")
    loaded = [{"package": package, "path": path, "sha256": digest}
              for (package, path), digest in expected.items() if path in main | worker]
    validate_release_sources(context["runtime"], loaded)
    authority = context["approvedNodeRuntime"]
    configured = approved_node or os.environ.get("MEMORY_EQ_NODE")
    local = ROOT / "work/node-v24.16.0-linux-x64/bin/node"
    selected = configured or (str(local) if local.is_file() else shutil.which("node"))
    require(selected is not None, "query-sync independent trusted Node decoder is unavailable")
    trusted = Path(selected).resolve(strict=True)
    require(trusted == Path(authority["execPath"]) and trusted.is_file()
            and hashlib.sha256(trusted.read_bytes()).hexdigest() == authority["sha256"],
            "query-sync captured Node authority differs from independently trusted decoder")
    return {**authority, "execPath": str(trusted)}


def _native_wires(raw, events, authority):
    encoded = []
    for direction, rows in (("request", raw["workerDispatches"]), ("reply", raw["workerMessages"])):
        for row in rows:
            message = row["message"]
            keys = (["input", "preparation"] if direction == "request" and message.get("type") in {"open", "execute", "execute-frame"}
                    else ["value"] if direction == "reply" and type(message.get("id")) is int and message.get("ok") is True else [])
            selected = {key for key in keys if isinstance(message.get(key), dict)
                        and message[key].get("privateType") in {"Uint8Array", "Buffer"}}
            require(set(row["decodedSerialized"]) == selected,
                    "cold-retry opaque original SQL wire lost its complete decode custody")
            for key in selected:
                wire, receipt = message[key], row["decodedSerialized"][key]
                require(wire["byteLength"] == len(bytes.fromhex(wire["hex"]))
                        and receipt["bytesSha256"] == hashlib.sha256(bytes.fromhex(wire["hex"])).hexdigest()
                        and set(receipt) == {"bytesSha256", "value"},
                        "cold-retry original V8 bytes were replaced or decoding failed")
                encoded.append((wire["hex"], receipt["value"]))
    require(encoded, "cold-retry omitted all original serialized SQL traffic")
    actual = _decode_v8(authority, [wire for wire, _ in encoded])
    require(all(_same(value, claimed) for value, (_, claimed) in zip(actual, encoded, strict=True)),
            "cold-retry independently decoded original V8 parameters differ from claimed values")
    for dispatch in raw["workerDispatches"]:
        _interval(dispatch, events, "actual-worker-dispatch-enter", "actual-worker-dispatch-return", "original worker dispatch detached")
        require(dispatch["returnedUndefined"] is True and "error" not in dispatch,
                "cold-retry actual worker postMessage failed")
        message = dispatch["message"]
        if type(message.get("id")) is int:
            replies = [row for row in raw["workerMessages"] if row["workerId"] == dispatch["workerId"]
                       and row["message"].get("id") == message["id"]]
            command = dispatch["decodedSerialized"].get("input", {}).get("value", {})
            if not replies:
                require(command.get("type") == "pluginState.appendJournal",
                        "cold-retry original SQL request lost its real worker reply")
                continue
            require(len(replies) == 1 and dispatch["returnSeq"] < replies[0]["sequence"]
                    and replies[0]["threadId"] == dispatch["threadId"] > 0
                    and type(replies[0]["message"].get("ok")) is bool,
                    "cold-retry original SQL worker reply changed request/process/order")
    require(len(raw["workerDispatches"]) == sum(row["event"] == "actual-worker-dispatch-enter" for row in events.values())
            == sum(row["event"] == "actual-worker-dispatch-return" for row in events.values())
            and len(raw["workerMessages"]) == sum(row["event"] == "actual-worker-message" for row in events.values()),
            "cold-retry original worker transport receipts were dropped")


def _native_calls(case, raw, result, events, owner_id, tools):
    require(all(row["method"] in NATIVE_METHODS for row in raw["methodCalls"])
            and all(sum(row["event"] == f"original-{method}-{suffix}" for row in events.values())
                    == sum(row["method"] == method for row in raw["methodCalls"])
                    for method in NATIVE_METHODS for suffix in ("enter", "return")),
            "cold-retry original Native method receipts were omitted or added")
    for bucket, method in (("statusCalls", "status"), ("originalSearchCalls", "search"),
                           ("backgroundCalls", "syncPublishedIndexInBackground")):
        require(_same(raw[bucket], [row for row in raw["methodCalls"] if row["method"] == method]),
                "cold-retry specialized original method receipts differ from complete calls")
    for call in raw["methodCalls"]:
        start, end = _interval(call, events, f'original-{call["method"]}-enter',
                               f'original-{call["method"]}-return', "original Native method interval detached")
        require(call["ownerId"] == owner_id and call["receiverIsExactObservedOwner"] is True
                and events[start]["ownerId"] == events[end]["ownerId"] == owner_id,
                "cold-retry original Native method was borrowed from another receiver")
    for label, tool in tools.items():
        during = [row for row in raw["methodCalls"] if row["activeTool"] == label
                  and tool["enterSeq"] < row["enterSeq"] < tool["returnSeq"]]
        require(_same(result["dispatches"][label], {
                    "managerSearches": sum(row["method"] == "search" for row in during),
                    "bootstrapAttempts": sum(row["method"] == "syncAdmitted" and row["args"][0].get("reason") == "search-bootstrap" for row in during)}),
                "cold-retry Native public counters differ from actual original method admissions")
        preparations = [row for row in during if row["method"] == "prepareKeywordSearch" and "error" not in row]
        for preparation in preparations:
            snapshot = _one(raw["snapshots"], lambda row: row.get("methodCallId") == preparation["id"],
                            "actual Native read generation SQL missing")
            require(preparation["returnSeq"] < snapshot["enterSeq"] < snapshot["returnSeq"] < tool["returnSeq"]
                    and snapshot["ownerId"] == owner_id,
                    "cold-retry actual read-generation SQL was moved after public return")
            _generation(case, snapshot, result["searches"][label], raw, native=True)
            leases = [row for row in snapshot["coordinationLeases"] if row["open"] is True
                      and row["transactionActive"] is True and row["location"] == snapshot["dbPath"] + ".generation-lock.sqlite"]
            require(len(leases) == 1, "cold-retry Native reader lacked its actual held generation lease")
            lease = leases[0]
            own = [row for row in raw["leaseCalls"] if row["databaseRef"] == lease["databaseRef"]]
            begin = _one(own, lambda row: row["method"] == "exec" and row["args"] == ["BEGIN"], "actual generation BEGIN omitted")
            pinned = _one(own, lambda row: row["method"] == "statement.get", "actual generation pin omitted")
            rollback = _one(own, lambda row: row["method"] == "exec" and row["args"] == ["ROLLBACK"], "actual generation rollback omitted")
            close = _one(own, lambda row: row["method"] == "close", "actual generation close omitted")
            require(begin["returnSeq"] < pinned["enterSeq"] < pinned["returnSeq"] < preparation["enterSeq"]
                    < snapshot["returnSeq"] < rollback["enterSeq"] < rollback["returnSeq"] < close["enterSeq"]
                    and begin["transactionBefore"] is False and begin["transactionAfter"] is True
                    and "acquireMemoryIndexReadGeneration" in begin["originalCallerStack"] and close["openAfter"] is False,
                    "cold-retry Native actual read checkpoint was outside its original held lease")
            pool = _one(raw["poolCalls"], lambda row: row["activeTool"] == label
                        and row["args"][0].get("kind") == "keyword"
                        and preparation["enterSeq"] < row["enterSeq"] < row["returnSeq"] < preparation["returnSeq"],
                        "actual Native keyword worker dispatch omitted")
            job = pool["args"][0]
            require(job["databasePath"] == snapshot["dbPath"] and job["agentId"] == case["input"]["identity"]["agentId"]
                    and job["query"]["body"]["query"] == case["input"]["queries"][label]["query"]
                    and job["query"]["body"]["sourceFilter"]["params"] == ["memory"]
                    and job["includeIndexState"] is True,
                    "cold-retry Native original worker searched another source/query/database")
            dispatch = _one(raw["workerDispatches"], lambda row: pool["enterSeq"] < row["enterSeq"] < row["returnSeq"] < pool["returnSeq"]
                            and _same(row["message"].get("input"), job), "actual Native keyword postMessage omitted")
            reply = _one(raw["workerMessages"], lambda row: row["workerId"] == dispatch["workerId"]
                         and row["message"].get("taskId") == dispatch["message"]["taskId"], "actual Native keyword reply omitted")
            require(dispatch["returnSeq"] < reply["sequence"] < pool["returnSeq"]
                    and reply["message"]["status"] == "ok" and _same(reply["message"]["value"], pool["result"])
                    and _same(pool["result"]["body"], preparation["result"]["keyword"]["body"])
                    and _same(pool["result"]["indexState"], preparation["result"]["indexState"]),
                    "cold-retry actual Native keyword result/read revision differs from its worker reply")
        if result["searches"][label]["results"]:
            require(preparations, "cold-retry Native public hits lack original physical reader")
    if "fault" in case["input"]:
        first = next(iter(tools))
        failures = [row for row in raw["methodCalls"] if row["activeTool"] == first and row["method"] == "syncAdmitted"
                    and row["args"][0].get("reason") == "search-bootstrap" and "error" in row]
        require(failures and raw["fault"]["actualBootstrapFailures"] == [row["id"] for row in failures]
                and all("open" in row["error"]["message"].lower() for row in failures)
                and result["searches"][first].get("unavailable") is True
                and not result["searches"][first]["results"],
                "cold-retry physical refusal never affected actual Native bootstrap/public result")
    for row in raw["leaseCalls"]:
        _interval(row, events, "original-coordination-enter", "original-coordination-return", "actual coordination receipt detached")
    for row in raw["poolCalls"]:
        _interval(row, events, "original-pool-run-enter", "original-pool-run-return", "actual pool receipt detached")


def _raw(case, raw, result, *, native, approved_node=None):
    require(isinstance(raw, dict) and raw.get("kind") == ("query-sync-cold-retry" if native else "query-sync-cold-retry-development")
            and raw.get("engine") == ("native" if native else "sdk") and raw.get("caseId") == case["id"]
            and _same(raw.get("input"), case["input"]) and _same(raw.get("result"), result)
            and type(raw.get("pid")) is type(raw.get("ppid")) is int
            and raw["pid"] > 0 and raw["ppid"] > 0 and raw["pid"] != raw["ppid"]
            and Path(raw["fixtureBase"]).is_absolute() and raw.get("completed") is True
            and raw.get("allManagersClosed") is True and "error" not in raw
            and not any(raw.get(key) for key in ("teardownError", "teardownErrors", "faultCleanupError")),
            "cold-retry actual protected capture is incomplete or belongs to another attempt")
    if not native:
        _private_markers(raw)
        _implementation_bindings(raw)
        require(_same(raw["requestedConfig"], case["input"]["config"])
                and _same(raw["clock"], {"owner": "public-tool-clock", "nowMs": case["input"]["nowMs"], "monotonicAndTimers": "unmodified"})
                and raw["sourcePolicy"]["sources"] == raw["sourcePolicy"]["searchSources"] == ["memory"]
                and raw["sdkProfile"]["memoryPublication"] == "on-search"
                and raw["sdkProfile"]["contextStatus"] is raw["sdkProfile"]["refreshStore"] is None,
                "cold-retry SDK real clock/source/publication profile was replaced")
    events = _chronology(raw)
    _sources(case, raw, result, events, native=native)
    owner_id, close = _owners(case, raw, events, native=native)
    tools = _tools(case, raw, result, events, owner_id, close, native=native)
    _fault(case, raw, events, owner_id, tools, native=native)
    for status in raw["statusCalls"]:
        _interval(status, events, "original-status-enter", "original-status-return", "actual original status detached")
        require(status["ownerId"] == owner_id and status["receiverIsExactObservedOwner"] is True
                and "error" not in status and isinstance(status["result"], dict)
                and status["result"]["provider"] == result["provider"],
                "cold-retry selected provider/status is detached from original owner")
    require(raw["statusCalls"], "cold-retry actual selected provider was never observed")
    (_native_calls if native else _sdk_calls)(case, raw, result, events, owner_id, tools)
    snapshots = raw["snapshots"]
    require(snapshots and len({row["label"] for row in snapshots}) == len(snapshots),
            "cold-retry actual physical SQL stages were omitted or duplicated")
    for snapshot in snapshots:
        _interval(snapshot, events, "physical-sql-read-enter", "physical-sql-read-return", "physical SQL interval detached")
        _sql(snapshot, raw, native=native, missing=snapshot["label"].startswith("before-"))
    final = _one(snapshots, lambda row: row["label"] == "after-close", "actual after-close physical SQL omitted")
    require(close["returnSeq"] < final["enterSeq"] < final["returnSeq"]
            < raw["sourceStages"]["afterClose"]["enterSeq"]
            and raw["sourceStages"]["initial"]["returnSeq"] < tools[next(iter(tools))]["enterSeq"],
            "cold-retry source/physical final checkpoint crossed original close")
    _generation(case, final, None, raw, native=native)
    if native:
        authority = _native_process(case, raw, approved_node=approved_node)
        _native_wires(raw, events, authority)
    return True


def _sdk(case, dispatch, result):
    require(isinstance(dispatch, dict) and dispatch.get("kind") == "query-sync-cold-retry-sdk-dispatch"
            and _same(dispatch.get("input"), case["input"]) and _same(dispatch.get("exit"), {"code": 0})
            and type(dispatch["pid"]) is type(dispatch["coordinatorPid"]) is int
            and dispatch["pid"] != dispatch["coordinatorPid"]
            and int(dispatch["startedAtNs"]) < int(dispatch["finishedAtNs"]),
            "cold-retry original SDK process dispatch failed or was reassigned")
    wire = dispatch["requestJson"]
    request = json.loads(wire)
    require(_same(request, dispatch["request"]) and set(request) == {"input", "directory"}
            and _same(request["input"], case["input"])
            and hashlib.sha256(wire.encode()).hexdigest() == dispatch["requestSha256"]
            and dispatch["argv"][1:] == ["-m", "equivalence.query_sync_cold_retry_sdk_cli"]
            and dispatch["environmentKeys"] == ["LANG", "OPENCLAW_HOME", "OPENCLAW_STATE_DIR", "PATH", "PYTHONPATH", "TZ"],
            "cold-retry SDK actual process request/argv/environment changed")
    observed = json.loads(dispatch["stdout"])
    require(_same(observed, dispatch["observation"]) and set(observed) == {"result", "raw"}
            and _same(observed["result"], result), "cold-retry SDK stdout lost whole actual public/raw output")
    raw = observed["raw"]
    require(raw["pid"] == dispatch["pid"] and raw["ppid"] == dispatch["coordinatorPid"]
            and raw["fixtureBase"] == request["directory"]
            and raw["process"]["executable"] == dispatch["argv"][0]
            and raw["process"]["cwd"] == raw["implementationRoot"]
            and set(raw["process"]["environmentKeys"]) in (set(dispatch["environmentKeys"]), set(dispatch["environmentKeys"]) | {"LC_CTYPE"})
            and int(dispatch["startedAtNs"]) < int(raw["events"][0]["atNs"])
            <= int(raw["events"][-1]["atNs"]) < int(dispatch["finishedAtNs"]),
            "cold-retry SDK actual child PID/directory/environment/chronology was reassigned")
    return _raw(case, raw, result, native=False)


def validate_result(case, result):
    try:
        return _validate_result(case, result)
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration, json.JSONDecodeError, OSError) as error:
        raise ValueError("cold-retry actual common public result is structurally incomplete") from error


def validate_capture(case, capture, result, *, native, approved_node=None):
    validate_result(case, result)
    try:
        return (_raw(case, capture, result, native=True, approved_node=approved_node)
                if native else _sdk(case, capture, result))
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration, json.JSONDecodeError, OSError) as error:
        raise ValueError(("Native" if native else "SDK") + " cold-retry evidence is structurally incomplete") from error


def validate_pair(case, native_raw, sdk_raw, native_result, sdk_result, *, approved_node=None):
    """Authenticate both actual captures; a genuine difference remains measurable."""
    validate_capture(case, native_raw, native_result, native=True, approved_node=approved_node)
    validate_capture(case, sdk_raw, sdk_result, native=False)
    return True


def replay_case(case, directory, *, approved_node=None):
    directory = Path(directory)
    native = json.loads((directory / "stdout.json").read_text())["result"]
    sdk = json.loads((directory / "sdk-output.json").read_text())
    originals = json.loads((directory / "evidence/native-raw.json").read_text())
    copies = json.loads((directory / "evidence/python-raw.json").read_text())
    require(len(originals) == len(copies) == 1, "cold-retry replay requires one actual capture per engine")
    validate_pair(case, originals[0], copies[0], native, sdk, approved_node=approved_node)
    return {"validated": True, "publicMatch": _same(native, sdk), "nativeSnapshots": 1,
            "sdkSnapshots": 1, "acceptancePointsAwarded": 0}

