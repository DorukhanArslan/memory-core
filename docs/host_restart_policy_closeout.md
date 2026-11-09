# Host restart source-policy follow-up — 2026-11-09

The later [producer publication/managed-index follow-up](host_restart_managed_closeout.md)
adds real force publication, corrects the Native transcript notification caller
and records three exact managed matches with one remaining sessions mismatch.
It awards zero conditions and retains the captures below under their original
SDK/adapter identities.

This follow-up changes HostKit search dispatch and makes the hosts' source
policies explicit. **The last verified baseline remains 64/128 (50.0%), with
64 conditions remaining.** Requirement 63 remains pending at 0/2. Neither the
four new literals nor the original three claim coverage; no new acceptance
condition is registered. The fixed scope is unchanged.

## Result and SDK behavior

`HostKit` now calls the actual registered search factory with its own clock,
session visibility, source policy, active projects and runtime identity. The
factory performs real store acquisition and ownership validation; HostKit
returns its complete actual `details` through the existing payload API.
Dreaming recall recording still follows successful search. Disabled memory
and a foreign store are refused at the same real tool boundary.

The host clock reaches search even without optional visibility/policy
overrides. A real acquisition test with a clock advancing seven milliseconds
returns `managerMs: 7`; no constant zero or synthetic status is installed.
Other tests cover authoritative visibility, model routing attempts, actual
session publication, owner mismatch and disabled-before-invalid-arguments.
The [host guide](host_kit.md) documents the current composition. No new public
configuration API or session-publication mode was added.

The final authenticated comparison on code commit
`31e7087f3dd2848cc45855d878fa3d3711d565d3` has **0 matches, 4 mismatches,
0 blocked cases and no runner errors**, with final authentication true.
The [committed summary](host_restart_policy_diagnostics.json) retains complete
public results, all differences, observed corpus timelines and artifact hashes.

| Exact new input | First clock-only capture: differing paths | Registered factory: differing paths |
| --- | ---: | ---: |
| Memory-only ASCII | 7 | 4 |
| Memory-only Unicode | 7 | 4 |
| Sessions indexed, memory queried | 9 | 6 |
| Actual post-search file read failure | 7 | 4 |

The same four input wires are used before and after factory integration.
Exactly the three `managerMs` paths disappear in each case; no other difference
is added or removed. Complete result fields, errors, scores and warnings remain
visible. An independent review verified all 142 artifact hashes, 156 SDK and
225 adapter hashes, the process/worker roles and all 24 read chains.

## Actual source and publication controls

The [new literals](host_restart_policy_literals.json) use a separate exact-hash
capability. Native's real resolver and the existing SDK resolver receive
`configuredSources: ["memory"]`, an explicit `rememberAcrossConversations`
boolean and `configuredSessionMemory: false`. Memory-only cases index memory;
the true case indexes memory plus sessions while queries remain memory-only.
Both hosts genuinely index the same writer transcript in the true case:
the actual save prompt and the common literal acknowledgement `Saved.`.
The guard rejects a missing writer session, not just foreign source types.

Original Native tools/AgentLoop and actual SDK HostSessionRunner still produce
and read the source. Each reader derives get arguments from real search output
and its terminal answer from the actual get message. The fresh/restarted
initial inputs remain fact-free, and isolation and directory-replacement errors
remain genuine. No manual restarted-process synchronization is added.

The fixture performs a real producer-only filesystem `utime` after the real
write result, preserving bytes and recording before/after observations. This
controls physical file mtime; it does **not** yet align indexed provenance:

- Native stamps before its first explicit producer index synchronization.
- SDK's curator already published during append dispatch. The metadata change
  is followed by the normal finalizer's incremental publication. The complete
  pre/post index snapshots, actual syscall arguments/return and final publication
  are retained separately. Indexed snapshots are not a complete ledger journal.

Both implementations intentionally reuse same-content memory chunks on an
ordinary incremental refresh. Separate real probes confirmed that only a real
force rebuild adopts the new timestamp on both sides. This is a fixture-stage
difference, not evidence that SDK alone has incorrect incremental arithmetic.
The unchanged `observedAt` values remain mismatches; no ledger/index rows are
rewritten and no timestamp alias is applied.

## Remaining boundaries

