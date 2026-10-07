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
  back to the deterministic append whenever any step rejects;
- ``ingestion=`` (:class:`DreamingIngestion`) makes a light or REM sweep first ingest the daily
  notes (:mod:`~memory_core.consolidation.daily_ingestion`) and the live session transcripts
  (:mod:`~memory_core.consolidation.session_ingestion`) as ``daily`` recall signals, like
  upstream's ``ingestDreamingPhaseSignals``; the ranking below still sees only entries with a
  recall (upstream's light phase also stages daily-only entries).

Known gaps (parity matrix rows "Light dreaming phase signals", "REM dreaming
phase signals", "Deep dreaming application flow"): no REM narrative or
evidence extraction, no light-phase metadata, no scheduler or cron; sweeps run
only when a host calls them (dreaming is off by default).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memory_core.bootstrap._js import js_to_well_formed
from memory_core.config import MemoryConfig
from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.consolidation.artifacts import read_dreams_file, resolve_dreams_path
from memory_core.consolidation.daily_ingestion import (
    DailyIngestionCollection,
    daily_ingestion_lookback_days,
    ingest_daily_memory_signals,
)
from memory_core.consolidation.llm_consolidation import DeepConsolidation
from memory_core.consolidation.origins import MemoryEntryOriginLedger
from memory_core.consolidation.policy import DeepDreamingPolicy
from memory_core.consolidation.promotion import (
    MemoryPromotionRun,
    PromotionCandidate,
    ReindexableStore,
    rank_short_term_promotion_candidates,
    run_short_term_promotion,
)
from memory_core.consolidation.recall import record_short_term_phase_signals
from memory_core.consolidation.session_ingestion import (
    SessionAdmissionPolicy,
    SessionCorpusEntry,
    SessionIngestionCollection,
    ingest_session_transcript_signals,
)
from memory_core.consolidation.store import SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity

DREAMING_PHASES = frozenset({"light", "rem", "deep"})
DREAMS_FILE_NAME = "DREAMS.md"


DEFAULT_PHASE_LOOKBACK_DAYS = {"light": 2, "rem": 7}
DEFAULT_PHASE_INGESTION_LIMIT = {"light": 100, "rem": 10}


@dataclass(frozen=True)
class DreamingIngestion:
    """What the light and REM sweeps ingest before they rank (``ingestDreamingPhaseSignals``).

    The daily notes of the last ``max(14, lookback_days)`` days become ``daily`` recall signals
    (:mod:`memory_core.consolidation.daily_ingestion`; ``provenance`` is the flush's trust store) and,
    when ``agent_ids`` and ``corpus_entries`` are given, the new messages of the live interactive
    sessions too (:mod:`memory_core.consolidation.session_ingestion`). ``lookback_days`` and ``limit``
    default to the phase's own (light 2 days and 100, REM 7 days and 10, upstream's defaults).
    """

    lookback_days: float | None = None
    limit: int | None = None
    provenance: MemoryArtifactProvenanceStore | None = None
    agent_ids: Sequence[str] | None = None
    corpus_entries: Callable[[str], Iterable[SessionCorpusEntry]] | None = None
    admission_policy: SessionAdmissionPolicy | None = None
    load_session_metadata: Callable[..., Any] | None = None
    redact_text: Callable[[str], str] | None = None


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
    # The daily and session ingestion of a light or REM sweep given ``ingestion``.
    daily_ingestion: DailyIngestionCollection | None = None
    session_ingestion: SessionIngestionCollection | None = None


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
    agent_id: str | None = None,
    workspace_agent_ids: Sequence[str] = (),
    origins: MemoryEntryOriginLedger | None = None,
    state_dir: str | Path | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    ingestion: DreamingIngestion | None = None,
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
    LLM consolidation; see :func:`run_short_term_promotion`, which also explains ``agent_id``,
    ``workspace_agent_ids`` and ``origins`` (the memory-entry origins ledger), ``state_dir`` (the
    sidecar lock's directory) and ``on_event`` (the host callback of the
    ``memory.promotion.applied`` event; the light and REM sweeps pass it to the ``memory.recall.*``
    events of their ingestion too). ``ingestion`` (default ``None``: none) makes a light or REM sweep
    ingest the daily notes and the session transcripts first, like upstream's phases
    (:class:`DreamingIngestion`).
    """
    if phase not in DREAMING_PHASES:
        raise ValueError(f"unsupported dreaming phase: {phase}")

    daily_result = session_result = None
    if ingestion is not None and phase in {"light", "rem"}:
        lookback = (
            ingestion.lookback_days
            if ingestion.lookback_days is not None
            else DEFAULT_PHASE_LOOKBACK_DAYS[phase]
        )
        ingestion_limit = ingestion.limit if ingestion.limit is not None else DEFAULT_PHASE_INGESTION_LIMIT[phase]
        daily_result = ingest_daily_memory_signals(
            config=config,
            now_ms=now_ms,
            lookback_days=daily_ingestion_lookback_days(lookback),
            limit=ingestion_limit,
            timezone=timezone,
            provenance=ingestion.provenance,
            origins=origins,
            on_event=on_event,
        )
        if ingestion.corpus_entries is not None:
            session_result = ingest_session_transcript_signals(
                config=config,
                agent_ids=ingestion.agent_ids,
                corpus_entries=ingestion.corpus_entries,
                lookback_days=lookback,
                now_ms=now_ms,
                timezone=timezone,
                admission_policy=ingestion.admission_policy,
                origins=origins,
                load_session_metadata=ingestion.load_session_metadata,
                redact_text=ingestion.redact_text,
                runtime_identity=identity,
                on_event=on_event,
            )

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
            agent_id=agent_id,
            workspace_agent_ids=workspace_agent_ids,
            origins=origins,
            state_dir=state_dir,
            on_event=on_event,
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
        daily_ingestion=daily_result,
        session_ingestion=session_result,
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
