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
238 upstream source modules, their tracked hashes, literal dependencies and exported
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

<!-- CURRENT-VERIFICATION-START -->
The latest complete local assessment has **71/128 verified conditions (55.5%)**,
with **57 conditions remaining**. The fixed scope remains 64 contracts and 128
conditions. This measures verified conditions, not effort or elapsed work.
The cold retry development package fixes genuine recovery behavior and adds
**zero acceptance points**. Its fresh full run loses one previously verified
condition; the earlier 72/128 report retains its historical identity.

On clean `e148d0b`, the changed SDK executes the unchanged **1,444-case** catalog:
**1,429 matches, 15 mismatches, zero blocked and no runner errors**. All original
1,444 complete builder definitions, 80 builder-only annotations, 41 evidence flags
and 127 of 128 original point records remain unchanged. All original fourteen
complete Native and SDK mismatch payloads remain unchanged. The new fifteenth
case, `host-turn-barrier-cold-unicode`, differs only because its actual Native
result omits the previous `warning` and `corpora` fields. Its SDK result is exactly
equal to the prior local result; source, hits, ranking, get and reply are unchanged.
The strict four-member family therefore no longer verifies
`host.turn-barrier.outcomes`; #62 is **partial, 1/2**. No warning is removed from
comparison and no historical variation allowance or passing rerun is substituted.

The report is independently authenticated with its failed gate retained. The
actual Native notice-counter timing was not recorded by that older profile, so
the precise scheduling cause remains unproved. All 23 current query/identity
pairs replay successfully with their complete public results equal to the prior
local baseline. The production SDK has 160 files, source SHA-256
`20abf913ac4d7d394aacbcad73e63ad14968c4f2d485ea2a3c0684413d40237d`;
only `memory_core/host/managed_index.py` changes from the prior SDK.

The genuine cold-retry packet first measures one control match and 23 recovery
differences. The narrow fix permits one later bootstrap only for an actually
empty opt-in on-search index after a retained publication error. Its corrected
two pairs match in full, with zero differences/blocked/errors; their adversarial
replay passes **119 tests with zero skips**. These standalone cases have
`covers=[]` and are not registered as boundary acceptance. Original
`indexing.query-sync.boundaries` remains unverified.

The current SDK passes **10,159 general tests**, zero failures and **1,658
uncredited skips** on the same clean `e148d0b`; SDK and all 298 adapter bytes stay
unchanged through both original full and regression commands. Code-head GitHub
package checks pass on Python 3.11 and 3.12: **7,850 tests passed and 3,967
uncredited skips per version**, with wheel/sdist consumers and 27 invalid typed
calls rejected per installed artifact. The separate Native workflow is still
running at documentation preparation; no completed hosted acceptance is inferred.

The complete local gate remains `mismatched`: **54 uncovered conditions plus
three registered unresolved conditions** remain. The earlier hosted18/local14
discrepancy is separate; investigation/download of those older reports remains
paused at the user's request. It is not relabeled as the fresh local fifteenth.
Complete OpenClaw equivalence is not established.

See the [cold retry closeout](query_sync_cold_retry_development_closeout.md) for
exact identities, preserved first failures, current gate loss and measured limits.
The next priority is the local next-turn notice discrepancy: observe actual
original notice/status/publication calls to establish when the first search gets
its renewal warning. For example, both systems find the saved note but must also
agree on the warning shown with that answer. Forced-sync/joining, revision-conflict
retry, other unavailable outcomes and remaining dispatch counts still need their
original query-sync boundary proof.

The preceding [query-sync outcome closeout](query_sync_outcomes_closeout.md)
historically verified **71 → 72/128** on clean `aa99a933`; its original capture and
SDK identities remain unchanged. The preceding
[index-identity boundary closeout](index_identity_boundaries_closeout.md) verified
**70 → 71/128** on clean `5856b4e`; that earlier 71 refers to its own verified set.

See the [boundary closeout](host_turn_barrier_boundaries_closeout.md) for exact identities,
complete public results, retained failures and measured limits. See the original
[natural next-turn outcomes closeout](host_turn_barrier_closeout.md) for exact
source, full-report and runtime identities, declared limits and retained attempts. The preceding
[host update/isolation batch](host_update_isolation_closeout.md) verified **66 → 68/128**
on clean `57270da`, with 1,411 cases, 1,397 matches, 14 differences and zero blocked.
The earlier
[shared managed-host restart batch](host_restart_session_closeout.md) verified **64 → 66/128**
on clean `9d13b19`, with 1,407 cases, 1,393 matches, 14 differences and zero blocked.
Its captured SDK identity remains historical. The earlier promotion apply batch verified
**62 → 64/128** on `b090394`; none of its original captures is relabeled.

See the [promotion apply closeout](promotion_apply_reconcile_closeout.md) for exact source,
report and runtime identities, the actual model-request serialization correction,
retained preparation failures and authority limits. The earlier
[promotion/heartbeat maintenance integration](promotion_heartbeat_integration_closeout.md)
awarded zero conditions; the [initial family development packet](promotion_apply_family_development_closeout.md)
also awarded zero. Their historical captures are not relabeled as executions of
this changed SDK or these completed acceptance callers. The new
[initial host restart development packet](host_restart_recall_development_closeout.md)
executes three authenticated process-restart comparisons: all three retain
complete-result differences, with zero blocked cases or runner errors. It awards
zero conditions and changes no SDK production source. Its fresh full regressions
pass **6,785 tests**, with the same **1,648 uncredited skips**. That diagnostic packet did not verify the whole restart contract. The later [source-policy/factory follow-up](host_restart_policy_closeout.md)
changes HostKit search dispatch, aligns explicit source policies and retains four
new mismatched diagnostic cases with zero blocked/errors. Its changed SDK has
separate evidence; the complete `b090394` catalog above remains historical.
Its final full regressions pass **6,826 tests**, with **1,648 uncredited skips**;
both clean offline wheel/sdist consumers pass against the changed SDK.
The [producer publication/managed-index package](host_restart_managed_closeout.md)
aligns real producer metadata publication and adds cold-search bootstrap.
Its separate managed family has **3 matches and 1 sessions mismatch**, zero
blocked/errors, with **6,929 passing regressions** and **1,648 uncredited skips**.
Both installed offline package consumers pass. The later
[session publication owner package](session_publication_closeout.md) implements
scoped atomic refresh, real post-commit notifications, a session queue and
query read-generation admission. That package left the explicit managed runner and fresh paired
process comparison as follow-up work. The changed SDK passes **6,991 full
regressions**, with **1,648 uncredited skips**, and both offline installed
package consumers. Those earlier restart packets award zero conditions and retain their
64/128 historical baseline. The later [shared managed-host package](host_restart_session_closeout.md)
completes the two original restart conditions against its clean `9d13b19` catalog,
reaching 66/128 before the update/isolation and natural next-turn packages.

| Contract status | Contracts | Verified conditions | Remaining conditions |
| --- | ---: | ---: | ---: |
| Complete | 32 | 64 | 0 |
| Partial | 7 | 7 | 7 |
| Pending verification | 25 | 0 | 50 |
| Total | 64 | 71 | 57 |

Pending verification can include existing implementation. Partial contracts retain one open
condition. Infrastructure sections 1–3 remain **20/22 tasks completed**; infrastructure and
source inventory do not add behavioral conditions. After each completed batch, report the
actual increase, complete/partial/pending status and any information needed from the user.

Current status of all 64 contracts:

| No. | Contract | Status | Verified conditions |
| ---: | --- | --- | ---: |
| 1 | `storage.discovery` | Complete | 2/2 |
| 2 | `storage.path-safety` | Complete | 2/2 |
| 3 | `storage.atomic-writes` | Complete | 2/2 |
| 4 | `storage.workspace-isolation` | Complete | 2/2 |
| 5 | `lexical.tokenization` | Complete | 2/2 |
| 6 | `lexical.fts-query` | Complete | 2/2 |
| 7 | `lexical.bm25` | Complete | 2/2 |
| 8 | `chunking.markdown-boundaries` | Complete | 2/2 |
| 9 | `chunking.utf16-cjk-budget` | Complete | 2/2 |
| 10 | `chunking.entry-provenance` | Complete | 2/2 |
| 11 | `indexing.identity` | Complete | 2/2 |
| 12 | `indexing.incremental-sync` | Complete | 2/2 |
| 13 | `indexing.transaction-publication` | Complete | 2/2 |
| 14 | `indexing.embedding-cache` | Pending verification | 0/2 |
| 15 | `indexing.query-sync` | Partial | 1/2 |
| 16 | `retrieval.vector-scoring` | Complete | 2/2 |
| 17 | `retrieval.hybrid-scoring` | Complete | 2/2 |
| 18 | `retrieval.exact-path-priority` | Complete | 2/2 |
| 19 | `retrieval.mmr` | Complete | 2/2 |
| 20 | `retrieval.temporal-decay` | Complete | 2/2 |
| 21 | `retrieval.importance-project` | Complete | 2/2 |
| 22 | `tools.search-contract` | Complete | 2/2 |
| 23 | `tools.get-contract` | Complete | 2/2 |
| 24 | `tools.deadline-cooldown` | Complete | 2/2 |
| 25 | `tools.unavailable-partial` | Complete | 2/2 |
| 26 | `sessions.corpus-admission` | Complete | 2/2 |
| 27 | `sessions.transcript-filtering` | Partial | 1/2 |
| 28 | `sessions.visibility-lineage` | Complete | 2/2 |
| 29 | `sessions.reset-hook` | Pending verification | 0/2 |
| 30 | `sessions.durable-context` | Complete | 2/2 |
| 31 | `prompt.bootstrap-discovery` | Partial | 1/2 |
| 32 | `prompt.bootstrap-budget` | Complete | 2/2 |
| 33 | `prompt.runtime-context` | Pending verification | 0/2 |
| 34 | `prompt.history-repair` | Pending verification | 0/2 |
| 35 | `flush.plan-target` | Pending verification | 0/2 |
| 36 | `flush.trigger-usage` | Complete | 2/2 |
| 37 | `flush.execute-finalize` | Partial | 1/2 |
| 38 | `compaction.memory-budget` | Complete | 2/2 |
| 39 | `compaction.context-assembly` | Pending verification | 0/2 |
| 40 | `compaction.provider-overflow` | Pending verification | 0/2 |
| 41 | `promotion.recall-signals` | Pending verification | 0/2 |
| 42 | `promotion.ranking-gates` | Partial | 1/2 |
| 43 | `promotion.apply-reconcile` | Complete | 2/2 |
| 44 | `promotion.deep-consolidation` | Pending verification | 0/2 |
| 45 | `dreaming.light` | Pending verification | 0/2 |
| 46 | `dreaming.rem` | Pending verification | 0/2 |
| 47 | `dreaming.deep` | Pending verification | 0/2 |
| 48 | `dreaming.diary-provenance` | Pending verification | 0/2 |
| 49 | `forget.lineage-tombstones` | Pending verification | 0/2 |
| 50 | `forget.index-fence` | Pending verification | 0/2 |
| 51 | `trust.secret-redaction` | Pending verification | 0/2 |
| 52 | `trust.configured-redaction` | Partial | 1/2 |
| 53 | `heartbeat.scratch` | Pending verification | 0/2 |
| 54 | `heartbeat.turn-decisions` | Pending verification | 0/2 |
| 55 | `automation.job-state` | Pending verification | 0/2 |
| 56 | `concurrency.workspace-locks` | Pending verification | 0/2 |
| 57 | `recovery.repair-diagnostics` | Pending verification | 0/2 |
| 58 | `recovery.failure-publication` | Pending verification | 0/2 |
| 59 | `engine.numeric-boundaries` | Pending verification | 0/2 |
| 60 | `engine.unicode-collation` | Pending verification | 0/2 |
| 61 | `engine.datetime-regex` | Pending verification | 0/2 |
| 62 | `host.turn-barrier` | Partial | 1/2 |
| 63 | `host.restart-recall` | Complete | 2/2 |
| 64 | `host.update-isolation` | Complete | 2/2 |

<!-- CURRENT-VERIFICATION-END -->

The integrated path/read proof now verifies both `storage.path-safety` conditions
with all eleven families and 99 genuine whole-tool calls. Its literal family/input
guard rejects reduced or helper-only claims. The corrected11 and legacy12 packets
retain their original empty coverage metadata and hashes; fresh registered proof
is recorded in the integrated closeout below. [Path proof](storage_path_safety_proof.md)
records the original source actors, checked descriptor/error behavior, exact
pre-open race authority, full raw filesystem evidence and broader SDK-only limits.

### Storage and workspace

- [x] **`storage.discovery` — Discover exactly the eligible memory files.** Compare roots, nested Markdown, case sensitivity, order, hidden artifacts and disappearing files. Exclude or admit symlinks and non-regular files exactly as the pinned reference does.
- [x] **`storage.path-safety` — Enforce memory path and read boundaries.** Exercise absolute, relative, traversal, encoded and symlink paths. Compare rejected operations, result shapes and absence of unintended writes.
- [x] **`storage.atomic-writes` — Publish writes atomically.** Compare append, replace, exclusive creation and concurrent rename outcomes. Inject write, flush, fsync and publication failures and inspect the surviving files.
- [x] **`storage.workspace-isolation` — Keep workspace and subject state separate.** Reuse one host configuration across distinct workspaces and subjects. Prove files, indexes, recalls and maintenance state cannot cross the selected boundary.

### Lexical and chunking

- [x] **`lexical.tokenization` — Match lexical tokenization.** Compare exported token sets for empty, repeated, ASCII, mixed-script, CJK and Unicode boundary inputs. Use deterministic generated strings as well as named cases; preserve all observable tokens.
- [x] **`lexical.fts-query` — Match full-text query construction.** Compare query strings and no-query outcomes for punctuation, quotes, identifiers, whitespace and mixed scripts. Exercise deterministic generated inputs without reconstructing the reference algorithm in the oracle.
- [x] **`lexical.bm25` — Match BM25 rank conversion.** Compare positive, negative, zero and boundary ranks, including supported non-finite input representations. Report numerical differences rather than masking score-gate changes with a blanket tolerance.
- [x] **`chunking.markdown-boundaries` — Match Markdown chunk boundaries.** Compare ordered chunks, lines, overlap, empty content, headings and per-entry curated files. Read the original source through every returned line range.
- [x] **`chunking.utf16-cjk-budget` — Match UTF-16 and CJK chunk budgets.** Exercise surrogate pairs, malformed surrogates, CJK weighting and exact budget boundaries. Compare truncation and overlap without splitting valid pairs or changing source ranges.
- [x] **`chunking.entry-provenance` — Retain chunk identity and provenance.** Compare chunk hashes, entry boundaries, source identities and provenance fields. Verify unchanged and changed inputs produce the reference identities and invalidation decisions.

### Index lifecycle

- [x] **`indexing.identity` — Match index identity gating.** Vary provider, model, endpoint settings, scope, sources, tokenizer and chunking versions. Compare missing, matching and stale metadata diagnostics before any query is admitted.
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

- [x] **`tools.search-contract` — Match memory_search inputs and results.** Compare definitions, accepted parameters, coercion, defaults, corpora and rejection errors. Compare complete ordered payloads, citations, warnings and source metadata. Verified for the declared provider-none memory/wiki profile; other lifecycle/provider/session contracts remain open.
- [x] **`tools.get-contract` — Match memory_get inputs and results.** Compare allowed files, line windows, UTF-16 budgets, continuation hints and missing sources. Compare exact status/error shapes and returned source text. Verified for the declared portable read/wiki profile; OS-specific loop causes, patterns and filesystem races remain uncredited.
- [x] **`tools.deadline-cooldown` — Match deadlines and cooldowns.** Control clocks and slow providers to exercise absolute deadlines and cooldown transitions. Compare subsequent admission, provider call counts and memory/wiki/session independence. Verified under the declared controlled backend/timer profile; live provider latency, indexed manager startup and transcript visibility are uncredited.
- [x] **`tools.unavailable-partial` — Match unavailable and partial corpus outcomes.** Fail individual providers and supplemental corpora independently. Compare partial results, timed-out flags, warnings and recovery on a later explicit query. Verified through complete controlled search/get factories and original source owners; general provider/network lifecycle remains uncredited.

### Sessions and transcript

- [x] **`sessions.corpus-admission` — Match session corpus admission.** Compare accepted session kinds, ownership, participants, archives and generated maintenance sessions. Provide the same host metadata and compare included and excluded entries.
- [ ] **`sessions.transcript-filtering` — Match transcript extraction and filtering.** Compare JSONL trees, tool rows, heartbeat markers, recalled content and failed or mirrored messages. Exercise reset fences, malformed rows and supported archives without inventing stored text.
- [x] **`sessions.visibility-lineage` — Match source-session visibility and lineage.** Vary visible sessions, source identities, trust and forgotten origins. Compare hits, provenance and source reads before and after reset or deletion.
- [ ] **`sessions.reset-hook` — Match new/reset memory capture.** Compare transcript projection, naming, timezone, slug behavior and exclusive publication. Verify source lines, trust records, collision handling and recall after the hook.
- [x] **`sessions.durable-context` — Preserve durable conversation context.** Persist actual transcript and session metadata and reconstruct the host in a fresh process. Compare continuation, ordering and retained context without relying on process-local lists.

### Prompt and bootstrap

- [ ] **`prompt.bootstrap-discovery` — Match workspace bootstrap selection.** Exercise setup states, session kinds, available files and compatibility layouts. Compare ensure decisions, selected files and their order under the same inputs.
- [x] **`prompt.bootstrap-budget` — Match bootstrap clipping and notices.** Exercise per-file, USER.md and aggregate UTF-16 limits and exact boundary values. Compare clipping, omitted files, warning modes and once-per-session state.
- [ ] **`prompt.runtime-context` — Match memory and runtime prompt composition.** Compare memory guidance, tools, runtime markers and fixed clock/timezone fragments. Compare insertion order and isolation of untrusted or recalled text.
- [ ] **`prompt.history-repair` — Match history windowing and tool repair.** Exercise missing results, duplicate or invalid calls, failed turns and provider replay metadata. Compare repaired model-visible messages while preserving the original durable transcript.

### Flush and compaction

