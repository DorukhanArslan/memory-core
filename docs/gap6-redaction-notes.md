# Gap 6: redaction, the registry, `logging.redactPatterns` and the policies (notes)

Scope: OpenClaw v2026.9.6 (oracle checkout `/tmp/openclaw-head`), `src/logging/redact.ts` with
`secret-redaction-registry.ts`, `redact-internal-state.ts`, `redact-pattern-runtime.ts`,
`src/security/config-regex.ts` + `safe-regex.ts` and `src/agents/transcript-redact-text.ts`.
This file records what the port adds, where it deviates and what stays out; the parity matrix row
(Redaction) and the upstream port notes are updated by the main session from it.

## What is ported (all oracle-verified, Python == TypeScript)

| Piece | Python | Upstream |
| --- | --- | --- |
| Exact-secret registry | `memory_core/secret_registry.py` (re-exported by `memory_core.redact`) | `secret-redaction-registry.ts` |
| User patterns: parsing, safe-regex screen, JS-regex translation | `memory_core/redact_user_patterns.py` | `redact-pattern-runtime.ts` (`parseRedactPatternSource`), `config-regex.ts`, `safe-regex.ts` |
| Options and policies | `memory_core/redact.py` | `redact.ts` |

Host-facing API (defaults unchanged: no registered value and no configuration gives the
previous output byte for byte; `redact_sensitive_text(text)` is still
`redactSensitiveText(text, {mode: "tools"})`):

- Registry: `register_secret_value_for_redaction(value)`, `register_secret_values_for_redaction`,
  `is_secret_value_registered_for_redaction`, `has_registered_secret_values_for_redaction`,
  `get_secret_redaction_registry_revision`, `reset_secret_redaction_registry`,
  `capture_sensitive_text_redaction_snapshot` / `create_sensitive_text_redactor`,
  `redact_registered_secret_values(text, mask)`. Every redaction entry point masks registered
  values first, including `build_session_entry` (it calls `redact_sensitive_text`), as upstream's
  session export does.
- Configuration: `LoggingConfig(redact_patterns=..., full_context_tool_payload=...)`,
  `configure_logging_redaction(config)` (the host's `readLoggingConfig()`: what the functions use
  when no `logging_config=` is passed), `mark_full_context_tool_payload_redaction(config)`.
- Functions: `redact_sensitive_text(text, *, mode, patterns, config)`,
  `redact_tool_payload_text` (`redactToolPayloadTextWithConfig`), `redact_model_visible_tool_payload_text`,
  `redact_sensitive_field_value`, `redact_model_visible_field_value`, `redact_secrets`,
  `redact_model_visible_secrets(value, *, logging_config=None)`, `redact_transcript_text`,
  `redact_transcript_structured_field_value`, `compute_sensitive_redaction_bitmap`,
  `get_default_redact_patterns`, the pattern constants `DEFAULT_REDACT_PATTERNS` and
  `TOOL_PAYLOAD_REDACT_PATTERNS`, and the programmatic rule types `RedactMatcher` / `RedactMatch`.

### (a) Registry rules reproduced

Values under 6 UTF-16 units are ignored; a value registers its `encodeURIComponent` form and its
`JSON.stringify` content form (each only when different) and then the raw value last; at most 512
distinct entries, oldest evicted first, re-registering an existing value only moves it to the newest
slot and does not change the revision; the matcher buckets values by their first 6 units, longest
first, scans left to right, leftmost start wins, longest value wins at a start, a rejected prefix
resumes one unit later; masks use `maskToken` (under 18 units `***`, else 6 + `…` + 4); the
registry applies in `mode="off"`, in the full-context path, to fields (also the public-share id
path), and a snapshot redactor ignores later registrations. UTF-16 counting is exact (an astral
character is 2 units, offsets passed to a mask callback are units).

### (b) `logging.redactPatterns` rules reproduced

- Entry syntax: `/source/flags` (flags from `gimsuy`, `g` added) or a bare source with the flags
  `gi`; the source is trimmed (JS whitespace); a blank entry is skipped silently; a nested
  repetition (`safe-regex.ts` tokenizer and analyzer, ported 1:1) or an invalid expression drops that
  entry only; `/x/d` is not a literal (a bare source), duplicate flags (`/x/gg`) are invalid.
- Combination: `redactSensitiveText({patterns})` and the no-options form (config) use the user
  patterns INSTEAD of the 122 default strings (the AWS bare-key matcher and the structured-auth,
  URL-query and form-body protections always run; an empty list means the defaults, with the
  prefilter); `redactToolPayloadText*` and `redactModelVisibleToolPayloadText*` MERGE (user first,
  then the default or tool-payload table, no prefilter); for field values the sensitive-name path
  merges the user patterns with the full default table and the others with the tool-payload table;
  user patterns have no prefilter, so every field value takes the full scan.
