# Changelog

memory-core follows [Semantic Versioning](https://semver.org/); before 1.0 a minor release may
break the API. Nothing is published to a package index yet.

## 0.2.0 (unreleased)

The first installable release: a host installs `memory-core` and runs memory for its agent through
the host kit. 0.1.0 is `main` at `b829bad` (2026-09-27), which had no build system.

### Added

- `memory_core.host`, the host kit (docs/host_kit.md): one `HostKit` per workspace with
  `tools()`, `dispatch()`, `before_turn()`, `after_turn()`, `on_new_session()` and
  `heartbeat_prompt()`, one `SessionState` per session, and the handles they return
  (`TurnContext`, `TurnRecord`, `FlushRequest`, `FlushOutcome`, `NewSession`, `ResetTurn`,
  `HeartbeatRun`, `HeartbeatOutcome`, `TurnUsage`). `HostKit.request_flush()` is a labelled
  memory-core extension (a forced flush once per compaction cycle), not upstream behaviour.
- `memory_core.memory_flush.ensure_memory_flush_target_file`, the port of upstream's
  `ensureMemoryFlushTargetFile`; `memory_core.workspace.append_daily_memory_file`, the locked daily
  append the flush write and the curated daily note share; `memory_core.heartbeat.resolve_message_text`
  (upstream's `resolveMessageText`).
- Packaging: a hatchling build (wheel and sdist). The core depends on `httpx` only; the Lab's
  `fastapi`, `jinja2` and `uvicorn` are the `demo` extra, and `dev` (pytest, ruff) includes it.

### Changed

- The package root exports 24 names instead of 171 (below): the host kit classes and
  `WorkspaceStateMigrationRequiredError` are new there, 154 names moved to their submodules
  (table below) and 5 were removed.
- The daily flush write and `MemoryCurator.append_daily_note` skip only content whose stripped
  text is exactly `NO_REPLY` (and empty content): `NO_REPLY_FACTS: ...` and any other text that
  only starts with the token is written now. Upstream's `write` appends even the exact token.
- The curated daily note's symlink refusals read
  `memory/ is a symlink; memory writes never follow symlinks` and
  `memory/<date>.md is a symlink; memory writes never follow symlinks`.
- Recording short-term recalls, marking promotions and repairing the recall store hold one
  process-wide lock per store file, so parallel recordings lose no update.

### Removed

- `Memory.prepare_turn()`, `Memory.chat()` and `Memory.record_turn()`, with
  `MemoryChatTurn`, `MemoryChatResult`, `MemoryRecordResult` and `DEFAULT_CHAT_SYSTEM_PROMPT`.
  Use `memory_core.host` (README Quickstart, `examples/quickstart.py`): the model recalls through
  the memory tools (`HostKit.tools()`, `HostKit.dispatch()`), and the flush is decided after
  the reply (`HostKit.after_turn()`) and written through the append-only `write` tool of its
  `FlushRequest`.
- `record_daily_memory_flush`. Record a daily signal with
  `memory_core.consolidation.record_short_term_recalls(..., signal_type="daily")`.

### Package root

`from memory_core import ...` offers:

- the host kit: `HostKit`, `SessionState`, `TurnUsage`, `TurnContext`, `TurnRecord`,
  `FlushRequest`, `FlushOutcome`, `NewSession`, `ResetTurn`, `HeartbeatRun`, `HeartbeatOutcome`
- the core handle and its configuration: `Memory`, `MemoryConfig`, `FeatureFlags`
- embeddings: `EmbeddingProvider`, `OpenAICompatibleEmbeddingProvider`
- workspace layouts: `WorkspaceLayout`, `MEMORY_CORE_WORKSPACE_LAYOUT`, `OPENCLAW_COMPAT_LAYOUT`
- errors: `MemoryToolInputError`, `CurationError`, `UnsafeMemoryPathError`,
  `WorkspaceStateMigrationRequiredError`
- `__version__`

### Moved out of the package root

Import each name from the module in its row (for example
`from memory_core.memory_flush import build_memory_flush_plan`).

| Module | Names |
| --- | --- |
| `memory_core.adapters.langgraph` | `format_memory_context`, `LangGraphMemoryRecall` |
| `memory_core.automation` | `AutomationJob`, `AutomationStore`, `due_automation_jobs`, `FileAutomationStore`, `heartbeat_scheduled_tasks`, `record_automation_job_run` |
| `memory_core.bootstrap` | `bootstrap_status`, `build_bootstrap_context_files`, `build_startup_context`, `build_workspace_context`, `ContextFile`, `DEFAULT_WORKSPACE_LAYOUT`, `initialize_agent_workspace`, `load_workspace_bootstrap_files`, `WorkspaceBootstrapFile`, `WorkspaceContext`, `WorkspaceInitResult`, `WorkspaceSetupState` |
| `memory_core.client` | `DEFAULT_MEMORY_MD_TEMPLATE`, `initialize_memory_core_workspace` |
| `memory_core.consolidation` | `audit_short_term_promotion_artifacts`, `DeepDreamingPolicy`, `DreamingSweepResult`, `MemoryPromotionRun`, `record_short_term_recalls`, `repair_short_term_promotion_artifacts`, `resolve_deep_dreaming_policy`, `run_dreaming_sweep`, `run_short_term_promotion` |
| `memory_core.context_engine_lifecycle` | `assemble_context_engine_messages`, `build_context_engine_conversation_snapshot`, `strip_runtime_context_custom_messages` |
| `memory_core.curation` | `CurationPolicy`, `CurationResult`, `CurationUnavailableError`, `MemoryCurator` |
| `memory_core.embeddings` | `FakeEmbeddingProvider` |
| `memory_core.heartbeat` | `decide_heartbeat_reply`, `HEARTBEAT_PROMPT`, `HEARTBEAT_TOKEN`, `HeartbeatReplyDecision`, `HeartbeatScheduledTask`, `HeartbeatTurn`, `prepare_heartbeat_turn`, `resolve_heartbeat_interval_ms`, `strip_heartbeat_token` |
| `memory_core.heartbeat_scratch` | `HeartbeatScratchState`, `HeartbeatScratchStore` |
| `memory_core.history` | `get_history_limit_from_session_key`, `limit_history_turns` |
| `memory_core.live` | `IdentityLoadError`, `JsonlTraceSink`, `LIVE_TURN_COMPLETED`, `LIVE_TURN_FAILED`, `LIVE_TURN_STARTED`, `LiveIdentity`, `LiveIdentityStore`, `LiveSDKConfig`, `LiveTurnContext`, `LiveTurnEvent`, `LiveTurnEventType`, `MEMORY_RECALL_COMPLETED`, `PreparedLiveTurn`, `PROMPT_ASSEMBLED`, `PROVIDER_EVENT`, `SENTENCE`, `SentenceBoundaryPolicy`, `SESSION_SUMMARY_COMPLETED`, `SESSION_SUMMARY_FAILED`, `SESSION_SUMMARY_SKIPPED`, `SESSION_SUMMARY_STARTED`, `SessionSummaryResult`, `SessionSummarySkipReason`, `SubjectMemory`, `SubjectPathBuilder`, `TEXT_DELTA`, `TraceSink`, `UnknownIdentityFilePolicy` |
| `memory_core.live.consolidation` | `SubjectConsolidation`, `SubjectPromotionDisabledError` |
| `memory_core.memory_flush` | `build_memory_flush_plan`, `build_memory_flush_plan_from_config`, `DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR`, `DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES`, `DEFAULT_MEMORY_FLUSH_SOFT_TOKENS`, `explain_memory_flush_trigger`, `followup_uses_cli_runtime`, `has_already_flushed_for_current_compaction`, `MAX_FLUSH_FAILURES`, `MemoryFlushFailureOutcome`, `MemoryFlushPlan`, `MemoryFlushTriggerDecision`, `record_memory_flush_failure`, `record_memory_flush_success`, `resolve_compaction_threshold`, `resolve_memory_flush_threshold`, `SESSION_TOTAL_TOKENS_VERSION`, `should_force_memory_flush_by_transcript_size`, `should_run_memory_flush`, `should_run_memory_flush_trigger`, `UnsafeMemoryFlushTargetError`, `validate_daily_memory_target` |
| `memory_core.overflow_recovery` | `classify_overflow_error`, `decide_provider_overflow_recovery`, `extract_observed_overflow_token_count`, `is_compaction_failure_error`, `is_context_overflow_error`, `is_likely_context_overflow_error`, `OverflowClassification`, `ProviderOverflowRecoveryDecision` |
| `memory_core.preemptive_compaction` | `estimate_pre_prompt_tokens`, `estimate_tool_result_reduction_potential`, `PreemptiveCompactionDecision`, `SessionToolResultTruncationResult`, `should_preemptively_compact_before_prompt`, `ToolResultReductionPotential`, `truncate_oversized_tool_results_in_session_file`, `truncate_tool_result_text` |
| `memory_core.replay_history` | `normalize_assistant_replay_content`, `STREAM_ERROR_FALLBACK_TEXT` |
| `memory_core.replay_repair` | `repair_tool_use_result_pairing`, `sanitize_tool_use_result_pairing`, `ToolUseRepairReport` |
| `memory_core.runtime_context_prompt` | `build_current_inbound_prompt`, `build_current_inbound_prompt_context_prefix`, `build_runtime_context_custom_message`, `build_runtime_context_system_context`, `build_runtime_event_system_context`, `resolve_runtime_context_prompt_parts`, `MEMORY_CORE_RUNTIME_CONTEXT_CUSTOM_TYPE` |
| `memory_core.runtime_identity` | `OPENCLAW_COMPAT_RUNTIME_IDENTITY`, `RuntimeIdentity`, `MEMORY_CORE_RUNTIME_IDENTITY` |
| `memory_core.session_corpus` | `SessionCorpusFile`, `MemoryCoreSessionCorpus` |
| `memory_core.session_memory` | `is_session_memory_trigger`, `save_session_memory`, `SessionMemoryResult` |
| `memory_core.supplements` | `MemoryCorpusResult`, `MemoryCorpusSupplement`, `sort_corpus_results`, `StaticMemoryCorpusSupplement` |
| `memory_core.tools.common` | `to_tool_error` |
| `memory_core.tools.memory_get` | `execute_memory_get_tool`, `memory_get`, `memory_get_tool_definition` |
| `memory_core.tools.memory_search` | `execute_memory_search_tool`, `memory_search`, `memory_search_tool_definition` |
| `memory_core.workspace` | `MemoryFile`, `MemoryReadResult`, `MemoryWorkspace` |
