# Durable Session Context

`MemorySessionCatalog` can persist a conversation and reconstruct its model context after
the Python process exits. It uses an SDK-owned SQLite schema; it does not read or modify
OpenClaw's binary database format. The host supplies its session identity and model client.

## Write and reopen a conversation

Register the session metadata before appending messages. A session key identifies the
conversation; a session ID identifies one incarnation of it.

```python
from memory_core.session_catalog import MemorySessionCatalog

key = "agent:main:dm:alice"
session_id = "conversation-1"
catalog = MemorySessionCatalog("state/sessions.sqlite", agent_id="main")
catalog.upsert_session(key, {
    "sessionId": session_id,
    "chatType": "direct",
    "compactionCount": 0,
})

saved = catalog.append_message(
    session_id,
    {
        "role": "user",
        "content": "I prefer kumquat tea.",
        "timestamp": 1_794_268_800_000,
        "idempotencyKey": "request-001",
    },
    session_key=key,
    event_id="user-001",
)
assert saved["appended"] is True
```

The first append creates the session header and message together. Message redaction,
parent selection, admission-key deduplication and insertion run in one write transaction.
The returned `message` contains the actual persisted, redacted message. `messageId` and
`effectiveParentId` identify its durable position. A returned `anchor` additionally certifies
its position on a clean active projection; the anchor contains the real database path and
persisted generation token.

In another Python process, open the same path and read the continuation:

```python
from memory_core.session_catalog import MemorySessionCatalog

catalog = MemorySessionCatalog("state/sessions.sqlite", agent_id="main")
continuation = catalog.read_continuation(
    "conversation-1", session_key="agent:main:dm:alice",
)
assert continuation is not None
messages = continuation["llmMessages"]
assert messages[0]["content"] == "I prefer kumquat tea."
```

This read acquires metadata, transcript events and version state in one SQLite snapshot.
No conversation list from the earlier process is required.

## Connect the model

`llmMessages` uses the agent message format: `user`, `assistant` and `toolResult` records,
including tool correlation IDs, usage and other ordinary JSON fields. The host's provider
adapter translates these records to its provider API. Passing this list directly to an
OpenAI-compatible endpoint is insufficient when it contains `toolResult` records or
provider-specific assistant fields.

The following synchronous integration accepts a host callback. `generate` must adapt the
input and return an ordinary assistant message in the same agent format:

```python
def complete_turn(catalog, key, session_id, request_id, text, generate):
    user = catalog.append_message(
        session_id,
        {"role": "user", "content": text, "idempotencyKey": request_id},
        session_key=key,
        event_id=f"user:{request_id}",
    )
    continuation = catalog.read_continuation(session_id, session_key=key)
    if continuation is None:
        raise RuntimeError("The registered transcript is missing")
    assistant_id = f"assistant:{user['messageId']}"
    for event in continuation["events"]:
        if event.get("id") == assistant_id:
            return event["message"]
    reply = generate(continuation["llmMessages"])
    saved = catalog.append_message(
        session_id, reply,
        session_key=key,
        event_id=assistant_id,
    )
    return saved["message"]
```

Run this function under a host-owned per-session queue or lock. Complete any tool loop by
persisting the assistant's tool calls, each matching `toolResult`, and the final assistant
message in order. Provider retries and crash recovery must consult the saved assistant
record before issuing another model call. The user admission key alone does not make an
entire provider turn exactly once.

The catalog does not run a model, index memory, schedule a flush or provide an automatic
turn-admission barrier. To use memory tools, supply this catalog to `Memory.from_workspace`
or `HostKit.open` and configure the session authority as described in
[Session Authority](session_authority.md). The host still dispatches the offered memory
tools and runs any requested flush. After the host receives updated session or flush state,
it persists the complete replacement metadata with `upsert_session`. `HostKit.after_turn`
does not automatically append messages or update the catalog.

## Inspect the persisted state

`read_continuation` returns:

| Field | Meaning |
| --- | --- |
| `entry` | Current metadata for the conversation key, or `None` if it was removed. |
| `instanceEntry` | Raw recorded metadata for the requested session ID. |
| `events` | Complete persisted transcript records, including header and control records. |
| `visibleEvents` | Events on the active transcript branch. |
| `context` | Selected messages plus the branch's latest `thinkingLevel` and `model`. |
| `llmMessages` | The actual model-facing conversion of the selected messages. |
| `historyPrelude`, `modelHistoryPrelude` | Reset-retained history markers for each corresponding message list. |
| `version` | Last raw sequence number, persisted generation and transcript mutation timestamp. |

Reset-retained markers are runtime metadata, outside JSON dictionary keys. Serializing
`context` to JSON does not preserve those markers. Rebuild context from the durable
transcript after reopening; do not treat serialized message lists as the source authority.

`read_anchor(session_id, entry_id, session_key=key)` reads the current certified identity.
A replacement rotates the generation; a normal append preserves it. An anchor can be
absent when the message is missing, is outside the active projection or that projection
needs rebuilding. Absence alone is not a visibility decision.

## Replay, rollover and empty transcripts

Reusing an admission key or event ID with the same redacted message returns the original
persisted message with `appended=False`. The root message timestamp is ignored for replay
comparison. Changed content or other changed fields raise
`TranscriptTurnAdmissionConflictError`; a conflict writes no partial header or message.
`expected_mutation_at` optionally rejects an append prepared against a stale transcript.

Use `upsert_session(key, {"sessionId": new_id, "previousSessionId": old_id, ...})` to register
a new incarnation. The earlier transcript remains addressable by its own session ID.
Consequently, `entry` can refer to the current incarnation while `events` and
`instanceEntry` refer to the requested retained incarnation. `list_transcript_instances`
provides the host history projection: complete current metadata for an exact current
instance, and window-owned classification fields for retained instances.

Unknown transcripts return `None`. A registered transcript with no events is different:
`read_transcript` returns a snapshot with an empty `events` tuple, and
`read_continuation` returns empty message lists with `thinkingLevel="off"` and `model=None`.
Its version fields are `None` until transcript state exists. The first `append_message`
then creates the header. Replacing an existing transcript with an empty event list removes
its events while retaining a new generation and mutation boundary.

## Supported boundary

The append owner supports ordinary JSON user, assistant and tool-result messages, their
full ordinary fields, role-aware storage redaction, durable parent links, replay/conflict
handling and generation/anchor identity. Context acquisition uses the persisted branch,
reset/compaction window, tool-result pairing and model-message conversion owners. Use
`append_events` and `replace_events` only as trusted raw transcript import operations;
they are separate from message admission and do not replace its redaction contract.

This API does not implement OpenClaw's provider-signed replay envelopes, media migration,
pending-input custody, writer-run fences, complete host turn barrier or maintenance worker
lifecycle. SQLite transactions protect each operation; the host owns ordering across a
whole model/tool/flush turn. Equivalence status belongs to the
[fixed checklist](full-equivalence-checklist.md), not to this usage example.

Incognito session keys route to a real process-held in-memory SQLite catalog. Their raw
state can be inspected by the trusted host in that process, disappears in a fresh process,
and is absent from the ordinary durable catalog and memory index. These raw methods do
not grant access to an actor: apply the session visibility policy before exposing history,
including for an incognito session's own requester.
