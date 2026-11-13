"""Original SDK calls for the frozen query-sync boundary schedules.

Fixtures own files, an independent SQLite reservation and publication-sidecar
faults. They never coalesce, retry, replace a producer or repair a public return.
Original base-method calls are observed through Python call events so a managed
request waiting for its workspace guard is not counted as a producer dispatch.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
import hashlib
from itertools import count
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from types import CodeType


ROOT = Path(__file__).resolve().parents[1]


def _observed_arguments(values):
    """Observe a real connection before the older function-callable codec.

    sqlite3.Connection is callable but is not a Python function and has no
    instance __qualname__. This witness does not invoke or change the handle.
    """
    from equivalence.query_sync_outcomes_sdk import _arguments

    return {key: ({"className": type(value).__qualname__, "module": type(value).__module__,
                   "objectId": str(id(value)), "sqliteConnection": True, "callable": callable(value)}
                 if isinstance(value, sqlite3.Connection) else _arguments({key: value})[key])
            for key, value in values.items()}


def _sdk_tool_context_codes():
    """Return original loaded SDK code anchors, without executing a search."""
    from memory_core.tools.memory_search import execute_memory_search_tool, _run_memory_search_tool

    nested = {item.co_name: item for item in _run_memory_search_tool.__code__.co_consts
              if isinstance(item, CodeType) and item.co_name in {"search_memory_worker", "search_memory_once"}}
    if set(nested) != {"search_memory_worker", "search_memory_once"}:
        raise RuntimeError("The original SDK source-context worker anchors changed")
    return execute_memory_search_tool.__code__, {_run_memory_search_tool.__code__, *nested.values()}


class _SdkToolContexts:
    """Match an actual SDK worker's source context and exact original store.

    Strong references prevent object-id reuse. No active-query fallback, source
    replacement, context propagation into production, lock or I/O is involved.
    """

    def __init__(self, public_code, worker_codes, owner_refs):
        self.public_code, self.worker_codes, self.owner_refs = public_code, worker_codes, owner_refs
        self.bindings = {}

    def public_entry(self, code, context, store, label):
        if code is not self.public_code or context is None or label is None or id(store) not in self.owner_refs:
            return None
        binding = {"context": context, "store": store, "label": label, "ownerId": self.owner_refs[id(store)]}
        self.bindings[(id(context), id(store))] = binding
        return binding

    def worker_entry(self, code, context, store):
        if code not in self.worker_codes:
            return None
        binding = self.bindings.get((id(context), id(store)))
        if binding is None or binding["context"] is not context or binding["store"] is not store:
            return None
        return binding


def _serialized(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _literal(value):
    from equivalence.query_sync_boundaries import build_cases, validate_case

    for case in build_cases():
        try:
            return validate_case({**case, "input": value})
        except ValueError:
            pass
    raise ValueError("The SDK query-sync boundary process requires an exact frozen input")


def _sdk_sources():
    digest = hashlib.sha256()
    files = []
    for path in sorted((ROOT / "memory_core").rglob("*.py")):
        if path.is_symlink():
            raise RuntimeError("SDK source identity cannot follow an alias")
        relative, payload = path.relative_to(ROOT).as_posix(), path.read_bytes()
        digest.update(relative.encode() + b"\0" + payload + b"\0")
        files.append({"path": relative, "bytes": len(payload),
                      "sha256": hashlib.sha256(payload).hexdigest()})
    return {"root": str(ROOT), "sourceFiles": len(files), "sourceSha256": digest.hexdigest(),
            "files": files}


def _loaded_sdk():
    return [{"module": name, "path": str(Path(module.__file__).resolve()),
             "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
            for name, module in sorted(sys.modules.items()) if name.startswith("memory_core")
            and getattr(module, "__file__", None) and Path(module.__file__).is_file()]


class _SqlWriterGate:
    """An actual independent SQLite writer reservation, without row mutations."""

    def __init__(self, path, event, path_entry):
        self.path, self.event, self.path_entry = path, event, path_entry
        self.db = None
        self.pending = threading.Event()
        self.receipt = {"kind": "actual-index-sqlite-writer-reservation", "path": str(path),
                        "pendingReceipts": [], "released": False}

    def arm(self):
        if self.db is not None:
            raise RuntimeError("The owned SQLite writer gate is already armed")
        self.receipt.update(armEnterSeq=self.event("physical-sql-gate-arm-enter")["sequence"],
                            before=self.path_entry(self.path))
        self.deadline = time.monotonic() + 4
        db = sqlite3.connect(self.path)
        self.db = db
        try:
            db.execute("BEGIN IMMEDIATE")
            self.receipt.update(inTransaction=db.in_transaction, totalChanges=db.total_changes,
                databases=[list(row) for row in db.execute("PRAGMA database_list")],
                acquired=self.path_entry(self.path),
                armReturnSeq=self.event("physical-sql-gate-arm-return")["sequence"])
        except BaseException:
            db.close()
            self.db = None
            raise
        if not db.in_transaction or db.total_changes:
            raise RuntimeError("The fixture did not acquire a read-only writer reservation")

    def observe(self, row):
        if self.db is not None and not self.receipt["released"]:
            self.receipt["pendingReceipts"].append(deepcopy(row))
            self.pending.set()

    def wait(self, timeout):
        if not self.pending.wait(min(timeout, self.remaining())):
            raise TimeoutError("No actual original publisher requested SQLite while the gate was held")
        self.receipt["pendingObservedSeq"] = self.event("physical-sql-gate-original-pending-observed")["sequence"]

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("The actual SQLite gate exceeded its bounded hold deadline")
        return remaining

    def release(self):
        if self.db is None:
            raise RuntimeError("The owned SQLite writer gate is not armed")
        db = self.db
        self.receipt.update(releaseEnterSeq=self.event("physical-sql-gate-release-enter")["sequence"],
                            inTransactionBeforeRelease=db.in_transaction,
                            totalChangesBeforeRelease=db.total_changes)
        try:
            db.rollback()
            self.receipt.update(inTransactionAfterRelease=db.in_transaction,
                                totalChangesAfterRelease=db.total_changes)
        finally:
            db.close()
            self.db = None
            self.receipt.update(released=True, closed=True,
                releaseReturnSeq=self.event("physical-sql-gate-release-return")["sequence"])


def run_query_sync_boundaries_sdk_host(request):
    """Run only the frozen ordered operations through actual SDK owners."""
    if not isinstance(request, dict) or set(request) != {"input", "directory"}:
        raise ValueError("The protected SDK boundary child requires input and owned directory")
    value, directory = request["input"], Path(request["directory"])
    case = _literal(value)
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ValueError("An existing absolute owned SDK boundary directory is required")
    before_imports, imported_before = _sdk_sources(), _loaded_sdk()

    import memory_core
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.host.managed_index import ManagedSQLiteMemoryStore
    from memory_core.consolidation.forget import plan_memory_index, purge_memory_index
    from memory_core.consolidation.origins import MemoryIndexRevisionConflictError
    from memory_core.index.identity import MEMORY_INDEX_META_KEY, MEMORY_INDEX_META_TABLE
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_visibility import resolve_memory_search_source_policy
    from memory_core.tools.memory_search import MemorySearchToolContext
    from memory_core.tools.search_factory import create_memory_search_tool
    from memory_core.workspace import MemoryWorkspace
    from equivalence.index_identity_boundaries_sdk import _search_result_custody
    from equivalence.query_sync_cold_retry_sdk import (
        _PublicationSidecarFault, _original_error as _full_original_error, _path_entry,
    )
    from equivalence.query_sync_outcomes_sdk import (
        _arguments, _capture_sources, _owned_path, _persist_tool_envelope,
        _search_return_custody, _sql_rows, _stat,
    )

    implementation = Path(memory_core.__file__).resolve().parents[1]
    after_imports = _sdk_sources()
    if implementation != ROOT or before_imports != after_imports:
        raise RuntimeError("The SDK child imported another tree or source bytes changed during import")
    workspace_path, index_path = directory / "workspace", directory / "index.sqlite"
    workspace_path.mkdir()
    settings = value["config"]["memory"]["search"]
    policy = resolve_memory_search_source_policy(settings["sources"],
        remember_across_conversations=settings["rememberAcrossConversations"],
        configured_session_memory=settings["experimental"]["sessionMemory"])
    catalog = MemorySessionCatalog(directory / "catalog.sqlite", agent_id=value["identity"]["agentId"],
                                   clock_ms=lambda: value["nowMs"])
    workspace = MemoryWorkspace(workspace_path, agent_id=value["identity"]["agentId"],
                                session_catalog=catalog, index_sources=tuple(policy["sources"]))
    config = MemoryConfig(workspace_path, agent_id=value["identity"]["agentId"], store_path=index_path,
        citation_mode=value["config"]["memory"]["citations"], session_search="sessions" in policy["searchSources"],
        search_max_results=settings["query"]["maxResults"], search_min_score=settings["query"]["minScore"],
        flags=FeatureFlags(vector_search=False, mmr=True, temporal_decay=True))
    raw = {"kind": "query-sync-boundaries", "engine": "sdk", "caseId": case["id"],
        "input": deepcopy(value), "pid": os.getpid(), "ppid": os.getppid(),
        "fixtureBase": str(directory), "implementationRoot": str(implementation),
        "sourceIdentity": {"beforeImports": before_imports, "afterImports": after_imports,
                           "loadedBeforeImports": imported_before, "loadedAfterImports": _loaded_sdk()},
        "requestedConfig": deepcopy(value["config"]), "sourcePolicy": deepcopy(policy),
        "sdkProfile": {"runtimeIdentity": "openclaw-compatible", "memoryPublication": "on-search",
            "publicFactory": "memory_core.tools.search_factory.create_memory_search_tool",
            "contextStatus": None, "refreshStore": None},
        "clock": {"owner": "public-tool-clock", "nowMs": value["nowMs"], "monotonicAndTimers": "unmodified"},
        "process": {"cwd": str(Path.cwd()), "executable": sys.executable, "version": sys.version,
            "environmentKeys": sorted(os.environ), "cmdlineHex": Path("/proc/self/cmdline").read_bytes().hex()},
        "events": [], "owners": {}, "ownerAcquisitions": [], "statusCalls": [],
        "originalSearchCalls": [], "methodCalls": [], "backgroundCalls": [], "readAdmissions": [],
        "originalBaseCalls": [], "sqlStatements": [], "publicationWrites": [], "publicationCalls": [],
        "snapshots": [], "sourceStages": {}, "toolCalls": {}, "toolBindings": [],
        "syncCalls": {}, "faults": [], "sqlGates": [], "schedule": [], "counterDerivations": {},
        "functionalInterleavings": [], "fixtureErrors": [], "metadataFixtures": [], "toolContextScopes": []}
    raw["eventObservation"] = {"sharedSequence": "itertools.count", "globalObserverMutex": False,
        "callbackFilesystemWrites": False, "storageOrder": "actual-buffer-append-interleaving",
        "flush": "declared-step-checkpoints-and-settled-teardown",
        "fullErrorFormatting": "after-original-callers-and-owners-settle"}
    sequence, phase = count(1), "setup"
    local = threading.local()
    owners, owner_refs, pending_searches = [], {}, []
    active_owner, fault, gate = None, None, None
    conflict_fixture = None
    publication_causes = {}
    job_settlements = {}
    calls, call_entered, call_futures = {}, {}, {}
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="query-sync-fixture-caller")
    searches, syncs = {}, {}
    pending_files, pending_envelopes, pending_errors = [], [], []

    def event(name, **values):
        row = {"event": name, "sequence": next(sequence), "atNs": str(time.monotonic_ns()),
            "phase": getattr(local, "phase", phase), "threadId": threading.get_ident(),
            "activeTool": getattr(local, "tool", None), "activeSync": getattr(local, "sync", None), **values}
        raw["events"].append(row)
        return row

    def observed_error(error, **context):
        """Keep actual identity now; read/format source and traceback after work."""
        error_type = type(error)
        witness = {"module": error_type.__module__, "qualname": error_type.__qualname__,
            "mro": [{"module": item.__module__, "qualname": item.__qualname__} for item in error_type.__mro__]}
        record = {"name": error_type.__name__, "module": error_type.__module__,
            "errorRef": f"sdk-error-{id(error)}", "objectId": str(id(error)),
            "exceptionType": witness, **context}
        pending_errors.append((record, error, error.__traceback__))
        return record

    def checkpoint():
        # Original callbacks only append immutable event/custody observations.
        # A declared step may flush their already captured values, without a
        # new mutex that original callers would have to acquire.
        for path, snapshot, receipt in pending_files[:]:
            if "serializedJSON" not in receipt:
                encoded = _serialized(snapshot)
                path.write_text(encoded + "\n", encoding="utf8")
                receipt.update(serializedJSON=encoded, sha256=hashlib.sha256(encoded.encode()).hexdigest())
        for label, envelope, call in pending_envelopes[:]:
            if "envelopeFile" not in call:
                call["envelopeFile"] = _persist_tool_envelope(directory, label, envelope)
        events = raw["events"][:]
        (directory / "events.jsonl").write_text("".join(_serialized(row) + "\n" for row in events), encoding="utf8")
        (directory / "sdk-host-raw.json").write_text(_serialized(raw) + "\n", encoding="utf8")

    def physical(label):
        entered = event("physical-sql-read-enter", label=label, dbPath=str(index_path))
        state = {"dbPath": str(index_path)}
        if not index_path.exists():
            state.update(absent=True, schema=[], tables={})
        else:
            state["fileStat"] = _stat(index_path.lstat())
            with closing(sqlite3.connect(index_path.as_uri() + "?mode=ro", uri=True)) as db:
                db.execute("BEGIN")
                state.update(absent=False, **_sql_rows(db))
                db.rollback()
        encoded = _serialized(state)
        destination = directory / f"sql-{label}.json"
        destination.write_text(encoded + "\n", encoding="utf8")
        finished = event("physical-sql-read-return", label=label, dbPath=str(index_path))
        raw["snapshots"].append({"label": label, "enterSeq": entered["sequence"],
            "returnSeq": finished["sequence"], **state, "serializedJSON": encoded,
            "sha256": hashlib.sha256(encoded.encode()).hexdigest(), "file": str(destination),
            "connection": {"uriMode": "ro", "begin": not state["absent"],
                           "rollback": not state["absent"], "closed": True}})

    def sources(label):
        entered = event("source-read-enter", label=label)
        paths = set(value["initialFiles"])
        mutation = value.get("sourceMutation") or {}
        paths.update(mutation[key] for key in ("path", "from", "to") if key in mutation)
        receipt = _capture_sources(workspace_path, paths, directory, label)
        receipt.update(enterSeq=entered["sequence"],
            returnSeq=event("source-read-return", label=label)["sequence"])
        raw["sourceStages"][label] = receipt

    base_functions = {SQLiteMemoryStore.reindex.__code__: SQLiteMemoryStore.reindex,
                      SQLiteMemoryStore.reindex_sources.__code__: SQLiteMemoryStore.reindex_sources}
    publisher_code = SQLiteMemoryStore.publish_prepared_index.__code__
    previous_profile, previous_thread_profile = sys.getprofile(), threading.getprofile()
    previous_trace, previous_thread_trace = sys.gettrace(), threading.gettrace()
    if any(item is not None for item in (previous_profile, previous_thread_profile, previous_trace, previous_thread_trace)):
        raise RuntimeError("The protected SDK process already has an unexpected call observer")
    base_frame_calls = {}
    public_context_code, worker_context_codes = _sdk_tool_context_codes()
    tool_contexts = _SdkToolContexts(public_context_code, worker_context_codes, owner_refs)
    raw["toolContextObservation"] = {"mechanism": "original-SDK-code-and-source-context-identity",
        "activeQueryFallback": False, "productionContextModified": False,
        "codes": [{"qualname": code.co_qualname, "file": code.co_filename, "firstLine": code.co_firstlineno,
            "sourceSha256": hashlib.sha256(Path(code.co_filename).read_bytes()).hexdigest()}
            for code in sorted({public_context_code, *worker_context_codes}, key=lambda item: item.co_firstlineno)]}
    raw["baseCallObservation"] = {"mechanism": "original-Python-function-call-profile",
        "previousCurrentProfile": None, "previousNewThreadProfile": None,
        "exceptionMechanism": "original-base-frame-exception-trace",
        "previousCurrentTrace": None, "previousNewThreadTrace": None,
        "typedConflictClass": {"module": MemoryIndexRevisionConflictError.__module__,
            "qualname": MemoryIndexRevisionConflictError.__qualname__,
            "sourceSha256": hashlib.sha256(Path(sys.modules[MemoryIndexRevisionConflictError.__module__].__file__).read_bytes()).hexdigest()},
        "functions": [{"module": function.__module__, "qualname": function.__qualname__,
            "file": function.__code__.co_filename, "firstLine": function.__code__.co_firstlineno,
            "sourceSha256": hashlib.sha256(Path(function.__code__.co_filename).read_bytes()).hexdigest()}
            for function in base_functions.values()]}

    def profile(frame, name, returned):
        # The public factory calls the original execute function synchronously.
        # Its actual context then appears in the original nested corpus worker
        # closures on another thread. Match those objects, not an ambient label.
        context_scopes = getattr(local, "tool_context_scopes", ())
        if name == "call":
            if frame.f_code is public_context_code:
                binding = tool_contexts.public_entry(frame.f_code, frame.f_locals.get("context"),
                    frame.f_locals.get("store"), getattr(local, "tool", None))
            elif frame.f_code in worker_context_codes:
                binding = tool_contexts.worker_entry(frame.f_code, frame.f_locals.get("context"), frame.f_locals.get("store"))
            else:
                binding = None
            if binding is not None:
                previous_tool, previous_phase = getattr(local, "tool", None), getattr(local, "phase", None)
                local.tool, local.phase = binding["label"], "query-" + binding["label"]
                scope = {"label": binding["label"], "ownerId": binding["ownerId"],
                    "contextObjectId": str(id(binding["context"])), "storeObjectId": str(id(binding["store"])),
                    "codeQualname": frame.f_code.co_qualname, "codeFirstLine": frame.f_code.co_firstlineno,
                    "codeFile": frame.f_code.co_filename, "threadId": threading.get_ident(),
                    "kind": "public-entry" if frame.f_code is public_context_code else "original-source-scope",
                    "enterSeq": event("original-sdk-tool-context-enter", label=binding["label"], ownerId=binding["ownerId"])["sequence"]}
                raw["toolContextScopes"].append(scope)
                local.tool_context_scopes = (*context_scopes, (id(frame), previous_tool, previous_phase, scope))
        elif name == "return" and context_scopes and context_scopes[-1][0] == id(frame):
            _, previous_tool, previous_phase, scope = context_scopes[-1]
            scope["returnSeq"] = event("original-sdk-tool-context-return", label=scope["label"], ownerId=scope["ownerId"])["sequence"]
            local.tool, local.phase = previous_tool, previous_phase
            local.tool_context_scopes = context_scopes[:-1]
        if frame.f_code is publisher_code and name == "call":
            publisher = frame.f_locals.get("self")
            if id(publisher) in owner_refs and conflict_fixture is not None:
                functional_purge(publisher, frame.f_locals)
        function = base_functions.get(frame.f_code)
        owner_id = owner_refs.get(id(frame.f_locals.get("self"))) if function is not None else None
        if owner_id is None or name not in {"call", "return"}:
            return
        stack = getattr(local, "bases", ())
        if name == "call":
            entered = event("original-base-producer-enter", ownerId=owner_id, method=function.__name__)
            arguments = frame.f_locals
            call = {"id": f"base-{entered['sequence']}", "ownerId": owner_id,
                "method": function.__name__, "module": function.__module__, "qualname": function.__qualname__,
                "enterSeq": entered["sequence"], "threadId": threading.get_ident(),
                "activeTool": getattr(local, "tool", None), "activeSync": getattr(local, "sync", None),
                "backgroundCause": getattr(local, "background_cause", None),
                "receiverIsExactObservedOwner": True, "receiverObjectId": str(id(arguments["self"])),
                "workspaceIsExactOwner": arguments.get("workspace") is workspace,
                "managedOperationIds": list(getattr(arguments["self"]._local, "operations", ())),
                "options": _arguments({key: arguments[key] for key in
                    ("force", "sources", "paths", "force_sources") if key in arguments})}
            raw["originalBaseCalls"].append(call)
            base_frame_calls[id(frame)] = call
            local.bases = (*stack, (id(frame), call))
        elif stack and stack[-1][0] == id(frame):
            call = stack[-1][1]
            call.update(returned=_search_result_custody(returned),
                returnSeq=event("original-base-producer-return", ownerId=owner_id,
                                method=function.__name__)["sequence"])
            call["outcome"] = {"status": "rejected" if returned is None else "fulfilled",
                "isTypedConflict": returned is None and bool(call.get("exceptions", [])
                    and call["exceptions"][-1]["isTypedConflict"])}
            if returned is None and call.get("exceptions"):
                call["errorRef"] = call["exceptions"][-1]["errorRef"]
            local.bases = stack[:-1]
            base_frame_calls.pop(id(frame), None)

    def exception_trace(frame, name, arguments):
        if name == "call":
            return (exception_trace if frame.f_code in base_functions
                    and id(frame.f_locals.get("self")) in owner_refs else None)
        if name == "exception":
            call = base_frame_calls.get(id(frame))
            if call is not None:
                error = arguments[1]
                observed = observed_error(error)
                call.setdefault("exceptions", []).append({"error": observed,
                    "errorRef": observed["errorRef"], "objectId": observed["objectId"],
                    "isTypedConflict": isinstance(error, MemoryIndexRevisionConflictError),
                    "exceptionType": observed["exceptionType"],
                    "sequence": event("original-base-producer-exception", ownerId=call["ownerId"],
                                      method=call["method"])["sequence"]})
        return exception_trace

    def bind_observers(owner, owner_id):
        original_connect = owner.connect

        def connect_observer():
            db = original_connect()
            connection_id = str(id(db))

            def traced(statement):
                stack = getattr(local, "bases", ())
                row = event("original-sql-statement", ownerId=owner_id, connectionId=connection_id,
                    statement=statement, baseCallId=stack[-1][1]["id"] if stack else None,
                    fixtureAction=getattr(local, "fixture_action", None))
                raw["sqlStatements"].append(row)
                if (gate is not None and stack and not getattr(local, "fixture_action", None)
                        and statement.strip().upper() == "BEGIN IMMEDIATE"):
                    gate.observe(row)

            db.set_trace_callback(traced)
            return db

        owner.connect = connect_observer

        def observe_method(name, bucket):
            original = getattr(owner, name)

            def observed(*args, **kwargs):
                entered = event("original-method-enter", ownerId=owner_id, method=name)
                operations = getattr(owner._local, "operations", ())
                stack = getattr(local, "bases", ())
                arguments = ({"prepared": _search_result_custody(args[0]), "expectedRevision": args[1]}
                             if name == "publish_prepared_index" else
                             _observed_arguments({str(i): v for i, v in enumerate(args)}))
                call = {"id": f"method-{entered['sequence']}", "ownerId": owner_id, "method": name,
                    "activeTool": getattr(local, "tool", None), "activeSync": getattr(local, "sync", None),
                    "enterSeq": entered["sequence"], "threadId": threading.get_ident(),
                    "options": _observed_arguments(kwargs), "arguments": arguments,
                    "parentOperationId": operations[-1] if operations else None,
                    "baseCallId": stack[-1][1]["id"] if stack else None,
                    "receiverIsExactObservedOwner": original.__self__ is owner}
                raw[bucket].append(call)
                previous_cause = getattr(local, "background_cause", None)
                if name == "_submit_memory_publication":
                    actual_cause = getattr(local, "tool", None) or previous_cause
                    publication_causes[(owner_id, args[0])] = actual_cause
                    call["causalPublicQuery"] = actual_cause
                    call["actualReadRevision"] = args[0]
                    call["memoryJobCountBefore"] = owner.lifecycle_snapshot()["memoryPublication"]["jobCount"]
                elif name == "_run_memory_publication":
                    call["actualJobAtEntry"] = deepcopy(args[0])
                    local.background_cause = publication_causes.get((owner_id, args[0]["readRevision"]))
                    call["causalPublicQuery"] = local.background_cause
                    job_settlements.setdefault((owner_id, args[0]["id"]), threading.Event())
                if name in {"reindex", "search"}:
                    label = getattr(local, "sync" if name == "reindex" else "tool", None)
                    if label in call_entered:
                        call_entered[label].set()
                if name == "_on_search_snapshot":
                    db = args[0]
                    pinned = {"ownerId": owner_id, "activeTool": getattr(local, "tool", None),
                        "dbPath": str(owner.path), "connectionId": str(id(db)),
                        "inTransactionBefore": db.in_transaction, "readRevision": owner.index_revision(db=db),
                        "databases": [list(row) for row in db.execute("PRAGMA database_list")],
                        **_sql_rows(db), "inTransactionAfter": db.in_transaction}
                    destination = directory / f"sql-pinned-{entered['sequence']}.json"
                    call["pinnedSnapshot"] = {**pinned, "file": str(destination)}
                    pending_files.append((destination, pinned, call["pinnedSnapshot"]))
                try:
                    returned = original(*args, **kwargs)
                    if name == "search":
                        pending_searches.append((call, returned))
                    else:
                        call["returned"] = _search_result_custody(returned)
                    return returned
                except BaseException as error:
                    call["error"] = observed_error(error)
                    call["errorRef"] = call["error"]["errorRef"]
                    raise
                finally:
                    if name == "_on_index_publication_write":
                        call["writeChanges"] = kwargs["changes"]
                        call["writeError"] = None if kwargs["error"] is None else observed_error(kwargs["error"])
                    call["lifecycleAfter"] = owner.lifecycle_snapshot()
                    if name == "_submit_memory_publication":
                        call["admittedJobIds"] = [job["id"] for job in call["lifecycleAfter"]["memoryPublication"]["jobs"]
                                                  if job["id"] > call["memoryJobCountBefore"]]
                    call["returnSeq"] = event("original-method-return", ownerId=owner_id, method=name)["sequence"]
                    if name == "_run_memory_publication":
                        job_settlements[(owner_id, args[0]["id"])].set()
                        local.background_cause = previous_cause

            setattr(owner, name, observed)

        for name in ("reindex", "reindex_sources", "_reindex_locked"):
            observe_method(name, "methodCalls")
        observe_method("publish_prepared_index", "publicationCalls")
        observe_method("search", "originalSearchCalls")
        observe_method("status", "statusCalls")
        for name in ("_submit_memory_publication", "_run_memory_publication"):
            observe_method(name, "backgroundCalls")
        observe_method("_on_search_snapshot", "readAdmissions")
        observe_method("_on_index_publication_write", "publicationWrites")

    def acquire(label):
        nonlocal active_owner
        entered = event("original-open-enter", role=label, api="ManagedSQLiteMemoryStore")
        owner = ManagedSQLiteMemoryStore(config, workspace, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
                                         memory_publication="on-search")
        owner_id = f"owner-{len(owners) + 1}"
        owners.append(owner)
        owner_refs[id(owner)] = owner_id
        raw["ownerAcquisitions"].append({"role": label, "ownerId": owner_id,
            "enterSeq": entered["sequence"], "returnSeq": event("original-open-return", ownerId=owner_id)["sequence"],
            "objectId": str(id(owner)), "workspaceIsExactOwner": owner._workspace is workspace,
            "catalogIsExactOwner": owner._bound_catalog is catalog})
        raw["owners"][owner_id] = {"role": label, "objectId": str(id(owner)),
            "constructorName": type(owner).__qualname__, "config": _search_result_custody(asdict(config)),
            "indexPath": str(owner.path), "lifecycleAtAcquisition": owner.lifecycle_snapshot()}
        bind_observers(owner, owner_id)
        active_owner = owner

    def close_owner(owner):
        owner_id = owner_refs[id(owner)]
        record = {"enterSeq": event("original-close-enter", ownerId=owner_id)["sequence"]}
        raw["owners"][owner_id]["close"] = record
        try:
            record["returned"] = owner.close()
        except BaseException as error:
            record["error"] = observed_error(error)
            raise
        finally:
            record.update(returnSeq=event("original-close-return", ownerId=owner_id)["sequence"],
                          lifecycle=owner.lifecycle_snapshot(), closed=owner.closed)

    def tool_call(owner, label, params):
        local.tool, local.phase = label, f"query-{label}"
        owner_id = owner_refs[id(owner)]
        tool = create_memory_search_tool(config, owner, context=MemorySearchToolContext(
            clock=lambda: value["nowMs"], source_policy=policy), runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
        if tool is None:
            raise RuntimeError("The original SDK factory returned no public memory_search")
        raw["toolBindings"].append({"label": label, "ownerId": owner_id,
            "sequence": event("actual-tool-binding", label=label, ownerId=owner_id)["sequence"],
            "storeIsExactObservedOwner": tool._store is owner, "storeObjectId": str(id(tool._store)),
            "configIsExactOwnerConfig": tool._config is config, "contextStatusIsNone": tool._context.status is None,
            "refreshStoreIsNone": tool._context.refresh_store is None, "definition": tool.definition})
        call = {"label": label, "ownerId": owner_id, "args": deepcopy(params),
                "enterSeq": event("actual-tool-enter", label=label, ownerId=owner_id)["sequence"]}
        raw["toolCalls"][label] = call
        try:
            returned = tool.execute(f"query-sync-boundaries-{label}", deepcopy(params))
            call["envelope"] = deepcopy(returned)
            pending_envelopes.append((label, call["envelope"], call))
            return deepcopy(returned["details"])
        except BaseException as error:
            call["error"] = observed_error(error)
            raise
        finally:
            call["returnSeq"] = event("actual-tool-return", label=label, ownerId=owner_id)["sequence"]
            local.tool, local.phase = None, None

    def sync_call(owner, label, params):
        local.sync, local.phase = label, f"sync-{label}"
        owner_id = owner_refs[id(owner)]
        call = {"label": label, "ownerId": owner_id, "params": deepcopy(params),
                "counterpart": "ManagedSQLiteMemoryStore.reindex", "workspaceIsExactOwner": True,
                "enterSeq": event("actual-sync-enter", label=label, ownerId=owner_id)["sequence"]}
        raw["syncCalls"][label] = call
        try:
            returned = owner.reindex(workspace, force=params["force"])
            call["returned"] = _search_result_custody(returned)
            call["outcome"] = {"status": "fulfilled", "isTypedConflict": False}
        except BaseException as error:
            call["error"] = observed_error(error)
            call["errorRef"] = call["error"]["errorRef"]
            call["outcome"] = {"status": "rejected", "isTypedConflict": isinstance(error, MemoryIndexRevisionConflictError)}
        finally:
            call["returnSeq"] = event("actual-sync-return", label=label, ownerId=owner_id)["sequence"]
            local.sync, local.phase = None, None
        return deepcopy(call["outcome"])

    def start_call(kind, label, params):
        if label in calls:
            raise ValueError("A frozen call label was submitted more than once")
        call_entered[label] = threading.Event()
        call = {"kind": kind, "ownerId": owner_refs[id(active_owner)],
                "submitSeq": event("independent-caller-submit", label=label, callKind=kind)["sequence"]}
        calls[label] = call
        call_futures[label] = executor.submit(tool_call if kind == "search" else sync_call,
                                             active_owner, label, deepcopy(params))

    def await_call(label):
        returned = call_futures[label].result(timeout=20)
        (searches if calls[label]["kind"] == "search" else syncs)[label] = returned
        calls[label]["joinedSeq"] = event("independent-caller-settled", label=label)["sequence"]

    def mutate(specification):
        entered = event("source-mutation-enter", specification=deepcopy(specification))
        kind = specification["kind"]
        if kind in {"create", "replace"}:
            target = _owned_path(workspace_path, specification["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(specification["text"], encoding="utf8", newline="")
            os.utime(target, ns=(specification["mtimeMs"] * 1_000_000,) * 2)
        elif kind == "delete":
            _owned_path(workspace_path, specification["path"]).unlink()
        elif kind != "none":
            raise ValueError("Unsupported frozen source mutation")
        raw["sourceMutation"] = {"specification": deepcopy(specification), "enterSeq": entered["sequence"],
            "returnSeq": event("source-mutation-return")["sequence"], "sdkNotification": "actual-source-detection"}

    def functional_purge(owner, publisher_arguments):
        """A declared rival original publication, distinct from passive tracing.

        Python disables recursive profile callbacks during this callback. Record
        the real fixture API calls and complete SQL before/after explicitly;
        never infer them from missing nested call events or alter the original
        prepared publisher's return/error.
        """
        paths, role = conflict_fixture["selectedPaths"], conflict_fixture["role"]
        same_arm = [row for row in raw["functionalInterleavings"] if row["armSeq"] == conflict_fixture["armSeq"]]
        position = len(same_arm)
        if position >= len(paths):
            return
        if role == "preparation":
            submitted = raw["syncCalls"].get(conflict_fixture["preparationSyncLabel"])
            if (submitted is None or "returnSeq" in submitted
                    or submitted["ownerId"] != owner_refs[id(owner)]):
                return
            actual_cause = {"syncLabel": conflict_fixture["preparationSyncLabel"],
                            "originalSyncEnterSeq": submitted["enterSeq"]}
        else:
            cause = getattr(local, "background_cause", None)
            if cause != conflict_fixture["maintenanceQueryLabel"]:
                return
            actual_cause = {"causalPublicQuery": cause}
        marker, number = paths[position], len(raw["functionalInterleavings"])
        owner_id = owner_refs[id(owner)]
        action = {"number": number, "kind": "declared-original-rival-source-purge",
            "ownerId": owner_id, "markerPath": marker, "role": role,
            "armSeq": conflict_fixture["armSeq"], "actualCause": actual_cause,
            "trigger": {"module": SQLiteMemoryStore.publish_prepared_index.__module__,
                "qualname": SQLiteMemoryStore.publish_prepared_index.__qualname__,
                "sourceSha256": hashlib.sha256(Path(publisher_code.co_filename).read_bytes()).hexdigest(),
                "expectedRevision": publisher_arguments["expected_revision"],
                "prepared": _search_result_custody(publisher_arguments["prepared"])},
            "originalFunction": {"module": purge_memory_index.__module__, "qualname": purge_memory_index.__qualname__,
                "file": purge_memory_index.__code__.co_filename,
                "sourceSha256": hashlib.sha256(Path(purge_memory_index.__code__.co_filename).read_bytes()).hexdigest()},
            "enterSeq": event("functional-rival-publication-enter", ownerId=owner_id, markerPath=marker)["sequence"],
            "profileRecursionIsDisabledByPython": True, "receiverIsExactObservedOwner": True}
        raw["functionalInterleavings"].append(action)
        local.fixture_action = f"rival-purge-{number}"
        try:
            physical(f"rival-{number}-before")
            action["revisionBefore"] = owner.index_revision()
            plan = plan_memory_index(owner, agent_id=value["identity"]["agentId"],
                changed_paths={marker}, removed_paths={marker}, session_ids=set(), excluded_session_ids=set(),
                matches_memory=lambda text: False)
            action["plan"] = _search_result_custody(plan)
            action["planFunction"] = {"module": plan_memory_index.__module__, "qualname": plan_memory_index.__qualname__,
                "changedPaths": [marker], "removedPaths": [marker], "sessionIds": [], "excludedSessionIds": []}
            action["returned"] = purge_memory_index(owner, plan)
            action["revisionAfter"] = owner.index_revision()
            physical(f"rival-{number}-after")
            if action["returned"] is not True or not plan.chunks or action["revisionAfter"] != action["revisionBefore"] + 1:
                raise RuntimeError("The declared rival publication did not purge an actual indexed marker generation")
        except BaseException as error:
            action["error"] = observed_error(error)
            raw["fixtureErrors"].append(observed_error(error, operation="functional-rival-source-purge"))
        finally:
            action["returnSeq"] = event("functional-rival-publication-return", ownerId=owner_id, markerPath=marker)["sequence"]
            local.fixture_action = None

    def newer_empty_format(specification):
        if any(not future.done() for future in call_futures.values()):
            raise RuntimeError("A declared empty-format fixture cannot overlap an active public call")
        entered = event("physical-newer-format-enter", specification=deepcopy(specification))
        before = active_owner.read_index_meta()
        with closing(active_owner.connect()) as db:
            if db.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is not None:
                raise RuntimeError("The newer-format fixture requires an actually empty index")
        if not isinstance(before, dict):
            raise RuntimeError("The newer-format fixture requires metadata from an actual prior empty public bootstrap")
        metadata = {**before, specification["field"]: specification["version"]}
        with closing(active_owner.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(f"INSERT OR REPLACE INTO {MEMORY_INDEX_META_TABLE}(key,value) VALUES (?,?)",
                       (MEMORY_INDEX_META_KEY, _serialized(metadata)))
        raw["metadataFixtures"].append({"specification": deepcopy(specification), "before": before,
            "actualStoredMetadataBefore": before, "written": metadata, "after": active_owner.read_index_meta(),
            "enterSeq": entered["sequence"], "returnSeq": event("physical-newer-format-return")["sequence"]})

    def dispatch_counts():
        primary = raw["ownerAcquisitions"][0]
        close = raw["owners"][primary["ownerId"]]["close"]

        def selected(call):
            return (call["ownerId"] == primary["ownerId"]
                    and primary["returnSeq"] < call["enterSeq"] < call["returnSeq"] < close["returnSeq"])

        tools = [call for call in raw["toolCalls"].values() if selected(call)]
        managers = [call for call in raw["originalSearchCalls"] if selected(call)]
        requests = [call for call in raw["methodCalls"]
                    if call["method"] in {"reindex", "reindex_sources"} and selected(call)]
        producers = sorted((call for call in raw["originalBaseCalls"] if selected(call)), key=lambda call: call["enterSeq"])
        producer_ids = {call["id"] for call in producers}
        commits = [call for call in raw["publicationCalls"] if selected(call)
                   and call["baseCallId"] in producer_ids and "error" not in call and "returned" in call]
        commit_proofs = []
        for call in commits:
            actual = [row["sequence"] for row in raw["sqlStatements"]
                if row["baseCallId"] == call["baseCallId"] and not row["fixtureAction"]
                and call["enterSeq"] < row["sequence"] < call["returnSeq"]
                and row["statement"].strip().upper() == "COMMIT"]
            if not actual:
                raise RuntimeError("An original publisher return lacks its real SQLite COMMIT receipt")
            commit_proofs.append({"baseCallId": call["baseCallId"], "publicationCallId": call["id"],
                                  "actualCommitSequences": actual})
        generations = sorted({call["baseCallId"] for call in commits})
        repairs = [row for row in close["lifecycle"]["repairs"] if row["reason"] == "search-bootstrap"]
        raw["counterDerivations"] = {"primaryOwnerId": primary["ownerId"],
            "lifetime": {"acquireReturnSeq": primary["returnSeq"], "closeReturnSeq": close["returnSeq"]},
            "publicSearchLabels": [call["label"] for call in tools],
            "managerSearchCallIds": [call["id"] for call in managers],
            "syncRequestCallIds": [call["id"] for call in requests],
            "bootstrapRepairIds": [row["id"] for row in repairs],
            "producerBaseCallIds": [call["id"] for call in producers],
            "publicationCommitCallIds": [call["id"] for call in commits],
            "publicationCommitEvidence": commit_proofs,
            "committedGenerationBaseCallIds": generations,
            "unit": "original-public-base-reindex-or-reindex_sources-execution-entry",
            "freshOwnerActivityExcludedFromCommonCounts": True}
        raw["allOwnerRawDispatchTotals"] = {"searchRequests": len(raw["toolCalls"]),
            "managerSearches": len(raw["originalSearchCalls"]),
            "managedSyncEntries": sum(call["method"] in {"reindex", "reindex_sources"} for call in raw["methodCalls"]),
            "originalBaseEntries": len(raw["originalBaseCalls"]),
            "successfulPublicationReturns": sum("error" not in call and "returned" in call for call in raw["publicationCalls"])}
        raw["primaryProducerOutcomes"] = [deepcopy(call["outcome"]) for call in producers]
        return {"searchRequests": len(tools), "managerSearches": len(managers), "syncRequests": len(requests),
                "bootstrapRequests": len(repairs), "producerAttempts": len(producers),
                "committedGenerations": len(generations)}

    threading.setprofile(profile)
    sys.setprofile(profile)
    threading.settrace(exception_trace)
    sys.settrace(exception_trace)
    try:
        for number, step in enumerate(value["steps"]):
            operation = step["operation"]
            phase = f"step-{number}-{operation}"
            entered = event("declared-step-enter", number=number, specification=deepcopy(step))
            schedule = {"number": number, "specification": deepcopy(step), "enterSeq": entered["sequence"]}
            raw["schedule"].append(schedule)
            if operation == "prepare-real-source-files":
                for relative, text in value["initialFiles"].items():
                    target = _owned_path(workspace_path, relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("x", encoding="utf8", newline="") as stream:
                        stream.write(text)
                    os.utime(target, ns=(value["initialSourceMtimeMs"] * 1_000_000,) * 2)
                sources("initial")
            elif operation in {"acquire-owner", "acquire-original-default-owner", "reopen-owner"}:
                acquire(step.get("label", "first" if not owners else "reopened"))
            elif operation in {"public-memory-search", "start-public-memory-search"}:
                label = step["label"]
                start_call("search", label, value["queries"][label])
                if operation == "public-memory-search":
                    await_call(label)
            elif operation in {"original-sync", "start-sync"}:
                label = step["label"]
                start_call("sync", label, step["params"])
                if operation == "original-sync":
                    await_call(label)
            elif operation in {"await-sync", "await-public-memory-search"}:
                await_call(step["label"])
            elif operation == "arm-sql-gate":
                gate = _SqlWriterGate(index_path, event, _path_entry)
                raw["sqlGates"].append(gate.receipt)
                gate.arm()
            elif operation in {"await-real-publication-pending", "await-original-busy"}:
                gate.wait(3)
            elif operation == "await-joined-requests":
                if gate is None or gate.db is None:
                    raise RuntimeError("The frozen concurrent request group lacks its actual held SQLite gate")
                observations = []
                for label in step["labels"]:
                    timeout = 3 if gate is None or gate.db is None else min(3, gate.remaining())
                    if not call_entered[label].wait(timeout):
                        raise TimeoutError("An independent caller did not enter its actual original API")
                    observations.append({"label": label, "originalCallPending": not call_futures[label].done(),
                        "observedSeq": event("independent-original-call-entered", label=label)["sequence"]})
                schedule["actualRequestEntries"] = observations
                schedule["coalescingAssertedByFixture"] = False
                schedule["leaderStillPending"] = not call_futures[step["leader"]].done()
                if not schedule["leaderStillPending"]:
                    raise RuntimeError("The actual first producer settled before the declared concurrent request entries")
            elif operation == "release-sql-gate":
                gate.remaining()
                schedule["callCompletionBeforeRelease"] = {label: future.done() for label, future in call_futures.items()}
                gate.release()
            elif operation == "arm-publication-fault":
                fault = _PublicationSidecarFault(index_path, directory, value["publicationFault"])
                raw["faults"].append(fault.receipt)
                fault.receipt["armEnterSeq"] = event("physical-fault-arm-enter")["sequence"]
                fault.arm()
                fault.receipt["armReturnSeq"] = event("physical-fault-arm-return")["sequence"]
            elif operation == "remove-publication-fault":
                fault.receipt["removeEnterSeq"] = event("physical-fault-remove-enter")["sequence"]
                fault.remove()
                fault.receipt["removeReturnSeq"] = event("physical-fault-remove-return")["sequence"]
            elif operation == "mutate-source":
                mutate(step.get("specification", value.get("sourceMutation")))
            elif operation == "arm-revision-conflict":
                role = step["role"]
                if role not in {"preparation", "maintenance"}:
                    raise ValueError("A rival-publication arm requires its exact preparation/maintenance role")
                conflict_fixture = {**deepcopy(value["revisionConflict"]), "role": role,
                    "selectedPaths": value["revisionConflict"]["paths"][:1] if role == "preparation"
                                     else value["revisionConflict"]["paths"][1:],
                    "armSeq": event("functional-rival-publication-armed", role=role)["sequence"]}
                raw.setdefault("revisionConflictFixtures", []).append(deepcopy(conflict_fixture))
            elif operation == "set-newer-empty-format":
                newer_empty_format(value["newerFormat"])
            elif operation == "capture-physical-sql":
                physical(step["label"])
            elif operation == "capture-sources":
                sources(step["label"])
            elif operation == "read-physical-sql-and-source-state":
                physical(step["label"])
                sources(step["label"])
            elif operation == "await-observed-background-settlement":
                label = step["searchLabel"]
                admitted = {(call["ownerId"], job) for call in raw["backgroundCalls"]
                    if call["method"] == "_submit_memory_publication" and call["activeTool"] == label
                    for job in call.get("admittedJobIds", [])}
                schedule["alreadyAdmittedJobKeys"] = [list(key) for key in sorted(admitted)]
                schedule["admission"] = "admitted" if admitted else "not-admitted"
                for key in admitted:
                    settlement = job_settlements.setdefault(key, threading.Event())
                    if not settlement.wait(20):
                        raise TimeoutError("An actually admitted original background publisher did not settle")
                schedule["settledSeq"] = event("already-admitted-background-settlement-observed", searchLabel=label,
                                                admittedJobs=len(admitted))["sequence"]
            elif operation in {"close-owner", "original-owner-close"}:
                close_owner(active_owner)
            else:
                raise ValueError("Unknown frozen SDK query-sync boundary operation: " + operation)
            schedule["returnSeq"] = event("declared-step-return", number=number)["sequence"]
            checkpoint()
        if any("joinedSeq" not in call for call in calls.values()):
            raise RuntimeError("A prescribed independent caller was never awaited by its frozen schedule")
        if any(not owner.closed for owner in owners):
            raise RuntimeError("A frozen boundary schedule omitted an original owner close")
        if raw["fixtureErrors"]:
            raise RuntimeError("A declared functional fixture failed; original public outputs remain retained")
        # Complete public envelopes and original streams are already durable.
        for call, returned in pending_searches:
            call.update(_search_return_custody(returned))
        providers = {call["returned"]["provider"] for call in raw["statusCalls"] if "returned" in call}
        if len(providers) != 1:
            raise RuntimeError("Actual public manager statuses did not identify one selected provider")
        raw["independentCalls"] = calls
        raw["result"] = {"provider": providers.pop(), "searches": searches, "syncs": syncs,
            "dispatches": dispatch_counts(),
            "producerOutcomes": raw["primaryProducerOutcomes"],
            "sources": {label: receipt["common"] for label, receipt in raw["sourceStages"].items()}}
        raw["completed"] = True
        return {"result": raw["result"], "raw": raw}
    except BaseException as error:
        raw["error"] = observed_error(error)
        raise
    finally:
        phase = "teardown"
        errors = []
        if gate is not None and gate.db is not None:
            try:
                gate.release()
                gate.receipt["releasedDuringTeardown"] = True
            except BaseException as error:
                errors.append(observed_error(error, operation="release-sql-gate"))
        for label, future in call_futures.items():
            try:
                future.result(timeout=20)
            except BaseException as error:
                errors.append(observed_error(error, operation="settle-independent-caller", label=label))
        executor.shutdown(wait=True)
        if fault is not None and fault.armed:
            try:
                fault.remove()
                fault.receipt["removedDuringTeardown"] = True
            except BaseException as error:
                errors.append(observed_error(error, operation="remove-fault"))
        for owner in owners:
            if not owner.closed:
                try:
                    close_owner(owner)
                except BaseException as error:
                    errors.append(observed_error(error, operation="owner-close"))
        sys.setprofile(previous_profile)
        threading.setprofile(previous_thread_profile)
        sys.settrace(previous_trace)
        threading.settrace(previous_thread_trace)
        raw["baseCallObservation"]["profilesRestored"] = (sys.getprofile() is previous_profile
            and threading.getprofile() is previous_thread_profile)
        raw["baseCallObservation"]["exceptionTraceRestored"] = (sys.gettrace() is previous_trace
            and threading.gettrace() is previous_thread_trace)
        raw["allManagersClosed"] = all(owner.closed for owner in owners)
        for armed in raw.get("revisionConflictFixtures", []):
            reached = [row["markerPath"] for row in raw["functionalInterleavings"] if row["armSeq"] == armed["armSeq"]]
            armed["actualReachedPaths"] = reached
            armed["notReachedPaths"] = [path for path in armed["selectedPaths"] if path not in reached]
            armed["missingProducerWasNotManufacturedOrWaitedFor"] = True
        raw["implementationBindings"] = _loaded_sdk()
        raw["sourceIdentity"]["afterClose"] = _sdk_sources()
        if errors:
            raw["teardownErrors"] = errors
        # Preserve early envelopes, events and exception identities even if an
        # unexpected private error codec fails. Source/traceback formatting is
        # deliberately after every real caller/owner has settled and observers
        # have been restored.
        checkpoint()
        for record, error, captured_traceback in pending_errors:
            record.update(_full_original_error(error))
            record["traceback"] = "".join(traceback.format_exception(type(error), error, captured_traceback))
        raw["errorFormatting"] = {"deferredUntilOriginalOwnersSettled": True,
                                  "observations": len(pending_errors)}
        checkpoint()
        if errors and sys.exc_info()[0] is None:
            raise RuntimeError("Original SDK teardown failed; actual errors and early envelopes retained")


def run_query_sync_boundaries_case(value, *, evidence_directory=None):
    """One protected child per exact input, with complete streams and no retry."""
    _literal(value)
    if evidence_directory is not None:
        Path(evidence_directory).mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="sdk-query-sync-boundaries-", dir=evidence_directory)).resolve()
    request = {"input": value, "directory": str(directory)}
    wire = _serialized(request)
    environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
        "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC", "OPENCLAW_HOME": str(directory),
        "OPENCLAW_STATE_DIR": str(directory / "state")}
    argv = [sys.executable, "-m", "equivalence.query_sync_boundaries_sdk_cli"]
    dispatch = {"kind": "query-sync-boundaries-sdk-dispatch", "input": deepcopy(value),
        "coordinatorPid": os.getpid(), "request": request, "requestJson": wire,
        "requestSha256": hashlib.sha256(wire.encode()).hexdigest(), "argv": argv,
        "environmentKeys": sorted(environment), "startedAtNs": str(time.monotonic_ns())}
    destination = Path(evidence_directory) if evidence_directory is not None else directory
    with subprocess.Popen(argv, cwd=ROOT, env=environment, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
        dispatch["pid"] = child.pid
        try:
            stdout, stderr = child.communicate(wire, timeout=120)
        except subprocess.TimeoutExpired:
            child.kill()
            stdout, stderr = child.communicate()
            dispatch.update(stdout=stdout, stderr=stderr, exit={"code": child.returncode},
                            finishedAtNs=str(time.monotonic_ns()))
            (destination / "python-raw.json").write_text(_serialized([dispatch]) + "\n", encoding="utf8")
            raise RuntimeError("Original SDK boundary child timed out; complete streams retained") from None
    dispatch.update(stdout=stdout, stderr=stderr, exit={"code": child.returncode},
                    finishedAtNs=str(time.monotonic_ns()))
    try:
        dispatch["observation"] = json.loads(stdout)
    except json.JSONDecodeError as error:
        dispatch["stdoutParseError"] = {"name": type(error).__name__, "message": str(error)}
    (destination / "python-raw.json").write_text(_serialized([dispatch]) + "\n", encoding="utf8")
    if child.returncode or "observation" not in dispatch or "result" not in dispatch["observation"]:
        raise RuntimeError("Original SDK boundary child failed; streams and early public envelopes retained")
    return dispatch["observation"]["result"]