- [ ] **`flush.plan-target` — Match flush plan and target selection.** Compare enabled/disabled configuration, model selection, timezone and daily target validation. Compare prompts, reserve terms and failure before a target can be safely prepared.
- [x] **`flush.trigger-usage` — Match flush trigger accounting.** Feed fresh/stale usage, missing usage, transcript byte limits and compaction counters. Compare trigger decisions, heartbeat exclusions and retry/exhaustion state.
- [ ] **`flush.execute-finalize` — Match flush execution and finalization.** Run the same labelled model/tool sequence through both hosts. Compare append-only writes, index readiness, provenance and successful or failed cycle stamps.
- [x] **`compaction.memory-budget` — Match curated memory budget compaction.** Exercise promotion sections mixed with user text and exact size/loss limits. Compare preserved bytes, removed sections, deferral and reconciliation markers.
- [ ] **`compaction.context-assembly` — Match context assembly and compaction replay.** Compare active transcript projections, summaries, checkpoints, tool-result bounds and replay decisions. Retain trailing required results and provider continuation data across restart.
- [ ] **`compaction.provider-overflow` — Match overflow recovery behavior.** Drive preflight and mid-turn overflow, truncation, compact/retry and terminal failures. Compare dispatch counts, protected messages and exact continuation/admission decisions.

### Recall and promotion

- [ ] **`promotion.recall-signals` — Match recall recording.** Compare filtering, deduplication, query hashes, day boundaries, retention and recall events. Verify ground truth source ranges and origin recording before published recall state.
- [ ] **`promotion.ranking-gates` — Match promotion ranking and gates.** Compare scores, custom weights, tie order, diversity, age, trust and visibility gates. Include exact score thresholds and promoted-entry visibility.
- [x] **`promotion.apply-reconcile` — Match promotion application and reconciliation.** Compare MEMORY.md/DREAMS.md, markers, authoritative candidates and applied/rejected receipts. Interleave candidate changes and verify lock-time rechecks and publication order. Verified through all eight frozen provider-free whole-operation families, complete callback envelopes, physical/API readbacks and live owner receipts; general model plans and origin-reservation behavior remain separate.
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

- [ ] **`host.turn-barrier` — Finalize memory before the next turn.** Partial: the separate full-channel boundary remains verified, but the current four-case outcome family fails its cold Unicode notice comparison. Saved source, search hits and reply agree; the actual Native warning/corpora fields differ. Complete public output remains required; original outcomes are currently unverified. No in-flight append or universal scheduling guarantee is claimed.
- [x] **`host.restart-recall` — Recall across fresh chats and process restart.** Use the same saved corpus with a fresh session and then a fresh host process. Compare source-backed retrieval and state continuity with facts omitted from the new prompt.
- [x] **`host.update-isolation` — Update current facts while preserving isolation.** Replace a prior preference, retain unrelated facts and query from independent user/workspace scopes. Compare current versus superseded answers and honest write/index failure reporting.

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


The first committed integrated report, `.equivalence-results/search-contract-full.json`,
ran all **1,015 cases** against `582f5bd8a4f4f0c97348fccc49c23d9320724da5`: **1,013 matches,
two retained mismatches, zero blocked cases and no runner errors**. All 69 search cases
matched, including the tightened configured-default and disabled-config inputs. Both search
acceptance points passed in that report; 93 other acceptance points remained uncovered.
The only differences were the existing Unicode path-order and warm first-recall diagnostics.

The first complete regression log retained **3,241 passes and 11 failures**, with the same
1,625 historical/live checks skipped. Ten failures were prior shape/clock/API expectations;
the remaining event fixture now supplies `minScore=0` explicitly so dated-hit decay does not
change its event-delivery purpose. A stronger persisted-snippet assertion then exposed a
real integration defect: the recall recorder failed to remove the new plain-label citation
suffix. The first new regressions retain three failures before the fix. Undecoration now
removes the actual `Source:` suffix while retaining legacy prefixed-label compatibility,
metadata and caller inputs. All 25 targeted recall/ingestion checks pass after the fix.
These changes add no acceptance points and do not broaden the fixed scope.

Affected demo/integration and LangGraph checks pass with complete payloads retained under
paired clocks. The official wheel/sdist script passed isolated core-only installs, imports,
real FTS HostKit flow, dependency checks and public API typing on the first implementation.
Initial package checks were blocked by missing cache entries and sandbox proxy access; their
logs were preserved, and the unchanged script succeeded with official dependencies and the
inherited proxy/TLS settings. Final source validation, the full regression rerun, clean
package consumers and the final integrated comparison are pending for the recall fix.


Final recall-fix checks at `cff2ff0acca10e3775ec352155a8e9d45b6dc5e4` passed **3,260 tests**
in 147.27 seconds, with the same **1,625 historical/live skips** granting no acceptance
credit. The first 11-failure regression log and the three failing citation regressions remain
retained. The unchanged official distribution script passed both wheel and sdist checks
again using the existing cache with networking disabled: contents, license, metadata, isolated
core-only installation, dependency consistency, every core import, a real FTS HostKit flow
and positive/negative public API typing. No production or adapter changes are planned after
this committed fix. Final integrated evidence follows below.


The final report, `.equivalence-results/search-contract-full-final.json`, reran all **1,015
cases** against clean implementation commit `cff2ff0acca10e3775ec352155a8e9d45b6dc5e4`. It
records **1,013 matches, two retained mismatches, zero blocked cases and no runner errors**.
All **69 search-contract cases match** after the integration fix. Both mapped acceptance
points pass: this batch targeted **+2** and verified **+2**, increasing **33/128 (25.8%)** to
**35/128 (27.3%)**, a **1.6 percentage-point** increase. **93/128 (72.7%)** remain. There are
**16 complete, three partial and 45 pending contracts**; no other item receives credit.

The final report identifies all 128 Python source files with SHA-256
`daa8c802585ff9e811c40f352ea4d6f05f92d1f2052f9b79bbf54da347b34cb5`; both implementation and
adapter hashes still match the checked source. The scope hash remains
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`. The same two diagnostic
differences remain uncredited: `hybrid-unicode-path-collation-diagnostic` and
`flush-execution-warm-index-first-recall`. The SDK's stronger eager index-readiness behavior
was preserved. The full gate returns incomplete/mismatched, not full equivalence, because
these differences and 93 uncovered acceptance points remain. No credentials were forwarded
and no paid provider requests were made.

The final regression log is
`/workspace/scratch/memory-core-search-contract-full-tests-final.log` (**3,260 passed, 1,625
skipped**). Clean wheel/sdist evidence is
`/workspace/scratch/memory-core-search-contract-distribution-recall-final.log`. First attempts
and reproduced failures remain separately retained. Ruff, project-name consistency, source
inventory validation and diff checks passed. This final follow-up changes documentation
only; SDK source, differential adapters and the inventory match the tested implementation.

After that search batch, the next fixed item was `tools.get-contract`, targeting
37/128 if verified; the get implementation and evidence follow below.


### Memory-get tool boundary implementation

This batch targets **+2 acceptance points**, from **35/128 (27.3%)** to **37/128
(28.9%)** if the committed integrated checks pass. The fixed scope remains **64 contracts
and 128 acceptance points**; no storage/deadline/OS behavior point is added by this batch.

The pre-change SDK baseline at `a94d989f134f94a311774ef261aeeb6ae918a06e` is retained in
`.equivalence-results/get-contract-python-baseline.json`. It consumed one Python character
instead of one UTF-16 unit, and sliced/clamped wiki content again while dropping provider
metadata. The read path now uses genuine shared production excerpt builders with 120-line
and 12,000-unit defaults, safe surrogate boundaries, exact continuation state and notices
even when no first character fits. Wiki providers own their excerpts; content becomes text,
status becomes ok and all other details remain intact. Explicit registered readers receive
lookup, range, agent and trusted host context; legacy anonymous callable signatures remain
supported. The English API guide is [memory_get_tool.md](memory_get_tool.md).

The new production factory exposes the actual definition and complete JSON result envelope,
checks live availability and captures one workspace/agent without requiring an index. Plain
configured file/directory roots authorize additional reads; model arguments cannot grant
that scope. Existing admission order, symlink refusals and read-only behavior are preserved.
Stable fs-safe causes are attached at the actual refusal checks for outside symlinks,
non-directory ancestors and nonregular leaves. Python's actual OS-owned symlink-loop cause
is retained rather than rewritten into Node's wording. Pattern configuration, descriptor
races, retry timing, deadlines and session visibility remain outside this bounded profile.

The first report, `.equivalence-results/get-contract-first.json`, retained **69 matches,
one filesystem mismatch and zero blocked cases**, before acceptance mapping. Its existing
loop request is still tested in the default catalog as the ordinary uncredited
`get-contract-symlink-loop-cause-diagnostic` under `storage.path-safety`. The corrected report,
`.equivalence-results/get-contract-corrected.json`, records **70 matches, that one visible
OS diagnostic mismatch, zero blocked cases and no runner errors**. All 70 get-contract
cases match: 52 original source helper cases, six official definitions and 12 complete
whole-tool batches. Across the 13 batches including the diagnostic, all 66 requested
operations and 112 original text carriers are retained.

The filesystem cases explicitly map each side's exact owned temporary fixture base to
`$FIXTURE`, retaining workspace/outside suffixes, full error words, codes and every envelope
field. Raw carriers validate against details before that identity mapping, and originals
remain separately retained. Prefixes such as `/`, `/tmp`, another case or a sibling are
rejected; neither OS error wording nor result fields are normalized away. Relative extra
paths reach both real factories unchanged. Provider request observations compare all actual
fields with only the declared Python/native keyword-name mapping.

Independent review supports both get points within this portable profile. **124 provenance
and transport guards** pass, including required read artifacts, split helper/full-tool
profiles, complete operation counts and raw-carrier authority. The genuine get path uses
2,885 authenticated release files and no index workers. Official compiled execution remains
separate from a reproduced source build. Broad affected SDK/HostKit checks passed 340 tests,
and demo/LangGraph checks passed 460 tests before the cause-only refinement. Final committed
regressions, package consumers and the integrated gate are recorded below. The OS diagnostic
joins the existing Unicode path-order and warm first-recall differences; all remain visible
and uncredited. No paid provider call is required.


Final get regression checks on committed implementation
`c61dfdc2f503d2a232de97fdc8ce1026458bd668` passed **3,448 tests** in 154.80 seconds. The same
**1,625 historical/live skips** grant no acceptance credit. The official wheel/sdist script
also passed with networking disabled and existing cached dependencies: archive contents,
license/metadata, isolated core-only installs, dependency consistency, every module import,
real FTS HostKit flow and positive/negative public API typing. Logs are retained at
`/workspace/scratch/memory-core-get-contract-full-tests.log` and
`/workspace/scratch/memory-core-get-contract-distribution.log`. No further SDK or adapter
changes are planned; final integrated evidence follows below.


The final report, `.equivalence-results/get-contract-full.json`, executes all **1,086 cases**
against clean implementation commit `c61dfdc2f503d2a232de97fdc8ce1026458bd668`. It records
**1,083 matches, three ordinary mismatches, zero blocked cases and no runner errors**. All
**70 get-contract cases match**, including portable complete filesystem error causes,
provider-owned wiki payloads and actual trusted reader requests. Both get acceptance points
pass. This batch targeted **+2** and verified **+2**, increasing **35/128 (27.3%)** to
**37/128 (28.9%)**, a **1.6 percentage-point** increase. **91/128 (71.1%)** remain. The fixed
list now has **17 complete, three partial and 44 pending contracts**.

All **130 Python source files** are identified by SHA-256
`f9c2f69b97fb11b5b9e25595d58c504682acd3fed0609c903b90b0954bdb6ccf`. Current source and adapter
hashes still match this tested implementation. The scope hash remains
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`. The three
visible differences are `hybrid-unicode-path-collation-diagnostic`,
`get-contract-symlink-loop-cause-diagnostic` and `flush-execution-warm-index-first-recall`;
each retains `covers: []` and grants no acceptance credit. Original error causes and raw
carriers remain in retained evidence. Secure path admission and the SDK's stronger eager
index-readiness guarantee were preserved.

