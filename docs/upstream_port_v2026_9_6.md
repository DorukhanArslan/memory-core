# Upstream port to OpenClaw v2026.9.6 (stage 2 plan)

Stage 1 (branch `feat/pin-v2026.9.6`, 2026-09-27) moved the oracle target from pin `4c42815348`
(2026-07-05) to release tag `v2026.9.6` = `eb377ac59e6c9fd6c7705028034812becf00271b` (tag
commit 2026-09-22) and changed no Python behaviour. The oracle runner now calls the tag's
functions, and every oracle test that fails at the tag is an `xfail(strict=True)` entry in
`tests/integration/oracle_worklist.py`, grouped by the areas below. Stage 2 ports the Python
code to the tag area by area; each area is done when its worklist entries are removed, its
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

## Stage 2 progress (measured 2026-09-27)

| Area | Status | Oracle at the tag |
| --- | --- | --- |
| 1 Workspace and bootstrap map | done (`7f28a3c`, `5be794e`, `e944b1d`, `afd9965`) | 19 worklist entries removed; 27 new tests (TOOLS.md migration ops, policy, legacy-state and retired-file scenarios) |
| 2 Bootstrap budget and truncation | done (`3bbf0b9`) | 11 worklist entries removed |
| Infrastructure | done (`39ba67e`, `aa4f7d3`, `1a5e09f`) | worklist xfails fail only on value assertions; oracle defaults point at the pin checkout with a Node engines check |
| Area 1 review fixes | done (`8f66aa2`, `145ca72`, `84f780d`, `4e771af`, `a6c8b97`, `3f40ecc`, `89cb1de`, `4803d13`) | no worklist change; 13 new tests (`toolsMdMigrationFindings` 10, archive collision probes 2, legacy-gate cache deviation 1) |
| 3 Heartbeat and automation | done (`0baac86`, `0d43b0d`, `033ef14`, `258f3dd`, docs) | 4 worklist entries removed; the 3 retired heartbeat ops re-ported and their skipped tests removed; 36 new tests (`heartbeatScratchContract`, `automationJobSchedule`, `heartbeatPreflight`, `heartbeatReplyDecision`, `legacyHeartbeatTasks` 1 each, `heartbeatScratchMigration` 17, `heartbeatTaskMigration` 14); `heartbeatRunPrompt` rewritten |
| Area 3 review fixes | done (`fb0a5d9`, `a40084c`, `58b8478`, `7e089ec`, `ef257f7`, `387ed5e`, `e0f23d8`, `358662f`, `0fc9bb1`) | no worklist change; 3 new tests (`heartbeatScratchMigration` crlf, `heartbeatTaskMigration` state-float and state-negative) and 3 extended (`heartbeatScratchContract` lone-surrogate steps, the disabled-owner findings steps) |
| 4 Flush plan and runtime flush gate | done (`83cbcc3`, `99ef3c9`, `cb3d48b`) | 5 worklist entries removed; 14 new tests (`flushPlan` windows 5, `memoryFlushGate` fixtures 9) |
| Area 4 review fixes | done (`dfe7e0c`, `d518dbe`, `5a44e11`, `1c9122f`, `a10eb23`, `d727d2e`, `e68f663`) | no worklist change; 13 new tests (`flushPlan` byte sizes 7, offset zones 4, out-of-range `nowMs` 1; `memoryFlushGate` disabled plan 1); flush plan row back to `partial` |
| Merge of areas 3 and 4 | done (`e656e88` merge, `301cac9`, `299bd1f`, `2316e5f`, `39fc96c`) | 5 more worklist entries gone from the pin branch (12 labels, 81 tests); 1 new test (`current_time_line_is_one_host_format_for_flush_and_heartbeat`); `heartbeatRunPrompt` now compares the full Body with the reported host format |

Full `tests/integration` at `afd9965` plus the plan and matrix edits, `/tmp/openclaw-head` at
`eb377ac59e6`, Node 24.21.0, seven chunks with the run-loop
included: 165 passed, 90 xfailed, 5 skipped (the 4 retired ops and the live-embedding test),
0 failed, 260 collected, about 27 minutes. Stage 1 ended at 108 passed, 120 xfailed, 5 skipped
(233 collected). The worklist now holds 15 areas and 90 tests.

