# Host Session Lifecycle

`HostSessionRunner` connects the existing `HostKit` and durable session catalog to a host's
model callback. It serializes each session from admission through transcript persistence,
memory maintenance and index publication. An immediately queued next turn reads the saved
conversation and waits for outstanding SDK writes before its model callback starts.

This is an SDK host policy, with stronger publication ordering than the pinned native
background search refresh. It does **not** establish full OpenClaw host lifecycle parity or
close the original `host.turn-barrier` equivalence condition. Status remains in the
[fixed checklist](full-equivalence-checklist.md).

## Run the offline example

```bash
python examples/host_session_lifecycle.py
```

The example uses a clearly labelled scripted model callback, real SDK file writes, SQLite
transcript records and a real FTS query. It makes no model or network requests and supplies
no prepopulated memory or fabricated search results. `--workspace /path/to/demo` keeps its
files for inspection; without that option it uses an owned temporary workspace.

Its setup is the same shape as an application integration:

```python
from pathlib import Path

from memory_core import (
    HostSessionRunner, SessionState,
)
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.session_catalog import MemorySessionCatalog

workspace = Path("demo-workspace").resolve()
config = MemoryConfig(workspace, flags=FeatureFlags(vector_search=False))
catalog = MemorySessionCatalog(
    config.resolved_store_path().with_name("sessions.sqlite"), agent_id=config.agent_id,
)
runner = HostSessionRunner.open(
    workspace,
    config=config,
    catalog=catalog,
    session=SessionState.new(
        session_key="agent:main:dm:alice", session_id="alice-conversation",
    ),
)
```

`open` creates the provenance ledger **before** constructing the immutable `HostKit`. Its
default is a separate sibling of the selected index database:
`<index-stem>.provenance.sqlite`. The catalog keeps its existing independent SDK schema.
These files do not interchange with OpenClaw's binary databases. An application can supply
its existing `MemoryArtifactProvenanceStore` instead. Direct construction with an existing
kit requires that kit to have a ledger and the same catalog already bound to its workspace.

## Connect a real model

The application supplies `async execute(turn)` and, for due memory maintenance,
`async execute_flush(turn)`. It keeps its provider client and provider-specific message
translation. The runner introduces no provider SDK and makes no provider requests itself.

For a normal turn, `turn.context` contains the actual `HostKit.before_turn` result, including
the system prompt and SDK tool definitions. `turn.messages` is rebuilt from persisted
continuation and includes the newly admitted user message. It uses ordinary agent messages
(`user`, `assistant`, `toolResult`), which the provider adapter translates to its API.

For each actual assistant response:

```python
from memory_core import HostModelResult, TurnUsage

async def execute(turn):
    while True:
        # The host adapts system_prompt/messages/tools to its provider client.
        response = await your_model_client.complete(
            system_prompt=turn.context.system_prompt if turn.context else None,
            messages=turn.messages,
            tools=turn.tools,
        )
        turn.record_message(response.agent_message)
        if response.tool_calls:
            for call in response.tool_calls:
                await turn.dispatch_async(call.id, call.name, call.arguments)
            continue  # send the real tool results back to the model
        return HostModelResult(
            usage=TurnUsage(response.last_input_tokens, response.last_output_tokens),
            payloads=tuple(response.visible_payloads),
        )
```

`record_message` persists complete ordinary JSON assistant fields and applies the owning
turn's real trust state. `dispatch_async` validates correlation with a recorded assistant
tool call, invokes the actual SDK dispatcher in a worker thread, and persists the actual
tool-result message. Its original complete receipt is retained in the outcome. The SDK's
curation mapping receipts are rendered as JSON text plus complete details for the model.
Provider messages cannot supply trusted `__openclaw` flags.

Use the same callback and `HostTurn` throughout a model retry. One verified `TurnTrust`
owner observes trusted tool registrations across the whole turn; it is not reset between
attempts. Additional `TurnTool` registrations in this initial profile are synchronous;
the host supplies their provider schemas. Their registered content source, rather than
model arguments or returned JSON, controls network taint. A new admitted turn gets a new
trust owner. Existing file quarantine stays sticky.

