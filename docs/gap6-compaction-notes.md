# Gap 6: the upstream callers of the compaction replay decision (v2026.9.6)

Scope: the call sites that feed `shouldPreemptivelyCompactBeforePrompt` and
`resolveCompactionReplayEligibility`, which earlier rounds ported without their callers
(`docs/parity_matrix.md` rows "Pre-prompt overflow decision" and "Provider overflow recovery";
CHANGELOG Stage 2 "still not ported" list). Everything is a decision function with host-supplied
inputs: there is no agent loop in memory-core.

## Changes

| Upstream | Python |
|---|---|
| `run/attempt-prompt-preflight.ts` `prepareEmbeddedAttemptPromptPreflight` | `memory_core/attempt_preflight.py` `prepare_attempt_prompt_preflight` |
| same file, `handleEmbeddedAttemptMidTurnPrecheck` | `handle_attempt_mid_turn_precheck` |
| `tool-result-context-guard.ts` `installToolResultContextGuard` (the mid-turn guard, `getReplay`) | `memory_core/tool_result_context_guard.py` `ToolResultContextGuard.transform_context` |
| `run/midturn-precheck.ts` | `MidTurnPrecheckRequest`, `MidTurnPrecheckSignal`, `is_mid_turn_precheck_assistant_error` |
| `tool-result-char-estimator.ts`, `tool-result-limits.ts` `resolveToolResultContextMaxChars`, `context-truncation-notice.ts` | same module (`estimate_message_chars`, `truncate_tool_result_to_chars`, ...) |
| `run/attempt-stream-settle.ts` eligibility call (`compactionReplayEnabled`) | `resolve_attempt_compaction_replay_enabled` |
| `compaction-session-execution.ts` eligibility call, `preserveCompactionReplayWindow` and `recordServerCompaction` measurement | `resolve_compaction_session_replay` returning `CompactionSessionReplay` (`preserve_window`, `estimate_server_compaction_tokens_after`) |

Behaviour worth knowing (all follows upstream line for line):

* The preflight builds the replay context from the attempt model, `sessionId`, the runtime plan's
  forwarded auth profile (the attempt's own `authProfileId` is ignored) and the eligibility flag.
  A context engine that owns compaction skips the decision unless it returned a checkpoint window
  (`compaction_replay`) or its prompt authority is `preassembly_may_overflow`. Only the checkpoint
  window's own route (`compaction_replay.route != "fits"`) blocks submission and yields a
  `PreflightRecovery`; the raw-history maximum that overflows is logged as
  `[context-pressure-diagnostic]` and admitted. `CompactionReplayRefreshRequiredError` becomes a
  `precheck` prompt error with `skip_prompt_submission`.
* The mid-turn guard builds its request from the top-level (diagnostic) decision, not from
  `compaction_replay`, exactly as `toMidTurnPrecheckRequest` does.
* The mid-turn handler tries the persisted tool-result truncation first for
  `truncate_tool_results_only`; "no oversized or aggregate tool results" is handled with
  `truncatedCount: 0` (no compaction manufactured), any other failure falls back to `compact_only`
  plus the precheck error text.

## Verification

Oracle: `tests/integration/test_openclaw_replay_callers_oracle.py` (op `replayCallers` in
`scripts/openclaw_oracle_runner.ts`), real TS on the v2026.9.6 checkout:

* `prepareEmbeddedAttemptPromptPreflight`: 1,950 scenarios (plain histories on 7 models, measured
  Responses usage recorded by the real `recordResponsesContextUsage`, Anthropic and Responses
  checkpoints including `refresh-required`, retained windows, heavy tool results under tight
  budgets, context-engine and prompt-authority variants, unwindowed views, skip flags) compared on
  the whole returned state, the budget record, the recovery route and snapshot, the prompt error
  class and text, and every log line. The eligibility flag comes from the real
  `resolveCompactionReplayEligibility` with the stream-settle wiring (`extraParams`, `apiKey`, env).
* `handleEmbeddedAttemptMidTurnPrecheck`: 450 scenarios on a real in-memory `SessionManager` with the
  real `truncateOversizedToolResultsInSessionManager` (all routes, handled with and without
  truncation, fallback), comparing the route, snapshot, error, the messages handed to
  `replaceSessionMessages`, the branch after truncation and the handler's own log lines.
* `installToolResultContextGuard`: 1,500 scenarios with 1 to 4 `transformContext` calls each (growing
  histories, images, mixed blocks, CJK, `tool`/`type: toolResult` shapes, fences, replay contexts
  from measured Responses histories), comparing the returned messages (and whether the same list came
  back) or the signal and its request, and the `onMidTurnPrecheck` calls.
* `estimateMessageChars` 2,500 messages, `resolveToolResultContextMaxChars` and the truncation notice
  (52 cases).
* The compaction-session wiring: 700 scenarios (eligibility, `preserveCompactionReplayWindow`, the
  post-compaction `estimateLlmBoundaryTokenPressure`).
* Offline: `tests/unit/test_replay_callers.py` (21 tests).

Ported from source and unit tested only (not reachable on the real TS): the 700-line
`compactSessionExecution` and the 680-line `attempt-stream-settle.ts` function around the two
eligibility calls. For those the oracle replays the same wiring on the real callees
(`resolveCompactionReplayEligibility`, `preserveCompactionReplayWindow`,
`estimateLlmBoundaryTokenPressure`), which checks the composition but not that upstream passes these
arguments; that is read from source (`compaction-session-execution.ts` lines 320, 394-410 and 483-487,
`attempt-stream-settle.ts` line 669).

## Deviations

* Host callables replace what memory-core does not have: `normalize_messages_for_llm_boundary`
  (`normalizeMessagesForLlmBoundary`, used only for the unwindowed precheck view),
  `sanitize_compaction_replay_messages`, `build_session_context_messages`, `replace_session_messages`,
  the persisted `truncate_tool_results` (the Python counterpart is
  `truncate_oversized_tool_results_in_session_file`), `log(level, message)` and `now` (the budget
  record's `Date.now()`). The oracle feeds the first from the real function's output for the same
  input and the truncation from the same transcript, so the combined output is real-vs-real; the
  normalizer itself is not ported.
* The guard is the state and decision of the wrapped `transformContext`; the host calls
  `transform_context` from its own hook and lets `MidTurnPrecheckSignal` propagate. The per-block
  `prepareToolResultTextChars` memo and `WeakMap` caches are dropped (pure caches).
* A `TypeError` that V8 raises for a malformed message (for example `content` that is not an array)
  is matched by class; the message wording is the engine's.
* The preflight returns `PreflightRecovery` and an `Exception` where upstream returns a plain object
  and an `Error`; `to_dict()` gives the upstream camelCase shape.

## Remaining gaps

* `installContextEngineLoopHook` (same file as the guard: per-iteration `afterTurn`/`ingest`/`assemble`
  with the transcript prompt markers) is not ported; it is context-engine orchestration.
* `normalizeMessagesForLlmBoundary` and `sanitizeCompactionReplayMessages` themselves (user timestamp
  stamping, persisted sender context, runtime-context carriers, stale thinking signatures and usage).
* The transport handler that records Responses context usage and the rest of the compaction run
  (hooks, server-endpoint compaction, timeouts) stay with the host.
* Nothing in `demo/` calls the new functions yet; the Lab never compacts.
* `overflow_recovery.decide_provider_overflow_recovery` still takes `preflight_route` and
  `preflight_source` as separate arguments; the host unpacks `PreflightRecovery` into them.
