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
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time


ROOT = Path(__file__).resolve().parents[1]


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
    from memory_core.index.sqlite_store import SQLiteMemoryStore
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_visibility import resolve_memory_search_source_policy
    from memory_core.tools.memory_search import MemorySearchToolContext
    from memory_core.tools.search_factory import create_memory_search_tool
    from memory_core.workspace import MemoryWorkspace
    from equivalence.index_identity_boundaries_sdk import _search_result_custody
    from equivalence.query_sync_cold_retry_sdk import (
        _PublicationSidecarFault, _original_error, _path_entry,
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
        "syncCalls": {}, "faults": [], "sqlGates": [], "schedule": [], "counterDerivations": {}}
    sequence, phase = 0, "setup"
    observation_lock, local = threading.RLock(), threading.local()
    owners, owner_refs, pending_searches = [], {}, []
    active_owner, fault, gate = None, None, None
    calls, call_entered, call_futures = {}, {}, {}
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="query-sync-fixture-caller")
    searches, syncs = {}, {}

    def event(name, **values):
        nonlocal sequence
        with observation_lock:
            sequence += 1
            row = {"event": name, "sequence": sequence, "atNs": str(time.monotonic_ns()),
                "phase": getattr(local, "phase", phase), "threadId": threading.get_ident(),
                "activeTool": getattr(local, "tool", None), "activeSync": getattr(local, "sync", None), **values}
            raw["events"].append(row)
            with (directory / "events.jsonl").open("a", encoding="utf8") as stream:
                stream.write(_serialized(row) + "\n")
            return row

    def checkpoint():
        with observation_lock:
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
    previous_profile, previous_thread_profile = sys.getprofile(), threading.getprofile()
    if previous_profile is not None or previous_thread_profile is not None:
        raise RuntimeError("The protected SDK process already has an unexpected call profiler")
    raw["baseCallObservation"] = {"mechanism": "original-Python-function-call-profile",
        "previousCurrentProfile": None, "previousNewThreadProfile": None,
        "functions": [{"module": function.__module__, "qualname": function.__qualname__,
            "file": function.__code__.co_filename, "firstLine": function.__code__.co_firstlineno,
            "sourceSha256": hashlib.sha256(Path(function.__code__.co_filename).read_bytes()).hexdigest()}
            for function in base_functions.values()]}

    def profile(frame, name, returned):
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
                "receiverIsExactObservedOwner": True, "workspaceIsExactOwner": arguments.get("workspace") is workspace,
                "options": _arguments({key: arguments[key] for key in
                    ("force", "sources", "paths", "force_sources") if key in arguments})}
            raw["originalBaseCalls"].append(call)
            local.bases = (*stack, (id(frame), call))
        elif stack and stack[-1][0] == id(frame):
            call = stack[-1][1]
            call.update(returned=_search_result_custody(returned),
                returnSeq=event("original-base-producer-return", ownerId=owner_id,
                                method=function.__name__)["sequence"])
            local.bases = stack[:-1]

    def bind_observers(owner, owner_id):
        original_connect = owner.connect

        def connect_observer():
            db = original_connect()
            connection_id = str(id(db))

            def traced(statement):
                stack = getattr(local, "bases", ())
                row = event("original-sql-statement", ownerId=owner_id, connectionId=connection_id,
                    statement=statement, baseCallId=stack[-1][1]["id"] if stack else None)
                raw["sqlStatements"].append(row)
                if gate is not None and stack and statement.strip().upper() == "BEGIN IMMEDIATE":
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
                call = {"id": f"method-{entered['sequence']}", "ownerId": owner_id, "method": name,
                    "activeTool": getattr(local, "tool", None), "activeSync": getattr(local, "sync", None),
                    "enterSeq": entered["sequence"], "threadId": threading.get_ident(),
                    "options": _arguments(kwargs), "arguments": _arguments({str(i): v for i, v in enumerate(args)}),
                    "parentOperationId": operations[-1] if operations else None,
                    "baseCallId": stack[-1][1]["id"] if stack else None,
                    "receiverIsExactObservedOwner": original.__self__ is owner}
                raw[bucket].append(call)
                if name in {"reindex", "search"}:
                    label = getattr(local, "sync" if name == "reindex" else "tool", None)
                    if label in call_entered:
                        call_entered[label].set()
                if name == "_reindex_locked":
                    call["revisionBefore"] = owner.index_revision()
                if name == "_on_search_snapshot":
                    db = args[0]
                    pinned = {"ownerId": owner_id, "activeTool": getattr(local, "tool", None),
                        "dbPath": str(owner.path), "connectionId": str(id(db)),
                        "inTransactionBefore": db.in_transaction, "readRevision": owner.index_revision(db=db),
                        "databases": [list(row) for row in db.execute("PRAGMA database_list")],
                        **_sql_rows(db), "inTransactionAfter": db.in_transaction}
                    encoded = _serialized(pinned)
                    destination = directory / f"sql-pinned-{entered['sequence']}.json"
                    destination.write_text(encoded + "\n", encoding="utf8")
                    call["pinnedSnapshot"] = {**pinned, "file": str(destination), "serializedJSON": encoded,
                        "sha256": hashlib.sha256(encoded.encode()).hexdigest()}
                try:
                    returned = original(*args, **kwargs)
                    if name == "search":
                        pending_searches.append((call, returned))
                    else:
                        call["returned"] = _search_result_custody(returned)
                    return returned
                except BaseException as error:
                    call["error"] = _original_error(error)
                    raise
                finally:
                    if name == "_reindex_locked":
                        call["revisionAfter"] = owner.index_revision()
                    if name == "_on_index_publication_write":
                        call["writeChanges"] = kwargs["changes"]
                        call["writeError"] = None if kwargs["error"] is None else _original_error(kwargs["error"])
                    call["lifecycleAfter"] = owner.lifecycle_snapshot()
                    call["returnSeq"] = event("original-method-return", ownerId=owner_id, method=name)["sequence"]

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
            record["error"] = _original_error(error)
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
            call["envelopeFile"] = _persist_tool_envelope(directory, label, returned)
            call["envelope"] = deepcopy(returned)
            return deepcopy(returned["details"])
        except BaseException as error:
            call["error"] = _original_error(error)
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
            call["outcome"] = {"status": "fulfilled"}
        except BaseException as error:
            call["error"] = _original_error(error)
            call["outcome"] = {"status": "rejected"}
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

    def dispatch_counts():
        commits = [call for call in raw["publicationCalls"] if "error" not in call and "returned" in call]
        raw["counterDerivations"] = {"managerSearchCallIds": [call["id"] for call in raw["originalSearchCalls"]],
            "explicitSyncLabels": list(raw["syncCalls"]),
            "producerBaseCallIds": [call["id"] for call in raw["originalBaseCalls"]],
            "publicationCommitCallIds": [call["id"] for call in commits],
            "unit": "original-public-base-reindex-or-reindex_sources-execution-entry"}
        return {"managerSearches": len(raw["originalSearchCalls"]), "explicitSyncRequests": len(raw["syncCalls"]),
                "producerDispatches": len(raw["originalBaseCalls"]), "publicationCommits": len(commits)}

    threading.setprofile(profile)
    sys.setprofile(profile)
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
            elif operation in {"acquire-owner", "acquire-original-default-owner", "reopen-owner"}:
                acquire(step.get("label", "first" if not owners else "reopened"))
            elif operation in {"public-memory-search", "start-search"}:
                label = step["label"]
                start_call("search", label, value["queries"][label])
                if operation == "public-memory-search":
                    await_call(label)
            elif operation in {"original-sync", "start-sync"}:
                label = step["label"]
                start_call("sync", label, step["params"])
                if operation == "original-sync":
                    await_call(label)
            elif operation in {"await-sync", "await-search"}:
                await_call(step["label"])
            elif operation == "arm-sql-gate":
                gate = _SqlWriterGate(index_path, event, _path_entry)
                raw["sqlGates"].append(gate.receipt)
                gate.arm()
            elif operation in {"await-real-publication-pending", "await-original-busy"}:
                gate.wait(3)
            elif operation == "await-call-enter":
                label = step["label"]
                timeout = 3 if gate is None or gate.db is None else min(3, gate.remaining())
                if not call_entered[label].wait(timeout):
                    raise TimeoutError("An independent caller did not enter its actual original API")
                schedule["originalCallPending"] = not call_futures[label].done()
                schedule["observedSeq"] = event("independent-original-call-entered", label=label)["sequence"]
            elif operation == "release-sql-gate":
                schedule["callCompletionBeforeRelease"] = {label: future.done() for label, future in call_futures.items()}
                gate.release()
            elif operation == "arm-publication-fault":
                fault = _PublicationSidecarFault(index_path, directory, value["fault"])
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
            elif operation == "capture-physical-sql":
                physical(step["label"])
            elif operation == "capture-sources":
                sources(step["label"])
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
        # Complete public envelopes and original streams are already durable.
        for call, returned in pending_searches:
            call.update(_search_return_custody(returned))
        providers = {call["returned"]["provider"] for call in raw["statusCalls"] if "returned" in call}
        if len(providers) != 1:
            raise RuntimeError("Actual public manager statuses did not identify one selected provider")
        raw["independentCalls"] = calls
        raw["result"] = {"provider": providers.pop(), "searches": searches, "syncs": syncs,
            "dispatches": dispatch_counts(),
            "sources": {label: receipt["common"] for label, receipt in raw["sourceStages"].items()}}
        raw["completed"] = True
        return {"result": raw["result"], "raw": raw}
    except BaseException as error:
        raw["error"] = _original_error(error)
        raise
    finally:
        phase = "teardown"
        errors = []
        if gate is not None and gate.db is not None:
            try:
                gate.release()
                gate.receipt["releasedDuringTeardown"] = True
            except BaseException as error:
                errors.append({"operation": "release-sql-gate", **_original_error(error)})
        for label, future in call_futures.items():
            try:
                future.result(timeout=20)
            except BaseException as error:
                errors.append({"operation": "settle-independent-caller", "label": label, **_original_error(error)})
        executor.shutdown(wait=True)
        if fault is not None and fault.armed:
            try:
                fault.remove()
                fault.receipt["removedDuringTeardown"] = True
            except BaseException as error:
                errors.append({"operation": "remove-fault", **_original_error(error)})
        for owner in owners:
            if not owner.closed:
                try:
                    close_owner(owner)
                except BaseException as error:
                    errors.append({"operation": "owner-close", **_original_error(error)})
        sys.setprofile(previous_profile)
        threading.setprofile(previous_thread_profile)
        raw["baseCallObservation"]["profilesRestored"] = (sys.getprofile() is previous_profile
            and threading.getprofile() is previous_thread_profile)
        raw["allManagersClosed"] = all(owner.closed for owner in owners)
        raw["implementationBindings"] = _loaded_sdk()
        raw["sourceIdentity"]["afterClose"] = _sdk_sources()
        if errors:
            raw["teardownErrors"] = errors
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
