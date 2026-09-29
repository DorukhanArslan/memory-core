# LangGraph Integration

A LangGraph agent whose memory runs through the host kit (`memory_core.host`, docs/host_kit.md):
[examples/langgraph_agent.py](../../examples/langgraph_agent.py) is the graph a LangGraph app
copies, and `memory_core.adapters.langgraph` holds the few framework-free helpers it needs
beyond the kit. The graph and the adapter are adapter-only: the orders and inputs they take from
upstream come from the kit, and no parity row claims `match` for them (Design › Parity labels).
Built on `feat/langgraph-agent`, 2026-09-29, against langgraph 1.2.12, langchain-core 1.6.5 and
langchain-openai 1.6.6; the Findings section below lists what the kit's API lacked for this host,
and the kit changes it recommends were built on `feat/kit-langgraph-fixes` the same day
(decision L10; docs/host_kit.md › LangGraph findings).

## Usage

### Install

```bash
pip install "/path/to/memory-core[langgraph]" langchain-openai
```

The `langgraph` extra is `langgraph` and `langchain-core`, the stack the adapter is tested
against; the adapter itself imports neither, and the core's only dependency stays `httpx`. The
chat model provider is the host's choice; the example uses `langchain-openai` for any
OpenAI-compatible endpoint. In a checkout, `uv sync` installs all of it.

### Run the example

```bash
OPENAI_API_KEY=... OPENAI_MODEL=... python examples/langgraph_agent.py
OPENAI_API_KEY=... OPENAI_MODEL=openai/gpt-4o-mini OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
  python examples/langgraph_agent.py --context-window 128000
```

A terminal chat over one thread (`--thread`, default `main`) and the workspace
`my-agent-app/` (`--workspace`), searched FTS-only. Replies go to stdout; stderr gets one line
for the setup (the context window and where it came from), one per tool call and one per
maintenance (the flush decision with its token count and threshold, and what the flush
appended). `/new` and `/reset` start a new session in the thread. An empty line, Ctrl-D (or
the end of piped input) or Ctrl-C ends the chat; a failed turn prints `[error] ...` to stderr
and the chat goes on, the next message starting a new turn after the failed one's user message
(F17). The checkpointer is in memory, so a restart starts the thread over; the memory files
stay.

`--context-window` is required when LangChain's model profile has no window for the model name
(OpenRouter-style names such as `openai/gpt-4o-mini` have none): the kit's 200,000-token
default would put a 128,000-token model's flush threshold at 176,000, above its window, and the
flush would never run (F12).

### Use the graph in an app

```python
import os
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph_agent import AgentContext, build_graph  # your copy of the example

from memory_core import FeatureFlags, HostKit, MemoryConfig

root = Path("my-agent-app")
kit = HostKit.open(  # FTS-only; pass embedding_provider= for hybrid search
    root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
)
model = ChatOpenAI(model=os.environ["OPENAI_MODEL"], stream_usage=True)
graph = build_graph(  # context_window_tokens: the model's window, for the flush gate
    kit, model, checkpointer=InMemorySaver(), context_window_tokens=128_000
)
config = {"configurable": {"thread_id": "customer-42"}}  # one thread is one session key

for update in graph.stream(
    {"messages": [HumanMessage("Our project codename is velvetkiwi.")]},
    config,
    context=AgentContext(runtime_context="Channel: web chat"),
    stream_mode="updates",
):
    if "maintain" in update:
        print(update["maintain"]["memory_maintenance"])
reply = graph.get_state(config).values["messages"][-1]
```

`build_graph(kit, model, *, context_window_tokens, checkpointer, session_key, new_id, redact,
redactor)`: `context_window_tokens` is required (L11): the model's window for the flush gate,
since the kit's 200,000-token default would silence a smaller model's flush (F12).
`session_key` maps the thread id to the session key (default: the thread id;
`lambda thread: f"agent:main:{thread}"` gives upstream-shaped keys), `new_id` makes session ids
(`uuid4` text), `redact` maps a failed flush's error text and `redactor` each line `/new` saves
from the ending session. The input is the standard `{"messages": [...]}`, so LangGraph clients
work unchanged; `context=AgentContext(runtime_context=...)` is optional.

### What one run does

```text
START -> new_session (a human "/new" or "/reset" first word: kit.on_new_session)
      -> prepare     (kit.before_turn, into a TurnState in the state)
      -> agent       (the model bound to kit.tools(); has tool calls?) -> tools -> agent ...
      -> maintain    (kit.after_turn; a due FlushRequest runs its flush turn) -> END
```

- `messages` is the session's visible transcript: user messages, replies, tool calls and
  results, and a bare `/new`'s reset row. The system prompt, the runtime context and the flush
  turn never enter it. `model_input` sends the system prompt first and the runtime context as a
  user message right before the turn's user message, where upstream keeps its runtime-context
  carrier (F22).
