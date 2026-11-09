# Fixed #53 scratch baseline handoff

Worktree: `/workspace/scratch/memory-core-heartbeat-scratch-lane`, based on
`2a56ed8`. Production SDK files are unchanged. The frozen root candidate,
shared reference installation, shared manifest and virtual environment were not
modified. This work is limited to `heartbeat.scratch`; it adds no scope and
claims no heartbeat decision or scheduler behavior.

## Completed ordinary observations

`/workspace/scratch/heartbeat-scratch-baseline-wire2/report.json` contains 17
zero-credit cases and 25 fresh-process phases. Twelve cases match completely;
15 phases match. Every case has `covers: []`; the report awards zero acceptance
points. Cap/store helper agreement does not satisfy the complete #53 scope,
which still requires doctor migration, OS claim recovery and diagnostics after
reconstruction.

The report SHA-256 is
`29fd3b5ef77262bb4865f71659619827d133f52d9b68328374ba793fc0e074c0`.
The retained packet has 271 files. Its `packet-manifest.json` SHA-256 is
`ebbfc52cba33c40df760c519c03d8b1b75798a59f077f90e6aee0f4d0ca34975`.
The packet retains requests, complete raw stdout/stderr, API call results,
original exception stacks, process import traces and before/after authentication.
The two authentication objects are equal.

The matching cases cover nine UTF-8 cap boundaries, five source hashes, the
write/read/unset/delete/CAS/provenance sequence and partition/job isolation.
The sequence also matches across two fresh-process reconstruction continuations.
Each process invokes the actual original exported scratch owner and actual SDK
API. Original exported row helpers establish real native ownership; there is no
SQL revision fabrication or local implementation of scratch rules.

The five differing cases are:

- `scratch-no-monitor`: native monitor absence is distinct from revision zero,
  and a late write returns `revision-conflict` at revision zero. The SDK lacks a
  monitor lookup API and accepts the write as revision one.
- `scratch-present-monitor`: native lookup returns the complete `{jobId, state}`
  envelope for absent, empty and unset scratch. The SDK's attempted real lookup
  raises its actual `AttributeError`.
- `scratch-deleted-owner-content`: after original `replaceCronRows` removes the
  owner while retaining revision-two content, native rejects a late writer and
  preserves that content. The SDK lacks owner removal and accepts revision three.
- `scratch-deleted-owner-tombstone`: the same boundary preserves native revision
  two without content; the SDK writes revision-three content.
- `scratch-deleted-owner-cleanup`: original `deleteCronJobRowInDatabase` removes
  owner and scratch, and late native writes remain rejected at revision zero.
  The SDK lacks owner removal and retains its previous row. Reconstruction
  preserves these different states.

Unsupported SDK operations are recorded as actual Python exceptions. The probe
does not emulate ownership locally or invent a native result for the SDK.

## Execution authority and retained rejection

The root independently verified the five original source and five compiled-owner
hashes/aliases in `equivalence/heartbeat-bindings.proposal.json` before capture.
The separate heartbeat capability admits only the reviewed heartbeat profiles
with exact Node 24.16.0 / ICU 78.3 / Unicode 17.0 binary identity. It borrows no
model, entry-provenance or backend capability. Original Node SQLite is the store
backend; the initial synchronous store profile rejects all workers. Genuine
`node:test` controls Date alone. All imported release/adapter files are
authenticated and networking is denied. No provider or model was invoked.

The first packet, `/workspace/scratch/heartbeat-scratch-baseline-first`, remains
retained and explicitly rejected. Nine cap cases completed, then Python raw
dictionary comparison rejected the hash case's input echo: a literal surrogate
pair and its JSON-decoded scalar contain identical JSON UTF-16 code units.
`capture-rejection.json` records the cause and the equal after-authentication
result. The original packet was not replaced. Its 101-file packet manifest has
SHA-256
`ed3f5431414f8cf711740f0f357e5c0b63969c0b96e87687232be6f46c514991`.

The separate wire2 run corrects only input-echo comparison through canonical
ASCII-escaped JSON code units. Tests prove lone surrogates remain distinct from
replacement characters and NFC remains distinct from NFD. Public scratch
results and hashes receive no normalization. The only declared exception class
mapping is `HeartbeatScratchTooLargeError` to native `Error`; messages,
attributes, causes and the original raw classes/stacks remain available.

Nine focused capability/transport tests pass:

```sh
/workspace/memory-core/.venv/bin/python -m pytest \
  tests/equivalence/test_heartbeat_scratch_authority.py -q
```

## Private doctor prerequisite and remaining work

A private reflink copy of the original 83-package runtime is available under the
worktree's `.reference/release-runtime`. The shared installation remains intact.
`croner@10.0.1` was fetched as an exact public npm archive after accessible local
caches had no copy. The first sandbox proxy connection failed; an approved
retry of the same request outside the sandbox succeeded. The package was then
authenticated against the genuine source lock and installed only in the private
copy. No shared package or manifest was changed.

Private archive:
`.reference/heartbeat-dependencies/archives/croner-10.0.1.tgz`.
Archive SHA-256:
`d6d93c286125fed567b986a576ff1daa74e72d56bb63fe28248ca17cfcb00cee`.
Eight-file authenticated tree SHA-256:
`dbf132f1899f1bbb92ec5f8fcc8519a7569337139c0004292862eeab87ce38e1`.
Complete file identities and source-lock integrity are recorded in the private
`.reference/heartbeat-dependencies/authentication.json`.
`equivalence/heartbeat_dependency.py` can recheck those exact archive/tree bytes.
It does not alter the shared release manifest or grant the store profile access
to this extra package. All compiled evidence retains
`sourceBuildReproduced: false`.

Next work should first review these genuine baseline gaps, then add persisted
SDK monitor identity/ownership and atomic owner-plus-revision guards through
production APIs. Doctor coverage still needs an independently reviewed exact
owner/clock/worker proposal around the original migration and cadence exports,
with the private croner package explicitly authenticated in that profile.
Important remaining inputs include shared owner retention/re-enable, archive
rollback, concurrent source replacement, live/stale/multiple/orphan claims,
single-thread Linux zombies, contained/escaping links, invalid UTF-8 and native
failure diagnostics after reopening. The existing Python zombie check only
uses `os.kill(pid, 0)`, whereas the original native owner checks `/proc` zombie
and thread state; this is a source-confirmed gap, not yet executable evidence.

No production fix, doctor capture, source-map credit, scope edit or integrated
full gate was performed in this handoff. Both fixed #53 acceptance conditions
remain uncredited pending complete execution, independent review and integration.
