# Full OpenClaw Memory Equivalence Checklist

This is the active plan for `memory-core`. Cleanup is the first work item. The target is fixed to OpenClaw `v2026.9.9`; old `v2026.9.6` results remain historical evidence and do not complete any item below.

A completed infrastructure task does not mean a completed port. Every behavior in section 4 starts unverified. The authoritative machine-readable contract is [scope.json](../equivalence/scope.json): **64 required contracts and 128 acceptance points**. A report belongs to the exact reference and scope hashes it records. Scope changes must be versioned explicitly; do not silently add requirements to a previously reported baseline.

## 1. Remove unnecessary and misleading material first

- [x] Remove the 14 superseded implementation plans and specifications under `docs/superpowers/`; verify that active documentation has no remaining links to them.
- [x] Remove the empty historical oracle worklist and the tests that only validate that empty worklist. Keep real behavioral regressions.
- [x] Remove test-startup deletion of the shared temporary OpenClaw lock directory. Tests must own and clean only their own state.
- [x] Mark the old parity matrix and re-pin narrative as historical `v2026.9.6` evidence. Correct broad claims that an empty worklist proves that no expected failures or behavioral gaps remain.
- [x] Run import, reference and focused regression checks after cleanup, and record exactly which files were removed.

Keep the working SDK, Lab, framework adapter, license and substantive regression cases. They have users or protect real behavior. Removing a test that exposes an unresolved difference is not cleanup. Existing regression tests may remain, but they cannot supply a pass to the new full-equivalence gate.

## 2. Freeze the reference and the contract

- [x] Verify the release tag resolves to commit `bcfc88812a35243893585dbeca87ca41b48272ca`, and retain that exact commit in [reference.json](../equivalence/reference.json).
- [x] Require a real, clean reference checkout at that commit. Reject a missing checkout, another release or modified reference source before comparison.
- [x] Verify and record the Node runtime. Supported reference range: `>=24.16.0 <25 || >=26.1.0`; Node 25 is excluded.
- [x] Inventory source modules, runtime dependencies, exported operations and observable effects for the fixed contract. Version any deliberate exclusion.
- [x] Record Python implementation identity, reference identity, contract identity, actual runtime versions and case identifiers in every comparison report.

The reference repository is `https://github.com/openclaw/openclaw.git`. Python-only convenience features remain separately tested extensions. Different internal storage is acceptable only where the declared external memory results, isolation, concurrency and failure behavior still match; this is not a promise of binary interchange with OpenClaw's private database.

The [source map](equivalence-source-map.md) links all 64 contracts and 128 acceptance points
to the pinned upstream code and the current Python implementation. The inventory records
103 upstream source modules, their tracked hashes, literal dependencies and exported
declarations. Source presence and inventory validation do not establish behavior or add
any differential-test coverage.

## 3. Rebuild the differential tests from a clean authority boundary

- [x] Keep the new comparison harness independent of `demo/`, old literal expectations and old parity status labels.
- [x] Import and execute the real pinned TypeScript functions. Do not copy the algorithm into an oracle stub or use Python output as the expected answer.
- [ ] Give both implementations the same fixtures, deterministic clocks, provider stubs, filesystem inputs and explicitly driven lifecycle events.
- [ ] Compare complete observable results: ordering, source ranges, citations, errors, events, changed files, published index state and dispatch counts where applicable.
- [x] Attach every case to a required contract and the exact acceptance points it exercises. One passing helper case cannot complete a whole feature area.
- [x] Distinguish `match`, `mismatch`, `blocked/error` and `uncovered` in reports. A missing runtime, dependency, unsupported operation or untested acceptance point must never become a match.
- [x] Make the default full command fail when any required contract or acceptance point is uncovered, mismatched or blocked. No skips, expected failures or implicit fallback results satisfy this gate.
- [x] Keep `--smoke` explicit. It executes the currently registered cases and can establish only that bounded comparison set; it cannot establish full equivalence.
- [x] Do not automatically retry a failed reference comparison and report only a later success. Preserve the first failure and its diagnostics.
- [x] Test the harness itself against wrong commits, dirty source, missing executables, timeout, malformed or duplicate results, missing coverage, unknown acceptance identifiers and deliberate result mismatches.
- [x] Keep credentials out of fixtures, subprocess environments and reports. Deterministic embedding and model wire fixtures test behavior without paid calls.
- [x] Add a reproducible CI command and retained comparison artifacts. Keep offline regression results and real differential results visibly separate.

