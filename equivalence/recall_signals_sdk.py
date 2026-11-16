"""Drive real SDK recall owners and retain complete private source/state facts."""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from dataclasses import asdict, is_dataclass
import hashlib
import inspect
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import traceback

from equivalence.forget_lineage_sdk import _origin, _owned, _tombstone, _write
from memory_core.config import MemoryConfig
from memory_core.consolidation.origins import MemoryEntryOriginLedger
from memory_core.consolidation.recall import (
    normalize_memory_path, record_grounded_short_term_candidates, record_short_term_recalls,
)
from memory_core.consolidation.session_ingestion import SessionIngestionCandidate, append_session_corpus_lines
from memory_core.consolidation.store import read_canonical_recall_store, recall_store_path, write_recall_store

TRIGGER_NAME = "recall_signal_origin_failure"
TRIGGER_SQL = (
    "CREATE TRIGGER recall_signal_origin_failure BEFORE INSERT ON memory_entry_origins "
    "BEGIN SELECT RAISE(ABORT,'recall-origin-write-blocked'); END"
)


def _wire(value):
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _wire(asdict(value))
    if isinstance(value, dict):
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_wire(item) for item in value]
    return value


def _failure(error):
    return {"name": type(error).__name__, "module": type(error).__module__, "message": str(error),
            "args": _wire(list(error.args)), "properties": _wire(vars(error)),
            "traceback": "".join(traceback.format_exception(error)),
            **({"code": error.sqlite_errorname, "sqlite_errorname": error.sqlite_errorname}
               if hasattr(error, "sqlite_errorname") else {}),
            **({"sqlite_errorcode": error.sqlite_errorcode} if hasattr(error, "sqlite_errorcode") else {})}


