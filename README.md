# memory-core

Python port of OpenClaw core memory, pinned to upstream commit
`7f6798094ce9486a8f463772f4535484aca73fe2`.

The first implementation slice covers `MEMORY.md`, `memory/YYYY-MM-DD.md`,
`memory_search`, `memory_get`, hybrid search, citations, and a local FastAPI demo.

## Python API

The stable package surface is exported from `memory-core`:

```python
from pathlib import Path

from memory_core import (
    MemoryCoreMemory,
    build_memory_flush_plan,
)
from memory_core.embeddings.base import FakeEmbeddingProvider

memory = MemoryCoreMemory.from_workspace(
    Path("."),
    embedding_provider=FakeEmbeddingProvider(),
)

results = memory.search("preferred name", max_results=5)
memory_file = memory.get("MEMORY.md", from_line=1, lines=20)
recall_node = memory.langgraph_recall()
flush_plan = build_memory_flush_plan(workspace_dir=memory.workspace.root)
```

`MemoryCoreMemory.from_workspace(...)` reads memory files from the host
application workspace, not from this package. For example:

```text
my-agent-app/
  MEMORY.md
  memory/
    2026-05-30.md
  .openclaw-memory/
    main.sqlite
```

Runtime-adapter helpers such as transcript replay cleanup, history windowing,
runtime-context prompt splitting, and overflow recovery are also exported from
the package root when host applications need OpenClaw-compatible behavior.

See [Package Boundary](docs/package_boundary.md) for what belongs to core
memory, runtime adapters, demo code, and out-of-scope host runtime behavior.
See [LangGraph Integration](docs/integrations/langgraph.md) for a minimal
`state -> memory_context` adapter example.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run Tests

```bash
pytest -v
ruff check .
```

## Run Demo

```bash
python -m uvicorn demo.app:app --port 8000
```

Open <http://127.0.0.1:8000>. The first screen is an OpenClaw-style chat
memory lab. Enter an OpenAI-compatible API key, send a message, inspect memory
recall, run a manual memory flush, or enable auto flush to write durable
memories while chatting.

The chat demo uses only the OpenAI-compatible engine. The browser keeps the API
key in session storage and sends it with each chat/flush request; the backend
does not write it to disk. Defaults are `https://api.openai.com/v1` and
`gpt-5.2`. You can also configure the backend with environment variables:

```bash
export OPENCLAW_DEMO_OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENCLAW_DEMO_OPENAI_API_KEY="sk-demo-key"
export OPENCLAW_DEMO_OPENAI_MODEL="gpt-5.2"
```

Memory flush writes are restricted to `memory/YYYY-MM-DD.md`, matching
OpenClaw pre-compaction memory flush behavior. The demo appends to the canonical
daily file and rejects timestamped variants or other write targets.

Smoke test the chat lab endpoints:

```bash
curl -s http://127.0.0.1:8000/api/chat/state
curl -s -X POST http://127.0.0.1:8000/api/chat/send \
  -H 'Content-Type: application/json' \
  -d '{"message":"Ben teknik cevapları Türkçe tercih ediyorum.","engine":"openai","openai":{"apiKey":"sk-demo-key","model":"gpt-5.2"},"autoFlush":true}'
```

## Live OpenAI-Compatible Embeddings

The demo and tests default to deterministic fake embeddings. To add a live
provider flow, configure `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and model
`text-embedding-3-small`.
