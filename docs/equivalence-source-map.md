# Equivalence Source Map

This source inventory maps the existing 64 contracts and 128 acceptance points to the exact OpenClaw v2026.9.9 source and current Python entry points. It adds no requirements and grants no behavioral test credit.

OpenClaw reference: `bcfc88812a35243893585dbeca87ca41b48272ca`. The machine-readable inventory, complete anchors, module hashes, declared imports/exports and implementation observations are in [source-map.json](../equivalence/source-map.json).

`present` means a source counterpart exists. It does not mean parity is proven. `partial`, `host-owned` and `missing` identify work already inside the fixed contract.

Execution reports distinguish two authorities. Tracked TypeScript execution records loaded
source hashes under `sources`; prepared-publication cases execute the original schema and
SQLite-worker SDK facades as well as the transaction owner. The older identity/cache kernel
projections retain their explicitly narrower scope. Verified bindings are described in
[index_bindings.py](../equivalence/index_bindings.py).

Manager lifecycle cases instead execute the official compiled release authenticated by
[release-runtime.json](../equivalence/release-runtime.json). Its loaded files and worker traces
are recorded separately as `releaseSources` and `releaseTraces`; package files are not reported
as tracked Git source. The release's matching version/build-commit attestation is publisher
evidence, not an independently reproduced build (`sourceBuildReproduced: false`). Neither
execution mode changes the fixed 64 contracts or 128 acceptance points. Behavioral coverage
and comparison normalizations remain in the [checklist](full-equivalence-checklist.md).

The 2026-11-08 fixture-reuse batch executes the original pinned chunking and bootstrap
budget owners. Its narrowly verified reexports bypass broad SDK/facade initialization;
[reuse_bindings.py](../equivalence/reuse_bindings.py) verifies the original binding declarations
and source hashes. This provides evidence for those function boundaries, not full host
orchestration. Additional package artifacts come from the pinned source dependency metadata
and verified local cache; they do not add dependencies to the Python SDK. Retained legacy
fixture inputs are reused without importing their expected outputs or treating their older
oracle results as v2026.9.9 evidence. The fixed contract remains 64 requirements, 128 acceptance
points and 103 mapped upstream modules. Current comparison results are in the checklist.


The later 2026-11-08 flush/session completion executes the broad original source owners
using static workspace aliases from tracked `tsconfig.json` and checked package exports.
Execution reports record the configuration hash and loaded source hashes. Source setup now
authenticates 90 packages and 8,762 installed files against the pinned Git lockfile SRI;
the exact committed `@openclaw/proxyline` 0.3.12 patch is verified against Git, its lockfile
patch hash and SHA-256 and recorded separately from archive integrity. No lifecycle scripts
run and reference source is unchanged. The older narrow reexport projections retain their
original scope.

Focused comparisons match all 111 flush and 79 session fixtures. The 73 complete JSONL
projections cover session filtering outcomes; six reset-only helpers receive no acceptance
credit. Live SQLite branch selection, integrated reset propagation, archive codecs and corpus
admission remain unverified. Flush plan/target and trigger acceptance remain open despite
matching the bounded fixtures. Current verified coverage is 22/128 (17.2%), with 106 points
remaining; this inventory itself grants none of that behavioral credit. Classifications
remain 11 present, 49 partial, one missing and three host-owned. Historical import-blocked
captures are superseded by the focused reports listed in the checklist.