Comparisons must not normalize away behavior. A platform-specific path, generated identifier or clock value may be normalized only under an explicit case rule that preserves the relevant relationship. Any numeric tolerance must be local and justified; it must not turn a changed ranking, gate decision or inclusion boundary into a match.

## 4. Implement and verify the fixed memory behavior contract

Entries remain pending until their complete acceptance conditions are verified against `v2026.9.9`. Their detailed acceptance points and stable identifiers are in [scope.json](../equivalence/scope.json). A helper that already exists in Python still needs the new differential evidence. A known difference must stay visible until its implementation and tests agree. Bounded passing subsets are recorded below without closing the containing contract.

### Storage and workspace

- [ ] **`storage.discovery` — Discover exactly the eligible memory files.** Compare roots, nested Markdown, case sensitivity, order, hidden artifacts and disappearing files. Exclude or admit symlinks and non-regular files exactly as the pinned reference does.
- [ ] **`storage.path-safety` — Enforce memory path and read boundaries.** Exercise absolute, relative, traversal, encoded and symlink paths. Compare rejected operations, result shapes and absence of unintended writes.
- [ ] **`storage.atomic-writes` — Publish writes atomically.** Compare append, replace, exclusive creation and concurrent rename outcomes. Inject write, flush, fsync and publication failures and inspect the surviving files.
- [ ] **`storage.workspace-isolation` — Keep workspace and subject state separate.** Reuse one host configuration across distinct workspaces and subjects. Prove files, indexes, recalls and maintenance state cannot cross the selected boundary.

### Lexical and chunking

- [ ] **`lexical.tokenization` — Match lexical tokenization.** Compare exported token sets for empty, repeated, ASCII, mixed-script, CJK and Unicode boundary inputs. Use deterministic generated strings as well as named cases; preserve all observable tokens.
- [ ] **`lexical.fts-query` — Match full-text query construction.** Compare query strings and no-query outcomes for punctuation, quotes, identifiers, whitespace and mixed scripts. Exercise deterministic generated inputs without reconstructing the reference algorithm in the oracle.
- [ ] **`lexical.bm25` — Match BM25 rank conversion.** Compare positive, negative, zero and boundary ranks, including supported non-finite input representations. Report numerical differences rather than masking score-gate changes with a blanket tolerance.
- [ ] **`chunking.markdown-boundaries` — Match Markdown chunk boundaries.** Compare ordered chunks, lines, overlap, empty content, headings and per-entry curated files. Read the original source through every returned line range.
- [ ] **`chunking.utf16-cjk-budget` — Match UTF-16 and CJK chunk budgets.** Exercise surrogate pairs, malformed surrogates, CJK weighting and exact budget boundaries. Compare truncation and overlap without splitting valid pairs or changing source ranges.
- [ ] **`chunking.entry-provenance` — Retain chunk identity and provenance.** Compare chunk hashes, entry boundaries, source identities and provenance fields. Verify unchanged and changed inputs produce the reference identities and invalidation decisions.

### Index lifecycle

- [ ] **`indexing.identity` — Match index identity gating.** Vary provider, model, endpoint settings, scope, sources, tokenizer and chunking versions. Compare missing, matching and stale metadata diagnostics before any query is admitted.
- [ ] **`indexing.incremental-sync` — Match index refresh and invalidation.** Create, update, rename and delete files and sessions while retaining an index. Compare discovery, chunk replacement and unchanged-file handling across reopen.
- [ ] **`indexing.transaction-publication` — Publish one coherent index revision.** Interleave readers with successful and failing rebuilds. Compare visible old/new revisions and prevent partial chunk, FTS or provenance publication.
- [ ] **`indexing.embedding-cache` — Match embedding reuse and invalidation.** Use a deterministic instrumented embedder to count query and document calls. Compare cache identity, batching, changed chunks, failed batches and retained entries.
- [ ] **`indexing.query-sync` — Match query-time synchronization.** Query an empty or stale index before and after source changes. Compare forced-sync/retry policy, unavailable outcomes and dispatch counts.