Every final case still differs at two primary-read `observedAt` paths and the
isolated result's `corpora`/automatic-repair warning. Native cold search performs
its real `search-bootstrap` rebuild and emits a live notice. SDK HostKit eagerly
reindexes at open and has no corresponding search-bootstrap notice producer.
This needs lifecycle work rather than an injected warning string.

The sessions case additionally differs in restarted `score` and `textScore`.
Both initial producer indexes contain the same note/writer projection and the
first scores match. SDK then eagerly publishes the fresh reader's transcript;
Native's actual manager still uses its earlier admitted session index. The
changed corpus affects BM25 on restart. No selective row filtering, fake delta
queue or changed cadence default was introduced to conceal that difference.
Actual original sync/watch defaults are retained; requested false knobs do not
disable the pinned resolver's automatic behavior.

## Authority, history and validation

Reference: OpenClaw `v2026.9.9`, commit
`bcfc88812a35243893585dbeca87ca41b48272ca`. The profile authenticates 62 source
owners, 65 compiled owners and the native file-safety artifact; release setup
checks the existing 83 packages/24,707 files. Approved Node remains 24.16.0 /
ICU 78.3 / Unicode 17, with the original executable hash. Memory-only cases
retain three main-process and nine worker traces; the sessions case has three
main-process and 13 worker traces. No source-build reproduction is claimed.

- `work/host-restart-policy/attempt-001/` retains the clock-only capture and
  its original source hashes: four mismatches, zero blocked/errors.
- `work/host-restart-policy/attempt-002-clean/` retains the final factory capture.
  Report size: 16,594,075 bytes; SHA-256:
  `f2970e8aabb5f16da0b580b50f46335d4298391c82f0bdf4213d1ed98645e2c0`.
- `work/host-restart-policy/original-family-after-fix/` reruns the unchanged old
  three literals against this SDK: three mismatches, eight differing paths each,
  zero blocked/errors. The original 20-path captures stay unchanged and bound to
  their original SDK. Their literal manifest, original Python family and original
  preload remain byte-identical to pushed `2be9ace`.

The initial targeted run caught two stale duplicate-context monkeypatches;
tests now use the actual host clock. The first full run is retained unchanged:
6,824 passed, two stale expectations failed and 1,648 skipped in 310.22 seconds.
The Lab privacy test now expects genuine acquisition metadata while still
comparing the entire owner result. Quickstart injects its clock at HostKit.open
and retains full payload equality. Both corrected tests pass. Source inventory
also caught ten moved Python anchor lines; only those line numbers changed.
The corrected inventory still validates 64 contracts, 128 conditions and 196
upstream modules without granting behavioral credit.

The combined focused selection passes 97 tests. Both clean offline wheel/sdist
consumers pass installed imports, real FTS/host lifecycle, durable sessions,
save/immediate recall/reopen, provenance/trust and public types, including ten
rejected invalid typed calls. The final complete regression run on `3d39398`
passes **6,826 tests, zero failures and 1,648 skips in 305.70 seconds**.
The skips retain the same historical/live and old absolute-runtime-path limits;
none grants acceptance credit. SDK and adapter bytes match the final comparison.

SDK source SHA-256 for 156 files:
`f6d56b8a1adbbec27cb71a92b0ba6d568ac3de6d3eb14f01b061ed6a0ca0aabb`.
The 1,403-case default catalog was not rerun in this follow-up. Its historical
`b090394` result (1,389 matches/14 differences) belongs to the earlier SDK source
hash, not this changed HostKit. The historical 64/128 count is not new execution
credit for this tree. Raw captures/dependencies remain ignored local artifacts;
the Git push includes summaries and identities. No paid model calls occur.

Next, declare a common **producer** rebuild stage after metadata setup on both
hosts and retain each real publication. Then address actual cold-index bootstrap
and session-admission/publication owners. Preserve the existing cold and
sessions-enabled diagnostics; matching only warmed memory-only cases cannot
close both restart conditions. Acceptance registration and a fresh complete
gate remain later work.

Reproduce the new family with existing verified dependencies and a new path:

```sh
.venv/bin/python scripts/check_host_restart_policy.py \
  --reference work/openclaw-v2026.9.9 \
  --node work/node-v24.16.0-linux-x64/bin/node \
  --release-runtime .reference/release-runtime \
  --output work/host-restart-policy-new-attempt
```

The command refuses an existing output path and never downloads or retries.
Exit 1 retains genuine mismatches; exit 2 denotes blocked/error cases. No exit
status grants acceptance credit for these development inputs.
