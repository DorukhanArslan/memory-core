# LangGraph Integration

## Design (2026-09-29)

Status: specification and TDD plan, written 2026-09-29 on `feat/langgraph-agent` (from `main`
`79a1b5c`). Nothing below is implemented yet. The host kit contract is docs/host_kit.md; this
design adds no kit behaviour. Library facts were read from the installed sources of langgraph
1.2.12 (with langgraph-checkpoint 4.2.0 and langgraph-prebuilt 1.1.0), langchain-core 1.6.5 and
langchain-openai 1.6.6; the ones marked "probe" were run against those versions. Library
citations are `<package>/<path>:<line>` in them; upstream anchors are OpenClaw v2026.9.6
(`/tmp/openclaw-head`). The sections after this design describe the legacy
`LangGraphMemoryRecall`; Task 4 removes them and Task 8 rewrites this file for the host-kit path.

### Goal

A LangGraph agent (a `StateGraph` with a checkpointer) whose memory runs entirely through
`memory_core.host.HostKit`: `before_turn` gives the system prompt and the tools, the model node
calls the host's chat model bound to those tools, a tools node answers every tool call with
`kit.dispatch`, a maintenance node calls `after_turn` after the reply and runs the flush turn of a
returned `FlushRequest` on the same model, and `/new` and `/reset` go through `on_new_session`.
It tests whether the kit's API is enough for a real framework host: whatever the graph needs
beyond the kit is adapter code (below) or a finding.

Labels: the graph and the adapter are adapter-only. The orders and inputs they take from
upstream come from the kit (docs/host_kit.md › Parity labels); no matrix row claims `match` for
them. The example opens its workspace FTS-only (`FeatureFlags(vector_search=False)`), as
`examples/quickstart.py` does; nothing in it is scripted or fake. The scripted chat model exists
only in the tests.

### Who owns what

| Piece | Where | Label |
| --- | --- | --- |
| state schema, nodes, edges, both model calls (turn and flush), the flush tool loop, `/new` parsing, the checkpointer, streaming | `examples/langgraph_agent.py` (`build_graph`, `main`) | host code |
| message and usage conversion, answering tool calls, the turn value that crosses nodes | `memory_core/adapters/langgraph.py` | adapter-only, framework-free |
| workspace, prompt, tools, dispatch, flush decision and write, session memory | `memory_core.host.HostKit` | kit (docs/host_kit.md) |

No node factory and no prebuilt agent (`create_memory_agent(kit, model)`): a factory that wires
the model node and the flush loop would own the agent loop and the tool loop, which adapters never
do (docs/package_boundary.md › Runtime Adapters; docs/host_kit.md, entry point 4). The example is
the template a LangGraph host copies, and every piece of glue it needs beyond the kit and the
adapter is listed under "Findings so far" (L8).

### Graph shape

```text
                START
                  |  route_input: is the last message a human "/new ..." or "/reset ..."?
          yes     |                      no
    +-------------+-----------------------+
    v                                     v
new_session ---------------------------> prepare          kit.before_turn (per-turn ensure)
kit.on_new_session                        |
                                          v
                               +-------> agent            host model: model.bind_tools(turn.tools)
                               |          |                 .invoke(turn.model_input(messages))
                               |          |  has_tool_calls(last)? (valid or invalid calls)
                               |     yes  |           no
                               |          v            \
                               +------- tools           +--> maintain ---> END
                                tool_messages(last,          kit.after_turn; for a FlushRequest
                                kit.dispatch)                the flush turn on the same model
                                                             (write tool only, not streamed),
                                                             request.dispatch, request.complete
```

One graph run is one turn (a bare `/new` run is the command plus its reset turn). The host runs
one run per thread at a time (F15).

### State schema

```py
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]  # the current session's visible transcript
    memory_session: NotRequired[dict | None]      # SessionState.to_json(), committed
    memory_turn: NotRequired[dict | None]         # PendingTurn.to_json(), the turn in flight
    memory_reset: NotRequired[dict | None]        # {"messageId", "modelPrompt"}, for prepare
    memory_maintenance: NotRequired[dict | None]  # the last maintenance: flush reason and outcome


@dataclass
class AgentContext:                    # the run context (context_schema), never checkpointed
    runtime_context: str | None = None  # the host's per-turn text (channel, sender)
```

