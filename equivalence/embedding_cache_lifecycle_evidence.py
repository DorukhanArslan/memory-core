"""Bind the complete cache protocol to real calls and durable observations.

Sync/reindex and search return values and exceptions remain unchanged in each
side's raw carrier. They are not a shared completion field. The shared packet
is the whole cache, effective identity, and every actual embedding receipt.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct

from equivalence.embedding_cache_lifecycle import validate_case
from equivalence.embedding_cache_lifecycle_bindings import COMPILED_HASHES
from equivalence.embedding_cache_lifecycle_profile import PROVIDER_SOURCE_HASHES
from equivalence.forget_lineage_evidence import _bytes, physical_snapshot
from equivalence.forget_lineage_outcomes_evidence import _files, _sdk_physical, _tables
from equivalence.search_contract import _same_json

ROOT = Path(__file__).resolve().parents[1]
MODE = "deterministic-embedding-fixture"
CACHE_COLUMNS = {"provider", "model", "provider_key", "hash", "embedding", "dims", "updated_at"}
NATIVE_TRIGGER = "embedding_cache_publication_failure"
NATIVE_TRIGGER_SQL = (
    "CREATE TRIGGER embedding_cache_publication_failure BEFORE INSERT ON memory_index_chunks "
    "BEGIN SELECT RAISE(ABORT,'embedding-cache-publication-blocked'); END"
)
SDK_TRIGGER = "embedding_fixture_publication_failure"
SDK_TRIGGER_SQL = (
    "CREATE TRIGGER embedding_fixture_publication_failure BEFORE INSERT ON chunks "
    "BEGIN SELECT RAISE(ABORT,'embedding fixture publication failure'); END"
)
MANAGER = "dist/extensions/memory-core/manager-runtime.js"
MANAGER_METHODS = (
    "sync", "search", "close", "status", "resolveConfiguredIndexIdentity", "resolveProviderIndexIdentities",
    "embedChunksInBatches", "embedBatchWithRetry", "embedQueryWithRetry", "persistGeneratedEmbeddings",
    "getIndexConcurrency",
)
HOST_LINK = re.compile(
    r"tmp/plugin-captures/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
    r"/captures/openclaw-plugin-build-[A-Za-z0-9]{6}/node_modules/openclaw"
)
LINK_IDENTITY = {"device", "inode", "mode", "nlink", "uid", "gid", "size", "atimeNs", "mtimeNs", "ctimeNs", "birthtimeNs"}


def _require(value, message):
    if not value:
        raise ValueError("embedding cache lifecycle: " + message)


def _same(left, right, message):
    _require(_same_json(left, right), message)


def _relative(name):
    _require(isinstance(name, str) and name and "\\" not in name, "invalid relative source path")
    path = PurePosixPath(name)
    _require(not path.is_absolute() and ".." not in path.parts and path.as_posix() == name,
             "a source path escaped its owned workspace")
    return name


def _sources(rows, workspace, files=None):
    """Validate either producer's unchanged source carrier, returning bytes only."""
    native = isinstance(rows, dict)
    _require(native or isinstance(rows, list), "the full source witness is missing")
    entries = rows.items() if native else ((row["path"], row) for row in rows)
    result = {}
    for name, row in entries:
        _relative(name)
        _require(name not in result, "a source witness is duplicated")
        _same(row["path"] if native else row["absolutePath"], str(Path(workspace) / name),
              "source identity belongs to another workspace")
        data, identity = _bytes(row["bytes"]), row["identity"]
        _require(set(identity) == {"device", "inode", "size", "mtimeNs", "ctimeNs"}
                 and identity["size"] == len(data)
                 and all(isinstance(identity[key], str) and identity[key].isdigit()
                         for key in ("device", "inode", "mtimeNs", "ctimeNs")),
                 "a source witness lost actual bytes or filesystem identity")
        result[name] = data
    if files is not None:
        expected = {name.removeprefix("workspace/"): data for name, data in files.items()
                    if name.startswith("workspace/")}
        _require(result == expected, "source witnesses differ from the whole physical workspace")
    return result


