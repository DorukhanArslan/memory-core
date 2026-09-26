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
- MEMORY.md budget compaction (`memory_core.memory_budget`)
- curated memory writes (`MemoryCurator`, `Memory.curator()`): a memory-core
  extension, not OpenClaw parity, behind `FeatureFlags.curated_memory_writes`;
  the host decides which operations to offer (`CurationPolicy`) and passes
  `memory_flush=True` during flush runs
- replay cleanup, history windowing, tool-use repair, and overflow helpers when
  those behaviors are required to preserve OpenClaw-compatible prompt assembly

Core memory should not know about Slack, WhatsApp, FastAPI, browser UI, or a
specific agent framework.

## Runtime Adapters

Runtime adapters connect core memory to host applications. They are intentionally
thin.

Included:

- `LangGraphMemoryRecall`

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
- manual flush buttons

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
