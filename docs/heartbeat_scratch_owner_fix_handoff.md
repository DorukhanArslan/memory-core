# Fixed #53 durable owner fix

The production fix is frozen at `b2326ef`, following the original uncredited
baseline commit `58950a6`. Worktree:
`/workspace/scratch/memory-core-heartbeat-scratch-lane`.
The frozen root candidate, main worktree, shared reference installation,
83-package manifest and virtual environment remain unchanged.

## Result and scope

The same 17 native inputs now match in all 17 cases and all 25 fresh-process
phases. Before the production fix, the retained baseline matched 12 cases and
exposed five monitor/ownership differences. No case or acceptance point was
added, and all cases still have `covers: []` with zero acceptance points.
Neither complete #53 condition is claimed: doctor migrations, OS claim recovery,
failure diagnostics, independent review and integration remain outstanding.

New packet: `/workspace/scratch/heartbeat-scratch-owned-first`.

- Report SHA-256:
  `43551b67597b708de48b74ba41d870d2481f7c7b74ffd54832952552f383de8f`.
- Its 270-file `packet-manifest.json` SHA-256:
  `94512c002af9fafece6fda72f37a6352233cf9fc38d1e479635a2bf52b47ab5e`.
- Exact 17-case input bytes SHA-256:
  `c0e33eeb013f7fe92626b6f347b0d6e457707853826ad0da026e7a1ef2fb8c1f`.

The case bytes match the pre-fix packet exactly. Native preload, runner,
Node-only authority, binding hashes, aliases and literal owner manifest are
unchanged from the reviewed baseline. The required original scratch owner runs
in each fresh native process with the same Date-only clock and strict no-worker
profile. Before/after artifact, binding, Node and SDK identities are equal.
The paired original compiled runtime still has 83 authenticated packages and
`sourceBuildReproduced: false`. The private doctor-only croner installation adds
no authority to this store profile.

Both earlier packets were rechecked against every retained manifest entry and
remain unchanged, including the rejected first surrogate input-echo capture.
The new fix packet completed on its first attempt with no rejection or retry.

## Production behavior

`FileAutomationStore` uses the existing private `automation.json`, advisory lock
and atomic replacement for both monitor ownership and scratch. The catalog
persists agent/job identity, active ownership, a retained generation and
job-keyed scratch. It validates its complete schema and bounded clocks/counters;
malformed state is refused without silent repair or partial publication.

The public extension supplies:

- `enroll_heartbeat_monitor`: explicit, idempotent enrollment; replacement or
  re-enrollment increments the retained generation. A job id cannot move across
  agents. Optional first enrollment adopts legacy content and revision intact.
- `read_heartbeat_monitor_scratch`: read-only `{jobId, state}` or absence; it
  never enrolls and does not expose retired scratch through monitor lookup.
- `read_job_scratch`, `write_job_scratch` and `delete_job_scratch`: explicit job
  state, including orphan cleanup. Writes check active agent/job binding,
  optional captured generation and scratch revision inside the same lock.
- `remove_heartbeat_monitor`: retire the owner while retaining orphan content or
  a revision tombstone, or clean scratch atomically when requested.
- `save_jobs`: a captured owner can guard an atomic job-plus-scratch commit.
  Removing a configured monitor id retires it and cleans scratch in that same
  transaction; a simultaneous scratch write to the removed owner is refused.

The UTF-8 content limit remains checked before ownership/CAS. The existing pure
scratch write rule remains the content/revision implementation. Constructor and
read operations do not enroll or write. Once an ownership catalog is persisted,
the opt-in is sticky across removal and all later default-constructor opens.

Legacy per-agent behavior remains the default before explicit opt-in. Hosts
enroll each configured agent and may adopt each agent's legacy scratch once.
`require_monitor_owner=True` refuses unowned writes even before enrollment; the
new diagnostic uses this explicit production capability. The result does not
claim that a never-enrolled legacy default store rejects all agent writes.
The old optional custom-store interface remains valid; the new ownership
protocol is an explicit extension rather than a mandatory ABI change.

