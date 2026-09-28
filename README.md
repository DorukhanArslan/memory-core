# memory-core

`memory-core` is a Python memory core for LLM agents. It tracks OpenClaw
memory-core behavior against upstream commit
`7f6798094ce9486a8f463772f4535484aca73fe2`.

The first implementation slice covers `MEMORY.md`, `memory/YYYY-MM-DD.md`,
`memory_search`, `memory_get`, hybrid search, citations, and a local FastAPI demo.

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
recall_node = memory.langgraph_recall()
flush_plan = build_memory_flush_plan(workspace_dir=memory.workspace.root)
```

## Host kit

`memory_core.host` composes the memory behaviour of one agent turn for any host (a chat
app, a channel bot, a voice agent): the workspace ensure, the injected context, the
memory tools and their dispatch, the post-reply memory flush, the `/new` hook and the
heartbeat turn. The host keeps the model call, the tool loop and session storage; the
kit returns what to send and takes back what came out (docs/host_kit.md).

```python
from pathlib import Path

from memory_core import FeatureFlags, MemoryConfig
from memory_core.host import HostKit, SessionState, TurnUsage

root = Path("my-agent-app")
kit = HostKit.open(  # FTS-only; pass embedding_provider= for hybrid search
    root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
)
state = SessionState.new(session_key="agent:main:main", session_id="s1")

turn = kit.before_turn(state)
# Your model call: turn.system_prompt, turn.runtime_context, the history and the user
# message, offering turn.tools; answer each tool call with
# kit.dispatch(name, arguments, session=turn.session).
record = kit.after_turn(turn.session, transcript=history, usage=TurnUsage(prompt_tokens))
state = record.session
if record.flush:  # later, off the reply path
    # Run record.flush.messages with record.flush.tools; answer its write calls with
    # record.flush.dispatch(name, arguments).
    state = record.flush.complete(state).session
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
OPENCLAW_ORACLE_REPO=/tmp/openclaw-head pytest tests/integration -v
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

Run the standalone example from another project directory:

```bash
cd /path/to/my-agent-app
OPENAI_API_KEY=<your key> python -m examples.basic_usage
```

Run the opt-in live embedding smoke test:

```bash
MEMORY_CORE_LIVE_OPENAI=1 OPENAI_API_KEY=<your key> pytest tests/integration/test_openai_embedding_live.py -q
```
