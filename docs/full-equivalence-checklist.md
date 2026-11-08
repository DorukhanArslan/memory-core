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
113 upstream source modules, their tracked hashes, literal dependencies and exported
declarations. Source presence and inventory validation do not establish behavior or add
any differential-test coverage.

## 3. Rebuild the differential tests from a clean authority boundary

- [x] Keep the new comparison harness independent of `demo/`, old literal expectations and old parity status labels.
- [x] Import and execute the real pinned TypeScript functions. Authenticate official compiled runtime cases separately, retaining their source-build limitation. Do not copy the algorithm into an oracle stub or use Python output as the expected answer.
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

The latest verified baseline has **33/128 acceptance points (25.8%)**, with **95 points
(74.2%)** remaining. This includes both importance/project points from actual annotation/SQL
source comparisons and authenticated provider-none public stored searches. The existing
unicode61, printable-ASCII path-tie and portable CPU capability profiles remain explicit.
The integrated 946-case gate records 944 matches, two retained differences and zero blocked
cases. Final regression validation passed 3,037 tests.

| Contract status | Contracts | Verified acceptance points | Remaining acceptance points |
| --- | ---: | ---: | ---: |
| Complete | 15 | 30 | 0 |
| Partial | 3 | 3 | 3 |
| Pending verification | 46 | 0 | 92 |
| Total | 64 | 33 | 95 |

Pending verification does not mean no implementation exists. Partial contracts have outcomes
verified and boundaries still open: `indexing.identity`, `sessions.transcript-filtering` and
`flush.execute-finalize`. Infrastructure sections 1–3 have **20/22 tasks completed**; the two
remaining harness tasks cover identical driven inputs and complete observable outputs across
the entire fixed scope. Infrastructure counts do not add behavioral acceptance points.

After each completed batch, update these counts and provide the full completed, partial and
pending lists, the batch's target and actual acceptance increase, and any information needed
from the user. The latest implementation batch targeted **+2 points** and verified **+2**;
correcting stale checklist status adds **zero** acceptance points.

Current status of all 64 contracts:

- **Complete (15):** `lexical.tokenization`, `lexical.fts-query`, `lexical.bm25`, `chunking.markdown-boundaries`, `chunking.utf16-cjk-budget`, `indexing.incremental-sync`, `indexing.transaction-publication`, `retrieval.vector-scoring`, `retrieval.hybrid-scoring`, `retrieval.exact-path-priority`, `retrieval.mmr`, `retrieval.temporal-decay`, `retrieval.importance-project`, `prompt.bootstrap-budget`, `flush.trigger-usage`.
- **Partial (3):** `indexing.identity`, `sessions.transcript-filtering`, `flush.execute-finalize`.
- **Pending verification (46):** `storage.discovery`, `storage.path-safety`, `storage.atomic-writes`, `storage.workspace-isolation`, `chunking.entry-provenance`, `indexing.embedding-cache`, `indexing.query-sync`, `tools.search-contract`, `tools.get-contract`, `tools.deadline-cooldown`, `tools.unavailable-partial`, `sessions.corpus-admission`, `sessions.visibility-lineage`, `sessions.reset-hook`, `sessions.durable-context`, `prompt.bootstrap-discovery`, `prompt.runtime-context`, `prompt.history-repair`, `flush.plan-target`, `compaction.memory-budget`, `compaction.context-assembly`, `compaction.provider-overflow`, `promotion.recall-signals`, `promotion.ranking-gates`, `promotion.apply-reconcile`, `promotion.deep-consolidation`, `dreaming.light`, `dreaming.rem`, `dreaming.deep`, `dreaming.diary-provenance`, `forget.lineage-tombstones`, `forget.index-fence`, `trust.secret-redaction`, `trust.configured-redaction`, `heartbeat.scratch`, `heartbeat.turn-decisions`, `automation.job-state`, `concurrency.workspace-locks`, `recovery.repair-diagnostics`, `recovery.failure-publication`, `engine.numeric-boundaries`, `engine.unicode-collation`, `engine.datetime-regex`, `host.turn-barrier`, `host.restart-recall`, `host.update-isolation`.

### Storage and workspace

- [ ] **`storage.discovery` — Discover exactly the eligible memory files.** Compare roots, nested Markdown, case sensitivity, order, hidden artifacts and disappearing files. Exclude or admit symlinks and non-regular files exactly as the pinned reference does.
- [ ] **`storage.path-safety` — Enforce memory path and read boundaries.** Exercise absolute, relative, traversal, encoded and symlink paths. Compare rejected operations, result shapes and absence of unintended writes.
- [ ] **`storage.atomic-writes` — Publish writes atomically.** Compare append, replace, exclusive creation and concurrent rename outcomes. Inject write, flush, fsync and publication failures and inspect the surviving files.
- [ ] **`storage.workspace-isolation` — Keep workspace and subject state separate.** Reuse one host configuration across distinct workspaces and subjects. Prove files, indexes, recalls and maintenance state cannot cross the selected boundary.

### Lexical and chunking

- [x] **`lexical.tokenization` — Match lexical tokenization.** Compare exported token sets for empty, repeated, ASCII, mixed-script, CJK and Unicode boundary inputs. Use deterministic generated strings as well as named cases; preserve all observable tokens.
- [x] **`lexical.fts-query` — Match full-text query construction.** Compare query strings and no-query outcomes for punctuation, quotes, identifiers, whitespace and mixed scripts. Exercise deterministic generated inputs without reconstructing the reference algorithm in the oracle.
- [x] **`lexical.bm25` — Match BM25 rank conversion.** Compare positive, negative, zero and boundary ranks, including supported non-finite input representations. Report numerical differences rather than masking score-gate changes with a blanket tolerance.
- [x] **`chunking.markdown-boundaries` — Match Markdown chunk boundaries.** Compare ordered chunks, lines, overlap, empty content, headings and per-entry curated files. Read the original source through every returned line range.
- [x] **`chunking.utf16-cjk-budget` — Match UTF-16 and CJK chunk budgets.** Exercise surrogate pairs, malformed surrogates, CJK weighting and exact budget boundaries. Compare truncation and overlap without splitting valid pairs or changing source ranges.
- [ ] **`chunking.entry-provenance` — Retain chunk identity and provenance.** Compare chunk hashes, entry boundaries, source identities and provenance fields. Verify unchanged and changed inputs produce the reference identities and invalidation decisions.

### Index lifecycle

- [ ] **`indexing.identity` — Match index identity gating.** Vary provider, model, endpoint settings, scope, sources, tokenizer and chunking versions. Compare missing, matching and stale metadata diagnostics before any query is admitted.
- [x] **`indexing.incremental-sync` — Match index refresh and invalidation.** Create, update, rename and delete files and sessions while retaining an index. Compare discovery, chunk replacement and unchanged-file handling across reopen.
- [x] **`indexing.transaction-publication` — Publish one coherent index revision.** Interleave readers with successful and failing rebuilds. Compare visible old/new revisions and prevent partial chunk, FTS or provenance publication. Both acceptance points are covered by the prepared-publication comparisons recorded below.
- [ ] **`indexing.embedding-cache` — Match embedding reuse and invalidation.** Use a deterministic instrumented embedder to count query and document calls. Compare cache identity, batching, changed chunks, failed batches and retained entries.
- [ ] **`indexing.query-sync` — Match query-time synchronization.** Query an empty or stale index before and after source changes. Compare forced-sync/retry policy, unavailable outcomes and dispatch counts.

### Retrieval and ranking