def _owner(function):
    path = Path(inspect.getfile(function)).resolve()
    return {"name": function.__qualname__, "module": function.__module__, "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _database(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        schema = [dict(row) for row in db.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
        def sql_value(value):
            return {"type": "bytes", "hex": value.hex()} if isinstance(value, bytes) else value
        tables = {row["name"]: [{key: sql_value(item[key]) for key in item.keys()}
                               for item in db.execute('SELECT * FROM "' + row["name"].replace('"', '""') + '"')]
                  for row in schema if row["type"] == "table"}
        db.rollback()
        return {"schema": schema, "tables": tables}


def _capture(root, directory, label):
    files, databases = {}, {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError("A recall-signals fixture unexpectedly contains a symlink")
        payload = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        files[relative] = {"hex": payload.hex(), "size": len(payload),
                           "sha256": hashlib.sha256(payload).hexdigest()}
        if payload.startswith(b"SQLite format 3\x00"):
            databases[relative] = _database(path)
    record = {"root": str(root), "files": files, "databases": databases}
    path = directory / f"physical-{label}.json"
    _write(path, record)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _source_witnesses(workspace, results):
    grouped = {}
    for result in results:
        path = normalize_memory_path(result["path"])
        grouped.setdefault(path, []).append(result)
    witnesses = []
    for relative, selected in grouped.items():
        path = _owned(workspace, relative)
        witness = {"path": relative, "absolutePath": str(path), "exists": path.is_file(),
                   "bytes": None, "identity": None, "ranges": []}
        lines = None
        if witness["exists"]:
            stat = path.stat()
            payload = path.read_bytes()
            witness["bytes"] = {"hex": payload.hex(), "size": len(payload),
                                "sha256": hashlib.sha256(payload).hexdigest()}
            witness["identity"] = {"device": str(stat.st_dev), "inode": str(stat.st_ino),
                                   "size": stat.st_size, "mtimeNs": str(stat.st_mtime_ns),
                                   "ctimeNs": str(stat.st_ctime_ns)}
            lines = payload.decode("utf8").replace("\r\n", "\n").split("\n")
        for result in selected:
            start, end = result["startLine"], result["endLine"]
            witness["ranges"].append({"startLine": start, "endLine": end,
                                      "lines": lines[start - 1:end] if lines is not None else None})
        witnesses.append(witness)
    return witnesses


class _Owners:
    def __init__(self, root, value):
        self.root, self.value = root, value
        self.workspace = root / "workspace"
        self.workspace.mkdir(parents=True)
        self.now = value["nowMs"]
        self.ledger = MemoryEntryOriginLedger(lambda agent: root / "agents" / agent / "memory.sqlite")
        self.config = MemoryConfig(workspace_dir=self.workspace)
        self.events = []
        self.calls = []
        self.event_path = root / "host-events.jsonl"

    def seed(self):
        for relative, content in self.value["files"].items():
            path = _owned(self.workspace, relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf8"))
        write_recall_store(recall_store_path(self.workspace), deepcopy(self.value["store"]))
        for row in self.value.get("tombstones", []):
            self.ledger.record_session_tombstones(
                row["agentId"], row["sessionIds"], created_at=self.now)

    def on_event(self, event):
        captured = deepcopy(event)
        self.calls.append({"owner": "on_event", "arguments": [captured], "returnValue": None})
        with self.event_path.open("a", encoding="utf8") as stream:
            stream.write(json.dumps(captured, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        self.events.append(captured)

    def state(self):
        return {"recall": read_canonical_recall_store(recall_store_path(self.workspace), self.now),
                "origins": {"main": [_origin(row) for row in self.ledger.list("main")]},
                "tombstones": {"main": [_tombstone(row) for row in self.ledger.list_session_tombstones("main")]},
                "events": deepcopy(self.events)}

    def schema(self):
        path = self.ledger.database_path("main")
        with closing(sqlite3.connect(path)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            schema = [dict(row) for row in db.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")]
            db.rollback()
            return schema

    def install_trigger(self):
        with closing(self.ledger._open_write("main")) as db:
            db.execute(TRIGGER_SQL)
        return {"name": TRIGGER_NAME, "sql": TRIGGER_SQL, "beforeSchema": self.schema()}

    def drop_trigger(self):
        with closing(sqlite3.connect(self.ledger.database_path("main"))) as db:
            db.execute("DROP TRIGGER " + TRIGGER_NAME)
        return self.schema()

    def arguments(self, operation, results):
        params = {"config": self.config, "query": operation["query"], "now_ms": self.now,
                  "origins": self.ledger}
        for camel, snake in (("dedupeByQueryPerDay", "dedupe_by_query_per_day"),
                             ("dayBucket", "day_bucket"), ("timezone", "timezone")):
            if camel in operation:
                params[snake] = operation[camel]
        params.setdefault("timezone", self.value["timezone"])
        grounded = operation["op"] in {"grounded", "append-grounded"}
        if grounded:
            params["items"] = deepcopy(results)
        else:
            params["results"] = deepcopy(results)
            params["signal_type"] = operation.get("signalType", "recall")
            params["on_event"] = self.on_event
        raw = {key: _wire(item) for key, item in params.items() if key not in {"origins", "on_event"}}
        raw["origins"] = {"owner": "MemoryEntryOriginLedger", "databasePaths": {
            "main": str(self.ledger.database_path("main"))}}
        if not grounded:
            raw["on_event"] = {"owner": "_Owners.on_event", "path": str(self.event_path)}
        return params, raw

    def append(self, operation):
        append = operation["append"]
        candidates = [SessionIngestionCandidate(
            day=row["day"], snippet=row["snippet"], rendered=row["rendered"],
            provenance=deepcopy(row["provenance"]), content_index=row["contentIndex"], hash=row["hash"],
            line_number=row["lineNumber"], scope=row["scope"], state_key=row["stateKey"],
            session_origin=deepcopy(row.get("sessionOrigin"))) for row in append["lines"]]
        arguments = {"workspace_dir": str(self.workspace), "day": append["day"], "lines": _wire(candidates)}
        request = {"path": "memory/.dreams/session-corpus/" + append["day"] + ".txt",
                   "startLine": 1, "endLine": 1}
        before = _source_witnesses(self.workspace, [request])
        produced = append_session_corpus_lines(workspace_dir=self.workspace, day=append["day"], lines=candidates)
        captured = {"owner": "append_session_corpus_lines", "arguments": arguments,
                    "returnValue": deepcopy(produced), "sourcesBefore": before,
                    "sourcesAfter": _source_witnesses(self.workspace, produced)}
        self.calls.append(captured)
        return produced, captured


def _run(value, directory):
    from equivalence.recall_signals import validate_input

    validate_input(value)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    root = directory / "sdk-fixture"
    if root.exists():
        raise ValueError("A recall-signals SDK attempt must use a fresh evidence directory")
    owners = _Owners(root, value)
    owners.seed()
    raw = {"kind": "recall-signals-sdk-raw", "input": deepcopy(value), "fixtureRoot": str(root),
           "workspace": str(owners.workspace), "clock": {"owner": "explicit-nowMs", "nowMs": value["nowMs"]},
           "owners": [_owner(function) for function in (
               record_short_term_recalls, record_grounded_short_term_candidates, append_session_corpus_lines,
               read_canonical_recall_store, write_recall_store, MemoryEntryOriginLedger.record,
               MemoryEntryOriginLedger.list, MemoryEntryOriginLedger.list_session_tombstones)],
           "calls": owners.calls, "operations": [], "physical": [], "closed": False}
    initial = owners.state()
    raw["initialState"] = deepcopy(initial)
    raw["physical"].append(_capture(root, directory, "initial"))
    observations = []
    for index, operation in enumerate(value["operations"]):
        owners.now = operation.get("nowMs", value["nowMs"])
        actual = {"operation": deepcopy(operation)}
        trigger = None
        if operation["op"] == "append-grounded":
            results, actual["producer"] = owners.append(operation)
        else:
            results = deepcopy(operation["items"] if operation["op"] == "grounded" else operation["results"])
        actual["sourcesBefore"] = _source_witnesses(owners.workspace, results)
        if operation.get("failOrigins"):
            trigger = owners.install_trigger()
            actual["trigger"] = trigger
        params, actual["arguments"] = owners.arguments(operation, results)
        function = (record_grounded_short_term_candidates if operation["op"] in {"grounded", "append-grounded"}
                    else record_short_term_recalls)
        call = {"owner": function.__name__, "arguments": deepcopy(actual["arguments"])}
        owners.calls.append(call)
        try:
            result = function(**params)
            call["returnValue"] = result
            actual["returnValue"] = result
            completed = True
        except Exception as error:
            call["error"] = _failure(error)
            actual["error"] = _failure(error)
            completed = False
        actual["sourcesAfter"] = _source_witnesses(owners.workspace, results)
        observed = {"operation": deepcopy(operation), "completed": completed, "state": owners.state()}
        actual["observed"] = deepcopy(observed)
        raw["operations"].append(actual)
        observations.append(observed)
        raw["physical"].append(_capture(root, directory, f"operation-{index}"))
        if trigger is not None:
            trigger["afterDropSchema"] = owners.drop_trigger()
    raw["closed"] = True
    _write(directory / "python-raw.json", [raw])
    return {"before": initial, "observations": observations}


def run_recall_signals(value, evidence_directory=None):
    if evidence_directory is not None:
        return _run(value, evidence_directory)
    with TemporaryDirectory(prefix="memory-recall-signals-sdk-") as directory:
        return _run(value, directory)
