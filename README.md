# memory-core

**Give your Python agent a memory that survives the conversation.**

Store preferences, decisions, and working context as readable Markdown.
Retrieve relevant notes with source lines. Bring them into the next session without replaying the entire conversation.

`memory-core` brings selected parts of [OpenClaw](https://github.com/openclaw/openclaw)'s memory system to a standalone Python SDK.
OpenClaw is the technical reference. You keep your model, tools, and agent loop; the SDK supplies the memory layer.

[Quickstart](#quickstart) · [How it works](#how-it-works) · [Integrations](#integrations) · [Try the Lab](#run-the-lab) · [Docs](#documentation)

## Why memory-core?

- **Memory you can inspect.** Notes are Markdown files you can read and edit. SQLite holds the search index.
- **Recall with sources.** Search results include snippets, scores, file paths, and source lines.
- **Start without an API key.** Use local keyword search, then add an embedding provider for hybrid retrieval.
- **Keep your agent architecture.** Call `Memory` directly, or connect memory to your existing tool loop with `HostKit`.

### Why a Python port when OpenClaw already has memory?

OpenClaw already has a TypeScript memory system.
At the reference release, its [memory plugin](https://github.com/openclaw/openclaw/blob/v2026.9.6/extensions/memory-core/index.ts) registers tools through OpenClaw's plugin API and uses runtime services.
A Python application can use that code through a bridge or a separate service.
This SDK offers direct Python memory APIs inside the application you already run.
You keep your existing model calls, workflow, session store, and deployment.

The core requires Python **3.11 or newer** and has one runtime dependency: `httpx`.
It uses Python's `sqlite3` module. Normal SDK use needs no Node.js, running OpenClaw instance, or separate vector database.
Node.js is needed for the upstream oracle tests.

## Quickstart

Clone or download this repository. There is no package index release yet.
From the repository root, install into your Python environment:

```bash
python -m pip install .
```

Save a note, reopen the workspace, and retrieve it.
This example uses local full-text search (FTS), with no model, API key, or embedding provider.

```python
from datetime import datetime, timezone
from pathlib import Path

from memory_core import FeatureFlags, Memory, MemoryConfig

root = Path("agent-memory")
config = MemoryConfig(
    workspace_dir=root,
    flags=FeatureFlags(vector_search=False),
)

# Save a note and index it.
memory = Memory.from_workspace(root, config=config)
path = f"memory/{datetime.now(timezone.utc):%Y-%m-%d}.md"
memory.workspace.append_daily_memory(
    path, "- I prefer technical answers in English."
)
memory.store.reindex(memory.workspace)

# Reopen the same workspace, as you would in another session.
reopened = Memory.from_workspace(root, config=config)
result = reopened.search("technical answers")
print(result["results"][0]["snippet"])
```

The snippet contains the saved preference and a `Source:` line with the note's path and line range.
For a note saved on 9 October 2026, the first run produces:

```text
- I prefer technical answers in English.

Source: memory/2026-10-09.md#L1-L2
```

The files remain in `agent-memory/` after the script exits. Repeated runs append the note again.
This example writes through the workspace API. In an agent, the model can use the write tools you expose.
A chat reply alone does not save a memory.

## How it works

Memory lives outside the model's context window.
Your application retrieves relevant notes and supplies them through prompts and tool results.
Stored notes do not change the model's weights.

| File in the workspace | Purpose |
| --- | --- |
| `MEMORY.md` | Long-term notes |
| `memory/YYYY-MM-DD.md` | Daily notes |
| `.memory-core/main.sqlite` | Search index |

1. **Write.** Save useful facts through the workspace API or agent write tools.
   The daily write tool appends to a dated note. The model chooses whether to use the tools your application offers.
2. **Index.** Split notes into chunks and index them in SQLite.
   Full-text search finds matching words. Hybrid search adds embedding similarity.
   An embedding provider turns text into vectors used for similarity search.
3. **Recall.** `memory_search` returns matching chunks, scores, paths, and source lines.
   For results from memory files, `memory_get` reads the original text. Your host returns the tool result to the model.
4. **Maintain.** Let your host run memory flushes and promotion helpers when needed.
   A flush is a separate model turn that can append useful facts before context fills.
   Promotion helpers use recall signals and score gates to select candidates for `MEMORY.md`.
   Budget helpers can remove older promotion blocks to reduce the file's size.

Reindex after direct writes or manual file edits with `memory.store.reindex(memory.workspace)`.
Reopening through `Memory.from_workspace()` reindexes by default.
Your application owns model calls, session state, workspace access, and maintenance scheduling.
See [Package Boundary](docs/package_boundary.md) for those responsibilities.

### What you can build

- **Resume a project in a new session.** Save project decisions in a stable workspace.
  Let the agent search those decisions and read their sources when work continues.
- **Keep facts across a long task.** Give `HostKit` the model's actual token usage and context limit.
  Run requested flushes so useful facts can survive later context changes.
- **Keep separate memory for streaming subjects.** Use subject workspaces and structured session summaries.
  Reopen the selected subject's memory in a later session. Your host selects the workspace and enforces access.

## Integrations

Start with the interface that fits the application you already have.

| Your application | Use | Example or guide |
| --- | --- | --- |
| A Python service that needs storage and retrieval | `Memory` | [Quickstart](#quickstart) |
| An agent with its own model and tool loop | `HostKit` | [Host loop example](examples/quickstart.py) · [Guide](docs/host_kit.md) |
| A LangGraph workflow | Graph and checkpoint helpers | [LangGraph guide](docs/integrations/langgraph.md) |
| A streaming assistant with separate subjects | Live SDK | [Live SDK guide](docs/integrations/live.md) |

`HostKit` prepares memory prompts and tools, dispatches tool calls, and can request a memory flush.
Your host executes model turns and stores the returned session state.
The model uses the offered recall tools; `before_turn()` does not search automatically.
Replace `call_my_llm` in the host loop example with your model call and tool loop before running it.

<details>
<summary><strong>HostKit lifecycle and integration requirements</strong></summary>

| Stage | API | Host responsibility |
| --- | --- | --- |
| Open | `HostKit.open(...)` | Select the workspace and search mode |
| Prepare | `kit.before_turn(state)` | Send the prompt, message, and tools to the model |
| Dispatch | `kit.dispatcher(turn.session)` | Execute tool calls and return their results to the model |
| Complete | `kit.after_turn(...)` | Deliver the reply first; supply the transcript, token usage, and model context limit |
| Flush | `record.flush` | Run the requested model turn and call `complete()` before the next `after_turn()` |
| New session | `kit.on_new_session(...)` | Supply the transcript and persist the new session state |

- Pass the last model call's provider usage through `TurnUsage`. Persist the returned `SessionState` in your session store.
- Pass `context_window_tokens` to **`kit.after_turn(...)`** with your model's actual limit.
  The default is 200,000 tokens, which can schedule a flush too late for a smaller model.
- A flush request does not itself save facts. If execution fails, pass the exception to `complete(state, error=...)`.
- Curation tools are project-specific extensions governed by `curated_memory_writes` and `CurationPolicy`.
  The feature flag is on by default; the host's policy controls available operations.
- Promotion and dreaming helpers run only when called. The scored deep policy is enabled by default.
  The separate LLM consolidation step is off by default.

See [HostKit](docs/host_kit.md) for error handling and [Workspace Layout](docs/workspace_layout.md) for initialization.

</details>

### Hybrid search

Hybrid search combines keyword matches with embedding similarity.
Configure an embedding provider:

```python
import os
from pathlib import Path

from memory_core import HostKit, OpenAICompatibleEmbeddingProvider

kit = HostKit.open(
    Path("agent-memory"),
    embedding_provider=OpenAICompatibleEmbeddingProvider(
        api_key=os.environ["OPENAI_API_KEY"],
        model="text-embedding-3-small",
    ),
)
```

Set the provider's `base_url` for another OpenAI-compatible embeddings endpoint, or supply your own `EmbeddingProvider`.
For `Memory.from_workspace()` and `HostKit.open()`, hybrid search is the default and requires a provider.
Without one, initialization raises an error. To use local keyword search, explicitly set `FeatureFlags(vector_search=False)`.
See [Feature Flags](docs/feature_flags.md) for search controls.

## Run the Lab

See the memory layer at work in a browser: inspect prompts, search results, saved notes, and session events.
The Lab uses the public SDK APIs. Its chat loop and UI are demo code.

From the repository root, install the development environment and configure an OpenAI-compatible chat provider.
For example, with OpenRouter:

```bash
uv sync --frozen

export MEMORY_CORE_DEMO_OPENAI_BASE_URL="https://openrouter.ai/api/v1"
export MEMORY_CORE_DEMO_OPENAI_API_KEY="<your-api-key>"
export MEMORY_CORE_DEMO_OPENAI_MODEL="<your-chat-model>"

uv run --frozen python -m uvicorn demo.app:app --port 8000
```

Choose a chat model that supports tool calls. The exports override the defaults in `demo/chat_engine.py`.
Open [localhost:8000](http://127.0.0.1:8000). Try this message:

> I prefer technical answers in English. Please remember that.

Inspect memory changes and search results to check whether the model saved the preference.
The model decides whether to call a write tool. A successful reply alone does not prove persistence.

<details>
<summary><strong>HTTP smoke test</strong></summary>

After the server starts with a configured chat key:

```bash
curl -s http://127.0.0.1:8000/api/lab/state
curl -s -N -X POST http://127.0.0.1:8000/api/lab/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"message":"I prefer technical answers in English. Please remember that.","sessionKind":"main"}'
```

Check file changes and retrieval results in the Lab after the request.

</details>

The Lab stores its workspace in the system temp directory. A missing chat key returns `no_api_key`.
An explicit `scripted` request runs without a model, memory tools, or a flush turn.
It does not test model recall or model writes.

The default OpenRouter configuration uses keyword search. The Lab uses no fake embeddings.
For hybrid search, supply a real endpoint through `MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL` and
`MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY`. The embedding model is set with `MEMORY_CORE_DEMO_OPENAI_EMBEDDING_MODEL`.
See [Lab Guide](docs/lab.md) for configuration, scripted modes, and demo privacy limits.

## OpenClaw reference

This project is an unofficial, standalone Python port of selected OpenClaw memory behavior.
The reference release is **OpenClaw `v2026.9.6`**. This project is not affiliated with OpenClaw.
The Python API, host adapters, and dedicated curation tools are this project's own design.

The [oracle runner](scripts/openclaw_oracle_runner.ts) calls real functions from the pinned TypeScript implementation.
[Comparison tests](tests/integration/test_openclaw_ts_oracle.py) give both implementations equivalent inputs and compare observable results.
These tests cover selected operations, not full compatibility or model quality.

The historical v2026.9.6 [Parity Matrix](docs/parity_matrix.md) separates oracle-backed behavior, source-backed ports, and known gaps.
Full REM behavior, some regex/tokenizer cases, and parts of runtime and index compatibility remain incomplete.
Host adapters and Lab behavior are identified separately from upstream parity.

### Current equivalence target

The [full-equivalence checklist](docs/full-equivalence-checklist.md) is the current acceptance plan.
It starts with repository cleanup and fixes the target at OpenClaw **v2026.9.9**, commit
`bcfc88812a35243893585dbeca87ca41b48272ca`, matching the native bridge's release.
Existing v2026.9.6 tests remain regression evidence; their results do not complete the new contract.
Project-specific extensions are identified separately and cannot establish upstream equivalence.

## Documentation

| Guide | What it covers |
| --- | --- |
| [HostKit](docs/host_kit.md) | Prompts, tools, flushes, sessions, and error handling |
| [LangGraph](docs/integrations/langgraph.md) | Graph state, checkpoints, and memory operations |
| [Live SDK](docs/integrations/live.md) | Subject memory, streaming events, and session summaries |
| [Workspace Layout](docs/workspace_layout.md) | Files, initialization, and prompt limits |
| [Feature Flags](docs/feature_flags.md) | Search modes and optional capabilities |
| [Package Boundary](docs/package_boundary.md) | SDK, adapters, demo, and host responsibilities |
| [Lab](docs/lab.md) | Browser demo setup and behavior |
| [Parity Matrix](docs/parity_matrix.md) | Upstream evidence and compatibility limits |
| [Full Equivalence Checklist](docs/full-equivalence-checklist.md) | Cleanup, fixed v2026.9.9 scope, acceptance conditions, and unfinished work |
| [Equivalence Source Map](docs/equivalence-source-map.md) | Pinned upstream/Python entry points, source hashes, and implementation gaps |
| [Release Checklist](docs/release.md) | Clean installs and consumer type checks |

See [CHANGELOG](CHANGELOG.md) for version history.

## Development

From the repository root:

```bash
uv sync --frozen
uv run --frozen pytest -q
uv run --frozen ruff check . --no-cache
uv run --frozen python scripts/check_distribution.py
```

Offline tests use deterministic fake embeddings and scripted test models where needed.
Historical v2026.9.6 oracle regressions require Node.js and `OPENCLAW_ORACLE_REPO` pointing to that checkout with installed dependencies.
Live embedding tests require `MEMORY_CORE_LIVE_OPENAI=1` and provider credentials.
See [Oracle Setup](docs/lab.md#oracle-checkout) for isolated runs.

The rebuilt acceptance suite runs independently of the Lab and its historical oracle:

```bash
git clone --depth 1 --branch v2026.9.9 https://github.com/openclaw/openclaw.git .reference/openclaw
uv run --frozen python -m equivalence.source_map --reference .reference/openclaw
uv run --frozen python scripts/check_equivalence.py --reference .reference/openclaw --node /path/to/node --smoke --report .equivalence-results/subset.json
uv run --frozen python scripts/check_equivalence.py --reference .reference/openclaw --node /path/to/node --report .equivalence-results/full.json
```

Use Node 24.16.0–24.x or 26.1.0 and newer. The registered subset imports real upstream
TypeScript without installing or starting OpenClaw. `--smoke` checks only those registered cases.
The default full command fails while required acceptance points remain uncovered, even when
the subset passes. Missing or modified reference sources, a wrong commit, runner failures,
and behavioral mismatches cannot produce a successful acceptance result.
Push and pull-request CI run the differential subset; manual equivalence workflow runs also
require the full contract. Neither the offline suite nor a green subset proves full equivalence.

The installed package contains `memory_core/` and inline type annotations through `py.typed`.
Clean consumer checks cover selected interfaces; dynamic options and some callbacks still accept `Any`.
The Lab, examples, tests, and scripts remain in the checkout.

For optional dependencies, run `python -m pip install ".[demo]"` for the Lab, or
`python -m pip install ".[langgraph]" langchain-openai` for the LangGraph example.
The `demo` extra installs dependencies, not the Lab application.

<details>
<summary><strong>Real embedding example</strong></summary>

[examples/basic_usage.py](examples/basic_usage.py) uses a real embedding provider and writes files in the working directory.
Run it from a scratch directory. Set the absolute checkout path in `PYTHONPATH`:

```bash
cd "$(mktemp -d)"
OPENAI_API_KEY="<your-api-key>" PYTHONPATH=/path/to/memory-core python -m examples.basic_usage
```

The example also accepts `OPENAI_BASE_URL` and `OPENAI_EMBEDDING_MODEL`.
The default embedding model is `text-embedding-3-small`.

</details>

<details>
<summary><strong>Project rename utility</strong></summary>

The project name is declared in `pyproject.toml`.
The script updates package names, metadata, environment prefixes, and tracked text from that declaration.
Start from a clean checkout, review the diff, and commit it:

```bash
.venv/bin/python scripts/rename_project.py --to <dist-name> [--display <text>]
.venv/bin/python scripts/rename_project.py --check
```

The rename preserves locked dependencies and protected OpenClaw names. It needs no resolver cache or network access.
It does not migrate existing workspaces or promotion markers. Read the script's help before renaming a project with saved memory.

</details>

## License

Ported code retains the upstream MIT notice in [LICENSE.openclaw](LICENSE.openclaw).
Both wheel and source distributions include that notice.
This project's own MIT notice and metadata await confirmation of the copyright holder and year.