The full gate remains mismatched/incomplete because these diagnostics and 91 uncovered
points remain; this is not complete OpenClaw equivalence. No provider credentials were
forwarded and no paid model requests were made. This follow-up changes documentation only;
SDK source, differential adapters and the source inventory remain identical to the tested
commit. After review of batch sizing, the next package combines **`tools.deadline-cooldown`**
and **`tools.unavailable-partial`**, targeting **+4 conditions**, or **41/128** if verified.
These equal checklist conditions measure coverage rather than effort. No additional user
information is required.


### Shared deadlines, cooldowns and partial corpus results — 2026-11-08

This package targets all four original acceptance conditions in `tools.deadline-cooldown`
and `tools.unavailable-partial`, from **37 to 41/128**, without changing the fixed 64-contract
scope. Verification counts are unweighted: four conditions do not imply four equal units of
work or a fixed percentage of time saved. The final committed integrated report below verifies all four targeted conditions.

The SDK now shares an actual deadline/signal owner between search and get. Search separates
an original parent cancellation from a deadline created by its own owner; a provider error
with the same timeout text cannot manufacture that identity or poison cooldown state. It
checks the absolute budget at settlement, supports nested managed-readiness pauses for memory,
and preserves an independent wiki budget. Later explicit queries exercise cached cooldown,
configuration/provider invalidation, the exact expiration boundary and successful recovery.
Factory calls accept the trusted third signal argument. These are host execution options,
not model arguments.

`memory_get` now supervises wiki/all through the shared corpus deadline and preserves completed
excerpts when another registered provider hangs. Native builtin-only reads bypass that budget,
including the native pre-aborted-parent behavior; the port represents that branch explicitly.
Registered wiki callbacks receive the actual native request context and no invented provider
cancellation argument. An uncooperative callback can keep running in its daemon worker after
the coordinator stops waiting; late completion cannot revise the returned result.

Search timeout fallback uses a real pre-deadline memory-only snapshot. It does not start a
new keyword query after its budget expires or return session hits through that fallback. The
SQLite backend publishes keyword candidates and releases its read lease before waiting for
embedding, so a hung provider does not retain that writer-blocking lease. Revision changes
and provider rotation invalidate the snapshot. Five real SQLite regressions exercise early
publication, concurrent writing, immutable metadata, generation changes and provider failures.
Custom backends opt into the explicit partial-result protocol; legacy callbacks retain their
existing call shape.

The native comparison uses **18 original source-owner cases, 12 complete controlled search
factory cases and three complete get factory cases**. Actual Node builtin mock timers and
`performance.now` drive the unchanged deadline, corpus, query and cooldown owners. The SDK
uses its production clock/schedule/wait dependency and real signal workers. Controlled search
acquisition supplies literal backend results and skips the index-manager constructor. Get
uses an owned literal memory file and the actual secure reader without substituting a manager.
This verifies the declared execution contract, not live provider latency, index-manager startup,
transcript visibility, OS scheduling, or universal filesystem behavior. Reviewed source and
authenticated official compiled artifacts remain separate; `sourceBuildReproduced: false`.

Complete public envelopes retain warnings, partial flags, corpus outcomes, actions and actual
debug durations. The already declared text-carrier codec verifies complete details before
JSON decoding and retains raw wire envelopes. Provider observations preserve every event in
its backend lane; independent backend entry has no global ordering guarantee, and raw evidence
also retains the actual global interleaving. Actual control-clock cuts and provider counts are
compared without timing tolerances. Readiness/winning-provider barriers observe actual owner
settlement, rather than assuming a resolved provider promise has completed its wrapper.

Retained first observations and corrections:

- `.equivalence-results/deadline-partial-python-baseline.json` runs actual unchanged SDK commit
  `903729befb4bddefda65ce894c0072e24669d49f`. Its wiki get remains pending after **30,050 ms**
  of real waiting, then completes only after provider release. Its search diagnostic observes
  one fresh keyword query after timeout using the existing accelerated private duration
  converter; that accelerated diagnostic grants no native acceptance credit.
- `.equivalence-results/deadline-partial-first.json` is invalid with
  `implementation-changed`: a final production fix overlapped the run. Its 30 observations
  supply no credit. The report is retained rather than replaced.
- `.equivalence-results/deadline-partial-valid-first.json` has **30 matches, zero mismatches
  and three blocked get cases**. The get transport was valid; the root Python dispatcher had
  omitted its new operation route. `.equivalence-results/deadline-get-python-transport-first.log`
  retains the traceback. A routing regression now checks actual dispatch and full evidence.
- `.equivalence-results/deadline-get-corrected.json` executes the corrected three get cases:
  **three matches, zero mismatches and zero blocked cases**. Public adapter outputs did not
  change. Independent review approves the four-condition mapping under the declared profile,
  pending fresh committed integrated validation.

The source inventory now maps 116 actual upstream modules, adding deadline-control, shared
parameter-reader and input-error owners. Classifications remain 15 present, 46 partial and
three host-owned; presence is separate from acceptance. Absolute settlement checks also retain
a pending timer handle until cleanup, verified by real scheduler-cancellation assertions.

No paid model calls or credential-bearing fixtures are used. The full gate must keep the
three existing uncredited diagnostics and every remaining uncovered condition visible.


#### Final integrated validation

The fresh strict full report, `.equivalence-results/deadline-partial-full.json`, runs all
**1,119 cases** on clean implementation **`c40225f87da4ed4362d30bf7633011a7e6ca379c`**.
It records **1,116 matches, three mismatches, zero blocked cases and no runner errors**.
All **33 deadline/partial cases match**, and all four reviewed original acceptance conditions
pass. This batch targeted **+4** and verified **+4**: **37 → 41/128**, with **87 remaining**.
There are now **19 complete, three partial and 42 pending contracts**. These are unweighted
verification counts, not an estimate of engineering work or remaining time.

