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
  `AutomationJob`, `FileAutomationStore`, `due_automation_jobs`, `heartbeat_scheduled_tasks`,
  `record_automation_job_run`; the doctor migrations in `memory_core.heartbeat_migration`).
  Heartbeat itself is a runtime feature: the host owns the scheduler (monitor cadence,
  job timers, retries), the model call and delivery; memory-core decides what the heartbeat
  turn sends (the monitor scratch, the due jobs as scheduled tasks), whether it is skipped
  and how its reply is read, and gives hosts a small scratch/job store interface with a
  file-backed default (`<root>/.memory-core/automation.json`). The helpers are in core because
  heartbeat turns change memory-core behaviour: the session corpus drops heartbeat prompt
  rows, `NO_REPLY` and `HEARTBEAT_OK` replies, which works only when the host writes the
  same prompt and tokens; and memory flush skips heartbeat runs. A later host kit
  (`memory_core.host`) is meant to wrap them; it does not exist yet. Evidence: the "Heartbeat
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
| Daily capture | `memory/YYYY-MM-DD.md` (append only) | the model's flush pass (`NO_REPLY` writes nothing) | `memory_core.memory_flush`, `Memory.chat(force_flush=True)` | flush plan oracle-backed; the write loop is adapter-only |
| Scored promotion and dreaming | dated `## Promoted From Short-Term Memory (<date>)` sections of `MEMORY.md`, `memory/.dreams/*.json`, `DREAMS.md` | recall signals and the score, signal, diversity and age gates; no LLM | `memory_core.consolidation` | 21 promotion oracle tests assert Python == TS (docs/parity_matrix.md) |
| Curated writes | the non-promotion blocks of `MEMORY.md`, `USER.md`, `PROACTIVE_PREFERENCES.md`, today's daily note (append only) | the agent, through curation tools (decision Q16, on by default) | `memory_core.curation` (`MemoryCurator`, `Memory.curator()`) | memory-core extension, no upstream counterpart; one oracle test runs curated edits against the real promotion apply |
| Session snapshot | a new `memory/<date>-<slug>.md` per ending session (never appended to) | the host's `/new` or `/reset` command; the slug comes from a host-supplied generator, else the timestamp | `memory_core.session_memory` (`save_session_memory`) | oracle-backed with named deviations (docs/parity_matrix.md) |

- Scored consolidation never runs on its own: there is no scheduler and
  dreaming is off by default (`DEFAULT_DEEP_DREAMING_ENABLED = False`). A host
  records hits with `record_short_term_recalls` and calls
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

## Runtime Adapters

Runtime adapters connect core memory to host applications. They are intentionally
thin.

Included:

- `LangGraphMemoryRecall`
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

Example: a LangGraph node can call `LangGraphMemoryRecall` before the model node
and inject the returned `memory_context` into the model prompt.

## Demo App

The demo is a local inspection tool. It is useful for manual testing but is not
the package contract.

Demo-only responsibilities:

- browser controls, the chat lab UI and its inspectors
- the host side of a turn: provider resolution (keys request-scoped or from
  the environment, never stored), the tool loop that dispatches the package's
  `memory_search`/`memory_get` adapters and `MemoryCurator.dispatch`, the
  pre-turn flush decision inputs, sessions, the event log and file snapshots
  (`demo/lab_*.py`, docs/lab.md)
- manual flush, promote, dreaming, audit and repair actions (they call
  `memory_core.consolidation` and `memory_core.memory_flush`; the demo keeps only
  serializers)

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
