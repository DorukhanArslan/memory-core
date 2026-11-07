# Historical port to OpenClaw v2026.9.6

This document retains the accepted port decisions and the evidence from the
completed v2026.9.6 stage-two work. Its original estimates and task states are
historical. The current v2026.9.9 target and acceptance work are tracked in
[Full Equivalence Checklist](full-equivalence-checklist.md).

Stage 1 (branch `feat/pin-v2026.9.6`, 2026-09-27) moved the oracle target from pin `4c42815348`
(2026-07-05) to release tag `v2026.9.6` = `eb377ac59e6c9fd6c7705028034812becf00271b` (tag
commit 2026-09-22) and changed no Python behaviour. The oracle runner now calls the tag's
functions. Every oracle test that failed at the tag was recorded as an
`xfail(strict=True)` entry in the stage-two worklist, grouped by the areas below.
Stage 2 ported the Python code to the tag area by area; each area was done when
its worklist entries were removed, its tests passed against the tag, and its
`docs/parity_matrix.md` rows were re-audited. The empty helper and its bookkeeping
tests have since been retired; their original contents remain in Git history.

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

## Stage 2 progress (evidence dates are shown per row)

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
| 5 Memory tools and index identity | done (2026-10-04) | all 41 `memoryGet`, `memoryToolDefinitions`, `memorySearchToolSequence` (17 steps), `memoryIndexIdentity` (24 new cases) and the new `memoryPromptSection` (32 combinations) tests pass against the tag; 4 worklist entries removed (31 tests); new oracle op `memoryPromptSection` |
| 6 Hybrid ranking and indexing | done (2026-10-04) | 14 `memorySearch` worklist tests removed; new oracle op `markdownChunks` (13 cases incl. CJK and emoji), 10 path-matching fixtures; decision: knobs stay, defaults become the tag's (0.7/0.3, MMR and temporal decay on) |
| 7 Promotion and dreaming | done (2026-10-04) | 4 worklist entries removed (25 tests): strict policy integers, defaults on (`minScore` 0.75), recall entries with `provenance`/`userQueryHashes`/`claimHash`, unique-query gate, `signals=`/trigger/importance annotations, per-project sections, budget compaction with `maxPriorEntryLossFraction` and the "memory budget" deferral, `qmd` tag dropped; decisions: no LLM consolidation port (deterministic promotion stays), curated project scoping follows the tag |
| 8 Session corpus | done as far as faithful (2026-10-04) | `buildSessionEntry` ported over host-supplied transcript events (decision 4); new oracle op `sessionCorpusEntry` (13 cases); gaps: `redactSensitiveText` (host `redact_text` hook only), SQLite stats/archives |
| 9 Session-memory hook | done (2026-10-04) | slug, hook scenarios, zone sweep, reset-prompt source check and the new `sessionMemoryProjection` op (82 cases) pass; worklist entries and the retired op removed |
| 10 Transcript and overflow helpers | done (2026-10-04) | history-limit hysteresis, runtime context prompt (4), replay normalization, startup emoji-at-file-cap, tool-result truncation (9 + 7 aggregate) and the run-loop mid-turn scenario pass; worklist is now empty; gaps in the CHANGELOG |
| 11 Matrix and re-measure | done (2026-10-05) | parity matrix re-audited (audit note 25: 11 `match`, 23 `partial`, 2 `missing`, 5 `out of scope`); full integration suite at `v2026.9.6` (`OPENCLAW_ORACLE_NODE` node 24.21): 382 passed, 2 skipped (live providers), 0 xfail, 0 failed, run twice (45 and 50 min); `extract_upstream_constants.py --check` clean |
| 12 Remaining gaps (2026-10-06) | done | four gap ports merged: redaction (`redact.py`, 564 tests), opt-in LLM consolidation (73 scenarios), replay and history (history limit about 190 keys, `stripInboundMetadata` 345 texts, `compactionReplayOwner` 508, `replayContentCases` 108, `normalizeUsage` 409, `mediaFact` 540 messages), tool-result projection (31) with the overflow tables (3) and recovery (25); no row moved to `match`. Remaining: `resolveCompactionSource`/`preserveCompactionReplayWindow`/provider checkpoint resolvers, `stripLeadingInboundMetadata`, `extractInboundSenderLabel`, `rewriteTranscriptEntriesInSessionManager` internals, cache-TTL provider eligibility and call sites, assistant-error `isContextOverflow` path, `run_llm_consolidation` not wired into `run_dreaming_sweep`, `DREAMS.md` consolidation-history summaries and deep-phase lock/commit, SQLite session statistics and archives (decision 4) |
| 13 Remaining gaps, second round (2026-10-06) | done | three gap ports merged: compaction checkpoints and inbound metadata (`compactionCheckpoint`, `inboundMetadataHelpers`; about 24,000 cases), transcript rewrite (`transcriptRewrite`, 317), reset window (`sessionContextWindow`, 421), cache-TTL (`cacheTtlEligibility`, 3,192 combinations) and the assistant-error overflow path (`assistantOverflow`, 1,382), deep consolidation (12 promotion scenarios, 5 history cases); no row moved to `match`. Remaining: `resolveCompactionReplayPressure`, compaction capture, `resolveCompactionReplayEligibility`, `sanitizeInlineImageDataUrl`, rewrite SQLite/bounded paths and `iterateSessionContextMessages`, cache-TTL transform caller, `reset` in `transcript_tree.py`, `rejectedCandidates` reporting and origin ledger, REM/light narrative inputs, exact-secret redaction registry, SQLite session statistics and archives (decision 4) |
| 14 Remaining gaps, third round (2026-10-06) | done | two gap ports merged: compaction replay pressure, writers, eligibility and egress (`inline_image.py`, `js_url.py`, `responses_egress.py`, capture and suppression writers; additions to `test_openclaw_compaction_checkpoint_oracle.py`, about 40,000 comparisons) and the apply half of the deep phase (`rejected_candidates`, `memory.promotion.applied`, second lock, SQLite origins ledger; `test_promotion_apply_oracle.py`, 29 cases); no row moved to `match`; remaining gaps in audit note 28 of `docs/parity_matrix.md` |
| 15 Remaining gaps, rounds four and five (2026-10-06) | done | origins callers, session backfill, tombstones, revision fence and the daily-file quarantine (`test_origins_callers_oracle.py`, 19 tests; 7 scenarios added to `test_promotion_apply_oracle.py`); the Responses converter, transcript transform and tool-result text (`test_openclaw_responses_converter_oracle.py`, 4,000 generated and 200 fixed histories); replay pressure wired into the pre-prompt decision (`test_openclaw_preemptive_replay_oracle.py`, about 6,700 cases); `redact_model_visible_secrets` and `record_responses_context_usage` (additions to `test_redact_oracle.py` and `test_openclaw_compaction_checkpoint_oracle.py`); no row moved to `match`; remaining gaps in audit note 29 of `docs/parity_matrix.md` |
| 16 Remaining gaps, round six (2026-10-07) | done | three gap ports merged: the forget flow with the index revision fence, `memory.recall.*` events, the daily flush trust observer and the dreaming daily and session ingestions (`test_forget_oracle.py` 35, `test_recall_events_oracle.py` 77, `test_daily_ingestion_oracle.py` 12, `test_session_ingestion_oracle.py` 45, `test_session_artifacts_oracle.py` 2, `test_memory_write_provenance_oracle.py` 32); the attempt preflight, mid-turn handler and tool-result context guard (`test_openclaw_replay_callers_oracle.py`, about 5,000 scenarios plus estimator cases); the exact-secret registry, `logging.redactPatterns` and the redaction policies (`test_redact_policies_oracle.py` 181, `test_redact_user_regex_oracle.py`); no row moved to `match`; remaining gaps in audit note 30 of `docs/parity_matrix.md` |
| 17 Bounded small-port closeout (2026-10-07) | done for the agreed helpers | promotion visibility/weights and tie evidence; reset-fenced navigation; session-memory trust reservation/publication; fresh daily-only light/REM eligibility. Cache-TTL installer already exists; asynchronous context-engine orchestration belongs to the host. Audit note 31 records evidence and the conditional numeric threshold xfail; complete light/REM and other named gaps remain. |

