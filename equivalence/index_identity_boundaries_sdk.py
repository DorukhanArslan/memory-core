"""Actual SDK manager/SQLite execution for the frozen identity boundary family.

The adapter prepares one declared source and metadata edit. Production managed
stores own publication, status, provider-knowledge admission and memory_search.
Complete returned values and physical SQL remain separate from the common API.
"""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import closing
from copy import deepcopy
from dataclasses import asdict, fields, is_dataclass
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

from equivalence.host_restart_sdk import _plain, _source
from equivalence.index_identity_boundaries import build_cases, validate_case


ROOT = Path(__file__).resolve().parents[1]


def _literal(value):
    for case in build_cases():
        try:
            return validate_case({**case, "input": value})
        except ValueError:
            pass
    raise ValueError("The SDK identity manager requires an exact frozen input")


def _serialized(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _search_result_custody(value):
    """Encode the SDK's private omitted-annotation enum without dropping fields.

    This applies only to the original store return in custody. The genuine
    public tool envelope/details are captured separately and remain untouched.
    """
    from memory_core.index.hybrid import HYBRID_METADATA_MISSING

    def encode(item):
        if item is HYBRID_METADATA_MISSING:
            return {"$sdkPrivate": "HYBRID_METADATA_MISSING"}
        if is_dataclass(item) and not isinstance(item, type):
            return {field.name: encode(getattr(item, field.name)) for field in fields(item)}
        if isinstance(item, Mapping):
            return {key: encode(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [encode(child) for child in item]
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, bytes):
            return {"blobHex": item.hex()}
        return item

    return encode(value)


def run_index_identity_boundaries_sdk_host(request):
    """Run the original public SDK APIs inside their actual protected child."""
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
        raise ValueError("The SDK identity manager accepts only input and its owned directory")
    value, directory = request["input"], Path(request["directory"])
    case = _literal(value)
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError("An absolute owned SDK identity directory is required")
    implementation = Path(memory_core.__file__).resolve().parents[1]
    if implementation != ROOT:
        raise RuntimeError("The protected identity process imported another SDK tree")
    workspace_path = directory / "workspace"
    workspace_path.mkdir()
    index_path = directory / "index.sqlite"
    catalog = MemorySessionCatalog(directory / "catalog.sqlite",
        agent_id=value["identity"]["agentId"], clock_ms=lambda: value["nowMs"])
    workspace = MemoryWorkspace(workspace_path, agent_id=value["identity"]["agentId"],
        session_catalog=catalog, index_sources=("memory", "sessions"))
    config = MemoryConfig(workspace_path, agent_id=value["identity"]["agentId"],
        store_path=index_path, citation_mode=value["config"]["memory"]["citations"],
        search_max_results=5, search_min_score=0,
        flags=FeatureFlags(vector_search=False, mmr=True, temporal_decay=True))
    source_policy = resolve_memory_search_source_policy(
        value["config"]["memory"]["search"]["sources"],
        remember_across_conversations=False, configured_session_memory=True)
    raw = {"kind": "index-identity-boundaries", "engine": "sdk", "caseId": case["id"],
        "input": deepcopy(value), "pid": os.getpid(), "ppid": os.getppid(),
        "fixtureBase": str(directory), "implementationRoot": str(implementation),
        "events": [], "owners": {}, "statusCalls": [], "snapshots": [], "toolCalls": {},
        "originalSearchCalls": [], "ownerAcquisitions": [], "toolBindings": [],
        "diagnosticStatusCalls": {"inspection": [], "searchOwner": []},
        "requestedConfig": deepcopy(value["config"]), "sourcePolicy": deepcopy(source_policy),
        "sdkProfile": {"runtimeIdentity": "openclaw-compatible", "memoryPublication": "on-search",
                       "publicFactory": "memory_core.tools.search_factory.create_memory_search_tool"},
        "clock": {"owner": "public-tool-clock", "nowMs": value["nowMs"],
                  "monotonicAndTimers": "unmodified"}}
    sequence = 0
    phase, request_label, active_tool = "setup", None, None
    lock = threading.RLock()
    owners = []
    object_refs = {}

    def ref(owner):
        identity = id(owner)
        if identity not in object_refs:
            object_refs[identity] = f"owner-{len(object_refs) + 1}"
        return object_refs[identity]

    def event(name, **fields):
        nonlocal sequence
        with lock:
            sequence += 1
            row = {"event": name, "sequence": sequence, "atNs": str(time.monotonic_ns()),
                   "phase": phase, "threadId": threading.get_ident(), **fields}
            raw["events"].append(row)
            return row

    def physical(label):
        entered = event("physical-sql-read-enter", label=label)
        with closing(sqlite3.connect(index_path.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            schema = [dict(row) for row in db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
            tables = {row["name"]: [_plain(dict(item)) for item in db.execute(
                'SELECT * FROM "' + row["name"].replace('"', '""') + '"')]
                for row in schema if row["type"] == "table"}
            db.rollback()
        returned = event("physical-sql-read-return", label=label)
        state = {"dbPath": str(index_path), "schema": schema, "tables": tables}
        encoded = _serialized(state)
        snapshot = {"label": label, "enterSeq": entered["sequence"],
            "returnSeq": returned["sequence"], "startedAtNs": entered["atNs"],
            "finishedAtNs": returned["atNs"], **state, "serializedJSON": encoded,
            "sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "connection": {"uriMode": "ro", "begin": True, "rollback": True, "closed": True}}
        raw["snapshots"].append(snapshot)
        return snapshot

    def arguments(values):
        observed = {}
        for key, item in values.items():
            if item is None or isinstance(item, (str, int, float, bool, list, tuple, dict)):
                observed[key] = _plain(item)
            elif isinstance(item, (set, frozenset)):
                observed[key] = {"setValues": sorted(item)}
            elif callable(item):
                observed[key] = {"callable": True, "module": item.__module__,
                                 "qualname": item.__qualname__, "objectId": str(id(item))}
            else:
                observed[key] = {"className": type(item).__qualname__, "objectId": str(id(item))}
                if hasattr(item, "aborted"):
                    observed[key]["aborted"] = bool(item.aborted)
        return observed

    def acquire(name):
        entered = event("original-open-enter", role=name, api="ManagedSQLiteMemoryStore")
        owner = ManagedSQLiteMemoryStore(config, workspace,
            runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, memory_publication="on-search")
        owners.append(owner)
        owner_id = ref(owner)
        returned = event("original-open-return", role=name, ownerId=owner_id,
                         api="ManagedSQLiteMemoryStore",
                         returnedIsActualConstructedOwner=type(owner) is ManagedSQLiteMemoryStore)
        raw["ownerAcquisitions"].append({"api": "ManagedSQLiteMemoryStore", "role": name,
            "ownerId": owner_id, "enterSeq": entered["sequence"], "returnSeq": returned["sequence"],
            "startedAtNs": entered["atNs"], "finishedAtNs": returned["atNs"],
            "actualClass": type(owner).__qualname__, "workspaceIsExactOwner": owner._workspace is workspace,
            "config": _plain(asdict(config)), "indexPath": str(owner.path)})
        raw["owners"][name] = {"ownerId": owner_id, "purpose": None,
            "settings": _plain(asdict(config)), "providerInitializedAtAcquisition": owner._provider_initialized,
            "constructorName": owner.__class__.__name__,
            "sdkPolicy": {"memoryPublication": owner._memory_publication,
                          "runtimeIdentity": _plain(asdict(owner._runtime_identity))}}
        original_status, original_search = owner.status, owner.search

        def status_observer(*args, **kwargs):
            entered = event("original-status-enter", ownerId=owner_id, requestLabel=request_label,
                activeTool=active_tool, receiverIsExactObservedOwner=original_status.__self__ is owner,
                providerInitialized=owner._provider_initialized)
            returned = original_status(*args, **kwargs)
            captured = deepcopy(_plain(returned))
            finished = event("original-status-return", ownerId=owner_id, requestLabel=request_label,
                activeTool=active_tool, receiverIsExactObservedOwner=original_status.__self__ is owner,
                providerInitialized=owner._provider_initialized)
            raw["statusCalls"].append({"id": f"status-{len(raw['statusCalls']) + 1}",
                "ownerId": owner_id, "phase": phase, "requestLabel": request_label,
                "activeTool": active_tool, "enterSeq": entered["sequence"],
                "returnSeq": finished["sequence"], "startedAtNs": entered["atNs"],
                "finishedAtNs": finished["atNs"], "receiverIsExactObservedOwner": original_status.__self__ is owner,
                "result": captured})
            return returned

        def search_observer(query, **options):
            entered = event("original-search-enter", ownerId=owner_id, activeTool=active_tool,
                receiverIsExactObservedOwner=original_search.__self__ is owner,
                providerInitialized=owner._provider_initialized)
            call = {"id": f"search-{len(raw['originalSearchCalls']) + 1}", "ownerId": owner_id,
                "phase": phase, "activeTool": active_tool, "query": query,
                "optionKeys": list(options), "options": arguments(options),
                "enterSeq": entered["sequence"], "startedAtNs": entered["atNs"],
                "receiverIsExactObservedOwner": original_search.__self__ is owner}
            raw["originalSearchCalls"].append(call)
            try:
                returned = original_search(query, **options)
                call["result"] = _search_result_custody(returned)
                call["returnType"] = {"module": type(returned).__module__,
                                      "qualname": type(returned).__qualname__}
                if hasattr(returned, "__dict__"):
                    call["returnAttributes"] = _search_result_custody(vars(returned))
                return returned
            except BaseException as error:
                call["error"] = {"name": type(error).__name__, "message": str(error)}
                raise
            finally:
                finished = event("original-search-return", ownerId=owner_id, activeTool=active_tool,
                    receiverIsExactObservedOwner=original_search.__self__ is owner,
                    providerInitialized=owner._provider_initialized)
                call.update(returnSeq=finished["sequence"], finishedAtNs=finished["atNs"])

        owner.status, owner.search = status_observer, search_observer
        return owner

    def status(owner, label):
        nonlocal request_label
        request_label = label
        try:
            value = deepcopy(owner.status())
            call = raw["statusCalls"][-1]
            if call["requestLabel"] != label or value != call["result"]:
                raise RuntimeError("The actual status return was detached from its receipt")
            return value, call["id"]
        finally:
            request_label = None

    def close(owner, label):
        entered = event("original-close-enter", ownerId=ref(owner), label=label)
        returned = owner.close()
        lifecycle = owner.lifecycle_snapshot()
        finished = event("original-close-return", ownerId=ref(owner), label=label,
            returnedNone=returned is None, closed=owner.closed, closing=lifecycle["closing"])
        raw["owners"][label]["close"] = {"enterSeq": entered["sequence"],
            "returnSeq": finished["sequence"], "startedAtNs": entered["atNs"],
            "finishedAtNs": finished["atNs"], "returnedNone": returned is None,
            "closed": owner.closed, "closing": lifecycle["closing"], "lifecycle": lifecycle}

    def tool_call(owner, label, params):
        nonlocal active_tool
        active_tool = label
        context = MemorySearchToolContext(status=owner.status,
            clock=lambda: value["nowMs"], source_policy=source_policy)
        tool = create_memory_search_tool(config, owner, context=context,
                                        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
        if tool is None:
            raise RuntimeError("The real SDK memory_search factory returned no tool")
        binding = event("actual-tool-binding", label=label, ownerId=ref(owner),
            storeIsExactObservedOwner=tool._store is owner)
        raw["toolBindings"].append({"label": label, "ownerId": ref(owner),
            "storeIsExactObservedOwner": tool._store is owner,
            "api": "memory_core.tools.search_factory.create_memory_search_tool(...).execute",
            "configIsExactOwnerConfig": tool._config is config,
            "statusIsObservedOwnerStatus": tool._context.status is owner.status,
            "runtimeIdentityIsExactOwner": tool._runtime_identity is owner._runtime_identity,
            "sequence": binding["sequence"], "definition": tool.definition})
        entered = event("actual-tool-enter", label=label, args=deepcopy(params))
        call = {"label": label, "args": deepcopy(params), "enterSeq": entered["sequence"],
                "startedAtNs": entered["atNs"]}
        raw["toolCalls"][label] = call
        try:
            returned = tool.execute(f"identity-{label}", deepcopy(params))
            envelope_file = directory / f"tool-{label}-envelope.json"
            envelope_bytes = (_serialized(returned) + "\n").encode("utf8")
            envelope_file.write_bytes(envelope_bytes)
            call["envelopeFile"] = {"path": str(envelope_file), "bytes": len(envelope_bytes),
                                    "sha256": hashlib.sha256(envelope_bytes).hexdigest()}
            call["envelope"] = deepcopy(returned)
            if (not isinstance(returned, dict) or not isinstance(returned.get("content"), list)
                    or not returned["content"] or returned["content"][0].get("type") != "text"
                    or json.loads(returned["content"][0]["text"]) != returned.get("details")):
                raise RuntimeError("The real SDK tool text carrier differs from its complete details")
            return deepcopy(returned["details"])
        except BaseException as error:
            call["error"] = {"name": type(error).__name__, "message": str(error)}
            raise
        finally:
            finished = event("actual-tool-return", label=label)
            call.update(returnSeq=finished["sequence"], finishedAtNs=finished["atNs"])
            active_tool = None

    try:
        for relative, content in value["files"].items():
            if relative != "MEMORY.md":
                raise ValueError("Only the exact frozen root source is admitted")
            source_path = workspace_path / relative
            with source_path.open("x", encoding="utf8", newline="") as stream:
                stream.write(content)
            os.utime(source_path, ns=(value["sourceMtimeMs"] * 1_000_000,) * 2)
        raw["sourceBefore"] = _source(workspace_path, "MEMORY.md")
        event("source-fixture-finished")
        raw["catalogBefore"] = _catalog_snapshot(catalog.path)
        phase = "producer-acquisition"
        producer = acquire("producer")
        phase = "seed-publication"
        entered = event("original-publication-enter", ownerId=ref(producer), args={"force": False})
        published = producer.reindex(workspace)
        finished = event("original-publication-return", ownerId=ref(producer), returned=published)
        raw["seedPublication"] = {"ownerId": ref(producer), "args": {"force": False},
            "returned": published, "enterSeq": entered["sequence"], "returnSeq": finished["sequence"]}
        status(producer, "seed-after-publication")
        physical("seed-after-publication")
        phase = "seed-search"
        seed_search = tool_call(producer, "seed", value["seed"]["baselineSearch"])
        if not seed_search.get("results"):
            raise RuntimeError("The real seed memory tool returned no genuine positive control")
        physical("seed-after-search")
        phase = "producer-close"
        close(producer, "producer")
        physical("seed-after-close")
        phase = "metadata-mutation"
        physical("metadata-fixture-before")
        mutation = value["metadataMutation"]
        entered = event("metadata-fixture-enter", mutation=deepcopy(mutation))
        with closing(sqlite3.connect(index_path)) as db:
            db.execute("BEGIN IMMEDIATE")
            before = db.execute("SELECT value FROM memory_index_meta WHERE key=?",
                                ("memory_index_meta_v1",)).fetchone()
            if before is None or not isinstance(before[0], str):
                raise RuntimeError("The actual producer did not retain real metadata")
            receipt = {"specification": deepcopy(mutation), "dbPath": str(index_path),
                "before": before[0], "enterSeq": entered["sequence"], "sql": [], "parameters": []}
            raw["fixtureMutation"] = receipt
            if mutation["kind"] == "delete-metadata-row":
                sql, params = "DELETE FROM memory_index_meta WHERE key=?", (mutation["key"],)
            elif mutation["kind"] == "replace-metadata-serialized":
                sql, params = "UPDATE memory_index_meta SET value=? WHERE key=?", (mutation["value"], mutation["key"])
            elif mutation["kind"] == "merge-metadata-fields":
                meta = json.loads(before[0])
                meta.update(deepcopy(mutation["fields"]))
                sql, params = "UPDATE memory_index_meta SET value=? WHERE key=?", (_serialized(meta), "memory_index_meta_v1")
            elif mutation["kind"] == "none":
                sql, params = None, ()
            else:
                raise ValueError("Unknown frozen metadata fixture")
            if sql is not None:
                db.execute(sql, params)
                receipt["sql"].append(sql)
                receipt["parameters"].append(list(params))
            receipt["sqliteChanges"] = db.total_changes
            after = db.execute("SELECT value FROM memory_index_meta WHERE key=?",
                               ("memory_index_meta_v1",)).fetchone()
            receipt["after"] = after[0] if after else None
            db.commit()
            receipt["committed"] = not db.in_transaction
        receipt["connectionClosed"] = True
        receipt["returnSeq"] = event("metadata-fixture-return")["sequence"]
        physical("metadata-fixture-after")
        phase = "inspection-acquisition"
        physical("inspection-before-open")
        inspection = acquire("inspection")
        physical("inspection-after-open")
        phase = "inspection-read"
        inspection_reads = []
        for number in range(1, 3):
            observed, call_id = status(inspection, f"inspection-{number}")
            inspection_reads.append(observed["custom"]["indexIdentity"])
            raw["diagnosticStatusCalls"]["inspection"].append(call_id)
            physical(f"inspection-after-read-{number}")
        phase = "inspection-close"
        close(inspection, "inspection")
        physical("inspection-after-close")
        phase = "search-owner-acquisition"
        physical("search-owner-before-open")
        search_owner = acquire("searchOwner")
        physical("search-owner-after-open")
        phase = "search-owner-read"
        search_reads = []
        for number in range(1, 3):
            observed, call_id = status(search_owner, f"search-owner-{number}")
            search_reads.append(observed["custom"]["indexIdentity"])
            raw["diagnosticStatusCalls"]["searchOwner"].append(call_id)
            physical(f"search-owner-after-read-{number}")
        phase = "first-query"
        searched = tool_call(search_owner, "query", value["search"])
        phase = "after-query-status"
        after, call_id = status(search_owner, "after-query")
        raw["diagnosticStatusCalls"]["afterQuery"] = call_id
        physical("search-owner-after-query")
        phase = "search-owner-close"
        close(search_owner, "searchOwner")
        physical("search-owner-after-close")
        raw["sourceAfter"] = _source(workspace_path, "MEMORY.md")
        raw["catalogAfter"] = _catalog_snapshot(catalog.path)
        raw["result"] = {"provider": "none", "seedSearch": seed_search,
            "diagnostics": {"inspection": inspection_reads, "searchOwner": search_reads,
                            "afterQuery": after["custom"]["indexIdentity"]},
            "search": searched, "source": raw["sourceAfter"]}
        raw["completed"] = True
        return {"result": raw["result"], "raw": raw}
    except BaseException as error:
        raw["error"] = {"name": type(error).__name__, "message": str(error)}
        raise
    finally:
        phase = "teardown"
        teardown_errors = []
        for owner in owners:
            try:
                if not owner.closed:
                    owner.close()
            except BaseException as error:
                teardown_errors.append({"ownerId": ref(owner), "name": type(error).__name__,
                                        "message": str(error)})
        raw["allManagersClosed"] = all(owner.closed for owner in owners)
        if teardown_errors:
            raw["teardownErrors"] = teardown_errors
        (directory / "sdk-host-raw.json").write_text(_serialized(raw) + "\n", encoding="utf8")
        if teardown_errors and sys.exc_info()[0] is None:
            raise RuntimeError("Actual SDK identity owner close failed; original receipts retained")


def _catalog_snapshot(path):
    from equivalence.host_restart_sdk import _sqlite_snapshot

    return _sqlite_snapshot(path)


def run_index_identity_boundaries_case(value, *, evidence_directory=None):
    """One protected SDK process; retain its exact streams, never retry it."""
    _literal(value)
    if evidence_directory is not None:
        Path(evidence_directory).mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="sdk-identity-boundary-", dir=evidence_directory)).resolve()
    request = {"input": value, "directory": str(directory)}
    wire = _serialized(request)
    environment = {"PATH": str(Path(sys.executable).parent) + os.pathsep + os.defpath,
        "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8", "TZ": "UTC",
        "OPENCLAW_HOME": str(directory), "OPENCLAW_STATE_DIR": str(directory / "state")}
    argv = [sys.executable, "-m", "equivalence.index_identity_boundaries_sdk_cli"]
    dispatch = {"kind": "index-identity-boundaries-sdk-dispatch", "input": deepcopy(value),
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
            (destination / "python-raw.json").write_text(_serialized([dispatch]) + "\n")
            raise RuntimeError("The original SDK identity process timed out; complete streams retained") from None
    dispatch.update(stdout=stdout, stderr=stderr, exit={"code": child.returncode},
                    finishedAtNs=str(time.monotonic_ns()))
    if child.returncode == 0:
        try:
            dispatch["observation"] = json.loads(stdout)
        except json.JSONDecodeError as error:
            dispatch["stdoutParseError"] = {"name": type(error).__name__, "message": str(error)}
    destination = Path(evidence_directory) if evidence_directory is not None else directory
    (destination / "python-raw.json").write_text(_serialized([dispatch]) + "\n", encoding="utf8")
    if child.returncode or "observation" not in dispatch:
        raise RuntimeError("The actual SDK identity process failed; complete streams retained")
    return dispatch["observation"]["result"]
