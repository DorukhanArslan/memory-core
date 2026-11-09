"""Literal multi-owner filesystem/index/recall/checkpoint comparison flows."""
from __future__ import annotations

from copy import deepcopy
from contextlib import ExitStack, closing
from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any
from unittest.mock import patch

from equivalence.get_contract import map_get_fixture_paths
from equivalence.importance_project import _logical_published
from equivalence.search_contract import decode_search_tool_envelope


_NOW = 1_790_000_000_000
_DAY = "memory/2026-09-04.md"
_PROFILE = (
    "One original native host config selects actual agents/workspaces/managers; one shared SDK "
    "MemoryConfig selects actual SubjectMemory workspaces. Common owner labels map native agents "
    "to SDK subjects, while the SDK config keeps its actual main-agent namespace. No public "
    "agentId field is rewritten. Genuine filesystem/index/tool outputs, awaited recall recording "
    "from real candidates and actual daily maintenance checkpoint APIs are observed for every "
    "owner across writes, deletion, owner switches and handle reopen. Provider:none; actual native "
    "manager/index workers; no generated maintenance job, embedding/model or full multi-agent "
    "host-API interchange claim. Native plugin SQLite and SDK JSON/index schemas remain separate."
)
_POLICY = (
    "Complete logical publication rows, discovered files/text, candidates, decoded full tool "
    "envelopes, recall stores and maintenance ledgers retain every field and order. The established "
    "JSON carrier codec validates full wire text against details before decoding; only the exact "
    "owned fixture-base prefix maps to $FIXTURE. Full private SQL, actual namespaces/configs and "
    "original envelopes remain independently recorded. No score tolerance, sorting repair or "
    "fixture-computed isolation decisions. The original ranking config fixes temporal decay on, "
    "regardless of the requested false knob; the SDK follows that actual policy. Native Date-only "
    "control and the SDK temporal_decay module's datetime.now seam share the literal nowMs; "
    "real timers/performance/workers remain unchanged."
)


def build_workspace_isolation_cases() -> list[dict[str, Any]]:
    cases = []
    for name, layout, custom_store in (("explicit-owner-workspaces", "explicit", False),
                                        ("legacy-default-and-nested-owner", "legacy-default", False),
                                        ("shared-config-relative-index-override", "explicit", True)):
        owners = [
            {"agentId": "alice", "subjectId": "alice", "workspace": "subjects/alice" if layout == "explicit" else "subjects"},
            {"agentId": "bob", "subjectId": "bob", "workspace": "subjects/bob"},
        ]
        files = [
            {"agentId": "alice", "path": "MEMORY.md", "text": "Amber alice workspace.\n"},
            {"agentId": "alice", "path": _DAY, "text": "Cobalt alice private project.\n"},
            {"agentId": "bob", "path": "MEMORY.md", "text": "Violet bob workspace.\n"},
            {"agentId": "bob", "path": _DAY, "text": "Saffron bob private project.\n"},
        ]

        def query(identity, owner, text, *, record=False):
            return {"id": identity, "agentId": owner, "query": text, "recordRecall": record}

        def read(identity, owner, path=_DAY):
            return {"id": identity, "agentId": owner, "path": path}

        def ledger(owner, mtime, size):
            return {"agentId": owner, "state": {"version": 1, "files": {
                _DAY: {"mtimeMs": mtime, "size": size, "lastDreamingDayIngested": "2026-09-05"},
            }}}

        steps = [
            {"label": "initial-independent-owners", "syncAgents": ["alice", "bob"],
             "maintenanceWrites": [ledger("alice", _NOW, 28)],
             "queries": [query("alice-own", "alice", "Cobalt", record=True),
                         query("alice-cannot-search-bob", "alice", "Saffron"),
                         query("bob-own", "bob", "Saffron", record=True),
                         query("bob-cannot-search-alice", "bob", "Cobalt")],
             "reads": [read("alice-file", "alice"), read("bob-file", "bob"),
                       read("alice-root", "alice", "MEMORY.md"), read("bob-root", "bob", "MEMORY.md")]},
            {"label": "alice-write-and-bob-checkpoint", "writes": [
                {"agentId": "alice", "path": _DAY, "text": "Juniper alice revised private project.\n"},
             ], "syncAgents": ["alice"], "maintenanceWrites": [ledger("bob", _NOW + 5, 29)],
             "queries": [query("alice-updated", "alice", "Juniper", record=True),
                         query("bob-preserved", "bob", "Saffron", record=True),
                         query("bob-cannot-search-alice-update", "bob", "Juniper")],
             "reads": [read("alice-updated-file", "alice"), read("bob-unchanged-file", "bob")]},
            {"label": "alice-delete-and-all-handles-reopen", "removeFiles": [{"agentId": "alice", "path": _DAY}],
             "syncAgents": ["alice"], "reopenAgents": ["alice", "bob"],
             "queries": [query("alice-deleted", "alice", "Juniper"), query("bob-after-reopen", "bob", "Saffron")],
             "reads": [read("alice-deleted-file", "alice"), read("bob-retained-file", "bob"),
                       read("outside-owner-read", "bob", "../alice/" + _DAY)]},
        ]
        cases.append({"id": "workspace-isolation-" + name, "requirement": "storage.workspace-isolation",
                      "operation": "workspace-isolation-runtime", "covers": ["storage.workspace-isolation.outcomes", "storage.workspace-isolation.boundaries"],
                      "input": {"kind": "flow", "nowMs": _NOW, "config": {"layout": layout,
                                "agents": ["alice", "bob"], "sharedConfigStore": custom_store},
                                "owners": owners, "files": files, "steps": steps},
                      "driverScope": _PROFILE, "normalizationPolicy": _POLICY})
    return cases


