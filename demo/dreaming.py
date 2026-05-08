from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from demo.short_term_promotion import (
    SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH,
    MemoryPromotionRun,
    PromotionCandidate,
    rank_short_term_promotion_candidates,
    record_short_term_phase_signals,
    run_short_term_promotion,
)
from memory_core.config import MemoryConfig

_DREAMING_PHASES = {"light", "rem", "deep"}


def run_dreaming_sweep(
    *,
    config: MemoryConfig,
    store: Any,
    phase: str,
    now_ms: int,
    timezone: str,
    limit: int = 5,
) -> dict[str, Any]:
    if phase not in _DREAMING_PHASES:
        raise ValueError(f"unsupported dreaming phase: {phase}")

    candidates = rank_short_term_promotion_candidates(
        config=config,
        now_ms=now_ms,
        limit=limit,
        min_score=0,
        min_recall_count=1,
        min_unique_queries=1,
    )
    candidate_keys = [candidate.key for candidate in candidates]
    files_changed: list[str] = []
    phase_signals_recorded = 0
    promotion = None

    if phase in {"light", "rem"}:
        phase_signals_recorded = record_short_term_phase_signals(
            config=config,
            keys=candidate_keys,
            phase=phase,
            now_ms=now_ms,
        )
        if phase_signals_recorded:
            files_changed.append(SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH.as_posix())

    if phase == "rem":
        _append_dreams_section(
            path=config.workspace_dir / "DREAMS.md",
            candidates=candidates,
            phase=phase,
            now_ms=now_ms,
            timezone=timezone,
        )
        files_changed.append("DREAMS.md")

    if phase == "deep":
        promotion_run = run_short_term_promotion(
            config=config,
            store=store,
            now_ms=now_ms,
            timezone=timezone,
            limit=limit,
        )
        promotion = _serialize_promotion_run(promotion_run)
        if promotion_run.parsed.should_write:
            files_changed.append(promotion_run.target)

    return {
        "phase": phase,
        "candidateCount": len(candidates),
        "candidateKeys": candidate_keys,
        "phaseSignalsRecorded": phase_signals_recorded,
        "filesChanged": files_changed,
        "promotion": promotion,
    }


def _append_dreams_section(
    *,
    path: Path,
    candidates: list[PromotionCandidate],
    phase: str,
    now_ms: int,
    timezone: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    prefix = "" if not before else "\n" if before.endswith("\n") else "\n\n"
    section = "\n".join(
        [
            f"## Dreaming sweep ({_iso(now_ms)})",
            "",
            f"- phase: {phase}",
            f"- candidate count: {len(candidates)}",
            f"- timezone: {timezone}",
            "- snippets:",
            *_snippet_lines(candidates),
            "",
        ]
    )
    path.write_text(f"{before}{prefix}{section}", encoding="utf-8")


def _snippet_lines(candidates: list[PromotionCandidate]) -> list[str]:
    if not candidates:
        return ["  - (none)"]
    return [f"  - {_single_line(candidate.snippet)}" for candidate in candidates]


def _serialize_promotion_run(run: MemoryPromotionRun) -> dict[str, Any]:
    return {
        "target": run.target,
        "rawText": run.raw_text,
        "parsed": {
            "shouldWrite": run.parsed.should_write,
            "target": run.parsed.target,
            "entry": run.parsed.entry,
            "reason": run.parsed.reason,
            "error": run.parsed.error,
        },
        "diff": run.diff,
        "indexedFiles": run.indexed_files,
        "chunks": run.chunks,
        "evaluatedCandidateCount": len(run.evaluated_candidates),
        "reindexError": run.reindex_error,
    }


def _single_line(value: str) -> str:
    return " ".join(value.strip().split())


def _iso(now_ms: int) -> str:
    return datetime.fromtimestamp(now_ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
