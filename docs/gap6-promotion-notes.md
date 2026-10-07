# Gap 6 notes: forget flow, recall events, daily flush trust and dreaming ingestion

Branch `worktree-agent-a734ad117f81053a9` (off `main`), OpenClaw `v2026.9.6` (`/tmp/openclaw-head`, Node 24.21.0).
This file is the hand-off for the parity docs: it lists the changes, the deviations and the remaining gaps so
whoever updates `docs/parity_matrix.md` (audit note 30), `docs/upstream_port_v2026_9_6.md` and `CHANGELOG.md`
has the evidence in one place. None of those three files was edited.

## What changed

### (a) Forget flow and the revision fence

- `memory_core/consolidation/forget.py` ports `forgetMemoryEntries` (`memory-forget.ts`),
  `planMemoryIndex`/`deleteMemoryIndexSources` (`memory-forget-index-sources.ts`), `collectTranscriptWrites`
  (`memory-forget-curated-writes.ts`), the report (`memory-forget-report.ts`), `referencesSession`,
  `scrubMemoryContent` and `resolveMemorySessionTargets`. It plans the purge (promoted entries named by the
  origin rows, session corpus lines and quotes, memory-file sections that name the sessions, recall entries,
  phase signals, session-ingestion checkpoint and seen scopes, consolidation preimages, index chunks and
  paths), writes the tombstones and fences the index in one guarded transaction, purges, rewrites each file
  against the content it was planned on, and finally deletes the origin rows. A lineage that changes while it
  plans makes it plan again.
- `MemoryEntryOriginLedger.record_session_tombstones_if_lineage_current` is upstream's `marked` transaction
  (origins read inside it, tombstones, exactly one revision bump). `IndexRevisionFence` (and
  `ledger.revision_fence(agent)`) is the index's handle on `memory_index_state`.
- `SQLiteMemoryStore(..., revision_fence=)` / `Memory.from_workspace(revision_fence=)`: `reindex` reads the
  revision before it builds and compares it in the publication transaction
  (`publishMemoryDatabaseTables`); a forget (or another publication) in between raises
  `MemoryIndexRevisionConflictError` and leaves the published index alone; a successful publication bumps the
  revision (the index tables' triggers upstream). Forgotten sessions leave the session corpus
  (`MemoryWorkspace(is_session_forgotten=)`, `MemoryCoreSessionCorpus(is_forgotten=)`).
- `memory_core/session_artifacts.py`: the transcript file-name classifiers `referencesSession` needs
  (`parseUsageCountedSessionIdFromFileName` and friends).

### (b) `memory.recall.*` host events

- `memory_core/consolidation/host_events.py` builds `memory.recall.recorded` and `memory.recall.skipped` and
  applies the event store's normalization (10 results, 2 KiB query, 256-byte paths, `storageTruncated`, 8 KiB
  JSON cap). `record_short_term_recalls(on_event=)` delivers them in stored form, like
  `memory.promotion.applied`: nothing for the `grounded` signal, nothing when every hit came from a forgotten
  session, a skipped-only recall emits just the skipped event, otherwise recorded then skipped.
  `HostKit(on_event=)` and `LiveSubjectConsolidation.record_recalls(on_event=)` pass the callback through.
  The truncation helpers moved here from `promotion.py` (it imports them).

### (c) Daily flush writer, dreaming ingestion, transcript scan

- `memory_core/memory_write_provenance.py` ports `createMemoryWriteProvenanceObserver`
  (`canonicalPathFromExistingAncestor`, the trust record before the commit, rollback, `clearAfterDelete`).
  `MemoryWorkspace.append_daily_memory(provenance=)` / `append_daily_memory_file(provenance=)` record the
  daily note's trust around the append; `FlushRequest` and `HostKit(artifact_provenance=)`,
  `after_turn(untrusted_turn=)`, `request_flush(untrusted_turn=)` wire the flush's `write` tool to it
  (untrusted turn: `untrusted` record, sticky).
- `memory_core/consolidation/daily_ingestion.py` ports the daily half of `dreaming-phases.ts`:
  `buildDailyIngestionResults` (heading-aware chunker, managed Light/REM block stripping, trust record
  resolution), `collectDailyIngestionBatches`, `ingestDailyMemorySignals`, `seedHistoricalDailyMemorySignals`
  and the checkpoint (`dreaming-ingestion-state.ts`).
- `memory_core/consolidation/session_ingestion.py` ports `session-ingestion.ts` and the session half of
  `dreaming-phases.ts`: `scanSessionIngestionSource` (fingerprint checkpoint, prefix-hash append detection,
  seen hashes, day rules, caps, foreign sources untrusted), `sessionExclusionReason` (tombstones and the
  admission policy), `appendSessionCorpusLines`, `collectSessionIngestionBatches`,
  `ingestSessionTranscriptSignals`.
