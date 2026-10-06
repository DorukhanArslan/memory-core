# Gap 4: origins ledger callers, tombstones, revision fence, daily-file quarantine

Ported against OpenClaw v2026.9.6 (oracle checkout `/tmp/openclaw-head`), on top of the ledger and apply stage of the
previous round. CHANGELOG.md,
`docs/parity_matrix.md` and `docs/upstream_port_v2026_9_6.md` are untouched.

## Changes

- `record_short_term_recalls` (`consolidation/recall.py`, upstream `recordShortTermRecalls`,
  short-term-promotion-record.ts:370): new `origins=` ledger. A hit may carry `sessionOrigin`
  (`agentId`, `sessionId`, `sessionKey?`). Under the workspace lock, hits of a tombstoned session
  are dropped (all dropped: nothing written); each written entry records one origin row per source
  session (the hit's `provenance` origin class and `observedAt`, default agent at now) before the
  recall store is published. `record_grounded_short_term_candidates` passes `origins` through.
- `consolidation/session_backfill.py` (new, upstream session-backfill.ts):
  `build_session_backfill_diary_entries` (line 316: the diary blocks and their `memory:session-backfill:<sha256>`
  marker keys, origins recorded before return), `coalesce_backfill_claims`, and
  `record_session_backfill_day` (the grounded-signal half of `applySessionBackfillDays`).
- `consolidation/origins.py`: session tombstones (`list_session_tombstones`,
  `record_session_tombstones`: batches of 128, `ON CONFLICT (session_id) DO NOTHING`, revision bump when
  any row is new) and the `memory_index_state` revision fence (`index_revision`, `bump_index_revision`,
  `assert_index_revision` raising `MemoryIndexRevisionConflictError` with upstream's message).
- `consolidation/artifact_provenance.py` (new, upstream src/memory/memory-artifact-provenance.ts):
  `MemoryArtifactProvenanceStore` (`record_write` with rollback, `clear`, `read`, `list`, 50,000-entry
  reject-new limit) and `with_daily_file_quarantine`. `run_short_term_promotion(artifact_provenance=...)`
  applies it to every ranked candidate before the gates, like `withDailyFileQuarantine`: every
  candidate of an `untrusted` daily file becomes `untrusted` (session kind kept, `observedAt` the
  record's) and is rejected by the `origin` gate, whatever the recall store says.
- Oracle runner (`scripts/openclaw_oracle_runner.ts`): ops `recordRecallScenarios` and
  `sessionBackfillLineage`; `originsLedger` gained `tombstone` / `tombstones` steps and reports
  `tombstones` and `revisions` per step; `applyPromotionScenarios` seeds trust records through the real
  `recordMemoryArtifactWriteProvenance` (`seedArtifactProvenance`, optional `rollback`) and reports
  `listMemoryArtifactProvenance`.

## Verification

- Real oracle: `tests/integration/test_origins_callers_oracle.py` (19 tests: 10 recall scenarios,
  6 backfill scenarios, tombstone and revision steps over the real agent database, plus coverage
  guards) and the 7 new quarantine scenarios of `tests/integration/test_promotion_apply_oracle.py`
  (37 tests in the file). Compared: recall store entries, origin rows, tombstones, revision counter,
  diary entries (marker keys hash `JSON.stringify([day, line])`, including a lone surrogate, an
  astral character, U+2028 and control characters), coalesced claims, rejected candidates with their
  rewritten provenance, applied candidates, MEMORY.md/DREAMS.md, and the trust records written by the
  real writer against the port's.
- `buildSessionBackfillDiaryEntries` and `coalesceBackfillClaims` are private upstream: the runner loads
  the real session-backfill.ts through a temporary copy with one extra `export` line (removed again).
- Not reachable through the oracle, ported from source and unit tested
  (`tests/unit/test_origins_callers.py`, 22 tests): the REM branch of the diary builder
  (`previewGroundedRemForFile` is not ported; the host passes `rem_preview`), the publication fence's
  message, ledger-failure ordering (no staged entry without its lineage), trust-store limits and rollback.

## Deviations

- Without an `origins` ledger, `sessionOrigin` on a hit is ignored (upstream always has the agent
  database); without an `artifact_provenance` store no file is quarantined.
- `record_session_tombstones` creates `memory_index_state` (seeded at revision 0) when absent; upstream's
  agent database always has it. The oracle shows the same counter values from a fresh real database.
- The trust store is a SQLite file of the host's choosing with upstream's key and record shape, not
  OpenClaw's plugin-state database; the file is not shared with OpenClaw.
- The session backfill has no transcript scan, rewind journal or CLI: the host supplies
  `SessionBackfillCandidate` values. JS `^` in `/^##\s+/gm` also matches after `\r`, U+2028 and U+2029;
  the REM heading strip only matches after `\n`.
- Quarantine reads the trust records once, before the locks (as upstream does); a record written during
  the apply is not seen by that run.

## Remaining gaps

- Nothing in memory-core writes tombstones (upstream: `memory forget`), and the Python index
  (`SQLiteMemoryStore.reindex`) does not consult the revision fence; `assert_index_revision` is the
  primitive a host's rebuild publication calls.
- The daily-file flush that writes the trust records (`recordMemoryArtifactWriteProvenance` callers) and the
  dreaming daily ingestion that reads them (`resolveDailyFileProvenance`, dreaming-phases.ts) are not ported.
- `memory.recall.recorded` / `memory.recall.skipped` host events are still not emitted.
- Session ingestion's own tombstone filter (`sessionExclusionReason`, session-ingestion.ts:184) belongs to the
  not-ported transcript scan.
