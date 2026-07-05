# memory-core

`memory-core` is a Python memory core for LLM agents. It tracks OpenClaw
memory-core behavior against upstream commit
`7f6798094ce9486a8f463772f4535484aca73fe2`.

The first implementation slice covers `MEMORY.md`, `memory/YYYY-MM-DD.md`,
`memory_search`, `memory_get`, hybrid search, citations, and a local FastAPI demo.

## Python API

The stable package surface is exported from `memory-core`:

```python
from memory_core import (
    FakeEmbeddingProvider,
    Memory,
    build_memory_flush_plan,
)

memory = Memory.from_workspace(
    embedding_provider=FakeEmbeddingProvider(),
)

results = memory.search("preferred name", max_results=5)
memory_file = memory.get("MEMORY.md", from_line=1, lines=20)
turn = memory.prepare_turn("Bana nasil hitap edeceksin?")
recall_node = memory.langgraph_recall()
flush_plan = build_memory_flush_plan(workspace_dir=memory.workspace.root)
```

`Memory.from_workspace(...)` reads memory files from the host
application workspace, not from this package. For example:

```text
my-agent-app/
  MEMORY.md
  memory/
    2026-05-30.md
  .memory-core/
    main.sqlite
```

By default, `Memory.from_workspace(...)` uses the current working
directory and creates only the memory-core workspace surface when it is missing:
`MEMORY.md`, `memory/`, and `.memory-core/`. It does not create OpenClaw
runtime/persona files such as `AGENTS.md`, `SOUL.md`, or `USER.md`, and it does
not overwrite an existing `MEMORY.md`. Pass `initialize=False` to disable file
creation.

Runtime-adapter helpers such as transcript replay cleanup, history windowing,
runtime-context prompt splitting, and overflow recovery are also exported from
the package root when host applications need OpenClaw-compatible behavior.

Optional capabilities (vector search, MMR, temporal decay) are controlled by
`FeatureFlags`; `FeatureFlags(vector_search=False)` gives a deterministic
FTS-only mode that needs no embedding provider. See
[Feature Flags](docs/feature_flags.md).

See [Package Boundary](docs/package_boundary.md) for what belongs to core
memory, runtime adapters, demo code, and out-of-scope host runtime behavior.
See [LangGraph Integration](docs/integrations/langgraph.md) for a minimal
`state -> memory_context` adapter example.
See [Live SDK Integration](docs/integrations/live.md) for streaming turn
assembly, sentence-level TTS events, subject-scoped memory, and post-session
summary writes.

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

OpenClaw TypeScript oracle tests are skipped unless `OPENCLAW_ORACLE_REPO`
points to an OpenClaw checkout with installed dependencies. The oracle needs
Node.js >= 22.13 (pnpm 11 and OpenClaw both use the `node:sqlite` builtin), and
`pnpm install --ignore-scripts` is enough for the runner. Note the first run
compiles TypeScript on demand; cold-cache runs can hit the 20s per-operation
oracle timeout and report spurious failures, so re-run once warm.

```bash
git clone https://github.com/openclaw/openclaw /tmp/openclaw-upstream
(cd /tmp/openclaw-upstream && pnpm install --ignore-scripts --frozen-lockfile)
OPENCLAW_ORACLE_REPO=/tmp/openclaw-upstream pytest tests/integration -v
```

## Run Demo

```bash
python -m uvicorn demo.app:app --port 8000
```

Open <http://127.0.0.1:8000>. The first screen is an OpenClaw-style chat
memory lab. Enter an OpenAI-compatible API key, send a message, inspect memory
recall, run a manual memory flush, or enable auto flush to write durable
memories while chatting.

The demo uses any OpenAI-compatible engine and defaults to OpenRouter
(`https://openrouter.ai/api/v1`, `openai/gpt-4o-mini`). The browser keeps the
API key in session storage and sends it with each chat/flush request; the
backend does not write it to disk. You can also configure the backend with
environment variables or a gitignored `.env` file in the repo root (loaded at
startup, existing environment values win):

```bash
export MEMORY_CORE_DEMO_OPENAI_BASE_URL="https://openrouter.ai/api/v1"
export MEMORY_CORE_DEMO_OPENAI_API_KEY="sk-or-..."
export MEMORY_CORE_DEMO_OPENAI_MODEL="openai/gpt-4o-mini"
```

OpenRouter does not serve an `/embeddings` endpoint, so the demo falls back to
deterministic local embeddings when the base URL points at OpenRouter. To use
real embeddings, point `MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL` and
`MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY` at an embeddings-capable provider.

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

Run the standalone example from another project directory:

```bash
cd /path/to/my-agent-app
OPENAI_API_KEY=sk-... python -m examples.basic_usage
```

For chatbot integrations, let the package prepare recall-injected messages and
pass them to your LLM client:

```python
turn = memory.prepare_turn("Bana nasil hitap edeceksin?")
response = llm.chat(turn.messages)
```

`prepare_turn()` is adapter ergonomics, not OpenClaw runtime parity. It performs
memory recall and returns ready chat messages; durable write/flush remains a
separate post-turn integration step.

For a managed answer + flush cycle, use `chat()`:

```python
result = memory.chat(
    "Bana Doruk diye hitap et.",
    llm=llm.chat,
    force_flush=True,
)

print(result.assistant_message)
print(result.flush_result.path)
```

This mirrors OpenClaw's memory-flush shape at package level when explicitly
forced: after the answer, the package runs a separate memory-flush prompt and
appends non-`NO_REPLY` output only to the canonical `memory/YYYY-MM-DD.md` file,
then reindexes memory. It is still adapter/runtime glue, not a full OpenClaw
agent runtime.

Run the opt-in live embedding smoke test:

```bash
MEMORY_CORE_LIVE_OPENAI=1 OPENAI_API_KEY=sk-... pytest tests/integration/test_openai_embedding_live.py -q
```