- [x] **`retrieval.vector-scoring` — Match vector candidate scoring.** Compare cosine scoring, candidate bounds, zero vectors and incompatible dimensions. Compare ordered source/range identities before downstream hybrid ranking. Verified for the paired portable CPU fallback capability; optional accelerated KNN remains unverified.
- [x] **`retrieval.hybrid-scoring` — Match hybrid merge and score gates.** Compare vector-only, text-only, overlapping and disjoint candidates with configured weights. Check selection, minimum-score boundaries and lexical fallback without dropping result fields. Verified for finite complete payloads with printable-ASCII path ties; the Unicode path-order diagnostic remains uncredited and mismatched.
- [x] **`retrieval.exact-path-priority` — Match exact-path retrieval priority.** Exercise exact paths, basename matches, partial paths and body-only matches. Compare path specificity tiers, ties and interaction with content score. Verified under the paired unicode61 profile, including actual inherited merge/limit methods; universal ICU, trigram and full-manager behavior remain unverified.
- [x] **`retrieval.mmr` — Match diversity reranking.** Compare disabled/enabled MMR, duplicate text, equal scores, stable ties and lambda boundaries. Exercise CJK, empty and punctuation-only snippets and preserve output ordering.
- [x] **`retrieval.temporal-decay` — Match recency decay.** Compare enabled/disabled decay, half-life boundaries, future dates and missing timestamps. Compare dated versus evergreen memory paths and session activity timestamps under a fixed clock.
- [x] **`retrieval.importance-project` — Match importance and active-project ranking.** Exercise importance annotations, triggers and active/inactive project keys. Compare multipliers and their order relative to path tiers, decay and MMR.

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
- [x] **`prompt.bootstrap-budget` — Match bootstrap clipping and notices.** Exercise per-file, USER.md and aggregate UTF-16 limits and exact boundary values. Compare clipping, omitted files, warning modes and once-per-session state.
- [ ] **`prompt.runtime-context` — Match memory and runtime prompt composition.** Compare memory guidance, tools, runtime markers and fixed clock/timezone fragments. Compare insertion order and isolation of untrusted or recalled text.
- [ ] **`prompt.history-repair` — Match history windowing and tool repair.** Exercise missing results, duplicate or invalid calls, failed turns and provider replay metadata. Compare repaired model-visible messages while preserving the original durable transcript.

### Flush and compaction

- [ ] **`flush.plan-target` — Match flush plan and target selection.** Compare enabled/disabled configuration, model selection, timezone and daily target validation. Compare prompts, reserve terms and failure before a target can be safely prepared.
- [x] **`flush.trigger-usage` — Match flush trigger accounting.** Feed fresh/stale usage, missing usage, transcript byte limits and compaction counters. Compare trigger decisions, heartbeat exclusions and retry/exhaustion state.
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

python -m equivalence.release_runtime \
  --reference /path/to/openclaw-v2026.9.9 \
  --destination .reference/release-runtime --install

python scripts/check_equivalence.py \
  --reference /path/to/openclaw-v2026.9.9 \
  --node /path/to/node \
  --release-runtime .reference/release-runtime \
  --smoke \
  --report /path/to/equivalence-smoke.json
```

Run the strict full gate:

```sh
python scripts/check_equivalence.py \
  --reference /path/to/openclaw-v2026.9.9 \
  --node /path/to/node \
  --release-runtime .reference/release-runtime \
  --report /path/to/equivalence-full.json
