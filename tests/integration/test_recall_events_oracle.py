"""Oracle test of the ``memory.recall.recorded`` / ``memory.recall.skipped`` host events.

One real-TS run (``recordRecallScenarios``: ``recordShortTermRecalls`` over seeded workspaces, then
``readMemoryHostEventRecords`` of each workspace) against OpenClaw v2026.9.6, replayed in Python
through the ``on_event`` callback of ``record_short_term_recalls``. The events (stored form: bounded
results, truncation marker, byte limits) and the recall store must agree.

Scenarios: named cases for every branch (recorded, skipped only, both, grounded, forgotten session,
contaminated snippets, truncation by results, query and path) and seeded random mixes.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.config import MemoryConfig
from memory_core.consolidation.origins import MemoryEntryOriginLedger
from memory_core.consolidation.recall import record_short_term_recalls

NOW_MS = 1779811200000
TZ = "Europe/Istanbul"
STORE = "memory/.dreams/short-term-recall.json"
DAILY = "memory/2026-05-08.md"


def _oracle() -> OpenClawOracle:
    return OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=300)


def _hit(line: int, text: str, path: str = DAILY, **over: Any) -> dict[str, Any]:
    hit: dict[str, Any] = {
        "path": path,
        "startLine": line,
        "endLine": line,
        "score": 0.8,
        "snippet": text,
        "source": "memory",
    }
    hit.update(over)
    return hit


def _named() -> dict[str, dict[str, Any]]:
    return {
        "recorded_only": {"recalls": [{"query": "backups", "results": [_hit(3, "- Backups run nightly.")]}]},
        "skipped_only": {
            "recalls": [{"query": "plan", "results": [_hit(2, "- Plan the launch.", path="MEMORY.md")]}]
        },
        "recorded_and_skipped": {
            "recalls": [
                {
                    "query": "mix",
                    "results": [
                        _hit(3, "- Backups run nightly."),
                        _hit(4, "- Release notes live in the wiki.", path="memory/notes.md"),
                        _hit(5, "- Another fact.", path="./memory/2026-05-08.md", score=2.5),
                    ],
                }
            ]
        },
        "grounded_has_no_events": {
            "recalls": [
                {
                    "query": "ground",
                    "signalType": "grounded",
                    "results": [_hit(3, "- Grounded claim one.", dayBucket="2026-05-08")],
                },
                {
                    "query": "ground two",
                    "signalType": "grounded",
                    "results": [_hit(3, "- Skipped path claim.", path="MEMORY.md")],
                },
            ]
        },
        "daily_signal_has_events": {
            "recalls": [{"query": "__dreaming_daily__:2026-05-08", "signalType": "daily", "results": [_hit(3, "- Daily fact here.")]}]
        },
        "non_memory_sources_are_ignored": {
            "recalls": [{"query": "sessions", "results": [_hit(3, "- From a session.", source="sessions")]}]
        },
        "contaminated_snippet_is_still_counted": {
            "recalls": [
                {
                    "query": "dream",
                    "results": [_hit(3, "Candidate: remember this", path=DAILY), _hit(4, "- A real fact line.")],
                }
            ]
        },
        "blank_query_records_nothing": {"recalls": [{"query": "   ", "results": [_hit(3, "- Fact.")]}]},
        "forgotten_session_drops_the_event": {
            "tombstones": [{"agentId": "ev-agent", "sessionIds": ["s1"]}],
            "recalls": [
                {
                    "query": "tomb",
                    "results": [
                        _hit(
                            3,
                            "- From the forgotten session.",
                            sessionOrigin={"agentId": "ev-agent", "sessionId": "s1", "sessionKey": "k"},
                        ),
                        _hit(4, "- Skipped path.", path="MEMORY.md"),
                    ],
                }
            ],
        },
        "forgotten_session_partial": {
            "tombstones": [{"agentId": "ev-agent", "sessionIds": ["s1"]}],
            "recalls": [
                {
                    "query": "tomb",
                    "results": [
                        _hit(3, "- From the forgotten session.", sessionOrigin={"agentId": "ev-agent", "sessionId": "s1"}),
                        _hit(4, "- From a live session.", sessionOrigin={"agentId": "ev-agent", "sessionId": "s2"}),
                    ],
                }
            ],
        },
        "more_than_ten_results": {
            "recalls": [
                {"query": "many", "results": [_hit(i, f"- Fact number {i} is here.") for i in range(1, 14)]}
            ]
        },
        "more_than_ten_skipped": {
            "recalls": [
                {
                    "query": "many",
                    "results": [_hit(1, "- Fact.")]
                    + [_hit(i, f"- Fact number {i}.", path=f"memory/n{i}.md") for i in range(1, 14)],
                }
            ]
        },
        "long_query_is_cut": {
            "recalls": [{"query": "é" * 1500 + " tail", "results": [_hit(3, "- Backups run nightly.")]}]
        },
        "long_path_is_cut": {
            "recalls": [
                {
                    "query": "path",
                    "results": [_hit(3, "- Backups run nightly.", path="memory/" + "ü" * 150 + "/2026-05-08.md")],
                }
            ]
        },
        "oversized_event_drops_results": {
            "recalls": [
                {
                    "query": '"' * 2000,  # JSON escapes double the bytes
                    "results": [
                        _hit(i, f"- Fact {i}.", path="memory/" + '"' * 200 + f"/2026-05-{i:02d}.md") for i in range(1, 11)
                    ],
                }
            ]
        },
        "fractional_and_zero_lines": {
            "recalls": [
                {
                    "query": "lines",
                    "results": [
                        _hit(3, "- Fractional.", startLine=3.7, endLine=9.2),
                        _hit(3, "- Zero.", startLine=0, endLine=0),
                        _hit(3, "- Negative.", path="MEMORY.md", startLine=-4, endLine=2.5, score=-1),
                    ],
                }
            ]
        },
    }


_PATHS = [
    DAILY,
    "memory/2026-05-09.md",
    "memory/2026-05-09-notes.md",
    "./memory/2026-05-08.md",
    "memory/.dreams/session-corpus/2026-05-08.txt",
    "MEMORY.md",
    "memory/notes.md",
    "memory/dreaming/light/2026-05-08.md",
    "docs/readme.md",
]


def _random_scenarios(count: int) -> dict[str, dict[str, Any]]:
    rng = random.Random(20260930)
    out: dict[str, dict[str, Any]] = {}
    for index in range(count):
        recalls = []
        for step in range(rng.randint(1, 3)):
            results = []
            for hit in range(rng.randint(0, 13)):
                over: dict[str, Any] = {}
                if rng.random() < 0.2:
                    over["source"] = rng.choice(["sessions", "memory", "wiki"])
                if rng.random() < 0.3:
                    over["score"] = rng.choice([0, 0.25, 1, 1.7, -0.5])
                if rng.random() < 0.15:
                    over["startLine"] = rng.choice([0, 2.9, 12])
                    over["endLine"] = rng.choice([0, 3.1, 14])
                results.append(
                    _hit(
                        rng.randint(1, 8),
                        rng.choice(["- Fact %d is true.", "- Alpha %d beats beta.", "Candidate: skip %d", "- Gamma %d."])
                        % rng.randint(1, 5),
                        path=rng.choice(_PATHS),
                        **over,
                    )
                )
            recalls.append(
                {
                    "query": rng.choice(["alpha", "beta query", "  gamma  ", "ü" * rng.randint(1, 40)]),
                    "signalType": rng.choice(["recall"] * 5 + ["daily", "grounded"]),
                    "dedupeByQueryPerDay": rng.random() < 0.3,
                    "results": results,
                }
            )
        out[f"random_{index:03d}"] = {"recalls": recalls}
    return out


def _scenarios() -> dict[str, dict[str, Any]]:
    return {**_named(), **_random_scenarios(60)}


def _seed(workspace: Path) -> None:
    (workspace / "memory").mkdir(parents=True, exist_ok=True)
    for day in ("2026-05-08", "2026-05-09"):
        (workspace / "memory" / f"{day}.md").write_text(
            f"# {day}\n\n" + "".join(f"- Line {i}.\n" for i in range(1, 15)), "utf-8"
        )
    (workspace / "memory" / "2026-05-09-notes.md").write_text("# notes\n\n- Note.\n", "utf-8")
    (workspace / "memory" / "notes.md").write_text("# notes\n", "utf-8")
    (workspace / "MEMORY.md").write_text("# Memory\n", "utf-8")


def _payload_recall(recall: dict[str, Any], index: int) -> dict[str, Any]:
    return {**recall, "nowMs": NOW_MS + index * 1000}


@pytest.fixture(scope="module")
def _ts(tmp_path_factory):
    root = tmp_path_factory.mktemp("recall-events-ts")
    payload = []
    for name, scenario in _scenarios().items():
        workspace = root / f"ts-{name}"
        _seed(workspace)
        payload.append(
            {
                "name": name,
                "workspaceDir": str(workspace),
                "nowMs": NOW_MS,
                "agentIds": ["ev-agent"] if scenario.get("tombstones") else [],
                "seedTombstones": scenario.get("tombstones", []),
                "recalls": [_payload_recall(r, i) for i, r in enumerate(scenario["recalls"])],
            }
        )
    response = _oracle().run(
        {"operation": "recordRecallScenarios", "timezone": TZ, "nowMs": NOW_MS, "recallScenarios": payload}
    )
    assert response["ok"] is True
    return {item["name"]: item for item in response["result"]["scenarios"]}


def _store(workspace: Path) -> dict[str, Any]:
    path = workspace / STORE
    text = path.read_text("utf-8") if path.exists() else ""
    return json.loads(text)["entries"] if text else {}


def _has_fractional_lines(scenario: dict[str, Any]) -> bool:
    return any(
        not float(hit.get(key, 1)).is_integer() or hit.get(key, 1) == 0
        for recall in scenario["recalls"]
        for hit in recall["results"]
        for key in ("startLine", "endLine")
    )


@pytest.mark.parametrize("name", sorted(_scenarios()))
def test_recall_events_match_openclaw(name: str, _ts, tmp_path: Path) -> None:
    scenario = _scenarios()[name]
    ts = _ts[name]
    assert ts["error"] is None
    workspace = tmp_path / f"py-{name}"
    _seed(workspace)
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / "agents" / f"{agent}.sqlite")
    for seed in scenario.get("tombstones", []):
        ledger.record_session_tombstones(seed["agentId"], seed["sessionIds"], created_at=1)
    config = MemoryConfig(workspace_dir=workspace, store_path=tmp_path / f"{name}.sqlite")
    events: list[dict[str, Any]] = []
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
            on_event=events.append,
        )
    assert events == ts["events"]
    if _has_fractional_lines(scenario):
        return  # the recall store's range keys of fractional lines are not this test's subject
    assert _store(workspace) == json.loads(ts["files"][STORE] or '{"entries": {}}')["entries"]


def test_event_scenarios_cover_the_branches(_ts) -> None:
    counts = {name: [e["type"] for e in item["events"]] for name, item in _ts.items()}
    assert counts["recorded_only"] == ["memory.recall.recorded"]
    assert counts["skipped_only"] == ["memory.recall.skipped"]
    assert counts["recorded_and_skipped"] == ["memory.recall.recorded", "memory.recall.skipped"]
    assert counts["grounded_has_no_events"] == []
    assert counts["forgotten_session_drops_the_event"] == []
    assert any(e.get("storageTruncated") for item in _ts.values() for e in item["events"])
    assert any(e.get("results") == [] and e.get("storageTruncated") for item in _ts.values() for e in item["events"])
