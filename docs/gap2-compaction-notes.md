# Gap 2: compaction checkpoint resolvers and inbound metadata helpers

Port target: OpenClaw v2026.9.6, each function verified against the real TS (oracle ops
`compactionCheckpoint` and `inboundMetadataHelpers` in `scripts/openclaw_oracle_runner.ts`, tests in
`tests/integration/test_openclaw_compaction_checkpoint_oracle.py`).

## Changes

`memory_core/compaction_replay.py`
- `resolve_compaction_source`, `preserve_compaction_replay_window`,
  `requires_compaction_replay_refresh` (upstream `provider-compaction-replay.ts`).
- `resolve_newest_anthropic_compaction`, `build_anthropic_replay_plan`
  (`anthropic-compaction-replay.ts`).
- `resolve_newest_openai_responses_compaction_replay`,
  `build_openai_responses_compaction_replay_plan`, `CompactionReplayRefreshRequiredError`,
  `read_openai_responses_compaction_window`, `is_openai_responses_compaction_output`
  (`openai-responses-compaction-replay.ts`, `openai-responses-compaction-window.ts`).
- The replay context fence: `short_hash` (`utils/hash.ts`), `build_provider_replay_context`,
  `provider_replay_context_matches`.
- Model identity and session/auth identity are plain parameters: `ReplayModel(provider, api, id,
  base_url)` and `ReplayIdentity(session_id, auth_profile_id, enabled)`.

`memory_core/session_entry.py`: `strip_leading_inbound_metadata`, `extract_inbound_sender_label`.

## Verification

Python == TS on the oracle for: `shortHash` and `buildProviderReplayContext` (about 300 cases),
Anthropic newest-checkpoint/plan/refresh/preserve (about 6800 cases), Responses
(about 15700 cases, including 60 `complete-window` and 90 `refresh-required` outcomes), about 700
window-validation cases, fencing across model/identity combinations, cross-family checkpoints, and
about 560 inbound texts for the two metadata helpers. `resolveCompactionSource` is private upstream;
it is checked through `requiresCompactionReplayRefresh` and `preserveCompactionReplayWindow`
(the family and mode decide their output), with the two newest-checkpoint resolvers and plan
builders compared directly.

## Deviations

- Egress projection is a host hook. Upstream `readOpenAIResponsesCompactionWindow` requires the
  saved window to survive the Responses image sanitiser and the payload policy unchanged
  (`sanitizeResponsesImagePayload`, `applyOpenAIResponsesPayloadPolicy`), which depend on the
  provider route. The port takes an optional `egress_projection(window) -> window` callable; without
  it the schema validation, byte limits and checkpoint match still apply but a window upstream would
  reject for a non-native route (`status` fields stripped) or an invalid inline image data URL is
  accepted. The oracle fixtures use a native OpenAI route and https/file image references, where the
  projection is the identity upstream.
- `replayIndex` is returned as an `int` (JSON floats such as `1.0` are accepted like upstream
  numbers).
- Owner identity: `owner` is the same message object from the input list, like upstream's `===`;
  callers must pass the objects they will compare.

## Remaining gaps

- `resolveCompactionReplayPressure` (needs `resolveResponsesContextUsageBoundary` and a token
  estimator) and the capture side (`createCompactionCapture`, `captureOpenAIResponsesCompaction`,
  suppression writers) are not ported.
- `resolveCompactionReplayEligibility` (needs the Anthropic server-compaction plan and the payload
  policy) is not ported; the host supplies `ReplayIdentity.enabled`.
- Inline image data URL sanitiser (`sanitizeInlineImageDataUrl`) is not ported (see the hook above).
