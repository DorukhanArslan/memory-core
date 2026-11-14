"""Original SDK actors for the frozen forget/index-fence process family.

This module is a driver, not a memory implementation. Each independently owned
process constructs the ordinary managed on-search store and calls the original
forget, search, sync and promotion APIs. Observers append to memory only. The
explicit functional gates may wait for a controller release; no gate substitutes
a producer, its expected revision, a transaction, or its public return.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import fields, is_dataclass
import hashlib
import inspect
import json
import math
import os
from pathlib import Path, PurePosixPath
import select
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from types import CodeType


ROOT = Path(__file__).resolve().parents[1]
WALL_MS = 1794614400000
PROCESS_TIMEOUT_SECONDS = 90
GATE_TIMEOUT_SECONDS = 30
BOUNDARIES = frozenset({
    "rebuild.revision-captured-before-publication",
    "publication.fence-checked-before-table-writes",
    "forget.marker-committed-before-purge",
    "search.keyword-result-before-enrichment",
    "promotion.model-planning-before-final-lock",
    "promotion.source-planned-before-final-lock",
    "forget.marker-commit-or-original-workspace-or-writer-wait",
})


def _serialized(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _encode(value):
    """Retain values, including raw scalar types, without invoking callbacks."""
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        return value if math.isfinite(value) else {"nonFiniteFloat": repr(value)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"bytesHex": value.hex(), "bytes": len(value)}
    if isinstance(value, sqlite3.Connection):
        return {"module": type(value).__module__, "className": type(value).__qualname__,
                "objectId": str(id(value)), "sqliteConnection": True}
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            return {"mappingEntries": [[_encode(key), _encode(item)] for key, item in value.items()]}
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return {"setValues": sorted((_encode(item) for item in value), key=_serialized)}
    if callable(value):
        return {"callable": True, "module": getattr(value, "__module__", type(value).__module__),
                "qualname": getattr(value, "__qualname__", type(value).__qualname__), "objectId": str(id(value))}
    return {"module": type(value).__module__, "className": type(value).__qualname__,
            "objectId": str(id(value)), "attributes": _encode(vars(value)) if hasattr(value, "__dict__") else None}


def _type_identity(cls):
    mro = []
    for parent in cls.__mro__:
        try:
            source = inspect.getsourcefile(parent)
        except TypeError:
            source = None
        path = Path(source).resolve() if source else None
        mro.append({"module": parent.__module__, "name": parent.__qualname__,
            "sourceFile": str(path) if path else None,
            "sourceSha256": hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None})
    return {"module": cls.__module__, "name": cls.__qualname__, "mro": mro}


def _error(error, conflict_type=None):
    result = {"module": type(error).__module__, "name": type(error).__qualname__,
            "message": str(error), "args": _encode(error.args),
            "isTypedConflict": bool(conflict_type is not None and isinstance(error, conflict_type)),
            "traceback": "".join(traceback.format_exception(error))}
    result["publicFields"] = {"message": str(error), **_encode(vars(error))}
    result["exceptionType"] = _type_identity(type(error))
    result["typedConflictClass"] = _type_identity(conflict_type) if conflict_type is not None else None
    for key in ("code", "sqlite_errorcode", "sqlite_errorname"):
        if hasattr(error, key):
            result["publicFields"][key] = _encode(getattr(error, key))
    if hasattr(error, "code"):
        result["code"] = _encode(error.code)
    try:
        result["classSource"] = inspect.getsourcefile(type(error))
    except TypeError:
        result["classSource"] = None
    return result


def _safe_path(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("A fixture path must be a nonempty canonical relative path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative:
        raise ValueError("A fixture path must be a canonical relative path")
    target = Path(root) / relative
    if not target.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("A fixture path escaped its exact owner")
    return target


def _code_identity(code):
    path = Path(code.co_filename).resolve()
    return {"qualname": code.co_qualname, "firstLine": code.co_firstlineno,
            "file": str(path), "sourceSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytecodeSha256": hashlib.sha256(code.co_code).hexdigest()}


def _sdk_sources():
    digest, rows = hashlib.sha256(), []
    for path in sorted((ROOT / "memory_core").rglob("*.py")):
        if path.is_symlink():
            raise RuntimeError("SDK source identity cannot follow an alias")
        relative, payload = path.relative_to(ROOT).as_posix(), path.read_bytes()
        digest.update(relative.encode() + b"\0" + payload + b"\0")
        rows.append({"path": relative, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    return {"root": str(ROOT), "sourceFiles": len(rows), "sourceSha256": digest.hexdigest(), "files": rows}


def _loaded_sdk():
    return [{"module": name, "path": str(Path(module.__file__).resolve()),
             "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
            for name, module in sorted(sys.modules.items()) if name.startswith("memory_core")
            and getattr(module, "__file__", None) and Path(module.__file__).is_file()]


def _literal(value):
    from equivalence.forget_index_fence_v2 import build_cases

    for case in build_cases():
        if case.get("input") == value:
            return case
    raise ValueError("The SDK forget/index-fence actor requires an exact frozen input")


class _FunctionalGate:
    """A declared fixture barrier; its wait does not replace an original call."""

    def __init__(self, specification):
        self.specification = deepcopy(specification)
        self.reached = threading.Event()
        self.released = threading.Event()
        self.armed = False
        self.hits = []

    def arm(self):
        if self.armed or self.reached.is_set():
            raise ValueError("A functional gate may be armed only once")
        self.armed = True

    def hit(self, receipt):
        if not self.armed or self.reached.is_set():
            return
        self.hits.append(deepcopy(receipt))
        self.reached.set()
        if self.specification.get("pause") is False:
            return
        if not self.released.wait(GATE_TIMEOUT_SECONDS):
            raise TimeoutError("The declared functional gate exceeded its bounded release deadline")

    def snapshot(self):
        return {"specification": deepcopy(self.specification), "armed": self.armed,
                "reached": self.reached.is_set(), "released": self.released.is_set(), "hits": deepcopy(self.hits)}


class _OriginalObserver:
    """Source-code and exact-receiver witnesses with no observer lock or I/O.

    ``codes`` maps original CodeType objects to {name, receiver}. A receiver is a
    frame-local parameter whose exact object must have been bound. ``None``
    accepts a receiverless function only inside an already labelled original
    worker scope. Strong owner/context references prevent object-id reuse.
    """

    def __init__(self, codes, *, gate_callback=None, sql_callback=None,
                 functional_profile=None, functional_trace=None):
        self.codes = dict(codes)
        self.owners = {}
        self.local = threading.local()
        self.events, self.exceptions, self.sql = [], [], []
        self.sql_executions = []
        self.connections = {}
        self.contexts = {}
        self.gate_callback = gate_callback
        self.sql_callback = sql_callback
        self.functional_profile, self.functional_trace = functional_profile, functional_trace
        self._sequence = 0

    def bind_owner(self, owner, label):
        self.owners[id(owner)] = (owner, label)

    def event(self, event_name, **values):
        # CPython's call event and list append run under its interpreter lock.
        # No observer mutex is introduced into an original execution lane.
        self._sequence += 1
        row = {"sequence": self._sequence, "event": event_name, "pid": os.getpid(),
               "threadId": threading.get_ident(), "atNs": str(time.monotonic_ns()), **values}
        self.events.append(row)
        return row

    @contextmanager
    def call_scope(self, label, kind, wall_ms=None):
        previous = getattr(self.local, "scope", None)
        self.local.scope = {"label": label, "kind": kind}
        if wall_ms is not None:
            self.local.scope["wallClockNowMs"] = wall_ms
        try:
            yield
        finally:
            self.local.scope = previous

    def _match(self, frame):
        specification = self.codes.get(frame.f_code)
        if specification is None:
            return None
        receiver_key = specification.get("receiver")
        receiver = frame.f_locals.get(receiver_key) if receiver_key else None
        bound = self.owners.get(id(receiver)) if receiver_key else None
        if receiver_key and (bound is None or bound[0] is not receiver):
            return None
        scope = getattr(self.local, "scope", None)
        context = frame.f_locals.get("context")
        store = frame.f_locals.get("store")
        if scope is None and context is not None and store is not None:
            saved = self.contexts.get((id(context), id(store)))
            if saved is not None and saved[0] is context and saved[1] is store:
                scope = saved[2]
        if scope is None:
            stack = getattr(self.local, "stack", ())
            scope = stack[-1][2] if stack else None
        if scope is None:
            return None
        return specification, receiver, bound[1] if bound else None, scope

    def profile(self, frame, event, returned):
        if self.functional_profile is not None:
            self.functional_profile(frame, event, returned)
        if event in {"c_call", "c_return", "c_exception"}:
            self._profile_sql(frame, event, returned)
            return
        if event not in {"call", "return"}:
            return
        match = self._match(frame)
        if match is None:
            return
        specification, receiver, owner_label, scope = match
        stack = getattr(self.local, "stack", ())
        if event == "call":
            if "context" in frame.f_locals and "store" in frame.f_locals:
                context, store = frame.f_locals["context"], frame.f_locals["store"]
                if context is not None and id(store) in self.owners:
                    self.contexts[(id(context), id(store))] = (context, store, scope)
            call = self.event("original-call", name=specification["name"],
                callLabel=scope["label"], callKind=scope["kind"], owner=owner_label,
                receiverObjectId=str(id(receiver)) if receiver is not None else None,
                exactReceiver=receiver is not None, code=specification.get("code"),
                arguments={key: _encode(value) for key, value in frame.f_locals.items()
                           if key not in {"self", "context", "store", "workspace", "config", "origins", "ledger"}})
            self.local.stack = (*stack, (id(frame), call, scope))
            if self.gate_callback is not None:
                self.gate_callback(frame, event, returned, call, scope)
        else:
            call = next((item[1] for item in reversed(stack) if item[0] == id(frame)), None)
            if call is None:
                return
            row = self.event("original-return", callSequence=call["sequence"], name=specification["name"],
                callLabel=scope["label"], owner=owner_label, returned=_encode(returned),
                frameScalars={key: _encode(frame.f_locals[key]) for key in (
                    "live", "expected", "expected_revision", "expected_fence_revision", "current_revision",
                    "expected_fence", "generation", "mutation_generation")
                    if key in frame.f_locals and (frame.f_locals[key] is None
                        or type(frame.f_locals[key]) in (bool, int, float, str))})
            if isinstance(returned, sqlite3.Connection):
                self._bind_connection(returned, scope, specification["name"])
            if self.gate_callback is not None:
                self.gate_callback(frame, event, returned, row, scope)
            self.local.stack = tuple(item for item in stack if item[0] != id(frame))

    def _bind_connection(self, db, scope, source):
        if self.connections.get(id(db)) is db:
            return
        self.connections[id(db)] = db
        self.bind_owner(db, "sqlite-connection")
        connection_id = str(id(db))

        def trace(statement):
            row = self.event("original-sql", connectionId=connection_id,
                             callLabel=scope["label"], source=source, statement=statement)
            pending = getattr(self.local, "sql_stack", ())
            if pending and pending[-1][0] is db:
                row["executionSequence"] = pending[-1][1]["sequence"]
                pending[-1][1].setdefault("statements", []).append(statement)
            self.sql.append(row)
            if self.sql_callback is not None:
                self.sql_callback(db, row, scope)

        db.set_trace_callback(trace)

    def _profile_sql(self, frame, event, function):
        db = getattr(function, "__self__", None)
        if not isinstance(db, sqlite3.Connection):
            return
        method = getattr(function, "__name__", None)
        if method not in {"execute", "executemany", "executescript", "commit", "rollback", "close"}:
            return
        match = self._match(frame)
        if match is None:
            return
        specification, _, _, scope = match
        if id(db) not in self.connections:
            # The first original execute already carries its real C receiver.
            # Attach observation before that execute, including schema creation
            # inside _open_write before the Python connection factory returns.
            if specification["name"] not in {"SQLiteMemoryStore.connect", "MemoryEntryOriginLedger._open_write"}:
                return
            self._bind_connection(db, scope, specification["name"])
        stack = getattr(self.local, "sql_stack", ())
        if event == "c_call":
            row = self.event("original-sql-c-call", connectionId=str(id(db)), method=method,
                callLabel=scope["label"], source=specification["name"], parentCode=specification.get("code"))
            self.sql_executions.append(row)
            self.local.sql_stack = (*stack, (db, row))
        elif stack and stack[-1][0] is db:
            pending = stack[-1][1]
            row = self.event("original-sql-c-return" if event == "c_return" else "original-sql-c-exception",
                connectionId=str(id(db)), executionSequence=pending["sequence"], callLabel=scope["label"], method=method)
            pending.update(finishedSequence=row["sequence"], finishedAtNs=row["atNs"],
                           settlement="returned" if event == "c_return" else "raised")
            self.local.sql_stack = stack[:-1]

    def exception_trace(self, frame, event, argument):
        if self.functional_trace is not None:
            self.functional_trace(frame, event, argument)
        match = self._match(frame)
        if match is None:
            return None
        if event == "exception":
            _, error, _ = argument
            specification, _, owner_label, scope = match
            row = self.event("original-exception", name=specification["name"], owner=owner_label,
                callLabel=scope["label"], error={"module": type(error).__module__,
                    "name": type(error).__qualname__, "message": str(error), "args": _encode(error.args)})
            self.exceptions.append(row)
        return self.exception_trace


def _validate_actor_command(command, declared_gates):
    if not isinstance(command, dict) or type(command.get("id")) is not int:
        raise ValueError("An actor command requires an integer id")
    allowed = {"acquire", "seed", "call", "await-call", "arm-gate", "await-gate", "release-gate", "set-wall-clock",
               "snapshot", "close", "observe", "stop"}
    if command.get("operation") not in allowed:
        raise ValueError("The actor command is not in the frozen protocol")
    if command["operation"] in {"arm-gate", "await-gate", "release-gate"}:
        if command.get("gate") not in declared_gates:
            raise ValueError("The functional gate was not declared in the frozen input")
    return command


def _nested_codes(code):
    yield code
    for item in code.co_consts:
        if isinstance(item, CodeType):
            yield from _nested_codes(item)


def _original_bindings():
    """Resolve original loaded functions, not wrappers or recompiled source."""
    from memory_core.consolidation.forget import forget_memory_entries, purge_memory_index
    from memory_core.consolidation.origins import IndexRevisionFence, MemoryEntryOriginLedger
    from memory_core.consolidation.promotion import run_short_term_promotion, rank_short_term_promotion_candidates
    from memory_core.consolidation.recall import record_short_term_recalls
    from memory_core.consolidation import promotion
    from memory_core.host.managed_index import ManagedSQLiteMemoryStore
    from memory_core.index.sqlite_store import SQLiteMemoryStore, read_index_source
    from memory_core.index import sqlite_store
    from memory_core.index.publication import write_prepared_index
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.tools.memory_search import execute_memory_search_tool, _run_memory_search_tool
    from memory_core.tools.search_factory import MemorySearchTool
    from memory_core import atomic_publication
    from memory_core.consolidation.artifacts import write_dreams_file_atomic
    from memory_core.index.temporal_decay import apply_temporal_decay_to_hybrid_results

    methods = [(SQLiteMemoryStore, name) for name in (
        "connect", "reindex", "reindex_sources", "_reindex_locked", "publish_prepared_index",
        "search", "_search_candidates", "_search_keyword_with_fallback", "attach_recall_metadata", "_on_search_snapshot")]
    methods += [(ManagedSQLiteMemoryStore, name) for name in ("reindex", "reindex_sources", "search", "close")]
    methods += [(MemoryEntryOriginLedger, name) for name in (
        "_open_write", "_open_read", "record", "delete", "record_session_tombstones_if_lineage_current",
        "list_session_tombstones", "index_revision")]
    methods += [(IndexRevisionFence, name) for name in ("read", "assert_unchanged", "assert_unchanged_in", "bump", "bump_in")]
    methods += [(MemorySessionCatalog, name) for name in ("_connect", "upsert_session", "replace_events", "append_message", "snapshot")]
    methods += [(MemorySearchTool, "execute")]
    codes = {}
    for owner, name in methods:
        function = getattr(owner, name)
        codes[function.__code__] = {"name": f"{owner.__name__}.{name}", "receiver": "self",
                                    "code": _code_identity(function.__code__)}
    for function, receiver in ((forget_memory_entries, "store"), (purge_memory_index, "store"),
        (run_short_term_promotion, "store"), (rank_short_term_promotion_candidates, None),
        (record_short_term_recalls, None),
        (execute_memory_search_tool, "store"), (_run_memory_search_tool, "store"),
        (write_prepared_index, "db"), (promotion.acquire_short_term_promotion_lock, None)):
        codes[function.__code__] = {"name": function.__qualname__, "receiver": receiver,
                                    "code": _code_identity(function.__code__)}
    for function in (SQLiteMemoryStore._reindex_locked, _run_memory_search_tool):
        for code in _nested_codes(function.__code__):
            if code is function.__code__:
                continue
            codes[code] = {"name": code.co_qualname, "receiver": None, "code": _code_identity(code)}
    # The imported publication function must be the original used by the store.
    if sqlite_store.write_prepared_index is not write_prepared_index:
        raise RuntimeError("The SDK index publication owner is not its original imported function")
    for function in (atomic_publication._io, atomic_publication._write_all, atomic_publication._commit,
        atomic_publication.append_memory_content, atomic_publication._write_existing_in_place,
        write_dreams_file_atomic, apply_temporal_decay_to_hybrid_results, read_index_source):
        codes[function.__code__] = {"name": function.__qualname__, "receiver": None,
                                    "code": _code_identity(function.__code__)}
    return codes


def _rows(path):
    path = Path(path)
    if not path.exists():
        payload = {"dbPath": str(path), "readOnly": True, "exists": False, "schema": [], "tables": {}}
        wire = _serialized(payload)
        return {**payload, "serializedJSON": wire, "sha256": hashlib.sha256(wire.encode()).hexdigest()}
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)) as db:
        db.execute("BEGIN")
        schema = [{"type": row[0], "name": row[1], "table": row[2], "sql": row[3]}
                  for row in db.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")]
        tables = {}
        for row in schema:
            if row["type"] != "table":
                continue
            cursor = db.execute('SELECT * FROM "' + row["name"].replace('"', '""') + '"')
            names = [column[0] for column in cursor.description]
            actual = [_encode(dict(zip(names, item, strict=True))) for item in cursor]
            tables[row["name"]] = {"columns": names, "rows": actual, "rowCount": len(actual)}
        payload = {"dbPath": str(path), "readOnly": True, "exists": True, "schema": schema, "tables": tables}
        wire = _serialized(payload)
        return {**payload, "serializedJSON": wire, "sha256": hashlib.sha256(wire.encode()).hexdigest()}


def _full_stat(info):
    """Retain every supplied OS stat field without assuming another platform's set."""
    return {name: str(getattr(info, name)) for name in dir(info) if name.startswith("st_")}


