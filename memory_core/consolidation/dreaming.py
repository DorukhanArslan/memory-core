"""Manual light / REM / deep dreaming sweeps over the short-term recall store.

Simplified port of the phase sweeps in
``extensions/memory-core/src/dreaming-phases.ts`` and ``dreaming.ts`` (OpenClaw
pin 4c42815348):

- ``light`` and ``rem`` rank every live recall entry (no gates) and record a
  phase signal per candidate (``recordDreamingPhaseSignals``); the signals feed
  the promotion score's phase boost;
- ``rem`` also appends a ``## Dreaming sweep`` summary to ``DREAMS.md``;
- ``deep`` runs gated scored promotion (:func:`run_short_term_promotion`); with an enabled
  :class:`~memory_core.consolidation.llm_consolidation.DeepConsolidation` it first lets the
  host's model plan a MEMORY.md rewrite (``consolidateMemory``), commits it under the promotion
  lock with a preimage and a DREAMS.md ``## Memory Consolidation History`` summary, and falls
  back to the deterministic append whenever any step rejects.

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

from memory_core.bootstrap._js import js_to_well_formed
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifacts import read_dreams_file, resolve_dreams_path
from memory_core.consolidation.llm_consolidation import DeepConsolidation
from memory_core.consolidation.policy import DeepDreamingPolicy
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
    # "disabled" when a deep sweep got a policy with enabled=False (nothing promoted).
    skip_reason: str | None = None


def run_dreaming_sweep(
    *,
    config: MemoryConfig,
    store: ReindexableStore,
    phase: str,
    now_ms: int,
    timezone: str,
    limit: int = 5,
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
    policy: DeepDreamingPolicy | None = None,
    consolidation: DeepConsolidation | None = None,
) -> DreamingSweepResult:
    """Run one dreaming phase over the workspace's recall store.

    ``phase`` is ``"light"``, ``"rem"`` or ``"deep"`` (anything else raises
    ``ValueError``). Up to ``limit`` candidates are ranked without gates.
    Without ``policy`` the deep phase promotes with the default gates, the same
    ``limit`` and no age gate. With a resolved ``policy``
    (:func:`resolve_deep_dreaming_policy`) it behaves like the pin's deep phase
    (``dreaming.ts`` runShortTermDreamingPromotion): nothing is promoted when
    ``policy.enabled`` is false (``skip_reason="disabled"``), otherwise the
    policy's limit, gates, ``max_age_days``, ``recency_half_life_days`` and
    ``max_promoted_snippet_tokens`` apply. ``files_changed`` lists
    workspace-relative paths the sweep wrote; ``identity`` picks the promotion
    marker prefix of the deep phase. ``consolidation`` (default ``None``, and off unless its
    ``options.enabled`` is set and it carries a model) opts the deep phase into the host-injected
    LLM consolidation; see :func:`run_short_term_promotion`.
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

    skip_reason = None
    if phase == "deep" and policy is not None and not policy.enabled:
        skip_reason = "disabled"
    elif phase == "deep":
        gates: dict[str, Any] = {"limit": limit}
        if policy is not None:
            gates = {
                "limit": policy.limit,
                "min_score": policy.min_score,
                "min_recall_count": policy.min_recall_count,
                "min_unique_queries": policy.min_unique_queries,
                "max_age_days": policy.max_age_days,
                "recency_half_life_days": policy.recency_half_life_days,
                "max_promoted_snippet_tokens": policy.max_promoted_snippet_tokens,
                "max_prior_entry_loss_fraction": policy.max_prior_entry_loss_fraction,
            }
        dreams_before = _read_dreams(config.workspace_dir)
        promotion = run_short_term_promotion(
            config=config,
            store=store,
            now_ms=now_ms,
            timezone=timezone,
            identity=identity,
            consolidation=consolidation,
            **gates,
        )
        if promotion.outcome.should_write:
            files_changed.append(promotion.target)
        if _read_dreams(config.workspace_dir) != dreams_before:
            files_changed.append(resolve_dreams_path(config.workspace_dir).name)

    return DreamingSweepResult(
        phase=phase,
        candidates=tuple(candidates),
        phase_signals_recorded=phase_signals_recorded,
        files_changed=tuple(files_changed),
        promotion=promotion,
        skip_reason=skip_reason,
    )


def _read_dreams(workspace_dir: Path) -> str:
    return read_dreams_file(resolve_dreams_path(workspace_dir))


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
    # Stored snippets may end in a lone surrogate (UTF-16 cap); write it as U+FFFD.
    return js_to_well_formed(" ".join(value.strip().split()))


def _iso_seconds(now_ms: int) -> str:
    return datetime.fromtimestamp(now_ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
