"""Original managed SDK owners and public tools for frozen query-sync inputs.

The adapter owns source fixtures and observation only. Production search admits
bootstrap and scoped publication; original close joins that admitted work.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time

from equivalence.index_identity_boundaries_sdk import _search_result_custody
from equivalence.query_sync_outcomes import build_cases, validate_case

ROOT = Path(__file__).resolve().parents[1]


def _serialized(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _literal(value):
    for case in build_cases():
        try:
            return validate_case({**case, "input": value})
        except ValueError:
            pass
    raise ValueError("The SDK query-sync owner requires an exact frozen input")


def _error(error):
    result = {"name": type(error).__name__, "message": str(error)}
    if isinstance(error, OSError):
        result.update(errno=error.errno, filename=error.filename, filename2=error.filename2)
    return result


def _stat(info):
    return {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}


def _owned_path(root, relative):
    path = PurePosixPath(relative)
    if (not isinstance(relative, str) or not relative or path.is_absolute()
            or ".." in path.parts or str(path) != relative or "\\" in relative):
        raise ValueError("Source fixtures require canonical owned relative paths")
    target = root.joinpath(*path.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("A source fixture escaped its exact workspace")
    return target


def _declared_paths(value):
    paths = set(value["initialFiles"])
    mutation = value["sourceMutation"] or {}
    paths.update(mutation[key] for key in ("path", "from", "to") if key in mutation)
    return paths


def _capture_sources(root, declared_paths, evidence_directory, label):
    """Read actual source bytes/stats, retaining durable bytes before any codec."""
    paths = set(declared_paths)
    for candidate in root.rglob("*"):
        if stat.S_ISREG(candidate.lstat().st_mode):
            paths.add(candidate.relative_to(root).as_posix())
    receipt = {"label": label, "workspace": str(root), "entries": [], "common": []}
    blob_directory = evidence_directory / "source-bytes" / label
    blob_directory.mkdir(parents=True)
    for number, relative in enumerate(sorted(paths)):
        target = _owned_path(root, relative)
        entry = {"path": relative, "absolutePath": str(target)}
        receipt["entries"].append(entry)
        try:
            before = target.lstat()
        except FileNotFoundError as error:
            entry.update(kind="missing", error=_error(error))
            receipt["common"].append({"path": relative, "kind": "missing"})
            continue
        entry["statBefore"] = _stat(before)
        if not stat.S_ISREG(before.st_mode):
            entry["kind"] = "non-regular"
            (evidence_directory / f"sources-{label}.json").write_text(_serialized(receipt) + "\n")
            raise RuntimeError("A declared source is not an actual regular file")
        payload = target.read_bytes()
        blob_path = blob_directory / f"{number:03d}.bin"
        blob_path.write_bytes(payload)
        after = target.lstat()
        entry.update(kind="file", statAfter=_stat(after), byteFile=str(blob_path),
                     hex=payload.hex(), sha256=hashlib.sha256(payload).hexdigest(),
                     text=payload.decode("utf8", errors="replace"))
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                or after.st_size != len(payload)):
            (evidence_directory / f"sources-{label}.json").write_text(_serialized(receipt) + "\n")
            raise RuntimeError("An actual source changed during its evidence read")
        receipt["common"].append({"path": relative, "kind": "file", "text": entry["text"],
            "hex": entry["hex"], "sha256": entry["sha256"], "size": after.st_size,
            "mtimeMs": after.st_mtime_ns / 1_000_000})
    (evidence_directory / f"sources-{label}.json").write_text(_serialized(receipt) + "\n", encoding="utf8")
    return receipt


def _persist_tool_envelope(directory, label, returned):
    """The public return is persisted before encoding any private store return."""
    path = directory / f"tool-{label}-envelope.json"
    payload = (_serialized(returned) + "\n").encode("utf8")
    path.write_bytes(payload)
    if (not isinstance(returned, dict) or not isinstance(returned.get("content"), list)
            or not returned["content"] or returned["content"][0].get("type") != "text"
            or json.loads(returned["content"][0]["text"]) != returned.get("details")):
        raise RuntimeError("The original SDK public text differs from complete tool details")
    return {"path": str(path), "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def _search_return_custody(returned):
    result = {"result": _search_result_custody(returned),
              "returnType": {"module": type(returned).__module__, "qualname": type(returned).__qualname__}}
    if hasattr(returned, "__dict__"):
        result["returnAttributes"] = _search_result_custody(vars(returned))
    # Unknown private objects must fail visibly, never turn into repr/str.
    _serialized(result)
    return result


def _sql_rows(db):
    """SELECT complete physical rows without changing the supplied reader."""
    def rows(sql):
        cursor = db.execute(sql)
        names = [column[0] for column in cursor.description]
        return [_search_result_custody(dict(zip(names, row, strict=True))) for row in cursor]

    schema = rows("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")
    tables = {row["name"]: rows('SELECT * FROM "' + row["name"].replace('"', '""') + '"')
              for row in schema if row["type"] == "table"}
    return {"schema": schema, "tables": tables}


def _arguments(values):
    observed = {}
    for key, value in values.items():
        if value is None or isinstance(value, (str, int, float, bool, list, tuple, dict)):
            observed[key] = deepcopy(value)
        elif isinstance(value, (set, frozenset)):
            observed[key] = {"setValues": sorted(value)}
        elif callable(value):
            observed[key] = {"callable": True, "module": value.__module__,
                             "qualname": value.__qualname__, "objectId": str(id(value))}
        elif is_dataclass(value):
            observed[key] = {"className": type(value).__qualname__, "objectId": str(id(value)),
                             "fields": _arguments(vars(value))}
        else:
            observed[key] = {"className": type(value).__qualname__, "objectId": str(id(value))}
            if hasattr(value, "aborted"):
                observed[key]["aborted"] = bool(value.aborted)
    return observed


def run_query_sync_outcomes_sdk_host(request):
    """Execute one frozen input in its original protected SDK child process."""
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
        raise ValueError("The protected SDK query-sync process requires input and owned directory")
    value, directory = request["input"], Path(request["directory"])
    case = _literal(value)
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ValueError("An existing absolute owned SDK query-sync directory is required")
    implementation = Path(memory_core.__file__).resolve().parents[1]
    if implementation != ROOT:
        raise RuntimeError("The protected query-sync child imported another SDK tree")
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
    raw = {"kind": "query-sync-outcomes", "engine": "sdk", "caseId": case["id"],
        "input": deepcopy(value), "pid": os.getpid(), "ppid": os.getppid(),
        "fixtureBase": str(directory), "implementationRoot": str(implementation),
        "requestedConfig": deepcopy(value["config"]), "sourcePolicy": deepcopy(policy),
        "sdkProfile": {"runtimeIdentity": "openclaw-compatible", "memoryPublication": "on-search",
                       "publicFactory": "memory_core.tools.search_factory.create_memory_search_tool",
                       "contextStatus": None},
        "clock": {"owner": "public-tool-clock", "nowMs": value["nowMs"], "monotonicAndTimers": "unmodified"},
        "process": {"cwd": str(Path.cwd()), "executable": sys.executable,
                    "version": sys.version, "environmentKeys": sorted(os.environ),
                    "cmdlineHex": Path("/proc/self/cmdline").read_bytes().hex()},
        "events": [], "owners": {}, "ownerAcquisitions": [], "statusCalls": [],
        "originalSearchCalls": [], "methodCalls": [], "backgroundCalls": [], "readAdmissions": [],
        "snapshots": [], "sourceStages": {}, "toolCalls": {}, "toolBindings": []}
    sequence, phase, active_tool = 0, "setup", None
    lock = threading.RLock()
    owners, pending_searches = [], []
    owner_refs = {}

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

    def physical(label, path=index_path):
        entered = event("physical-sql-read-enter", label=label, dbPath=str(path))
        state = {"dbPath": str(path)}
        try:
            state["fileStat"] = _stat(path.lstat())
        except FileNotFoundError as error:
            state.update(absent=True, error=_error(error), schema=[], tables={})
        else:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
                db.execute("BEGIN")
                state.update(absent=False, **_sql_rows(db))
                db.rollback()
        encoded = _serialized(state)
        destination = directory / f"sql-{label}.json"
        destination.write_text(encoded + "\n", encoding="utf8")
        finished = event("physical-sql-read-return", label=label, dbPath=str(path))
        snapshot = {"label": label, "enterSeq": entered["sequence"], "returnSeq": finished["sequence"],
                    **state, "serializedJSON": encoded, "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                    "file": str(destination), "connection": {"uriMode": "ro", "begin": not state["absent"],
                                                              "rollback": not state["absent"], "closed": True}}
        raw["snapshots"].append(snapshot)
        return snapshot

    def sources(label):
        entered = event("source-read-enter", label=label)
        receipt = _capture_sources(workspace_path, _declared_paths(value), directory, label)
        finished = event("source-read-return", label=label)
        receipt.update(enterSeq=entered["sequence"], returnSeq=finished["sequence"])
        raw["sourceStages"][label] = receipt
        return receipt

    def acquire(role):
        entered = event("original-open-enter", role=role, api="ManagedSQLiteMemoryStore")
        owner = ManagedSQLiteMemoryStore(config, workspace, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
                                         memory_publication="on-search")
        owners.append(owner)
        owner_id = f"owner-{len(owners)}"
        owner_refs[id(owner)] = owner_id
        returned = event("original-open-return", role=role, ownerId=owner_id,
                         returnedIsActualConstructedOwner=type(owner) is ManagedSQLiteMemoryStore)
        raw["ownerAcquisitions"].append({"role": role, "ownerId": owner_id, "api": "ManagedSQLiteMemoryStore",
            "enterSeq": entered["sequence"], "returnSeq": returned["sequence"], "config": _search_result_custody(asdict(config)),
            "indexPath": str(owner.path), "workspaceIsExactOwner": owner._workspace is workspace,
            "catalogIsExactOwner": owner._bound_catalog is catalog})
        raw["owners"][role] = {"ownerId": owner_id, "providerInitializedAtAcquisition": owner._provider_initialized,
            "constructorName": type(owner).__qualname__, "config": _search_result_custody(asdict(config)),
            "sdkPolicy": {"memoryPublication": owner._memory_publication,
                          "runtimeIdentity": asdict(owner._runtime_identity)}}
        original_status, original_search = owner.status, owner.search

        def status_observer(*args, **kwargs):
            entered = event("original-status-enter", ownerId=owner_id, activeTool=active_tool,
                            providerInitialized=owner._provider_initialized)
            result = original_status(*args, **kwargs)
            captured = deepcopy(result)
            finished = event("original-status-return", ownerId=owner_id, activeTool=active_tool,
                             providerInitialized=owner._provider_initialized)
            call = {"id": f"status-{len(raw['statusCalls']) + 1}",
                "ownerId": owner_id, "activeTool": active_tool, "phase": phase,
                "enterSeq": entered["sequence"], "returnSeq": finished["sequence"], "result": captured,
                "receiverIsExactObservedOwner": original_status.__self__ is owner}
            raw["statusCalls"].append(call)
            with lock, (directory / "status-calls.jsonl").open("a", encoding="utf8") as stream:
                stream.write(_serialized(call) + "\n")
            return result

        def search_observer(query, **options):
            entered = event("original-search-enter", ownerId=owner_id, activeTool=active_tool,
                            providerInitialized=owner._provider_initialized)
            call = {"id": f"search-{len(raw['originalSearchCalls']) + 1}",
                "ownerId": owner_id, "activeTool": active_tool, "phase": phase, "query": query,
                "optionKeys": list(options), "options": _arguments(options), "enterSeq": entered["sequence"],
                "receiverIsExactObservedOwner": original_search.__self__ is owner}
            raw["originalSearchCalls"].append(call)
            try:
                result = original_search(query, **options)
                pending_searches.append((call, result))
                return result
            except BaseException as error:
                call["error"] = _error(error)
                raise
            finally:
                finished = event("original-search-return", ownerId=owner_id, activeTool=active_tool,
                                 providerInitialized=owner._provider_initialized)
                call["returnSeq"] = finished["sequence"]

        owner.status, owner.search = status_observer, search_observer

        def observe_method(name, bucket):
            original = getattr(owner, name)

            def observed(*args, **kwargs):
                entered = event("original-method-enter", ownerId=owner_id, method=name,
                                activeTool=active_tool, receiverIsExactObservedOwner=original.__self__ is owner)
                call = {"ownerId": owner_id, "method": name, "activeTool": active_tool, "phase": phase,
                    "enterSeq": entered["sequence"], "threadId": threading.get_ident(),
                    "argumentCount": len(args), "options": _arguments(kwargs),
                    "receiverIsExactObservedOwner": original.__self__ is owner}
                if name == "reindex_sources":
                    call["request"] = {"sources": list(kwargs["sources"]),
                        "paths": None if kwargs.get("paths") is None else list(kwargs["paths"]),
                        "forceSources": kwargs.get("force_sources", False)}
                    call["workspaceIsExactOwner"] = args[0] is owner._workspace
                elif name == "reindex":
                    call["request"] = {"force": kwargs.get("force", False)}
                    call["workspaceIsExactOwner"] = args[0] is owner._workspace
                elif name == "_submit_memory_publication":
                    call.update(readRevision=args[0], before=owner.lifecycle_snapshot()["memoryPublication"])
                elif name == "_run_memory_publication":
                    call.update(jobId=args[0]["id"], jobAtEntry=deepcopy(args[0]),
                        workerTokenId=str(id(args[1])), actualWorkerTokenMatches=owner._memory_worker_token is args[1])
                elif name == "_on_search_snapshot":
                    call["readRevision"] = owner.index_revision(db=args[0])
                    db = args[0]
                    pinned_enter = event("pinned-sql-read-enter", ownerId=owner_id,
                        connectionId=str(id(db)), inTransaction=db.in_transaction)
                    operations = getattr(owner._local, "operations", ())
                    pinned = {"dbPath": str(owner.path), "connectionId": str(id(db)),
                        "ownerId": owner_id, "activeTool": active_tool, "threadId": threading.get_ident(),
                        "operationId": operations[-1] if operations else None,
                        "inTransactionBefore": db.in_transaction, "readRevision": call["readRevision"],
                        "databases": [list(row) for row in db.execute("PRAGMA database_list")], **_sql_rows(db),
                        "inTransactionAfter": db.in_transaction}
                    encoded = _serialized(pinned)
                    pinned_path = directory / f"sql-pinned-{owner_id}-{len(raw['readAdmissions']) + 1}.json"
                    pinned_path.write_text(encoded + "\n", encoding="utf8")
                    pinned_return = event("pinned-sql-read-return", ownerId=owner_id,
                        connectionId=str(id(db)), inTransaction=db.in_transaction)
                    call["pinnedSnapshot"] = {**pinned, "serializedJSON": encoded,
                        "sha256": hashlib.sha256(encoded.encode()).hexdigest(), "file": str(pinned_path),
                        "enterSeq": pinned_enter["sequence"], "returnSeq": pinned_return["sequence"],
                        "sameActualConnectionPassedToOriginal": True}
                raw[bucket].append(call)
                try:
                    result = original(*args, **kwargs)
                    call["returned"] = _search_result_custody(result)
                    return result
                except BaseException as error:
                    call["error"] = _error(error)
                    raise
                finally:
                    if name in {"_submit_memory_publication", "_run_memory_publication", "_on_search_snapshot"}:
                        call["lifecycleAfter"] = owner.lifecycle_snapshot()
                    if name == "_run_memory_publication":
                        call["jobAtReturn"] = deepcopy(args[0])
                    finished = event("original-method-return", ownerId=owner_id, method=name, activeTool=active_tool)
                    call["returnSeq"] = finished["sequence"]
            setattr(owner, name, observed)

        for name in ("reindex", "reindex_sources"):
            observe_method(name, "methodCalls")
        for name in ("_submit_memory_publication", "_run_memory_publication"):
            observe_method(name, "backgroundCalls")
        observe_method("_on_search_snapshot", "readAdmissions")
        return owner

    def close(owner, role):
        entered = event("original-close-enter", ownerId=owner_refs[id(owner)], role=role)
        result = owner.close()
        finished = event("original-close-return", ownerId=owner_refs[id(owner)], role=role,
                         returnedNone=result is None, closed=owner.closed)
        lifecycle = owner.lifecycle_snapshot()
        raw["owners"][role]["close"] = {"enterSeq": entered["sequence"], "returnSeq": finished["sequence"],
            "returnedNone": result is None, "closed": owner.closed, "closing": lifecycle["closing"],
            "lifecycle": lifecycle}
        failed = [job for job in lifecycle["memoryPublication"]["jobs"] if job["state"] == "failed"]
        if failed:
            raise RuntimeError("An original admitted SDK memory publisher failed; raw receipts retained")

    def tool_call(owner, label, params):
        nonlocal active_tool
        active_tool = label
        tool = create_memory_search_tool(config, owner, context=MemorySearchToolContext(
            clock=lambda: value["nowMs"], source_policy=policy), runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
        if tool is None:
            raise RuntimeError("The original SDK public factory returned no tool")
        binding = event("actual-tool-binding", label=label, ownerId=owner_refs[id(owner)])
        raw["toolBindings"].append({"label": label, "ownerId": owner_refs[id(owner)],
            "storeIsExactObservedOwner": tool._store is owner, "configIsExactOwnerConfig": tool._config is config,
            "contextStatusIsNone": tool._context.status is None,
            "runtimeIdentityIsExactOwner": tool._runtime_identity is owner._runtime_identity,
            "sequence": binding["sequence"], "definition": tool.definition})
        entered = event("actual-tool-enter", label=label, args=deepcopy(params), ownerId=owner_refs[id(owner)])
        call = {"label": label, "ownerId": owner_refs[id(owner)], "args": deepcopy(params),
                "enterSeq": entered["sequence"]}
        raw["toolCalls"][label] = call
        try:
            returned = tool.execute(f"query-sync-{label}", deepcopy(params))
            call["envelopeFile"] = _persist_tool_envelope(directory, label, returned)
            call["envelope"] = deepcopy(returned)
            call["ownKeys"] = list(returned)
            call["detailsOwnKeys"] = list(returned["details"])
            call["resultOwnKeys"] = [list(row) for row in returned["details"].get("results", [])]
            return deepcopy(returned["details"])
        except BaseException as error:
            call["error"] = _error(error)
            raise
        finally:
            finished = event("actual-tool-return", label=label, ownerId=owner_refs[id(owner)])
            call["returnSeq"] = finished["sequence"]
            active_tool = None

    def mutation():
        spec = value["sourceMutation"]
        entered = event("source-mutation-enter", specification=deepcopy(spec))
        if spec is not None and spec["kind"] != "none":
            if spec["kind"] in {"create", "replace"}:
                target = _owned_path(workspace_path, spec["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("x" if spec["kind"] == "create" else "w", encoding="utf8", newline="") as stream:
                    stream.write(spec["text"])
                os.utime(target, ns=(spec["mtimeMs"] * 1_000_000,) * 2)
            elif spec["kind"] == "delete":
                _owned_path(workspace_path, spec["path"]).unlink()
            elif spec["kind"] == "rename":
                target = _owned_path(workspace_path, spec["to"])
                target.parent.mkdir(parents=True, exist_ok=True)
                _owned_path(workspace_path, spec["from"]).rename(target)
            elif spec["kind"] == "touch-same-bytes":
                os.utime(_owned_path(workspace_path, spec["path"]), ns=(spec["mtimeMs"] * 1_000_000,) * 2)
            else:
                raise ValueError("Unknown frozen source mutation")
        finished = event("source-mutation-return")
        raw["sourceMutation"] = {"specification": deepcopy(spec), "enterSeq": entered["sequence"],
                                 "returnSeq": finished["sequence"], "sdkNotification": "actual-source-detection"}

    try:
        for relative, text in value["initialFiles"].items():
            target = _owned_path(workspace_path, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("x", encoding="utf8", newline="") as stream:
                stream.write(text)
            os.utime(target, ns=(value["initialSourceMtimeMs"] * 1_000_000,) * 2)
        sources("initial")
        physical("catalog-before", catalog.path)
        physical("before-first-open")
        phase = "first-owner-acquisition"
        owner = acquire("first")
        physical("after-first-open")
        seed = None
        if value["queries"]["seed"] is not None:
            phase = "seed-query"
            seed = tool_call(owner, "seed", value["queries"]["seed"])
            physical("after-seed")
        phase = "source-mutation"
        mutation()
        sources("afterMutation")
        physical("after-mutation")
        phase = "first-query"
        first = tool_call(owner, "first", value["queries"]["first"])
        phase = "first-close"
        close(owner, "first")
        phase = "after-first-close"
        physical("after-first-close")
        sources("afterFirstClose")
        physical("before-reopened-open")
        phase = "reopened-owner-acquisition"
        reopened_owner = acquire("reopened")
        physical("after-reopened-open")
        phase = "reopened-query"
        reopened = tool_call(reopened_owner, "reopened", value["queries"]["reopened"])
        phase = "final-close"
        close(reopened_owner, "reopened")
        phase = "after-final-close"
        physical("after-final-close")
        sources("afterFinalClose")
        physical("catalog-after", catalog.path)
        # All actual public returns and source bytes are durable before private
        # result encoding, so a codec failure cannot erase the original output.
        for call, returned in pending_searches:
            call.update(_search_return_custody(returned))
        raw["result"] = {"provider": "none", "searches": {"seed": seed, "first": first, "reopened": reopened},
            "sources": {label: raw["sourceStages"][label]["common"] for label in
                        ("initial", "afterMutation", "afterFirstClose", "afterFinalClose")}}
        raw["completed"] = True
        return {"result": raw["result"], "raw": raw}
    except BaseException as error:
        raw["error"] = _error(error)
        raise
    finally:
        phase = "teardown"
        teardown_errors = []
        for owner in owners:
            try:
                if not owner.closed:
                    owner.close()
            except BaseException as error:
                teardown_errors.append({"ownerId": owner_refs[id(owner)], **_error(error)})
        raw["allManagersClosed"] = all(owner.closed for owner in owners)
        raw["implementationBindings"] = [{"module": name, "path": str(Path(module.__file__).resolve()),
            "sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()}
            for name, module in sorted(sys.modules.items()) if name.startswith("memory_core")
            and getattr(module, "__file__", None) and Path(module.__file__).is_file()]
        if teardown_errors:
            raw["teardownErrors"] = teardown_errors
        (directory / "sdk-host-raw.json").write_text(_serialized(raw) + "\n", encoding="utf8")
        if teardown_errors and sys.exc_info()[0] is None:
            raise RuntimeError("An original SDK owner failed close; complete raw custody retained")


def run_query_sync_outcomes_case(value, *, evidence_directory=None):
    """One sanitized original SDK process per invocation; no automatic retry."""
    _literal(value)
    if evidence_directory is not None:
        Path(evidence_directory).mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="sdk-query-sync-", dir=evidence_directory)).resolve()
    request = {"input": value, "directory": str(directory)}
    wire = _serialized(request)
    environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
        "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC", "OPENCLAW_HOME": str(directory),
        "OPENCLAW_STATE_DIR": str(directory / "state")}
    argv = [sys.executable, "-m", "equivalence.query_sync_outcomes_sdk_cli"]
    dispatch = {"kind": "query-sync-outcomes-sdk-dispatch", "input": deepcopy(value),
        "coordinatorPid": os.getpid(), "request": request, "requestJson": wire,
        "requestSha256": hashlib.sha256(wire.encode()).hexdigest(), "argv": argv,
        "environmentKeys": sorted(environment), "startedAtNs": str(time.monotonic_ns())}
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
            destination = Path(evidence_directory) if evidence_directory is not None else directory
            (destination / "python-raw.json").write_text(_serialized([dispatch]) + "\n", encoding="utf8")
            raise RuntimeError("The original SDK query-sync process timed out; full streams retained") from None
    dispatch.update(stdout=stdout, stderr=stderr, exit={"code": child.returncode},
                    finishedAtNs=str(time.monotonic_ns()))
    try:
        dispatch["observation"] = json.loads(stdout)
    except json.JSONDecodeError as error:
        dispatch["stdoutParseError"] = _error(error)
    destination = Path(evidence_directory) if evidence_directory is not None else directory
    (destination / "python-raw.json").write_text(_serialized([dispatch]) + "\n", encoding="utf8")
    if child.returncode or "observation" not in dispatch or "result" not in dispatch["observation"]:
        raise RuntimeError("The actual SDK query-sync process failed; full streams and early public envelopes retained")
    return dispatch["observation"]["result"]
