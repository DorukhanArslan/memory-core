"""Oracle test of the dreaming daily ingestion against OpenClaw v2026.9.6.

One real-TS run (``dailyIngestionScenarios``: the real ``dreaming-phases.ts`` loaded with one extra
export line, so ``buildDailyIngestionResults``, ``ingestDailyMemorySignals`` and
``seedHistoricalDailyMemorySignals`` run over seeded workspaces), replayed step by step in Python
(``memory_core.consolidation.daily_ingestion``). After every step the recall store, the daily
ingestion checkpoint and (at the end) the host events must agree.

- ``build`` steps: the chunker over about 400 generated and hand-written notes (headings, nested and
  numbered lists, loose paragraphs, managed Light and REM blocks, CRLF, long and non-ASCII lines),
  with and without a trust record of every kind;
- ingest scenarios: lookback window, the unchanged-file checkpoint, the next dreaming day, an edited
  or removed note, a flush quarantine (``untrusted`` record, sticky across edits), the sweep cap and
  rolled-back provenance;
- seed scenarios: explicit files (daily names, other names, a missing file, one outside the workspace).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenance, MemoryArtifactProvenanceStore
from memory_core.consolidation.daily_ingestion import (
    build_daily_ingestion_results,
    ingest_daily_memory_signals,
    read_daily_ingestion_state,
    seed_historical_daily_memory_signals,
)

DAY_MS = 86_400_000
NOW_MS = 1779811200000  # 2026-05-26T16:00:00Z
TZ = "Europe/Istanbul"
STORE = "memory/.dreams/short-term-recall.json"


def _oracle() -> OpenClawOracle:
    return OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=600)


# --- chunker inputs ----------------------------------------------------------------------------

_FRAGMENTS = [
    "# 2026-05-08",
    "# Notes for the week",
    "## Project Alpha",
    "## Monday",
    "### May 8th, 2026",
    "## 05/08/2026",
    "## Today",
    "### Release plan",
    "# 2026-05-08-notes.md",
    "- Backups run nightly on the primary host.",
    "- short",
    "  - Nested item about the database migration plan.",
    "    - Deeper item that keeps going for a while about retries.",
    "* Star bullet with enough characters to count.",
    "+ Plus bullet with enough characters to count.",
    "1. First numbered step of the deployment checklist.",
    "2. Second numbered step of the deployment checklist.",
    "- Parent with children:",
    "  - Child one of the container item.",
    "  - Child two of the container item.",
    "- Item with a continuation line",
    "  that wraps to the next line of text.",
    "Plain paragraph line one is long enough to be kept.",
    "Plain paragraph line two continues the thought here.",
    "Plain paragraph line three adds more detail to it.",
    "Plain paragraph line four rounds the chunk off nicely.",
    "Plain paragraph line five forces a split of the chunk.",
    "tiny",
    "<!-- a comment line that is ignored -->",
    "",
    "",
    "Ünïcödé line with ümlauts and emoji \U0001f600 inside the text.",
    " - Non-breaking space before a bullet that should still parse.",
    "Tabbed\tline\twith\ttabs inside the sentence here.",
    "- " + "word " * 80,
    "A very long paragraph line " + "x" * 300,
    "- Fact with \U0001f600" * 1 + " " + "\U0001f600" * 150,
    "<!-- openclaw:dreaming:light:start -->",
    "- Managed light bullet that must never be ingested.",
    "<!-- openclaw:dreaming:light:end -->",
    "## Light Sleep",
    "## REM Sleep",
    "<!-- openclaw:dreaming:rem:start -->",
    "Managed REM paragraph that must never be ingested.",
    "<!-- openclaw:dreaming:rem:end -->",
    "- 2026-05-08 appears inside a bullet as a date reference.",
]


def _doc(rng: random.Random) -> str:
    lines = [rng.choice(_FRAGMENTS) for _ in range(rng.randint(1, 18))]
    separator = rng.choice(["\n", "\n", "\r\n"])
    text = separator.join(lines)
    if rng.random() < 0.3:
        text += separator
    return text


def _hand_docs() -> list[str]:
    return [
        "",
        "\n\n\n",
        "# 2026-05-08\n\n- Backups run nightly.\n- Rotate the keys monthly.\n",
        "## Project Alpha\nFirst line of the paragraph is here.\nSecond line of the paragraph is here.\n",
        "- Parent:\n  - Child one is long enough.\n  - Child two is long enough.\n- Sibling item that stands alone.\n",
        "- Parent:\n\n  - Loose child separated by a blank line.\n",
        "- Item\n  continuation text that is long enough\n  second continuation line\n- Next item that is long enough.\n",
        "<!-- openclaw:dreaming:light:start -->\n- hidden hidden hidden\n",
        "## Light Sleep\n<!-- openclaw:dreaming:light:start -->\n- hidden bullet one\n<!-- openclaw:dreaming:light:end -->\n- Kept bullet after the block.\n",
        "## REM Sleep\n\n<!-- openclaw:dreaming:rem:start -->\nhidden paragraph here\n## Next heading\n- Kept bullet after the heading.\n",
        "Line one is here and fine.\r\nLine two is here and fine.\r\n\r\nLine three after a gap here.\r\n",
        "x" * 600,
        "- " + "y" * 600,
        "# Heading\n" + "\n".join(f"- Bullet number {i} in a long list." for i in range(40)),
    ]


# --- scenarios ---------------------------------------------------------------------------------


def _build_steps() -> list[dict[str, Any]]:
    rng = random.Random(20261001)
    docs = _hand_docs() + [_doc(rng) for _ in range(400)]
    steps = []
    for index, raw in enumerate(docs):
        step: dict[str, Any] = {
            "kind": "build",
            "raw": raw,
            "path": f"memory/2026-05-{(index % 28) + 1:02d}.md",
            "limit": rng.choice([1, 2, 3, 6, 12, 30]),
            "defaultObservedAt": 1_700_000_000_000 + index,
        }
        roll = rng.random()
        digest = hashlib.sha256(raw.encode("utf-8", "surrogatepass")).hexdigest()
        if roll < 0.2:
            step["recorded"] = {"fileHash": digest, "originClass": "agent", "observedAt": 42 + index}
        elif roll < 0.35:
            step["recorded"] = {"fileHash": digest, "originClass": "untrusted", "observedAt": 43 + index}
        elif roll < 0.45:
            step["recorded"] = {"fileHash": "0" * 64, "originClass": "agent", "observedAt": 44 + index}
        elif roll < 0.5:
            step["recorded"] = {"fileHash": "0" * 64, "originClass": "untrusted", "observedAt": 45 + index}
        steps.append(step)
    return steps


def _note(day: str, *lines: str) -> str:
    return f"# {day}\n\n" + "".join(f"{line}\n" for line in lines)


def _write(path: str, content: str, days_ago: float = 0) -> dict[str, Any]:
    return {"kind": "write", "path": path, "content": content, "mtimeMs": NOW_MS - int(days_ago * DAY_MS)}


def _ingest(offset_days: int = 0, lookback: int = 14, limit: int = 5) -> dict[str, Any]:
    return {"kind": "ingest", "lookbackDays": lookback, "limit": limit, "nowMs": NOW_MS + offset_days * DAY_MS}


def _scenarios() -> dict[str, list[dict[str, Any]]]:
    big = "".join(f"- Fact number {i} about topic {i % 7} for the cap.\n" for i in range(60))
    return {
        "basic_window_and_checkpoint": [
            _write("memory/2026-05-26.md", _note("2026-05-26", "- Backups run nightly on the primary.", "- Keys rotate monthly."), 0),
            _write("memory/2026-05-20.md", _note("2026-05-20", "- The staging cluster was rebuilt.", "Plain paragraph about the rebuild details."), 6),
            _write("memory/2026-05-20-notes.md", _note("2026-05-20", "- A suffixed note for the same day."), 6),
            _write("memory/2026-05-01.md", _note("2026-05-01", "- Too old to be ingested at all."), 25),
            _write("memory/notes.md", "- Not a dated daily note at all.\n", 1),
            _ingest(),
            _ingest(),
            _ingest(1),
            _ingest(1),
            _ingest(0, lookback=30),
        ],
        "edit_remove_and_reingest": [
            _write("memory/2026-05-26.md", _note("2026-05-26", "- First version of the fact here."), 0),
            _write("memory/2026-05-25.md", _note("2026-05-25", "- Another fact worth keeping around."), 1),
            _ingest(),
            _write("memory/2026-05-26.md", _note("2026-05-26", "- First version of the fact here.", "- Second fact added later."), 0),
            _ingest(),
            {"kind": "remove", "path": "memory/2026-05-25.md"},
            _ingest(),
            _ingest(2),
        ],
        "flush_quarantine_is_sticky": [
            _write("memory/2026-05-26.md", _note("2026-05-26", "- Written by the flush with an untrusted turn."), 0),
            {
                "kind": "provenance",
                "relativePath": "memory/2026-05-26.md",
                "contentBefore": "",
                "contentAfter": _note("2026-05-26", "- Written by the flush with an untrusted turn."),
                "originClass": "untrusted",
                "observedAt": NOW_MS - 1000,
            },
            _ingest(),
            _write("memory/2026-05-26.md", _note("2026-05-26", "- Written by the flush with an untrusted turn.", "- Then edited by hand."), 0),
            _ingest(1),
        ],
        "trusted_record_and_hash_mismatch": [
            _write("memory/2026-05-26.md", _note("2026-05-26", "- Trusted flush write of this fact."), 0),
            {
                "kind": "provenance",
                "relativePath": "memory/2026-05-26.md",
                "contentBefore": "",
                "contentAfter": _note("2026-05-26", "- Trusted flush write of this fact."),
                "originClass": "agent",
                "observedAt": NOW_MS - 2000,
            },
            _write("memory/2026-05-25.md", _note("2026-05-25", "- A different file with a stale record."), 1),
            {
                "kind": "provenance",
                "relativePath": "memory/2026-05-25.md",
                "contentBefore": "",
                "contentAfter": "something else entirely\n",
                "originClass": "agent",
                "observedAt": NOW_MS - 3000,
            },
            _ingest(),
        ],
        "rolled_back_provenance": [
            _write("memory/2026-05-26.md", _note("2026-05-26", "- A fact whose flush write rolled back."), 0),
            {
                "kind": "provenance",
                "relativePath": "memory/2026-05-26.md",
                "contentBefore": "",
                "contentAfter": "ignored\n",
                "originClass": "untrusted",
                "observedAt": NOW_MS - 1000,
                "rollback": True,
            },
            _ingest(),
        ],
        "cap_and_per_file_cap": [
            *[_write(f"memory/2026-05-{day:02d}.md", big, 26 - day) for day in range(10, 27)],
            _ingest(0, 14, 1),
            _ingest(1, 14, 1),
            _ingest(2, 14, 8),
        ],
        "managed_blocks_and_headings": [
            _write(
                "memory/2026-05-26.md",
                "# 2026-05-26\n\n## Project Alpha\nThe alpha launch checklist is long.\nIt has many parts to cover.\n\n"
                "## Light Sleep\n<!-- openclaw:dreaming:light:start -->\n- Managed light bullet that stays out.\n<!-- openclaw:dreaming:light:end -->\n\n"
                "## REM Sleep\n<!-- openclaw:dreaming:rem:start -->\nManaged REM paragraph that stays out.\n<!-- openclaw:dreaming:rem:end -->\n\n"
                "- Parent with children:\n  - Child one that is long enough.\n  - Child two that is long enough.\n",
                0,
            ),
            _ingest(),
        ],
        "empty_and_unreadable_files": [
            _write("memory/2026-05-26.md", "", 0),
            _write("memory/2026-05-25.md", "tiny\n", 1),
            _ingest(),
            _write("memory/2026-05-25.md", "tiny\nok\n", 1),
            _ingest(),
        ],
        "seed_historical": [
            _write("memory/2026-05-10.md", _note("2026-05-10", "- Old fact one about the cluster.", "- Old fact two about the proxy."), 16),
            _write("memory/2026-05-11.md", _note("2026-05-11", "- Another old fact about monitoring."), 15),
            _write("memory/notes.md", _note("notes", "- Not a daily note, skipped."), 15),
            {"kind": "seed", "filePaths": ["memory/2026-05-10.md", "memory/2026-05-11.md", "memory/notes.md", "memory/2026-05-12.md"], "limit": 3},
            {"kind": "seed", "filePaths": ["memory/2026-05-10.md", "memory/2026-05-11.md", "memory/2026-05-10.md"], "limit": 3, "nowMs": NOW_MS + DAY_MS},
            _ingest(1),
        ],
        "seed_outside_workspace": [
            {"kind": "seed", "filePaths": ["@outside/2026-05-09.md", "@outside/readme.md"], "limit": 2},
        ],
    }


def _seed_workspace(workspace: Path) -> None:
    (workspace / "memory").mkdir(parents=True, exist_ok=True)


def _ts_payload(root: Path) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = [
        {"name": "chunker", "workspaceDir": str(root / "ts-chunker"), "steps": _build_steps()}
    ]
    for name, steps in _scenarios().items():
        workspace = root / f"ts-{name}"
        _seed_workspace(workspace)
        payload.append({"name": name, "workspaceDir": str(workspace), "steps": _resolve_outside(steps, root)})
    (root / "ts-chunker").mkdir(parents=True, exist_ok=True)
    return payload


def _resolve_outside(steps: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    outside = root / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "2026-05-09.md").write_text(_note("2026-05-09", "- A note outside the workspace that is still seeded."), "utf-8")
    (outside / "readme.md").write_text("- not dated\n", "utf-8")
    resolved = []
    for step in steps:
        if step.get("kind") == "seed":
            step = {**step, "filePaths": [str(outside / p[len("@outside/") :]) if p.startswith("@outside/") else p for p in step["filePaths"]]}
        resolved.append(step)
    return resolved


@pytest.fixture(scope="module")
def _ts(tmp_path_factory):
    root = tmp_path_factory.mktemp("daily-ingestion-ts")
    response = _oracle().run(
        {
            "operation": "dailyIngestionScenarios",
            "timezone": TZ,
            "nowMs": NOW_MS,
            "ingestScenarios": _ts_payload(root),
        }
    )
    assert response["ok"] is True, response.get("error")
    return {item["name"]: item for item in response["result"]["scenarios"]}


# --- the Python replay -------------------------------------------------------------------------


def _recorded(raw: dict[str, Any] | None) -> MemoryArtifactProvenance | None:
    if raw is None:
        return None
    return MemoryArtifactProvenance(raw["fileHash"], raw["originClass"], raw["observedAt"])


def _recall_entries(workspace: Path) -> dict[str, Any]:
    path = workspace / STORE
    text = path.read_text("utf-8") if path.exists() else ""
    return dict(sorted(json.loads(text)["entries"].items())) if text else {}


def _py_step(step: dict[str, Any], workspace: Path, config: MemoryConfig, store: MemoryArtifactProvenanceStore, events: list) -> Any:
    now = int(step.get("nowMs", NOW_MS))
    kind = step["kind"]
    if kind == "write":
        target = workspace / step["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(step["content"], "utf-8")
        os.utime(target, ns=(step["mtimeMs"] * 1_000_000, step["mtimeMs"] * 1_000_000))
    elif kind == "remove":
        (workspace / step["path"]).unlink(missing_ok=True)
    elif kind == "provenance":
        rollback = store.record_write(
            workspace_dir=workspace,
            relative_path=step["relativePath"],
            content_before=step.get("contentBefore", ""),
            content_after=step.get("contentAfter", ""),
            origin_class=step["originClass"],
            observed_at=step["observedAt"],
        )
        if step.get("rollback") and rollback:
            rollback()
    elif kind == "build":
        return build_daily_ingestion_results(
            raw=step["raw"],
            path=step["path"],
            limit=step["limit"],
            default_observed_at=step["defaultObservedAt"],
            recorded=_recorded(step.get("recorded")),
        )
    elif kind == "ingest":
        ingest_daily_memory_signals(
            config=config,
            now_ms=now,
            lookback_days=step["lookbackDays"],
            limit=step["limit"],
            timezone=TZ,
            provenance=store,
            on_event=events.append,
        )
    elif kind == "seed":
        outcome = seed_historical_daily_memory_signals(
            config=config,
            file_paths=[p if os.path.isabs(p) else str(workspace / p) for p in step["filePaths"]],
            limit=step["limit"],
            now_ms=now,
            timezone=TZ,
            provenance=store,
            on_event=events.append,
        )
        return {
            "importedFileCount": outcome.imported_file_count,
            "importedSignalCount": outcome.imported_signal_count,
            "skippedPaths": [p if os.path.isabs(p) else str(workspace / p) for p in outcome.skipped_paths],
        }
    return None


def _tail(path: str) -> str:
    return "/".join(Path(path).parts[-2:])


def _replay(name: str, steps: list[dict[str, Any]], tmp_path: Path, ts: dict[str, Any], ts_workspace: Path) -> None:
    workspace = tmp_path / f"py-{name}"
    _seed_workspace(workspace)
    config = MemoryConfig(workspace_dir=workspace, store_path=tmp_path / f"{name}.sqlite")
    store = MemoryArtifactProvenanceStore(tmp_path / f"{name}-prov.sqlite")
    events: list[dict[str, Any]] = []
    for index, (step, expected) in enumerate(zip(steps, ts["steps"], strict=True)):
        result = _py_step(step, workspace, config, store, events)
        label = f"{name} step {index} ({step['kind']})"
        assert expected["error"] is None, label
        if step["kind"] == "build":
            assert result == expected["result"], label
        elif step["kind"] == "seed":
            # TS reports absolute workspace paths of the skipped files; compare by basename.
            assert [_tail(p) for p in result["skippedPaths"]] == [
                _tail(p) for p in expected["result"]["skippedPaths"]
            ], label
            assert {k: v for k, v in result.items() if k != "skippedPaths"} == {
                k: v for k, v in expected["result"].items() if k != "skippedPaths"
            }, label
        if step["kind"] in {"ingest", "seed"}:
            assert _recall_entries(workspace) == expected["recall"], label
            assert read_daily_ingestion_state(workspace).to_json()["files"] == expected["daily"], label
    assert events == [e for e in ts["events"]], name


def test_daily_chunker_matches_openclaw(_ts, tmp_path: Path) -> None:
    steps = _build_steps()
    _replay("chunker", steps, tmp_path, _ts["chunker"], tmp_path)
    nonempty = sum(1 for item in _ts["chunker"]["steps"] if item["result"])
    assert nonempty > 250  # the generated notes mostly produce chunks


@pytest.mark.parametrize("name", sorted(_scenarios()))
def test_daily_ingestion_matches_openclaw(name: str, _ts, tmp_path: Path) -> None:
    steps = _resolve_outside(_scenarios()[name], tmp_path)
    _replay(name, steps, tmp_path, _ts[name], tmp_path)


def test_ingestion_scenarios_exercise_the_branches(_ts) -> None:
    basic = _ts["basic_window_and_checkpoint"]["steps"]
    # The old note is out of the window; the checkpoint skips the unchanged files; the next day re-reads.
    assert "memory/2026-05-01.md" not in basic[5]["daily"]
    assert basic[5]["daily"] == basic[6]["daily"]
    assert basic[7]["daily"] != basic[6]["daily"]
    counts = [sum(e["dailyCount"] for e in item["recall"].values()) for item in basic if item["recall"]]
    assert counts[-1] > counts[0] > 0
    quarantine = _ts["flush_quarantine_is_sticky"]["steps"]
    classes = {e["provenance"]["originClass"] for item in quarantine[-1:] for e in item["recall"].values()}
    assert classes == {"untrusted"}
    cap = _ts["cap_and_per_file_cap"]["steps"]
    assert any(item["recall"] for item in cap)
    assert _ts["seed_historical"]["steps"][3]["result"]["importedFileCount"] >= 1