- `memory_session` is `SessionState.to_json()`, committed by `maintain`, by `new_session`
  and, for a thread's first session, by `prepare`; a turn that fails before `maintain` records
  nothing. `memory_maintenance` shows the last
  maintenance: `flush` (the decision's reason), `tokenCount`, `threshold`, `window`, `target`,
  `wrote` (the appended entries) and `failure`.
- `maintain` runs after the final reply, in the same run. A `stream_mode="updates"` consumer
  gets the reply with the `agent` update before the flush's model call starts; `invoke` returns
  only after it (F6). Drain the stream: a consumer that stops after the reply closes the run
  and `maintain` never completes (F20).
- The flush turn is the same model bound to the flush's `write` tool only, on exactly
  `FlushRequest.messages`, tagged `TAG_NOSTREAM` so none of it reaches a `messages` stream (F7),
  at most `MAX_FLUSH_TOOL_ROUNDS` (6) tool rounds. A failed flush model call is one strike
  (`request.complete(error=...)`); three mark the cycle flushed.
- A turn gets at most `MAX_TOOL_ROUNDS` (6) model calls that ask for tools; the next call gets
  no tools, as the Lab's loop does, and a reply that still asks for tools fails the turn. Set no
  `recursion_limit` for this: LangGraph's default is 10,007 steps (F25).
- Without compaction a session flushes once: after the flush every later turn reads
  `already_flushed` until `/new` starts the next session (F9).
- A bare `/new` or `/reset` saves the ending session (`memory/<date>-<slug>.md`), replaces the
  thread's messages with the identity's reset row and runs the reset turn in the same run: the
  model gets `ResetTurn.model_prompt` (startup context and reset prompt) in place of the row,
  and later turns replay only the row. `/new <text>` starts the new session with the text.
- Failures: a failed model call raises out of the run with the user message in `messages` and
  `memory_session` unchanged; `graph.invoke(None, config)` resumes the failed node (F17). The
  kit's error payloads (bad arguments, invalid JSON, an unknown tool) go back to the model as
  tool messages with `status="error"`; a tool call without an id raises `ValueError` (F19). A
  turn that failed in or before `tools` leaves an AI message whose tool calls have no tool
  message, which a provider rejects: every model call sends a repaired copy of `messages`
  (`repair_tool_calls` over `kit.repair_tool_calls`, upstream's replay repair), where such a
  call gets upstream's synthetic error result and a call without an id is dropped; the stored
  messages keep the AI message (F26).
- One run per thread at a time: LangGraph does not serialize runs of one thread, and the kit's
  one-maintenance-lane rule needs it (F15).

### Adapter

`memory_core.adapters.langgraph` (also exported by `memory_core.adapters`) reads LangChain
messages by their attributes and returns plain dicts, which `add_messages` and LangChain chat
models convert; it imports no framework, owns no loop and calls no model.

| Name | What |
| --- | --- |
| `transcript_rows(messages)` | the kit's `{"role", "content"}` rows of LangChain messages (objects or dict forms) for `after_turn` and `on_new_session`; never a `type` key |
| `turn_usage(message)` | `TurnUsage` from an AI message's `usage_metadata`, else `None` |
| `has_tool_calls(message)` | valid or invalid tool calls, for routing |
| `tool_messages(message, dispatch)` | one `{"role": "tool", ...}` dict per tool call, valid and invalid, answered through `kit.dispatcher(session)` or `FlushRequest.dispatch` |
| `repair_tool_calls(messages, repair)` | the messages for a model call after upstream's replay repair of their tool calls through `kit.repair_tool_calls` (`repair`): unchanged messages are the original objects, a changed AI message is a copy without its dropped calls, and a missing result is a synthetic tool dict with `status="error"`; the stored messages stay as they are |

There is no node factory or prebuilt agent: wiring the model and the flush loop would own the
agent loop, which adapters never do (docs/package_boundary.md). `LangGraphMemoryRecall`, the
earlier auto-recall node, was removed in 0.2.0 (L1, confirmed by Doruk on 2026-09-29; Design › Fate of
`LangGraphMemoryRecall`).

### Tests

- `tests/unit/test_langgraph_adapter.py`: the adapter against real `langchain_core` messages.
- `tests/unit/test_langgraph_agent.py`: the compiled graph end to end with a scripted chat
  model (a test double; nothing calls a provider), plus `ChatOpenAI` against a local
  OpenAI-compatible stub on 127.0.0.1 for the usage finding (F5) and for `main`.
- `tests/integration/test_langgraph_agent_live.py`: a real model, opt-in with
  `MEMORY_CORE_LIVE_OPENAI=1`, `OPENAI_API_KEY` and `OPENAI_MODEL` (`OPENAI_BASE_URL`
  optional); skipped otherwise. It has not run against a real model on this branch yet.

Measured 2026-09-29 on the branch: offline 1387 passed, 312 skipped at `5171e6e` and 1395
passed, 312 skipped after the review fixes (`caa244e`..`2b685d9`, eight new tests; baseline at
`79a1b5c`: 1347 passed, 311 skipped), ruff and the name check clean; the oracle suite at
`7388ea0` (v2026.9.6, Node 24) 254 passed, 81 xfailed, 3 skipped, 0 failed of 338, the
reference counts plus the skipped live test. The review fixes change no file under
`memory_core/`, so the oracle was not rerun for them. On `feat/kit-langgraph-fixes` (the L10 kit
changes, 2026-09-29): offline 1476 passed, 325 skipped at `7e1d23b` and after its docs (baseline
at `807508d`: 1396 passed, 312 skipped), ruff and the name check clean; the oracle suite has not
run on that branch yet.

## Findings

What building this host showed about the host kit's API, confirmed while implementing the
design below (numbers kept from Design; F22-F26 are new). Evidence: **test** is a named offline
test in `tests/unit/test_langgraph_agent.py` or `tests/unit/test_langgraph_adapter.py`,
**probe** a scratch run on the tested versions, **source** read but not run. Verdict: the six
entry points were enough; nothing needed a kit change to work, but a LangGraph host needs about
200 lines of graph code and five adapter helpers, and the items marked **kit** would remove glue
or a trap. Addressed on `feat/kit-langgraph-fixes` (2026-09-29, decision L10; docs/host_kit.md ›
LangGraph findings): F1, F2, F3, F7, F12, F21, F22, F24 and F26, each row naming its commits
("the docs after `7e1d23b`" is the branch's docs commit). The oracle fixtures of the two ports F26
uses have not run yet (ported, oracle-unverified).

### Awkward or missing in the kit

| # | Finding | Evidence | Recommendation |
| --- | --- | --- | --- |
| F2 | `TurnContext` does not serialize (it holds a `WorkspaceContext`), but a graph's model, tools and maintenance nodes run in separate supersteps that read their input from the checkpoint | test: every graph test carries the turn in `memory_turn` | **Addressed** (`14dbdcb`, `76dfdd7`): the kit's `TurnState` (`memory_core/host/turn.py`: session, system prompt, runtime context, tools and the reset turn, `to_json` / `from_json`) is the turn in `memory_turn`; the adapter's `PendingTurn` is gone |
| F3 | a bare `/new` turn has two user prompts, `ResetTurn.model_prompt` for the model and `transcript_prompt` for the transcript, and the model needs the first on every call of the turn, tool rounds included, while a graph keeps one `messages` list | test: `test_bare_new_saves_session_memory_and_runs_the_reset_turn`, `test_reset_turn_substitutes_the_active_user_message_on_every_call`, `test_reset_turn_keeps_its_prompt_when_the_repair_drops_an_answered_call`, `test_model_input_replaces_only_the_transcript_prompt` | **Addressed** (`14dbdcb`, `76dfdd7`): `TurnState.reset` carries the `ResetTurn` (`ResetTurn.to_json` / `from_json` in `memory_reset`); `model_input` gives the turn's active user message (upstream's `findActiveUserMessageIndex`) the model prompt under upstream's guard (`installModelPromptTransform`), so the reset row needs no message id |
| F6 | with maintenance in the graph, `graph.invoke` returns only after a due flush's model call, and the node starts when the reply is in state, not when it is delivered (upstream waits for delivery settlement, `agent-runner-maintenance.ts:69-71`) | test: `test_due_flush_runs_after_the_reply_and_writes_the_daily_file` (the `agent` update streams before the flush call) | labelled deviation; detached maintenance needs no kit change (end the graph after `agent`, run `after_turn` and the flush on a thread with a per-thread future that the next run's `prepare` waits for and merges); one decision with docs/host_kit.md Q13 (L3) |
| F7 | a flush turn run inside a graph streams its tokens into `stream_mode="messages"` unless its model run is tagged | test: `test_flush_turn_is_restricted_to_the_write_tool_and_not_streamed` (with the reply present as the positive control) | the example tags it `TAG_NOSTREAM`; **Addressed** (the docs after `7e1d23b`): docs/host_kit.md names the need next to `FlushRequest` |
| F8 | the kit takes a parsed `/new` command and ships no parser; upstream's (`session-reset-command.ts:249`) handles mentions, envelopes, the soft `/reset` and configured triggers | source | the example's `reset_command` is a labelled simplification (first word, any case; `test_a_command_that_is_not_first_word_is_an_ordinary_message`); porting a subset into core needs an oracle op (L6) |
| F9 | without compaction a session flushes once: every later due turn reads `already_flushed` until `/new` | test: `test_second_turn_past_the_threshold_reads_already_flushed`, `test_new_keeps_the_session_key_and_rotates_the_session_id` (the next session flushes again) | the kit's known gap; LangGraph hosts that trim history change nothing, hosts that summarize skip `maintain` for that turn and call `SessionState.after_compaction` (upstream skips maintenance after an auto-compaction, `agent-runner-maintenance.ts:31`) |
| F12 | `after_turn`'s default window (upstream's 200,000) silently disables the flush for a smaller model: 128,000 gives a 176,000 threshold. LangChain's profile knows the window for some model names only | probe: `ChatOpenAI(model="gpt-4o-mini").profile["max_input_tokens"] == 128000`, `gpt-6-luna` 1,050,000, none for `openai/gpt-4o-mini` or `openai/gpt-6-luna`; test: `test_example_main_requires_a_window_the_profile_does_not_give` | the example's `main` requires `--context-window` when the profile has none and prints the window's source; `build_graph` requires the window (L11, `9c8c6b8`); `memory_maintenance` shows the threshold; **Addressed** (the docs after `7e1d23b`): docs/host_kit.md › `after_turn` and README say the default is right only for a 200,000-token model |
| F21 | `FlushRequest.complete` takes `redact`, but `after_turn` records a flush-target failure's message without one | test: `test_redact_maps_a_flush_target_failure`, `test_redact_and_redactor_reach_the_kit` | **Addressed** (`dcba413`, `76dfdd7`): `after_turn(redact=)`; `maintain` passes `redact` and no longer rebuilds the failure outcome |
| F22 | the kit does not say where `runtime_context` goes: the Turn lifecycle diagram lists `system_prompt, runtime_context, history, user message`, the block's own header says it is for "the immediately preceding user message", and upstream keeps the carrier immediately before the active user message and sends it as a user message | source: `src/agents/internal-runtime-context.ts:378`, `packages/agent-core/src/harness/messages.ts:139-153`, `attempt-llm-boundary.ts:268`; test: `test_runtime_context_reaches_the_model_and_is_optional` | the example follows upstream (a user message right before the turn's user message, on every model call of the turn); **Addressed** (the docs after `7e1d23b`): docs/host_kit.md › `before_turn` and README state the placement and the role, and the lifecycle diagram is fixed |
| F24 | `kit.dispatch` needs `session=` as a keyword while `FlushRequest.dispatch` takes two arguments, so a shared tool-answering helper needs `functools.partial` | test: the tools node | **Addressed** (`dcba413`, `76dfdd7`): `HostKit.dispatcher(session)`, on the kit so that a `TurnState` read from JSON can use it (K4); the tools node passes `kit.dispatcher(turn.session)`, and so do the quickstart and README |
| F26 | a turn that fails in or before its tools node (a call without an id, a raising `dispatch`, a crash between `agent` and `tools`) leaves an AI message whose tool calls have no tool message. The next message sent it to the model as `[system, human, ai(tool_calls), human]`, which OpenAI-compatible APIs reject (their documented rule; not run here), and `graph.invoke(None)` reran a deterministic failure, so the thread stayed stuck. Upstream repairs the replayed history with synthetic error results (`repairToolUseResultPairing`, `src/agents/session-transcript-repair.ts:391`); the core's port (`memory_core/replay_repair.py`) takes upstream's message shape, and the kit offers no repair for host messages | probe (review); test: `test_next_message_after_a_failed_tools_node_repairs_the_unanswered_call` (both causes), `test_model_input_repairs_the_history_before_placing_the_prompts` | **Addressed** (`0869989`, `89945b3`, `9e1b00c`, `7e1d23b`): the core's pairing repair re-ported to the tag and upstream's `sanitizeToolCallInputs` ported (both oracle-unverified), composed by `HostKit.repair_tool_calls` over host rows and by the adapter's `repair_tool_calls` over LangChain messages; every model call gets the repaired copy (a synthetic error result for a call with an id, a call without one dropped), the stored messages keep the AI message, and `unanswered_tool_calls` with its `RemoveMessage` and labelled deviation is gone |

