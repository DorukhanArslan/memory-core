# Promotion apply and reconciliation comparison plan

This is a proposal for the existing two conditions under fixed requirement 43.
It is not a capture, coverage registration, or production correction. The
worktree starts at frozen integration commit `21177bf`.

The outcome condition compares MEMORY.md, DREAMS.md, markers, authoritative
candidates, and complete applied/rejected receipts. The boundary condition
interleaves candidate changes and checks lock-time revalidation and publication
order. Existing memory-budget apply cases and canonical ranking cases support
individual owners, but do not establish these whole-operation conditions.

## First proposed literal

`promotion-apply-zero-rehydrated-directory-memory` is defined in
`equivalence/promotion_apply_reconcile_fixtures.py`. It seeds one ordinary
canonical recall entry and passes the same candidate explicitly. Its source
`memory/2026-05-08.md` is absent. MEMORY.md is a real empty directory. All numeric
gates permit selection; there is no completion callback or provider.

The original owner checks for zero successfully rehydrated candidates before
reading MEMORY.md or acquiring the promotion file lock. It still reads artifact
provenance and takes/releases its initial durable workspace lease to read recall.
The current SDK acquires its
locks and reads MEMORY.md before its no-live-candidate branch. These are source
findings only; neither expected return nor expected error is put in the fixture.
The first actual before comparison must precede any SDK correction.

## Original authority and transport

Use a distinct `promotion-apply-reconcile-runtime` capability. Keep the existing
budget capability and its accepted cases unchanged. Invoke the original public
`dist/short-term-promotion-MX1vHJuE.mjs` export `a` directly. Configure the real
dreaming state using `dist/dreaming-state-VYUvbU-n.mjs:p` and the public
`dist/plugin-sdk/plugin-state-store-runtime.js:createPluginStateKeyedStore`
factory. Seed and read the real canonical store through
`dist/short-term-promotion-store-B6T388Bo.mjs:l` and `:a` respectively.

Retain the original plugin-state/shared-state backend roles, SQLite carrier
`dist/infra/sqlite-store.worker.js` and backend
`dist/state/openclaw-state.worker.js`. The published carrier and backend hashes
are respectively `b6fb8b9d214bd7d35beb77849e1c44926d4963cacd9fc13af40f8c3b43374d69`
and `52fdb859d0add218690d0db4358fa5b2f2d2118379163eefb42a35c87f0715d4`.
Use ranking's explicit worker-route binding/observation template: the old budget
validator discards worker-import observations and is not sufficient authority
for a new whole-apply claim. Do not borrow a no-worker heartbeat capability.
Bind the pinned source owners, official
compiled artifacts/import edges, native fs-safe artifact, and actual worker
bootstrap artifacts before and after execution. Use only the approved Node
24.16.0 binary and Date-only main-process clock. Original timers, performance,
worker clocks, options, inherited protected preload, and messages remain actual.

The SDK invokes the real `run_short_term_promotion`, real canonical recall store,
and real SQLiteMemoryStore with vectors disabled. Select explicit OpenClaw marker
identity. Retain its full richer return and index calls as SDK extensions; the
original public apply function does not itself reindex.

## Whole observations before and after

Keep the complete original eight-field apply result or complete actual error.
Keep the SDK's full return/error separately as well as the mechanical eight-field
comparison. Never replace an owner error with an observation failure.

Before invocation and at its actual settlement, retain the source's existence
and bytes, canonical recall state, MEMORY.md and DREAMS.md path kind and bytes
when regular, full owned filesystem tree/lock files, actual calls, and full
physical SQLite schemas and rows. Capture post-call state before additional
readback APIs, then record every real readback call and its result separately.
Directory-aware observation must use lstat and must not readFile the directory:
the existing budget document observer would otherwise introduce its own EISDIR.
No claim that an absent final lock file proves no lock was acquired is allowed.
Any lock/write-order claim requires authentic live receipts, not reconstructed
order from final state. Path mapping is restricted to the owned fixture prefix;
no candidate key, hash, receipt, error, provenance, timestamp, or score repair.

## Remaining proposed whole-operation families

After review of the first literal and authority mapping, add literal families
for authoritative recall overrides and moved-line rehydration; provenance/gate
rejections; existing-marker reconciliation; and actual prelock mutations of
recall, source, or MEMORY.md. The public awaited `consolidation.subagent.complete`
callback supplies a genuine provider-free prelock seam: retain its entire request,
the declared literal completion, actual mutations, and original fallback/parser
behavior. One add-only valid plan can exercise real preimage, origin, and DREAMS
publication. General model-plan equivalence remains requirement 44.

Append-only lock contention without consolidation needs a separately reviewed
exact lock-helper/test-hook profile. No such hook capability or capture is
included in this first proposal. No points or completion date are promised
before the actual whole-operation differences and boundary evidence are reviewed.
