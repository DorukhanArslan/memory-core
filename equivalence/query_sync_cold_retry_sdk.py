"""Zero-credit cold-retry measurements using one original managed SDK owner.

Only fixture files, a physical publication fault, and observations belong to this
adapter. The original public tool and store decide all repair and retry behavior.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback

from equivalence.index_identity_boundaries_sdk import _search_result_custody
from equivalence.query_sync_cold_retry import build_cases, validate_case
from equivalence.query_sync_outcomes_sdk import (
    _arguments,
    _capture_sources,
    _error,
    _owned_path,
    _persist_tool_envelope,
    _search_return_custody,
    _serialized,
    _sql_rows,
    _stat,
)

ROOT = Path(__file__).resolve().parents[1]


def _literal(value):
    for case in build_cases():
        try:
            return validate_case({**case, "input": value})
        except ValueError:
            pass
    raise ValueError("The SDK cold-retry process requires an exact frozen zero-credit input")


def _query_labels(value):
    """The ordered steps own execution; JSON object key order is immaterial."""
    labels = [step["label"] for step in value["steps"]
              if step["operation"] == "public-memory-search"]
    if len(labels) != len(set(labels)) or set(labels) != set(value["queries"]):
        raise ValueError("Every declared query requires exactly one ordered public search step")
    return labels


def _original_error(error):
    result = {**_error(error), "module": type(error).__module__,
              "arguments": _search_result_custody(error.args),
              "traceback": "".join(traceback.format_exception(error))}
    for name in ("sqlite_errorcode", "sqlite_errorname", "code", "name"):
        if hasattr(error, name):
            result[name] = _search_result_custody(getattr(error, name))
    return result


def _path_entry(path):
    """Inspect an owned directory entry without following its possible alias."""
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        return {"path": str(path), "kind": "missing", "error": _original_error(error)}
    kind = ("symlink" if stat.S_ISLNK(info.st_mode) else
            "file" if stat.S_ISREG(info.st_mode) else "other")
    result = {"path": str(path), "kind": kind, "stat": _stat(info)}
    if kind == "symlink":
        result["linkTarget"] = os.readlink(path)
    elif kind == "file":
        payload = path.read_bytes()
        result.update(hex=payload.hex(), sha256=hashlib.sha256(payload).hexdigest())
    return result


class _PublicationSidecarFault:
    """Own only the declared temporary journal entry, preserving any real file."""

    def __init__(self, index_path, directory, specification):
        self.path = Path(str(index_path) + "-journal")
        self.saved = directory / "original-publication-sidecar"
        self.target = _owned_path(directory, specification["target"])
        self.armed = False
        self.receipt = {"kind": specification["kind"], "path": str(self.path),
                        "target": str(self.target), "savedPath": str(self.saved)}

    def arm(self):
        self.receipt["before"] = _path_entry(self.path)
        self.receipt["targetParentBefore"] = _path_entry(self.target.parent)
        if self.receipt["targetParentBefore"]["kind"] != "missing":
            raise RuntimeError("The declared sidecar target parent must actually be absent")
        if self.saved.exists() or self.saved.is_symlink():
            raise RuntimeError("The sidecar preservation path is already occupied")
        if self.receipt["before"]["kind"] == "file":
            self.path.rename(self.saved)
            self.receipt["renamedOriginal"] = _path_entry(self.saved)
        elif self.receipt["before"]["kind"] != "missing":
            raise RuntimeError("Refuse to follow or replace an existing sidecar alias")
        try:
            self.path.symlink_to(self.target)
        except BaseException:
            if self.saved.exists():
                self.saved.rename(self.path)
            raise
        self.armed = True
        self.receipt["armed"] = _path_entry(self.path)
        try:
            self.path.stat()
        except FileNotFoundError as error:
            self.receipt["actualFollowError"] = _original_error(error)
        else:
            raise RuntimeError("The armed sidecar must be a genuine dangling symlink")
        return self.receipt

    def remove(self):
        current = _path_entry(self.path)
        self.receipt["beforeRemoval"] = current
        expected = self.receipt["armed"]
        if (current["kind"] != "symlink" or current["linkTarget"] != expected["linkTarget"]
                or any(current["stat"][key] != expected["stat"][key]
                       for key in ("st_dev", "st_ino"))):
            raise RuntimeError("The owned fault entry changed before removal")
        self.path.unlink()
        self.receipt["afterUnlink"] = _path_entry(self.path)
        if "renamedOriginal" in self.receipt:
            self.saved.rename(self.path)
        self.receipt["afterRemoval"] = _path_entry(self.path)
        self.receipt["savedAfterRemoval"] = _path_entry(self.saved)
        self.armed = False
        return self.receipt


def _derive_dispatches(raw, labels):
    """Use real receiver-qualified calls and the actual managed repair journal."""
    lifecycle = raw["owners"]["owner-1"]["close"]["lifecycle"]
    if lifecycle["operationJournalTruncated"] or lifecycle["repairJournalTruncated"]:
        raise RuntimeError("Cold-retry dispatch custody was truncated")
    dispatches, derivations = {}, {}
    for label in labels:
        tool = raw["toolCalls"][label]
        calls = [call for call in raw["originalSearchCalls"] if call["activeTool"] == label]
        if any(not call["receiverIsExactObservedOwner"] or call["ownerId"] != "owner-1"
               or not tool["enterSeq"] < call["enterSeq"] < call["returnSeq"] < tool["returnSeq"]
               for call in calls):
            raise RuntimeError("A search dispatch escaped its actual same-owner public call")
        operation_ids = {number for call in calls for number in call["managedSearchOperationIds"]}
        repairs = [repair for repair in lifecycle["repairs"]
                   if repair["reason"] == "search-bootstrap"
                   and repair["searchOperationId"] in operation_ids]
        reindexes = [call for call in raw["methodCalls"]
                     if call["method"] == "reindex" and call["parentOperationId"] in operation_ids]
        if len(repairs) != len(reindexes):
            raise RuntimeError("Actual bootstrap repairs differ from original reindex entries")
        dispatches[label] = {"managerSearches": len(calls), "bootstrapAttempts": len(repairs)}
        derivations[label] = {"searchCallIds": [call["id"] for call in calls],
            "managedSearchOperationIds": sorted(operation_ids), "repairIds": [row["id"] for row in repairs],
            "reindexCallIds": [row["id"] for row in reindexes]}
    raw["dispatchDerivations"] = derivations
    return dispatches


def run_query_sync_cold_retry_sdk_host(request):
    """Run one frozen schedule; the coordinator never retries this process."""
    import memory_core
    from memory_core.config import MemoryConfig
    from memory_core.flags import FeatureFlags
    from memory_core.host.managed_index import ManagedSQLiteMemoryStore
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.session_catalog import MemorySessionCatalog
    from memory_core.session_visibility import resolve_memory_search_source_policy
    from memory_core.tools.memory_search import MemorySearchToolContext
    from memory_core.tools.search_factory import create_memory_search_tool
    from memory_core.workspace import MemoryWorkspace

    if not isinstance(request, dict) or set(request) != {"input", "directory"}:
        raise ValueError("The protected SDK cold-retry process requires input and directory")
    value, directory = request["input"], Path(request["directory"])
    case = _literal(value)
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ValueError("An existing absolute owned SDK cold-retry directory is required")
    implementation = Path(memory_core.__file__).resolve().parents[1]
    if implementation != ROOT:
        raise RuntimeError("The protected cold-retry child imported another SDK tree")
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
    raw = {"kind": "query-sync-cold-retry-development", "engine": "sdk", "caseId": case["id"],
        "acceptancePointsAwarded": 0, "input": deepcopy(value), "pid": os.getpid(), "ppid": os.getppid(),
        "fixtureBase": str(directory), "implementationRoot": str(implementation),
        "requestedConfig": deepcopy(value["config"]), "sourcePolicy": deepcopy(policy),
        "sdkProfile": {"runtimeIdentity": "openclaw-compatible", "memoryPublication": "on-search",
                       "publicFactory": "memory_core.tools.search_factory.create_memory_search_tool",
                       "contextStatus": None, "refreshStore": None},
        "clock": {"owner": "public-tool-clock", "nowMs": value["nowMs"], "monotonicAndTimers": "unmodified"},
        "process": {"cwd": str(Path.cwd()), "executable": sys.executable, "version": sys.version,
                    "environmentKeys": sorted(os.environ),
                    "cmdlineHex": Path("/proc/self/cmdline").read_bytes().hex()},
        "events": [], "owners": {}, "ownerAcquisitions": [], "statusCalls": [],
        "originalSearchCalls": [], "methodCalls": [], "backgroundCalls": [], "readAdmissions": [],
        "snapshots": [], "sourceStages": {}, "toolCalls": {}, "toolBindings": [], "faults": []}
    sequence, phase, active_tool = 0, "setup", None
    lock = threading.RLock()
    owner, fault, pending_searches = None, None, []

    def event(name, **values):
        nonlocal sequence
        with lock:
            sequence += 1
            row = {"event": name, "sequence": sequence, "atNs": str(time.monotonic_ns()),
                   "phase": phase, "threadId": threading.get_ident(), **values}
            raw["events"].append(row)
            with (directory / "events.jsonl").open("a", encoding="utf8") as stream:
                stream.write(_serialized(row) + "\n")
            return row

    def checkpoint():
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
        receipt = _capture_sources(workspace_path, set(value["initialFiles"]), directory, label)
        finished = event("source-read-return", label=label)
        receipt.update(enterSeq=entered["sequence"], returnSeq=finished["sequence"])
        raw["sourceStages"][label] = receipt

    def bind_observers():
        original_status, original_search = owner.status, owner.search

        def status_observer(*args, **kwargs):
            entered = event("original-status-enter", ownerId="owner-1", activeTool=active_tool)
            call = {"ownerId": "owner-1", "activeTool": active_tool, "enterSeq": entered["sequence"],
                    "receiverIsExactObservedOwner": original_status.__self__ is owner}
            raw["statusCalls"].append(call)
            try:
                returned = original_status(*args, **kwargs)
                call["result"] = deepcopy(returned)
                return returned
            except BaseException as error:
                call["error"] = _original_error(error)
                raise
            finally:
                call["returnSeq"] = event("original-status-return", ownerId="owner-1",
                                          activeTool=active_tool)["sequence"]

        def search_observer(query, **options):
            entered = event("original-search-enter", ownerId="owner-1", activeTool=active_tool)
            before = owner.lifecycle_snapshot()["operationCount"]
            call = {"id": f"search-{len(raw['originalSearchCalls']) + 1}", "ownerId": "owner-1",
                "activeTool": active_tool, "query": query, "options": _arguments(options),
                "enterSeq": entered["sequence"], "threadId": threading.get_ident(),
                "receiverIsExactObservedOwner": original_search.__self__ is owner}
            raw["originalSearchCalls"].append(call)
            try:
                returned = original_search(query, **options)
                pending_searches.append((call, returned))
                return returned
            except BaseException as error:
                call["error"] = _original_error(error)
                raise
            finally:
                lifecycle = owner.lifecycle_snapshot()
                call["managedSearchOperationIds"] = [row["id"] for row in lifecycle["operations"]
                    if row["name"] == "search" and row["id"] > before
                    and row["threadId"] == call["threadId"]]
                call["lifecycleAfter"] = lifecycle
                call["returnSeq"] = event("original-search-return", ownerId="owner-1",
                                          activeTool=active_tool)["sequence"]

        owner.status, owner.search = status_observer, search_observer

        def observe_method(name, bucket):
            original = getattr(owner, name)

            def observed(*args, **kwargs):
                entered = event("original-method-enter", ownerId="owner-1", method=name,
                                activeTool=active_tool)
                operations = getattr(owner._local, "operations", ())
                call = {"id": f"{name}-{entered['sequence']}", "ownerId": "owner-1", "method": name,
                    "activeTool": active_tool, "enterSeq": entered["sequence"],
                    "threadId": threading.get_ident(), "options": _arguments(kwargs),
                    "parentOperationId": operations[-1] if operations else None,
                    "receiverIsExactObservedOwner": original.__self__ is owner}
                raw[bucket].append(call)
                if name in {"reindex", "reindex_sources"}:
                    call["workspaceIsExactOwner"] = args[0] is workspace
                elif name == "_submit_memory_publication":
                    call["readRevision"] = args[0]
                elif name == "_run_memory_publication":
                    call.update(jobAtEntry=deepcopy(args[0]), workerTokenId=str(id(args[1])),
                                actualWorkerTokenMatches=owner._memory_worker_token is args[1])
                elif name == "_on_search_snapshot":
                    db = args[0]
                    call["readRevision"] = owner.index_revision(db=db)
                    pinned = {"ownerId": "owner-1", "activeTool": active_tool,
                        "dbPath": str(owner.path), "connectionId": str(id(db)),
                        "inTransactionBefore": db.in_transaction, "readRevision": call["readRevision"],
                        "databases": [list(row) for row in db.execute("PRAGMA database_list")],
                        **_sql_rows(db), "inTransactionAfter": db.in_transaction,
                        "sameActualConnectionPassedToOriginal": True}
                    encoded = _serialized(pinned)
                    destination = directory / f"sql-pinned-{entered['sequence']}.json"
                    destination.write_text(encoded + "\n", encoding="utf8")
                    call["pinnedSnapshot"] = {**pinned, "file": str(destination), "serializedJSON": encoded,
                                             "sha256": hashlib.sha256(encoded.encode()).hexdigest()}
                try:
                    returned = original(*args, **kwargs)
                    call["returned"] = _search_result_custody(returned)
                    return returned
                except BaseException as error:
                    call["error"] = _original_error(error)
                    raise
                finally:
                    call["lifecycleAfter"] = owner.lifecycle_snapshot()
                    if name == "_run_memory_publication":
                        call["jobAtReturn"] = deepcopy(args[0])
                    call["returnSeq"] = event("original-method-return", ownerId="owner-1", method=name,
                                              activeTool=active_tool)["sequence"]
            setattr(owner, name, observed)

        for name in ("reindex", "reindex_sources"):
            observe_method(name, "methodCalls")
        for name in ("_submit_memory_publication", "_run_memory_publication"):
            observe_method(name, "backgroundCalls")
        observe_method("_on_search_snapshot", "readAdmissions")

    def tool_call(label, params):
        nonlocal active_tool
        active_tool = label
        tool = create_memory_search_tool(config, owner, context=MemorySearchToolContext(
            clock=lambda: value["nowMs"], source_policy=policy), runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
        if tool is None:
            raise RuntimeError("The actual SDK factory returned no public memory_search tool")
        binding = event("actual-tool-binding", label=label, ownerId="owner-1")
        raw["toolBindings"].append({"label": label, "ownerId": "owner-1", "sequence": binding["sequence"],
            "storeIsExactObservedOwner": tool._store is owner, "storeObjectId": str(id(tool._store)),
            "configIsExactOwnerConfig": tool._config is config, "contextStatusIsNone": tool._context.status is None,
            "refreshStoreIsNone": tool._context.refresh_store is None, "definition": tool.definition})
        call = {"label": label, "ownerId": "owner-1", "args": deepcopy(params),
                "enterSeq": event("actual-tool-enter", label=label, ownerId="owner-1")["sequence"]}
        raw["toolCalls"][label] = call
        try:
            returned = tool.execute(f"cold-retry-{label}", deepcopy(params))
            call["envelopeFile"] = _persist_tool_envelope(directory, label, returned)
            call["envelope"] = deepcopy(returned)
            return deepcopy(returned["details"])
        except BaseException as error:
            call["error"] = _original_error(error)
            raise
        finally:
            call["returnSeq"] = event("actual-tool-return", label=label, ownerId="owner-1")["sequence"]
            active_tool = None

    try:
        for relative, text in value["initialFiles"].items():
            target = _owned_path(workspace_path, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf8", newline="") as stream:
                stream.write(text)
            os.utime(target, ns=(value["initialSourceMtimeMs"] * 1_000_000,) * 2)
        sources("initial")
        physical("before-open")
        phase = "owner-acquisition"
        entered = event("original-open-enter", api="ManagedSQLiteMemoryStore")
        owner = ManagedSQLiteMemoryStore(config, workspace, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
                                         memory_publication="on-search")
        returned = event("original-open-return", ownerId="owner-1")
        raw["ownerAcquisitions"].append({"ownerId": "owner-1", "api": "ManagedSQLiteMemoryStore",
            "enterSeq": entered["sequence"], "returnSeq": returned["sequence"], "objectId": str(id(owner)),
            "workspaceIsExactOwner": owner._workspace is workspace, "catalogIsExactOwner": owner._bound_catalog is catalog})
        raw["owners"]["owner-1"] = {"objectId": str(id(owner)), "constructorName": type(owner).__qualname__,
            "config": _search_result_custody(asdict(config)), "indexPath": str(owner.path),
            "sdkPolicy": {"memoryPublication": owner._memory_publication,
                          "runtimeIdentity": asdict(owner._runtime_identity)},
            "lifecycleAtAcquisition": owner.lifecycle_snapshot()}
        bind_observers()
        physical("after-open")
        if "fault" in value:
            phase = "fault-arm"
            fault = _PublicationSidecarFault(index_path, directory, value["fault"])
            raw["faults"].append(fault.receipt)
            fault.receipt["armEnterSeq"] = event("physical-fault-arm-enter")["sequence"]
            fault.arm()
            fault.receipt["armReturnSeq"] = event("physical-fault-arm-return")["sequence"]
        searches = {}
        query_labels = _query_labels(value)
        for number, label in enumerate(query_labels):
            phase = f"query-{label}"
            searches[label] = tool_call(label, value["queries"][label])
            if number == 0 and fault is not None:
                phase = "fault-removal"
                fault.receipt["removeEnterSeq"] = event("physical-fault-remove-enter")["sequence"]
                fault.remove()
                fault.receipt["removeReturnSeq"] = event("physical-fault-remove-return")["sequence"]
        phase = "owner-close"
        entered = event("original-close-enter", ownerId="owner-1")
        close_receipt = {"enterSeq": entered["sequence"]}
        raw["owners"]["owner-1"]["close"] = close_receipt
        try:
            close_receipt["returned"] = owner.close()
        except BaseException as error:
            close_receipt["error"] = _original_error(error)
            raise
        finally:
            close_receipt.update(returnSeq=event("original-close-return", ownerId="owner-1")["sequence"],
                                 lifecycle=owner.lifecycle_snapshot(), closed=owner.closed)
        phase = "after-close"
        physical("after-close")
        sources("afterClose")
        checkpoint()
        for call, returned in pending_searches:
            call.update(_search_return_custody(returned))
        providers = {call["result"]["provider"] for call in raw["statusCalls"] if "result" in call}
        if len(providers) != 1:
            raise RuntimeError("Actual public manager statuses did not identify one selected provider")
        raw["result"] = {"provider": providers.pop(), "searches": searches,
            "dispatches": _derive_dispatches(raw, query_labels),
            "sources": {label: raw["sourceStages"][label]["common"] for label in ("initial", "afterClose")}}
        raw["completed"] = True
        return {"result": raw["result"], "raw": raw}
    except BaseException as error:
        raw["error"] = _original_error(error)
        raise
    finally:
        phase = "teardown"
        teardown_errors = []
        if fault is not None and fault.armed:
            try:
                fault.remove()
                fault.receipt["removedDuringTeardown"] = True
            except BaseException as error:
                teardown_errors.append({"operation": "remove-fault", **_original_error(error)})
        if owner is not None and not owner.closed:
            try:
                owner.close()
            except BaseException as error:
                teardown_errors.append({"operation": "owner-close", **_original_error(error)})
        raw["allManagersClosed"] = owner is not None and owner.closed
        raw["finalLifecycle"] = None if owner is None else owner.lifecycle_snapshot()
        raw["implementationBindings"] = [{"module": name, "path": str(Path(module.__file__).resolve()),
            "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
            for name, module in sorted(sys.modules.items()) if name.startswith("memory_core")
            and getattr(module, "__file__", None) and Path(module.__file__).is_file()]
        if teardown_errors:
            raw["teardownErrors"] = teardown_errors
        checkpoint()
        if teardown_errors and sys.exc_info()[0] is None:
            raise RuntimeError("Original SDK teardown failed; actual errors and early envelopes retained")


def run_query_sync_cold_retry_case(value, *, evidence_directory=None):
    """One protected original SDK child, with no retry or output repair."""
    _literal(value)
    if evidence_directory is not None:
        Path(evidence_directory).mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="sdk-cold-retry-", dir=evidence_directory)).resolve()
    request = {"input": value, "directory": str(directory)}
    wire = _serialized(request)
    environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
        "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC", "OPENCLAW_HOME": str(directory),
        "OPENCLAW_STATE_DIR": str(directory / "state")}
    argv = [sys.executable, "-m", "equivalence.query_sync_cold_retry_sdk_cli"]
    dispatch = {"kind": "query-sync-cold-retry-sdk-dispatch", "input": deepcopy(value),
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
            raise RuntimeError("Original SDK cold-retry process timed out; complete streams retained") from None
    dispatch.update(stdout=stdout, stderr=stderr, exit={"code": child.returncode},
                    finishedAtNs=str(time.monotonic_ns()))
    try:
        dispatch["observation"] = json.loads(stdout)
    except json.JSONDecodeError as error:
        dispatch["stdoutParseError"] = _original_error(error)
    (destination / "python-raw.json").write_text(_serialized([dispatch]) + "\n", encoding="utf8")
    if child.returncode or "observation" not in dispatch or "result" not in dispatch["observation"]:
        raise RuntimeError("Original SDK cold-retry process failed; streams and early tool envelopes retained")
    return dispatch["observation"]["result"]
