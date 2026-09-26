"""Scored memory consolidation: short-term recall, promotion, dreaming, audit.

Port of the OpenClaw memory-core consolidation pipeline
(``extensions/memory-core/src/short-term-promotion.ts``, ``concept-vocabulary.ts``,
``memory-budget.ts`` via :mod:`memory_core.memory_budget`, the deep-phase config of
``src/memory-host-sdk/dreaming.ts`` and a simplified ``dreaming-phases.ts``) at
pin 4c42815348. It is the package's scored consolidation mode:

1. hosts record ``memory_search`` hits (:func:`record_short_term_recalls`) and
   daily-flush writes (:func:`record_daily_memory_flush`) as recall signals in
   ``memory/.dreams/short-term-recall.json``;
2. a dreaming sweep (:func:`run_dreaming_sweep`) adds light/REM phase signals,
   and the deep phase or a direct :func:`run_short_term_promotion` call
   promotes the entries that pass the score, signal, diversity and age gates
   into a dated ``## Promoted From Short-Term Memory`` section of MEMORY.md;
3. :func:`audit_short_term_promotion_artifacts` and
   :func:`repair_short_term_promotion_artifacts` inspect and fix the stores.

Nothing here runs on its own: there is no scheduler, and dreaming is off by
default (:data:`DEFAULT_DEEP_DREAMING_ENABLED`). The module knows no web
framework, UI or LLM. Evidence per behaviour lives in docs/parity_matrix.md.
"""

from memory_core.consolidation.audit import (
    ShortTermAuditIssue,
    ShortTermAuditSummary,
    ShortTermRepairResult,
    audit_short_term_promotion_artifacts,
    repair_short_term_promotion_artifacts,
)
from memory_core.consolidation.concepts import MAX_CONCEPT_TAGS, derive_concept_tags
from memory_core.consolidation.dreaming import (
    DREAMING_PHASES,
    DREAMS_FILE_NAME,
    DreamingSweepResult,
    run_dreaming_sweep,
    serialize_promotion_run,
)
from memory_core.consolidation.markers import (
    OPENCLAW_PROMOTION_MARKER_PREFIX,
    PROMOTION_MARKER_PREFIXES,
    MEMORY_CORE_PROMOTION_MARKER_PREFIX,
    extract_promotion_markers,
    format_promotion_marker,
)
from memory_core.consolidation.policy import (
    DEFAULT_DEEP_DREAMING_ENABLED,
    DEFAULT_DEEP_DREAMING_LIMIT,
    DEFAULT_DEEP_DREAMING_MAX_AGE_DAYS,
    DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS,
    DEFAULT_PROMOTION_MIN_RECALL_COUNT,
    DEFAULT_PROMOTION_MIN_SCORE,
    DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES,
    DEFAULT_RECENCY_HALF_LIFE_DAYS,
    DeepDreamingPolicy,
    resolve_deep_dreaming_policy,
)
from memory_core.consolidation.promotion import (
    PROMOTION_COMPONENT_WEIGHTS,
    MemoryPromotionRun,
    PromotionCandidate,
    PromotionEvaluation,
    PromotionWriteOutcome,
    ReindexableStore,
    evaluate_short_term_promotion_candidates,
    format_memory_dreaming_day,
    rank_short_term_promotion_candidates,
    run_short_term_promotion,
)
from memory_core.consolidation.recall import (
    is_contaminated_dreaming_snippet,
    record_daily_memory_flush,
    record_short_term_phase_signals,
    record_short_term_recalls,
)
from memory_core.consolidation.store import (
    SHORT_TERM_LOCK_RELATIVE_PATH,
    SHORT_TERM_LOCK_STALE_MS,
    SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH,
    SHORT_TERM_RECALL_MAX_ENTRIES,
    SHORT_TERM_RECALL_MAX_SNIPPET_CHARS,
    SHORT_TERM_STORE_RELATIVE_PATH,
    ShortTermLockResult,
    acquire_short_term_promotion_lock,
)
from memory_core.memory_budget import DEFAULT_MEMORY_FILE_MAX_CHARS

__all__ = [
    "DEFAULT_DEEP_DREAMING_ENABLED",
    "DEFAULT_DEEP_DREAMING_LIMIT",
    "DEFAULT_DEEP_DREAMING_MAX_AGE_DAYS",
    "DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS",
    "DEFAULT_MEMORY_FILE_MAX_CHARS",
    "DEFAULT_PROMOTION_MIN_RECALL_COUNT",
    "DEFAULT_PROMOTION_MIN_SCORE",
    "DEFAULT_PROMOTION_MIN_UNIQUE_QUERIES",
    "DEFAULT_RECENCY_HALF_LIFE_DAYS",
    "DREAMING_PHASES",
    "DREAMS_FILE_NAME",
    "DeepDreamingPolicy",
    "DreamingSweepResult",
    "MAX_CONCEPT_TAGS",
    "MemoryPromotionRun",
    "PROMOTION_COMPONENT_WEIGHTS",
    "OPENCLAW_PROMOTION_MARKER_PREFIX",
    "PROMOTION_MARKER_PREFIXES",
    "MEMORY_CORE_PROMOTION_MARKER_PREFIX",
    "PromotionCandidate",
    "PromotionEvaluation",
    "PromotionWriteOutcome",
    "ReindexableStore",
    "SHORT_TERM_LOCK_RELATIVE_PATH",
    "SHORT_TERM_LOCK_STALE_MS",
    "SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH",
    "SHORT_TERM_RECALL_MAX_ENTRIES",
    "SHORT_TERM_RECALL_MAX_SNIPPET_CHARS",
    "SHORT_TERM_STORE_RELATIVE_PATH",
    "ShortTermAuditIssue",
    "ShortTermAuditSummary",
    "ShortTermLockResult",
    "ShortTermRepairResult",
    "acquire_short_term_promotion_lock",
    "audit_short_term_promotion_artifacts",
    "derive_concept_tags",
    "evaluate_short_term_promotion_candidates",
    "extract_promotion_markers",
    "format_memory_dreaming_day",
    "format_promotion_marker",
    "is_contaminated_dreaming_snippet",
    "rank_short_term_promotion_candidates",
    "record_daily_memory_flush",
    "record_short_term_phase_signals",
    "record_short_term_recalls",
    "repair_short_term_promotion_artifacts",
    "resolve_deep_dreaming_policy",
    "run_dreaming_sweep",
    "run_short_term_promotion",
    "serialize_promotion_run",
]
