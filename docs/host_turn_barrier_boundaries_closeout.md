# Host turn-barrier boundary acceptance

Prepared 2026-11-10 (Europe/Istanbul). The initial fresh complete catalog verifies
only the existing `host.turn-barrier.boundaries` condition: **69 → 70/128 (54.7%)**,
with **58 remaining**. Contract #62 has both original conditions verified under
this explicit profile. There are 32 complete, six partial and 26 pending contracts.
A subsequent general regression exposed a genuine concurrent session-publication
failure. Its sessions-only catalog reservation correction passed independent review;
fresh final full-catalog, suite and distribution validation are in progress; this document does
not label either failed general test run as successful.

The fixed 64-contract/128-condition scope SHA-256 remains
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`.
The earlier four-case `host.turn-barrier.outcomes` family keeps its exact literal
hashes and coverage. This package registers six separate boundary cases after
the prior 1,415 cases, for 1,421 registered definitions. The definition audit
and fresh full-report audit confirm the earlier definitions and statuses unchanged.

## Behavior measured by the six cases

All six exact members must match with validated Native and SDK custody together.
A missing, blocked, mismatched or unverified member leaves the original condition
open. The [literal manifest](host_turn_barrier_boundaries_literals.json)
contains independent inputs and schedules, not captured expected outputs.

| Schedule | Actual boundary and observation |
| --- | --- |
| Pending optional preemption, ASCII | The original post-turn scheduler creates a real pending owner. The actual terminal delivery callback holds only its channel acknowledgment and immediately submits the next same-session dispatch. Foreground admission aborts the pending owner, joins its real completion, then admits the next user. Persisted usage and a read-only resolved plan establish eligibility; the committed-maintenance case supplies the separate executed positive control. The first host return can follow the next submission. |
| Target-open preparation, Unicode | An owned empty daily file is held by an approved Python process using a real Linux read lease. Kernel `SIGIO` proves the original append-mode target open is blocked. A new foreground request aborts the running owner; a real event-loop checkpoint sees no next model and still-owned work. Releasing the lease lets the actual open/checkpoint settle before the next admission. A real read-lease reacquisition checks that no writable descriptor remains. |
| Committed maintenance, ASCII | The actual default maintenance model consumes persisted first-turn history and writes the distinct daily fact through its real producer tool. It consumes the actual success result before the next request. The committed file survives cancellation and the follow-up retrieves it through actual search/get. |
| Refused maintenance, Unicode | After genuine target preparation, a second hard link exists only around the actual maintenance write. The private model consumes the real failed result; the empty source stays unchanged. The next foreground joins the real owner. The private tool error is retained without inventing a public background warning. |
| Refused foreground replacement, ASCII | A genuine warm-up saves the old preference. A second hard link blocks replacement; the model derives its failure acknowledgment from the actual tool result. The later search/get retrieves the unchanged old preference. This is a populated source schedule, with no inserted explicit index publication. |
| Cold automatic publication failure, Unicode | The first user asks to save and verify through actual search. A dangling symlink blocks the real publisher sidecar: Native's reindex-lock database and the SDK rollback journal. The source commits; the first verification consumes and externally delivers the genuine unavailable/error/warning/action carrier before the next user admission. The fault remains through the follow-up. |

No forced reindex, synchronization call or timer drain supplies a match. Empty
lease/refusal files are declared filesystem fixtures, not fabricated saved facts.
Actual hard-link, symlink, inode, source-byte and publisher receipts remain retained.

## Public comparison and custody

Native uses pristine full `dispatchReplyFromConfig`, its actual core reply
dispatcher, and the original `runReplyAgent` and foreground admission. Fixture
code supplies no replacement reply operation or maintenance owner. A separately
authenticated local scripted-provider transport drives the real tools; no paid
model or embedding calls occur.

The compared channel result retains every delivered payload field, including
`replyToTag`, `replyToId` and `audioAsVoice`, plus complete search/get results and
source bytes. Native's complete dispatcher API return is retained. The SDK's
channel adapter computes its actual queue/delivery accounting; its complete
`HostTurnOutcome` stays in engine-specific raw custody. This is not a claim of
raw SDK outcome/Native API-return identity. Coding, curated and maintenance
producer APIs also keep their distinct complete receipts in custody.

The genuine Native `onAgentRunStart` callback reads the entry, transcript and
physical SQLite rows. Actual abort and `owner.done` observers independently read
the same state. The next user is absent at cancellation/completion and present
at the real later admission callback, bound to physical transcript event and
identity rows and the original lifecycle run ID. The guard rejects reordered
admissions, borrowed callbacks, missing physical rows, a running owner relabeled
pending, and abort relabeled completion. This measures these admission checkpoints;
it does not claim the restart family's complete per-message SQL commit chain.

The lease gates **pre-model target preparation**, specifically the real
`ensureMemoryFlushTargetFile` append-mode open. It does not hold an already
dispatched physical append. Native `owner.done` can precede unowned provider
transport cleanup. The SDK retains its callback cleanup and accepted physical
dispatches until they settle. The comparison preserves these distinct ownership
limits; it does not claim that Native joins that unrelated transport lifetime.

## Explicit profile and production changes

The SDK selects `maintenance="background"` alongside
`memory_publication="on-search"`. The default maintenance policy remains
`"inline"`. The new in-process coordinator reserves foreground priority before
the session lane, retires pending optional work, withdraws running model authority
once, and joins admitted work before committing the next user. Real target
preparation runs off the event loop and keeps settlement custody. Committed files
remain committed after cancellation. `maintenance_status()` retains actual job
outcomes and failures; `aclose()` joins actual asynchronous work.

An optional real `deliver` callback holds the foreground until acknowledgment.
Failed or cancelled delivery cannot authorize a later optional write. These
choices do not add cross-process preemption, a file watcher or embeddings.
Background model-visible failures do not automatically become public warnings.

The full Native channel pipeline resolves `fixture-user` as an ordinary user
with effective `senderIsOwner=false` and no owner grant. The SDK fixture therefore
passes the same effective authority. Its earlier default-owner assumption was
corrected at the input adapter. The unused asserted Native context flag was
removed. The warm-up's untrusted provenance is retained; a refused replacement
does not invent an authority upgrade or downgrade.

Native explicitly uses the real `skipBootstrap=true` configuration; the SDK
profile declares `initialize=false`. This prevents Native's unrelated default
bootstrap corpus from changing the complete ranking results. V1 manifest/module
bytes remain under `contract/freeze-revisions/v1/`; V2 declares both settings and
was frozen before its first formal execution. V1 has zero formal executions and
zero SDK comparisons. Current manifest SHA-256:
`76c50a9a3d0cea31780b519fbab3c2943f3800b4c1e1e003806e82bdbea6f3c1`.

The original default flush prompt is used; an ineffective development custom
prompt is not presented as effective configuration. The declared wall clock
replaces Native `Date` only, including inherited workers. Timers and monotonic
clocks remain real. Actual `utime` fixes root/daily atime and mtime inside the
model callback after a successful producer result. It changes no source bytes
and performs no indexing. Scores, warning/action/debug fields and provenance
remain whole; no numeric tolerance or output normalization supplies equality.

## Read-generation and cold-admission corrections

Review reproduced an old reader losing its stale/failure notice when a real
background publisher recovered a newer SQL generation. The result now carries
status from the SQLite generation it actually read. An old pinned reader keeps
its retained warning; a genuinely newer reader can see recovery. A real WAL
regression verifies both results without rewriting hits or waiting for freshness.
Evidence: `index-notice-review/reproduction.json` and `summary.json`.

The cold failure comparison also found an extra SDK repair-request notice before
storage admission. A hook on the existing real prepared-write attempt records
the actual `connection.total_changes` delta and SQLite error before commit or
rollback. An unopened cold `SQLITE_CANTOPEN` with zero changes does not announce
an admitted rebuild. Actual source-scan failures, failures after admitted writes,
and populated-index repair keep their genuine notices. This is a phase-aware
publication correction, not blanket failure suppression or altered output text.
Evidence: `index-notice-review/cold-admission-summary.json`, SHA-256
`d1c96c5abe7642a017bb8b5a6136d0fb6fd4a4cec1dd0ae058d9c58663fbc23e`.
No private Native notice-counter receipt was captured; the Native phase relation
is established from authenticated source and the complete actual public warning.
These correctness fixes award no separate acceptance conditions.

## Clean preflight and verification

The clean six-case preflight uses commit
`82dba0543e6e35c3249e987e0f9497ad6334398e`, with **160 SDK Python files** and
canonical SHA-256
`560cccffded7eceaaa633631ec5d85b96314085971af4c676dc1599821194e96`.
All six match, with zero mismatches, zero blocked cases, no runner errors,
successful final authentication and both custody snapshots validated per case.
The standalone report awards **zero** acceptance points:

`work/turn-barrier-boundaries/preflight/attempt-001-clean-82dba05/report.json`,
**26,810,351 bytes**, SHA-256
`45febf478b50201779d3abc11c7a915ccf9a5c7c62dda5ac3a0400258b721b9a`.

Reference: OpenClaw `v2026.9.9`, commit
`bcfc88812a35243893585dbeca87ca41b48272ca`. Node is exact `v24.16.0`, ICU
78.3, Unicode 17.0, executable SHA-256
`b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd`.
Source and official compiled artifacts are authenticated separately; no
independent source build is claimed. The target lease helper and actual Python
executable have separately bound source/binary/version/PID/parent receipts.

Focused checks pass **267 retained-evidence tamper tests**, **58 actual capability
tests**, **10 actual kernel-lease tests**, and **68 SDK-focused tests**, including
19 new background-maintenance cases. These batches add no acceptance credit.
The final installed wheel and sdist consumers pass, valid public typing passes,
and **27 invalid calls** are rejected. Distribution log:
`work/turn-barrier-boundaries/distribution-002.log`, SHA-256
`fd530ed2c7ea3090f92ff02440a38e53ea5a47f8c72579860f97128feff53e28`.
Distribution 001 belongs to the earlier development SDK and is retained
without being relabeled as final validation.

The initial fresh complete catalog, on clean `82dba05`, executes **1,421 cases:
1,407 matched, 14 existing differences, zero blocked and no runner errors**, in
1,796.449878 seconds. It verifies only the original boundary condition: **69 →
70/128 (54.7%)**, with **58 remaining**: 56 uncovered and the same two registered
unresolved conditions. Contract #62 has both original conditions verified under
this declared profile. There are 32 complete, six partial and 26 pending contracts.
The gate remains `mismatched`, with `fullScopePassed=false`.

Report: `work/turn-barrier-boundaries/full-001.json`, **571,976,839 bytes**, SHA-256
`927d693aa41c39645d824630cd52d4e23ad955ce9673ae762433227b73f6e3fb`.
Independent retained-only audit: `work/turn-barrier-boundaries/independent-audit-full-001.json`,
**17,075 bytes**, SHA-256
`53ed1c2becb331bbd61afdf0dac38efa0aace4f19092f5e3e817057bcb37803f`.
All 1,415 prior case definitions, statuses, annotations and 12 runtime-evidence
flags remain unchanged; all other 127 acceptance records are unchanged. Only
six new matched and validated cases supply the one original condition. Six Native
raw files remain physically retained; full-run SDK originals are verified from
embedded snapshots and their original serialization hashes, not claimed as still
existing temporary files. Audit itself adds no execution or acceptance credit.

The initial whole suite records **8,657 passed, three failed, 1,648 skipped** in
429.86 seconds. The three failures are obsolete catalog metadata assertions;
isolated tests-only `a283885` preserves the original 1,411-case hash and frozen
families while recognizing the six added cases. Its 224 focused tests pass. A
second full collection, using the actual two corrected test files without changing
sealed SDK/adapters, records **8,659 passed, one failed, 1,648 skipped** in 427.20
seconds. This distinct failure retains a real `MemoryIndexSourceChangedError`
in an admitted session publisher whose catalog source changed during preparation;
the controller genuinely remained failed/pending. The guard is correct to reject
it. Its complete raw capture is preserved in the session-conflict review cache.
The correction reserves the actual SQLite writer slot of a separate durable
catalog through sessions-only publication without changing rows. Concurrent real
appends commit afterward and retain their pending publication. Mixed selections,
process-memory catalogs and physically shared catalog/index databases keep strict
source validation. The existing custody guard, source-change checks and timer
behavior remain unchanged; no automatic retry is added. Ten new deterministic
regressions and four fresh old-family SDK comparisons passed independent review.
**PENDING:** final suite, installed consumers and fresh complete catalog on the
changed SDK identity. Earlier full001 and distribution002 remain historical. Neither failed run is relabelled
green or discarded.

## Retained development failures and limits

- SDK `focused-first.log` targeted a nonexistent test file; no tests ran. SDK
  `focused-second.log` retained a genuine failure: 61 passed, one failed because
  an old recovery reader lost its `stale` field. The read-generation correction
  above addresses that actual failure.
- SDK attempts 001/002 retain their complete results and raw hosts. Their report
  bytes are identical, SHA-256
  `208e2e329e0d871c0f74aa5acb6ff856853dd892d64b077ad6afaf1d6d78636f`.
  The first public comparison records the ordinary-user provenance mismatch.
  Attempt 003 corrects that authority input but retains the two cold-notice
  differences. Attempt 004 records six complete matches after the actual fix;
  its report SHA-256 is
  `9fc8dfc4a734a4179eea2f6113d50b6d39fd07d6f91b0d149c47dab86efc7490`.
- Native development 008 retained a fixture decoder error: it rejected an actual
  `isError=true` deferred search carrier despite its complete genuine details,
  causing a generic agent failure. It is negative evidence, not accepted search
  failure dataflow. New attempt 009 consumes the unchanged error payload while
  still checking complete carrier/details equality, and delivers its real
  warning/action. Old actor bytes and captures remain unchanged.
- Native 001–006 are separate scheduling probes, including standalone caller
  delivery-ack findings and the pending transport-ack schedule. Later authority
  and read-only physical-admission observer revisions retain their earlier
  source bytes and hashes. Older captures lacking the new required checkpoint
  are not relabeled as final evidence. Native 010 is an actual dirty six-case
  cache used by adversarial tests; the clean preflight has its own identity.

The preserved paths above are under `work/turn-barrier-boundaries/`. Standalone
matches and replay do not constitute another Native execution or acceptance award.
No in-flight physical append cancellation, all possible maintenance interleavings,
cross-process scheduling, real-model answer quality or general watcher behavior
is claimed. The separate outcome family's existing warm stale-read behavior
remains bounded evidence; this package does not turn it into fresh recall.
