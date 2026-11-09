# Heartbeat scratch observations

This lane belongs only to fixed contract `heartbeat.scratch` (#53). Every case
has `covers: []` and every report awards zero acceptance points. Cap or store
helper agreement alone does not establish either complete condition: the
contract also requires doctor migrations, persisted state and diagnostics after
reconstruction. Scheduler execution and heartbeat turn decisions are separate
fixed contracts and receive no claim here.

The original reference is `v2026.9.9`, commit
`bcfc88812a35243893585dbeca87ca41b48272ca`. Official compiled npm artifacts are
authenticated separately from original source declarations; their publisher
build attestation has `sourceBuildReproduced: false`.

`equivalence/heartbeat-bindings.proposal.json` records literal original source
and compiled-owner hashes, direct export aliases, fixture roles, clocks and
transport rules. The scratch fixture uses original exported row helpers to
create or remove actual owning jobs. It never issues SQL to fabricate a
scratch row, revision or expected result.

The independent heartbeat capability pins Node 24.16.0, ICU 78.3, Unicode 17.0
and binary SHA-256
`b2959781cc5a74c357ffa02367efa8a0330cbb1c9cb347732fdfaaaca381cbcd`.
It imports no model, entry-provenance or generic backend capability. Its preload
checks the actual binary in every process, authenticates every imported
artifact byte and rejects network calls. The initial store profile admits no
workers. Date alone is controlled by genuine `node:test` mock timers; other
timers retain their original implementation.

Run the ordinary paired store observations with explicit paths:

```sh
/workspace/memory-core/.venv/bin/python -m equivalence.heartbeat_scratch_probe \
  --checkout /workspace/scratch/openclaw-equivalence-v2026.9.9 \
  --runtime-cache /workspace/scratch/memory-core-heartbeat-scratch-lane/.reference/release-runtime \
  --node /workspace/openclaw-memory-bridge/node_modules/node/bin/node \
  --output /workspace/scratch/heartbeat-scratch-baseline
```

Each reconstruction phase runs a fresh native process and a fresh SDK process
against its preceding phase's durable fixture. Native stdout is one complete
awaited JSON envelope. Reports retain original input, complete API outputs,
trace identity, SDK file bytes and original exception stacks. The only exception
class translation is the declared `HeartbeatScratchTooLargeError` to native
`Error`; messages and attributes remain intact. Unknown errors keep their
original class. Native `undefined` monitor lookup becomes `{ "absent": true }`
and is never merged with an existing monitor whose scratch revision is zero.
Input echoes compare their exact JSON UTF-16 code units: a Python literal
surrogate pair and the scalar produced by JSON decoding serialize identically.
Lone surrogates, replacement characters and Unicode normalization forms remain
distinct. Returned scratch content and hashes receive no normalization.

The baseline intentionally calls the SDK's actual APIs before production fixes.
A missing monitor lifecycle API produces its actual Python exception. The
adapter supplies no local monitor emulation, scratch CAS algorithm, migration
algorithm or expected outputs.

The subsequent owned-store adapter calls the production
`enroll_heartbeat_monitor`, `read_heartbeat_monitor_scratch`,
`read_job_scratch`, `write_job_scratch`, `delete_job_scratch` and
`remove_heartbeat_monitor` APIs directly. It uses the same 17 native inputs and
the same original native exports. Owner fixture setup invokes the real SDK
enrollment API with the fixture's literal agent/job identities; ownership is
never implemented in the adapter. Python `None` from monitor lookup uses the
already declared absent-monitor transport tag. The original pre-fix packets
remain separate and unchanged.

For production hosts, ownership is an explicit extension:

```python
store = FileAutomationStore(root, require_monitor_owner=True)
owner = store.enroll_heartbeat_monitor("main", "configured-monitor-main")
monitor = store.read_heartbeat_monitor_scratch("main")  # read-only
result = store.write_job_scratch(
    "main", owner.job_id, "- Check the queue\n",
    expected_revision=monitor.state.current_revision,
    expected_owner_generation=owner.generation,
    now_ms=now_ms,
)
```

Enrollment belongs to configuration, never to each turn or preview. The catalog
is durable and remains active after removal and reopening through the legacy
constructor. Its job-keyed orphan content and revision tombstones remain
available through explicit job reads; monitor lookup returns absence after
owner removal. Generations persist across removal/re-enrollment and reject
captured writers even if a job id and scratch revision are reused. The existing
atomic store transaction checks ownership and scratch revision together.
`save_jobs` uses that guard for combined scratch commits and cleans ownership
when a configured monitor id is removed.

`HostKit.heartbeat_prompt` resolves the actual monitor and captures its owner
without enrollment. `HeartbeatRun.write_scratch` writes through that captured
job/generation and revision. The Lab's explicit edit enrolls/adopts legacy state
once; subsequent browser drafts carry the captured owner as well as revision.
Default legacy custom stores retain their original interface. No monitor
cadence, scheduler execution or provider call is added by this extension.

Doctor observations require a private runtime copy plus separately authenticated
`croner@10.0.1`. The original source lock pins
`sha512-ixNtAJndqh173VQ4KodSdJEI6nuioBWI0V1ITNKhZZsO0pEMoDxz539T4FTTbSZ/xIOSuDnzxLVRqBVSvPNE2g==`.
Shared reference artifacts, manifests and virtual environments remain unchanged.

The first protected capture, `/workspace/scratch/heartbeat-scratch-baseline-first`,
was rejected during the hash case's input-echo validation after nine completed
cap pairs. Python raw dictionary equality distinguished a literal surrogate pair
from its JSON-decoded scalar despite their identical JSON code units. Original
raw stdout, stderr, traces, before/after authentication and the explicit
`capture-rejection.json` remain retained. Any subsequent run uses a separate
output directory and records the transport correction; it does not replace the
rejected packet.