After the area 1 review fixes (2026-09-27, `4803d13`, same checkout and Node, twelve chunks with
the run-loop included): 178 passed, 90 xfailed, 5 skipped, 0 failed, 273 collected, about 33
minutes. The fixes: the oracle refuses an `OPENCLAW_ORACLE_NODE` that is not an absolute binary
named `node` (the scripts' `#!/usr/bin/env node` would run another Node); a leftover TOOLS.md is
reported through the ported `collectToolsMdMigrationFindings` (`WorkspaceContext` and
`LiveIdentity` `migration_findings`, the Lab prompt inspector) instead of being dropped
silently; the archive collision keeps its cause and the archive parents are created `0o700`;
lifecycle snapshots compare the stored setup state again; the per-call legacy-state gate is a
documented deviation from upstream's per-process cache; the run-loop oracle's one file in the
checkout is a documented exception whose stale copy is removed and reported.

After area 3, heartbeat and automation (2026-09-27, `4ccd966`, same checkout and Node, twelve
chunks with the run-loop included): 218 passed, 86 xfailed, 2 skipped (the retired
`sessionMemoryTranscript` op and the live-embedding test), 0 failed, 306 collected, about 33
minutes. Against the area 1 review-fix run (178 passed, 90 xfailed, 5 skipped of 273): the four
heartbeat worklist entries pass, the three retired heartbeat tests were replaced, and 36 heartbeat
and automation tests are new. The worklist now holds 14 areas and 86 tests. Offline suite at
`4ccd966`: 1105 passed, 280 skipped; ruff clean; `scripts/extract_upstream_constants.py --check`
against the tag rc 0; `/tmp/openclaw-head` clean after the runs.

After the area 3 review fixes (2026-09-27, `0fc9bb1`, same checkout and Node, twelve chunks with
the run-loop included): 221 passed, 86 xfailed, 2 skipped, 0 failed, 309 collected, about 29
minutes. The fixes: the monitor scratch stores and hashes lone surrogates like Node's UTF-8
conversion; the legacy-file finding honours `retain_source`; the task migration and
`FileAutomationStore.save_jobs` run the ported `assertCronStoreCanPersist`; `AutomationStore`
declares the store contract and `list_jobs` skips rows it cannot load; hosts and the Lab record
only the jobs whose tasks went into the turn; the Lab scratch editor saves on its draft's base
revision and a stale save is `409 revision_conflict`; a demo-only legacy HEARTBEAT.md endpoint
starts scenario S09. Offline suite at `0fc9bb1`: 1114 passed, 283 skipped; ruff clean;
`scripts/extract_upstream_constants.py --check` against the tag rc 0; `/tmp/openclaw-head`
clean after the runs.

After area 4 (2026-09-27, `cb3d48b` on `wip/pin-flush`, same checkout and Node, seven chunks,
run-loop test not run in this lane): `tests/integration` 191 passed, 84 xfailed, 5 skipped,
0 failed of 280 collected, about 29 minutes. The worklist holds 13 areas and 85 tests (84
here plus the run-loop xfail). Offline suite: 1109 passed, 254 skipped (run-loop deselected).

After the area 4 review fixes (2026-09-27, `e68f663` on `wip/pin-flush`, same checkout and Node,
six chunks, run-loop test not run in this lane): `tests/integration` 204 passed, 84 xfailed,
5 skipped, 0 failed of 293 collected, about 29 minutes; the 13 new tests pass. Offline suite:
1154 passed, 267 skipped (run-loop deselected); ruff clean; `scripts/extract_upstream_constants.py
--check` against the tag rc 0; `/tmp/openclaw-head` clean after the runs. The fixes: byte sizes
parse like `parseNonNegativeByteSize`/`parseByteSize` (−0.5 no longer disables the transcript-size
force path; `UNIT_MULTIPLIERS` is extracted), ECMA-402 offset zones such as `+03:00` resolve like
`Intl` (the flush targeted the previous day's file before), an `nowMs` beyond ±8.64e15 falls back
to the current time (`resolveMemoryCoreNowMs`), the `memoryFlushGate` op returns `{disabled: true}`
for a disabled plan instead of failing, flush errors carry the cause chain and take a host
redactor, `resolve_memory_flush_threshold`/`resolve_compaction_threshold` are top-level, and the
Lab prompt inspector shows the flush decision and the flush turn apart, with the host-supplied time
format. The flush plan row is `partial` again: it names four gaps (host time format, UTC fallback
for an invalid zone, the Python date range, `zoneinfo` versus ICU names).

After merging areas 3 and 4 (2026-09-27, `wip/pin-flush` into `feat/pin-v2026.9.6` as
`e656e88`, then `301cac9`..`39fc96c`, same checkout and Node, fourteen chunks with the run-loop
included; tests ran at `39fc96c`): `tests/integration` 254 passed, 81 xfailed (exactly the 81
worklist entries, strict), 2 skipped (the retired `sessionMemoryTranscript` op and the
live-embedding test), 0 failed, 337 collected, about 32 minutes summed. The run-loop oracle,
which the flush lane never ran, is 6 passed and 1 xfailed (its worklist entry). Against the two
lanes (221 passed, 86 xfailed, 2 skipped of 309 on the pin branch; 204 passed, 84 xfailed,
5 skipped of 293 on `wip/pin-flush` without the run-loop): the five flush worklist entries pass
on the merged branch, the flush lane's 27 new tests (14 in area 4, 13 in its review fixes) are
in, and the one new time-format oracle test passes (309 + 27 + 1 = 337). The merge settled the
time format: one host `time_format` for every current-time line (`memory_core/current_time.py`,
area 4 above). Offline suite at `39fc96c`: 1218 passed, 311 skipped; `tests/parity` 70 passed;
ruff clean; `scripts/extract_upstream_constants.py --check` against the tag rc 0 (the four
generated modules were regenerated at the merge and did not change); `/tmp/openclaw-head` clean
after the runs. Matrix after the merge: 42 rows, 24 `partial`, 11 `mismatch`, 2 `missing`,
5 `out of scope`, 0 `match`.

## Decisions needed before stage 2

1. Default workspace layout: decided by Doruk 2026-09-27. The default follows the v2026.9.6
   map plus the labelled memory-core extensions; extensions that overlap newer upstream features
   (PROACTIVE_PREFERENCES.md vs the AGENTS.md "Automations - Be Proactive" section, `user/` vs
   `users/<profile-id>/USER.md`) are kept and the overlap documented. Done in area 1:
   `OPENCLAW_COMPAT_LAYOUT` replaces `OPENCLAW_PIN_LAYOUT`.
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
`PendingPort.area` labels of `tests/integration/oracle_worklist.py` that each plan area owns
(stage 1: 17 labels, 120 tests; after areas 1 and 2: 15 labels, 90 tests; after area 3: 14
labels, 86 tests; after areas 3 and 4 merged: 12 labels, 81 tests; each label carries its plan
area as `PendingPort.plan_area`, which the xfail reason prints as "area N"); every worklist test
belongs to exactly one plan area, and the stage-1 counts below add up to 120.

### 1. Workspace and bootstrap map, TOOLS.md migration (estimate 14-24 h)

Status: done 2026-09-27 (commits `7f28a3c`, `5be794e`, `e944b1d`, `afd9965`). Both layouts follow
the tag's map (`OPENCLAW_COMPAT_LAYOUT` replaces `OPENCLAW_PIN_LAYOUT`; `MEMORY_CORE_WORKSPACE_LAYOUT`
adds the labelled extensions), TOOLS.md and HEARTBEAT.md left both, `migrate_tools_md` ports
the doctor migration, retired JSON setup state is refused (`migrate_legacy_workspace_state`
imports it), and the 19 worklist entries passed against the tag and were removed; the new ops
`toolsMdMigration` (21 upstream fixtures plus one memory-core structural probe), `toolsMdMergeDecision` and `workspaceBootstrapPolicy`, a
legacy-state scenario and a retired-files lifecycle scenario pass too. Left (known gaps, row
"Workspace bootstrap files"): attestations and `WorkspaceVanishedError`, the personal
`users/<profile-id>/USER.md` overlay, the automatic-memory provenance filter, the per-project
curated MEMORY.md filter (area 7), `bootstrap-extra-files`, oracle ops for `resolveBootstrapMode`
and `resolveAttemptBootstrapContext`, and no oracle for the legacy-state import (its upstream
target is SQLite). HEARTBEAT.md is still read by `memory_core.heartbeat` until area 3.

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
- Port (as done): `OPENCLAW_COMPAT_LAYOUT` for the tag's map, the default layout on the same map
  plus the extensions (decision 1); a `migrate_tools_md(root)` helper that ports
  `shouldMergeToolsMd` and `mergeToolsMdIntoAgentsMd` byte for byte and archives under
  `<root>/.memory-core/backups/tools-md-migration/` before removing anything; setup state stays in
  `.memory-core/workspace-state.json` (documented deviation) while upstream's retired JSON state is
  refused; the shared-session MEMORY.md filter; the new render text.
- Tests: 19 (`workspaceBootstrapFiles` 4, `workspaceLifecycle` 10, `projectContextRender` 5).
- Worklist areas: none left; the `workspace bootstrap map` entries were removed when
  the area landed (2026-09-27).
- New oracle ops: `toolsMdMigration` (`maybeMigrateToolsMd` with `shouldRepair` on a fixture
  workspace and state dir: merged AGENTS.md, archive name, removed source), `toolsMdMergeDecision`
  (`shouldMergeToolsMd`), `workspaceBootstrapPolicy` (`createWorkspaceBootstrapFilePolicy`,
  `WORKSPACE_BOOTSTRAP_FILENAMES`), and a setup-state seeding step for `workspaceBootstrapFiles`
  so completed-setup scenarios need no legacy JSON.

### 2. Bootstrap budget and truncation (estimate 6-10 h)

Status: done 2026-09-27 (commit `3bbf0b9`). The USER.md cap, `effectiveFileLimit` and the
total-limit cause rule, the new warning lines, the digest markers and framing, surrogate-safe
slices and path-only injection stats are ported, `append_bootstrap_prompt_warning` is removed,
and the numbers and keyword sets are generated from the tag (`_bootstrap_constants.py`). The 11
worklist entries passed and were removed. Left: config resolution stays host numbers
(source-backed), the ICU tie-break of the signature for non-ASCII paths is approximated, and
the personal-USER skip waits for the overlay.

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
- Worklist areas: none left; the `bootstrap budget and truncation` entries were removed
  when the area landed (2026-09-27).
- New oracle ops: none; the existing op covers it.

### 3. Heartbeat and automation (estimate 16-28 h)

Doruk wants heartbeat and automation kept, in the tag's shape; nothing here is dropped.

Status: done 2026-09-27 (commits `0baac86`, `0d43b0d`, `033ef14`, `258f3dd`). The SDK shape is
memory-core's own (the host owns the scheduler, the model call and delivery; memory-core decides what
the heartbeat turn sends, whether it is skipped and how its reply is read):
`memory_core.heartbeat_scratch` (the 256 KiB contract, the compare-and-swap write rule and a
`HeartbeatScratchStore` interface), `memory_core.automation` (`AutomationJob`, the tag's
`computeJobNextRunAtMs`/`isJobDue`, due jobs as the runner's scheduled tasks, the ok/skipped
reschedule, `FileAutomationStore` in `<root>/.memory-core/automation.json` as the default store),
`memory_core.heartbeat` (preflight, run prompt, Body time lines, `decide_heartbeat_reply` with the
`NO_REPLY` and legacy `HEARTBEAT_OK` rules, the transcript filter) and
`memory_core.heartbeat_migration` (`analyzeLegacyHeartbeatTasks` and both doctor migrations with their
findings). The texts are generated into `memory_core/_heartbeat_constants.py`. Every heartbeat op
passes at the tag; the four worklist entries were removed and the three retired ops re-ported.
The `## Heartbeats` section, HEARTBEAT.md reading, file task parsing and the layout parameters
left `memory_core.heartbeat`; `heartbeat.ackMaxChars` left the Lab settings. The session corpus
drops silent replies like `sanitizeSessionText`. The Lab heartbeat view became the scratch
editor, the automation job list on the virtual clock, the doctor migration action, the next
prompt preview and the reply decision; scenario S09 starts from a legacy HEARTBEAT.md that the
demo-only `POST /api/lab/heartbeat/legacy-file` puts in place (the Lab editor cannot write
non-layout files). Left (known gaps in the three
matrix rows): pending system events (exec-completion, cron-event and session-notice prompts),
the `heartbeat_respond` tool and its `scratch` argument, host time-format detection (the host
passes one `time_format` for every current-time line, `memory_core/current_time.py`), job
conflicts between planning and commit, `applyJobResult` beyond the ok/skipped path, the
heartbeat monitor job and its cadence migration (the host runs the monitor).
`HostKit.heartbeat_prompt` composes these helpers for a host (docs/host_kit.md, entry point 6);
the Lab's heartbeat run moves onto it in that plan's Task 9c.

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
- Port (as done): the host owns scheduling and storage (AGENTS.md › Code and scope boundaries),
  so the core gets data contracts, not a scheduler. `HeartbeatScratchState` (a revision plus
  optional content; the 256 KiB check and the compare-and-swap write rule are
  `assert_heartbeat_scratch_content` and `apply_heartbeat_scratch_write`) sits behind the
  `HeartbeatScratchStore` interface; `AutomationJob` (every schedule, `systemEvent` payload,
  declaration key, owner agent) comes with `compute_job_next_run_at_ms`, `is_job_due`,
  `due_automation_jobs`, `heartbeat_scheduled_tasks`, `record_automation_job_run` and the
  persist gate `assert_automation_jobs_can_persist`, behind the `AutomationStore` interface
  (the scratch methods plus `list_jobs` and the atomic scratch-and-jobs `save_jobs`);
  `FileAutomationStore` (`<root>/.memory-core/automation.json`) is the default for both.
  `prepare_heartbeat_turn(scratch=..., scheduled_tasks=...)` builds the tag's preflight skip and
  run prompt, and `decide_heartbeat_reply` reads the reply; the constants with `NO_REPLY` are
  generated. `migrate_heartbeat_md(root, store)` moves a legacy file into the scratch and
  `migrate_heartbeat_tasks(store)` turns its `tasks:` block into jobs, each with its doctor
  findings. There is no pin-layout mode: area 1 replaced `OPENCLAW_PIN_LAYOUT` with
  `OPENCLAW_COMPAT_LAYOUT`, and `memory_core.heartbeat` takes no layout parameter. The Lab
  heartbeat view edits the scratch, lists the automation jobs and runs both migrations.
- Tests: 4 (`heartbeatConstants`, `heartbeatPromptConfig`, `heartbeatRunPrompt`,
  `heartbeatSessionFilter`), plus re-ports of the retired `parseHeartbeatTasks`,
  `heartbeatTaskDue` and `heartbeatSystemSection` tests in the new shape.
- Worklist areas: none left; the `heartbeat monitor scratch` entries were removed when the area
  landed (2026-09-27).
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
- Worklist areas: none left; the `flush plan` and `flush gate` entries were removed when the
  area landed (2026-09-27).
- New oracle ops: none; `flushPlan` gains a `contextWindowTokens` payload field and reports
  `hostTimeFormat`, and `memoryFlushGate` fixtures switch to the tag's entry fields.
