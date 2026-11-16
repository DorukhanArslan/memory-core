"""Observe real session-memory publication, trust and complete recall owners.

The host fixture persists and reads the original transcript tree. Production
capture chooses the visible reset window; this driver never projects events.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from datetime import UTC
import hashlib
import inspect
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from equivalence.embedding_cache_lifecycle_sdk import _failure as _base_failure, _owner, _returned, _sources, _wire
from equivalence.forget_lineage_sdk import _owned, _write
from equivalence.recall_signals_sdk import _capture, _database
from equivalence.search_contract import decode_search_tool_envelope
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.flags import FeatureFlags
from memory_core.index import temporal_decay
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.memory_write_provenance import MemoryWriteProvenanceObserver
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_memory import (
    _publish_new_file, _write_session_memory_file, capture_session_memory_events,
    get_recent_session_projection_from_events, save_session_memory,
)
from memory_core.tools.get_factory import create_memory_get_tool
from memory_core.tools.memory_search import MemorySearchToolContext
from memory_core.tools.search_factory import MemorySearchTool, create_memory_search_tool
from memory_core.workspace import MemoryWorkspace

AUDIT_SQL = (
    "CREATE TABLE reset_boundary_trust_audit (seq INTEGER PRIMARY KEY, "
    "event TEXT NOT NULL, store_key TEXT NOT NULL, old_value TEXT, new_value TEXT)",
    "CREATE TRIGGER reset_boundary_trust_insert AFTER INSERT ON memory_artifact_provenance "
    "BEGIN INSERT INTO reset_boundary_trust_audit(event,store_key,new_value) "
    "VALUES('insert',NEW.store_key,NEW.value); END",
    "CREATE TRIGGER reset_boundary_trust_update AFTER UPDATE ON memory_artifact_provenance "
    "BEGIN INSERT INTO reset_boundary_trust_audit(event,store_key,old_value,new_value) "
    "VALUES('update',NEW.store_key,OLD.value,NEW.value); END",
    "CREATE TRIGGER reset_boundary_trust_delete AFTER DELETE ON memory_artifact_provenance "
    "BEGIN INSERT INTO reset_boundary_trust_audit(event,store_key,old_value) "
    "VALUES('delete',OLD.store_key,OLD.value); END",
)


def _failure(error):
    return {**_base_failure(error), **{key: getattr(error, key)
        for key in ("errno", "strerror", "filename", "filename2") if hasattr(error, key)}}


def _file(path):
    payload, info = path.read_bytes(), path.stat()
    return {"path": str(path), "bytes": {"hex": payload.hex(), "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()},
            "identity": {"device": str(info.st_dev), "inode": str(info.st_ino),
                         "size": info.st_size, "mtimeNs": str(info.st_mtime_ns),
                         "ctimeNs": str(info.st_ctime_ns), "mode": stat.S_IMODE(info.st_mode),
                         "uid": info.st_uid, "gid": info.st_gid}}


class _Owners:
    def __init__(self, root, value):
        self.root, self.value = root, value
        self.now = value["nowMs"]
        self.provenance_reads = []
        self.workspace = root / "workspace"
        self.workspace.mkdir(parents=True)
        self.memory_dir = self.workspace / "memory"
        self.memory_dir.mkdir()
        self.session_directory = root / "host-transcripts"
        self.session_directory.mkdir()
        self.session_paths = {}
        for name, profile in value["sessions"].items():
            path = _owned(self.session_directory, name + ".jsonl")
            path.write_text("".join(json.dumps(event, ensure_ascii=False, allow_nan=False,
                separators=(",", ":")) + "\n" for event in profile["events"]), encoding="utf8")
            self.session_paths[name] = path
        for relative, text in value["files"].items():
            path = _owned(self.workspace, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf8")
        self.database = root / "index.sqlite"
        self.trust = MemoryArtifactProvenanceStore(root / "trust.sqlite")
        self.config = MemoryConfig(
            workspace_dir=self.workspace, store_path=self.database, agent_id=value["agentId"],
            session_search=False, citation_mode="auto", flags=FeatureFlags(vector_search=False),
        )
        self.workspace_owner = MemoryWorkspace(self.workspace, agent_id=value["agentId"])
        self.store = SQLiteMemoryStore(self.config, None, artifact_provenance=self.trust)
        # Public readers create the owner's real schema before observational SQL
        # triggers record its committed reservations and compensating rollbacks.
        initialized = self.trust.list(self.workspace)
        self.schema_initialization_provenance_read = {
            "owner": "MemoryArtifactProvenanceStore.list",
            "arguments": {"workspace_dir": str(self.workspace)}, "returnValue": _returned(initialized),
        }
        with closing(self.trust._connect()) as db:
            for statement in AUDIT_SQL:
                db.execute(statement)
        self.tool_calls = []
        context = MemorySearchToolContext(manager_ms=0, clock=lambda: self.now)
        self.search = create_memory_search_tool(
            self.config, self.store, context=context, agent_session_key=value["sessionKey"],
            runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
        )
        self.get = create_memory_get_tool(self.config, agent_session_key=value["sessionKey"])
        if self.search is None or self.get is None:
            raise RuntimeError("The actual provider-none memory tool factories were unavailable")

    def files(self):
        return {path.relative_to(self.workspace).as_posix(): path.read_bytes().decode("utf8")
                for path in sorted(self.memory_dir.rglob("*.md")) if path.is_file()}

    def read_provenance(self):
        records = self.trust.list(self.workspace)
        self.provenance_reads.append({"owner": "MemoryArtifactProvenanceStore.list",
            "arguments": {"workspace_dir": str(self.workspace)}, "returnValue": _returned(records)})
        return records

    def state(self):
        records = self.read_provenance()
        if len({relative for relative, _record in records}) != len(records):
            raise ValueError("The actual provenance reader returned duplicate paths")
        provenance = {relative: {
            "fileHash": record.file_hash, "originClass": record.origin_class,
            "observedAt": record.observed_at,
            **({"sessionId": record.session_id} if record.session_id is not None else {}),
            **({"sessionKey": record.session_key} if record.session_key is not None else {}),
        } for relative, record in records}
        return {"files": self.files(), "provenance": provenance, "toolCalls": deepcopy(self.tool_calls)}

    def databases(self):
        return {"index": _database(self.database), "trust": _database(self.trust.path)}

    def mode(self):
        info = self.memory_dir.stat()
        return {"path": str(self.memory_dir), "mode": stat.S_IMODE(info.st_mode),
                "uid": info.st_uid, "gid": info.st_gid,
                "processUid": os.getuid(), "effectiveUid": os.geteuid(),
                "processGid": os.getgid(), "effectiveGid": os.getegid()}

    def execute_tool(self, tool, arguments, actual):
        owner = self.search if tool == "memory_search" else self.get
        call = {"tool": tool, "arguments": deepcopy(arguments)}
        actual.setdefault("toolCalls", []).append(call)
        envelope = owner.execute("reset-boundary-" + str(len(self.tool_calls)), arguments)
        call["returnValue"] = _returned(envelope)
        decoded = decode_search_tool_envelope(envelope)
        call["decodedEnvelope"] = deepcopy(decoded)
        receipt = {"tool": tool, "arguments": deepcopy(arguments), "result": decoded["details"]}
        self.tool_calls.append(deepcopy(receipt))
        if tool == "memory_search":
            drain = {"owner": "MemorySearchTool.wait_for_recalls", "arguments": {}}
            call["recallDrain"] = drain
            try:
                returned = self.search.wait_for_recalls()
                drain["apiOutcome"] = {"kind": "return", "returnValue": _returned(returned)}
            except BaseException as error:
                drain["apiOutcome"] = {"kind": "throw", "error": _failure(error)}
                raise
        return envelope

    def invoke(self, operation, actual):
        name = operation["op"]
        if name == "hook":
            profile = self.value["sessions"][operation["session"]]
            path = self.session_paths[operation["session"]]
            before = _file(path)
            # This is a host input reader, not a transcript projection owner.
            text = path.read_text(encoding="utf8")
            events = [json.loads(line) for line in text.split("\n") if line]
            actual["sourceRead"] = {"owner": "Path.read_text/json.loads", "path": str(path),
                "before": before, "after": _file(path), "returnValue": deepcopy(events)}
            actual["owner"] = "save_session_memory"
            arguments = {"workspace_dir": str(self.workspace), "session_key": self.value["sessionKey"],
                         "session_id": profile["sessionId"], "events": events,
                         "source": operation["source"], "now_ms": operation["nowMs"],
                         "timezone": self.value["timezone"]}
            actual["arguments"] = deepcopy(arguments)
            actual["trustOwner"] = {"class": type(self.trust).__qualname__, "path": str(self.trust.path)}
            return save_session_memory(**arguments, artifact_provenance=self.trust)
        if name == "sync":
            actual["owner"] = "SQLiteMemoryStore.reindex"
            actual["arguments"] = {"workspace": str(self.workspace), "force": operation["force"]}
            actual["mtimeWrites"] = []
            for path in sorted(self.memory_dir.rglob("*.md")):
                before = _file(path)
                returned = os.utime(path, ns=(operation["mtimeMs"] * 1_000_000,) * 2)
                actual["mtimeWrites"].append({"owner": "os.utime", "before": before,
                    "arguments": {"path": str(path), "ns": [operation["mtimeMs"] * 1_000_000] * 2},
                    "returnValue": _returned(returned), "after": _file(path)})
            return self.store.reindex(self.workspace_owner, force=operation["force"])
        if name == "search":
            arguments = {"query": operation["query"], "maxResults": operation["maxResults"],
                         "minScore": operation["minScore"]}
            actual.update(owner="MemorySearchTool.execute", arguments=deepcopy(arguments))
            return self.execute_tool("memory_search", arguments, actual)
        if name == "get-all":
            actual.update(owner="MemoryGetTool.execute (all actual artifacts)", arguments=deepcopy(operation))
            return [self.execute_tool("memory_get", {"path": relative, "from": operation["from"],
                        "lines": operation["lines"]}, actual) for relative in self.files()
                    if relative.endswith(".md")]
        if name == "memory-mode":
            actual.update(owner="Path.chmod", arguments={"path": str(self.memory_dir), "mode": operation["mode"]})
            return self.memory_dir.chmod(operation["mode"])
        if name == "trust-failure":
            statement = (operation["fault"]["sdkSql"] if operation["enabled"]
                         else 'DROP TRIGGER "' + operation["fault"]["name"].replace('"', '""') + '"')
            actual.update(owner="sqlite3.Connection.execute", arguments={"databasePath": str(self.trust.path),
                          "statement": statement})
            with closing(self.trust._connect()) as db:
                db.execute(statement)
            return None
        raise ValueError("Unknown frozen session-reset boundary operation")


def _run(value, directory):
    from equivalence.session_reset_boundaries import validate_input

    validate_input(value)
    if value.get("preconditions", {}).get("nonRootPosix") and (os.name != "posix" or os.geteuid() == 0):
        raise RuntimeError("The frozen publication fault requires an actual non-root POSIX fixture host")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    root = directory / "sdk-fixture"
    if root.exists():
        raise ValueError("Session-reset boundaries require a fresh SDK evidence directory")
    original_clock, original_monotonic, original_sleep = time.time_ns, time.monotonic, time.sleep
    original_datetime = temporal_decay.datetime
    ranking_owners = {name: getattr(temporal_decay, name) for name in (
        "calculate_temporal_decay_multiplier", "apply_temporal_decay_to_score",
        "apply_temporal_decay_to_hybrid_results",
    )}
    now = [value["nowMs"]]

    class PhaseDateTime(original_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(now[0] / 1000, tz=tz)

    def wall_clock_read(phase, operation_index=None):
        observed = temporal_decay.datetime.now(tz=UTC)
        return {"phase": phase, "operationIndex": operation_index, "requestedNowMs": now[0],
                "actualNowMs": int(observed.timestamp() * 1000), "returnedIso": observed.isoformat(),
                "datetimeOwner": {"module": temporal_decay.datetime.__module__,
                                  "name": temporal_decay.datetime.__qualname__},
                "nowOwner": {"module": temporal_decay.datetime.now.__module__,
                             "name": temporal_decay.datetime.now.__qualname__},
                "datetimeIsFixture": temporal_decay.datetime is PhaseDateTime,
                "inheritedMethodsUnchanged": {name: inspect.getattr_static(PhaseDateTime, name)
                    is inspect.getattr_static(original_datetime, name)
                    for name in ("fromtimestamp", "timestamp", "isoformat", "__new__", "__sub__")},
                "rankingOwnersUnchanged": {name: getattr(temporal_decay, name) is function
                                           for name, function in ranking_owners.items()}}

    raw = {"kind": "session-reset-boundaries-sdk-raw", "input": deepcopy(value),
           "fixtureRoot": str(root), "workspace": str(root / "workspace"),
           "databasePath": str(root / "index.sqlite"), "trustPath": str(root / "trust.sqlite"),
           "owners": [_owner(function) for function in (
               save_session_memory, capture_session_memory_events, get_recent_session_projection_from_events,
               _write_session_memory_file, _publish_new_file, MemoryWriteProvenanceObserver.write,
               MemoryArtifactProvenanceStore.record_write, MemoryArtifactProvenanceStore.list,
               SQLiteMemoryStore.reindex, create_memory_search_tool, create_memory_get_tool,
               MemorySearchTool.wait_for_recalls)],
           "auditStatements": list(AUDIT_SQL), "clock": {"owner": "time.time_ns", "requestedNowMs": value["nowMs"],
               "clockFunctionReplaced": False, "monotonicUnchanged": True, "sleepUnchanged": True,
               "originalClockRestored": False},
           "wallClock": {"owner": "memory_core.index.temporal_decay.datetime.now",
                         "originalDatetimeOwner": {"module": original_datetime.__module__,
                                                   "name": original_datetime.__qualname__},
                         "readings": [], "originalDatetimeRestored": False},
           "operations": [], "physical": [], "closed": False}
    owners = None
    try:
        with (patch("time.time_ns", lambda: now[0] * 1_000_000),
              patch.object(temporal_decay, "datetime", PhaseDateTime)):
            raw["clock"].update(clockFunctionReplaced=time.time_ns is not original_clock,
                actualNowMs=time.time_ns() // 1_000_000, monotonicUnchanged=time.monotonic is original_monotonic,
                sleepUnchanged=time.sleep is original_sleep)
            raw["wallClock"]["readings"].append(wall_clock_read("initial"))
            owners = _Owners(root, value)
            raw["schemaInitializationProvenanceRead"] = owners.schema_initialization_provenance_read
            raw["orderedProvenanceReads"] = owners.provenance_reads
            raw["hostSources"] = {name: _file(path) for name, path in owners.session_paths.items()}
            initial = owners.state()
            raw["initialState"], raw["initialMode"] = deepcopy(initial), owners.mode()
            raw["initialIndex"] = _wire(owners.store.read_published_index())
            raw["physical"].append(_capture(root, directory, "initial"))
            observations = []
            for operation in value["operations"]:
                now[0] = owners.now = operation["nowMs"]
                raw["wallClock"]["readings"].append(wall_clock_read("operation", len(raw["operations"])))
                actual = {"operation": deepcopy(operation), "sourcesBefore": _sources(owners.workspace),
                          "databasesBefore": owners.databases(), "modeBefore": owners.mode()}
                try:
                    returned = owners.invoke(operation, actual)
                    actual["apiOutcome"] = {"kind": "return", "returnValue": _returned(returned)}
                except BaseException as error:
                    actual["apiOutcome"] = {"kind": "throw", "error": _failure(error)}
                actual.update(sourcesAfter=_sources(owners.workspace), databasesAfter=owners.databases(),
                              modeAfter=owners.mode(), indexState=_wire(owners.store.read_published_index()))
                observed = {"operation": deepcopy(operation), "state": owners.state()}
                actual["observed"] = deepcopy(observed)
                raw["operations"].append(actual)
                observations.append(observed)
                raw["physical"].append(_capture(root, directory, "operation-" + str(len(observations) - 1)))
            raw["closed"] = True
            return {"provider": "none", "before": initial, "observations": observations}
    finally:
        if owners is not None:
            owners.memory_dir.chmod(0o700)
            raw["restoredMode"] = owners.mode()
        raw["clock"]["originalClockRestored"] = time.time_ns is original_clock
        raw["wallClock"]["originalDatetimeRestored"] = temporal_decay.datetime is original_datetime
        raw["wallClock"]["rankingOwnersRestored"] = {
            name: getattr(temporal_decay, name) is function for name, function in ranking_owners.items()
        }
        _write(directory / "python-raw.json", [raw])


def run_session_reset_boundaries(value, *, evidence_directory=None):
    if evidence_directory is not None:
        return _run(value, evidence_directory)
    with TemporaryDirectory(prefix="memory-session-reset-sdk-") as directory:
        return _run(value, directory)
