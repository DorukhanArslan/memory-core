"""Oracle tests of the callers that write the memory-entry origins ledger, against OpenClaw v2026.9.6.

Three real-TS runs (each one oracle process over many seeded scenarios), replayed in Python:

- ``recordRecallScenarios``: ``recordShortTermRecalls`` (short-term-promotion-record.ts:370) with
  ``sessionOrigin`` on the hits, tombstoned sessions and every signal type; the recall store, the
  origins ledger and the tombstones must agree;
- ``sessionBackfillLineage``: ``buildSessionBackfillDiaryEntries`` (session-backfill.ts:316) loaded
  from the real source with one extra export line, and the grounded-signal half of
  ``applySessionBackfillDays`` (``coalesceBackfillClaims`` then ``recordGroundedShortTermCandidates``);
- ``originsLedger`` tombstone steps: ``recordMemorySessionTombstonesInDatabase`` /
  ``listMemorySessionTombstones`` over the real agent database and its ``memory_index_state`` revision
  fence counter.

Not reachable through the oracle (unit tested instead, tests/unit/test_origins_callers.py): the REM
branch of the diary builder (needs ``previewGroundedRemForFile``) and the index publication that
reads the revision fence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.config import MemoryConfig
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger
from memory_core.consolidation.recall import record_short_term_recalls
from memory_core.consolidation.session_backfill import (
    SessionBackfillCandidate,
    build_session_backfill_diary_entries,
    coalesce_backfill_claims,
    record_session_backfill_day,
)
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

NOW_MS = 1779811200000  # 2026-05-26T16:00:00Z
TZ = "Europe/Istanbul"
DAILY = "memory/2026-05-08.md"
CORPUS = "memory/.dreams/session-corpus/2026-05-08.txt"
STORE = "memory/.dreams/short-term-recall.json"


def _oracle() -> OpenClawOracle:
    return OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=240)


def _origin(agent: str, session: str, key: str | None = "") -> dict[str, Any]:
    out: dict[str, Any] = {"agentId": agent, "sessionId": session}
    if key is not None:
        out["sessionKey"] = f"agent:{agent}:{session}" if key == "" else key
    return out


def _hit(line: int, text: str, path: str = DAILY, **over: Any) -> dict[str, Any]:
    hit = {
        "path": path,
        "startLine": line,
        "endLine": line,
        "score": 0.8,
        "snippet": text,
        "source": "memory",
    }
    hit.update(over)
    return hit


def _owner(observed: int = 1234, kind: str = "interactive") -> dict[str, Any]:
    return {"originClass": "owner", "sessionKind": kind, "observedAt": observed}


# --- recordShortTermRecalls ---------------------------------------------------------------------


def _recall_scenarios() -> dict[str, dict[str, Any]]:
    return {
        "single_origin": {
            "agents": ["rc-single"],
            "recalls": [
                {
                    "query": "backups",
                    "results": [
                        _hit(3, "- Backups run nightly.", sessionOrigin=_origin("rc-single", "s1"), provenance=_owner())
                    ],
                }
            ],
        },
        "default_provenance_and_missing_session_key": {
            "agents": ["rc-default"],
            "recalls": [
                {
                    "query": "alpha",
                    "results": [_hit(4, "- Alpha is first.", sessionOrigin=_origin("rc-default", "s1", None))],
                }
            ],
        },
        "two_sessions_one_entry": {
            "agents": ["rc-two"],
            "recalls": [
                {
                    "query": "q one",
                    "results": [_hit(3, "- Shared fact.", sessionOrigin=_origin("rc-two", "s1"), provenance=_owner(10))],
                },
                {
                    "query": "q two",
                    "results": [
                        _hit(
                            3,
                            "- Shared fact.",
                            sessionOrigin=_origin("rc-two", "s2"),
                            provenance={"originClass": "untrusted", "sessionKind": "cron", "observedAt": 99},
                        ),
                        _hit(3, "- Shared fact.", sessionOrigin=_origin("rc-two", "s1"), provenance=_owner(500)),
                    ],
                },
            ],
        },
        "tombstoned_session_is_dropped": {
            "agents": ["rc-tomb"],
            "tombstones": [{"agentId": "rc-tomb", "sessionIds": ["s1"]}],
            "recalls": [
                {
                    "query": "tomb",
                    "results": [
                        _hit(3, "- From the forgotten session.", sessionOrigin=_origin("rc-tomb", "s1")),
                        _hit(4, "- From a live session.", sessionOrigin=_origin("rc-tomb", "s2")),
                        _hit(5, "- From the search index."),
                    ],
                }
            ],
        },
        "every_hit_tombstoned_writes_nothing": {
            "agents": ["rc-all"],
            "tombstones": [{"agentId": "rc-all", "sessionIds": ["s1", "s2"]}],
            "recalls": [
                {
                    "query": "gone",
                    "results": [
                        _hit(3, "- One.", sessionOrigin=_origin("rc-all", "s1")),
                        _hit(4, "- Two.", sessionOrigin=_origin("rc-all", "s2")),
                    ],
                }
            ],
        },
        "tombstones_are_per_agent": {
            "agents": ["rc-per-a", "rc-per-b"],
            "tombstones": [{"agentId": "rc-per-b", "sessionIds": ["shared-id"]}],
            "recalls": [
                {
                    "query": "per agent",
                    "results": [
                        _hit(3, "- Kept for a.", sessionOrigin=_origin("rc-per-a", "shared-id")),
                        _hit(4, "- Dropped for b.", sessionOrigin=_origin("rc-per-b", "shared-id")),
                        _hit(5, "- Kept for b.", sessionOrigin=_origin("rc-per-b", "other")),
                    ],
                }
            ],
        },
        "skipped_snippets_record_no_origin": {
            "agents": ["rc-skip"],
            "recalls": [
                {
                    "query": "skip",
                    "results": [
                        _hit(3, "<!-- openclaw-memory-promotion:abc -->", sessionOrigin=_origin("rc-skip", "s1")),
                        _hit(4, "   ", sessionOrigin=_origin("rc-skip", "s2")),
                        _hit(5, "- Real fact.", sessionOrigin=_origin("rc-skip", "s3")),
                        _hit(6, "- Not a daily file.", path="notes/x.md", sessionOrigin=_origin("rc-skip", "s4")),
                    ],
                }
            ],
        },
        "session_corpus_hit": {
            "agents": ["rc-corpus"],
            "recalls": [
                {
                    "query": "corpus",
                    "results": [
                        _hit(
                            2,
                            "User: remember the deploy window.",
                            path=CORPUS,
                            sessionOrigin=_origin("rc-corpus", "s1"),
                            provenance=_owner(7),
                        )
                    ],
                }
            ],
        },
        "grounded_signal": {
            "agents": ["rc-grounded"],
            "recalls": [
                {
                    "query": "__dreaming_session_backfill__:2026-05-08",
                    "signalType": "grounded",
                    "dedupeByQueryPerDay": True,
                    "results": [
                        _hit(
                            2,
                            "Deploys happen on Tuesday.",
                            path=CORPUS,
                            dayBucket="2026-05-08",
                            sessionOrigin=_origin("rc-grounded", "s1"),
                            provenance=_owner(42),
                        ),
                        _hit(
                            2,
                            "Deploys happen on Tuesday.",
                            path=CORPUS,
                            dayBucket="2026-05-08",
                            sessionOrigin=_origin("rc-grounded", "s2"),
                            provenance=_owner(43),
                        ),
                    ],
                }
            ],
        },
        "daily_signal_claim_key": {
            "agents": ["rc-daily"],
            "recalls": [
                {
                    "query": "daily",
                    "signalType": "daily",
                    "results": [
                        _hit(3, "- Daily claim.", sessionOrigin=_origin("rc-daily", "s1"), provenance=_owner(5)),
                    ],
                }
            ],
        },
    }


def _seed_daily(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "memory").mkdir(exist_ok=True)
    (workspace / DAILY).write_text("# 2026-05-08\n\n" + "".join(f"- Line {i}.\n" for i in range(1, 12)), "utf-8")


@pytest.fixture(scope="module")
def _recall_ts(tmp_path_factory):
    root = tmp_path_factory.mktemp("recall-origins-ts")
    payload = []
    for name, scenario in _recall_scenarios().items():
        workspace = root / f"ts-{name}"
        _seed_daily(workspace)
        payload.append(
            {
                "name": name,
                "workspaceDir": str(workspace),
                "nowMs": NOW_MS,
                "agentIds": scenario["agents"],
                "seedTombstones": scenario.get("tombstones", []),
                "recalls": [{**recall, "nowMs": NOW_MS + index * 1000} for index, recall in enumerate(scenario["recalls"])],
            }
        )
    response = _oracle().run(
        {"operation": "recordRecallScenarios", "timezone": TZ, "nowMs": NOW_MS, "recallScenarios": payload}
    )
    assert response["ok"] is True
    results = {item["name"]: item for item in response["result"]["scenarios"]}
    return {name: (results[name], root / f"ts-{name}") for name in _recall_scenarios()}


def _origin_json(origin: MemoryEntryOrigin) -> dict[str, Any]:
    return {
        "entryKey": origin.entry_key,
        "agentId": origin.agent_id,
        "sessionId": origin.session_id,
        "sessionKey": origin.session_key,
        "originClass": origin.origin_class,
        "observedAt": origin.observed_at,
    }


def _store_entries(workspace: Path) -> dict[str, Any]:
    path = workspace / STORE
    return json.loads(path.read_text("utf-8"))["entries"] if path.exists() and path.read_text("utf-8") else {}


def _tombstone_json(ledger: MemoryEntryOriginLedger, agent: str) -> list[dict[str, Any]]:
    return [
        {"sessionId": t.session_id, "agentId": t.agent_id, "reason": t.reason, "createdAt": t.created_at}
        for t in ledger.list_session_tombstones(agent)
    ]


@pytest.mark.parametrize("name", sorted(_recall_scenarios()))
def test_recall_origins_match_openclaw(name: str, _recall_ts, tmp_path: Path) -> None:
    ts, ts_workspace = _recall_ts[name]
    scenario = _recall_scenarios()[name]
    assert ts["error"] is None
    workspace = tmp_path / f"py-{name}"
    _seed_daily(workspace)
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / "agents" / f"{agent}.sqlite")
    for seed in scenario.get("tombstones", []):
        ledger.record_session_tombstones(seed["agentId"], seed["sessionIds"], created_at=1)
    config = MemoryConfig(workspace_dir=workspace, store_path=tmp_path / f"{name}.sqlite")
    for index, recall in enumerate(scenario["recalls"]):
        record_short_term_recalls(
            config=config,
            query=recall["query"],
            results=recall["results"],
            now_ms=NOW_MS + index * 1000,
            signal_type=recall.get("signalType", "recall"),
            dedupe_by_query_per_day=recall.get("dedupeByQueryPerDay", False),
            day_bucket=recall.get("dayBucket"),
            timezone=TZ,
            origins=ledger,
        )
    assert {
        agent: [_origin_json(item) for item in ledger.list(agent)] for agent in scenario["agents"]
    } == ts["origins"]
    assert {agent: _tombstone_json(ledger, agent) for agent in scenario["agents"]} == ts["tombstones"]
    assert _store_entries(workspace) == json.loads(ts["files"][STORE] or '{"entries": {}}')["entries"]


def test_recall_scenarios_exercise_both_outcomes(_recall_ts) -> None:
    rows = {name: sum(len(v) for v in ts["origins"].values()) for name, (ts, _w) in _recall_ts.items()}
    assert rows["single_origin"] == 1
    assert rows["two_sessions_one_entry"] == 2
    assert rows["tombstoned_session_is_dropped"] == 1
    assert rows["every_hit_tombstoned_writes_nothing"] == 0
    assert rows["tombstones_are_per_agent"] == 2
    assert rows["skipped_snippets_record_no_origin"] == 1
    assert rows["grounded_signal"] == 2


# --- session backfill ---------------------------------------------------------------------------


def _candidate(day: str, snippet: str, agent: str | None, session: str | None, klass: str = "owner", **over: Any):
    candidate: dict[str, Any] = {
        "day": day,
        "snippet": snippet,
        "rendered": f"User: {snippet}",
        "provenance": {"originClass": klass, "sessionKind": "interactive", "observedAt": 1000 + len(snippet)},
    }
    if agent is not None:
        candidate["sessionOrigin"] = {"agentId": agent, "sessionId": session, **over}
    return candidate


def _backfill_scenarios() -> dict[str, dict[str, Any]]:
    day, day2 = "2026-05-08", "2026-05-09"
    return {
        "diary_basic": {
            "agent": "bf-basic",
            "agents": ["bf-basic"],
            "days": [
                {
                    "day": day,
                    "candidates": [
                        _candidate(day, "Deploys happen on Tuesday.", "bf-basic", "s1", sessionKey="agent:bf-basic:s1"),
                        _candidate(day, "The staging DB is read-only.", "bf-basic", "s2", klass="agent"),
                        _candidate(day, "No session identity here.", None, None),
                    ],
                },
                {
                    "day": day2,
                    "candidates": [
                        _candidate(day2, f"Fact number {i}.", "bf-basic", f"t{i}") for i in range(7)
                    ],
                },
                {"day": "2026-05-10", "candidates": []},
            ],
        },
        "diary_identical_lines_accumulate": {
            "agent": "bf-same",
            "agents": ["bf-same"],
            "days": [
                {
                    "day": day,
                    "candidates": [
                        _candidate(day, "Same words twice.", "bf-same", "s1"),
                        _candidate(day, "Same words twice.", "bf-same", "s2", klass="agent"),
                        _candidate(day, "Same words twice.", "bf-same", "s1"),
                    ],
                }
            ],
        },
        "diary_hash_of_awkward_text": {
            "agent": "bf-text",
            "agents": ["bf-text"],
            "days": [
                {
                    "day": day,
                    "candidates": [
                        _candidate(day, 'He said "quote" and \\ backslash\ttab', "bf-text", "s1"),
                        _candidate(day, "emoji \U0001f600 and line sep and é", "bf-text", "s2"),
                        _candidate(day, "lone \ud800 surrogate", "bf-text", "s3"),
                        _candidate(day, "ctl \u0001 \u007f char", "bf-text", "s4"),
                    ],
                }
            ],
        },
        "diary_foreign_agent_session_is_rejected": {
            "agent": "bf-own",
            "agents": ["bf-own", "bf-foreign"],
            "days": [
                {
                    "day": day,
                    "candidates": [
                        _candidate(day, "Mine.", "bf-own", "s1"),
                        _candidate(day, "Someone else's.", "bf-foreign", "s9"),
                    ],
                }
            ],
        },
        "record_day_coalesces_claims": {
            "agents": ["bf-claims"],
            "recordDays": [
                {
                    "day": day,
                    "results": [
                        _hit(
                            2,
                            "User: Deploys happen on Tuesday.",
                            path=CORPUS,
                            provenance=_owner(11),
                            sessionOrigin=_origin("bf-claims", "s1"),
                        ),
                        _hit(
                            5,
                            "Assistant:   deploys  HAPPEN on tuesday.  ",
                            path=CORPUS,
                            provenance={"originClass": "agent", "sessionKind": "cron", "observedAt": 12},
                            sessionOrigin=_origin("bf-claims", "s2"),
                        ),
                        _hit(7, "Another claim entirely.", path=CORPUS, provenance=_owner(13), sessionOrigin=_origin("bf-claims", "s1")),
                        _hit(9, "User:   ", path=CORPUS, provenance=_owner(14), sessionOrigin=_origin("bf-claims", "s3")),
                    ],
                },
                {"day": "2026-05-09", "results": [_hit(3, "User: ", path=CORPUS, sessionOrigin=_origin("bf-claims", "s4"))]},
            ],
        },
        "record_day_skips_forgotten_sessions": {
            "agents": ["bf-forget"],
            "tombstones": [{"agentId": "bf-forget", "sessionIds": ["gone"]}],
            "recordDays": [
                {
                    "day": day,
                    "results": [
                        _hit(2, "User: Forgotten claim.", path=CORPUS, provenance=_owner(1), sessionOrigin=_origin("bf-forget", "gone")),
                        _hit(3, "User: Kept claim.", path=CORPUS, provenance=_owner(2), sessionOrigin=_origin("bf-forget", "kept")),
                    ],
                }
            ],
        },
    }


@pytest.fixture(scope="module")
def _backfill_ts(tmp_path_factory):
    root = tmp_path_factory.mktemp("backfill-origins-ts")
    payload = []
    for name, scenario in _backfill_scenarios().items():
        workspace = root / f"ts-{name}"
        _seed_daily(workspace)
        item: dict[str, Any] = {
            "name": name,
            "workspaceDir": str(workspace),
            "nowMs": NOW_MS,
            "agentIds": scenario["agents"],
            "seedTombstones": scenario.get("tombstones", []),
        }
        if "days" in scenario:
            item["agentId"] = scenario["agent"]
            item["days"] = scenario["days"]
        if "recordDays" in scenario:
            item["recordDays"] = scenario["recordDays"]
        payload.append(item)
    response = _oracle().run(
        {"operation": "sessionBackfillLineage", "timezone": TZ, "nowMs": NOW_MS, "backfillScenarios": payload}
    )
    assert response["ok"] is True
    results = {item["name"]: item for item in response["result"]["scenarios"]}
    return {name: (results[name], root / f"ts-{name}") for name in _backfill_scenarios()}


def _py_candidate(raw: dict[str, Any]) -> SessionBackfillCandidate:
    return SessionBackfillCandidate(
        day=raw["day"],
        snippet=raw["snippet"],
        rendered=raw["rendered"],
        provenance=raw["provenance"],
        session_origin=raw.get("sessionOrigin"),
    )


@pytest.mark.parametrize("name", sorted(_backfill_scenarios()))
def test_session_backfill_lineage_matches_openclaw(name: str, _backfill_ts, tmp_path: Path) -> None:
    ts, _ts_workspace = _backfill_ts[name]
    scenario = _backfill_scenarios()[name]
    workspace = tmp_path / f"py-{name}"
    _seed_daily(workspace)
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / "agents" / f"{agent}.sqlite")
    for seed in scenario.get("tombstones", []):
        ledger.record_session_tombstones(seed["agentId"], seed["sessionIds"], created_at=1)
    config = MemoryConfig(workspace_dir=workspace, store_path=tmp_path / f"{name}.sqlite")
    error = None
    diary = None
    coalesced: list[Any] = []
    try:
        if "days" in scenario:
            diary = build_session_backfill_diary_entries(
                ledger=ledger,
                agent_id=scenario["agent"],
                days=[(d["day"], [_py_candidate(c) for c in d["candidates"]]) for d in scenario["days"]],
                identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
            )
        for day in scenario.get("recordDays", []):
            coalesced.append(coalesce_backfill_claims(day["results"]))
            record_session_backfill_day(
                config=config, ledger=ledger, day=day["day"], results=day["results"], now_ms=NOW_MS, timezone=TZ
            )
    except ValueError as caught:
        error = str(caught)
    assert error == ts["error"]
    assert diary == ts["diary"]
    assert coalesced == ts["coalesced"]
    assert {
        agent: [_origin_json(item) for item in ledger.list(agent)] for agent in scenario["agents"]
    } == ts["origins"]
    assert _store_entries(workspace) == json.loads(ts["files"][STORE] or '{"entries": {}}')["entries"]


def test_backfill_scenarios_cover_the_interesting_outcomes(_backfill_ts) -> None:
    diary, _w = _backfill_ts["diary_basic"]
    assert len(diary["origins"]["bf-basic"]) == 2 + 5  # the top five snippets of a day
    shared, _w = _backfill_ts["diary_identical_lines_accumulate"]
    assert len(shared["origins"]["bf-same"]) == 2  # one marker, two distinct sessions
    foreign, _w = _backfill_ts["diary_foreign_agent_session_is_rejected"]
    assert foreign["error"] and foreign["origins"] == {"bf-own": [], "bf-foreign": []}
    forgotten, _w = _backfill_ts["record_day_skips_forgotten_sessions"]
    assert [row["sessionId"] for row in forgotten["origins"]["bf-forget"]] == ["kept"]


# --- tombstones and the revision fence ----------------------------------------------------------


def _tombstone_steps() -> list[dict[str, Any]]:
    many = [f"bulk-{i}" for i in range(300)]
    return [
        {"kind": "tombstone", "agentId": "main", "sessionIds": ["s1", "s2"], "createdAt": 111},
        {"kind": "tombstone", "agentId": "main", "sessionIds": ["s2", "s3", "s3"], "createdAt": 222},
        {"kind": "tombstone", "agentId": "main", "sessionIds": ["s1"], "createdAt": 333},
        {"kind": "tombstone", "agentId": "main", "sessionIds": [], "createdAt": 333},
        {"kind": "tombstone", "agentId": "other", "sessionIds": ["s1"], "reason": "purged", "createdAt": 444},
        {"kind": "tombstones", "agentId": "main"},
        {"kind": "tombstones", "agentId": "main", "sessionIds": ["s3", "unknown"]},
        {"kind": "tombstones", "agentId": "main", "sessionIds": []},
        {"kind": "tombstones", "agentId": "never-created"},
        {"kind": "tombstone", "agentId": "main", "sessionIds": many, "createdAt": 555},
        {"kind": "tombstone", "agentId": "main", "sessionIds": many[:5] + ["fresh"], "createdAt": 666},
    ]


def test_tombstones_and_revision_fence_match_openclaw(tmp_path: Path) -> None:
    steps = _tombstone_steps()
    agent_ids = ["main", "other", "never-created"]
    workspace = tmp_path / "ts"
    workspace.mkdir()
    ts = _oracle().run(
        {"operation": "originsLedger", "workspaceDir": str(workspace), "agentIds": agent_ids, "originSteps": steps}
    )["result"]["steps"]

    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / "agents" / f"{agent}.sqlite")
    for index, (step, ts_step) in enumerate(zip(steps, ts, strict=True)):
        result: Any = None
        if step["kind"] == "tombstone":
            result = ledger.record_session_tombstones(
                step["agentId"],
                step["sessionIds"],
                reason=step.get("reason", "forgotten"),
                created_at=step["createdAt"],
            )
        elif step["kind"] == "tombstones":
            result = [
                {"sessionId": t.session_id, "agentId": t.agent_id, "reason": t.reason, "createdAt": t.created_at}
                for t in ledger.list_session_tombstones(step["agentId"], step.get("sessionIds"))
            ]
        assert result == ts_step["result"], (index, step["kind"])
        assert {a: _tombstone_json(ledger, a) for a in agent_ids} == ts_step["tombstones"], index
        # The fence counter of every agent database that exists on both sides.
        for agent in agent_ids:
            live = ledger.index_revision(agent)
            if live is not None:
                assert ts_step["revisions"][agent] == live, (index, agent)
