# memory-core

`memory-core` is an unofficial, independent Python port of the memory behaviour of
OpenClaw memory-core, the memory plugin of [OpenClaw](https://github.com/openclaw/openclaw)
(`extensions/memory-core` in its repository). It is not affiliated with the OpenClaw project.
Here "memory-core" on its own means this port; OpenClaw's plugin is written
"OpenClaw memory-core" or by its path.

For LLM agents it provides Markdown memory files (`MEMORY.md`, `memory/YYYY-MM-DD.md`), the
`memory_search` and `memory_get` tools over a SQLite index with hybrid search and citations,
the memory flush, the `/new` session hook, the heartbeat turn and scored promotion, composed
for any agent host by the host kit (`memory_core.host`). An oracle suite runs the upstream
TypeScript functions and tracks the port against OpenClaw release tag `v2026.9.6`; the
[parity matrix](docs/parity_matrix.md) gives each area's status.

## Install

Python 3.11 or newer. From a checkout (nothing is published to a package index yet):

```bash
pip install /path/to/memory-core            # the package; its only dependency is httpx
pip install "/path/to/memory-core[demo]"    # adds FastAPI, Jinja2 and uvicorn for the Lab
pip install "/path/to/memory-core[langgraph]" langchain-openai  # LangGraph, for its example
```

The Lab (`demo/`), the tests, the scripts and the examples stay in the checkout; the
package holds only `memory_core/`. For development, create the checkout's environment with
[uv](https://docs.astral.sh/uv/) (an editable install with the demo and langgraph extras,
plus langchain-openai, pytest and ruff from the `dev` dependency group, which is not part of
the package's metadata):

```bash
uv sync
```

[CHANGELOG.md](CHANGELOG.md) lists what changed in each version.

Licence: memory-core's own licence is not decided yet. Code ported from OpenClaw keeps
upstream's MIT notice in [LICENSE.openclaw](LICENSE.openclaw), which the wheel and the
sdist carry.

## Quickstart

The host kit (`memory_core.host`) gives every turn of an agent its memory, in any host: a chat
app, a channel bot, a voice agent. It seeds the workspace, builds the system prompt, offers
the memory tools and answers their calls, and after the reply decides the memory flush. The
host keeps the model call, the tool loop and session storage.
[examples/quickstart.py](examples/quickstart.py) is a whole host loop as a terminal chat;
replace `call_my_llm` with your model call:

```python
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from memory_core import FeatureFlags, HostKit, MemoryConfig, SessionState, TurnUsage


def call_my_llm(
    messages: Sequence[dict[str, str]],
    tools: Sequence[dict[str, Any]],
    run_tool: Callable[[str, Any], dict[str, Any]],
) -> tuple[str, TurnUsage]:
    """Your model call and its tool loop.

    Send ``messages`` and offer ``tools`` (``{"name", "description", "parameters"}`` specs, to
    wrap in your provider's format). Answer each tool call with ``run_tool(name, arguments)``,
    the arguments as JSON text or a dict, and send the payload back until the model replies.
    Return the reply text and the last call's token usage as the provider reports it.
    """
    raise NotImplementedError("replace call_my_llm with your model call")


def main() -> None:
    root = Path("my-agent-app")
    # FTS-only search; pass embedding_provider= instead of config= for hybrid search.
    kit = HostKit.open(
        root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    )
    state = SessionState.new(session_key="agent:main:main", session_id=str(uuid.uuid4()))
    history: list[dict[str, str]] = []
    while text := input("> "):
        turn = kit.before_turn(state)
        history.append({"role": "user", "content": text})
        reply, usage = call_my_llm(
            [{"role": "system", "content": turn.system_prompt}, *history],
            turn.tools,
            kit.dispatcher(turn.session),
        )
        print(reply)  # deliver the reply; the memory flush runs after it
        history.append({"role": "assistant", "content": reply})
        record = kit.after_turn(turn.session, transcript=history, usage=usage)
        state = record.session
        if record.flush is not None:  # the flush run's own reply is never shown
            call_my_llm(record.flush.messages, record.flush.tools, record.flush.dispatch)
            state = record.flush.complete(state).session


if __name__ == "__main__":
    main()
```

- `HostKit.open` creates `my-agent-app/` with the layout's workspace files (`AGENTS.md`,
  `SOUL.md`, `USER.md` and the rest, empty unless you pass `templates=`) and indexes the
  memory files in `.memory-core/main.sqlite`. The default config searches hybrid and refuses to
  open without an embedder; the example opts into FTS-only search. Hybrid search takes an
  `OpenAICompatibleEmbeddingProvider` or any other `EmbeddingProvider`:

  ```python
  import os

  from memory_core import OpenAICompatibleEmbeddingProvider

  kit = HostKit.open(
      root,
      embedding_provider=OpenAICompatibleEmbeddingProvider(
          api_key=os.environ["OPENAI_API_KEY"], model="text-embedding-3-small"
      ),
  )
  ```

- `kit.before_turn(state, runtime_context=text)` also wraps the host's per-turn context
  (channel, sender) in the runtime-context markers as `turn.runtime_context`, the dynamic
  part to send after the stable `turn.system_prompt`.
- The model recalls through `memory_search` and `memory_get`. The curation tools, a memory-core
  extension (flag `curated_memory_writes`, [Feature Flags](docs/feature_flags.md)), let it
  edit `MEMORY.md`, `USER.md`, `PROACTIVE_PREFERENCES.md` and today's daily note.
  `kit.dispatcher(turn.session)` answers each tool call with the payload to send back,
  errors included (`kit.dispatch(name, arguments, session=...)` is the same call unbound).
- `after_turn` stores the provider's token usage in the session and returns a `FlushRequest`
  when the session nears the model's context window (`context_window_tokens=`, default
  upstream's 200,000). Upstream runs the flush after the reply is delivered and never shows
  its reply. A host may run it later, off the reply path, as long as `complete()` comes
  before the session's next `after_turn`; a failed run passes its exception as
  `complete(state, error=...)`.
- Keep `state` with your session record (`SessionState.to_json()`, `from_json()`). `/new`
  and `/reset` go through `kit.on_new_session`, the scheduled heartbeat turn through
  `kit.heartbeat_prompt`. The full contract and the upstream sites it follows:
  [docs/host_kit.md](docs/host_kit.md).
- For LangGraph, [examples/langgraph_agent.py](examples/langgraph_agent.py) is this loop as a
  `StateGraph` with a checkpointer, one thread per session
  ([LangGraph Integration](docs/integrations/langgraph.md)).

## Python API

The package root exports what a host needs (the host kit, `Memory`, its configuration,
the embedding providers, the workspace layouts and the errors a host handles); every
other helper imports from its submodule ([CHANGELOG.md](CHANGELOG.md) lists where each
name moved in 0.2.0):

```python
from pathlib import Path

from memory_core import FeatureFlags, Memory, MemoryConfig
from memory_core.memory_flush import build_memory_flush_plan

root = Path(".")
memory = Memory.from_workspace(  # FTS-only; pass embedding_provider= for hybrid search
    root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
)

results = memory.search("preferred name", max_results=5)
memory_file = memory.get("MEMORY.md", from_line=1, lines=20)
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

Runtime-adapter helpers such as transcript replay cleanup (`memory_core.replay_history`,
`memory_core.replay_repair`), history windowing (`memory_core.history`), runtime-context prompt
splitting (`memory_core.runtime_context_prompt`) and overflow recovery
(`memory_core.overflow_recovery`, `memory_core.preemptive_compaction`) import from their modules
when host applications need OpenClaw-compatible behavior.

Heartbeat and automation follow the v2026.9.6 shape: the host keeps each agent's
heartbeat monitor scratch and its recurring automation jobs (`FileAutomationStore`
is a file-backed default) and owns the scheduler; memory-core builds the heartbeat
turn and reads its reply:

```python
from memory_core.automation import (
    FileAutomationStore,
    due_automation_jobs,
    heartbeat_scheduled_tasks,
    record_automation_job_run,
)
from memory_core.heartbeat import decide_heartbeat_reply, prepare_heartbeat_turn

store = FileAutomationStore(workspace_root)
due = due_automation_jobs(store.list_jobs(agent_id="main"), now_ms)
turn = prepare_heartbeat_turn(
    now_ms=now_ms,
    scratch=store.read_scratch("main"),
    scheduled_tasks=heartbeat_scheduled_tasks(due),
    time_format="24",  # the host's 12/24-hour format; pass the same value to the flush plan
)
if turn.skip_reason is None:
    decision = decide_heartbeat_reply(run_model(turn.message))  # host model call
    if decision.deliver:
        deliver(decision.text)  # host delivery
# Only heartbeat-task jobs go into the turn; record those. Other due jobs are the host's to run.
in_turn = {task.job_id for task in turn.scheduled_tasks}
store.save_jobs(
    [record_automation_job_run(job, started_at_ms=now_ms) for job in due if job.id in in_turn]
)
```

`memory_core.heartbeat_migration` moves a leftover HEARTBEAT.md into the scratch and its
`tasks:` block into automation jobs (the doctor migrations).

Every `Current time:` prompt line (the heartbeat turn, the memory flush plan, the bare
`/new` / `/reset` prompt) comes from `memory_core.current_time` and takes the host's
`time_format` (`"12"` or `"24"`, default `"24"`). Upstream detects the host OS setting
instead; memory-core leaves that to the host.

Optional capabilities (vector search, MMR, temporal decay) are controlled by
`FeatureFlags`; `FeatureFlags(vector_search=False)` gives a deterministic
FTS-only mode that needs no embedding provider. See
[Feature Flags](docs/feature_flags.md).

See [Package Boundary](docs/package_boundary.md) for what belongs to core
memory, runtime adapters, demo code, and out-of-scope host runtime behavior.
See [LangGraph Integration](docs/integrations/langgraph.md) for the LangGraph agent over the
host kit (`examples/langgraph_agent.py`, the `memory_core.adapters.langgraph` helpers) and
what the kit's API lacked for it.
See [Live SDK Integration](docs/integrations/live.md) for streaming turn
assembly, sentence-level TTS events, subject-scoped memory, and post-session
summary writes.
See [Workspace Layout](docs/workspace_layout.md) for the agent workspace files
(`memory_core.bootstrap`): seeding, the BOOTSTRAP.md lifecycle, and what each turn
injects.

## Run Tests

In the environment from `uv sync`:

```bash
uv run pytest -q
uv run ruff check .
```

OpenClaw TypeScript oracle tests are skipped unless `OPENCLAW_ORACLE_REPO`
points to an OpenClaw checkout with installed dependencies. The runner supports
only the parity pin, release tag `v2026.9.6` (`memory_core/parity/upstream.py`); the
Lab's parity view defaults to a checkout at `/tmp/openclaw-head`. The tag needs
Node `>=24.16.0 <25` or `>=26.1.0` (its `package.json` `engines`; Node 25 is
refused for SQLite state). `OPENCLAW_ORACLE_NODE` names the node binary the
oracle runs with (default: the first `node` on `PATH`; it must be a binary or
symlink named `node`), and the oracle client fails fast with
`oracle-node-unsupported` when that Node is outside the range.
`pnpm install --ignore-scripts` is enough for the runner. The first run compiles
TypeScript on demand; cold-cache runs can hit the per-operation oracle timeout, so
re-run once warm. Setup details: [docs/lab.md › Oracle checkout](docs/lab.md).

```bash
git clone https://github.com/openclaw/openclaw /tmp/openclaw-head
git -C /tmp/openclaw-head checkout v2026.9.6
# <node-dir>: a directory whose `node` is Node >=24.16 <25 or >=26.1.
export OPENCLAW_ORACLE_NODE=<node-dir>/node
(cd /tmp/openclaw-head && PATH=<node-dir>:$PATH \
  npx --yes pnpm@12.4.0 install --ignore-scripts --frozen-lockfile)
OPENCLAW_ORACLE_REPO=/tmp/openclaw-head uv run pytest tests/integration -v
```

## Rename the Project

`pyproject.toml` declares the name once: `[project] name` (the distribution name) and
`display-name` in `[tool.memory_core]`. `memory_core/project_name.py` repeats the two values for the
installed package and derives the other forms (the package, the `MEMORY_CORE_` environment prefix,
the `.memory-core/` state directory, the Lab title); runtime code never spells the name itself.
One command renames the project; review the diff and commit it:

```bash
.venv/bin/python scripts/rename_project.py --to <dist-name> [--display <text>]
.venv/bin/python scripts/rename_project.py --check
```

`--to` refuses uncommitted changes and untracked files (a failed rename is then undone with
git), moves the package directory with `git mv`, rewrites every spelling of the name in the
tracked files, relocks `uv.lock` and runs `--check` before and after (a test runs it too).
Spellings that name OpenClaw memory-core (its paths, the plugin config key and the identifiers
and prose the script's `PROTECTED` lists) stay as they are, and a rename to a name the tree
already spells elsewhere is refused. A rename does not migrate existing workspaces: their state
directory and promotion markers keep the old name.

## Run the Lab

The Lab is a FastAPI app over the package (`demo/`); it adds no memory logic of
its own. It needs the demo extra (included in `uv sync`). Run it from the
repo root:

```bash
.venv/bin/python -m uvicorn demo.app:app --port 8000
```

Open <http://127.0.0.1:8000>. Agent previews use port 8010. The Lab workspace lives in
the system temp directory (`memory-core-lab-workspace`; the live task uses
`memory-core-live-task-demo-workspace`), never in the repo tree.

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

Every chat turn runs a host tool loop over the host kit (`memory_core.host`): the model
gets `memory_search`, `memory_get` and the curation tools, the flush is decided and
run after the reply like upstream's session maintenance, and every file change shows
up with its source. Endpoints, modes and
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

The example writes `MEMORY.md` and `memory/` into the working directory, so run it
from a scratch directory with the checkout on `PYTHONPATH` (`examples/` is not part of
the package):

```bash
cd "$(mktemp -d)"
OPENAI_API_KEY=<your key> PYTHONPATH=/path/to/memory-core python -m examples.basic_usage
```

Run the opt-in live embedding smoke test:

```bash
MEMORY_CORE_LIVE_OPENAI=1 OPENAI_API_KEY=<your key> uv run pytest tests/integration/test_openai_embedding_live.py -q
```
