"""Oracle tests of the deep-phase consolidation orchestration and the DREAMS.md history summaries.

``applyShortTermPromotions`` op with a ``consolidation`` payload: the runner drives
``applyShortTermPromotionsForTests`` (extensions/memory-core/src/test-helpers.ts) with a stubbed
subagent, so the real plan-before-lock, lock-time re-check, preimage, commit, DREAMS.md summary and
append-only fallback run. Python replays the same recalls through ``run_short_term_promotion`` with a
:class:`DeepConsolidation` and the same stubbed model; MEMORY.md, DREAMS.md, the preimages, the
model calls, the warnings and the recall store must be equal. ``consolidationHistory`` op: the two
summary writers over seeded DREAMS.md contents.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from demo.openclaw_oracle import OpenClawOracle
from memory_core.config import MemoryConfig
from memory_core.consolidation import (
    DeepConsolidation,
    LlmConsolidationOptions,
    append_consolidation_skipped_summary,
    append_consolidation_summary,
    read_memory_preimages,
    record_short_term_recalls,
    run_short_term_promotion,
)
from memory_core.consolidation.llm_consolidation import ConsolidationRequest
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY

NOW_MS = 1779811200000  # 2026-05-26T16:00:00Z
TZ = "Europe/Istanbul"
GATES = {"minScore": 0, "minRecallCount": 0, "minUniqueQueries": 0}
DAILY = (
    "# 2026-05-08\n\n- Move backups to S3 Glacier.\n- Rotate keys every quarter.\n"
    "- Prefers dark mode.\n"
)
KEY_A = "memory:memory/2026-05-08.md:3:3"
KEY_B = "memory:memory/2026-05-08.md:4:4"
KEY_C = "memory:memory/2026-05-08.md:5:5"


def _oracle() -> OpenClawOracle:
    return OpenClawOracle(repo_path=Path(os.environ["OPENCLAW_ORACLE_REPO"]), timeout_seconds=120)


def _result(line: int, snippet: str) -> dict[str, Any]:
    return {
        "source": "memory",
        "path": "memory/2026-05-08.md",
        "startLine": line,
        "endLine": line,
        "snippet": snippet,
        "score": 1,
    }


RESULTS = [
    _result(3, "- Move backups to S3 Glacier."),
    _result(4, "- Rotate keys every quarter."),
    _result(5, "- Prefers dark mode."),
]


def reply(*operations: tuple[str, str, list[str]]) -> str:
    return json.dumps(
        {
            "operations": [
                {"candidateKey": key, "action": action, "priorEntries": prior}
                for key, action, prior in operations
            ]
        }
    )


def _scenarios() -> dict[str, dict[str, Any]]:
    memory = "# Memory\n\n- Existing global fact.\n- Move backups to S3 Glacier.\n"
    return {
        "added": {
            "memory": memory,
            "results": RESULTS[:1],
            "replies": [reply((KEY_A, "added", []))],
        },
        "merged_and_added": {
            "memory": memory,
            "results": RESULTS[:2],
            "replies": [
                reply((KEY_A, "merged", ["- Move backups to S3 Glacier."]), (KEY_B, "added", []))
            ],
        },
        "model_name_passed": {
            "memory": memory,
            "results": RESULTS[:1],
            "model": "host/model-1",
            "replies": [reply((KEY_A, "added", []))],
        },
        "empty_memory": {
            "memory": None,
            "results": RESULTS[:2],
            "replies": [reply((KEY_A, "added", []), (KEY_B, "added", []))],
        },
        "invalid_json_falls_back": {
            "memory": memory,
            "results": RESULTS[:1],
            "replies": ["not json"],
        },
        "model_throws_falls_back": {
            "memory": memory,
            "results": RESULTS[:1],
            "replies": [{"throw": "boom"}],
        },
        "unrelated_merge_rejected": {
            "memory": memory,
            "results": RESULTS[2:],
            "replies": [reply((KEY_C, "merged", ["- Existing global fact."]))],
        },
        "memory_changed_during_call": {
            "memory": memory,
            "results": RESULTS[:1],
            "mutateMemoryDuringCall": "\n- Added by someone else.\n",
            "replies": [reply((KEY_A, "added", []))],
        },
        "untrusted_candidate_filtered": {
            "memory": memory,
            "results": RESULTS[:2],
            "untrusted": [KEY_A],
            "replies": [reply((KEY_B, "added", []))],
        },
        "history_appends_to_existing_dreams": {
            "memory": memory,
            "dreams": "# Dream Diary\n\nOld entry.\n",
            "results": RESULTS[:1],
            "replies": [reply((KEY_A, "added", []))],
        },
        "history_reuses_heading": {
            "memory": memory,
            "dreams": "## Memory Consolidation History\n\n### 2026-05-01T00:00:00.000Z\n\n- Added: 1\n",
            "results": RESULTS[:1],
            "replies": [reply((KEY_A, "added", []))],
        },
        "lowercase_dreams_file": {
            "memory": memory,
            "dreamsName": "dreams.md",
            "dreams": "kept\n",
            "results": RESULTS[:1],
            "replies": [reply((KEY_A, "added", []))],
        },
    }


class _Warnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _seed(workspace: Path, scenario: dict[str, Any]) -> None:
    daily = workspace / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(DAILY, encoding="utf-8")
    if scenario["memory"] is not None:
        (workspace / "MEMORY.md").write_text(scenario["memory"], encoding="utf-8")
    if "dreams" in scenario:
        (workspace / scenario.get("dreamsName", "DREAMS.md")).write_text(
            scenario["dreams"], encoding="utf-8"
        )


def _mark_untrusted(workspace: Path, keys: list[str]) -> None:
    path = workspace / "memory" / ".dreams" / "short-term-recall.json"
    store = json.loads(path.read_text(encoding="utf-8"))
    for key in keys:
        store["entries"][key]["provenance"] = {
            "originClass": "untrusted",
            "sessionKind": "unknown",
            "observedAt": 1,
        }
    path.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")


def _snapshot(files: dict[str, str]) -> dict[str, str]:
    return {name: files[name] for name in ("MEMORY.md", "DREAMS.md", "dreams.md") if name in files}


def _py_files(workspace: Path) -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in workspace.iterdir()
        if path.name in ("MEMORY.md", "DREAMS.md", "dreams.md")
    }


def _run_ts(scenario: dict[str, Any], workspace: Path) -> dict[str, Any]:
    oracle = _oracle()
    _seed(workspace, scenario)
    oracle.run(
        {
            "operation": "recordShortTermRecalls",
            "workspaceDir": str(workspace),
            "query": "backups",
            "results": scenario["results"],
            "nowMs": NOW_MS,
            "timezone": TZ,
        }
    )
    if scenario.get("untrusted"):
        _mark_untrusted(workspace, scenario["untrusted"])
    ranked = oracle.run(
        {
            "operation": "rankShortTermPromotionCandidates",
            "workspaceDir": str(workspace),
            "nowMs": NOW_MS,
            "timezone": TZ,
            **GATES,
        }
    )
    consolidation: dict[str, Any] = {"replies": scenario["replies"]}
    for field in ("model", "mutateMemoryDuringCall"):
        if field in scenario:
            consolidation[field] = scenario[field]
    return oracle.run(
        {
            "operation": "applyShortTermPromotions",
            "workspaceDir": str(workspace),
            "nowMs": NOW_MS,
            "timezone": TZ,
            "candidates": ranked["result"]["candidates"],
            "consolidation": consolidation,
            **GATES,
        }
    )


def _run_python(scenario: dict[str, Any], workspace: Path) -> dict[str, Any]:
    _seed(workspace, scenario)
    config = MemoryConfig(
        workspace_dir=workspace, store_path=workspace.parent / f"{workspace.name}.sqlite"
    )
    record_short_term_recalls(
        config=config, query="backups", results=scenario["results"], now_ms=NOW_MS
    )
    if scenario.get("untrusted"):
        _mark_untrusted(workspace, scenario["untrusted"])
    calls: list[ConsolidationRequest] = []
    replies = list(scenario["replies"])

    def model(request: ConsolidationRequest) -> Any:
        calls.append(request)
        if "mutateMemoryDuringCall" in scenario:
            with (workspace / "MEMORY.md").open("a", encoding="utf-8") as handle:
                handle.write(scenario["mutateMemoryDuringCall"])
        item = replies[len(calls) - 1]
        if isinstance(item, dict) and "throw" in item:
            raise RuntimeError(item["throw"])
        return item

    handler = _Warnings()
    logger = logging.getLogger(f"deep-consolidation-test.{workspace.name}")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    run = run_short_term_promotion(
        config=config,
        store=SQLiteMemoryStore(config, FakeEmbeddingProvider(dimensions=8)),
        now_ms=NOW_MS,
        timezone=TZ,
        min_score=0,
        min_recall_count=0,
        min_unique_queries=0,
        limit=10,
        identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
        consolidation=DeepConsolidation(
            model=model,
            options=LlmConsolidationOptions(enabled=True, model_name=scenario.get("model")),
            logger=logger,
        ),
    )
    return {"run": run, "calls": calls, "warnings": handler.messages}


def _comparable_calls(ts_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "message": call["message"],
            "systemPrompt": call["extraSystemPrompt"],
            "model": call.get("model"),
            "timeoutMs": call["timeoutMs"],
        }
        for call in ts_calls
    ]


@pytest.fixture(scope="module")
def _results() -> dict[str, tuple[dict[str, Any], dict[str, Any], Path, Path]]:
    out = {}
    with tempfile.TemporaryDirectory(prefix="memory-core-deep-consolidation-") as tmp:
        root = Path(tmp)
        for name, scenario in _scenarios().items():
            ts_workspace = root / f"ts-{name}"
            py_workspace = root / f"py-{name}"
            ts_workspace.mkdir()
            py_workspace.mkdir()
            ts = _run_ts(scenario, ts_workspace)
            py = _run_python(scenario, py_workspace)
            out[name] = (ts, py, ts_workspace, py_workspace)
        yield out
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.parametrize("name", sorted(_scenarios()))
def test_deep_consolidation_matches_openclaw(name: str, _results) -> None:
    ts, py, ts_workspace, py_workspace = _results[name]
    assert ts["ok"] is True
    assert _snapshot(_py_files(py_workspace)) == _snapshot(ts["files"])
    assert py["calls"] and [
        {
            "message": call.message,
            "systemPrompt": call.system_prompt,
            "model": call.model,
            "timeoutMs": call.timeout_ms,
        }
        for call in py["calls"]
    ] == _comparable_calls(ts["result"]["calls"])
    ts_preimages = [
        {"createdAt": p["createdAt"], "content": p["content"], "contentHash": p["contentHash"]}
        for p in ts["result"]["preimages"]
    ]
    assert read_memory_preimages(py_workspace) == ts_preimages
    run = py["run"]
    assert [c.key for c in run.applied_candidates] == [
        c["key"] for c in ts["result"]["appliedCandidates"]
    ]
    assert run.appended == ts["result"]["appended"]
    assert len(run.applied_candidates) == ts["result"]["applied"]
    ts_warnings = [w.replace("memory-core: ", "", 1) for w in ts["result"]["warnings"]]
    py_warnings = [w.split(": ", 1)[1] for w in py["warnings"]]
    assert py_warnings == ts_warnings
    ts_store = json.loads(
        (ts_workspace / "memory" / ".dreams" / "short-term-recall.json").read_text(encoding="utf-8")
    )
    py_store = json.loads(
        (py_workspace / "memory" / ".dreams" / "short-term-recall.json").read_text(encoding="utf-8")
    )
    assert {k: v.get("promotedAt") for k, v in py_store["entries"].items()} == {
        k: v.get("promotedAt") for k, v in ts_store["entries"].items()
    }


# --- the DREAMS.md summary writers -------------------------------------------------------

_HISTORY_CASES = {
    "summary_into_empty": {
        "dreams": None,
        "steps": [
            {
                "kind": "summary",
                "nowMs": NOW_MS,
                "result": {
                    "added": 1,
                    "merged": 2,
                    "superseded": 3,
                    "highlights": ["<!-- m:a -->\n- `+ x`", "<!-- m:b -->\n- `- y`"],
                },
            }
        ],
    },
    "summary_without_highlights": {
        "dreams": "",
        "steps": [
            {
                "kind": "summary",
                "nowMs": NOW_MS,
                "result": {"added": 0, "merged": 0, "superseded": 0, "highlights": []},
            }
        ],
    },
    "skipped_after_existing_text": {
        "dreams": "# Dream Diary\n\nentry\n\n\n",
        "steps": [{"kind": "skipped", "nowMs": NOW_MS, "reason": "MEMORY.md changed"}],
    },
    "summary_then_skipped_reuse_heading": {
        "dreams": "# Dream Diary\n",
        "steps": [
            {
                "kind": "summary",
                "nowMs": NOW_MS,
                "result": {"added": 1, "merged": 0, "superseded": 0, "highlights": ["h"]},
            },
            {"kind": "skipped", "nowMs": NOW_MS + 60_000, "reason": "again"},
        ],
    },
    "heading_text_inside_diary": {
        "dreams": "mention of ## Memory Consolidation History in prose   \n\n",
        "steps": [{"kind": "skipped", "nowMs": NOW_MS, "reason": "r"}],
    },
}


def _python_history(workspace: Path, steps: list[dict[str, Any]]) -> None:
    for step in steps:
        if step["kind"] == "skipped":
            append_consolidation_skipped_summary(workspace, now_ms=step["nowMs"], reason=step["reason"])
        else:
            result = step["result"]
            append_consolidation_summary(
                workspace,
                added=result["added"],
                merged=result["merged"],
                superseded=result["superseded"],
                highlights=result["highlights"],
                now_ms=step["nowMs"],
            )


@pytest.mark.parametrize("name", sorted(_HISTORY_CASES))
def test_consolidation_history_summaries_match_openclaw(name: str, tmp_path: Path) -> None:
    case = _HISTORY_CASES[name]
    ts_workspace = tmp_path / "ts"
    py_workspace = tmp_path / "py"
    for workspace in (ts_workspace, py_workspace):
        workspace.mkdir()
        if case["dreams"] is not None:
            (workspace / "DREAMS.md").write_text(case["dreams"], encoding="utf-8")
    ts = _oracle().run(
        {
            "operation": "consolidationHistory",
            "workspaceDir": str(ts_workspace),
            "nowMs": NOW_MS,
            "historySteps": case["steps"],
        }
    )
    _python_history(py_workspace, case["steps"])
    assert (py_workspace / "DREAMS.md").read_text(encoding="utf-8") == ts["files"]["DREAMS.md"]