### LangGraph facts a host must handle (documented, no kit change)

| # | Finding | Evidence | Handling |
| --- | --- | --- | --- |
| F1 | `SessionState` cannot live in graph state as an object: the checkpoint serializer refuses it | probe: `TypeError: Type is not msgpack serializable: SessionState`; test: `test_state_loads_under_a_strict_serializer` | `to_json()` in the state, `from_json` in every node; **Addressed** (the docs after `7e1d23b`): docs/host_kit.md › `SessionState` has the line |
| F4 | malformed tool-call JSON lands in `invalid_tool_calls`, which `tools_condition` and `ToolNode` ignore while langchain-openai sends the calls back to the provider | source: `langgraph/prebuilt/tool_node.py:1657`, `langchain_openai/chat_models/base.py:490-496`; test: `test_invalid_tool_call_gets_the_kit_error_payload` | adapter `has_tool_calls` and `tool_messages`; the kit's JSON-text `dispatch` already answers with its error payload |
| F5 | under `stream_mode="messages"` the chat model streams, and `ChatOpenAI` asks for streamed usage only for OpenAI's own URL: with a custom `base_url` (OpenRouter) the reply has no `usage_metadata`, the gate reads `missing_tokens` and the flush never runs, silently. An `updates` stream does not stream the call | test: `test_stream_usage_decides_whether_a_custom_endpoint_reports_usage` (a local stub endpoint: no `stream_options` without `stream_usage=True`) | the example sets `stream_usage=True`; `memory_maintenance["flush"]` and the example's status line show `missing_tokens` |
| F10 | a checkpointer has no session file, so there is no transcript size for the size gate | source | the gate stays off (L9) |
| F11 | checkpoints keep each turn's system prompt (up to about 60,000 characters of workspace files) and marker-wrapped runtime context in `memory_turn`, and the old session's raw messages after `/new`; `get_state` and the checkpoint history expose them | source; test: `test_system_prompt_comes_from_before_turn_and_stays_out_of_the_transcript` checks the transcript only | document retention (the host's); `UntrackedValue` would keep the turn out of the checkpoint but lose it on `invoke(None)` resume, so it is not used; the size effect on a SQLite saver is unverified |
| F13 | `ToolNode` wants `BaseTool`s, whose argument validation would replace the kit's upstream-shaped error payloads | source: `langgraph/prebuilt/tool_node.py:743-757` | a custom tools node over `tool_messages` |
| F14 | the kit is synchronous; under `ainvoke` LangGraph runs sync nodes in an executor | test: `test_graph_runs_under_ainvoke` | no async twins needed; node timeouts exist only for async nodes (`langgraph/graph/state.py:714-722`, source) |
| F15 | LangGraph does not serialize two runs of one thread, and the kit's one maintenance lane per session needs that | source; `multitask_strategy` names at `langgraph_sdk/schema.py:81-87` | one run per thread at a time; under LangGraph Server `reject` or `enqueue` keep the lane, `interrupt` cancels a running `maintain` (which records nothing), `rollback` leaves a written daily append behind, so its flush repeats (Server semantics from its docs, unverified: langgraph-api is not installed) |
| F16 | the kit needs a stable session key; a thread id is one, and the quickstart's upstream-shaped `agent:main:main` is another shape | test: `test_session_key_mapping_names_the_session`; `test_two_threads_on_one_graph_and_kit_are_separate_sessions` (own key, id and flush cycle per thread on one graph and kit; `/new` in one leaves the other's state as it was) | `build_graph(session_key=...)`, default the thread id (L2) |
| F17 | a failed turn leaves its user message in `messages` without a reply | test: `test_failed_model_call_commits_no_session_state` | `graph.invoke(None, config)` reruns the failed node; the next message otherwise follows the unanswered user message (after F26's repair when the failure was in `tools`) |
| F18 | `bind_tools(strict=True)` makes every parameter of the kit's tools required (`memory_search`'s `maxResults`, `minScore` and `corpus`, `memory_get`'s `from`, `lines` and `corpus`, the curation tools' optional `section` and `supersede`), which changes what the model must send | probe: `convert_to_openai_tool(tool, strict=True)` on `kit.tools()`; test: `test_tools_are_bound_without_strict_mode` | the example binds without `strict`; strict mode would need nullable optional parameters in the kit's schemas |
| F19 | langchain-core allows a tool call with `id: None`, but a `ToolMessage` needs a string id | probe (design review); test: `test_tool_messages_reject_a_call_without_an_id` | `tool_messages` raises `ValueError` before dispatching anything: a provider or host error; the next model call's repaired copy drops the call (F26) |
| F20 | a stream consumer that stops after the reply cancels `maintain`, and a node reruns on resume, so a crash inside a flush turn repeats its appends | source (LangGraph run semantics) | drain the stream (the example does); the repeat is documented, no dedupe |
| F23 | `memory_core/client.py` imported the LangGraph adapter at module level, so the adapter could not import `memory_core.host` (`host -> host.flush -> client -> adapters -> host` failed) | probe (design review) | fixed by the recall removal; `test_the_adapter_and_the_package_import_in_either_order` guards it |
| F25 | LangGraph 1.x's default `recursion_limit` is 10,007 steps (`langgraph/_internal/_config.py:32`), not langchain-core's 25, so it does not bound a model that keeps asking for tools: about 5,000 model calls, each with a longer context, before `GraphRecursionError` | test: `test_tool_rounds_are_bounded_and_the_last_call_has_no_tools` (before the fix it ran into the limit after 161 s) | the example's `MAX_TOOL_ROUNDS` (6): the next call gets no tools, and a reply that still asks for tools fails the turn (`test_a_reply_that_asks_for_tools_past_the_bound_fails_the_turn`) |

### Worked unchanged

`kit.tools()` and `FlushRequest.tools` bind through `bind_tools` as they are; LangChain chat
models take `FlushRequest.messages` (role dicts) as they are; the kit's payloads go back as
`json.dumps(payload, ensure_ascii=False)`, which a `"tool"` role dict carries into a
`ToolMessage` with its `status`; `SessionState.to_json()` round-trips through the checkpointer,
also under a strict serializer; the sync kit runs under `ainvoke`; `/new` keeps the session key
and starts a new flush cycle; a restart over the same saver continues the thread
(`test_session_state_survives_in_the_checkpointer`).

