# Gap 3: compaction replay pressure, writers, eligibility and egress (v2026.9.6)

Port of the remaining `provider-compaction-replay.ts` surface against the real TS oracle
(`/tmp/openclaw-head`, v2026.9.6). Everything below is compared Python == TS in
`tests/integration/test_openclaw_compaction_checkpoint_oracle.py` unless a section says it is
unit tested instead. Ops live in `scripts/openclaw_oracle_runner.ts` (`compactionCheckpoint`
gained fns, `inlineImage` is new).

## Changes

| Upstream | Python | Oracle fixtures |
| --- | --- | --- |
| `sanitizeInlineImageDataUrl`, `...ForStorage`, `sanitizeInlineImageBase64`, `canonicalizeBase64`, `sniffInlineImageMime` (media-core) | `memory_core/inline_image.py` | canonical base64 362, signature sniffing 500+ (incl. every high-bit alias of RIFF/WEBP/GIF/ftyp), data URLs 1,482 (url + storage), `sanitizeInlineImageBase64` 300 |
| `sanitizeResponsesImagePayload` | `memory_core/responses_egress.py` | 161 payloads (nested, non-string URLs, identity of the unchanged params) |
| Responses payload policy, input part (`resolveOpenAIResponsesEndpointClass`, `usesKnownNativeOpenAIRoute`, `shouldStripInputStatus`) | `memory_core/responses_egress.py` | through `window`/`isOutput`: 36 windows x 226 route models = 16,344 comparisons, plus 1,000+ resolver/plan/preserve cases over 10 routes |
| `new URL(x).hostname` (needed by the endpoint classifiers) | `memory_core/js_url.py` | 1,260 host/template combinations (IPv4 forms, IPv6, IDNA, userinfo, ports, schemes) |
| `isOpenAIResponsesCompactionOutput(value, model)`, `readOpenAIResponsesCompactionWindow(replay, model)` | `compaction_replay.py`: signature is now `(value, model=None, egress_projection=None)` | see the egress rows |
| `createCompactionCapture` (begin/delta/complete), `suppressAnthropicCompaction` | `CompactionCapture`, `suppress_anthropic_compaction` | 1,008 event sequences, plus suppression over 7 models x 4 identities |
| `captureOpenAIResponsesCompaction`, `suppressOpenAIResponsesCompaction` (with `onCompactionRejected`), `createCompactionTracker`, `buildOpenAIResponsesReasoningReplayMetadata`, `isOpenAIResponsesReplayContext` | `capture_openai_responses_compaction`, `suppress_openai_responses_compaction`, `CompactionTracker`, `build_openai_responses_reasoning_replay_metadata`, `is_openai_responses_replay_context` | capture 2,500+ (items x boundaries x metadata x pre-existing replay x compacted outputs, one 16 MiB window), tracker 500+, suppression 600+ |
| `resolveCompactionReplayEligibility`, `resolveAnthropicServerCompactionPlan(...).enabled`, `isDirectAnthropicModel` | `resolve_compaction_replay_eligibility` and friends | 3,309 combinations of provider x api x base URL x extraParams x API key x `ANTHROPIC_BASE_URL`, against the real host (`src/llm/ai-transport-host.ts`) |
| `resolveCompactionReplayPressure`, `estimateResponsesInput` (private), `estimateResponsesContent` (private) | `resolve_compaction_replay_pressure`, `estimate_responses_input` | anthropic 5,760, responses 7,840 (prefix, window, retained, refresh-required, suppression, usage shapes, tails with and without `contextUsage`), `estimateResponsesInput` 1,042 |
| `resolveResponsesContextUsageBoundary`, `contextFingerprint`, `normalizeAssistantReplayInput`, `stableStringify` | `resolve_responses_context_usage_boundary`, `responses_context_fingerprint` | measured usage: 900 recorded conversations (real `recordResponsesContextUsage`) x about 6 mutations = 5,000+ pressure cases, `stableStringify` 426 |

`egress_projection` stays on every resolver, plan builder and the window readers as an override of
the built-in projection (unit tested in `tests/unit/test_compaction_replay_gap3.py`).