| Contract | OpenClaw entry | Python entry | Python surface |
| --- | --- | --- | --- |
| `storage.discovery` | [listMemoryFiles](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/packages/memory-host-sdk/src/host/internal.ts#L266) | [list_memory_files](../memory_core/workspace.py#L60) | partial |
| `storage.path-safety` | [readMemoryFile](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/packages/memory-host-sdk/src/host/read-file.ts#L34) | [MemoryWorkspace.resolve_memory_read_path](../memory_core/workspace.py#L377) | partial |
| `storage.atomic-writes` | [commitMemoryContent](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/short-term-promotion-memory-write.ts#L139) | [MemoryCurator._write_target](../memory_core/curation.py#L1153) | partial |
| `storage.workspace-isolation` | [resolveMemoryHostAgentWorkspaceDir](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/packages/memory-host-sdk/src/host/config-utils.ts#L164) | [SubjectMemory.open](../memory_core/live/__init__.py#L390) | partial |
| `lexical.tokenization` | [tokenize](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/tokenize.ts#L6) | [tokenize](../memory_core/index/mmr.py#L17) | present |
| `lexical.fts-query` | [buildFtsQuery](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/keyword-query.ts#L3) | [build_fts_query](../memory_core/index/fts.py#L20) | present |
| `lexical.bm25` | [bm25RankToScore](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/keyword-query.ts#L14) | [bm25_rank_to_score](../memory_core/index/fts.py#L29) | present |
| `chunking.markdown-boundaries` | [chunkMarkdown](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/packages/memory-host-sdk/src/host/markdown-chunks.ts#L80) | [chunk_markdown](../memory_core/index/chunking.py#L63) | present |
| `chunking.utf16-cjk-budget` | [estimateStringChars](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/packages/normalization-core/src/cjk-chars.ts#L79) | [estimate_string_chars](../memory_core/index/cjk_chars.py#L73) | present |
| `chunking.entry-provenance` | [prepareMemoryIndexChunks](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/manager-index-preparation.ts#L42) | [MemoryChunk](../memory_core/index/chunking.py#L30) | partial |
| `indexing.identity` | [resolveMemoryIndexIdentityState](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/manager-reindex-state.ts#L222) | [resolve_memory_index_identity_state](../memory_core/index/identity.py#L269) | partial |
| `indexing.incremental-sync` | [MemoryManagerSyncBase.executeSourceSync](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/manager-sync-base.ts#L294) | [SQLiteMemoryStore.reindex](../memory_core/index/sqlite_store.py#L461) | partial |
| `indexing.transaction-publication` | [publishMemoryDatabaseTables](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/manager-db-kernel.ts#L108) | [SQLiteMemoryStore.reindex](../memory_core/index/sqlite_store.py#L461) | present |
| `indexing.embedding-cache` | [loadMemoryEmbeddingCache](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/manager-embedding-cache.ts#L40) | [load_memory_embedding_cache](../memory_core/index/embedding_cache.py#L86) | partial |
| `indexing.query-sync` | [MemorySearchOrchestration.searchCandidates](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/manager-search-orchestration.ts#L109) | [SQLiteMemoryStore.search](../memory_core/index/sqlite_store.py#L751) | partial |
| `retrieval.vector-scoring` | [searchVector](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/manager-search-vector.ts#L24) | [cosine_similarity](../memory_core/index/vector.py#L7) | partial |
| `retrieval.hybrid-scoring` | [mergeHybridResults](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/hybrid.ts#L58) | [merge_hybrid_results](../memory_core/index/hybrid.py#L101) | partial |
| `retrieval.exact-path-priority` | [prepareExactPathMatcher](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/manager-search.ts#L135) | [prepare_exact_path_matcher](../memory_core/index/keyword_search.py#L102) | present |
| `retrieval.mmr` | [applyMMRToHybridResults](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/mmr.ts#L32) | [apply_mmr_to_hybrid_results](../memory_core/index/mmr.py#L130) | present |
| `retrieval.temporal-decay` | [applyTemporalDecayToHybridResults](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/temporal-decay.ts#L112) | [apply_temporal_decay_to_hybrid_results](../memory_core/index/temporal_decay.py#L109) | partial |
| `retrieval.importance-project` | [applyImportanceMultiplier](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/importance.ts#L9) | — | missing |
| `tools.search-contract` | [createMemorySearchTool](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/tools.ts#L226) | [memory_search_tool_definition](../memory_core/tools/memory_search.py#L148) | partial |
| `tools.get-contract` | [createMemoryGetTool](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/tools.ts#L569) | [memory_get_tool_definition](../memory_core/tools/memory_get.py#L85) | partial |
| `tools.deadline-cooldown` | [runMemorySearchWithDeadline](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/search-deadline.ts#L28) | [_DeadlineWorker](../memory_core/tools/memory_search.py#L415) | partial |
| `tools.unavailable-partial` | [buildMemorySearchUnavailableResult](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/tools.shared.ts#L93) | [build_memory_search_unavailable_result](../memory_core/tools/memory_search.py#L170) | partial |
| `sessions.corpus-admission` | [listSessionTranscriptCorpusEntriesForAgent](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/packages/memory-host-sdk/src/host/session-transcript-corpus.ts#L560) | [MemoryCoreSessionCorpus](../memory_core/session_corpus.py#L43) | partial |
| `sessions.transcript-filtering` | [buildSessionEntryInProcess](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/packages/memory-host-sdk/src/host/session-files.ts#L667) | [build_session_entry](../memory_core/session_entry.py#L649) | partial |
| `sessions.visibility-lineage` | [filterMemorySearchHitsBySessionVisibility](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/session-search-visibility.ts#L164) | [MemoryCoreSessionCorpus](../memory_core/session_corpus.py#L43) | partial |
| `sessions.reset-hook` | [saveSessionMemoryNow](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/hooks/bundled/session-memory/handler.ts#L126) | [save_session_memory](../memory_core/session_memory.py#L1089) | partial |
| `sessions.durable-context` | [appendTranscriptMessage](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/config/sessions/session-accessor.sqlite-transcript-write.ts#L427) | [SessionState](../memory_core/host/session.py#L45) | host-owned |
| `prompt.bootstrap-discovery` | [ensureAgentWorkspace](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/agents/workspace.ts#L715) | [initialize_agent_workspace](../memory_core/bootstrap/lifecycle.py#L420) | partial |
| `prompt.bootstrap-budget` | [buildBootstrapContextFiles](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/agents/embedded-agent-helpers/bootstrap.ts#L401) | [build_bootstrap_context_files](../memory_core/bootstrap/budget.py#L393) | present |
| `prompt.runtime-context` | [buildMemoryPromptSection](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory-tool-contract.ts#L131) | [build_prompt_section](../memory_core/prompt_section.py#L15) | partial |
| `prompt.history-repair` | [limitHistoryTurns](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/agents/embedded-agent-runner/history.ts#L37) | [limit_history_turns](../memory_core/history.py#L19) | partial |
| `flush.plan-target` | [buildMemoryFlushPlan](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/flush-plan.ts#L63) | [build_memory_flush_plan_from_config](../memory_core/memory_flush.py#L272) | partial |
| `flush.trigger-usage` | [shouldRunMemoryFlush](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/auto-reply/reply/memory-flush.ts#L122) | [resolve_fresh_session_total_tokens](../memory_core/memory_flush.py#L341) | partial |
| `flush.execute-finalize` | [runMemoryFlushIfNeeded](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/auto-reply/reply/agent-runner-memory.ts#L1117) | [FlushRequest](../memory_core/host/flush.py#L85) | partial |
| `compaction.memory-budget` | [compactMemoryForBudget](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory-budget.ts#L180) | [compact_memory_for_budget](../memory_core/memory_budget.py#L190) | present |
| `compaction.context-assembly` | [assembleHarnessContextEngine](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/agents/harness/context-engine-lifecycle.ts#L133) | [assemble_context_engine_messages](../memory_core/context_engine_lifecycle.py#L26) | partial |
| `compaction.provider-overflow` | [prepareEmbeddedAttemptPromptPreflight](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/agents/embedded-agent-runner/run/attempt-prompt-preflight.ts#L136) | [prepare_attempt_prompt_preflight](../memory_core/attempt_preflight.py#L269) | partial |
| `promotion.recall-signals` | [recordShortTermRecalls](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/short-term-promotion-record.ts#L137) | [record_short_term_recalls](../memory_core/consolidation/recall.py#L218) | partial |
| `promotion.ranking-gates` | [rankShortTermPromotionCandidates](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/short-term-promotion.ts#L80) | [rank_short_term_promotion_candidates](../memory_core/consolidation/promotion.py#L773) | partial |
| `promotion.apply-reconcile` | [applyShortTermPromotions](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/short-term-promotion-apply.ts#L184) | [run_short_term_promotion](../memory_core/consolidation/promotion.py#L315) | present |
| `promotion.deep-consolidation` | [consolidateMemory](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/dreaming-consolidation.ts#L396) | [consolidate_memory](../memory_core/consolidation/llm_consolidation.py#L532) | partial |
| `dreaming.light` | [runLightDreaming](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/dreaming-phases.ts#L1271) | [run_dreaming_sweep](../memory_core/consolidation/dreaming.py#L143) | partial |
| `dreaming.rem` | [runRemDreaming](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/dreaming-phases.ts#L1361) | [run_dreaming_sweep](../memory_core/consolidation/dreaming.py#L143) | partial |
| `dreaming.deep` | [runShortTermDreamingPromotion](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/dreaming.ts#L84) | [run_dreaming_sweep](../memory_core/consolidation/dreaming.py#L143) | partial |
| `dreaming.diary-provenance` | [appendNarrativeEntry](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/dreaming-dreams-file.ts#L445) | [_append_dreams_section](../memory_core/consolidation/dreaming.py#L323) | partial |
| `forget.lineage-tombstones` | [forgetMemoryEntries](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory-forget.ts#L172) | [forget_memory_entries](../memory_core/consolidation/forget.py#L679) | partial |
| `forget.index-fence` | [readMemoryDatabaseRevision](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/manager-db-kernel.ts#L36) | [IndexRevisionFence](../memory_core/consolidation/origins.py#L473) | partial |
| `trust.secret-redaction` | [registerSecretValueForRedaction](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/logging/secret-redaction-registry.ts#L41) | [register_secret_value_for_redaction](../memory_core/secret_registry.py#L110) | partial |
| `trust.configured-redaction` | [parsePattern](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/logging/redact.ts#L159) | [compile_config_regex](../memory_core/redact_user_patterns.py#L879) | partial |
| `heartbeat.scratch` | [readCronJobScratchState](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/cron/scratch-store.ts#L76) | [apply_heartbeat_scratch_write](../memory_core/heartbeat_scratch.py#L173) | partial |
| `heartbeat.turn-decisions` | [resolveHeartbeatPreflight](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/infra/heartbeat-runner-prompt.ts#L83) | [resolve_heartbeat_preflight](../memory_core/heartbeat.py#L842) | partial |
| `automation.job-state` | [computeJobNextRunAtMs](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/cron/service/jobs-scheduling.ts#L317) | [compute_job_next_run_at_ms](../memory_core/automation.py#L275) | partial |
| `concurrency.workspace-locks` | [withMemoryWorkspaceLock](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory-workspace-lock.ts#L207) | [memory_workspace_lock](../memory_core/consolidation/store.py#L194) | partial |
| `recovery.repair-diagnostics` | [auditShortTermPromotionArtifacts](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/short-term-promotion-artifacts.ts#L47) | [audit_short_term_promotion_artifacts](../memory_core/consolidation/audit.py#L79) | partial |
| `recovery.failure-publication` | [publishMemoryDatabaseTables](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/memory/manager-db-kernel.ts#L108) | [SQLiteMemoryStore.reindex](../memory_core/index/sqlite_store.py#L461) | partial |
| `engine.numeric-boundaries` | [asFiniteNumber](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/packages/normalization-core/src/number-coercion.ts#L4) | [js_to_fixed](../memory_core/consolidation/_util.py#L63) | partial |
| `engine.unicode-collation` | [sliceUtf16Safe](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/packages/normalization-core/src/utf16-slice.ts#L30) | [utf16_slice](../memory_core/bootstrap/_js.py#L96) | partial |
| `engine.datetime-regex` | [resolveCronStyleNow](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/agents/current-time.ts#L23) | [format_current_time_line](../memory_core/current_time.py#L198) | partial |
| `host.turn-barrier` | [beginForegroundSessionMaintenance](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/agents/session-maintenance/coordinator.ts#L181) | [HostKit.after_turn](../memory_core/host/kit.py#L503) | host-owned |
| `host.restart-recall` | [loadSessionStore](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/src/plugin-sdk/session-store-runtime.ts#L263) | [MemoryCoreSessionCorpus](../memory_core/session_corpus.py#L43) | host-owned |
| `host.update-isolation` | [consolidateMemory](https://github.com/openclaw/openclaw/blob/bcfc88812a35243893585dbeca87ca41b48272ca/extensions/memory-core/src/dreaming-consolidation.ts#L396) | [MemoryCurator.replace_memory_entry](../memory_core/curation.py#L939) | partial |

## Validation

```sh
python -m equivalence.source_map --reference /path/to/openclaw-v2026.9.9
```

This checks the exact clean reference commit, tracked module hashes, literal source anchors, Python locations and complete inventory coverage. It does not execute those behaviors. Actual differential cases still run through `scripts/check_equivalence.py`; the full acceptance gate remains incomplete until every required point is tested.

The module dependency inventory is a source-level index of literal specifiers, including type-only imports and declarations. Variable plugin imports and runtime callback wiring remain explicit host/integration work.