### Decisions (Doruk, 2026-09-29)

L1-L9 as recommended (Design › Open questions); L11: `build_graph` requires
`context_window_tokens`. L10: the kit changes the findings recommend (F2 with F3, F7, F12, F21,
F22, F24, F26, and the F1 line) follow on their own branch, since each changes the kit's contract.
They were built on `feat/kit-langgraph-fixes` on 2026-09-29 (`9b90245`..`7e1d23b` and the docs
after it; docs/host_kit.md › LangGraph findings), each of that spec's open questions K1-K7 as
its recommendation, K3 as the recorded decision `f2351d5`; Doruk has not answered K1-K7 yet.

## Design (2026-09-29)

Status: specification and TDD plan, written 2026-09-29 on `feat/langgraph-agent` (from `main`
`79a1b5c`), revised after review the same day (`8bf7586` is the first draft, `f43756b` the
revision), then implemented on the branch (Tasks 1-9, `06b3c0c` onwards); "As built" marks
where the implementation differs from the plan. The host kit contract is docs/host_kit.md;
this design adds no kit behaviour. Since the kit changes of L10 (`feat/kit-langgraph-fixes`,
2026-09-29) Who owns what, Parity labels, Graph shape, State schema, Kit calls per node, Flush
handling, `/new` and `/reset`, Error handling and Adapter surface describe the code after them;
the Test plan and the TDD tasks stay as planned, with notes.
Library facts were read from the installed sources of langgraph 1.2.12 (with
langgraph-checkpoint 4.2.0, langgraph-prebuilt 1.1.0 and langgraph-sdk 0.4.5), langchain-core
1.6.5 and langchain-openai 1.6.6; the ones marked "probe" were run against those versions.
Library citations are `<package>/<path>:<line>` in them; upstream anchors are OpenClaw v2026.9.6
(`/tmp/openclaw-head`).

### Goal

A LangGraph agent (a `StateGraph` with a checkpointer) whose memory runs entirely through
`memory_core.host.HostKit`: `before_turn` gives the system prompt and the tools, the model node
calls the host's chat model bound to those tools, a tools node answers every tool call with
`kit.dispatch`, a maintenance node calls `after_turn` after the reply and runs the flush turn of a
returned `FlushRequest` on the same model, and `/new` and `/reset` go through `on_new_session`.
It tests whether the kit's API is enough for a real framework host: whatever the graph needs
beyond the kit is adapter code (below) or a finding.

### Who owns what

| Piece | Where | Label |
| --- | --- | --- |
| state schema, nodes, edges, prompt assembly (`model_input`), both model calls (turn and flush), the flush tool loop, `/new` parsing, the session-key mapping, the checkpointer, streaming | `examples/langgraph_agent.py` (`build_graph`, `main`) | host code |
| message and usage conversion, answering tool calls, the tool-call repair of the model's copy of LangChain messages | `memory_core/adapters/langgraph.py` | adapter-only, framework-free |
| workspace, prompt, tools, dispatch, flush decision and write, session memory, the serializable turn that crosses nodes (`TurnState`), the tool-call repair over host rows (`repair_tool_calls`, composing two core ports) | `memory_core.host.HostKit` | kit (docs/host_kit.md) |

No node factory and no prebuilt agent (`create_memory_agent(kit, model)`): a factory that wires
the model node and the flush loop would own the agent loop and the tool loop, which adapters never
do (docs/package_boundary.md › Runtime Adapters; docs/host_kit.md, entry point 4). The example is
the template a LangGraph host copies, and every piece of glue it needs beyond the kit and the
adapter is listed in the Findings section at the top of this file (L8).

### Parity labels

The graph and the adapter are adapter-only; no matrix row claims `match` for them. The orders and
inputs they take from upstream come from the kit (docs/host_kit.md › Parity labels). Labelled
deviations of the example, beyond the kit's:

- The in-graph `maintain` node runs on the run's own path: `graph.invoke` returns after it, and it
  starts when the `agent` node's final reply is in state, not when the reply is delivered.
  Upstream schedules maintenance only after the delivery owner settles, and only for a completed,
  unaborted reply (`src/auto-reply/reply/agent-runner-maintenance.ts:69-71`, `ownerSettlement`).
- The `/new` and `/reset` parser is a simplification of upstream's (below).
- Every model call of a turn gets a repaired copy of `messages` (F26). Upstream repairs the
  replayed history once per attempt (`run/attempt-history-prepare.ts:78`), and tool rounds
  inside an attempt bypass that path (`run/attempt-stream.ts:243`); the per-call repair is a
  superset that leaves a well-formed round unchanged. A round the input repair rewrites (an
  invalid call without a valid name or without input, which the tools node answered) loses the
  call and its tool message in later calls' copies, where upstream sends the attempt's own
  round as it is; the turn's user message is found on the stored messages, so the reset prompt
  and the runtime context keep their place. The labelled gaps of the kit's repair
  (docs/host_kit.md › LangGraph findings › Parity labels) apply: no stop reason on host rows,
  content tool-call blocks and a legacy `function_call` neither read nor rewritten. Until
  `7e1d23b` the example removed such an AI message instead, a labelled deviation that is gone.
- `MAX_TOOL_ROUNDS` bounds a turn's tool loop and `MAX_FLUSH_TOOL_ROUNDS` the flush turn's
  (host policy, like the Lab's `MAX_TOOL_ROUNDS`, `demo/lab_tools.py:37`; upstream bounds no
  round count, and its rolling `tools.loopDetection` is off unless enabled,
  `src/config/schema.help.runtime.ts:430-431`).

The example opens its workspace FTS-only (`FeatureFlags(vector_search=False)`), as
`examples/quickstart.py` does; nothing in it is scripted or fake. The scripted chat model exists
only in the tests.

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
                               |          |                 .invoke(model_input(turn, messages, repair))
                               |          |  has_tool_calls(last)? (valid or invalid calls)
                               |     yes  |           no
                               |          v            \
                               +------- tools           +--> maintain ---> END
                                tool_messages(last,          kit.after_turn; for a FlushRequest
                                kit.dispatcher(session))     the flush turn on the same model
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
    memory_turn: NotRequired[dict | None]         # TurnState.to_json(), the turn in flight
    memory_reset: NotRequired[dict | None]        # ResetTurn.to_json() of a bare /new, for prepare
    memory_maintenance: NotRequired[dict | None]  # the last maintenance: the gate and the flush


@dataclass
class AgentContext:                    # the run context (context_schema)
    runtime_context: str | None = None  # the host's per-turn text (channel, sender)