def _links(snapshot, raw, *, fixture, require_live_disk=False):
    """Retain only the original loader's host link, without reading its target."""
    links = snapshot.get("links")
    _require(isinstance(links, dict), "the complete physical symbolic-link map is missing")
    _require(not fixture or not links, "the input fixture unexpectedly contains a symbolic link")
    root = Path(snapshot["root"])
    if require_live_disk:
        actual_links = set()
        for directory, directories, filenames in os.walk(root, followlinks=False):
            for name in directories + filenames:
                path = Path(directory) / name
                if path.is_symlink():
                    actual_links.add(path.relative_to(root).as_posix())
        _same(sorted(actual_links), sorted(links), "the complete surviving symbolic-link set differs from capture")
    for name, row in links.items():
        _relative(name)
        _require(not fixture and HOST_LINK.fullmatch(name) and set(row) == {"path", "target", "resolvedTarget", "lstatIdentity"},
                 "a physical symbolic link is outside the original plugin loader's exact host path")
        path = root / name
        _same(row["path"], str(path), "a retained loader link escaped its physical owner")
        _same(row["target"], raw["runtimeRoot"], "the loader link targets a different runtime")
        _same(row["resolvedTarget"], raw["runtimeRoot"], "the resolved loader target differs from its actual runtime")
        _require(not any(filename == name or filename.startswith(name + "/") for filename in snapshot["files"]),
                 "physical evidence followed a loader link or rewrote it as a regular file")
        identity = row["lstatIdentity"]
        _require(set(identity) == LINK_IDENTITY
                 and all(isinstance(value, str) and value.isdigit() for value in identity.values())
                 and stat.S_ISLNK(int(identity["mode"])) and int(identity["nlink"]) > 0
                 and int(identity["size"]) == len(row["target"].encode()),
                 "a loader link lost its complete actual lstat identity")
        if require_live_disk:
            observed = path.lstat()
            fields = {"device": observed.st_dev, "inode": observed.st_ino, "mode": observed.st_mode,
                      "nlink": observed.st_nlink, "uid": observed.st_uid, "gid": observed.st_gid,
                      "size": observed.st_size, "atimeNs": observed.st_atime_ns,
                      "mtimeNs": observed.st_mtime_ns, "ctimeNs": observed.st_ctime_ns}
            if hasattr(observed, "st_birthtime_ns"):
                fields["birthtimeNs"] = observed.st_birthtime_ns
            _same({key: identity[key] for key in fields}, {key: str(value) for key, value in fields.items()},
                  "the surviving loader link differs from its captured lstat identity")
            _same(os.readlink(path), row["target"], "the surviving loader link changed its literal target")


def _sql(database, native):
    _require(isinstance(database, dict) and isinstance(database.get("schema"), list)
             and isinstance(database.get("tables"), dict), "a complete actual SQL snapshot is missing")
    schema, tables = database["schema"], database["tables"]
    _require(all(set(row) == {"type", "name", "tbl_name", "sql"} for row in schema),
             "an actual SQL schema row lost fields")
    names = [row["name"] for row in schema if row["type"] == "table"]
    _require(len(names) == len(set(names)) and set(names) == set(tables)
             and all(isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
                     for rows in tables.values()), "the SQL snapshot dropped a table or complete row")
    if native:
        _same(database.get("transaction"), {"mode": "deferred", "active": True},
              "Native SQL was not captured under the actual read transaction")
    return tables


def _cache(database, observed, native):
    tables = _sql(database, native)
    _require("memory_embedding_cache" in tables, "the actual persistent cache is absent")
    rows = tables["memory_embedding_cache"]
    projected = []
    for row in sorted(rows, key=lambda item: tuple(item[key] for key in ("provider", "model", "provider_key", "hash"))):
        _require(set(row) == CACHE_COLUMNS and set(row["embedding"]) == {"type", "hex"}
                 and row["embedding"]["type"] == "bytes", "a cache row lost one of its seven SQL columns or BLOB")
        payload = bytes.fromhex(row["embedding"]["hex"])
        _require(len(payload) % 8 == 0, "a generated cache BLOB is not binary64")
        vector = [item[0] for item in struct.iter_unpack("<d", payload)]
        _require(vector and all(math.isfinite(item) for item in vector)
                 and row["dims"] == len(vector), "a generated cache vector has inconsistent dimensions")
        projected.append({**row, "embedding": vector, "embeddingHex": payload.hex()})
    _same(observed, projected, "the public cache dropped or changed SQL columns, BLOB bytes, vectors or order")


def _key(data):
    # Frozen provider facts contain only ordinary finite JSON values. This is
    # the literal wire supplied to the actual configured identity resolver.
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _identity(profile, enabled, actual):
    _same(actual, {"provider": profile["id"], "model": profile["model"],
          "providerKey": _key(profile["cacheKeyData"]), "cacheKeyData": profile["cacheKeyData"],
          "indexIdentityAliases": [{**alias, "providerKey": _key(alias["cacheKeyData"])}
                                   for alias in profile["indexIdentityAliases"]], "cacheEnabled": enabled},
          "the complete configured identity, aliases or effective cache policy changed")


