# Tool Outcomes and Turn Trust

`TurnTrust` connects actual tool execution to memory-write provenance and stored
assistant messages. Create one instance for an incoming user turn and reuse it
for that turn's retries. A registered network source taints the turn when its
execution returns or fails. Later local tools do not clear that state.

The host controls the turn identity, sender ownership and tool registrations.
Model arguments, tool-result JSON and assistant text cannot supply those facts.

```text
registered callable executes
    → TurnToolDispatcher observes the actual result or execution error
    → the owning TurnTrust becomes sticky-tainted for network content
    → each memory write reads that live state through its provenance observer
    → later assistant messages are stamped before their genuine catalog append
    → a fresh process reads the stored messages and artifact records
```

## Register the actual callables

The following fragments belong to an application's turn handler. `fetch_external`
is the application's real network client; the SDK does not call a model or fetch
a page by itself.

```python
from pathlib import Path
import time

from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.model_tool_result import sanitize_tool_result
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.turn_tool_dispatch import TurnTool, TurnToolDispatcher
from memory_core.turn_trust import TurnTrust, build_tool_result_message

root = Path("chat-data").resolve()
workspace = root / "workspace"
workspace.mkdir(parents=True, exist_ok=True)
ledger = MemoryArtifactProvenanceStore(root / "artifact-provenance.sqlite")
catalog_path = root / "state/agents/main/sessions/authority.sqlite"
catalog = MemorySessionCatalog(catalog_path, agent_id="main")

session_key = "agent:main:dm:alice"
session_id = "conversation-1"       # The host's registered transcript identity.
turn_id = "incoming-message-42"    # The host's identity for this user turn.
now_ms = lambda: time.time_ns() // 1_000_000
catalog.upsert_session(session_key, {
    "sessionId": session_id, "updatedAt": now_ms(), "chatType": "direct",
})
trust = TurnTrust(turn_id, sender_is_owner=True)

# Constructing this before a network call is intentional. It reads current
# trust at EVERY write, rather than capturing a trusted/untrusted boolean now.
observer = trust.write_observer(
    store=ledger,
    mutation_root=workspace,
    workspace_dir=workspace,
    session_id=session_id,
    session_key=session_key,
    now=now_ms,
)
```

Register the implementation that really performs each operation. This example
allows a memory tool to write one host-selected file; the model chooses its
content, not the workspace root or provenance identity.

```python
def make_dispatcher(fetch_external):
    def lookup(_call_id, arguments):
        text = fetch_external(arguments["query"])
        return {"content": [{"type": "text", "text": text}]}

    def write_note(_call_id, arguments):
        target = workspace / "memory/current-turn.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        before = target.read_text(encoding="utf-8") if target.exists() else ""
        after = arguments["content"]
        observer.write(
            absolute_path=target,
            content_before=before,
            content_after=after,
            commit=lambda: target.write_text(after, encoding="utf-8"),
        )
        return {"content": [{"type": "text", "text": "Memory note written."}]}

    return TurnToolDispatcher(
        trust,
        [TurnTool("lookup", lookup, result_content_source="network"),
         TurnTool("write_note", write_note)],
        model_result_preparer=sanitize_tool_result,
    )
```

Call `dispatcher.dispatch(name, arguments, tool_call_id=...)` with an actual
model tool call, using `dispatcher = make_dispatcher(your_fetch_callable)` in
the turn handler. For an asynchronous network client, make `lookup` async and
await its client call. `dispatch_async` awaits asynchronous callables before observing
their settled outcome. A retry can construct a new dispatcher while retaining
the same `trust` and observer. Raw outcomes reach `on_outcome`, if configured,
before `model_result_preparer` prepares the model-facing result.

When the memory runtime indexes or promotes these files, give it the same
ledger, for example through `Memory.from_workspace(...,
artifact_provenance=ledger)`. Separate ledgers would separate the writer's trust
record from the reader that must consult it.

## Persist the messages that actually occurred

Stamp every actual assistant message at its emission boundary, including
assistant tool-call messages. Then append it through the catalog. Earlier
messages are not retroactively stamped when a later tool taints the turn.