Generation checking provides additional SDK protection when a deleted job id
and scratch revision are reused. That ABA protection has real SDK/process
tests, but the 17 native comparisons make no broader claim about native
generation-token interchange or every corrupt clock/error variant.

## Actual consumers and validation

`HostKit.heartbeat_prompt` reads the active monitor and captures its identity,
generation and revision without enrollment. A held `HeartbeatRun.write_scratch`
uses that captured owner, so deletion/replacement or later edits cannot redirect
the write into a new monitor. An orphan's instructions do not enter the prompt.
The Lab's first valid explicit scratch edit opts in/adopts legacy state; reads,
previews and invalid initial edits do not. Browser drafts retain job/generation
alongside revision and reject a same-id replacement even at an equal revision.
Existing legacy custom stores continue through their original per-agent API.
No scheduler execution, timer, provider call or new #54/#55 claim is added.

Validation completed:

- 89 focused core, ownership, migration compatibility, HostKit and capability
  tests passed. They include an external Python process losing its held owner
  write to removal, real reopen, orphan/tombstone retention, ABA at revision
  zero, cross-agent refusal, malformed catalog/clock/counter refusal with
  byte-identical state, atomic `save_jobs` conflict/removal and read-only previews.
- 24 heartbeat TestClient tests passed outside the sandbox with both
  `OPENAI_API_KEY` and `OPENROUTER_API_KEY` blank. The sandbox's known AnyIO
  self-pipe stall was diagnosed before ASGI dispatch; no owner lock was entered.
  The focused outer run passed, then the full heartbeat selection passed.
- Same-17 protected native/SDK comparison: 17 cases / 25 phases match, with
  complete before/after authentication and unchanged earlier packets.

Reproduce the core selection:

```sh
/workspace/memory-core/.venv/bin/python -m pytest \
  tests/unit/test_heartbeat_ownership.py tests/unit/test_heartbeat_scratch.py \
  tests/unit/test_heartbeat_migration.py tests/unit/test_host_kit_heartbeat.py \
  tests/equivalence/test_heartbeat_scratch_authority.py -q
```

The local TestClient selection requires the environment's approved outer local
IPC execution:

```sh
env OPENAI_API_KEY= OPENROUTER_API_KEY= \
  /workspace/memory-core/.venv/bin/python -m pytest \
  tests/demo/test_demo_app.py -k heartbeat -q
```

The standalone comparison command is documented in
`docs/heartbeat_scratch_equivalence.md`; use a new output directory for each run.
All Native inputs and outputs come from the same real original exports. SDK
setup calls the real enrollment API using the literal fixture identities, then
job-bound read/write/delete/removal APIs. The driver implements no local owner,
revision, tombstone or expected-native state.

Doctor work remains a separate next proposal using the already authenticated
private `croner@10.0.1` archive. No doctor capture, condition credit, source-map
promotion or integrated full gate was performed for this fix handoff.

## Independent review correction

Independent read-only review found that `_load` filled the legacy default
`version: 1` before validating an existing ownership catalog. Removing the
required top-level version could therefore bypass refusal and a subsequent
write could silently restore it. The correction validates the original owned
catalog before applying any legacy defaults. Missing or invalid owned-store
versions now refuse reads and writes with byte-identical persistence; a store
without an ownership catalog retains the existing legacy default behavior.

Seven new parameterized/version compatibility tests exercise existing and
freshly reopened stores, monitor/job reads, job-bound and per-agent writes, and
`save_jobs`. The expanded focused selection passes 96 tests. This correction is
not represented by the historical 17-case producer hash `b2326ef`: that packet
remains unchanged and its claim remains limited to the recorded inputs. No
native packet was rerun for this previously unexercised malformed SDK state.
Subsequent full-gate or Doctor evidence must bind the corrected SDK source hash.
