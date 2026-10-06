# Gap notes: `redactSensitiveText` (R13)

Scope: port of OpenClaw v2026.9.6 `redactSensitiveText(text, {mode: "tools"})`, the redaction
`buildSessionEntry` applies to every exported session text. Written for whoever updates
`docs/parity_matrix.md` and `docs/upstream_port_v2026_9_6.md` (not edited here).

## What changed

- `memory_core/redact.py`: `redact_sensitive_text(text)`. Upstream sources ported:
  `src/logging/redact.ts` (the `redactText` path: structured authorization parameters, URL query
  values, form bodies, then the default pattern list with chunked matching above 32,768 units),
  `redact-patterns.ts` (all 122 `DEFAULT_REDACT_STRING_PATTERNS` verbatim, the AWS secret-access-key
  matcher), `redact-pem.ts` (complete-block matcher), `redact-bounded.ts`, `redact-pattern-runtime.ts`
  (capture selection, PEM block masking), `packages/acp-core/src/structured-auth-redaction.ts` and
  `isSensitiveUrlQueryParamName` of `packages/net-policy/src/redact-sensitive-url.ts`. Also the
  default-options prefilter (fast path) with all its triggers.
- `memory_core/session_entry.py`: the default redaction is now `redact_sensitive_text`. The host
  `redact_text` hook stays as an extension applied after it; `apply_default_redaction=False` turns
  the built-in pass off. `session_corpus.py` therefore redacts what it indexes.
- Oracle: op `redactSensitiveText` in `scripts/openclaw_oracle_runner.ts` (texts in, redacted texts
  out; `meta` returns the pattern table, `BODY_SECRET_KEYS` and the `\p{C}`/`\p{Z}` ranges of the
  runtime). The `sessionCorpusEntry` op now uses upstream's default redaction instead of the
  identity, and has a case with secrets.
- Tests: `tests/integration/test_redact_oracle.py` (about 535 fixtures, a third of them from the vendor-token table, across vendor
  tokens, env/JSON/CLI/URL/header/form/config shapes, PEM, AWS, base64 boundaries, UTF-16 and
  Unicode edge cases, chunking and gate edges, plus 4,520 seeded generated texts, all compared with the
  real function; table checks for the pattern sources, key sets, prefilter sources, chunk
  constants and Unicode tables) and `tests/unit/test_redact.py` (offline).

## How JavaScript semantics are kept

- Pattern sources are the upstream JavaScript strings (a test compares them with the checkout);
  `translate_js_regex` rewrites `\s`, `\S`, `.`, `$`, `\w`, `\d`, `\b`, classes and the `s`/`k`
  folding of `/iu` into Python `re` with `re.ASCII`. Bare strings are case-insensitive, `/.../g`
  literals keep their (absent) flags, like `parseRedactPatternSource`.
- UTF-16: the `u`-flag stages (authorization parameters, URL query, form bodies, gate) run over
  code points; the non-`u` pattern stage runs over a unit string (`to_units`), so `{0,40}`
  gaps, mask lengths, chunk boundaries and lone surrogates count like JavaScript.
- `\p{C}` / `\p{Z}`: tables generated with Node 24 (Unicode 17); Python 3.11's `unicodedata`
  (Unicode 14) would read newer assigned characters as unassigned. A test compares the tables with
  the pinned runtime.
- The one variable-length lookbehind (`;base64,` guard of the base64-safe vendor prefixes) is a
  post-match check with retry; the gate's two lookbehind alternatives are replaced by their forward
  equivalents.

## Deviations and remaining gaps

- Not ported: the registry of exact secret values (`redactRegisteredSecretValues`,
  `secret-redaction-registry.ts`): memory-core has no such registry; hosts mask their own values via
  `redact_text`. Also not ported: the config-driven `logging.redactPatterns`, the other policies
  (`redactToolPayloadText`, model-visible tool payloads, structured field/JSON-record redaction,
  edit composition, app-specific passwords), and the performance measurement hooks.
- The gate (fast path) is run over code points and the pattern stage over units; the oracle
  agrees on 4,520 generated texts and the fixtures, but a text that only differs where Python's
  `re` and V8 disagree on backtracking limits or case folding outside the ASCII/`ſ`/`K` cases is
  untested (for example `İ` and `ı` do not fold, matching JavaScript, because `re.ASCII` is used).
- Large inputs: Python has no regex time limit; upstream's chunking bounds pattern work but both
  sides handle a 17,000-line env dump and a 9,000-fragment text in the fixtures.
- `to_units`/`from_units` join adjacent surrogate halves on output, so a string holding a high
  and a low surrogate that JavaScript would also treat as a pair compares equal; lone halves stay.
