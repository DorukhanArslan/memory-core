# Session publication owner development closeout

Prepared 2026-11-09 (Europe/Istanbul). This package adds actual SDK publication
owners and regression evidence. It adds **zero acceptance conditions**. The
latest verified baseline remains **64/128**, with **64 remaining**: 29 complete,
six partial and 29 pending contracts. The fixed scope SHA-256 remains
`a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9`.

## Implemented behavior

`SQLiteMemoryStore.reindex_sources` prepares an explicit memory/session scope
through the existing readers, chunking, embeddings, provenance and atomic CAS
publisher. Selected deletions stay inside that scope, while other valid source,
chunk, FTS, path and metadata rows remain intact. Full reindex semantics remain
unchanged. A cold, mismatched or invalidated namespace requires explicit full
repair; the selected API does not silently broaden the refresh.

`MemorySessionCatalog.subscribe_transcript_changes` publishes immutable hints
after the actual append/replace transaction commits and its connection closes.
Hints contain that transaction's real session/catalog revisions and generation.
Rollback, replay and no-op append do not notify. Observer failure is retained in
redacted diagnostics without relabeling a committed write as failed. Durable
path aliases share the actual catalog owner; independent volatile databases
with the same sentinel path retain distinct listener namespaces.

The optional `SessionPublicationController` starts explicitly. It compares
actual admitted corpus fingerprints with published SQL source state at startup,
queues committed changes with a first-event five-second timer, and publishes
only the selected session targets. New arrivals remain owned during an active
publication. Failed claims stay visible for a later genuine admission or
explicit retry. Reconciliation handles missing or newly excluded session paths.
Close cancels a future timer and joins work already admitted, without forcing
pending targets to publish early.

`ManagedSQLiteMemoryStore.bind_session_publication` is inert. Its first valid
nonempty query starts the controller only after the existing SQLite read
transaction has pinned index identity. Scoring and hydration keep that real
read generation. A bounded journal records the revision read through the
leased connection. Closing and controller startup share one admission gate:
an admitted query can finish while new background work is refused.

The [API guide](session_publication.md) describes usage, status and ownership.
Construction without the controller and the existing eager `HostKit` and
`HostSessionRunner` paths retain their complete awaited publication behavior.

## Verification and identity

The changed SDK has **158 Python source files**, canonical SHA-256
`0a7f3570321f63e1bc43070891c41294902e01d58b09141834daf49b75823608`.
This identity describes the implemented SDK, not a new differential execution.

The actual WAL regression completes a genuine background publication while a
query still holds its previously admitted read transaction. Its returned scores
match that old generation; the next query reads the newly committed generation.
It does not supply saved result rows or copy expected scores into the backend.
Another integration test lets the real default five-second timer publish a
committed transcript without an injected scheduler or early flush.

Regression coverage also exercises selected-source preservation and deletion,
source/CAS/provenance conflicts, rollback, replay, concurrent catalog peers,
notification namespace isolation, failed scheduling and executor admission,
arrival during publication, worker handoff, and managed/controller close races.

Both offline installed wheel and sdist consumers pass, including actual scoped
publication, committed queue delivery and managed query admission. Their valid
typed consumer passes and **19 invalid public calls are rejected**.
The complete regression run passes **6,991 tests**, with **1,648 uncredited
skips**, in 331.93 seconds. The skips retain the previous historical/live and
old absolute runtime-path limitations; they award no acceptance credit.
Ruff, diff checks and the authenticated source inventory pass: 64 contracts,
128 fixed acceptance points and 196 upstream modules, with no behavioral credit
from the inventory.

The retained local verification logs are
`work/session-publication-full-regressions-001.log` and
`work/session-publication-distribution-001.log`. The complete regression command
is `.venv/bin/python -m pytest -q`; the package check is
`UV_CACHE_DIR=/workspace/memory-core/work/uv-cache UV_OFFLINE=1 UV_DEFAULT_INDEX=https://pypi.org/simple UV_INDEX_URL=https://pypi.org/simple .venv/bin/python scripts/check_distribution.py`.

## Remaining boundary

No fresh Native/SDK process comparison or full differential catalog was run for
this changed SDK. All 15 existing frozen restart inputs, profiles and their
historical captures remain unchanged. The previous managed packet's three
matches and one two-score-field session mismatch describe its original SDK;
they are not relabeled as executions of this controller.

The next implementation is an explicit managed runner/outcome that publishes
memory files at its chosen barrier and reports pending session publication
separately. Its curator must retain the real write/index lock while selecting
the memory scope. It must acquire the managed owner after actual user-message
persistence and preserve honest durable index markers. The existing eager
runner's `ready` contract must remain intact.

After that integration, a separately frozen genuine Native/SDK process family
must exercise startup, admitted read generations, committed queue delivery,
publication failures and close/restart boundaries. Complete results and actual
score fields must remain visible. Only complete registered acceptance evidence
and a fresh full gate can award the two still-open `host.restart-recall`
conditions. Metadata/archive/tombstone changes currently require explicit
reconciliation or later startup; there is no cross-process event bus or
background memory-file watcher in this package.