def _sdk_index(database, observed):
    """Ground the complete SDK publication read in its independently captured SQL."""
    tables = database["tables"]

    def records(name, columns, order):
        return [{target: row[source] for source, target in columns}
                for row in sorted(tables[name], key=lambda row: tuple(row[key] for key in order))]

    details = records("memory_index_chunk_details", (("chunk_id", "chunkId"), ("hash", "hash"),
                      ("model", "model"), ("updated_at", "updatedAt")), ("chunk_id",))
    provenance = records("memory_index_chunk_provenance", (("chunk_id", "chunkId"),
                         ("origin_class", "originClass"), ("session_kind", "sessionKind"),
                         ("observed_at", "observedAt"), ("supersedes_key", "supersedesKey")), ("chunk_id",))
    recall = records("memory_index_chunk_recall_metadata", (("chunk_id", "chunkId"),
                     ("importance", "importance"), ("triggers", "triggers"), ("project_key", "projectKey")), ("chunk_id",))
    chunks = records("chunks", (("id", "id"), ("path", "path"), ("source", "source"),
                     ("start_line", "startLine"), ("end_line", "endLine"), ("text", "text"),
                     ("embedding", "embedding")), ("id",))
    for chunk in chunks:
        chunk["embedding"] = json.loads(chunk["embedding"])
        for collection, key in ((details, None), (provenance, "provenance"), (recall, "recall")):
            metadata = {name: value for row in collection if row["chunkId"] == chunk["id"]
                        for name, value in row.items() if name != "chunkId"}
            if key is None:
                chunk.update(metadata)
            else:
                chunk[key] = metadata
    chunk_map = {row["id"]: row for row in chunks}
    fts = []
    for row in sorted(tables["chunks_fts"], key=lambda item: (item["id"], item["text"])):
        chunk = chunk_map.get(row["id"], {})
        fts.append({"id": row["id"], "text": row["text"],
                    **{key: chunk.get(key) for key in ("path", "source", "startLine", "endLine", "model")}})
    expected = {"revision": next(row["revision"] for row in tables["memory_core_index_sync"] if row["id"] == 1),
                "chunks": chunks, "provenance": provenance, "recall": recall, "details": details, "fts": fts,
                "sources": records("memory_core_index_sources", tuple((key, key) for key in (
                    "path", "source", "hash", "mtime", "size")), ("source", "path")),
                "paths": records("paths_fts", (("path", "path"), ("source", "source")), ("source", "path")),
                "meta": records("memory_index_meta", (("key", "key"), ("value", "value")), ("key",))}
    _same(observed, expected, "the complete SDK publication read differs from physical index SQL")


def _outcome(actual, native):
    outcome = actual["apiOutcome"]
    _require(isinstance(outcome, dict) and outcome.get("kind") in {"return", "throw"},
             "an original API outcome is missing")
    field = "returnValue" if outcome["kind"] == "return" else "error"
    _require(set(outcome) == {"kind", field} and isinstance(outcome[field], dict),
             "an original API outcome was coerced or truncated")
    if field == "returnValue":
        _require(isinstance(outcome[field].get("type"), str), "the original return type was dropped")
    else:
        error = outcome[field]
        _require(isinstance(error.get("name"), str) and isinstance(error.get("message"), str)
                 and isinstance(error.get("stack" if native else "traceback"), str),
                 "an original exception lost its type, message or stack")
        if not native:
            _require({"module", "args", "properties"} <= set(error), "an SDK exception lost original fields")
    return outcome, field


