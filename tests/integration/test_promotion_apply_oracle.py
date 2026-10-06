"""Oracle tests of the apply half of the deep phase against the real OpenClaw v2026.9.6 code.

``applyPromotionScenarios`` (scripts/openclaw_oracle_runner.ts) seeds workspaces, the recall store
and the origins ledger, then runs the real ``applyShortTermPromotions`` for each scenario in one
process. Python replays the same fixtures through ``run_short_term_promotion`` (host-ranked
``candidates``) and must produce the same:

- ``rejectedCandidates`` (candidate, category, reason) and the applied candidates;
- ``memory.promotion.applied`` host events (the stored, normalized form), also through the host
  callback;
- MEMORY.md, DREAMS.md and recall-store ``promotedAt`` marks;
- origins ledger rows (a real SQLite database on both sides) after reserve and prune;
- the order of the sidecar lock and the MEMORY.md / DREAMS.md writes;
- the file-lock contract (name, payload, errors) of the second lock, through ``fileLockProbe``;
- ``recordMemoryEntryOrigins`` / ``reserveMemoryEntryOrigins`` / ``pruneMemoryEntryOrigins`` /
  ``storeMemoryPreimage`` rotation through ``originsLedger``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.config import MemoryConfig
from memory_core.consolidation import DeepConsolidation, LlmConsolidationOptions
from memory_core.consolidation.artifacts import read_memory_preimages, store_memory_preimage
from memory_core.consolidation.file_lock import (
    FileLockError,
    FileLockOptions,
    resolve_memory_promotion_lock_target,
    with_file_lock,
)
from memory_core.consolidation.llm_consolidation import ConsolidationRequest
from memory_core.consolidation.origins import (
    MemoryEntryOrigin,
    MemoryEntryOriginLedger,
    prune_memory_entry_origins,
    reserve_memory_entry_origins,
)
from memory_core.consolidation.promotion import PromotionCandidate, run_short_term_promotion
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

NOW_MS = 1779811200000  # 2026-05-26T16:00:00Z
TZ = "Europe/Istanbul"
TEST_AGENT = "memory-core-test"
FACTS = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota", "Kappa", "Lambda", "Mu"]
DAILY_PATH = "memory/2026-05-08.md"
LONG_DIR = "/".join(["a" * 100, "b" * 100, "c" * 100])
LONG_PATH = f"memory/{LONG_DIR}/2026-05-09.md"
PRIOR_KEY = "memory:memory/2026-05-01.md:3:3"
EXISTING = "# Memory\n\n- Existing global fact.\n"


def _oracle() -> OpenClawOracle:
    return OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=240)


def daily_text(title: str = "2026-05-08") -> str:
    return f"# {title}\n\n" + "".join(f"- {name} fact {index}.\n" for index, name in enumerate(FACTS, 1))


def snippet_of(line: int) -> str:
    return f"- {FACTS[line - 3]} fact {line - 2}."


def key_of(line: int, path: str = DAILY_PATH) -> str:
    return f"memory:{path}:{line}:{line}"


def store_entry(line: int, path: str = DAILY_PATH, **over: Any) -> dict[str, Any]:
    entry = {
        "key": key_of(line, path),
        "path": path,
        "startLine": line,
        "endLine": line,
        "source": "memory",
        "snippet": snippet_of(line),
        "recallCount": 4,
        "dailyCount": 0,
        "groundedCount": 0,
        "totalScore": 3.6,
        "maxScore": 1.0,
        "firstRecalledAt": "2026-05-20T16:00:00.000Z",
        "lastRecalledAt": "2026-05-25T16:00:00.000Z",
        "queryHashes": ["a1", "a2", "a3"],
        "userQueryHashes": ["a1", "a2", "a3"],
        "recallDays": ["2026-05-21", "2026-05-22", "2026-05-23"],
        "conceptTags": [],
        "provenance": {"originClass": "agent", "sessionKind": "unknown", "observedAt": 1},
    }
    entry.update(over)
    return {key: value for key, value in entry.items() if value is not None}


def candidate_of(line: int, path: str = DAILY_PATH, **over: Any) -> dict[str, Any]:
    candidate = {
        "key": key_of(line, path),
        "path": path,
        "startLine": line,
        "endLine": line,
        "source": "memory",
        "snippet": snippet_of(line),
        "recallCount": 4,
        "dailyCount": 0,
        "groundedCount": 0,
        "signalCount": 4,
        "avgScore": 0.9,
        "maxScore": 1,
        "uniqueQueries": 3,
        "firstRecalledAt": "2026-05-20T16:00:00.000Z",
        "lastRecalledAt": "2026-05-25T16:00:00.000Z",
        "ageDays": 1,
        "score": 0.9 - line / 1000,
        "recallDays": ["2026-05-21", "2026-05-22", "2026-05-23"],
        "conceptTags": [],
        "components": {
            "frequency": 0.5,
            "relevance": 0.9,
            "diversity": 0.6,
            "recency": 0.9,
            "consolidation": 0.5,
            "conceptual": 0,
        },
        "provenance": {"originClass": "agent", "sessionKind": "unknown", "observedAt": 1},
    }
    candidate.update(over)
    return {key: value for key, value in candidate.items() if value is not None}


def reply(*operations: tuple[str, str, list[str]]) -> str:
    return json.dumps(
        {
            "operations": [
                {"candidateKey": key, "action": action, "priorEntries": prior}
                for key, action, prior in operations
            ]
        }
    )


def origin_row(entry_key: str, session: str, agent: str = TEST_AGENT, klass: str = "owner") -> dict[str, Any]:
    return {
        "entryKey": entry_key,
        "agentId": agent,
        "sessionId": session,
        "sessionKey": f"agent:{agent}:{session}",
        "originClass": klass,
        "observedAt": 1000,
    }


def _scenarios() -> dict[str, dict[str, Any]]:
    both = {"limit": 20, "minScore": 0.75, "minRecallCount": 3, "minUniqueQueries": 3, "maxAgeDays": 30}
    prior_memory = (
        "# Memory\n\n"
        f"<!-- openclaw-memory-promotion:{PRIOR_KEY} -->\n- Alpha fact 1.\n"
        "- Existing global fact.\n"
    )
    merge_reply = reply((key_of(3), "merged", ["- Alpha fact 1."]))
    return {
        "applied_two_and_event": {
            "entries": [store_entry(3), store_entry(4)],
            "candidates": [candidate_of(3), candidate_of(4)],
            **both,
        },
        "reconciled_existing_marker": {
            "memory": f"# Memory\n\n<!-- openclaw-memory-promotion:{key_of(3)} -->\n- Alpha fact 1.\n",
            "entries": [store_entry(3), store_entry(4)],
            "candidates": [candidate_of(3), candidate_of(4)],
            **both,
        },
        "origin_untrusted_and_system": {
            "entries": [
                store_entry(3, provenance={"originClass": "untrusted", "sessionKind": "unknown", "observedAt": 1}),
                store_entry(4, provenance={"originClass": "system", "sessionKind": "unknown", "observedAt": 1}),
                store_entry(5),
            ],
            "candidates": [candidate_of(3), candidate_of(4), candidate_of(5)],
            **both,
        },
        "origin_authoritative_from_store": {
            # The candidate claims an agent origin; the store (authoritative) says system.
            "entries": [
                store_entry(3, provenance={"originClass": "system", "sessionKind": "unknown", "observedAt": 1}),
                store_entry(4, provenance=None),
            ],
            "candidates": [candidate_of(3), candidate_of(4)],
            **both,
        },
        "thresholds": {
            "entries": [store_entry(line) for line in range(3, 9)],
            "candidates": [
                candidate_of(3, score=0.5),
                candidate_of(4, signalCount=1),
                candidate_of(5, uniqueQueries=1),
                candidate_of(6, ageDays=40.25),
                candidate_of(7, score=0.7449999),
                candidate_of(8),
            ],
            **both,
        },
        "thresholds_fractional_min_score": {
            "entries": [store_entry(3)],
            "candidates": [candidate_of(3, score=0.61)],
            **{**both, "minScore": 0.8},
        },
        "already_promoted": {
            "entries": [store_entry(3, promotedAt="2026-05-25T00:00:00.000Z"), store_entry(4)],
            "candidates": [candidate_of(3), candidate_of(4, promotedAt="2026-05-24T00:00:00.000Z")],
            **both,
        },
        "contamination": {
            # readStore drops the contaminated row, so the candidate's own snippet is judged.
            "entries": [
                store_entry(3, snippet="<!-- openclaw-memory-promotion:abc --> - Alpha fact 1."),
                store_entry(4),
            ],
            "candidates": [
                candidate_of(3, snippet="<!-- openclaw-memory-promotion:abc --> - Alpha fact 1."),
                candidate_of(4),
            ],
            **both,
        },
        "contaminated_row_does_not_hide_clean_candidate": {
            "entries": [store_entry(3, snippet="<!-- openclaw-memory-promotion:abc --> - Alpha fact 1.")],
            "candidates": [candidate_of(3)],
            **both,
        },
        "selection_limit": {
            "entries": [store_entry(line) for line in (3, 4, 5)],
            "candidates": [candidate_of(3), candidate_of(4), candidate_of(5)],
            **{**both, "limit": 1},
        },
        "limit_zero": {
            "entries": [store_entry(3), store_entry(4)],
            "candidates": [candidate_of(3), candidate_of(4)],
            **{**both, "limit": 0},
        },
        "source_rehydration": {
            "entries": [
                store_entry(3, snippet="- Text that is no longer in the daily note."),
                store_entry(4, path="memory/2026-05-09.md", startLine=3, endLine=3),
                store_entry(5),
            ],
            "candidates": [
                candidate_of(3, snippet="- Text that is no longer in the daily note."),
                candidate_of(4, path="memory/2026-05-09.md"),
                candidate_of(5),
            ],
            **both,
        },
        "memory_budget_deferred": {
            "memory": "# Memory\n\n" + "kept entry text. " * 40 + "\n",
            "entries": [store_entry(3), store_entry(4)],
            "candidates": [candidate_of(3), candidate_of(4)],
            **both,
            "memoryFileMaxChars": 300,
        },
        "consolidation_filter_without_model": {
            # Any consolidation option turns the origin/session filter on: no store entry, no
            # provenance and a session-derived path are all rejected or dropped.
            "consolidation": {"noSubagent": True},
            "entries": [store_entry(3, provenance=None), store_entry(4)],
            "candidates": [candidate_of(3), candidate_of(4), candidate_of(5)],
            **both,
        },
        "consolidation_session_path": {
            "consolidation": {"noSubagent": True},
            "files": {"memory/.dreams/session-corpus/2026-05-08.md": daily_text("sessions")},
            "entries": [
                store_entry(
                    3,
                    path="memory/.dreams/session-corpus/2026-05-08.md",
                    provenance={"originClass": "agent", "sessionKind": "cron", "observedAt": 1},
                ),
                store_entry(
                    4,
                    path="memory/.dreams/session-corpus/2026-05-08.md",
                    provenance={"originClass": "owner", "sessionKind": "interactive", "observedAt": 1},
                ),
            ],
            "candidates": [
                candidate_of(3, path="memory/.dreams/session-corpus/2026-05-08.md"),
                candidate_of(4, path="memory/.dreams/session-corpus/2026-05-08.md"),
            ],
            **both,
        },
        "candidate_changed_source_mutated": {
            "memory": EXISTING,
            "consolidation": {
                "replies": [reply((key_of(3), "added", []))],
                "mutateDuringCall": [{"path": DAILY_PATH, "content": "- Appended elsewhere.\n", "append": True}],
            },
            "entries": [store_entry(3)],
            "candidates": [candidate_of(3)],
            **both,
        },
        "direct_candidate_missing_from_store": {
            "entries": [store_entry(4)],
            "candidates": [candidate_of(3), candidate_of(4)],
            **both,
        },
        "event_truncation_long_paths": {
            "files": {LONG_PATH: daily_text("2026-05-09")},
            "entries": [store_entry(line, LONG_PATH) for line in range(3, 15)],
            "candidates": [candidate_of(line, LONG_PATH) for line in range(3, 15)],
            **both,
        },
        "consolidated_lock_and_dreams_order": {
            "memory": EXISTING,
            "agent": True,
            "consolidation": {"replies": [reply((key_of(3), "added", []))]},
            "entries": [store_entry(3)],
            "candidates": [candidate_of(3)],
            **both,
        },
        "append_lock_order_with_agent": {
            "memory": EXISTING,
            "agent": True,
            "entries": [store_entry(3)],
            "candidates": [candidate_of(3)],
            **both,
        },
        "origins_merge_union_and_prune": {
            "memory": prior_memory,
            "workspaceAgentIds": ["sibling"],
            "dreams": "# Diary\n\n<!-- openclaw-memory-promotion:keep-in-diary -->\n",
            "consolidation": {"replies": [merge_reply]},
            "seedOrigins": [
                origin_row(PRIOR_KEY, "session-1"),
                origin_row(key_of(3), "session-2", klass="agent"),
                origin_row(PRIOR_KEY, "session-3", agent="sibling"),
                origin_row("keep-in-diary", "session-4"),
                origin_row("keep-in-diary", "session-5", agent="sibling"),
                origin_row("unrelated", "session-6"),
            ],
            "entries": [store_entry(3)],
            "candidates": [candidate_of(3)],
            **both,
        },
        "origins_prune_keeps_sibling_indexed_key": {
            "memory": prior_memory,
            "workspaceAgentIds": ["sibling"],
            "consolidation": {"replies": [merge_reply]},
            "seedOrigins": [
                origin_row(PRIOR_KEY, "session-1"),
                origin_row(PRIOR_KEY, "session-3", agent="sibling"),
            ],
            "seedIndexChunks": [
                {"agentId": "sibling", "text": f"<!-- openclaw-memory-promotion:{PRIOR_KEY} -->\n- Alpha fact 1."}
            ],
            "entries": [store_entry(3)],
            "candidates": [candidate_of(3)],
            **both,
        },
        "origins_skipped_rewrite_rolls_back": {
            "memory": prior_memory,
            "consolidation": {
                "replies": [merge_reply],
                "mutateDuringCall": [{"path": "MEMORY.md", "content": "\n- Added by someone else.\n", "append": True}],
            },
            "seedOrigins": [origin_row(PRIOR_KEY, "session-1")],
            "entries": [store_entry(3)],
            "candidates": [candidate_of(3)],
            **both,
        },
        "append_prunes_without_consolidation": {
            "memory": prior_memory,
            "agent": True,
            "seedOrigins": [origin_row(PRIOR_KEY, "session-1"), origin_row(key_of(3), "session-2")],
            "entries": [store_entry(3), store_entry(4)],
            "candidates": [candidate_of(3)],
            **both,
        },
    }


# --- running one scenario on both sides --------------------------------------------------------


class _Messages(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        (self.warnings if record.levelno >= logging.WARNING else self.infos).append(record.getMessage())


def _seed(workspace: Path, scenario: dict[str, Any]) -> None:
    files = {DAILY_PATH: daily_text(), **scenario.get("files", {})}
    for rel, text in files.items():
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    if scenario.get("memory") is not None:
        (workspace / "MEMORY.md").write_text(scenario["memory"], encoding="utf-8")
    if scenario.get("dreams") is not None:
        (workspace / "DREAMS.md").write_text(scenario["dreams"], encoding="utf-8")
    store = {
        "version": 1,
        "updatedAt": "2026-05-25T16:00:00.000Z",
        "entries": {entry["key"]: entry for entry in scenario["entries"]},
    }
    path = workspace / "memory" / ".dreams" / "short-term-recall.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def _ts_payload(scenario: dict[str, Any], workspace: Path, name: str) -> dict[str, Any]:
    keys = (
        "candidates", "limit", "minScore", "minRecallCount", "minUniqueQueries", "maxAgeDays",
        "memoryFileMaxChars", "workspaceAgentIds", "seedOrigins", "seedIndexChunks", "consolidation",
        "agent",
    )  # fmt: skip
    return {
        "name": name,
        "workspaceDir": str(workspace),
        "nowMs": NOW_MS,
        "timezone": TZ,
        **{key: scenario[key] for key in keys if key in scenario},
    }


class _Timeline:
    """Records the lock sidecar, MEMORY.md and DREAMS.md writes of a Python run (like the runner's fs hook)."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    def lock(self, event: str, _path: Path) -> None:
        self.entries.append("lock:acquire" if event == "acquired" else "lock:release")

    def target(self, path: Any) -> None:
        name = Path(str(path)).name
        if name == "MEMORY.md":
            self.entries.append("memory:write")
        elif name in ("DREAMS.md", "dreams.md"):
            self.entries.append("dreams:write")


def _dedupe(entries: list[str]) -> list[str]:
    return [item for index, item in enumerate(entries) if index == 0 or entries[index - 1] != item]


def _run_python(scenario: dict[str, Any], workspace: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root = workspace.parent
    config = MemoryConfig(workspace_dir=workspace, store_path=root / f"{workspace.name}.sqlite")
    ledger = MemoryEntryOriginLedger(lambda agent: root / "agents" / f"{agent}.sqlite")
    for seed in scenario.get("seedOrigins", []):
        ledger.record(seed["agentId"], [_origin(seed)])
    for seed in scenario.get("seedIndexChunks", []):
        _insert_index_chunk(ledger.database_path(seed["agentId"]), seed["text"])
    timeline = _Timeline()
    real_replace = os.replace
    real_write_text = Path.write_text

    def replace(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
        timeline.target(dst)
        real_replace(src, dst, *args, **kwargs)

    def write_text(self: Path, *args: Any, **kwargs: Any) -> int:
        timeline.target(self)
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(Path, "write_text", write_text)

    messages = _Messages()
    logger = logging.getLogger(f"promotion-apply-oracle.{workspace.name}")
    logger.handlers = [messages]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    calls: list[ConsolidationRequest] = []
    deep = None
    consolidation = scenario.get("consolidation")
    if consolidation is not None:
        replies = list(consolidation.get("replies", []))

        def model(request: ConsolidationRequest) -> Any:
            calls.append(request)
            for mutation in consolidation.get("mutateDuringCall", []):
                target = workspace / mutation["path"]
                if mutation.get("append"):
                    with target.open("a", encoding="utf-8") as handle:
                        handle.write(mutation["content"])
                else:
                    target.write_text(mutation["content"], encoding="utf-8")
            item = replies[len(calls) - 1]
            if isinstance(item, dict) and "throw" in item:
                raise RuntimeError(item["throw"])
            return item

        deep = DeepConsolidation(
            model=None if consolidation.get("noSubagent") else model,
            options=LlmConsolidationOptions(enabled=not consolidation.get("noSubagent")),
            logger=logger,
        )
    use_agent = bool(consolidation is not None or scenario.get("agent"))
    events: list[dict[str, Any]] = []
    run = run_short_term_promotion(
        config=config,
        store=SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8)),
        now_ms=NOW_MS,
        timezone=TZ,
        limit=scenario["limit"],
        min_score=scenario["minScore"],
        min_recall_count=scenario["minRecallCount"],
        min_unique_queries=scenario["minUniqueQueries"],
        max_age_days=scenario["maxAgeDays"],
        memory_file_max_chars=scenario.get("memoryFileMaxChars", 50_000),
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
        consolidation=deep,
        candidates=[PromotionCandidate.from_json(item) for item in scenario["candidates"]],
        agent_id=TEST_AGENT if use_agent else None,
        workspace_agent_ids=scenario.get("workspaceAgentIds", ()),
        origins=ledger,
        state_dir=root / "state",
        on_event=events.append,
        lock_observer=timeline.lock,
    )
    agents = [TEST_AGENT, *scenario.get("workspaceAgentIds", [])]
    return {
        "run": run,
        "events": events,
        "origins": {agent: [_origin_json(item) for item in ledger.list(agent)] for agent in agents},
        "calls": calls,
        "warnings": messages.warnings,
        "infos": messages.infos,
        "timeline": _dedupe(timeline.entries),
    }


def _origin(raw: dict[str, Any]) -> MemoryEntryOrigin:
    return MemoryEntryOrigin(
        raw["entryKey"], raw["agentId"], raw["sessionId"], raw["sessionKey"], raw["originClass"], raw["observedAt"]
    )


def _origin_json(origin: MemoryEntryOrigin) -> dict[str, Any]:
    return {
        "entryKey": origin.entry_key,
        "agentId": origin.agent_id,
        "sessionId": origin.session_id,
        "sessionKey": origin.session_key,
        "originClass": origin.origin_class,
        "observedAt": origin.observed_at,
    }


def _insert_index_chunk(db_path: Path, text: str) -> None:
    import sqlite3

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS memory_index_chunks (id TEXT, source TEXT, text TEXT)")
        db.execute("INSERT INTO memory_index_chunks VALUES (?, 'memory', ?)", (os.urandom(4).hex(), text))


@pytest.fixture(scope="module")
def _ts_results(tmp_path_factory):
    """Every scenario through the real TS apply in one oracle process."""
    root = tmp_path_factory.mktemp("promotion-apply-ts")
    scenarios = _scenarios()
    payloads = []
    for name, scenario in scenarios.items():
        workspace = root / f"ts-{name}"
        workspace.mkdir()
        _seed(workspace, scenario)
        payloads.append(_ts_payload(scenario, workspace, name))
    response = _oracle().run({"operation": "applyPromotionScenarios", "promotionScenarios": payloads})
    assert response["ok"] is True
    results = {item["name"]: item for item in response["result"]["scenarios"]}
    return {name: (results[name], root / f"ts-{name}") for name in scenarios}


def _events_at(events: list[dict[str, Any]], workspace: Path) -> list[dict[str, Any]]:
    """The events with the workspace directory (which differs between the two runs) made symbolic."""
    return [
        {**event, "memoryPath": event["memoryPath"].replace(str(workspace), "<workspace>")}
        for event in events
    ]


def _file(workspace: Path, name: str) -> str:
    path = workspace / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _rejection_json(item: Any) -> dict[str, Any]:
    candidate = item.candidate
    return {
        "key": candidate.key,
        "path": candidate.path,
        "startLine": candidate.start_line,
        "endLine": candidate.end_line,
        "snippet": candidate.snippet,
        "provenance": candidate.provenance,
        "category": item.category,
        "reason": item.reason,
    }


def _ts_rejection_json(item: dict[str, Any]) -> dict[str, Any]:
    candidate = item["candidate"]
    return {
        "key": candidate["key"],
        "path": candidate["path"],
        "startLine": candidate["startLine"],
        "endLine": candidate["endLine"],
        "snippet": candidate["snippet"],
        "provenance": candidate.get("provenance"),
        "category": item["category"],
        "reason": item["reason"],
    }


@pytest.mark.parametrize("name", sorted(_scenarios()))
def test_apply_matches_openclaw(name: str, _ts_results, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ts, ts_workspace = _ts_results[name]
    scenario = _scenarios()[name]
    assert ts["error"] is None
    py_workspace = tmp_path / f"py-{name}"
    py_workspace.mkdir()
    _seed(py_workspace, scenario)
    py = _run_python(scenario, py_workspace, monkeypatch)
    run, applied = py["run"], ts["applied"]

    assert [_rejection_json(item) for item in run.rejected_candidates] == [
        _ts_rejection_json(item) for item in applied["rejectedCandidates"]
    ]
    assert [(c.key, c.start_line, c.end_line, c.snippet) for c in run.applied_candidates] == [
        (c["key"], c["startLine"], c["endLine"], c["snippet"]) for c in applied["appliedCandidates"]
    ]
    assert len(run.applied_candidates) == applied["applied"]
    assert run.appended == applied["appended"]
    assert run.reconciled_existing == applied["reconciledExisting"]
    assert list(run.compacted_dates) == applied["compactedDates"]
    assert _file(py_workspace, "MEMORY.md") == _file(ts_workspace, "MEMORY.md")
    assert _file(py_workspace, "DREAMS.md") == _file(ts_workspace, "DREAMS.md")
    ts_store = json.loads(_file(ts_workspace, "memory/.dreams/short-term-recall.json"))
    py_store = json.loads(_file(py_workspace, "memory/.dreams/short-term-recall.json"))
    # (readStore drops rows memory-core's store reader keeps, so compare the marks only)
    assert {k: v["promotedAt"] for k, v in py_store["entries"].items() if v.get("promotedAt")} == {
        k: v["promotedAt"] for k, v in ts_store["entries"].items() if v.get("promotedAt")
    }

    # memory.promotion.applied: nothing for a run that rehydrated no candidate, else one event,
    # identical in the store the host reads and in the callback.
    ts_events = _events_at(ts["events"], ts_workspace)
    assert _events_at(py["events"], py_workspace) == ts_events
    assert _events_at([run.host_event] if run.host_event else [], py_workspace) == ts_events

    assert py["origins"] == ts["origins"]
    assert [w.split(": ", 1)[1] for w in py["warnings"]] == [
        w.replace("memory-core: ", "", 1) for w in ts["warnings"]
    ]
    assert [w.split(": ", 1)[1] for w in py["infos"]] == [
        w.replace("memory-core: ", "", 1) for w in ts["infos"]
    ]
    assert [c.message for c in py["calls"]] == [c["message"] for c in ts["calls"]]
    assert read_memory_preimages(py_workspace) == [
        {"createdAt": p["createdAt"], "content": p["content"], "contentHash": p["contentHash"]}
        for p in ts["preimages"]
    ]
    # Upstream takes neither lock when no candidate is rehydrated; memory-core always takes both
    # (a held workspace lock reports "promotion locked" even then), so only the file lock shows.
    assert py["timeline"] == (_dedupe(ts["timeline"]) or ["lock:acquire", "lock:release"])


def test_two_locks_wrap_the_writes(_ts_results, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both sides: sidecar lock first, MEMORY.md then DREAMS.md inside it, the lock released last."""
    for name in ("consolidated_lock_and_dreams_order", "append_lock_order_with_agent"):
        ts, _workspace = _ts_results[name]
        timeline = _dedupe(ts["timeline"])
        assert timeline[0] == "lock:acquire"
        assert timeline[-1] == "lock:release"
        assert "memory:write" in timeline
    consolidated, _workspace = _ts_results["consolidated_lock_and_dreams_order"]
    assert _dedupe(consolidated["timeline"]) == [
        "lock:acquire",
        "memory:write",
        "dreams:write",
        "lock:release",
    ]


def test_scenarios_exercise_every_category(_ts_results) -> None:
    categories = {
        item["category"]
        for ts, _workspace in _ts_results.values()
        for item in ts["applied"]["rejectedCandidates"]
    }
    assert categories == {
        "origin",
        "consolidation origin/session",
        "contamination",
        "already promoted",
        "score threshold",
        "signal threshold",
        "query threshold",
        "age threshold",
        "selection limit",
        "source rehydration",
        "memory budget",
        "candidate changed",
    }, categories


# --- the second lock ---------------------------------------------------------------------------


def _dead_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def _probe_python(workspace: Path, state_dir: Path, seed: dict[str, Any] | None, retries: int) -> dict[str, Any]:
    target = resolve_memory_promotion_lock_target(state_dir, workspace)
    lock_dir = target.parent
    if seed is not None:
        seed = {**seed}
        if seed.get("pid") == "self":
            seed["pid"] = os.getpid()
        Path(f"{target}.lock").write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    options = FileLockOptions(retries=retries, factor=1.2, min_timeout_ms=5, max_timeout_ms=10)
    try:
        with with_file_lock(target, options) as lock_path:
            raw = lock_path.read_text(encoding="utf-8")
            outcome: dict[str, Any] = {
                "ok": True,
                "lockName": lock_path.name,
                "raw": raw,
                "mode": lock_path.stat().st_mode & 0o777,
                "dirMode": lock_dir.stat().st_mode & 0o777,
                "listing": sorted(os.listdir(lock_dir)),
            }
    except FileLockError as error:
        outcome = {"ok": False, "code": error.code, "message": str(error).replace(str(target), "<target>")}
    outcome["afterListing"] = sorted(os.listdir(lock_dir))
    outcome["expectedName"] = f"memory-promotion-{hashlib.sha256(os.path.realpath(workspace).encode()).hexdigest()}.lock"
    return outcome


def _lock_cases() -> dict[str, dict[str, Any]]:
    return {
        "free": {"seed": None},
        "live_holder_times_out": {"seed": {"pid": "self", "createdAt": "2026-05-26T16:00:00.000Z"}, "retries": 2},
        "dead_holder_fails_closed": {"seed": {"pid": _dead_pid(), "createdAt": "2026-05-26T16:00:00.000Z"}},
        "reused_pid_fails_closed": {
            "seed": {"pid": "self", "createdAt": "2026-05-26T16:00:00.000Z", "starttime": 1}
        },
        "ownerless_payload_is_waited_for": {"seed": {"createdAt": "2026-05-01T00:00:00.000Z"}, "retries": 1},
    }


def _stable_lock_message(message: str) -> str:
    """The stale-owner detail names a pid and a start time that differ per process."""
    return re.sub(r"pid=\d+", "pid=N", re.sub(r"observed-start=\d+", "observed-start=N", message))


_TOKEN = re.compile(r"\n(\t{8}[ \t]{128})\n$")


def _structure(raw: str) -> dict[str, Any]:
    token = _TOKEN.search(raw)
    assert token, raw
    payload = json.loads(raw[: token.start()])
    return {"keys": sorted(payload), "indent": raw.startswith('{\n  "pid"'), "pidIsInt": isinstance(payload["pid"], int)}


def test_file_lock_matches_openclaw(tmp_path: Path) -> None:
    cases = _lock_cases()
    ts_workspaces = {}
    for name in cases:
        ts_workspaces[name] = tmp_path / f"ts-{name}"
        ts_workspaces[name].mkdir()
    responses = {}
    oracle = _oracle()
    for name, case in cases.items():
        responses[name] = oracle.run(
            {
                "operation": "fileLockProbe",
                "workspaceDir": str(ts_workspaces[name]),
                "lockProbe": case,
            }
        )["result"]
    for name, case in cases.items():
        workspace = tmp_path / f"py-{name}"
        workspace.mkdir()
        py = _probe_python(workspace, tmp_path / f"state-{name}", case.get("seed"), case.get("retries", 3))
        ts = responses[name]
        assert py["ok"] == ts["ok"], name
        if ts["ok"]:
            assert py["lockName"] == py["expectedName"] and ts["lockName"] == ts["expectedName"]
            assert py["mode"] == ts["mode"] == 0o600
            assert py["dirMode"] == ts["dirMode"] == 0o700
            assert py["listing"] == [py["expectedName"]] and ts["listing"] == [ts["expectedName"]]
            assert _structure(py["raw"]) == _structure(ts["raw"])
        else:
            assert py["code"] == ts["code"], name
            assert _stable_lock_message(py["message"]) == _stable_lock_message(ts["message"]), name
        # A lock that was never ours stays; ours is gone.
        assert len(py["afterListing"]) == len(ts["afterListing"]), name


# --- the origins ledger ------------------------------------------------------------------------


def _ledger_steps() -> list[dict[str, Any]]:
    prior_memory = (
        "# Memory\r\n"
        "<!-- openclaw-memory-promotion:prior -->\n- Prior fact one.\n"
        "<!--openclaw-memory-promotion:other-->\n- Prior fact two.\n"
        "  - Not marked.\n"
        "- First line.\n"
    )
    return [
        {"kind": "record", "agentId": "main", "origins": [origin_row("prior", "s1", "main"), origin_row("prior", "s2", "main")]},
        {"kind": "record", "agentId": "main", "origins": [origin_row("prior", "s1", "main"), origin_row("candidate", "s3", "main")]},
        {"kind": "record", "agentId": "main", "origins": [origin_row("prior", "s9", "main", "agent")], "entryKey": "rekeyed"},
        {"kind": "record", "agentId": "main", "origins": [origin_row("x", "s1", "someone-else")]},
        {"kind": "record", "agentId": "main", "origins": []},
        {"kind": "list", "agentId": "main", "sessionIds": ["s1"]},
        {"kind": "list", "agentId": "main", "entryKeys": ["prior", "missing"], "sessionIds": ["s2", "s9"]},
        {"kind": "list", "agentId": "main", "sessionIds": []},
        {"kind": "list", "agentId": "never-created"},
        {
            "kind": "reserve",
            "agentIds": ["other", "main", "main"],
            "previousMemory": prior_memory,
            "operations": [
                {"candidateKey": "candidate", "action": "merged", "priorEntries": ["- Prior fact one.", "- Prior fact two.", "- First line.", "- Unknown."]},
                {"candidateKey": "fresh", "action": "added", "priorEntries": []},
            ],
        },
        {
            "kind": "reserve",
            "agentIds": ["main"],
            "previousMemory": prior_memory,
            "operations": [{"candidateKey": "rolled-back", "action": "superseded", "priorEntries": ["- Prior fact one."]}],
            "rollback": True,
        },
        {"kind": "index", "agentId": "main", "texts": ["<!-- openclaw-memory-promotion:indexed -->\n- text", "no marker"]},
        {"kind": "index", "agentId": "main", "texts": ["<!-- openclaw-memory-promotion:wiki-only -->"], "source": "wiki"},
        {"kind": "record", "agentId": "main", "origins": [origin_row("indexed", "s5", "main"), origin_row("wiki-only", "s6", "main"), origin_row("diary", "s7", "main")]},
        {
            "kind": "prune",
            "agentIds": ["main", "main"],
            "entryKeys": ["prior", "indexed", "wiki-only", "diary", "retained", "indexed"],
            "retainedEntryKeys": ["retained", "prior-not-listed"],
        },
        {"kind": "prune", "agentIds": ["main"], "entryKeys": ["retained"], "retainedEntryKeys": ["retained"]},
        {"kind": "prune", "agentIds": ["main"], "entryKeys": [], "retainedEntryKeys": []},
    ]


def test_origins_ledger_matches_openclaw(tmp_path: Path) -> None:
    steps = _ledger_steps()
    agent_ids = ["main", "other", "never-created", "someone-else"]
    ts_workspace = tmp_path / "ts"
    py_workspace = tmp_path / "py"
    for workspace in (ts_workspace, py_workspace):
        workspace.mkdir()
        (workspace / "DREAMS.md").write_text("# Diary\n\n<!-- openclaw-memory-promotion:diary -->\n", encoding="utf-8")
        (workspace / "dreams.md").write_text("<!--  openclaw-memory-promotion:lower-diary  -->\n", encoding="utf-8")
    ts = _oracle().run(
        {
            "operation": "originsLedger",
            "workspaceDir": str(ts_workspace),
            "agentIds": agent_ids,
            "originSteps": steps,
        }
    )["result"]["steps"]

    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / "agents" / f"{agent}.sqlite")
    py: list[dict[str, Any]] = []
    for step in steps:
        result: Any = None
        try:
            if step["kind"] == "record":
                result = [
                    _origin_json(item)
                    for item in ledger.record(
                        step["agentId"], [_origin(raw) for raw in step["origins"]], entry_key=step.get("entryKey")
                    )
                ]
            elif step["kind"] == "reserve":
                rollback = reserve_memory_entry_origins(
                    ledger,
                    agent_ids=step["agentIds"],
                    previous_memory=step["previousMemory"],
                    operations=[
                        _Operation(op["candidateKey"], op["action"], op["priorEntries"]) for op in step["operations"]
                    ],
                )
                if step.get("rollback"):
                    rollback()
            elif step["kind"] == "prune":
                prune_memory_entry_origins(
                    ledger,
                    workspace_dir=py_workspace,
                    agent_ids=step["agentIds"],
                    entry_keys=step["entryKeys"],
                    retained_entry_keys=set(step["retainedEntryKeys"]),
                )
            elif step["kind"] == "index":
                for text in step["texts"]:
                    _insert_index_chunk_source(ledger.database_path(step["agentId"]), text, step.get("source", "memory"))
            elif step["kind"] == "list":
                result = [
                    _origin_json(item)
                    for item in ledger.list(
                        step["agentId"], session_ids=step.get("sessionIds"), entry_keys=step.get("entryKeys")
                    )
                ]
        except ValueError as error:
            result = {"error": str(error)}
        py.append(
            {
                "result": result,
                "state": {agent: [_origin_json(item) for item in ledger.list(agent)] for agent in agent_ids},
            }
        )
    for index, (py_step, ts_step) in enumerate(zip(py, ts, strict=True)):
        assert py_step == ts_step, (index, steps[index]["kind"])


class _Operation:
    def __init__(self, candidate_key: str, action: str, prior_entries: list[str]) -> None:
        self.candidate_key = candidate_key
        self.action = action
        self.prior_entries = prior_entries


def _insert_index_chunk_source(db_path: Path, text: str, source: str) -> None:
    import sqlite3

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS memory_index_chunks (id TEXT, source TEXT, text TEXT)")
        db.execute("INSERT INTO memory_index_chunks VALUES (?, ?, ?)", (os.urandom(4).hex(), source, text))


def test_preimage_rotation_prunes_expired_origins(tmp_path: Path) -> None:
    """``storeMemoryPreimage``: ten snapshots keep eight; the origins of the two expired keys go."""
    ts_workspace = tmp_path / "ts"
    py_workspace = tmp_path / "py"
    ts_workspace.mkdir()
    py_workspace.mkdir()
    snapshots = [f"# Memory\n<!-- openclaw-memory-promotion:key-{i} -->\n- Fact {i}.\n" for i in range(10)]
    steps: list[dict[str, Any]] = [
        {"kind": "record", "agentId": "main", "origins": [origin_row(f"key-{i}", f"s{i}", "main") for i in range(10)]}
    ]
    for index, content in enumerate(snapshots):
        steps.append(
            {
                "kind": "preimage",
                "content": content,
                "nowMs": NOW_MS + index * 1000,
                "agentIds": ["main"],
                "retainedEntryKeys": ["key-1"],
            }
        )
    ts = _oracle().run(
        {
            "operation": "originsLedger",
            "workspaceDir": str(ts_workspace),
            "agentIds": ["main"],
            "originSteps": steps,
        }
    )["result"]["steps"]
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / "agents" / f"{agent}.sqlite")
    ledger.record("main", [_origin(raw) for raw in steps[0]["origins"]])
    py = []
    for step in steps[1:]:
        retained = store_memory_preimage(
            py_workspace,
            step["content"],
            step["nowMs"],
            agent_ids=step["agentIds"],
            retained_entry_keys=set(step["retainedEntryKeys"]),
            ledger=ledger,
        )
        py.append({"result": sorted(retained), "state": {"main": [_origin_json(i) for i in ledger.list("main")]}})
    assert py == ts[1:]
    # key-0 expired and was released; key-1 was named as retained, so it stays.
    assert {row["entryKey"] for row in py[-1]["state"]["main"]} >= {"key-1", "key-9"}
    assert "key-0" not in {row["entryKey"] for row in py[-1]["state"]["main"]}
    assert len(read_memory_preimages(py_workspace)) == 8
