# Gap notes: opt-in LLM consolidation (decision 3)

Port of OpenClaw v2026.9.6 `extensions/memory-core/src/dreaming-consolidation.ts`
(+ `dreaming-consolidation-candidates.ts`, `dreaming-consolidation-artifacts.ts` preimage part).
Deterministic promotion stays the default and the fallback.

## Changes

- `memory_core/consolidation/llm_consolidation.py`: `consolidate_memory`,
  `apply_memory_consolidation_plan`, prompt building (`build_consolidation_prompt`,
  `CONSOLIDATION_SYSTEM_PROMPT`), `parse_consolidation_plan`, `validate_consolidation_plan`,
  candidate eligibility, and the opt-in wrapper `run_llm_consolidation`.
- `memory_core/consolidation/curated_annotations.py`: `extract_project_keys_from_curated_entry`
  (project scoping of prior entries), ported from `curated-annotations.ts`.
- Exports added to `memory_core.consolidation`.
- Oracle: runner op `consolidateMemory` (`scripts/openclaw_oracle_runner.ts`) through
  `consolidateMemoryForTests` and `applyMemoryConsolidationPlan`; tests in
  `tests/integration/test_consolidation_oracle.py` (73 scenarios) and offline
  `tests/unit/test_llm_consolidation.py`.

## API

- Model: `ConsolidationModel = Callable[[ConsolidationRequest], str | obj-with-.text]`.
  `ConsolidationRequest` carries `message` (the JSON prompt), `system_prompt`, `model`,
  `timeout_ms` (60000). memory-core never imports an LLM client and never enforces the timeout.
- `consolidate_memory(model=, existing_memory=, candidates=, max_prior_entry_loss_fraction=, now_ms=,
  model_name=, memory_file_max_chars=, max_promoted_snippet_tokens=, identity=, logger=)` returns the
  validated plan or `None` (any group failed, was rejected, or the aggregate dry run failed).
- `apply_memory_consolidation_plan(...)` returns `MemoryConsolidationResult` or `None`.
- `run_llm_consolidation(workspace, candidates, model, LlmConsolidationOptions(enabled=False, ...))`:
  `enabled` is False by default; disabled or missing model returns `applied=False` and touches
  nothing. On success it writes MEMORY.md, stores the previous content in
  `memory/.dreams/consolidation-preimages.json` (last 8) and marks candidates promoted. On any
  rejection nothing is written and the host runs deterministic promotion.

## Deviations

- Sync callable instead of an async `subagent.complete`; no agent id; `logger` is a `logging.Logger`.
- Promotion marker prefix follows `RuntimeIdentity` (default `memory-core-memory-promotion:`;
  compat identity is byte-identical to upstream). The lineage marker prefix is derived from it
  (`memory-core-memory-lineage:` / `openclaw-memory-lineage:`). Readers accept both spellings; the
  replay check in apply also treats either promotion prefix as already promoted.
- Preimages live in a JSON file next to the recall store, not in the plugin-state SQLite keyed store;
  no `pruneMemoryEntryOrigins` (no origin store in Python).
- The model reply is `str` or an object with `.text`; other shapes are a parse failure (upstream
  would throw on `JSON.parse(undefined)`, same outcome: rejection).

## Remaining gaps

- Not wired into `run_dreaming_sweep` / deep phase: the host calls `run_llm_consolidation`
  itself and falls back to `run_short_term_promotion` on `applied=False`. Upstream's deep-phase
  orchestration (dreaming-phases.ts: candidate gating, workspace lock, `MemoryWriteConflictError`
  retry, atomic commit) is not ported.
- No `DREAMS.md` "Memory Consolidation History" summaries (`appendConsolidationSummary`,
  `appendConsolidationSkippedSummary`); `highlights` are returned but not written.
- No `tests` for deep-phase config keys that enable consolidation (`dreaming.deep.consolidation*`
  in the plugin config) since there is no config surface for it.
- Case-insensitive regexes use Python `re.IGNORECASE` rather than JS `/iu` folding (differs only
  for exotic characters such as U+212A/U+017F).
