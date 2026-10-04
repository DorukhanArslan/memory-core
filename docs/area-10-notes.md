# Area 10 notes (transcript and overflow helpers), for the lead to merge

Branch `worktree-agent-aa5ddb14b939f6380`, oracle tag v2026.9.6.

## What changed

- `history.limit_history_turns`: hysteresis eviction (d5dee714c4f). Nothing is cut until more than
  `ceil(1.5 * limit)` user turns exist; then `limit + (users - limit) % (ceil(1.5*limit) - limit + 1)`
  turns are kept.
- `runtime_context_prompt`: ported `run/runtime-context-prompt.ts`. Provenance is explicit
  (`fragments`), prompt text is never parsed. `resolve_runtime_context_prompt_parts` takes
  `fragments` / `allow_runtime_only` (the `model_prompt` / `empty_transcript_mode` parameters and
  `runtimeSystemContext` are gone); the custom message content is only the delimited block and its
  `details` carry `runtimeContextCarrier` and `fragments`. New: `append_current_inbound_context`,
  `prepend_runtime_context_for_model`, `build_runtime_context_message_content`,
  `build_current_inbound_prompt(prefer_resumable_text=)`.
- `replay_history.normalize_assistant_replay_content`: failed turns (error stop or zero-usage empty
  stop, empty or legacy sentinel content) are dropped instead of rewritten to the sentinel;
  reasoning-only `length` turns, bare delivery-mirror duplicates, managed display blocks
  (image/audio/video/attachment*) and silent text next to reasoning are dropped; blank user turns
  with persisted media (`__openclaw.media`) are kept with `content: ""`.
- `bootstrap/startup.py`: the 1,200-unit per-file cut is `truncateUtf16Safe` (no lone surrogate).
  `docs/workspace_layout.md:154` still describes the pin-era split-surrogate transport shim; it is a
  no-op now (kept as a harmless boundary).
- Tool-result budgets: new `memory_core/_tool_result_budget.py` (`cjk-chars.ts` weighting incl.
  `minimumRawWeight`, budgeted head/tail slices). `truncate_tool_result_text`,
  `truncate_tool_result_message` (small-block preservation, notice budgets) and the aggregate plan
  (two-phase trim then clear, `aggregateEligible`, protected trailing batch that stops at an
  assistant message, nested `details.spill`) now count weighted chars, not code points.
- `overflow_recovery`: `CONTINUATION_PROMPT` (shared, replaces the mid-turn-only text; the old name
  `MID_TURN_PRECHECK_CONTINUATION_PROMPT` is an alias), `current_attempt_replay_safe`,
  provider request-size ceiling (`is_provider_request_size_ceiling_error`, also lets the TPM check
  keep a ceiling message classified as overflow), side-effect caution in the user text, failed
  preflight compaction as `compaction_failure` with the timeout wording.
- Oracle runner: `runtimeContextPrompt` now passes fragments and also reports
  `appendedContext` / `prependedMessages`; `truncateToolResultText` accepts `minimumRawWeight`.

## Oracle numbers (against /tmp/openclaw-head)

Worklist tests of area 10 all pass and both entries are removed from `oracle_worklist.py`:
history limit, runtime context prompt (4 cases), assistant replay (extended fixture), startup
emoji-at-file-cap, tool-result text truncation (9 cases incl. CJK, astral, floors 2 and 3) and the
run-loop mid-turn scenario. New passing fixtures: 7 aggregate session-truncation cases, 2 extra
overflow-helper messages. See the final report for the last full run.

## For the lead

- `tests/parity/test_oracle_worklist.py::test_port_plan_assigns_every_worklist_area_to_one_plan_area`
  fails until the two labels ("transcript and replay helpers", "overflow run loop") are removed from
  area 10's "Worklist areas" line in docs/upstream_port_v2026_9_6.md.
- The prefix-entry check in that file now uses a synthetic wildcard entry (no real one is left).

## Deviations and open gaps

- `get_history_limit_from_session_key` lacks the account-scoped values and `route` disambiguation
  (`accounts.<id>`, linked peers) of the tag; the fixture keys do not use them. The
  `SESSION_HISTORY_PRELUDE` symbol has no Python equivalent.
- Replay: `hasPersistedMedia` is simplified (no `normalizeMediaFact`), `hasNonzeroUsage` reads the
  common counters only (no nested `*_details` or cache subtraction), compaction-replay checkpoint
  owners (`replaceCompactionReplayOwnerContent`) and `stripInboundMetadata` are not ported; silent
  reply detection is still the exact token (existing known gap).
- Tool results: UTF-16 lengths are used in the truncation helpers, but the aggregate plan still
  slices through the same helpers only; prompt-projection state (cache-TTL pruning, frozen keys,
  `projectToolResultBranch`) and `truncateOversizedToolResultsInSessionManager` on a real
  `SessionManager` are not ported (the session-file variant stays).
- Overflow: `decide_provider_overflow_recovery` stays a pure decision function. Not ported: parked
  Code Mode work blocking continuation, the no-real-conversation compaction no-op reset, and the
  provider-fallback candidate matching of the overflow tables (ceiling messages use the explicit
  check only). The run loop itself lives in the oracle only.
