# Upstream port to OpenClaw v2026.9.6 (stage 2 plan)

Stage 1 (branch `feat/pin-v2026.9.6`, 2026-09-27) moved the oracle target from pin `4c42815348`
(2026-07-05) to release tag `v2026.9.6` = `eb377ac59e6c9fd6c7705028034812becf00271b` (tag
commit 2026-09-22) and changed no Python behaviour. The oracle runner now calls the tag's
functions, and every oracle test that fails at the tag is an `xfail(strict=True)` entry in
`tests/integration/oracle_worklist.py`, grouped by the areas below. Stage 2 ports memory-core's
Python to the tag area by area; each area is done when its worklist entries are removed, its
tests pass against the tag, and its `docs/parity_matrix.md` rows are re-audited.

## Where stage 1 left the suite (measured 2026-09-27)

All runs used Node 24.21.0 against a checkout of the tag with its pnpm deps (the tag refuses
Node 25 for SQLite work), a fresh `OPENCLAW_STATE_DIR` and a short `TMPDIR`.

| Run | Result |
| --- | --- |
| Tag, runner unchanged (run-loop deselected) | 69 passed, 155 failed, 1 skipped (497 s) |
| Tag, after the embedding-registry and dreaming-state re-wire | 95 passed, 129 failed, 1 skipped (1223 s) |
| Tag, after the full re-wire, before classification | 102 passed, 119 failed, 5 skipped |
| Tag, final, three chunks (run-loop deselected) | 102 passed, 119 xfailed, 5 skipped, 0 failed (1258 s) |
| Tag, run-loop oracle (one Vitest run, 7 tests) | 6 passed, 1 xfailed (32 s) |
| Tag, final run at `d49d157`, run-loop included | 108 passed, 120 xfailed, 5 skipped, 0 failed (1263 s) |
| Old pin `4c428153`, pre-bump tree `99f33ca` (Node 25.2.1) | 224 passed, 1 failed, 1 skipped (491 s, run-loop included) |

The five skips are the four retired operations and the live-embedding test. The old-pin failure
(`session_memory_hook_matches_python[zone_sweep]`, scenario 193: Python writes `GMT+0` for
Europe/Dublin in January, the pin's TS writes `GMT`) passed on 2026-09-26 and is unexplained
(open question 5). The integration suite takes about 21 minutes at the tag, since every oracle
call starts a fresh tsx process that loads a much larger module graph (5-13 s per call).

No matrix row is `match` at the tag. The rows that were `match` at the pin are measured
mismatches (deep dreaming policy, flush plan, `memory_search` params) or `partial` (promotion
gates).

## Decisions needed before stage 2

1. Default workspace layout. Q2 and the USER.md directive "Always keep TOOLS.md and HEARTBEAT.md
   as workspace files" keep the pin-era files; the tag has neither. This plan adds the tag's map
   as a new layout (`OPENCLAW_V2026_9_6_LAYOUT`) with a TOOLS.md migration helper and a
   heartbeat monitor-scratch surface, and keeps `OPENCLAW_PIN_LAYOUT` for existing workspaces.
   Which layout `MEMORY_CORE_WORKSPACE_LAYOUT` (the default) follows is Doruk's call.
2. Search defaults. The tag fixes hybrid weights at 0.7/0.3 and turns MMR and temporal decay on
   by default with no config knob. Porting that changes memory-core defaults (0.5/0.5, both off) and
   removes configurability, which needs Doruk's go-ahead (AGENTS.md: never change defaults
   unasked). Keeping configurable weights would be a flagged extension (Q16 process).
3. Dreaming on by default and the LLM consolidation step (`dreaming-consolidation.ts`): port,
   or keep memory-core's deterministic promotion as a documented deviation (touches Q13, Q16).
4. Session storage. The tag stores sessions and transcripts in per-agent SQLite. Either memory-core
   reads host-supplied transcript events (recommended; the host owns storage) or it reads
   OpenClaw's SQLite directly (couples the package to a private schema).
