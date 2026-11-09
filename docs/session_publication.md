# Explicit session publication

`SessionPublicationController` is an optional owner for publishing committed
session transcripts separately from memory files. It uses the actual session
catalog, admitted corpus readers and checked SQLite publisher. It does not
change `HostSessionRunner`'s awaited full-index barrier or its `ready` result.
Those eager APIs still publish every configured source.

## Selected source refresh

`SQLiteMemoryStore.reindex_sources(workspace, sources={"memory"})` refreshes
memory files while preserving existing session rows. Selecting `"sessions"`
refreshes the admitted session corpus. Optional `paths` restricts that refresh
and its removals to exact canonical relative paths; an empty collection selects
nothing. With `paths=None`, missing or newly excluded paths are reconciled
across the selected corpus. Unselected published sources remain intact.

Preparation, embedding cache validation, provenance, source revalidation and
atomic revision checks use the existing publisher. `force_sources=True` reparses
only the selection. A cold, mismatched or invalidated namespace raises
`MemoryIndexRequiresFullReindexError`; perform an explicit ordinary `reindex`
before selecting a scope. There is no implicit full refresh fallback.

## Controller admission

```python
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.host.session_publication import SessionPublicationController

# workspace.session_catalog must be this exact catalog. The configuration,
# workspace, index path and agent must describe the same owner.
store = ManagedSQLiteMemoryStore(config, workspace)
store.reindex(workspace)  # Explicit initial publication for this example.
controller = SessionPublicationController(store, workspace, catalog)
store.bind_session_publication(controller)
try:
    hits = store.search("drink preference", sources={"memory"})
    controller.wait_idle(timeout=5)  # Joins admitted jobs; does not fire a timer.

    # Later append_message/append_events/replace_events commits queue targets.
    # A memory-file publisher can refresh just its own corpus:
    store.reindex_sources(workspace, sources={"memory"})
    controller.flush(timeout=5)  # Explicitly admits pending session targets.
finally:
    store.close()
```

Construction and binding are inert. The managed store starts the controller
after a valid nonempty search has read index identity in its SQLite transaction.
That read pins the actual generation before asynchronous startup reconciliation
begins. Keyword scoring and result hydration retain that same reader snapshot,
even if a writer commits a later generation before the query finishes. The
bounded managed read journal records the revision read through that connection.

Startup compares genuine admitted sources and their hash/mtime/size fingerprints
with published SQL source rows. It recovers work left by an earlier process and
removes stale selected-session paths. `controller.start()` is also available
for hosts that explicitly own a different acquisition boundary.

`MemorySessionCatalog.subscribe_transcript_changes()` emits immutable
`SessionTranscriptChange` hints after transcript commits and connection close.
It covers `append_message`, `append_events` and `replace_events`; rollback,
idempotent replay and no-op append produce no hint. Listeners share the exact
physical catalog/agent namespace in this process. Ordinary listener exceptions
are recorded as redacted diagnostics and do not turn committed writes into
apparent producer failures.

The first committed hint arms a real five-second timer. Further hints retain
their actual transaction revisions without resetting the timer. Publication
claims a batch; arrivals during that batch remain pending. Failed claims remain
owned and visible rather than being acknowledged or immediately retried in a
loop. An explicit `flush()` can retry them. The original full `reindex` API
remains available for an independently chosen complete publication.

## Status and close

`status()` and `lifecycle_snapshot()` expose startup, pending/in-flight targets,
accepted and published generations, timers, errors and bounded job receipts.
Before startup discovery, `pending` is `None`: readiness is unknown.
`wait_idle()` joins admitted work only; a future timer can still own pending
targets. Its return value is not an all-source readiness assertion.

`close()` cancels an untriggered timer and joins actual admitted jobs, including
workers still preparing their selected publication. It does not flush pending
targets early. A later controller can recover their durable source changes at
startup. Managed close first refuses new calls and controller startup admissions,
then closes the controller and joins its physical publications and admitted
searches. An admitted query can finish without starting new background work.

Metadata, archive and tombstone changes currently require `reconcile()` or a
later startup scan. Other processes are observed through discovery; there is
no cross-process notification bus or background memory-file watcher here.
Hosts using the existing eager runner still get its full publication behavior.
The [shared managed host](managed_host_session.md) integrates per-chat runners
with separate pending session status and actual publication custody. These
primitives alone add no equivalence acceptance credit; credit belongs to the
complete authenticated process family in the full comparison gate.