The report fingerprints **131 SDK source files**, SHA-256
`ea0397841aa7d2e7d30bda105b35d5c6353d4632088743aef3b4b6e2aa78a597`. The fixed reference remains
`bcfc88812a35243893585dbeca87ca41b48272ca`, scope remains 64 contracts / 128 conditions,
and scope SHA-256 remains
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`.
Source and authenticated release evidence remain separate; `sourceBuildReproduced: false`.
Incidental protected runtime workers belong to actual SQLite/plugin state; controlled search
and get receive no new memory-index-worker or index-manager construction credit.

The three ordinary diagnostics remain visible and uncredited, each with `covers: []`:
`hybrid-unicode-path-collation-diagnostic`, `get-contract-symlink-loop-cause-diagnostic`,
and `flush-execution-warm-index-first-recall`. Original error causes, full payloads and raw
observations are preserved. The SDK's stronger eager first-recall guarantee remains intact.
The full gate therefore returns **mismatched/incomplete**, not a full-equivalence pass.

The complete regression run passed **3,693 tests in 173.30 seconds**. The existing **1,625
historical/live skips** grant no acceptance credit. The offline distribution check built and
installed both wheel and sdist into independent consumers, exercised core imports and actual
FTS host lifecycle, accepted the valid public typing consumer and rejected six invalid calls.
Logs are `/workspace/scratch/memory-core-deadline-partial-full-tests.log` and
`/workspace/scratch/memory-core-deadline-partial-distribution.log`. Ruff, project-name consistency,
source-map validation, Node syntax and staged diff checks passed. No provider credentials
were forwarded and **zero paid provider calls** were made. Earlier invalid and blocked reports
remain retained as documented above. This final follow-up changes documentation only.

The proposed next related package is **`sessions.corpus-admission` +
`sessions.visibility-lineage`**, targeting **+4 original conditions**, or **45/128** if verified.
It tests which transcripts are admitted and which source-session results/read operations
remain visible after resets, trust changes and forgotten origins. This remains existing scope;
no new checklist conditions are added. No additional user information is currently required.


### Persisted session admission and authorized lineage — 2026-11-09

This package targets the four original conditions in `sessions.corpus-admission` and
`sessions.visibility-lineage`: **41 → 45/128** if verified. The fixed 64-contract scope and
its hash remain unchanged. Counts record verified conditions rather than equal units of
engineering effort. Acceptance remains at the last committed baseline until integrated
validation below.

The SDK now has an agent-scoped `MemorySessionCatalog` over its own durable SQLite schema.
Authoritative metadata, transcript generations, participants, archive bindings and memory
admission tombstones are separate facts. `MemoryCoreSessionCorpus` enumerates actual active,
retained and archive identities; manager admission then checks generated/maintenance kinds,
all-system projections and tombstones. The existing JSONL adapter remains separate. Native
binary database interchange, full archive publication and reset-hook orchestration are not
claimed by this catalog implementation.

`MemoryWorkspace` carries the actual projection hash, source coordinates, provenance,
activity time and exported byte size into indexing, including logical SQLite locators with
no corresponding transcript file. Genuine complete Zstandard reset/deleted archives are
read through the Python codec. Python versions before 3.14 use the normal `zstandard` core
dependency; later versions use standard-library `compression.zstd`. The existing 61 external
lock records and artifact hashes are unchanged; only the root dependency declaration is
added, and `uv lock --check --offline` validates it. Native codec edge behavior follows the
actual Node 24 frame reader; this does not close malformed/archive-cache boundaries in #27.

The trusted visibility context loads live catalog/archive/reset and spawned-session facts.
Search applies the actual visibility filter before source selection, result limiting and
withheld/debug counts, including partial and refreshed-manager paths. Ordinary visibility
can accept any authorized alias; private conversation recall requires every alias to remain
private and checks its anchor, requester, reset cutoff and archive reason. No requester
means no transcript hits. Bound requester/agent conflicts retain the native structured error
at the native stage; memory-only early return remains distinct.

`Memory` and `HostKit` capture the host catalog and visibility/source policies. Model arguments
cannot replace them or the actual requester in `SessionState`. The source-policy owner
separates indexed sources from ordinary query sources so remembered transcripts can be
available to trusted private recall without appearing in ordinary memory-only searches.
Static host policy affects configuration cooldown identity; live catalog content does not.
The [session authority guide](session_authority.md) documents actual SDK wiring and explicit
transcript persistence followed by index refresh. Automatic query sync and the durable
next-turn barrier remain separate contracts.

The guarded source-read profile authorizes a CURRENT session key through the actual history
access owner, resolves its current recorded identity and reads complete persisted events.
Incarnation-specific grants are rechecked where the native owner supplies an expected ID.
This is distinct from expanding a cached search-hit descriptor or proving an entire history
tool/UI. Memory tombstones remove memory admission without erasing otherwise authorized
source history. Persisted reset-boundary records are common input facts; no adapter generates
native lifecycle events or claims new/reset-hook equivalence.

The native comparison constructs the genuine provider-none index manager and actual session
SQLite stores. Main process and memory-index worker imports must be authenticated separately;
generic plugin-state worker counts cannot stand in for index execution. Tree/all ownership
lookups run the actual hosted in-process Gateway session-list handler and projection over
those stores, rather than a supplied list of visible keys. Initial archive records use the
genuine archive insertion owner and actual archive bytes; this is fixture preparation rather
than full archive-publisher lifecycle proof. Source and official compiled artifact authority
remain separate, with `sourceBuildReproduced: false`.

Before production changes, `.equivalence-results/session-contract-python-baseline.json`
ran the actual unchanged SDK at commit `9b0eaa9`: an ordinary tool call with no requester
returned a registered private transcript hit. The separate default-all diagnostic is retained
in `session-contract-python-baseline-default-all.json`; same-agent Bob-to-Alice visibility
under native ordinary `all` is not itself an authorization failure. Neither diagnostic adds
acceptance credit. The first broad development run is retained at
`/workspace/scratch/memory-core-session-visibility-broad-first.log` (2,693 passing regression
tests and three failing old authority/dependency/public-field assertions). The targeted
corrections preserve real catalog/requester/origins/fence behavior and require no weaker
visibility policy. Focused corrected results are retained separately.


The first formal 50-case report, `.equivalence-results/session-contract-first.json`, is
**blocked** and grants **zero** credit. Its first compressed archive fixture supplied numeric
`generation: 0`; the actual native persistence owner requires a nonempty owner generation
and failed before index acquisition. The subsequent missing-owner attestation error was a
consequence of that setup failure. The original failure row, raw state, trace summary and
diagnostic are retained as `session-archive-first-failure.*` under `.equivalence-results`.
The corrected initial archive facts use coherent nonempty generation, filename suffix and
creation time. Additional legacy generationless artifacts exercise the actual archive-reason
branches alongside canonical registry-backed artifacts; neither changes the fixed scope.

The native archive-reason helper currently omits the generation suffix accepted by the
archive-identity parser. The SDK preserves that actual behavior and does not claim universal
deleted-archive denial from that helper. Complete indexed results and explicit tombstone
behavior remain observable. No native guard or source authority was weakened to repair the
fixture.

Independent review also reproduced an actual SDK admission defect: a process-only incognito
key entered the ordinary durable catalog and transcript index. The corrected catalog routes
such state to a process-held SQLite owner, preserving private raw writes while excluding it
from ordinary catalog/disk/index views. The corpus also excludes those keys in its legacy
adapter. Native scoped history denies incognito targets before source lookup; it does not
grant private-self history access. This is part of the original admission/visibility scope,
with no added acceptance condition or full restart/host-lifecycle claim.

#### Integrated session acceptance results — 2026-11-09

The valid first full packet, `session-contract-corrected.json`, retained **43 matches, six
mismatches and one blocked case**. Corrections address real SDK ownership, not output
normalization: canonical session keys across the durable accessors, monotonic observed
transcript activity, native archive enumeration order and structured agent-owner validation
before tool arguments or provider/cooldown work. Test adapters now retain the compiled policy
helper's actual raw result and use each agent's real workspace, preventing an extra main-agent
memory file from changing peer-agent BM25 statistics. Scores are never rounded or tolerated.

The seven affected cases then matched in `session-contract-affected-corrected.json`. The fresh
50-case packet, `session-contract-final-focused.json`, records **50 matches, zero differences,
zero blocked cases and no errors**, on clean implementation `ce98aee`. Its original coverage
remains empty; reviewed coverage was registered afterward. The 38 helpers remain uncredited.
Five genuine persisted admission flows cover the two original admission conditions; seven
visibility flows cover outcomes, with only the deleted-archive and persisted-reset flows
covering the before/after source-read boundary.

The final strict full report, `.equivalence-results/session-contract-full.json`, runs **1,169
cases: 1,166 matched, three mismatched, zero blocked and no runner errors**, on clean tested
commit `ac2d366`. All 50 session cases match. The unchanged uncredited differences are
`hybrid-unicode-path-collation-diagnostic`, `get-contract-symlink-loop-cause-diagnostic` and
`flush-execution-warm-index-first-recall`. The full gate remains `mismatched`, with **83
conditions uncovered**. Source and official compiled authority stay separate; no paid provider
calls occurred and no provider credentials were forwarded.

This batch targeted **+4** and verifies **+4: 41 → 45/128 (35.2%)**. Contract status is now
**21 complete, three partial and 40 pending**. The fixed scope and hash are unchanged. These
are counts of verified conditions, not engineering effort or a completion-time prediction.
Participant evidence establishes admission metadata, not every participant-registry feature.
Current-key history reads do not claim arbitrary archive history or a complete history UI.
Literal reset facts do not establish generated reset hooks, and valid compressed archives do
not close the remaining malformed/cache boundary.

Full regressions passed **4,370 tests in 305.97 seconds**, with the same 1,625 historical/live
skips granting no credit. Both clean offline wheel and sdist consumers passed core/session/
compressed-archive lifecycle and public typing checks. Ruff, rename consistency, source-map
checks and diff checks passed. The regression log is
`/workspace/scratch/memory-core-sessions-full-tests.log`; package results are retained in
`.equivalence-results/session-distribution-final-offline.log`. This results update changes
only documentation; tested implementation and comparison adapters remain unchanged.

The next package targets durable context's **two original conditions**, or **45 → 47/128**
if verified. The actual compressed-cache diagnostic stays visible under transcript filtering;
it does not earn the remaining archive-boundary condition.

### Durable context across three fresh processes — 2026-11-09

This batch targets and verifies **two original conditions**:
`sessions.durable-context.outcomes` and `sessions.durable-context.boundaries`.
Acceptance advances **45 → 47/128 (36.7%)**, leaving **81 conditions**:
**22 complete, three partial and 39 pending contracts**. Both durable cases cover the same
two conditions; they do not create four points. The scope remains 64 contracts and its
SHA-256 is unchanged. Transcript filtering's remaining boundary stays open.

`MemorySessionCatalog.append_message` now owns ordinary JSON message persistence: header,
parent/branch selection, generation anchor, replay/conflict decisions and role-aware storage
redaction share one write transaction. `read_continuation` reads actual durable events and
metadata in one snapshot, reconstructing the selected context, full model messages and
non-persisted history-prelude markers. Current participant projections come from real SQL
records; session/lifecycle rotation persists the original recovery-clear patch. A raw import
keeps the first normalized nonempty event identity while preserving unidentified rows.
These are production owners, not comparison-adapter output changes.

The [durable session guide](durable_session_context.md) shows actual SDK wiring, provider
adapter responsibilities and reopen semantics. The current profile is ordinary JSON with
provider-none indexing. It does not claim provider-signed replay, media migration, pending
input custody, a complete host turn barrier or the separate host-restart orchestration.
Process-only private state is intentionally absent in new processes.

Each native and SDK case uses **three distinct, ordered fresh OS processes**: write, reopen
and continue, then reopen and verify. The next process receives literal identity/action
inputs and the same persisted root, never another process's reconstructed history or output.
Complete requests, hashes, exit status, stdout/stderr, SQL tables, source/index publication,
recall, model context, provenance and real append/read anchors remain retained. The third
process performs zero application upserts/appends and leaves observed metadata, events,
context and published SQL unchanged. Native integrity child processes and actual index
workers are separately authenticated; optional fast paths are not replaced with fake workers.

The only generated-identity codec maps actual valid append/read-anchor generations through
one cross-phase bijection and recognized producer store paths through an exact owner alias.
Raw values remain retained. There is no score tolerance, output sorting or expected-context
injection. Native settings genuinely force temporal decay enabled with a 30-day half-life;
SDK comparison uses that same effective policy and the literal phase wall clock. Original
Date and SDK decay-clock seams preserve real timers and performance clocks.

The first formal packet, `transcript-durable-first.json`, is retained as **blocked**. Its
validator incorrectly equated literal writer inputs with persisted output when the original
writer dropped a duplicate event identity. Original failed temporary raw state had already
been cleaned; that absence is recorded explicitly. The separately labelled exact reproduction
retains complete original stdout/raw/traces. The corrected writer attestation binds the exact
request to its genuine immediate post-write capture and subsequent reads. Generic rejected
runtime evidence is now captured before cleanup, explicitly unverified and without credit.

The valid corrected packet, `transcript-durable-corrected.json`, retained **six matches and
four differences**. Genuine SDK repairs address raw event identity and regular-file admission;
participant/recovery fields now come from their real owners. Ranking used mismatched effective
settings in the SDK driver; it now follows the original settings producer and common wall clock.
The fresh `transcript-durable-final-focused.json` records **nine matches, one visible cache
difference, zero blocked cases and no errors**, with both complete durable flows matching.
Its original coverage remains empty; independent review approved the two condition assignments
before registration. All eight source-boundary cases remain uncredited.

The final strict integrated report, `.equivalence-results/transcript-durable-full.json`, runs
**1,179 cases: 1,175 matched, four mismatched, zero blocked and no runner errors**. The original
three uncredited diagnostics remain; the fourth is
`transcript-boundary-compressed-same-size-mtime-cache-diagnostic`: the original reader returns
cached A after same-size, same-truncated-millisecond replacement while the SDK reads current B.
This remains an ordinary mismatch under transcript filtering, with no boundary credit and no
weakened SDK freshness. The full gate remains `mismatched`, not full equivalence.

Full regressions pass **4,521 tests in 290.04 seconds**, with the same 1,625 historical/live
skips adding no credit. Clean offline wheel and sdist consumers pass, including actual new
append, reopen/continuation and idempotent replay APIs, compressed archives and public typing.
Logs are `/workspace/scratch/memory-core-durable-full-tests.log` and
`.equivalence-results/durable-distribution-lifecycle-final.log`. The integrated report records
clean tested implementation `74162b9`; this results update changes documentation only.
No paid provider requests occurred and no provider credentials were forwarded.

## Verified Storage and Stored Turn Trust Batch

This fixed-scope batch targeted and verified **five additional acceptance conditions**, from
**47 to 52/128 (40.6%)**. There are **76 conditions remaining**, with **24 contracts complete,
four partial and 36 pending verification**. These are unweighted verified condition counts,
not a percentage of engineering effort. Discovery and workspace isolation each close both
conditions; configured redaction closes only its owner/taint/provenance boundary. Its regex,
mode and full-context outcome condition remains open. No acceptance scope was added or removed.

The final integrated report is `.equivalence-results/storage-turn-trust-locked-full.json`:
**1,239 cases, 1,235 matched, four visible uncredited differences, zero blocked cases and no
runner errors**, completed in 1,597.315089 seconds. Its clean tested commit is
`d3fc35ce86e99914d6a4d3dc667197ffa55504e1`, with 143 SDK source files and source SHA-256
`d7488a5523e3c868c7ee23725964c365de7685ff3d8aa5322033ea9f371830f0`.
The scope SHA-256 remains
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`.
Reference OpenClaw remains `v2026.9.9`, commit
`bcfc88812a35243893585dbeca87ca41b48272ca`. Runtime profiles use the authenticated
published release, with `sourceBuildReproduced: false`; they do not claim a rebuilt release.

