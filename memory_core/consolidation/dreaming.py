"""Manual light / REM / deep dreaming sweeps over the short-term recall store.

Simplified port of the phase sweeps in
``extensions/memory-core/src/dreaming-phases.ts`` and ``dreaming.ts`` (OpenClaw
pin 4c42815348):

- ``light`` and ``rem`` rank every live recall entry (no gates) and record a
  phase signal per candidate (``recordDreamingPhaseSignals``); the signals feed
  the promotion score's phase boost;
- ``rem`` also appends a ``## Dreaming sweep`` summary to ``DREAMS.md``;
- ``deep`` runs gated scored promotion (:func:`run_short_term_promotion`).

Known gaps (parity matrix rows "Light dreaming phase signals", "REM dreaming
phase signals", "Deep dreaming application flow"): no REM narrative or
evidence extraction, no light-phase metadata, no scheduler or cron; sweeps run
only when a host calls them (dreaming is off by default).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory_core.config import MemoryConfig
from memory_core.consolidation.promotion import (
    MemoryPromotionRun,
    PromotionCandidate,
    ReindexableStore,
    rank_short_term_promotion_candidates,
    run_short_term_promotion,
)
from memory_core.consolidation.recall import record_short_term_phase_signals
from memory_core.consolidation.store import SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity

DREAMING_PHASES = frozenset({"light", "rem", "deep"})
DREAMS_FILE_NAME = "DREAMS.md"


@dataclass(frozen=True)
class DreamingSweepResult:
    """Outcome of one :func:`run_dreaming_sweep` call."""

    phase: str
    candidates: tuple[PromotionCandidate, ...]
    phase_signals_recorded: int
    files_changed: tuple[str, ...]
    promotion: MemoryPromotionRun | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready summary (camelCase keys) used by the Lab state payload."""
        return {
            "phase": self.phase,
            "candidateCount": len(self.candidates),
            "candidateKeys": [candidate.key for candidate in self.candidates],
            "phaseSignalsRecorded": self.phase_signals_recorded,
            "filesChanged": list(self.files_changed),
            "promotion": serialize_promotion_run(self.promotion) if self.promotion else None,
        }


def run_dreaming_sweep(
    *,
    config: MemoryConfig,
    store: ReindexableStore,
    phase: str,
    now_ms: int,
    timezone: str,
    limit: int = 5,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> DreamingSweepResult:
    """Run one dreaming phase over the workspace's recall store.

    ``phase`` is ``"light"``, ``"rem"`` or ``"deep"`` (anything else raises
    ``ValueError``). Up to ``limit`` candidates are ranked without gates; the
    deep phase promotes with the default gates and the same ``limit``.
    ``files_changed`` lists workspace-relative paths the sweep wrote;
    ``identity`` picks the promotion marker prefix of the deep phase.
    """
    if phase not in DREAMING_PHASES:
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
            path=config.workspace_dir / DREAMS_FILE_NAME,
            candidates=candidates,
            phase=phase,
            now_ms=now_ms,
            timezone=timezone,
        )
        files_changed.append(DREAMS_FILE_NAME)

    if phase == "deep":
        promotion = run_short_term_promotion(
            config=config,
            store=store,
            now_ms=now_ms,
            timezone=timezone,
            limit=limit,
            identity=identity,
        )
        if promotion.parsed.should_write:
            files_changed.append(promotion.target)

    return DreamingSweepResult(
        phase=phase,
        candidates=tuple(candidates),
        phase_signals_recorded=phase_signals_recorded,
        files_changed=tuple(files_changed),
        promotion=promotion,
    )


def serialize_promotion_run(run: MemoryPromotionRun) -> dict[str, Any]:
    """JSON-ready summary of a promotion run (camelCase keys, candidate count only)."""
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
            f"## Dreaming sweep ({_iso_seconds(now_ms)})",
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


def _single_line(value: str) -> str:
    return " ".join(value.strip().split())


def _iso_seconds(now_ms: int) -> str:
    return datetime.fromtimestamp(now_ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
