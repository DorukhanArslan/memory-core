"""Drive real SDK indexing and query owners with an observed fixture embedder.

The fixture supplies provider responses and external failures, never cache-hit
decisions. Complete API outcomes and index state remain private observations;
the declared shared boundary is cache, effective identity and embedding calls.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from dataclasses import fields, is_dataclass
import hashlib
import inspect
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
import traceback
from unittest.mock import patch

from equivalence.forget_lineage_sdk import _owned, _write
from equivalence.recall_signals_sdk import _capture, _database
from memory_core.bootstrap._js import js_utf8_encode
from memory_core.config import MemoryConfig
from memory_core.index.embedding_cache import decode_memory_embedding
from memory_core.index.hybrid import HYBRID_METADATA_MISSING
from memory_core.index.identity import resolve_memory_index_provider_identities
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace

PROVIDER = "deterministic-embedding-fixture"
TRIGGER = "embedding_fixture_publication_failure"
TRIGGER_SQL = (
    "CREATE TRIGGER embedding_fixture_publication_failure BEFORE INSERT ON chunks "
    "BEGIN SELECT RAISE(ABORT,'embedding fixture publication failure'); END"
)


def _wire(value):
    if value is HYBRID_METADATA_MISSING:
        return {"type": "HYBRID_METADATA_MISSING"}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"type": "bytes", "hex": value.hex()}
    if is_dataclass(value):
        return {field.name: _wire(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_wire(item) for item in value]
    return value


def _failure(error):
    return {"name": type(error).__name__, "module": type(error).__module__, "message": str(error),
            "args": _wire(error.args), "properties": _wire(vars(error)),
            "traceback": "".join(traceback.format_exception(error)),
            **{key: getattr(error, key) for key in ("sqlite_errorcode", "sqlite_errorname")
               if hasattr(error, key)}}


def _returned(value):
    return {"type": type(value).__name__, "value": _wire(value)}


def _owner(function):
    path = Path(inspect.getfile(function)).resolve()
    return {"name": function.__qualname__, "module": function.__module__, "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _sources(workspace):
    rows = []
    for path in sorted(workspace.rglob("*")):
        if path.is_symlink():
            raise ValueError("An embedding fixture source is a symlink")
        if not path.is_file():
            continue
        payload, stat = path.read_bytes(), path.stat()
        rows.append({"path": path.relative_to(workspace).as_posix(), "absolutePath": str(path),
                     "bytes": {"hex": payload.hex(), "size": len(payload),
                               "sha256": hashlib.sha256(payload).hexdigest()},
                     "identity": {"device": str(stat.st_dev), "inode": str(stat.st_ino),
                                  "size": stat.st_size, "mtimeNs": str(stat.st_mtime_ns),
                                  "ctimeNs": str(stat.st_ctime_ns)}})
    return rows


class Error(RuntimeError):
    """The controlled provider fixture's Error domain, not a core error adapter."""

    def __init__(self, message, *, status=None, retry_after_ms=None):
        super().__init__(message)
        if status is not None:
            self.status = status
        if retry_after_ms is not None:
            self.retryAfterMs = retry_after_ms


