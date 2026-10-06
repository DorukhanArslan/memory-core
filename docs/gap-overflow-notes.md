# Gap notes: tool-result projection and overflow recovery (v2026.9.6)

Closes two known gaps of `docs/upstream_port_v2026_9_6.md` area 10 against the oracle checkout
(`/tmp/openclaw-head`, v2026.9.6). Nothing here edits the plan, the matrix or the changelog; fold
these notes in when the area is re-measured.

## (a) Prompt projection of tool results

New module `memory_core/tool_result_projection.py`, around the unchanged budget and plan code in
`memory_core/_tool_result_budget.py` and `memory_core/preemptive_compaction.py`.

Ported from `tool-result-truncation.ts` and `session-prompt-state.ts`:

- `ToolResultPromptProjectionState` (replacements, frozen keys, ambiguous base keys, source hashes,
  restored cache-TTL marks, last written snapshot hash) with create, clone, record, serialize,
  hash and persist (`persistToolResultProjections`).
- Key resolution (`getToolResultProjectionKeys`: base keys, ambiguity, id/text-hash fallback keys,
  duplicate migration), `projectToolResultBranch` (`frozenOnly`, `recordSources`,
  `aggregateEligible`), `materializeRestoredCacheTtl`, the merge of projected content.
- Cache-TTL pruning: `resolveCacheTtlPruningSettings` (duration, allow/deny globs, hard clear),
  `pruneExpiredCacheTtlToolResults` (soft trim, hard clear, thresholds, thinking-aware estimate),
  `restoreCacheTtlToolResultProjections` (zod schema as a manual validator),
  `reconcileToolResultPromptProjectionState`.
- `truncateOversizedToolResultsInMessages` with a projection state.
- Session variant: `truncate_oversized_tool_results_in_session_file(..., projection_state=...)` now
  follows `buildRecoveryToolResultReplacementPlan` (frozen-only projection, replacement only where
  the final message differs from the stored one by JSON equality), reconciles the state after the
  rewrite, restricts the plan to the context window of the last compaction
  (`iterateSessionContextEntries`) and remaps `firstKeptEntryId` of re-appended compactions like
  `rewriteTranscriptEntriesInSessionManager`. The Python session-file variant stays.
- `ProjectedMessage` / `spread_message` in `preemptive_compaction.py`: the projection key travels
  through message copies the way upstream's symbol property travels through object spread.

Oracle coverage (`scripts/openclaw_oracle_runner.ts` op `toolResultProjection`, tests in
`tests/integration/test_openclaw_tool_result_projection_oracle.py`, 31 cases): scripted sequences of
the exported entry points over one shared state, comparing every step's result and a canonical dump
of the state. `projectToolResultBranch` is private upstream and is reached only through them.
`truncateOversizedToolResultsInSessionManager` runs on a real `SessionManager` (in memory), with
and without a projection state and with a compaction entry.

### Deviations

- The projection key is an attribute (`projection_key`), not a symbol. It is dropped before a
  rewritten message is written to the session file; upstream's in-memory `SessionManager` keeps the
  symbol on the object it rewrote, which only matters for ambiguous tool-call ids inside one
  process.
- `session_context_entries` handles compaction boundaries; a `reset` boundary keeps no retained
  entries (upstream asks `selectResetKeptEntries`, not ported).
- JSON number formatting follows Python (`1.0` versus `1`) where a tool-call argument is
  re-serialized for the cache-TTL size estimate.

### Remaining gaps

- `rewriteTranscriptEntriesInSessionManager` itself (match detection by bytes, `stripStalePrefixReplay`,
  transcript-update events) and the log/dedupe side of `logToolResultSessionTruncation`.
- Cache-TTL eligibility and markers: `isCacheTtlEligibleProvider`, `readLastCacheTtlTimestamp`,
  the `getEmbeddedSessionPromptState` global LRU and the call sites that pick `now`,
  `lastCacheTouchAt` and `pruneNewRounds` (host-owned in memory-core).

## (b) Overflow recovery

