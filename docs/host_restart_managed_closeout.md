# Host restart producer publication and managed index — 2026-11-09

This package adds a real optional managed cold-index owner and corrects the
Native comparison caller's transcript publication route. The final managed
family has **3 complete matches and 1 mismatch**, with zero blocked cases or
runner errors. The remaining sessions-enabled case differs at two restarted
score fields. **The last verified baseline remains 64/128, with 64 remaining.**
Requirement 63 remains pending at 0/2; all eight new development inputs have
empty coverage and are absent from the default acceptance catalog.

The [committed diagnostic summary](host_restart_managed_diagnostics.json)
contains complete public results/differences, corpus timelines, report identities
and raw artifact hashes. The [managed index guide](managed_memory_index.md)
documents the new SDK API and physical close contract.

## Real changes

`ManagedSQLiteMemoryStore` is an explicitly selected provider-none subclass of
the actual SQLite store. It reads real identity/chunk/FTS state, requests a real
`search-bootstrap` rebuild when appropriate, and uses the original checked atomic
publisher. The normal tool sees the owner's live notice sequence transition;
no warning is injected into an eager index after the event. Warm searches do not
replay a prior notice. Newer incompatible indexes remain untouched, actual repair
errors are retained, and close joins work admitted by this owner even after its
awaiter stops waiting. Bounded journals expose actual linked operations and
truncation. The typed base search signature, forwarded options and original
results/errors are preserved. Existing eager kit/runner defaults are unchanged.

Both new families declare a genuine producer force rebuild **after** physical
source metadata setup. Native calls original `manager.sync` with
`reason: "host-restart-producer-publication", force: true`; SDK calls actual
`store.reindex(workspace, force=True)` after its committed writer turn. Full
pre/post rows, revisions, real returns and source observations remain raw.
The source inode/bytes/mtime remain unchanged by the rebuild. This adopts the
declared filesystem timestamp through actual indexing; no payload/ledger alias
or direct index-row rewrite is used. Earlier ordinary incremental publications
remain visible in the SDK capture. The two implementations' same-content
incremental behavior was already consistent; it was not patched to force a match.

Investigation also found an omission in the earlier Native harness: lower-level
`appendTranscriptMessage` persists a message but does not publish its transcript
notification. New families now call original public
`appendSessionTranscriptMessageByIdentityStrict` with the actual emitted event,
exact scope/config and inline update mode. The original committed sequence/turn
owner produces the normalized update. Actual return unions, original metadata
transformations, observer events and versions are retained. Guards bind every
commit anchor to both the normalized notification and actual SQLite transcript
row/identity/readback. Legacy routing and physical database paths stay distinct.
No fabricated compatibility receipt or caller-authored message sequence is added.

## Observed families

| Scenario | Earlier policy family | New producer rebuild with eager SDK | New managed SDK |
| --- | ---: | ---: | ---: |
| Memory-only ASCII | 4 differing paths | 2 | 0 — complete match |
| Memory-only Unicode | 4 | 2 | 0 — complete match |
| Sessions indexed, memory queried | 6 | 4 | 2 |
| Actual post-search directory replacement/get error | 4 | 2 | 0 — complete match |

These columns are separate frozen input families with different declared
publication/lifecycle controls, not relabeled earlier captures or same-wire
before/after claims. The earlier seven inputs/profile files remain unchanged.
New [publication inputs](host_restart_publication_literals.json) and
[managed inputs](host_restart_managed_literals.json) have independent exact-hash
profiles, entry points and preloads; they cannot borrow another family's literals
or execution capability.

All original write/search/get objects and actual SDK host calls remain genuine.
Each side produces its own absent-at-start source, uses a fresh same-process chat,
fully exits, then opens a new process and session over the saved state. Initial
read inputs omit the unique answer across system/runtime context, tools, messages
and Native model/options. Real search supplies get arguments; actual get supplies
the final assistant answer. A separate workspace retrieves no primary memory.
The real read failure is retained as `MEMORY_READ_FAILED`, not empty success.

In the managed family, SQL identity is genuinely missing after cold construction.
The actual query owns repair -> force publication -> valid revision -> live notice.
Sixteen owner close receipts join actual operations. The SDK explicitly selects
the existing OpenClaw compatibility identity in these inputs so genuine guidance
names that host; the SDK owner's default identity remains its own product.

## Remaining session publication difference

The corrected caller emits the committed notifications used by the original
Native queue; it adds no awaited per-turn publication barrier. The consuming
scheduler uses a fixed **5000 ms** session debounce, detached startup catchup and
background valid-index maintenance. The displayed 100000-byte/50-message settings
were not found as consumers of that runtime queue and are not ported as its
observed admission rule. No separate missing `onSessionStart` call was found:
the original warm-session claim occurs inside the actual search path.

