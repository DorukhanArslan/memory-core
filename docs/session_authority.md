# Session Authority and Transcript Recall

Use a persisted session catalog when an application needs memory from conversation
transcripts. The catalog supplies session identity, ownership, participants, retained
generations, archive bindings and reset metadata. The visibility context supplies the
requester's policy. Both are trusted host inputs, separate from model tool arguments.

`MemorySessionCatalog` uses an SDK-owned SQLite schema. It is not a binary reader or
replacement for OpenClaw's private session database. A host imports its own authoritative
metadata and events through the public methods. The legacy JSONL corpus adapter remains
available for existing file-based hosts.

## Connect the SDK and HostKit

```python
from pathlib import Path

from memory_core import HostKit, Memory, MemoryConfig, SessionState
from memory_core.flags import FeatureFlags
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_visibility import SessionVisibilityContext, SessionVisibilityPolicy

root = Path("workspace")
catalog = MemorySessionCatalog("state/sessions.sqlite", agent_id="main")
key = "agent:main:dm:alice"
catalog.upsert_session(key, {
    "sessionId": "alice-current",
    "chatType": "direct",
})
catalog.record_participant(key, {
    "identity": {"type": "profile", "id": "alice"},
    "promptedAt": catalog.now_ms(),
})
catalog.append_events("alice-current", [{
    "type": "message",
    "id": "message-one",
    "message": {
        "role": "user",
        "content": "I prefer cedar tea.",
        "__openclaw": {"senderIsOwner": True},
    },
}])
authority = SessionVisibilityContext.from_catalog(
    catalog, SessionVisibilityPolicy(visibility="self"),
)
memory = Memory.from_workspace(
    root,
    config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False)),
    session_catalog=catalog,
    session_visibility=authority,
)
kit = HostKit(memory)
state = SessionState.new(session_key=key, session_id="alice-current")
result = kit.dispatch(
    "memory_search", {"query": "cedar", "corpus": "sessions", "minScore": 0},
    session=state,
)
```

`HostKit.open(..., session_catalog=catalog, session_visibility=authority)` performs the
same binding. Direct callers use
`memory.search("cedar", corpus="sessions", agent_session_key=key)`.
The host supplies the actual requester through `SessionState` or that explicit keyword;
a model cannot change it by adding permission fields to its arguments.

The policy supports `self`, `tree`, `agent` and `all`, sandbox restrictions and agent-to-agent
rules. An omitted visibility value follows the pinned native default, `all`; select `self`
when only the requester's own conversation should be visible. A missing requester removes
session hits. Participant metadata remains authoritative source information; it does not
itself grant access. An agent-bound catalog cannot be attached to another agent's `Memory`.

## Persist and refresh before the next recall

Append committed transcript events to the catalog, then explicitly refresh the index:

```python
catalog.append_events("alice-current", completed_turn_events)
memory.store.reindex(memory.workspace)
```

The host owns the order of transcript persistence, refresh and admission of the next turn.
`HostKit.after_turn()` does not automatically append events to this catalog or refresh it.
Automatic query synchronization and a durable next-turn barrier retain their separate
checklist contracts. Catalog changes are read afresh for authorization, while indexed text
changes require the explicit refresh.

The catalog's recorded session ID controls source identity. Filesystem locator names cannot
stand in for that identity. Admission keeps active, retained and archived generations
separate; maintenance classifications and memory tombstones determine which sources enter
the index. Tombstones suppress memory admission without erasing otherwise authorized source
history. JSONL archive reads support genuine Zstandard `.zst` data through the Python codec;
no Node process or Gateway is required by the SDK.

Incognito keys use process-held SQLite state. Their raw host writes remain available in
that process while ordinary catalog, durable database and transcript index exclude them.
The history access guard denies incognito targets, including private-self requests.

## Separate indexed sources from ordinary search sources

```python
from memory_core.session_visibility import resolve_memory_search_source_policy

policy = resolve_memory_search_source_policy(remember_across_conversations=True)
# policy["sources"] == ["memory", "sessions"]
# policy["searchSources"] == ["memory"]
```

Pass `source_policy=policy` to `Memory.from_workspace()` or `HostKit.open()`. This keeps
transcripts available to trusted private conversation recall while ordinary model searches
use the selected search sources. `Memory.search(context=...)` accepts trusted execution
context, including `conversation_recall`; it is absent from the model's schema. Private
recall checks the anchor, requester, every transcript alias, reset cutoff and archive reason.
Ordinary visibility and private recall intentionally have different alias rules.

## Read an authorized current transcript

```python
from memory_core.session_visibility import read_visible_session_source

source = read_visible_session_source(
    catalog, authority,
    requester_session_key=key,
    target_session_key=key,
    agent_id="main",
)
```

This authorizes a target session key, resolves its current recorded session ID and reads
actual persisted events. The result retains the complete access decision and event records.
An incarnation-specific grant is revalidated around the read. This API does not interpret a
cached search hit as permission to expand an arbitrary old transcript. `memory_get` retains
its memory-file read contract.

## Verification boundary

The active reference is OpenClaw `v2026.9.9`, commit
`bcfc88812a35243893585dbeca87ca41b48272ca`. The differential profile uses genuine native
session SQLite accessors, corpus discovery, index managers, visibility owners and current-key
source access. SDK storage uses its own schema. Source hashes and official release evidence
remain separate; the release source build is not independently reproduced.

Complete archive frames are part of the integrated profile. Native codec edge behavior,
cache materialization, full archive publication, transcript filtering boundaries, session
reset hooks and general host orchestration retain their own acceptance requirements.
See the [full checklist](full-equivalence-checklist.md) for actual verified counts and limits.
