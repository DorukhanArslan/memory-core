"""Oracle test of the memory forget flow against OpenClaw v2026.9.6.

One real-TS run (``forgetScenarios``: ``forgetMemoryEntries`` of ``memory-forget.ts`` over seeded
workspaces: memory files with promotion and lineage markers, session corpus files, the recall and
phase-signal stores, the session-ingestion checkpoint, consolidation preimages, origin rows, trust
records, sessions in OpenClaw's SQLite session store and index chunks), replayed in Python
(``memory_core.consolidation.forget``). After every forget call the report, the rewritten files, the
stores, the origin rows, the tombstones, the index rows left and the revision fence must agree.

Scenarios: named cases (entries, sections, corpus quotes, mixed lineage, tombstoned twice, session keys,
unresolved sessions, hook sources, the consolidation-history refusal, curated writes found in a
transcript, an index purge) and seeded random workspaces. Not reachable through the oracle (unit tested
in tests/unit/test_forget.py): ``since`` (the creation time of a seeded session is the oracle's clock),
participant selectors (they come from a separate participants table) and retained archives.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import random
import time
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.consolidation.forget import SessionInstance, forget_memory_entries
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger
from memory_core.consolidation.session_ingestion import (
    SessionCorpusEntry,
    SessionIngestionFileState,
    SessionIngestionState,
    read_session_ingestion_state,
    write_session_ingestion_state,
)
from memory_core.index.sqlite_store import SQLiteMemoryStore

NOW_MS = 1779811200000
STORE = "memory/.dreams/short-term-recall.json"
PHASE = "memory/.dreams/phase-signals.json"
PRE = "openclaw-memory-promotion:"
LIN = "openclaw-memory-lineage:"
CORPUS = "memory/.dreams/session-corpus"


def _oracle() -> OpenClawOracle:
    return OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=900)


# --- fixtures ----------------------------------------------------------------------------------


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def _recall_entry(key: str, path: str, snippet: str, **over: Any) -> dict[str, Any]:
    now = _now_iso()
    entry = {
        "key": key,
        "path": path,
        "startLine": 1,
        "endLine": 1,
        "source": "memory",
        "snippet": snippet,
        "recallCount": 1,
        "dailyCount": 0,
        "groundedCount": 0,
        "totalScore": 0.8,
        "maxScore": 0.8,
        "firstRecalledAt": now,
        "lastRecalledAt": now,
        "queryHashes": ["abc"],
        "recallDays": ["2026-05-08"],
        "conceptTags": [],
    }
    entry.update(over)
    return entry


def _phase_entry(key: str) -> dict[str, Any]:
    now = _now_iso()
    return {"key": key, "lightHits": 1, "remHits": 0, "lastLightAt": now, "lastRemAt": None, "updatedAt": now}


def _json_file(entries: dict[str, Any]) -> str:
    return json.dumps({"version": 1, "updatedAt": _now_iso(), "entries": entries}, indent=2) + "\n"


def _promo(key: str, text: str, *, lineage: str | None = None, extra: list[str] | None = None) -> str:
    lines = []
    if lineage:
        lines.append(f"<!-- {LIN}{lineage} -->")
    lines.append(f"<!-- {PRE}{key} -->")
    lines.append(text)
    lines.extend(extra or [])
    return "\n".join(lines)


def _origin(entry_key: str, agent: str, session: str, klass: str = "owner", at: int = 1000) -> dict[str, Any]:
    return {
        "entryKey": entry_key,
        "agentId": agent,
        "sessionId": session,
        "sessionKey": f"agent:{agent}:{session}",
        "originClass": klass,
        "observedAt": at,
    }


def _msg(role: str, content: Any, day: int = 0) -> dict[str, Any]:
    return {"role": role, "content": content, "timestamp": NOW_MS - day * 86_400_000}


def _tool_call(name: str, **arguments: Any) -> dict[str, Any]:
    return {"type": "toolCall", "id": "c1", "name": name, "arguments": arguments}


def _basic(agent: str) -> dict[str, Any]:
    k1, k2, k3, k4 = (f"memory:memory/2026-05-0{d}.md:{line}:{line}" for d, line in ((8, 3), (8, 5), (9, 2), (9, 7)))
    memory = "\n".join(
        [
            "# Memory",
            "",
            _promo(k1, "- Backups run nightly.", extra=["  Second line of the entry text."]),
            _promo(k2, "- Keys rotate monthly.", lineage="lin-1"),
            _promo(k3, "- Shared fact from two sessions."),
            _promo(k4, "- Fact only from the other session."),
            _promo("memory:stray", "- Entry with no origin rows."),
            "",
            f"## Imported from {agent}:s1",
            "",
            "Details copied from the session.",
            "",
            "## Unrelated section",
            "Keep this.",
            "",
        ]
    )
    daily = "\n".join(
        [
            "# 2026-05-08",
            "",
            "- Backups run nightly.",
            "- Note from a session. Session ID: s1",
            "- Another bullet",
            "  - Session ID: s1",
            "  - child bullet row",
            f"## Section about {agent}:s1",
            "body of section",
            "more body",
            "## Next section",
            "keep",
            "",
        ]
    )
    corpus_1 = "\n".join(
        [
            f"[{agent}/sessions/{agent}/s1#L1] User: Remember that the backups run nightly at two.",
            f"[{agent}/sessions/{agent}/s2#L1] User: The other session talks about invoices today.",
            f"[{agent}/sessions/{agent}/s1#L2] Assistant: Short row",
            "",
        ]
    )
    corpus_2 = "\n".join(
        [
            f"[{agent}/sessions/{agent}/s1#L5] User: Everything here belongs to the forgotten session.",
            f"[{agent}/sessions/{agent}/s1#L6] Assistant: Also this whole line goes away.",
        ]
    )
    quoted = "# 2026-05-09\n\n- Quoted: User: Remember that the backups run nightly at two.\n- Unrelated bullet.\n"
    recall = {
        k1: _recall_entry(k1, "memory/2026-05-08.md", "Backups run nightly."),
        k3: _recall_entry(k3, "memory/2026-05-09.md", "Shared fact from two sessions."),
        k4: _recall_entry(k4, "memory/2026-05-09.md", "Fact only from the other session."),
        "memory:corpus:1": _recall_entry(
            "memory:corpus:1", f"{CORPUS}/2026-05-08.txt", "User: Remember that the backups run nightly at two."
        ),
        "memory:corpus:2": _recall_entry(
            "memory:corpus:2", "memory/2026-05-08.md", f"see sessions/{agent}/s1.jsonl for details"
        ),
        "memory:corpus:3": _recall_entry("memory:corpus:3", "memory/2026-05-10.md", "Unrelated recall entry."),
    }
    phase = {key: _phase_entry(key) for key in (k1, k3, "memory:corpus:1", "memory:corpus:3")}
    backup_content = "# Memory\n\n" + _promo(k1, "- Backups run nightly.") + "\n" + _promo(k4, "- Other.") + "\n"
    return {
        "files": {
            "MEMORY.md": memory,
            "memory/2026-05-08.md": daily,
            "memory/2026-05-09.md": quoted,
            f"{CORPUS}/2026-05-08.txt": corpus_1,
            f"{CORPUS}/2026-05-09.txt": corpus_2,
            "DREAMS.md": f"# Dreams\n\n## A dream about {agent}:s1\nsome diary text\n\n## Another dream\nstays\n",
            STORE: _json_file(recall),
            PHASE: _json_file(phase),
        },
        "origins": [
            _origin(k1, agent, "s1"),
            _origin(k2, agent, "s1"),
            _origin(k3, agent, "s1"),
            _origin(k3, agent, "s2", "agent", 2000),
            _origin(k4, agent, "s2", "agent", 2000),
        ],
        "sessionIngestion": {
            "files": {
                f"{agent}:sessions/{agent}/s1": {
                    "mtimeMs": 5,
                    "size": 5,
                    "contentHash": "h1",
                    "lineCount": 3,
                    "lastContentLine": 3,
                },
                f"{agent}:sessions/{agent}/s2": {
                    "mtimeMs": 6,
                    "size": 6,
                    "contentHash": "h2",
                    "lineCount": 2,
                    "lastContentLine": 2,
                },
            },
            "seenMessages": {f"{agent}:sessions/{agent}/s1": ["a1", "a2"], f"{agent}:sessions/{agent}/s2": ["b1"]},
        },
        "backups": [
            {"createdAt": "2026-05-01T00:00:00.000Z", "content": backup_content, "contentHash": hashlib.sha256(backup_content.encode()).hexdigest()},
            {"createdAt": "2026-05-02T00:00:00.000Z", "content": "# Memory\nplain\n", "contentHash": hashlib.sha256(b"# Memory\nplain\n").hexdigest()},
        ],
        "sessions": [
            {"sessionId": "s1", "messages": [_msg("user", "Please remember the backups run nightly at two."), _msg("assistant", [_tool_call("write", path="memory/2026-05-08.md", content="x"), _tool_call("edit", file_path="MEMORY.md")])]},
            {"sessionId": "s2", "messages": [_msg("user", "Another session about invoices and other things.")]},
        ],
        "provenance": [
            {"relativePath": "memory/2026-05-08.md", "contentAfter": "x", "originClass": "agent", "observedAt": 5, "sessionId": "s1"},
            {"relativePath": "memory/2026-05-09.md", "contentAfter": "y", "originClass": "untrusted", "observedAt": 6, "sessionKey": f"agent:{agent}:s1"},
            {"relativePath": "memory/2026-05-10.md", "contentAfter": "z", "originClass": "agent", "observedAt": 7, "sessionId": "s2"},
        ],
        "chunks": [
            {"path": "MEMORY.md", "source": "memory", "text": "alpha chunk of memory"},
            {"path": "MEMORY.md", "source": "memory", "text": "beta chunk"},
            {"path": "memory/2026-05-08.md", "source": "memory", "text": "daily chunk"},
            {"path": "memory/2026-05-10.md", "source": "memory", "text": "untouched chunk"},
            {"path": f"sessions/{agent}/s1", "source": "sessions", "text": "session one transcript"},
            {"path": f"sessions/{agent}/s1.jsonl", "source": "sessions", "text": "legacy session path"},
            {"path": f"sessions/{agent}/s2", "source": "sessions", "text": "session two transcript"},
            {"path": f"{CORPUS}/2026-05-09.txt", "source": "sessions", "text": "corpus two"},
            {"path": f"{CORPUS}/2026-05-08.txt", "source": "sessions", "text": "corpus one"},
        ],
        "sources": [
            {"path": "MEMORY.md", "source": "memory"},
            {"path": f"sessions/{agent}/s1", "source": "sessions"},
            {"path": f"{CORPUS}/2026-05-09.txt", "source": "sessions"},
            {"path": f"{CORPUS}/2026-05-08.txt", "source": "sessions"},
            {"path": f"sessions/{agent}/s2", "source": "sessions"},
        ],
    }


@functools.cache
def _scenarios() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    agent = "fg-basic"
    out[agent] = {**_basic(agent), "runs": [{"sessionIds": ["s1"], "dryRun": True}, {"sessionIds": ["s1"]}, {"sessionIds": ["s1"]}]}
    agent = "fg-both"
    out[agent] = {**_basic(agent), "runs": [{"sessionIds": ["s1", "s2"]}]}
    agent = "fg-key"
    out[agent] = {**_basic(agent), "runs": [{"sessionIds": [f"agent:{agent}:s2"]}]}
    agent = "fg-unresolved"
    out[agent] = {**_basic(agent), "runs": [{"sessionIds": ["ghost", "s2"]}, {"sessionIds": ["ghost"]}]}
    agent = "fg-pre-tombstoned"
    out[agent] = {**_basic(agent), "tombstones": ["s1"], "runs": [{"sessionIds": ["s1"]}]}
    agent = "fg-selectors-missing"
    out[agent] = {**_basic(agent), "runs": [{}]}
    agent = "fg-history"
    scenario = _basic(agent)
    scenario["files"]["DREAMS.md"] += "\n## Memory Consolidation History\n- run one\n  - `+ A highlighted fact`\n  - `- Removed fact`\n"
    out[agent] = {**scenario, "runs": [{"sessionIds": ["s1"]}]}
    agent = "fg-crlf"
    scenario = _basic(agent)
    scenario["files"]["MEMORY.md"] = scenario["files"]["MEMORY.md"].replace("\n", "\r\n")
    scenario["files"]["memory/2026-05-08.md"] = scenario["files"]["memory/2026-05-08.md"].replace("\n", "\r\n")
    out[agent] = {**scenario, "runs": [{"sessionIds": ["s1"]}]}
    agent = "fg-nothing"
    out[agent] = {
        "files": {"MEMORY.md": "# Memory\n", STORE: _json_file({})},
        "runs": [{"sessionIds": ["s9"]}, {"sessionIds": ["s9"], "dryRun": True}],
    }
    agent = "fg-hooks"
    scenario = _basic(agent)
    scenario["sessions"][0]["entry"] = {"hookExternalContentSource": "webhook"}
    out[agent] = {**scenario, "runs": [{"hookSources": ["webhook"]}, {"hookSources": ["gmail"]}]}
    out.update(_random_scenarios(24))
    return out


def _random_scenarios(count: int) -> dict[str, dict[str, Any]]:
    rng = random.Random(20261005)
    out: dict[str, dict[str, Any]] = {}
    for index in range(count):
        agent = f"fg-r{index:02d}"
        sessions = ["s1", "s2", "s3"]
        keys = [f"memory:memory/2026-05-{10 + i:02d}.md:{i + 2}:{i + 2}" for i in range(rng.randint(2, 6))]
        origins = []
        entries = []
        for i, key in enumerate(keys):
            owners = rng.sample(sessions, rng.randint(1, 2)) if rng.random() < 0.85 else []
            origins += [_origin(key, agent, s, rng.choice(["owner", "agent"]), 100 + i) for s in owners]
            entries.append(
                _promo(
                    key,
                    rng.choice(["- Fact number %d about backups." % i, "- Fact %d with ünïcödé text" % i, "- Fact %d" % i]),
                    lineage=f"lin-{i}" if rng.random() < 0.3 else None,
                    extra=rng.choice([[], ["  continuation %d" % i], ["  c1", "  c2"], [""]]),
                )
            )
        body = ["# Memory", ""]
        for entry in entries:
            body.append(entry)
            if rng.random() < 0.3:
                body.append(rng.choice([f"## Notes about {agent}:{rng.choice(sessions)}", f"### Row\n- Session ID: {rng.choice(sessions)}", "## Plain heading"]))
                body.append("some text under it")
        daily = "\n".join(
            rng.choice(
                [
                    "- A daily bullet that stays.",
                    f"- Bullet. Session ID: {rng.choice(sessions)}",
                    f"## From sessions/{agent}/{rng.choice(sessions)}.jsonl.reset.2026-05-01T00-00-00.000Z",
                    "text line",
                    "",
                    f"  - nested Session ID: {rng.choice(sessions)}",
                ]
            )
            for _ in range(rng.randint(3, 12))
        )
        corpus_lines = [
            f"[{agent}/sessions/{agent}/{rng.choice(sessions)}#L{n}] {rng.choice(['User', 'Assistant'])}: "
            + rng.choice(["Remember the backups run nightly.", "short", "Another long enough message here.", "x" * 30])
            for n in range(rng.randint(1, 8))
        ]
        recall = {
            key: _recall_entry(key, "memory/2026-05-10.md", rng.choice(["Fact one", f"see {agent}:s1 notes", "plain"]))
            for key in keys
            if rng.random() < 0.7
        }
        recall["memory:plain"] = _recall_entry("memory:plain", f"{CORPUS}/2026-05-10.txt", rng.choice(corpus_lines))
        out[agent] = {
            "files": {
                "MEMORY.md": "\n".join(body) + "\n",
                "memory/2026-05-10.md": daily + "\n",
                f"{CORPUS}/2026-05-10.txt": "\n".join(corpus_lines) + "\n",
                STORE: _json_file(recall),
                PHASE: _json_file({k: _phase_entry(k) for k in recall if rng.random() < 0.6}),
            },
            "origins": origins,
            "sessions": [{"sessionId": s, "messages": [_msg("user", f"message of {s} with some text.")]} for s in sessions],
            "chunks": [
                {"path": rng.choice(["MEMORY.md", "memory/2026-05-10.md", f"sessions/{agent}/s1", f"{CORPUS}/2026-05-10.txt"]), "source": rng.choice(["memory", "sessions"]), "text": f"chunk {n} " + rng.choice(["alpha", "Fact number 1 about backups.", "Fact"])}
                for n in range(rng.randint(0, 6))
            ],
            "sources": [{"path": f"{CORPUS}/2026-05-10.txt", "source": "sessions"}, {"path": "MEMORY.md", "source": "memory"}],
            "runs": [{"sessionIds": rng.sample(sessions, rng.randint(1, 3))}],
        }
    return out


# --- the oracle run ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _ts(tmp_path_factory):
    root = tmp_path_factory.mktemp("forget-ts")
    payload = []
    for name, scenario in _scenarios().items():
        payload.append({"name": name, "agentId": name, "workspaceDir": str(root / f"ts-{name}"), **scenario})
    response = _oracle().run({"operation": "forgetScenarios", "nowMs": NOW_MS, "forgetScenarios": payload})
    assert response["ok"] is True, response.get("error")
    return {item["name"]: item for item in response["result"]["scenarios"]}


# --- the Python replay -------------------------------------------------------------------------


def _tree(workspace: Path) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace).as_posix()
        if relative == "memory/.dreams" or relative.startswith("memory/.dreams/"):
            continue
        out[relative + ("/" if path.is_dir() else "")] = None if path.is_dir() else path.read_bytes().decode("utf-8")
    return out


def _entries(workspace: Path, relative: str) -> dict[str, Any]:
    path = workspace / relative
    return dict(sorted(json.loads(path.read_text("utf-8"))["entries"].items())) if path.exists() else {}


def _origin_json(origin: MemoryEntryOrigin) -> dict[str, Any]:
    return {
        "entryKey": origin.entry_key,
        "agentId": origin.agent_id,
        "sessionId": origin.session_id,
        "sessionKey": origin.session_key,
        "originClass": origin.origin_class,
        "observedAt": origin.observed_at,
    }


def _state_json(workspace: Path) -> dict[str, Any]:
    return read_session_ingestion_state(workspace).to_json()


def _setup(name: str, scenario: dict[str, Any], tmp_path: Path, ts: dict[str, Any]):
    workspace = tmp_path / f"py-{name}"
    for relative, content in scenario.get("files", {}).items():
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, "utf-8")
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / "agents" / f"{agent}.sqlite")
    rows = [
        MemoryEntryOrigin(o["entryKey"], o["agentId"], o["sessionId"], o["sessionKey"], o["originClass"], o["observedAt"])
        for o in scenario.get("origins", [])
    ]
    if rows:
        ledger.record(name, rows)
    if scenario.get("tombstones"):
        ledger.record_session_tombstones(name, scenario["tombstones"], created_at=1)
    ingestion = scenario.get("sessionIngestion")
    if ingestion:
        write_session_ingestion_state(
            workspace,
            SessionIngestionState(
                {k: SessionIngestionFileState(v["mtimeMs"], v["size"], v["contentHash"], v["lineCount"], v["lastContentLine"]) for k, v in ingestion["files"].items()},
                {k: list(v) for k, v in ingestion["seenMessages"].items()},
            ),
        )
    if scenario.get("backups"):
        target = workspace / "memory" / ".dreams" / "consolidation-preimages.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"version": 1, "entries": scenario["backups"]}), "utf-8")
    provenance = MemoryArtifactProvenanceStore(tmp_path / f"{name}-prov.sqlite")
    for seed in scenario.get("provenance", []):
        provenance.record_write(
            workspace_dir=workspace,
            relative_path=seed["relativePath"],
            content_before=seed.get("contentBefore", ""),
            content_after=seed.get("contentAfter", ""),
            origin_class=seed["originClass"],
            observed_at=seed["observedAt"],
            session_id=seed.get("sessionId"),
            session_key=seed.get("sessionKey"),
        )
    config = MemoryConfig(workspace_dir=workspace, store_path=tmp_path / f"{name}.sqlite", flags=FeatureFlags(vector_search=False))
    store = SQLiteMemoryStore(config, None, revision_fence=ledger.revision_fence(name))
    with store.connect() as db:
        for number, chunk in enumerate(scenario.get("chunks", []), start=1):
            db.execute(
                "INSERT INTO chunks VALUES (?, ?, 1, 1, ?, ?, '[]')",
                (f"chunk-{number}", chunk["path"], chunk.get("source", "memory"), chunk["text"]),
            )
            db.execute("INSERT INTO chunks_fts(id, text) VALUES (?, ?)", (f"chunk-{number}", chunk["text"]))
        for source in scenario.get("sources", []):
            db.execute("INSERT INTO paths_fts(path, source) VALUES (?, ?)", (source["path"], source.get("source", "memory")))
    # The transcripts: OpenClaw's SQLite events start with the session header.
    transcripts: dict[str, Path] = {}
    for session in scenario.get("sessions", []):
        target = tmp_path / "py-sessions" / name / f"{session['sessionId']}.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = [{"type": "session", "id": session["sessionId"]}] + [{"type": "message", "message": m} for m in session["messages"]]
        target.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows), "utf-8")
        transcripts[session["sessionId"]] = target

    def corpus_entries(_agent: str) -> list[SessionCorpusEntry]:
        return [
            SessionCorpusEntry(
                agent_id=e["agentId"],
                session_id=e["sessionId"],
                session_file=str(transcripts[e["sessionId"]]),
                session_key=e["sessionKey"],
                session_kind=e["sessionKind"],
                artifact_kind=e["artifactKind"],
                transcript_source="sqlite",
                generated_by_dreaming_narrative=e["generatedByDreamingNarrative"],
                generated_by_cron_run=e["generatedByCronRun"],
            )
            for e in ts["corpusEntries"]
            if e["sessionId"] in transcripts
        ]

    instances = [
        SessionInstance(
            agent_id=name,
            session_id=s["sessionId"],
            session_key=s.get("sessionKey") or f"agent:{name}:{s['sessionId']}",
            created_at=0,
            hook_external_content_source=(s.get("entry") or {}).get("hookExternalContentSource"),
        )
        for s in scenario.get("sessions", [])
    ]
    return config, workspace, ledger, provenance, store, corpus_entries, instances


@pytest.mark.parametrize("name", sorted(_scenarios()))
def test_forget_matches_openclaw(name: str, _ts, tmp_path: Path) -> None:
    scenario = _scenarios()[name]
    ts = _ts[name]
    config, workspace, ledger, provenance, store, corpus_entries, instances = _setup(name, scenario, tmp_path, ts)
    for index, (run, expected) in enumerate(zip(scenario["runs"], ts["runs"], strict=True)):
        label = f"{name} run {index}"
        revision_before = ledger.index_revision(name)
        error: str | None = None
        report: Any = None
        try:
            report = forget_memory_entries(
                config=config,
                agent_id=name,
                origins=ledger,
                session_ids=run.get("sessionIds"),
                hook_sources=run.get("hookSources"),
                participants=run.get("participants"),
                instances=instances,
                corpus_entries=corpus_entries,
                artifact_provenance=provenance,
                store=store,
                dry_run=bool(run.get("dryRun")),
            ).to_json()
        except Exception as caught:
            error = str(caught)
        assert error == expected["error"], label
        assert report == expected["report"], label
        assert _tree(workspace) == expected["files"], label
        # OpenClaw's store reader normalizes entries (adds fields); every field Python keeps must agree.
        assert _subset(_entries(workspace, STORE), expected["recall"]), (label, _first_difference(_entries(workspace, STORE), expected["recall"]))
        assert _subset(_entries(workspace, PHASE), expected["phase"]), label
        assert _state_json(workspace) == expected["sessionState"], label
        preimages = json.loads((workspace / "memory/.dreams/consolidation-preimages.json").read_text("utf-8"))["entries"] if (workspace / "memory/.dreams/consolidation-preimages.json").exists() else []
        assert sorted(preimages, key=lambda p: p["createdAt"]) == sorted(expected["preimages"], key=lambda p: p["createdAt"]), label
        assert [_origin_json(o) for o in ledger.list(name)] == expected["origins"], label
        assert [
            {"sessionId": t.session_id, "agentId": t.agent_id, "reason": t.reason}
            for t in ledger.list_session_tombstones(name)
        ] == [{k: v for k, v in t.items() if k != "createdAt"} for t in expected["tombstones"]], label
        with store.connect() as db:
            chunks = [
                {"path": p, "source": s, "text": t}
                for p, s, t in db.execute("SELECT path, source, text FROM chunks ORDER BY path, source, text")
            ]
            sources = [{"path": p, "source": s} for p, s in db.execute("SELECT path, source FROM paths_fts ORDER BY path, source")]
        assert chunks == expected["chunks"], label
        assert sources == expected["sources"], label
        # Every real forget of a session moves the revision fence (the exact count is upstream's row triggers).
        moved = ledger.index_revision(name) != revision_before
        was_real = not run.get("dryRun") and report is not None and report["sessionIds"] != []
        assert moved == was_real, label


def test_forget_scenarios_exercise_the_branches(_ts) -> None:
    basic = _ts["fg-basic"]["runs"]
    assert basic[0]["report"]["dryRun"] is True and basic[0]["report"]["artifacts"]["memoryFiles"] >= 2
    assert basic[1]["report"]["entryKeys"] and basic[1]["report"]["mixedLineageEntryKeys"]
    assert basic[1]["report"]["untargetableEntryKeys"] == ["memory:stray"]
    assert basic[1]["report"]["artifacts"]["indexChunks"] >= 5
    assert any(i["relativePath"].startswith("memory/") for i in basic[1]["report"]["curatedWrites"])
    assert basic[2]["report"]["artifacts"]["memoryEntries"] == 0
    assert _ts["fg-history"]["runs"][0]["report"]["refusals"]
    assert _ts["fg-selectors-missing"]["runs"][0]["error"]
    assert _ts["fg-unresolved"]["runs"][0]["report"]["sessionResolutions"][0]["source"] == "unresolved"
    assert any(run["report"] and run["report"]["sessionIds"] for run in _ts["fg-hooks"]["runs"])


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


def _subset(got: dict[str, Any], want: dict[str, Any]) -> bool:
    return set(got) == set(want) and all(
        all(key in want[name] and want[name][key] == value for key, value in entry.items() if value is not None and key != "updatedAt")
        for name, entry in got.items()
    )
