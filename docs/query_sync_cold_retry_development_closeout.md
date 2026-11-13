# Cold query retry development closeout

Prepared 2026-11-12 (Europe/Istanbul). The production fix and bounded pair
are verified. The fresh complete gate **fails**: **71/128 conditions**, with
**57 remaining**. This closeout retains that loss of one previously verified
condition rather than reporting the historical 72 as a current result.

A cold memory search can now recover after a temporary index-publication failure
is removed. Previously, the SDK remembered the first failure and prevented the
next search on that same owner from attempting the otherwise eligible bootstrap.
The original Native implementation retried and found the source. The SDK now
performs that real retry under the explicit `on-search` policy for an empty index.

This is a bounded, **zero-credit development package**. Its two cases have
`covers=[]`, are not registered in the acceptance catalog, and do not establish
`indexing.query-sync.boundaries`. The fixed scope remains 64 contracts and 128
conditions; all 1,444 registered case definitions remain unchanged. The historical
independently audited `aa99a933` report verified **72/128**, with 56 remaining.
The current clean `e148d0b` comparison verifies 71/128: the separately observed
`host.turn-barrier.outcomes` condition loses credit in this run. The original
72/128 report retains its historical SDK identity and result.

## Frozen inputs and genuine before/after observations

The two input-only schedules were frozen before execution. The manifest is
`docs/query_sync_cold_retry_development_literals.json`, **8,680 bytes**, SHA-256
`1a374d6f1f54a3b59d033bf56014b21e6d8c0bde268277f64d030104b6a3fa1f`.
Every retained attempt uses those same inputs; no expected search result or
bootstrap count supplies the comparison. The complete common wire is separately
declared in `docs/query_sync_cold_retry_common_wire.json`.

| Actual attempt | Tested commit | SDK source | Complete result |
| --- | --- | --- | --- |
| `cold-retry-baseline-001` | `750e0b8` | `a5972f3e…` | Invalid initial packet: two blocked guard results; raw observations preserved |
| `cold-retry-baseline-002` | `1099428` | `a5972f3e…` | One match, one mismatch; 23 differences, zero blocked, no runner errors |
| `cold-retry-corrected-001` | `05385b0` | `20abf913…` | Two matches; zero differences, zero blocked, no runner errors |

Each report records successful final source/adapter authentication. This does not
turn the invalid first attempt into a valid schedule. In that first attempt,
canonical request serialization reordered JSON object keys; the Native caller
mistakenly used that object order and executed `afterRemoval` while the fault was
armed. Both callers now take execution order from the frozen `steps` array.
A separate initial guard defect compared final public hits to an earlier empty
Native preparation. The guard now authenticates every actual generation and
binds final public hits to the last real preparation. Neither first report nor
its inputs, labels, results or raw captures was rewritten. Only the corrected
valid baseline supports the production bug finding.

The clean control performs two actual searches over an existing source. Both
engines publish on the first query and avoid another bootstrap on the unchanged
second query. In the refusal case, the actual first query returns unavailable
with no hit and one actual bootstrap attempt on both engines. After the fixture
removes only its owned filesystem fault, the next query uses the same exact
still-live owner. Before the fix, Native retried once and returned one hit while
the SDK attempted no bootstrap and remained unavailable. After the fix, both
retry once and return the same complete public JSON.

The valid baseline and corrected runs preserve every Native public result, the
SDK clean-control result and the SDK first faulted payload exactly. Only the
SDK recovery behavior changes. Full warnings, actions, error and debug fields,
search arrays, numeric scores and source observations remain in the comparison;
no projection, tolerance, missing-field repair or automatic comparison retry is
used. All complete report hashes and independent proof references are in the
companion diagnostics.

## Production change and preserved policy

Commit `05385b0188fe3153fe575832ec6944eb9af9c0fa` changes one of the 160 SDK
production files: `memory_core/host/managed_index.py`. The other 159 production
files are unchanged. The aggregate implementation SHA-256 changes from
`a5972f3e37bcf97bce7f7cda82ef52b99226882b7a14bd87f094a9ba1219b70d` to
`20abf913ac4d7d394aacbcad73e63ad14968c4f2d485ea2a3c0684413d40237d`.