```

The full gate is expected to remain non-passing while any acceptance point above is unimplemented or untested. Keep its report; do not disable requirements or add expected failures to make it green.

Both setup commands are explicit downloads with integrity verification. Normal comparison
runs authenticate the installed source dependencies and release artifacts without installing,
repairing or fetching anything. The official release's matching build-commit attestation does
not reproduce its source build; reports retain `sourceBuildReproduced: false`. Tracked
TypeScript sources and compiled release files/traces remain separate evidence sets.


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

## Persistent cache and selective index refresh — 2026-11-07

The existing `indexing.embedding-cache` and `indexing.incremental-sync` work now
has a persistent SQLite cache and selective source publication. A refresh still
discovers, reads and hashes sources. Matching sources retain their chunks;
changed/new sources are rebuilt, and renamed/deleted paths are removed in the
same transaction as chunk, FTS, path, source-state and metadata changes. Empty
files retain source state. `force=True` reparses all sources for explicit repair
and can still reuse valid document embeddings.

Cache identity includes provider, model, provider settings and chunk-content
hash. Binary64 encoding, alias precedence, invalid entries, batches of 400,
last-occurrence deduplication and capacity/age/rowid eviction follow the native
cache kernel. The store uses the native default cap of 50,000 entries. Complete
provider batches must have the expected count, finite nonempty vectors and one
compatible dimension before retention. Valid generated vectors can survive a
later index publication failure; source, provider and index generations are
checked before writes. An explicit retry recovers after incompatible dimensions
invalidate that cache identity.

Selected session forgets clear the unattributed cache, including vectors retained
before a failed index publication and rows added after a zero-count purge plan.
The purge advances the private generation in the same transaction, so older
refreshes cannot repopulate it. Dry runs and unresolved selections retain state;
a failed purge leaves the tombstone available for an explicit retry.

Cooperating SDK curated writes and refreshes share a reentrant process-local
workspace guard. A regression caught concurrent curated appends reporting an
avoidable source-change error after their writes had committed. The guard now
keeps each write and its refresh together, including separate store/curator
instances, without retrying provider calls. External writes, provider changes
and stale database generations still produce visible conflicts. This does not
establish native cross-process lock/lease equivalence.
The guard is scoped to the SDK's original synchronous refresh callback. Generic
curator hooks, and callers replacing that callback, retain their prior behavior;
four bounded worker-thread join regressions protect that integration boundary.

The same three-file Python lifecycle was measured against commit `9028ad2` and
the updated store with a deterministic instrumented embedder:

| Refresh | Previous document items | Current document items |
| --- | ---: | ---: |
| Initial index | 3 | 3 |
| No content changes | 3 | 0 |
| One file changed | 3 | 1 |
| Store reopened | 3 | 0 |
| File renamed, same content | 3 | 0 |
| One file deleted | 2 | 0 |

These are actual provider document-item counts, not startup-time estimates or
native manager equivalence evidence. Query embeddings still make one fresh call
per search in this fixture. Both runs made zero paid calls. The local accounting
artifacts are `.equivalence-results/index-call-accounting-before.json` and
`.equivalence-results/index-call-accounting-after.json`.

The fresh native suite adds 66 cache-kernel cases and 20 source-entry cases.
Actual cache SQL executes through the original Kysely/SQLite helpers, codecs and
cache implementation. Source snapshots execute original `buildFileEntry` across
CRLF, malformed UTF-8, unchanged time/size, rename/delete and nonregular paths.
Kysely 0.29.6 is authenticated against the same upstream lockfile; there are now
1,249 authenticated npm files. Verified direct reexport projections remain
explicitly limited to the named kernels and bypass broad facade initialization.

The full registered comparison has **279 matched, 0 mismatched, 0 blocked**.
The full acceptance gate still has **117 uncovered points**: these new kernel
cases deliberately have no full acceptance credit. Native provider dispatch,
retry/batch orchestration, complete session sync and concurrent publication still
require their existing lifecycle comparisons. No requirement was added or removed.
The source inventory now classifies 10 counterparts present, 50 partial, 1 missing
and 3 host-owned; those classifications are not parity results.

Current generated reports are `.equivalence-results/cache-incremental-subset.json`
and `.equivalence-results/cache-incremental-full.json`. Historical first captures
are retained separately; the cache kernel's first actual run matched, so no
pre-port mismatch count is claimed for it.

The final combined offline run passed **2,216 tests**: 122 acceptance
harness/adapter guards and 2,094 direct/retained regressions. The 1,625 historical
oracle/live checks remained skipped with their opt-in gates disabled and provide
no equivalence credit. Concurrent SDK append and two-store barrier checks also
passed eight repeated runs each. The timeout guard now counts reference process
launches, preserving its no-retry assertion even when a busy runner expires the
deadline before the child writes its first marker. Ruff, project-name consistency,
source inventory and staged diff checks passed. No paid provider call was made;
hosted CI remains a separate result.

## Prepared publication and manager lifecycle — 2026-11-07

The Python store now uses one prepared-index publication owner for ordinary refreshes and
explicit prepared revisions. A revision carries source rows, chunk identifiers, vectors,
hashes, models, update times, recall annotations and provenance. Publication replaces the
selected state in one transaction while preserving unrelated metadata and the embedding
cache. Empty sources retain source state. Stale generations and failed publication remain
visible failures rather than successful receipts.

The 17 new prepared-publication cases execute the actual pinned
`publishMemoryDatabaseTables` owner and the original schema/SQLite-worker SDK facades.
**All 17 match.** Independent SQLite connections observe old state until commit; a held
reader retains its old snapshot after commit. Cases compare successful and empty replacement,
same-row publication, stale revision rejection, failures at begin/source/chunk/details/recall/
provenance/commit boundaries, a post-commit failure, orphan metadata replacement/rollback,
and reopened state. Comparisons retain every source, chunk, FTS, path, detail, recall and
provenance row, raw metadata, body/path query results, live cache contents and attachment
release observations. Controlled prepared chunk IDs are shared, not normalized away.

Native per-row revision counters and Python's private publication generation have different
internal counts. These cases compare revision advancement and stale-generation rejection,
not absolute counter values. Injected failures retain their exact stage. A failure after
COMMIT is classified by that boundary: native handle fencing can replace its final private
diagnostic during cleanup, but durable new state, the old held-reader snapshot and reopening
are still compared in full. No rollback is invented and unexpected errors retain their
actual class/message. These rules are recorded in each case's `normalizationPolicy`.

Both `indexing.transaction-publication` acceptance points are now covered. This does not
complete the separate `recovery.failure-publication` contract, which also includes writes,
flush, consolidation, forget and diary operations.

| Fixed acceptance coverage | Covered | Remaining | Progress |
| --- | ---: | ---: | ---: |
| Previous batch | 11 / 128 | 117 | 8.6% |
| Verified prepared publication | 13 / 128 | 115 | 10.2% |
| Verified publication and manager lifecycle | 15 / 128 | 113 | 11.7% |

The registered catalog now contains **302 cases**: 279 previous cases, 17 prepared-publication
cases and 6 manager lifecycle cases. The first 296 execute tracked TypeScript; the last 6
execute the authenticated official compiled v2026.9.9 manager and its workers with provider
mode `none`. The source checkout and compiled runtime are separately authenticated, and
reports distinguish `trackedTypeScriptCaseIds` from `compiledReleaseCaseIds`. Matching release
version/build-commit metadata is publisher attestation; the source build has not been
independently reproduced (`sourceBuildReproduced: false`).

The lifecycle fixtures cover memory create/update/rename/delete/reopen, unchanged inputs,
content changes with unchanged size/time, empty and whitespace sources, recognized memory
provenance, session create/append/rename/delete/reopen, and chunk-write failure followed by an
explicit retry. They drive existing dirty/reconciliation notifications directly. Session
rename uses the actual public host operations: read stored messages, delete the old identity,
create the new identity and append messages in order. Existing startup-catchup admission
then feeds one complete native sync. OS watcher scheduling and binary transcript interchange
are outside that driver. All six cases match across 28 observed refresh boundaries, completing
both `indexing.incremental-sync` acceptance points.

Lifecycle normalization retains actual chunk IDs, public paths, source mtimes, all semantic
rows and the complete `memory_index_meta_v1` identity. Execution-clock write times compare
new/retained/rewritten relationships. SQLite session revision prefixes compare their complete
SessionEntry snapshot hash and retention behavior. Session transport byte counts compare
zero/nonzero, retention and change direction because the hosts use different private
transcript encodings; memory-file byte counts remain exact. Raw absolute states and all host
metadata keys are retained separately in `runtimeDiagnostics` so those differences remain
inspectable. Each case records these policies explicitly.

Runtime cases use owned state/log directories and a fresh process per case. The controlled
preload is inherited by workers, denies network fetches and records loaded artifact traces;
no model or embedding-provider request is part of these fixtures. The owned host config uses
`session.maintenance.mode: warn` so unrelated age-based pruning cannot remove the fixed-clock
fixtures; automated maintenance remains a separate contract. Archive and installed-file
integrity checks run before and after comparisons. The runtime authenticates 48 archives and
21,737 files. No paid provider call was made.

Native query-time synchronization is the next existing contract, `indexing.query-sync`.
Provider dispatch/retry/batch orchestration, automatic watcher scheduling and the other
unchecked contracts remain separate work. The contract still contains exactly **64 contracts
and 128 acceptance points**; catalog growth adds evidence, not requirements.

The combined comparison passed **302 matched, 0 mismatched, 0 blocked**. Coverage is
**15/128 (11.7%)**, with **113 acceptance points (88.3%) remaining**; this measures verified
acceptance coverage, not development effort. Reports are retained at
`.equivalence-results/index-publication-lifecycle-subset.json` and
`.equivalence-results/index-publication-lifecycle-full.json`. The first integrated capture,
`index-publication-lifecycle-first.json`, was blocked by runtime evidence validation during
adapter integration and is retained without parity credit.

The complete offline regression run passed **2,417 tests**, with the same 1,625 historical
oracle/live checks gated off and granting no acceptance credit. Ruff, project-name consistency,
source inventory and staged diff checks passed. The source inventory now records 11 present,
49 partial, 1 missing and 3 host-owned counterparts; those are source classifications. The
earlier 279-case and 2,216-test figures above describe the previous batch only.

Review also found and fixed two integration errors: prepared chunks now consult the optional
host artifact-provenance ledger rather than upgrading recorded untrusted files; and a search
rechecks its captured provider identity inside the reader transaction before using its query
vector. Regression tests exercise an actual observed untrusted write across content changes
and reopen, and a model change/reindex immediately before opening the reader. Metadata-only
trust transitions still require explicit repair and remain separate from automatic trust
synchronization.


### 2026-11-08: reuse existing fixtures against pinned native owners

This batch reuses inputs from retained Markdown, UTF-16/CJK, bootstrap, flush and session
fixtures. Those tests already exercise substantial Python implementations. Their existing
inputs remain useful even when an older oracle targeted v2026.9.6; this batch obtains new
outputs from the unchanged v2026.9.9 source and the current production Python functions.
It imports neither historical expected outputs nor historical oracle implementations.
An unchecked acceptance point measures missing verified contract evidence, not a missing
implementation or a unit of development effort.

The chunking comparison reuses the 13 legacy Markdown cases and the existing line-range
fixture, then adds exact budget, CJK, surrogate, whitespace, curated-entry and helper cases.
It compares ordered text, native content hashes, overlap, entry spans and the UTF-16 units
of original source lines. The raw Python chunker now preserves native whitespace chunks;
`SQLiteMemoryStore._prepare_source_chunks` retains the index owner's separate whitespace
filter. Other observed differences required JavaScript heading-whitespace semantics, valid
literal-surrogate-pair weighting and safe UTF-16 truncation; overlap and entry spans
were verified without replacing their algorithms. The first 54-case report
matched 44 and mismatched 10; the first six helper cases matched three and mismatched three.
The final chunk/helper comparison matches all **60 cases**, completing both acceptance
points of `chunking.markdown-boundaries` and `chunking.utf16-cjk-budget`. This does not close
`chunking.entry-provenance`.

The bootstrap comparison reuses the existing clipping probe, policy digest, missing marker,
path matching and USER.md budget inputs, with exact limits, UTF-16 and warning-transition
cases. It executes native clipping, injection statistics, budget analysis and notices.
The first executable comparison matched 73 of 77 cases and exposed four personal USER.md
differences. The Python file records now preserve the host-supplied `personal_user` flag
and apply its native no-clipping policy. All **77 cases** now match, completing both
`prompt.bootstrap-budget` acceptance points. Authenticated personal-overlay discovery
remains separate from this supplied-input budget comparison.

| Fixed acceptance coverage | Covered | Remaining | Progress |
| --- | ---: | ---: | ---: |
| Previous publication and lifecycle batch | 15 / 128 | 113 | 11.7% |
| Verified chunking and bootstrap reuse | 21 / 128 | 107 | 16.4% |

The six newly covered points leave **107/128 (83.6%)** unverified. Source-presence
classifications remain 11 present, 49 partial, one missing and three host-owned. Neither
those classifications nor passing legacy unit tests grant additional acceptance credit.
Flush and session projection adapters compare bounded function surfaces; their broader
contracts remain unchecked unless complete acceptance evidence is established separately.

Retained comparisons are `.equivalence-results/markdown-chunking-first.json`,
`markdown-chunking-helpers-first.json`, `markdown-chunking-with-helpers-after-native-fixes.json`,
`bootstrap-budget-before-fix-3.json` and `bootstrap-budget-final.json`. Earlier blocked
bootstrap setup captures remain available without parity credit. The combined registered
catalog now has **463 cases**: 302 previous, 60 chunk/helper, 77 bootstrap-budget,
18 fresh-usage/error and six session-reset probes. The integrated subset comparison
matched all 463 with zero mismatches or blocked cases. The last two groups receive no
complete flush/session acceptance credit. The full regression run passed **2,465 tests**; the same 1,625 historical oracle/live
checks remained gated off and grant no acceptance credit. Ruff, project-name consistency,
source inventory and staged diff checks passed.

The new adapters call original tracked source owners through narrowly verified original
reexports. [reuse_bindings.py](../equivalence/reuse_bindings.py) authenticates declaration
bindings and source hashes while bypassing broad facade initialization; these projections
make no claim about full host orchestration. Additional package artifacts are pinned by the
reference source metadata and use the verified local cache, without adding dependencies to
the Python SDK. The scope remains exactly **64 contracts and 128 acceptance points**; its
scope digest and the inventory's 103 upstream modules are unchanged.


### Initial broad source probes — 2026-11-08 (superseded)

At the initial fixture-reuse baseline, the prospective builders preserved the complete
111 flush and 79 session fixtures, but the 166 additional cases were import-blocked.
The broad probes encountered `acorn` for 62 plan cases, `mdast-util-from-markdown`
for eight target and 73 session cases, and `partial-json` for 23 gate/threshold cases.
Those captures established no implementation mismatches or acceptance coverage. At
that baseline, source-only setup authenticated 34 packages against the pinned lockfile.
The import blockers were subsequently resolved by the source setup below; they are
historical diagnostics, not current blocked cases.

The retained baseline reports are `.equivalence-results/reused-fixtures-subset-first.json`
(**463 matched, zero mismatched or blocked**),
`.equivalence-results/reused-fixtures-prospective.json` (**166 import-blocked**) and
`.equivalence-results/reused-fixtures-full.json` (**107 uncovered acceptance points**).
They describe that earlier baseline and remain available without rewriting their results.

### Flush and session source completion — 2026-11-08

The complete retained flush and session matrices now execute against the original pinned
native source owners. The focused reports record **111 flush matches** and **79 session
matches**, each with zero mismatches or blocked cases. This adds executable comparisons
for all 166 formerly import-blocked fixtures: 93 flush and 73 session cases beyond the
24 probes in the previous registered catalog. No production Python change was required.
The default catalog contains **629 cases** (463 previous plus 166). The integrated
subset comparison matched all 629 with zero mismatches or blocked cases.

The flush cases compare complete plans and prompts, model/configuration coercion, reserve
terms, byte-size parsing, timezone and clock fallback, target validation and surviving file
contents, exported token/compaction gates, and error text/cause chains. All 111 retain
`covers: []`. Plan evidence does not settle dates below year 1000 or above 9999 and the
documented host time-format/timezone boundaries. Python target preparation still has
stricter filesystem admission. At this baseline, native `assertCurrent` authority revocation
was untested; the later bounded comparison below addresses its three helper checkpoints.
Exported gates do not establish actual transcript/provider usage accounting, heartbeat
exclusions, durable retry/exhaustion stamps or execution/finalization. All existing flush
acceptance points remain open.

The 73 complete session JSONL projections compare ordered text, full hashes, raw source
ordinals and line maps, timestamps, provenance, session flags, observed messages and prefix
hash checks. Inputs include tree/side-branch rows in physical file order, tool rows,
heartbeat and recalled-content markers, failed/mirrored messages and malformed rows.
These comparisons cover **`sessions.transcript-filtering.outcomes`**. Six standalone reset
helpers retain `covers: []`. Raw JSONL projection does not verify live SQLite branch
selection, integrated reset-cutoff propagation, archive codecs/materialization or corpus
admission; `sessions.transcript-filtering.boundaries` and the containing contract stay open.
Plain reset/deleted archive filenames in the fixtures do not establish those integrations.

| Fixed acceptance coverage | Covered | Remaining | Progress |
| --- | ---: | ---: | ---: |
| Previous chunking and bootstrap batch | 21 / 128 | 107 | 16.4% |
| Verified session projection outcomes | 22 / 128 | 106 | 17.2% |

The remaining **106/128 points (82.8%)** measure unverified acceptance conditions, not
missing implementations or development effort. The fixed scope remains **64 contracts and
128 acceptance points** with the same scope digest and 103 mapped upstream modules. Source
classifications remain 11 present, 49 partial, one missing and three host-owned.

Source-only setup now authenticates **90 packages and 8,762 installed files**. Every archive
is checked against the exact pinned Git lockfile SRI. `@openclaw/proxyline` 0.3.12 also uses
the original committed `patches/@openclaw__proxyline@0.3.12.patch`: setup checks its Git bytes,
lockfile patch hash and SHA-256, applies only those literal hunks, and records patch evidence
separately from archive integrity. No package lifecycle script runs. These packages belong
to the test authority and add no dependency to the Python SDK.

Workspace imports resolve through static aliases in the original tracked `tsconfig.json`
and checked package exports. Reports retain the configuration SHA-256 alongside loaded
source hashes. Broad flush/session owners execute their source dependency graph; the older
narrowly verified chunking/bootstrap reexport projections retain their declared boundaries.
Reference source is unchanged. Comparisons use owned state/log directories, deny network
fetches and make no paid provider calls.

Current focused reports are `.equivalence-results/flush-completion-registered.json` and
`.equivalence-results/session-completion-05-registered.json`. Their full-gate status remains
incomplete wherever fixed acceptance points are uncovered; a passing focused comparison
cannot complete the full contract. First failures and import-blocked captures remain
historical artifacts. All retained fixtures now run by default; `--include-prospective`
remains an accepted, idempotent compatibility option and adds no duplicate cases.


Integrated results are retained at `.equivalence-results/completed-fixtures-subset-first.json`
(**629 matched, zero mismatched or blocked**). The committed full-gate report is
`.equivalence-results/completed-fixtures-full.json`; it retains **106 uncovered acceptance
points**, so this remains partial verification of the fixed contract. The final regression
run passed **2,490 tests**; the same 1,625 historical oracle/live checks remained gated off
and grant no acceptance credit. Ruff, project-name consistency, source-map and staged diff
checks passed. No production Python implementation changed in this completion batch.

### Flush target authority and cancellation — 2026-11-08

The public `ensure_memory_flush_target_file(..., *, assert_current=None)` now matches the native
helper's optional raising authority checkpoints before mkdir, after mkdir and after open. It
closes the real descriptor in `finally`, including when the last check raises. A callback is
synchronous and prompt; its return value is ignored. Omitting it retains legacy behavior. The
existing stricter refusal of symlinked parents and symlink, hard-linked or non-regular targets
remains explicit.

The new `flush-target` operation adds **22 cases**, bringing the default catalog to **651**
(629 previous plus 22). `.equivalence-results/flush-target-first.json` retains the original
**22 mismatches** from the helper without callback support. The intermediate
`.equivalence-results/flush-target-after-helper.json` records **21 matches and one mismatch**:
failure injection below `Path.mkdir` let `exist_ok` absorb the artificial failure for an existing
directory. The transport now injects at the corresponding `Path.mkdir` and native
`fs.promises.mkdir` API boundaries. No case was removed. The final focused report,
`.equivalence-results/flush-target-final.json`, records **22 matches, zero mismatches or blocked
cases**. Earlier captures remain diagnostic evidence.

These fixtures execute both real helpers and compare ordered callback and filesystem events,
surviving directories, exact file bytes (including non-UTF-8 bytes), and actual descriptor
closure. They cover revocation at each checkpoint for new and existing targets, actual
`asyncio.CancelledError`, invalid paths, and declared mkdir/open/close failures. Close-failure
injection occurs after releasing the real handle. Normalization is limited to declared injected
authority errors, the two path-validation messages, injected errno/operation/owned path fields,
and owned temporary roots in unexpected-error diagnostics.

`HostKit.after_turn` and `request_flush` carry the optional check through request creation,
dispatch and completion. During preparation, both host methods preserve the original authority
exception if descriptor cleanup also fails, chain the close failure as its cause and record no
cancellation strike. The standalone target helper retains native close-error priority. The shared
append checks authority under the actual file lock and
again before provenance reservation, open and write, including after provenance callbacks.
Cancellation while waiting for the lock or after reserving provenance prevents an append and
preserves rollback. Precommit authority exception identity survives, including cancellation;
rollback failures remain chained causes. After an append commits, ordinary authority/index
exceptions return `appended` plus `afterWriteError`, so the host keeps the write without retry.
`BaseException` cancellation propagates while retaining committed bytes and the request entry.
Completion rejects an active dispatch, closes the request before its callback, and records no
success or failure stamp if that callback raises. Python regression tests exercise these host
boundaries; the native comparison is bounded to target preparation.

All new cases retain **`covers: []`**. This batch does not close either `flush.plan-target`
acceptance point or establish host queue ordering, a durable next-turn barrier, usage accounting
or full execution/finalization equivalence. Verified acceptance remains **22/128 (17.2%)**,
with **106/128 (82.8%)** remaining. Scope remains **64 contracts, 128 acceptance points**, the
same scope digest and **103 mapped upstream modules**.

The integrated subset report, `.equivalence-results/flush-authority-subset-first.json`, matched
all **651 cases**, with zero mismatches or blocked cases. The committed full-gate report,
`.equivalence-results/flush-authority-full.json`, remains **incomplete** because the same
**106 acceptance points** remain uncovered. The full regression run passed **2,571 tests**;
the same **1,625 historical oracle/live checks** remain gated off and grant no acceptance
credit. Ruff, project-name consistency, source-map and staged diff checks passed.

### Runtime flush accounting and retry state — 2026-11-08

This batch completes **`flush.trigger-usage.outcomes`** and
**`flush.trigger-usage.boundaries`**. Verified acceptance advances from **22/128 (17.2%)** to
**24/128 (18.8%)**, leaving **104/128 points (81.2%)** unverified. The fixed scope remains
**64 contracts and 128 acceptance points**, scope SHA-256
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`, and **103 mapped upstream
modules**. Source classifications are now 12 present, 48 partial, one missing and three host-owned.

