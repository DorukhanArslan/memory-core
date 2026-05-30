# LangGraph Integration

`LangGraphMemoryRecall` is a small adapter that makes memory recall fit the
common LangGraph shape:

```text
state in -> partial state update out
```

It does not import LangGraph. This keeps `memory-core` usable in projects
that do not depend on LangGraph.

## Minimal Flow

```python
from memory_core import MemoryCoreMemory
from memory_core.embeddings.base import FakeEmbeddingProvider

memory = MemoryCoreMemory.from_workspace(
    embedding_provider=FakeEmbeddingProvider(),
)
recall_node = memory.langgraph_recall()

state_update = recall_node({"input": "Bana nasil hitap edeceksin?"})
```

The memory files live in the host application workspace:

```text
my-agent-app/
  MEMORY.md
  memory/
    2026-05-30.md
  .memory-core/
    main.sqlite
```

Initialization is on by default and is memory-core only. It creates `MEMORY.md`,
`memory/`, and `.memory-core/` if missing, while preserving existing files.
Pass `initialize=False` to disable file creation.

Example output:

```python
{
    "memory_context": "Memory recall:\n- memory/2026-05-30.md:3-3 score=0.91\n  User prefers to be addressed as Doruk.\n\nSource: memory/2026-05-30.md#L3",
    "memory_results": [
        {
            "path": "memory/2026-05-30.md",
            "score": 0.91,
            "snippet": "User prefers to be addressed as Doruk.\n\nSource: memory/2026-05-30.md#L3",
        }
    ],
}
```

The host application decides how to insert `memory_context` into its prompt.

## Message State

If the state does not contain `input`, the adapter reads the latest user message
from `messages`:

```python
state_update = recall_node(
    {
        "messages": [
            {"role": "user", "content": "Selam"},
            {"role": "assistant", "content": "Selam Doruk."},
            {"role": "user", "content": "Bana nasil hitap edeceksin?"},
        ]
    }
)
```

## What This Is Not

This adapter is not OpenClaw runtime parity. It is `adapter-only` glue.

OpenClaw-compatible behavior remains inside the memory APIs it calls:

- `memory_search`
- scoring and citations
- workspace path rules
- replay/context helpers used by host runtimes

LangGraph still owns graph edges, checkpointer behavior, model invocation, and
final prompt assembly.
