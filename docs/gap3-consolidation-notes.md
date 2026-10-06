# Gap 3: the apply half of the deep phase (v2026.9.6)

Ported against OpenClaw v2026.9.6 (`extensions/memory-core/src/short-term-promotion-apply.ts`,
`memory-entry-origins.ts`, `dreaming-consolidation-artifacts.ts`, `src/memory-host-sdk/event-store.ts`,
`src/plugin-sdk/file-lock.ts`), each part checked against the real TS code through
`scripts/openclaw_oracle_runner.ts`. Tests: `tests/integration/test_promotion_apply_oracle.py`
(29 cases, one oracle start for all 24 apply scenarios) and `tests/unit/test_promotion_apply.py`
(20 offline cases).

## What changed

### (a) `rejectedCandidates`

`run_short_term_promotion` now ranks like `rankShortTermPromotionCandidates` (or takes the host's
`candidates=`, upstream's CLI path) and runs the apply stage of `applyShortTermPromotions`. The run
carries `rejected_candidates`, a tuple of `PromotionRejection(candidate, reason, category)`, with all
13 upstream categories: `origin`, `consolidation origin/session`, `contamination`,
`already promoted`, `score threshold`, `signal threshold`, `query threshold`, `age threshold`,
`selection limit`, `source rehydration`, `source changed`, `memory budget`, `candidate changed`.
Reasons carry the gate values exactly as upstream formats them (`toFixed(3)`, JS number text).
Compared with the TS result for 24 scenarios: category, reason and the authoritative candidate
(path, range, snippet, provenance taken from the store entry) for every rejection, plus the
applied candidates, MEMORY.md, DREAMS.md and the `promotedAt` marks.

Behavior that moved to match upstream (all visible in plain deterministic promotion too):

- ranking excludes entries with an `untrusted` or `system` origin (`isPromotionOriginBlocked`), so
  they never promote on any path (before, only the consolidation path filtered them);
- the consolidation origin/session filter runs after the rank limit, not before it, and any
  `DeepConsolidation` object (even one that is disabled or has no model) turns it on, like
  upstream's `options.consolidation`;
- candidates take path, range, snippet and provenance from the recall-store row (authoritative),
  rows `readStore` would drop (contaminated snippet, no path or range) count as absent, and a
  candidate whose row changed or was promoted while the model ran is rejected as
  `candidate changed` at lock time;
- the recall store's `updatedAt` never moves backwards.

### (b) `memory.promotion.applied`

`build_promotion_applied_event` builds the event in the stored form
(`normalizeMemoryHostEventRecordForStorage`: 10 candidates, 256-byte key/path/memoryPath with an
ellipsis, `storageTruncated`, the 8 KiB JSON cap). `run_short_term_promotion(on_event=...)` calls
the host callback once, after both locks are released, for every run that rehydrated a candidate
(like upstream, even when 0 were applied); the run also keeps it as `host_event`. Nothing is
persisted or sent anywhere. Compared with `readMemoryHostEvents` of the TS workspace, including the
long-path truncation and the 12-candidate cap. `run_dreaming_sweep` passes the callback through.

### (c) The second lock

`memory_core/consolidation/file_lock.py` ports `withFileLock` with `MEMORY_WRITE_LOCK_OPTIONS` and
`resolveMemoryPromotionLockTarget`: sidecar `<state dir>/locks/memory-promotion-<sha256 of the
realpath>.lock`, mode 0600, payload `{pid, createdAt, starttime}` plus the ownership-token line,
retry schedule 100 x (25 ms ... 250 ms, factor 1.2), `file lock timeout for <target>`, and
`fail-closed` recovery (`file lock stale for <target> [reason pid=... recorded-start=...
observed-start=...]`). The deep phase takes it first and the workspace lock inside it, as upstream;
`update_dreams_file` (and so the consolidation summaries) takes the workspace lock too
(`store.memory_workspace_lock`: reentrant per call chain, waits up to 10 s, then
`MemoryWorkspaceLockHeldError`). The skipped-rewrite note is written after both locks are released,
the consolidation summary inside them. Verified: the real `withFileLock` for name, mode, payload
shape, directory mode and the timeout / stale / PID-reuse / ownerless-holder outcomes
(`fileLockProbe`), and the order lock acquire, MEMORY.md write, DREAMS.md write, lock release
from the fs calls of the real apply (`applyPromotionScenarios`, equal in all 24 scenarios).

### (d) The origins ledger

`memory_core/consolidation/origins.py` ports `memory-entry-origins.ts` over a real SQLite database
(stdlib `sqlite3`, upstream's `STRICT` DDL and conflict rule): `MemoryEntryOriginLedger.record` /
`list` / `delete`, `reserve_memory_entry_origins` (parent union, sorted agents, rollback) and
`prune_memory_entry_origins` (retained keys, both DREAMS files, sibling agents' indexed MEMORY
chunks). `store_memory_preimage` returns the retained keys and prunes the origins of expired
snapshots when given a ledger; the consolidation commit reserves before the rename and rolls back
on a skipped rewrite; the commit prunes after the store write. Compared with the real module over
the real per-agent database: 17 ledger steps (record, re-key, foreign agent error, list filters,
reserve with CRLF/unmarked/unknown prior entries, rollback, index retention incl. non-memory
chunks, diary retention, prune), a ten-snapshot rotation and five apply scenarios (merge union and
prune, sibling index retention, skipped rewrite rollback, append-only prune). The database path is
the host's (`path_for_agent`).

## Deviations

- No `state_dir` falls back to `<workspace>/memory/.dreams` (upstream: `resolveStateDir()`); the
  sidecar is created and removed there and an empty `locks/` directory stays.
- Upstream takes neither lock when no candidate is rehydrated; memory-core always takes both (the
  existing "promotion locked" no-op result for a held workspace lock stays, with or without
  candidates), so the lock timeline of such a run is acquire/release only.
- A held workspace lock returns `"promotion locked"` (upstream waits 10 s and throws); only the
  DREAMS.md writers wait. The workspace lock is memory-core's lock file, not upstream's plugin-state
  lease, so a TS and a Python process do not exclude each other on it, only on the sidecar.
- The sidecar lock supports `fail-closed` and `remove-if-unchanged` recovery in-process and
  across processes by `O_EXCL`; fs-safe's reclaim guard, admission contexts, `reentrantOwner` and
  compromise monitoring are not ported.
- Preimages stay in `memory/.dreams/consolidation-preimages.json` (upstream: SQLite plugin
  state); the TS side of the rotation test uses upstream's store.
- Session tombstones and the `memory_index_state` revision fence are not ported (host session
  index). `memory_index_chunks` is read from the ledger's database when present, else from the
  host's `indexed_promotion_keys` callable.
- The daily-file quarantine (`listMemoryArtifactProvenance`) is not ported: it needs the host's
  flush provenance records.
- A malformed host event is not a `TypeError` (the event is built, not validated from input).

## Remaining gaps

- Nothing in memory-core records origins yet: `recordMemoryEntryOrigins` has two upstream callers
  (`short-term-promotion-record.ts:370`, `session-backfill.ts:316`) and `memory-forget.ts` reads
  them; the Python recall recorder and session ingestion do not write the ledger, so a host fills it
  with `MemoryEntryOriginLedger.record` itself.
- A recall store that changes while the model runs is covered offline only: the TS test helpers
  keep the store in process memory, so the oracle cannot change it mid-run (`candidate changed` from
  a changed source file is oracle-verified).
- REM/light narrative writes of `run_dreaming_sweep` (`_append_dreams_section`) do not take the
  workspace lock.
- `readStore` normalization in the Python store reader is still lenient (the apply stage filters the
  rows `readStore` drops, the reader and the recall recorder do not).