The reference executes the official compiled `runMemoryFlushIfNeeded`, authenticated separately
from tracked TypeScript source. Reports retain reviewed source-owner and compiled-export hashes,
release archive/file authentication, loaded release files and runtime traces. The publisher's
version/build-commit attestation is not an independently reproduced source build:
**`sourceBuildReproduced: false`**. Runtime dependencies authenticate **65 packages and 23,917
installed files**. The actual memory plugin resolves the initial plan; a declared infrastructure
failure on its second plan resolution occurs only after the real runtime gate admits an attempt.
This exercises accounting, admission and failure/exhaustion persistence without reaching a model.

The **55 new runtime cases** bring the default catalog from 651 to **706**. They compare fresh,
stale, missing and versioned usage; provider context/cache components; projected trailing user
and tool messages; output-read proximity boundaries; reset/compaction/CLI/unavailable-context
barriers and the 512-event tail; actual active-transcript UTF-8 byte limits; disabled configuration;
heartbeat, CLI, read-only and incognito exclusions; compaction-cycle suppression; and repeated
preparation failures through exhaustion and the next cycle. Native transcripts and failure stamps
use the actual SQLite session accessor. The Python driver calls public `HostKit.prepare_flush`,
persists returned `SessionState` as JSON and reconstructs it between attempts. Incognito state
remains process-local in both drivers.

