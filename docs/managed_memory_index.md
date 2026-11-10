# Managed provider-none index

`ManagedSQLiteMemoryStore` is an explicit FTS-only owner for hosts that need
search-time cold-index bootstrap. It uses the normal SQLite search and atomic
index publisher. The existing eager `HostKit.open()` API keeps its behavior.

```python
from dataclasses import replace
from pathlib import Path

from memory_core import FeatureFlags, HostKit, Memory, MemoryConfig, SessionState
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.session_visibility import resolve_memory_search_source_policy

workspace = Path("agent-workspace").resolve()
config = MemoryConfig(
    workspace_dir=workspace,
    session_search=False,
    flags=FeatureFlags(vector_search=False),
)
policy = resolve_memory_search_source_policy(["memory"])
memory = Memory.from_workspace(
    workspace, config=config, source_policy=policy,
    initialize=False, reindex=False,
)
# A genuine saved source exists, but no index has been published yet.
memory.workspace.append_daily_memory(
    "memory/2026-11-09.md", "My drink preference is cedar tea."
)
store = ManagedSQLiteMemoryStore(config, memory.workspace)
kit = HostKit(replace(memory, store=store))
session = SessionState.new(session_key="agent:main:main", session_id="one")
try:
    result = kit.dispatch(
        "memory_search", {"query": "drink preference", "minScore": 0},
        session=session,
    )
finally:
    store.close()
```

The first search reads real index identity, chunks and FTS state. A missing
eligible cold index requests a real rebuild, increments the live repair notice
and publishes through `SQLiteMemoryStore.reindex`. The ordinary search tool
observes that transition and includes its warning. A later warm query does
not replay the old notice. A valid empty index can scan current sources without
inventing another full-rebuild notice. A newer incompatible identity is left
unchanged. Failed real repair is retained until an explicit refresh succeeds.

A failed memory-scope `reindex_sources` publication is retained separately. The
index is then behind its committed source, so `status()` reports the real error
as `lastSyncError` (a failed whole reindex takes precedence) and the search tool
marks results `stale` with that error and its rebuild guidance. The report ends
when the failed selection publishes: a memory publication with `paths=None`,
path-limited memory publications that together cover the failed paths, or a
whole `reindex`. Requests refused before any publication (argument errors, an
index that needs a full reindex) are not retained, and sessions-only
publications neither set nor settle it. Unlike a failed whole reindex, it does
not pause automatic preparation. `lifecycle_snapshot()` keeps `lastSyncError`
for whole reindexes and adds `memoryScopeSyncFailure` (`error`, `paths`) only
while such a failure is retained. This report is Python behavior covered by
unit tests; no differential comparison with OpenClaw reaches it.

`status()` reads actual published SQL state. `lifecycle_snapshot()` returns
bounded operation/repair journals, totals, truncation indicators and close
state. The typed `search` signature and original SQLite results/errors are
preserved. Workspace, index, agent and catalog ownership are checked.

`close()` rejects new managed search/status/reindex admissions and joins work
already admitted by this instance. A caller stopping its wait does not terminate
an ongoing physical publication; close still waits for it. It does not fence
unrelated processes or inherited raw SQL helpers. The store holds no idle DB
connection. The owner supplies cold bootstrap. Hosts can explicitly bind the
[session publication controller](session_publication.md) for committed session
queues and publication after read-generation admission. Construction alone
starts no session work. Background memory-file watching and provider fallback
remain outside this owner.

For `HostSessionRunner`, bind the same session catalog and artifact-provenance
store to the memory, managed store and kit, then use the existing runner
constructor. Its normal awaited end-of-turn publication remains in effect;
selecting this store does not change that guarantee. Supply a fully resolved
source policy, as above; indexed sources and ordinary query sources are distinct.

The owner defaults to the SDK runtime identity. Interoperability callers can
explicitly pass `OPENCLAW_COMPAT_RUNTIME_IDENTITY` as the store's
`runtime_identity` and the kit's `identity` so guidance names the intended host.
The [restart publication/managed closeout](host_restart_managed_closeout.md)
records the bounded comparisons and remaining session-publication difference.