Discovery evidence retains 76 actual original-source scenarios and their SDK counterparts,
including UTF-16 wildcards, Unicode 17 POSIX classes, roots, pruning, duplicates, symlinks,
non-regular files, disappearing sources and operational errors. Complete error type, message,
code, path and cause are compared; original language-specific exception facts remain raw.
The generic SDK IO bridge follows the original Node system-error facts rather than rewriting
individual test results. Glob parsing uses the declared `bracex` and `wcmatch` dependencies;
the Unicode facts have a reproducible exact-runtime generator and Unicode license notice.

Three genuine workspace lifecycles reuse one original multi-agent configuration and one SDK
host configuration across selected subjects. The predeclared host-routing mapping preserves
both actual configurations and namespaces. Real files, index publication, recalls, daily
checkpoint state and handle reopen are observed. Direct mismatched workspace configuration
now fails before side effects. This proves the stated workspace/subject boundary; it does
not claim interchangeable database schemas or the separate full process-restart contract.
The complete 79-case focused storage/error report is retained as
`storage-boundaries-full-errors-79.json` in the storage worktree.

Two original AgentLoop flows exercise actual registered local/network tools, failed network
execution, controlled retries, new owner/non-owner turns, sticky file quarantine, assistant
trust stamping and a fresh-process stored-session reopen. The only source substitution is
one authenticated, unchanged, dependency-free original turn-taint module; all other owners
remain in the official runtime. Its explicit mixed-source profile is separate from the
ordinary release profile. Complete outer tool returns/errors, messages, live trust, artifact
records and stored source provenance are compared. Native coding-tool presentation and
internal diagnostic hashes remain raw and are outside this declared outer-tool comparison.
The original failed-network hash prefix is validated from the actual thrown outcome; no
hash is fabricated or rewritten. The first rejected validator capture remains unverified;
the corrected two-case report matches both cases.

The final run uses **Node 24.16.0, ICU 78.3, Unicode 17**, with executable SHA-256
`b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd`, and Python 3.12.14
with the declared locked `bracex 3.2.2` and `wcmatch 10.2.1`. Preliminary package resolution
failed because registry range metadata was absent from the offline cache. The superseded
full comparison was explicitly cancelled and retained as unverified before updating the
older local glob dependencies. The first full regression run also exposed a stale test
expecting an unmasked token from a now-redacted tool diagnostic; the exact masked expectation
was corrected. No production policy or failed result was weakened to pass these checks.

Fresh full regressions pass **4,768 tests in 345.14 seconds**. The same **1,625 historical/live
skips add no credit**. Both clean offline wheel and sdist consumers pass: core-only imports,
real dispatch, live write provenance, stored trust, append/continuation/replay, Unicode glob
facts, fail-closed workspace ownership and public typing. Evidence logs are
`/workspace/scratch/memory-core-storage-trust-locked-full-tests.log` and
`.equivalence-results/storage-trust-distribution-locked-deps.log`.

