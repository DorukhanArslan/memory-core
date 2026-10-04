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
- For framework hosts (docs/host_kit.md › LangGraph findings): `TurnState`, the turn in flight
  as JSON (session, system prompt, runtime context, tools and the reset turn:
  `from_context`, `to_json`, `from_json`), with `ResetTurn.to_json()` / `from_json()`, for a
  host whose steps run apart; `HostKit.dispatcher(session)`, `dispatch` bound to one session
  in the two-argument shape of `FlushRequest.dispatch`; a `redact` input on
  `HostKit.after_turn()` for the message of a flush target that cannot be created, as
  `FlushRequest.complete(redact=)` has; and `HostKit.repair_tool_calls(messages,
  allowed_tool_names=)` with `ToolCallRepair`, upstream's replay repair of tool calls
  (`sanitizeToolCallInputs`, then `sanitizeToolUseResultPairingForModel`) over a host's
  chat-completions rows, which answers a call a failed turn left without its result with
  upstream's synthetic error result on the model's copy of the history.
- `memory_core.replay_repair.sanitize_tool_call_inputs`, the port of upstream's
  `sanitizeToolCallInputs` (its general branch), with
  `sanitize_tool_use_result_pairing_for_model`, `is_synthetic_missing_tool_result`,
  `ToolUseRepairReport.discarded` and the constant `TOOL_CALL_BLOCK_TYPES` (upstream's six
  tool-call block types, `src/shared/tool-block-contract.ts`); the module now has an `__all__`
  (`AgentMessage`, `DEFAULT_MISSING_TOOL_RESULT_TEXT` and `SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY`
  included), so a star import no longer brings its incidental imports.
- `memory_core.memory_flush.ensure_memory_flush_target_file`, the port of upstream's
  `ensureMemoryFlushTargetFile`; `memory_core.workspace.append_daily_memory_file`, the locked daily
  append the flush write and the curated daily note share; `memory_core.heartbeat.resolve_message_text`
  (upstream's `resolveMessageText`).
- One declaration of the project name: `[project] name` and `display-name` in `[tool.memory_core]`
  of pyproject.toml. `memory_core.project_name` derives the other forms, which runtime code and
  the Lab use instead of spelling the name; `scripts/rename_project.py --to <name>` renames the
  project and `--check` checks that the name is spelled consistently (README › Rename the
  Project).
- Packaging: a hatchling build (wheel and sdist). The core depends on `httpx` only; the Lab's
  `fastapi`, `jinja2` and `uvicorn` are the `demo` extra; `langgraph` and `langchain-core` are
  the `langgraph` extra (the stack the LangGraph adapter is tested against; the adapter imports
  neither); the `dev` dependency group (PEP 735: pytest, ruff, langchain-openai and both
  extras) is for a checkout and stays out of the package metadata.
- The LangGraph host integration (docs/integrations/langgraph.md):
  `memory_core.adapters.langgraph` holds `transcript_rows`, `turn_usage`, `has_tool_calls`,
  `tool_messages` and `repair_tool_calls`, framework-free helpers for a LangGraph graph over
  the host kit (adapter-only), with the type aliases `ToolDispatch` and `ToolCallRepairer` of
  their callable arguments, and
  `examples/langgraph_agent.py` is the graph a LangGraph app copies (`build_graph`: the kit's
  prompt and tools, the turn in flight as a `TurnState` in the graph state, a tools node over
  `HostKit.dispatcher`, the kit's tool-call repair on every model call, the flush after the
  reply on the same model, `/new` and `/reset`, the session state in a checkpointer) with a
  terminal `main` for any OpenAI-compatible endpoint.

### Changed

- Search ranking follows OpenClaw v2026.9.6 (port plan area 6): chunks are sized in CJK-weighted
  characters (`tokens * 4`) and `MEMORY.md` / `USER.md` chunk per `- ` entry and heading; keyword
  retrieval searches chunk text and file paths (a query naming a file, basename or stem ranks it in
  an exact-path tier) and scores hits with the tag's lexical boost; the hybrid merge, selection,
  MMR and temporal decay are the tag's (dated files with a suffix or in subdirectories decay, USER.md
  is evergreen, snippets are cut at 700 characters). **Defaults change:** `MemoryConfig` weights are
  0.7 / 0.3 and MMR and temporal decay are on (`FeatureFlags.mmr`, `temporal_decay` default on); all
  stay configurable. An FTS-only result's `score` is the boosted ranking score, `textScore` the raw
  BM25 one. The paused-index warning and action are the tag's (`RuntimeIdentity.memory_index_*`).
  Existing indexes need `SQLiteMemoryStore.reindex` (new path table, new chunks).

