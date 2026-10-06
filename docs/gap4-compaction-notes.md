# Gap 4: compaction call site and the Responses converter (v2026.9.6)

Scope: the two items the third round left open ("`preemptive_compaction.py` does not call
`resolve_compaction_replay_pressure`" and "the Responses message converter is a `projector` hook"),
each compared with the real TS at tag `v2026.9.6` (oracle checkout `/tmp/openclaw-head`). The
CHANGELOG, `docs/parity_matrix.md` and `docs/upstream_port_v2026_9_6.md` are untouched; fold these
notes in when the rows are updated.

## Changes

### (a) The pre-prompt decision calls the replay pressure

`memory_core/preemptive_compaction.py` now follows `preemptive-compaction.ts` end to end:

- `should_preemptively_compact_before_prompt(..., replay=, tool_schema_tokens=,
  llm_boundary_token_pressure=)`: `replay` is a `CompactionReplayPressureContext` (model, session,
  auth profile, `enabled`). With it, the transcript estimate runs over the checkpoint-projected
  window of `resolve_compaction_replay_pressure` (measured Responses usage bound to the wire prefix,
  else prefix estimate plus the later messages, or the Anthropic compaction summary). The returned
  `PreemptiveCompactionDecision` is the diagnostic maximum (the unwindowed history can win) and its
  new `compaction_replay` field carries the independently selected outgoing decision.
  `CompactionReplayRefreshRequiredError` and `TypeError` propagate as upstream's throws do.
- New helpers: `estimate_llm_boundary_token_pressure`, `estimate_rendered_llm_boundary_token_pressure`,
  `estimate_tool_schema_token_pressure` / `estimate_tool_schema_tokens`, `calculate_context_tokens`
  (the provider-measured boundary and its barriers: `api: "cli"` and zero `unavailable` records),
  `resolve_effective_compaction_reserve_tokens`, `format_pre_prompt_precheck_log`,
  `build_pre_prompt_context_budget_status`, `PREEMPTIVE_OVERFLOW_ERROR_TEXT`, `LlmBoundaryTokenPressure`.
- Behaviour changes to older code, all found by the new comparisons:
  - the effective reserve is capped at a quarter of the window
    (`resolveEffectiveCompactionReserveTokens`); the old `MIN_PROMPT_BUDGET_*` rule agreed only for
    small reserves;
  - `excludeFromContext: true` zeroes the estimate of any message (it was only read on
    `bashExecution`);
  - a missing `summary` on `branchSummary` / `compactionSummary` prints `undefined` as the
    template literal does;
  - `estimate_pre_prompt_tokens` stays (same value as the no-replay path).
- The Lab does not run an embedded agent, so nothing in `demo/` calls the decision; the call site
  of the provider-attempt preflight (`attempt-prompt-preflight.ts`) is the host's.

### (b) The Responses converter is built in

- `memory_core/responses_converter.py`: `convert_responses_messages` (transport projection) and
  `convert_provider_responses_messages` (provider projection), with the reasoning-item replay and
  ciphertext fencing, text/tool-call ids, async result ordering
  (`order_responses_async_tool_results`), delivery-order reconstruction
  (`responses_input_fingerprint`, `_InputReplay`), media and the system prompt message.
  `default_responses_input_projector(model, identity)` is the default `projector` of
  `resolve_responses_context_usage_boundary` / `resolve_compaction_replay_pressure`; the
  `projector=` argument stays an override. `ResponsesProjectionUnavailableError` is no longer raised
  (kept as a name).
- `memory_core/transcript_transform.py`: `transform_messages`, `transform_provider_messages`,
  `transform_transport_messages` (the OpenClaw host transform over `repair_tool_use_result_pairing`),
  `resolve_model_bound_thinking_replay_mode` with the Claude identity resolvers, and the replay turn
  classification (`resolve_failed_assistant_replay`, `is_reasoning_only_length_assistant_turn`).
- `memory_core/tool_result_text.py`: `extract_tool_result_text` and friends,
  `sanitize_surrogates`, the transport payload text helpers.
- `ReplayModel` gained `input`, `reasoning`, `compat`, `params` (defaults: a text and image model,
  as the oracle's model stub), which the converter reads; `stableStringify` prints `UNDEFINED` as
  `undefined` (the delivery-order fingerprint hashes items that still carry `phase: undefined`).

## Oracle numbers

- `tests/integration/test_openclaw_responses_converter_oracle.py`: 4,000 generated histories
  (10 Responses models, 3 identities, both projections, system prompts with cache boundaries,
  options, checkpoints, failed turns, async calls, reasoning signatures, unicode and lone
  surrogates) plus 200 fixed ones (10 histories x 10 models x 2 projections); 3,000 histories through the provider and transport transforms on
  their own (15 models incl. Anthropic Claude identities); 38 tool-result block lists (76 runs, with and without `includeStructured`);
  1,600 `resolveModelBoundThinkingReplayMode` pairs. All equal, error class included.
- `test_openclaw_compaction_checkpoint_oracle.py::..._measured_usage_pressure_...`: the 3,000+
  measured-usage pressure cases now also run against the built-in converter (no hook), all equal;
  the hook-fed comparison stays as the override path.
- `tests/integration/test_openclaw_preemptive_replay_oracle.py`: 2,500 histories without a
  checkpoint (measured usage, barriers, tool schema, boundary pressure, unwindowed), 3,000+
  measured-replay decisions built by the real `recordResponsesContextUsage` (1,000+ with a nested
  `compactionReplay`), 500 Anthropic-checkpoint decisions, 300 estimate-helper cases, 400 log lines
  and budget-status records. All equal. The existing `preemptiveCompaction` cases in
  `test_openclaw_ts_oracle.py` still pass (22 selected tests).
- Offline: `tests/unit/test_responses_converter.py` (16 tests).

## Deviations and remaining gaps

1. **Structured secret redaction.** Upstream's `extractToolResultText` redacts through the host's
   `redactModelVisibleSecrets`: `redactSecretsWithOptions` with the tool-payload patterns
   (`TOOL_PAYLOAD_REDACT_PATTERNS` = the default patterns minus the ambiguous assignment ones) and
   field-name based masking (`STRUCTURED_SECRET_FIELD_RE`, env field names, app-password fields).
   The built-in default (`tool_result_text.default_redact_model_visible_secrets`) applies
   `redact_sensitive_text` to every string and never masks by key; a host passes `redact=` to
   `extract_tool_result_text` / the converters. Measured against the oracle on structured blocks:
   vendor-token shapes and `Authorization: Bearer ...` agree; `{"password": "pw"}`,
   `{"apiKey": ...}` and similar field-name masks, and the tool-payload carve-outs (`KEY=value` env
   lines are left as is upstream, masked here), differ. The oracle fixtures avoid those shapes.
   Porting `redactModelVisibleSecrets` (the field regexes, `redactSensitiveFieldValueWithOptions`,
   the tool-payload pattern subset in `redact.py`) is the open item.
2. `normalizeAssistantReplayInput(fromResponse=true)` and `recordResponsesContextUsage` (the
   producer of the measured-usage state) are still not ported; the converter only needs the
   consumer side.
3. A malformed block throws a `TypeError` where upstream's property read would; the port raises
   `TypeError` at the same places it was observed (thinking without a string `thinking`, tool call
   without a string `id`, non-list `content`), not for every conceivable shape. `null` and a missing
   key are the same `None` in a Python dict, so `arguments: null` and a missing `arguments` are told
   apart only where the converter reads the key explicitly.
4. Synthetic missing tool results carry `int(time.time() * 1000)` as `timestamp` (`Date.now()`);
   the comparisons zero timestamps.
5. Callers upstream still without a Python counterpart: `attempt-prompt-preflight.ts` (routes on
   `compaction_replay`), `tool-result-context-guard.ts` (mid-turn `getReplay`),
   `compaction-session-execution.ts` and `attempt-stream-settle.ts` (the eligibility resolver's
   callers). `ReplayModel` is the host's description of the model; a real `Model` catalogue is not
   ported.
