# Live SDK Integration

`memory_core.live` is adapter-only glue for low-latency host runtimes. It keeps
workflow state, streaming output, and durable subject memory separate, and it
reads the agent's workspace files through `memory_core.bootstrap` (see
[Workspace Layout](../workspace_layout.md)).

Use it when the host application already owns:

- audio, ASR, TTS, interruption, and transport
- workflow state and tool execution
- trace persistence and audit storage
- provider routing and retry policy

The SDK prepares OpenClaw-compatible prompt context, runs memory recall for a
single subject namespace, wraps a streaming LLM callable, emits sentence-ready
events for TTS, and writes post-session summaries to daily memory files.

## Workspace Files

`LiveIdentity` loads the agent workspace with the default `MEMORY_CORE_WORKSPACE_LAYOUT`, filters
it like a main session, applies the upstream budget and renders it in the
upstream prompt format:

```text
workspace/
  AGENTS.md
  SOUL.md
  TOOLS.md
  IDENTITY.md
  USER.md
  PROACTIVE_PREFERENCES.md   # memory-core extension, provisional
  HEARTBEAT.md
  BOOTSTRAP.md               # first run only
  MEMORY.md                  # not injected into subject prompts by default
  user/  workspace/          # created by initialize_agent_workspace, never injected
```

Seed the workspace with `initialize_agent_workspace(root, templates=...)`; pass
`seed_bootstrap=False` when the host has no first-run ritual.

`to_prompt_section()` returns, in upstream order: `## Bootstrap Pending` and
`## Bootstrap Context Notice` when they apply, `## Workspace Files (injected)`
with its intro line, `# Project Context` with one `## <path>` block per file in
render order (AGENTS, SOUL, IDENTITY, USER, PROACTIVE_PREFERENCES, TOOLS,
BOOTSTRAP, MEMORY), then `# Dynamic Project Context` with HEARTBEAT.md. There is
no cache boundary marker, and the Workspace Files lines are left out when no file
is injected. With `openclaw_compatible=True` the intro line names OpenClaw
instead of memory-core.

Defaults and behaviour a host will notice:

- `max_chars_per_file=20_000` and `total_max_chars=60_000` (UTF-16 units), with
  upstream's 75/25 head/tail markers and AGENTS.md policy digest. `None` or a
  value `<= 0` falls back to the default.
- A missing layout file renders `[MISSING] Expected at: <path>`, like upstream;
  empty files and a missing MEMORY.md are skipped. Use
  `layout=OPENCLAW_PIN_LAYOUT` for a workspace without PROACTIVE_PREFERENCES.md.
- The agent's root MEMORY.md is not injected unless `include_agent_memory=True`.
  This is a deliberate deviation: upstream injects it for every session that is
  not a subagent or cron session, but a live subject prompt should not carry the
  operator's long-term memory. Subject memory reaches the prompt through recall.
- While BOOTSTRAP.md is pending, the prompt carries `## Bootstrap Pending` and
  the file, as in an upstream full-mode run. A live workspace never produces
  setup evidence on its own (subject memory lives under `subjects/`), so the
  host removes BOOTSTRAP.md, seeds with `seed_bootstrap=False`, or passes
  `bootstrap_mode="none"`.
- `include_heartbeat=True` keeps HEARTBEAT.md, like upstream's default agent.

Loader options:

```python
identity = LiveIdentity.from_dir(
    "./workspace",
    required_files=["AGENTS.md", "SOUL.md"],
    max_chars_per_file=20_000,
    total_max_chars=60_000,
    unknown_files="error",
)
```

`unknown_files="error"` rejects root-level Markdown files outside the layout;
BOOT.md, DREAMS.md and dreams.md are accepted (upstream files that are never
injected), and folders such as `user/`, `workspace/`, `memory/`, `skills/` and
`subjects/` are ignored. `identity.sections` holds `(path, injected text)`
pairs and `identity.warnings` the budget warnings. `IDENTITY_FILE_ORDER` stays
exported for compatibility as `(name, name)` pairs in the default load order.

Use `LiveIdentityStore` when a host runtime wants stable cached workspace
instructions during a session and explicit reloads after file changes:

```python
identity_store = LiveIdentityStore("./workspace", required_files=["AGENTS.md"])
identity = identity_store.load()
identity = identity_store.reload()
```

The loader itself only reads files. Whether an agent can update workspace files
is controlled by the host runtime's normal file/tool policy, matching OpenClaw's
workspace-first model.

Durable memory is scoped by `subject_id`:

```text
memory-core-state/
  subjects/
    subj_123/
      MEMORY.md
      memory/
        2026-07-05.md
      .memory-core/
        main.sqlite
```

`subject_id` is intentionally generic. In a host application it can represent a
user, customer, account, device, patient, lead, or another durable memory
subject.

The default namespace is `subjects/<subject_id>`. Hosts can choose another
namespace or provide a path builder:

```python
memory = SubjectMemory.open(
    workspace_dir="./memory-core-state",
    subject_id="subj_123",
    namespace="accounts",
)

memory = SubjectMemory.open(
    workspace_dir="./memory-core-state",
    subject_id="subj_123",
    subject_path_builder=lambda root, subject_id: root / "tenants" / "default" / subject_id,
)
```

## Streaming Turn