def _provider_calls(raw, native):
    calls = raw["providerCalls" if native else "providerRawCalls"]
    _require(isinstance(calls, list), "the actual embedding callback journal is missing")
    selected = raw["input"]["provider"]
    by_operation = {}
    for index, operation in enumerate(raw["input"]["operations"]):
        if operation["op"] == "reopen":
            selected = operation.get("provider", selected)
        profile = raw["input"]["providers"][selected]
        control = operation.get("providerControl", {})
        remaining = {"document": control.get("documentFailures", 0), "query": control.get("queryFailures", 0)}
        ordinals = {"document": 0, "query": 0}
        operation_calls = [row for row in calls if row["operationIndex"] == index]
        if index == 0:
            _require(operation["op"] == "sync" and operation_calls,
                     "the cold index operation never reached the actual document embedder")
        if operation["op"] == "query":
            _require(operation_calls and all(row["semantic" if native else "semanticReceipt"]["kind"] == "query"
                                            for row in operation_calls),
                     "a driven query did not reach the actual query embedder")
        by_operation[index] = operation_calls
        for row in operation_calls:
            semantic = row["semantic" if native else "semanticReceipt"]
            kind, inputs = semantic["kind"], semantic["inputs"]
            _require(kind in ordinals and isinstance(inputs, list) and inputs
                     and all(isinstance(text, str) and text for text in inputs)
                     and operation["op"] == ("sync" if kind == "document" else "query"),
                     "an embedding request is detached from its real driven operation")
            ordinals[kind] += 1
            _same(row["control"], control, "the actual callback used a different fixture policy")
            _same(row["arguments"][0], inputs if kind == "document" else inputs[0],
                  "the actual embedding arguments differ from their receipt")
            if kind == "query":
                _same(inputs, [operation["query"]], "the real query embedder received a different query")
            else:
                _same(row["documentOrdinal" if native else "operationCallOrdinal"], ordinals[kind],
                      "document callback attempts or split/retry order were dropped")
            before = _sources(row["sourcesBefore"], raw["workspace"])
            after = _sources(row["sourcesAfter"], raw["workspace"])
            mutation = control.get("mutateOnDocumentCall")
            expected_sources = dict(before)
            if kind == "document" and mutation and mutation["call"] == ordinals[kind]:
                expected_sources.update({name: text.encode() for name, text in mutation["files"].items()})
            _require(after == expected_sources, "the actual callback source mutation differs from its literal fault")
            _sql(row["databaseBefore"], native)
            _sql(row["databaseAfter"], native)
            _same(row["databaseBefore"], row["databaseAfter"], "a fixture embedding callback itself altered durable SQL")
            error = None
            if kind == "document" and "maxItems" in control and len(inputs) > control["maxItems"]:
                error = {"name": "Error", "message": "input array max " + str(control["maxItems"]), "status": 400}
            elif kind == "document" and control.get("failText") and any(control["failText"] in text for text in inputs):
                error = {"name": "Error", "message": "embedding fixture terminal document failure", "status": 400}
            elif remaining[kind]:
                remaining[kind] -= 1
                error = {"name": "Error", "message": "embedding fixture transient " + kind + " failure",
                         "status": 503, "retryAfterMs": 0}
            expected = {"kind": kind, "provider": profile["id"], "model": profile["model"], "inputs": inputs,
                        "completed": error is None}
            if error is not None:
                expected["error"] = error
                actual_error = row["error"]
                error_fields = actual_error if native else {**actual_error, **actual_error["properties"]}
                _same({key: error_fields[key] for key in error}, error, "a callback error changed its actual domain fields")
                _require(isinstance(actual_error.get("stack" if native else "traceback"), str),
                         "an actual embedding callback exception lost its original stack")
                _require("returnValue" not in row, "a failed callback acquired a successful vector return")
            else:
                dimensions = 3 if kind == "document" and control.get("response") == "dimensions-3" else profile["dimensions"]
                vectors = [[1, len(text.encode()), *([0.5] if dimensions == 3 else [])] for text in inputs]
                result = ([] if control.get("response") == "empty" else vectors) if kind == "document" else vectors[0]
                expected["returnValue"] = result
                _same(row["returnValue"], {"type": "object" if native else "list", "value": result},
                      "the actual complete embedding vector return differs from its receipt")
                _require("error" not in row, "a successful callback acquired a fabricated error")
            _same(semantic, expected, "the complete actual embedding receipt was changed or filtered")
    ordered = [row for rows in by_operation.values() for row in rows]
    _same(ordered, calls, "an embedding callback occurred outside the literal operation order")
    _require(any((receipt := row["semantic" if native else "semanticReceipt"])["kind"] == "document"
                 and receipt["completed"] is True and receipt.get("returnValue") for row in calls),
             "the managed family never returned actual document vectors")
    if native:
        _same([row["ordinal"] for row in calls], list(range(1, len(calls) + 1)), "a global callback ordinal was lost")
    return by_operation