## Deviations and host hooks

- **Message converter (hook).** The measured-usage boundary rebuilds the wire input with
  `convertResponsesMessages` / `convertProviderResponsesMessages` (615 lines plus the
  transcript transform). It is a `projector` hook on `resolve_compaction_replay_pressure` and
  `resolve_responses_context_usage_boundary`. Without one, a candidate that passes every other
  check raises `ResponsesProjectionUnavailableError` (upstream would convert). The oracle runs the
  real converter and hands its output to the Python hook, so everything except the converter is
  compared. Fixtures are produced with the real `recordResponsesContextUsage`.
- **Anthropic endpoint class.** Eligibility follows the real OpenClaw host
  (`resolveProviderRequestCapabilities` over plugin manifests): `api.anthropic.com` is
  `anthropic-public`, a bare host (`api.anthropic.com/v1`) gets `https://` first. The
  library-default host (every URL `default`) would answer differently for those; the `endpoint_class`
  hook replaces the classification (other plugins' hosts, route facts attached to a model).
- **Secret sentinels.** `resolveSecretSentinel` swaps process-local `oc-sent-v2.` sentinels (AES-GCM
  with a per-process key). Python has no such registry: `resolve_secret_sentinel` hook, identity
  default. A sentinel-shaped key therefore is not compared (the real host throws for an unknown one).
- **Payload policy.** Only the part that touches `payload.input` is ported (the `status` rule of
  `shouldStripInputStatus`). Store, prompt-cache, server-compaction threshold and reasoning rules
  cannot change `payload.input` and are not ported. The Anthropic compact threshold is not ported
  (eligibility needs `.enabled` only).
- **URL host parsing.** `js_url.url_hostname` is a WHATWG host parser written for this port. IDNA is
  NFKC + per-character lower-casing + punycode (UTS 46 without its validity checks), so an invalid
  non-ASCII host can differ (valid ones, `ß`, final sigma, full-width forms, ideographic dots,
  match).
- **Replay `ReplayModel`** still carries only provider, api, id and base URL; `compat`,
  `contextTokens` and `contextWindow` do not influence anything ported here.
- **Not touched:** `memory_core/session_entry.py`. Nothing in this gap reaches it; the capture and
  suppression writers write `providerReplay` on the assistant message dict they are given.

## Findings worth keeping

- `_stable_stringify` first sorted keys by UTF-16 little-endian bytes (wrong for astral versus
  high BMP keys); caught by the unit test and now verified against the oracle (426 values).
- Node 24 `JSON.parse` of the oracle payload intermittently produced an object whose last sorted key
  was `"\\"` instead of the real key when a batch mixed a `"\\"` key with other BMP keys (reproduced
  by sending the same value after about 20 others; the same value alone is parsed correctly). The
  stableStringify fixtures avoid a `"\\"` key; the other fixtures never hit it.
- `estimateResponsesInput` is private upstream. The oracle loads a throw-away sibling copy of
  `provider-compaction-replay.ts` that also exports it (written next to the original, imported,
  deleted at once) instead of re-implementing it on the TS side.

## Remaining gaps

- The Responses message converter itself (see the hook above), including its use of the host
  `transformTransportMessages`.
- Call sites: `memory_core/preemptive_compaction.py` does not call `resolve_compaction_replay_pressure`
  yet (upstream `estimateTranscriptBoundaryTokenPressure` and `compaction-session-execution.ts` /
  `attempt-stream-settle.ts` for `resolveCompactionReplayEligibility`). The functions and the
  estimator the runner passes (`default_replay_pressure_estimator`) are ready for that wiring.
- Existing `_js_length`/`_js_index_of` of `replace_compaction_replay_owner_content` count a string
  `content` in code points, not UTF-16 units. An assistant `content` is an array upstream, so this
  is unreachable with valid messages; left as is.
- `normalizeAssistantReplayInput(output, fromResponse=true)` (provider output side of the usage
  fingerprint) is not ported: the boundary only fingerprints request input.
