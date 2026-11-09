# Tool result settlement

`memory_core.tool_result_persistence.settle_session_tool_result` composes the
ordinary tool-result stages owned by OpenClaw's AgentSession and guarded writer:

1. Prepare model-visible text before live message listeners.
2. Deliver the real event and prepare again after listeners return.
3. Normalize the persisted tool name and error flag, then cap content and details.
4. Apply the role-aware before-write redaction policy and cap again.
5. Append through `MemorySessionCatalog.append_message` and its storage policy.
6. Prepare the original live event again after settlement.

The live message and committed message are distinct outputs. Diagnostic `details`
can remain unchanged in live context while the stored copy has been redacted and
bounded. Prepared text provenance avoids repeating non-idempotent text rules
when the same genuine block and policy are still admitted. Inline image records
and recognized image data URLs use the existing base64 and byte-signature owner
before generic credential redaction.

The details cap preserves the original 8,192-byte limit and its early-exit byte
lower bounds, sensitive parent keys, depth limit, bounded session summaries and
UTF-16 boundary-overlap notices. It does not implement media migration, provider
replay custody or the complete AgentSession execution loop.

## Host integration example

[`examples/session_tool_result.py`](../examples/session_tool_result.py) provides
`HostToolSession` around actual SDK owners. The application supplies its provider
loop, real messages and trusted tool registrations. Begin one host-owned turn,
append the actual user and assistant messages, and dispatch each selected call:

```python
from pathlib import Path
from examples.session_tool_result import HostToolSession
from memory_core.turn_tool_dispatch import TurnTool

session = HostToolSession(
    Path(".memory-session"), session_id="conversation-1",
    session_key="agent:main:dm:conversation-1", now_ms=1000,
)
session.begin_turn("turn-1", sender_is_owner=True)
session.append_message(
    {"role": "user", "content": "Look up the release.", "timestamp": 1000},
    now_ms=1000,
)
# Supply the actual callable and source classification from the host registry.
result = session.dispatch(
    TurnTool("lookup", lookup_release, result_content_source="network"),
    {"id": "call-1", "name": "lookup", "arguments": {"query": "release"}},
    now_ms=1000,
)
provider_messages = session.model_messages()
committed_context = session.continuation()
```

The same `TurnTrust` instance remains active across local tools and retries in
that turn. Reopening the example reads committed continuation without replacing
existing metadata. The lower-level `dispatch_and_persist` also accepts an existing
host-owned trust instance. Source classification and sender ownership come from
the host; model-authored arguments do not establish them.

## Diagnostic boundaries

`equivalence.trust_model_session_probe` invokes the real original AgentSession,
registered tool and guarded SQLite writer, then continues and reads again in
separate OS processes. Its SDK lane invokes the example, dispatcher, settlement,
catalog and continuation reader. Literal assistant streams replace provider
input only; all complete result, live-context and stored-message outputs remain
available in the retained reports. These diagnostics award no acceptance points.

`equivalence.trust_redaction_source_probe` is a separate explicit all-source
profile: the unchanged private full-context mark, actual redactor, whole JSON
walkers and transcript owner share the same authenticated TypeScript graph.
It cannot fall back to compiled modules or mix their private markers. Registered
secrets are synthetic fixtures, with provider credentials absent from child
environments. Source, dependency and SDK identities are verified before and after
execution.

Valid JavaScript regex behavior unsupported by the SDK remains an ordinary visible
difference. Native raw-input WeakMap identity reuse also remains different from
the SDK's uncached raw dictionaries; prepared output reuse is supported. Neither
diagnostic establishes complete redaction parity while those differences remain.