- `messages` holds what upstream's transcript holds: user messages, replies, tool calls and
  results, and the reset turn's transcript row. Never the system prompt, the runtime context or
  the flush turn (docs/host_kit.md › Turn lifecycle: the host records "never the runtime-context
  block and never the flush turn").
- The input is the standard `{"messages": [HumanMessage(text)]}` (or `("user", text)`), so
  LangGraph clients that send messages work unchanged. `AgentContext` comes through
  `graph.invoke(..., context=AgentContext(...))` and reaches a node as `runtime.context`
  (`langgraph/runtime.py:125`); without it the runtime context is `None`.
- The `memory_*` keys hold JSON values only and `messages` holds LangChain messages, which are
  on the checkpoint serializer's safe list (`langgraph/checkpoint/serde/_msgpack.py:57`), so the
  state also loads under `LANGGRAPH_STRICT_MSGPACK=true`
  (`langgraph/checkpoint/serde/jsonplus.py:92-114`).

### Kit calls per node

| Node | Kit call | Reads | Writes |
| --- | --- | --- | --- |
| `route_input` (conditional edge from START) | none | the last message | the next node |
| `new_session` | `kit.on_new_session(ending, command=, session_id=, transcript=transcript_rows(messages), text=)` | `memory_session` (or a first `SessionState.new`) | `messages`: remove all, then the new session's first row; `memory_session`: `NewSession.session`; `memory_reset` for a bare command |
| `prepare` | `kit.before_turn(session, runtime_context=...)` with its per-turn ensure | `memory_session`, `memory_reset`, `runtime.context` | `memory_turn`: `PendingTurn.from_context(...)`; `memory_reset`: `None` |
| `agent` | none (the host's model) | `memory_turn`, `messages` | `messages`: the AI message |
| `tools` | `kit.dispatch(name, args, session=turn.session)` through `tool_messages` | `memory_turn`, the last AI message | `messages`: one tool message per call |
| `maintain` | `kit.after_turn(turn.session, transcript=transcript_rows(messages), usage=turn_usage(last), context_window_tokens=)`; for a request `request.messages`, `.tools`, `.dispatch`, `.complete(session, error=)` | `memory_turn`, `messages` | `memory_session`, `memory_turn`: `None`, `memory_maintenance` |

Not wired, on purpose: `heartbeat_prompt` (it needs the host's scheduler; L7), `request_flush`
(a memory-core extension with no upstream counterpart; the example has no `/flush`) and
`SessionState.after_compaction` (the example never compacts; F9).

### SessionState persistence

- One LangGraph thread is one upstream session key: the thread id (`config["configurable"]
  ["thread_id"]`, required) is `SessionState.session_key`, which stays across `/new`
  (docs/host_kit.md › `SessionState`), and `/new` rotates `session_id` inside the thread (L2,
  F16). The first run of a thread (no `memory_session` yet) starts
  `SessionState.new(session_key=<thread id>, session_id=<new id>)` in `prepare` or
  `new_session`; `build_graph` takes the id generator (`uuid4` by default), so tests are
  deterministic.
- The state lives in the checkpoint as `SessionState.to_json()`, and every node reads it with
  `from_json`. The object itself cannot be checkpointed: `InMemorySaver` raises `TypeError: Type
  is not msgpack serializable: SessionState` (probe; F1).
- Commit points follow the kit's rule that only a completed turn is recorded: `prepare` keeps
  `before_turn`'s session (truncation signatures, the bootstrap-turn fold) in `memory_turn`
  only; `maintain` commits `after_turn`'s session, or the flush's `FlushOutcome.session`, to
  `memory_session`; `new_session` commits `NewSession.session`. A turn that fails before
  `maintain` leaves `memory_session` as it was, and the next `prepare` replaces its stale
  `memory_turn`.
- A restart restores everything from the checkpointer: the host opens a new `HostKit` for the
  same workspace root and compiles the graph over the same saver, and the next run reads
  `memory_session` from the checkpoint. The example uses `InMemorySaver` (in process); a
  durable saver (`langgraph-checkpoint-sqlite`, `langgraph-checkpoint-postgres`) is the host's
  choice and not a dependency.

### Flush handling

- `maintain` runs after the `agent` node's final reply (no tool calls): upstream's post-reply
  maintenance order (docs/host_kit.md, entry point 4). A streaming host
  (`graph.stream(..., stream_mode="updates")`) delivers the reply from the `agent` update before
  `maintain` starts; `graph.invoke` returns only after `maintain`, so an invoke-only host waits
  for a due flush's model call (F6, L3).
- The `FlushRequest` is created and completed inside `maintain`: it holds the workspace's
  `Memory` and its appends, so it cannot cross a checkpoint (F6). The flush turn, in host code:

```py
def run_flush(request: FlushRequest, session: SessionState) -> FlushOutcome:
    flush_model = model.bind_tools(request.tools).with_config(tags=[TAG_NOSTREAM])
    messages: list[Any] = list(request.messages)
    try:
        for _ in range(MAX_FLUSH_TOOL_ROUNDS):
            reply = flush_model.invoke(messages)
            if not has_tool_calls(reply):
                break
            messages += [reply, *tool_messages(reply, request.dispatch)]
    except Exception as error:  # the reply is already delivered; a failed flush is a strike
        return request.complete(session, error=error)
    return request.complete(session)
```

- Same model, restricted to the kit's `write` tool (`request.tools`), on exactly
  `request.messages` (role dicts, which LangChain chat models take as they are). The flush reply
  is never delivered and never enters `messages`.
- `TAG_NOSTREAM` keeps the flush turn out of `stream_mode="messages"`: the messages handler skips
  chat-model runs with that tag (`langgraph/pregel/_messages.py:141`; probe). Without it the
  flush turn's tokens reach the host's stream (F7).
- `MAX_FLUSH_TOOL_ROUNDS` bounds the flush turn's tool loop (host policy, like the Lab's
  `MAX_TOOL_ROUNDS = 6`, `demo/lab_tools.py:37`); a flush turn that stops at the bound completes
  as a success with what it appended. The agent's own tool loop is bounded by LangGraph's
  `recursion_limit` (host config).
- `session` is `record.session`: maintenance runs inside the turn's run, so it is the current
  state. `complete` stamps the compaction cycle, so the next due turn reads `already_flushed`
  until `/new` (docs/host_kit.md › Turn lifecycle, known gap; F9).
- `context_window_tokens` is a `build_graph` argument. `main` passes the model's
  `profile["max_input_tokens"]` when LangChain knows it (a beta field: 128,000 for `gpt-4o-mini`,
  none for OpenRouter-style names such as `openai/gpt-4o-mini`; probe), else nothing, which
  gives the kit default of 200,000 (F12).
- `transcript_bytes` is not passed: a checkpointer has no session file, so the transcript-size
  gate stays off (F10, L9).
- `memory_maintenance` is `{"flush": <decision reason>, "target": <path or None>, "wrote":
  <entries appended>, "failure": <the failure's message or None>}`, so the flush shows in the
  `updates` stream and in `graph.get_state(config)`.

### `/new` and `/reset`

- `route_input` sends a run to `new_session` when the last message is a human message whose first
  word is `/new` or `/reset` (case-insensitive); the rest is `text`. This parser is host code and
  a simplification: upstream's `resolveSessionResetCommand`
  (`src/auto-reply/reply/session-reset-command.ts:249`) also handles mentions, envelopes, the soft
  `/reset` mode and the configured `session.resetTriggers` (default `["/new", "/reset"]`,
  `src/config/sessions/types.ts:888`). The kit takes a parsed command and ships no parser (F8,
  L6).
- `new_session` calls `on_new_session` with the ending session's rows (the command row included:
  the session-memory hook drops lines that start with `/`, `memory_core/session_memory.py`
  `_recent_message_lines`), a new id and `text`. It returns `messages` =
  `[RemoveMessage(id=REMOVE_ALL_MESSAGES), first]`, which drops everything before the marker
  (`langgraph/graph/message.py:38`, `:212-213`), so the thread's `messages` become the new
  session's transcript.
  - Bare command: `first` is `HumanMessage(reset.transcript_prompt, id=<new id>)` and
    `memory_reset` is `{"messageId": <that id>, "modelPrompt": reset.model_prompt}`. `prepare`
    makes it the `PendingTurn`'s model prompt, so every model call of that turn gets `[startup
    context, reset prompt]` while the transcript keeps `[memory-core session new]`; later turns
    replay only the row, as upstream (docs/host_kit.md, entry point 5).
  - With text: `first` is `HumanMessage(text)` and there is no reset prompt; the turn runs like
    any other.
- The run continues `new_session -> prepare -> agent ...`, so a bare `/new` gets the model's
  reset reply in the same run.
- The old session's messages stay in the thread's earlier checkpoints; the session-memory file
  holds only its last 15 lines. Checkpoint retention is the host's (F11).

### Error handling

| Failure | Node | Behaviour |
| --- | --- | --- |
| `before_turn` raises (`WorkspaceStateMigrationRequiredError`, `OSError`, `ValueError`) | `prepare` | the run raises; `memory_session` unchanged |
| the model call raises | `agent` | the run raises; nothing is recorded (the kit's failed-turn rule) |
| too many tool rounds | graph | `GraphRecursionError` at the host's `recursion_limit`: a failed turn |
| a tool call the model got wrong (bad params, invalid JSON, unknown tool, refused write) | `tools` | the kit's error payload as a tool message with `status="error"`; never raises |
| `after_turn` raises (`OSError`) | `maintain` | the run raises after the reply is in `messages`; `memory_session` keeps the previous snapshot |
| the flush target cannot be created | `maintain` | `TurnRecord.flush_failure`: one strike in `memory_session`, named in `memory_maintenance` |
| the flush model call raises (`Exception`) | `maintain` | `request.complete(session, error=exc)`: one strike (three mark the cycle); the run completes |
| the flush run is cancelled (`BaseException`) | `maintain` | not completed (upstream records nothing for a cancelled flush); propagates |
| `on_new_session` raises | `new_session` | the run raises; `messages` and `memory_session` stay the old session's (plus the command row); if the save succeeded and the ensure after it failed, a retry saves a second file (`-2` suffix) |

- LangGraph applies the input before the first node, so a failed turn leaves its user message in
  `messages` without a reply (probe: after a failing node, `get_state` shows the message and the
  earlier node's writes). The host resumes the failed node with `graph.invoke(None, config)`
  (probe: the failed node reruns, the earlier ones do not) or sends the next message, which then
  follows the orphan row (F17).
- Model-caused errors never raise out of the kit; host programming errors do (docs/host_kit.md ›
  Errors). The adapter keeps that split: an invalid tool call without a name is dispatched with
  `""`, so the model gets an error payload, not the host a `TypeError`.

### Adapter surface (proposed)

`memory_core/adapters/langgraph.py` stays framework-free: it imports only `memory_core` and the
standard library, reads LangChain messages by duck typing (`type`, `content`, `id`, `tool_calls`,
`invalid_tool_calls`, `usage_metadata`) and builds plain dicts, which LangChain's `add_messages`
and chat models convert (`langchain_core/messages/utils.py:679`: a `"tool"` role dict becomes a
`ToolMessage` with its `status`; probe). So the core keeps `httpx` as its only dependency, and
`tests/unit/test_packaging.py::test_core_dependencies_are_exactly_what_memory_core_imports`
stays as it is.

```py
def transcript_rows(messages: Iterable[Any]) -> list[dict[str, Any]]:
    """The kit's transcript rows of LangChain messages; role dicts pass through.

    human -> user, ai -> assistant, tool -> tool (with tool_call_id), system -> system; the
    content as it is (a string or content blocks, whose text blocks the kit reads).
    after_turn and on_new_session keep only the text of user and assistant rows."""

