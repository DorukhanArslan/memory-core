# Package Boundary

This project is a Python memory-core package, not a full OpenClaw runtime.

The goal is to preserve OpenClaw-compatible memory behavior where it belongs in
the portable memory layer, while keeping host-framework glue small and explicit.

## Core Memory

Core memory is the reusable package surface that any agent runtime can call.

Included:

- `MemoryWorkspace` and `MemoryConfig`
- `Memory.from_workspace(...)`
- `initialize_memory_core_workspace(...)`
- `memory_search` and `memory_get`, their tool-call entry points
  (`execute_memory_search_tool`, `execute_memory_get_tool`) and upstream tool
  definitions (`memory_search_tool_definition`, `memory_get_tool_definition`);
  params, errors, deadline, cooldown and index-identity gating:
  `docs/memory_search_tool.md`
- Markdown memory files such as `MEMORY.md` and `memory/YYYY-MM-DD.md`
- SQLite-backed indexing, hybrid search, MMR, temporal scoring, and citations
- flush planning and daily-memory target validation
- `memory_core.bootstrap`: workspace layouts, seeding and the BOOTSTRAP.md
  lifecycle, bootstrap file loading, budget and truncation, Project Context
  rendering and the startup-context prelude (see
  [Workspace Layout](workspace_layout.md))
