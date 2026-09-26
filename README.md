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
See [Workspace Layout](docs/workspace_layout.md) for the agent workspace files
(`memory_core.bootstrap`): seeding, the BOOTSTRAP.md lifecycle, and what each turn
injects.

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

## Run the Lab

The Lab is a FastAPI app over the package (`demo/`); it adds no memory logic of
its own. Run it from the repo root:

```bash
.venv/bin/python -m uvicorn demo.app:app --port 8000
```

Open <http://127.0.0.1:8000>. Agent previews use port 8010 (`.claude/launch.json`
entry `memory-core-demo`). The Lab workspace lives in the system temp directory
(`memory-core-lab-workspace`; the live task uses `memory-core-live-task-demo-workspace`),
never in the repo tree.

Configure the chat model with environment variables or a gitignored `.env` in the
repo root (loaded at startup; names already set win). A key can also be sent per
request from the UI; the backend never stores or returns it:

```bash
export MEMORY_CORE_DEMO_OPENAI_BASE_URL="https://openrouter.ai/api/v1"   # default
export MEMORY_CORE_DEMO_OPENAI_API_KEY="<your key>"
export MEMORY_CORE_DEMO_OPENAI_MODEL="openai/gpt-6-luna"                # default (D4)
```

The default model is the newest OpenAI GPT chat model in OpenRouter's public model
list, checked on 2026-09-26 (`demo/chat_engine.py` `DEFAULT_OPENAI_MODEL_SOURCE`).
Without a key the chat fails with `no_api_key`; there is no fake chat model. A
request can ask for the labelled `scripted` engine, which runs the pipeline but
calls no model and no tool.

Embeddings: OpenRouter serves no `/embeddings` endpoint, so by default the Lab
searches FTS-only (`yalnız FTS`) and never builds an embedder. For hybrid search
point `MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL` and
`MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY` (optional `_MODEL`, default
`text-embedding-3-small`) at an embeddings endpoint.

Every chat turn runs a host tool loop: the model gets `memory_search`,
`memory_get` and the curation tools, the flush is decided before the turn like
upstream, and every file change shows up with its source. Endpoints, modes and
what is scripted or real: [docs/lab.md](docs/lab.md).

Smoke test:

```bash
curl -s http://127.0.0.1:8000/api/lab/state
curl -s -N -X POST http://127.0.0.1:8000/api/lab/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message":"Ben teknik cevapları Türkçe tercih ediyorum.","sessionKind":"main"}'
```

## Live OpenAI-Compatible Embeddings

Tests use deterministic fake embeddings; the Lab never does. To add a live
provider flow, configure `OPENAI_API_KEY`, optional `OPENAI_BASE_URL`, and model
`text-embedding-3-small`.

Run the standalone example from another project directory:

```bash
cd /path/to/my-agent-app
OPENAI_API_KEY=<your key> python -m examples.basic_usage
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
MEMORY_CORE_LIVE_OPENAI=1 OPENAI_API_KEY=<your key> pytest tests/integration/test_openai_embedding_live.py -q
```
