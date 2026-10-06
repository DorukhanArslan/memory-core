# Gap 2: transcript rewrite, reset window, cache-TTL wiring, overflow error path

Against OpenClaw v2026.9.6 (oracle checkout `/tmp/openclaw-head`). Four items from the "Remaining"
list of the close-out row in `docs/upstream_port_v2026_9_6.md`. The parity docs and the changelog
are not edited here.

## What changed

| Item | Python | Oracle op | Fixtures (Python == TS) |
|---|---|---|---|
| `rewriteTranscriptEntriesInSessionManager` internals | `memory_core/transcript_rewrite.py` | `transcriptRewrite` | 29 scripted + 288 seeded-random transcripts, multi-round cases |
| `selectResetKeptEntries`, reset boundary of the context window | `memory_core/session_context_window.py`; `tool_result_projection.session_context_entries` delegates | `sessionContextWindow` | 21 scripted + 400 random entry lists |
| Cache-TTL provider eligibility, marker, call-site wiring | `memory_core/cache_ttl.py` | `cacheTtlEligibility` | 3,192 provider/model/api/route combinations, 131 marker reads, 12 marker-append scenarios |
| Assistant-error `isContextOverflow` path, provider-plugin hook | `memory_core/overflow_recovery.py` | `assistantOverflow` | 695 assistant messages, 447 upstream failover-corpus texts, 240 plugin/hook cases |

### Rewrite (`transcript_rewrite.py`)

`rewrite_transcript_entries_in_session_manager` is the line-for-line port of
`transcript-rewrite.ts` (matching by JSON equality, UTF-8 `bytesFreed`, branch from the first
rewritten message's parent or `resetLeaf`, per-type re-append with id remapping of
`firstKeptEntryId`, label targets and branch-summary parents, `__openclaw` compaction identity,
stale-checkpoint stripping, the prepare/commit step). It runs over `TranscriptSessionManager`, an
in-memory port of what the rewrite drives in upstream's `SessionManager`: the entry navigation
(`session-entry-navigation.ts`: opaque leaf controls, logical parents, reset-boundary crossing,
labels, `getBranch`), the append methods, `branch`/`resetLeaf`/`branchWithSummary`,
`appendLeafControl`, `getPersistedEntries` and `prepareTranscriptRewrite` with its commit (side
entries, `buildIndex`, trailing leaf control, adoption). The oracle compares the round results, the
active branch, all stored entries, the append cursor and the persisted entry list (leaf controls
included) with ids normalized and timestamps dropped. A deliberate mutation (dropping the side
marker) fails both tests.

### Reset boundary (`session_context_window.py`)

`iterate_session_context_entries` and `select_reset_kept_entries` replace the earlier
"a reset keeps nothing" approximation: a reset keeps the user/assistant messages after
`firstKeptEntryId` plus the tool results that a retained call owns (the pairing classifier of
`replay_repair.py`), and those entries bypass `excludeFromContext`. Contexts are `current`,
`retained` and `reset-retained`.

### Cache-TTL (`cache_ttl.py`)

`is_cache_ttl_eligible_provider` (Anthropic family incl. Bedrock ARN heuristics, Kilo Code
`anthropic/` refs, Google `gemini-2.5`/`gemini-3`), `read_last_cache_ttl_timestamp`,
`append_attempt_cache_ttl_if_needed` and, for the call site of `attempt-setup.ts`,
`resolve_attempt_cache_ttl_settings` (mode checked before the provider, so a disabled mode never
resolves hooks) and `CacheTtlContextTransform` / `install_cache_ttl_context_transform` (previous
transform first, prune with the cache-touch time, a prune moves the touch time to now,
`record_cache_touch`, server-side tool clearing suppresses new rounds only).

### Overflow (`overflow_recovery.py`)

`is_context_overflow(message, context_window)` (error wording with throttling exclusions, silent
overflow, length-stop overflow at 99 percent, context-usage buckets, provider refusals),
`classify_provider_plugin_error`, `is_context_overflow_error(..., provider_plugin=...)` and
`PreparedProviderFailoverOwner`, and `resolve_context_overflow_error`, the selection inside
`recoverEmbeddedRunOverflow` (prompt error alone; otherwise refusal and failover-reason vetoes,
structured `context_overflow`, own overflow shape, assistant error text, `length` stop).
`is_likely_context_overflow_error` gained the `discover_provider_plugin` hook.

## Deviations

* **Provider plugin hooks are host-supplied callables.** Upstream resolves the plugin from the
  plugin runtime by provider id. `is_cache_ttl_eligible_provider(provider_hook=...)` takes the
  `isCacheTtlEligible` callable for the provider; `provider_plugin=` takes a
  `PreparedProviderFailoverOwner`, `None` means explicit absence (no discovery, as upstream's
  `null`) and the unset default falls back to `discover_provider_plugin` (the host's
  `classifyProviderFailoverSignalWithPlugin`), absent that nothing classifies.
* **The rewrite is synchronous and in memory.** No SQLite store, bounded-context view, mutation
  fence, write admission or pending-input relocation (a pass-through when no pending input owns
  the entry). `appendMessage` does not run `applyAssistantDeliveryDirectives` (it strips
  reply/audio/TTS tags in place on every assistant append); pass `prepare_message` to
  `TranscriptSessionManager` for that.
* `resolve_context_overflow_error` takes `format_error` for `formatErrorMessage` (upstream also
  redacts; redaction is host side here) and the host's `FailoverClassification` mapping.
* `isProviderRefusalAssistantError` on a truthy non-array `diagnostics` throws upstream; Python
  returns `False`.
* `read_last_cache_ttl_timestamp` takes the entry list (or a callable) instead of a session
  manager.

## Not reachable from the oracle (ported from source, unit tested)

* The `transformContext` wiring in `attempt-setup.ts` and the overflow selection in
  `recoverEmbeddedRunOverflow` are inline in large installers: `tests/unit/test_cache_ttl.py` and
  `tests/unit/test_overflow_assistant_path.py`. The pruning, eligibility rules, marker and the two
  predicates they call are oracle-compared.
* A registered provider plugin: the runner has none, so the cache-TTL oracle runs the core rules
  and the hook is unit tested; the failover hook is oracle-compared with plugins built from a
  declarative spec on both sides (including the context each hook receives).

## Remaining gaps

* `memory_core/transcript_tree.py` omits `reset` from the canonical session entry types that
  `transcript-tree.ts` lists at v2026.9.6 (one frozenset entry; left alone because that module is
  shared with the session-corpus code and is not oracle-compared yet).
* The rewrite's persisted/bounded paths, `iterateSessionContextMessages` (message projection,
  `sessionHistoryPrelude`) and the other `SessionManager` methods are not ported.
* The cache-TTL transform is not yet connected to a Python host loop: nothing in the package calls
  `install_cache_ttl_context_transform` (the host owns the agent loop and its `transformContext`).
