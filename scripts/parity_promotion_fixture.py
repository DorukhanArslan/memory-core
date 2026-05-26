from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo.short_term_promotion import (  # noqa: E402
    DEFAULT_PROMOTION_MIN_RECALL_COUNT,
    DEFAULT_PROMOTION_MIN_SCORE,
    DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
    evaluate_short_term_promotion_candidates,
    record_daily_memory_flush,
    record_short_term_recalls,
)
from memory_core.config import MemoryConfig  # noqa: E402


NOW_MS = int(datetime(2026, 5, 8, 12, 0, tzinfo=UTC).timestamp() * 1000)


@dataclass(frozen=True)
class CandidateSummary:
    snippet: str
    score: float
    signal_count: int
    context_diversity: int
    reasons: list[str]
    components: dict[str, float]


@dataclass(frozen=True)
class ParityScenarioResult:
    scenario: str
    selected: bool
    top: CandidateSummary | None


def build_workspace(root: Path) -> MemoryConfig:
    memory = root / "MEMORY.md"
    memory.write_text("# MEMORY.md\n", encoding="utf-8")
    daily = root / "memory" / "2026-05-08.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text(
        "# 2026-05-08\n\n"
        "- User prefers to be addressed as \"Kudret\" in every conversation.\n",
        encoding="utf-8",
    )
    config = MemoryConfig(workspace_dir=root, store_path=root / "memory.sqlite")
    entry = "- User prefers to be addressed as \"Kudret\" in every conversation.\n"
    record_daily_memory_flush(
        config=config,
        target="memory/2026-05-08.md",
        entry=entry,
        now_ms=NOW_MS,
    )
    for query in ("call me kudret", "future sessions kudret"):
        record_short_term_recalls(
            config=config,
            query=query,
            results=[
                {
                    "path": "memory/2026-05-08.md",
                    "startLine": 3,
                    "endLine": 3,
                    "snippet": entry,
                    "score": 0.3,
                }
            ],
            now_ms=NOW_MS,
        )
    return config


def summarize(candidate: Any) -> CandidateSummary:
    components = {
        key: round(float(value), 6)
        for key, value in dict(candidate.components).items()
    }
    score = float(candidate.score)
    reasons: list[str] = []
    if score < DEFAULT_PROMOTION_MIN_SCORE:
        reasons.append(f"score {score:.3f} < {DEFAULT_PROMOTION_MIN_SCORE:.3f}")
    if candidate.signal_count < DEFAULT_PROMOTION_MIN_RECALL_COUNT:
        reasons.append(f"signals {candidate.signal_count} < {DEFAULT_PROMOTION_MIN_RECALL_COUNT}")
    if candidate.context_diversity < DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES:
        reasons.append(
            f"unique queries/days {candidate.context_diversity} < "
            f"{DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES}"
        )
    return CandidateSummary(
        snippet=candidate.snippet,
        score=round(score, 6),
        signal_count=candidate.signal_count,
        context_diversity=candidate.context_diversity,
        reasons=reasons,
        components=components,
    )


def run_fixture(workspace: Path | None = None, *, keep_workspace: bool = False) -> dict[str, Any]:
    temp_dir = None
    if workspace is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="memory-core-parity-"))
        workspace = temp_dir
    else:
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)

    try:
        config = build_workspace(workspace)
        evaluations = evaluate_short_term_promotion_candidates(
            config=config,
            now_ms=NOW_MS,
            min_score=DEFAULT_PROMOTION_MIN_SCORE,
            min_recall_count=DEFAULT_PROMOTION_MIN_RECALL_COUNT,
            min_unique_queries=DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
        )
        top = evaluations[0] if evaluations else None
        summary = summarize(top) if top else None
        selected = bool(summary and not summary.reasons)
        result = ParityScenarioResult(
            scenario="openclaw_core_three_signal_preference",
            selected=selected,
            top=summary,
        )
        payload = asdict(result)
        payload["workspace"] = str(workspace)
        return payload
    finally:
        if temp_dir is not None and not keep_workspace:
            shutil.rmtree(temp_dir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the memory-core/OpenClaw promotion fixture.")
    parser.add_argument("--workspace", type=Path, help="Optional workspace path to write fixture files.")
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args(argv)
    json.dump(
        run_fixture(workspace=args.workspace, keep_workspace=args.keep_workspace),
        sys.stdout,
        indent=2,
        ensure_ascii=False,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
