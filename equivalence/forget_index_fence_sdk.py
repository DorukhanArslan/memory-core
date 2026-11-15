"""Original SDK actors for the frozen forget/index-fence process family.

This module is a driver, not a memory implementation. Each independently owned
process constructs the ordinary managed on-search store and calls the original
forget, search, sync and promotion APIs. Observers append to memory only. The
explicit functional gates may wait for a controller release; no gate substitutes
a producer, its expected revision, a transaction, or its public return.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import fields, is_dataclass
import hashlib
import importlib
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

from equivalence.forget_index_fence_sdk_clock import CodeIdentityMap


ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = ROOT
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
SEARCH_EFFECT_KINDS = frozenset({"forget-index-fence-v3", "forget-index-fence-v4", "forget-index-fence-v5", "forget-index-fence-v6"})
PROFILE_MODULES = {f"forget-index-fence-v{version}": f"equivalence.forget_index_fence_v{version}"
                   for version in (2, 3, 4, 5, 6)}


def _serialized(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _capture_dispatch_packet(dispatch):
    """Use retained V5 stdout instead of serializing its parsed value twice."""
    packet = dict.copy(dispatch)
    kind = dispatch.get("input", {}).get("kind")
    v5 = dispatch.get("kind") in {"forget-index-fence-v5-sdk-dispatch", "forget-index-fence-v6-sdk-dispatch"}
    input_v5 = kind in {"forget-index-fence-v5", "forget-index-fence-v6"}
    if v5 != input_v5 or v5 and dispatch.get("kind") != kind + "-sdk-dispatch":
        raise ValueError("The compact SDK packet requires matching closed V5/V6 identities")
    if "observationEncoding" in dispatch:
        raise ValueError("A live SDK dispatch cannot already contain an observation encoding")
    if v5 and any(field in dispatch for field in (
            "stdoutDecodeError", "stdoutBytesHex", "stderrDecodeError", "stderrBytesHex")):
        raise ValueError("A failed UTF8 stream cannot assert a positive SDK observation encoding")
    if not v5 or "observation" not in dispatch:
        return packet
    stdout, observation = dispatch.get("stdout"), dispatch["observation"]
    if not isinstance(stdout, str) or not isinstance(observation, dict):
        raise ValueError("A compact SDK packet requires its complete UTF8 JSON object")
    payload = stdout.encode("utf8")
    def same_json(actual, retained):
        if type(actual) is not type(retained):
            return False
        if isinstance(actual, dict):
            return actual.keys() == retained.keys() and all(same_json(value, retained[key])
                                                           for key, value in actual.items())
        if isinstance(actual, list):
            return len(actual) == len(retained) and all(same_json(left, right)
                                                       for left, right in zip(actual, retained, strict=True))
        return actual == retained

    if not same_json(json.loads(stdout), observation):
        raise ValueError("The parsed SDK observation differs from its actual retained stdout")
    del packet["observation"]
    packet["observationEncoding"] = {"kind": "stdout-json-v1", "field": "stdout",
        "utf8Bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    return packet


def _decode_dispatch_stream(payload, field, dispatch):
    """Keep invalid UTF8 losslessly as a diagnostic, never a decoded substitute."""
    try:
        return payload.decode("utf8")
    except UnicodeDecodeError as error:
        dispatch[field + "BytesHex"] = payload.hex()
        dispatch[field + "DecodeError"] = _error(error)
        return None


def _observation_copy(value, memo=None):
    """Copy each live container's membership before recursively observing it.

    Journals can grow while an original worker runs. Builtin container copies
    avoid iterating a live dict without adding a worker/observer mutex. This is
    an observation of those containers, not one atomic multi-thread snapshot.
    """
    value_type = type(value)
    if (value is None or value_type is str or value_type is bytes or value_type is int
            or value_type is float or value_type is bool):
        return value
    memo = {} if memo is None else memo
    identity = id(value)
    if identity in memo:
        return memo[identity]
    if isinstance(value, dict):
        members = dict.copy(value)
        copied = {}
        memo[identity] = copied
        for key, item in members.items():
            copied[_observation_copy(key, memo)] = _observation_copy(item, memo)
        return copied
    if isinstance(value, list):
        members = list.copy(value)
        copied = []
        memo[identity] = copied
        copied.extend(_observation_copy(item, memo) for item in members)
        return copied
    if isinstance(value, tuple):
        copied = tuple(_observation_copy(item, memo) for item in value)
        memo[identity] = copied
        return copied
    return deepcopy(value, memo)


def _source_clock_observation(clock):
    # One membership cut across the clock's shared sequence. Rich row copies
    # happen after releasing its private journal lock, as for other observers.
    journals = clock.snapshot_journals()
    return {field: _observation_copy(journals[name]) for field, name in (
        ("sourceClockReceipts", "receipts"), ("sourceClockOriginalIO", "original_io"),
        ("sourceClockReads", "source_reads"), ("sourceClockFailures", "failures"))}


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
    if isinstance(value, Future):
        return {"module": type(value).__module__, "className": type(value).__qualname__,
                "objectId": str(id(value)), "state": value._state,
                "result": _encode(value._result), "exception": _encode(value._exception)}
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


def _validated_sdk_root(value):
    root = Path(value)
    if (not root.is_absolute() or root.is_symlink() or root.resolve() != root
            or (root / "memory_core").is_symlink() or not (root / "memory_core" / "__init__.py").is_file()):
        raise ValueError("The original SDK requires an independently selected absolute source root")
    return root.resolve(strict=True)


def _configure_sdk_root(value):
    """Select original imports before any SDK module is loaded in this child."""
    global SDK_ROOT
    selected = _validated_sdk_root(value)
    for row in _loaded_sdk():
        if not Path(row["path"]).is_relative_to(selected):
            raise RuntimeError("The child already loaded another original SDK source root")
    SDK_ROOT = selected
    sys.path[:] = [str(selected), *(entry for entry in sys.path if entry != str(selected))]


def _sdk_sources(root=None):
    root = SDK_ROOT if root is None else _validated_sdk_root(root)
    digest, rows = hashlib.sha256(), []
    for path in sorted((root / "memory_core").rglob("*.py")):
        if path.is_symlink():
            raise RuntimeError("SDK source identity cannot follow an alias")
        relative, payload = path.relative_to(root).as_posix(), path.read_bytes()
        digest.update(relative.encode() + b"\0" + payload + b"\0")
        rows.append({"path": relative, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    return {"root": str(root), "sourceFiles": len(rows), "sourceSha256": digest.hexdigest(), "files": rows}


def _loaded_sdk():
    return [{"module": name, "path": str(Path(module.__file__).resolve()),
             "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
            for name, module in sorted(sys.modules.items()) if name.startswith("memory_core")
            and getattr(module, "__file__", None) and Path(module.__file__).is_file()]


def _adapter_sources(kind="forget-index-fence-v3"):
    if kind not in SEARCH_EFFECT_KINDS:
        raise ValueError("Adapter custody requires a closed search-effects profile")
    version = kind.rsplit("-", 1)[1]
    names = ("equivalence/forget_index_fence_sdk.py", "equivalence/forget_index_fence_sdk_cli.py",
             "equivalence/forget_index_fence_sdk_clock.py", f"equivalence/forget_index_fence_{version}.py",
             f"docs/forget_index_fence_{version}_literals.json", f"docs/forget_index_fence_{version}_plan.md")
    rows, digest = [], hashlib.sha256()
    for name in names:
        path = ROOT / name
        if path.is_symlink():
            raise RuntimeError("Adapter custody cannot follow a source alias")
        payload = path.read_bytes()
        digest.update(name.encode() + b"\0" + payload + b"\0")
        rows.append({"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    return {"root": str(ROOT), "sourceSha256": digest.hexdigest(), "files": rows}


def _loaded_fixtures():
    rows = []
    for name, module in sorted(sys.modules.items()):
        source = getattr(module, "__file__", None)
        if source is None:
            continue
        path = Path(source).resolve()
        if path.is_relative_to(ROOT / "equivalence") and path.is_file():
            rows.append({"module": name, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return rows


def _literal(value):
    if not isinstance(value, dict) or value.get("kind") not in PROFILE_MODULES:
        raise ValueError("The SDK actor requires a supported closed profile kind")
    module = importlib.import_module(PROFILE_MODULES[value["kind"]])
    for case in module.build_cases():
        if case.get("input") == value:
            return case
    raise ValueError("The SDK forget/index-fence actor requires an exact frozen input")


def _search_maintenance_binding(owner, declared_sync):
    """Describe the actual SDK policy without inventing unsupported sync flags."""
    owner_class = type(owner)

    def identity(value):
        return None if value is None else {"objectId": str(id(value)),
            "module": type(value).__module__, "className": type(value).__qualname__}

    return {"declaredNativeSync": deepcopy(declared_sync),
        "constructorParameters": list(inspect.signature(owner_class.__init__).parameters),
        "actualSdk": {"memoryPublication": owner._memory_publication,
            "sessionPublicationController": identity(owner._session_publication),
            "memoryExecutor": identity(owner._memory_executor), "memoryActive": owner._memory_active,
            "memoryJobs": _encode(_observation_copy(list(owner._memory_jobs.copy())))},
        "sourceRoles": {key: _code_identity(getattr(owner_class, name).__code__) for key, name in (
            ("constructor", "__init__"), ("onSearchSnapshot", "_on_search_snapshot"),
            ("submitMemoryPublication", "_submit_memory_publication"),
            ("bindSessionPublication", "bind_session_publication"))}}


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
                "reached": self.reached.is_set(), "released": self.released.is_set(), "hits": _observation_copy(self.hits)}


class _OriginalObserver:
    """Source-code and exact-receiver witnesses with a private journal lock.

    ``codes`` maps original CodeType objects to {name, receiver}. A receiver is a
    frame-local parameter whose exact object must have been bound. ``None``
    accepts a receiverless function only inside an already labelled original
    worker scope. Strong owner/context references prevent object-id reuse.
    The lock covers only journal metadata/publication and membership copies;
    original operations, argument encoding and functional callbacks stay outside.
    """

    def __init__(self, codes, *, gate_callback=None, sql_callback=None,
                 functional_profile=None, functional_trace=None):
        self.codes = CodeIdentityMap(codes)
        self.owners = {}
        self.local = threading.local()
        self.events, self.exceptions, self.sql, self.failures = [], [], [], []
        self.submitted_tasks, self.pending_submissions, self.job_scopes = [], {}, {}
        self.sql_executions = []
        self.connections = {}
        self.contexts = {}
        self.watchers = {}
        self.gate_callback = gate_callback
        self.sql_callback = sql_callback
        self.functional_profile, self.functional_trace = functional_profile, functional_trace
        self._sequence = 0
        self._event_lock = threading.Lock()

    def bind_owner(self, owner, label):
        self.owners[id(owner)] = (owner, label)

    def bind_watcher(self, watcher, store):
        self.watchers[id(watcher)] = (watcher, store)
        self.bind_owner(watcher, "memory-watcher")
        self.bind_owner(watcher._condition, "memory-watcher-condition")
        if watcher._backend is not None:
            self.bind_owner(watcher._backend, "memory-watcher-inotify")

    def _watch_scope(self):
        for watcher, store in tuple(self.watchers.values()):
            thread = watcher._thread
            if thread is None or thread.ident != threading.get_ident() or thread is not threading.current_thread():
                continue
            local = watcher._callback_local
            generation = getattr(local, "delivery", None)
            if generation is None:
                generation = getattr(local, "settling", None)
            if generation is None:
                generation = watcher._changes
            return {"kind": "watch", "label": f"watch:{id(watcher)}:{generation}",
                "origin": "original-memory-watcher", "watcherObjectId": str(id(watcher)),
                "storeObjectId": str(id(store)), "detectorGeneration": generation}
        return None

    def _store_watch_scope(self, store):
        watcher = getattr(store, "_memory_watcher", None)
        binding = self.watchers.get(id(watcher))
        if binding is None or binding[0] is not watcher or binding[1] is not store:
            return None
        generation = store._memory_watch_ready_generation
        fact = next((row for row in reversed(tuple(store._memory_watch_facts))
                     if row["watchGeneration"] == generation), None)
        if fact is None:
            return None
        detected = fact["detectorGeneration"]
        return {"kind": "watch", "label": f"watch:{id(watcher)}:{detected}",
            "origin": "original-memory-watcher", "watcherObjectId": str(id(watcher)),
            "storeObjectId": str(id(store)), "detectorGeneration": detected}

    def event(self, event_name, **values):
        if {"sequence", "event", "pid", "threadId", "atNs"}.intersection(values):
            raise ValueError("Original event values cannot override journal metadata")
        # The GIL does not make allocation, timestamping and append one action.
        # Values are already encoded; no original operation/callback runs here.
        with self._event_lock:
            sequence = self._sequence + 1
            row = {"sequence": sequence, "event": event_name, "pid": os.getpid(),
                   "threadId": threading.get_ident(), "atNs": str(time.monotonic_ns()), **values}
            list.append(self.events, row)
            self._sequence = sequence
        return row

    def snapshot_events(self):
        with self._event_lock:
            return list.copy(self.events)

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
        if specification["name"] == "ThreadPoolExecutor.submit" and self._task_kind(frame) is None:
            return None
        receiver_key = specification.get("receiver")
        receiver = frame.f_locals.get(receiver_key) if receiver_key else None
        bound = self.owners.get(id(receiver)) if receiver_key else None
        if receiver_key and (bound is None or bound[0] is not receiver):
            return None
        scope = getattr(self.local, "scope", None)
        if specification["name"] == "ManagedSQLiteMemoryStore._queue_memory_watch_publication":
            scope = self._store_watch_scope(receiver)
        context = frame.f_locals.get("context")
        store = frame.f_locals.get("store")
        if scope is None and context is not None and store is not None:
            saved = self.contexts.get((id(context), id(store)))
            if saved is not None and saved[0] is context and saved[1] is store:
                scope = saved[2]
        if scope is None and receiver is not None and "job" in frame.f_locals:
            job = frame.f_locals["job"]
            saved = self.job_scopes.get((id(receiver), id(job)))
            if saved is not None and saved[0] is receiver and saved[1] is job:
                scope = saved[2]
        if scope is None:
            scope = self._watch_scope()
        if scope is None:
            stack = getattr(self.local, "stack", ())
            scope = stack[-1][2] if stack else None
        if scope is None:
            return None
        return specification, receiver, bound[1] if bound else None, scope

    def _task_kind(self, frame):
        function = frame.f_locals.get("fn")
        code = getattr(getattr(function, "__func__", function), "__code__", None)
        role = self.codes.get(code, {}).get("name")
        return {"ManagedSQLiteMemoryStore._run_memory_publication": "memory-publication",
                "_record_search_recalls": "recall"}.get(role)

    def _remember_submission(self, frame, scope, call, stack):
        kind = self._task_kind(frame)
        if kind is None:
            return
        function, args, kwargs = (frame.f_locals[key] for key in ("fn", "args", "kwargs"))
        if kind == "memory-publication":
            store, job = function.__self__, args[0]
            if self.owners.get(id(store), (None,))[0] is not store:
                return
            self.job_scopes[(id(store), id(job))] = (store, job, deepcopy(scope))
            arguments = {"args": _encode(args), "kwargs": _encode(kwargs)}
            context = None
        else:
            store, context, job = kwargs["store"], kwargs["context"], None
            arguments = {"args": _encode(args), "kwargs": {
                key: _encode(value) for key, value in kwargs.items() if key not in {"store", "context"}},
                "storeObjectId": str(id(store)), "contextObjectId": str(id(context))}
        call["arguments"] = {"fn": _encode(function), **arguments}
        task = {"kind": kind, "scope": deepcopy(scope), "submitSequence": call["sequence"],
            "executorObjectId": str(id(frame.f_locals["self"])), "storeObjectId": str(id(store)),
            "contextObjectId": str(id(context)) if context is not None else None,
            "jobObjectId": str(id(job)) if job is not None else None,
            "parentCallSequences": [item[1]["sequence"] for item in stack],
            "functionCode": deepcopy(self.codes[getattr(function, "__func__", function).__code__]["code"])}
        self.pending_submissions[id(frame)] = (task, store, job)

    def task_receipts(self):
        return [{**deepcopy(task["receipt"]), "future": _encode(task["future"]),
                 "job": _encode(dict(task["job"]) if isinstance(task["job"], dict) else task["job"])}
                for task in self.submitted_tasks]

    def profile(self, frame, event, returned):
        if self.functional_profile is not None:
            self.functional_profile(frame, event, returned)
        if event in {"c_call", "c_return", "c_exception"}:
            self._profile_sql(frame, event, returned)
            return
        if event not in {"call", "return"}:
            return
        stack = getattr(self.local, "stack", ())
        entry = (next((item for item in reversed(stack) if item[0] is frame
                       and item[4] is frame.f_code), None) if event == "return" else None)
        # A callee may clear or delete its receiver in finally. Its actual
        # return still belongs to the exact frame/code/receiver checked on entry.
        match = entry[3] if entry is not None else self._match(frame) if event == "call" else None
        if match is None:
            return
        specification, receiver, owner_label, scope = match
        if event == "call":
            if specification.get("bindSelfOnCall") and frame.f_locals.get("self") is not None:
                self.bind_owner(frame.f_locals["self"], specification["bindSelfOnCall"])
            if "context" in frame.f_locals and "store" in frame.f_locals:
                context, store = frame.f_locals["context"], frame.f_locals["store"]
                if context is not None and id(store) in self.owners:
                    self.contexts[(id(context), id(store))] = (context, store, scope)
            call = self.event("original-call", name=specification["name"],
                callLabel=scope["label"], callKind=scope["kind"], owner=owner_label,
                scope=deepcopy(scope),
                frameObjectId=str(id(frame)),
                receiverObjectId=str(id(receiver)) if receiver is not None else None,
                contextObjectId=str(id(frame.f_locals["context"])) if frame.f_locals.get("context") is not None else None,
                selfObjectId=str(id(frame.f_locals["self"])) if frame.f_locals.get("self") is not None else None,
                workspaceObjectId=str(id(frame.f_locals["workspace"])) if frame.f_locals.get("workspace") is not None else None,
                configObjectId=str(id(frame.f_locals["config"])) if frame.f_locals.get("config") is not None else None,
                exactReceiver=receiver is not None, code=specification.get("code"),
                arguments={key: _encode(value) for key, value in frame.f_locals.items()
                           if specification["name"] != "ThreadPoolExecutor.submit"
                           if key not in {"self", "context", "store", "workspace", "config", "origins", "ledger"}})
            if specification["name"] in {"MemorySearchRecallOwner.submit", "_record_search_recalls"}:
                recall_owner = frame.f_locals["context"].recall
                call["contextRecallOwnerObjectId"] = str(id(recall_owner)) if recall_owner is not None else None
            if specification["name"] == "ThreadPoolExecutor.submit":
                self._remember_submission(frame, scope, call, stack)
            if specification.get("replanCallback") and frame.f_locals.get("db") is not None:
                parent, db = frame.f_back, frame.f_locals["db"]
                parent_specification = self.codes.get(parent.f_code, {}) if parent is not None else {}
                parent_entry = next((item for item in reversed(stack) if item[0] is parent), None)
                replan = parent.f_locals.get("replan") if parent is not None else None
                proof = {"parentFrameObjectId": str(id(parent)) if parent is not None else None,
                    "parentCallSequence": parent_entry[1]["sequence"] if parent_entry is not None else None,
                    "parentCode": parent_specification.get("code"),
                    "replanObjectId": str(id(replan)) if replan is not None else None,
                    "replanCodeIsCallback": getattr(replan, "__code__", None) is frame.f_code,
                    "databaseObjectId": str(id(db)),
                    "parentDatabaseObjectId": str(id(parent.f_locals.get("db"))) if parent is not None else None,
                    "parentStoreObjectId": str(id(parent.f_locals.get("store"))) if parent is not None else None,
                    "inTransaction": db.in_transaction if isinstance(db, sqlite3.Connection) else None}
                call["replanParent"] = proof
                if (parent_specification.get("name") != "purge_memory_index" or parent_entry is None
                        or not proof["replanCodeIsCallback"] or parent.f_locals.get("db") is not db):
                    self.failures.append({"phase": "original-replan-parent", "callSequence": call["sequence"],
                                          "proof": proof})
            self.local.stack = (*stack, (frame, call, scope, match, frame.f_code))
            if self.gate_callback is not None:
                self.gate_callback(frame, event, returned, call, scope)
        else:
            call = entry[1]
            submission = self.pending_submissions.pop(id(frame), None)
            if submission is not None and isinstance(returned, Future):
                task, store, job = submission
                task.update(futureObjectId=str(id(returned)), submitReturnedAtNs=str(time.monotonic_ns()))
                self.submitted_tasks.append({"receipt": task, "future": returned, "store": store, "job": job})
                self.bind_owner(returned, "original-submitted-future")
                self.bind_owner(returned._condition, "original-future-condition")
            returned_owner = ({"returnedOwnerObjectId": str(id(returned)),
                               "returnedOwnerType": {"module": type(returned).__module__, "name": type(returned).__qualname__}}
                              if specification.get("bindReturnedOwner") and returned is not None else {})
            receiver_key = specification.get("receiver")
            lookup = {"strategy": "retained-entry-frame", "frameObjectId": str(id(frame)),
                      "entryCallSequence": call["sequence"], "entryReceiverObjectId": call["receiverObjectId"],
                      "entryCode": deepcopy(specification.get("code")), "receiverLocalName": receiver_key,
                      "receiverLocalPresent": receiver_key is not None and receiver_key in frame.f_locals}
            if lookup["receiverLocalPresent"]:
                actual_receiver = frame.f_locals[receiver_key]
                lookup["receiverLocal"] = (_encode(actual_receiver) if actual_receiver is None
                    or type(actual_receiver) in (str, bool, int, float) else
                    {"objectId": str(id(actual_receiver)), "module": type(actual_receiver).__module__,
                     "className": type(actual_receiver).__qualname__})
            encoded_return = ({"module": type(returned).__module__, "className": type(returned).__qualname__,
                "objectId": str(id(returned))} if specification.get("returnIdentityOnly") and returned is not None
                else _encode(returned))
            row = self.event("original-return", callSequence=call["sequence"], name=specification["name"],
                callLabel=scope["label"], owner=owner_label, returned=encoded_return,
                returnLookup=lookup,
                **returned_owner,
                frameScalars={key: _encode(frame.f_locals[key]) for key in (
                    "live", "expected", "expected_revision", "expected_fence_revision", "current_revision",
                    "expected_fence", "expected_forget_revision", "generation", "mutation_generation",
                    "detector_generation", "observed_watch_generation", "settling_generation")
                    if key in frame.f_locals and (frame.f_locals[key] is None
                        or type(frame.f_locals[key]) in (bool, int, float, str))})
            if isinstance(returned, sqlite3.Connection):
                self._bind_connection(returned, scope, specification["name"])
            if specification.get("bindReturnedOwner") and returned is not None:
                self.bind_owner(returned, specification["bindReturnedOwner"])
                if specification["name"] == "ManagedSQLiteMemoryStore.memory_watcher":
                    self.bind_watcher(returned, receiver)
            if specification.get("bindConditionOnReturn"):
                condition = getattr(frame.f_locals.get("self"), "_condition", None)
                if condition is not None:
                    self.bind_owner(condition, "memory-watcher-condition")
            if self.gate_callback is not None:
                self.gate_callback(frame, event, returned, row, scope)
            self.local.stack = tuple(item for item in stack if item[0] is not frame)

    def _bind_connection(self, db, scope, source):
        if self.connections.get(id(db)) is db:
            return
        self.connections[id(db)] = db
        self.bind_owner(db, "sqlite-connection")
        connection_id = str(id(db))

        def trace(statement):
            pending = getattr(self.local, "sql_stack", ())
            stack = getattr(self.local, "stack", ())
            active_scope = (pending[-1][1].get("callScope") if pending and pending[-1][0] is db else
                            getattr(self.local, "scope", None) or (stack[-1][2] if stack else None)) or scope
            row = self.event("original-sql", connectionId=connection_id,
                             callLabel=active_scope["label"], callScope=deepcopy(active_scope),
                             connectionOpenedByScope=deepcopy(scope), source=source, statement=statement)
            if pending and pending[-1][0] is db:
                row["executionSequence"] = pending[-1][1]["sequence"]
                pending[-1][1].setdefault("statements", []).append(statement)
            self.sql.append(row)
            if self.sql_callback is not None:
                self.sql_callback(db, row, active_scope)

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
            if specification["name"] not in {"SQLiteMemoryStore.connect", "MemoryEntryOriginLedger._open_write",
                                             "SQLiteMemoryStore.is_session_forgotten", "_ReindexLease._open_database"}:
                return
            self._bind_connection(db, scope, specification["name"])
        stack = getattr(self.local, "sql_stack", ())
        if event == "c_call":
            row = self.event("original-sql-c-call", connectionId=str(id(db)), method=method,
                callLabel=scope["label"], callScope=deepcopy(scope), source=specification["name"], parentCode=specification.get("code"))
            if specification["name"] in {"SQLiteMemoryStore.is_session_forgotten", "_ReindexLease._open_database",
                                         "_ReindexLease.try_acquire", "_ReindexLease._close", "_ReindexLease.release"}:
                row.update(ownerDatabasePath=str(frame.f_locals["self"].path),
                           databaseOwnerObjectId=str(id(frame.f_locals["self"])))
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
               "snapshot", "close", "observe", "stop", "await-search-effects", "watch-ready", "watch-effects"}
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
    from memory_core.consolidation.forget import (
        _forget_workspace_memory, forget_memory_entries, purge_memory_index, plan_memory_index,
    )
    from memory_core.consolidation.origins import IndexRevisionFence, MemoryEntryOriginLedger
    from memory_core.consolidation.promotion import run_short_term_promotion, rank_short_term_promotion_candidates
    from memory_core.consolidation.recall import record_short_term_recalls
    from memory_core.consolidation import promotion
    from memory_core.host.managed_index import ManagedSQLiteMemoryStore
    from memory_core.index.sqlite_store import SQLiteMemoryStore, read_index_source
    from memory_core.index import sqlite_store
    from memory_core.index.publication import write_prepared_index
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.tools import memory_search as search_module
    from memory_core.tools.search_factory import MemorySearchTool
    from memory_core import atomic_publication
    from memory_core.consolidation.artifacts import write_dreams_file_atomic
    from memory_core.index.temporal_decay import apply_temporal_decay_to_hybrid_results

    methods = [(SQLiteMemoryStore, name) for name in (
        "connect", "reindex", "reindex_sources", "_reindex_locked", "publish_prepared_index",
        "search", "_search_candidates", "_search_keyword_with_fallback", "attach_recall_metadata", "_on_search_snapshot",
        "is_session_forgotten") if hasattr(SQLiteMemoryStore, name)]
    methods += [(ManagedSQLiteMemoryStore, name) for name in (
        "reindex", "reindex_sources", "search", "close", "_on_search_snapshot", "_submit_memory_publication",
        "_run_memory_publication", "_index_producer_guard", "_memory_watch_dirty", "_memory_watch_changed",
        "_memory_watch_unavailable", "_queue_memory_watch_publication", "wait_for_memory_watches")
        if hasattr(ManagedSQLiteMemoryStore, name)]
    methods += [(MemoryEntryOriginLedger, name) for name in (
        "_open_write", "_open_read", "record", "delete", "record_session_tombstones_if_lineage_current",
        "list_session_tombstones", "index_revision")]
    methods += [(IndexRevisionFence, name) for name in ("read", "assert_unchanged", "assert_unchanged_in", "bump", "bump_in")]
    methods += [(MemorySessionCatalog, name) for name in ("_connect", "upsert_session", "replace_events", "append_message", "snapshot")]
    methods += [(MemorySearchTool, name) for name in ("execute", "wait_for_recalls") if hasattr(MemorySearchTool, name)]
    methods += [(Future, "result"), (threading.Condition, "wait")]
    codes = {}
    for owner, name in methods:
        function = getattr(owner, name)
        function = getattr(function, "__wrapped__", function)
        codes[function.__code__] = {"name": f"{owner.__name__}.{name}", "receiver": "self",
                                    "code": _code_identity(function.__code__)}
    for function, receiver in ((forget_memory_entries, "store"), (purge_memory_index, "store"),
        (plan_memory_index, "store"), (ManagedSQLiteMemoryStore.__init__, None),
        (run_short_term_promotion, "store"), (rank_short_term_promotion_candidates, None),
        (record_short_term_recalls, None),
        (search_module.execute_memory_search_tool, "store"), (search_module._run_memory_search_tool, "store"),
        (write_prepared_index, "db"), (promotion.acquire_short_term_promotion_lock, None)):
        codes[function.__code__] = {"name": function.__qualname__, "receiver": receiver,
                                    "code": _code_identity(function.__code__)}
    optional = [(getattr(search_module, "_record_search_recalls", None), "store"),
                (getattr(SQLiteMemoryStore, "_existing_forget_revision", None), "db")]
    recall_class = getattr(search_module, "MemorySearchRecallOwner", None)
    if recall_class is not None:
        optional.extend(((recall_class.submit, "store"), (recall_class.wait, "self")))
    ledger_property = getattr(IndexRevisionFence, "ledger", None)
    if isinstance(ledger_property, property):
        optional.append((ledger_property.fget, "self"))
    guard = getattr(IndexRevisionFence, "publication_guard", None)
    if guard is not None:
        optional.append((getattr(guard, "__wrapped__", guard), "self"))
    for function, receiver in optional:
        if function is not None:
            codes[function.__code__] = {"name": function.__qualname__, "receiver": receiver,
                                       "code": _code_identity(function.__code__)}
    codes[ThreadPoolExecutor.submit.__code__] = {"name": "ThreadPoolExecutor.submit", "receiver": None,
                                                "code": _code_identity(ThreadPoolExecutor.submit.__code__)}
    if (SDK_ROOT / "memory_core" / "host" / "reindex_lease.py").is_file():
        lease_module = importlib.import_module("memory_core.host.reindex_lease")
        for name in ("_open_database", "try_acquire", "release", "waiting", "_close"):
            function = getattr(lease_module._ReindexLease, name)
            function = getattr(function, "__wrapped__", function)
            codes[function.__code__] = {"name": f"_ReindexLease.{name}", "receiver": "self",
                                       "code": _code_identity(function.__code__)}
        for name in ("_lease_for", "memory_index_producer_guard"):
            function = getattr(lease_module, name)
            function = getattr(function, "__wrapped__", function)
            codes[function.__code__] = {"name": name, "receiver": None, "code": _code_identity(function.__code__)}
            if name == "_lease_for":
                codes[function.__code__]["bindReturnedOwner"] = "original-reindex-producer-lease"
    if (SDK_ROOT / "memory_core" / "host" / "memory_watcher.py").is_file():
        watch_module = importlib.import_module("memory_core.host.memory_watcher")
        for owner, names in ((watch_module.MemoryFileWatcher, (
                "__init__", "start", "_run", "_dirty", "_deliver", "_unavailable", "_candidate", "_owned_file",
                "_version", "capture_versions", "_retained_targets", "wait_for_versions", "status", "snapshot", "close")),
                (watch_module._Inotify, ("__init__", "reconcile", "read", "close"))):
            for name in names:
                function = getattr(owner, name)
                codes[function.__code__] = {"name": f"{owner.__name__}.{name}",
                    "receiver": None if name in {"__init__", "start", "_version"} else "self",
                    "code": _code_identity(function.__code__)}
                if name == "__init__":
                    codes[function.__code__]["bindSelfOnCall"] = f"original-{owner.__name__}"
                    if owner is watch_module.MemoryFileWatcher:
                        codes[function.__code__]["bindConditionOnReturn"] = True
        for name in ("_inventory", "_directory_identity"):
            function = getattr(watch_module, name)
            codes[function.__code__] = {"name": name, "receiver": None, "code": _code_identity(function.__code__)}
        for name in ("delivery_generation", "settling_generation"):
            function = getattr(watch_module.MemoryFileWatcher, name).fget
            codes[function.__code__] = {"name": function.__qualname__, "receiver": "self",
                                       "code": _code_identity(function.__code__)}
        watcher_property = getattr(ManagedSQLiteMemoryStore, "memory_watcher", None)
        if isinstance(watcher_property, property):
            function = watcher_property.fget
            codes[function.__code__] = {"name": function.__qualname__, "receiver": "self",
                "code": _code_identity(function.__code__), "bindReturnedOwner": "memory-watcher",
                "returnIdentityOnly": True}
    for function in (SQLiteMemoryStore._reindex_locked, search_module._run_memory_search_tool):
        for code in _nested_codes(function.__code__):
            if code is function.__code__:
                continue
            codes[code] = {"name": code.co_qualname, "receiver": None, "code": _code_identity(code)}
    for code in _nested_codes(_forget_workspace_memory.__code__):
        if code.co_name == "current_index_plan":
            codes[code] = {"name": code.co_qualname, "receiver": None, "code": _code_identity(code),
                           "replanCallback": True}
    # The imported publication function must be the original used by the store.
    if sqlite_store.write_prepared_index is not write_prepared_index:
        raise RuntimeError("The SDK index publication owner is not its original imported function")
    for function in (atomic_publication._io, atomic_publication._write_all, atomic_publication._commit,
        atomic_publication._read_content, atomic_publication.append_memory_content, atomic_publication._write_existing_in_place,
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


def _search_factory_capabilities(factory):
    parameters = inspect.signature(factory).parameters
    return {"signature": str(inspect.signature(factory)), "parameters": list(parameters),
            "recallOrigins": "recall_origins" in parameters, "onEvent": "on_event" in parameters,
            "source": _code_identity(factory.__code__)}


def _await_existing_search_effects(tool, owner, tasks, receipt, *, timeout=PROCESS_TIMEOUT_SECONDS,
                                   partition_watch=False):
    """Join actual submitted effects; this checkpoint cannot admit a producer."""
    deadline = time.monotonic() + timeout

    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("The declared search-effects checkpoint exceeded its watchdog")
        return value

    receipt.update(enteredAtNs=str(time.monotonic_ns()), toolObjectId=str(id(tool)),
                   storeObjectId=str(id(owner)), conditionObjectId=str(id(owner._condition)),
                   tasksAtEntry=[deepcopy(task["receipt"]) for task in tasks], conditionWaits=[])
    if any(task["store"] is not owner or task["receipt"]["scope"].get("kind") != "search"
           or not isinstance(task["future"], Future)
           or task["receipt"]["futureObjectId"] != str(id(task["future"])) for task in tasks):
        raise RuntimeError("Search effects must retain this original owner's exact submitted Futures")
    wait = getattr(tool, "wait_for_recalls", None)
    receipt["recall"] = {"supported": callable(wait), "futureObjectIds": [str(id(task["future"]))
        for task in tasks if task["receipt"]["kind"] == "recall"]}
    if callable(wait):
        receipt["recall"]["enteredAtNs"] = str(time.monotonic_ns())
        returned = wait(timeout=remaining())
        receipt["recall"].update(returned=_encode(returned), returnedAtNs=str(time.monotonic_ns()))
    elif receipt["recall"]["futureObjectIds"]:
        raise RuntimeError("A source without recall-wait support owns a queued recall task")

    publications = [task for task in tasks if task["receipt"]["kind"] == "memory-publication"]
    with owner._condition:
        def state():
            return {"memoryActive": owner._memory_active,
                    "syncActivePresent": hasattr(owner, "_sync_active"),
                    "syncActive": getattr(owner, "_sync_active", False),
                    "fullSyncObjectId": str(id(owner._full_sync)) if getattr(owner, "_full_sync", None) is not None else None,
                    "jobs": _encode(tuple(getattr(owner, "_memory_jobs", ())))}

        receipt["publisherBefore"] = state()
        if partition_watch:
            receipt["partition"] = "retained-search-jobs"

        def pending():
            if partition_watch:
                return any(task["future"]._state in {"PENDING", "RUNNING"}
                    and isinstance(task["job"], dict) and task["job"].get("state") in {"queued", "running"}
                    for task in publications)
            return (owner._memory_active or getattr(owner, "_sync_active", False)
                    or getattr(owner, "_full_sync", None) is not None)

        while pending():
            if not any(task["future"]._state in {"PENDING", "RUNNING"} for task in publications):
                raise RuntimeError("An active publisher has no captured search-origin submission")
            row = {"enteredAtNs": str(time.monotonic_ns()), "stateBefore": state()}
            receipt["conditionWaits"].append(row)
            returned = owner._condition.wait(timeout=remaining())
            row.update(returned=returned, returnedAtNs=str(time.monotonic_ns()), stateAfter=state())
        receipt["publisherAfter"] = state()
    # Readiness is notified in the worker's finally block, before its Future
    # settles. Join those exact Futures after releasing the owner condition.
    receipt["publisherFutures"] = []
    for task in publications:
        row = {"futureObjectId": str(id(task["future"])), "enteredAtNs": str(time.monotonic_ns())}
        receipt["publisherFutures"].append(row)
        try:
            row["returned"] = _encode(task["future"].result(timeout=remaining()))
        except BaseException as error:
            row["error"] = _error(error)
            raise
        finally:
            row["settledAtNs"] = str(time.monotonic_ns())
    receipt["returnedAtNs"] = str(time.monotonic_ns())
    receipt["tasksAtReturn"] = [{**deepcopy(task["receipt"]), "future": _encode(task["future"]),
        "job": _encode(dict(task["job"]) if isinstance(task["job"], dict) else task["job"])} for task in tasks]
    return receipt


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
        self.adapter_before = _adapter_sources(self.value["kind"]) if self.value["kind"] in SEARCH_EFFECT_KINDS else None
        self.imported_before = _loaded_sdk()
        self.storage = _storage(self.value, self.directory)
        self.root = self.directory / "workspace"
        self.owner = self.catalog = self.ledger = self.provenance = self.workspace = self.config = None
        self.futures = {}
        self.public_calls = {}
        self.search_tools, self.search_effect_waits = {}, []
        self.watch_ready_waits, self.watch_effect_waits = [], []
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
        origin_connection = row["source"] == "MemoryEntryOriginLedger._open_write"
        if index_connection or origin_connection:
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
            "callScope": deepcopy(self._active_scope())})

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
            self.observer.bind_owner(self.owner._condition, "managed-index-condition")
            watcher = getattr(self.owner, "memory_watcher", None)
            if watcher is not None:
                self.observer.bind_watcher(watcher, self.owner)
            with closing(self.owner.connect()) as db:
                journal_mode = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        record = {"actor": self.actor, "pid": os.getpid(), "storeObjectId": str(id(self.owner)),
            "storeClass": type(self.owner).__qualname__, "workspaceObjectId": str(id(self.workspace)),
            "catalogObjectId": str(id(self.catalog)), "ledgerObjectId": str(id(self.ledger)),
            "configObjectId": str(id(self.config)), "config": _encode(self.config), "storage": _encode(self.storage),
            "memoryPublication": self.owner._memory_publication, "explicitFence": fence is not None,
            "forgottenCallback": callback is not None, "catalogTombstoneMirror": False}
        record["declaredPhysicalPreparation"] = {"statement": "PRAGMA journal_mode=WAL", "returned": journal_mode}
        record["classMro"] = _type_identity(type(self.owner))["mro"]
        record["constructorCode"] = _code_identity(ManagedSQLiteMemoryStore.__init__.__code__)
        record["searchMaintenance"] = _search_maintenance_binding(self.owner, config.get("sync"))
        if self.value["kind"] in {"forget-index-fence-v5", "forget-index-fence-v6"}:
            record["memoryWatcher"] = {"present": watcher is not None,
                "objectId": str(id(watcher)) if watcher is not None else None,
                "classMro": _type_identity(type(watcher))["mro"] if watcher is not None else None,
                "status": watcher.status() if watcher is not None else None,
                "root": str(watcher.root) if watcher is not None else None}
        predicate = self.workspace.is_session_forgotten
        predicate_function = getattr(predicate, "__func__", predicate)
        record["effectiveForgottenCallback"] = {"present": predicate is not None,
            "callable": _encode(predicate),
            "boundReceiverObjectId": str(id(predicate.__self__)) if getattr(predicate, "__self__", None) is not None else None,
            "code": _code_identity(predicate_function.__code__) if hasattr(predicate_function, "__code__") else None}
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

    def _capture_watch_targets(self, call):
        key = f"{call['kind']}:{call['label']}"
        captured = {"callKey": key, "actor": self.actor, "pid": os.getpid(),
            "storeObjectId": str(id(self.owner)), "watcherObjectId": None,
            "capturedAtNs": str(time.monotonic_ns()), "mutations": [], "versions": [], "absence": None}
        call["watchTargetCapture"] = captured
        with self.observer.call_scope(key, "watch-control"):
            watcher = getattr(self.owner, "memory_watcher", None)
            captured["watcherObjectId"] = str(id(watcher)) if watcher is not None else None
            mutations = [("source-write-clock", row, row["absolutePath"])
                for row in tuple(self.source_clock.receipts) if row.get("callKey") == key and row.get("committed")]
            mutations.extend(("source-delete", row, row["arguments"][0])
                for row in tuple(self.source_clock.original_io)
                if row.get("syscall") == "unlink" and (row.get("scope") or {}).get("kind") == call["kind"]
                and row["scope"].get("label") == call["label"] and row.get("arguments")
                and str(row["arguments"][0]).endswith((".md", ".txt")))
            mutations.sort(key=lambda item: int(item[1]["atNs"]))
            for receipt_kind, receipt, path in mutations:
                row = {"receiptKind": receipt_kind, "receiptSequence": receipt["sequence"],
                    "receipt": _observation_copy(receipt), "capture": None, "applicabilityError": None}
                captured["mutations"].append(row)
                if watcher is None:
                    continue
                try:
                    versions = watcher.capture_versions([path])
                except ValueError as error:
                    # The real source API owns eligibility. Preserve its
                    # rejection instead of guessing another watch path.
                    row["applicabilityError"] = _error(error)
                    continue
                row["capture"] = _observation_copy(versions)
                if receipt_kind == "source-write-clock":
                    actual = receipt["committedState"]["stat"]
                    expected = {"device": str(actual["st_dev"]), "inode": str(actual["st_ino"]),
                        "size": int(actual["st_size"]), "mtimeNs": str(actual["st_mtime_ns"]),
                        "ctimeNs": str(actual["st_ctime_ns"])}
                    matches = versions == [{"path": str(path), "exists": True, "version": expected}]
                else:
                    matches = versions == [{"path": str(path), "exists": False, "version": None}]
                if not matches:
                    self.observer.failures.append({"phase": "watch-target-version", "callKey": key,
                        "receiptSequence": receipt["sequence"], "capture": _observation_copy(versions)})
                    continue
                captured["versions"].extend(_observation_copy(versions))
            if watcher is None:
                captured["absence"] = "no-existing-memory-watcher"
            elif not captured["versions"]:
                captured["absence"] = "no-applicable-successful-watched-source-mutation"
        captured["completedAtNs"] = str(time.monotonic_ns())

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
                    capabilities = _search_factory_capabilities(create_memory_search_tool)
                    recall_options = {}
                    if capabilities["recallOrigins"]:
                        recall_options["recall_origins"] = self.ledger
                    if capabilities["onEvent"]:
                        recall_options["on_event"] = self._host_event
                    tool = create_memory_search_tool(self.config, self.owner,
                        context=MemorySearchToolContext(clock=lambda: self.wall_ms, source_policy=policy,
                            session_visibility=SessionVisibilityContext.from_catalog(self.catalog)),
                        agent_session_key=self.value["identity"]["requesterSessionKey"],
                        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, **recall_options)
                    if tool is None:
                        raise RuntimeError("The original search factory returned no tool")
                    self.observer.bind_owner(tool, "public-memory-search-tool")
                    recall_owner = getattr(tool, "_recall_owner", None)
                    if recall_owner is not None:
                        self.observer.bind_owner(recall_owner, "search-recall-owner")
                    wait_method = getattr(tool, "wait_for_recalls", None)
                    capabilities.update(toolObjectId=str(id(tool)), recallOwnerObjectId=str(id(recall_owner))
                        if recall_owner is not None else None, waitForRecalls=callable(wait_method),
                        waitSource=_code_identity(wait_method.__func__.__code__) if callable(wait_method) else None)
                    call["searchFactoryCapabilities"] = capabilities
                    self.search_tools[label] = {"tool": tool, "owner": self.owner, "capabilities": capabilities}
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
                if self.value["kind"] in {"forget-index-fence-v5", "forget-index-fence-v6"}:
                    try:
                        self._capture_watch_targets(call)
                    except BaseException as error:
                        self.observer.failures.append({"phase": "watch-target-capture", "callKey": f"{kind}:{label}",
                                                      "error": _error(error)})
                call["returnSeq"] = self.observer.event("public-call-return", label=label, kind=kind)["sequence"]
                if kind == "search" and label in self.search_tools:
                    tasks = [task for task in self.observer.submitted_tasks if task["store"] is self.owner
                        and task["receipt"]["scope"].get("kind") == "search"
                        and task["receipt"]["scope"].get("label") == label]
                    self.search_tools[label]["tasksAtPublicSettle"] = tuple(tasks)
                    call["effectsAtPublicSettle"] = [{**deepcopy(task["receipt"]),
                        "future": _encode(task["future"]),
                        "job": _encode(dict(task["job"]) if isinstance(task["job"], dict) else task["job"])} for task in tasks]
        return deepcopy(call)

    def snapshot(self, label):
        from memory_core.consolidation.artifacts import read_memory_preimages
        from memory_core.consolidation.session_ingestion import read_session_ingestion_state
        from memory_core.consolidation.store import (read_recall_store, recall_store_path,
            read_phase_signal_store, phase_signal_store_path)

        self._assert_search_effects_settled()
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

    def _assert_search_effects_settled(self):
        if self.value["kind"] not in SEARCH_EFFECT_KINDS:
            return
        missing = [label for label, binding in self.search_tools.items()
            if "returnSeq" in self.public_calls.get("search:" + label, {}) and not binding.get("effectsSettled")]
        if missing:
            raise RuntimeError("Settled searches require their declared effects barrier before snapshot or close: "
                               + ", ".join(missing))

    def _watch_ready(self, label):
        """Inspect only the already constructed original watch owner and resources."""
        waits = getattr(self, "watch_ready_waits", None)
        if waits is None:
            self.watch_ready_waits = waits = []
        owner = self.owner
        row = {"label": label, "actor": self.actor, "pid": os.getpid(),
            "ownerObjectId": str(id(owner)) if owner is not None else None, "watcherObjectId": None,
            "ownerClosed": None, "status": None, "snapshot": None, "resources": None, "sourceRoles": {}}
        waits.append(row)

        def registered(value):
            function = value.fget if isinstance(value, property) else getattr(value, "__func__", value)
            code = getattr(function, "__code__", None)
            binding = self.observer.codes.get(code)
            return {"registered": binding is not None, "module": getattr(function, "__module__", None),
                "qualname": getattr(function, "__qualname__", None),
                "code": _observation_copy(binding.get("code")) if binding is not None else None}

        with self.observer.call_scope(label, "watch-control"):
            row["enterSeq"] = self.observer.event("watch-ready-control-enter", label=label)["sequence"]
            try:
                if owner is None:
                    row["outcome"] = {"status": "absent", "reason": "original-owner-not-acquired"}
                    return row
                row["ownerClosed"] = owner.closed
                row["sourceRoles"]["memoryWatcherProperty"] = registered(getattr(type(owner), "memory_watcher", None))
                if row["ownerClosed"]:
                    row["outcome"] = {"status": "absent", "reason": "original-owner-closed"}
                    return row
                watcher = getattr(owner, "memory_watcher", None)
                if watcher is None:
                    row["outcome"] = {"status": "absent", "reason": "original-owner-has-no-watcher"}
                    return row
                row["watcherObjectId"] = str(id(watcher))
                row["sourceRoles"].update({name: registered(getattr(watcher, name, None))
                                           for name in ("start", "status", "snapshot")})
                row["status"] = _observation_copy(watcher.status())
                row["snapshot"] = _observation_copy(watcher.snapshot())
                backend = getattr(watcher, "_backend", None)
                thread = getattr(watcher, "_thread", None)
                paths = dict.copy(backend.paths) if backend is not None else {}
                descriptors = dict.copy(backend.descriptors) if backend is not None else {}
                row["resources"] = {"backendObjectId": str(id(backend)) if backend is not None else None,
                    "fd": backend.fd if backend is not None else None,
                    "paths": [{"path": str(path), "watchDescriptor": value[0], "identity": _encode(value[1])}
                              for path, value in paths.items()],
                    "descriptors": [{"watchDescriptor": descriptor, "path": str(path)}
                                    for descriptor, path in descriptors.items()],
                    "shutdownPipe": _encode(getattr(watcher, "_pipe", None)),
                    "threadObjectId": str(id(thread)) if thread is not None else None,
                    "threadId": thread.ident if thread is not None else None,
                    "threadAlive": thread.is_alive() if thread is not None else False}
                status = row["status"]
                ready = (status.get("started") is True and status.get("closed") is False
                    and status.get("alive") is True and row["resources"]["threadAlive"] is True
                    and all(role["registered"] for role in row["sourceRoles"].values()))
                row["outcome"] = ({"status": "ready"} if ready else
                    {"status": "absent", "reason": "original-watcher-readiness-not-proved"})
            except BaseException as error:
                row["error"] = _error(error)
                row["outcome"] = {"status": "rejected"}
                raise
            finally:
                row["returnSeq"] = self.observer.event("watch-ready-control-return", label=label)["sequence"]
        return _observation_copy(row)

    def _watch_effects(self, label, versions, source_calls, interrupted_source_calls=()):
        """Join retained targets through the existing original managed API once."""
        waits = getattr(self, "watch_effect_waits", None)
        if waits is None:
            self.watch_effect_waits = waits = []
        owner = self.owner
        row = {"label": label, "actor": self.actor, "pid": os.getpid(),
            "ownerObjectId": str(id(owner)) if owner is not None else None, "watcherObjectId": None,
            "ownerClosed": None, "versions": _observation_copy(versions),
            "sourceCalls": _observation_copy(source_calls),
            "interruptedSourceCalls": _observation_copy(interrupted_source_calls), "status": None, "api": None}
        waits.append(row)
        with self.observer.call_scope(label, "watch-control"):
            row["enterSeq"] = self.observer.event("watch-effects-control-enter", label=label)["sequence"]
            try:
                if owner is None:
                    row["outcome"] = {"status": "absent", "reason": "original-owner-not-acquired"}
                    return row
                row["ownerClosed"] = owner.closed
                if row["ownerClosed"]:
                    row["outcome"] = {"status": "absent", "reason": "original-owner-closed"}
                    return row
                watcher = getattr(owner, "memory_watcher", None)
                if watcher is None:
                    row["outcome"] = {"status": "absent", "reason": "original-owner-has-no-watcher"}
                    return row
                row["watcherObjectId"] = str(id(watcher))
                row["status"] = _observation_copy(watcher.status())
                if not versions:
                    row["outcome"] = ({"status": "interrupted-before-source-publication"} if interrupted_source_calls else
                        {"status": "no-applicable-targets"} if source_calls else
                        {"status": "absent", "reason": "no-original-source-call-proof"})
                    return row
                wait = getattr(owner, "wait_for_memory_watches", None)
                if not callable(wait):
                    row["outcome"] = {"status": "absent", "reason": "original-watch-wait-api-unavailable"}
                    return row
                function = getattr(wait, "__func__", wait)
                binding = self.observer.codes.get(getattr(function, "__code__", None))
                row["api"] = {"receiverObjectId": str(id(getattr(wait, "__self__", None))),
                    "registered": binding is not None, "module": getattr(function, "__module__", None),
                    "qualname": getattr(function, "__qualname__", None),
                    "code": _observation_copy(binding.get("code")) if binding is not None else None}
                returned = wait(_observation_copy(versions), timeout=PROCESS_TIMEOUT_SECONDS - 5)
                row["returned"] = _observation_copy(returned)
                row["outcome"] = {"status": "fulfilled"}
            except BaseException as error:
                row["error"] = _error(error)
                row["outcome"] = {"status": "rejected"}
                raise
            finally:
                row["returnSeq"] = self.observer.event("watch-effects-control-return", label=label)["sequence"]
        return _observation_copy(row)

    def observation(self):
        return {"actor": self.actor, "pid": os.getpid(), "sourceProvenanceBefore": self.before,
            **({"adapterProvenanceBefore": self.adapter_before, "adapterProvenanceAfter": _adapter_sources(self.value["kind"]),
                "loadedFixtureModules": _loaded_fixtures()} if self.adapter_before is not None else {}),
            "sourceProvenanceAfter": _sdk_sources(), "importedBefore": self.imported_before, "loadedSdk": _loaded_sdk(),
            "codeOwners": list(self.observer.codes.values()), "ownerBindings": _observation_copy(self.bindings),
            "originalCalls": _observation_copy(self.observer.snapshot_events()), "originalExceptions": _observation_copy(self.observer.exceptions),
            "observerFailures": _observation_copy(self.observer.failures),
            "sqlStatements": _observation_copy(self.observer.sql), "sqlExecutions": _observation_copy(self.observer.sql_executions),
            "functionalGates": {key: gate.snapshot() for key, gate in self.gates.items()},
            "publicCalls": _observation_copy(self.public_calls), "catalogSourceFacts": _observation_copy(self.catalog_facts),
            "hostEvents": _observation_copy(self.host_events), "hostEventReceipts": _observation_copy(self.host_event_receipts),
            "clockBindings": _observation_copy(self.clock_bindings), "datetimeClockCalls": _observation_copy(self.datetime_clock_calls),
            "datetimeClockFailures": _observation_copy(self.datetime_proxy.failures),
            **_source_clock_observation(self.source_clock),
            "queuedSearchTasks": [row for row in self.observer.task_receipts()
                if self.value["kind"] not in {"forget-index-fence-v5", "forget-index-fence-v6"} or row["scope"]["kind"] == "search"],
            **({"queuedWatchTasks": [row for row in self.observer.task_receipts() if row["scope"]["kind"] == "watch"],
                "queuedOriginalTasks": self.observer.task_receipts(),
                "watchReadyWaits": _observation_copy(self.watch_ready_waits),
                "watchEffectWaits": _observation_copy(self.watch_effect_waits)}
               if self.value["kind"] in {"forget-index-fence-v5", "forget-index-fence-v6"} else {}),
            "searchEffectWaits": _observation_copy(self.search_effect_waits),
            "ppid": os.getppid(), "wallClockNowMs": self.wall_ms,
            "providerIdentity": _encode(self.owner._index_provider()) if self.owner is not None else {"unacquired": True},
            "process": {"cwd": str(Path.cwd()), "executable": sys.executable, "version": sys.version,
                "cmdlineHex": Path("/proc/self/cmdline").read_bytes().hex()}}

    def command(self, command):
        _validate_actor_command(command, self.gates)
        operation = command["operation"]
        if operation == "watch-ready":
            return self._watch_ready(command["label"])
        if operation == "watch-effects":
            return self._watch_effects(command["label"], command["versions"], command["sourceCalls"],
                                       command.get("interruptedSourceCalls", ()))
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
        if operation == "await-search-effects":
            if self.value["kind"] not in SEARCH_EFFECT_KINDS:
                raise ValueError("Search effect waits require their separately frozen V3 profile")
            label = command["label"]
            call = self.public_calls.get("search:" + label)
            binding = self.search_tools.get(label)
            if (call is None or "returnSeq" not in call or binding is None or binding["owner"] is not self.owner
                    or call["pid"] != os.getpid()):
                raise ValueError("Only this actor's settled original search can join its captured effects")
            tasks = binding["tasksAtPublicSettle"]
            maximum = self.value["observationPolicy"]["searchEffects"]["maxReferencesPerBarrier"]
            if len(tasks) > maximum:
                raise RuntimeError("The actual search effects exceed the frozen finite-reference bound")
            receipt = {"label": label, "actor": self.actor, "pid": os.getpid(),
                "publicReturnSequence": call["returnSeq"], "factoryCapabilities": deepcopy(binding["capabilities"])}
            self.search_effect_waits.append(receipt)
            try:
                with self.observer.call_scope(label, "search", self.wall_ms):
                    returned = _await_existing_search_effects(binding["tool"], self.owner, tasks, receipt,
                        timeout=PROCESS_TIMEOUT_SECONDS - 5,
                        partition_watch=self.value["kind"] in {"forget-index-fence-v5", "forget-index-fence-v6"})
                binding["effectsSettled"] = True
                return returned
            except BaseException as error:
                receipt["error"] = _error(error)
                raise
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
            self._assert_search_effects_settled()
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
    if request.get("adapterRoot", str(ROOT)) != str(ROOT):
        raise ValueError("The actor must use its actual loaded adapter root")
    if "sdkRoot" in request:
        _configure_sdk_root(request["sdkRoot"])
    _literal(request["input"])
    actor = _SdkActor(request)
    for line in sys.stdin:
        command = json.loads(line)
        try:
            result = actor.command(command)
            response = {"id": command["id"], "ok": True, "result": _encode(result)}
        except BaseException as error:
            response = {"id": command.get("id"), "ok": False, "error": _error(error)}
        try:
            response["observation"] = actor.observation()
        except BaseException as error:
            # A codec/observer failure is not an error of the original command.
            # Keep its already captured result/error and identify the control failure.
            response["observationInvalid"] = {"phase": "actor-observation", "error": _error(error)}
        sys.stdout.write(_serialized(response) + "\n")
        sys.stdout.flush()
        if command.get("operation") == "stop":
            break
    actor.executor.shutdown(wait=True)


class _ActorProcess:
    def __init__(self, value, directory, actor):
        self.actor, self.directory = actor, directory
        self.request = {"mode": "actor", "input": value, "directory": str(directory), "actor": actor}
        if value["kind"] in SEARCH_EFFECT_KINDS or SDK_ROOT != ROOT:
            self.request["sdkRoot"] = str(SDK_ROOT)
        if value["kind"] in SEARCH_EFFECT_KINDS:
            self.request["adapterRoot"] = str(ROOT)
        self.argv = [sys.executable, "-m", "equivalence.forget_index_fence_sdk_cli"]
        self.environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
            "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC",
            "OPENCLAW_HOME": str(directory), "OPENCLAW_STATE_DIR": str(directory / "state")}
        if value["kind"] in SEARCH_EFFECT_KINDS:
            self.environment["PYTHONDONTWRITEBYTECODE"] = "1"
        self.child = subprocess.Popen(self.argv, cwd=ROOT, env=self.environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.receipt = {"actor": actor, "pid": self.child.pid, "argv": self.argv,
            "cwd": str(ROOT), "environment": deepcopy(self.environment),
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
        self.receipt["stdoutLines"].append(line)
        response = json.loads(line)
        self.receipt["stdoutResponses"].append(deepcopy(response))
        if isinstance(response.get("observation"), dict):
            self.receipt["observation"] = deepcopy(response["observation"])
        if "fatal" in response:
            self.receipt.setdefault("observationFailures", []).append({"commandId": command["id"], "fatal": response["fatal"]})
            raise RuntimeError("The original SDK actor emitted a fatal control failure: " + _serialized(response["fatal"]))
        if response.get("id") != command["id"]:
            raise RuntimeError("The original actor returned another command's receipt")
        if "observationInvalid" in response:
            self.receipt.setdefault("observationFailures", []).append({"commandId": command["id"],
                                                                       **response["observationInvalid"]})
            raise RuntimeError("The SDK observer failed after the actual command settlement; complete result retained")
        if not response.get("ok"):
            raise RuntimeError(f"Original SDK actor command failed: {_serialized(response.get('error'))}")
        if operation == "acquire":
            self.acquired = True
        return response["result"]

    def kill(self):
        self.receipt["kill"] = {"signal": "SIGKILL", "pid": self.child.pid, "pollBefore": self.child.poll(),
                                "enteredAtNs": str(time.monotonic_ns())}
        returned = self.child.kill()
        self.receipt["kill"].update(returnedAtNs=str(time.monotonic_ns()), returnValue=_encode(returned))

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


def _select_snapshot_receiver(actors, requested_actor=None):
    """Observe through an existing live owner without acquiring another one."""
    candidates = [{"actor": name, "pid": process.child.pid,
                   "poll": process.child.poll(), "acquired": process.acquired}
                  for name, process in actors.items()]
    available = {row["actor"]: row for row in candidates if row["poll"] is None and row["acquired"]}
    preferred = requested_actor if requested_actor is not None else "foreground"
    if preferred in available:
        selected = preferred
        reason = "explicit-live-acquired-actor" if requested_actor is not None else "implicit-foreground-live-acquired"
    elif requested_actor is not None:
        raise ValueError(f"The selected SDK snapshot actor is not live and acquired: {requested_actor}")
    elif available:
        selected = next(iter(available))
        reason = "implicit-live-acquired-fallback"
    else:
        raise ValueError("A physical snapshot requires an already live and acquired SDK actor")
    return actors[selected], {"requestedActor": requested_actor, "preferredActor": preferred,
                              "selectedActor": selected, "pid": available[selected]["pid"],
                              "reason": reason, "candidates": candidates}


def _interrupted_source_call(call_key, call, processes):
    """Retain an authenticated gate-held interruption, never a completion."""
    if ("returnSeq" in call or "watchTargetCapture" in call or "apiEntry" not in call or "enterSeq" not in call
            or call.get("termination", {}).get("signal") != "SIGKILL"):
        raise RuntimeError("A missing watch target capture is not a proved interrupted original call")
    process = next((row for row in processes if row["pid"] == call.get("pid")), None)
    if (process is None or process.get("kill", {}).get("signal") != "SIGKILL"
            or process.get("kill", {}).get("pid") != call["pid"] or process.get("kill", {}).get("pollBefore") is not None
            or (process.get("exit") or {}).get("code") != -9 or not process.get("reapedAtNs")):
        raise RuntimeError("An interrupted source call requires its actual SIGKILL and process reap")
    responses = process.get("stdoutResponses", [])
    matching = [(index, row) for index, row in enumerate(responses)
        if call_key in row.get("observation", {}).get("publicCalls", {})]
    if not matching:
        raise RuntimeError("The interrupted original frame has no captured observation")
    response_index, response = matching[-1]
    observation = response["observation"]
    original = observation["publicCalls"][call_key]
    if "returnSeq" in original or "watchTargetCapture" in original:
        raise RuntimeError("An actual completed call cannot be relabelled interrupted")
    if original != {key: value for key, value in call.items() if key != "termination"}:
        raise RuntimeError("The interrupted source call differs from its actual observed pending frame")
    gates = [(name, gate) for name, gate in observation.get("functionalGates", {}).items()
        if gate.get("reached") is True and gate.get("released") is False
        and gate["specification"].get("boundary") == "forget.marker-committed-before-purge"
        and gate["specification"].get("callLabel") == call["label"]]
    if len(gates) != 1 or not gates[0][1].get("hits"):
        raise RuntimeError("The interrupted source frame is not held at the actual marker-before-purge gate")
    trigger = gates[0][1]["hits"][0]["triggerSequence"]
    entered = next((row for row in observation.get("originalCalls", []) if row["sequence"] == trigger), None)
    kill = process["kill"]
    if (entered is None or "atNs" not in entered or not kill.get("enteredAtNs") or not kill.get("returnedAtNs")
            or not int(kill["enteredAtNs"]) <= int(kill["returnedAtNs"]) <= int(process["reapedAtNs"])
            or int(kill["returnedAtNs"]) >= int(entered["atNs"]) + GATE_TIMEOUT_SECONDS * 1_000_000_000):
        raise RuntimeError("The original process was not killed inside the captured gate's real hold deadline")
    io = [row for row in observation.get("sourceClockOriginalIO", [])
        if (row.get("scope") or {}).get("kind") == call["kind"]
        and row["scope"].get("label") == call["label"]]
    clocks = [row for row in observation.get("sourceClockReceipts", []) if row.get("callKey") == call_key]
    if any(row.get("committed") for row in clocks) or any(
            row.get("syscall") in {"write", "pwrite", "replace", "unlink"} for row in io):
        raise RuntimeError("An interrupted original call has source mutations requiring retained positive custody")
    return {"kind": "original-interrupted-source-call", "callKey": call_key,
        "actor": call["actor"], "pid": call["pid"], "call": _observation_copy(call),
        "sourceObservation": {"pid": process["pid"], "commandId": response["id"], "stdoutResponseIndex": response_index},
        "markerGate": {"name": gates[0][0], **_observation_copy(gates[0][1])},
        "sourceIOCutoff": {"originalIO": _observation_copy(io), "sourceClockReceipts": _observation_copy(clocks),
            "lastOriginalSequence": max((row["sequence"] for row in observation.get("originalCalls", [])), default=None),
            "lastSourceIOSequence": max((row["sequence"] for row in observation.get("sourceClockOriginalIO", [])), default=None)},
        "kill": _observation_copy(process["kill"]),
        "reap": {"exit": _observation_copy(process["exit"]), "reapedAtNs": process["reapedAtNs"]}}


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
    if not isinstance(request, dict) or set(request) not in (
            {"input", "directory"}, {"input", "directory", "sdkRoot"}, {"input", "directory", "sdkRoot", "adapterRoot"}):
        raise ValueError("The protected SDK host requires exactly input and directory")
    value, directory = request["input"], Path(request["directory"])
    if request.get("adapterRoot", str(ROOT)) != str(ROOT):
        raise ValueError("The host must use its actual loaded adapter root")
    if "sdkRoot" in request:
        _configure_sdk_root(request["sdkRoot"])
    _literal(value)
    if not directory.is_absolute() or not directory.is_dir() or directory.is_symlink():
        raise ValueError("An existing absolute fixture directory is required")
    before = _sdk_sources()
    actors, processes, steps, snapshots, calls = {}, [], [], {}, {}
    common_snapshots = {}
    wall_ms = value["clock"]["nowMs"]
    raw = {"kind": value["kind"] + "-sdk-host", "input": deepcopy(value), "pid": os.getpid(),
        "adapterRoot": str(ROOT), "sdkRoot": str(SDK_ROOT),
        "fixtureRoot": str(directory), "sourceProvenanceBefore": before, "processes": processes,
        "steps": steps, "physicalSnapshots": snapshots, "publicCalls": calls}
    if value["kind"] in SEARCH_EFFECT_KINDS:
        raw["adapterProvenanceBefore"] = _adapter_sources(value["kind"])

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
            elif operation == "await-original-search-effects":
                record["returned"] = actors[actor].command("await-search-effects", label=label)
            elif operation in {"await-original-watch-ready", "await-original-watch-effects"}:
                source_calls, retained_versions, interrupted_source_calls = [], [], []
                if operation == "await-original-watch-effects":
                    for call_key in step["afterCalls"]:
                        if call_key not in calls:
                            raise ValueError("A watch effects barrier has no actual declared source call: " + call_key)
                        original_call = _observation_copy(calls[call_key])
                        capture = original_call.get("watchTargetCapture")
                        if isinstance(capture, dict):
                            source_calls.append(original_call)
                            retained_versions.extend(_observation_copy(capture.get("versions", [])))
                        elif original_call.get("termination"):
                            interrupted_source_calls.append(_interrupted_source_call(call_key, original_call, processes))
                        else:
                            raise RuntimeError("A completed source call has no original completion-time target capture")
                record["returned"] = []
                for selected_actor in step["actors"]:
                    process = actors.get(selected_actor)
                    lifecycle = {"actor": selected_actor, "processPresent": process is not None,
                        "pid": process.child.pid if process is not None else None,
                        "poll": process.child.poll() if process is not None else None,
                        "acquired": process.acquired if process is not None else False}
                    last_owner_closed = None
                    if process is not None:
                        responses = {response.get("id"): response for response in process.receipt["stdoutResponses"]}
                        for command in process.receipt["stdinCommands"]:
                            response = responses.get(command["id"], {})
                            if response.get("ok") is True and command["operation"] == "acquire":
                                last_owner_closed = False
                            elif response.get("ok") is True and command["operation"] == "close":
                                last_owner_closed = response.get("result", {}).get("closed")
                    lifecycle["ownerClosedFromOriginalReceipt"] = last_owner_closed
                    if process is None or lifecycle["poll"] is not None or not lifecycle["acquired"] or last_owner_closed is True:
                        reason = ("actor-never-started" if process is None else "original-process-exited"
                            if lifecycle["poll"] is not None else "original-owner-not-acquired"
                            if not lifecycle["acquired"] else "original-owner-closed")
                        result = {"label": label, "actor": selected_actor, "lifecycle": lifecycle,
                            "outcome": {"status": "absent", "reason": reason}}
                        if operation == "await-original-watch-effects":
                            result.update(versions=_observation_copy(retained_versions), sourceCalls=_observation_copy(source_calls),
                                interruptedSourceCalls=_observation_copy(interrupted_source_calls))
                    else:
                        control = "watch-ready" if operation == "await-original-watch-ready" else "watch-effects"
                        options = {} if control == "watch-ready" else {
                            "versions": _observation_copy(retained_versions), "sourceCalls": _observation_copy(source_calls),
                            "interruptedSourceCalls": _observation_copy(interrupted_source_calls)}
                        result = process.command(control, label=label, **options)
                        lifecycle["commandId"] = process.counter
                        result = {**result, "lifecycle": lifecycle}
                    record["returned"].append(result)
            elif operation in {"arm-gate", "await-gate", "release-gate"}:
                record["returned"] = actors[gate_actor(step["gate"])].command(operation, gate=step["gate"])
            elif operation == "capture-physical-state":
                receiver, record["snapshotReceiver"] = _select_snapshot_receiver(actors, step.get("actor"))
                record["returned"] = receiver.command("snapshot", label=label)
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
        if value["kind"] in SEARCH_EFFECT_KINDS:
            raw["adapterProvenanceAfter"] = _adapter_sources(value["kind"])
    clock_failures = [{"actor": process["actor"], "pid": process["pid"],
        "sourceClockFailures": process["observation"].get("sourceClockFailures", []),
        "datetimeClockFailures": process["observation"].get("datetimeClockFailures", []),
        "observerFailures": process["observation"].get("observerFailures", [])}
        for process in processes if process.get("observation") and (
            process["observation"].get("sourceClockFailures") or process["observation"].get("datetimeClockFailures")
            or process["observation"].get("observerFailures"))]
    observation_failures = [{"actor": process["actor"], "pid": process["pid"], "failures": process["observationFailures"]}
                            for process in processes if process.get("observationFailures")]
    raw["observationInvalid"] = [*clock_failures, *observation_failures]
    raw["complete"] = "error" not in raw and not raw["observationInvalid"]
    raw["result"] = {"provider": "none", "calls": _common_calls(calls, directory / "workspace"),
                     "snapshots": common_snapshots}
    return raw


def run_forget_index_fence_sdk_case(value, *, evidence_directory=None, sdk_root=None):
    """Protected once-only outer process; retain full streams even on failure."""
    _literal(value)
    selected_sdk = _validated_sdk_root(ROOT if sdk_root is None else sdk_root)
    if evidence_directory is not None:
        Path(evidence_directory).mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="sdk-forget-index-fence-", dir=evidence_directory)).resolve()
    destination = Path(evidence_directory) if evidence_directory is not None else directory
    request = {"input": value, "directory": str(directory)}
    if value["kind"] in SEARCH_EFFECT_KINDS or sdk_root is not None:
        request["sdkRoot"] = str(selected_sdk)
    if value["kind"] in SEARCH_EFFECT_KINDS:
        request["adapterRoot"] = str(ROOT)
    wire = _serialized(request)
    argv = [sys.executable, "-m", "equivalence.forget_index_fence_sdk_cli"]
    environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
        "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC",
        "OPENCLAW_HOME": str(directory), "OPENCLAW_STATE_DIR": str(directory / "state")}
    if value["kind"] in SEARCH_EFFECT_KINDS:
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
    dispatch = {"kind": value["kind"] + "-sdk-dispatch", "input": deepcopy(value), "request": request,
        "adapterRoot": str(ROOT), "sdkRoot": str(selected_sdk),
        "cwd": str(ROOT), "environment": deepcopy(environment),
        "requestJson": wire, "requestSha256": hashlib.sha256(wire.encode()).hexdigest(),
        "argv": argv, "environmentKeys": sorted(environment), "coordinatorPid": os.getpid(),
        "sourceProvenanceBefore": _sdk_sources(selected_sdk)}
    if value["kind"] in SEARCH_EFFECT_KINDS:
        dispatch["adapterProvenanceBefore"] = _adapter_sources(value["kind"])
    binary_streams = value["kind"] in {"forget-index-fence-v5", "forget-index-fence-v6"}
    with subprocess.Popen(argv, cwd=ROOT, env=environment, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=not binary_streams) as child:
        dispatch["pid"] = child.pid
        try:
            sent = (wire + "\n").encode("utf8") if binary_streams else wire + "\n"
            stdout, stderr = child.communicate(sent, timeout=PROCESS_TIMEOUT_SECONDS * 4)
        except subprocess.TimeoutExpired:
            child.kill()
            stdout, stderr = child.communicate()
            dispatch["timeout"] = True
    if binary_streams:
        stdout = _decode_dispatch_stream(stdout, "stdout", dispatch)
        stderr = _decode_dispatch_stream(stderr, "stderr", dispatch)
    dispatch.update(stdout=stdout, stderr=stderr, exit={"code": child.returncode},
                    sourceProvenanceAfter=_sdk_sources(selected_sdk))
    if value["kind"] in SEARCH_EFFECT_KINDS:
        dispatch["adapterProvenanceAfter"] = _adapter_sources(value["kind"])
    if isinstance(stdout, str):
        try:
            dispatch["observation"] = json.loads(stdout)
        except json.JSONDecodeError as error:
            dispatch["stdoutParseError"] = _error(error)
    try:
        packet = _capture_dispatch_packet(dispatch)
    except (ValueError, TypeError, UnicodeError) as error:
        # Invalid transport data still keeps every actual stream and parsed
        # value as a diagnostic; no compact positive encoding is asserted.
        dispatch["observationEncodingError"] = _error(error)
        packet = dispatch
    (destination / "python-raw.json").write_text(_serialized([packet]) + "\n", encoding="utf8")
    if (child.returncode or "observation" not in dispatch or "result" not in dispatch["observation"]
            or "stdoutDecodeError" in dispatch or "stderrDecodeError" in dispatch
            or "observationEncodingError" in dispatch):
        raise RuntimeError("Original SDK forget/index-fence child failed; complete streams retained")
    if not dispatch["observation"].get("complete"):
        raise RuntimeError("Original SDK forget/index-fence schedule failed; complete receipts retained")
    return dispatch["observation"]["result"]


run_forget_index_fence_case = run_forget_index_fence_sdk_case
