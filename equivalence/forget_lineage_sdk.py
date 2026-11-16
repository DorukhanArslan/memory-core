"""Actual SDK owners for the six diagnostic forget/lineage inputs.

Fixture setup supplies facts; it never supplies a forget/admission outcome.
Every operation retains complete private files and SQLite schema/rows separately.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
import time
from unittest.mock import patch

from equivalence.forget_lineage_cases import build_cases
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifacts import read_memory_preimages
from memory_core.consolidation.forget import SessionInstance, forget_memory_entries
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger
from memory_core.consolidation.recall import record_grounded_short_term_candidates
from memory_core.consolidation.session_ingestion import (
    SessionCorpusEntry, read_session_ingestion_state, session_exclusion_reason,
    session_ingestion_source_from_corpus,
)
from memory_core.consolidation.store import (
    phase_signal_store_path, read_canonical_phase_signal_store,
    read_canonical_recall_store, recall_store_path,
)
from memory_core.session_catalog import MemorySessionCatalog

STATE_PATHS = {
    "recall": "memory/.dreams/short-term-recall.json",
    "phase": "memory/.dreams/phase-signals.json",
    "preimages": "memory/.dreams/consolidation-preimages.json",
    "ingestion": "memory/.dreams/session-ingestion.json",
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _owned(root, relative):
    path = PurePosixPath(relative)
    if (not relative or path.is_absolute() or ".." in path.parts or str(path) != relative
            or "\\" in relative):
        raise ValueError("A fixture path must be canonical and owned")
    target = root.joinpath(*path.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("A fixture path escaped its exact root")
    return target


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json(value) + "\n", encoding="utf8")


def _origin(row):
    return {"entryKey": row.entry_key, "agentId": row.agent_id, "sessionId": row.session_id,
            "sessionKey": row.session_key, "originClass": row.origin_class, "observedAt": row.observed_at}


def _tombstone(row):
    return {"sessionId": row.session_id, "agentId": row.agent_id,
            "reason": row.reason, "createdAt": row.created_at}


def _sql_value(value):
    return {"type": "bytes", "hex": value.hex()} if isinstance(value, bytes) else value


def _database(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        def rows(query):
            cursor = db.execute(query)
            keys = [column[0] for column in cursor.description]
            return [{key: _sql_value(value) for key, value in zip(keys, row, strict=True)} for row in cursor]
        schema = rows("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")
        return {"schema": schema, "tables": {
            row["name"]: rows('SELECT * FROM "' + row["name"].replace('"', '""') + '"')
            for row in schema if row["type"] == "table"}}


def _capture(root, directory, label):
    """Losslessly retain actual bytes before any logical-state representation."""
    files, databases = {}, {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError("The bounded diagnostic fixture unexpectedly contains a symlink")
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        files[relative] = {"hex": payload.hex(), "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
        if payload.startswith(b"SQLite format 3\x00"):
            databases[relative] = _database(path)
    record = {"root": str(root), "files": files, "databases": databases}
    _write(directory / f"physical-{label}.json", record)
    return {"path": str(directory / f"physical-{label}.json"),
            "sha256": hashlib.sha256((_json(record) + "\n").encode()).hexdigest()}


class _Owners:
    def __init__(self, root, value):
        self.root, self.value = root, value
        self.workspace = root / "workspace"
        self.now = value["nowMs"]
        self.agents = sorted({value["agentId"], *(session["agentId"] for session in value["sessions"]),
                              *(origin["agentId"] for origin in value["origins"])})
        self.ledger = MemoryEntryOriginLedger(lambda agent: root / "agents" / agent / "memory.sqlite")
        self.catalogs = {agent: MemorySessionCatalog(
            root / "agents" / agent / "sessions" / "catalog.sqlite", agent_id=agent,
            clock_ms=lambda: self.now) for agent in self.agents}
        self.config = MemoryConfig(workspace_dir=self.workspace)

    def seed(self):
        for relative, content in self.value["files"].items():
            target = _owned(self.workspace, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf8")
        for name, relative in STATE_PATHS.items():
            if name in self.value:
                state = self.value[name]
                _write(_owned(self.workspace, relative), {"version": 1, "entries": state} if name == "preimages" else state)
        for agent in self.agents:
            origins = [MemoryEntryOrigin(row["entryKey"], row["agentId"], row["sessionId"], row["sessionKey"],
                                         row["originClass"], row["observedAt"])
                       for row in self.value["origins"] if row["agentId"] == agent]
            if origins:
                self.ledger.record(agent, origins)
        for session in self.value["sessions"]:
            catalog = self.catalogs[session["agentId"]]
            entry = {"sessionId": session["sessionId"], "sessionStartedAt": session["createdAt"],
                     "updatedAt": self.now, "delivery": {"kind": "none"}}
            if "hookExternalContentSource" in session:
                entry["hookExternalContentSource"] = session["hookExternalContentSource"]
            catalog.upsert_session(session["sessionKey"], entry)
            events = [{"type": "session", "id": session["sessionId"]},
                      *({"type": "message", "message": message} for message in session["messages"])]
            catalog.replace_events(session["sessionId"], events, updated_at_ms=self.now,
                                   session_key=session["sessionKey"])
            for identity in session.get("participants", []):
                catalog.record_participant(session["sessionKey"], {
                    "identity": identity, "promptedAt": self.now, "sessionAgentId": session["agentId"]})
        self._transcripts()

    def _transcripts(self):
        for catalog in self.catalogs.values():
            for instance in catalog.snapshot().instances:
                snapshot = catalog.read_transcript(instance.session_id, session_key=instance.session_key)
                if snapshot is None:
                    raise RuntimeError("An actual persisted session transcript disappeared")
                path = self.root / "agents" / instance.agent_id / "sessions" / (instance.session_id + ".jsonl")
                path.write_text("".join(_json(event) + "\n" for event in snapshot.events), encoding="utf8")

    def instances(self):
        out = []
        for catalog in self.catalogs.values():
            for row in catalog.list_transcript_instances():
                metadata = row["sourceMetadata"]
                out.append(SessionInstance(
                    agent_id=row["agentId"], session_id=row["sessionId"], session_key=row["sessionKey"],
                    created_at=metadata["createdAt"], hook_external_content_source=metadata["hookExternalContentSource"],
                    channel=metadata["channel"], account_id=metadata["accountId"], chat_type=metadata["chatType"],
                    participants=tuple(item["identity"] for item in row["entry"].get("participants", []))))
        return out

    def corpus_entries(self, agent):
        return [SessionCorpusEntry(
            agent_id=instance.agent_id, session_id=instance.session_id, session_key=instance.session_key,
            session_file=str(self.root / "agents" / agent / "sessions" / (instance.session_id + ".jsonl")),
            transcript_source="sqlite", updated_at_ms=instance.updated_at_ms)
            for instance in self.catalogs[agent].snapshot().instances]

    def state(self):
        files = {path.relative_to(self.workspace).as_posix(): path.read_text(encoding="utf8")
                 for path in sorted(self.workspace.rglob("*")) if path.is_file()
                 and path.relative_to(self.workspace).as_posix() not in STATE_PATHS.values()}
        return {"files": files,
                "recall": read_canonical_recall_store(recall_store_path(self.workspace), self.now),
                "phase": read_canonical_phase_signal_store(phase_signal_store_path(self.workspace), self.now),
                "preimages": read_memory_preimages(self.workspace),
                "ingestion": read_session_ingestion_state(self.workspace).to_json(),
                "origins": {agent: [_origin(row) for row in self.ledger.list(agent)] for agent in self.agents},
                "tombstones": {agent: [_tombstone(row) for row in self.ledger.list_session_tombstones(agent)] for agent in self.agents}}

    def replay(self, operation):
        admission, arguments = [], []
        for agent in operation["agentIds"]:
            for entry in self.corpus_entries(agent):
                source = session_ingestion_source_from_corpus(entry)
                if source is None:
                    raise RuntimeError("A literal interactive session has no actual ingestion source")
                reason = session_exclusion_reason(source, origins=self.ledger)
                admission.append({"agentId": agent, "sessionId": entry.session_id, "reason": reason})
                arguments.append({"source": asdict(source), "returnValue": reason})
        before = read_canonical_recall_store(recall_store_path(self.workspace), self.now)
        backfill = operation["backfill"]
        result = record_grounded_short_term_candidates(
            config=self.config, origins=self.ledger, query="__dreaming_session_backfill__:" + backfill["day"],
            items=[{**deepcopy(item), "dayBucket": backfill["day"]} for item in backfill["results"]],
            now_ms=self.now, dedupe_by_query_per_day=True, timezone=self.value["timezone"])
        after = read_canonical_recall_store(recall_store_path(self.workspace), self.now)
        return {"admission": admission, "backfill": {"returnValue": {"type": "number", "value": result},
                "beforeCount": len(before["entries"]), "afterCount": len(after["entries"])}}, {
                    "admission": arguments, "backfill": {"input": deepcopy(backfill), "returnValue": result}}


    def admission(self, operation):
        decisions, arguments = [], []
        for agent in operation["agentIds"]:
            for entry in self.corpus_entries(agent):
                source = session_ingestion_source_from_corpus(entry)
                if source is None:
                    raise RuntimeError("A persisted interactive session has no actual ingestion source")
                reason = session_exclusion_reason(source, origins=self.ledger)
                decisions.append({"agentId": agent, "sessionId": entry.session_id, "reason": reason})
                arguments.append({"source": asdict(source), "returnValue": reason})
        return {"admission": decisions}, arguments


def _run_forget_lineage(value, evidence_directory):
    directory = Path(evidence_directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    root = directory / "sdk-fixture"
    root.mkdir()
    observations, raw = [], {"input": deepcopy(value), "fixtureRoot": str(root), "physical": [], "operations": []}
    original_clock = time.time
    # The common fixture explicitly controls the host wall clock as well as now_ms.
    with patch("memory_core.consolidation.origins.time.time", return_value=value["nowMs"] / 1000):
        raw["clock"] = {"requestedNowMs": value["nowMs"], "actualNowMs": time.time() * 1000,
                        "clockFunctionReplaced": time.time is not original_clock}
        owners = _Owners(root, value)
        owners.seed()
        raw["physical"].append(_capture(root, directory, "initial"))
        raw["initialState"] = owners.state()
        for number, operation in enumerate(value["operations"]):
            observed = {"operation": deepcopy(operation), "error": None, "report": None, "replay": None}
            private = {"operation": deepcopy(operation)}
            try:
                if operation["op"] == "forget":
                    selectors = {key: operation[key] for key in ("sessionIds", "hookSources", "participants", "since") if key in operation}
                    private["instances"] = [asdict(instance) for instance in owners.instances()]
                    observed["report"] = forget_memory_entries(
                        config=owners.config, agent_id=value["agentId"], origins=owners.ledger,
                        session_ids=selectors.get("sessionIds"), hook_sources=selectors.get("hookSources"),
                        participants=selectors.get("participants"), since=selectors.get("since"),
                        instances=owners.instances(), corpus_entries=owners.corpus_entries,
                        dry_run=operation.get("dryRun", False), now_ms=value["nowMs"]).to_json()
                elif operation["op"] == "reopen":
                    owners = _Owners(root, value)
                elif operation["op"] == "replay":
                    observed["replay"], private["replay"] = owners.replay(operation)
                elif operation["op"] == "admission":
                    observed["replay"], private["admission"] = owners.admission(operation)
                else:
                    raise ValueError("Unknown frozen diagnostic operation")
            except Exception as error:
                observed["error"] = {"name": type(error).__name__, "message": str(error)}
                private["error"] = deepcopy(observed["error"])
            observed["state"] = owners.state()
            observations.append(observed)
            private["observed"] = deepcopy(observed)
            raw["operations"].append(private)
            raw["physical"].append(_capture(root, directory, str(number)))
            _write(directory / "python-raw.json", raw)
    raw["clock"]["originalClockRestored"] = time.time is original_clock
    _write(directory / "python-raw.json", raw)
    return {"kind": "forget-lineage-tombstones", "provider": "none",
            "acceptancePointsAwarded": 0, "observations": observations}


def run_forget_lineage(value, evidence_directory):
    """Preserve the original exact-six entry point and diagnostic behavior."""
    if not any(value == case["input"] for case in build_cases()):
        raise ValueError("The diagnostic requires one exact common six-case input")
    return _run_forget_lineage(value, evidence_directory)


def run_forget_boundaries(value, evidence_directory):
    """Execute only the independently frozen admission boundary input."""
    from equivalence.forget_boundaries import validate_input

    validate_input(value)
    return _run_forget_lineage(value, evidence_directory)
