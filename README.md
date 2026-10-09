# memory-core

**OpenClaw memory behavior for Python agent applications.**

[Why this exists](#why-a-python-port) · [How it works](#how-memory-works) · [Quickstart](#quickstart) · [Try the Lab](#run-the-lab) · [Docs](#read-the-docs)

[OpenClaw](https://github.com/openclaw/openclaw) already has a memory system written in TypeScript.
This project ports selected parts of that system into a standalone Python SDK.
Use it to add OpenClaw-style memory to an agent application whose model calls, tools, and workflow you already control.

OpenClaw is the technical reference for this project.
The port includes memory storage, retrieval, write tools, and memory maintenance helpers.
Its Python API and host adapters are this project's own design.

## Why a Python port?

At the pinned OpenClaw release, `extensions/memory-core` is an OpenClaw plugin.
Its [entry point](https://github.com/openclaw/openclaw/blob/v2026.9.6/extensions/memory-core/index.ts)
registers tools through the OpenClaw plugin API and uses services from that runtime.

A Python application can use TypeScript through a bridge or a separate service.
This project offers another integration path: call the memory APIs directly inside your Python application.
You can keep your existing agent loop, model provider, application tools, and session store.
The core package needs Python, SQLite, and `httpx`.
Normal Python memory calls do not require Node.js or a running OpenClaw instance.
Node.js is required for the upstream oracle tests.

| You already have | What this package adds |
| --- | --- |
| A Python agent or service | `Memory` for local files, indexing, and retrieval |
| Your own model and tool loop | `HostKit` for memory prompts, tool dispatch, and flush requests |
| A LangGraph workflow | Helpers that connect graph state and checkpoints to the same memory APIs |
| A streaming application | A live SDK for subject memory, events, and session summaries |

Your application still runs the model, stores session state, and schedules maintenance.
The package supplies memory mechanisms that those parts can call.
See [Package Boundary](docs/package_boundary.md) for the division of responsibilities.

## How memory works

A model's context window holds the information available for one model call.
Persistent memory stores useful information outside that window.
A later session can search and read that information instead of sending the entire old conversation to the model.

1. **Store readable notes.** A workspace holds `MEMORY.md` for long-term notes and `memory/YYYY-MM-DD.md` for daily notes.
   These Markdown files are the saved memory. You can open and inspect them.
2. **Build an index.** The SDK splits notes into chunks and builds a SQLite search index.
   Full-text search finds matching words. Hybrid search combines text results with vectors from an embedding provider.
   The provider turns text into vectors used for similarity search.
3. **Retrieve sources.** `memory_search` returns matching chunks, scores, file paths, and source lines.
   For results from memory files, `memory_get` reads the original text.
   Your application sends these tool results back to the model.
4. **Save useful facts.** The model chooses whether to use the write tools that your application provides.
   The daily write tool appends to a dated note. Curation tools can edit long-term notes under a host-supplied policy.
   These curation tools are a documented memory-core extension, rather than ports of OpenClaw tools.
5. **Preserve facts before context fills.** After a reply, your host supplies token usage and the model's context limit to `HostKit`.
   The kit can request a memory flush: a separate model turn with an append-only daily write tool.
   Your host runs that turn and records its result. A request alone does not save the facts.
6. **Maintain long-term memory.** Promotion helpers use recall signals and score gates to select candidates for `MEMORY.md`.
   Budget helpers can remove older promotion blocks to reduce the file's size.
   Your host chooses when to run these helpers.

Memory does not change the model's weights. It gives the model stored information through prompts and tool results.
The [Quickstart](#quickstart) below shows a file write, a new memory instance, and a search without a model call.
The [complete host loop](examples/quickstart.py) shows where a model and its tool calls fit into that process.

## What you can build

| Application | How the memory layer supports it |
| --- | --- |
| A project assistant that resumes work in a new session | Keep a stable project workspace. Save decisions in notes, then retrieve them with source lines in later sessions. |
| A long-running Python workflow | Connect `HostKit` to your tool loop. Supply actual token usage and run requested flushes before useful facts leave the context window. |
| A LangGraph agent with memory across graph runs | Store session state in checkpoints and call the memory helpers from graph nodes. Durable notes stay in the workspace. |
| A streaming assistant with memory for separate subjects | Use subject workspaces and structured session summaries. Reopen the selected subject's memory for a later session. |

The host selects each workspace and enforces access to it.
The [HostKit guide](docs/host_kit.md), [LangGraph guide](docs/integrations/langgraph.md), and
[live SDK guide](docs/integrations/live.md) explain those integrations.
The Lab shows memory prompts, search results, saved notes, and session events in a browser.

## OpenClaw reference and oracle tests

The reference release is **OpenClaw `v2026.9.6`**.
An oracle test uses the upstream implementation as the reference result.
Our [TypeScript runner](scripts/openclaw_oracle_runner.ts) calls real OpenClaw functions from that pinned checkout.
The [comparison tests](tests/integration/test_openclaw_ts_oracle.py) give the Python and TypeScript implementations equivalent inputs and compare their observable results.

These tests cover selected operations. They do not establish complete OpenClaw compatibility.
The [parity matrix](docs/parity_matrix.md) separates oracle-backed behavior, source-backed ports, and known gaps.
Host adapters and Lab behavior are identified separately from upstream parity.
This project is unofficial and is not affiliated with OpenClaw.

### Future direction is open

We have not yet decided whether future development will remain strictly aligned with OpenClaw or add independently designed memory capabilities.
OpenClaw is the current technical reference and the baseline for the oracle tests.
Existing project-specific APIs and extensions are identified in the documentation.

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