def _capture(raw, capture, state, native, profile, enabled, source_rows, database_path=None):
    _require(set(state) == {"cache", "identity", "providerCalls"}, "the shared cache protocol acquired or lost a field")
    if native:
        fixture, durable = capture["fixture"], capture["state"]
        _same(fixture["root"], raw["fixtureBase"], "Native physical fixture ownership changed")
        _same(durable["root"], raw["stateDirectory"], "Native physical state ownership changed")
        _links(fixture, raw, fixture=True)
        _links(durable, raw, fixture=False)
        files, durable_files = _files(fixture), _files(durable)
        stores = [(Path(fixture["root"]), _tables(fixture, files)),
                  (Path(durable["root"]), _tables(durable, durable_files))]
        matches = [record for root, databases in stores for name, record in databases.items()
                   if str(root / name) == database_path]
        _require(len(matches) == 1, "the actual manager database is absent or duplicated in physical evidence")
        database = matches[0]
        config = json.loads(_bytes(capture["config"]))
        _same(config["memory"]["search"]["provider"], profile["id"], "physical Native provider configuration changed")
        for key, expected in (("model", profile["model"]), ("outputDimensionality", profile["dimensions"]),
                              ("remote", {"baseUrl": profile["cacheKeyData"]["endpoint"], "batch": {"enabled": False}})):
            _same(config["memory"]["search"][key], expected, "the physical Native provider request changed")
        _same(config["memory"]["search"]["cache"], {"enabled": enabled}, "physical Native cache policy changed")
    else:
        _same(capture["root"], raw["fixtureRoot"], "SDK physical fixture ownership changed")
        files = _files(capture)
        databases = _tables(capture, files)
        _require("index.sqlite" in databases, "the actual SDK store is absent from physical evidence")
        database = databases["index.sqlite"]
        sink = [json.loads(line) for line in files.get("provider-calls.jsonl", b"").splitlines()]
        _same(sink, state["providerCalls"], "the complete callback receipt sink differs from public state")
    _sources(source_rows, raw["workspace"], files)
    _cache(database, state["cache"], native)
    _identity(profile, enabled, state["identity"])
    return files, database


def _publication(actual, previous, database, native):
    trigger = actual["publicationFailure" if native else "trigger"]
    name, statement = (NATIVE_TRIGGER, NATIVE_TRIGGER_SQL) if native else (SDK_TRIGGER, SDK_TRIGGER_SQL)
    _same(trigger["name"], name, "the real publication abort trigger changed")
    _same(trigger["statement"], statement, "the actual SQLite publication failure policy changed")
    active = trigger["schemaBeforeDispatch"]
    rows = [row for row in active if row["name"] == name]
    _require(len(rows) == 1 and rows[0]["type"] == "trigger" and rows[0]["sql"] == statement
             and rows[0] in database["schema"], "the actual abort trigger was absent during dispatch or capture")
    _same(trigger["schemaAfterDrop" if native else "afterDropSchema"],
          [row for row in active if row["name"] != name], "the real trigger was not removed before recovery")
    _require(actual["apiOutcome"]["kind"] == "throw", "the physical publication abort did not reach the actual caller")
    marker = "embedding-cache-publication-blocked" if native else "embedding fixture publication failure"
    _require(marker in actual["apiOutcome"]["error"]["message"], "the real publication error lost the trigger cause")
    prefix = ("memory_index_chunks", "memory_index_sources", "memory_index_paths_fts", "memory_index_chunk_") if native else (
        "chunks", "paths_fts", "memory_core_index_sources", "memory_index_chunk_")
    for name, rows in previous["tables"].items():
        if name == "memory_index_meta" or name.startswith(prefix):
            _same(database["tables"][name], rows, "a failed publication changed a published index table")
    _require(database["tables"]["memory_embedding_cache"] != previous["tables"]["memory_embedding_cache"],
             "the publication fault did not retain the separately committed generated cache")