### Retrieval and ranking

- [ ] **`retrieval.vector-scoring` — Match vector candidate scoring.** Compare cosine scoring, candidate bounds, zero vectors and incompatible dimensions. Compare ordered source/range identities before downstream hybrid ranking.
- [ ] **`retrieval.hybrid-scoring` — Match hybrid merge and score gates.** Compare vector-only, text-only, overlapping and disjoint candidates with configured weights. Check selection, minimum-score boundaries and lexical fallback without dropping result fields.
- [ ] **`retrieval.exact-path-priority` — Match exact-path retrieval priority.** Exercise exact paths, basename matches, partial paths and body-only matches. Compare path specificity tiers, ties and interaction with content score.
- [ ] **`retrieval.mmr` — Match diversity reranking.** Compare disabled/enabled MMR, duplicate text, equal scores, stable ties and lambda boundaries. Exercise CJK, empty and punctuation-only snippets and preserve output ordering.
- [ ] **`retrieval.temporal-decay` — Match recency decay.** Compare enabled/disabled decay, half-life boundaries, future dates and missing timestamps. Compare dated versus evergreen memory paths and session activity timestamps under a fixed clock.
- [ ] **`retrieval.importance-project` — Match importance and active-project ranking.** Exercise importance annotations, triggers and active/inactive project keys. Compare multipliers and their order relative to path tiers, decay and MMR.

### Memory tool contract

- [ ] **`tools.search-contract` — Match memory_search inputs and results.** Compare definitions, accepted parameters, coercion, defaults, corpora and rejection errors. Compare complete ordered payloads, citations, warnings and source metadata.
- [ ] **`tools.get-contract` — Match memory_get inputs and results.** Compare allowed files, line windows, UTF-16 budgets, continuation hints and missing sources. Compare exact status/error shapes and returned source text.
- [ ] **`tools.deadline-cooldown` — Match deadlines and cooldowns.** Control clocks and slow providers to exercise absolute deadlines and cooldown transitions. Compare subsequent admission, provider call counts and memory/wiki/session independence.
- [ ] **`tools.unavailable-partial` — Match unavailable and partial corpus outcomes.** Fail individual providers and supplemental corpora independently. Compare partial results, timed-out flags, warnings and recovery on a later explicit query.

### Sessions and transcript

- [ ] **`sessions.corpus-admission` — Match session corpus admission.** Compare accepted session kinds, ownership, participants, archives and generated maintenance sessions. Provide the same host metadata and compare included and excluded entries.
- [ ] **`sessions.transcript-filtering` — Match transcript extraction and filtering.** Compare JSONL trees, tool rows, heartbeat markers, recalled content and failed or mirrored messages. Exercise reset fences, malformed rows and supported archives without inventing stored text.
- [ ] **`sessions.visibility-lineage` — Match source-session visibility and lineage.** Vary visible sessions, source identities, trust and forgotten origins. Compare hits, provenance and source reads before and after reset or deletion.
- [ ] **`sessions.reset-hook` — Match new/reset memory capture.** Compare transcript projection, naming, timezone, slug behavior and exclusive publication. Verify source lines, trust records, collision handling and recall after the hook.
- [ ] **`sessions.durable-context` — Preserve durable conversation context.** Persist actual transcript and session metadata and reconstruct the host in a fresh process. Compare continuation, ordering and retained context without relying on process-local lists.

### Prompt and bootstrap

