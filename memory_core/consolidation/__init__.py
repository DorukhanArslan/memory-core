"""Scored memory consolidation: short-term recall, promotion, dreaming, audit.

Port of the OpenClaw memory-core consolidation pipeline
(``extensions/memory-core/src/short-term-promotion.ts``, ``concept-vocabulary.ts``,
``memory-budget.ts`` via :mod:`memory_core.memory_budget`, the deep-phase config of
``src/memory-host-sdk/dreaming.ts`` and a simplified ``dreaming-phases.ts``) at
pin 4c42815348. It is the package's scored consolidation mode:

1. hosts record ``memory_search`` hits (:func:`record_short_term_recalls`) as
   recall signals in ``memory/.dreams/short-term-recall.json``
   (``signal_type="daily"`` counts a daily signal, the kind upstream's light
   dreaming phase records);
2. a dreaming sweep (:func:`run_dreaming_sweep`) adds light/REM phase signals,
   and the deep phase or a direct :func:`run_short_term_promotion` call
   promotes the entries that pass the score, signal, diversity and age gates
   into a dated ``## Promoted From Short-Term Memory`` section of MEMORY.md;
3. :func:`audit_short_term_promotion_artifacts` and
   :func:`repair_short_term_promotion_artifacts` inspect and fix the stores.

Nothing here runs on its own: there is no scheduler. Dreaming is off by
default (:data:`DEFAULT_DEEP_DREAMING_ENABLED`): a deep sweep given a
resolved :class:`DeepDreamingPolicy` promotes nothing unless the policy
enables it; a call without a policy runs whenever the host makes it. The
module knows no web framework, UI or LLM client; the opt-in LLM consolidation step
(:mod:`~memory_core.consolidation.llm_consolidation`) takes a host-injected model callable. Evidence per behaviour lives in
docs/parity_matrix.md.
"""

from memory_core.consolidation.audit import (
    ShortTermAuditIssue,
    ShortTermAuditSummary,
    ShortTermRepairResult,
    audit_short_term_promotion_artifacts,
    repair_short_term_promotion_artifacts,
)
from memory_core.consolidation.artifacts import (
    append_consolidation_skipped_summary,
    append_consolidation_summary,
    read_memory_preimages,
    store_memory_preimage,
)
from memory_core.consolidation.concepts import MAX_CONCEPT_TAGS, derive_concept_tags
from memory_core.consolidation.daily_ingestion import (
    build_daily_ingestion_results,
    ingest_daily_memory_signals,
    seed_historical_daily_memory_signals,
)
from memory_core.consolidation.dreaming import (
    DREAMING_PHASES,
    DREAMS_FILE_NAME,
    DreamingIngestion,
    DreamingSweepResult,
    run_dreaming_sweep,
)
from memory_core.consolidation.forget import (
    MemoryForgetReport,
    MemorySessionTarget,
    SessionArchive,
    SessionInstance,
    forget_memory_entries,
    resolve_memory_session_targets,
)
from memory_core.consolidation.host_events import (
    build_recall_recorded_event,
    build_recall_skipped_event,
)
from memory_core.consolidation.session_ingestion import (
    SessionAdmissionPolicy,
    SessionCorpusEntry,
    ingest_session_transcript_signals,
    resolve_admission_policy,
    scan_session_ingestion_source,
)
from memory_core.consolidation.llm_consolidation import (
    CONSOLIDATION_SYSTEM_PROMPT,
    ConsolidationModel,
    ConsolidationRequest,
    DeepConsolidation,
    LlmConsolidationOptions,
    LlmConsolidationOutcome,
    MemoryConsolidationPlan,
    MemoryConsolidationResult,
    apply_memory_consolidation_plan,
    consolidate_memory,
    run_llm_consolidation,
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
    DEFAULT_DEEP_DREAMING_MIN_RECALL_COUNT,
    DEFAULT_DEEP_DREAMING_MIN_SCORE,
    DEFAULT_DEEP_DREAMING_MIN_UNIQUE_QUERIES,
    DEFAULT_RECENCY_HALF_LIFE_DAYS,
    DeepDreamingPolicy,
    resolve_deep_dreaming_policy,
)
from memory_core.consolidation.file_lock import (
    FileLockError,
    FileLockOptions,
    FileLockStaleError,
    FileLockTimeoutError,
    resolve_memory_promotion_lock_target,
    with_file_lock,
)
from memory_core.consolidation.artifact_provenance import (
    MemoryArtifactProvenance,
    MemoryArtifactProvenanceStore,
)
from memory_core.consolidation.origins import (
    MemoryEntryOrigin,
    IndexRevisionFence,
    MemoryEntryOriginLedger,
    MemoryIndexRevisionConflictError,
    MemorySessionTombstone,
    prune_memory_entry_origins,
    reserve_memory_entry_origins,
)
from memory_core.consolidation.promotion import (
    PROMOTION_COMPONENT_WEIGHTS,
    MemoryPromotionRun,
    PromotionCandidate,
    PromotionEvaluation,
    PromotionRejection,
    PromotionWriteOutcome,
    ReindexableStore,
    build_promotion_applied_event,
    evaluate_short_term_promotion_candidates,
    is_promotion_origin_blocked,
    format_memory_dreaming_day,
    rank_short_term_promotion_candidates,
    run_short_term_promotion,
)
from memory_core.consolidation.recall import (
    is_contaminated_dreaming_snippet,
    record_short_term_phase_signals,
    record_short_term_recalls,
    undecorate_search_results,
)
from memory_core.consolidation.store import (
    SHORT_TERM_LOCK_RELATIVE_PATH,
    SHORT_TERM_LOCK_STALE_MS,
    SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH,
    SHORT_TERM_RECALL_MAX_ENTRIES,
    SHORT_TERM_RECALL_MAX_SNIPPET_CHARS,
    SHORT_TERM_STORE_RELATIVE_PATH,
    MemoryWorkspaceLockHeldError,
    ShortTermLockResult,
    acquire_short_term_promotion_lock,
    memory_workspace_lock,
)
from memory_core.memory_budget import DEFAULT_MEMORY_FILE_MAX_CHARS