- `memory_core/_overflow_tables.py`: the scopes of `matchesContextOverflowMessage`
  (`assistant-error`, `failover-explicit`, `provider-fallback`, `failover-hint`,
  `context-window-too-small`, `tpm-rate-limit-hint`, `rate-limit-hint`), the provider-fallback
  candidate gate (`looksLikeProviderContextOverflowCandidate`) and the exact `rateLimit` and
  `billing` tables of `message-patterns.ts` (`isRateLimitErrorMessage`, `isBillingErrorMessage`).
  JS regex semantics are kept (ASCII `\b` and case folding, the JS `\s` set, `.` without line
  terminators, `$` at the very end).
- `memory_core/overflow_recovery.py`: `is_context_overflow_error_from_tables` /
  `is_context_overflow_error` and `is_likely_context_overflow_error` follow
  `failover/context-overflow.ts` (provider-fallback candidates, the `prompt template` exit, the
  real billing and rate-limit tables instead of approximations); the second observed-token pattern
  (backticked `max_tokens`) is added.
- `decide_provider_overflow_recovery` gains the parked Code Mode block
  (`previous_session_id`, `code_mode_suspended`; action `give_up` with
  `parked_work_blocks_continuation`, the `compact_then_truncate` truncation still runs, the
  truncation fallback does not), the no-real-conversation compaction no-op
  (`compaction_ok`, `compaction_reason`, `has_preflight_recovery`; action
  `reset_snapshot_and_retry` with `reset_context_snapshot`, no owned-transcript mark) and
  `is_no_real_conversation_compaction_noop`. A fix found by the oracle: the truncation-fallback
  retry now continues from the transcript when the attempt is not replay safe
  (`prepareCurrentTranscriptRetry`), like the other retries.

Oracle coverage:

- `contextOverflowTables` op, `tests/integration/test_openclaw_overflow_tables_oracle.py`: a
  hand-written corpus (about 100 messages, provider-fallback candidates, exclusions, Unicode edge
  cases) plus every string of the upstream `failover-classification.*.cases.ts` files, compared on
  every scope and on the helpers.
- `run_overflow_recovery_oracle` in `demo/openclaw_run_loop_oracle.py` (shares one runner,
  `_run_generated_vitest`, with the run-loop oracle) generates a Vitest file that reuses the mock
  harness and `makeInput` of upstream's `run.overflow-context-recovery.test.ts` (read from the
  checkout) and drives the real `recoverEmbeddedRunOverflow` through 22 scenarios (parked work,
  no-op reset, failed-compaction texts, truncation fallback).
  `tests/integration/test_openclaw_overflow_recovery_oracle.py` replays each scenario through the
  Python decision function and compares action, kind, user text and the side-effect counts. The
  existing run-loop oracle (7 cases) still passes after the refactor.

### Deviations and remaining gaps

- The Python side is a decision function, not the recovery runtime: compaction itself, hooks,
  context-engine maintenance, `resetNoRealConversationTokenSnapshot` (a session-store patch, host
  owned) and the transcript retry preparation are the host's. The decision carries the flags the
  host needs.
- `isContextOverflowError` consults a prepared provider plugin upstream
  (`classifyProviderPluginError`); memory-core has no provider plugins, so only the tables apply.
- The parked and no-op cases are exercised through `recoverEmbeddedRunOverflow` with upstream's
  mocks, not through `runEmbeddedAgent`; the full run loop is not driven for them.
- The assistant-error path (`isContextOverflow` over an assistant message, silent and length
  overflow, refusal handling) is not ported; only its wording scope is.

## Verification

With `OPENCLAW_ORACLE_NODE=/tmp/node24/bin/node OPENCLAW_ORACLE_REPO=/tmp/openclaw-head`:
projection 31 passed, overflow tables 3 passed (one call over the corpus), overflow recovery 25
passed, run-loop 7 passed, the existing truncate/preemptive/overflow-helper cases of
`test_openclaw_ts_oracle.py` 21 passed. Offline suite (`--ignore=tests/integration`): 1478 passed,
2 skipped, with the known sandbox failures deselected; `ruff check .` clean.