`.equivalence-results/flush-runtime-first.json` retains **52 matches and two mismatches** across
the initial 54 cases. Both differences were transport issues: the CLI fixture needed the native
provider registry, and reset byte accounting needed the public active-context window rather than
all physical event rows. Neither required another production change. The corrected two cases and
an added reset-discarded-byte-force boundary all match in
`.equivalence-results/flush-runtime-boundaries.json` (**three matches, zero mismatches or blocked
cases**). The original 52 passing cases remain. Earlier reports are retained without rewriting
their results.

The paired diagnostic `.equivalence-results/flush-runtime-legacy-paired.json` executes the actual
old public `after_turn` at commit `f884f5701e276ee8a0b551a6ae23af70a536a518` alongside the observed
native runtime. With a fresh prompt total of 175,999 and completion of one, the old path admitted
a flush; native maintenance with an empty estimate skipped it. The current path uses a fresh
maintenance total directly. Stale/missing usage recovers a reliable transcript snapshot and
projected trailing messages; a nonblank next prompt reads fresh transcript output only at the
positive threshold's 8,192-token proximity boundary. Recovered prompt totals do not reduce an
existing fresh snapshot. The [host guide](host_kit.md) documents the persisted-state entry point
and required transcript/byte snapshot.

Comparison preserves owned accounting, compaction and flush fields, including absent fields,
attempt admission, outcomes, persisted state and actual transcript bytes. Host storage metadata
and native visible-error rendering are outside this trigger-accounting comparison; raw evidence
remains separate. These cases grant no `flush.execute-finalize`, model/tool write, host queue,
durable next-turn barrier or general storage equivalence credit. Both `flush.plan-target` points
also remain open.

The committed full-gate report, `.equivalence-results/flush-runtime-full.json`, records **706
matches, zero mismatches and zero blocked cases**. It retains the **104 uncovered acceptance
points**, so the full contract remains incomplete. Full regression validation passed **2,641
tests**; the same **1,625 historical oracle/live checks** remain gated off and grant no acceptance
credit. Old Lab and LangGraph assertions that added completion tokens to a fresh maintenance
snapshot were corrected against the observed native behavior. Ruff, project-name consistency,
source-map and staged diff checks passed.

### Flush execution and finalization — 2026-11-08