The change allows an otherwise eligible empty `on-search` owner to attempt one
bootstrap on its next nonempty public query despite a retained whole-publication
failure. A persistent physical refusal still causes one real failed attempt per
query and leaves the index unpublished. Successful original publication clears
the actual error; the fixture does not reset error state or replace a result.
The ordinary `on-write` policy, warm-index explicit recovery and restrictions on
newer or configuration-mismatched identities remain in force. Seven new real
filesystem regression instances cover recovery, persistent refusal, clean repeat,
those two recovery policies and the two identity guards.

## Original entrypoints and independent custody

Native calls its original manager facade and public `memory_search` factory.
The SDK calls its original managed owner and public search factory under the
declared provider-none `memory_publication="on-search"` profile. Every query
resolves the observed original receiver; no manager is reopened between queries.

The fixture arms a real dangling symlink at the actual acquired owner's
publication sidecar: Native `.reindex-lock.sqlite`, SDK `-journal`. These are
declared engine-specific mechanisms. Actual path/stat/readlink receipts and the
original SQLite failure show that the fault affected publication. After the
first complete public return, the fixture unlinks its own unchanged symlink,
restoring its actual original sidecar state, and immediately calls the next
query. Source bytes remain unchanged. There is no intervening manual sync,
private wait, reopen, extra query or timer drain. Original close runs only after
the two public calls and joins already-admitted work.

The guard independently validates whole original envelopes and text/details
carriers; exact-owner calls; actual repair journals; physical sources and SQL;
Native held generation leases and worker replies; SDK pinned reader connections
and lifecycle admissions; real fault identities and syscall receipts; original
imports; and original V8 bytes decoded with an independently trusted approved
Node executable. An untrusted captured executable is never decoder authority.
The initial unavailable response legitimately may precede SDK reader admission.

Shared counters describe actual manager search entries and actual bootstrap
admissions per public call. Native `syncAdmitted(reason="search-bootstrap")`
entries and SDK repair-journal requests, cross-checked against original reindex
entries, supply those counters. Internal worker/task totals, full private API
shapes and binary SQLite identity are retained separately without an identity
claim. OS receipts come from original call-through observers, not an independent
kernel syscall trace.

## Completed bounded and complete checks

The valid baseline was independently audited before changing primary SDK bytes;
its original 160-file SDK and actor inventory is sealed. That audit rehashed 76
artifacts. The corrected independent audit rehashed 77, reauthenticated the
original source/import authority and recomputed the complete equality. Original
caller and collector bytes are unchanged between the valid baseline and corrected
comparison; the evidence guard was independently hardened.

Genuine-capture adversarial replay passes **119 tests with zero skips** before
the fix, in **30.61 seconds**, and **119 with zero skips** after the fix, in
**30.06 seconds**. Pair custody deliberately accepts an honestly captured
mismatch; the collector separately compares the complete common result. The
invalid first schedule remains a negative regression, never a positive witness.

The separately recorded pre-fix capability/SDK helper command passes **58 tests
in 19.13 seconds**. The isolated production-focused commands pass **74 tests** in
1.92 seconds and an independent 1.67 seconds. Those two 74-test observations
were actual tool outputs, not standalone saved logs; no path or hash is invented
for them. These command totals overlap and are not added as unique tests.
Both callers include regressions for sorted JSON transport and invalid ordered-step schedules; the completed 10,159-test whole regression run covers their current versions.

The original complete CLI on clean `e148d0b2532842c3113f1ae6a2bd18d9c94364be`
executes **1,444 cases: 1,429 matched, 15 mismatched, zero blocked and no runner
errors**. PID 11643 actually exits **1** after **2108.745164 seconds**;
before/after SDK and all **298 protected adapter files** remain unchanged.
The full report is **655,848,148 bytes**, SHA-256
`0b3c8eb8a69f675a588766b0b13c3ea101edb971715bc683bdeb68b8bea095a9`. Original launch, seal, actual exit receipt and report
remain attributed to that execution; this documentation commit does not retag them.

Independent review authenticates the report and preserves its failed gate:
**71 verified / 57 remaining**, comprising **54 uncovered and three registered
unresolved conditions**; **32 complete, seven partial and 25 pending contracts**.
All 1,444 complete builder definitions, 80 builder-only annotations, 41 prior
evidence flags and 127 of the 128 original point records remain unchanged.
The report historically omits 79 `fixtureSource` and one `diagnosticOnly` builder
annotations; they are independently checked in the frozen builder, not invented
inside the report. All 23 current query/identity pairs replay with their complete
public results equal to the earlier local baseline. Legacy identity captures use
their actual protected PID/parent/import-trace carrier; per-module SDK hash lists
and a separate `process.json` are not invented for that older profile.