- Landed 2026-09-27 (`83cbcc3`, `99ef3c9`, `cb3d48b`): `build_memory_flush_plan(context_window_tokens=...)`
  derives reserve and soft threshold; the removed overrides are gone from the Python API (no
  host depended on them); hints and prompts come from `memory_core/_memory_flush_constants.py`
  (script-extracted); `should_run_memory_flush(entry, threshold, token_count)`,
  `resolve_compaction_threshold`, `resolve_memory_flush_threshold`,
  `resolve_fresh_session_total_tokens`; `explain_memory_flush_trigger` takes the host's plan;
  the success/failure helpers write the tag's `memoryFlush` object. Found while porting:
  edecdbd05ef also made `resolveCronStyleNow` ignore `timeFormat` and detect the host's
  12/24-hour format, so the flush prompt's time line is host-dependent at the tag; memory-core takes
  `time_format` from the host (default `"24"`, documented deviation). The Lab builds the plan for
  its window, shows the derived terms, and S11 uses a 5,333-token window (threshold 2,000; the
  pin's 26,000 gives 15,500 at the tag). Not ported: the store-load projection of the flat
  pre-tag `memoryFlush*` fields, the incognito/sandbox skips and the provider server-compaction
  minimum threshold (docs/parity_matrix.md, row Runtime flush trigger).
- Review fixes 2026-09-27 (`dfe7e0c`..`e68f663`): see the measured paragraph under Stage 2
  progress. `DEFAULT_PI_COMPACTION_RESERVE_TOKENS_FLOOR` is `DEFAULT_AGENT_COMPACTION_RESERVE_TOKENS_FLOOR`
  since `83cbcc3` (the tag's name, src/agents/agent-settings.ts); no alias was kept, so a host
  importing the old name must rename it.
- Time format, settled at the merge with area 3 (2026-09-27, `301cac9`, `299bd1f`): upstream
  builds every `Current time:` line with `resolveCronStyleNow`, which detects the host's
  12/24-hour format since edecdbd05ef. `memory_core/current_time.py` ports `current-time.ts` with
  the parts of `date-time.ts` it uses and is the one place that documents the deviation: the
  host passes one `time_format` (`"12"` or `"24"`, default `"24"`, `"auto"` refused) and
  `build_memory_flush_plan`, `prepare_heartbeat_turn`, the bare reset prompt, `Memory.record_turn`
  / `chat` (removed in 0.2.0) and the live SDK's session summary pass it through. The
  `heartbeatRunPrompt` op reports `hostTimeFormat` like `flushPlan`, its test compares the full
  Body, and `current_time_line_is_one_host_format_for_flush_and_heartbeat` compares both tag
  paths with both Python paths for one instant. The Lab passes one `LAB_TIME_FORMAT` and shows it.

### 5. memory_get, memory_search contract, deadline and index identity (estimate 16-26 h)

- Upstream: `memory_get` results carry `status` ok/not_found/error, path-gate errors use code
  `MEMORY_PATH_NOT_ALLOWED`, read failures their own codes, and `disabled` is gone
  (35e0bc22ead #125979); USER.md and DREAMS.md are memory paths (28630a9a650). The tool contract
  moved to `extensions/memory-core/src/memory-tool-contract.ts` (16bec3c7272 #126552), whose
  descriptions name MEMORY.md, USER.md and per-corpus outcomes (3fe833dfa40 #126530); it also
  builds `## Memory Recall` (`buildMemoryPromptSection`). A blank numeric param such as
  `maxResults: ""` reads as omitted (the stage-1 text said "rejected"; measured the other way
  round on 2026-09-29, see the plan below), and an unknown corpus is an error
  (`corpus must be one of: ...`, `tools.ts:80-98`) where the pin searched every source. The
  deadline is 30 s with partial-timeout guidance (d46f9ebf2b2 #147702,
  `memory/search-deadline.ts`, `memory-corpus.ts`); the 60 s cooldown stays. Index identity reports
  `index provenance classifier changed` / `provenance_version` (28630a9a650).
- Python: `memory_core/tools/{memory_get,memory_search,common,citations}.py`,
  `memory_core/memory_paths.py`, `memory_core/index/identity.py`, `memory_core/prompt_section.py`.
- Tests: 31 (`memoryGet` 26, `memoryToolDefinitions` 1, params/deadline 3, identity 1). Done so
  far (2026-09-29): the 2 param entries (A2), the 26 "memory_get contract" entries (A4) and the
  "memory tool definitions" entry (A6); both labels left the worklist. 2026-09-30: the
  "memory index identity" entry (B5) and the deadline/cooldown sequence (B7), which moved to
  area 6's label under D5(c) while its single-chunk copy passes here; no label is left.
- Worklist areas: none left; the area-5 labels were removed as their tests passed (the
  deadline/cooldown sequence moved to area 6, see there).
- Status: Parts A and B done (2026-09-30, see the Part A and Part B status paragraphs under the
  TDD tasks below); B9, the full oracle run, is open.
- New oracle ops: `memoryPromptSection` (`buildMemoryPromptSection`) for the prompt-section row;
  `memoryCorpusMetadata`, `memoryIndexSearchDiagnostic` and, with D7, `memoryCorpusSupplements`
  (the plan below).

#### Area 5 port plan (2026-09-29)

Audit on `feat/port-area-5` at `fc0f6bc`; no Python changed. Oracle checkout `/tmp/openclaw-head`
at `eb377ac59e6`, Node 24.21.0. Upstream anchors are `file:line` at the tag; `tools.ts`,
`memory-corpus.ts`, `memory-read-tool.ts`, `memory-tool-contract.ts` and
`memory-search-tool-query.ts` live in `extensions/memory-core/src/`, `read-file.ts`,
`read-file-shared.ts`, `internal.ts`, `markdown-chunks.ts` and `types.ts` in
`packages/memory-host-sdk/src/host/`.

**Measured 2026-09-29 (`fc0f6bc`).** The 31 area-5 worklist tests, run with `--runxfail`:
31 failed, 0 passed, 216 s, every failure a value assertion. Probes through the same runner ops
(a scratch script, not committed): 13 `memoryGet` calls, 4 `memorySearch` calls, and three
area-6 tests (`memory_search_pauses_on_index_model_change`,
`memory_search_param_coercion_matches_python[numeric-strings]` and `[integral-float]`) to find
where area 5 ends.

| Worklist label | Tests | Diff measured at the tag |
| --- | --- | --- |
| memory_get contract | 26 | 16 reads differ only by `status` (`"ok"`; `"not_found"` for the two missing files). 8 gate refusals (`notes.txt`, `sessions/main/*.jsonl`, the `.txt` session-corpus file, `memory/../AGENTS.md` twice, `memory.md`, `/MEMORY.md`, a leading U+001C) are `status: "error"`, `code: "MEMORY_PATH_NOT_ALLOWED"`, `path is not an allowed Markdown memory file`, where Python returns `disabled: true`, `path required`. `memory/link.md` and `memory/dir.md` keep `path must be a regular file`, with `status: "error"`, `code: "MEMORY_READ_FAILED"` |
| memory tool definitions | 1 | both descriptions (source contract, outcome guidance); `minimum: 1` on `from`/`lines`; `additionalProperties: false` on both schemas |
| memory_search params, errors and deadline | 3 | `max-results-empty-string`: the tag **accepts** a blank `maxResults` as omitted and Python raises (the stage-1 label, this area's first bullet until today and the params matrix row say the opposite); `unknown-corpus-searches-all-sources`: the tag answers `corpus must be one of: memory, wiki, all, sessions`; tool sequence: 13 of 17 steps differ (below) |
| memory index identity | 1 | 25 of 26 states are `index provenance classifier changed` (`code: "provenance_version"`, `owner: "openclaw"`, `versionOrder: "older"`) because the fixture meta has no `provenanceVersion`; `missing-meta` gains `code: "metadata_missing"`, `owner: "openclaw"` |

Tool-sequence steps (0-based): 1, 4, 13 and 15 match. Steps 2, 3, 6, 7, 8, 10, 12 and 14 differ
on the area-5 contract: per-corpus `corpora`/`warning`/`error` metadata; step 6 is a `partial`
keyword result (`timedOut`, `timeoutMs: 30000`, `memory_search timed out after 30s`) instead of
an unavailable result; step 7 is `Session transcript search is not enabled.` instead of the
step-6 cooldown; steps 8, 10 and 12 keep the other corpus instead of failing the call. Steps 5,
9, 11 and 16 differ only because the tag returns two `MEMORY.md` chunks (curated-entry chunking,
area 6). Step 0 differs only by the warning `Automatic memory index repair was requested. ...`:
the TS index is built by that first search (`manager-search-orchestration.ts:288-297`,
`manager-sync-ops.ts:85-88`), while the Python fixture reindexes before step 0.

Probe findings that no worklist test covers yet:

- A path through a symlinked directory that leaves the workspace is `status: "error"`,
  `code: "outside-workspace"`, `file is outside workspace root | Symlink escapes root (<root>):
  <link>` (fs-safe `root().resolve`, `read-file.ts:155-166`). Python answers `path required`
  (its documented stricter deviation, which the tag no longer needs).
- A file ending in `\n` has no phantom last line (`read-file-shared.ts:106-111`, 1b6ad8da8f8
  #115722): `"a\nb\n"` with `lines: 2` is `text: "a\nb"` without `truncated`/`nextFrom`; Python
  appends the continuation notice and `nextFrom: 3`.
- `USER.md` is read (Python: `path required`), `user.md` is refused, and `USER.md` is indexed and
  returned by `memory_search` (`internal.ts:275`).
- `from: ""`, `lines: "  "` and `minScore: " "` read as omitted; Python raises.
- `memory_get` with `corpus: "bogus"` is `corpus must be one of: memory, wiki, all`
  (`tools.ts:594`); Python reads memory.
- `memory_get` with `corpus: "wiki"` and no supplement is `{path, text: "", corpora:
  [{wiki, not-registered}], warning: "Wiki corpus is not registered; results do not cover that
  requested corpus."}` (no `status`); `corpus: "all"` adds `corpora: [{memory, ok}, {wiki,
  not-registered}]` to the memory result.
- The character budget counts UTF-16 units and never splits a surrogate pair (`truncateUtf16Safe`,
  c3d567db95d #102478): `ab` U+1F600 `cd` at `memoryGetMaxChars: 3` is `ab`; Python returns
  `ab` U+1F600.
- An unreadable file is `code: "EACCES"`, `EACCES: permission denied, open '<abs>'`; Python has no
  code and `[Errno 13] Permission denied: '<abs>'`.
- `memory_search` with `corpus: "all"` on a paused index is no longer a top-level paused result:
  `corpora` marks memory `unavailable`, the warning appends `Tell the user: memory search is
  paused because the current memory configuration no longer matches the index (...)`, and
  `action` is the rebuild guidance (`types.ts:313-360`).
- `corpus: "sessions"` without session search is the unavailable result `Session transcript
  search is not enabled.` (`tools.ts:255-267`).

##### Sub-items

5.1 `memory_get` read contract.
- Upstream: `tools.ts:583-628` (`createMemoryGetTool`); `memory-read-tool.ts:55-70` (direct read,
  `extractErrorCode(error) ?? "MEMORY_READ_FAILED"`, `formatErrorMessage`); `read-file.ts:35-39`
  (`MEMORY_PATH_NOT_ALLOWED`, 67f55de5553 #144669), `:85-194` (`readMemoryFile`: gate 94-154,
  fs-safe root 155-166, `not_found` 161-170 and 180-182), `:197-219` (`readAgentMemoryFile`);
  `read-file-shared.ts:15-128` (`status: "ok"` 35e0bc22ead #125979, greedy fit a7f2413c4b0
  #140634, `truncateUtf16Safe`, `resolveIntegerOption` 964c8c84c18 #122299).
- Python: `memory_core/tools/memory_get.py` (`memory_get`, `_memory_read_failure`,
  `_memory_get_text`, `_fit_lines_to_char_budget`); `memory_core/workspace.py:299-349`
  (`resolve_memory_read_path` raises errors that carry a `code`: the gate refusal, fs-safe's
  `outside-workspace` for a symlinked-parent escape; the stricter deviation goes);
  `memory_core/tools/common.py` gains `extract_error_code` (a string `code` attribute; an
  `OSError`'s errno name). Results carry `status`, never `disabled`; failures are `{path, text:
  "", status: "error", code, error}`; the budget counts UTF-16 units and cuts pair-safe; the
  trailing-newline sentinel is dropped.
- Read rules the audit above did not list (review 2026-09-29), each ported with a fixture or
  documented as a deviation:
  - the continuation notice is appended when `truncated && (text || hardTruncatedSingleLine)`
    (`read-file-shared.ts:79`), so an empty pair-safe cut still gets it;
  - `suggestReadFallback` is set only for workspace reads (`read-file.ts:192`); memory-core has no
    extra paths, so every read is one, but the rule is ported as a parameter;
  - a read that fails with `path-mismatch` (the file changed between stat and open) is
    `not_found` (`read-file.ts:72-82`);
  - transient reads retry: `EAGAIN`, `EWOULDBLOCK`, `EDEADLK` or errno -11, 3 attempts,
    25-50 ms (`read-retry.ts`);
  - the workspace resolve is fs-safe's `RootHandle.resolve` (`root-impl.js:211-214`,
    `allowFinalSymlink`, `resolveCanonical`) over `root-path.js` `traverseRootPath`: an
    intermediate symlink leaving the root is `outside-workspace` with the cause
    `Symlink escapes root (<root realpath>): <link>` (`root-path-errors.js:21`, `shortPath`
    replaces the home directory with `~`, `error-detail.js:7-13`; core reads no env, so the home
    directory is a parameter, `None` meaning no shortening, documented); a file used as a
    directory is `outside-workspace` with `Path component is not a directory: <path>` and
    `ENOTDIR` (`root-path.js:242-246`); a final symlink is kept and then refused by
    `statRegularFile` (`path must be a regular file`, `MEMORY_READ_FAILED`); `ENAMETOOLONG` is
    `invalid-path` / `relative path is too long` (`root-context.js:225-227`);
  - `formatErrorMessage` skips a cause message the text already contains
    (`packages/normalization-core/src/error-coercion.ts:152-162`); memory-core's
    `format_error_message` only skips exact repeats.
- Flips: the 26 "memory_get contract" entries.
- New tests: `memoryGet` fixtures for the probe cases (symlinked parent, file as a directory,
  final symlink escape, trailing newline, UTF-16 cap, `memory` directory, `USER.md`/`user.md`),
  the EACCES and ENAMETOOLONG cases only if D6 ports the message (else unit tests of the code).
- Constants (extract): `path is not an allowed Markdown memory file`, `MEMORY_PATH_NOT_ALLOWED`,
  `MEMORY_READ_FAILED`, `path required`, the continuation-notice texts,
  `DEFAULT_MEMORY_READ_LINES`/`DEFAULT_MEMORY_READ_MAX_CHARS`, the transient-read codes; fs-safe's
  refusal codes and messages from `node_modules/@openclaw/fs-safe/dist/root-context.js:225-229`,
  `root-path.js:244` and `root-path-errors.js:18-22` (fs-safe 0.18.1). `memory search disabled`
  (`read-file.ts:206`) has no memory-core counterpart and is not extracted.
- Host kit and Lab: `HostKit.dispatch` passes the payload through; `demo/lab_tools.py:180-187`
  (`finish_call`) keeps its rule `status == "error" or disabled`: the tag's `memory_search`
  unavailable result still carries `disabled: true` and `unavailable: true`
  (`tools.shared.ts:136-139`), so only the comment changes; the Lab tool record and the `/get`
  playground (`demo/lab_kept_api.py:87`) show `status`/`code` chips;
  `tests/demo/test_demo_app.py:870-880` and docs/host_kit.md (the table row at :781) change with
  them; the refusals paragraph at :297-301 stays correct except for the `memory_get` shape.

5.2 Memory paths (`USER.md`, `DREAMS.md`).
- Upstream: `internal.ts:157-170` (`isMemoryPath`: `MEMORY.md`, `USER.md`, `dreams.md` in any
  case, `memory/...`), `internal.ts:249-275` (`listMemoryFiles` adds `USER.md` after the root
  memory file, a regular `.md` only); 28630a9a650 #114819.
- Python: `memory_core/workspace.py:36-44` (`is_memory_path`) and `:47-91` (`list_memory_files`)
  add `USER.md`; `memory_core/client.py:104-106` reindexes after a curated `USER.md` write, since
  the file is now indexed; `memory_core/memory_paths.py` keeps only the daily-path shapes (no
  change). `DREAMS.md` is already readable in Python; its `system` provenance class
  (`memory/memory-path-provenance.ts:58-67`) belongs to area 7.
- Also measured while applying the review (2026-09-29, `listMemoryFiles` op): the tag sorts the
  whole `memory/` walk by path (`internal.ts:246`, `scan.entries.map(...).toSorted()`, UTF-16
  code-unit order), so `memory/a-b.md`, `memory/a.md`, `memory/a/b.md`; memory-core's pre-order
  walk gives `memory/a/b.md` first. The existing scenarios pass by coincidence; the sort is
  ported here with a scenario that separates the two orders. On a case-insensitive file system
  a lowercase `user.md` is listed as `USER.md` (the tag lstats the joined name); the Python port
  lstats the same name, so it agrees. Not ported here: the scan now throws
  `MemorySourceScanError` on an unreadable directory (`internal.ts:191-247`) where memory-core
  skips it; that changes the reindex contract and goes with area 6.
- Flips: none on the worklist (`path_gate[dreams.md]` flips with 5.1).
- New tests: `listMemoryFiles` scenarios with `USER.md` (regular, symlinked, a directory,
  lowercase `user.md`, alone) and the sort scenario.
- Host kit and Lab: `USER.md` lines appear in `memory_search` hits (Lab search panel, the kit's
  recall signals); docs/workspace_layout.md and the "Memory file discovery" row; the
  `client.py:96-101` docstring ("USER.md writes skip the reindex") changes with the reindex.

5.3 Tool definitions.
- Upstream: `memory-tool-contract.ts:23-45` (schemas), `:47-64` (`resolveMemorySourceContract`),
  `:83-102` (outcome guidance, the two contracts), `tools.shared.ts:62-90` (`createMemoryTool`);
  16bec3c7272 #126552, 3fe833dfa40 #126530. The search description names `indexed session
  transcripts` only when `searchSources` has `sessions` (`src/agents/memory-search.ts:97-148`,
  `src/agents/memory-search-source-policy.ts:26-47`).
- Python: `memory_search_tool_definition()`/`memory_get_tool_definition()` take the search sources
  (D1) and fill the extracted `describe` templates; both schemas gain `minimum: 1` where upstream
  has it and `additionalProperties: false`. `label` is not added: host specs stay `{name,
  description, parameters}`. The `files` part also depends on `extraPaths` (`configured extra
  paths` when non-empty, `memory-tool-contract.ts:52-57`); memory-core has none, so that input is
  fixed to "none" and documented. Until D1 is decided the kit passes memory-core's current
  search sources (memory and sessions), so no default changes.
- Flips: `memory_tool_definitions_match_python`.
- Oracle op change: `memoryToolDefinitions` takes a payload `config` (`memory.search.sources`,
  `memory.search.experimental.sessionMemory`), so both description variants are compared.
- Constants (extract): `SEARCH_CORPUS_OUTCOME_GUIDANCE`, `GET_READ_OUTCOME_GUIDANCE`, the two
  `describe` template literals (fields `search`, `files`), the source-contract pieces.
- Host kit and Lab: `HostKit.tools()` (`memory_core/host/kit.py:314`) passes the sources, and so
  do the callers in `tests/unit/test_host_kit_tools.py:273-274` and
  `tests/integration/test_memory_tools.py:66-95`; the Lab shows the offered definitions in its
  prompt inspector; docs/host_kit.md:242-243.

5.4 Prompt section.
- Upstream: `memory-tool-contract.ts:108-145` (`buildMemoryPromptSection`; the session-hit lines
  came with 67f55de5553 #144669), registered in `extensions/memory-core/index.ts:245-259`;
  `src/agents/system-prompt.ts:212` drops the section for minimal prompts.
- Python: `memory_core/prompt_section.py` rebuilt from extracted texts. The `citations_mode` check
  stays `on`/`off`: upstream only tests `=== "off"`, and memory-core has no `auto` citations mode
  (a pre-existing, documented gap).
- New oracle op `memoryPromptSection` over the tool sets {none, `memory_search`, `memory_get`,
  both} crossed with {no session tools, `sessions_search`, `sessions_history`, both} and the
  citation modes {on, off} (the review dropped `auto` and undefined: Python rejects them, and
  upstream prints the "on" line for both, so the matrix row names them as the gap);
  `tests/parity/test_prompt_section.py` keeps offline literals equal to the op's outputs; the
  "Prompt memory tool section" row can become `match`.
- Host kit and Lab: `HostKit.before_turn` (`kit.py:432`) offers no `sessions_*` tool, so its
  section says `Session hits are search snippets only; exact session history is unavailable with
  the enabled tools.` plus the line-number and outcome lines; the Lab prompt inspector and
  `/prompt-preview` (`demo/lab_kept_api.py:97-105`) accept the two session tool names for the
  preview only; the Lab tests assert only the `## Memory Recall` header
  (`tests/demo/test_demo_app.py:682, 817, 1412`), so the new lines need a Lab assertion of
  their own.

5.5 Param readers and corpus validation.
- Upstream: `src/agents/tools/common.ts:104-108` (`isBlankParamValue`), `:230-252`
  (`readPositiveIntegerParam`), `:278-312` (`readFiniteNumberParam`); b22c36f1125 #100399 and
  aaf5ab910cb #100483, both after the pin. `tools.ts:80-98` (`readCorpusParam`, 4b3ee5e7eb6
  #100140) throws a plain `Error`; the model sees the same `{"status": "error", "tool", "error"}`
  payload (`src/agents/agent-tool-definition-adapter.ts:228-237`).
- Python: `memory_core/tools/common.py:212-255` reads a blank string as omitted; a
  `read_corpus_param(raw, allowed)` raises `MemoryToolInputError` (same payload; upstream's error
  is not a `ToolInputError`, documented) with `memory, wiki, all, sessions` for search and
  `memory, wiki, all` for get. The reader trims like `readStringParam` (blank means omitted,
  `" memory "` is valid) and keeps upstream's error order: query, maxResults, minScore, corpus
  for search; path, from, lines, corpus for get. The Python-call forms `memory_get(corpus=...)`
  and `memory_search(corpus=...)` validate through the same reader, so a host cannot bypass it.
- Flips: the two param entries change tables instead of flipping in place (D5): the unknown
  corpus becomes the error case `unknown-corpus-rejected`; the blank `maxResults` leaves the error
  table for a new ranking-free test, `memory_search_blank_params_read_as_omitted`, on a fixture
  with a single daily file and no `MEMORY.md`, so area 6's curated-entry chunking cannot reach it
  (measured 2026-09-29: the tag returns the same single `memory/2026-05-26.md#1-3` hit for blank
  `maxResults`, blank `minScore`, blank `corpus` and the omitted params). No new xfail is added.
  Further ranking-free coverage: `memoryGet` raw-param fixtures with blank `from`/`lines` and an
  unknown corpus.

5.6 Unavailable results, deadline and cooldown.
- Upstream: `tools.shared.ts:92-150` (`buildMemorySearchUnavailableResult` with `agentId`,
  `deadline`, `code`: the deadline warning and action, `timedOut`/`timeoutMs`,
  `SESSION_CANONICAL_KEY_MIGRATION_*` at :17-21); `memory/search-deadline.ts:1-32` (30 s; a
  deadline error is known by identity, not by its text); `memory-corpus.ts:111-189`
  (`runMemoryCorpusDeadline`: `<operation> timed out after 30s`, pause/resume for managed
  readiness); `tools.ts:73-130` (cooldown entries hold `MemoryCorpusFailure` and the runtime
  config key).
- Python: `memory_core/tools/memory_search.py:89` (15 s) takes the extracted 30 s;
  `_run_with_deadline` (`:309`) is replaced by the deadline runner of `memory_core/tools/corpus.py`
  (built in A5 for `memory_get`, reused here), whose timeout error is a dedicated type known by
  identity; `build_memory_search_unavailable_result` gains `agent_id`, `deadline` and `code`;
  cooldown entries hold `{error, deadline, code}` plus a configuration fingerprint (the frozen
  `MemoryConfig` and the store's provider identity, for upstream's `resolveRuntimeConfigCacheKey`)
  and stay keyed by store path (the documented deviation). The tag keys the cooldown by agent
  alone (`tools.ts:269`, `readMemorySearchToolCooldown(agentId, cfg)`): the session-key fallback
  of `resolve_memory_search_tool_cooldown_key` goes, or is documented with the store-path
  deviation. Pause/resume is not ported: memory-core has no managed local embedding service.
- New tests: the `memorySearchUnavailableResult` payload gains `agentId`, `deadline` and `code`,
  with cases for a deadline with and without an agent, the canonical-key code, and quota text plus
  a deadline flag.
- Runtime identity: the deadline action and the canonical-key texts name OpenClaw commands (D4);
  `memory_core/runtime_identity.py:47-50, 102` lists the new fields and drops
  `memory_search_paused_action` when the paused result moves to the ported diagnostic (5.8).
- Lab and tests that change with it: `demo/lab_kept_api.py:43-46, 314, 386` import
  `MEMORY_SEARCH_TOOL_TIMEOUT_MS` (the deadline chip, 15 s) and
  `memory_search_tool_cooldown_remaining` (the entry becomes `{error, deadline, code}` plus the
  fingerprint); `tests/unit/test_memory_search_deadline.py:145` (15 s) and the cooldown key tests
  at `:206-309`.

5.7 Per-corpus outcomes (`memory_search` and `memory_get`).
- Upstream: `memory-corpus.ts:29-109` (attempts ok/unavailable/partial/not-registered,
  `unavailableMemoryCorpus`), `:191-221` (`composeMemoryCorpusMetadata`), `:223-317` (supplement
  settle with per-plugin failures, search merge, read); `tools.ts:232-581` (memory and wiki run
  together at 436-454, memory-only unavailable 456-466, stream merge 168-230 and 469-476, recall
  signals 477-508, metadata 509-550, catch 553-568; sessions not enabled 255-267);
  `memory-read-tool.ts:39-96` (wiki and `all` reads); `memory-search-tool-query.ts:91-99` and
  `:133-161` (source selection, keyword partials); `manager-search-orchestration.ts:422-446`
  (partials published after the keyword leg, before `embedQueryWithRetry` at :475).
- Python: a new `memory_core/tools/corpus.py` (attempts, metadata, supplement settle, the deadline
  runner and its error type) serves both tools; A5 builds all of it for `memory_get`, and B3/B6
  only reuse it. `_run_memory_search_tool` (`memory_search.py:452`) runs the memory
  and wiki attempts on two workers under their own deadlines; a memory failure records the
  cooldown for any corpus, a wiki failure never does. `_merge_corpus_results` (`:577`) becomes a
  1:1 port of `mergeMemorySearchCorpusResults` (`tools.ts:168-230`, both branches): the balanced
  branch takes items one at a time up to `ceil(max/2)` per corpus, keeps each stream's own order,
  then merges the stream heads (the Python branch re-sorts everything, `:577-602`); supplement
  results merge score-descending, then path, sliced to `max(1, maxResults ?? 10)`.
  `SQLiteMemoryStore.search` (`memory_core/index/sqlite_store.py`) runs the keyword leg first and
  reports the keyword-only memory hits through an `on_partial_results` callback before embedding
  the query; a deadline with partials is `partial` (`partial: true`, the extracted warning, no
  cooldown). `corpus=sessions` returns the not-enabled result when sessions are not searched
  (D1). `memory_get` `wiki`/`all` follow `memory-read-tool.ts`; with the supplement's own excerpt
  only if D7 ports the protocol.
- Supplement settle (`memory-corpus.ts:223-273`): supplements are sorted by `pluginId`, at most 4
  run at once, failures are labelled `pluginId: error` and joined with `; ` (a single failure is
  unlabelled), and completed results survive a failure. `supplement.search` receives `{query,
  maxResults?, agentId, agentSessionKey, sandboxed}` and no `corpus` (`:283-286`); `get` receives
  `{lookup, fromLine, lineCount, ...}`. The Python `MemoryCorpusSupplement`
  (`memory_core/supplements.py:20-25`) has no plugin id and other signatures, so D7 covers the
  whole registration. Until D7 is decided, A5 ports what does not depend on the protocol
  (attempts, metadata, deadline, the outcome rules of the wiki and `all` reads with no or one
  supplement) and documents the rest.
- `corpus=all` read outcomes (`memory-read-tool.ts:84-93`): when the memory read throws or misses,
  the result is the wiki result, else `not_found` when either corpus answered ok, else
  `{status: "error", path, text: ""}` with no `code`; fixtures cover the gate refusal and a
  missing file under `all`, with and without a supplement.
- Flips: `memory_search_deadline_and_cooldown_match_python` once area 6 lands the chunking, or
  earlier through the fixture copy of D5; the D3 harness change removes the step-0 difference.
  After B6, `memory_search_all_balances_memory_and_wiki` (area-6 label) runs with `--runxfail`:
  if the merge port makes it pass, its entry moves or goes (strict xfail).
- New tests: a pure op `memoryCorpusMetadata` (`composeMemoryCorpusMetadata` over attempt lists:
  not-registered alone and with memory, partial, deadline flags; it can only pass an already
  joined plugin-failure string through); an op `memoryCorpusSupplements` that runs the real
  `searchMemoryCorpusSupplements`/`readMemoryCorpusSupplements` over several registered
  supplements (ok, throwing, null), for the per-plugin join, once D7 gives Python plugin ids;
  `memoryGet` wiki/`all` fixtures (the op registers a supplement as `memorySearchToolSequence`
  does: found, missing, throwing).
- Host kit and Lab: `HostKit._memory_search` (`kit.py:375`) records recall only when the memory
  attempt is ok or partial and only for the memory hits in the returned list (`tools.ts:477-508`),
  not on `not result.get("unavailable")`; the Lab `/search` (`demo/lab_kept_api.py:112`) emits a
  `search.partial` event and shows `corpora`, `partial`, `timedOut` and `stale` chips
  (`demo/static/lab/inspector/memory.js`); the scenario check `searchUnavailable`
  (`demo/static/lab/scenarios/checks.js:137`) also accepts a per-corpus outage;
  docs/memory_search_tool.md.

5.8 Index identity.
- Upstream: `memory/manager-reindex-state.ts:10-30` (state type; meta with `chunkingVersion` and
  `provenanceVersion`; `MEMORY_INDEX_PROVENANCE_VERSION = 1`), `:102-123` (codes and owners),
  `:167-230` (configuration and content-scope checks, now ordered sources, scope, chunking, FTS
  tokenizer, then vector dims; `expectedModel` is undefined for a provider without a model),
  `:232-279` (`resolveMemoryIndexIdentityState`: newer versions first, then older provenance,
  then older chunking with `chunkingVersionOnly`); `markdown-chunks.ts:22`
  (`MEMORY_CHUNKING_VERSION = 5`); `types.ts:202-380` (`resolveMemoryIndexIdentityDiagnostic`,
  `formatMemoryIndexRebuildGuidance`, `resolveMemoryIndexSearchDiagnostic`,
  `resolveMemorySearchStaleness`); `memory-search-tool-query.ts:23-39` and `:207-229` (paused
  result; keyword-only on a pending chunking upgrade); 28630a9a650 #114819.
- Python: `memory_core/index/identity.py` returns `{status, reason, code, owner}` plus
  `versionOrder`/`chunkingVersionOnly` where upstream sets them, with the two version constants
  as parameters (D2); `sqlite_store.py:172-187` writes `provenanceVersion` and `chunkingVersion`,
  and `index_identity()` passes memory-core's versions; `memory_search.py` builds paused results
  through the ported diagnostic, and a chunking-only mismatch searches keyword-only with the
  staleness fields; `resolve_paused_memory_index_identity_reason` and `PAUSED_MEMORY_INDEX_*`
  (`memory_search.py:114-118, 182-201`) go. Versions compare with JavaScript semantics
  (`(v ?? 0) > N` on the stored JSON: strings, `null` and a missing key), with fixtures for each;
  the stored meta keeps the tag's key order (`nextMeta`, `manager-sync-ops.ts:639-643`).
- Flips: `memory_index_identity_matches_python`, after the fixture meta gains the tag's
  `provenanceVersion: 1` and `chunkingVersion: 5` and new cases (older and newer provenance,
  older chunking with and without a content match, newer chunking, a provider without a model).
- New oracle op `memoryIndexSearchDiagnostic` (the five `types.ts` exports:
  `resolveMemoryIndexIdentityReason` at `:239`, `resolveMemoryIndexIdentityDiagnostic`,
  `formatMemoryIndexRebuildGuidance`, `resolveMemoryIndexSearchDiagnostic`,
  `resolveMemorySearchStaleness`) with `provider`/`requestedProvider` inputs, so the keyword-only
  disclosure for provider `none` is compared; the repair-failure branch (`:318-331`, input
  `lastSyncError`) is either covered by the op with a Python `last_sync_error` input or listed as
  not ported (memory-core has no background sync). A paused-result test for `corpus=memory` and
  `corpus=all` compares only the paused payloads, because
  `memory_search_pauses_on_index_model_change` stays on the area-6 label (its built step returns
  two `MEMORY.md` chunks).
- Matrix: the identity row records the missing search-time repair (D3) as a deviation: upstream
  repairs `metadata_missing` and older OpenClaw-owned identities in place
  (`manager-search-orchestration.ts:288-297`), where memory-core returns the paused result.
- Host kit and Lab: the Lab already reindexes on a non-valid identity before a search
  (`demo/lab_kept_api.py:336`); its identity chip (`demo/static/lab/inspector/memory.js:77`)
  adds `code`/`owner`. With D2's stored versions at 0/0, an index written before the port reads
  as `valid`, so nothing is rebuilt at the next kit start.

##### TDD tasks

Each task starts with failing tests, removes its worklist entries as they pass, and is one
commit after `ruff`, the offline suite and a targeted oracle run (`-k`) of its tests.

Part A: `memory_get` contract, memory paths, tool definitions, prompt section.

- A1. Extraction: a new generated module for the memory tools (sources `memory-tool-contract.ts`,
  `read-file.ts`, `read-file-shared.ts`, `read-retry.ts`, every text of `memory-corpus.ts` and
  `memory/search-deadline.ts`, the `memory_get` texts of `tools.ts`, the fs-safe refusal texts)
  in `scripts/extract_upstream_constants.py`, with its set-equality check in
  `tests/integration/test_extracted_upstream_constants.py`; `--check` rc 0. The extractor's
  `ts_template_literal` (`:164-205`) raises on any unmapped `${expr}` and cannot take literals
  out of ternaries or nested templates, which the guidance and session lines of
  `buildMemoryPromptSection` (`memory-tool-contract.ts:119-137`) need, and later
  `deadlineAction` (`tools.shared.ts:111-113`) and the rebuild guidance and paused causes
  (`types.ts:300-360`, the ` --agent ` suffix at `:304`): A1 first adds a helper for ternary
  branch literals and nested templates at an anchor, with unit tests
  (`tests/unit/test_extract_upstream_constants.py`); B1 reuses it.
- A2. Param readers (5.5, with the old B2): blank numeric strings read as omitted;
  `read_corpus_param` for both tools, the `memory_get` and `memory_search` corpus errors, the
  error order; the param tables of D5 (the unknown corpus as the error case
  `unknown-corpus-rejected`, the blank `maxResults` in the new ranking-free
  `memory_search_blank_params_read_as_omitted`, the worklist label text corrected); the two
  area-5 param entries go. Red first: `memoryGet` raw-param fixtures (blank `from`/`lines`,
  unknown corpus) and `tests/unit/test_memory_search_params.py` blank cases.
- A3. Memory paths: `USER.md` in `is_memory_path` and `list_memory_files`, the walk sorted by
  path, the curator reindex, `listMemoryFiles` scenarios, docs/workspace_layout.md.
- A4. `memory_get` read contract (5.1): status, codes and messages, the fs-safe resolve and its
  refusals, the read-result rules (sentinel, UTF-16 budget, pair-safe cut, notice condition,
  read fallback, path-mismatch, transient retry), the substring rule of `format_error_message`;
  the 26 "memory_get contract" entries go (the misnamed
  `memory_get_disabled_error_matches_python` is renamed, a new node id, when its entry goes);
  the probe fixtures are added.
- A5. `memory_get` corpora (5.7, read half) and the shared corpus layer: `memory_core/tools/
  corpus.py` with the deadline runner (`runMemoryCorpusDeadline`, `memory_get timed out after
  30s`, `DEFAULT_MEMORY_SEARCH_TIMEOUT_MS`), the dedicated deadline error
  (`search-deadline.ts:18-32`), the attempts, `composeMemoryCorpusMetadata` and the settle step;
  the pure `memoryCorpusMetadata` op; the wiki and `all` reads, supplement registration in the
  `memoryGet` op, fixtures (the protocol-dependent part waits on D7).
- A6. Tool definitions (5.3): the op's `config` payload, definitions from the source contract,
  `HostKit.tools()`, Lab and test literals; the "memory tool definitions" entry goes.
- A7. Prompt section (5.4): the `memoryPromptSection` op and fixtures, `prompt_section.py`,
  `HostKit.before_turn`, the Lab preview; the prompt-section row.
- A8. Host kit and Lab for Part A: tool-record status, `/get` takes `corpus` and shows `status`,
  `code`, `corpora` and `warning` chips (today the per-corpus `memory_get` outcomes cannot be
  seen in the Lab; the chat tool records already carry the full payload,
  `demo/static/lab/views/chat.js:50`), docs/host_kit.md (also `:242-249, 372-377, 951-954, 1011,
  1264, 1279`), UI test literals, a browser check at several widths; matrix rows `memory_get`,
  "Memory file discovery", "Prompt memory tool section" and an audit note.

Part A status (2026-09-30, measured): done on `feat/port-area-5`, one commit per task: A1
`8603d56`, A2 `79f68ab`, A3 `2129618`, A4 `3e6e358`, A5 `89f7914`, A6 `a0f2390`, A7 `14b95d0`, A8
the host kit and Lab commit after it. Worklist entries removed: the 26 "memory_get contract"
entries (A4; `memory_get_disabled_error_matches_python` is now
`memory_get_refuses_a_non_memory_path_like_python`), `memory_tool_definitions_match_python`
(A6; now parametrized `[memory-only]`, `[memory-and-sessions]`),
`memory_search_param_errors_match_python[max-results-empty-string]` and
`memory_search_param_coercion_matches_python[unknown-corpus-searches-all-sources]` (A2); none was
added. Targeted oracle run of every Part A test (Node 24.21.0, `/tmp/openclaw-head` at
`eb377ac59e6`): 115 passed, 6 xfailed (the area-6 ranking cases), 0 failed; offline 1521 passed,
375 skipped; ruff, `scripts/rename_project.py --check`, `scripts/extract_upstream_constants.py
--check` and `tests/parity` clean. The full oracle suite was not run in this stage. Differences
from the plan: the `listMemoryFiles` sort was ported in A3 (found while applying the review);
`format_error_message` gained the substring rule in A4; the D7-dependent parts stayed out (no
found-supplement fixture, unlabelled failure join) and D6's recommendation is implemented
provisionally (Python messages, errno names as codes), both documented at the code site and in
the `memory_get` row. Browser check of the Lab at 375, 768, 1024 and 1440 px (the `memory_get`
dialog's corpus switch, status and corpus chips, warning; no horizontal overflow).

Part B: `memory_search` params, errors, deadline, per-corpus outcomes, index identity.

- B1. Extraction for Part B with A1's helper: unavailable texts (deadline, canonical key), the
  sessions-not-enabled texts, the partial warning, `MEMORY_SEARCH_TOOL_COOLDOWN_MS`, the identity
  reasons and versions, the diagnostic and rebuild-guidance templates. The timeout template,
  `DEFAULT_MEMORY_SEARCH_TIMEOUT_MS` and the metadata templates come from A1. Not extracted
  (review): the rebuild notice, which the Python side never emits under D3, unless D3 changes.
- B2. (Moved into A2.)
- B3. Unavailable result (5.6): `agent_id`/`deadline`/`code`, the op payload extension and cases;
  A5's deadline error supplies `deadline`.
- B4. Supplement search (5.7): the search half of the settle step and, once D7 is decided, the
  `memoryCorpusSupplements` op with the per-plugin failure join.
- B5. Index identity (5.8): fixture meta and new cases red, `identity.py` codes and versions (D2,
  JavaScript version comparison), the store meta, the `memoryIndexSearchDiagnostic` op and the
  diagnostic port, the paused-result test; the "memory index identity" entry goes.
- B6. `memory_search` orchestration (5.6, 5.7): concurrent attempts on A5's runner, the cooldown
  rule, key and config fingerprint, the `mergeMemorySearchCorpusResults` port, the supplement
  merge, sessions not enabled (D1), the default corpus (D8), the recall filter, the 30 s
  deadline, the harness pre-sync (D3); the callers of the `corpus="all"` default
  (`memory_core/client.py:58`, `memory_search.py:410`, `memory_core/live/__init__.py:335, 433`,
  `demo/lab_chat.py:157`) and their tests follow D8; the area-6 balance test runs with
  `--runxfail` afterwards.
- B7. Keyword partials (5.7): the store's `on_partial_results`, the partial outcome, the sequence
  copy of D5 (only if its first run matches; a still-differing copy is not added, never a new
  xfail to get green); the tool-sequence entry goes here or with area 6.
- B8. Host kit and Lab for Part B: the recall gate, `/search` events and chips, the scenario check,
  docs/memory_search_tool.md and docs/host_kit.md; matrix rows `memory_search` corpora, params,
  deadline, identity and "Recall tracking from `memory_search`" (row 33, the recall gate
  changes, `tools.ts:477-508`) re-audited with an audit note; this plan's status.
- B9. Full `tests/integration` at the tag in the foreground (reference at `64770c7`: 268 passed,
  80 xfailed, 3 skipped, 0 failed of 351), the offline suite (baseline at `fc0f6bc`: 1485 passed,
  325 skipped), ruff, `scripts/rename_project.py --check`,
  `scripts/extract_upstream_constants.py --check`, `/tmp/openclaw-head` clean; results recorded
  here.

Part B status (2026-09-30, measured): B1-B8 done on `feat/port-area-5`, one commit per task: B1
`acebe2c` (extraction: the unavailable, cooldown, sessions-not-enabled and partial texts in
`memory_core/tools/_memory_tool_constants.py`, the new generated
`memory_core/index/_index_identity_constants.py`), B3 `e5e292b` (the unavailable result's
`agent_id`/`deadline`/`code`, 12 new op cases), B4 `50abc09` (the supplement search settle), B5
`dd67ecd` (identity codes, owners and versions, the index search diagnostic and the new
`memoryIndexSearchDiagnostic` op, the paused result from it), B6 `9516fd0` (the per-corpus
orchestration under the 30 s deadline, the 1:1 merge, the configuration-bound cooldown keyed by
agent, the not-enabled sessions result, `on_recall`, the op's `preSync`; the store now breaks score
ties by path where the tag's manager does, so `breaks_score_ties_with_locale_compare` keeps
passing after the tool stopped re-sorting), B7 `00395eb` (keyword partials; the single-chunk
sequence copy), B8 the Lab and docs commit after it. Worklist entries removed:
`memory_index_identity_matches_python` (B5); `memory_search_deadline_and_cooldown_match_python`
moved to the area-6 label (B7, D5(c): on the two-line MEMORY.md only steps 5, 8, 9, 11 and 16
differ, by curated-entry chunking) while its new single-chunk copy passes, so no area-5 label is
left; none was added. `memory_search_all_balances_memory_and_wiki` was run with `--runxfail` after
B6: it still fails on area 6's chunking (the tag returns two MEMORY.md chunks), so its entry stays.
Targeted oracle run at the B7 tree (Node 24.21.0, `/tmp/openclaw-head` at `eb377ac59e6`, `-k`
memory_search, memory_index, index_search, paused, unavailable_result, memory_get,
tool_definitions, corpus, prompt_section, recall): 128 passed, 17 xfailed (areas 6 and 7), 0
failed; offline (B8) 1537 passed, 378 skipped; ruff, `scripts/rename_project.py --check`,
`scripts/extract_upstream_constants.py --check` and `tests/parity` clean; `/tmp/openclaw-head`
unmodified. The full oracle suite (B9) was not run in this stage. Browser check of the Lab at 375,
768, 1024 and 1440 px (FTS-only, no keys): the search playground's per-corpus chips (`memory · ok`,
`wiki · not-registered` under `corpus=all`), the 30 s deadline chip and the identity chip, no
horizontal overflow; the partial, stale and corpus-outage chips are checked by tests only (a
partial needs a hanging embedding provider, and the Lab reindexes a non-valid identity before
searching). Decisions implemented provisionally, each documented at the code site and in the
matrix rows, for Doruk to confirm: D1 memory-core keeps searching sessions (`search_sources`
default memory and sessions; the sequence fixture enables TS session search); D2 memory-core's
own versions 0/0; D3 no search-time repair (the op pre-syncs); D4 memory-core wording for the
deadline-with-agent, canonical-key, sessions-not-enabled, rebuild-command, version-change and
upgrade texts and the stale warning's owner (`memory_core/runtime_identity.py`); D5(c) as above;
D7 supplements keep their protocol (no plugin ids, no `memoryCorpusSupplements` op, so B4 has
only its search half); D8 the facade keeps `corpus="all"` and takes the per-corpus side effects.

Labelled estimate (2026-09-29, from this audit, not measured): Part A 9-14 h, Part B 13-20 h,
above the area's 16-26 h because of the corpus orchestration and keyword partials found here.

##### Decisions needed from Doruk

- D1. Search sources. Upstream has two lists (`src/agents/memory-search-source-policy.ts:26-47`):
  `sources`, what is indexed, which the identity meta stores (`manager-sync-ops.ts:629`), and
  `searchSources`, which sets the `memory_search` description (`, indexed session
  transcripts`) and the `corpus=sessions` not-enabled result; both default to `["memory"]`
  unless sessions are configured. memory-core always indexes and searches memory and sessions
  (`sqlite_store.py:51` `CONFIGURED_SOURCES`). The choice is per knob:
  - keep memory and sessions (a documented deviation): step 7 of the tool sequence can match
    only if the `memorySearchToolSequence` config sets `memory.search.sources: ["memory",
    "sessions"]` and `memory.search.experimental.sessionMemory: true`; the tag's step 7 is then a
    sessions search or the cooldown, not "not enabled", so the fixture expectations change;
  - adopt upstream's defaults (a default change): existing indexes read `index sources changed`
    and stay paused until reindexed, and sessions disappear from `Memory.search` and the Lab.
  Part A's tool definitions take the search sources as a parameter and the kit passes memory and
  sessions until this is decided.
- D2. Index version constants. The tag's identity compares `provenanceVersion` with 1 and
  `chunkingVersion` with 5; memory-core has neither the provenance classifier (area 7) nor the v5
  chunker (area 6). Recommended: the versions are parameters of the ported function (the oracle
  test passes the tag's values), the store writes and compares memory-core's own versions (0 and 0
  until areas 6 and 7 bump them), so an older index degrades as upstream's does when those areas
  land. Writing 1 and 5 now would claim behaviour memory-core lacks; writing nothing would make
  every index "older" at the tag's constants and pause or degrade every search.
- D3. Search-time repair. Upstream rebuilds a missing or older OpenClaw-owned identity during the
  search and warns `Automatic memory index repair was requested. ...`; memory-core reindexes only
  when the host asks. Recommended: keep host-driven reindexing, return the tag's paused
  diagnostics, and let the `memorySearchToolSequence` op pre-build the TS index with a
  `reason: "cli"` sync before step 0, as the Python fixture reindexes first.
- D4. Default-identity wording. New texts name OpenClaw commands or config: the deadline action
  (`openclaw memory status --deep`, `openclaw memory index --force`), the rebuild guidance
  (`openclaw memory status --index`), the paused causes (`this OpenClaw version changed the memory
  index format`), the newer-index reason (`upgrade OpenClaw or reindex explicitly`), the
  sessions-not-enabled action (`memory.search.experimental.sessionMemory`,
  `memory.search.sources`) and the canonical-key texts (`openclaw doctor --fix`). The compat
  identity keeps them verbatim; the default identity needs memory-core wording, proposed on the
  existing pattern (`SQLiteMemoryStore.reindex(workspace)` for rebuilds, `MemoryConfig` field
  names for config), for Doruk to approve text by text.
- D5. Worklist moves. (a) `param_errors[max-results-empty-string]` leaves the error table because
  the tag accepts it. Revised by the review: it moves to the new ranking-free
  `memory_search_blank_params_read_as_omitted` (A2), so no new strict xfail is needed; adding the
  case to the accepted table under the area-6 label as well would be a new xfail and needs
  Doruk's yes. (b) `param_coercion[unknown-corpus-searches-all-sources]` becomes the error case
  `unknown-corpus-rejected` (a new node id). (c) `memory_search_deadline_and_cooldown_match_python`
  also needs area 6's chunking (steps 5, 9, 11, 16): keep it strict and move its entry to the
  area-6 label, and add a copy of the sequence on a memory file that is one chunk at the tag,
  only if its first run shows no ranking difference (a still-differing copy is not added).
- D6. OS error messages. The tag reports Node's `code` and message (`EACCES: permission denied,
  open '<abs>'`). Recommended: port the code (the errno name) and keep Python's message as a
  documented deviation; the alternative is a libuv message table in memory-core.
- D7. Supplement protocol, the whole registration. Upstream registers each supplement under a
  `pluginId` (the settle step sorts and labels failures by it), calls `search({query,
  maxResults?, agentId, agentSessionKey, sandboxed})` without a `corpus`, and `get({lookup,
  fromLine, lineCount, agentId, agentSessionKey, sandboxed})`, returning the excerpt as is
  (already so at the pin). Python's `MemoryCorpusSupplement` has no plugin id,
  `search(query, max_results, corpus)` and `get(path, corpus)`, and `memory_get` re-slices the
  content and adds `from`/`lines`. Porting changes the public protocol
  (`memory_core/supplements.py:20-25`); keeping it is a documented deviation, and then the
  per-plugin failure join and the `memoryCorpusSupplements` op stay out.
- D8. Default corpus of the Python-call forms. `Memory.search()` (`memory_core/client.py:58`),
  `memory_search()` (`memory_search.py:410`) and the live SDK (`memory_core/live/__init__.py:335,
  433`) default to `corpus="all"`, and the Lab's auto-recall (`demo/lab_chat.py:157`) inherits
  it. At the tag `all` adds a wiki attempt, the `balanceCorpora` merge and `corpora` metadata
  (`tools.ts:469-475, 509-514`), where an omitted corpus does not. Options: default to `None`
  (upstream's "omitted"), or keep `"all"` and take the new side effects in every caller.

Not ported, to document at the code site and in the matrix: the deadline pause/resume for managed
local embedding readiness; `lastSyncError` staleness (memory-core has no background sync);
upstream's caller `AbortSignal` (no Python caller passes one); `debug`, `fallback` and `mode` in
`memory_search` results; the `auto` citations mode; the scan error of `listMemoryFiles` (area 6).

Review applied 2026-09-29 (no blockers; 9 major and 12 minor findings, all anchors and the 13
cited commits re-checked at `eb377ac59e6`): the `finish_call` rule stays (5.1); D8 added for the
`corpus="all"` default; D1 split into `sources` and `searchSources` with the test consequences of
each option; A1 adds the extractor helper; the corpus layer (deadline runner and error,
metadata, settle, the metadata op) moves from Part B into A5 and B2 into A2; D7 covers the whole
registration and a `memoryCorpusSupplements` op; B6 ports `mergeMemorySearchCorpusResults` 1:1;
the Part B Lab and test consequences are listed (5.6); the missing `memory_get` read rules are in
5.1 and A4. Minor: 5.8's rebuild sentence is corrected and the version comparison specified; the
diagnostic op gains its fifth export and inputs; the prompt-section op drops `auto`/undefined;
B8 re-audits row 33; A8 lists the other docs/host_kit.md lines; the cooldown key rule (5.6);
`read_corpus_param` trimming and order (5.5); `corpus=all` read fixtures (5.7); D3 in the
identity row (5.8); worklist hygiene (A4, D5); B1 drops texts that are never emitted; 5.3 names
the extra-paths input. Found while applying it: the `listMemoryFiles` sort (5.2), the fs-safe
resolve refusals for a file used as a directory and a final symlink (5.1), the
`formatErrorMessage` substring rule (5.1) and the single-file fixture that resolves D5(a).

### 6. Hybrid ranking and indexing (estimate 24-40 h)

- Upstream: hybrid weights fixed at 0.7/0.3 (783a5d21cfc #111382), MMR on by default
  (c37b53868d1 #121224), temporal decay on by default (28630a9a650); filename and path matching
  with exact-path tiers (e9b7a9a9127 #104449); curated MEMORY.md entries chunked per entry
  (`packages/memory-host-sdk/src/host/markdown-chunks.ts` `splitCuratedMarkdownEntries`,
  `chunkMarkdown`, `MEMORY_CHUNKING_VERSION` 5); `buildFtsQuery` and `bm25RankToScore` in
  `memory/keyword-query.ts`; config under `memory.search`.
- Python: `memory_core/index/{hybrid,fts,keywords,mmr,temporal_decay,chunking,sqlite_store}.py`,
  `memory_core/config.py`.
- Tests: 15: 14 `memorySearch` fixtures (corpus, text/vector/hybrid scores, wiki balance, 6
  param coercion cases, index-model change, session-memory files, invalid UTF-8) and, since area
  5 B7 (2026-09-30), the `memorySearchToolSequence` fixture on a two-line MEMORY.md, whose
  steps 5, 8, 9, 11 and 16 differ only by the curated-entry chunking (its single-chunk copy
  passes in area 5).
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
- Tests: 7 (six helper fixtures and the run-loop mid-turn scenario); 6 left after the
  tool-use repair re-port.
- Worklist areas: "transcript and replay helpers", "overflow run loop".
- New oracle ops: `sanitizeToolCallInputs` (2026-09-29).
- 2026-09-29, `feat/kit-langgraph-fixes` (docs/host_kit.md › LangGraph findings, F26): the
  tool-use repair (`repairToolUseResultPairing` over `classifyToolUseResultPairing`) is re-ported
  to the tag, with four new fixtures, and the input repair `sanitizeToolCallInputs` is ported
  (the general branch, nine fixtures); both pass the oracle at `64770c7` (268 passed, 80 xfailed,
  3 skipped, 0 failed of 351).

### 11. Matrix, docs and re-measure (estimate 6-10 h)

Re-audit each row as its area lands, re-earn `match` only with passing oracle ops, and run the
full suite at the tag twice.

Total labelled estimate (2026-09-27): about 152-260 engineering hours for areas 1-11.

## Retired oracle operations

| Operation | Removed upstream | Stage-2 replacement |
| --- | --- | --- |
| `parseHeartbeatTasks` | b23c7bd0f84 (#113165) | re-ported 2026-09-27 (area 3): `legacyHeartbeatTasks` (`analyzeLegacyHeartbeatTasks`, the pin's inputs included) and scheduled tasks in `heartbeatRunPrompt` / `heartbeatPreflight`; the skipped test and its `RETIRED_OPS` entry are gone |
| `heartbeatTaskDue` | b23c7bd0f84 (#113165) | re-ported 2026-09-27 (area 3): `automationJobSchedule` (`computeJobNextRunAtMs`, `isJobDue`; cron owns due-ness) and `heartbeatDurations`; the skipped test and its entry are gone |
| `heartbeatSystemSection` | 6a1dedb00c2 (#129642) | re-ported 2026-09-27 (area 3): `heartbeatRunPrompt`, `heartbeatPreflight` (the prompt lives only in the heartbeat user turn); the skipped test and its entry are gone |
| `sessionMemoryTranscript` | 2cc49503a60 (#107412), 4273ca9dbd9 (#113233) | `getRecentSessionProjectionFromEvents`, `countSessionMemoryMessages` |

## Harness notes for stage 2

- The runner is tag-only: it imports `src/plugins/embedding-providers.ts`,
  `extensions/memory-core/src/test-helpers.ts`, `src/agents/bootstrap-budget-warning.ts` and
  other files the pin lacks. Old-pin comparisons use the pre-bump tree.
- Test hooks the runner relies on (`configureMemoryCoreDreamingStateForTests`,
  `shortTermTestState`, `registerEmbeddingProvider`, `SessionManager.inMemory`, the run-loop
  shared integration harness) are upstream test surfaces and will move again; prefer
  `plugin-sdk` exports where they exist.
- The run-loop oracle is the one accepted write into the oracle checkout: it adds
  `src/agents/embedded-agent-runner/memory-core-overflow-run-loop.oracle.test.ts` for one Vitest run
  and removes it in a `finally` block; the next run removes and reports a copy a killed run left
  (docs/lab.md › Oracle checkout). Moving it outside the checkout would need a Vitest root or
  config override that the tag's project matrix (`test/vitest/*.config.ts`) does not offer.
- `memoryFlushGate` derives the threshold with the expression of `agent-runner-memory.ts:1254-1260`
  (inline upstream, not exported) around the real `resolveCompactionThreshold`; without explicit
  reserve/soft it takes both from the real `buildMemoryFlushPlan` for the window. `flushPlan`
  reports the host's detected time format (`hostTimeFormat`, `resolveUserTimeFormat(undefined)`),
  which the Python side passes as `time_format`; `heartbeatRunPrompt` reports it too
  (the same `resolveUserTimeFormat(undefined)` the Body's `resolveCronStyleNow` uses).
- A persistent runner that serves many operations per process would cut the 21-minute suite
  (estimate 4-6 h, not included above).
