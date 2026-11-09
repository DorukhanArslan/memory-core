# Shared managed-host restart acceptance

Prepared 2026-11-10 (Europe/Istanbul). This package targets **+2** and verifies
**+2** original acceptance conditions: **64 → 66/128 (51.6%)**, with **62
remaining**. There are 30 complete, six partial and 28 pending contracts.
The fixed 64-contract scope SHA-256 remains
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`.
The percentage counts verified conditions, not engineering effort.

## Behavior and actual ownership

`ManagedHostSession` shares one actual kit, catalog, managed store and session
publisher across an agent's chats in one host. Fresh chat B reuses writer A's
owner. Reader C opens a new owner only in a separate host process. Constructor
and first-query admission retain real cold-index preparation and SQLite read
generation ownership.

The scoped curator retains its write/index lock. A cold file can be committed
while its index is explicitly pending. Valid-index ordinary writes, finalizers,
repair, flush and acknowledgment publish only the memory scope. They do not
publish pending session targets early. Actual committed transcript hints feed
the session controller; scoring and hydration retain the query's admitted
SQLite generation while later publication can proceed.

The managed outcome reports memory and session readiness separately and keeps
the inherited `ready` guarantee. Durable `needsMemoryIndex` and
`needsSessionIndex` combine into `needsIndex`. Source coverage uses actual
admitted fingerprints, including stale exclusion/removal. Coverage acknowledgment
plans against one catalog snapshot and uses a real `BEGIN IMMEDIATE` revision
CAS to patch only owned lifecycle metadata. Concurrent resets, appends or
metadata edits leave the plan unapplied and dirty markers intact.

Public construction requires the actual scoped/deferred kit and bound
controller. The inherited eager managed-runner factory rejects before IO.
Acknowledgment remains admitted through final catalog settlement and
cancellation. Close joins actual work and cancels a future timer without
flushing it early. Startup errors propagate before another reconciliation can
mask them. The existing eager host APIs retain full awaited publication.

The explicit producer `owner.reindex(force=True)` is a stronger SDK owner
barrier that joins actual startup/reconciliation work. This is not a claim
that every Native force call waits for every constructor discovery operation.
Ordinary fresh/restarted reader turns use no scripted flush or reconciliation.
See the [public API guide](managed_host_session.md).

## Complete original acceptance family

The independently frozen [four literals](host_restart_session_literals.json)
cover ASCII, Unicode, sessions-indexed retrieval and actual get failure. Each
uses the same genuinely produced corpus with a fresh same-host chat, a fresh
host process, and another agent/workspace. All four are required atomically for
both original `host.restart-recall` conditions. A missing, mismatched, blocked
or unverified member prevents either condition receiving credit.

Both engines run their real memory tools. The Native actor executes the pinned
official runtime, its real AgentLoop and original worker paths. The SDK uses
its registered daily-note producer and managed runners. The different write
tools are declared corpus setup, not a claim of write-tool API equivalence.
Explicit physical timestamp setup and producer force publication are visible
on both sides. The provider-none profile and actual runtime identity are
declared inputs.

Reader prompts, initial model contexts and inherited capabilities omit the
saved fact. Separate reader processes receive only their own phase, identity,
policy, clock and locations. The model derives the get range from the actual
search result and its terminal answer from the actual get result. The failure
case renames the selected source and creates a real directory before get;
the complete resulting error stays visible. No score field, warning, failure
or result is dropped or repaired for comparison.

All 15 earlier diagnostic inputs, hash maps, entry/preload capabilities and
historical captures remain separate and unchanged. Shared Native actor changes
only admit the independently protected new lifecycle marker.

## Fresh complete gate

The complete catalog ran on clean code commit
`9d13b192d7b124700988cea61b78ed3949d77380`, with **159 SDK Python files** and
canonical source SHA-256
`1243192c301ee4b634f7a8dc65d525199317e08597073ee3de2f6735f2b91975`.
It retains the exact `v2026.9.9` reference
`bcfc88812a35243893585dbeca87ca41b48272ca` and authenticated Node `v24.16.0`
(ICU 78.3, Unicode 17.0), executable SHA-256
`b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd`.

The run completed in **1,584.152651 seconds**: **1,407 cases, 1,393 matched,
14 mismatched, zero blocked and no runner errors**. Every new host case is
matched with verified Native and SDK evidence. The two original conditions
are complete; the scope is unchanged. There are 60 uncovered conditions and
two registered but unresolved boundary conditions, totaling 62 remaining.

The full gate remains `mismatched` and `fullScopePassed=false`. This is an
increase in bounded verified coverage, not complete OpenClaw equivalence.
The retained complete report `work/host-restart-session-full-001.json` contains
462,990,976 bytes and SHA-256
`ea41a771eb5905a359c03153cbe2a1accc7306b4615b88d011082ffb5ac8f085`.
The [committed diagnostics](host_restart_session_diagnostics.json) retain all
four complete public Native/SDK results, exact source/report identities,
raw diagnostic hashes and successful custody replay. Large original raw
captures remain in ignored `work/` and `.equivalence-results/`.

## Regressions and retained preparation failures

Full regressions pass **7,138 tests**, with **1,648 uncredited skips**, in
393.28 seconds. The skips retain the previous historical/live and old absolute
runtime-path limits. Both offline installed wheel and sdist consumers pass,
including shared-owner save, pending readiness and reopened recall; public
typing accepts valid calls and rejects **24 invalid calls**. Ruff, source
inventory and diff checks pass. Inventory remains 64 contracts, 128 conditions
and 196 upstream modules; source presence itself adds no credit.

The first regression run retained one stale catalog-inventory expectation:
7,137 passed and one failed because the new `host.restart-recall` requirement
was missing from that test's expected set. The one-line test-only correction
was verified by a complete isolated run on
`327380a84d5c12c447393e5c621f2ac8fd09570e`. All 411 tracked SDK/adapter files
were byte-identical to the clean gate source; the primary gate continued on
its original clean commit. The test-only correction was fast-forwarded after
that gate completed. Logs retain both runs.

The first development comparison remains **four blocked cases**: its replay
guard confused zero-based SDK anchor positions with one-based physical SQL
sequences. Its original report SHA-256 is
`cdaa9a250f13a4c5bfa294088e04f4482249b67dc736757405212b30dbef7b48`.
The corrected second development comparison matches all four with zero
blocked/errors; report SHA-256 is
`eb34cc5d1272ef45ca2c5d735df85a72f0eafc64340e4ab1fd8e8bc3d0be131b`.
Independent preflight review verified 142 artifacts, 160 committed-message
chains, 12 real SDK read leases and 12 owner closes. Those development reports
retain their own dirty source identities and zero awarded credit; they are
not relabeled as executions of the final clean SDK. The fresh complete gate
above supplies acceptance evidence.

## Next original contract

The next target is `host.update-isolation` (#64): update an old preference,
retain unrelated facts and independent user/workspace state, and report actual
write/index failures honestly. A complete family should cover ASCII and
Unicode updates, real write refusal and real publication failure. For example,
after changing “I prefer tea” to “I now prefer coffee,” recall should use coffee
while preserving another user's records and an unrelated saved fact.
`host.turn-barrier` (#62) remains a separate contract.