5. The old-pin zone-sweep failure above: investigate, or accept as environment drift.
6. Oracle defaults: done in stage 2 area 1 (2026-09-27, decided by Doruk). The default checkout
   is `/tmp/openclaw-head` (`demo/openclaw_oracle.py` `PIN_CHECKOUT_PATH`, the producer
   commands, README, docs/lab.md), `OPENCLAW_ORACLE_NODE` names the node binary, and the client
   refuses a Node outside the checkout's `engines.node` range (docs/lab.md › Oracle checkout).

## Areas

Estimates are labelled estimates (2026-09-27, inferred from the measured failure classes and
source reading, not measured). "Tests" counts worklist tests, and "Worklist areas" names the
`PendingPort.area` labels of `tests/integration/oracle_worklist.py` (17 labels, 120 tests) that
each plan area owns; every worklist test belongs to exactly one plan area, and the counts below add
up to 120.

### 1. Workspace and bootstrap map, TOOLS.md migration (estimate 14-24 h)

- Upstream: the bootstrap set is AGENTS, SOUL, IDENTITY, USER, BOOTSTRAP, MEMORY, and load order
  equals render order (`src/agents/workspace-bootstrap-policy.ts` `WORKSPACE_BOOTSTRAP_FILENAMES`,
  78d7a8489cd #114436). TOOLS.md was retired into the `## Tools` section of AGENTS.md with a
  doctor migration (669db2968fc #113966): `src/commands/doctor-tools-md-migration.ts`
  (`maybeMigrateToolsMd`; private `mergeToolsMdIntoAgentsMd` appends customised content under
  `### Local notes (migrated from TOOLS.md)`, archives the original under
  `<state>/backups/tools-md-migration/` and removes it) and
  `doctor-tools-md-migration-content.ts` (`shouldMergeToolsMd` skips empty files and stock
  templates). HEARTBEAT.md left the bootstrap set (area 3). Setup state and attestations moved to
  the SQLite state DB; legacy JSON state is refused until doctor migrates it (#109147). Root
  MEMORY.md is dropped for subagent, cron, group and channel sessions (d06fc25a0c5 #119198);
  subagents get AGENTS.md only, cron gets AGENTS, SOUL, IDENTITY, USER. A missing USER.md is
  skipped like MEMORY.md. The Project Context wording changed (`src/agents/system-prompt.ts`,
  `src/agents/system-prompt-context-files.ts`), and so did the bootstrap-pending lines.
- Python: `memory_core/bootstrap/{layout,files,lifecycle,render,context}.py`, `memory_core/workspace.py`,
  `memory_core/live/__init__.py` (`IDENTITY_FILE_ORDER`), `demo/workspace_context.py`, the Lab
  workspace views.
- Port: add `OPENCLAW_V2026_9_6_LAYOUT`; a `migrate_tools_md(root)` helper that ports
  `shouldMergeToolsMd` and `mergeToolsMdIntoAgentsMd` byte for byte (archive into the host's
  state dir, never delete without the archive); setup state through a host-supplied store
  instead of `.memory-core/workspace-state.json` for the new layout; the shared-session MEMORY.md
  filter; the new render text.
- Tests: 19 (`workspaceBootstrapFiles` 4, `workspaceLifecycle` 10, `projectContextRender` 5).
- Worklist areas: none left; the `workspace bootstrap map` entries were removed when
  the area landed (2026-09-27).
- New oracle ops: `toolsMdMigration` (`maybeMigrateToolsMd` with `shouldRepair` on a fixture
  workspace and state dir: merged AGENTS.md, archive name, removed source), `toolsMdMergeDecision`
  (`shouldMergeToolsMd`), `workspaceBootstrapPolicy` (`createWorkspaceBootstrapFilePolicy`,
  `WORKSPACE_BOOTSTRAP_FILENAMES`), and a setup-state seeding step for `workspaceBootstrapFiles`
  so completed-setup scenarios need no legacy JSON.

### 2. Bootstrap budget and truncation (estimate 6-10 h)

- Upstream: USER.md has a fixed 4000-character cap (`USER_BOOTSTRAP_MAX_CHARS`,
  28630a9a650 #114819) reported as `effectiveFileLimit` with its own warning line
  (dae1aea7117 #136967); the AGENTS.md policy digest adds Traditional Chinese markers
  (dfc9678a516 #142915); `appendBootstrapPromptWarning` is gone and the notice goes into the
  system prompt (0b450013ea0 #130325); `buildBootstrapPromptWarning` lives in
  `src/agents/bootstrap-budget-warning.ts`.
- Python: `memory_core/bootstrap/budget.py` (keyword sets: write the new ranges as `\u` escapes and
  keep the extraction plus set-equality check), `append_bootstrap_prompt_warning` (retire or keep
  as adapter-only).
- Tests: 11 (`bootstrapContextFiles` 9, warning once-mode 1, keyword/constant source check 1).
- Worklist areas: "bootstrap budget and truncation".
- New oracle ops: none; the existing op covers it.

### 3. Heartbeat and automation (estimate 16-28 h)

Doruk wants heartbeat and automation kept, in the tag's shape; nothing here is dropped.

- Upstream: HEARTBEAT.md became a per-agent monitor scratch in the shared state DB
  (3e2b3ea4d5e #112967; runtime fallback removed in 07e3855b465 #113131): table
  `cron_job_scratch` joined to the system-owned heartbeat automation job (`declaration_key`
  `heartbeat:<agentId>`), 256 KiB cap (`src/cron/scratch-contract.ts`
  `CRON_JOB_SCRATCH_MAX_BYTES`, `assertCronJobScratchContent`), compare-and-swap revisions
  (`src/cron/scratch-store.ts` `readHeartbeatMonitorScratch`, `writeCronJobScratch`). The agent
  can rewrite it through the optional `scratch` argument of `heartbeat_respond`. Recurring
  `tasks:` entries are independent automation (cron) jobs (b23c7bd0f84 #113165; doctor parses
  the legacy syntax with `src/commands/heartbeat-task-legacy.ts` `analyzeLegacyHeartbeatTasks`
  and `doctor-heartbeat-task-migration.ts` `maybeMigrateHeartbeatTasksToCron`; HEARTBEAT.md text
  moves into scratch with `doctor-heartbeat-scratch-migration.ts`
  `maybeMigrateHeartbeatFilesToScratch`). The runner never reads a workspace file:
  `src/infra/heartbeat-runner-prompt.ts` `resolveHeartbeatPreflight` (empty scratch skips with
  `empty-heartbeat-file`, no scratch runs the generic prompt, cron/exec/wake scopes bypass it)
  and `resolveHeartbeatRunPrompt` (appends `Heartbeat monitor scratch:` and the due scheduled
  tasks). The default prompt follows the scratch, sends recurring work to the automations tool
  and ends with `NO_REPLY` (`src/auto-reply/heartbeat.ts`); legacy `HEARTBEAT_OK` is still
  stripped (`stripHeartbeatToken`, 300 chars). The `## Heartbeats` system-prompt section is gone
  (6a1dedb00c2 #129642). `resolveHeartbeatPrompt` is `resolveHeartbeatPromptCore`
  (e74be5d41db #122157); the transcript marker is `INTERNAL_WAKE_TRANSCRIPT_PROMPTS.heartbeat`.
- Python: `memory_core/heartbeat.py`, `memory_core/runtime_identity.py`, `memory_core/bootstrap/files.py`
  (heartbeat filters), `demo/lab_heartbeat.py` and the Lab heartbeat view.
- Port: the host owns scheduling and storage (AGENTS.md › Code and scope boundaries), so the core
  gets data contracts, not a scheduler: a `HeartbeatMonitorScratch` value (content, revision,
  256 KiB check, CAS update) and an `AutomationJob` description (declaration key, schedule,
  payload kind, owner agent) that hosts persist; `prepare_heartbeat_turn(scratch=...,
  scheduled_tasks=...)` builds the tag's prompt and preflight skip; the new constants with
  `NO_REPLY`; a `migrate_heartbeat_md(root)` helper that splits a legacy file into scratch text
  and task jobs the way doctor does. `OPENCLAW_PIN_LAYOUT` keeps the pin behaviour for existing
  workspaces. The Lab heartbeat view edits the scratch and lists automation jobs.
- Tests: 4 (`heartbeatConstants`, `heartbeatPromptConfig`, `heartbeatRunPrompt`,
  `heartbeatSessionFilter`), plus re-ports of the retired `parseHeartbeatTasks`,
  `heartbeatTaskDue` and `heartbeatSystemSection` tests in the new shape.
- Worklist areas: "heartbeat monitor scratch".
- New oracle ops: `heartbeatPreflight` and a rewritten `heartbeatRunPrompt` that seed the monitor
  scratch through a `CronService` heartbeat job plus `writeCronJobScratch` (as upstream's
  `seedHeartbeatScratchForTest` does) instead of writing HEARTBEAT.md, with scheduled tasks as
  input; `heartbeatScratchContract` (`CRON_JOB_SCRATCH_MAX_BYTES`,
  `assertCronJobScratchContent`); `legacyHeartbeatTasks` (`analyzeLegacyHeartbeatTasks`);
  `heartbeatScratchMigration` and `heartbeatTaskMigration` (the two doctor migrations on fixture
  workspaces).

### 4. Flush plan and runtime flush gate (estimate 6-10 h)

- Upstream: the read-only hint names MEMORY.md, DREAMS.md, SOUL.md and AGENTS.md (669db2968fc
  dropped TOOLS.md); `reserveTokensFloor` and the prompt/systemPrompt overrides are no longer
  config (783a5d21cfc #111382, edecdbd05ef); reserve and soft threshold derive from the context
  window (`buildMemoryFlushPlan({contextWindowTokens})`, `resolveEffectiveCompactionReserveTokens`,
  6b6f1969c11 #130072). `shouldRunMemoryFlush` takes a precomputed `threshold`
  (084d51d0c7b #152268), counts only fresh session totals and reads
  `entry.memoryFlush.compactionCount` (8ee1d046d33 #115299). The target stays
  `memory/YYYY-MM-DD.md`.
- Python: `memory_core/memory_flush.py` (verbatim hints by extraction), `demo/lab_flush.py`.
- Tests: 5 (`flushPlan` 2, `memoryFlushGate` 3).
- Worklist areas: "flush plan", "flush gate".
- New oracle ops: none; `flushPlan` gains a `contextWindowTokens` payload field, and
  `memoryFlushGate` fixtures switch to the tag's entry fields.

### 5. memory_get, memory_search contract, deadline and index identity (estimate 16-26 h)

- Upstream: `memory_get` results carry `status` ok/not_found/error, path-gate errors use code
  `MEMORY_PATH_NOT_ALLOWED`, read failures their own codes, and `disabled` is gone
  (35e0bc22ead #125979); USER.md and DREAMS.md are memory paths (28630a9a650). The tool contract
  moved to `extensions/memory-core/src/memory-tool-contract.ts` (16bec3c7272 #126552), whose
  descriptions name MEMORY.md, USER.md and per-corpus outcomes (3fe833dfa40 #126530); it also
  builds `## Memory Recall` (`buildMemoryPromptSection`). An empty-string `maxResults` is
  rejected, and an unknown corpus is an error (`corpus must be one of: ...`,
  `tools.ts:82-97`) where the pin searched every source. The deadline is 30 s with
  partial-timeout guidance (d46f9ebf2b2 #147702, `memory/search-deadline.ts`,
  `memory-corpus.ts`); the 60 s cooldown stays. Index identity reports
  `index provenance classifier changed` / `provenance_version` (28630a9a650).
- Python: `memory_core/tools/{memory_get,memory_search,common,citations}.py`,
  `memory_core/memory_paths.py`, `memory_core/index/identity.py`, `memory_core/prompt_section.py`.
- Tests: 31 (`memoryGet` 26, `memoryToolDefinitions` 1, params/deadline 3, identity 1).
- Worklist areas: "memory_get contract", "memory tool definitions", "memory_search params,
  errors and deadline", "memory index identity".
- New oracle ops: `memoryPromptSection` (`buildMemoryPromptSection`) for the prompt-section row.

### 6. Hybrid ranking and indexing (estimate 24-40 h)

- Upstream: hybrid weights fixed at 0.7/0.3 (783a5d21cfc #111382), MMR on by default
  (c37b53868d1 #121224), temporal decay on by default (28630a9a650); filename and path matching
  with exact-path tiers (e9b7a9a9127 #104449); curated MEMORY.md entries chunked per entry
  (`packages/memory-host-sdk/src/host/markdown-chunks.ts` `splitCuratedMarkdownEntries`,
  `chunkMarkdown`, `MEMORY_CHUNKING_VERSION` 5); `buildFtsQuery` and `bm25RankToScore` in
  `memory/keyword-query.ts`; config under `memory.search`.
- Python: `memory_core/index/{hybrid,fts,keywords,mmr,temporal_decay,chunking,sqlite_store}.py`,
  `memory_core/config.py`.
- Tests: 14 `memorySearch` fixtures (corpus, text/vector/hybrid scores, wiki balance, 6 param
  coercion cases, index-model change, session-memory files, invalid UTF-8).
- Worklist areas: "memory_search ranking and indexing".
- New oracle ops: `hybridMerge` (`mergeHybridResults`, `selectHybridSearchResults`), `mmrRerank`
  (`applyMMRToHybridResults`), `temporalDecay` (`applyTemporalDecayToHybridResults`),
  `markdownChunks` (`chunkMarkdown`, `splitCuratedMarkdownEntries`), `ftsQuery`
  (`buildFtsQuery`, `bm25RankToScore`). These isolate ranking from the full tool, so the
  `memorySearch` fixtures can be re-expressed under the fixed weights.

### 7. Promotion and dreaming (estimate 30-50 h)

- Upstream: deep dreaming is on by default with `minScore` 0.75 (b2cc5f50420 #115715,
  28630a9a650 #114819), and its integer fields (`limit`, `minRecallCount`, `minUniqueQueries`,
  `recencyHalfLifeDays`) are parsed with `parseStrictNonNegativeInteger` instead of `Number()`
  (`src/memory-host-sdk/dreaming.ts:480-490`; 6 of the 7 malformed-value fixtures differ there);
  recall entries carry `provenance`, `userQueryHashes` and `claimHash`, tainted captures are quarantined (20668eed037 #115818), and the unique-query gate counts
  provenance-qualified query hashes (fe6556b643e #119624); promotion lines carry `signals=`,
  `trigger` and `importance` metadata; `short-term-promotion.ts` was split into
  `short-term-promotion-{record,apply,store,scoring,...}.ts` (a7d2f0bd685 #113223); curated
  entries are scoped per project (d41a56fca1f #115438); budget compaction bounds prior-entry loss
  (`memory-budget.ts`); the `qmd` concept tag went with the QMD backend (8b0735e89f2 #120936);
  deep dreaming adds an LLM consolidation step (`dreaming-consolidation.ts`).
- Python: `memory_core/consolidation/*`, `memory_core/memory_budget.py`, `memory_core/curation.py`.
- Tests: 25 (deep policy 8, concept tags 1, recall and promotion 15, budget 1).
- Worklist areas: "deep dreaming policy", "concept vocabulary", "short-term recall and
  promotion", "MEMORY.md budget compaction".
- New oracle ops: `consolidateMemory` through `test-helpers.ts` `consolidateMemoryForTests` with a
  stubbed model (only if decision 3 ports it), `recordGroundedShortTermCandidates`.

### 8. Session corpus (estimate 16-30 h)

- Upstream: sessions and transcripts live in per-agent SQLite (0a8e3604ba2 #98236; file-era
  runtime removed in 4273ca9dbd9 #113233); `buildSessionEntry` reads SQLite snapshots and
  redacts through `redactSensitiveText` (mode `tools`); the heartbeat transcript filter changed
  (`heartbeat-filter.ts`, 10 commits after the pin). The reset-recall cutoffs seen on main
  (f34c36899cf) are not in the tag.
- Python: `memory_core/session_corpus.py`, `memory_core/transcript_tree.py`.
- Tests: 0. `heartbeatSessionFilter` touches the session corpus but is counted once, under area 3
  (worklist area "heartbeat monitor scratch"); the TS-literal sessions fixture already passes
  with its transcript seeded into SQLite by the runner.
- Worklist areas: none of its own.
- New oracle ops: `sessionCorpusEntry` (`buildSessionEntry` over SQLite-seeded transcripts),
  `redactSensitiveText` (with the redaction hooks, R13).

### 9. Session-memory hook (estimate 8-14 h)

- Upstream: the hook requires `context.agentId`, reads the previous transcript from the SQLite
  session store (`captureSessionMemoryTranscript`), projects events with
  `getRecentSessionProjectionFromEvents` / `countSessionMemoryMessages`, writes through the
  memory provenance observer, and the slug run is admitted for the agent; the bare reset prompts
  changed (`session-reset-prompt.ts`).
- Python: `memory_core/session_memory.py`, `memory_core/bootstrap/startup.py` (reset prompts).
- Tests: 4 (slug 1, hook 2, reset-prompt source check 1), plus the re-port of the retired
  `sessionMemoryTranscript` test.
- Worklist areas: "session-memory hook".
- New oracle ops: `sessionMemoryProjection` (the two exports over event lists); the
  `sessionMemoryHook` op seeds transcripts into SQLite instead of JSONL files.

### 10. Transcript and overflow helpers (estimate 10-18 h)

- Upstream: history-limit hysteresis eviction (d5dee714c4f #115281); changes in
  `session-transcript-repair.ts` (17 commits after the pin), `runtime-context-prompt.ts` (5),
  `replay-history.ts` (23), `tool-result-truncation.ts` (36; session truncation now goes through
  `truncateOversizedToolResultsInSessionManager` on a `SessionManager`) and `startup-context.ts`
  (2); the run loop moved from `run.ts` into `run/*` and the mid-turn precheck retry no longer
  sends the continuation prompt.
- Python: `memory_core/{history,replay_history,replay_repair,runtime_context_prompt,
  context_engine_lifecycle,preemptive_compaction,overflow_recovery}.py`,
  `memory_core/bootstrap/startup.py`.
- Tests: 7 (six helper fixtures and the run-loop mid-turn scenario).
- Worklist areas: "transcript and replay helpers", "overflow run loop".
- New oracle ops: none.

### 11. Matrix, docs and re-measure (estimate 6-10 h)

Re-audit each row as its area lands, re-earn `match` only with passing oracle ops, and run the
full suite at the tag twice.

Total labelled estimate (2026-09-27): about 152-260 engineering hours for areas 1-11.

## Retired oracle operations

| Operation | Removed upstream | Stage-2 replacement |
| --- | --- | --- |
| `parseHeartbeatTasks` | b23c7bd0f84 (#113165) | `analyzeLegacyHeartbeatTasks` (doctor) and cron-owned scheduled tasks in `resolveHeartbeatRunPrompt` |
| `heartbeatTaskDue` | b23c7bd0f84 (#113165) | none for `isTaskDue` (cron owns due-ness); durations and intervals moved to `heartbeatDurations` |
| `heartbeatSystemSection` | 6a1dedb00c2 (#129642) | `resolveHeartbeatRunPrompt` (the prompt lives only in the heartbeat user turn) |
| `sessionMemoryTranscript` | 2cc49503a60 (#107412), 4273ca9dbd9 (#113233) | `getRecentSessionProjectionFromEvents`, `countSessionMemoryMessages` |

## Harness notes for stage 2

- The runner is tag-only: it imports `src/plugins/embedding-providers.ts`,
  `extensions/memory-core/src/test-helpers.ts`, `src/agents/bootstrap-budget-warning.ts` and
  other files the pin lacks. Old-pin comparisons use the pre-bump tree.
- Test hooks the runner relies on (`configureMemoryCoreDreamingStateForTests`,
  `shortTermTestState`, `registerEmbeddingProvider`, `SessionManager.inMemory`, the run-loop
  shared integration harness) are upstream test surfaces and will move again; prefer
  `plugin-sdk` exports where they exist.
- `memoryFlushGate` derives the threshold with the expression of `agent-runner-memory.ts:1254-1260`
  (inline upstream, not exported) around the real `resolveCompactionThreshold`.
- A persistent runner that serves many operations per process would cut the 21-minute suite
  (estimate 4-6 h, not included above).