SDK HostSessionRunner deliberately awaits an all-source refresh at accepted turn
completion. Its reader transcript is therefore indexed before process restart;
the fast-closing Native host still has the earlier admitted session corpus in
these captures. Their BM25 corpus statistics differ on restart. Both first scores
and all source/get/answer dataflow agree, but restarted `score` and `textScore`
remain ordinary visible mismatches. No sleep/drain, artificial row filter,
selective catalog hiding or weakened SDK default barrier was introduced.
The optional managed store supplies cold bootstrap, not this background/session
publication controller. Matching the memory-only cases does not close both host
acceptance conditions.

## Authority and retained evidence

Code comparison commit: `4634055`. Reference: OpenClaw `v2026.9.9`, source commit
`bcfc88812a35243893585dbeca87ca41b48272ca`, original verified official runtime and
approved Node 24.16.0 / ICU 78.3 / Unicode 17. Additional pinned owners cover strict
append, committed sequences, normalized transcript notifications and the actual
session scheduler. Source-build reproduction and full embedded-runner execution
remain unclaimed. Runtime fetch is denied; no provider credentials or paid calls
are used.

| Capture | Result | Report SHA-256 |
| --- | --- | --- |
| `work/host-restart-publication/attempt-002-clean/` | 4 mismatches, 0 blocked/errors | `b3f54263e60fbcb0a5ef2fa91c40cabf63564088e8daaeecb2dd97a80fa27266` |
| `work/host-restart-managed/attempt-002-clean/` | 3 matches, 1 mismatch, 0 blocked/errors | `1fcabd126450f1d237456fb534bbc076dd8a2cfc9863ea2ac24fc48f896ffc63` |

Both have `finalAuthenticationPassed: true`. Earlier `attempt-001` reports and
local preparation probes are retained under their original source identities;
none is overwritten or promoted into current execution evidence. The first local
managed probe predates the final close-state cleanup and typed-signature hardening.
No original execution failure is automatically retried. Independent review of the
first eight authenticated captures verified 284 artifacts, 160 strict committed
notifications, 48 read chains, four actual cold repairs and 16 close receipts.
Final captures repeat the same real flows on the committed implementation.

The complete SDK source SHA-256 for 157 files is
`c0768be678f951862f27844d90a4263586ad45001e129334abeec5990da097e3`.
Raw captures/dependencies remain ignored local files; pushing Git includes their
summaries and identities. The historical 1,403-case `b090394` catalog belongs to
its earlier SDK source hash and was not rerun or relabeled in this package.

## Validation and next work

The focused selection passes **188 tests**. The fresh full suite passes
**6,929 tests, zero failures and 1,648 skips in 323.74 seconds**. Skips retain the
previous historical/live and absolute-runtime-path limits and grant no credit.
Capability tests reject cross-family borrowing, changed hashes/inputs and hidden
producer carriers before original imports; actual ESM workers inherit protection.
Guard tests reject forged revisions, counts, notifications, SQL rows, repairs and
close receipts. Real owner tests cover cold/warm behavior, failure, ownership,
newer identity, cancellation/physical close and typed option/error preservation.
Source inventory still validates 64 contracts, 128 conditions and 196 upstream
modules; the new Python counterpart remains classified partial.

Both offline wheel/sdist consumers pass real installed managed bootstrap, live
notice, warm recall and close as well as the existing host/session/trust tests.
Valid installed typing passes and **12 invalid typed calls** are rejected.
The first installed-consumer attempt is retained: the new test supplied an
incomplete trusted source policy and got an actual `searchSources` unavailable
error. Fixture correction `52880d4` supplies the real resolver's complete output;
no SDK result was repaired. The original log and complete diagnostic response are
retained alongside the corrected package run. SDK/adapter bytes match the final
comparison throughout that consumer-only correction. Ruff, naming and diff checks
pass.

Next, implement a genuine separately owned session publication plan/controller
using actual committed catalog revisions and source-scoped atomic publication.
Preserve the existing eager runner guarantee and cold/session diagnostics; do
not imitate Native timing by hiding records or dropping score fields. Once the
supported family and required boundaries pass, acceptance registration and a fresh
complete gate can target the original two restart conditions.

Use the existing verified dependencies and a new output directory to reproduce:

```sh
.venv/bin/python scripts/check_host_restart_publication.py \
  --reference work/openclaw-v2026.9.9 \
  --node work/node-v24.16.0-linux-x64/bin/node \
  --release-runtime .reference/release-runtime \
  --output work/new-publication-attempt
.venv/bin/python scripts/check_host_restart_managed.py \
  --reference work/openclaw-v2026.9.9 \
  --node work/node-v24.16.0-linux-x64/bin/node \
  --release-runtime .reference/release-runtime \
  --output work/new-managed-attempt
```

The commands neither download nor retry. Exit 1 preserves mismatches; exit 2
indicates blocked/error cases. All development executions award zero conditions.