This batch completes **`flush.execute-finalize.outcomes`** only. Verified acceptance advances to
**25/128 (19.5%)**, leaving **103 points (80.5%)** unverified. The boundaries point remains open,
so the containing `flush.execute-finalize` checkbox stays unchecked. Source classifications
remain 12 present, 48 partial, one missing and three host-owned. The inventory maps **105 upstream
modules**, adding the actual maintenance-followup and internal-session-identity owners. The fixed
**64 contracts, 128 acceptance points** and scope SHA-256
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9` remain unchanged.

The reference executes the authenticated official model/tool loop through the native provider
plugin contract. A labelled scripted provider emits the declared replies; actual native session,
append, provenance, indexing and finalization owners run. Reviewed source-owner identities remain
separate from compiled artifact identities, and **`sourceBuildReproduced: false`** remains explicit.
The authenticated release runtime uses **83 packages and 24,707 installed files**. The Python
candidate calls public SDK APIs directly and does not delegate its implementation to Node.

The **15 new execution cases** bring the default catalog to **721**. Fourteen reviewed cases
cover the outcomes point: exact content and conditional separators, empty/whitespace and literal
`NO_REPLY` writes, sequential tool rounds, read-before-append, recovered tool errors, model errors
after writes, captured compaction cycles, cancellation before/after writes, failure exhaustion,
automatic-maintenance trust and quarantine after an external edit. Resolved model payloads drive
completion; source-session stamps remain separate from internal execution/provenance identities.
Automatic `prepare_flush`/`after_turn` maintenance is always an `untrusted` writer because native
maintenance clears sender ownership. The labelled forced `request_flush` extension keeps its
caller's trust policy; the saved-session hook keeps source-origin and source-session provenance.

The first trusted report, `.equivalence-results/flush-execution-first.json`, retains **13 matches,
two mismatches and zero blocked cases**. The recovered-tool-error case exposed one SDK difference:
its tool message had `isError: False` where the complete native loop supplied `True`. The minimal
receipt fix preserves the recoverable error and allows the later model reply to succeed. The
actual corrected comparison, `.equivalence-results/flush-execution-tool-error-final.json`, records
**one match, zero mismatches or blocked cases**. The other 13 passing cases remain unchanged;
focused regression validation passed **126 tests**.

The remaining warm-index case stays registered with **`covers: []`** and an explicit
`declaredDeviation`; it is not an expected-failure substitution or input normalization. In the
trusted first report, the SDK's first query returned one hit while native returned none. The
separate `.equivalence-results/flush-execution-warm-diagnostic.json` previously observed an older
native snippet (`obsoletekiwi\n`) while the SDK returned the updated content
(`obsoletekiwi\nfreshmangosteen`). Native recall after synchronization agrees. These captures
show a real first-recall generation boundary, not a guarantee that native always returns stale
content. Timing may let a later run match; that cannot close
**`flush.execute-finalize.boundaries`** or establish a host queue/durable next-turn barrier.

The committed full-gate report, `.equivalence-results/flush-execution-full.json`, includes all
**721 cases** and retains **103 uncovered acceptance points**. Its actual warm comparison remains
visible and grants no acceptance credit; a full-equivalence pass remains unavailable. Full
regression validation passed **2,727 tests**; the same **1,625 historical oracle/live checks**
remain gated off and grant no acceptance credit. Ruff, project-name consistency, source-map and
staged diff checks passed.

### Portable CPU vector candidates — 2026-11-08

This batch completes **`retrieval.vector-scoring.outcomes`** and
**`retrieval.vector-scoring.boundaries`** for the explicitly paired portable CPU capability:
native optional vector acceleration is unavailable/disabled, and the SDK uses its CPU backend.
Verified acceptance advances from 25/128 to **27/128 (21.1%)**, leaving **101 points (78.9%)**
unverified. This does not implement or verify optional sqlite-vec KNN, float32 accelerated
distance behavior or full memory-manager execution. The fixed **64 contracts, 128 acceptance
points** and scope SHA-256
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9` remain unchanged. The
inventory now maps **107 upstream modules**; classifications are 13 present, 47 partial,
one missing and three host-owned.

The actual old SDK cosine at commit `b3dbfc5ad4d62aab0303c7803104c1b60679e0d2` returned zero
for `[1, 0]` versus `[1]`, while the actual native helper returned one. The retained
`.equivalence-results/vector-prefix-baseline.json` records that difference without acceptance
credit. Cosine now uses the shared minimum-length prefix for both norms, including empty and
zero-vector behavior. Corrupt or non-finite stored vectors decode as empty; non-finite candidate
scores are excluded.

Public `SQLiteMemoryStore.search_vector_candidates` returns raw ordered candidates before
hybrid ranking. It filters actual per-chunk model identity, truthy aliases and sources before
bounding candidates; scans signed SQLite rowids in batches of 256; and retains stable descending
finite top-K scores, with ties in rowid order. Payload hydration shares each batch's snapshot.
Bounded snippet projection respects the database encoding and final UTF-16 truncation. Normal
public search retains its all-zero query guard, identity check, whole-generation read transaction
and later path ordering. Lower-level callers that supply a connection retain their transaction
ownership; autocommit batch snapshots finish before the cooperative yield.

The reference executes the unchanged original SQLite scan, binary64 codec/cosine and row
projection owners. [vector_bindings.py](../equivalence/vector_bindings.py) authenticates exact
named bindings and source hashes while bypassing broad facade initialization. Reports explicitly
exclude accelerated KNN and full-manager execution. The **40 new cases** include incompatible
lengths, zero/non-finite values, model/source filtering, candidate limits/ties, signed rowid batch
boundaries, Unicode/NUL snippets and SQLite encodings, cancellation, batch mutation and an actual
external WAL writer during scoring. Cancellation diagnostics retain no acceptance credit.

The first actual comparison, `.equivalence-results/vector-scoring-first.json`, records **40
matches, zero mismatches and zero blocked cases** with `covers: []` before registration. After
reviewed point assignment, `.equivalence-results/vector-scoring-registered.json` also records
**40 matches, zero mismatches and zero blocked cases**. Compared outputs are unrounded; reports
retain exact inputs, capability profile, status and loaded-file evidence. Matched outputs are not
duplicated per row; mismatch outputs remain available when a comparison differs.

The committed full-gate report, `.equivalence-results/vector-scoring-full.json`, executes all
**761 cases** against implementation commit `bc7a83ea4421def784bcbbd9c81678b89b57ec80` with a
clean tracked tree. It records **760 matches, one mismatch and zero blocked cases**. The sole
difference is the existing `flush-execution-warm-index-first-recall` comparison; it remains
registered, visible and uncredited. `flush.execute-finalize.boundaries` stays open even if a
later timing-dependent run matches. The full gate therefore reports `mismatched`, not a
full-equivalence pass, and still has **101 uncovered acceptance points**. All 40 vector cases
match; both declared CPU vector points are covered. No provider credentials were forwarded and
no paid provider calls were made.

Full regression validation passed **2,781 tests** in 131.77 seconds. The same **1,625 historical
oracle/live checks** remain skipped and grant no acceptance credit. Ruff, project-name
consistency, source-map validation and staged diff checks passed. These results are recorded in
this documentation-only follow-up; implementation, adapters and source inventory are unchanged.

### Hybrid merge and score gates — 2026-11-08

This batch targets and verifies **+2 points**: **`retrieval.hybrid-scoring.outcomes`** and
**`retrieval.hybrid-scoring.boundaries`**. Current acceptance is **29/128 (22.7%)**, with **99
points (77.3%)** remaining: **13 complete, three partial and 48 pending contracts**. The fixed
64-contract/128-point scope and its SHA-256 remain unchanged. Source inventory now maps **108
upstream modules**, including the actual curated-annotations constant owner; classifications
are 14 present, 47 partial, zero missing and three host-owned. Importance/project has a new partial
source counterpart but receives no separate acceptance credit.

The declared profile compares finite complete result payloads with printable-ASCII path ties.
Unicode content is compared exactly. The original native hybrid, importance, project-ranking,
decay, MMR and selection owners execute; an authenticated exact named binding resolves
`INVALID_PROJECT_ANNOTATION_KEY` to its unchanged source owner without broad storage-facade
initialization. No full-manager, annotation-storage pipeline or optional KNN equivalence is
claimed. Cases cover vector/text overlap, weights, score thresholds and lexical fallback while
retaining source/range identities, importance, triggers, project keys and provenance, including
absent-versus-null fields. Required modifiers and timestamp plumbing add no separate importance,
temporal or engine acceptance points.