- MEMORY.md budget compaction (`memory_core.memory_budget`)
- curated memory writes (`MemoryCurator`, `Memory.curator()`): a memory-core
  extension, not OpenClaw parity, behind `FeatureFlags.curated_memory_writes`;
  the host decides which operations to offer (`CurationPolicy`) and passes
  `memory_flush=True` during flush runs; `MemoryCurator.dispatch` raises
  `MemoryToolInputError` like `memory_search`, so one host handler sends the
  model `error.to_tool_error()` for both; a failing `after_write` hook (the
  facade's reindex) never raises: the committed write returns its ok payload
  with `afterWriteError`. `dispatch` accepts a mapping or its JSON text, while
  `execute_memory_search_tool` / `execute_memory_get_tool` need the parsed
  mapping (a JSON string reads as `{}`, as upstream `asToolParamsRecord`)
- the session-memory hook for `/new` and `/reset` (`save_session_memory`,
  `memory_core.session_memory`): the host calls it with the ending session's
  transcript file or messages; it writes a new `memory/<date>-<slug>.md` through
  its own write path, never through the daily-flush target, and after the host
  reindexes, `memory_search` finds it like any `memory/**/*.md`; an LLM slug needs a
  host-supplied generator, and a host redactor can map each stored line
- heartbeat and automation helpers in the v2026.9.6 shape (`prepare_heartbeat_turn`,
  `HeartbeatTurn`, `HeartbeatScheduledTask`, `decide_heartbeat_reply`,
  `HeartbeatReplyDecision`, `strip_heartbeat_token`, `resolve_heartbeat_interval_ms`,
  `HEARTBEAT_PROMPT`, `HEARTBEAT_TOKEN`; `HeartbeatScratchState`, `HeartbeatScratchStore`;
  `AutomationJob`, `AutomationStore`, `FileAutomationStore`, `due_automation_jobs`,
  `heartbeat_scheduled_tasks`,
  `record_automation_job_run`; the doctor migrations in `memory_core.heartbeat_migration`).
  Heartbeat itself is a runtime feature: the host owns the scheduler (monitor cadence,
  job timers, retries), the model call and delivery; memory-core decides what the heartbeat
  turn sends (the monitor scratch, the due jobs as scheduled tasks), whether it is skipped
  and how its reply is read, and gives hosts a small scratch/job store interface with a
  file-backed default (`<root>/.memory-core/automation.json`). The helpers are in core because
  heartbeat turns change memory-core behaviour: the session corpus drops heartbeat prompt
  rows, `NO_REPLY` and `HEARTBEAT_OK` replies, which works only when the host writes the
  same prompt and tokens; and memory flush skips heartbeat runs. The host kit's
  `HostKit.heartbeat_prompt` composes them for one run (below). Evidence: the "Heartbeat
  turn inputs and reply handling", "Heartbeat monitor scratch" and "Automation jobs and
  heartbeat migrations" rows in `docs/parity_matrix.md`
- replay cleanup, history windowing, tool-use repair, and overflow helpers when
  those behaviors are required to preserve OpenClaw-compatible prompt assembly
- `memory_core.consolidation`: scored consolidation. Short-term recall signals,
  gated promotion into `MEMORY.md`, manual light/REM/deep dreaming sweeps,
  the deep-dreaming policy resolver, and audit/repair of the recall stores
  (moved out of `demo/` on 2026-09-26, decision Q13). Budget compaction is
  `memory_core.memory_budget`.

Core memory should not know about Slack, WhatsApp, FastAPI, browser UI, or a
specific agent framework.

## Consolidation Modes

Four paths change memory files; none of them uses keyword triggers.

| Mode | Writes | Decided by | Module | Evidence |
| --- | --- | --- | --- | --- |
| Daily capture | `memory/YYYY-MM-DD.md` (append only) | the model's flush pass through the append-only `write` tool (`NO_REPLY` writes nothing) | `memory_core.memory_flush`, `memory_core.host` (`FlushRequest`) | flush plan oracle-backed; the write loop is adapter-only |
| Scored promotion and dreaming | dated `## Promoted From Short-Term Memory (<date>)` sections of `MEMORY.md`, `memory/.dreams/*.json`, `DREAMS.md` | recall signals and the score, signal, diversity and age gates; optional host-model consolidation in the deep phase | `memory_core.consolidation` | oracle-backed helpers with named phase/runtime gaps (docs/parity_matrix.md) |
| Curated writes | the non-promotion blocks of `MEMORY.md`, `USER.md`, `PROACTIVE_PREFERENCES.md`, today's daily note (append only) | the agent, through curation tools (decision Q16, on by default) | `memory_core.curation` (`MemoryCurator`, `Memory.curator()`) | memory-core extension, no upstream counterpart; one oracle test runs curated edits against the real promotion apply |
| Session snapshot | a new `memory/<date>-<slug>.md` per ending session (never appended to) | the host's `/new` or `/reset` command; the slug comes from a host-supplied generator, else the timestamp | `memory_core.session_memory` (`save_session_memory`) | oracle-backed with named deviations (docs/parity_matrix.md) |

- Scored consolidation never runs on its own: there is no scheduler and
  the scored deep policy is enabled by default (`DEFAULT_DEEP_DREAMING_ENABLED = True`).
  The separate LLM consolidation option is off by default and requires a host-supplied model.
  A host records hits with `record_short_term_recalls` and calls
  `run_short_term_promotion` or `run_dreaming_sweep` when it chooses.
- Promotion and curation share one block model
  (`memory_core.memory_budget.parse_memory_blocks`): budget compaction only drops
  the oldest promotion sections, never other blocks, and `memory_core.curation`
  treats the same promotion sections, and any line carrying a promotion
  marker, as read-only.
- Promotion markers use the runtime identity's prefix
  (`memory-core-memory-promotion:` by default, `openclaw-memory-promotion:` under
  `OPENCLAW_COMPAT_RUNTIME_IDENTITY`); both prefixes are read, by promotion
  and by curation (`memory_core.consolidation.markers`, decision Q22).
- Live subjects: `memory_core.live.SubjectConsolidation` runs the same pipeline in
  one `subjects/<id>/` workspace behind `FeatureFlags.subject_promotion` (off
  by default, decision Q16).

## Host Kit

`memory_core.host` is the composition a host would otherwise copy: one `HostKit` per
workspace with six entry points (`tools`, `dispatch`, `before_turn`, `after_turn`,
`on_new_session`, `heartbeat_prompt`), `ensure` (the workspace ensure `before_turn` runs
first), the labelled extension `request_flush` (a flush outside the token gate, decision Q6),
two helpers for framework hosts (`dispatcher`, `dispatch` bound to a session;
`repair_tool_calls`, which composes the core's ports of upstream's replay repair over the
host's rows) and the handles they return (`TurnContext`, `TurnState`, `TurnRecord`,
`FlushRequest`, `FlushOutcome`, `NewSession`, `ResetTurn`, `HeartbeatRun`,
`HeartbeatOutcome`, `ToolCallRepair`). The host keeps one `SessionState` per session and
gets new copies back. The kit only composes core
functions, never calls a model and keeps no per-session state; the host owns the agent
and tool loop, the model call, streaming, compaction, scheduling and session storage.
It is adapter-only code: the orders and inputs it takes from upstream are
source-backed and named in `docs/host_kit.md`. It replaced the facade's turn helpers
(`Memory.prepare_turn`, `Memory.chat`, `Memory.record_turn`), removed in 0.2.0.

## Runtime Adapters

Runtime adapters connect core memory to host applications. They are intentionally
thin.

Included:

- `memory_core.adapters.langgraph`: framework-free helpers for a LangGraph host over the
  host kit (`transcript_rows`, `turn_usage`, `has_tool_calls`, `tool_messages`,
  `repair_tool_calls`); it imports no framework, owns no loop and calls no model. The turn
  in flight crosses the graph's steps as the kit's `TurnState`. The graph
  itself is host code: `examples/langgraph_agent.py` (docs/integrations/langgraph.md)
- `memory_core.live` (subject memory, live turns, session summaries) and
  `SubjectConsolidation`, which only routes a subject's workspace into
  `memory_core.consolidation`

Adapter responsibilities:

- read the current user input from host state
- call core memory APIs
- return a host-friendly state patch

Adapter non-goals:

- owning the host conversation loop
- choosing the LLM provider
- replacing LangGraph checkpointers
- pretending to be OpenClaw runtime behavior

The auto-recall node `LangGraphMemoryRecall` was removed in 0.2.0, pending Doruk's
confirmation (docs/integrations/langgraph.md › Open questions, L1): it injected search
results into the prompt, which upstream never does (CHANGELOG.md › Removed).

## Demo App

The demo is a local inspection tool. It is useful for manual testing but is not
the package contract.

Demo-only responsibilities:

- browser controls, the chat lab UI and its inspectors
- the host side of a turn over `memory_core.host` (the Lab dogfoods the kit): provider
  resolution (keys request-scoped or from the environment, never stored), the tool loop
  over `HostKit.tools()` and `HostKit.dispatch`, the index bookkeeping (`LabStore`), the
  host inputs of `HostKit.after_turn` (turn usage or a labelled estimate, the transcript
  size), the flush run of a `FlushRequest` on its model, `/new` over
  `HostKit.on_new_session`, the heartbeat run over `HostKit.heartbeat_prompt`, sessions,
  the event log and file snapshots (`demo/lab_*.py`, docs/lab.md)
- the `/flush` extension (`HostKit.request_flush`) and the promote, dreaming, audit and
  repair actions (they call `memory_core.consolidation`; the demo keeps only serializers)

Do not copy demo internals into production integrations. Production hosts should
depend on the package API and adapter layer.

## Out Of Scope

This package does not implement the full OpenClaw runtime.

Out of scope:

- channel gateways
- RBAC and permission middleware
- scheduler/cron runtime
- subagent orchestration
- process sandboxing
- provider routing for a full agent system
- UI shell

Those belong to a host framework such as OpenClaw, LangGraph, or a custom
application.

## Parity Labels

Use these labels when documenting or reviewing behavior:

- `oracle-backed`: verified by running pinned OpenClaw TypeScript behavior
- `source-backed`: implemented from upstream source reading, without executable
  oracle coverage
- `adapter-only`: Python host integration glue, not an OpenClaw behavior
- `demo-only`: local browser lab behavior, not package API
- `known-gap`: intentionally documented difference or unfinished behavior

The public package should not claim full OpenClaw parity for `adapter-only` or
`demo-only` code.
