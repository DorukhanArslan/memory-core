"""Oracle test of the dreaming session ingestion against OpenClaw v2026.9.6.

One real-TS run (``sessionIngestionScenarios``), replayed in Python
(``memory_core.consolidation.session_ingestion``):

- ``scan`` scenarios: ``scanSessionIngestionSource`` over JSONL transcript files (the real
  ``session-ingestion.ts``), step after step with the checkpoint and the seen hashes chained like the
  sweep does: first scan, the unchanged fingerprint, appends found through the prefix hash, a rewritten
  prefix, the per-file cap and its cursor, include/skip/block days, short and noisy messages, foreign
  (untrusted) sources, excluded (cron and dreaming) sessions, a vanished file; plus seeded random
  transcripts;
- ``sweep`` scenarios: the real ``ingestSessionTranscriptSignals`` over sessions seeded in OpenClaw's
  SQLite session store (tombstones, an admission policy, the 14 and 30 day windows, the per-sweep
  cap, several agents), against the same transcripts as JSONL files behind a host-supplied corpus
  (``transcript_source="sqlite"``: the host's store, as upstream's SQLite branch).

The recall store, the session corpus files, the origins ledger, the checkpoint (without the
file mtimes and sizes, which a SQLite revision makes incomparable) and the host events must agree.
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
from memory_core.consolidation.session_ingestion import (
    SessionCorpusEntry,
    SessionIngestionFileState,
    foreign_session_ingestion_source,
    ingest_session_transcript_signals,
    merge_tracked_message_hashes,
    read_session_ingestion_state,
    resolve_admission_policy,
    scan_session_ingestion_source,
    session_ingestion_source_from_corpus,
)

DAY_MS = 86_400_000
NOW_MS = 1779811200000  # 2026-05-26T16:00:00Z
TZ = "Europe/Istanbul"
STORE = "memory/.dreams/short-term-recall.json"


def _oracle() -> OpenClawOracle:
    return OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=900)


# --- transcript helpers ------------------------------------------------------------------------


def _msg(role: str, text: Any, days_ago: float = 0, hour: float = 0, **extra: Any) -> dict[str, Any]:
    return {
        "role": role,
        "content": text,
        "timestamp": int(NOW_MS - days_ago * DAY_MS + hour * 3_600_000),
        **extra,
    }


def _record(message: dict[str, Any]) -> dict[str, Any]:
    return {"type": "message", "message": message}


FACTS = [
    "The staging cluster was rebuilt on Tuesday after the failed upgrade.",
    "Rotate the signing keys every thirty days and record the date here.",
    "Backups run nightly at two in the morning and are kept for a week.",
    "The on-call engineer pages the database owner for replication lag.",
    "Release notes live in the wiki under the engineering handbook page.",
    "short",
    "tiny one",
    "Customer asked about invoicing; the answer is net thirty by default.",
    "Unicode check: ümläuts, emoji \U0001f600 and a long tail " + "\U0001f600" * 120,
    "A very long line " + "word " * 120,
    "  spaced   out\ttext\nwith   newlines   inside it for the collapse  ",
]


def _scan_step(agent: str, session: str, **over: Any) -> dict[str, Any]:
    return {"kind": "scan", "agentId": agent, "sessionId": session, "chain": True, **over}


def _write_step(agent: str, session: str, messages: list[dict[str, Any]], mtime: int, **over: Any) -> dict[str, Any]:
    return {
        "kind": "write",
        "agentId": agent,
        "sessionId": session,
        "records": [_record(m) for m in messages],
        "mtimeMs": mtime,
        **over,
    }


def _messages(n: int, rng: random.Random | None = None, days: tuple[float, ...] = (0, 1, 2)) -> list[dict[str, Any]]:
    rng = rng or random.Random(n)
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append(_msg(role, rng.choice(FACTS) + f" #{i}", days_ago=rng.choice(days), hour=i * 0.01))
    return out


def _scan_scenarios() -> dict[str, list[dict[str, Any]]]:
    base = _messages(10)
    extra = base + _messages(4, random.Random(99))
    scenarios: dict[str, list[dict[str, Any]]] = {
        "first_scan_unchanged_append": [
            _write_step("main", "s1", base, NOW_MS - 5000),
            _scan_step("main", "s1"),
            _scan_step("main", "s1"),
            _write_step("main", "s1", extra, NOW_MS - 4000),
            _scan_step("main", "s1"),
            _scan_step("main", "s1"),
        ],
        "rewritten_prefix_rescans": [
            _write_step("main", "s1", base, NOW_MS - 5000),
            _scan_step("main", "s1"),
            _write_step("main", "s1", [_msg("user", "Edited first message with entirely different text.", 0, 0.5), *base[1:]], NOW_MS - 4000),
            _scan_step("main", "s1"),
            _scan_step("main", "s1", verifyContent=True),
        ],
        "per_file_cap_cursor": [
            _write_step("main", "s1", _messages(30), NOW_MS - 5000),
            *[_scan_step("main", "s1", maxCandidates=7) for _ in range(6)],
        ],
        "day_rules": [
            _write_step("main", "s1", _messages(24, days=(0, 1, 2, 3)), NOW_MS - 5000),
            _scan_step("main", "s1", includeDays=["2026-05-26", "2026-05-25"], blockDays=["2026-05-24"]),
            _scan_step("main", "s1", includeDays=[]),
            _scan_step("main", "s1", includeDays=["2026-05-23"], blockDays=["2026-05-26"], chain=False),
        ],
        "short_empty_and_noise": [
            _write_step("main", "e1", [], NOW_MS - 5000),
            _scan_step("main", "e1"),
            _write_step(
                "main",
                "n1",
                [
                    _msg("user", "short"),
                    _msg("user", "Inter session user message that must be dropped.", provenance={"kind": "inter_session"}),
                    _msg("user", "Heartbeat prompt that must be dropped from the export.", provenance={"kind": "internal_system", "sourceTool": "heartbeat"}),
                    _msg("assistant", "Reply inside the heartbeat turn that is dropped as well."),
                    _msg("user", "Recalled memory text that must be dropped.", provenance={"kind": "internal_system", "sourceTool": "memory_search"}),
                    _msg("assistant", "Reply inside the recalled memory turn is dropped too."),
                    _msg("user", "A real user question about the deployment pipeline."),
                    _msg("assistant", "A real assistant answer about the deployment pipeline."),
                    _msg("assistant", [{"type": "text", "text": "Block content with a text part that is long enough."}]),
                    _msg("assistant", [{"type": "toolCall", "name": "x"}]),
                    {"role": "system", "content": "System rows never export anywhere."},
                    _msg("user", "No timestamp on this message so the file time decides.", **{}),
                ],
                NOW_MS - 3_000_000,
            ),
            _scan_step("main", "n1"),
        ],
        "foreign_source_is_untrusted": [
            _write_step("main", "f1", _messages(8), NOW_MS - 5000),
            _scan_step("main", "f1", foreign=True, chain=False),
            _scan_step("main", "f1", chain=False),
        ],
        "accept_provenance_filter": [
            _write_step(
                "main",
                "p1",
                [
                    _msg("user", "Owner style message with enough characters in it.", __openclaw={"turnTainted": False}),
                    _msg("user", "Tainted message with enough characters in it here.", __openclaw={"turnTainted": True}),
                    _msg("assistant", "Assistant message with enough characters in it too."),
                ],
                NOW_MS - 5000,
            ),
            _scan_step("main", "p1", chain=False, acceptOrigins=["owner"]),
            _scan_step("main", "p1", chain=False, acceptOrigins=["untrusted", "agent"]),
            _scan_step("main", "p1", chain=False),
        ],
        "excluded_sessions": [
            _write_step("main", "c1", _messages(6), NOW_MS - 5000),
            _scan_step("main", "c1", chain=False, generatedByCronRun=True),
            _scan_step("main", "c1", chain=False, generatedByDreamingNarrative=True),
            _scan_step("main", "c1", chain=False, sessionKind="cron"),
            _scan_step("main", "c1", chain=False, sessionKey="agent:main:c1"),
        ],
        "absent_then_present": [
            _scan_step("main", "gone"),
            _write_step("main", "gone", _messages(6), NOW_MS - 5000),
            _scan_step("main", "gone"),
            {"kind": "remove", "agentId": "main", "sessionId": "gone"},
            _scan_step("main", "gone"),
        ],
        "dreaming_marker_inside_transcript": [
            _write_step(
                "main",
                "d1",
                [
                    _msg("user", "A normal message before the dreaming run starts here."),
                    {"type": "custom", "customType": "openclaw:bootstrap-context:full", "data": {"runId": "dreaming-narrative-light-1"}},
                    _msg("user", "Message after the dreaming marker is excluded now."),
                ],
                NOW_MS - 5000,
            ),
            _scan_step("main", "d1"),
        ],
    }
    rng = random.Random(20261003)
    for index in range(24):
        steps: list[dict[str, Any]] = []
        messages: list[dict[str, Any]] = []
        mtime = NOW_MS - 100_000
        for round_ in range(rng.randint(2, 5)):
            messages = messages + _messages(rng.randint(1, 14), rng, days=(0, 0, 1, 2, 5))
            if rng.random() < 0.2 and messages:
                messages[rng.randrange(len(messages))] = _msg("user", "Edited in place " + rng.choice(FACTS), 1)
            mtime += 1000 * rng.randint(1, 9)
            steps.append(_write_step("main", "r1", messages, mtime))
            for _ in range(rng.randint(1, 3)):
                steps.append(
                    _scan_step(
                        "main",
                        "r1",
                        **({"maxCandidates": rng.randint(1, 9)} if rng.random() < 0.5 else {}),
                        **({"includeDays": ["2026-05-26", "2026-05-25", "2026-05-24"]} if rng.random() < 0.4 else {}),
                        **({"blockDays": ["2026-05-21"]} if rng.random() < 0.2 else {}),
                        **({"verifyContent": True} if rng.random() < 0.15 else {}),
                    )
                )
        scenarios[f"random_{index:02d}"] = steps
    return scenarios


# --- sweep scenarios ---------------------------------------------------------------------------


def _session(agent: str, session: str, messages: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    return {"kind": "session", "agentId": agent, "sessionId": session, "messages": messages, **over}


def _via(channel: str) -> dict[str, Any]:
    """The session entry fields OpenClaw derives ``channel`` from (``sessionDeliveryChannel``)."""
    return {"delivery": {"kind": "external", "context": {"channel": channel}, "origin": {"provider": channel}}}


def _ingest(offset_days: float = 0, lookback: int = 14) -> dict[str, Any]:
    return {"kind": "ingest", "lookbackDays": lookback, "nowMs": int(NOW_MS + offset_days * DAY_MS)}


def _sweep_scenarios() -> dict[str, dict[str, Any]]:
    return {
        "two_sessions_idempotent_and_append": {
            "agents": ["ing-a"],
            "steps": [
                _session("ing-a", "s1", _messages(10)),
                _session("ing-a", "s2", _messages(6, random.Random(5))),
                _ingest(),
                _ingest(),
                {"kind": "append", "agentId": "ing-a", "sessionId": "s1", "messages": _messages(4, random.Random(77))},
                _ingest(),
                _ingest(1),
            ],
        },
        "tombstoned_session_is_excluded": {
            "agents": ["ing-b"],
            "steps": [
                _session("ing-b", "s1", _messages(8)),
                _session("ing-b", "s2", _messages(8, random.Random(6))),
                {"kind": "tombstone", "agentId": "ing-b", "sessionIds": ["s1"]},
                _ingest(),
                {"kind": "tombstone", "agentId": "ing-b", "sessionIds": ["s2"]},
                _ingest(),
            ],
        },
        "forgotten_after_ingestion": {
            "agents": ["ing-c"],
            "steps": [
                _session("ing-c", "s1", _messages(8)),
                _ingest(),
                {"kind": "tombstone", "agentId": "ing-c", "sessionIds": ["s1"]},
                _ingest(),
            ],
        },
        "lookback_windows": {
            "agents": ["ing-d"],
            "steps": [
                _session("ing-d", "s1", _messages(20, days=(0, 3, 9, 13, 16, 20))),
                _ingest(0, 14),
                _ingest(0, 30),
                _ingest(0, 3),
            ],
        },
        "non_interactive_sessions": {
            "agents": ["ing-e"],
            "steps": [
                _session("ing-e", "s1", _messages(6)),
                _session("ing-e", "cron1", _messages(6, random.Random(8)), sessionKey="agent:ing-e:cron:job1"),
                _session("ing-e", "sub1", _messages(6, random.Random(9)), sessionKey="agent:ing-e:subagent:task1"),
                _ingest(),
            ],
        },
        "admission_policy": {
            "agents": ["ing-f"],
            "pluginConfig": {
                "memoryPolicy": {"excludeSessions": {"channels": ["slack"], "chatTypes": ["group"], "hookExternalContentSources": []}}
            },
            "steps": [
                _session("ing-f", "s1", _messages(6), entry=_via("slack")),
                _session("ing-f", "s2", _messages(6, random.Random(3)), entry={**_via("telegram"), "chatType": "group"}),
                _session("ing-f", "s3", _messages(6, random.Random(4)), entry={**_via("telegram"), "chatType": "direct"}),
                _session("ing-f", "s4", _messages(6, random.Random(12))),
                _ingest(),
            ],
        },
        "per_sweep_cap": {
            "agents": ["ing-g"],
            "steps": [
                *[_session("ing-g", f"s{i}", _messages(120, random.Random(i))) for i in range(1, 4)],
                _ingest(),
                _ingest(),
                _ingest(),
                _ingest(),
            ],
        },
        "two_agents_one_workspace": {
            "agents": ["ing-h1", "ing-h2"],
            "steps": [
                _session("ing-h1", "s1", _messages(6)),
                _session("ing-h2", "s1", _messages(6, random.Random(21))),
                {"kind": "tombstone", "agentId": "ing-h2", "sessionIds": ["s1"]},
                _ingest(),
            ],
        },
        "noise_and_dedupe": {
            "agents": ["ing-i"],
            "steps": [
                _session(
                    "ing-i",
                    "s1",
                    [
                        _msg("user", "Same sentence appears twice in this transcript, record once."),
                        _msg("assistant", "Same sentence appears twice in this transcript, record once."),
                        _msg("user", "Heartbeat prompt dropped from this export entirely.", provenance={"kind": "internal_system", "sourceTool": "heartbeat"}),
                        _msg("user", "A different message that is long enough to count."),
                    ],
                ),
                _ingest(),
                _ingest(2),
            ],
        },
    }


# --- the oracle run ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _ts(tmp_path_factory):
    root = tmp_path_factory.mktemp("session-ingestion-ts")
    payload: list[dict[str, Any]] = []
    for name, steps in _scan_scenarios().items():
        payload.append({"name": name, "kind": "scan", "workspaceDir": str(root / f"ts-{name}"), "steps": steps})
    for name, scenario in _sweep_scenarios().items():
        workspace = root / f"ts-{name}"
        (workspace / "memory").mkdir(parents=True, exist_ok=True)
        payload.append(
            {
                "name": name,
                "kind": "sweep",
                "workspaceDir": str(workspace),
                "agentIds": scenario["agents"],
                "pluginConfig": scenario.get("pluginConfig"),
                "steps": scenario["steps"],
            }
        )
    response = _oracle().run(
        {"operation": "sessionIngestionScenarios", "timezone": TZ, "nowMs": NOW_MS, "sessionScenarios": payload}
    )
    assert response["ok"] is True, response.get("error")
    results = {item["name"]: item for item in response["result"]["scenarios"]}
    results["__root__"] = {"path": str(root)}
    return results


# --- scan replay -------------------------------------------------------------------------------


def _candidate_json(candidate: Any) -> dict[str, Any]:
    out = {
        "day": candidate.day,
        "snippet": candidate.snippet,
        "rendered": candidate.rendered,
        "provenance": dict(candidate.provenance),
        "contentIndex": candidate.content_index,
        "hash": candidate.hash,
        "lineNumber": candidate.line_number,
        "scope": candidate.scope,
        "stateKey": candidate.state_key,
    }
    if candidate.session_origin:
        out["sessionOrigin"] = dict(candidate.session_origin)
    return out


def _state_from_json(raw: dict[str, Any] | None) -> SessionIngestionFileState | None:
    if raw is None:
        return None
    return SessionIngestionFileState(
        raw["mtimeMs"],
        raw["size"],
        raw["contentHash"],
        raw["lineCount"],
        raw["lastContentLine"],
        raw.get("excludedReason"),
    )


def _ts_root(ts: dict[str, Any]) -> str:
    return ts["root"]


def _replay_scan(name: str, steps: list[dict[str, Any]], tmp_path: Path, ts: dict[str, Any]) -> None:
    # A foreign source's scope holds the absolute path, so the replay reuses the oracle's directory.
    workspace = Path(_ts_root(ts)) / f"ts-{name}"
    previous: SessionIngestionFileState | None = None
    seen: dict[str, list[str]] = {}
    for index, (step, expected) in enumerate(zip(steps, ts["steps"], strict=True)):
        label = f"{name} step {index} ({step['kind']})"
        assert expected["error"] is None, (label, expected["error"])
        target = workspace / "agents" / step["agentId"] / "sessions" / f"{step['sessionId']}.jsonl"
        if step["kind"] == "write":
            target.parent.mkdir(parents=True, exist_ok=True)
            records = step["records"]
            target.write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in records), "utf-8")
            os.utime(target, ns=(step["mtimeMs"] * 1_000_000, step["mtimeMs"] * 1_000_000))
            continue
        if step["kind"] == "remove":
            target.unlink(missing_ok=True)
            continue
        if step.get("foreign"):
            source = foreign_session_ingestion_source(step["agentId"], str(target))
        else:
            source = session_ingestion_source_from_corpus(
                SessionCorpusEntry(
                    agent_id=step["agentId"],
                    session_id=step["sessionId"],
                    session_file=str(target),
                    session_key=step.get("sessionKey"),
                    session_kind=step.get("sessionKind", "interactive"),
                    generated_by_cron_run=bool(step.get("generatedByCronRun")),
                    generated_by_dreaming_narrative=bool(step.get("generatedByDreamingNarrative")),
                )
            )
        blocked = set(step.get("blockDays", []))
        included = set(step["includeDays"]) if "includeDays" in step else None
        accept = step.get("acceptOrigins")
        if source is None:
            assert expected["result"] is None, label
            continue
        scan = scan_session_ingestion_source(
            source=source,
            previous=previous if step.get("chain") else _state_from_json(step.get("previous")),
            seen_messages=seen if step.get("chain") else step.get("seen", {}),
            timezone=TZ,
            max_candidates=step.get("maxCandidates"),
            verify_content=step.get("verifyContent", False),
            accept_provenance=(lambda p, accept=accept: p["originClass"] in accept) if accept is not None else None,
            classify_day=lambda day: "block" if day in blocked else ("include" if included is None or day in included else "skip"),
        )
        if step.get("chain"):
            if scan.file_state is not None:
                previous = scan.file_state
            if scan.candidates:
                seen[source.scope] = merge_tracked_message_hashes(
                    seen.get(source.scope, []), [c.hash for c in scan.candidates]
                )
        got = {
            "status": scan.status,
            "candidates": [_candidate_json(c) for c in scan.candidates],
            "scannedEndIndex": scan.scanned_end_index,
        }
        if scan.file_state is not None:
            got["fileState"] = scan.file_state.to_json()
        if scan.progress_block_index is not None:
            got["progressBlockIndex"] = scan.progress_block_index
        want = expected["result"]["scan"]
        assert got == want, (label, _first_difference(got, want))
        assert source.scope == expected["result"]["scope"] and source.state_key == expected["result"]["stateKey"], label


@pytest.mark.parametrize("name", sorted(_scan_scenarios()))
def test_session_scan_matches_openclaw(name: str, _ts, tmp_path: Path) -> None:
    _replay_scan(name, _scan_scenarios()[name], tmp_path, {**_ts[name], "root": _ts["__root__"]["path"]})


def test_scan_scenarios_exercise_the_branches(_ts) -> None:
    def results(name: str) -> list[dict[str, Any]]:
        return [s["result"]["scan"] for s in _ts[name]["steps"] if s["result"]]

    first = results("first_scan_unchanged_append")
    assert [r["status"] for r in first] == ["scanned", "unchanged", "scanned", "unchanged"]
    assert len(first[2]["candidates"]) > 0
    assert any(r["status"] == "excluded" for r in results("excluded_sessions"))
    assert any(r["status"] == "absent" for r in results("absent_then_present"))
    assert any("progressBlockIndex" in r for r in results("day_rules"))
    foreign = results("foreign_source_is_untrusted")
    assert {c["provenance"]["originClass"] for c in foreign[0]["candidates"]} == {"untrusted"}
    capped = results("per_file_cap_cursor")
    assert sum(len(r["candidates"]) for r in capped) > 20


# --- sweep replay ------------------------------------------------------------------------------


def _strip_files(state: dict[str, Any]) -> dict[str, Any]:
    files = {
        key: {k: v for k, v in value.items() if k not in ("mtimeMs", "size")}
        for key, value in state["files"].items()
    }
    return {**state, "files": files}


def _recall_entries(workspace: Path) -> dict[str, Any]:
    path = workspace / STORE
    text = path.read_text("utf-8") if path.exists() else ""
    return dict(sorted(json.loads(text)["entries"].items())) if text else {}


def _origin_json(origin: Any) -> dict[str, Any]:
    return {
        "entryKey": origin.entry_key,
        "agentId": origin.agent_id,
        "sessionId": origin.session_id,
        "sessionKey": origin.session_key,
        "originClass": origin.origin_class,
        "observedAt": origin.observed_at,
    }


@pytest.mark.parametrize("name", sorted(_sweep_scenarios()))
def test_session_sweep_matches_openclaw(name: str, _ts, tmp_path: Path) -> None:
    scenario = _sweep_scenarios()[name]
    ts = _ts[name]
    workspace = tmp_path / f"py-{name}"
    (workspace / "memory").mkdir(parents=True, exist_ok=True)
    transcripts: dict[tuple[str, str], list[dict[str, Any]]] = {}
    session_entries: dict[tuple[str, str], dict[str, Any]] = {}
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / "agents" / f"{agent}.sqlite")
    config = MemoryConfig(workspace_dir=workspace, store_path=tmp_path / f"{name}.sqlite")
    policy = resolve_admission_policy(scenario.get("pluginConfig"))
    events: list[dict[str, Any]] = []

    def transcript_file(agent: str, session: str) -> Path:
        target = tmp_path / "py-sessions" / name / agent / f"{session}.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = transcripts.get((agent, session), [])
        # OpenClaw's SQLite events start with the session header, so message line numbers start at 2.
        header = json.dumps({"type": "session", "id": session}, separators=(",", ":")) + "\n"
        target.write_text(header + "".join(json.dumps(_record(m), ensure_ascii=False, separators=(",", ":")) + "\n" for m in rows), "utf-8")
        return target

    def metadata(origin: Any, _store: Any) -> dict[str, Any] | None:
        entry = session_entries.get((origin["agentId"], origin["sessionId"]))
        if entry is None:
            return None
        delivery = entry.get("delivery") or {}
        return {
            "channel": (delivery.get("context") or {}).get("channel"),
            "chatType": entry.get("chatType"),
            "hookExternalContentSource": entry.get("hookExternalContentSource"),
        }

    for index, (step, expected) in enumerate(zip(scenario["steps"], ts["steps"], strict=True)):
        label = f"{name} step {index} ({step['kind']})"
        assert expected["error"] is None, (label, expected["error"])
        kind = step["kind"]
        if kind == "session":
            transcripts[(step["agentId"], step["sessionId"])] = list(step["messages"])
            session_entries[(step["agentId"], step["sessionId"])] = dict(step.get("entry", {}))
        elif kind == "append":
            transcripts[(step["agentId"], step["sessionId"])].extend(step["messages"])
        elif kind == "tombstone":
            ledger.record_session_tombstones(step["agentId"], step["sessionIds"], created_at=1)
        elif kind == "ingest":
            corpus = {
                (e["agentId"], e["sessionId"]): e for e in expected["corpusEntries"]
            }  # what OpenClaw's own corpus enumeration reports after this step

            def entries_for(agent: str, corpus: dict = corpus) -> list[SessionCorpusEntry]:
                return [
                    SessionCorpusEntry(
                        agent_id=e["agentId"],
                        session_id=e["sessionId"],
                        session_file=str(transcript_file(e["agentId"], e["sessionId"])),
                        session_key=e["sessionKey"],
                        session_kind=e["sessionKind"],
                        artifact_kind=e["artifactKind"],
                        transcript_source="sqlite",
                        generated_by_dreaming_narrative=e["generatedByDreamingNarrative"],
                        generated_by_cron_run=e["generatedByCronRun"],
                    )
                    for (a, _s), e in sorted(corpus.items())
                    if a == agent
                ]

            ingest_session_transcript_signals(
                config=config,
                agent_ids=sorted(scenario["agents"]),
                corpus_entries=entries_for,
                lookback_days=step["lookbackDays"],
                now_ms=step["nowMs"],
                timezone=TZ,
                admission_policy=policy,
                origins=ledger,
                load_session_metadata=metadata,
                on_event=events.append,
            )
            corpus_dir = workspace / "memory" / ".dreams" / "session-corpus"
            got_corpus = {p.name: p.read_text("utf-8") for p in sorted(corpus_dir.glob("*"))} if corpus_dir.exists() else {}
            assert got_corpus == expected["corpus"], label
            assert _recall_entries(workspace) == expected["recall"], label
            got_state = read_session_ingestion_state(workspace).to_json()
            assert _strip_files(got_state) == _strip_files(expected["state"]), label
            assert {
                agent: [_origin_json(o) for o in ledger.list(agent)] for agent in scenario["agents"]
            } == expected["origins"], label
    assert events == ts["events"], name


def test_sweep_scenarios_exercise_the_branches(_ts) -> None:
    def last(name: str) -> dict[str, Any]:
        return [s for s in _ts[name]["steps"] if "state" in s][-1]

    assert last("two_sessions_idempotent_and_append")["corpus"]
    tomb = last("tombstoned_session_is_excluded")["state"]["files"]
    assert {v.get("excludedReason") for v in tomb.values()} == {"forgotten"}
    assert any(v.get("excludedReason") == "forgotten" for v in last("forgotten_after_ingestion")["state"]["files"].values())
    assert last("per_sweep_cap")["corpus"]
    policy = last("admission_policy")["state"]["files"]
    assert any(str(v.get("excludedReason", "")).startswith("channel:") for v in policy.values())
    assert any(str(v.get("excludedReason", "")).startswith("chatType:") for v in policy.values())
    assert last("noise_and_dedupe")["recall"]


def _first_difference(got: Any, want: Any, path: str = "") -> str | None:
    if isinstance(got, dict) and isinstance(want, dict):
        for key in sorted(set(got) | set(want)):
            if key not in got or key not in want:
                return f"{path}/{key}: only in {'want' if key not in got else 'got'}"
            found = _first_difference(got[key], want[key], f"{path}/{key}")
            if found:
                return found
        return None
    if isinstance(got, list) and isinstance(want, list):
        if len(got) != len(want):
            return f"{path}: length {len(got)} != {len(want)}"
        for index, (a, b) in enumerate(zip(got, want, strict=True)):
            found = _first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
        return None
    return None if got == want else f"{path}: {got!r} != {want!r}"
