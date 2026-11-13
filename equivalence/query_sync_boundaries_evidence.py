"""Independent custody for the closed query-sync boundary family.

Actual policy differences, including missing retries and different original
exception classes, are valid observations.  The harness compares the entire
common result only after this module authenticates each side independently.
"""
from __future__ import annotations

import ast
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from equivalence.host_turn_barrier_evidence import _same, require
from equivalence.query_sync_boundaries import validate_case
from equivalence.query_sync_cold_retry_evidence import (
    _entry_identity, _fault_syscall_entries, _owned_file, _sql,
)
from equivalence.query_sync_outcomes_evidence import (
    NATIVE_METHODS, _finite, _interval, _one,
    V8_DECODER, _private_markers, _published_sources, _returned_hits, _source_entries,
)
from equivalence.query_sync_boundaries_bindings import (
    COMPILED_HASHES, REQUIRED_MAIN_ARTIFACTS, REQUIRED_WORKER_ARTIFACTS,
)
from equivalence.release_runtime import MANIFEST_SHA256, REFERENCE_COMMIT, VERSION, validate_release_sources

ROOT = Path(__file__).resolve().parents[1]
COUNTERS = {"searchRequests", "managerSearches", "syncRequests", "bootstrapRequests",
            "producerAttempts", "committedGenerations"}


@lru_cache(maxsize=2048)
def _sealed_file_digest(filename, device, inode, size, mtime_ns, ctime_ns):
    return hashlib.sha256(Path(filename).read_bytes()).hexdigest()