- `run_dreaming_sweep(ingestion=DreamingIngestion(...))` runs both ingestions first for light and REM
  (lookback 2/7 days, limit 100/10, like upstream's defaults).

## Verification

Real TS oracle (each oracle call about 8 s), `OPENCLAW_ORACLE_NODE=/tmp/node24/bin/node`,
`OPENCLAW_ORACLE_REPO=/tmp/openclaw-head`; new ops in `scripts/openclaw_oracle_runner.ts`
(`dailyIngestionScenarios`, `sessionIngestionScenarios`, `sessionArtifactNames`, `memoryWriteProvenance`,
`forgetScenarios`; `recordRecallScenarios` now also returns the host events; `importPatched` loads a private
function by appending an export line to a copy of the real module, like the backfill op does).

| Area | Test | Oracle evidence |
| --- | --- | --- |
| recall events | `tests/integration/test_recall_events_oracle.py` | 77 passed: 17 named cases (recorded, skipped, both, grounded, daily, forgotten sessions, contaminated, >10 results, long query/path, 8 KiB cap, fractional lines) + 60 random mixes; events and recall store |
| daily ingestion | `tests/integration/test_daily_ingestion_oracle.py` | 12 passed: about 414 notes through the chunker (with and without trust records), 10 step scenarios (window, checkpoint, next dreaming day, edits, removal, quarantine, cap, rolled-back record, seed) on results, recall store, checkpoint, events |
| session ingestion | `tests/integration/test_session_ingestion_oracle.py` | 45 passed: 35 scan scenarios (11 named + 24 random) over the real `scanSessionIngestionSource`, 10 sweeps over the real `ingestSessionTranscriptSignals` with sessions in OpenClaw's SQLite store (tombstones, admission policy, windows, per-sweep cap, two agents): recall store, corpus files, origins, checkpoint, events |
| file names | `tests/integration/test_session_artifacts_oracle.py` | 2 passed: about 700 names |
| write observer | `tests/integration/test_memory_write_provenance_oracle.py` | 32 passed: trusted chains, sticky untrusted, edits in between, rollback, deletes, classification of 18 paths, symlink aliases inside and outside the root, dangling links, random chains |
| forget | `tests/integration/test_forget_oracle.py` | 35 passed: 11 named + 24 random workspaces on report, files, recall/phase stores, checkpoint, preimages, origins, tombstones, index rows left, revision moved |

Offline: `tests/unit/test_forget_and_fence.py` (18), `test_flush_provenance_and_ingestion.py` (9),
`test_ingestion_helpers.py` (7). Unit tested only, because the oracle cannot reach them: the `since` and
participant selectors and retained archives of `resolveMemorySessionTargets`; the revision fence inside
`SQLiteMemoryStore.reindex` (the Python store is not upstream's index; the ledger half, the revision counter
and the tombstone transaction are oracle tested in `test_origins_callers_oracle.py`); the lineage re-plan
loop; the host kit and sweep composition; the symlink refusals of the corpus append.

## Deviations (all labelled at their code sites)

- State upstream keeps in SQLite plugin state is JSON in `memory/.dreams/`: `daily-ingestion.json` (version 1)
  and `session-ingestion.json` (version 3), the legacy file names. One per-workspace ingestion lock replaces
  the workspace lock; each batch records under the recall store's own lock. Forget holds the workspace lock,
  the ingestion lock and the recall lock for the whole run.
- The host supplies session facts: `SessionCorpusEntry` for the transcripts (`transcript_source="sqlite"`
  mirrors upstream's SQLite branch: logical path `sessions/<agent>/<id>`, scope with legacy scope, reset-recall
  cutoff read from the events, the host's events start with a session header so message lines start at 2),
  `SessionInstance`/`SessionArchive` for the selectors, `load_session_metadata` for the admission policy.
- The index is `SQLiteMemoryStore` (chunks, paths and FTS tables): no `memory_index_sources`, vector or
  embedding-cache rows (`vectorRows` and `embeddingCacheRows` are 0) and no per-chunk provenance, so chunks
  cannot be selected as system-origin. A rewritten file's chunks are purged and a later `reindex` restores it.
- Fence atomicity: when the ledger and the index share one database file the revision check and bump run in
  the publication transaction (as upstream); with separate files the check precedes the transaction and the
  bump follows it, so a forget landing between them is not fenced. A forget bumps once per call (upstream's row
  triggers bump per deleted row; the tests compare "moved", not the count). The origin-ledger check before the
  index purge is a second read, not one transaction with the purge.
- Memory files are listed with `list_memory_files` plus the two DREAMS names (no `extraPaths`).
- Events: a recall hit without numeric lines gets line 1 in the event (upstream would throw on a non-finite
  number after writing the store).
- Excluded sessions record `mtimeMs: floor(updatedAtMs)` (upstream stores the raw number).

## Remaining gaps

- The light and REM phase bodies still do not stage daily-only entries (`ingestDreamingPhaseSignals` is
  ported, the rest of `runLightDreaming`/`runRemDreaming` and the narrative are not); the deep phase is
  unchanged. `run_dreaming_sweep` ranks only entries with a recall.
- Nothing calls `forget_memory_entries`, `ingest_*` or `HostKit(artifact_provenance=)` on its own: hosts wire
  them (no CLI command, no scheduler). The session-memory hook (`save_session_memory`) still writes no trust
  record (upstream attaches the observer at `handler.ts:256`).
- Participant identities (`listSessionParticipantsReadOnly`) and archive enumeration come from the host.
- `sessionExclusionReason`'s metadata (`loadMemorySessionMetadata`) is a host callback.
- `consolidation_history` refusals in `DREAMS.md` are detected (oracle verified) but the history itself is not
  rewritten (upstream refuses as well).
- Upstream's hard-coded `openclaw-memory-*` marker names are matched through the package's marker prefixes
  (both spellings); markers written under an earlier project name are not recognised.