The original prepared auditor stopped on an incorrect assumption about matched
case links for a failed atomic family. That failure is retained. The supplemental
review follows the sealed harness's actual closed-family rule and records the
genuine failure. Review: `work/query-sync-boundaries/independent-review/full-001-actual-independent-review.json`,
SHA-256 `c67e76f45cc9e2666f962cd998db0d0f4f57d66c3091708c561fc4f629c62b95`. It adds no credit.

Whole regressions on the same clean `e148d0b` pass **10,159 tests, zero failures
and 1,658 uncredited skips in 552.02 seconds**. The process exit is observed as
**0**, with unchanged SDK/adapter identities. Log:
`work/query-sync-boundaries/regressions-001.log`, SHA-256
`372af697cb6eade2fe8affff7449858e10d5b4348599c68bd8b452337629f5a4`. These tests run after the fresh full captures exist;
historical SDK bytes are not relabeled as current-source replay evidence.

Code-head GitHub package run `43228096214` on `e148d0b` passes on both
Python versions: job `131216449713` (3.11), **7,850 passed, 3,967 uncredited skips**,
607.90 seconds; job `131216450104` (3.12), the same counts in 623.03 seconds.
Both installed wheel/sdist consumers and 27 invalid typed-call checks per
artifact/version pass. Exact job logs and observed completed job states are
retained. The separate Native run `43228096177` remains in progress at documentation preparation;
no completed differential conclusion is inferred. Later documentation-head workflow results belong in PR metadata; no future pass is claimed.

## Newly observed local notice mismatch

The new fifteenth local mismatch is `host-turn-barrier-cold-unicode`.
The current Native result omits exactly `followup.search.warning` and
`followup.search.corpora`, which were present in its previous local capture.
Its source bytes, hits, ranking, provenance, `memory_get` and final reply are
unchanged. The complete SDK result is exactly equal to its previous local
result. Original Native caller bytes, case inputs, Node binary and official
compiled authority are also unchanged. This case establishes no introduced
SDK public-output regression; it does establish a current verification gap.

The strict four-case outcome family requires all four complete matches, so
`host.turn-barrier.outcomes` loses credit. No field is omitted from comparison,
no historical variation allowance is added, and the report is not retried to
select a passing run. All original fourteen complete Native and SDK mismatch
payloads remain unchanged; even the previously allowed warm diagnostic arrays
have zero actual changes in this run.

Original notice source emits the warning when its live sequence changes after
capture; tool assembly includes `corpora` for that warning. The actual older
Native host capture lacks before/after numeric notice counters and a unique
sync-route trace. A scheduling explanation is source-supported but **not proved**
by these captures. The next priority is narrow call-through observation of those
original notice/status/publication events, preserving ordinary host calls and
complete results. The original query-sync force/retry/count boundaries also
remain open.

## Unchanged scope and evidence availability

The fixed scope SHA-256 remains
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`.
The all-field canonical SHA-256 of the unchanged 1,444 registered definitions is
`feea3f91ed24646488b241e6dd739d737c05d25d5c71e724e2febd14b349ece7`.
The new standalone packet awards zero. Broader forced-sync/joining and retry
boundaries, other unavailable schedules, semantic or paid providers, vector
transport and complete OS watcher timing remain unverified by these two cases.

The source inventory has **238 upstream modules**, with **18 present and 46
partial** counterpart classifications. This package authenticates **55 original
source pins, 29 official compiled pins and 37 named import links**. Source,
official release and actual execution remain separate authorities; no independent
source-to-release build reproduction is claimed. Source inventory adds no score.

Raw captures, physical databases and logs under ignored
`work/query-sync-boundaries/` are retained locally; a git push does not upload
them. CI is configured to create its own fresh evidence and retain a separate artifact.
The Native job was still running at this closeout's preparation. The later
[notice observation closeout](next_turn_notice_observation_closeout.md) records
the subsequent work without relabeling this package's captures. This
tracked closeout and diagnostics cite completed evidence without presenting
local ignored files as already downloadable GitHub artifacts.

The older four additional hosted differences remain a separate unresolved issue.
Their investigation and artifact access are still paused at the user's request.
No older hosted artifact was accessed, downloaded or analyzed for this package.