__all__ = [
    "DreamingIngestion",
    "IndexRevisionFence",
    "MemoryForgetReport",
    "MemorySessionTarget",
    "SessionAdmissionPolicy",
    "SessionArchive",
    "SessionCorpusEntry",
    "SessionInstance",
    "build_daily_ingestion_results",
    "build_recall_recorded_event",
    "build_recall_skipped_event",
    "forget_memory_entries",
    "ingest_daily_memory_signals",
    "ingest_session_transcript_signals",
    "resolve_admission_policy",
    "resolve_memory_session_targets",
    "scan_session_ingestion_source",
    "seed_historical_daily_memory_signals",
    "FileLockError",
    "FileLockOptions",
    "FileLockStaleError",
    "FileLockTimeoutError",
    "MemoryArtifactProvenance",
    "MemoryArtifactProvenanceStore",
    "MemoryEntryOrigin",
    "MemoryEntryOriginLedger",
    "MemoryIndexRevisionConflictError",
    "MemorySessionTombstone",
    "MemoryWorkspaceLockHeldError",
    "PromotionRejection",
    "build_promotion_applied_event",
    "is_promotion_origin_blocked",
    "memory_workspace_lock",
    "prune_memory_entry_origins",
    "reserve_memory_entry_origins",
    "resolve_memory_promotion_lock_target",
    "with_file_lock",
    "DeepConsolidation",
    "append_consolidation_skipped_summary",
    "append_consolidation_summary",
    "read_memory_preimages",
    "store_memory_preimage",
    "CONSOLIDATION_SYSTEM_PROMPT",
    "ConsolidationModel",
    "ConsolidationRequest",
    "LlmConsolidationOptions",
    "LlmConsolidationOutcome",
    "MemoryConsolidationPlan",
    "MemoryConsolidationResult",
    "apply_memory_consolidation_plan",
    "consolidate_memory",
    "run_llm_consolidation",
    "DEFAULT_DEEP_DREAMING_ENABLED",
    "DEFAULT_DEEP_DREAMING_LIMIT",
    "DEFAULT_DEEP_DREAMING_MAX_AGE_DAYS",
    "DEFAULT_DEEP_DREAMING_MAX_PROMOTED_SNIPPET_TOKENS",
    "DEFAULT_DEEP_DREAMING_MIN_RECALL_COUNT",
    "DEFAULT_DEEP_DREAMING_MIN_SCORE",
    "DEFAULT_DEEP_DREAMING_MIN_UNIQUE_QUERIES",
    "DEFAULT_MEMORY_FILE_MAX_CHARS",
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
    "record_short_term_phase_signals",
    "record_short_term_recalls",
    "repair_short_term_promotion_artifacts",
    "resolve_deep_dreaming_policy",
    "run_dreaming_sweep",
    "run_short_term_promotion",
    "undecorate_search_results",
]