def _files(root):
    entries = []
    if not root.exists():
        return entries
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if path.is_symlink():
            entries.append({"path": path.relative_to(root).as_posix(), "kind": "symlink",
                            "target": os.readlink(path), "stat": _full_stat(info)})
        elif path.is_file():
            payload = path.read_bytes()
            entries.append({"path": path.relative_to(root).as_posix(), "kind": "file", "hex": payload.hex(),
                "text": payload.decode("utf8", errors="replace"), "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload), "mtimeNs": str(info.st_mtime_ns), "mode": info.st_mode,
                "device": info.st_dev, "inode": info.st_ino, "stat": _full_stat(info),
                "statAfter": _full_stat(path.lstat())})
    return entries


def _storage(value, directory):
    storage = value["storageProfile"]
    if isinstance(storage, str):
        name = storage
        shared = "split" not in name.lower()
        fenced = "unfenced" not in name.lower()
    else:
        sdk = storage["sdk"]
        name = storage["mapping"]
        shared = sdk["indexAndOrigins"] == "same-database-file"
        fenced = sdk["revisionFence"] == "actual-ledger-revision-fence"
        if sdk["sessionCatalog"] != "separate-database-file" or sdk["catalogTombstoneMirroring"] is not False:
            raise ValueError("The frozen SDK catalog owner must remain separate without tombstone mirroring")
    index = directory / "state" / "index.sqlite"
    return {"name": name, "index": index, "origins": index if shared else directory / "state" / "origins.sqlite",
            "catalog": directory / "state" / "catalog.sqlite", "provenance": directory / "state" / "provenance.sqlite",
            "fenced": bool(fenced), "shared": bool(shared)}


