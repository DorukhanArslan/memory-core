# Fixed #53 whole Doctor baseline

This separate Doctor worktree began at `20ab9c8` and carries the independently
reviewed owner/version and first-edit fixes as `7bd859f` and `40f6327`.
The original owner-17 packets remain historical evidence for their own producer
hashes. The Doctor branch's separate `0656f5b` authority hardening removes the
unused STORE Doctor label and rejects mixed STORE/Doctor/release contexts;
it does not reattribute those historical packets or award any points.

Every Doctor case has `covers: []`. Doctor source/API behavior is captured before
any Doctor SDK fixes. Scope remains fixed `heartbeat.scratch`, including its
migration and reconstruction boundaries. No heartbeat decision, scheduler
execution, model/provider behavior or #55 credit is claimed.

The current literal bindings manifest SHA-256 is
`e08e2474e9582bac3fed1730cefe66c5c10a4d001380559191c85ba9bc1622c2`.
It pins 38 original source files and 26 official compiled artifacts, their real
export aliases, private bundled source regions and exact caller/worker roles.
The exact earlier manifest is retained separately with SHA-256
`1f572b21305684bae8b684d510f3cd9666f83f16e920262591f828ec71b6f29a`.
Only the declared inherited context-variable name changed between them.

The current codec/observer appendix SHA-256 is
`86671a5b11a40cfcd5299c5a867a7c8f27898112055bdaa7c3bbc2eeccd54a38`.
The exact initial appendix remains retained with SHA-256
`284a9059aa04e09ab53e7b91a0dc806ff4b1f4def9aebb39028eb4f8c1352e52`.
Its additions declare actual original termination-Promise observation and
separate synchronous readonly return/after-close state cuts. Comparison still
uses only a proper literal fixture-root prefix relation. It never replaces
generated monitor IDs, archive suffixes, PIDs, timestamps, counters, CLI hints,
error text or source/archive bytes. All four actual document byte sets are
authenticated separately before and after a batch.

The compiled reference is the official publisher-attested `v2026.9.9` artifact
at original commit `bcfc88812a35243893585dbeca87ca41b48272ca`.
`sourceBuildReproduced` remains false. The private runtime has the unchanged
83-package authenticated base plus exactly `croner@10.0.1`. Its source-lock
SHA-512, full eight-file installed tree and original archive are rechecked
before and after execution. Neither shared installation nor shared manifest is
modified. Archive SHA-256:
`d6d93c286125fed567b986a576ff1daa74e72d56bb63fe28248ca17cfcb00cee`.
Installed croner tree SHA-256:
`dbf132f1899f1bbb92ec5f8fcc8519a7569337139c0004292862eeab87ce38e1`.

The Doctor-only capability has its own kind and `MEMORY_EQ_DOCTOR_CONTEXT`.
STORE and release context variables are rejected. Exact literal operation,
clock, agent/config and owned path schemas are checked before original module
imports. The complete config and each actual call's arguments are captured
before invocation. Unsupported SDK preview input produces its real TypeError;
the adapter supplies no local preview, ownership resolver, migration decision or
expected-native state.

Native calls use the original `collectHeartbeatScratchMigrationFindings` and
`maybeMigrateHeartbeatFilesToScratch`. Repair uses the original
`ensureHeartbeatMonitorJobs`, `CronService.list/add` and genuine async
`cron.loadMutable`, `cron.scheduleUnowned`, `cron.saveChanges` path. No Gateway
completion wrapper is installed: that would change the original async save to
a synchronous path. `cronEnabled: false` prevents automatic execution while
preserving the caller's required state materialization.

Only the real `dist/infra/sqlite-store.worker.js` carrier is admitted. It loads
the original `dist/state/openclaw-state.worker.js` backend, state runtime and
runtime-maintenance owners. Different or nested workers are rejected. The
original compiled constructor clears execArgv, so the exclusive preload is
inherited through NODE_OPTIONS. Every main/worker bootstrap records the actual
binary, environment and execArgv, with a genuine Date-only `node:test` clock.
setTimeout, setInterval and performance.now identities remain unchanged.

Worker and MessagePort observations forward the same original receivers,
messages, transfer lists and remaining arguments. They retain actual returns,
errors, private native commit/settlement receipts and shared decision bytes.
No worker class, port, backend, reply or admission outcome is substituted.
The terminate observer returns the exact original Promise and records its real
resolution/error. An actual termination code of one remains one; it is never
rewritten into a fabricated successful exit zero.

Immediately after each actual awaited caller return, a synchronous Node SQLite
readonly observer captures complete schema/table rows (exact bigints/blobs)
and physical state bytes before another await. Its connection is query-only
and uses a read transaction; it performs no schema preparation or writes.
A distinct snapshot follows the genuine canonical owned database close and
actual worker retirement. The observer does not call the mutation-capable
public mutable cron loader. Original read-only monitor accessors retain the
complete monitor envelopes. Source/archive observers retain actual bytes,
links, modes and physical statistics; an unreadable entry retains its actual
error while other directory entries continue to be observed.

The literal corpus contains 22 cases: ordinary/empty/CRLF/BOM/no-source and
reopen, operator scratch and explicit unset, shared enabled and disabled owners,
a custom store, invalid UTF-8/size, contained/escaping symlinks, hard links,
directories/chmod, and real exited/live/single-thread-zombie/multiple/orphan
claim PIDs. Claim liveness is witnessed through actual /proc status rather than
invented PID values. Each reconstruction phase is a fresh native and SDK
process. A chmod fixture is restored only during explicit post-case artifact
cleanup, after all engine observations, with a separate mode/actual-byte receipt.

The collector requires a one-to-one correspondence between every encoded
input/value/preparation field in the original transport traces and the decoded
rows. Missing, extra or duplicate decoded rows are rejected before the actual
command whitelist is evaluated. It also binds each engine's exact public
operations and complete snapshot list to its retained raw calls and snapshots
before comparison. The focused authority and completeness suite passes 38
tests; its synthetic negative inputs are guard tests, not captured evidence.

Run a new first baseline output only after final independent authority review:

```sh
env OPENAI_API_KEY= OPENROUTER_API_KEY= \
  /workspace/memory-core/.venv/bin/python -m equivalence.heartbeat_doctor_probe \
  --checkout /workspace/scratch/openclaw-equivalence-v2026.9.9 \
  --runtime-cache /workspace/scratch/memory-core-heartbeat-doctor-lane/.reference/release-runtime \
  --node /workspace/openclaw-memory-bridge/node_modules/node/bin/node \
  --output /workspace/scratch/heartbeat-doctor-baseline-first
```

Use `--case doctor-ordinary` for a separately retained ordinary pilot. A rejected
attempt is preserved with original streams/traces, explicit rejection and
after-authentication. It must never be silently retried or promoted to accepted
evidence. The baseline intentionally retains real CLI/layout/generated-identity
and unsupported-preview differences; no complete #53 condition can receive
credit before the full Doctor/OS work, independent review and integrated gate.