The actual old annotated API failed with `TypeError` at commit
`a2084cd7d06f7775a2c160e59de59d9cb5506aeb`;
`.equivalence-results/hybrid-annotated-baseline.json` retains that observation. The first native
comparison, `.equivalence-results/hybrid-scoring-first.json`, records **64 matches, two mismatches
and zero blocked cases**. One mismatch exposed a one-ULP decay difference; the other was real
Unicode path ordering. `.equivalence-results/hybrid-decay-gate-before-fix.json` retains a decisive
selector case where that numeric difference changes inclusion at the minimum-score gate.

Indexed `memory_source_mtimes` are now authoritative, including an explicitly empty map, and
timestamps follow numeric Date TimeClip. A private `_js_exp.py` translates V8/fdlibm binary64
exponential behavior from immutable Node commit `c7d10158bc31036de6783d66beaaaf551e3167aa`, retaining
the full Sun and V8 BSD notices. It adds no production Node runtime or package dependency.
`.equivalence-results/hybrid-exp-source-provenance.json` records source/license provenance;
`.equivalence-results/hybrid-exp-bits.json` records **11,503/11,503** helper bit matches, with
an independent **2,263-case** comparison also bit-exact. Those diagnostics grant no engine credit.

The actual corrected report, `.equivalence-results/hybrid-scoring-after-exp.json`, records
**66 hybrid matches**, **one known Unicode diagnostic mismatch**, zero blocked cases and no runner
errors. Outputs remain unrounded and complete; no blanket numeric tolerance hides a gate change.
After reviewed point assignment, `.equivalence-results/hybrid-scoring-registered.json` records
the same **66 hybrid matches and one known Unicode mismatch**, with zero blocked cases or runner
errors, and covers both hybrid points.
The Unicode diagnostic belongs to `engine.unicode-collation`, retains no acceptance credit and
remains an ordinary mismatch with its declared deviation. That engine contract still has **0/2
points verified**; printable-ASCII hybrid tie evidence does not establish general Unicode path
collation. The prior warm first-recall comparison likewise remains visible and uncredited.

The committed full-gate report, `.equivalence-results/hybrid-scoring-full.json`, executes all
**828 cases** against implementation commit `0687e8726bd0cb408c5575bca608359783a64600` with a clean
tracked tree. It records **826 matches, two mismatches and zero blocked cases**, with no runner
errors. All **66 hybrid cases match**. The only differences are the uncredited
`hybrid-unicode-path-collation-diagnostic` and `flush-execution-warm-index-first-recall` cases.
Both remain ordinary visible mismatches; neither grants acceptance credit. The full gate reports
`mismatched`, not a full-equivalence pass, and **99 acceptance points remain uncovered**. No
provider credentials were forwarded and no paid provider calls were made.

Full regression validation passed **2,857 tests** in 133.16 seconds. The same **1,625 historical
oracle/live checks** remain skipped and grant no acceptance credit. Ruff, project-name
consistency, exact source-map validation and staged diff checks passed. These final results are
recorded in a documentation-only follow-up; implementation, adapters and source inventory are
unchanged from the tested commit.

### Exact-path retrieval priority — 2026-11-08

This batch targets and verifies **+2 points**: **`retrieval.exact-path-priority.outcomes`** and
**`retrieval.exact-path-priority.boundaries`**. Current acceptance is **31/128 (24.2%)**, with
**97 points (75.8%)** remaining: **14 complete, three partial and 47 pending contracts**. The
fixed **64 contracts, 128 acceptance points** and scope SHA-256
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9` remain unchanged. Inventory
now maps **110 upstream modules**; classifications remain 14 present, 47 partial, zero missing
and three host-owned. No additional hybrid, Unicode-engine or manager-lifecycle credit is added.

The paired profile uses unicode61 path FTS. Actual unchanged TypeScript functions compare full
path, basename and stem tiers, normalization and literal folding, partial/body-only candidates,
SQLite live-row admission, first-chunk snippets, source filters and exact-path candidate bounds.
Path-to-hybrid component fixtures combine real path candidates with disjoint declared body
candidates; they do not run the private keyword premerge. The SDK's
public `search_path_candidates` filters live logical sources before caps and projects the first
chunk/snippet in the same statement snapshot. Normal search retains explicit 200 exact-path
headroom, identity checks and its generation transaction. JavaScript trim and UTF-16 snippet
comparison now match the exercised boundaries. This establishes neither universal ICU collation
nor trigram execution.

`.equivalence-results/exact-path-old-sdk-baseline.json` retains actual unchanged SDK behavior
at commit `e0b7c29e16c4595c915960cd3f2645b70c918d7c`: FEFF/0085 whitespace differences, a UTF-16
snippet choice and an orphan-row 200-candidate cap that returned no live result. The actual source
comparison, `.equivalence-results/exact-path-source-first.json`, records **49 matches, zero
mismatches and zero blocked cases**. An authenticated four-file named-binding chain resolves
`escapeRegExp` to its unchanged source owner; it does not initialize the broad text facade.

The private keyword merge/limit methods are also tested in the authenticated official compiled
release through `Object.create(MemoryIndexManager.prototype)`. Reviewed source-class/export links
and compiled artifact hashes remain separate; **`sourceBuildReproduced: false`** and
**`constructorSkipped: true`** are explicit. No constructor, provider, worker or full-manager
end-to-end behavior is claimed. An attempted source-class import remained blocked by missing
`markdown-it` after loading 2,472 sources; its separate diagnostic at
`/workspace/scratch/exact-class-import-transform-result.json` is retained, with no installation
used to turn that attempt into evidence.

The first compiled report, `.equivalence-results/exact-path-runtime-first.json`, retains **15
blocked Python cases**: the initial adapter omitted `python-raw.json` evidence writing. This was
a diagnostic-wiring failure, not an SDK/native behavior mismatch. The corrected adapter writer
and its guard passed **41 targeted tests**. Actual
`.equivalence-results/exact-path-runtime-evidence-fixed.json` then records **15 matches, zero
mismatches and zero blocked cases**. These original focused reports retain `covers: []`; reviewed
point assignments belong to the registered catalog and the full gate below.

The committed full-gate report, `.equivalence-results/exact-path-priority-full.json`, executes all
**892 cases** against implementation commit `ea38a8504934a2811406ed6592e693585b45f906` with a clean
tracked tree. It records **890 matches, two mismatches and zero blocked cases**, with no runner
errors. All **64 exact-path cases match**: 49 source cases and 15 protected compiled-method
executions with native and Python raw evidence. The only differences remain
`hybrid-unicode-path-collation-diagnostic` and `flush-execution-warm-index-first-recall`; both
are ordinary visible mismatches with no acceptance credit. The full gate reports `mismatched`,
not full equivalence, and **97 acceptance points remain uncovered**. No provider credentials
were forwarded and no paid provider calls were made.

Full regression validation passed **2,943 tests** in 133.59 seconds. The same **1,625 historical
oracle/live checks** remain skipped and grant no acceptance credit. Ruff, project-name
consistency, exact source-map validation and staged diff checks passed. These final results are
recorded in a documentation-only follow-up; implementation, adapters and source inventory are
unchanged from the tested commit.

### Stored importance and active-project ranking — 2026-11-08

This batch targets and verifies **+2 points**: **`retrieval.importance-project.outcomes`** and
**`retrieval.importance-project.boundaries`**. Current acceptance is **33/128 (25.8%)**, with
**95 points (74.2%)** remaining: **15 complete, three partial and 46 pending contracts**. The
fixed **64 contracts, 128 acceptance points** and scope SHA-256
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9` remain unchanged. Source
inventory maps **113 upstream modules**; classifications are 15 present, 46 partial, zero
missing and three host-owned. This closes only the two importance/project points.