All four ordinary uncredited differences remain visible: Unicode path collation, symlink-loop
cause shape, first recall during a native background refresh, and same-size/same-millisecond
compressed transcript cache freshness. No score tolerance or diagnostic reassignment hides
them. The full gate remains **mismatched**, not full equivalence. There were zero paid provider
calls and no provider credentials forwarded. This closeout changes documentation only.

### Entry provenance and serialized SDK host closeout — 2026-11-09

The fixed scope remains 64 contracts / 128 conditions, SHA-256
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`.
This batch targets and verifies **two conditions**, from 52 to **54/128 (42.2%)**:
both `chunking.entry-provenance` conditions require all three complete comparisons:

- `entry-provenance-canonical-collision-invalidation`: genuine ID upsert, unchanged
  and same-size changed source invalidation, complete published state and SQL.
- `entry-provenance-provider-entry-fragments`: actual original text preparation and
  source-index kernel, ordered byte-limited fragments and retained entry spans.
- `entry-provenance-session-provenance-replacement-reset`: real persisted session
  replacement, revision/provenance refresh, line mappings and valid/invalid reset fences.

The clean integrated implementation is `2a56ed8fed789668af77333f0c7e31ff495d3231`:
150 SDK source files, SHA-256
`61088d9e3eb8fd20b107fa9bda2c653ec1c34fb857b7e41a3af0b38904cd313d`.
The full report is `.equivalence-results/host-publication-entry-complete-pipe-full.json`,
SHA-256 `bd33601f27e6c427becb3834add45078c7cf3af20eb0153dea1084d09ed5042d`.
It completed in 1,844.807131 seconds: **1,303 cases, 1,291 matched, 12 mismatched,
zero blocked and no runner errors**. All three required entry profiles matched.
All 5,519 regressions pass; the same 1,625 historical/live skips add no credit.
Both clean offline wheel and sdist consumers were verified on `67e3051`, with the
identical SDK source hash; subsequent changes affect documentation, report transport
and tests. Installed consumers exercise save/immediate recall/reopen and reject ten
invalid typed API calls. No paid provider calls were made.

The SDK now also exposes the serialized host turn flow, durable publication intent,
committed/uncertain outcomes and an explicit current-memory acknowledgment API. These
checks cover real producers, partial IO, cancellation and later turns. The lane is
for cooperating runners in one process; it does not establish cross-process custody.
Its stronger uncertainty policy and the atomic writer development fixes grant no
`host.turn-barrier` or `storage.atomic-writes` conditions in this batch. The earlier
atomic development packet remains 31/32 with its physical-receipt difference, rather
than being presented as a successful protected whole-operation proof.

The four earlier uncredited differences remain visible: Unicode path collation,
symlink-loop cause text, compressed same-size transcript cache freshness and first
recall after a warm flush index. The 61 added redaction/model boundary cases contribute
53 matches and eight additional ordinary differences: four source regular-expression
engine differences, two original-input identity reuse differences and two session
regular-expression engine differences. None receives condition credit. In particular,
no strong global cache retaining raw secret inputs was added to imitate a WeakMap.
The historical small collector's reported 6/6 was corrected to its actual 4/6; the
original failed artifact and correction remain retained, with no credit from either.

Two integrated attempts failed and remain retained. The first attempted report
(`host-publication-entry-full.*`, implementation `67e3051`) could not encode a genuine
lone UTF-16 surrogate to UTF-8; its empty output is not evidence of any case count.
The escaped-JSON rerun (`host-publication-entry-escaped-full.*`, `af9988b`) retained a
blocked report: the genuine model-session UTF-16 boundary child's synchronous stdout
write hit `EAGAIN`, leaving partial JSON and exit code 1. Its original streams and
unverified traces are retained. The transport now writes one complete JSON envelope
and awaits the actual stdout callback, without rerunning a model operation. The exact
failed case then matched in a fresh protected comparison; 115 focused transport/guard
checks include a complete two-megabyte Unicode output. The successful full run above
follows those fixes; the failures were not discarded or converted into matches.

Reference execution uses the authenticated official compiled release and the exact
approved Node 24.16.0 / ICU 78.3 / Unicode 17 binary. `sourceBuildReproduced` remains
false. **74 conditions remain unverified**, and the full gate remains `mismatched`.


### Atomic, path, budget, bootstrap and ranking closeout — 2026-11-09

The fixed scope remains 64 contracts / 128 conditions, SHA-256
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`.
This batch targets and verifies **eight conditions**, from 54 to **62/128 (48.4%)**.
These are unweighted acceptance counts; they do not measure engineering effort.
There are **66 conditions remaining: 28 contracts complete, six partial and 30 pending**.

| Requirement | Required outcome families | Required boundary families | Verified conditions |
| --- | ---: | ---: | ---: |
| `storage.path-safety` | 11/11 | 11/11 | 2/2 |
| `storage.atomic-writes` | 41/41 | 32/32 | 2/2 |
| `compaction.memory-budget` | 13/13 | 13/13 | 2/2 |
| `prompt.bootstrap-discovery` | 9/9 | 9/11 | 1/2 |
| `promotion.ranking-gates` | 15/15 | 15/16 | 1/2 |

The fresh full comparison ran on clean implementation
`21177bf519e3e0d2b07454b32fc9734fd7361bbf`: **155 SDK source files**, SHA-256
`38f3c9ce2fcca74060c81b01ad17f893d6a5cd5d186061eed1a2f9158929192d`.
The retained report, `.equivalence-results/atomic-path-budget-bootstrap-ranking-full.json`,
has SHA-256 `6bd983bcbb1ec99e40e757f544085bd036f38e02c37ef212a987794e1650f2eb`
and contains 274,817,208 bytes. From 07:14:50 to 07:52:42 UTC it executed
**1,395 cases: 1,381 matched, 14 ordinary differences, zero blocked and no runner errors**,
in 2,272.705012 seconds. No previously matching case regressed. The earlier get-tool
symlink-loop cause diagnostic now also matches. All original 1,303 cases remain,
with 92 new registered families; source inventory itself adds no credit.

The real SDK changes include checked-descriptor reads, primary/cleanup error preservation
and no-replace publication, identity-aware budget markers and newline-preserving preimages,
actual bootstrap path/provenance classification, and canonical recall/phase views with
JavaScript numeric gates and scoring. Embedding batching/cache corrections are included
as production improvements, with **no embedding-cache condition credit** in this batch.
The narrow upstream plugin identifier remains stable across SDK rebranding.

Detailed source, authority, raw-channel and first-failure limits are retained in the
[atomic closeout](../equivalence/ATOMIC_PUBLICATION_CLOSEOUT.md),
[path proof](storage_path_safety_proof.md), [budget closeout](memory_budget_closeout.md),
[bootstrap proof](bootstrap_discovery_equivalence.md) and
[ranking closeout](promotion_ranking_closeout.md). Independent executable/source/backend
capabilities are mutually exclusive; exact operation, input-kind and complete reviewed
literal guards run before imports where required. The real atomic return checkpoint
remains distinct from process-exit cleanup. The read-race hook is confined to its one
reviewed fixture in the main thread. No worker, source or provider authority is borrowed
from another lane.

The first full regression run on `21177bf` is retained unchanged in
`.equivalence-results/atomic-path-budget-bootstrap-ranking-regressions.log`:
**6,432 passed, one failed, 1,625 skipped** in 529.42 seconds. Its sole failure injected
an error through `Path.read_bytes`, which the checked-descriptor reader no longer uses.
Test-only commit `27ec24bd73f4019d194902568a866c95a34df6ea` injects the same real read error
through `os.read` on the actual target descriptor and verifies one attempted read and
redacted public diagnostics. It changes no SDK, adapter, catalog or Native runtime bytes.
The fresh clean full rerun at that commit passes **6,433 tests, zero failures and the same
1,625 historical/live skips** in 499.41 seconds. Its retained log is
`/workspace/scratch/memory-core-equivalence-next-regression-fix/.equivalence-results/atomic-path-budget-bootstrap-ranking-regressions-read-fault-fixed.log`.
Both clean offline wheel and sdist consumers pass on `21177bf`, with the identical SDK
source hash, including real save/immediate recall/reopen and ten invalid typed calls.
The first failed run was not replaced by the passing rerun.

The 14 visible differences comprise the earlier Unicode collation, compressed same-size
transcript cache and first warm-flush recall diagnostics; eight redaction/identity/regex
boundary differences; two bootstrap default-layout/legacy-state selection differences;
and the stronger rejection of malformed primitive promotion provenance. The latter
three still cover their registered boundary conditions, which therefore remain open.
No raw-secret strong cache or weaker trust admission was introduced for matching results.
The report has 64 uncovered conditions plus these two covered-but-unverified conditions;
**64 uncovered does not mean only 64 conditions remain**.

Reference execution uses the authenticated official compiled release, exact pinned source
and approved Node 24.16.0 / ICU 78.3 / Unicode 17 binary. `sourceBuildReproduced` remains
false. There were **zero paid provider calls and no forwarded provider credentials**.
The full gate intentionally remains `mismatched`; these bounded results establish neither
complete OpenClaw equivalence nor the still-unverified host restart/turn conditions.


### Promotion application and reconciliation closeout — 2026-11-09