class _SdkActor:
    """One independently killable process and its exact original owner graph."""

    def __init__(self, request):
        self.value, self.directory, self.actor = request["input"], Path(request["directory"]), request["actor"]
        self.before = _sdk_sources()
        self.imported_before = _loaded_sdk()
        self.storage = _storage(self.value, self.directory)
        self.root = self.directory / "workspace"
        self.owner = self.catalog = self.ledger = self.provenance = self.workspace = self.config = None
        self.futures = {}
        self.public_calls = {}
        self.bindings = []
        self.catalog_facts = []
        self.host_events = []
        self.host_event_receipts = []
        self.wall_ms = self.value["clock"]["nowMs"]
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix=f"forget-fence-{self.actor}")
        self.gates = {item["name"]: _FunctionalGate(item) for item in self.value.get("gates", [])
                      if item.get("actor", self.actor) == self.actor}
        if any(gate.specification["boundary"] not in BOUNDARIES for gate in self.gates.values()):
            raise ValueError("An undeclared SDK source boundary was requested")
        self.observer = _OriginalObserver(_original_bindings(), gate_callback=self._boundary,
                                           sql_callback=self._sql_progress)
        self.datetime_clock_calls = []
        self._install_clock_fixtures()
        if _sdk_sources() != self.before:
            raise RuntimeError("SDK sources changed while loading original actors")
        # V2 declares wall and source-file clock controls. Monotonic clocks,
        # waits, timers, deadlines and unrelated filesystem metadata stay real.
        self.real_time = time.time
        time.time = lambda: self.wall_ms / 1000
        sys.setprofile(self.observer.profile)
        threading.setprofile(self.observer.profile)
        sys.settrace(self.observer.exception_trace)
        threading.settrace(self.observer.exception_trace)

    def _active_scope(self):
        scope = getattr(self.observer.local, "scope", None)
        stack = getattr(self.observer.local, "stack", ())
        return scope if scope is not None else stack[-1][2] if stack else None

    def _install_clock_fixtures(self):
        from memory_core import atomic_publication
        from memory_core.consolidation.artifacts import write_dreams_file_atomic
        from memory_core.index import temporal_decay
        from memory_core.index.sqlite_store import read_index_source
        from equivalence.forget_index_fence_sdk_clock import DatetimeClockProxy, OwnedSourceWriteClock

        roles = {atomic_publication._io: "io", atomic_publication._write_all: "write-all",
            atomic_publication._commit: "atomic", atomic_publication.append_memory_content: "append",
            atomic_publication._write_existing_in_place: "in-place", write_dreams_file_atomic: "dreams",
            read_index_source: "source-read"}
        owners = {function.__code__: {"role": role, "code": deepcopy(self.observer.codes[function.__code__]["code"])}
                  for function, role in roles.items()}
        self.source_clock = OwnedSourceWriteClock(root=self.root, actor=self.actor,
            policy=self.value["clock"]["sourceWriteClock"], owners=owners, scope=self._active_scope,
            encode=_encode, full_stat=_full_stat)
        self.observer.functional_profile = self.source_clock.profile
        self.observer.functional_trace = self.source_clock.trace
        declaration = self.value["clock"]["sdkDatetimeClock"]
        if declaration["module"] != temporal_decay.__name__ or declaration["binding"] != "datetime" or declaration["controlledApi"] != "now":
            raise ValueError("The declared datetime clock is not the narrow original temporal-decay binding")
        original_datetime = temporal_decay.datetime
        self.datetime_clock_source = deepcopy(self.observer.codes[temporal_decay.apply_temporal_decay_to_hybrid_results.__code__]["code"])

        def record_datetime(receipt, frame):
            if frame.f_code is not temporal_decay.apply_temporal_decay_to_hybrid_results.__code__:
                raise ValueError("The narrow datetime fallback was invoked outside its original declared source")
            self.datetime_clock_calls.append({**receipt, "scope": deepcopy(self._active_scope()),
                "sourceCode": deepcopy(self.datetime_clock_source), "pid": os.getpid(), "actor": self.actor})

        self.datetime_proxy = DatetimeClockProxy(original_datetime, lambda: self.wall_ms, record_datetime)
        temporal_decay.datetime = self.datetime_proxy
        self.clock_bindings = {"datetime": {"declaration": deepcopy(declaration),
            "module": temporal_decay.__name__, "binding": "datetime", "originalClassObjectId": str(id(original_datetime)),
            "originalClass": _type_identity(original_datetime), "proxyObjectId": str(id(self.datetime_proxy)),
            "proxyClass": _type_identity(type(self.datetime_proxy)), "sourceCode": deepcopy(self.datetime_clock_source),
            "bindingIsExactProxy": temporal_decay.datetime is self.datetime_proxy},
            "sourceWrites": {"declaration": deepcopy(self.value["clock"]["sourceWriteClock"]),
                "owners": list(owners.values()), "syscallsReplaced": False, "extraFsync": False}}

    def _boundary(self, frame, event, returned, row, scope):
        name = self.observer.codes[frame.f_code]["name"]
        public_names = {"forget": "forget_memory_entries", "promotion": "run_short_term_promotion",
            "sync": "ManagedSQLiteMemoryStore.reindex", "search": "MemorySearchTool.execute",
            "recall": "record_short_term_recalls"}
        call = self.public_calls.get(f"{scope['kind']}:{scope['label']}")
        if event == "call" and name == public_names.get(scope["kind"]) and call is not None:
            call.setdefault("apiEntry", {"name": name, "sequence": row["sequence"], "atNs": row["atNs"],
                                          "code": row.get("code")})
        boundary = None
        if event == "call" and name == "SQLiteMemoryStore.publish_prepared_index":
            boundary = "rebuild.revision-captured-before-publication"
        elif event == "call" and name == "write_prepared_index":
            boundary = "publication.fence-checked-before-table-writes"
        elif event == "call" and name == "purge_memory_index" and scope["kind"] == "forget":
            boundary = "forget.marker-committed-before-purge"
        elif (event == "return" and name == "MemoryEntryOriginLedger.record_session_tombstones_if_lineage_current"
              and returned is True and scope["kind"] == "forget"):
            self._hit("forget.marker-commit-or-original-workspace-or-writer-wait", scope,
                      {**row, "progressKind": "actual-marker-COMMIT-returned"}, frame)
        elif (event == "return" and name == "SQLiteMemoryStore._search_keyword_with_fallback"
              and isinstance(returned, list)):
            boundary = "search.keyword-result-before-enrichment"
        elif event == "call" and name == "acquire_short_term_promotion_lock" and scope["kind"] == "promotion":
            boundary = "promotion.source-planned-before-final-lock"
        if boundary is not None:
            self._hit(boundary, scope, row, frame)

    def _sql_progress(self, db, row, scope):
        # This is an original SQL attempt, not a timeout-derived assumption.
        # The paired coordinator keeps the builder's actual index transaction
        # owned until it receives this declared nonpausing progress witness.
        statement = " ".join(row["statement"].strip().upper().split())
        writer_attempt = (statement == "BEGIN IMMEDIATE" or
                          statement.startswith("CREATE TABLE IF NOT EXISTS MEMORY_SESSION_TOMBSTONES"))
        if scope["kind"] != "forget" or not writer_attempt:
            return
        index_connection = row["source"] == "SQLiteMemoryStore.connect"
        shared_origin_connection = self.storage["shared"] and row["source"] == "MemoryEntryOriginLedger._open_write"
        if index_connection or shared_origin_connection:
            self._hit("forget.marker-commit-or-original-workspace-or-writer-wait", scope,
                      {**row, "progressKind": "actual-original-SQLite-writer-attempt"})

    def _hit(self, boundary, scope, row, frame=None):
        for gate in self.gates.values():
            spec = gate.specification
            if (gate.armed and not gate.reached.is_set() and spec["boundary"] == boundary
                    and spec.get("callLabel", scope["label"]) == scope["label"]):
                parents = []
                parent = frame.f_back if frame is not None else None
                while parent is not None:
                    original = self.observer.codes.get(parent.f_code)
                    if original is not None and original["name"] in {
                        "run_short_term_promotion", "SQLiteMemoryStore._reindex_locked"}:
                        expected_owner = parent.f_locals.get("store", parent.f_locals.get("self"))
                        if expected_owner is self.owner:
                            parents.append({"code": deepcopy(original["code"]),
                                "exactStoreObjectId": str(id(self.owner)),
                                "locals": {key: _encode(parent.f_locals[key]) for key in
                                    ("plan", "ranked", "expected_fence", "generation", "mutation_generation", "rebuild")
                                    if key in parent.f_locals}})
                    parent = parent.f_back
                receipt = {"boundary": boundary, "actor": self.actor, "callLabel": scope["label"],
                    "triggerSequence": row["sequence"], "pid": os.getpid(), "threadId": threading.get_ident(),
                    "progressKind": row.get("progressKind"),
                    "sqlExecutionSequence": row.get("executionSequence"), "originalParentFrames": parents,
                    "originalFrame": deepcopy(self.observer.codes[frame.f_code]["code"]) if frame is not None else None,
                    "originalArguments": {key: _encode(frame.f_locals[key]) for key in
                        ("expected_revision", "expected_fence_revision", "prepared", "plan")
                        if frame is not None and key in frame.f_locals}}
                gate.hit(receipt)

    def _host_event(self, event):
        body = deepcopy(event)
        self.host_events.append(body)
        self.host_event_receipts.append({"event": body, "atNs": str(time.monotonic_ns()),
            "actor": self.actor, "pid": os.getpid(),
            "callScope": deepcopy(getattr(self.observer.local, "scope", None))})

    def acquire(self):
        from memory_core.config import MemoryConfig
        from memory_core.flags import FeatureFlags
        from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
        from memory_core.consolidation.origins import MemoryEntryOriginLedger
        from memory_core.host.managed_index import ManagedSQLiteMemoryStore
        from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
        from memory_core.session_catalog import MemorySessionCatalog
        from memory_core.workspace import MemoryWorkspace

        if self.owner is not None and not self.owner.closed:
            raise ValueError("The actor already owns an open original manager")
        self.storage["index"].parent.mkdir(parents=True, exist_ok=True)
        agent = self.value["identity"]["agentId"]
        config = self.value["config"]["memory"]["search"]
        flags = FeatureFlags(vector_search=False)
        self.config = MemoryConfig(self.root, agent_id=agent, store_path=self.storage["index"], flags=flags,
            citation_mode=self.value["config"]["memory"]["citations"],
            session_search=config["experimental"]["sessionMemory"], search_max_results=config["query"]["maxResults"],
            search_min_score=config["query"]["minScore"])
        self.catalog = MemorySessionCatalog(self.storage["catalog"], agent_id=agent, clock_ms=lambda: self.wall_ms)
        self.ledger = MemoryEntryOriginLedger(lambda selected: self.storage["origins"] if selected == agent else
                                              self.directory / "state" / f"origins-{selected}.sqlite")
        self.provenance = MemoryArtifactProvenanceStore(self.storage["provenance"])
        callback = ((lambda sid: bool(self.ledger.list_session_tombstones(agent, [sid])))
                    if self.storage["fenced"] else None)
        self.workspace = MemoryWorkspace(self.root, agent_id=agent, session_catalog=self.catalog,
            is_session_forgotten=callback, index_sources=config.get("sources", ["memory", "sessions"]))
        fence = self.ledger.revision_fence(agent) if self.storage["fenced"] else None
        with self.observer.call_scope("acquire", "acquire"):
            for owner, label in ((self.catalog, "catalog"), (self.ledger, "origins"),
                                 (self.workspace, "workspace"), (self.provenance, "artifact-provenance")):
                self.observer.bind_owner(owner, label)
            if fence is not None:
                self.observer.bind_owner(fence, "revision-fence")
            self.owner = ManagedSQLiteMemoryStore(self.config, self.workspace, revision_fence=fence,
                artifact_provenance=self.provenance, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
                memory_publication="on-search")
            self.observer.bind_owner(self.owner, "managed-index")
            with closing(self.owner.connect()) as db:
                journal_mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        record = {"actor": self.actor, "pid": os.getpid(), "storeObjectId": str(id(self.owner)),
            "storeClass": type(self.owner).__qualname__, "workspaceObjectId": str(id(self.workspace)),
            "catalogObjectId": str(id(self.catalog)), "ledgerObjectId": str(id(self.ledger)),
            "config": _encode(self.config), "storage": _encode(self.storage),
            "memoryPublication": "on-search", "explicitFence": fence is not None,
            "forgottenCallback": callback is not None, "catalogTombstoneMirror": False}
        record["declaredPhysicalPreparation"] = {"statement": "PRAGMA journal_mode=WAL", "returned": journal_mode}
        record["classMro"] = _type_identity(type(self.owner))["mro"]
        record["constructorCode"] = _code_identity(ManagedSQLiteMemoryStore.__init__.__code__)
        self.bindings.append(record)
        return record

    def _facts(self):
        from memory_core.consolidation.forget import SessionInstance, SessionArchive
        from memory_core.consolidation.session_ingestion import SessionCorpusEntry
        from memory_core.session_corpus import MemoryCoreSessionCorpus

        facts = self.value.get("sessionFacts", {})
        session_rows = facts if isinstance(facts, list) else facts.get("instances", facts.get("sessions", []))
        instances = [SessionInstance(agent_id=row.get("agentId", self.config.agent_id),
            session_id=row["sessionId"], session_key=row["sessionKey"], created_at=row.get("entry", {}).get("createdAt", self.wall_ms),
            hook_external_content_source=row.get("hookExternalContentSource"), channel=row.get("channel"),
            account_id=row.get("accountId"), chat_type=row.get("chatType"), participants=tuple(row.get("participants", [])))
            for row in session_rows]
        archives = [SessionArchive(row["sessionId"], row["sessionKey"], row["createdAt"])
                    for row in ([] if isinstance(facts, list) else facts.get("archives", []))]

        def corpus_entries(agent):
            corpus = MemoryCoreSessionCorpus(self.storage["catalog"].parent, agent_id=agent, catalog=self.catalog)
            rows = corpus.discover_entries(include_retained_sqlite=True)
            self.catalog_facts.append({"operation": "discover-actual-corpus-for-forget", "rows": _encode(rows)})
            return [SessionCorpusEntry(agent_id=row["agentId"], session_id=row["sessionId"],
                session_file=row["sessionFile"], session_key=row.get("sessionKey"),
                session_kind=row.get("sessionKind", "interactive"), artifact_kind=row.get("artifactKind", "active-session"),
                transcript_source=row.get("transcriptSource", "file"), store_path=row.get("storePath"),
                updated_at_ms=row.get("updatedAtMs"), generated_by_dreaming_narrative=row.get("generatedByDreamingNarrative", False),
                generated_by_cron_run=row.get("generatedByCronRun", False)) for row in rows]
        return instances, archives, corpus_entries

    def seed(self):
        from memory_core.session_catalog import MemorySessionCatalog

        if self.catalog is None:
            self.storage["catalog"].parent.mkdir(parents=True, exist_ok=True)
            self.catalog = MemorySessionCatalog(self.storage["catalog"],
                agent_id=self.value["identity"]["agentId"], clock_ms=lambda: self.wall_ms)
            self.observer.bind_owner(self.catalog, "catalog")
        result = []
        with self.observer.call_scope("seed", "seed"):
            facts = self.value.get("sessionFacts", {})
            rows = facts if isinstance(facts, list) else facts.get("instances", facts.get("sessions", []))
            for row in rows:
                entry = deepcopy(row.get("entry", {}))
                entry.update(sessionId=row["sessionId"])
                self.catalog.upsert_session(row["sessionKey"], entry)
                for number, message in enumerate(row.get("messages", [])):
                    result.append(_encode(self.catalog.append_message(row["sessionId"], message,
                        session_key=row["sessionKey"], event_id=f"{row['sessionId']}-seed-{number}", now_ms=self.wall_ms)))
                if row.get("events"):
                    self.catalog.replace_events(row["sessionId"], deepcopy(row["events"]),
                                                session_key=row["sessionKey"], updated_at_ms=entry.get("updatedAt", self.wall_ms))
            self.catalog_facts.append({"operation": "prepare-real-host-inputs", "sessions": deepcopy(rows),
                                       "actualSnapshot": _encode(self.catalog.snapshot())})
        return result

    def _invoke(self, label, kind, arguments):
        from memory_core.consolidation.forget import forget_memory_entries
        from memory_core.consolidation.origins import MemoryIndexRevisionConflictError
        from memory_core.consolidation.promotion import PromotionCandidate, rank_short_term_promotion_candidates, run_short_term_promotion
        from memory_core.consolidation.llm_consolidation import DeepConsolidation, LlmConsolidationOptions
        from memory_core.consolidation.recall import record_short_term_recalls
        from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
        from memory_core.tools.memory_search import MemorySearchToolContext
        from memory_core.tools.search_factory import create_memory_search_tool
        from memory_core.session_visibility import SessionVisibilityContext, resolve_memory_search_source_policy

        call = {"label": label, "kind": kind, "arguments": deepcopy(arguments), "actor": self.actor,
                "pid": os.getpid(), "storeObjectId": str(id(self.owner))}
        self.public_calls[f"{kind}:{label}"] = call
        with self.observer.call_scope(label, kind, self.wall_ms):
            call["enterSeq"] = self.observer.event("public-call-enter", label=label, kind=kind)["sequence"]
            try:
                if kind == "search":
                    settings = self.value["config"]["memory"]["search"]
                    policy = resolve_memory_search_source_policy(settings["sources"],
                        remember_across_conversations=settings["rememberAcrossConversations"],
                        configured_session_memory=settings["experimental"]["sessionMemory"])
                    tool = create_memory_search_tool(self.config, self.owner,
                        context=MemorySearchToolContext(clock=lambda: self.wall_ms, source_policy=policy,
                            session_visibility=SessionVisibilityContext.from_catalog(self.catalog)),
                        agent_session_key=self.value["identity"]["requesterSessionKey"],
                        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
                    if tool is None:
                        raise RuntimeError("The original search factory returned no tool")
                    self.observer.bind_owner(tool, "public-memory-search-tool")
                    returned = tool.execute(label, deepcopy(arguments))
                    call["envelope"] = deepcopy(returned)
                    call["details"] = deepcopy(returned["details"])
                    if json.loads(returned["content"][0]["text"]) != returned["details"]:
                        raise RuntimeError("The complete original search text and details disagree")
                elif kind == "sync":
                    returned = self.owner.reindex(self.workspace, force=arguments.get("force", False))
                    call["outcome"] = {"status": "fulfilled", "isTypedConflict": False}
                elif kind == "forget":
                    instances, archives, corpus_entries = self._facts()
                    mapping = {"sessionIds": "session_ids", "hookSources": "hook_sources", "dryRun": "dry_run", "nowMs": "now_ms"}
                    params = {mapping.get(key, key): deepcopy(item) for key, item in arguments.items()}
                    params.setdefault("now_ms", self.wall_ms)
                    report = forget_memory_entries(config=self.config, agent_id=self.config.agent_id,
                        origins=self.ledger, store=self.owner, artifact_provenance=self.provenance,
                        instances=instances, archives=archives, corpus_entries=corpus_entries, **params)
                    returned = report.to_json()
                    call["report"] = deepcopy(returned)
                elif kind == "promotion":
                    selection = arguments["candidateSelection"]
                    candidate_mode = selection["mode"]
                    direct = selection.get("candidates")
                    consolidation_specification = arguments["consolidation"]
                    model_response = (consolidation_specification["completion"]
                                      if consolidation_specification is not None else None)
                    mapping = {"minScore": "min_score", "minRecallCount": "min_recall_count",
                        "minUniqueQueries": "min_unique_queries", "maxAgeDays": "max_age_days",
                        "memoryFileMaxChars": "memory_file_max_chars", "maxPromotedSnippetTokens": "max_promoted_snippet_tokens",
                        "maxPriorEntryLossFraction": "max_prior_entry_loss_fraction", "agentId": "agent_id",
                        "workspaceAgentIds": "workspace_agent_ids"}
                    params = {mapping.get(key, key): deepcopy(item) for key, item in arguments["options"].items()}
                    params.pop("agent_id", None)
                    params.setdefault("timezone", "UTC")
                    params.setdefault("min_score", 0)
                    params.setdefault("min_recall_count", 1)
                    params.setdefault("min_unique_queries", 1)
                    candidates = ([PromotionCandidate.from_json(item) for item in direct] if direct is not None else
                        rank_short_term_promotion_candidates(config=self.config, now_ms=self.wall_ms,
                            **{key: params[key] for key in ("limit", "min_score", "min_recall_count", "min_unique_queries", "max_age_days") if key in params}))
                    if direct is None:
                        candidates = [item for item in candidates if item.key in selection["keys"]]
                    call["actualCandidates"] = [_encode(item.to_json()) for item in candidates]
                    consolidation = None
                    if model_response is not None:
                        def model(request):
                            call.setdefault("modelRequests", []).append(_encode(request))
                            row = self.observer.event("declared-model-promise", label=label)
                            self._hit("promotion.model-planning-before-final-lock", {"label": label, "kind": kind}, row)
                            response = model_response.get("text") if isinstance(model_response, dict) else model_response
                            call.setdefault("modelResponses", []).append(deepcopy(response))
                            return response
                        consolidation = DeepConsolidation(model=model, options=LlmConsolidationOptions(enabled=True))
                    returned = run_short_term_promotion(config=self.config, store=self.owner, now_ms=self.wall_ms,
                        candidates=candidates, consolidation=consolidation, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
                        agent_id=self.config.agent_id, origins=self.ledger, artifact_provenance=self.provenance,
                        state_dir=self.directory / "state", on_event=self._host_event, **params)
                    call["promotion"] = _encode(returned)
                    from equivalence.promotion_apply_runtime import _public_result
                    call["publicPromotion"] = _public_result(returned, self.root)
                    call["candidateMode"] = candidate_mode
                elif kind == "recall":
                    mapping = {"signalType": "signal_type", "dedupeByQueryPerDay": "dedupe_by_query_per_day", "dayBucket": "day_bucket"}
                    params = {mapping.get(key, key): deepcopy(item) for key, item in arguments.items()}
                    returned = record_short_term_recalls(config=self.config, origins=self.ledger,
                        now_ms=self.wall_ms, on_event=self._host_event, **params)
                else:
                    raise ValueError(f"Unsupported original public call kind: {kind}")
                call["returned"] = _encode(returned)
                call["returnType"] = {"module": type(returned).__module__, "name": type(returned).__qualname__}
            except BaseException as error:
                call["error"] = _error(error, MemoryIndexRevisionConflictError)
                if kind == "sync":
                    call["outcome"] = {"status": "rejected", "isTypedConflict": isinstance(error, MemoryIndexRevisionConflictError)}
            finally:
                call["returnSeq"] = self.observer.event("public-call-return", label=label, kind=kind)["sequence"]
        return deepcopy(call)

    def snapshot(self, label):
        from memory_core.consolidation.artifacts import read_memory_preimages
        from memory_core.consolidation.session_ingestion import read_session_ingestion_state
        from memory_core.consolidation.store import (read_recall_store, recall_store_path,
            read_phase_signal_store, phase_signal_store_path)

        agent = self.value["identity"]["agentId"]
        # A read-only snapshot can be taken while another actor owns its writer.
        payload = {"label": label, "pid": os.getpid(), "actor": self.actor,
            "files": _files(self.root), "indexSql": _rows(self.storage["index"]),
            "originsSql": _rows(self.storage["origins"]), "catalogSql": _rows(self.storage["catalog"]),
            "provenanceSql": _rows(self.storage["provenance"]),
            "logicalOrigins": _encode(self.ledger.list(agent)) if self.ledger else [],
            "tombstones": _encode(self.ledger.list_session_tombstones(agent)) if self.ledger else [],
            "catalogForgotten": sorted(self.catalog.snapshot().forgotten_session_ids) if self.catalog else [],
            "logicalStores": {"recall": read_recall_store(recall_store_path(self.root), self.wall_ms),
                "phaseSignals": read_phase_signal_store(phase_signal_store_path(self.root), self.wall_ms),
                "ingestion": read_session_ingestion_state(self.root).to_json(),
                "preimages": read_memory_preimages(self.root)}}
        sessions = []
        if self.catalog is not None:
            for row in self.value["sessionFacts"]["sessions"]:
                transcript = self.catalog.read_transcript(row["sessionId"], agent_id=row["agentId"],
                                                           session_key=row["sessionKey"])
                sessions.append({"agentId": row["agentId"], "sessionId": row["sessionId"], "sessionKey": row["sessionKey"],
                    "entry": self.catalog.get_session_entry(row["sessionKey"]),
                    "events": _encode(transcript.events) if transcript is not None else None})
        admitted_files = self.workspace.discover_session_transcript_files() if self.workspace is not None else []
        admitted_paths = {item.rel_path for item in admitted_files}
        payload["logicalSessions"] = {"facts": sessions, "admission": [
            {"agentId": row["agentId"], "sessionId": row["sessionId"],
             "admitted": f"sessions/{row['agentId']}/{row['sessionId']}.jsonl" in admitted_paths}
            for row in self.value["sessionFacts"]["sessions"]]}
        payload["actualAdmittedSourceFiles"] = [_encode(item) for item in admitted_files]
        wire = _serialized(payload)
        return {**payload, "serializedJSON": wire, "sha256": hashlib.sha256(wire.encode()).hexdigest()}

    def observation(self):
        return {"actor": self.actor, "pid": os.getpid(), "sourceProvenanceBefore": self.before,
            "sourceProvenanceAfter": _sdk_sources(), "importedBefore": self.imported_before, "loadedSdk": _loaded_sdk(),
            "codeOwners": list(self.observer.codes.values()), "ownerBindings": deepcopy(self.bindings),
            "originalCalls": deepcopy(self.observer.events), "originalExceptions": deepcopy(self.observer.exceptions),
            "sqlStatements": deepcopy(self.observer.sql), "sqlExecutions": deepcopy(self.observer.sql_executions),
            "functionalGates": {key: gate.snapshot() for key, gate in self.gates.items()},
            "publicCalls": deepcopy(self.public_calls), "catalogSourceFacts": deepcopy(self.catalog_facts),
            "hostEvents": deepcopy(self.host_events), "hostEventReceipts": deepcopy(self.host_event_receipts),
            "clockBindings": deepcopy(self.clock_bindings), "datetimeClockCalls": deepcopy(self.datetime_clock_calls),
            "datetimeClockFailures": deepcopy(self.datetime_proxy.failures),
            "sourceClockReceipts": deepcopy(self.source_clock.receipts),
            "sourceClockOriginalIO": deepcopy(self.source_clock.original_io),
            "sourceClockReads": deepcopy(self.source_clock.source_reads),
            "sourceClockFailures": deepcopy(self.source_clock.failures),
            "ppid": os.getppid(), "wallClockNowMs": self.wall_ms,
            "providerIdentity": _encode(self.owner._index_provider()) if self.owner is not None else {"unacquired": True},
            "process": {"cwd": str(Path.cwd()), "executable": sys.executable, "version": sys.version,
                "cmdlineHex": Path("/proc/self/cmdline").read_bytes().hex()}}

    def command(self, command):
        _validate_actor_command(command, self.gates)
        operation = command["operation"]
        if operation == "acquire":
            return self.acquire()
        if operation == "seed":
            return self.seed()
        if operation == "call":
            label = command["label"]
            call_key = f"{command['kind']}:{label}"
            if call_key in self.futures or call_key in self.public_calls:
                raise ValueError("An original call label may execute only once per actor")
            if command.get("background", False):
                self.futures[call_key] = self.executor.submit(self._invoke, label, command["kind"], command["arguments"])
                return {"submitted": True, "label": label, "pid": os.getpid()}
            return self._invoke(label, command["kind"], command["arguments"])
        if operation == "await-call":
            return self.futures[f"{command['kind']}:{command['label']}"].result(timeout=PROCESS_TIMEOUT_SECONDS)
        if operation == "set-wall-clock":
            if command["nowMs"] not in {self.value["clock"]["nowMs"], self.value["clock"].get("recoveryNowMs")}:
                raise ValueError("The wall-clock phase was not frozen in the input")
            self.wall_ms = command["nowMs"]
            return {"nowMs": self.wall_ms, "monotonicAndTimers": "unmodified"}
        if operation in {"arm-gate", "await-gate", "release-gate"}:
            gate = self.gates[command["gate"]]
            if operation == "arm-gate":
                gate.arm()
            elif operation == "await-gate":
                if not gate.reached.wait(GATE_TIMEOUT_SECONDS):
                    raise TimeoutError("The original execution did not reach its declared gate")
            else:
                if not gate.reached.is_set():
                    raise ValueError("A functional gate cannot release before its actual boundary was reached")
                gate.released.set()
            return gate.snapshot()
        if operation == "snapshot":
            return self.snapshot(command["label"])
        if operation == "close":
            if self.owner is not None:
                with self.observer.call_scope("close", "close"):
                    returned = self.owner.close()
                return {"returned": _encode(returned), "closed": self.owner.closed,
                        "lifecycle": _encode(self.owner.lifecycle_snapshot())}
            return {"closed": True, "neverAcquired": True}
        if operation == "observe":
            return {"pending": {key: not future.done() for key, future in self.futures.items()}}
        if operation == "stop":
            return {"stopping": True}
        raise AssertionError(operation)


def run_forget_index_fence_sdk_actor(request):
    """JSON-lines actor; all public receipts remain outside observation codecs."""
    _literal(request["input"])
    actor = _SdkActor(request)
    for line in sys.stdin:
        command = json.loads(line)
        try:
            result = actor.command(command)
            response = {"id": command["id"], "ok": True, "result": _encode(result)}
        except BaseException as error:
            response = {"id": command.get("id"), "ok": False, "error": _error(error)}
        response["observation"] = actor.observation()
        sys.stdout.write(_serialized(response) + "\n")
        sys.stdout.flush()
        if command.get("operation") == "stop":
            break
    actor.executor.shutdown(wait=True)


class _ActorProcess:
    def __init__(self, value, directory, actor):
        self.actor, self.directory = actor, directory
        self.request = {"mode": "actor", "input": value, "directory": str(directory), "actor": actor}
        self.argv = [sys.executable, "-m", "equivalence.forget_index_fence_sdk_cli"]
        self.environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
            "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC",
            "OPENCLAW_HOME": str(directory), "OPENCLAW_STATE_DIR": str(directory / "state")}
        self.child = subprocess.Popen(self.argv, cwd=ROOT, env=self.environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.receipt = {"actor": actor, "pid": self.child.pid, "argv": self.argv,
            "request": deepcopy(self.request), "requestJson": _serialized(self.request),
            "requestSha256": hashlib.sha256(_serialized(self.request).encode()).hexdigest(),
            "startedAtNs": str(time.monotonic_ns()), "stdinCommands": [], "stdoutResponses": [],
            "stdoutLines": [], "stderr": "", "exit": None}
        self.counter = 0
        self.acquired = False
        self.child.stdin.write(_serialized(self.request) + "\n")
        self.child.stdin.flush()

    def command(self, operation, **values):
        self.counter += 1
        command = {"id": self.counter, "operation": operation, **values}
        self.receipt["stdinCommands"].append(deepcopy(command))
        self.child.stdin.write(_serialized(command) + "\n")
        self.child.stdin.flush()
        ready, _, _ = select.select([self.child.stdout], [], [], PROCESS_TIMEOUT_SECONDS)
        if not ready:
            raise TimeoutError(f"The original SDK actor {self.actor} did not settle its command")
        line = self.child.stdout.readline()
        if not line:
            self.reap()
            raise RuntimeError(f"The original SDK actor {self.actor} exited before its command receipt")
        response = json.loads(line)
        self.receipt["stdoutLines"].append(line)
        self.receipt["stdoutResponses"].append(deepcopy(response))
        self.receipt["observation"] = deepcopy(response.get("observation"))
        if response.get("id") != command["id"]:
            raise RuntimeError("The original actor returned another command's receipt")
        if not response.get("ok"):
            raise RuntimeError(f"Original SDK actor command failed: {_serialized(response.get('error'))}")
        if operation == "acquire":
            self.acquired = True
        return response["result"]

    def kill(self):
        self.receipt["kill"] = {"signal": "SIGKILL", "pid": self.child.pid, "pollBefore": self.child.poll()}
        self.child.kill()

    def reap(self):
        if self.receipt["exit"] is not None:
            return self.receipt["exit"]
        if self.child.stdin and not self.child.stdin.closed:
            self.child.stdin.close()
        self.child.wait(timeout=PROCESS_TIMEOUT_SECONDS)
        residual = self.child.stdout.read()
        self.receipt["stdoutResidual"] = residual
        self.receipt["stderr"] = self.child.stderr.read()
        self.receipt["exit"] = {"code": self.child.returncode}
        self.receipt["reapedAtNs"] = str(time.monotonic_ns())
        return self.receipt["exit"]


def _arguments_for(value, kind, label):
    mapping = {"search": "queries", "sync": "syncs", "forget": "forgetCalls", "promotion": "promotions", "recall": "recallCalls"}
    entries = value[mapping[kind]]
    if isinstance(entries, dict):
        specification = entries[label]
    else:
        specification = next(item for item in entries if item["label"] == label)
    return deepcopy(specification.get("arguments", specification.get("params", specification)))


def _common_calls(calls, workspace):
    result = {}
    for key, call in calls.items():
        kind = call["kind"]
        if "termination" in call:
            outcome = {"status": "terminated", "signal": call["termination"]["signal"]}
        elif kind == "sync":
            outcome = deepcopy(call["outcome"])
        elif "error" in call:
            error = {"message": call["error"]["message"]}
            if "code" in call["error"]:
                error["code"] = deepcopy(call["error"]["code"])
            outcome = {"status": "rejected", "error": error}
        elif kind == "recall":
            # The declared cross-source boundary compares settlement only:
            # native returns undefined while this original SDK returns a count.
            # The integer, original return frame, event and complete state stay raw.
            outcome = {"status": "fulfilled"}
        else:
            payload = (call["details"] if kind == "search" else call["report"] if kind == "forget"
                       else deepcopy(call["publicPromotion"]) if kind == "promotion" else call["returned"])
            if kind == "promotion":
                path = Path(payload["memoryPath"])
                if not path.is_absolute() or not path.resolve().is_relative_to(workspace.resolve()):
                    raise RuntimeError("The original promotion memoryPath is outside its verified workspace")
                payload["memoryPath"] = "$WORKSPACE/" + path.relative_to(workspace).as_posix()
            outcome = {"status": "fulfilled", "result": payload}
        result[key] = {"operation": kind, "label": call["label"], "outcome": outcome}
    return result


def _logical_origins(rows):
    return [{"entryKey": row["entry_key"], "agentId": row["agent_id"], "sessionId": row["session_id"],
             "sessionKey": row["session_key"], "originClass": row["origin_class"], "observedAt": row["observed_at"]}
            for row in rows]


def _logical_tombstones(rows):
    return [{"sessionId": row["session_id"], "agentId": row["agent_id"], "reason": row["reason"],
             "createdAt": row["created_at"]} for row in rows]


def _common_snapshot(value, snapshot, observations, workspace):
    files = {row["path"]: row for row in snapshot["files"] if row["path"].endswith((".md", ".txt"))}
    declared = {path for path in value["initialFiles"] if path.endswith((".md", ".txt"))}
    documents = []
    for path in sorted(set(files) | declared):
        row = files.get(path)
        documents.append({"path": path, "exists": row is not None,
                          "bytes": row["hex"] if row is not None else None,
                          "sha256": row["sha256"] if row is not None else None})
    tables = snapshot["indexSql"]["tables"]
    chunks = [{"path": row["path"], "source": row["source"], "startLine": row["start_line"],
               "endLine": row["end_line"], "text": row["text"]}
              for row in tables.get("chunks", {}).get("rows", [])]
    chunks.sort(key=lambda row: (row["path"], row["source"], row["startLine"], row["endLine"], row["text"]))
    raw_calls = [call for observation in observations for call in observation.get("publicCalls", {}).values()]

    controlled_syncs = {gate["callLabel"] for gate in value["gates"] if gate["boundary"] in {
        "rebuild.revision-captured-before-publication", "publication.fence-checked-before-table-writes"}}

    def settled(kind):
        selected = [call for call in raw_calls if call["kind"] == kind and "apiEntry" in call
                    and (kind != "sync" or call["label"] in controlled_syncs)]
        if not selected:
            return None
        selected.sort(key=lambda call: int(call["apiEntry"]["atNs"]))
        return "returnSeq" in selected[-1]

    selected_id = value["forgetCalls"]["selected"]["sessionIds"][0]
    event_receipts = [receipt for observation in observations for receipt in observation.get("hostEventReceipts", [])]
    event_receipts.sort(key=lambda receipt: int(receipt["atNs"]))
    events = []
    for receipt in event_receipts:
        event = deepcopy(receipt["event"])
        if event.get("type") == "memory.promotion.applied" and "memoryPath" in event:
            path = Path(event["memoryPath"])
            if not path.is_absolute() or not path.resolve().is_relative_to(workspace.resolve()):
                raise RuntimeError("An original promotion event memoryPath escaped its verified workspace")
            event["memoryPath"] = "$WORKSPACE/" + path.relative_to(workspace).as_posix()
        events.append(event)
    return {"documents": documents, **deepcopy(snapshot["logicalStores"]),
        "origins": _logical_origins(snapshot["logicalOrigins"]),
        "tombstones": _logical_tombstones(snapshot["tombstones"]), "sessions": deepcopy(snapshot["logicalSessions"]),
        "index": chunks, "concurrency": {"markerVisible": any(row["session_id"] == selected_id for row in snapshot["tombstones"]),
            "forgetSettled": settled("forget"), "oldBuildSettled": settled("sync")}, "events": events}


def run_forget_index_fence_sdk_host(request):
    """Orchestrate the exact declared independent-process schedule once."""
    if not isinstance(request, dict) or set(request) != {"input", "directory"}:
        raise ValueError("The protected SDK host requires exactly input and directory")
    value, directory = request["input"], Path(request["directory"])
    _literal(value)
    if not directory.is_absolute() or not directory.is_dir() or directory.is_symlink():
        raise ValueError("An existing absolute fixture directory is required")
    before = _sdk_sources()
    actors, processes, steps, snapshots, calls = {}, [], [], {}, {}
    common_snapshots = {}
    wall_ms = value["clock"]["nowMs"]
    raw = {"kind": "forget-index-fence-v2-sdk-host", "input": deepcopy(value), "pid": os.getpid(),
        "fixtureRoot": str(directory), "sourceProvenanceBefore": before, "processes": processes,
        "steps": steps, "physicalSnapshots": snapshots, "publicCalls": calls}

    def start(actor):
        if actor in actors and actors[actor].child.poll() is None:
            raise ValueError("A scheduled process actor already exists")
        process = _ActorProcess(value, directory, actor)
        actors[actor] = process
        processes.append(process.receipt)
        if wall_ms != value["clock"]["nowMs"]:
            process.command("set-wall-clock", nowMs=wall_ms)
        return process

    def owner(actor):
        process = actors.get(actor)
        if process is None or process.child.poll() is not None:
            process = start(actor)
        if not process.acquired:
            process.command("acquire")
        return process

    def gate_actor(name):
        return next(item["actor"] for item in value["gates"] if item["name"] == name)

    def record_call(record, returned):
        key = f"{returned['kind']}:{returned['label']}"
        calls[key] = returned
        record["returned"] = returned

    try:
        for number, step in enumerate(value["steps"]):
            operation = step["operation"]
            actor = step.get("actor", "foreground")
            label = step.get("label", step.get("callLabel"))
            record = {"number": number, "specification": deepcopy(step), "status": "entered",
                      "enteredAtNs": str(time.monotonic_ns())}
            steps.append(record)
            if "wallClockNowMs" in step:
                wall_ms = step["wallClockNowMs"]
                for process in actors.values():
                    if process.child.poll() is None:
                        process.command("set-wall-clock", nowMs=wall_ms)
            if operation == "prepare-real-host-inputs":
                root = directory / "workspace"
                root.mkdir(parents=True, exist_ok=True)
                initial = value.get("initialFiles", {})
                for relative, specification in initial.items():
                    target = _safe_path(root, relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    text = specification["text"] if isinstance(specification, dict) else specification
                    target.write_text(text, encoding="utf8", newline="")
                    mtime = (specification.get("mtimeMs", value["clock"]["initialSourceMtimeMs"])
                             if isinstance(specification, dict) else value["clock"]["initialSourceMtimeMs"])
                    os.utime(target, ns=(mtime * 1_000_000,) * 2)
                # Session metadata/events have their own genuine producer.
                # No manager is secretly acquired during host-input preparation.
                fixture = start("host-inputs")
                record["returned"] = fixture.command("seed")
                fixture.command("stop")
                fixture.reap()
            elif operation == "acquire-original-owner":
                process = actors.get(actor)
                if process is None or process.child.poll() is not None:
                    process = start(actor)
                record["returned"] = process.command("acquire")
            elif operation == "start-fresh-original-process":
                record["returned"] = {"pid": start(actor).child.pid, "actor": actor, "managerAcquisition": "not-yet-requested"}
            elif operation == "execute-seed-actions":
                record["returned"] = []
                for action in value["seedActions"]:
                    if action["operation"] != "original-record-short-term-recalls":
                        raise ValueError("A seed action is outside the frozen original API protocol")
                    target, seed_label = action["actor"], action["label"]
                    returned = owner(target).command("call", label=seed_label, kind="recall",
                        arguments=_arguments_for(value, "recall", seed_label), background=False)
                    record["returned"].append(returned)
                    calls[f"recall:{seed_label}"] = returned
            elif operation in {"public-memory-search", "start-public-memory-search", "original-sync", "start-sync",
                               "original-forget", "start-forget", "original-promotion", "start-promotion",
                               "original-record-short-term-recalls"}:
                kind = ("search" if "search" in operation else "sync" if "sync" in operation else
                        "forget" if "forget" in operation else "recall" if "recalls" in operation else "promotion")
                background = operation.startswith("start-")
                returned = owner(actor).command("call", label=label, kind=kind,
                    arguments=_arguments_for(value, kind, label), background=background)
                record["returned"] = returned
                if not background:
                    record_call(record, returned)
            elif operation in {"await-public-call", "await-sync", "await-forget", "await-promotion"}:
                kind = ("search" if operation == "await-public-call" else operation.removeprefix("await-"))
                returned = actors[actor].command("await-call", label=label, kind=kind)
                record_call(record, returned)
            elif operation in {"arm-gate", "await-gate", "release-gate"}:
                record["returned"] = actors[gate_actor(step["gate"])].command(operation, gate=step["gate"])
            elif operation == "capture-physical-state":
                record["returned"] = actors[actor].command("snapshot", label=label)
                snapshots[label] = record["returned"]
                capture_path = _safe_path(directory, f"captures/{label}-sdk.json")
                capture_path.parent.mkdir(parents=True, exist_ok=True)
                capture_bytes = (_serialized(record["returned"]) + "\n").encode("utf8")
                capture_path.write_bytes(capture_bytes)
                record["physicalCapture"] = {"path": str(capture_path), "bytes": len(capture_bytes),
                    "sha256": hashlib.sha256(capture_bytes).hexdigest()}
                observations_at_capture = [deepcopy(process["observation"])
                    for process in processes if process.get("observation")]
                record["observationsAtCapture"] = observations_at_capture
                common_snapshots[label] = _common_snapshot(value, record["returned"],
                    observations_at_capture, directory / "workspace")
            elif operation == "original-owner-close":
                record["returned"] = actors[actor].command("close")
            elif operation == "stop-original-process":
                if step["mode"] == "SIGKILL":
                    actors[actor].kill()
                    # Retain the original entered call as terminated; no fake
                    # forget report, return or exception is manufactured.
                    last = actors[actor].receipt.get("observation", {}).get("publicCalls", {})
                    for key, call in last.items():
                        if "returnSeq" not in call:
                            calls[key] = {**deepcopy(call), "termination": {"signal": "SIGKILL", "pid": actors[actor].child.pid}}
                    record["returned"] = deepcopy(actors[actor].receipt["kill"])
                elif step["mode"] == "graceful":
                    record["returned"] = actors[actor].command("stop")
                else:
                    raise ValueError("A process stop mode was not frozen")
            elif operation == "reap-original-process":
                record["returned"] = actors[actor].reap()
            elif operation in {"observe-original-process", "await-original-busy"}:
                record["returned"] = actors[actor].command("observe")
            else:
                raise ValueError(f"Unsupported frozen SDK schedule operation: {operation}")
            record["status"] = "settled"
            record["settledAtNs"] = str(time.monotonic_ns())
    except BaseException as error:
        raw["error"] = _error(error)
    finally:
        for process in actors.values():
            if process.child.poll() is None:
                try:
                    process.command("close")
                    process.command("stop")
                except BaseException as error:
                    process.receipt["cleanupError"] = _error(error)
                    process.kill()
            try:
                process.reap()
            except BaseException as error:
                process.receipt["reapError"] = _error(error)
        raw["sourceProvenanceAfter"] = _sdk_sources()
    clock_failures = [{"actor": process["actor"], "pid": process["pid"],
        "sourceClockFailures": process["observation"].get("sourceClockFailures", []),
        "datetimeClockFailures": process["observation"].get("datetimeClockFailures", [])}
        for process in processes if process.get("observation") and (
            process["observation"].get("sourceClockFailures") or process["observation"].get("datetimeClockFailures"))]
    raw["observationInvalid"] = clock_failures
    raw["complete"] = "error" not in raw and not clock_failures
    raw["result"] = {"provider": "none", "calls": _common_calls(calls, directory / "workspace"),
                     "snapshots": common_snapshots}
    return raw


def run_forget_index_fence_sdk_case(value, *, evidence_directory=None):
    """Protected once-only outer process; retain full streams even on failure."""
    _literal(value)
    if evidence_directory is not None:
        Path(evidence_directory).mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="sdk-forget-index-fence-", dir=evidence_directory)).resolve()
    destination = Path(evidence_directory) if evidence_directory is not None else directory
    request = {"input": value, "directory": str(directory)}
    wire = _serialized(request)
    argv = [sys.executable, "-m", "equivalence.forget_index_fence_sdk_cli"]
    environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
        "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC",
        "OPENCLAW_HOME": str(directory), "OPENCLAW_STATE_DIR": str(directory / "state")}
    dispatch = {"kind": "forget-index-fence-v2-sdk-dispatch", "input": deepcopy(value), "request": request,
        "requestJson": wire, "requestSha256": hashlib.sha256(wire.encode()).hexdigest(),
        "argv": argv, "environmentKeys": sorted(environment), "coordinatorPid": os.getpid(),
        "sourceProvenanceBefore": _sdk_sources()}
    with subprocess.Popen(argv, cwd=ROOT, env=environment, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
        dispatch["pid"] = child.pid
        try:
            stdout, stderr = child.communicate(wire + "\n", timeout=PROCESS_TIMEOUT_SECONDS * 4)
        except subprocess.TimeoutExpired:
            child.kill()
            stdout, stderr = child.communicate()
            dispatch["timeout"] = True
    dispatch.update(stdout=stdout, stderr=stderr, exit={"code": child.returncode},
                    sourceProvenanceAfter=_sdk_sources())
    try:
        dispatch["observation"] = json.loads(stdout)
    except json.JSONDecodeError as error:
        dispatch["stdoutParseError"] = _error(error)
    (destination / "python-raw.json").write_text(_serialized([dispatch]) + "\n", encoding="utf8")
    if child.returncode or "observation" not in dispatch or "result" not in dispatch["observation"]:
        raise RuntimeError("Original SDK forget/index-fence child failed; complete streams retained")
    if not dispatch["observation"].get("complete"):
        raise RuntimeError("Original SDK forget/index-fence schedule failed; complete receipts retained")
    return dispatch["observation"]["result"]


run_forget_index_fence_case = run_forget_index_fence_sdk_case