```python
from memory_core import JsonlTraceSink, LiveIdentity, LiveSDKConfig, LiveTurnContext, SubjectMemory

identity = LiveIdentity.from_dir("./workspace")
memory = SubjectMemory.open(
    workspace_dir="./memory-core-state",
    subject_id="subj_123",
)
trace_sink = JsonlTraceSink("./memory-core-state/trace/session_456.jsonl")
live_config = LiveSDKConfig(
    openclaw_compatible=True,
    trace_sink=trace_sink,
)

context = LiveTurnContext(
    subject_id="subj_123",
    session_id="session_456",
    user_utterance="Adresimi değiştirmek istiyorum.",
    transcript_window=[
        "User: Merhaba.",
        "Assistant: Size nasil yardimci olabilirim?",
    ],
    workflow_state={
        "workflow_id": "address_change",
        "current_step": "verify_identity",
        "pending_steps": ["verify_identity", "collect_new_address", "confirm"],
    },
)

async for event in memory.stream_live_turn(
    context,
    identity=identity,
    llm=streaming_llm,
    config=live_config,
):
    if event.type == "text_delta":
        live_transcript.append(event.text)
    elif event.type == "sentence":
        tts_queue.put_nowait(event.text)
```

`llm` is a host-supplied callable. It receives the assembled chat messages and
returns an async iterable of text chunks, or dictionaries containing `text`,
`delta`, or `content`.

## Event Contract

The SDK exports event-name constants and a `LiveTurnEventType` literal alias.
Current event types:

- `live_turn_started`
- `memory_recall_completed`
- `prompt_assembled`
- `text_delta`
- `provider_event`
- `sentence`
- `live_turn_completed`
- `live_turn_failed`
- `session_summary_started`
- `session_summary_completed`
- `session_summary_skipped`
- `session_summary_failed`

`sentence` events are designed for TTS. `text_delta` events are useful for live
UI, logs, and transcript buffers.

`provider_event` passes through non-text provider chunks such as tool-call or
function-call deltas. The SDK does not execute tools or mutate workflow state;
the host runtime consumes these events and decides what to do.

If the host-supplied LLM stream raises, the SDK records `live_turn_failed` to
the trace sink with `error_type`, `error`, and partial `assistant_text`, then
re-raises the original exception so the host runtime can apply its retry or
fallback policy.

The host still owns workflow state transitions and tool calls. Put active
workflow state into `LiveTurnContext.workflow_state`; the SDK places it inside
runtime context rather than durable memory.

## Trace Sink

Pass `trace_sink=` when you want the SDK to persist the same events it yields.
`JsonlTraceSink` writes one JSON object per event:

```json
{"type":"sentence","text":"Tabii, yardimci olayim.","data":{}}
```

This is intentionally append-only and generic. Production hosts can implement
the `TraceSink` protocol to write events into their own audit log, database, or
message bus.

## Post-Session Summary

Do not write raw transcripts directly to durable memory. Run a summarizer or
extractor and append only durable facts, preferences, decisions, or follow-up
items:

```python
result = memory.record_session_summary(
    session_id="session_456",
    transcript=full_transcript,
    redactor=redact_sensitive_text,
    summary_llm=summary_llm,
    timezone="Europe/Istanbul",
    trace_sink=trace_sink,
)

if result.wrote:
    trace_store.write({"memory_path": result.path})
```

Async extractors can use the async variant:

```python
result = await memory.async_record_session_summary(
    session_id="session_456",
    transcript=full_transcript,
    summary_llm=async_summary_llm,
    trace_sink=trace_sink,
)
```

`summary_llm` receives the OpenClaw-style memory flush messages. If it returns
empty text or starts with `NO_REPLY`, nothing is written.

For safer extraction, `summary_llm` may return JSON:

```json
{
  "durable_facts": ["Subject moved to the premium plan."],
  "preferences": ["Subject prefers evening delivery."],
  "follow_ups": ["Send updated invoice."]
}
```

Only `durable_facts`, `preferences`, and `follow_ups` are appended to subject
memory.

## Demo Environment

The FastAPI demo app exposes a generic live task simulator for local latency and
integration checks:

```bash
uvicorn demo.app:app --reload
```

Endpoints:

- `POST /api/live-task/reset`
- `GET /api/live-task/state`
- `POST /api/live-task/turn-stream`
- `POST /api/live-task/summary`

Example streaming payload:

```json
{
  "sessionId": "session_demo",
  "subjectId": "subject_demo",
  "message": "Doğum tarihim 12.04.1990"
}
```

`/api/live-task/turn-stream` returns SSE events named after the live SDK event
types. Each live event payload includes `elapsed_ms`, so the same client path can
later compare fake-provider latency with real inference latency. The final
`live_task_state` event returns serialized workflow state and transcript.

The demo task is appointment rescheduling. It verifies identity, collects a new
time, asks for confirmation, emits sentence events for TTS-style chunking, and
writes post-session summaries through `SubjectMemory.record_session_summary`.
Without a provider key the replies are scripted.

The live task uses its own workspace (`memory-core-live-task-demo-workspace` in the
system temp dir), separate from the chat workspace. It is seeded with the Lab
templates, and the demo appends its `## Live Task Demo: appointment_reschedule`
section to AGENTS.md once: only while no line of the file equals that heading.
Its BOOTSTRAP.md stays pending, so live prompts carry `## Bootstrap Pending`.

## OpenClaw Compatibility

`openclaw_compatible=True` uses OpenClaw runtime-context markers when assembling
live prompt context. This helps host runtimes keep internal workflow and trace
context separate from visible transcript text.

This adapter is not full OpenClaw runtime parity. It does not own scheduler,
channel gateway, workflow execution, tool policy, sandboxing, or provider
fallback. Those remain host responsibilities.