This batch targets and verifies **two existing conditions**, from 62 to **64/128
(50.0%)**, with **64 remaining**: 29 complete, six partial and 29 pending contracts.
All eight exact family wires execute against the genuine pinned original apply
and real SDK owner. The strict registration rejects a missing family or changed
literal/owner/coverage before comparison. The old one-input capability remains unchanged.

The clean integrated implementation is `b090394d2729031cf239619b7ed7bbeecac8f379`:
156 SDK files, SHA-256 `0944d2bcdd15096e59e1ec3715d47e57013427fec85dc47c541fa176c8739997`.
The complete report is `work/promotion-apply-integrated-full.json`, SHA-256
`df6e393b4f0affb17db5058506c54d8b58bfef5438a2c993c59886131c55d5dc`,
428,615,477 bytes. It executes **1,403 cases: 1,389 matched, 14 mismatched,
zero blocked and no runner errors**, in 1,460.268716 seconds. Every promotion apply
case matches both conditions. All 6,759 regressions and both clean offline wheel
and sdist consumers pass; 1,648 historical/live/optional transport skips add no credit.

The production correction sends JavaScript-compatible numeric text in actual model
requests (`1.0` becomes `1`, including correct negative-zero/exponent handling).
It changes the consolidation prompt serializer, not expected outputs or the global
bootstrap serializer. Callback requests/results are actual comparison data.
Original physical recall carriers remain distinct from actual original normalized
API reads; real exported normalization/retention observations establish that mapping.

The [detailed closeout](promotion_apply_reconcile_closeout.md) preserves blocked
preparation reports, real differing before requests, adversarial guard failures,
consumer cache setup failure and limits. The named origin fixture does not create
an agent-origin row after original provenance normalization; no general origin,
model-plan, worker SQL transaction or host restart condition is claimed. Exact
Node 24.16.0 / ICU 78.3 / Unicode 17 and official artifacts remain authenticated;
source-build reproduction remains false. There were no paid provider calls.

The report retains **62 uncovered conditions** plus the two covered-but-unverified
bootstrap/ranking boundary conditions: **64 remain**, not 62. All 14 differences
stay visible and the full gate remains `mismatched`.


## Shared managed-host restart acceptance (2026-11-10)

The [shared managed-host closeout](host_restart_session_closeout.md) verifies the two
original `host.restart-recall` conditions: **64 → 66/128 (51.6%)**, **62 remaining**.
Its fresh full catalog on clean `9d13b19` contains **1,407 cases: 1,393 matched,
14 mismatched, zero blocked and no runner errors**. All four new closed-family
cases match with verified process, source, publication and real-error custody.
The prior 1,403 case definitions and all earlier restart diagnostic captures remain unchanged.

The SDK shares one actual owner across chats, preserves read generations, publishes
memory separately from pending sessions, and guards catalog acknowledgments with
an atomic revision CAS. Eager defaults retain their full publication barrier.
Full regressions pass **7,138 tests**, with **1,648 uncredited skips**; both offline
installed artifacts and **24 negative public typing cases** pass. The full gate
remains `mismatched`: **60 uncovered conditions plus two registered unresolved
boundaries** remain. No full OpenClaw-equivalence claim follows.

The next original contract is `host.update-isolation` (#64): replace a preference,
retain unrelated facts and independent users/workspaces, and report genuine write/index
failures. For example, changing tea to coffee must update later recall while preserving
another user's records. `host.turn-barrier` (#62) remains a separate contract.


## Host update/isolation acceptance (2026-11-10)

The [host update/isolation closeout](host_update_isolation_closeout.md) verifies the two
original #64 conditions: **66 → 68/128 (53.1%)**, with **60 remaining**. Clean
`57270da` executes **1,411 cases: 1,397 matched, 14 mismatched, zero blocked and no
runner errors**. All four closed update-family cases match with authenticated Native/SDK
source, dispatch, real-fault, publication and complete retrieval custody. Earlier restart
inputs and all prior 1,407 case definitions remain unchanged.

The direct managed-curator readiness gap is corrected: a real retained publication failure
keeps the owner pending, including after close, until actual matching recovery. Full
regressions pass **7,797 tests** with **1,648 uncredited skips**; both offline installed
artifacts and **24 invalid typed-call checks** pass. All **490 evidence tests** execute
against genuine retained Native data with zero evidence-fixture skips. Replay data is
explicitly labelled and adds no extra execution or credit.

The full gate stays `mismatched`: **58 uncovered conditions plus two registered unresolved
boundaries** remain. The next original host contract is `host.turn-barrier` (#62): verify
natural save and immediate follow-up, required maintenance settlement, optional maintenance
preemption and visible failure without inserting forced publication before the next turn.


## Natural host save/follow-up outcomes (2026-11-10)

The [natural next-turn closeout](host_turn_barrier_closeout.md) verifies the original
`host.turn-barrier.outcomes` condition: **68 → 69/128 (53.9%)**, with **59 remaining**.
Contract #62 is now **partial, 1/2**. Clean `d306944` executes **1,415 cases:
1,401 matched, 14 mismatched, zero blocked and no runner errors**. The four frozen
cold/warm ASCII/Unicode cases match with authenticated full Native caller admission,
actual tool/model/source/reply custody and complete public results.

The opt-in SDK `on-search` policy reproduces the original warm read generation and
admits a genuine background publisher. Cold reads retrieve the newly committed fact;
the populated warm control succeeds, then the immediate new-fact search returns empty
on both engines. Scripted replies follow actual memory-tool results; this does not
measure a language model's ability to answer from its existing conversation history.
No forced publication, maintenance wait or timer drain precedes the follow-up.

Full regressions pass **8,194 tests**, with the same **1,648 uncredited skips**.
Both offline installed artifacts and **24 invalid typed-call checks** pass. The
**252 actual retained-evidence tamper tests** and **39 capability tests** add no
acceptance credit by themselves. Retained failed attempts keep their own identities.

The full gate remains `mismatched`: **57 uncovered conditions plus two registered
unresolved boundaries** remain. Next is the original `host.turn-barrier.boundaries`
condition: measure pending optional preemption, actual running-producer settlement
and honest failure visibility before the next admission. The current SDK owner still
runs optional maintenance inline; that boundary is not closed by this packet.

## Update capture and CI follow-up (2026-11-10)

The [update closeout](host_update_isolation_closeout.md#capture-and-ci-follow-up-2026-11-10)
records four later infrastructure corrections: the original home-relative refusal
spelling, explicit ranking/prompt limits, a disappearing diagnostic lease journal,
and hosted capture retention/replay. Clean integrated `c45cb03` matches all four
actual Native/SDK cases, with zero blocked cases or runner errors. Independent
custody/trace replay and 163 artifact hashes pass; all eight public results match
the prior update-family baseline. SDK, frozen literals and fixed scope are unchanged.

This reruns an already verified family and grants **+0**: the overall baseline stays
**69/128 (53.9%)**, with **59 remaining**. It does not replace the previous complete
catalog or resolve its 14 differences. The next acceptance target remains
`host.turn-barrier.boundaries`, covering maintenance/failure before the next admission.


## Full-channel maintenance boundary acceptance (2026-11-10)

The [boundary closeout](host_turn_barrier_boundaries_closeout.md) verifies the
existing `host.turn-barrier.boundaries` point: **69 → 70/128 (54.7%)**, with
**58 remaining**. The final clean `b27624d` complete catalog validates the
coherent-source SDK: **1,421 cases, 1,407 matches, 14 existing differences,
zero blocked and no runner errors**. It confirms the same 70, not 71.
All 1,415 earlier definitions/statuses, 12 earlier evidence flags and the other
127 original point records remain unchanged. The gate remains `mismatched`.

Actual pristine full-channel dispatch uses its own original reply operation.
Pending optional preemption, running maintenance, real failures and an actual
pre-model target-open lease are measured. In-flight append cancellation and
unowned provider cleanup are not claimed. The corrected SDK passes **8,670 general
tests** with **1,648 uncredited skips**, both installed artifacts and **27 invalid
typed calls** each. Historical failures, initial SDK identity and the separate
validator-only hosted follow-up retain their actual records and grant no extra point.


## Index identity pre-query boundary acceptance (2026-11-10)

The [identity boundary closeout](index_identity_boundaries_closeout.md) verifies
only the original `indexing.identity.boundaries` condition: **70 → 71/128 (55.5%)**,
with **57 remaining**. Clean `5856b4e` executes **1,437 cases: 1,423 matched,
14 mismatched, zero blocked and no runner errors**. The 16 independently frozen
pairs retain complete pre-query identity diagnostics, actual first-search results,
real owner/publication/import/process/SQL custody and unchanged source bytes.

All earlier 1,421 definitions/statuses/annotations, 18 evidence flags and the other
127 point records are unchanged. The two Native first-recall result arrays in one
already-declared zero-credit warm diagnostic vary with background publication;
its complete SDK payload and the other 13 mismatch payloads remain identical.
That diagnostic remains mismatched and uncredited. Full regressions pass 9,757
tests with 1,648 uncredited skips; fresh evidence replay passes 981 with zero skips.
Both installed artifacts and 27 invalid typed calls each pass. The full gate
remains mismatched, with 55 uncovered and two registered unresolved conditions.