- [ ] **`prompt.bootstrap-discovery` — Match workspace bootstrap selection.** Exercise setup states, session kinds, available files and compatibility layouts. Compare ensure decisions, selected files and their order under the same inputs.
- [ ] **`prompt.bootstrap-budget` — Match bootstrap clipping and notices.** Exercise per-file, USER.md and aggregate UTF-16 limits and exact boundary values. Compare clipping, omitted files, warning modes and once-per-session state.
- [ ] **`prompt.runtime-context` — Match memory and runtime prompt composition.** Compare memory guidance, tools, runtime markers and fixed clock/timezone fragments. Compare insertion order and isolation of untrusted or recalled text.
- [ ] **`prompt.history-repair` — Match history windowing and tool repair.** Exercise missing results, duplicate or invalid calls, failed turns and provider replay metadata. Compare repaired model-visible messages while preserving the original durable transcript.

### Flush and compaction

- [ ] **`flush.plan-target` — Match flush plan and target selection.** Compare enabled/disabled configuration, model selection, timezone and daily target validation. Compare prompts, reserve terms and failure before a target can be safely prepared.
- [ ] **`flush.trigger-usage` — Match flush trigger accounting.** Feed fresh/stale usage, missing usage, transcript byte limits and compaction counters. Compare trigger decisions, heartbeat exclusions and retry/exhaustion state.
- [ ] **`flush.execute-finalize` — Match flush execution and finalization.** Run the same labelled model/tool sequence through both hosts. Compare append-only writes, index readiness, provenance and successful or failed cycle stamps.
- [ ] **`compaction.memory-budget` — Match curated memory budget compaction.** Exercise promotion sections mixed with user text and exact size/loss limits. Compare preserved bytes, removed sections, deferral and reconciliation markers.
- [ ] **`compaction.context-assembly` — Match context assembly and compaction replay.** Compare active transcript projections, summaries, checkpoints, tool-result bounds and replay decisions. Retain trailing required results and provider continuation data across restart.
- [ ] **`compaction.provider-overflow` — Match overflow recovery behavior.** Drive preflight and mid-turn overflow, truncation, compact/retry and terminal failures. Compare dispatch counts, protected messages and exact continuation/admission decisions.

### Recall and promotion

- [ ] **`promotion.recall-signals` — Match recall recording.** Compare filtering, deduplication, query hashes, day boundaries, retention and recall events. Verify ground truth source ranges and origin recording before published recall state.
- [ ] **`promotion.ranking-gates` — Match promotion ranking and gates.** Compare scores, custom weights, tie order, diversity, age, trust and visibility gates. Include exact score thresholds and promoted-entry visibility.
- [ ] **`promotion.apply-reconcile` — Match promotion application and reconciliation.** Compare MEMORY.md/DREAMS.md, markers, authoritative candidates and applied/rejected receipts. Interleave candidate changes and verify lock-time rechecks and publication order.
- [ ] **`promotion.deep-consolidation` — Match model-assisted consolidation.** Feed identical deterministic model plans for added, merged, superseded and rejected entries. Compare preimages, loss safeguards, history, origin changes and deterministic fallback.

### Dreaming phases

- [ ] **`dreaming.light` — Match the complete light phase.** Compare ingestion, freshness, ordering, deduplication, evidence grouping and selection. Compare live-source checks, staged-key state, phase signals and published artifacts.
- [ ] **`dreaming.rem` — Match the complete REM phase.** Compare narrative/evidence extraction and staged-key preference, consumption and freshness. Compare diary outputs, live-source checks and failure/publication semantics.
- [ ] **`dreaming.deep` — Match the complete deep phase.** Compare eligibility, consolidation invocation, fallback and phase composition. Compare phase ordering, source provenance and all resulting memory/recall state.
- [ ] **`dreaming.diary-provenance` — Match diary and phase publication.** Compare diary structure, coverage, evidence references, timestamps and artifact trust. Inject publisher failures and concurrent changes and compare locks and durable receipts.

### Forget and provenance

- [ ] **`forget.lineage-tombstones` — Match forget selection and tombstones.** Exercise dry-run and commit for direct, promoted, mixed-lineage and missing origins. Compare retained/deleted memory, lineage, tombstones and same-session replay admission.
- [ ] **`forget.index-fence` — Match forget/index revision fences.** Interleave forget with rebuild, search and promotion using the same source revisions. Prove a stale rebuild cannot republish forgotten entries, including after restart.