- Pattern identity quirks kept: a configured string equal to a built-in source keeps that source's
  special handling (shell-reference preservation, form-aware values, PEM matcher, chunk-unsafe
  prefixes also for user strings); matchers are deduplicated by identity and the AWS matcher is
  appended when absent.
- Chunking above 32,768 units for ordinary user patterns, whole text for chunk-unsafe prefixes and in
  full-context mode; empty matches advance one position (JavaScript `replace`, not Python `sub`);
  sticky (`y`) patterns match contiguously.
- Programmatic `RedactMatcher` rules (the plugin SDK's executable entries) with `groups`,
  `replacement` and ordering, tested against a JS matcher with the same logic.

### (c) Full-context and policy rules reproduced

`isFullContextToolPayloadRedaction` (`mark_full_context_tool_payload_redaction`): registered values,
then every pattern over the whole text in one pass (no prefilter, no chunking); only the passed config
counts for the mark (a missing config is not full-context even if the host's is set). The
tool-payload, model-visible, field-value, structured-record (`redactSecrets` /
`redactModelVisibleSecrets`) and transcript policies, with the registry and user patterns, and
`computeSensitiveRedactionBitmap`.

## Oracle numbers

New operation `redactPolicies` in `scripts/openclaw_oracle_runner.ts` (scenario = registry values,
file or explicit logging config, full-context mark, steps; the registry is reset through upstream's
test API with `NODE_ENV=test`; the config file is read by the real `readLoggingConfig`).

- `tests/integration/test_redact_policies_oracle.py`: 174 fixed scenarios (4,611 steps: registry
  ordering, encoded/JSON variants, eviction, snapshots, 61 pattern cases each run directly and through a
  config file, chunking, matchers, the policies under 5 configs with and without full-context, transcript
  wrappers, bitmaps) + 2 generated batches (900 scenarios with random registries, patterns and policy
  calls) + the unsupported-syntax classification check + the identity-port guard: 181 tests.
- `tests/integration/test_redact_user_regex_oracle.py`: 5 seeds x 500 generated JavaScript regexes
  (about 1,800 valid ones, 14,000 texts; the rest are rejected by the nested-repetition screen or invalid,
  classification compared too).
- Offline: `tests/unit/test_redact_policies.py` (17 tests).
- Together with the 564 earlier redaction oracle tests and the 39 offline redaction tests: 882 passed in 43 s.

## Deviations

1. Python API shape: keyword-only options; `config="host"`/`logging_config=None` read the process's
   `configure_logging_redaction` value instead of the config file. `readLoggingConfig`'s includes,
   env substitution and partial-config recovery are not ported (the host passes the strings).
2. `register_secret_value_for_redaction` raises `ValueError` where `encodeURIComponent` throws
   `URIError` (a lone surrogate), before registering anything.
3. Programmatic matchers receive a code-point `str` and return code-point offsets (converted to units
   internally); a registry mask callback receives the value and its UTF-16 offset.
4. Regex translation is a parser written for this port, checked against V8 on generated expressions, not an
   engine. Valid JavaScript it cannot translate is classified `unsupported-syntax` and dropped like an
   invalid entry (not fail-closed; `compile_redact_pattern(raw).reason` tells a host which entries are
   dropped): `\p{..}`/`\P{..}` with `u`, look-behind bodies Python cannot compile (top-level alternatives
   are split into one look-behind each and do work), the `v` flag, duplicate named groups (V8 accepts them
   in some shapes), repeat counts beyond Python's limit.
5. Engine differences left: case-insensitive matching uses Python's Unicode folding, so U+017F, U+212A, U+0130
   and U+0131 fold differently from V8 without `u`; captures inside a repeated group are not reset per
   iteration; an empty match inside an astral character under the `u` flag (V8 resumes between the
   surrogate halves); a very large nested or backtracking-heavy pattern is not time-limited.
6. Values walked by the structured policies are JSON values (dict, list, tuple, str, number, bool, None), as
   before.

## Remaining gaps

- The log-record transport: `redactLogRecord`, `redactLogRecordForTransport`,
  `serializeRedactedFileLogRecord`, `redactSensitiveLines`, `resolveFileLogRedactOptions` and their
  machinery (`redact-json.ts`, `redact-json-tokens.ts`, `redact-edit-composition.ts`): a logging
  concern (serialized JSON log lines with origin tracking), no memory-core caller.
- `redactInputTextWithSourcePolicy` / `redact-source.ts` (a JavaScript tokenizer, acorn, decides which
  assignment-looking source text is syntax).
- `prepareModelVisibleToolTextBlock` and the provenance cache of `redact-internal-state.ts` (identity-keyed;
  no effect on the redacted text, only on whether a block is redacted again).
- `redact-performance.ts` (diagnostics channel), `diagnostic-support-redaction.ts`, `log-tail-redaction.ts`
  and the other consumers in `src/` (not read for this port).
- Patterns that depend on engine behaviours listed under deviation 5.