- The memory tools follow OpenClaw v2026.9.6 (port plan area 5, docs/memory_search_tool.md):
  - `memory_get` results carry `status` (`ok`, `not_found`, `error`); a refused or failed read is
    `{"path", "text": "", "status": "error", "code", "error"}` (`MEMORY_PATH_NOT_ALLOWED` for a path
    outside the memory files) and `disabled` is gone. USER.md is a memory path. `corpus=wiki` and
    `corpus=all` add `corpora`, `warning` and `error`.
  - `memory_search` and `memory_get` read an unknown `corpus` as an error instead of searching every
    source, and a blank `maxResults`, `from` or `lines` as omitted. Their descriptions and schemas
    are the tag's (USER.md, the outcome guidance, `minimum`, `additionalProperties: false`), and
    `build_prompt_section` is the tag's `## Memory Recall` with the session-history lines.
  - The memory deadline is 30 s (was 15 s). With `corpus=all` (the facade's default) or `wiki`, each
    corpus has its own outcome in `corpora`, so a failed memory corpus is reported next to the wiki
    hits instead of as the unavailable result; use `corpus="memory"` for that result. A deadline
    with keyword hits returns them as `partial: true` and records no cooldown. New:
    `MemoryConfig.session_search` (default on), `SQLiteMemoryStore.search_memory_keywords`.
  - `SQLiteMemoryStore.index_identity()` returns upstream's diagnostics (`code`, `owner`,
    `versionOrder`, `chunkingVersionOnly`), and a reindex writes `provenanceVersion` and
    `chunkingVersion`. **An index written by an earlier memory-core has neither, so search is
    paused (`index provenance classifier changed`) until `SQLiteMemoryStore.reindex(workspace)`
    runs.** The recorded chunking version is the tag's before the chunker is re-ported (area 6).

- The project name is now memory-core (0.1.0 used an earlier name), and every spelling of it
  derives from the one declaration: the distribution `memory-core`, the import package
  `memory_core`, the `MEMORY_CORE_` environment prefix (the Lab's `MEMORY_CORE_DEMO_OPENAI_*`
  and `MEMORY_CORE_LAB_PARITY_RESULTS`, the run-loop oracle's `MEMORY_CORE_OVERFLOW_ORACLE_OUT`,
  the live embedding test's `MEMORY_CORE_LIVE_OPENAI`), the workspace state directory
  `.memory-core/` (index, setup state, automation store, migration backups), the promotion
  marker prefix `memory-core-memory-promotion:`, the runtime context markers
  (`<<<BEGIN_MEMORY_CORE_INTERNAL_CONTEXT>>>`, `<<<END_MEMORY_CORE_INTERNAL_CONTEXT>>>`, custom
  type `memory_core.runtime-context`, source `memory-core-runtime-context`) and prompts, the
  heartbeat and session transcript rows (`[memory-core heartbeat poll]`,
  `[memory-core session new]`, `[memory-core session reset]`), the default workspace layout's
  name, and the Lab's title and `X-Title` header (`memory-core Lab`), persona name and temp
  workspace directories (`memory-core-lab-workspace`, `memory-core-live-task-demo-workspace`).
  The names that carry it are `MEMORY_CORE_RUNTIME_IDENTITY`, `MEMORY_CORE_WORKSPACE_LAYOUT`,
  `MEMORY_CORE_PROMOTION_MARKER_PREFIX`, `MEMORY_CORE_RUNTIME_CONTEXT_CUSTOM_TYPE`,
  `MEMORY_CORE_WORKSPACE_STATE_FILENAME` and `MemoryCoreSessionCorpus`;
  `memory_core.project_name.STATE_DIRNAME` replaces the bootstrap lifecycle's own state
  directory constant. Existing workspaces are not migrated: a state directory or promotion
  markers written under the earlier name are not read, so entries promoted under it can be
  promoted again (README › Rename the Project).
- The package root exports 26 names instead of 171 (below): the host kit classes and
  `WorkspaceStateMigrationRequiredError` are new there, 152 names moved to their submodules
  (table below) and 7 were removed.
- `memory_core.replay_repair.repair_tool_use_result_pairing` follows upstream v2026.9.6
  (`classifyToolUseResultPairing`) instead of the earlier pin: a provider id reused on a later
  turn pairs by occurrence and keeps its result (the earlier port dropped it and left the call
  unanswered), a later real result replaces a synthetic one, a displaced result is claimed
  across frames by the one unresolved call that owns it, a second result within a frame counts
  as a duplicate (`dropped_duplicate_count` is 1 where it was 0), synthetic results carry
  `details.reason` `"missing_tool_result"`, and it takes `preserve_unframed_tool_results` and
  reports `discarded`. Also as upstream: a message that is not a mapping is dropped (the earlier
  port kept it); tool-result ids and tool names are trimmed with JavaScript's whitespace set
  instead of `str.strip`; a synthetic result keeps an empty-string tool name or
  `missing_tool_result_text` (the earlier port replaced it with `"unknown"` or the default
  text). `sanitize_tool_use_result_pairing` takes `preserve_unframed_tool_results` too.
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
- `LangGraphMemoryRecall` and `format_memory_context`
  (`memory_core.adapters.langgraph`, `memory_core.adapters`) and `Memory.langgraph_recall()`.
  The node injected search results into
  the prompt, which upstream never does, and read only role dicts, so a LangGraph state of
  LangChain messages recalled nothing. Use the host kit from a LangGraph graph instead
  (docs/integrations/langgraph.md): the model recalls through `HostKit.tools()` and
  `HostKit.dispatch()`. A host that still wants auto-recall calls `Memory.search` itself.
- `memory_core.adapters.PendingTurn`, added earlier in 0.2.0: carry a turn in flight with
  `TurnState` (`memory_core.host`), which holds the reset prompts as well.

### Package root

`from memory_core import ...` offers:

- the host kit: `HostKit`, `SessionState`, `TurnUsage`, `TurnContext`, `TurnState`,
  `TurnRecord`, `FlushRequest`, `FlushOutcome`, `NewSession`, `ResetTurn`, `HeartbeatRun`,
  `HeartbeatOutcome`, `ToolCallRepair`
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