def _operations(case, raw, public, captures, native):
    value = case["input"]
    _same(raw["input"], value, "the actual input differs from the frozen case")
    _require(set(public) == {"provider", "before", "observations"} and public["provider"] == MODE,
             "the complete shared protocol changed")
    _require(len(raw["operations"]) == len(public["observations"]) == len(value["operations"])
             and len(captures) == len(value["operations"]) + (2 if native else 1),
             "a driven operation or complete physical capture is missing")
    _require(any(row["state"]["cache"] for row in public["observations"]),
             "the managed family never admitted any actual cache entry")
    by_operation = _provider_calls(raw, native)
    _same(raw["initialState"], public["before"], "the whole initial state was changed")
    _same(public["before"]["cache"], [], "the managed family was seeded with derived cache rows")
    _same(public["before"]["providerCalls"], [], "a callback was supplied before any real operation")
    selected, enabled = value["provider"], value["cacheEnabled"]
    states = raw["states"] if native else None
    if native:
        _require(len(states) == len(value["operations"]) + 1, "a complete Native manager state is missing")
    initial_sources = states[0]["sources"] if native else raw["operations"][0]["sourcesBefore"]
    database_path = states[0]["settings"]["store"]["databasePath"] if native else raw["databasePath"]
    files, previous_db = _capture(raw, captures[0], public["before"], native, value["providers"][selected],
                                  enabled, initial_sources, database_path)
    if native:
        _same(states[0]["state"], public["before"], "the initial actual manager state changed")
        _same(states[0]["rawSQL"], previous_db, "the initial complete manager SQL differs from physical capture")
    else:
        _sdk_index(previous_db, raw["initialIndex"])
    _require(_sources(initial_sources, raw["workspace"]) == {name: text.encode() for name, text in value["files"].items()},
             "the initial sources differ from the literal source facts")
    cumulative = []
    source_rows = initial_sources
    api_calls = [row for row in raw["calls"] if row.get("operation") in {"MemoryIndexManager.sync", "MemoryIndexManager.search"}] if native else []
    call_index = 0
    for index, (request, actual, observed, capture) in enumerate(zip(
            value["operations"], raw["operations"], public["observations"], captures[1:1 + len(value["operations"])], strict=True)):
        _same(actual["operation"], request, "a raw operation was changed or reordered")
        _same(actual["observed"], observed, "a whole public observation differs from actual raw")
        _require(set(observed) == {"operation", "state"}, "wrapper completion was introduced into the shared protocol")
        _same(observed["operation"], request, "a public operation differs from its frozen request")
        _same(actual["sourcesBefore"], source_rows, "the source revision changed before actual dispatch")
        outcome, field = _outcome(actual, native)
        if request["op"] == "reopen":
            selected, enabled = request.get("provider", selected), request.get("cacheEnabled", enabled)
        profile = value["providers"][selected]
        calls = by_operation[index]
        expected_files = {name.removeprefix("workspace/"): payload for name, payload in files.items()
                          if name.startswith("workspace/")}
        callback_sources = actual["sourcesBefore"]
        for call in calls:
            _same(call["sourcesBefore"], callback_sources, "a callback was detached from the actual source revision sequence")
            callback_sources = call["sourcesAfter"]
        if request["op"] in {"sync", "query"}:
            _same(actual["sourcesAfter"], callback_sources, "sources changed outside the retained embedding callbacks")
        elif request["op"] == "write":
            expected_files[request["path"]] = request["text"].encode()
        elif request["op"] == "rename":
            expected_files[request["to"]] = expected_files.pop(request["path"])
        elif request["op"] == "remove":
            del expected_files[request["path"]]
        if calls:
            expected_files = _sources(callback_sources, raw["workspace"])
        _require(_sources(actual["sourcesAfter"], raw["workspace"]) == expected_files,
                 "a driven fixture operation changed source bytes beyond its literal request")
        cumulative.extend(row["semantic" if native else "semanticReceipt"] for row in calls)
        _same(observed["state"]["providerCalls"], cumulative, "an actual embedding callback was omitted from public state")
        if native:
            state = states[index + 1]
            _same(state["operationIndex"], index, "Native state was borrowed from another operation")
            _same(state["state"], observed["state"], "the public state differs from its actual manager read")
            _same(state["sources"], actual["sourcesAfter"], "the source revision changed during the actual state read")
            database_path = state["settings"]["store"]["databasePath"]
            configured = state["configuredIdentity"]
            _same(configured["provider"], {"id": profile["id"], "model": profile["model"]},
                  "the actual configured identity resolver returned a different provider")
            _same(configured["cacheKeyData"], profile["cacheKeyData"], "the actual identity resolver changed cache key data")
            if state["activeProvider"] and state["activeProvider"].get("id") == "ollama":
                _same(state["actualIndexConcurrency"], 1, "the actual ollama owner did not use its sequential branch")
        files, database = _capture(raw, capture, observed["state"], native, profile, enabled,
                                   actual["sourcesAfter"], database_path)
        if native:
            _same(states[index + 1]["rawSQL"], database, "the complete manager SQL differs from physical capture")
        else:
            _sdk_index(database, actual["indexState"])
        if request["op"] in {"sync", "query"}:
            expected_args = ({"reason": "search-bootstrap", "force": request["force"]} if request["op"] == "sync" else
                             [request["query"], {"maxResults": 5, "minScore": 0}]) if native else (
                                 {"workspace": raw["workspace"], "force": request["force"]} if request["op"] == "sync" else
                                 {"query": request["query"], "max_results": 6, "min_score": 0})
            _same(actual["arguments"], expected_args, "the actual public owner received different arguments")
            if native:
                call = api_calls[call_index]
                call_index += 1
                _same(call["operation"], "MemoryIndexManager.sync" if request["op"] == "sync" else "MemoryIndexManager.search",
                      "a different original API owner handled the driven operation")
                _same(call["arguments"], [expected_args] if request["op"] == "sync" else expected_args,
                      "the original owner call journal changed dispatched arguments")
                _same(call[field], outcome[field], "the original owner call journal changed its complete outcome")
            else:
                _same(actual["owner"], "SQLiteMemoryStore.reindex" if request["op"] == "sync" else "SQLiteMemoryStore.search",
                      "a different SDK API owner handled the driven operation")
        if request.get("publicationFailure"):
            _same(actual["publicationFailure" if native else "trigger"]["databasePath"], database_path,
                  "the abort trigger targeted another physical database")
            _publication(actual, previous_db, database, native)
        previous_db, source_rows = database, actual["sourcesAfter"]
    if native:
        _require(call_index == len(api_calls), "an original sync/search call was dropped or added")


