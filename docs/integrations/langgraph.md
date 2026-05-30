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
from pathlib import Path

from memory_core import LangGraphMemoryRecall, MemoryConfig, MemoryWorkspace
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore

workspace = MemoryWorkspace(Path("."))
config = MemoryConfig(workspace_dir=workspace.root)
store = SQLiteMemoryStore.in_memory(embedding_provider=FakeEmbeddingProvider())
store.reindex(workspace)

recall_node = LangGraphMemoryRecall(config=config, store=store)

state_update = recall_node({"input": "Bana nasil hitap edeceksin?"})
```

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