```python
def persist(message, event_id):
    return catalog.append_message(
        session_id, message,
        session_key=session_key,
        event_id=event_id,
        now_ms=now_ms(),
        cwd=str(workspace),
    )

# Incoming user message: sender ownership comes from the host's authenticated
# channel/request context, not from model-authored JSON.
persist({"role": "user", "content": "Look up and save the preference.",
         "timestamp": now_ms(), "__openclaw": {"senderIsOwner": True}},
        "turn-42:user")

# actual_assistant_message and actual_tool_call come from the model response.
persist(trust.stamp_assistant(actual_assistant_message), "turn-42:assistant-1")
result = dispatcher.dispatch(
    actual_tool_call["name"], actual_tool_call["arguments"],
    tool_call_id=actual_tool_call["id"],
)
persist(build_tool_result_message(
    actual_tool_call, result, is_error=False, timestamp_ms=now_ms(),
    result_content_source="network",  # Read this from the trusted registration.
), "turn-42:tool-result-1")

# For a following actual model request to call write_note, stamp its assistant
# message first. The existing observer now reads the network-tainted state.
persist(trust.stamp_assistant(actual_write_assistant_message),
        "turn-42:assistant-2")
written = dispatcher.dispatch(
    "write_note", actual_write_tool_call["arguments"],
    tool_call_id=actual_write_tool_call["id"],
)
persist(build_tool_result_message(
    actual_write_tool_call, written, is_error=False, timestamp_ms=now_ms(),
), "turn-42:tool-result-2")

# After a network result, this receives __openclaw.turnTainted = true.
persist(trust.stamp_assistant(actual_final_assistant_message),
        "turn-42:assistant-3")
```

Use the registration's source for each result; a local write tool has no network
source. A source execution exception still updates network taint before it is
re-raised. `build_tool_execution_error_result(error)` provides the ordinary
execution-error payload when the host needs to persist or present that result.
Apply `sanitize_tool_result` to that payload before model presentation; the
catalog's append owner applies its separate storage policy.
The host remains responsible for preserving actual tool-call/result ordering
and choosing unique message event IDs.

A presentation-only notification uses the separate trusted host
`TurnTrust.observe` path. Registered tools represent actual executions and have
no presentation-only override; their network outcomes update live taint even if
model arguments or result JSON contain a `presentationOnly` field.

## Reopen storage and distinguish retries from new turns

A new process needs only the owned catalog path and registered source identity
to read the committed conversation. It does not need a forwarded list of prior
messages or tool responses.

```python
reopened = MemorySessionCatalog(catalog_path, agent_id="main")
saved = reopened.read_continuation(session_id, session_key=session_key)
assert saved is not None
messages_for_model = saved["llmMessages"]
stored_events = saved["events"]

reopened_ledger = MemoryArtifactProvenanceStore(root / "artifact-provenance.sqlite")
artifact = reopened_ledger.read(
    workspace_dir=workspace, relative_path="memory/current-turn.md",
)
```

For a retry of the **same** turn, a trusted host checkpoint may carry
`trust.to_json()`. Restore it with
`TurnTrust.from_json(checkpoint, expected_turn_id=turn_id)`; a different turn ID
is rejected. Alternatively, a host recovering the current active turn can read
its committed context and use `is_active_turn_tainted(saved["context"]["messages"])`
as the new owner's `initially_tainted` value.

For a **new user turn**, create a new `TurnTrust(new_turn_id, ...)` with fresh
state. Do not restore the previous turn's checkpoint into it. The new turn can
be clean while a file previously recorded as `untrusted` remains quarantined:
that quarantine belongs to the artifact ledger and survives later writes and
process restarts.

## Host responsibilities and current boundary

These APIs provide callable execution, current-turn trust, provenance-aware
writes and message/storage owners. They do not automatically replace
`HostKit.dispatcher`, call a model, run a provider retry policy, serialize
concurrent writers or implement the complete host turn barrier. The application
must wire the same turn owner through its actual tool, write and transcript
boundaries. See [the host kit](host_kit.md) for its separate memory/flush entry
points.