### Trust and redaction

- [ ] **`trust.secret-redaction` — Match secret redaction policies.** Compare literal registered secrets, structured credentials and model/tool/transcript policies. Compare bounded chunks, sanitization order and failure diagnostics without leaking live credentials.
- [ ] **`trust.configured-redaction` — Match configured patterns and trust transitions.** Compare supported JavaScript regex patterns, mode overrides and full-context walking. Compare owner/taint/provenance transitions at tool time and through stored session state.

### Heartbeat and automation

- [ ] **`heartbeat.scratch` — Match heartbeat monitor scratch state.** Compare read/write/unset/delete, size limits, tombstones and doctor migrations. Compare persisted state and diagnostics after reconstruction.
- [ ] **`heartbeat.turn-decisions` — Match heartbeat turn inputs and reply handling.** Compare skip/run decisions, prompt inputs, due tasks, NO_REPLY and HEARTBEAT_OK handling. Compare flush exclusion and removal from the session-memory corpus.
- [ ] **`automation.job-state` — Match memory-related automation state.** Compare schedule parsing, due decisions, run recording and migration outcomes under a fixed clock. Drive jobs explicitly; compare observable memory inputs and outputs without cloning an OS scheduler.

### Concurrency and recovery

- [ ] **`concurrency.workspace-locks` — Match workspace lock semantics.** Exercise simultaneous writers in separate processes, lock timeout, owner death and stale recovery. Compare exclusion, lease/reclaim behavior and absence of cross-workspace interference.
- [ ] **`recovery.repair-diagnostics` — Match audit and repair outcomes.** Corrupt recall stores, indexes, provenance and lock artifacts independently. Compare diagnostic codes, retained valid state and repair effects without silently resetting data.
- [ ] **`recovery.failure-publication` — Match interrupted operation recovery.** Interrupt write, index, flush, consolidation, forget and diary publication at defined boundaries. Compare next-open behavior, partial outcomes, unknown operations and retry policy.

### Cross-language boundaries

- [ ] **`engine.numeric-boundaries` — Match numeric boundary behavior.** Exercise coercion, non-finite numbers, negative zero, integer limits and exact score gates. Compare decisions and serialization; document any operation-specific tolerance without masking inclusion changes.
- [ ] **`engine.unicode-collation` — Match Unicode and collation behavior.** Exercise UTF-16 units, lone surrogates, case folding, segmentation and path ordering. Compare ordering and truncation for deterministic generated and named multilingual cases.
- [ ] **`engine.datetime-regex` — Match date/time and regex edge behavior.** Compare supported date parsing, offsets, DST boundaries, locale-independent clocks and regex options. Classify unsupported source behavior as a mismatch or uncovered requirement, never an implicit match.

### Host lifecycle acceptance

- [ ] **`host.turn-barrier` — Finalize memory before the next turn.** Drive a natural first-turn save and an immediate follow-up in both host paths. Compare committed and searchable memory, serialized maintenance and visible failure before next admission.
- [ ] **`host.restart-recall` — Recall across fresh chats and process restart.** Use the same saved corpus with a fresh session and then a fresh host process. Compare source-backed retrieval and state continuity with facts omitted from the new prompt.
- [ ] **`host.update-isolation` — Update current facts while preserving isolation.** Replace a prior preference, retain unrelated facts and query from independent user/workspace scopes. Compare current versus superseded answers and honest write/index failure reporting.

## 5. Completion evidence and release decision

The host acceptance entries above already include the end-to-end scenario: save a natural preference, ask an immediate follow-up, update the preference while retaining unrelated facts, open a fresh chat, restart the host and recall the updated fact from an actual source. Repeat isolation and failure cases. Do not turn these steps into new checklist items at closeout.

A full-equivalence release requires all of the following in the same declared baseline:

- Every required contract and acceptance point has executed differential cases.
- Every registered case matches the pinned reference; no mismatches, blocked cases, skipped cases, expected failures or uncovered required points remain.
- The report identifies the exact reference commit, source state, implementation and contract used.
- Failure, concurrency, restart and host lifecycle cases use real storage and orchestration, not fabricated successful receipts.
- Package regression, supported-Python, distribution and clean-consumer checks pass.
- A reviewer can reproduce the report from the documented commands.

Passing these conditions establishes equivalence for this declared memory contract and pinned release. It does not establish equivalence with later OpenClaw releases or with excluded platform services. A green smoke run, a historical matrix row or a count of Python unit tests cannot complete this checklist.

## Commands

Use a separate reference checkout. Runtime/package use of `memory-core` still needs neither Node nor an OpenClaw service; Node and the reference sources are comparison-test dependencies only.

Run the currently implemented differential cases explicitly:

```sh
python -m equivalence.dependencies \
  --reference /path/to/openclaw-v2026.9.9 \
  --destination .reference/npm --install

python scripts/check_equivalence.py \
  --reference /path/to/openclaw-v2026.9.9 \
  --node /path/to/node \
  --smoke \
  --report /path/to/equivalence-smoke.json
```

Run the strict full gate:

```sh
python scripts/check_equivalence.py \
  --reference /path/to/openclaw-v2026.9.9 \
  --node /path/to/node \
  --report /path/to/equivalence-full.json
```

The full gate is expected to remain non-passing while any acceptance point above is unimplemented or untested. Keep its report; do not disable requirements or add expected failures to make it green.


## Initial rebuilt baseline — 2026-11-07

Cleanup removed 14 obsolete plan/specification files (7,176 lines), the empty
historical worklist and its bookkeeping tests. Useful SDK, Lab, adapter and
behavioral regression code remains. Cleanup also removed automatic deletion of
the shared temporary OpenClaw lock directory. The removed material is recoverable
from Git history.

The new harness and adapters passed 36 offline guard tests. Retained regression
suites passed 1,927 tests; 1,625 historical oracle/live checks were skipped with
their opt-in gates disabled. Those skips are not equivalence evidence. Ruff,
project-name consistency and the diff check passed.

Actual Node 24.16.0 comparison against the pinned v2026.9.9 source executed
76 cases: **75 matched, 1 mismatched, 0 blocked**. The report records 12 imported
TypeScript source hashes and the Python implementation fingerprint. Both smoke
and full commands return exit code 1; the full contract additionally reports
**118 uncovered acceptance points**. A missing-reference probe returns blocked
with exit code 2. No paid provider call was made.

The observed difference is `mmr-empty-token-text`, within the existing
`retrieval.mmr` contract: with lambda 0, padded Cyrillic snippets that produce no
lexical tokens yield Python order `a,b,c` and OpenClaw order `a,c,b`. At that baseline it was retained as
a normal failing comparison, with input and both outputs, not an xfail. The
subsequent correction is recorded below; the initial failure is not erased.

Local generated artifacts are `.equivalence-results/full.json`,
`.equivalence-results/subset.json` and `.equivalence-results/missing-reference.json`.
They are ignored by Git and can be reproduced with the commands above. The new
CI workflow retains its own artifacts; a hosted run has not been established by
this local verification. Every behavioral checkbox remains pending review of its
complete acceptance conditions; registered subset coverage alone does not close it.

## Source inventory and MMR correction — 2026-11-07

The [source map](equivalence-source-map.md) now inventories all 64 contracts and
128 acceptance points against 103 tracked upstream modules. It records actual
code anchors, direct literal imports, exported declarations and current Python
counterparts. Its source-presence classifications are 10 present, 49 partial,
2 missing and 3 host-owned. These are source observations, not equivalence scores.
The validator checked the exact clean reference, hashes against Git and disk,
and every Python/upstream anchor. CI now runs that validation separately.

The original `mmr-empty-token-text` difference is corrected by applying the
existing ECMAScript `js_trim()` before lowercasing empty-token snippets. Ordinary
space, BOM and non-breaking space now follow the reference; NEL, U+001C and
zero-width space remain significant as JavaScript requires. The original case
remains in the suite. Eleven additional paired MMR cases and 17 direct ranking
regressions exercise whitespace boundaries, ties, disabled MMR and lambda values.