def _native(case, public, snapshots, evidence_directory, *, require_live_disk):
    validate_case(case)
    _require(isinstance(snapshots, list) and len(snapshots) == 1 and isinstance(snapshots[0], dict),
             "one complete original raw capture is required")
    raw = snapshots[0]
    base, directory = Path(raw["fixtureBase"]), Path(evidence_directory).resolve()
    _require(base.is_absolute() and base.parent == directory and base.name.startswith("native-embedding-cache-")
             and raw["closed"] is True and "closePhysicalError" not in raw,
             "the original fixture lost its owned identity or clean close")
    _same(raw["workspace"], str(base / "workspace"), "Native workspace changed")
    runtime_root = Path(raw["runtimeRoot"])
    _require(runtime_root.is_absolute() and str(runtime_root) == raw["runtimeRoot"] and ".." not in runtime_root.parts,
             "the actual original runtime root is not an absolute canonical path")
    _same(raw["request"], case["input"], "the original request was changed")
    _same(raw["clock"], {"owner": "node:test", "apis": ["Date"], "nowMs": case["input"]["nowMs"],
          "dateConstructorReplaced": True, "setTimeoutUnchanged": True, "performanceNowUnchanged": True},
          "the actual clock fixture changed scheduler ownership")
    expected = {"MemoryIndexManager": (MANAGER, "MemoryIndexManager"),
                "MemoryIndexManager.get": (MANAGER, "MemoryIndexManager"),
                "closeAllMemoryIndexManagers": (MANAGER, "closeAllMemoryIndexManagers"),
                "closeOpenClawAgentDatabasesAsync": ("dist/openclaw-agent-db-lifecycle-B8sSLgPo.mjs", "s"),
                "loadPluginMetadataSnapshot": ("dist/plugin-metadata-snapshot-DT_pRp6g.mjs", "o"),
                "loadAndActivateRootPluginRegistry": ("dist/loader-DpAS3szV.mjs", "t"),
                "decodeMemoryEmbedding": ("dist/embedding-vector-CGPWflQ5.mjs", "n"),
                "hashText": ("dist/hash-CAMhNIP1.mjs", "t"),
                "configureMemoryCoreDreamingState": ("dist/dreaming-state-VYUvbU-n.mjs", "p"),
                "openMemoryCoreStateStore": ("dist/dreaming-state-VYUvbU-n.mjs", "v"),
                "createPluginStateKeyedStore": ("dist/plugin-state-store-BPUaLoVD.mjs", "r"),
                "closePluginStateDatabaseAsync": ("dist/plugin-state-store-BPUaLoVD.mjs", "u")}
    expected.update({"MemoryIndexManager." + name: (MANAGER, "MemoryIndexManager") for name in MANAGER_METHODS})
    _require(len(raw["codeOwners"]) == len(expected) and {row["name"] for row in raw["codeOwners"]} == set(expected),
             "an actual Native owner is missing or duplicated")
    for row in raw["codeOwners"]:
        _same((row["modulePath"], row["exportName"]), expected[row["name"]], "an original function owner changed")
        _same(row["compiledSha256"], COMPILED_HASHES[row["modulePath"]], "an original compiled owner changed")
        _same(row["functionSourceSha256"], hashlib.sha256(row["functionSource"].encode()).hexdigest(),
              "an original function source observation changed")
    for name, digest in PROVIDER_SOURCE_HASHES.items():
        path = ROOT / "equivalence" / name
        _require(not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                 "the genuine fixture plugin adapter or manifest changed")
    registrations = raw["pluginRegistry"]["embeddingProviders"]
    _require(len(registrations) == 3 and {row["provider"]["id"] for row in registrations} == {
        "ollama", "fixture-cache-a", "fixture-cache-b"}
        and all(row["pluginId"] == "fixture-embedding-cache" for row in registrations),
        "the real plugin registry did not own exactly the three declared provider adapters")
    _same([row["operation"] for row in raw["closeReceipts"]],
          ["closeAllMemoryIndexManagers", "closeOpenClawAgentDatabasesAsync", "closePluginStateDatabaseAsync"],
          "a real durable close owner was omitted")
    _require(all(row.get("returnValue") == {"type": "undefined"} and "error" not in row for row in raw["closeReceipts"]),
             "a real close owner failed")
    captures = []
    for reference in raw["physical"]:
        path = Path(reference["path"])
        _require(path.is_absolute() and path.parent == directory and not path.is_symlink(), "Native capture escaped its attempt")
        if require_live_disk:
            _require(hashlib.sha256(path.read_bytes()).hexdigest() == reference["sha256"], "Native physical capture differs from disk")
        captures.append(physical_snapshot(reference))
    _same(Path(raw["physical"][-1]["path"]).name, "native-physical-closed.json", "the final close capture is missing")
    _same(raw["output"], public, "the complete original public packet changed")
    _operations(case, raw, public, captures, True)
    for fixture, tree in ((True, captures[-1]["fixture"]), (False, captures[-1]["state"])):
        _links(tree, raw, fixture=fixture, require_live_disk=require_live_disk)
        files = _files(tree)
        _tables(tree, files)
        for name, data in files.items():
            path = Path(tree["root"]) / name
            if require_live_disk:
                _require(not path.is_symlink() and path.read_bytes() == data, "the surviving physical file differs from close capture")


