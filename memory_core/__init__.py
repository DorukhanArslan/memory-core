"""memory-core public package surface.

The package root exposes the stable, plug-and-play memory-core surface. Runtime
parity helpers remain available from their modules and selected helpers are
re-exported here when they are useful for host integrations. OpenClaw remains
the upstream parity target for source-backed and oracle-backed behavior.
"""

from memory_core.adapters.langgraph import LangGraphMemoryRecall, format_memory_context
from memory_core.runtime_identity import RuntimeIdentity, OPENCLAW_COMPAT_RUNTIME_IDENTITY, MEMORY_CORE_RUNTIME_IDENTITY
from memory_core.client import (
    DEFAULT_CHAT_SYSTEM_PROMPT,
    DEFAULT_MEMORY_MD_TEMPLATE,
    MemoryChatResult,
    MemoryChatTurn,
    MemoryRecordResult,
    Memory,
    initialize_memory_core_workspace,
)
from memory_core.config import MemoryConfig
from memory_core.context_engine_lifecycle import (
    assemble_context_engine_messages,
    build_context_engine_conversation_snapshot,
    strip_runtime_context_custom_messages,
)
from memory_core.history import get_history_limit_from_session_key, limit_history_turns
from memory_core.memory_flush import (
    DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES,
    DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
    DEFAULT_PI_COMPACTION_RESERVE_TOKENS_FLOOR,
    MemoryFlushPlan,
    MemoryFlushTriggerDecision,
    UnsafeMemoryFlushTargetError,
    build_memory_flush_plan,
    build_memory_flush_plan_from_config,
    explain_memory_flush_trigger,
    has_already_flushed_for_current_compaction,
    should_force_memory_flush_by_transcript_size,
    should_run_memory_flush,
    should_run_memory_flush_trigger,
    validate_daily_memory_target,
)
from memory_core.overflow_recovery import (
    OverflowClassification,
    ProviderOverflowRecoveryDecision,
    classify_overflow_error,
    decide_provider_overflow_recovery,
    extract_observed_overflow_token_count,
    is_compaction_failure_error,
    is_context_overflow_error,
    is_likely_context_overflow_error,
)
from memory_core.preemptive_compaction import (
    PreemptiveCompactionDecision,
    SessionToolResultTruncationResult,
    ToolResultReductionPotential,
    estimate_pre_prompt_tokens,
    estimate_tool_result_reduction_potential,
    should_preemptively_compact_before_prompt,
    truncate_oversized_tool_results_in_session_file,
    truncate_tool_result_text,
)
from memory_core.replay_history import (
    STREAM_ERROR_FALLBACK_TEXT,
    normalize_assistant_replay_content,
)
from memory_core.replay_repair import (
    ToolUseRepairReport,
    repair_tool_use_result_pairing,
    sanitize_tool_use_result_pairing,
)
from memory_core.runtime_context_prompt import (
    MEMORY_CORE_RUNTIME_CONTEXT_CUSTOM_TYPE,
    build_current_inbound_prompt,
    build_current_inbound_prompt_context_prefix,
    build_runtime_context_custom_message,
    build_runtime_context_system_context,
    build_runtime_event_system_context,
    resolve_runtime_context_prompt_parts,
)
from memory_core.session_corpus import MemoryCoreSessionCorpus, SessionCorpusFile
from memory_core.supplements import (
    MemoryCorpusResult,
    MemoryCorpusSupplement,
    StaticMemoryCorpusSupplement,
    sort_corpus_results,
)
from memory_core.tools.memory_get import memory_get
from memory_core.tools.memory_search import memory_search
from memory_core.workspace import (
    MemoryFile,
    MemoryReadResult,
    MemoryWorkspace,
    UnsafeMemoryPathError,
)

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_CHAT_SYSTEM_PROMPT",
    "DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES",
    "DEFAULT_MEMORY_FLUSH_SOFT_TOKENS",
    "DEFAULT_MEMORY_MD_TEMPLATE",
    "DEFAULT_PI_COMPACTION_RESERVE_TOKENS_FLOOR",
    "LangGraphMemoryRecall",
    "RuntimeIdentity",
    "OPENCLAW_COMPAT_RUNTIME_IDENTITY",
    "MEMORY_CORE_RUNTIME_CONTEXT_CUSTOM_TYPE",
    "MEMORY_CORE_RUNTIME_IDENTITY",
    "Memory",
    "STREAM_ERROR_FALLBACK_TEXT",
    "MemoryConfig",
    "MemoryCorpusResult",
    "MemoryCorpusSupplement",
    "MemoryChatTurn",
    "MemoryChatResult",
    "MemoryFile",
    "MemoryFlushPlan",
    "MemoryFlushTriggerDecision",
    "MemoryReadResult",
    "MemoryRecordResult",
    "MemoryWorkspace",
    "MemoryCoreSessionCorpus",
    "OverflowClassification",
    "PreemptiveCompactionDecision",
    "ProviderOverflowRecoveryDecision",
    "SessionCorpusFile",
    "SessionToolResultTruncationResult",
    "StaticMemoryCorpusSupplement",
    "ToolResultReductionPotential",
    "ToolUseRepairReport",
    "UnsafeMemoryFlushTargetError",
    "UnsafeMemoryPathError",
    "__version__",
    "assemble_context_engine_messages",
    "build_context_engine_conversation_snapshot",
    "build_current_inbound_prompt",
    "build_current_inbound_prompt_context_prefix",
    "build_memory_flush_plan",
    "build_memory_flush_plan_from_config",
    "build_runtime_context_custom_message",
    "build_runtime_context_system_context",
    "build_runtime_event_system_context",
    "classify_overflow_error",
    "decide_provider_overflow_recovery",
    "estimate_pre_prompt_tokens",
    "estimate_tool_result_reduction_potential",
    "explain_memory_flush_trigger",
    "extract_observed_overflow_token_count",
    "format_memory_context",
    "get_history_limit_from_session_key",
    "has_already_flushed_for_current_compaction",
    "initialize_memory_core_workspace",
    "is_compaction_failure_error",
    "is_context_overflow_error",
    "is_likely_context_overflow_error",
    "limit_history_turns",
    "memory_get",
    "memory_search",
    "normalize_assistant_replay_content",
    "repair_tool_use_result_pairing",
    "resolve_runtime_context_prompt_parts",
    "sanitize_tool_use_result_pairing",
    "should_force_memory_flush_by_transcript_size",
    "should_preemptively_compact_before_prompt",
    "should_run_memory_flush",
    "should_run_memory_flush_trigger",
    "sort_corpus_results",
    "strip_runtime_context_custom_messages",
    "truncate_oversized_tool_results_in_session_file",
    "truncate_tool_result_text",
    "validate_daily_memory_target",
]