def turn_usage(message: Any) -> TurnUsage | None:
    """TurnUsage(input_tokens, output_tokens) of an AI message's usage_metadata, else None."""

def has_tool_calls(message: Any) -> bool:
    """True when an AI message has tool calls, the invalid ones included (for routing)."""

def tool_messages(
    message: Any,
    dispatch: Callable[[str, Mapping[str, Any] | str | None], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Answer every tool call of an AI message through dispatch, in order.

    tool_calls with their parsed args, then invalid_tool_calls with their raw args text (the
    kit answers invalid JSON with its error payload). One {"role": "tool", "tool_call_id",
    "name", "content": <payload as JSON text>, "status": "error" | "success"} dict per call;
    status is "error" for the kit's error payload."""


@dataclass(frozen=True)
class PendingTurn:
    """The turn in flight between prepare and maintain, as checkpointable JSON."""

    session: SessionState                 # TurnContext.session: for dispatch and after_turn
    system_prompt: str                    # TurnContext.system_prompt
    runtime_context: str | None           # TurnContext.runtime_context (marker-wrapped)
    tools: tuple[dict[str, Any], ...]     # TurnContext.tools, for bind_tools
    model_prompt: str | None = None       # a bare /new or /reset: ResetTurn.model_prompt, sent
    model_prompt_message_id: str | None = None  # in place of the message with this id

    @classmethod
    def from_context(
        cls,
        context: TurnContext,
        *,
        model_prompt: str | None = None,
        model_prompt_message_id: str | None = None,
    ) -> PendingTurn: ...  # ValueError when only one of the two reset fields is given

    def model_input(self, messages: Sequence[Any]) -> list[Any]:
        """[system prompt, runtime context] (each only when not empty) + messages, with the
        reset row replaced by {"role": "user", "content": model_prompt}."""

    def to_json(self) -> dict[str, Any]: ...

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> PendingTurn: ...  # ValueError: bad shape
```

- Tool schemas need no mapping: `bind_tools` takes `kit.tools()` and `FlushRequest.tools`
  unchanged, since a dict with a `name` is read as an OpenAI function
  (`langchain_core/utils/function_calling.py:432`; probe with `ChatOpenAI.bind_tools`).
- `tool_messages` and `has_tool_calls` exist because LangGraph's `tools_condition` routes only on
  `tool_calls` (`langgraph/prebuilt/tool_node.py:1657`) and `ToolNode` never answers
  `invalid_tool_calls`, while langchain-openai sends those back to the provider as tool calls
  (`langchain_openai/chat_models/base.py:490-496`), each of which then needs a tool message; and
  because `ToolNode` wants `BaseTool`s whose argument validation would replace the kit's
  upstream-shaped error payloads (F4, F13).
- `PendingTurn` exists because `TurnContext` holds a `WorkspaceContext` and is not serializable
  while the model node and the tools node run in separate supersteps (F2), and because the reset
  turn's two prompts have to share one `messages` list (F3).
- `memory_core/adapters/__init__.py` exports these five names; the package root keeps its 24.

### Fate of `LangGraphMemoryRecall`

Decision: remove it in 0.2.0 (still unreleased), with `format_memory_context` and
`Memory.langgraph_recall`. Reasons:

- It injects search results into the prompt, which upstream never does; the same reason removed
  `Memory.prepare_turn` in 0.2.0 (docs/host_kit.md › `Memory.prepare_turn`, `Memory.chat`,
  `Memory.record_turn`: removed). This design is the upstream shape for a LangGraph host.
- It does not work with LangGraph's own message state: it reads only `Mapping` messages with
  `role == "user"`, so a `MessagesState` of `HumanMessage` objects recalls nothing (probe:
  `{'memory_context': '', 'memory_results': []}` for a query whose dict form finds the hit).
- It drops the `disabled`, `warning` and `action` of an unavailable or paused search
  (docs/memory_search_tool.md), so a paused index goes unnoticed.
- Nothing is published ("Nothing is published to a package index yet", CHANGELOG.md), so a
  deprecation cycle would protect no user, and a labelled legacy helper would keep a broken,
  non-upstream method on the `Memory` handle.

Breaking change for 0.x, recorded in CHANGELOG.md › Removed, with the "Moved out of the package
root" table losing its row (154 to 152 names) and the counts next to it: `LangGraphMemoryRecall`
and `format_memory_context` (from `memory_core.adapters.langgraph` and `memory_core.adapters`) and
`Memory.langgraph_recall()`. Replacement: this integration; a host that still wants auto-recall
calls `Memory.search` itself and labels it. The removal reverses docs/host_kit.md's line
(2026-09-28) that the helper "stays as an explicit, labelled adapter-only auto-recall", so Doruk
confirms it (L1). It changes `memory_core/client.py`, outside `memory_core/adapters/`, so Task 9
runs the oracle suite.

### Dependencies

- `[project.optional-dependencies] langgraph = ["langgraph>=1.0", "langchain-core>=1.0"]`: what
  `examples/langgraph_agent.py` imports besides a provider, and the stack the adapter's duck
  typing is tested against. The adapter imports neither, so the extra pins the tested stack and
  gives LangGraph hosts one install line; it is not a code dependency (L5).
- The provider stays out of the extra (the host picks its model). The example uses
  `langchain-openai` for any OpenAI-compatible endpoint, installed next to the extra
  (`pip install "memory-core[langgraph]" langchain-openai`).
- `[dependency-groups] dev`: `memory-core[demo,langgraph]` and `langchain-openai>=1.0`, so the
  offline tests import LangGraph and the live test runs in the checkout's environment.
- `uv.lock` relocked with `uv lock`. On the design day the resolver picked langgraph 1.2.12,
  langgraph-checkpoint 4.2.0, langgraph-prebuilt 1.1.0, langchain-core 1.6.5 and
  langchain-openai 1.6.6; the lock records what it resolves when Task 1 runs.
- `tests/unit/test_packaging.py`: the extras are `{"demo", "langgraph"}`, the dev group has its
  new members, and a subprocess check shows that importing `memory_core.adapters.langgraph`
  loads no `langchain_core`, `langgraph` or `openai` module.

### Findings so far

Found while reading the sources and running probes for this design. The implementation
confirms, corrects or extends them, and Task 8 turns them into this file's findings section.

| # | Finding | Evidence | Recommendation |
| --- | --- | --- | --- |
| F1 | `SessionState` cannot live in graph state as an object | probe: `InMemorySaver` raises `TypeError: Type is not msgpack serializable: SessionState` | store `to_json()` (the kit's documented round trip); say so in docs/host_kit.md › `SessionState` |
| F2 | `TurnContext` is not serializable, but a graph's model and tools nodes run in separate supersteps | `TurnContext.workspace` is a `WorkspaceContext` | adapter `PendingTurn`; or the kit offers a JSON form of a turn's prompt, tools and session |
| F3 | the reset turn has two user prompts (model and transcript), and a graph has one `messages` list | docs/host_kit.md, entry point 5 | adapter substitution by message id (`PendingTurn.model_input`) |
| F4 | malformed tool-call JSON lands in `invalid_tool_calls`, which `tools_condition` and `ToolNode` ignore and langchain-openai sends back | `langgraph/prebuilt/tool_node.py:1657`, `langchain_openai/chat_models/base.py:490-496` | adapter `has_tool_calls` and `tool_messages`; the kit's JSON-text `dispatch` already gives the right payload |
| F5 | under `stream_mode="messages"` a chat model streams internally, and `ChatOpenAI` enables `stream_usage` only for the default OpenAI URL: with a `base_url` (OpenRouter) there is no `usage_metadata`, so `after_turn` reads `missing_tokens` and the flush never runs, silently | `langchain_core/language_models/chat_models.py:549-585`, `langchain_openai/chat_models/base.py:1431-1450` (source; Task 7 checks it against a local stub endpoint) | the example sets `stream_usage=True`; `memory_maintenance` shows `missing_tokens`; the docs warn |
| F6 | the flush sits on the reply path of `graph.invoke`, and it cannot move to a later run or a background task, because `FlushRequest` holds live objects | docs/host_kit.md, entry point 4 | keep the in-graph node (streaming hosts deliver first); for detached maintenance, a serializable flush request the kit can rebuild (L3) |
| F7 | the flush turn's tokens reach a `messages` stream unless tagged | probe with `TAG_NOSTREAM` | document the tag next to `FlushRequest` |
| F8 | the kit takes a parsed `/new` command but has no parser; upstream's is configurable and handles mentions and the soft reset | `src/auto-reply/reply/session-reset-command.ts:249`, `src/config/sessions/types.ts:888` | port a subset of `resolveSessionResetCommand` into core with an oracle op, or document the host's parser (L6) |
| F9 | one flush per session without compaction: LangGraph hosts trim history (windowing, which does not count) or summarize it (a compaction, which must call `after_compaction`) | docs/host_kit.md › Turn lifecycle, decision Q9 | document the mapping (trim: nothing; summarize: `after_compaction`) |
| F10 | no transcript size for the size gate: a checkpointer has no session file | docs/host_kit.md, entry point 4 | leave the gate off (L9) |
| F11 | checkpoints keep every turn's prompt (up to about 60,000 chars of workspace files in `memory_turn`) and the old session's raw messages after `/new` | this design | document retention; or rebuild the prompt per model call with `before_turn(ensure=False)` instead of storing it |
| F12 | the kit's 200,000-token default window overshoots most models, and LangChain knows the window only for some model names | probe: `ChatOpenAI(model="gpt-4o-mini").profile["max_input_tokens"] == 128000`, none for `openai/gpt-4o-mini` | the host passes the window; the example reads the profile |
| F13 | `ToolNode` needs `BaseTool`s whose argument validation would change the kit's error payloads | `langgraph/prebuilt/tool_node.py:743-757` | a custom tools node over `dispatch` (adapter `tool_messages`) |
| F14 | the kit is sync; LangGraph runs sync nodes in an executor under `ainvoke` (probe), but node timeouts exist only for async nodes | `langgraph/_internal/_runnable.py:571`, `langgraph/graph/state.py:714-722` | no async twins needed for LangGraph: memory nodes stay sync, the model node may be async |
| F15 | LangGraph does not serialize two runs on one thread (no lock in the pregel loop or `InMemorySaver`), so the kit's one-lane-per-session rule is the host's | source | document one run per thread at a time |
| F16 | the kit needs a stable session key; LangGraph has a thread id | this design | thread id = `session_key` (L2) |
| F17 | a failed turn leaves its user message in `messages` | probe | document `graph.invoke(None, config)` to resume |
| F18 | `bind_tools(strict=True)` rewrites schemas for OpenAI's strict mode, which wants every property required; the kit's optional parameters may not fit | `langchain_core/utils/function_calling.py` (`strict`; source, Task 5 checks it) | the example passes no `strict` |

Positive so far: `kit.tools()` and `FlushRequest.tools` bind unchanged; LangChain chat models take
`FlushRequest.messages` as they are; `SessionState.to_json()` round-trips through the
checkpointer; the kit's payloads go to the model as `json.dumps(payload, ensure_ascii=False)`, as
the Lab sends them (`demo/lab_tools.py:287`).

### Test plan

The offline tests drive the real compiled graph of `examples/langgraph_agent.py:build_graph` with
`ScriptedChatModel`, a test-only `BaseChatModel` subclass whose `bind_tools` returns
`self.bind(tools=...)` and whose `_generate` answers from a per-test script and records each
call's messages and bound tool names. Neither LangChain fake (`FakeMessagesListChatModel`,
`GenericFakeChatModel`, `langchain_core/language_models/fake_chat_models.py:21, 227`) implements
`bind_tools` (the base raises `NotImplementedError`,
`langchain_core/language_models/chat_models.py:2366-2383`). Workspaces are
FTS-only with a fixed kit clock (`now_ms`), UTC and a fixed session-id sequence; the
checkpointer is `InMemorySaver`, which serializes every value it stores. Modules that need
LangGraph start with `pytest.importorskip`.

`tests/unit/test_langgraph_adapter.py` (rewritten; the recall tests go with Task 4):

- `test_transcript_rows_map_langchain_types_to_kit_roles`
- `test_transcript_rows_keep_content_blocks_and_pass_role_dicts_through`
- `test_turn_usage_reads_usage_metadata`
- `test_turn_usage_without_usage_metadata_is_none`
- `test_has_tool_calls_counts_invalid_calls`
- `test_tool_messages_answer_every_call_through_dispatch`
- `test_tool_messages_answer_invalid_calls_with_the_kit_error_payload`
- `test_tool_messages_mark_error_payloads_and_convert_to_tool_messages`
- `test_pending_turn_round_trips_json`
- `test_pending_turn_from_json_rejects_a_bad_shape`
- `test_pending_turn_model_input_puts_the_system_prompt_and_runtime_context_first`
- `test_pending_turn_model_input_sends_the_reset_prompt_in_place_of_its_row`
- `test_pending_turn_needs_both_reset_fields`

`tests/unit/test_packaging.py`: `test_demo_and_langgraph_are_the_only_extras_and_dev_tools_a_group`
(replaces `test_demo_dependencies_are_the_only_extra_and_dev_tools_a_group`) and
`test_importing_the_langgraph_adapter_loads_no_framework`.

`tests/unit/test_langgraph_agent.py` (end to end):

- `test_turn_offers_the_kit_tools_and_answers_memory_search`: the bound tool names are
  `kit.tools()`'s, the tool message carries `kit.dispatch`'s payload, and the reply ends the run.
- `test_system_prompt_comes_from_before_turn_and_stays_out_of_the_transcript`
- `test_due_flush_runs_after_the_reply_and_writes_the_daily_file`: usage past the threshold; the
  `agent` update streams before the flush model call; `memory/<date>.md` holds the fact;
  `memoryFlush` is stamped; `messages` hold no flush message.
- `test_flush_turn_is_restricted_to_the_write_tool_and_not_streamed`: bound tools `["write"]`,
  model input equal to `FlushRequest.messages`, no `messages`-mode chunk from `maintain`.
- `test_second_turn_finds_the_flushed_fact`: `memory_search` returns the daily file with its
  citation.
- `test_second_turn_past_the_threshold_reads_already_flushed` (the kit's known gap, pinned)
- `test_session_state_survives_in_the_checkpointer`: a second graph over the same saver continues
  the thread; `memory_session` reads back with `SessionState.from_json`.
- `test_invalid_tool_call_gets_the_kit_error_payload`
- `test_bare_new_saves_session_memory_and_runs_the_reset_turn`: `memory/<date>-<slug>.md`
  exists; `messages` are the reset row and the reply; the model got `ResetTurn.model_prompt`.
- `test_new_keeps_the_session_key_and_rotates_the_session_id`
- `test_new_with_text_starts_the_new_session_with_that_text`
- `test_reset_prompt_is_not_replayed_on_the_next_turn`
- `test_failed_model_call_commits_no_session_state`: the run raises, `memory_session` is
  unchanged, and `graph.invoke(None, config)` resumes the turn.
- `test_failed_flush_turn_records_a_strike_and_keeps_the_reply`
- `test_example_main_requires_the_model_environment`: without `OPENAI_API_KEY` or
  `OPENAI_MODEL`, `main` exits with a message naming them, before any network call.

`tests/integration/test_langgraph_agent_live.py`:
`test_live_langgraph_agent_flushes_and_recalls_across_new`, skipped unless
`MEMORY_CORE_LIVE_OPENAI=1`, `OPENAI_API_KEY` and `OPENAI_MODEL` are set (`OPENAI_BASE_URL`
optional; L4). It runs the example's graph on `ChatOpenAI` with
`stream_usage=True` and a `context_window_tokens` whose flush threshold is 1 token (computed from
the flush plan's reserve and soft-threshold constants), so every turn with real usage is due.
Turn 1 states a random codename: the test asserts that real usage reached the kit, the decision
`token_threshold`, the stamped cycle and the codename in the daily file. After `/new` a later turn
asks for the codename: the test asserts it in the reply and names the path it came by (a
`memory_search` or `memory_get` result, or the reset turn's startup context). A real model can
vary; each assertion names the step that differed.

`tests/unit/test_examples.py`: `test_langgraph_doc_example_runs_without_an_embedder` goes with
Task 4; Task 8 adds `test_langgraph_doc_shows_the_example_graph` (the doc's graph block equals
`build_graph`'s source, like the README Quickstart test).

### TDD tasks

Each task: tests first (watch them fail), implement, run the offline suite (baseline at
`79a1b5c`: 1347 passed, 311 skipped), `ruff check . --no-cache` and
`scripts/rename_project.py --check`, then commit that task alone.

1. Dependencies: `pyproject.toml`, `uv.lock`, `tests/unit/test_packaging.py`.
2. Adapter conversions: `transcript_rows`, `turn_usage`, `has_tool_calls` and `tool_messages` in
   `memory_core/adapters/langgraph.py` (next to the legacy recall until Task 4) and its exports;
   the adapter tests above except `PendingTurn`'s.
3. `PendingTurn`: the same files; its five tests.
4. Remove `LangGraphMemoryRecall`, `format_memory_context` and `Memory.langgraph_recall` (L1):
   `memory_core/adapters/`, `memory_core/client.py`, `tests/unit/test_client.py`,
   `tests/unit/test_public_api.py` (`Memory`'s methods, the changelog table count),
   `tests/unit/test_examples.py`, CHANGELOG.md (Removed, the table, the counts), the legacy
   sections of this file, and the mentions in README.md, docs/package_boundary.md,
   docs/memory_search_tool.md and docs/host_kit.md.
5. The graph: `examples/langgraph_agent.py` (`AgentState`, `AgentContext`, `build_graph` with
   `prepare`, `agent`, `tools` and `maintain`) and `tests/unit/test_langgraph_agent.py` (the turn,
   flush, second-turn, checkpointer and invalid-call tests).
6. `/new`, `/reset` and failures: `route_input`, `new_session`, the reset substitution and the
   failure tests.
7. `main` and the live test: the env-driven terminal loop (it streams `updates`, prints the reply
   before maintenance, sets `stream_usage=True` and passes the profile's window),
   `tests/integration/test_langgraph_agent_live.py` and the offline `main` test; check F5 against
   a local stub OpenAI-compatible endpoint (127.0.0.1, no network).
8. Docs: this file rewritten for the host-kit path with the findings section (F1-F18 as
   confirmed); README.md (the Python API snippet loses `langgraph_recall`, the pointer names the
   agent); docs/package_boundary.md › Runtime Adapters; docs/parity_matrix.md audit note 21
   (adapter-only, no row changes) with `tests/parity/test_parity_matrix_evidence.py`;
   CHANGELOG.md › Added (the adapter helpers, the extra, the example); the doc drift test.
9. Verify: the full offline suite, ruff, the name check, and the oracle suite
   (`OPENCLAW_ORACLE_REPO=/tmp/openclaw-head` with Node 24, since Task 4 changed
   `memory_core/client.py`; reference 254 passed, 81 xfailed, 2 skipped, 0 failed of 337). The
   measured numbers go into the commit body and this file. The main session runs the live test.

### Open questions for Doruk

- L1. Remove `LangGraphMemoryRecall`, `format_memory_context` and `Memory.langgraph_recall` in
  0.2.0 (recommended, above), or keep them as a labelled legacy helper, fixed to read LangChain
  messages? Removal reverses docs/host_kit.md's line of 2026-09-28.
- L2. One thread per session key with `/new` rotating the session id inside the thread
  (recommended), or one thread per session id, the host switching threads on `/new`?
- L3. The flush in an in-graph `maintain` node (recommended: upstream's order, and a streaming
  host delivers the reply first; `invoke` waits), or detached maintenance, which needs a kit
  change (a serializable flush request)?
- L4. The live test requires `OPENAI_MODEL` and skips without it (recommended: memory-core picks
  no model for the host), or it gets a default model, and which one?
- L5. The `langgraph` extra holds `langgraph` and `langchain-core` only (recommended), or
  `langchain-openai` too?
- L6. `/new` parsing stays a labelled host simplification in the example (recommended for this
  stage), or a subset of upstream's `resolveSessionResetCommand` is ported into core first, with
  its own oracle op?
- L7. Heartbeat stays out of this agent (recommended: it needs the host's scheduler), or the
  graph gets a heartbeat entry now?
- L8. No node factory or prebuilt agent (recommended: it would own the loop), or a labelled
  `create_memory_agent(kit, model)` convenience?
- L9. The transcript-size gate stays off (recommended), or the example passes the Lab's labelled
  JSON-size estimate of `messages`?

## Legacy: `LangGraphMemoryRecall` (removed by Task 4)

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

from memory_core import FeatureFlags, Memory, MemoryConfig

root = Path(".")
memory = Memory.from_workspace(  # FTS-only; pass embedding_provider= for hybrid search
    root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
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