def _file_digest(filename):
    path = Path(filename)
    info = path.stat()
    return _sealed_file_digest(str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


_WIRE_CACHE = {}


def _decode_v8(authority, wires):
    # The executable is selected and authenticated by _native_process first.
    # Cache data decoding, never a captured executable or an unchecked file.
    binary = Path(authority["execPath"])
    digest = _file_digest(binary)
    require(digest == authority["sha256"], "trusted original V8 decoder binary changed")
    decoder_digest = hashlib.sha256(V8_DECODER.encode()).hexdigest()
    missing = list(dict.fromkeys(wire for wire in wires if (digest, decoder_digest, wire) not in _WIRE_CACHE))
    if missing:
        finished = subprocess.run([str(binary), "--input-type=module", "-e", V8_DECODER],
            input=json.dumps(missing), capture_output=True, text=True, timeout=30,
            cwd="/tmp", env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"}, check=False)
        require(finished.returncode == 0 and not finished.stderr, "independent original V8 decode failed")
        values = json.loads(finished.stdout)
        require(isinstance(values, list) and len(values) == len(missing), "independent V8 decode dropped original bytes")
        for wire, value in zip(missing, values, strict=True):
            _WIRE_CACHE[digest, decoder_digest, wire] = value
    return [_WIRE_CACHE[digest, decoder_digest, wire] for wire in wires]


def _sdk_source_path(recorded, approved_sdk_root):
    """Read historical bytes only beneath an independently selected source seal."""
    relative = Path(recorded).relative_to(ROOT)
    require(relative.parts and relative.parts[0] == "memory_core" and ".." not in relative.parts,
            "original SDK module path escaped its actual imported source namespace")
    root = Path(approved_sdk_root or os.environ.get("MEMORY_QUERY_SYNC_BOUNDARIES_SDK_SOURCE_ROOT", ROOT)).resolve(strict=True)
    path = root / relative
    require(path.is_file() and not path.is_symlink() and path.resolve() == path,
            "trusted SDK source seal is incomplete or aliased")
    return path


def _sdk_bindings(raw, approved_sdk_root):
    bindings = raw["implementationBindings"]
    required = {"memory_core.host.managed_index", "memory_core.index.sqlite_store",
                "memory_core.index.publication", "memory_core.tools.search_factory", "memory_core.tools.memory_search"}
    require(isinstance(bindings, list) and required <= {row["module"] for row in bindings}
            and len({row["module"] for row in bindings}) == len(bindings),
            "actual SDK imported implementation modules were omitted")
    for row in bindings:
        path = _sdk_source_path(row["path"], approved_sdk_root)
        require(_file_digest(path) == row["sha256"],
                "actual SDK capture differs from independently selected production bytes")
    identity = raw["sourceIdentity"]["beforeImports"]
    require(identity["root"] == str(ROOT), "SDK source inventory borrowed another imported tree")
    digest = hashlib.sha256()
    expected = []
    source_root = _sdk_source_path(ROOT / "memory_core/__init__.py", approved_sdk_root).parent.parent
    for path in sorted((source_root / "memory_core").rglob("*.py")):
        require(not path.is_symlink(), "SDK source inventory contains an alias")
        relative, data = path.relative_to(source_root).as_posix(), path.read_bytes()
        digest.update(relative.encode() + b"\0" + data + b"\0")
        expected.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    require(identity["sourceFiles"] == len(expected) and identity["sourceSha256"] == digest.hexdigest()
            and _same(identity["files"], expected), "actual SDK complete source inventory differs from the trusted source seal")


def _sdk_tool_contexts(case, raw, events, approved_sdk_root):
    observation = raw["toolContextObservation"]
    require(observation["mechanism"] == "original-SDK-code-and-source-context-identity"
            and observation["activeQueryFallback"] is observation["productionContextModified"] is False,
            "SDK query cause was guessed or production context was replaced")
    filename = ROOT / "memory_core/tools/memory_search.py"
    source = _sdk_source_path(filename, approved_sdk_root)
    definitions = {}
    def visit(node, parent=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = parent + child.name
                definitions[name] = child.lineno
                visit(child, name + ".<locals>.")
            else:
                visit(child, parent)
    visit(ast.parse(source.read_text()))
    names = {"execute_memory_search_tool", "_run_memory_search_tool",
             "_run_memory_search_tool.<locals>.search_memory_once",
             "_run_memory_search_tool.<locals>.search_memory_worker"}
    codes = {row["qualname"]: row for row in observation["codes"]}
    require(set(codes) == names and len(codes) == len(observation["codes"]), "SDK original query code anchors were removed or added")
    for name, row in codes.items():
        require(row["file"] == str(filename) and row["firstLine"] == definitions[name]
                and row["sourceSha256"] == _file_digest(source), "SDK original query code anchor changed")
    scopes = raw["toolContextScopes"]
    require(len(scopes) == sum(row["event"] == "original-sdk-tool-context-enter" for row in events.values())
            == sum(row["event"] == "original-sdk-tool-context-return" for row in events.values()),
            "SDK original query context entries/returns were removed or added")
    for label, tool in raw["toolCalls"].items():
        public = _one(scopes, lambda row: row["label"] == label and row["kind"] == "public-entry",
                      "actual SDK public entry context missing")
        owner = raw["owners"][tool["ownerId"]]
        for scope in [row for row in scopes if row["label"] == label]:
            start, end = _interval(scope, events, "original-sdk-tool-context-enter", "original-sdk-tool-context-return", "SDK original context interval detached")
            code = codes[scope["codeQualname"]]
            require(tool["enterSeq"] < start < end < tool["returnSeq"]
                    and scope["ownerId"] == public["ownerId"] == tool["ownerId"]
                    and scope["storeObjectId"] == public["storeObjectId"] == owner["objectId"]
                    and scope["contextObjectId"] == public["contextObjectId"]
                    and scope["codeFile"] == code["file"] and scope["codeFirstLine"] == code["firstLine"]
                    and events[start]["threadId"] == events[end]["threadId"] == scope["threadId"]
                    and events[start]["label"] == events[end]["label"] == label,
                    "SDK query worker lost the exact original public context/store/code/thread identity")
    methods = raw["methodCalls"] + raw["statusCalls"] + raw["originalSearchCalls"] + raw["readAdmissions"]
    for call in methods:
        label = call.get("activeTool")
        if label is None:
            continue
        require(any(row["label"] == label and row["ownerId"] == call["ownerId"]
                    and row["threadId"] == call["threadId"]
                    and row["enterSeq"] < call["enterSeq"] < call["returnSeq"] < row["returnSeq"] for row in scopes),
                "SDK original tool-labelled method has no actual source context on its original thread")


def _outcome(value):
    require(isinstance(value, dict) and set(value) == {"status", "isTypedConflict"}
            and value["status"] in {"fulfilled", "rejected"}
            and type(value["isTypedConflict"]) is bool
            and (value["status"] == "rejected" or value["isTypedConflict"] is False),
            "query-sync boundaries original semantic outcome is incomplete or relabelled")


def _expected_sources(case, *, initial):
    value = case["input"]
    sources = {path: (text, value["initialSourceMtimeMs"]) for path, text in value["initialFiles"].items()}
    mutation = value.get("sourceMutation")
    paths = set(sources)
    if mutation:
        paths.add(mutation["path"])
        if not initial:
            if mutation["kind"] in {"create", "replace"}:
                sources[mutation["path"]] = mutation["text"], mutation["mtimeMs"]
            elif mutation["kind"] == "delete":
                sources.pop(mutation["path"], None)
    return sorted(paths), sources


def validate_result(case, result):
    validate_case(case)
    value = case["input"]
    require(isinstance(result, dict) and set(result) == {
                "provider", "searches", "syncs", "dispatches", "producerOutcomes", "sources"}
            and result["provider"] == "none" and _finite(result)
            and set(result["searches"]) == set(value["queries"])
            and set(result["syncs"]) == set(value["syncs"])
            and set(result["dispatches"]) == COUNTERS
            and all(type(count) is int and count >= 0 for count in result["dispatches"].values()),
            "query-sync boundaries whole common wire or original request labels changed")
    labels = {"initial"} | {step["label"] for step in value["steps"]
                          if step["operation"] == "read-physical-sql-and-source-state"}
    require(set(result["sources"]) == labels, "query-sync boundaries source stage omitted or added")
    for label, sources in result["sources"].items():
        paths, expected = _expected_sources(case, initial=label == "initial")
        _source_entries(sources, paths, expected)
    for details in result["searches"].values():
        require(isinstance(details, dict) and isinstance(details.get("results"), list),
                "query-sync boundaries complete original search details are absent")
    for outcome in [*result["syncs"].values(), *result["producerOutcomes"]]:
        _outcome(outcome)
    require(len(result["producerOutcomes"]) == result["dispatches"]["producerAttempts"],
            "query-sync boundaries producer outcomes were detached from actual dispatches")
    return True


def _clock(raw, *, native):
    rows = raw["events"]
    require(isinstance(rows, list) and rows and all(type(row["sequence"]) is int
            and isinstance(row["atNs"], str) and row["atNs"].isdigit() for row in rows),
            "query-sync boundaries original lifecycle clock is absent")
    events = {row["sequence"]: row for row in rows}
    require(len(events) == len(rows) and set(events) == set(range(1, len(rows) + 1)),
            "query-sync boundaries original event allocations were duplicated or removed")
    for thread in {row.get("threadId", 0) for row in rows}:
        selected = sorted((row for row in rows if row.get("threadId", 0) == thread),
                          key=lambda row: row["sequence"])
        times = [int(row["atNs"]) for row in selected]
        require(times == sorted(times), "query-sync boundaries per-thread chronology was reordered")
    # Concurrent SDK observations have no added mutex: timestamp/append order
    # across different original threads is not asserted to be globally atomic.
    return events


def _source_custody(case, raw, result, events, *, native):
    require(set(result["sources"]) <= set(raw["sourceStages"])
            and len(raw["sourceStages"]) == sum(row["event"] == "source-read-enter" for row in events.values())
            == sum(row["event"] == "source-read-return" for row in events.values()),
            "actual source observations were removed or added")
    for label, stage in raw["sourceStages"].items():
        common = stage["common"]
        paths, expected = _expected_sources(case, initial=label == "initial")
        _source_entries(common, paths, expected)
        start, end = _interval(stage, events, "source-read-enter", "source-read-return", "source stage detached")
        require(events[start]["label"] == events[end]["label"] == label
                and (label not in result["sources"] or _same(common, result["sources"][label])),
                "query-sync boundaries complete source stage changed")
        records = stage["records" if native else "entries"]
        require(len(records) == len(common), "query-sync boundaries source byte/stat records omitted")
        for record, source in zip(records, common, strict=True):
            path = str(Path(raw["fixtureBase"]) / "workspace" / source["path"])
            require(record["absolutePath"] == path and record["path"] == source["path"]
                    and record["kind"] == source["kind"], "query-sync boundaries source path was borrowed")
            if source["kind"] == "missing":
                require(record["error"].get("code") == "ENOENT" if native else record["error"].get("errno") == 2,
                        "query-sync boundaries absent source lacks an actual OS receipt")
                continue
            require(all(_same(record[key], source[key]) for key in ("text", "hex", "sha256")),
                    "query-sync boundaries source bytes/hash were detached")
            if native:
                stat = record["stat"]
                require(stat["nlink"]["value"] == "1" and int(stat["size"]["value"]) == source["size"]
                        and int(stat["mtimeNs"]["value"]) / 1_000_000 == source["mtimeMs"],
                        "query-sync boundaries Native source stat was replaced")
            else:
                before, after = record["statBefore"], record["statAfter"]
                require(all(before[key] == after[key] for key in ("st_dev", "st_ino", "st_size", "st_mtime_ns"))
                        and after["st_nlink"] == 1 and after["st_size"] == source["size"]
                        and after["st_mtime_ns"] / 1_000_000 == source["mtimeMs"]
                        and _owned_file(record["byteFile"], raw["fixtureBase"]).read_bytes().hex() == source["hex"],
                        "query-sync boundaries SDK source bytes/stat were replaced")
    for snapshot in raw["snapshots"]:
        _interval(snapshot, events, "physical-sql-read-enter", "physical-sql-read-return", "actual SQL snapshot detached")
        sealed = json.loads(snapshot["serializedJSON"])
        checked = snapshot
        if native and snapshot.get("exists") is False:
            original, final = sealed["error"], snapshot["error"]
            require(original["code"] == final["code"] == "ENOENT"
                    and original["stack"] is None and isinstance(final["stack"], str)
                    and original["stackSerialization"] == final["stackSerialization"] == "original-teardown"
                    and _same({key: item for key, item in original.items() if key != "stack"},
                              {key: item for key, item in final.items() if key != "stack"}),
                    "initial ENOENT receipt changed beyond its declared deferred stack enrichment")
            # The immutable JSON carrier remains the original observation.
            # Only the separately retained, later formatted stack is enriched.
            checked = {**snapshot, "error": original}
        _sql(checked, raw, native=native, missing=snapshot["label"].startswith("before-"))
        owner_paths = {owner["settings"]["store"]["databasePath"] if native else owner["indexPath"]
                       for owner in raw["owners"].values()}
        require(snapshot["dbPath"] in owner_paths and len(owner_paths) == 1,
                "physical SQL snapshot borrowed another original index database")
        if not (snapshot.get("exists") is False if native else snapshot.get("absent") is True):
            _generation(case, snapshot, native=native)


def _generation(case, snapshot, *, native, output=None):
    tables = snapshot["tables"]
    source_table = "memory_index_sources" if native else "memory_core_index_sources"
    chunk_table = "memory_index_chunks" if native else "chunks"
    variants = {}
    for initial in (True, False):
        for path, value in _expected_sources(case, initial=initial)[1].items():
            variants.setdefault(path, []).append(value)
    expected = {}
    for source in tables[source_table]:
        matches = [value for value in variants.get(source["path"], [])
                   if hashlib.sha256(value[0].encode()).hexdigest() == source["hash"]
                   and value[1] == source["mtime"]]
        require(matches, "physical indexed source is detached from every actual declared source generation")
        expected[source["path"]] = matches[0]
    if expected:
        _published_sources(snapshot, expected, native=native)
    else:
        require(all(not tables[name] for name in (chunk_table, "memory_index_chunk_provenance",
                    "memory_index_chunk_recall_metadata", "memory_index_chunks_fts" if native else "chunks_fts",
                    "memory_index_paths_fts" if native else "paths_fts"))
                and (native or not tables["memory_index_chunk_details"]),
                "empty actual source generation retained unrelated chunks/provenance/recall/FTS rows")
    if output is not None:
        for hit in output["results"]:
            chunk = _one(tables[chunk_table], lambda row: row["path"] == hit["path"]
                and row["source"] == hit["source"] and row["start_line"] == hit["startLine"]
                and row["end_line"] == hit["endLine"], "actual pinned SQL chunk for public hit missing")
            provenance = _one(tables["memory_index_chunk_provenance"], lambda row: row["chunk_id"] == chunk["id"],
                              "actual pinned public provenance missing")
            expected_provenance = {"originClass": provenance["origin_class"], "sessionKind": provenance["session_kind"],
                                   "observedAt": provenance["observed_at"]}
            if provenance["supersedes_key"] is not None:
                expected_provenance["supersedesKey"] = provenance["supersedes_key"]
            require(hit["snippet"].strip() in chunk["text"] and _same(hit.get("provenance"), expected_provenance),
                    "complete public hit text/provenance differs from its actual pinned SQL generation")


def _read_generations(case, raw, result, events, *, native):
    if not native:
        for read in raw["readAdmissions"]:
            pinned = read["pinnedSnapshot"]
            _sql(pinned, raw, native=False)
            require(pinned["ownerId"] == read["ownerId"] and pinned["activeTool"] == read["activeTool"]
                    and pinned["dbPath"] == raw["owners"][read["ownerId"]]["indexPath"]
                    and pinned["inTransactionBefore"] is pinned["inTransactionAfter"] is True
                    and [row for row in pinned["databases"] if row[1] == "main"] == [[0, "main", pinned["dbPath"]]]
                    and _one(pinned["tables"]["memory_core_index_sync"], lambda row: row["id"] == 1,
                             "actual pinned SDK revision omitted")["revision"] == pinned["readRevision"],
                    "SDK physical reader lost its actual owner/database/transaction/revision")
            search = _one(raw["originalSearchCalls"], lambda row: row["ownerId"] == read["ownerId"]
                and row["threadId"] == read["threadId"] and row["enterSeq"] < read["enterSeq"] < read["returnSeq"] < row["returnSeq"],
                "actual SDK pinned read lies outside its original search")
            admission = _one(read["lifecycleAfter"]["sessionReadAdmissions"],
                lambda row: row["operationId"] == read["parentOperationId"], "actual SDK reader lifecycle admission omitted")
            operation = _one(search["lifecycleAfter"]["operations"], lambda row: row["id"] == read["parentOperationId"],
                             "actual SDK original search operation omitted")
            require(admission["revision"] == pinned["readRevision"] and admission["threadId"] == read["threadId"]
                    and operation["name"] == "search" and operation["state"] in {"completed", "failed"}
                    and operation["query"] == case["input"]["queries"][read["activeTool"]]["query"]
                    and operation["threadId"] == search["threadId"] == read["threadId"],
                    "SDK pinned physical read lost actual original operation/thread/revision custody")
            _generation(case, pinned, native=False,
                output=result["searches"][read["activeTool"]] if "error" not in search else None)
        return
    for lease in raw["leaseCalls"]:
        _interval(lease, events, "original-coordination-enter", "original-coordination-return", "original read/write lease interval detached")
    for preparation in [row for row in raw["methodCalls"] if row["method"] == "prepareKeywordSearch" and "error" not in row]:
        db = raw["owners"][preparation["ownerId"]]["settings"]["store"]["databasePath"]
        pool = _one(raw["poolCalls"], lambda row: row["args"][0].get("kind") == "keyword"
            and preparation["enterSeq"] < row["enterSeq"] < row["returnSeq"] < preparation["returnSeq"],
            "actual original keyword worker dispatch omitted")
        job = pool["args"][0]
        require(job["databasePath"] == db and job["agentId"] == case["input"]["identity"]["agentId"]
                and job["query"]["body"]["query"] == preparation["args"][0]
                and job["query"]["body"]["sourceFilter"]["params"] == ["memory"] and job["includeIndexState"] is True,
                "Native original keyword worker read another source/query/database")
        dispatch = _one(raw["workerDispatches"], lambda row: pool["enterSeq"] < row["enterSeq"] < row["returnSeq"] < pool["returnSeq"]
                        and _same(row["message"].get("input"), job), "actual original keyword postMessage omitted")
        reply = _one(raw["workerMessages"], lambda row: row["workerId"] == dispatch["workerId"]
            and row["message"].get("taskId") == dispatch["message"]["taskId"], "actual original keyword result omitted")
        returned = json.loads(preparation["nativeSerializedJSON"])
        require(dispatch["returnSeq"] < reply["sequence"] < pool["returnSeq"]
                and reply["message"]["status"] == "ok" and _same(reply["message"]["value"], pool["result"])
                and _same(pool["result"]["body"], returned["keyword"]["body"])
                and _same(pool["result"]["indexState"], returned["indexState"])
                and _same(preparation["result"]["indexState"], returned["indexState"]),
                "Native keyword result/index-state differs from the actual original worker reply")
        candidates = []
        for begin in raw["leaseCalls"]:
            if (begin["location"] != db + ".generation-lock.sqlite" or begin["method"] != "exec"
                    or begin["args"] != ["BEGIN"] or "error" in begin
                    or begin["activeTool"] != preparation["activeTool"]):
                continue
            own = [row for row in raw["leaseCalls"] if row["databaseRef"] == begin["databaseRef"]]
            pin = [row for row in own if row["method"] == "statement.get" and "error" not in row]
            rollback = [row for row in own if row["method"] == "exec" and row["args"] == ["ROLLBACK"]]
            close = [row for row in own if row["method"] == "close"]
            if len(pin) == len(rollback) == len(close) == 1 and begin["returnSeq"] < pin[0]["enterSeq"] < pin[0]["returnSeq"] < preparation["enterSeq"] < preparation["returnSeq"] < rollback[0]["enterSeq"] < close[0]["enterSeq"]:
                candidates.append(begin)
                require(begin["transactionBefore"] is False and begin["transactionAfter"] is True
                        and pin[0]["transactionBefore"] is pin[0]["transactionAfter"] is True
                        and close[0]["openAfter"] is False
                        and "tryAcquireMemorySqliteLease" in begin["originalCallerStack"]
                        and "/dist/manager-vector-warning-DcyxxT5h.mjs:" in begin["originalCallerStack"],
                        "Native keyword generation lease was not actually pinned/held/released by the original reader")
        require(len(candidates) == 1, "Native keyword read lacks its single actual held original generation lease")
    for label, output in result["searches"].items():
        if not output["results"]:
            continue
        preparations = [row for row in raw["methodCalls"] if row["method"] == "prepareKeywordSearch"
                        and row["activeTool"] == label and "error" not in row]
        require(preparations, "Native public hits lack their original pinned keyword preparation")
        prepared = json.loads(max(preparations, key=lambda row: row["returnSeq"])["nativeSerializedJSON"])["keyword"]
        for hit in output["results"]:
            original = _one(prepared["body"]["rows"] + prepared["path"]["rows"],
                lambda row: all(row[key] == hit[key] for key in ("path", "source", "startLine", "endLine")),
                "Native public hit is absent from its actual pinned keyword result")
            require(hit["snippet"].strip() in original["snippet"], "Native public snippet was detached from its pinned original worker hit")


def _steps(case, raw, events, *, native):
    rows = raw["executedSteps" if native else "schedule"]
    require(len(rows) == len(case["input"]["steps"]), "query-sync boundaries frozen step omitted or added")
    for number, (step, row) in enumerate(zip(case["input"]["steps"], rows, strict=True)):
        require(_same(row["step" if native else "specification"], step), "query-sync boundaries executed another frozen step")
        start, end = _interval(row, events, "declared-step-enter", "declared-step-return", "ordered fixture step detached")
        require(events[start].get("index", events[start].get("number")) == number,
                "query-sync boundaries step array order was replaced by JSON object order")
        if number:
            require(rows[number - 1]["returnSeq"] < start, "query-sync boundaries frozen step schedule overlaps")


def _tools(case, raw, result, events, *, native):
    require(set(raw["toolCalls"]) == set(case["input"]["queries"]),
            "query-sync boundaries real public tool call omitted or added")
    for label, call in raw["toolCalls"].items():
        start, end = _interval(call, events, "actual-tool-enter", "actual-tool-return", "public tool interval detached")
        require("error" not in call and events[start]["label"] == events[end]["label"] == label
                and _same(call["args"], case["input"]["queries"][label]),
                "query-sync boundaries real public input or result changed")
        envelope = call["envelope"]
        require(isinstance(envelope["content"], list) and envelope["content"]
                and envelope["content"][0]["type"] == "text"
                and _same(json.loads(envelope["content"][0]["text"]), envelope["details"])
                and _same(envelope["details"], result["searches"][label]),
                "query-sync boundaries entire original public envelope/text/details was projected")
        if native:
            require(_same(json.loads(call["nativeEnvelopeSerializedJSON"]), envelope)
                    and set(call["nativeDetailsOwnKeys"]) == set(envelope["details"]) | set(call["nativeDetailsUndefinedOwnKeys"])
                    and set(call["nativeDetailsUndefinedOwnKeys"]).isdisjoint(envelope["details"]),
                    "query-sync boundaries Native original own-field custody was changed")
            gets = [row for row in raw["originalGetCalls"]
                    if row["requestedPurpose"] == "default"
                    and start < row["enterSeq"] < row["returnSeq"] < end]
            require(gets and all(row["receiverIsOriginalClass"] is True
                    and row["originalReturnPromisePreserved"] is True and row["ownerId"] in raw["owners"]
                    and row["requestedPurpose"] == "default" for row in gets)
                    and len({row["ownerId"] for row in gets}) == 1,
                    "actual Native public tool lost its original manager acquisition/owner")
        else:
            carrier = call["envelopeFile"]
            data = _owned_file(carrier["path"], raw["fixtureBase"]).read_bytes()
            require(len(data) == carrier["bytes"] and hashlib.sha256(data).hexdigest() == carrier["sha256"]
                    and _same(json.loads(data), envelope), "query-sync boundaries early original tool carrier changed")
            binding = _one(raw["toolBindings"], lambda row: row["label"] == label, "original public factory binding missing")
            require(binding["ownerId"] == call["ownerId"] and binding["storeIsExactObservedOwner"] is True
                    and binding["configIsExactOwnerConfig"] is True and binding["contextStatusIsNone"] is True
                    and binding["refreshStoreIsNone"] is True
                    and binding["storeObjectId"] == raw["owners"][call["ownerId"]]["objectId"],
                    "query-sync boundaries public factory replaced its owner or installed a refresh")
        searches = [row for row in raw["originalSearchCalls"] if row["activeTool"] == label
                    and start < row["enterSeq"] < row["returnSeq"] < end]
        for search in searches:
            require(search["receiverIsExactObservedOwner"] is True
                    and (search["query"] if native else search["arguments"]["0"])
                    == case["input"]["queries"][label]["query"],
                    "query-sync boundaries public search dispatched to another receiver/query")
            if native:
                require(search["ownerId"] == gets[-1]["ownerId"],
                        "Native public search borrowed a manager outside its actual tool acquisition")
        if searches and "error" not in searches[-1]:
            _returned_hits(searches[-1], result["searches"][label], native=native)
    require(len(raw["toolCalls"]) == sum(row["event"] == "actual-tool-enter" for row in events.values())
            == sum(row["event"] == "actual-tool-return" for row in events.values()),
            "query-sync boundaries original public tool events were dropped")
    require(set(raw["syncCalls"]) == set(case["input"]["syncs"]),
            "query-sync boundaries original explicit synchronization omitted or added")
    for label, call in raw["syncCalls"].items():
        _interval(call, events, "actual-sync-request-enter" if native else "actual-sync-enter",
                  "actual-sync-request-return" if native else "actual-sync-return", "original sync request detached")
        require(_same(call["params"], case["input"]["syncs"][label]),
                "query-sync boundaries original force/reason parameters changed")
        actual = ({"status": call["state"], "isTypedConflict": call.get("isTypedConflict", False)}
                  if native else call["outcome"])
        _outcome(actual)
        require(_same(actual, result["syncs"][label]) and (actual["status"] == "rejected") == ("error" in call),
                "query-sync boundaries original sync return/error was relabelled")
        original = _one(raw["methodCalls"], lambda row: row["ownerId"] == call["ownerId"]
            and row["method"] == ("sync" if native else "reindex")
            and call["enterSeq"] < row["enterSeq"] < row["returnSeq"] < call["returnSeq"]
            and ((row.get("operationContext") or {}).get("label") == label if native else row["activeSync"] == label),
            "actual explicit force request lost its original method dispatch")
        require(_same(original["args"][0], call["params"]) if native
                else original["options"]["force"] is call["params"]["force"],
                "actual explicit sync changed force/reason arguments on its original dispatch")
        if native:
            require(original["returnedPromiseRef"] == call["returnedPromiseRef"],
                    "explicit Native sync replaced the actual original returned promise")
        if "error" in call:
            require(original["errorRef"] == call["errorRef"], "explicit sync replaced its actual propagated original error")
        else:
            require(_same(original["result" if native else "returned"], call["result" if native else "returned"]),
                    "explicit sync replaced its actual original completion value")


def _native_counts(raw, result, events):
    require(all(sum(row["event"] == f"original-{method}-{suffix}" for row in events.values())
                == sum(row["method"] == method for row in raw["methodCalls"])
                for method in NATIVE_METHODS for suffix in ("enter", "return")),
            "actual original Native method events were removed or added")
    for bucket, method in (("statusCalls", "status"), ("originalSearchCalls", "search"),
                           ("backgroundCalls", "syncPublishedIndexInBackground")):
        require(_same(raw[bucket], [row for row in raw["methodCalls"] if row["method"] == method]),
                "Native specialized method receipts differ from complete original calls")
    require(len(raw["wholeJobs"]) == sum(row["event"] == "original-sync-ledger-enter" for row in events.values())
            == sum(row["event"] in {"original-sync-ledger-settled", "original-sync-ledger-threw"} for row in events.values()),
            "Native actual original whole-producer ledger entries/settlements were removed or added")
    require(len(raw["publicationCalls"]) == sum(row["event"] == "original-publication-enter" for row in events.values())
            == sum(row["event"] in {"original-publication-settled", "original-publication-threw"} for row in events.values()),
            "Native producer counts lost actual original publication entries/settlements")
    window = raw["comparableWindow"]
    primary = window["primaryOwnerId"]
    acquisition = _one(raw["facadeCalls"], lambda row: row["ownerId"] == primary, "first foreground acquisition missing")
    close = _one(raw["methodCalls"], lambda row: row["id"] == window["closeCallId"], "first foreground close missing")
    require(close["method"] == "close" and close["ownerId"] == primary and "error" not in close
            and window["endSeq"] == close["returnSeq"]
            and not any(row["method"] == "close" and row["ownerId"] == primary and row["enterSeq"] < close["enterSeq"]
                        for row in raw["methodCalls"]), "query-sync boundaries first lifetime cutoff changed")
    owners = {primary}
    for _ in raw["owners"]:
        owners |= {ref for ref, row in raw["owners"].items() if row.get("maintenanceSourceOwnerId") in owners}
    require(set(window["ownerIds"]) == owners and primary in raw["owners"],
            "query-sync boundaries borrowed or omitted original maintenance ancestry")
    def selected(row):
        return row.get("ownerId") in owners and acquisition["returnSeq"] < row["enterSeq"] < close["returnSeq"]
    methods = [row for row in raw["methodCalls"] if selected(row)]
    for call in raw["methodCalls"]:
        _interval(call, events, f'original-{call["method"]}-enter', f'original-{call["method"]}-return', "original Native method detached")
        require(call["method"] in NATIVE_METHODS and call["ownerId"] in raw["owners"]
                and call["receiverIsExactObservedOwner"] is True,
                "query-sync boundaries original Native method receiver changed")
    jobs = sorted((row for row in raw["wholeJobs"] if row["active"] is True and selected(row)), key=lambda row: row["enterSeq"])
    require(window["wholeJobIds"] == [row["id"] for row in jobs],
            "query-sync boundaries whole producer admission list was forged")
    commits = set()
    for job in jobs:
        _interval(job, events, "original-sync-ledger-enter", "original-sync-ledger-settled", "actual producer interval detached")
        require(job["active"] is True and job["originalOperationRef"]
                and job["originalReturnPromisePreserved"] is True and job["returnedPromiseRef"]
                and job["stateBefore"]["syncOutcomesRef"] == job["ledgerRef"]
                and job["returnSeq"] < close["returnSeq"],
                "query-sync boundaries producer was replaced or left unsettled at close")
        for call in raw["publicationCalls"]:
            if call.get("wholeJobId") != job["id"]:
                continue
            require(job["enterSeq"] < call["enterSeq"] < call["returnSeq"] < job["returnSeq"]
                    and call["ownerId"] == job["ownerId"]
                    and (call.get("operationContext") or {}).get("kind") != "revision-rival",
                    "query-sync boundaries rival/private publication was counted as a primary producer")
            committed = ("error" not in call and (call["method"] == "publishShadow"
                or call["method"] == "deleteSource" and call["result"] is True
                or call["method"] == "replaceSource" and isinstance(call.get("result"), dict)
                and call["result"].get("databaseRevision", -1) > call["result"].get("beforeRevision", -1)))
            if committed:
                commits.add(job["id"])
                require(call["id"] in job["publicationCommitCallIds"],
                        "query-sync boundaries actual visible publication was omitted from its generation")
        require((job.get("committedGeneration") is True) == (job["id"] in commits),
                "query-sync boundaries committed-generation count was asserted without actual publication")
    counts = {"searchRequests": sum(acquisition["returnSeq"] < row["enterSeq"] < row["returnSeq"] < close["returnSeq"]
                                   for row in raw["toolCalls"].values()),
        "managerSearches": sum(row["method"] == "search" for row in methods),
        "syncRequests": sum(row["method"] == "syncAdmitted" for row in methods),
        "bootstrapRequests": sum(row["method"] == "syncAdmitted" and row["args"][0].get("reason") == "search-bootstrap" for row in methods),
        "producerAttempts": len(jobs), "committedGenerations": len(commits)}
    outcomes = [{"status": job["state"], "isTypedConflict": job["isTypedConflict"]} for job in jobs]
    require(_same(counts, result["dispatches"]) and _same(outcomes, result["producerOutcomes"]),
            "query-sync boundaries public counters/outcomes differ from original true producer dispatches")
    return primary, close, jobs


def _native_publication_wires(raw, events):
    require(len(raw["publicationCalls"]) == sum(row["event"] == "original-publication-enter" for row in events.values())
            == sum(row["event"] in {"original-publication-settled", "original-publication-threw"} for row in events.values()),
            "actual original Native publication entries/settlements were removed or added")
    for call in raw["publicationCalls"]:
        start, end = _interval(call, events, "original-publication-enter", "original-publication-settled", "original publication interval detached")
        require(events[start]["ownerId"] == events[end]["ownerId"] == call["ownerId"]
                and events[start]["method"] == events[end]["method"] == call["method"],
                "actual original Native publication owner/method was relabelled")
        commands = []
        for dispatch in raw["workerDispatches"]:
            if not (start < dispatch["enterSeq"] < dispatch["returnSeq"] < end):
                continue
            domain = dispatch["decodedSerialized"].get("input", {}).get("value", {})
            if domain.get("type") != "database.domain.execute":
                continue
            command = domain["input"]["command"]
            reply = _one(raw["workerMessages"], lambda row: row["workerId"] == dispatch["workerId"]
                and row["message"].get("id") == dispatch["message"]["id"], "original publication worker reply omitted")
            require(dispatch["returnSeq"] < reply["sequence"] < end, "original publication settled before its actual worker reply")
            commands.append((command, reply["decodedSerialized"]["value"]["value"]))
        typ = {"publishShadow": "database.publish", "replaceSource": "source.replace", "deleteSource": "source.delete"}[call["method"]]
        command, settled = _one(commands, lambda row: row[0]["type"] == typ,
                                "original visible publication has no independently decoded matching worker command")
        require(settled["ok"] is ("error" not in call), "actual publication worker error/success differs from original settlement")
        if "error" in call:
            require(all(settled["error"][key] == call["error"][key] for key in ("name", "message")),
                    "actual worker publication error was replaced on original propagation")
        else:
            require(_same(settled["value"], call["result"]), "original publication result differs from the decoded real commit reply")
        if call["method"] in {"publishShadow", "deleteSource"}:
            require(all(key in command["input"] and _same(value, command["input"][key])
                        for key, value in call["args"][0].items()),
                    "actual visible publication parameters differ from its independently decoded worker command")
        else:
            begin, _ = _one(commands, lambda row: row[0]["type"] == "stage.start", "actual source replacement stage omitted")
            original = call["args"][0]
            require(_same(begin["input"]["header"], {key: original[key] for key in ("entry", "model", "now", "vectorReady", "source")})
                    and begin["input"]["rows"] == len(original["chunks"])
                    and command["input"]["operation"] == begin["input"]["operation"],
                    "actual source replacement header/operation differs from original input")
        if call.get("wholeJobId"):
            job = _one(raw["wholeJobs"], lambda row: row["id"] == call["wholeJobId"], "actual publication lost its original producer")
            run = _one(raw["methodCalls"], lambda row: row["method"] == "runSync"
                and row["id"] == (call.get("operationContext") or {}).get("runSyncCallId"), "actual publication lost its original runSync cause")
            require(run["ownerId"] == job["ownerId"] == call["ownerId"]
                    and job["enterSeq"] < run["enterSeq"] < start < end < run["returnSeq"] < job["returnSeq"],
                    "actual visible publication borrowed another original producer/runSync")


def _sdk_counts(raw, result, events, *, approved_sdk_root=None):
    acquisition = raw["ownerAcquisitions"][0]
    primary = acquisition["ownerId"]
    close = raw["owners"][primary]["close"]
    _interval(close, events, "original-close-enter", "original-close-return", "original SDK close detached")
    require(close["closed"] is True and "error" not in close and close["lifecycle"]["activeOperations"] == 0
            and not any(close["lifecycle"][key] for key in ("operationJournalTruncated", "repairJournalTruncated")),
            "query-sync boundaries SDK actual close omitted admitted producer work")
    def selected(row):
        return row.get("ownerId") == primary and acquisition["returnSeq"] < row["enterSeq"] < row["returnSeq"] < close["returnSeq"]
    methods = raw["methodCalls"] + raw["originalSearchCalls"] + raw["statusCalls"] + raw["backgroundCalls"] + raw["publicationCalls"] + raw["readAdmissions"] + raw["publicationWrites"]
    require(len(methods) == sum(row["event"] == "original-method-enter" for row in events.values())
            == sum(row["event"] == "original-method-return" for row in events.values()),
            "actual original SDK method entries/returns were removed or added")
    for call in methods:
        _interval(call, events, "original-method-enter", "original-method-return", "original SDK method detached")
        require(call["receiverIsExactObservedOwner"] is True and call["ownerId"] in raw["owners"],
                "query-sync boundaries SDK original receiver was replaced")
    producers = sorted((row for row in raw["originalBaseCalls"] if selected(row)), key=lambda row: row["enterSeq"])
    meta = raw["baseCallObservation"]
    functions = {row["qualname"]: row for row in meta["functions"]}
    require(set(functions) == {"SQLiteMemoryStore.reindex", "SQLiteMemoryStore.reindex_sources"},
            "query-sync boundaries base profile did not observe original public producer methods")
    for row in functions.values():
        path = Path(row["file"])
        require(path == ROOT / "memory_core/index/sqlite_store.py"
                and _file_digest(_sdk_source_path(path, approved_sdk_root)) == row["sourceSha256"],
                "query-sync boundaries original base producer bytes changed")
    for call in raw["originalBaseCalls"]:
        _interval(call, events, "original-base-producer-enter", "original-base-producer-return", "original public base producer detached")
        require(call["qualname"] in functions and call["module"] == "memory_core.index.sqlite_store"
                and call["receiverIsExactObservedOwner"] is True and call["workspaceIsExactOwner"] is True
                and call["receiverObjectId"] == raw["owners"][call["ownerId"]]["objectId"],
                "query-sync boundaries original base dispatch was borrowed or counted from a private helper")
        _outcome(call["outcome"])
        rejected = call["returned"] is None
        require((call["outcome"]["status"] == "rejected") is rejected,
                "query-sync boundaries original producer exception was presented as completion")
        if rejected:
            require(call.get("exceptions") and call["outcome"]["isTypedConflict"] is call["exceptions"][-1]["isTypedConflict"],
                    "query-sync boundaries original producer exception classification was relabelled")
    commits = [row for row in raw["publicationCalls"] if selected(row)
               and row["baseCallId"] in {call["id"] for call in producers} and "error" not in row and "returned" in row]
    evidence = []
    for call in commits:
        statements = [row["sequence"] for row in raw["sqlStatements"] if row["baseCallId"] == call["baseCallId"]
                      and not row["fixtureAction"] and call["enterSeq"] < row["sequence"] < call["returnSeq"]
                      and row["statement"].strip().upper() == "COMMIT"]
        require(statements, "query-sync boundaries SDK publication return lacks an actual original COMMIT")
        evidence.append({"baseCallId": call["baseCallId"], "publicationCallId": call["id"], "actualCommitSequences": statements})
    generations = sorted({row["baseCallId"] for row in commits})
    repairs = [row for row in close["lifecycle"]["repairs"] if row["reason"] == "search-bootstrap"]
    derivation = {"primaryOwnerId": primary,
        "lifetime": {"acquireReturnSeq": acquisition["returnSeq"], "closeReturnSeq": close["returnSeq"]},
        "publicSearchLabels": [row["label"] for row in raw["toolCalls"].values() if selected(row)],
        "managerSearchCallIds": [row["id"] for row in raw["originalSearchCalls"] if selected(row)],
        "syncRequestCallIds": [row["id"] for row in raw["methodCalls"] if row["method"] in {"reindex", "reindex_sources"} and selected(row)],
        "bootstrapRepairIds": [row["id"] for row in repairs], "producerBaseCallIds": [row["id"] for row in producers],
        "publicationCommitCallIds": [row["id"] for row in commits], "publicationCommitEvidence": evidence,
        "committedGenerationBaseCallIds": generations, "unit": "original-public-base-reindex-or-reindex_sources-execution-entry",
        "freshOwnerActivityExcludedFromCommonCounts": True}
    counts = {"searchRequests": len(derivation["publicSearchLabels"]), "managerSearches": len(derivation["managerSearchCallIds"]),
        "syncRequests": len(derivation["syncRequestCallIds"]), "bootstrapRequests": len(repairs),
        "producerAttempts": len(producers), "committedGenerations": len(generations)}
    require(_same(raw["counterDerivations"], derivation) and _same(counts, result["dispatches"])
            and _same([row["outcome"] for row in producers], result["producerOutcomes"]),
            "query-sync boundaries SDK common counts differ from actual original public producer entries")
    return primary, close, producers


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
    require(set(local) == {str(ROOT / "equivalence" / f"query-sync-boundaries-{name}.mjs")
                           for name in ("entry", "preload", "runtime")}
            and process["cwd"] == str(ROOT),
            "query-sync boundaries Native context supplied an unreviewed local program")
    for filename, digest in local.items():
        require(Path(filename).is_file() and _file_digest(filename) == digest,
                "query-sync Native protected actor bytes changed after actual execution")
    expected = {(package["location"], file["path"]): file["sha256"]
                for package in context["runtime"]["packages"] for file in package["files"]}
    runtime = context["runtime"]
    require(runtime["reference"] == {"tag": "v" + VERSION, "commit": REFERENCE_COMMIT}
            and runtime["manifestSha256"] == MANIFEST_SHA256
            and all(expected.get(("node_modules/openclaw", path)) == digest for path, digest in COMPILED_HASHES.items()),
            "query-sync boundaries Native context does not bind the independently pinned original compiled owners")
    runtime_root = Path(runtime["runtimeRoot"])
    package_root = runtime_root.parent.parent
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
        own = [row for row in rows if row["event"] == "query-sync-boundaries-bootstrap"]
        require(len(own) == 1 and own[0]["clock"]["apis"] == ["Date"]
                and own[0]["clock"]["nowMs"] == case["input"]["nowMs"]
                and own[0]["clock"]["setTimeoutUnchanged"] is True
                and own[0]["clock"]["performanceNowUnchanged"] is True,
                "query-sync Native actual workers changed timer or Date-only profile")
        for row in rows[1:]:
            require(row["pid"] == raw["pid"] and row["threadId"] == first["threadId"],
                    "query-sync Native actual import trace changed worker identity")
            if row["event"] == "query-sync-boundaries-bootstrap":
                continue
            require(row["event"] in {"load", "resolve-native"}, "query-sync Native actual import trace added unknown operation")
            if row.get("kind") == "oracle":
                require(local.get(row["path"]) == row["sha256"], "query-sync Native unapproved actor executed")
                oracle.add(row["path"])
            else:
                require(row.get("kind") == "release" and expected.get((row["package"], row["path"])) == row["sha256"],
                        "query-sync Native actual imported engine source bytes changed")
                relative = Path(row["path"])
                package = Path(row["package"])
                require(not relative.is_absolute() and ".." not in relative.parts
                        and not package.is_absolute() and ".." not in package.parts,
                        "query-sync boundaries actual imported artifact escaped its approved package")
                loaded_path = package_root / package / relative
                require(loaded_path.is_file() and not loaded_path.is_symlink()
                        and loaded_path.resolve() == loaded_path
                        and _file_digest(loaded_path) == row["sha256"],
                        "query-sync boundaries actually imported original compiled bytes changed on disk")
                (main if first["isMainThread"] else worker).add(row["path"])
    require(0 in threads and len(threads) > 1 and set(local) - {str(Path(process["cwd"]) / "equivalence/query-sync-boundaries-preload.mjs")} <= oracle
            and {"dist/extensions/memory-core/manager-runtime.js", "dist/tools-DotaQGXh.mjs"} <= main
            and "dist/sqlite-worker-store-D6Kl0iv0.mjs" in worker,
            "query-sync Native actual public manager/tool/read/publication workers did not execute")
    require(set(REQUIRED_MAIN_ARTIFACTS) <= main and set(REQUIRED_WORKER_ARTIFACTS) <= worker,
            "query-sync boundaries omitted independently declared actual original main/worker owners")
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
            and _file_digest(trusted) == authority["sha256"],
            "query-sync captured Node authority differs from independently trusted decoder")
    return {**authority, "execPath": str(trusted)}


def _typed_errors(raw, *, native, approved_sdk_root=None):
    if native:
        typed = raw["typedConflictClass"]
        require(typed["module"] == "dist/manager-db-kernel-DyJADqYu.mjs"
                and typed["export"] == "t" and typed["classRef"] and typed["prototypeRef"]
                and typed["compiledSha256"] == COMPILED_HASHES[typed["module"]],
                "query-sync boundaries original typed-conflict constructor lost its authority")
        witnesses = {row["errorRef"]: row for row in raw["originalErrors"]}
        require(len(witnesses) == len(raw["originalErrors"]), "original exception identity was duplicated")
        calls = raw["wholeJobs"] + raw["publicationCalls"] + raw["methodCalls"] + list(raw["syncCalls"].values())
        for call in calls:
            if "error" not in call:
                require(not call.get("isTypedConflict"), "successful original operation became a typed conflict")
                continue
            witness = witnesses[call["errorRef"]]
            actual = typed["prototypeRef"] in witness["prototypeChainRefs"]
            require(witness["originalTypedClassRef"] == typed["classRef"]
                    and witness["isTypedConflict"] is actual and _same(witness["payload"], call["error"])
                    and ("isTypedConflict" not in call or call["isTypedConflict"] is actual),
                    "query-sync boundaries original exception/prototype predicate was relabelled")
    else:
        typed = raw["baseCallObservation"]["typedConflictClass"]
        require(typed["module"] == "memory_core.consolidation.origins"
                and typed["qualname"] == "MemoryIndexRevisionConflictError"
                and typed["sourceSha256"] == hashlib.sha256(_sdk_source_path(ROOT / "memory_core/consolidation/origins.py", approved_sdk_root).read_bytes()).hexdigest(),
                "query-sync boundaries SDK original typed-conflict class bytes changed")
        witnesses = {}
        for call in raw["originalBaseCalls"]:
            for witness in call.get("exceptions", []):
                kind = witness["exceptionType"]
                actual = {"module": typed["module"], "qualname": typed["qualname"]} in kind["mro"]
                error = witness["error"]
                frames = re.findall(r'^\s*File "([^"]+)", line \d+', error["traceback"], flags=re.MULTILINE)
                require(frames and not Path(frames[-1]).is_relative_to(ROOT / "equivalence"),
                        "SDK original producer was interrupted by an observer-origin exception")
                require(witness["isTypedConflict"] is actual
                        and error["errorRef"] == witness["errorRef"]
                        and error["module"] == kind["module"] and _same(error["exceptionType"], kind),
                        "query-sync boundaries actual SDK exception type/MRO was relabelled")
                witnesses[witness["errorRef"]] = witness
            if call["outcome"]["status"] == "rejected":
                require(call["errorRef"] == call["exceptions"][-1]["errorRef"],
                        "SDK producer settlement borrowed another original exception")
        for call in raw["syncCalls"].values():
            if "error" in call and call["errorRef"] in witnesses:
                require(call["outcome"]["isTypedConflict"] is witnesses[call["errorRef"]]["isTypedConflict"],
                        "SDK explicit sync error changed its actual propagated predicate")


def _physical_fault(case, raw, events, primary, *, native):
    specification = case["input"].get("publicationFault")
    faults = ([raw["fault"]] if raw.get("fault") else []) if native else raw["faults"]
    require(len(faults) == int(specification is not None), "declared physical publication refusal missing or added")
    if not faults:
        return
    fault = faults[0]
    owner = raw["owners"][primary]
    db = owner["settings"]["store"]["databasePath"] if native else owner["indexPath"]
    sidecar = db + (".reindex-lock.sqlite" if native else "-journal")
    target = str(Path(raw["fixtureBase"]) / specification["target"])
    initial = fault["initial" if native else "before"]
    restored = fault["restored" if native else "afterRemoval"]
    armed, before = fault["armed"], fault["beforeRemoval"]
    link = "target" if native else "linkTarget"
    require(fault["sidecar" if native else "path"] == sidecar and fault["target"] == target
            and Path(sidecar).is_relative_to(raw["fixtureBase"])
            and fault["targetParentBefore"]["kind"] == "missing"
            and initial["kind"] in {"missing", "file"}
            and armed["kind"] == before["kind"] == "symlink"
            and armed["path"] == before["path"] == sidecar and armed[link] == before[link] == target
            and _entry_identity(armed, native=native) == _entry_identity(before, native=native)
            and _entry_identity(armed, native=native)[2] == 1 and fault["afterUnlink"]["kind"] == "missing"
            and fault["armEnterSeq"] < fault["armReturnSeq"] < fault["removeEnterSeq"] < fault["removeReturnSeq"],
            "query-sync boundaries actual owned publication refusal path/identity/chronology changed")
    if initial["kind"] == "file":
        renamed = fault["backupAfterRename" if native else "renamedOriginal"]
        require(restored["kind"] == renamed["kind"] == "file"
                and _entry_identity(initial, native=native) == _entry_identity(renamed, native=native)
                == _entry_identity(restored, native=native)
                and initial["hex"] == renamed["hex"] == restored["hex"]
                and initial["sha256"] == renamed["sha256"] == restored["sha256"]
                == hashlib.sha256(bytes.fromhex(initial["hex"])).hexdigest(),
                "query-sync boundaries preserved original sidecar was not physically restored")
    else:
        require(restored["kind"] == "missing", "publication refusal left an invented sidecar")
    if native:
        require(fault["removed"] is True and fault["emergencyRemoval"] is False
                and all(fault[key]["kind"] == "missing" for key in
                        ("targetBefore", "targetAfterArm", "targetBeforeRemoval", "backupBefore", "backupAfterRestore")),
                "Native physical refusal lacked actual removal or a persistently missing target")
        calls = [row for row in raw["faultSyscalls"]
                 if fault["armEnterSeq"] < row["enterSeq"] < fault["removeReturnSeq"]]
        for call in calls:
            _interval(call, events, "fault-syscall-enter", "fault-syscall-return", "real fault syscall detached")
        _fault_syscall_entries(fault, calls)
        for method, args in (("symlinkSync", [target, sidecar]), ("unlinkSync", [sidecar])):
            call = _one(calls, lambda row: row["method"] == method, "actual fault mutation syscall omitted")
            require(call["args"] == args and "error" not in call, "physical refusal mutation failed or changed path")
        failures = [row for row in raw["methodCalls"] if row["method"] == "syncAdmitted" and "error" in row
                    and fault["armReturnSeq"] < row["returnSeq"] < fault["removeEnterSeq"]]
    else:
        require(fault["actualFollowError"]["errno"] == 2 and fault["actualFollowError"]["filename"] == sidecar
                and not fault.get("removedDuringTeardown") and fault["savedAfterRemoval"]["kind"] == "missing",
                "SDK dangling publication sidecar did not refuse actual access or was only removed at teardown")
        failures = [row for row in raw["methodCalls"] if row["method"] in {"reindex", "reindex_sources"}
                    and "error" in row and fault["armReturnSeq"] < row["returnSeq"] < fault["removeEnterSeq"]]
    require(failures, "declared real publication refusal never affected an original admitted sync")


def _physical_controls(case, raw, events, primary, *, native, approved_sdk_root=None):
    value = case["input"]
    gates = raw["gates" if native else "sqlGates"]
    require(len(gates) == sum(step["operation"] == "arm-sql-gate" for step in value["steps"]),
            "actual owned SQLite gate omitted or added")
    for gate in gates:
        db = (raw["owners"][primary]["settings"]["store"]["databasePath"] if native
              else raw["owners"][primary]["indexPath"])
        require(gate["path"] == db + (".reindex-lock.sqlite" if native else "")
                and gate["released"] is True
                and gate["armEnterSeq"] < gate["armReturnSeq"] < gate["releaseEnterSeq"] < gate["releaseReturnSeq"],
                "query-sync boundaries real SQLite gate lifetime/path changed")
        if native:
            require(gate["transactionActiveAtArm"] is True and gate["busyCallIds"]
                    and gate["originalSyncSlotRef"] and gate["joinedRequests"]["joinCallIds"],
                    "Native gate never held a real transaction/producer/joined request")
            for ref in gate["busyCallIds"]:
                call = _one(raw["leaseCalls"], lambda row: row.get("id") == ref, "actual original SQLite busy receipt omitted")
                require(gate["armReturnSeq"] < call["enterSeq"] < call["returnSeq"] < gate["releaseEnterSeq"]
                        and call.get("error"), "SQLite gate did not physically block an original producer")
            for ref in gate["joinedRequests"]["joinCallIds"]:
                call = _one(raw["methodCalls"], lambda row: row["id"] == ref, "actual joined original request omitted")
                require(call["method"] == "syncAdmitted" and call["stateBefore"]["syncingRef"] == gate["originalSyncSlotRef"]
                        and call["enterSeq"] < gate["releaseEnterSeq"] < call["returnSeq"],
                        "Native request did not join the actual held original sync")
        else:
            require(gate["inTransaction"] is True and gate["totalChanges"] == 0
                    and gate["pendingReceipts"] and not gate.get("releasedDuringTeardown")
                    and gate["inTransactionBeforeRelease"] is True and gate["inTransactionAfterRelease"] is False
                    and gate["totalChangesBeforeRelease"] == gate["totalChangesAfterRelease"] == 0
                    and gate["closed"] is True,
                    "SDK gate lacked an actual nonwriting held writer transaction/pending original producer")
            for row in gate["pendingReceipts"]:
                require(gate["armReturnSeq"] < row["sequence"] < gate["releaseEnterSeq"]
                        and row["statement"].strip().upper() == "BEGIN IMMEDIATE"
                        and row in raw["sqlStatements"], "SDK original producer never reached the actual held SQLite gate")
    _physical_fault(case, raw, events, primary, native=native)
    specification = value.get("revisionConflict")
    if specification:
        if native:
            require(_same(raw["revisionControl"]["specification"], specification) and not raw["revisionErrors"],
                    "Native real revision conflict fixture specification/control failed")
            rows = raw["revisionControl"]["rounds"]
            actual_targets = [call for call in raw["publicationCalls"] if call["method"] == "publishShadow"
                and raw["owners"][call["ownerId"]].get("maintenanceSourceOwnerId") == primary
                and (call.get("operationContext") or {}).get("kind") == "search"
                and call["operationContext"].get("label") == specification["maintenanceQueryLabel"]]
            reached = sum(row["role"] == "maintenance" and row["reached"] for row in rows)
            require(reached == min(len(specification["paths"]) - 1, len(actual_targets)),
                    "Native revision control missed an actual eligible original maintenance publisher")
        else:
            rows = raw["functionalInterleavings"]
            require([row["role"] for row in raw["revisionConflictFixtures"]] == ["preparation", "maintenance"],
                    "SDK typed conflict controls lost their declared roles")
        require(any(row["role"] == "preparation" and (row.get("reached") if native else True) for row in rows),
                "actual original preparatory rival publication was never reached")
        for row in rows:
            paths = specification["paths"][:1] if row["role"] == "preparation" else specification["paths"][1:]
            require(row["markerPath"] in paths, "actual rival publication borrowed an undeclared marker/role")
            if native:
                if not row["reached"]:
                    continue
                require(row["rivalResult"] is True and row["actualRevisionAfter"] > row["expectedRevision"]
                        and row["acquireReturnSeq"] < row["reachedSeq"] < row["rivalEnterSeq"] < row["rivalReturnSeq"]
                        < row["releaseEnterSeq"] < row["releaseReturnSeq"] and row["released"] is True,
                        "Native actual revision conflict lacked a real rival commit/reader lifetime")
                read = _one(raw["revisionReads"], lambda call: call["id"] == row["revisionReadId"], "original revision read omitted")
                require(read["result"]["revision"] == row["expectedRevision"]
                        and row["rivalArguments"]["path"] == row["markerPath"],
                        "Native rival revision/source differs from original producer's actual read")
                before = _one(raw["snapshots"], lambda call: call["label"] == row["beforeSnapshot"], "real rival prepublication SQL omitted")
                after = _one(raw["snapshots"], lambda call: call["label"] == row["afterSnapshot"], "real rival committed SQL omitted")
                marker = _one(before["tables"]["memory_index_sources"], lambda call: call["path"] == row["markerPath"], "actual indexed rival marker omitted")
                require(marker["hash"] == row["rivalArguments"]["expectedHash"]
                        and not any(call["path"] == row["markerPath"] for call in after["tables"]["memory_index_sources"])
                        and _one(after["tables"]["memory_index_state"], lambda call: call["id"] == 1, "rival committed revision omitted")["revision"] == row["actualRevisionAfter"],
                        "Native rival claimed revision/source change without actual committed SQL")
            else:
                require(row["returned"] is True and "error" not in row
                        and row["revisionAfter"] == row["revisionBefore"] + 1
                        and row["trigger"]["expectedRevision"] == row["revisionBefore"]
                        and row["planFunction"]["changedPaths"] == row["planFunction"]["removedPaths"] == [row["markerPath"]]
                        and row["receiverIsExactObservedOwner"] is True
                        and row["plan"].get("chunks"),
                        "SDK rival action did not genuinely purge an indexed source through the original publisher")
                original = row["originalFunction"]
                require(original["module"] == "memory_core.consolidation.forget" and original["qualname"] == "purge_memory_index"
                        and _file_digest(_sdk_source_path(original["file"], approved_sdk_root)) == original["sourceSha256"],
                        "SDK rival publication lost its original purge API source authority")
                before = _one(raw["snapshots"], lambda snapshot: snapshot["label"] == f'rival-{row["number"]}-before', "actual rival prepublication SQL omitted")
                after = _one(raw["snapshots"], lambda snapshot: snapshot["label"] == f'rival-{row["number"]}-after', "actual rival committed SQL omitted")
                require(_one(before["tables"]["memory_core_index_sync"], lambda item: item["id"] == 1, "rival prior revision omitted")["revision"] == row["revisionBefore"]
                        and _one(after["tables"]["memory_core_index_sync"], lambda item: item["id"] == 1, "rival committed revision omitted")["revision"] == row["revisionAfter"]
                        and any(item["path"] == row["markerPath"] for item in before["tables"]["memory_core_index_sources"])
                        and not any(item["path"] == row["markerPath"] for item in after["tables"]["memory_core_index_sources"]),
                        "SDK rival revision/source purge differs from its real before/after SQL")
                if row["role"] == "preparation":
                    request = raw["syncCalls"][specification["preparationSyncLabel"]]
                    require(row["actualCause"]["syncLabel"] == specification["preparationSyncLabel"]
                            and row["actualCause"]["originalSyncEnterSeq"] == request["enterSeq"]
                            and request["enterSeq"] < row["enterSeq"] < row["returnSeq"] < request["returnSeq"],
                            "SDK preparatory rival borrowed another actual sync request")
                else:
                    require(row["actualCause"]["causalPublicQuery"] == specification["maintenanceQueryLabel"]
                            and any(call["method"] == "_run_memory_publication"
                                and call["causalPublicQuery"] == specification["maintenanceQueryLabel"]
                                and call["ownerId"] == row["ownerId"]
                                and call["enterSeq"] < row["enterSeq"] < row["returnSeq"] < call["returnSeq"]
                                for call in raw["backgroundCalls"]),
                            "SDK automatic rival borrowed a producer outside the actual declared query maintenance")
    if value.get("newerFormat"):
        fixture = raw["newerFormatFixture"] if native else _one(raw["metadataFixtures"], lambda row: True, "actual newer metadata fixture omitted")
        require(_same(fixture["specification"], value["newerFormat"])
                and raw["toolCalls"]["emptySeed"]["returnSeq"] < fixture["enterSeq"] < fixture["returnSeq"]
                < raw["toolCalls"]["automaticRefusal"]["enterSeq"],
                "newer metadata fixture did not follow the real public empty bootstrap")
        before = fixture["beforeMetadata" if native else "actualStoredMetadataBefore"]
        after = fixture["afterMetadata" if native else "after"]
        require(isinstance(before, dict) and _same(after, {**before, value["newerFormat"]["field"]: value["newerFormat"]["version"]})
                and (not native or fixture["committed"] is True and fixture["actualChunkCount"] == fixture["actualSourceCount"] == 0),
                "newer-format control changed more than actual existing empty-generation metadata")


def _raw(case, raw, result, *, native, approved_node=None, approved_sdk_root=None):
    require(isinstance(raw, dict) and raw.get("kind") == "query-sync-boundaries"
            and raw.get("engine") == ("native" if native else "sdk") and raw.get("caseId") == case["id"]
            and _same(raw.get("input"), case["input"]) and _same(raw.get("result"), result)
            and type(raw.get("pid")) is type(raw.get("ppid")) is int
            and raw["pid"] > 0 and raw["ppid"] > 0 and raw["pid"] != raw["ppid"]
            and Path(raw["fixtureBase"]).is_absolute() and raw.get("completed") is True
            and raw.get("allManagersClosed") is True and "error" not in raw
            and not any(raw.get(key) for key in ("teardownError", "teardownErrors", "faultCleanupError",
                "gateCleanupError", "revisionErrors", "fixtureErrors", "observationErrors")),
            "query-sync boundaries actual protected capture is incomplete or belongs to another attempt")
    events = _clock(raw, native=native)
    if native:
        authority = _native_process(case, raw, approved_node=approved_node)
        _native_wires(raw, events, authority)
        require(raw["runtimeCloseAllInvoked"] is raw["runtimeCloseAllReturned"] is True
                and all(row["closed"] is row["closing"] is True for row in raw["finalManagerStates"]),
                "Native original owners were not actually closed")
    else:
        _private_markers(raw)
        _sdk_bindings(raw, approved_sdk_root)
        require(Path(raw["implementationRoot"]) == ROOT
                and _same(raw["requestedConfig"], case["input"]["config"])
                and _same(raw["clock"], {"owner": "public-tool-clock", "nowMs": case["input"]["nowMs"], "monotonicAndTimers": "unmodified"})
                and raw["sourcePolicy"]["sources"] == raw["sourcePolicy"]["searchSources"] == ["memory"]
                and raw["sdkProfile"]["memoryPublication"] == "on-search"
                and raw["sdkProfile"]["contextStatus"] is raw["sdkProfile"]["refreshStore"] is None
                and raw["baseCallObservation"]["profilesRestored"] is raw["baseCallObservation"]["exceptionTraceRestored"] is True,
                "SDK actual implementation/source/profile/clock or observer restoration changed")
        identity = raw["sourceIdentity"]
        require(_same(identity["beforeImports"], identity["afterImports"])
                and _same(identity["beforeImports"], identity["afterClose"]),
                "SDK production bytes changed during original execution")
        _sdk_tool_contexts(case, raw, events, approved_sdk_root)
    _steps(case, raw, events, native=native)
    _source_custody(case, raw, result, events, native=native)
    _tools(case, raw, result, events, native=native)
    if native:
        _native_publication_wires(raw, events)
    primary, close, producers = (_native_counts(raw, result, events) if native
        else _sdk_counts(raw, result, events, approved_sdk_root=approved_sdk_root))
    _typed_errors(raw, native=native, approved_sdk_root=approved_sdk_root)
    _read_generations(case, raw, result, events, native=native)
    _physical_controls(case, raw, events, primary, native=native, approved_sdk_root=approved_sdk_root)
    require(raw["statusCalls"], "actual original selected provider was never observed")
    for call in raw["statusCalls"]:
        returned = call["result" if native else "returned"]
        require("error" not in call and returned["provider"] == result["provider"],
                "complete original status/selected provider was substituted")
    return True


def _sdk(case, dispatch, result, *, approved_sdk_root=None):
    require(isinstance(dispatch, dict) and dispatch.get("kind") == "query-sync-boundaries-sdk-dispatch"
            and _same(dispatch.get("input"), case["input"]) and _same(dispatch.get("exit"), {"code": 0})
            and type(dispatch["pid"]) is type(dispatch["coordinatorPid"]) is int
            and dispatch["pid"] != dispatch["coordinatorPid"], "actual SDK process dispatch failed or was reassigned")
    wire = dispatch["requestJson"]
    request = json.loads(wire)
    require(_same(request, dispatch["request"]) and set(request) == {"input", "directory"}
            and _same(request["input"], case["input"])
            and hashlib.sha256(wire.encode()).hexdigest() == dispatch["requestSha256"]
            and dispatch["argv"][1:] == ["-m", "equivalence.query_sync_boundaries_sdk_cli"]
            and dispatch["environmentKeys"] == ["LANG", "OPENCLAW_HOME", "OPENCLAW_STATE_DIR", "PATH", "PYTHONPATH", "TZ"],
            "actual SDK process request/argv/environment changed")
    observed = json.loads(dispatch["stdout"])
    require(_same(observed, dispatch["observation"]) and set(observed) == {"result", "raw"}
            and _same(observed["result"], result), "SDK stdout lost whole actual public/raw output")
    raw = observed["raw"]
    require(raw["pid"] == dispatch["pid"] and raw["ppid"] == dispatch["coordinatorPid"]
            and raw["fixtureBase"] == request["directory"]
            and raw["process"]["executable"] == dispatch["argv"][0]
            and raw["process"]["cwd"] == raw["implementationRoot"]
            and set(raw["process"]["environmentKeys"]) in (set(dispatch["environmentKeys"]), set(dispatch["environmentKeys"]) | {"LC_CTYPE"})
            and int(dispatch["startedAtNs"]) < min(int(row["atNs"]) for row in raw["events"])
            <= max(int(row["atNs"]) for row in raw["events"]) < int(dispatch["finishedAtNs"]),
            "actual SDK child PID/directory/environment/chronology was reassigned")
    return _raw(case, raw, result, native=False, approved_sdk_root=approved_sdk_root)


def validate_capture(case, capture, result, *, native, approved_node=None, approved_sdk_root=None):
    try:
        validate_result(case, result)
        return (_raw(case, capture, result, native=True, approved_node=approved_node)
                if native else _sdk(case, capture, result, approved_sdk_root=approved_sdk_root))
    except (KeyError, IndexError, TypeError, AttributeError, StopIteration, json.JSONDecodeError, OSError) as error:
        raise ValueError(("Native" if native else "SDK") + " query-sync boundary custody is structurally incomplete: " + str(error)) from error


def validate_pair(case, native_raw, sdk_raw, native_result, sdk_result, *, approved_node=None, approved_sdk_root=None):
    """Independent custody, including genuine differences; never predicts parity."""
    validate_capture(case, native_raw, native_result, native=True, approved_node=approved_node)
    validate_capture(case, sdk_raw, sdk_result, native=False, approved_sdk_root=approved_sdk_root)
    return True


def replay_case(case, directory, *, approved_node=None, approved_sdk_root=None):
    directory = Path(directory)
    native = json.loads((directory / "stdout.json").read_text())["result"]
    sdk = json.loads((directory / "sdk-output.json").read_text())
    originals = json.loads((directory / "evidence/native-raw.json").read_text())
    copies = json.loads((directory / "evidence/python-raw.json").read_text())
    require(len(originals) == len(copies) == 1, "replay requires exactly one actual capture per engine")
    validate_pair(case, originals[0], copies[0], native, sdk, approved_node=approved_node, approved_sdk_root=approved_sdk_root)
    return {"validated": True, "publicMatch": _same(native, sdk), "nativeSnapshots": 1,
            "sdkSnapshots": 1, "acceptancePointsAwarded": 0}



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

