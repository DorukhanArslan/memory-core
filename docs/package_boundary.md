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
- `memory_search` and `memory_get`
- Markdown memory files such as `MEMORY.md` and `memory/YYYY-MM-DD.md`
- SQLite-backed indexing, hybrid search, MMR, temporal scoring, and citations
- flush planning and daily-memory target validation
- `memory_core.bootstrap`: workspace layouts, seeding and the BOOTSTRAP.md
  lifecycle, bootstrap file loading, budget and truncation, Project Context
  rendering and the startup-context prelude (see
  [Workspace Layout](workspace_layout.md))
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

Three paths change memory files; none of them uses keyword triggers.

| Mode | Writes | Decided by | Module | Evidence |
| --- | --- | --- | --- | --- |
| Daily capture | `memory/YYYY-MM-DD.md` (append only) | the model's flush pass (`NO_REPLY` writes nothing) | `memory_core.memory_flush`, `Memory.chat(force_flush=True)` | flush plan oracle-backed; the write loop is adapter-only |
| Scored promotion and dreaming | dated `## Promoted From Short-Term Memory (<date>)` sections of `MEMORY.md`, `memory/.dreams/*.json`, `DREAMS.md` | recall signals and the score, signal, diversity and age gates; no LLM | `memory_core.consolidation` | 21 promotion oracle tests assert Python == TS (docs/parity_matrix.md) |
| Curated writes | the rest of `MEMORY.md` | the agent, through curation tools (decision Q16, on by default) | `memory_core.curation` (developed on its own branch, not in this tree yet) | memory-core extension, no upstream counterpart |

- Scored consolidation never runs on its own: there is no scheduler and
  dreaming is off by default (`DEFAULT_DEEP_DREAMING_ENABLED = False`). A host
  records hits with `record_short_term_recalls` and calls
  `run_short_term_promotion` or `run_dreaming_sweep` when it chooses.
- The two MEMORY.md writers share one block model
  (`memory_core.memory_budget.parse_memory_blocks`): budget compaction only drops
  the oldest promotion sections, never other blocks.
- Promotion markers use the runtime identity's prefix
  (`memory-core-memory-promotion:` by default, `openclaw-memory-promotion:` under
  `OPENCLAW_COMPAT_RUNTIME_IDENTITY`); both prefixes are read (decision Q22).
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

- browser controls
- chat lab UI
- OpenAI-compatible demo provider form
- side-by-side inspectors
- manual flush, promote, dreaming, audit and repair buttons (they call
  `memory_core.consolidation`; the demo keeps only serializers)

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