Current actual-source comparison: **87 matched, 0 mismatched, 0 blocked**. The
subset exits 0. The full command exits 1 with status `incomplete` because
**118 acceptance points remain uncovered**. Source mapping gives none of those
points behavioral credit. The focused inventory/harness/MMR checks passed
68 tests; retained regressions passed 1,944 tests with 1,625 historical oracle/live
checks skipped. Ruff, project-name consistency and the diff check passed.

The before-fix failure is retained locally in
`.equivalence-results/before-mmr-fix.json`; current reports are
`.equivalence-results/current-subset.json` and
`.equivalence-results/current-full.json`. Reports include the inventory digest
as traceability metadata. Hosted CI results are separate from these local checks.
No model/provider call was made.

## Default storage and index identity correction — 2026-11-07

This increment stays inside the existing storage/index contracts. It adds 21
default-root discovery fixtures, 6 read-path fixtures containing 55 requests,
and 79 index identity fixtures. They execute the original pinned native source
against isolated local files and stored-JSON/configuration inputs.

Discovery now includes root `USER.md`, sorts the whole memory tree by JavaScript
UTF-16 order, and reports operational scan failures instead of silently accepting
a partial scan. The original source snapshot mismatched 8 of the 21 discovery
fixtures; all 21 now agree. A successful curated `USER.md` write also rebuilds the Python
index before returning, and a fresh store can retrieve that published note.

Read-path probes compare absolute/relative paths, traversal, encoded names,
symlinks, hardlinks, FIFOs, missing files and invalid roots, and check that reads
leave the filesystem unchanged. The fixes retain native filesystem policy codes
and remove a phantom final line/continuation caused by a terminal newline. Two
historical assertions expecting that phantom content were corrected with direct
current-native evidence; the original failing fixture inputs remain in the suite.

The first strict identity comparison found 8 differences in stored-JSON numeric
coercion. Version checks now follow JavaScript conversion for hexadecimal,
binary/octal strings and arrays, and reject Python-only numeric spellings. All
79 identity cases now agree. The oracle verifies that the three identity imports
are unchanged direct reexports of the original host functions, then projects that
binding for the kernel comparison. Its report explicitly does not attest storage
facade initialization or full native manager/query dispatch.

Filesystem execution uses authenticated `@openclaw/fs-safe` 0.21.1, its exact
platform binary, and `p-map` 7.0.8. Setup alone downloads archives; every comparison
checks archive SHA512 values against the pinned upstream lockfile and all extracted
file bytes before/after execution. Package evidence is separate from committed
TypeScript hashes. Adapter hashes cover both native and Python halves of the run.
These test dependencies do not change the standalone Python SDK's runtime needs.

Current actual-source comparison: **193 matched, 0 mismatched, 0 blocked**. Only
`indexing.identity.outcomes` receives new acceptance coverage; the strict full gate
remains incomplete with **117 uncovered acceptance points**. The two storage
contracts deliberately receive no whole-contract credit: configured extra paths,
patterns/multimodal discovery, write admission and descriptor/concurrent path
checks remain unproved. Cache reuse, incremental refresh, coherent concurrent
publication and query-time synchronization remain pending in the existing list.

The final combined offline run passed **2,089 tests** (97 acceptance harness/adapter
guards and 1,992 retained/direct regressions). The 1,625 historical oracle/live
checks remained skipped with their opt-in gates disabled and supply no equivalence
credit. Ruff, project-name consistency, source inventory and staged diff checks
passed. The actual report records 65 executed tracked native source files and 639
authenticated dependency files; hosted CI remains a separate result.

Local reports are `.equivalence-results/storage-index-before.json`,
`.equivalence-results/storage-index-subset.json` and
`.equivalence-results/storage-index-full.json`. The first strict report preserves
the eight identity differences. Separate discovery/read baseline captures are
retained under `.equivalence-results/storage-discovery-before.json` and
`.equivalence-results/storage-read-*-before.*`. No model/provider call was made.