class _Provider:
    def __init__(self, owners, profile):
        self.owners, self.profile = owners, deepcopy(profile)
        self.provider_id, self.model = profile["id"], profile["model"]
        self.dimensions = profile["dimensions"]
        self.control = {}
        self.document_ordinal = self.query_ordinal = 0
        self.document_failures = self.query_failures = 0

    def cache_key_data(self):
        value = deepcopy(self.profile["cacheKeyData"])
        self.owners.raw_calls.append({"owner": "EmbeddingProvider.cache_key_data", "returnValue": value})
        return value

    def index_identity_aliases(self):
        value = deepcopy(self.profile.get("indexIdentityAliases", []))
        self.owners.raw_calls.append({"owner": "EmbeddingProvider.index_identity_aliases", "returnValue": value})
        return value

    def configure(self, control):
        self.control = deepcopy(control)
        self.document_ordinal = self.query_ordinal = 0
        self.document_failures = control.get("documentFailures", 0)
        self.query_failures = control.get("queryFailures", 0)

    def _vector(self, text, dimensions):
        values = [1, len(js_utf8_encode(text))]
        return values + [0.5] if dimensions == 3 else values

    def _call(self, kind, inputs):
        if kind == "document":
            self.document_ordinal += 1
            ordinal = self.document_ordinal
        else:
            self.query_ordinal += 1
            ordinal = self.query_ordinal
        receipt = {"kind": kind, "provider": self.provider_id, "model": self.model,
                   "inputs": deepcopy(inputs), "completed": False}
        raw = {"owner": "embed_documents" if kind == "document" else "embed_query",
               "operationIndex": self.owners.operation_index, "operationCallOrdinal": ordinal,
               "arguments": [deepcopy(inputs)] if kind == "document" else [inputs[0]],
               "control": deepcopy(self.control), "sourcesBefore": _sources(self.owners.workspace),
               "databaseBefore": _database(self.owners.database)}
        self.owners.provider_raw_calls.append(raw)
        self.owners.provider_calls.append(receipt)
        try:
            mutation = self.control.get("mutateOnDocumentCall")
            if kind == "document" and mutation and ordinal == mutation["call"]:
                raw["mutation"] = []
                for name, text in mutation["files"].items():
                    raw["mutation"].append(self.owners.write_source(name, text))
            if kind == "document":
                if self.control.get("maxItems") is not None and len(inputs) > self.control["maxItems"]:
                    raise Error("input array max " + str(self.control["maxItems"]), status=400)
                if self.control.get("failText") and any(self.control["failText"] in text for text in inputs):
                    raise Error("embedding fixture terminal document failure", status=400)
                if self.document_failures:
                    self.document_failures -= 1
                    raise Error("embedding fixture transient document failure", status=503, retry_after_ms=0)
                dimensions = 3 if self.control.get("response") == "dimensions-3" else self.dimensions
                result = [] if self.control.get("response") == "empty" else [self._vector(text, dimensions) for text in inputs]
            else:
                if self.query_failures:
                    self.query_failures -= 1
                    raise Error("embedding fixture transient query failure", status=503, retry_after_ms=0)
                result = self._vector(inputs[0], self.dimensions)
            raw["returnValue"] = _returned(result)
            receipt.update(completed=True, returnValue=deepcopy(result))
            return result
        except BaseException as error:
            raw["error"] = _failure(error)
            receipt["error"] = {"name": type(error).__name__, "message": str(error),
                                **{key: getattr(error, key) for key in ("status", "retryAfterMs") if hasattr(error, key)}}
            raise
        finally:
            raw["sourcesAfter"] = _sources(self.owners.workspace)
            raw["databaseAfter"] = _database(self.owners.database)
            raw["semanticReceipt"] = deepcopy(receipt)
            with self.owners.provider_sink.open("a", encoding="utf8") as stream:
                stream.write(json.dumps(receipt, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")

    def embed_documents(self, texts):
        return self._call("document", texts)

    def embed_query(self, text):
        return self._call("query", [text])


class _Owners:
    def __init__(self, root, value):
        self.root, self.value = root, value
        self.workspace = root / "workspace"
        self.workspace.mkdir(parents=True)
        self.database = root / "index.sqlite"
        self.provider_sink = root / "provider-calls.jsonl"
        self.now = value["nowMs"]
        self.operation_index = -1
        self.provider_calls, self.provider_raw_calls, self.raw_calls = [], [], []
        self.selected_provider = value["provider"]
        self.cache_enabled = value["cacheEnabled"]
        self.config = MemoryConfig(workspace_dir=self.workspace, store_path=self.database)
        self.memory_workspace = MemoryWorkspace(self.workspace)
        for name, text in value["files"].items():
            self.write_source(name, text)
        self.reopen({})

    def write_source(self, name, text):
        path = _owned(self.workspace, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        returned = path.write_bytes(text.encode("utf8"))
        os.utime(path, ns=(self.now * 1_000_000, self.now * 1_000_000))
        return {"path": name, "absolutePath": str(path), "text": text,
                "actualWriteReturn": returned, "mtimeNs": str(path.stat().st_mtime_ns)}

    def reopen(self, operation):
        self.selected_provider = operation.get("provider", self.selected_provider)
        self.cache_enabled = operation.get("cacheEnabled", self.cache_enabled)
        self.provider = _Provider(self, self.value["providers"][self.selected_provider])
        self.store = SQLiteMemoryStore(self.config, self.provider, embedding_cache_enabled=self.cache_enabled)
        self.raw_calls.append({"owner": "SQLiteMemoryStore", "arguments": {
            "config": _wire(self.config), "providerProfile": deepcopy(self.provider.profile),
            "embedding_cache_enabled": self.cache_enabled},
            "instanceObservation": {"class": type(self.store).__qualname__, "path": str(self.store.path)}})

    def state(self):
        identities = self.store._provider_identities()
        key_data = self.provider.cache_key_data()
        aliases = self.provider.index_identity_aliases()
        identity = {"provider": self.provider.provider_id, "model": self.provider.model,
                    "providerKey": identities[0]["providerKey"], "cacheKeyData": key_data,
                    "indexIdentityAliases": [{"model": alias["model"], "cacheKeyData": deepcopy(alias["cacheKeyData"]),
                        "providerKey": resolve_memory_index_provider_identities(
                            {"id": self.provider.provider_id, "model": alias["model"]},
                            cache_key_data=alias["cacheKeyData"])[0]["providerKey"]}
                        for alias in aliases], "cacheEnabled": self.store.embedding_cache_enabled}
        with closing(self.store.connect()) as db:
            cursor = db.execute("SELECT provider,model,provider_key,hash,embedding,dims,updated_at "
                                "FROM memory_embedding_cache ORDER BY provider,model,provider_key,hash")
            cache = [{"provider": provider, "model": model, "provider_key": provider_key, "hash": chunk_hash,
                      "embedding": decode_memory_embedding(payload), "embeddingHex": payload.hex(),
                      "dims": dims, "updated_at": updated_at}
                     for provider, model, provider_key, chunk_hash, payload, dims, updated_at in cursor]
        return {"cache": cache, "identity": identity, "providerCalls": deepcopy(self.provider_calls)}

    def schema(self):
        with closing(self.store.connect()) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")]

    def install_trigger(self):
        with closing(self.store.connect()) as db:
            db.execute(TRIGGER_SQL)
        return {"name": TRIGGER, "statement": TRIGGER_SQL, "databasePath": str(self.database),
                "schemaBeforeDispatch": self.schema()}

    def drop_trigger(self):
        with closing(self.store.connect()) as db:
            db.execute("DROP TRIGGER " + TRIGGER)
        return self.schema()

    def invoke(self, operation, actual):
        name = operation["op"]
        if name in {"sync", "query"}:
            self.provider.configure(operation.get("providerControl", {}))
        if name == "sync":
            actual["owner"] = "SQLiteMemoryStore.reindex"
            actual["arguments"] = {"workspace": str(self.workspace), "force": operation.get("force", False)}
            return self.store.reindex(self.memory_workspace, force=operation.get("force", False))
        if name == "query":
            actual["owner"] = "SQLiteMemoryStore.search"
            actual["arguments"] = {"query": operation["query"], "max_results": 6, "min_score": 0}
            results = self.store.search(operation["query"], max_results=6, min_score=0)
            actual["searchPayloads"] = [result.to_payload() for result in results]
            return results
        if name == "write":
            actual["owner"] = "_Owners.write_source"
            actual["arguments"] = {"path": operation["path"], "text": operation["text"]}
            return self.write_source(operation["path"], operation["text"])
        if name == "rename":
            actual["owner"] = "Path.rename"
            actual["arguments"] = {"path": operation["path"], "to": operation["to"]}
            source, destination = _owned(self.workspace, operation["path"]), _owned(self.workspace, operation["to"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            result = source.rename(destination)
            os.utime(destination, ns=(self.now * 1_000_000, self.now * 1_000_000))
            return result
        if name == "remove":
            actual["owner"] = "Path.unlink"
            actual["arguments"] = {"path": operation["path"]}
            return _owned(self.workspace, operation["path"]).unlink()
        if name == "reopen":
            actual["owner"] = "_Owners.reopen"
            actual["arguments"] = deepcopy(operation)
            return self.reopen(operation)
        raise ValueError("Unknown frozen embedding lifecycle operation")


def _run(value, directory):
    from equivalence.embedding_cache_lifecycle import validate_input

    validate_input(value)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    root = directory / "sdk-fixture"
    if root.exists():
        raise ValueError("Embedding lifecycle requires a fresh SDK evidence directory")
    original_clock, original_monotonic, original_sleep = time.time_ns, time.monotonic, time.sleep
    now = [value["nowMs"]]
    raw = {"kind": "embedding-cache-lifecycle-sdk-raw", "input": deepcopy(value),
           "fixtureRoot": str(root), "workspace": str(root / "workspace"), "databasePath": str(root / "index.sqlite"),
           "owners": [_owner(function) for function in (SQLiteMemoryStore.__init__, SQLiteMemoryStore.reindex,
               SQLiteMemoryStore._reindex_locked, SQLiteMemoryStore.search, SQLiteMemoryStore._search_candidates,
               SQLiteMemoryStore._provider_identities, SQLiteMemoryStore.read_published_index, decode_memory_embedding,
               resolve_memory_index_provider_identities)],
           "clock": {"owner": "time.time_ns", "requestedNowMs": value["nowMs"], "clockFunctionReplaced": False,
                     "monotonicUnchanged": True, "sleepUnchanged": True, "originalClockRestored": False},
           "operations": [], "physical": [], "closed": False}
    try:
        with patch("time.time_ns", lambda: now[0] * 1_000_000):
            raw["clock"].update(clockFunctionReplaced=time.time_ns is not original_clock,
                                actualNowMs=time.time_ns() // 1_000_000,
                                monotonicUnchanged=time.monotonic is original_monotonic,
                                sleepUnchanged=time.sleep is original_sleep)
            owners = _Owners(root, value)
            raw["calls"], raw["providerRawCalls"] = owners.raw_calls, owners.provider_raw_calls
            initial = owners.state()
            raw["initialState"] = deepcopy(initial)
            raw["initialIndex"] = _wire(owners.store.read_published_index())
            raw["physical"].append(_capture(root, directory, "initial"))
            observations = []
            for index, operation in enumerate(value["operations"]):
                now[0] = owners.now = operation["nowMs"]
                owners.operation_index = index
                actual = {"operation": deepcopy(operation), "sourcesBefore": _sources(owners.workspace)}
                trigger = owners.install_trigger() if operation.get("publicationFailure") else None
                if trigger is not None:
                    actual["trigger"] = trigger
                try:
                    returned = owners.invoke(operation, actual)
                    actual["apiOutcome"] = {"kind": "return", "returnValue": _returned(returned)}
                except BaseException as error:
                    actual["apiOutcome"] = {"kind": "throw", "error": _failure(error)}
                actual["sourcesAfter"] = _sources(owners.workspace)
                actual["indexState"] = _wire(owners.store.read_published_index())
                observed = {"operation": deepcopy(operation), "state": owners.state()}
                actual["observed"] = deepcopy(observed)
                raw["operations"].append(actual)
                observations.append(observed)
                raw["physical"].append(_capture(root, directory, f"operation-{index}"))
                if trigger is not None:
                    trigger["afterDropSchema"] = owners.drop_trigger()
            raw["closed"] = True
            return {"provider": PROVIDER, "before": initial, "observations": observations}
    finally:
        raw["clock"]["originalClockRestored"] = time.time_ns is original_clock
        _write(directory / "python-raw.json", [raw])


def run_embedding_cache_lifecycle(value, *, evidence_directory=None):
    if evidence_directory is not None:
        return _run(value, evidence_directory)
    with TemporaryDirectory(prefix="memory-embedding-cache-sdk-") as directory:
        return _run(value, directory)
