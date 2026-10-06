# Gap 2: deep-dreaming consolidation port (v2026.9.6)

Scope: decision 3 of docs/upstream_port_v2026_9_6.md for the consolidation half of the deep
phase. Oracle: `extensions/memory-core/src/{short-term-promotion-apply,dreaming-consolidation,
dreaming-consolidation-artifacts,dreaming-dreams-file}.ts` at `/tmp/openclaw-head`.

## What changed

- `memory_core/consolidation/artifacts.py` (new): `store_memory_preimage` /
  `read_memory_preimages` over the existing `memory/.dreams/consolidation-preimages.json`
  (last 8, `{createdAt, content, contentHash}`), the DREAMS.md helpers (`resolve_dreams_path`
  with the `dreams.md` fallback, `read_dreams_file`, `write_dreams_file_atomic` that refuses
  symlinks and non-files, `update_dreams_file`) and the two history writers
  `append_consolidation_summary` / `append_consolidation_skipped_summary` (upstream text:
  `## Memory Consolidation History`, `### <ISO>`, `- Added/Merged/Superseded`, highlights, and
  `- Rewrite skipped: <reason>.` / `- Fallback: append-only promotion.`).
- `llm_consolidation.py`: `DeepConsolidation` (host model + `LlmConsolidationOptions` + logger;
  inactive unless `options.enabled` and a model are set), `plan_deep_consolidation`,
  `commit_deep_consolidation`, `record_deep_consolidation_history`, `hash_memory_content`,
  `consolidation_candidate_fingerprint`. `run_llm_consolidation` also writes the DREAMS summary.
- `promotion.py`: `run_short_term_promotion(consolidation=...)` follows
  `applyShortTermPromotions`: origin/session filter before the selection limit, model plan
  before the lock, lock-time re-check (same candidates by fingerprint, MEMORY.md hash), apply,
  preimage, hash re-check just before the replace, atomic commit, mark promoted, DREAMS summary;
  every failed step falls back to the deterministic append and a skipped rewrite gets the
  skipped-summary note. `MemoryPromotionRun` gained `consolidation` and
  `consolidation_skipped_reason`.
- `dreaming.py`: `run_dreaming_sweep(consolidation=...)` passes it to the deep phase, lists
  the DREAMS file in `files_changed` when it changed, and now forwards the policy's
  `max_prior_entry_loss_fraction` (it was dropped before).
- Case folding (`bootstrap/_js.py` `js_i_pattern`, existing `js_iu_keyword_pattern`): the
  `/giu` regexes (normalize-comparable-fact steps, promotion markers, project annotations) use
  simple-fold classes; the `/i` regexes (dreaming fences, recall contamination patterns) fold
  ASCII only, with ASCII `\b` and `\d`. Python `re.IGNORECASE` is gone from
  `memory_core/consolidation`.

## Oracle evidence

- `tests/integration/test_deep_consolidation_oracle.py`: `applyShortTermPromotions` op with a
  `consolidation` payload (through `applyShortTermPromotionsForTests`, stubbed subagent) for 12
  scenarios, and the new `consolidationHistory` op for the two summary writers (5 cases).
  MEMORY.md, DREAMS.md/dreams.md, preimages, model calls (message, system prompt, model,
  timeout), warnings, applied keys and `promotedAt` all compare equal to the TS run.
- `tests/unit/test_deep_consolidation.py`: offline wiring, history text and case-folding tests.

## Deviations

- Opt-in: default off, and the consolidation-only filter (reject candidates whose origin is not
  `owner`/`agent`, or that are non-interactive session-derived) applies only when consolidation
  is active. Upstream's deep phase always passes `consolidation`, so it filters even with no
  subagent.
- One process lock instead of upstream's two (`withFileLock` + `withMemoryWorkspaceLock`); the
  deep sweep's promotion lock covers the commit and the DREAMS write. DREAMS writes take no
  extra workspace lock.
- The preimage store is a JSON file, not a keyed SQLite namespace; entries have no `key`.
- No memory-entry origin ledger (`reserveMemoryEntryOrigins` / `pruneMemoryEntryOrigins`), so
  preimage rotation prunes nothing and there is no rollback of reserved origins.
- No `ENOENT`-style `MemoryAtomicPublicationError` / in-place fallback distinctions: a
  `PermissionError` on the replace maps to upstream's "directory blocked atomic replacement"
  skip; other write errors propagate.
- Python evaluates and plans once before the lock and once under it (upstream re-reads the store
  entry and source file fingerprints per candidate; here the candidate fingerprint covers key,
  range, snippet, provenance and project key, and the rehydrated snippet is compared).
- `memory.promotion.applied` host events and the rejection categories list
  (`rejectedCandidates`) are not ported.

## Remaining gaps

- `rejectedCandidates` categories and the `reject()` reporting of the deep report lines.
- REM/light phase narrative consolidation inputs are unchanged (separate gap).
- The model call is the host's: it enforces `timeout_ms`; the package never cancels it.