Call the runner, rather than manually sequencing `after_turn` and a later save:

```python
outcome = await runner.run_turn(
    "Remember that I prefer kumquat tea.",
    execute=execute,
    execute_flush=execute_flush,
)
```

A flush callback receives the actual `FlushRequest` through `turn.flush_request`, with its
private `messages` and restricted `tools`. Its `context` is `None`. It uses the same
`record_message` and dispatch methods; those maintenance messages stay outside the visible
conversation transcript. The runner calls `FlushRequest.complete` itself after the actual
dispatches settle. If a flush is due and no executor was supplied, the outcome explicitly
reports that missing executor and records no false successful flush.

## Completion and failures

`HostTurnOutcome` retains the actual session, transcript append receipts, complete tool
receipts, model payloads, flush outcome and structured failures. `ready` means publication
finished and the turn has no recorded failure or cancellation.

| Field | Meaning |
| --- | --- |
| `transcript_committed` | This request has a durable user admission; partial model/tool records can also exist after failure. |
| `memory_writes_committed` | At least one SDK memory publication is known to have committed, including a flush body. This does not promise those bytes survived a later external edit. |
| `memory_publication` | `none`, `committed`, or `uncertain`; a publisher uncertainty or unresolved owned write intent takes precedence even when another write is known to have committed. |
| `index_status` | `ready`, `failed`, or `not-run`; it is separate from file commitment. |
| `failures` | Phase, error type, message, known commitment and optional publication/intent uncertainty for each visible failure. |
| `appends`, `tools` | Actual durable append results and complete execution receipts. |
| `flush` | The actual completion state, including write/failure/cancellation facts. |

`memory_publication="none"` means these selected owners supplied no publication fact or
unresolved write intent;
it is not a guarantee that every failed external tool or low-level append left no partial
IO. An ordinary append IO error retains its original error contract, with no invented lower
`publication` field. If that owned producer started, the SDK separately keeps its durable
intent unresolved instead of inferring that the append wrote nothing.

A committed file with `afterWriteError` remains committed. The outcome reports the index
failure, persists `needsIndex`, and does not repeat the write. The next admission attempts
one actual index repair **before** accepting another user input or calling its model. If
repair still fails, it returns an explicit failure without running that model. A successful
flush body keeps its successful flush stamp even when indexing fails; repair refreshes
the index without duplicating the note. Failed actual tool receipts remain visible even
when the model returns an ordinary reply. A failed maintenance write cannot stamp success.
If the host executor rejects a dispatch before its source starts, its receipt records
`sourceExecuted: false` and the actual `schedulingError`. The turn reports `tool-scheduling`,
releases that unused reservation, and does not claim a file write or successful tool result.
If cancellation or session rotation withdraws maintenance authority after a flush body has
already committed, the outcome preserves that commitment and closes the flush as cancelled
without stamping success or restoring the older current session.

A checked publisher can report `publication="committed"` after its rename succeeded but
later verification failed. The outcome preserves that historical fact, reports the failure
and indexes the actual current file; the file may already contain an external replacement.
`publication="uncertain"` means the dispatched mutation cannot be resolved from its receipt.
It does not mean no write occurred. The runner preserves that state in the catalog before
indexing and refuses further dispatches and subsequent admissions, including after reopening.
Successful indexing alone cannot clear it, and optional memory maintenance does not run.
The original trust quarantine remains attached to either dispatched publication state.

Before the first trusted builtin memory producer enters a turn, the runner durably saves
an owner-bound `stage="intent"` marker. The real write observer gates file/provenance
producers; a due flush's existing authority check also gates target preparation. If the
intent save fails, that producer does not run. Argument validation, skipped/unchanged
operations and ordinary chat/read-only turns do not leave unresolved intents. The same
intent stays through all accepted writes and private flush work, and known final settlement
clears it. An actual uncertain replacement records `stage="uncertain"`; an ambiguous append
error keeps `stage="intent"`. If final catalog settlement fails or the process stops, the
prior intent survives for a fresh runner to refuse admission until acknowledgment. This
does not resume or repeat the interrupted model/provider operation.

After the host has inspected and accepted the **current** files, acknowledge the exact pending
turn explicitly:

```python
await runner.acknowledge_memory_publication(expected_turn_id=outcome.turn_id)
```

The acknowledgment holds the same session lane, checks the current session identity,
pending turn and bound workspace/index/provenance stores, performs a real index refresh,
and records its turn id, owner paths and time before clearing
only that matching marker. It makes no provider call and does not replay the write or assert
that the original requested bytes survived. An index failure, changed owner, stale turn id,
or cancellation before acknowledgment commits leaves the uncertainty pending. Index source
custody remains held until the actual producer finishes, even after caller cancellation.

Public `HostTurnFailure.message` values pass through the shared error formatter and its
configured redaction policy. Complete tool receipts, raw model/tool messages and append
results are private application diagnostics; do not expose those unfiltered in a UI or log.

Finalization merges owned usage/flush fields into the latest current catalog metadata, preserving
unrelated caller fields. A small `sdkHostLifecycle` metadata envelope holds auxiliary kit
state and the owner-bound intent/publication marker; it never recursively serializes the entry into itself.
An observed session-incarnation change refuses stale model records and dispatches instead
of restoring the older current session.

Cancellation signals the callback through `turn.cancelled` and `turn.cancel_requested`.
Provider timeouts and cooperative cancellation belong to that host callback; the SDK does
not forcibly terminate arbitrary vendor I/O. The lane stays held until the callback and
its accepted producers actually settle.
The caller receives `CancelledError` only after the producer and every accepted synchronous
dispatch have actually settled. Cancelling an awaited dispatch future cannot release the
session lane while its real file/index producer continues. A dispatch queued too late sees
a closed generation and cannot write. `runner.last_outcome` is the latest completed turn's
receipt, including effects that committed before cancellation.

If the producer task itself is terminated during finalization, a separate settlement owner
joins accepted dispatches and the actual executor source performing publication. It records
a cancelled outcome with a conservative `needsIndex` marker instead of spinning on the
cancelled task or releasing the next turn early. The next admission repairs publication;
it does not repeat already committed file writes.

## Supported boundary

The runner coordinates cooperating SDK calls in one process. Different runner instances
for the same canonical catalog/agent/session key share a lane. Concurrent use from another
event loop fails closed; a model callback cannot recursively enter its own session lane.
Separate sessions can run independently. External filesystem writes and competing processes
are outside this lane; catalog transactions and existing source-revision checks still apply.
Durable mutation intents cover the exact builtin curation and private flush producers;
additional host tool implementations retain their own mutation/admission policy.
Live identity and pending-turn checks fence cooperating runners; they are not an atomic
compare-and-set against unrelated direct catalog writes. Hosts must serialize those raw
metadata edits themselves while a turn or acknowledgment owns the session.

Incognito lifecycle writes are explicitly unsupported. The runner refuses them before
workspace initialization instead of turning private conversation content into durable
memory. The existing volatile catalog APIs retain their original behavior.

A request id supplies the default user-admission key; an existing message admission key is
preserved. It can prevent a second model invocation for an already admitted user message;
replay returns an explicit failure rather than silently repeating provider or tool effects.
This is not crash-resumable provider execution or an exactly-once turn transaction. The model
still chooses what facts to save. Provider-signed replay, media migration and complete
native host orchestration are outside this ordinary JSON callback profile.

## Reused trust production owners

The production helpers come from the independently reviewed SDK commit
`6ed8c0eb1ff12ecda498abaa409a022fede00e9d`, with no adapter algorithms moved into the runner.
The original source hashes are:

| File | SHA-256 at the copied commit |
| --- | --- |
| `memory_core/turn_trust.py` | `294c6e18d8cedc82754ea06c517290ecb6b1e190aea40ede6ff76651fa90d77c` |
| `memory_core/turn_tool_dispatch.py` | `73b67aef1dd60a06cf4131881a30d5fd5564dbc9160fc07a521c621c35b3116a` |

Both files remain byte-for-byte unchanged from that verified commit.

They provide `TurnTrust`, registered `TurnTool` execution, assistant trust stamping and
ordinary result-message construction. The runner owns admission, persistence and settlement;
the existing curator, provenance observer, flush and SQLite index owners perform the writes.
