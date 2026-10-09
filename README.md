# memory-core

**Memory for Python agents. Across sessions. In files you can read.**

[Install](#install) · [Quickstart](#quickstart) · [Connect your agent](#python-api) · [Try the Lab](#run-the-lab) · [Docs](#read-the-docs)

New session. Same questions. Again?

- **Tired of repeating “I prefer technical answers in English”?** Save the preference for the next session.
- **Want your agent to keep yesterday’s project decisions?** Store the useful facts and search them when needed.
- **Need to see where an answer came from?** Get the saved note, its file path, and its source lines.

If you need this in a Python agent application, use `memory-core` as its memory layer.
You build the agent. The package supplies memory files, search tools, and memory maintenance helpers.

## What it does

`memory-core` is a Python SDK for persistent agent memory.
It stores notes in Markdown files and builds a SQLite search index.
Your agent can search saved facts, read their sources, and write useful information through the tools you allow.

| Need | Package support |
| --- | --- |
| Keep facts between sessions | Daily notes, long-term notes, and session snapshots |
| Find a saved fact | `memory_search` with keyword or hybrid search and source lines |
| Read the original note | `memory_get` with file and line selection |
| Save facts before the context window fills | Flush planning and an append-only daily write tool |
| Keep important notes within a size budget | Scored promotion and memory budget helpers |
| Connect an existing Python agent | `HostKit`, LangGraph helpers, and a streaming SDK |

Your application runs the model, answers tool calls, stores session state, and schedules maintenance.
`HostKit` prepares the memory prompt and tools. It also returns requests for a memory flush.
A flush is a separate model turn that saves useful facts before the context window fills.

The memory algorithms are an independent Python port of [OpenClaw](https://github.com/openclaw/openclaw)'s
`extensions/memory-core` plugin. This project is unofficial and is not affiliated with OpenClaw.
Tests compare supported functions with the real TypeScript code at release `v2026.9.6`.
The [parity matrix](docs/parity_matrix.md) lists verified behavior and known gaps.

## Install

Use Python **3.11 or newer**. Install from a checkout; there is no package index release yet.

```bash
# Core SDK. Its only runtime dependency is httpx.
pip install /path/to/memory-core

# Optional Lab dependencies.
pip install "/path/to/memory-core[demo]"

# Optional LangGraph stack and the example's model integration.
pip install "/path/to/memory-core[langgraph]" langchain-openai
```

The installed package contains `memory_core/`.
The Lab, examples, tests, and scripts stay in the checkout.
The `demo` extra adds dependencies; it does not install the Lab application.

For development, run this command from the repo root:

```bash
uv sync --frozen
```

This installs the editable package and the development tools from `uv.lock`.
See the [release checklist](docs/release.md) for clean install and consumer type checks.

## Quickstart

Save a note. Open the same workspace again. Search the saved note.
This example uses local full-text search (FTS). It needs no model, API key, or embedding provider.

```python
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from memory_core import FeatureFlags, Memory, MemoryConfig

with TemporaryDirectory() as folder:
    root = Path(folder)
    config = MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(root, config=config)
    path = f"memory/{datetime.now(timezone.utc):%Y-%m-%d}.md"
    memory.workspace.append_daily_memory(path, "- I prefer technical answers in English.")
    memory.store.reindex(memory.workspace)

    # A new instance reads the saved files.
    reopened = Memory.from_workspace(root, config=config)
    result = reopened.search("technical answers")
    print(result["results"][0]["snippet"])
```

The result contains the preference and a `Source:` line with the note's path and line range.
For example, a note saved on 9 October 2026 produces this output:

```text
- I prefer technical answers in English.

Source: memory/2026-10-09.md#L1-L2
```

This example writes the note directly through the workspace API.
In an agent, the model uses the write tools that your application offers.
The temporary workspace is removed when the example ends. Use a permanent path in your application.

### Hybrid search

The package default combines vector search with keyword search.
An embedding provider converts text to vectors for that search.
The default configuration requires a provider. It raises an error if you omit one.
Use `FeatureFlags(vector_search=False)` to select FTS-only search explicitly.

For hybrid search, configure `OpenAICompatibleEmbeddingProvider` or another `EmbeddingProvider`:

```python
import os
from pathlib import Path

from memory_core import HostKit, OpenAICompatibleEmbeddingProvider

root = Path("my-agent-app")
kit = HostKit.open(
    root,
    embedding_provider=OpenAICompatibleEmbeddingProvider(
        api_key=os.environ["OPENAI_API_KEY"], model="text-embedding-3-small"
    ),
)
```

This configuration uses a real embeddings endpoint.
Set the provider's `base_url` if your endpoint differs from its OpenAI default.
For search controls, see [Feature Flags](docs/feature_flags.md).

## Python API

Use `Memory` for file storage and search. Use `HostKit` to connect those functions to an agent loop.

| Step | HostKit call | Your application does this |
| --- | --- | --- |
| Open a workspace | `HostKit.open(...)` | Select the path and search mode |
| Prepare a turn | `kit.before_turn(state)` | Send the prompt, current message, and memory tools to the model |
| Answer a tool call | `kit.dispatcher(turn.session)` | Run the requested tool and send its result back to the model |
| Complete a turn | `kit.after_turn(...)` | Deliver the reply first; pass the transcript, actual token usage, and model window size |
| Run a requested flush | `record.flush` | Run its model turn and call `complete()` before the next `after_turn()` |
| Start another session | `kit.on_new_session(...)` | Supply the transcript and store the new session state |
| Run maintenance | `kit.heartbeat_prompt(...)` and consolidation helpers | Choose when to run them |

The [complete host loop](examples/quickstart.py) shows prompt assembly, tool dispatch, and flush execution.
Replace its `call_my_llm` function with your model call and tool loop before you run it.
The [HostKit guide](docs/host_kit.md) covers error handling, session state, and runtime context.

Pass your model's actual window size as `context_window_tokens` to `kit.after_turn`.
The default is 200,000 tokens. Its flush threshold can exceed a smaller model's window.
Keep `SessionState` in your session store. Pass provider token usage through `TurnUsage`.
If a flush fails, pass the exception to `complete(state, error=...)`.

The curation tools can edit long-term notes, user preferences, and daily notes.
They are a memory-core extension, controlled by `curated_memory_writes` and `CurationPolicy`.
Promotion and dreaming helpers run only when your host calls them.
The scored deep policy is enabled by default. The separate LLM consolidation step is off by default.

A workspace can contain:

```text
my-agent-app/
  MEMORY.md                 # Long-term notes
  memory/
    YYYY-MM-DD.md           # Daily notes
  .memory-core/
    main.sqlite             # Search index
```

`Memory.from_workspace()` creates only this memory surface when it is missing.
It preserves existing notes. Pass `initialize=False` to skip memory-file initialization.
`HostKit.open()` also seeds the selected agent file layout; files are empty unless you supply templates.
See [Workspace Layout](docs/workspace_layout.md) for bootstrap files and prompt limits.

## Run the Lab

The Lab shows prompts, search results, memory changes, and session events in a browser.
It uses the public package APIs. Its chat loop and UI are demo code.
Run it from a checkout after `uv sync --frozen`.
Set the chat endpoint, API key, and model before you start the server.
Use environment variables or a gitignored `.env`:

```bash
export MEMORY_CORE_DEMO_OPENAI_BASE_URL="https://openrouter.ai/api/v1"
export MEMORY_CORE_DEMO_OPENAI_API_KEY="<your key>"
export MEMORY_CORE_DEMO_OPENAI_MODEL="openai/gpt-6-luna"
```

These endpoint and model values are the current defaults in `demo/chat_engine.py`.
Use the model and endpoint that you select. A missing key returns `no_api_key`.

Start the server:

```bash
uv run --frozen python -m uvicorn demo.app:app --port 8000
```

Open [localhost:8000](http://127.0.0.1:8000).
The Lab stores its workspace in the system temp directory.

An explicit `scripted` request runs the demo pipeline without a model, memory tools, or a flush turn.
It does not test model recall or model writes.

With a configured chat key, run this smoke test:

```bash
curl -s http://127.0.0.1:8000/api/lab/state
curl -s -N -X POST http://127.0.0.1:8000/api/lab/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message":"I prefer technical answers in English.","sessionKind":"main"}'
```

The model decides whether to call a write tool. A successful reply alone does not prove that a note was saved.
Check the file changes and search results in the Lab.

The default OpenRouter configuration uses FTS-only search.
For hybrid search, set `MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL` and
`MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY` to a real embeddings endpoint.
The Lab uses no fake embeddings.
See [Lab Guide](docs/lab.md) for endpoints, scripted modes, privacy limits, and demo behavior.

## Read the docs

| Guide | Use it for |
| --- | --- |
| [HostKit](docs/host_kit.md) | Prompts, tools, flushes, session state, and error handling |
| [LangGraph Integration](docs/integrations/langgraph.md) | A graph with session checkpoints and explicit memory operations |
| [Live SDK Integration](docs/integrations/live.md) | Streaming events, subject memory, and session summaries |
| [Feature Flags](docs/feature_flags.md) | Search modes and optional capabilities |
| [Package Boundary](docs/package_boundary.md) | Core, adapters, demo, and host responsibilities |
| [Parity Matrix](docs/parity_matrix.md) | Oracle evidence and known differences from OpenClaw |

The package includes `py.typed` for its inline annotations.
Clean install checks cover selected public interfaces. Dynamic options and some callbacks still accept `Any`.
Full REM behavior, some regex/tokenizer cases, and parts of runtime and index compatibility remain incomplete.
See the parity matrix for each boundary. See [CHANGELOG](CHANGELOG.md) for version history.

## Run Tests

Run these commands from the checkout's development environment:

```bash
uv run --frozen pytest -q
uv run --frozen ruff check . --no-cache
uv run --frozen python scripts/check_distribution.py
```

Offline tests use deterministic fake embeddings and scripted test models where needed.
Oracle tests require `OPENCLAW_ORACLE_REPO`. It must point to the pinned OpenClaw checkout with installed dependencies.
Live embedding tests require `MEMORY_CORE_LIVE_OPENAI=1` and provider credentials.
See [Oracle Setup](docs/lab.md#oracle-checkout) and the [release checklist](docs/release.md) for isolated runs.

## Live OpenAI-Compatible Embeddings

[examples/basic_usage.py](examples/basic_usage.py) uses a real embedding provider.
It writes memory files in the working directory. Run it from a scratch directory:

```bash
cd "$(mktemp -d)"
OPENAI_API_KEY="<your key>" PYTHONPATH=/path/to/memory-core python -m examples.basic_usage
```

The example accepts `OPENAI_BASE_URL` and `OPENAI_EMBEDDING_MODEL` as optional settings.
Use a real embeddings endpoint. The default model is `text-embedding-3-small`.

## Rename the Project

The project name is declared in `pyproject.toml`.
The rename script updates the package, metadata, environment prefix, and tracked text from that declaration.
Start from a clean checkout, then review and commit the diff:

```bash
.venv/bin/python scripts/rename_project.py --to <dist-name> [--display <text>]
.venv/bin/python scripts/rename_project.py --check
```

A rename preserves locked dependencies and protected OpenClaw names.
It needs no resolver cache or network access. It does not migrate existing workspaces or promotion markers.
See the script's help before you rename a project that already has saved memory.

## License

The project's own MIT notice and metadata await the confirmed copyright holder and year.
Ported code retains the upstream MIT notice in [LICENSE.openclaw](LICENSE.openclaw).
Both the wheel and the source distribution include that notice.