Current status (2026-10-07): 11 `match`, 24 `partial`, 1 `missing`, 5 `out of scope`,
0 `mismatch` (audit note 31 and the current parity matrix rows). The area 11
counts and all earlier round results above are historical measurements, not a fresh full-suite
claim. This closeout does not promote any matrix row to `match`.

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
source reading, not measured). "Tests" counts historical worklist tests, and "Worklist areas"
names the retired helper's `PendingPort.area` labels that each plan area owned
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
  builds `## Memory Recall` (`buildMemoryPromptSection`). An empty-string `maxResults` is
  rejected, and an unknown corpus is an error (`corpus must be one of: ...`,
  `tools.ts:82-97`) where the pin searched every source. The deadline is 30 s with
  partial-timeout guidance (d46f9ebf2b2 #147702, `memory/search-deadline.ts`,
  `memory-corpus.ts`); the 60 s cooldown stays. Index identity reports
  `index provenance classifier changed` / `provenance_version` (28630a9a650).
- Python: `memory_core/tools/{memory_get,memory_search,common,citations}.py`,
  `memory_core/memory_paths.py`, `memory_core/index/identity.py`, `memory_core/prompt_section.py`.
- Tests: 31 (`memoryGet` 26, `memoryToolDefinitions` 1, params/deadline 3, identity 1).
- Worklist areas: none left; the `memory_get contract`, `memory tool definitions`, `memory_search
  deadline` and `memory index identity` entries were removed when the area landed.
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
- Worklist areas: none left; the `memory_search ranking and indexing` entries were removed when the
  area landed (2026-10-04).
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
- Worklist areas: none left; the four area-7 entries were removed when the area landed (2026-10-04).
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
- Worklist areas: none left; the `session-memory hook` entries were removed when the area landed (2026-10-04).
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
- Worklist areas: none left; the `transcript and replay helpers` and `overflow run loop` entries were removed when the area landed (2026-10-04).
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
