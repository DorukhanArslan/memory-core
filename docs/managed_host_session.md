# Shared managed host sessions

`ManagedHostSession` owns one agent's kit, catalog, index and session publisher
for a running host. Create per-chat runners from that owner. A new chat in the
same host reuses its actual owner; a restarted host opens a new owner over the
saved files and catalog. The eager `HostKit.open` and `HostSessionRunner.open`
APIs keep their awaited full-index behavior.

```python
from pathlib import Path

from memory_core import FeatureFlags, MemoryConfig, SessionState
from memory_core.host.managed_session import ManagedHostSession
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_visibility import resolve_memory_search_source_policy

root = Path("agent-workspace").resolve()
catalog = MemorySessionCatalog(root / "sessions.sqlite", agent_id="main")
config = MemoryConfig(
    workspace_dir=root,
    session_search=True,
    flags=FeatureFlags(vector_search=False),
)
policy = resolve_memory_search_source_policy(
    ["memory"], remember_across_conversations=True,
    configured_session_memory=False,
)
owner = ManagedHostSession.open(
    root, catalog=catalog, config=config, source_policy=policy,
    initialize=False,
)
try:
    writer = owner.runner(SessionState.new(
        session_key="agent:main:writer", session_id="writer",
    ))
    fresh = owner.runner(SessionState.new(
        session_key="agent:main:fresh", session_id="fresh",
    ))
    # Run these runners with the application's normal model callbacks.
    # They share the exact kit, index and session controller.
    status = owner.publication_status()
finally:
    owner.close()
```

Construction is inert: it does not publish the corpus or start a session timer.
Create managed runners through `owner.runner(...)`; the inherited eager
`ManagedHostSessionRunner.open(...)` route is rejected before filesystem work.
`initialize=False` also avoids creating workspace templates. Search uses the
real managed cold-index repair path when required. For an existing valid index,
the first search pins its SQLite read generation before admitting asynchronous
startup work. Subsequent chats reuse that controller rather than starting a new
startup scan for every fresh session.

## Writes and readiness

The managed kit keeps the curator's real write/index lock and publishes only
memory files after an ordinary memory write. A cold scoped write can commit its
file while publication remains pending. Its result includes
`indexStatus: "pending"`; this is not reported as an indexing failure. Ordinary
turn finalization, before-turn repair, flush and memory-publication
acknowledgment also retain the managed memory scope.

Committed transcript changes enter the real session controller queue. Ordinary
turns do not flush its future timer or force session publication to report
readiness. `ManagedHostTurnOutcome` retains the normal outcome fields and adds
an emission-time `publication` snapshot. Its inherited `ready` remains false
for pending, failed or uncertain work. A snapshot is historical; later
background progress does not rewrite a completed outcome.

`owner.publication_status()` reports `memoryIndexStatus`, `sessionIndexStatus`,
`indexStatus`, `sessionPending`, the controller state and current owner custody.
Before startup knowledge, session publication can be unknown. Durable
`sdkHostLifecycle` metadata keeps `needsMemoryIndex` and `needsSessionIndex`
separately, with `needsIndex` as their logical OR. Actual retained memory/full-publication
failures also keep readiness pending when a direct kit/curator call has no durable
turn marker. The read-only failure snapshot remains available after close. A source
already published can be current even while older queue hints remain pending; readiness stays
conservative until the corresponding work is acknowledged.

## Explicit publication and close

`owner.reindex(force=True)` requests real full publication and joins its actual
startup/reconciliation work. This is an explicit, stronger SDK owner barrier;
it does not claim that every Native manager's force call waits for all startup
discovery. It propagates an actual startup failure before another reconciliation
can hide it. A later explicit call can retry after the caller repairs the cause.

`owner.synchronize(timeout=...)` refreshes the memory scope and explicitly
reconciles admitted sessions. A cold namespace requires actual bootstrap or
explicit full reindex. The original store `reindex` remains a full-source API.
Neither operation is inserted into ordinary fresh/restarted reader turns.

Close cancels an untriggered session timer and joins physical admitted work.
For active asynchronous hosts, use `await owner.aclose()`: it refuses new host
admissions and waits through active turns and acknowledgment metadata
settlement. An active turn cannot close its own owner. Closing does not publish
pending timer targets early; a later owner recovers durable changes through
the real startup scan.

See [the session publisher](session_publication.md) for source selection,
postcommit notifications, status and failure behavior. This host surface still
supports provider-none indexing only. Metadata/archive/tombstone changes need
explicit reconciliation or later startup; there is no cross-process event bus
or memory-file watcher here. Acceptance evidence belongs to the exact frozen
process family and its complete comparison report.