```

- `messages` holds what upstream's transcript holds: user messages, replies, tool calls and
  results, and the reset turn's transcript row. Never the system prompt, the runtime context or
  the flush turn (docs/host_kit.md › Turn lifecycle: the host records "never the runtime-context
  block and never the flush turn").
- The input is the standard `{"messages": [HumanMessage(text)]}` (or `("user", text)`), so
  LangGraph clients that send messages work unchanged. `AgentContext` comes through
  `graph.invoke(..., context=AgentContext(...))` and reaches a node as `runtime.context`
  (`langgraph/runtime.py:125`). Without `context=` it is `None` (probe), and `prepare` then
  passes no runtime context.
- The run context itself is not checkpointed, but the turn's marker-wrapped runtime context and
  system prompt are: `memory_turn` holds them from `prepare` to `maintain` (F11).
- The `memory_*` keys hold JSON values only and `messages` holds LangChain messages, which are
  on the checkpoint serializer's safe list (`langgraph/checkpoint/serde/_msgpack.py:57`), so the
  state also loads under a strict serializer (`JsonPlusSerializer(allowed_msgpack_modules=None)`,
  `langgraph/checkpoint/serde/jsonplus.py:92-119`; Task 5 pins it).

### Kit calls per node

| Node | Kit call | Reads | Writes |
| --- | --- | --- | --- |
| `route_input` (conditional edge from START) | none | the last message | the next node |
| `new_session` | `kit.on_new_session(ending, command=, session_id=, transcript=transcript_rows(messages), text=, redactor=)` | `memory_session` (or a first `SessionState.new`) | `messages`: remove all, then the new session's first row; `memory_session`: `NewSession.session`; `memory_reset` for a bare command |
| `prepare` | `kit.before_turn(session, runtime_context=...)` with its per-turn ensure | `memory_session`, `memory_reset`, `runtime.context` (may be `None`) | `memory_turn`: `TurnState.from_context(context, reset=ResetTurn.from_json(memory_reset))`; `memory_reset`: `None`; `memory_session` only for a thread's first `SessionState.new` |
| `agent` | `kit.repair_tool_calls(rows, allowed_tool_names=<the offered tools' names>)` through the adapter's `repair_tool_calls`, then the host's model | `memory_turn`, `messages` | `messages`: the AI message |
| `tools` | `tool_messages(last, kit.dispatcher(turn.session))` | `memory_turn`, the last AI message | `messages`: one tool message per call |
| `maintain` | `kit.after_turn(turn.session, transcript=transcript_rows(messages), usage=turn_usage(last), context_window_tokens=, redact=)`; for a request `request.messages`, `.tools`, `.dispatch`, `.complete(session, error=, redact=)` | `memory_turn`, `messages` | `memory_session`, `memory_turn`: `None`, `memory_maintenance` |

Not wired, on purpose: `heartbeat_prompt` (it needs the host's scheduler; L7), `request_flush`
(a memory-core extension with no upstream counterpart; the example has no `/flush`) and
`SessionState.after_compaction` (the example never compacts; F9).

### SessionState persistence

- One LangGraph thread is one upstream session key. `build_graph` takes `session_key`, a mapping
  from the thread id (`config["configurable"]["thread_id"]`, required) to the key, by default
  the thread id itself (L2, F16). A host that wants upstream-shaped keys passes, for example,
  `lambda thread: f"agent:main:{thread}"`. The key stays across `/new`
  (docs/host_kit.md › `SessionState`); `/new` rotates `session_id` inside the thread. The first
  run of a thread (no `memory_session` yet) starts `SessionState.new(session_key=..., session_id=<new
  id>)` in `prepare` or `new_session` and commits it at once, so a failed first turn keeps its
  session id. `build_graph` takes the id generator (`uuid4` text by default), so tests are
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
  maintenance order (docs/host_kit.md, entry point 4), with the deviation named under Parity
  labels. A streaming host (`graph.stream(..., stream_mode="updates")`) gets the reply from the
  `agent` update before `maintain` starts; `graph.invoke` returns only after `maintain`, so an
  invoke-only host waits for a due flush's model call (F6).
- The `FlushRequest` is created and completed inside `maintain`: it holds the workspace's
  `Memory` and its appends, so it does not cross a checkpoint. Detached maintenance needs no kit
  change (F6, L3); the example keeps the in-graph node. The flush turn, in host code:

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
    except Exception as error:  # the reply is already in state; a failed flush is a strike
        return request.complete(session, error=error, redact=redact)
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
  as a success with what it appended. The agent's own tool loop is bounded by
  `MAX_TOOL_ROUNDS` (Error handling), not by LangGraph's `recursion_limit` (F25).
- `session` is `record.session`: maintenance runs inside the turn's run, so it is the current
  state. `complete` stamps the compaction cycle, so the next due turn reads `already_flushed`
  until `/new` (docs/host_kit.md › Turn lifecycle, known gap; F9).
- `context_window_tokens` is a `build_graph` argument. `main` takes the model's
  `profile["max_input_tokens"]` when LangChain knows it (read with `getattr(model, "profile",
  None)`: a beta field; 128,000 for `gpt-4o-mini`, none for OpenRouter-style names such as
  `openai/gpt-4o-mini`; probe), else the required `--context-window` input, and prints the window
  and its source. `main` never falls back to the kit's 200,000 default, which for a 128,000-token
  model puts the threshold (176,000) above the window, so the flush would never run (F12). As
  built, a given `--context-window` wins over the profile, and `build_graph` requires the window
  (L11): it has no default.
- `transcript_bytes` is not passed: a checkpointer has no session file, so the transcript-size
  gate stays off (F10, L9).
- `memory_maintenance` is `{"flush": <decision reason>, "tokenCount": <the gate's token count or
  None>, "threshold": <the gate's threshold or None>, "window": <context window>, "target": <path
  or None>, "wrote": <entries appended>, "failure": <{"error", "failureCount", "exhausted"} or
  None>}`, so the gate and the flush show in the `updates` stream and in
  `graph.get_state(config)`. The failure's `error` is the redacted, truncated message (`redact`
  below).
- `build_graph` takes the host's `redact` (passed to `request.complete(error=..., redact=...)`
  and to `after_turn(redact=...)` for a flush target that cannot be created, F21) and
  `redactor` (passed to `on_new_session`, which stores the ending session's raw recent lines
  unless it maps them). Both default to none, as in the kit.