def _private_sql(store) -> dict:
    def value(item):
        return {"type": "bytes", "hex": item.hex()} if isinstance(item, bytes) else item

    with closing(store.connect()) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        if any(not name.replace("_", "").isalnum() for name in tables):
            raise ValueError("Unexpected diagnostic SQLite table name")
        return {name: {"columns": [dict(row) for row in db.execute(f'PRAGMA table_info("{name}")')],
                       "rows": [{key: value(item) for key, item in dict(row).items()}
                                for row in db.execute(f'SELECT * FROM "{name}"')]}
                for name in tables}


def run_workspace_isolation(arguments: dict[str, Any], *, evidence_directory: Path | None = None) -> dict:
    from memory_core.config import MemoryConfig
    from memory_core.consolidation.daily_ingestion import (
        normalize_daily_ingestion_state, read_daily_ingestion_state, write_daily_ingestion_state,
    )
    from memory_core.consolidation.recall import record_short_term_recalls
    from memory_core.consolidation.store import read_recall_store, recall_store_path
    from memory_core.flags import FeatureFlags
    from memory_core.live import SubjectMemory
    from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
    from memory_core.tools.get_factory import create_memory_get_tool
    from memory_core.tools.memory_search import MemorySearchToolContext
    from memory_core.tools.search_factory import create_memory_search_tool
    from equivalence.session_contract import _session_error

    value = deepcopy(arguments)
    if evidence_directory is not None:
        evidence_directory = Path(evidence_directory)
        evidence_directory.mkdir(parents=True, exist_ok=True)
    now = value["nowMs"]

    class PairedWallClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(now / 1000, tz)

    with ExitStack() as clock, tempfile.TemporaryDirectory(prefix="sdk-workspace-isolation-", dir=evidence_directory) as temporary:
        clock.enter_context(patch("memory_core.index.temporal_decay.datetime", PairedWallClock))
        root = Path(temporary)
        raw: dict[str, Any] = {"kind": "flow", "fixtureBase": str(root), "input": value,
                               "wallClock": {"target": "memory_core.index.temporal_decay.datetime.now", "nowMs": now},
                               "sharedConfiguration": None, "subjectOpens": [], "writes": [], "removals": [],
                               "ledgerWrites": [], "recallRequests": [], "pythonSearchEnvelopes": [],
                               "pythonGetEnvelopes": [], "snapshots": []}
        shared = MemoryConfig(workspace_dir=root, agent_id="main", session_search=False,
                              store_path=root / "indexes/custom.sqlite" if value["config"].get("sharedConfigStore") else None,
                              flags=FeatureFlags(vector_search=False, text_search=True, mmr=False, temporal_decay=True),
                              search_max_results=200, search_min_score=0)
        raw["sharedConfiguration"] = asdict(shared)
        owners = {owner["agentId"]: owner for owner in value["owners"]}
        subjects = {}

        def owned_path(workspace: Path, relative: str) -> Path:
            path = Path(relative)
            if path.is_absolute() or ".." in relative.replace("\\", "/").split("/"):
                raise ValueError("Literal fixture writes must remain in their owned workspace")
            return workspace / path

        def open_subject(identifier: str, reason: str) -> None:
            owner = owners[identifier]
            workspace = owned_path(root, owner["workspace"])
            subject = SubjectMemory.open(workspace_dir=root, subject_id=owner["subjectId"], config=shared,
                                         subject_path_builder=lambda _root, _subject: workspace,
                                         initialize=False, reindex=False)
            workspace.mkdir(parents=True, exist_ok=True)
            subjects[identifier] = subject
            raw["subjectOpens"].append({"agentId": identifier, "reason": reason, "subjectId": subject.subject_id,
                                        "workspace": str(subject.memory.workspace.root), "config": asdict(subject.memory.config),
                                        "indexDatabasePath": str(subject.memory.store.path)})

        def write(item: dict, label: str) -> None:
            selected = subjects[item["agentId"]].memory.workspace.root
            path = owned_path(selected, item["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item["text"], encoding="utf-8")
            os.utime(path, ns=(now * 1_000_000, now * 1_000_000))
            raw["writes"].append({"label": label, "input": deepcopy(item), "selectedWorkspace": str(selected), "filename": str(path)})

        try:
            for identifier in owners:
                open_subject(identifier, "initial")
            for item in value.get("files", []):
                write(item, "initial")
            steps = []
            for step in value["steps"]:
                for item in step.get("writes", []):
                    write(item, step["label"])
                for item in step.get("removeFiles", []):
                    path = owned_path(subjects[item["agentId"]].memory.workspace.root, item["path"])
                    path.unlink()
                    raw["removals"].append({"label": step["label"], "input": deepcopy(item), "filename": str(path)})
                for identifier in step.get("reopenAgents", []):
                    open_subject(identifier, step["label"])
                for identifier in step.get("syncAgents", []):
                    memory = subjects[identifier].memory
                    memory.store.reindex(memory.workspace)
                for item in step.get("maintenanceWrites", []):
                    workspace = subjects[item["agentId"]].memory.workspace.root
                    write_daily_ingestion_state(workspace, normalize_daily_ingestion_state(item["state"]))
                    raw["ledgerWrites"].append({"label": step["label"], "input": deepcopy(item), "selectedWorkspace": str(workspace)})
                queries = {identifier: [] for identifier in owners}
                reads = {identifier: [] for identifier in owners}
                for query in step.get("queries", []):
                    memory = subjects[query["agentId"]].memory
                    candidates = [hit.to_payload() for hit in memory.store.search(
                        query["query"], max_results=200, min_score=0, sources={"memory"},
                    )]
                    tool = create_memory_search_tool(memory.config, memory.store,
                        context=MemorySearchToolContext(clock=lambda: now), runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
                    envelope = tool.execute(query["id"], {"query": query["query"], "maxResults": 200, "minScore": 0})
                    raw["pythonSearchEnvelopes"].append({"label": step["label"], "input": deepcopy(query),
                                                        "candidates": deepcopy(candidates), "envelope": deepcopy(envelope)})
                    queries[query["agentId"]].append({"id": query["id"], "candidates": candidates,
                                                     "result": decode_search_tool_envelope(envelope)})
                    if query.get("recordRecall"):
                        record_short_term_recalls(config=memory.config, query=query["query"], results=candidates, now_ms=now)
                        raw["recallRequests"].append({"label": step["label"], "agentId": query["agentId"],
                                                     "workspace": str(memory.workspace.root), "query": query["query"],
                                                     "results": deepcopy(candidates), "nowMs": now})
                for read in step.get("reads", []):
                    memory = subjects[read["agentId"]].memory
                    tool = create_memory_get_tool(memory.config)
                    try:
                        envelope = tool.execute(read["id"], {"path": read["path"]})
                        reads[read["agentId"]].append({"id": read["id"], "result": decode_search_tool_envelope(envelope)})
                        raw["pythonGetEnvelopes"].append({"label": step["label"], "input": deepcopy(read), "envelope": deepcopy(envelope)})
                    except Exception as error:
                        detail = _session_error(error)
                        reads[read["agentId"]].append({"id": read["id"], "error": detail})
                        raw["pythonGetEnvelopes"].append({"label": step["label"], "input": deepcopy(read), "error": detail})
                snapshots, public = [], []
                for identifier in owners:
                    memory = subjects[identifier].memory
                    workspace = memory.workspace.root
                    observable = {"agentId": identifier, "workspace": str(workspace),
                                  "files": [{"path": file.rel_path, "text": file.abs_path.read_text(encoding="utf-8")}
                                            for file in memory.workspace.discover_memory_files()],
                                  "published": _logical_published(memory.store),
                                  "indexSources": [{"path": item["path"], "source": item["source"]}
                                                   for item in memory.store.read_published_index()["sources"]],
                                  "queries": queries[identifier], "reads": reads[identifier],
                                  "recallStore": read_recall_store(recall_store_path(workspace), now),
                                  "dailyIngestionState": read_daily_ingestion_state(workspace).to_json()}
                    public.append(observable)
                    state_files = {str(path.relative_to(workspace)): path.read_text(encoding="utf-8")
                                   for path in sorted((workspace / "memory/.dreams").glob("*.json"))}
                    snapshots.append({**deepcopy(observable), "config": asdict(memory.config),
                                      "indexDatabasePath": str(memory.store.path),
                                      "fullSql": _private_sql(memory.store), "stateFiles": state_files})
                raw["snapshots"].append({"label": step["label"], "owners": snapshots})
                steps.append({"label": step["label"], "owners": public})
            result = {"provider": "none", "steps": steps}
            raw["result"] = deepcopy(result)
            return map_get_fixture_paths(result, str(root))
        finally:
            if evidence_directory is not None:
                (evidence_directory / "python-raw.json").write_text(
                    json.dumps([raw], ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n", encoding="utf-8",
                )