def validate_native(case, public, snapshots, evidence_directory):
    _native(case, public, snapshots, evidence_directory, require_live_disk=True)


def validate_pair(case, native_raw, sdk_raw, native_public, sdk_public, sdk_directory):
    _native(case, native_public, [native_raw], Path(native_raw["fixtureBase"]).parent, require_live_disk=False)
    directory = Path(sdk_directory).resolve()
    raw_path = directory / "python-raw.json"
    _require(not raw_path.is_symlink(), "the SDK raw record is a symlink")
    _same(json.loads(raw_path.read_text()), [sdk_raw], "the complete SDK raw record differs from disk")
    _require(sdk_raw["kind"] == "embedding-cache-lifecycle-sdk-raw" and sdk_raw["closed"] is True
             and sdk_raw["fixtureRoot"] == str(directory / "sdk-fixture")
             and sdk_raw["workspace"] == str(directory / "sdk-fixture/workspace")
             and sdk_raw["databasePath"] == str(directory / "sdk-fixture/index.sqlite"),
             "the SDK fixture escaped its exact owned attempt")
    _same(sdk_raw["clock"], {"owner": "time.time_ns", "requestedNowMs": case["input"]["nowMs"],
          "clockFunctionReplaced": True, "actualNowMs": case["input"]["nowMs"],
          "monotonicUnchanged": True, "sleepUnchanged": True, "originalClockRestored": True},
          "the SDK clock fixture changed scheduler ownership or was not restored")
    names = {"SQLiteMemoryStore.__init__", "SQLiteMemoryStore.reindex", "SQLiteMemoryStore._reindex_locked",
             "SQLiteMemoryStore.search", "SQLiteMemoryStore._search_candidates", "SQLiteMemoryStore._provider_identities",
             "SQLiteMemoryStore.read_published_index", "decode_memory_embedding", "resolve_memory_index_provider_identities"}
    _require(len(sdk_raw["owners"]) == len(names) and {row["name"] for row in sdk_raw["owners"]} == names,
             "an actual SDK owner is missing or duplicated")
    for owner in sdk_raw["owners"]:
        path = Path(owner["path"])
        _require(path.is_relative_to(ROOT / "memory_core") and not path.is_symlink()
                 and hashlib.sha256(path.read_bytes()).hexdigest() == owner["sha256"], "an actual SDK owner source changed")
    _operations(case, sdk_raw, sdk_public, _sdk_physical(sdk_raw, directory), False)
    return native_public, sdk_public