The SDK now reads stored importance, triggers, project keys and full provenance for retained
live candidates within the same read generation. Missing optional annotations remain neutral;
missing chunks are excluded. Keyword-only, vector-only and hybrid paths apply importance bounds,
active/inactive project modifiers and malformed-project filtering in the exercised order with
path specificity, decay and MMR. Indexed memory/session mtimes reach ranking and are stripped
from public results. Public serialization preserves branch-specific component scores and
candidate-id presence; the numeric Python attributes retain their existing access contract.

Trusted host code supplies `active_project_keys` through `Memory.search`, `HostKit` or the tool
execution/deadline APIs. The model-facing `memory_search` schema is unchanged and model arguments
cannot override that context. Trigger annotations survive as metadata; automatic trigger/project
candidate APIs and prompt injection remain outside this batch.

The retained old-SDK diagnostic,
`.equivalence-results/importance-project-old-sdk-baseline.json`, uses actual unchanged commit
`54025ce8429408a25b7a72e2243e871e4fb56982`: annotations with importance 10/1 persisted, while
public results omitted that metadata and the host project-context argument raised `TypeError`.
The actual first comparison, `.equivalence-results/importance-project-first.json`, records
**54 matches, zero mismatches, zero blocked cases and no runner errors**: **46 source cases**
and **eight authenticated official-runtime public stored-search cases**. The source cases cover
12 modifier, eight hybrid, 14 preparation and 12 real SQL-reader cases. The original first
report retains `covers: []`; reviewed coverage is assigned in the registered catalog.

Source preparation executes the original owner and its facade imports. The recall SQL reader
executes unchanged with Kysely and a narrow authenticated projection of its invalid-project
constant. The declared logical published SQL view compares source, path, range, text and every
annotation/provenance field, preserving duplicate rows and order. Private IDs and update clocks
remain in both raw diagnostics. In the text-only preparation profile, the SDK's actual embedding
text maps to the native text-input wrapper; multimodal and provider-enforcement behavior is
unverified. Public search rows retain every returned field and exact score, without projection,
rounding or tolerance.

The runtime cases construct the real provider-none `MemoryIndexManager`, call public
`get`/`sync`/`search`/`close`, update annotations and reopen the published index. Four required
compiled owners, ten source identities and protected native worker traces remain authenticated.
The release proof records **`sourceBuildReproduced: false`**, **`constructorSkipped: false`**,
`fullManagerExecutionVerified: false` and `fullHostOrchestrationVerified: false`. This bounded
stored-search evidence does not close other manager or host lifecycle contracts. The paired
profile retains printable-ASCII path ties, exact Unicode content and annotations, unicode61
FTS and portable CPU vector behavior. Alternate trigram/ICU/KNN behavior and the existing warm
first-recall and Unicode-path diagnostics remain open and uncredited.

Two legacy flag-test field-shape expectations were corrected against the actual native public
probe. A host twin fixture now supplies identical source mtimes because provenance exposes
`observedAt`; the correction fixes nondeterministic inputs rather than normalizing output.
The committed full-gate report, `.equivalence-results/importance-project-full.json`, executes
all **946 cases** against implementation commit `2f4b5460e54dbd6aabaf30e33d9eb57323bd1a11` with a
clean tracked tree. It records **944 matches, two mismatches and zero blocked cases**, with no
runner errors. All **54 importance/project cases match**, including eight public stored-search
flows with protected workers and all four required artifact owners. The only differences remain
`hybrid-unicode-path-collation-diagnostic` and `flush-execution-warm-index-first-recall`; neither
grants acceptance credit. The full gate reports `mismatched`, not full equivalence, and **95
acceptance points remain uncovered**. No provider credentials were forwarded and no paid
provider calls were made.

The first full regression attempt recorded 3,036 passes and one legacy Lab failure: its
keyword-only assertion required `vectorScore`, contrary to the observed native branch payload.
That log remains at `/workspace/scratch/memory-core-importance-project-full-tests.log`. The
assertion now checks the native absence of that field and a positive text component; the
targeted test passes. The complete rerun passed **3,037 tests** in 141.12 seconds, retained at
`/workspace/scratch/memory-core-importance-project-full-tests-final.log`. The same **1,625
historical oracle/live checks** remain skipped and grant no acceptance credit. Ruff,
project-name consistency, exact source-map validation and staged diff checks passed.

These final results and the legacy Lab assertion are recorded in a documentation/test follow-up;
SDK implementation, differential adapters and source inventory are unchanged from the tested
implementation commit.


### Memory-search tool boundary implementation

The `tools.search-contract` batch targets **+2 acceptance points**, from **33/128
(25.8%)** to **35/128 (27.3%)** if the committed integrated gate verifies the final
fixtures. The fixed scope remains 64 contracts and 128 acceptance points.

The pre-change SDK baseline at `3b2c42f72b36ff8b3aff427ea5ec931f7237a3a4` is retained in
`.equivalence-results/search-contract-python-baseline.json`: the raw tool returned five
results, rejected a blank numeric score and emitted citation/truncation fields that the
native result omits. The implementation now uses native raw defaults (six results, minimum
score 0.35), configured query defaults, blank numeric omission, ordinary corpus errors,
canonical citation presentation and full public source metadata. The Python convenience
API deliberately keeps its explicit five-result/zero-score arguments.

The production factory provides the genuine definition, alias preparation, live configuration
revocation, captured-store ownership validation and complete JSON result envelope. Its default
manager timing measures the actual ready-store lookup; hosts can supply their measured
manager acquisition and live status/debug events. `FeatureFlags.memory` controls factory
availability and is appended to preserve prior positional fields. The new query settings
also preserve existing `MemoryConfig` positional arguments. `HostKit` prepares model aliases
and handles ordinary tool errors; its provider-neutral dictionary API remains intact.
The default citation mode is `auto`, including matching direct/group/channel presentation.
A related prompt guard now accepts `auto`, preserving working chat preparation.

The first report, `.equivalence-results/search-contract-first.json`, records **69 matches,
zero mismatches and zero blocked cases**, before acceptance mapping. It executes 46 original
source helpers, 12 separately authenticated compiled definition/preparation cases and 11
actual provider-none whole-tool cases. The latter construct the real native manager and
require all eight compiled owners plus protected index workers. Provenance guards reject
missing owners, forged traces and selecting the helper profile for a whole-tool fixture.
Official release execution retains `sourceBuildReproduced: false`; it is not a claim of a
locally reproduced source build. The source helper process uses Node's built-in TypeScript
transform support on unchanged authenticated source.

Every public envelope, ordered result, error name/status/message, debug field, warning and
source field survives comparison. The declared JSON carrier codec first uses the actual
JSON transport, verifies text/details agreement and compares the decoded complete payload.
Both original text carriers and envelopes remain in raw evidence. JSON whitespace and
numeric spelling are not claimed byte-identical; absent and null JSON fields remain distinct.
There is no score rounding, result sorting or public-field projection.

Independent review tightened the configured-default fixture so its minimum score separates
a stored importance-10 result from ordinary hits, and aligned disabled-config inputs on
both sides. These final refinements and mapped acceptance points await the committed full
gate. The bounded profile covers memory-file provider-none searches and registered wiki
supplements, including partial/multiple failure ordering. Real transcript visibility,
provider/fallback/bootstrap execution, stale/rebuild lifecycle, deadline/cooldown timing and
all other contracts remain uncredited by this batch. The existing Unicode path-order and
warm first-recall differences remain visible. No paid provider calls are required.
