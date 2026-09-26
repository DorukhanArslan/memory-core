"""Scored promotion and dreaming on a live subject's own workspace.

Q16 extension (accepted 2026-09-26, no upstream counterpart): upstream runs
short-term promotion only on the agent workspace. :class:`SubjectConsolidation`
runs the same :mod:`memory_core.consolidation` pipeline on one
:class:`~memory_core.live.SubjectMemory` directory (``subjects/<id>/`` by default):
recall signals go to ``subjects/<id>/memory/.dreams/``, promotions to
``subjects/<id>/MEMORY.md`` and REM summaries to ``subjects/<id>/DREAMS.md``,
never to the agent workspace or another subject.

Behind ``FeatureFlags.subject_promotion`` (off by default): with the flag off
every method raises :class:`SubjectPromotionDisabledError` before touching the
workspace. Enable it per subject with
``SubjectMemory.open(..., flags=FeatureFlags(vector_search=False, subject_promotion=True))``.
Nothing runs on its own; the host decides when to record, promote or dream.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from memory_core.consolidation import (
    DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS,
    DEFAULT_MEMORY_FILE_MAX_CHARS,
    DEFAULT_PROMOTION_MIN_RECALL_COUNT,
    DEFAULT_PROMOTION_MIN_SCORE,
    DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
    DEFAULT_RECENCY_HALF_LIFE_DAYS,
    DreamingSweepResult,
    MemoryPromotionRun,
    ShortTermAuditSummary,
    ShortTermRepairResult,
    audit_short_term_promotion_artifacts,
    record_short_term_recalls,
    repair_short_term_promotion_artifacts,
    run_dreaming_sweep,
    run_short_term_promotion,
    undecorate_search_results,
)
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity

if TYPE_CHECKING:
    from memory_core.live import SubjectMemory


class SubjectPromotionDisabledError(RuntimeError):
    """Raised when subject consolidation runs without ``FeatureFlags.subject_promotion``."""


@dataclass(frozen=True)
class SubjectConsolidation:
    """Record, promote and dream over one subject's memory workspace.

    ``identity`` picks the promotion marker prefix written into the subject's
    MEMORY.md (neutral by default). All paths resolve under
    ``subject.memory.config.workspace_dir``; a promotion that writes
    reindexes the subject's own store.
    """

    subject: SubjectMemory
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY

    @property
    def enabled(self) -> bool:
        """True when the subject's config enables ``subject_promotion``."""
        return self.subject.memory.config.effective_flags().subject_promotion

    def record_recalls(
        self, query: str, results: Iterable[Mapping[str, Any]], *, now_ms: int
    ) -> int:
        """Record hits of ``subject.memory.search(query)`` as short-term recall signals.

        Citation suffixes are removed first (:func:`undecorate_search_results`);
        only ``memory/*.md`` hits count. Returns the number of entries touched.
        """
        self._require_enabled()
        return record_short_term_recalls(
            config=self.subject.memory.config,
            query=query,
            results=undecorate_search_results(results),
            now_ms=now_ms,
        )

    def promote(
        self,
        *,
        now_ms: int,
        timezone: str = "UTC",
        limit: int = 5,
        min_score: float = DEFAULT_PROMOTION_MIN_SCORE,
        min_recall_count: int = DEFAULT_PROMOTION_MIN_RECALL_COUNT,
        min_unique_queries: int = DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
        max_age_days: int = -1,
        recency_half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS,
        memory_file_max_chars: int = DEFAULT_MEMORY_FILE_MAX_CHARS,
        max_promoted_snippet_tokens: int = DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS,
    ) -> MemoryPromotionRun:
        """Run gated scored promotion into the subject's MEMORY.md.

        Same parameters and defaults as
        :func:`memory_core.consolidation.run_short_term_promotion`.
        """
        self._require_enabled()
        return run_short_term_promotion(
            config=self.subject.memory.config,
            store=self.subject.memory.store,
            now_ms=now_ms,
            timezone=timezone,
            limit=limit,
            min_score=min_score,
            min_recall_count=min_recall_count,
            min_unique_queries=min_unique_queries,
            max_age_days=max_age_days,
            recency_half_life_days=recency_half_life_days,
            memory_file_max_chars=memory_file_max_chars,
            max_promoted_snippet_tokens=max_promoted_snippet_tokens,
            identity=self.identity,
        )

    def dream(
        self, phase: str, *, now_ms: int, timezone: str = "UTC", limit: int = 5
    ) -> DreamingSweepResult:
        """Run one ``light``, ``rem`` or ``deep`` sweep over the subject's recall store.

        Same behaviour as :func:`memory_core.consolidation.run_dreaming_sweep`; a deep
        sweep that promotes reindexes the subject's store.
        """
        self._require_enabled()
        return run_dreaming_sweep(
            config=self.subject.memory.config,
            store=self.subject.memory.store,
            phase=phase,
            now_ms=now_ms,
            timezone=timezone,
            limit=limit,
            identity=self.identity,
        )

    def audit(self, *, now_ms: int) -> ShortTermAuditSummary:
        """Audit the subject's recall store (read-only)."""
        self._require_enabled()
        return audit_short_term_promotion_artifacts(self.subject.memory.config, now_ms)

    def repair(self, *, now_ms: int) -> ShortTermRepairResult:
        """Repair the subject's recall store and promotion lock."""
        self._require_enabled()
        return repair_short_term_promotion_artifacts(self.subject.memory.config, now_ms)

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise SubjectPromotionDisabledError(
                "subject promotion is disabled; enable FeatureFlags(subject_promotion=True) "
                f"for subject {self.subject.subject_id!r}"
            )
