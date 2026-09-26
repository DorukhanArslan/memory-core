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
  PROACTIVE_PREFERENCES.md   # memory-core extension
  HEARTBEAT.md
  BOOTSTRAP.md               # first run only
  MEMORY.md                  # not injected into subject prompts by default
  user/  workspace/          # created by initialize_agent_workspace, never injected
```

Seed the workspace with `initialize_agent_workspace(root, templates=...)`; pass
`seed_bootstrap=False` when the host has no first-run ritual (setup is then
marked complete right away).

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
  empty files, a missing MEMORY.md and a missing PROACTIVE_PREFERENCES.md
  (extension, no upstream counterpart) are skipped, so a pin-era workspace
  renders the same under the default layout and `OPENCLAW_PIN_LAYOUT`.
- The agent's root MEMORY.md is not injected unless `include_agent_memory=True`.
  This is a deliberate deviation: upstream injects it for every session that is
  not a subagent or cron session, but a live subject prompt should not carry the
  operator's long-term memory. Subject memory reaches the prompt through recall.
- While BOOTSTRAP.md is pending, the bootstrap mode follows upstream's
  `resolveBootstrapMode` with host inputs. `has_bootstrap_file_access`
  (default `False`: memory_core.live gives the model no tools; pass `True` when
  the host gives it a `read` tool) and `is_canonical_workspace` (default
  `True`). A BOOTSTRAP.md with content counts as file access, as upstream's
  attempt routing does, so the prompt carries `## Bootstrap Pending` and the
  file (`full`). An empty BOOTSTRAP.md without file access gives the `limited`
  lines and leaves the file out. A live workspace never produces setup
  evidence on its own (subject memory lives under `subjects/`), so the host
  removes BOOTSTRAP.md, seeds with `seed_bootstrap=False`, or passes
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
pairs and `identity.warnings` the budget warnings. `IDENTITY_FILE_ORDER` and
`IDENTITY_FILE_NAMES` stay exported for compatibility (`(name, name)` pairs and
a frozenset of the default load order).

Changes from the earlier loader that a host will notice:

- `max_chars_per_file=None` used to mean "no cap"; it now falls back to the
  20,000 default like upstream's config resolution, and there is no way to
  switch the cap off.
- A directory that does not exist no longer yields an empty identity: every
  layout file renders `[MISSING] Expected at: <absolute path>`, as upstream
  does for a workspace without its files. Pass `required_files` to fail
  instead.
- With the default `path_style="absolute"` the `## <path>` headings and the
  `[MISSING]` markers carry the host's absolute filesystem paths (user names,
  server layout) to the LLM provider on every turn, exactly like upstream.
  Pass `path_style="relative"` to send root-relative paths instead.

Use `LiveIdentityStore` when a host runtime wants stable cached workspace
instructions during a session and explicit reloads after file changes:

```python
identity_store = LiveIdentityStore("./workspace", required_files=["AGENTS.md"])
identity = identity_store.load()
identity = identity_store.reload()
```

`load()` caches everything, including the bootstrap state: the bootstrap mode,
`## Bootstrap Pending` and the truncation notice stay as they were at the last
`reload()`, even after BOOTSTRAP.md is deleted. Upstream refreshes bootstrap
files every turn (`src/agents/bootstrap-cache.ts`) and runs
`ensureAgentWorkspace` on every reply (`src/auto-reply/reply/get-reply.ts`),
which is when a configured workspace gets its BOOTSTRAP.md reconciled away. A
host that wants that lifecycle calls `initialize_agent_workspace(root,
templates=...)` with the same templates and then `reload()` at each turn (or at
least at each session start).

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

`subject_id` must be filesystem-safe, because it names the subject directory:
letters, digits, `_`, `.` and `-` only (`SAFE_ID_RE`), and not only dots (`.`
and `..` would name the namespace directory or the root). `SubjectMemory.open`
rejects an unsafe `subject_id` with `ValueError`.

