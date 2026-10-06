# Gap 5: model-visible redaction and measured-usage recording (v2026.9.6)

Scope: the two items `docs/gap4-compaction-notes.md` left open (deviations 1 and 2), each compared
with the real TS at tag `v2026.9.6` (oracle checkout `/tmp/openclaw-head`). The CHANGELOG,
`docs/parity_matrix.md` and `docs/upstream_port_v2026_9_6.md` are untouched; fold these notes in
when the rows are updated.

Base: this branch started from `main` at `e101a13`, which does not hold the converter; the
converter lives on `feat/close-port-gaps-4` (`6787086`), so the branch was fast-forwarded to it
before any change.

## Changes

### (a) `redact_model_visible_secrets` (`memory_core/redact.py`)

Port of `redactModelVisibleSecrets` (`src/logging/redact.ts`) with `redact-patterns.ts` and
`structured-authorization-code.ts`:

- A string goes through `redactSensitiveText` over `TOOL_PAYLOAD_REDACT_PATTERNS`: the default
  patterns minus the twelve ambiguous assignment families (env `KEY=value`, escaped env,
  structured JSON secret, quoted secret/auth fields, standalone and config assignments), plus the
  AWS matcher. Model-visible tool output is mostly source code, so `API_KEY=...` lines and
  `const password = "..."` are left alone (`TOOL_PAYLOAD_REDACT_STRING_PATTERNS`,
  `_tool_payload_patterns`).
- A dict or list is walked (`redactStructuredSecretValue`): every string under a key goes through
  `redactSensitiveFieldValue` (`redact_model_visible_field_value`): public-share ids are masked;
  the tool-payload subset runs, or the full default table under a sensitive key; then
  app-specific passwords (`xxxx-xxxx-xxxx-xxxx`, benign-word exceptions, forced for keys such as
  `text`/`message`/`error`); then a whole-value `mask_token` for a sensitive key
  (`STRUCTURED_SECRET_FIELD_RE`, the env-style key RE, `isSensitiveFieldKey`) unless the value is a
  shell reference to its own key or the internal `$WORKSPACE_DIR/....jsonl` session path. A key
  named `code` is masked unless its path ends in `error`/`nodeError`/`status`/`details`/`warnings`
  or it is a top-level key, and a `cause.code` that is a known transport error code is kept.
  Numbers and booleans under a sensitive key become `"***"`; `None` stays; key order follows
  JS (index keys first); the input is never mutated.
- `memory_core.tool_result_text.default_redact_model_visible_secrets` is now this function, and
  `memory_core/responses_converter.py` imports it as the default of `redact=` (the override stays).
  `redact_sensitive_text` is unchanged apart from `_redact_text(text, patterns)` taking a pattern
  table.

### (b) `recordResponsesContextUsage` and `normalizeAssistantReplayInput(fromResponse=true)`

In `memory_core/compaction_replay.py`:

- `record_responses_context_usage(message, model, identity, request, output, projection)`: the
  producer of `openclawResponsesInputReplay.contextUsage` (gates: available positive safe-integer
  total, not `error`/`aborted`, no `providerReplay`, no `previous_response_id`, a compaction item in
  the request and none in the output; the replay output comes from the built-in converter with
  synthetic `function_call_output` items removed; `includeSystemPrompt` is true when the request has
  no `instructions` and starts with a developer/system message). It mutates `message`.
- `normalize_assistant_replay_input(items, from_response=False)`: the `fromResponse` branch
  re-serializes a function call's `arguments` object through `JSON.parse` with unsafe integers
  quoted (`quote_unsafe_integer_literals`, `parse_json_object_preserving_unsafe_integers`, ports
  of `json-unsafe-integers.ts`) and `JSON.stringify` (`js_stringify`).
- `responses_continuation_prefix_fingerprint(input, output)` and
  `responses_context_fingerprint(input, output=())`: the fingerprint now takes the output side
  (reasoning bytes of both, `fromResponse` normalization of the output) and the prefix hash runs
  over the JSON round trip upstream applies (`undefined` properties vanish).

## Oracle numbers

New oracle ops: `redactModelVisibleSecrets` (values, `isSensitiveFieldKey`, per-field values,
pattern tables) and, in `compactionCheckpoint`, `normalizeReplayInput`, `prefixFingerprint`,
`recordContextUsage`. `normalizeAssistantReplayInput` is private upstream; the op loads a
sibling copy of `openai-responses-continuation.ts` that also exports it (same trick as the
pressure estimator).

- `test_redact_oracle.py`: 86 named structured values (field-name masks, `KEY=value` carve-outs,
  `code` paths, app passwords, public-share ids, numbers under secret keys, shell references,
  index-order keys, lone surrogates, 80 KB strings), 2,100 generated structured values,
  163 key names through `isSensitiveFieldKey`, 18 `(key, value)` field cases, the tool-payload
  pattern table, and the field/env/app-password regex sources against the upstream source. All
  equal. The 564 earlier `redactSensitiveText` tests still pass.
- `test_openclaw_responses_converter_oracle.py`: 13 secret-bearing tool-result block lists added to
  both the tool-text comparison (76 -> 102 runs) and the history generator; the 4,000 generated and
  200 fixed histories still equal.
- `test_openclaw_compaction_checkpoint_oracle.py`: 1,600 generated item lists plus 48 argument
  texts (96 runs) through `normalizeAssistantReplayInput` (both modes, 100+ rewritten arguments), 1,200
  prefix fingerprints (with and without output), 3,000 `recordResponsesContextUsage` cases
  (hundreds recorded, hundreds gated off, state and hash equal). The existing 3,000+ measured-usage
  pressure comparison passes with the new fingerprint. Whole file: 691 passed together with
  `test_redact_oracle.py`.
- Offline: `tests/unit/test_redact_model_visible.py` (6 tests). Known sandbox failures unchanged
  (`test_project_name.py` 1 failure and 3 errors, the `test_curation_tools` os-error test).

## Deviations and remaining gaps

1. The exact-secret registry (`redactRegisteredSecretValues`, `secret-redaction-registry.ts`) is
   not ported: a host has no registry, so it is empty, as in the oracle process.
2. `logging.redactPatterns` and the full-context tool-payload mode
   (`isFullContextToolPayloadRedaction`) are not read. The oracle runs with a sandbox `HOME`, so
   upstream also sees no user patterns; a host that wants them passes `redact=`.
3. Only JSON values are walked: no `bigint`, no non-plain objects (upstream returns those as is), no
   `undefined`; circular containers print `[Circular]` but cannot arise from JSON.
4. `prepareModelVisibleToolTextBlock` (the per-block provenance cache, used when blocks are
   persisted) is not ported; it has no effect on the redacted text.
5. `redact_model_visible_field_value` returns the original string object when nothing changed and
   compares through `from_units`, so a string holding split surrogate halves is returned as
   given; upstream's `!==` sees no difference.
6. `record_responses_context_usage` omits `undefined` hashes (absent session/auth/base URL) from the
   saved state instead of storing `None`, as persistence would; `request` keys are read by presence
   (`instructions` is "undefined" only when the key is missing, so JSON `null` counts as set).
7. Callers upstream (the transport's terminal-response handler that invokes
   `recordResponsesContextUsage`) still have no Python counterpart; the function is for hosts
   that run their own Responses transport.
8. `normalizeAssistantReplayInput` equality is shown through the output of the private function
   (JSON, so an `arguments: undefined` that upstream sets on a call without arguments reads as
   absent on both sides).