- Skipped on purpose, as upstream skips maintenance for them: a heartbeat run (upstream skips by
  run, `context.isHeartbeat`, `agent-runner-maintenance.ts:27`; the kit skips by session kind,
  and this thread's kind is always `main`, so a future heartbeat entry must bypass `maintain`;
  `HeartbeatRun.complete` already records the usage) and a turn that compacted (upstream
  `autoCompactionCount > 0`, `:31`: a host that summarizes history in a turn skips `maintain`
  for it and calls `SessionState.after_compaction`; F9).

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
  `_recent_message_lines`), a new session id, `text` and the host's `redactor`. It returns
  `messages` = `[RemoveMessage(id=REMOVE_ALL_MESSAGES), first]`, which drops everything before
  the marker (`langgraph/graph/message.py:38`, `:212-213`), so the thread's `messages` become the
  new session's transcript.
  - Bare command: `first` is `HumanMessage(reset.transcript_prompt)` and `memory_reset` is
    `reset.to_json()`. `prepare` puts it in the `TurnState` (`reset`), and `model_input` gives
    the turn's active user message `reset.model_prompt` while its text is the reset row
    (upstream's `installModelPromptTransform` guard), so every model call of that turn gets
    `[startup context, reset prompt]` while the transcript keeps the identity's reset row
    (`format_session_reset_transcript_prompt`); later turns replay only the row, as upstream
    (docs/host_kit.md, entry point 5).
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
| `MAX_TOOL_ROUNDS` (6) model calls with tool calls in one turn | `agent` | the next model call gets no tools; a reply that still asks for tools raises `RuntimeError` and is not stored, so every call in `messages` keeps its tool message: a failed turn (F25) |
| a tool call the model got wrong (bad params, invalid JSON, unknown tool, refused write) | `tools` | the kit's error payload as a tool message with `status="error"`; never raises |
| a tool call without a string id (valid or invalid) | `tools` | `tool_messages` raises `ValueError`: a provider or host error (a `ToolMessage` needs the id, and langchain-openai would send the id-less call back; F19); `graph.invoke(None, config)` reruns the failure, and the next message works, since its model calls get a repaired copy without the call (F26) |
| `kit.dispatch` raises (`OSError`), or the process stops between `agent` and `tools` | `tools` | the run raises (or stops) with the AI message's calls unanswered; `graph.invoke(None, config)` reruns `tools`, or the next message's model calls get a repaired copy with upstream's synthetic error result for each unanswered call (F26) |
| `after_turn` raises (`OSError`) | `maintain` | the run raises after the reply is in `messages`; `memory_session` keeps the previous snapshot |
| the flush target cannot be created | `maintain` | `TurnRecord.flush_failure`: one strike in `memory_session`, named in `memory_maintenance` |
| the flush model call raises (`Exception`) | `maintain` | `request.complete(session, error=exc, redact=redact)`: one strike (three mark the cycle); the run completes |
| the flush run is cancelled (`BaseException`) | `maintain` | not completed (upstream records nothing for a cancelled flush); propagates |
| `on_new_session` raises | `new_session` | the run raises; `messages` and `memory_session` stay the old session's (plus the command row); if the save succeeded and the ensure after it failed, a retry saves a second file (`-2` suffix) |

- LangGraph applies the input before the first node, so a failed turn leaves its user message in
  `messages` without a reply (probe: after a failing node, `get_state` shows the message and the
  earlier node's writes). The host resumes the failed node with `graph.invoke(None, config)`
  (probe: the failed node reruns, the earlier ones do not) or sends the next message, which then
  follows the unanswered user message (F17). A failure in or before `tools` also leaves an AI
  message whose tool calls have no tool message, which a provider rejects; the stored messages
  keep it, and every later model call gets the repaired copy (F26).
- Model-caused errors never raise out of the kit; host programming errors do (docs/host_kit.md ›
  Errors). The adapter keeps that split: an invalid tool call without a name is dispatched with
  `""`, so the model gets an error payload, not the host a `TypeError`.
- Lane and resume edges (F20): a stream consumer that stops iterating after the reply (a `break`,
  a closed connection) closes the run, so `maintain` never completes; the host drains the stream.
  A node reruns on resume, so a crash in the middle of a flush turn repeats its appends when the
  run resumes. Under LangGraph Server the `multitask_strategy` of a run
  (`langgraph_sdk/schema.py:81-87`: `reject`, `interrupt`, `rollback`, `enqueue`) decides the
  lane; from the Server docs, unverified here (langgraph-api is not installed): `reject` and
  `enqueue` keep one run per thread, `interrupt` cancels a running `maintain` (which records
  nothing, correctly), and `rollback` deletes the interrupted run's checkpoints but not a daily
  append already written, so that flush repeats.

### Adapter surface

`memory_core/adapters/langgraph.py` stays framework-free: it imports only `memory_core` and the
standard library, reads LangChain messages by duck typing (`type`, `content`, `id`, `tool_calls`,
`invalid_tool_calls`, `usage_metadata`) and builds plain dicts, which LangChain's `add_messages`
and chat models convert (`langchain_core/messages/utils.py:679`: a `"tool"` role dict becomes a
`ToolMessage` with its `status`; probe). So the core keeps `httpx` as its only dependency, and
`tests/unit/test_packaging.py::test_core_dependencies_are_exactly_what_memory_core_imports`
stays as it is. It imports `memory_core.host`, which works only once `memory_core/client.py`
stops importing the adapter at module level (the chain `host -> host.flush -> client ->
adapters.langgraph -> host` fails with `ImportError: cannot import name 'Memory' from partially
initialized module`; probe): Task 2 removes that import with the recall helper, before any adapter
code lands.

```py
def transcript_rows(messages: Iterable[Any]) -> list[dict[str, Any]]:
    """The kit's transcript rows of LangChain messages (objects or their dict forms).

    human -> user, ai -> assistant, tool -> tool (with tool_call_id and name), system -> system,
    a chat message -> its role; the content as it is (a string or content blocks, whose text
    blocks the kit reads). A role dict is copied, a LangChain type dict ({"type": "human", ...})
    is read like the object; no row carries a "type" key, since the session-memory hook reads a
    mapping with one as a raw transcript entry (memory_core/session_memory.py:256-263) and would
    drop it. ValueError for an unknown message type. after_turn and on_new_session keep only the
    text of user and assistant rows."""

def turn_usage(message: Any) -> TurnUsage | None:
    """TurnUsage(prompt_tokens=usage_metadata["input_tokens"],
    completion_tokens=usage_metadata["output_tokens"]) of an AI message, else None."""

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
    status is "error" for the kit's error payload. ValueError for a call whose id is not a
    string. Pass kit.dispatcher(turn.session) for a turn, FlushRequest.dispatch for a flush."""

def repair_tool_calls(
    messages: Iterable[Any],
    repair: Callable[[Sequence[Mapping[str, Any]]], ToolCallRepair],
) -> list[Any]:
    """The messages with upstream's replay repair of their tool calls, for the next model call.

    repair is kit.repair_tool_calls (or a function passing it allowed_tool_names). An unchanged
    message comes back as the original object, a changed AI message as a copy with only its kept
    calls (tool_calls, invalid_tool_calls and additional_kwargs["tool_calls"] filtered), a tool
    message without an id that the kit paired with its frame's only call as a copy with that
    call's id and status "error", and a missing result as a synthetic tool dict with the call's
    name and status "error". The host keeps its stored messages as they are."""
```

- Prompt assembly stays host code: the example's `model_input(turn, messages, repair)` sends
  the system prompt and then the repaired copy of `messages`, whose active user message (found
  on the stored messages, then in the copy by identity, as upstream fixes its target prompt
  once per turn) gets `turn.reset.model_prompt` under upstream's guard on a reset turn. As built,
  the runtime context goes in as a user message immediately before the turn's user message, where
  upstream keeps its carrier (F22); the plan had it as a second system message before the history, which
  is where the kit's lifecycle diagram listed it until the kit docs were fixed (F22).
- Tool schemas need no mapping: `bind_tools` takes `kit.tools()` and `FlushRequest.tools`
  unchanged, since a dict with a `name` is read as an OpenAI function
  (`langchain_core/utils/function_calling.py:432`; probe with `ChatOpenAI.bind_tools`).
- `tool_messages` and `has_tool_calls` exist because LangGraph's `tools_condition` routes only on
  `tool_calls` (`langgraph/prebuilt/tool_node.py:1657`) and `ToolNode` never answers
  `invalid_tool_calls`, while langchain-openai sends those back to the provider as tool calls
  (`langchain_openai/chat_models/base.py:490-496`), each of which then needs a tool message; and
  because `ToolNode` wants `BaseTool`s whose argument validation would replace the kit's
  upstream-shaped error payloads (F4, F13).
- The turn in flight is the kit's `TurnState`, because `TurnContext` holds a `WorkspaceContext`
  and is not serializable while the model node and the tools node run in separate supersteps
  (F2), and because the reset turn's two prompts have to share one `messages` list (F3). The
  adapter's `PendingTurn` did this until `76dfdd7`.
- `repair_tool_calls` exists because the kit's repair takes chat-completions rows, while a
  LangChain AI message carries its calls in `tool_calls`, `invalid_tool_calls` and
  `additional_kwargs["tool_calls"]` (langchain-openai sends the last when both lists are empty,
  `langchain_openai/chat_models/base.py:490-498`), so a copy without a dropped call must filter
  all three (F26).
- `memory_core/adapters/__init__.py` exports these five names; the package root has 26 since
  the kit changes (`TurnState`, `ToolCallRepair`).

### Fate of `LangGraphMemoryRecall`

Decision (Doruk, 2026-09-29, L1): remove it in 0.2.0
(still unreleased), with `format_memory_context` and `Memory.langgraph_recall`. Reasons:

- It injects search results into the prompt, which upstream never does; the same reason removed
  `Memory.prepare_turn` in 0.2.0 (docs/host_kit.md › `Memory.prepare_turn`, `Memory.chat`,
  `Memory.record_turn`: removed). This design is the upstream shape for a LangGraph host.
- It does not work with LangGraph's own message state: it reads only `Mapping` messages with
  `role == "user"` (`memory_core/adapters/langgraph.py:80-83` at `79a1b5c`), so a `MessagesState` of
  `HumanMessage` objects recalls nothing (probe: `{'memory_context': '', 'memory_results': []}`
  for a query whose dict form finds the hit).
- It drops the `disabled`, `warning` and `action` of an unavailable or paused search
  (docs/memory_search_tool.md), so a paused index goes unnoticed.
- Its module-level import in `memory_core/client.py` is what blocks the adapter from importing
  the host kit (above).
- Nothing is published ("Nothing is published to a package index yet", CHANGELOG.md), so a
  deprecation cycle would protect no user, and a labelled legacy helper would keep a broken,
  non-upstream method on the `Memory` handle.

Breaking change for 0.x, recorded in CHANGELOG.md › Removed, with the "Moved out of the package
root" table losing its row (154 to 152 names) and the counts next to it: `LangGraphMemoryRecall`
and `format_memory_context` (from `memory_core.adapters.langgraph` and `memory_core.adapters`) and
`Memory.langgraph_recall()`. Replacement: this integration; a host that still wants auto-recall
calls `Memory.search` itself and labels it. The removal reverses docs/host_kit.md's line
(2026-09-28) that the helper "stays as an explicit, labelled adapter-only auto-recall", and Doruk
confirmed it (L1, 2026-09-29). It changes `memory_core/client.py`,
outside `memory_core/adapters/`, so Task 9 runs the oracle suite.

### Dependencies

- `[project.optional-dependencies] langgraph = ["langgraph>=1.2", "langchain-core>=1.6"]`: what
  `examples/langgraph_agent.py` imports besides a provider, and the stack the adapter's duck
  typing is tested against. The lower bounds are the tested minor versions (1.0 and the model
  `profile` field are untested). The adapter imports neither, so the extra pins the tested stack
  and gives LangGraph hosts one install line; it is not a code dependency (L5).
- The provider stays out of the extra (the host picks its model). The example uses
  `langchain-openai` for any OpenAI-compatible endpoint, installed next to the extra
  (`pip install "memory-core[langgraph]" langchain-openai`).
- `[dependency-groups] dev`: `memory-core[demo]` stays as it is, and `memory-core[langgraph]` and
  `langchain-openai>=1.6` are added as their own entries, so the offline tests import LangGraph
  and the live test runs in the checkout's environment. `scripts/rename_project.py` rewrites the
  `memory-core[demo]` entry through `_replace_once` (`:424`) and its check expects that exact
  string in the dev group (`pyproject_problems`, `:590`), so a merged `memory-core[demo,langgraph]`
  would fail both `--check` and `--to`; Task 1 extends `rewrite_pyproject` and
  `pyproject_problems` to the `langgraph` entry, with their tests.
- `uv.lock` relocked with `uv lock`. On the design day the resolver picked langgraph 1.2.12,
  langgraph-checkpoint 4.2.0, langgraph-prebuilt 1.1.0, langchain-core 1.6.5 and
  langchain-openai 1.6.6; the lock records what it resolves when Task 1 runs.
- `tests/unit/test_packaging.py`: the extras are `{"demo", "langgraph"}`, the dev group has its
  new members, and a subprocess check shows that importing `memory_core.adapters.langgraph`
  loads no `langchain_core`, `langgraph` or `openai` module.

### Findings so far

The design-time table (F1-F21) became the Findings section at the top of this file, with the
same numbers, the evidence of the implementation and F22-F26.

### Test plan

The offline tests drive the real compiled graph of `examples/langgraph_agent.py:build_graph` with
`ScriptedChatModel`, a test-only `BaseChatModel` subclass whose `bind_tools` returns
`self.bind(tools=...)` and whose `_generate` answers from a per-test script and records each
call's messages and bound tool names. Neither LangChain fake (`FakeMessagesListChatModel`,
`GenericFakeChatModel`, `langchain_core/language_models/fake_chat_models.py:21, 227`) implements
`bind_tools` (the base raises `NotImplementedError`,
`langchain_core/language_models/chat_models.py:2366-2383`). Workspaces are
FTS-only with a fixed kit clock (`now_ms`), UTC and a fixed id sequence; the checkpointer is
`InMemorySaver`, which serializes every value it stores. Modules that need LangGraph start with
`pytest.importorskip`. The tools node's dispatch is exactly
`functools.partial(kit.dispatch, session=turn.session)` (as planned; since `76dfdd7`
`kit.dispatcher(turn.session)`).

`tests/unit/test_langgraph_adapter.py` (rewritten; the recall tests go with Task 2):

- `test_transcript_rows_map_langchain_types_to_kit_roles`
- `test_transcript_rows_keep_content_blocks_and_copy_role_dicts`
- `test_transcript_rows_read_type_dicts_and_never_emit_a_type_key` (a type dict's row reaches the
  session-memory file)
- `test_transcript_rows_reject_an_unknown_message_type`
- `test_turn_usage_reads_usage_metadata`
- `test_turn_usage_without_usage_metadata_is_none`
- `test_has_tool_calls_counts_invalid_calls`
- `test_tool_messages_answer_every_call_through_dispatch`
- `test_tool_messages_answer_invalid_calls_with_the_kit_error_payload`
- `test_tool_messages_mark_error_payloads_and_convert_to_tool_messages`
- `test_tool_messages_reject_a_call_without_an_id`
- `test_pending_turn_round_trips_json`, `test_pending_turn_from_json_rejects_a_bad_shape` and
  `test_pending_turn_needs_both_reset_fields`, removed with `PendingTurn` in `76dfdd7`
  (`tests/unit/test_host_kit_turn_state.py` covers `TurnState`); `7e1d23b` added the four
  `test_repair_tool_calls_*` tests

`tests/unit/test_packaging.py`: `test_demo_and_langgraph_are_the_only_extras_and_dev_tools_a_group`
(replaces `test_demo_dependencies_are_the_only_extra_and_dev_tools_a_group`),
`test_importing_the_langgraph_adapter_loads_no_framework`, and
`test_the_adapter_and_the_package_import_in_either_order` (subprocesses importing
`memory_core.adapters.langgraph` first, and `memory_core` first).
`tests/unit/test_project_name.py`: the hand-edit test lists the `langgraph` dev entry too, and the
probe rename rewrites it.

`tests/unit/test_langgraph_agent.py` (end to end):

- `test_turn_offers_the_kit_tools_and_answers_memory_search`: the bound tool names are
  `kit.tools()`'s, the tool message carries `kit.dispatch`'s payload, and the reply ends the run.
- `test_system_prompt_comes_from_before_turn_and_stays_out_of_the_transcript`
- `test_runtime_context_reaches_the_model_and_is_optional`: with `context=AgentContext(...)` the
  marker-wrapped block reaches the model; without `context=` the turn runs.
- `test_due_flush_runs_after_the_reply_and_writes_the_daily_file`: usage past the threshold; the
  `agent` update streams before the flush model call; `memory/<date>.md` holds the fact;
  `memoryFlush` is stamped; `messages` hold no flush message; `memory_maintenance` shows the
  token count and the threshold.
- `test_flush_turn_is_restricted_to_the_write_tool_and_not_streamed`: bound tools `["write"]`,
  model input equal to `FlushRequest.messages`, no `messages`-mode chunk from `maintain`, and
  (positive control) the `agent` reply does appear in `messages` mode.
- `test_second_turn_finds_the_flushed_fact`: `memory_search` returns the daily file with its
  citation.
- `test_second_turn_past_the_threshold_reads_already_flushed` (the kit's known gap, pinned)
- `test_session_state_survives_in_the_checkpointer`: a second graph over the same saver continues
  the thread; `memory_session` reads back with `SessionState.from_json`.
- `test_state_loads_under_a_strict_serializer`: the same turn over
  `InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=None))`.
- `test_graph_runs_under_ainvoke`
- `test_invalid_tool_call_gets_the_kit_error_payload`
- `test_tools_are_bound_without_strict_mode` (F18)
- `test_bare_new_saves_session_memory_and_runs_the_reset_turn`: `memory/<date>-<slug>.md`
  exists; `messages` are the reset row (compared against
  `format_session_reset_transcript_prompt("new", MEMORY_CORE_RUNTIME_IDENTITY)`, not a literal)
  and the reply; the model got `ResetTurn.model_prompt`.
- `test_new_keeps_the_session_key_and_rotates_the_session_id`
- `test_session_key_mapping_names_the_session`
- `test_new_with_text_starts_the_new_session_with_that_text`
- `test_reset_prompt_is_not_replayed_on_the_next_turn`
- `test_failed_model_call_commits_no_session_state`: the run raises, `memory_session` is
  unchanged, and `graph.invoke(None, config)` resumes the turn.
- `test_failed_flush_turn_records_a_strike_and_keeps_the_reply`
- `test_redact_and_redactor_reach_the_kit`: the failure's message in `memory_maintenance` is
  redacted, and the session-memory file holds the redactor's lines.
- `test_example_main_requires_the_model_environment`: without `OPENAI_API_KEY` or
  `OPENAI_MODEL`, `main` exits with a message naming them, before any network call.
- `test_example_main_requires_a_window_the_profile_does_not_give`
- `test_stream_usage_decides_whether_a_custom_endpoint_reports_usage` (F5): `ChatOpenAI` against
  a local stub OpenAI-compatible endpoint (127.0.0.1, no network) under `stream_mode="messages"`;
  without `stream_usage=True` the request carries no `stream_options` and `memory_maintenance`
  reads `missing_tokens`; with it the gate gets the usage.

`tests/integration/test_langgraph_agent_live.py`:
`test_live_langgraph_agent_flushes_and_recalls_across_new`, skipped unless
`MEMORY_CORE_LIVE_OPENAI=1`, `OPENAI_API_KEY` and `OPENAI_MODEL` are set (`OPENAI_BASE_URL`
optional; L4). It runs the example's graph on `ChatOpenAI` with `stream_usage=True` and a
`context_window_tokens` whose flush threshold is 1 token (computed with the flush plan's
functions), so every turn with real usage is due. Turn 1 states a random codename: the test
asserts that real usage reached the kit, the decision `token_threshold`, the stamped cycle and the
codename in the daily file whose path it reads from `memory_maintenance["target"]`. After `/new` a
later turn asks for the codename: the test asserts it in the reply and names the path it came by
(a `memory_search` or `memory_get` result, or the reset turn's startup context). A real model can
vary; each assertion names the step that differed.

`tests/unit/test_examples.py`: `test_langgraph_doc_example_runs_without_an_embedder` goes with
Task 2. Task 8 adds the doc drift tests to `tests/unit/test_langgraph_agent.py`, next to the
scripted model: `test_langgraph_doc_usage_runs_the_graph` (the Usage code block runs with a
scripted model in place of `ChatOpenAI`) and `test_langgraph_doc_lists_the_adapter_exports`.

As built, beyond the plan: `test_a_command_that_is_not_first_word_is_an_ordinary_message`,
`test_redact_maps_a_flush_target_failure`,
`test_example_main_chats_against_an_openai_compatible_endpoint` (the whole `main` loop against
the local stub), and after review `test_tool_rounds_are_bounded_and_the_last_call_has_no_tools`
and `test_a_reply_that_asks_for_tools_past_the_bound_fails_the_turn` (F25) and
`test_next_message_after_a_failed_tools_node_drops_the_unanswered_call` (F26;
`..._repairs_the_unanswered_call` since `7e1d23b`) and
`test_two_threads_on_one_graph_and_kit_are_separate_sessions` (F16), and for `main`
`test_example_main_exits_cleanly_at_the_end_of_input` and
`test_example_main_reports_a_failed_turn_and_goes_on`. The live test's code was dry-run once against a scripted local endpoint in a
scratch directory; it has not run against a real model on this branch.

### TDD tasks

Each task: tests first (watch them fail), implement, run the offline suite (baseline at
`79a1b5c`: 1347 passed, 311 skipped), `ruff check . --no-cache` and
`scripts/rename_project.py --check`, then commit that task alone.

1. Dependencies: `pyproject.toml`, `uv.lock`, `tests/unit/test_packaging.py`,
   `scripts/rename_project.py` (`rewrite_pyproject`, `pyproject_problems`) and
   `tests/unit/test_project_name.py`.
2. Remove `LangGraphMemoryRecall`, `format_memory_context` and `Memory.langgraph_recall` (L1)
   first, since the adapter cannot import the host kit while `memory_core/client.py` imports it:
   `memory_core/adapters/`, `memory_core/client.py`, `tests/unit/test_client.py`,
   `tests/unit/test_public_api.py` (`Memory`'s methods, the changelog table count),
   `tests/unit/test_langgraph_adapter.py`, `tests/unit/test_examples.py`, CHANGELOG.md (Removed,
   the table, the counts), the legacy sections of this file, and the mentions in README.md,
   docs/package_boundary.md, docs/memory_search_tool.md and docs/host_kit.md.
3. Adapter conversions: `transcript_rows`, `turn_usage`, `has_tool_calls` and `tool_messages` in
   `memory_core/adapters/langgraph.py` and its exports; their tests and the import-order
   subprocess test.
4. `PendingTurn`: the same files; its three tests (removed in `76dfdd7`, L10).
5. The graph: `examples/langgraph_agent.py` (`AgentState`, `AgentContext`, `model_input`,
   `build_graph` with `prepare`, `agent`, `tools` and `maintain`) and
   `tests/unit/test_langgraph_agent.py` (the turn, runtime-context, flush, second-turn,
   checkpointer, strict-serializer, `ainvoke`, invalid-call and strict-mode tests).
6. `/new`, `/reset` and failures: `route_input`, `new_session`, the reset substitution, the
   session-key mapping, `redact` and `redactor`, and their tests.
7. `main` and the live test: the env-driven terminal loop (it streams `updates`, prints the reply
   before maintenance, sets `stream_usage=True`, takes the window from the profile or
   `--context-window` and prints it with its source),
   `tests/integration/test_langgraph_agent_live.py`, the offline `main` tests and the F5 stub
   check.
8. Docs: this file rewritten for the host-kit path with the findings section (as confirmed);
   README.md (the Python API snippet loses `langgraph_recall`, the pointer names the agent);
   docs/package_boundary.md › Runtime Adapters; docs/parity_matrix.md audit note 23
   (adapter-only, no row changes) with `tests/parity/test_parity_matrix_evidence.py`;
   CHANGELOG.md › Added (the adapter helpers, the extra, the example); the doc drift test.
9. Verify: the full offline suite, ruff, the name check, and the oracle suite
   (`OPENCLAW_ORACLE_REPO=/tmp/openclaw-head` with Node 24, since Task 2 changed
   `memory_core/client.py`; reference 254 passed, 81 xfailed, 2 skipped, 0 failed of 337). The
   measured numbers go into the commit body and this file. The main session runs the live test.
   As built: measured in Usage › Tests; the oracle ran at `7388ea0` (after Task 7), since the
   docs of Task 8 change no code it runs.

### Open questions for Doruk

Answered on 2026-09-29: every recommendation taken; L11 made `context_window_tokens` required;
L10's kit changes follow on their own branch (Decisions, at the top).

- L1. Remove `LangGraphMemoryRecall`, `format_memory_context` and `Memory.langgraph_recall` in
  0.2.0 (recommended, above), or keep them as a labelled legacy helper, fixed to read LangChain
  messages, with the import moved into the method? Removal reverses docs/host_kit.md's line of
  2026-09-28.
- L2. One thread per session key with `/new` rotating the session id inside the thread
  (recommended), or one thread per session id, the host switching threads on `/new`? And the key's
  default: the thread id (recommended) or an upstream-shaped `agent:main:<thread>`?
- L3. The flush in an in-graph `maintain` node (recommended for the example: every flush lands
  in its run's updates, and a streaming host delivers the reply first; `invoke` waits), or
  detached host-side maintenance (closer to upstream; no kit change, a per-thread future that the
  next run's `prepare` waits for)? The same choice is open for the Lab as docs/host_kit.md Q13.
- L4. The live test requires `OPENAI_MODEL` and skips without it (recommended: memory-core picks
  no model for the host), or it gets a default model, and which one?
- L5. The `langgraph` extra holds `langgraph` and `langchain-core` only (recommended), or
  `langchain-openai` too?
- L6. `/new` parsing stays a labelled host simplification in the example (recommended for this
  stage), or a subset of upstream's `resolveSessionResetCommand` is ported into core first, with
  its own oracle op?
- L7. Heartbeat stays out of this agent (recommended: it needs the host's scheduler), or the
  graph gets a heartbeat entry now (which bypasses `maintain`)?
- L8. No node factory or prebuilt agent (recommended: it would own the loop), or a labelled
  `create_memory_agent(kit, model)` convenience?
- L9. The transcript-size gate stays off (recommended), or the example passes the Lab's labelled
  JSON-size estimate of `messages`?
- L10. Which kit changes from the Findings to take (none is made on this branch): a JSON form of
  a turn with the reset prompt (F2, F3), `redact` on `after_turn` (F21), the runtime-context
  placement in the kit docs (F22), a session-bound dispatch (F24), a repair of unanswered tool
  calls over host messages (F26), and doc lines for
  `TAG_NOSTREAM` (F7), the default window (F12) and `SessionState` in framework state (F1).
- L11. Make `build_graph`'s `context_window_tokens` required, so an app that copies the graph
  cannot fall into the kit's 200,000-token default (F12), or keep the default for `None` with
  the docstring warning (as built)? Only `main` refuses the default today.