`session_id` is any host id (`whatsapp:+905551234567`, a Slack thread key):
`prepare_live_turn`, `stream_live_turn` and `record_session_summary` never build
a path from it. The check applies where an id becomes a file name, in
`JsonlTraceSink.for_session` (see [Trace Sink](#trace-sink)).

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

One `MemoryConfig` can be shared by every subject (`config=shared_config`). Its
settings (flags, weights, `agent_id`, limits) are kept, but its paths are
rebased onto the subject directory: `workspace_dir` becomes
`subjects/<subject_id>/`, and `store_path` is resolved like this:

| `store_path` in the shared config | Index used by subject `subj_123` |
|---|---|
| `None` | `subjects/subj_123/.memory-core/<agent_id>.sqlite` |
| inside the subject directory | kept as given |
| inside `config.workspace_dir` (for example `<root>/index/live.sqlite`) | same relative path under the subject (`subjects/subj_123/index/live.sqlite`) |
| anywhere else | `ValueError`: one index would serve every subject |

Without the rebase, every subject shared `<root>/.memory-core/main.sqlite`, each
reindex deleted the other subjects' chunks, and `memory_get` read from the root.

## Streaming Turn

```python
from memory_core import JsonlTraceSink, LiveIdentity, LiveSDKConfig, LiveTurnContext, SubjectMemory

identity = LiveIdentity.from_dir("./workspace")
memory = SubjectMemory.open(
    workspace_dir="./memory-core-state",
    subject_id="subj_123",
)
trace_sink = JsonlTraceSink.for_session("./memory-core-state/trace", "session_456")
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
    host_context={"plan": "premium", "preferred_channel": "sms"},
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

`LiveTurnContext` carries the host's input for the turn. Besides
`user_utterance`, the optional `transcript_window`, `host_context` (host-owned
facts about the subject or session, such as an account record or device state;
a mapping or text), `workflow_state` and `trace_events` are rendered into the
marker-wrapped runtime context as `## Transcript window`, `## Host context`,
`## Active workflow` and `## Recent trace`. None of them is written to memory.

Breaking change (commit `5655077`, 2026-09-26): `host_context` replaced the
field left over from the removed live prototype, and its section heading became
`## Host context`. There is no alias (the package is unreleased,
0.1.0): passing the old keyword raises `TypeError`, and a host that matched the
old heading in its own prompt handling must match `## Host context`.

`llm` is a host-supplied callable. It receives the assembled chat messages and
returns an async iterable of text chunks, or dictionaries containing `text`,
`delta`, or `content`.

A blank `user_utterance` (empty or whitespace only, such as a silent ASR turn)
makes `prepare_live_turn` raise `MemoryToolInputError("query required")` from the
memory search; `stream_live_turn` yields `live_turn_started`, then
`live_turn_failed` (`error_type` `MemoryToolInputError`, `error` `query required`),
then re-raises it, like any other failure after the start event. Skip the turn
or catch the error (`docs/memory_search_tool.md`, "Blank queries").

## Event Contract

The SDK exports event-name constants and a `LiveTurnEventType` literal alias.
Current event types:

| Event | Emitted by | Reaches the host as |
|---|---|---|
| `live_turn_started` | `stream_live_turn` | yielded, and recorded to the trace sink |
| `memory_recall_completed` | `stream_live_turn` | yielded, and recorded to the trace sink |
| `prompt_assembled` | `stream_live_turn` | yielded, and recorded to the trace sink |
| `text_delta` | `stream_live_turn` | yielded, and recorded to the trace sink |
| `provider_event` | `stream_live_turn` | yielded, and recorded to the trace sink |
| `sentence` | `stream_live_turn` | yielded, and recorded to the trace sink |
| `live_turn_completed` | `stream_live_turn` | yielded, and recorded to the trace sink |
| `live_turn_failed` | `stream_live_turn` | yielded, and recorded to the trace sink, then the exception is re-raised |
| `session_summary_started` | `record_session_summary` | trace sink only |
| `session_summary_completed` | `record_session_summary` | trace sink only |
| `session_summary_skipped` | `record_session_summary` | trace sink only |
| `session_summary_failed` | `record_session_summary` | trace sink only, then the exception is re-raised |

The `session_summary_*` events are never yielded: `record_session_summary` and
`async_record_session_summary` return a `SessionSummaryResult`, and their events
go only to the `trace_sink=` passed to that call (`LiveSDKConfig.trace_sink`
applies to `stream_live_turn` only). Without a trace sink they are not
observable.

`sentence` events are designed for TTS. `text_delta` events are useful for live
UI, logs, and transcript buffers.

`provider_event` passes through non-text provider chunks such as tool-call or
function-call deltas. The SDK does not execute tools or mutate workflow state;
the host runtime consumes these events and decides what to do.

Once `live_turn_started` has been yielded, any exception in the turn (a
`subject_id` that does not match the `SubjectMemory`, a recall error, or the
host-supplied LLM stream raising) records `live_turn_failed` with `error_type`,
`error`, and the partial `assistant_text` to the trace sink, yields it, and
then re-raises the original exception on the next iteration step, so the host
runtime can apply its retry or fallback policy. A consumer that stops iterating
at `live_turn_failed` closes the stream without the re-raise. The `error` text
is `str(exception)`, unredacted: a host that forwards events to a client
should redact it first.

The host still owns workflow state transitions and tool calls. Put active
workflow state into `LiveTurnContext.workflow_state`; the SDK places it inside
runtime context rather than durable memory.

## Trace Sink

Pass `trace_sink=` to `stream_live_turn` when you want the SDK to persist the
same events it yields, in the same order. Pass it to `record_session_summary`
to observe the `session_summary_*` events at all; they are trace-only.
`JsonlTraceSink` writes one JSON object per event:

```json
{"type":"sentence","text":"Tabii, yardimci olayim.","data":{}}
```

`JsonlTraceSink.for_session(trace_dir, session_id)` builds
`<trace_dir>/<session_id>.jsonl` and raises `ValueError` unless `session_id`
matches upstream's `SAFE_SESSION_ID_RE` (`src/config/sessions/paths.ts`): a
leading letter or digit, then at most 127 of `[A-Za-z0-9._-]`. So `../../x`
cannot write outside the trace directory and a very long id fails before the
first write. A host whose ids do not fit (a phone number with `+` and `:`) maps
them to a safe file name itself, or keeps traces in its own `TraceSink`.

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

`summary_llm` receives the OpenClaw-style memory flush messages; the
memory-core-authored part of the user message names the two accepted reply shapes
(a JSON object with `durable_facts`, `preferences` and `follow_ups`, or lines
that each start with `- `). Its reply is sanitized before anything is written,
and only those two shapes are ever written. This is a memory-core rule (upstream's
flush turn writes through tools and has no reply-to-file step):

1. Tool-call spans (`<|tool_call>…<tool_call|>`, `<tool_call>…</tool_call>`,
   `<|tool_call_begin|>…<|tool_call_end|>`; an unclosed span runs to the end of
   the reply) and special tokens with a pipe on both sides, such as
   `<|im_end|>`, are removed; so is a line that is only a marker (upstream's
   `HARMONY_CHANNEL_MARKER_RE`, applied per line). Text such as `<A|B>` inside
   a fact stays. A reply that then starts with `NO_REPLY` writes nothing
   (`skip_reason="silent"`). A trailing `NO_REPLY` is stripped, as upstream's
   `stripSilentToken` does.
2. A JSON object, optionally inside a ```` ``` ```` fence and after label
   lines, keeps only `durable_facts`, `preferences`, and `follow_ups`, one
   bullet per item with whitespace collapsed:

   ```json
   {
     "durable_facts": ["Subject moved to the premium plan."],
     "preferences": ["Subject prefers evening delivery."],
     "follow_ups": ["Send updated invoice."]
   }
   ```

3. Otherwise the reply must be a bullet list. Label lines are dropped:
   non-bullet lines ending with `:` (a model preamble `Appending durable memory
   to memory/2026-09-26.md:`, a `Preferences:` label), Markdown headings
   (`## Session notes`) and bold labels (`**Preferences:**`,
   `**Preferences**:`). An indented line continues the bullet above it. Every
   other non-empty line must start with `-`, `*`, or `+`. Bullets are written
   as `- <text>`.
4. Anything else writes nothing (`skip_reason="unstructured"`): prose, a JSON
   value that is not an object, a numbered list, other bullet glyphs (`•`), a
   reasoning block such as `<think>…</think>`, or bullets mixed with prose. A
   reply with nothing left, or a JSON object without those fields, gives
   `skip_reason="empty"`.

| `summary_llm` reply | Written to `memory/YYYY-MM-DD.md` |
|---|---|
| `Appending durable memory to memory/2026-09-26.md:`<br>`- Subject prefers SMS.<\|tool_call>call:write{…}<tool_call\|>`<br>`NO_REPLY` | `- Subject prefers SMS.` |
| `{"preferences": ["Subject prefers SMS."]}` | `- Preference: Subject prefers SMS.` |
| `**Preferences:**`<br>`- Subject uses the <A\|B> plan tier.` | `- Subject uses the <A\|B> plan tier.` |
| `The subject prefers SMS updates.` | nothing (`unstructured`) |
| `NO_REPLY` | nothing (`silent`) |

`result.skip_reason` is `None` when something was written; the
`session_summary_skipped` trace event carries the same `skip_reason`.
`result.raw_text` keeps the unsanitized reply. A skip raises nothing: without
a trace sink it is visible only in the returned `skip_reason`, so a host that
must not lose facts checks it (and can retry with a stricter extractor).

Behaviour change (branch `feat/workspace-layout`, 2026-09-26): before this rule,
any reply that was not a JSON object was appended verbatim. A host whose
extractor answered in prose or another shape now writes nothing for it.

## Subject Promotion

`SubjectConsolidation` runs scored promotion and dreaming
(`memory_core.consolidation`) inside one subject's workspace. It is a memory-core
extension (decision Q16) behind `FeatureFlags.subject_promotion`, off by
default; with the flag off every call raises `SubjectPromotionDisabledError`.

```python
from memory_core import FeatureFlags, SubjectConsolidation
from memory_core.live import SubjectMemory

memory = SubjectMemory.open(
    workspace_dir="runtime",
    subject_id="subject_123",
    flags=FeatureFlags(vector_search=False, subject_promotion=True),
)
consolidation = SubjectConsolidation(memory)

hits = memory.memory.search("delivery window")["results"]
consolidation.record_recalls("delivery window", hits, now_ms=now_ms)
run = consolidation.promote(now_ms=now_ms, timezone="Europe/Istanbul")
sweep = consolidation.dream("light", now_ms=now_ms)
```

Recall stores, promoted `MEMORY.md` sections and `DREAMS.md` stay under
`runtime/subjects/subject_123/`. `record_recalls` drops the `Source:` citation
that `memory_search` appends, like upstream recall tracking. Nothing runs on a
schedule; the host decides when to promote or dream.

Promotion markers: `SubjectConsolidation(memory)` writes the neutral
`<!-- memory-core-memory-promotion:<key> -->` marker whatever
`LiveSDKConfig.openclaw_compatible` says (the live config switches only the
runtime-context markers). A host in compatibility mode passes
`SubjectConsolidation(memory, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)` to
write upstream's `openclaw-memory-promotion:` prefix. Compatibility is one
way: memory-core reads both prefixes, but OpenClaw's `extractPromotionMarkers` and
`isContaminatedDreamingSnippet` match only its own. OpenClaw run on a
`MEMORY.md` with neutral markers would promote the same lines again, and it
does not treat a recalled snippet that holds only a neutral marker as
scaffolding, so a workspace that OpenClaw also promotes into must use the
compat identity.

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
Without a provider key (request or `.env`) the replies are scripted; the state
payload's `engine` says which one a turn uses. Summaries pass a host redactor
that replaces the utterance which verified the subject with
`[kimlik bilgisi gizlendi]`, so identity data never reaches subject memory, and
the SDK sanitizer skips replies that are neither JSON nor `- ` lines.

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
