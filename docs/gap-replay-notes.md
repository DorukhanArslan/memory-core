# Replay and history gaps closed against v2026.9.6

Oracle: OpenClaw checkout at `v2026.9.6` (`OPENCLAW_ORACLE_REPO`), node 24. Every item below is
compared Python == TS by an oracle op (new ops in `scripts/openclaw_oracle_runner.ts`, tests in
`tests/integration/test_openclaw_ts_oracle.py`). Docs `CHANGELOG.md`, `docs/parity_matrix.md` and
`docs/upstream_port_v2026_9_6.md` are left for the integrator.

## Changes

| Item | Python | Oracle op | Fixtures |
|---|---|---|---|
| (a) `getHistoryLimitFromSessionKey` with account scopes, linked peers, `route` | `memory_core/history.py` | `historyLimitCases` | about 190 keys in 4 tests (key shapes, account-scoped keys, route facts, config/provider edge cases) |
| (b) `stripInboundMetadata` in the replay display path (`stripInternalMetadataForDisplay`) | `memory_core/replay_history.py` (wiring), `memory_core/session_entry.py` (existing port, fixed) | `stripInboundMetadata` (stripped text and display text) | 345 texts |
| (c) `replaceCompactionReplayOwnerContent`, `isCompactionReplayCheckpoint`, `stripCompactionReplayCheckpoint(+InPlace)` | new `memory_core/compaction_replay.py`; call sites in `replay_history.py` and `replay_repair.py` (`sanitize_tool_call_inputs`) | `compactionReplayOwner`, `replayContentCases` | 508 owner cases, 108 replay / tool-input lists |
| `hasPersistedMedia` (`normalizeMediaFact`) | `memory_core/replay_history.py` | `replayContentCases` | 540 user messages |
| `hasNonzeroUsage(normalizeUsage(...))` | new `memory_core/usage_normalization.py` | `normalizeUsage`, `replayContentCases` | 409 usage values (full normalized dict compared) plus the mirror-duplicate recovery |

Details worth knowing:

- (a) The provider list is gone: upstream's `normalizeProviderId` is only trim plus lowercase, so
  any channel key matches (the old port knew eight providers and mapped `z.ai`). Empty key parts
  are kept (`"telegram::dm:1"` is not `"telegram:dm:1"`). The configured value is returned as is,
  with no number validation (a string or `true` limit comes back unchanged, `null` is `None`),
  because upstream does the same. The account key lookup is `resolveChannelAccountEntry` without a
  channel key policy (the plugin metadata snapshot that supplies policies is not in the port):
  exact key, then the first key whose `normalizeAccountId` equals the routed one.
- (b) `strip_inbound_metadata` already existed in `session_entry.py` (session corpus). Fixture
  runs found one divergence, fixed there: the bare `Context:` sentinel line uses a JS `/m` regex,
  where `\r`, U+2028 and U+2029 also end a line. The replay display strip is now
  `strip_inbound_metadata(strip runtime context and preface)`; `session_entry` keeps the
  runtime-context-only stripper (`_strip_runtime_context_and_preface`) because upstream's
  `sanitizeSessionText` applies `stripInboundMetadata` to user text only, once.
- (c) Matching of surviving blocks is by identity (`is`), like `Array.prototype.indexOf`;
  primitives compare by value with JS strict equality (`True` is not `1`).
- `hasNonzeroUsage` now reads the nested `*_details` objects, subtracts the cache buckets from
  provider input totals, applies the context-usage rules (`unavailable` counts, `available` only
  with `total >= prompt`), and accepts only real numbers (no numeric strings or booleans), as
  upstream. `_is_bare_delivery_mirror_duplicate` accepts array usage like upstream's
  `typeof usage === "object"`.

## Deviations

- `replace_compaction_replay_owner_content` on a string original content: the text search of
  `String.prototype.indexOf` is reproduced for string and object blocks only (`"[object Object]"`
  for an object). A `null` original content raises `TypeError` like upstream; a non-array,
  non-string original content with new blocks raises `TypeError` too. In the replay pipeline this
  only matters for an owner message that has a compaction checkpoint and malformed content.
- Strings are indexed by code point, not UTF-16 unit, inside `strip_inbound_metadata`; results are
  the same because only slices and searches over the same string are used.
- Numbers beyond 2**53 echoed through JSON are not part of the fixtures (Python ints vs JS
  doubles); `normalize_usage` itself clamps counters to `Number.MAX_SAFE_INTEGER`.
- `historyLimitCases` passes `config` per case or from the payload; a case with an `undefined`
  config is not expressible.

## Remaining gaps

- Not ported from `provider-compaction-replay.ts`: `resolveCompactionSource`,
  `preserveCompactionReplayWindow`, `requiresCompactionReplayRefresh`,
  `resolveCompactionReplayPressure` and their feeders (`anthropic-compaction-replay.ts`,
  `openai-responses-compaction-replay.ts`, `openai-responses-context-usage.ts`, about 800 lines
  that need the provider payload policies and model identity). Other callers of
  `replaceCompactionReplayOwnerContent` (`embedded-agent-helpers/openai.ts`, `images.ts`,
  `run/attempt-tool-call-replay-sanitization.ts`) belong to unported provider-specific rewrites.
- `limit_history_turns` ignores upstream's `openclaw.sessionHistoryPrelude` symbol marker (a
  runtime-only property that JSON cannot carry).
- `stripLeadingInboundMetadata` and `extractInboundSenderLabel` (same upstream file) are not
  ported; no replay or session path of the port calls them.
- `isSilentReplyPayloadText` stays the exact-token check noted in `replay_history.py`, and
  `isZeroUsageEmptyStopAssistantTurn` keeps its own simplified port (`empty-assistant-turn.ts`).
