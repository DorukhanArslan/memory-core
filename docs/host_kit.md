# memory-core host kit (`memory_core.host`)

Status: specification and TDD plan, written 2026-09-28 on `feat/host-kit` (from `main`
`b829bad`), revised after review the same day. Implemented on that branch the same night:
Tasks 1-8 and the kit parts of Task 10's docs. Task 9 (the Lab's flush, `/new` and heartbeat run)
followed Doruk's decisions of 2026-09-28 ("Decisions") and landed the same day (`7f78de1`,
`363d471`, `5ffee1c`, `ca54643`); the packaging stage (0.2.0) and the quickstart (README,
`examples/quickstart.py`) followed. Task 10's oracle re-run and the real-browser check of Task 9
are still open. Upstream anchors are OpenClaw v2026.9.6 (`eb377ac59e6`, checkout
`/tmp/openclaw-head`) unless a line says otherwise. The kit changes the LangGraph host's findings
recommend ("LangGraph findings (2026-09-29)" at the end) were built on `feat/kit-langgraph-fixes`
on 2026-09-29 (`14dbdcb`..`7e1d23b`): `TurnState`, `HostKit.dispatcher`, `after_turn(redact=)`
and `HostKit.repair_tool_calls`, with the doc lines below.

# Part 1: Specification

## Purpose

A host (a FastAPI or LangGraph chat app, a WhatsApp or Slack bot, an iOS backend, a voice
agent) today has to compose about twenty memory-core functions in the right order to get
OpenClaw memory behaviour: seed the workspace, render the bootstrap context, offer and run
the memory tools, decide and run the memory flush, save session memory on `/new`, build the
heartbeat turn. The Lab does exactly that in `demo/lab_*.py`, and a production host would have
to copy it. `memory_core.host` is that composition as a package API: six entry points on one
object per workspace, plus the small handles they return.

Rules the kit keeps:

- It only composes existing functions. No ported algorithm changes; every oracle result stays
  identical. Where the kit fixes an order or an input that upstream fixes (the post-reply flush,
  the flush run's tool set, the recall-tracking gate), it cites the upstream site.
- It never calls a model. Every model run (the turn, the flush turn, the heartbeat turn) is the
  host's; the kit returns what to send and takes back what came out.
- It keeps no per-session state. The host stores a small `SessionState` value next to its own
  session record and passes it in; the kit returns updated copies.
- It writes only through the existing write paths: `MemoryWorkspace.append_daily_memory` (under
  the shared per-file lock, see Thread safety), the curation tools behind
  `FeatureFlags.curated_memory_writes`, `save_session_memory`, the automation store, and the
  flush target's empty-file creation (`ensure_memory_flush_target_file`, entry point 4).

## Object model

### `HostKit`: one per workspace

```python
class HostKit:
    def __init__(
        self,
        memory: Memory,
        *,
        layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
        templates: Mapping[str, str] | None = None,
        seed_bootstrap: bool | None = None,
        timezone: str = "UTC",
        time_format: TimeFormat = DEFAULT_TIME_FORMAT,
        identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
        curation_policy: CurationPolicy | None = None,
        bootstrap_max_chars: int = DEFAULT_BOOTSTRAP_MAX_CHARS,
        bootstrap_total_max_chars: int = DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
        context_injection: ContextInjectionMode = "always",
        truncation_warning_mode: BootstrapPromptWarningMode = "always",
        dreaming_enabled: bool = False,
        automation_store: AutomationStore | None = None,
        now_ms: Callable[[], int] | None = None,
    ) -> None: ...

    @classmethod
    def open(
        cls,
        workspace_dir: str | os.PathLike[str],
        *,
        embedding_provider: EmbeddingProvider | None = None,
        config: MemoryConfig | None = None,
        **options,  # the keyword options of __init__
    ) -> HostKit: ...

    memory: Memory            # read-only
    curator: MemoryCurator    # read-only; the curator dispatch() uses
    def ensure(self) -> WorkspaceInitResult: ...
```

- Every option is an input some core function already takes:
  `layout`, `templates`, `seed_bootstrap` (`initialize_agent_workspace`); `timezone` and
  `time_format` (the flush plan, the curator's "today", the session-memory stamp, the startup
  context, the reset prompt and the heartbeat time line all take the one host value, as
  `memory_core/current_time.py` asks; recall tracking does not, see `dispatch`); `identity`
  (context markers, transcript rows); `curation_policy` (`MemoryCurator`, default
  `CurationPolicy.for_layout(layout)`); the bootstrap caps, `context_injection` and
  `truncation_warning_mode` (`build_workspace_context`); `dreaming_enabled` (recall tracking,
  see `dispatch`); `automation_store` (default `FileAutomationStore(root)`); `now_ms` (epoch-ms
  clock, as `MemoryCurator` takes it). The agent id is `memory.config.agent_id`. The Lab uses
  each of them except `identity` (memory-core's compat markers).
- `seed_bootstrap=None` (default) seeds BOOTSTRAP.md only when `templates` supplies the layout's
  bootstrap file. memory-core has no ritual text of its own, so an empty BOOTSTRAP.md would leave a
  host without a ritual in limited-mode "Bootstrap Pending" on every turn until `memory/`
  appears (decision Q4). `False` marks setup complete at once (the core extension);
  `True` seeds even an empty file. The Lab passes `True` with its templates.
- `__init__` does no I/O beyond validating the timezone and the curation policy against the
  layout (the curator is built there), so a host whose settings change (the Lab) builds a new
  kit per request.
- `ensure()` runs `initialize_agent_workspace(root, layout, templates, seed_bootstrap, now_ms)`:
  upstream runs `ensureAgentWorkspace` on every reply (`src/auto-reply/reply/get-reply.ts:443-448`),
  which is where BOOTSTRAP.md is reconciled away. `before_turn` runs it first (unless told not
  to); a host that writes workspace files between turns (the Lab editor) calls it after the write.
- `open` checks the store config first (`validate_store_config`, so a bad provider/flag
  combination leaves no file behind), builds `Memory.from_workspace(..., initialize=False,
  reindex=False)`, then the kit, then runs `ensure()` and one reindex. The order matters:
  `initialize_memory_core_workspace` writes MEMORY.md, which counts as setup evidence, so
  initializing `Memory` first would stop BOOTSTRAP.md from ever being seeded
  (`memory_core/bootstrap/lifecycle.py:initialize_agent_workspace` docstring). Store construction
  creates only `.memory-core/`, which is not setup evidence. A kit option that fails validation raises
  after the index file exists (a host error, not a model one).
- The default `MemoryConfig` is hybrid (`vector_search=True`), so `HostKit.open(root)` without an
  embedder raises in `validate_store_config` (fail closed). The zero-config FTS-only call is
  `HostKit.open(root, config=MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False)))`;
  the README Quickstart shows both (`examples/quickstart.py` opens FTS-only).
- Hosts that build their own `Memory` (the Lab, one store per search mode) use
  `HostKit(memory, ...)` with `Memory.from_workspace(..., initialize=False)` and call `ensure()`
  before any memory file is created.

### `SessionState`: one per session, stored by the host

```python
@dataclass(frozen=True)
class SessionState:
    session_key: str                 # upstream sessionKey; stays the same across /new
    session_id: str                  # upstream sessionId; new on /new and /reset
    kind: SessionKind = "main"       # main, group, channel, direct, heartbeat, subagent, cron
    entry: Mapping[str, Any] = ...   # read-only SessionEntry fields of the flush gate
    last_output_tokens: int | None = None
    seen_truncation_signatures: tuple[str, ...] = ()
    completed_bootstrap_turn: bool = False

    @classmethod
    def new(cls, *, session_key: str, session_id: str, kind: SessionKind = "main") -> SessionState
    def after_compaction(self, *, tokens_after: int | None = None) -> SessionState
    def to_json(self) -> dict[str, Any]
    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SessionState
```

- `entry` is upstream's `SessionEntry` subset as `memory_core.memory_flush` reads it:
  `sessionId`, `compactionCount`, `totalTokens`, `totalTokensFresh`, `totalTokensVersion`,
  `memoryFlush`. `new` starts it as `{"sessionId": ..., "compactionCount": 0}`. The state deep-copies
  `entry` on construction and exposes it read-only (`MappingProxyType`); the kit never mutates it
  and every state it returns carries its own copy, so two states never share a dict.
- `after_compaction` is upstream's `incrementCompactionCount` accounting
  (`src/config/sessions/session-entry-projection.ts:91-131` `projectCompactionAccountingPatch`):
  `compactionCount + 1`, and the token snapshot becomes stale (`totalTokensFresh: False`,
  `totalTokensVersion` removed) unless `tokens_after` gives the fresh post-compaction total. It is
  for hosts that compact or window their history; the kit itself never compacts.
- `to_json` / `from_json` round-trip exactly, so a host can keep the state in any store.
  `from_json` raises `ValueError` for a field of the wrong type, the entry's flush-gate fields
  included (numbers as integers, `totalTokensFresh` a boolean, `memoryFlush` an object; each
  may be null or absent), so a lax store cannot hand the kit a string `compactionCount`.
- A framework whose state must serialize keeps `to_json()` there and reads it with `from_json`
  in each step: a LangGraph checkpointer refuses the object itself (`TypeError: Type is not
  msgpack serializable: SessionState`). `TurnState` and `ResetTurn` carry a turn and a reset the
  same way (entry point 3; F1).

```python
@dataclass(frozen=True)
class TurnUsage:
    prompt_tokens: int | None        # the last model call's prompt size (upstream totalTokens)
    completion_tokens: int | None = None
```

A host without provider usage passes `None` (the token gate then reports `missing_tokens`,
as upstream without a fresh total) or its own estimate. The kit invents no estimate.

## Turn lifecycle

```text
Host step                                  Kit call, then what it composes (core)
---------                                  --------------------------------------
inbound user message
  before_turn(state, runtime_context)  ->  initialize_agent_workspace (ensure=True)
                                           build_workspace_context
                                           build_prompt_section
                                           build_runtime_context_system_context
  <- TurnContext(system_prompt, runtime_context, tools, session')
     (a host whose steps run apart keeps TurnState.from_context(context).to_json())
  model call (host): system_prompt, repair_tool_calls(history), runtime_context, user message
    each tool call:
    dispatch(name, args, session)      ->  execute_memory_search_tool (+ recall signals)
                                           execute_memory_get_tool
                                           MemoryCurator.dispatch (+ reindex)
    <- JSON payload, sent back to the model
  deliver the reply (host)
  after_turn(session', usage, ...)     ->  token snapshot
                                           build_memory_flush_plan
                                           explain_memory_flush_trigger
                                           ensure_memory_flush_target_file (flush due)
  <- TurnRecord(session'', flush_decision, flush)
  if flush: model run (host, detached, off the reply path) with flush.messages, flush.tools
    each tool call:
    flush.dispatch("write", args)      ->  locked append_daily_memory (+ reindex)
    flush.complete(current_state, error=None | exc)
                                       ->  record_memory_flush_success / _failure
    <- FlushOutcome(session''')
  the session's next after_turn runs only after complete() (one maintenance lane per session)

/new or /reset
  on_new_session(state, command, ...)  ->  save_session_memory (+ reindex)
                                           initialize_agent_workspace
                                           resolve_bare_session_reset_prompt_state
                                           build_startup_context
                                           format_session_reset_transcript_prompt
  <- NewSession(session, saved, reset)     the reset turn then runs through before_turn

scheduler tick (host)
  heartbeat_prompt(state)              ->  due_automation_jobs, heartbeat_scheduled_tasks
                                           prepare_heartbeat_turn
                                           the before_turn composition (run kind heartbeat)
  <- HeartbeatRun(turn, jobs, host_jobs, context)
  if not skipped: model call (host), tool calls through dispatch
    run.complete(reply, usage)         ->  decide_heartbeat_reply, record_automation_job_run
    <- HeartbeatOutcome(session, decision, jobs_recorded, transcript)
```

The host persists every returned `SessionState`. It records in its transcript the visible user
message (or the reset / heartbeat transcript row), the reply and its own tool rows; never the
runtime-context block and never the flush turn.

Known gap: one flush per compaction cycle. upstream's guard (`hasAlreadyFlushedForCurrentCompaction`)
allows one flush per `compactionCount`, and upstream compacts, which starts the next cycle. The kit
never compacts, so a host that does not call `SessionState.after_compaction()` flushes at most once
per session: after one flush, or three failed ones, every later turn reads `already_flushed` until
`/new`. A WhatsApp or Slack session that keeps one `session_key` for weeks then stops flushing after
the first time. Hosts that compact call `after_compaction()` when they do; history windowing with
`limit_history_turns` does not count as a compaction (decision Q9, upstream's rule).

## Entry points

### 1. `tools()`

```python
def tools(self) -> list[dict[str, Any]]
```

- Returns provider-neutral `{"name", "description", "parameters"}` dicts:
  `memory_core/tools/memory_search.py:memory_search_tool_definition`,
  `memory_core/tools/memory_get.py:memory_get_tool_definition`, then
  `memory_core/curation.py:MemoryCurator.tool_definitions` for the operations the policy allows.
  The host wraps them in its format (`{"type": "function", "function": d}` for
  OpenAI-style APIs).
- The two memory tool definitions are pin-era code (pin `4c428153`): at v2026.9.6 the contract
  lives in `extensions/memory-core/src/memory-tool-contract.ts` with different descriptions. Port
  plan area 5 (tool definitions and prompt section) ports them; until then the kit ships the pin-era
  texts, labelled in "Parity labels".
- Flags: `curated_memory_writes` off means no curation definitions (the curator returns none).
- Pure: no I/O, never raises.

### 2. `dispatch(name, arguments, *, session)`

```python
def dispatch(
    self,
    name: str,
    arguments: Mapping[str, Any] | str | None,
    *,
    session: SessionState,
) -> dict[str, Any]
```

- Composes `execute_memory_search_tool(config, store, args, agent_session_key=session.session_key,
  runtime_identity=identity)`, `execute_memory_get_tool(config, args)` and
  `MemoryCurator.dispatch(name, args)` on `HostKit.curator`, built from `Memory.curator(layout,
  policy, timezone, now_ms)` (whose `after_write` reindexes after MEMORY.md and daily-note writes).
- Arguments: a mapping, its JSON text (parsed once for every tool) or `None` (read as `{}`).
  Blank text reads as `{}`. Parsing JSON text is host-transport glue and deliberately differs from
  the core's `asToolParamsRecord` (`as_tool_params_record`, where a string reads as `{}`): the kit
  sees the transport's raw text, the core sees an already-decoded value.
- Recall tracking: with `dreaming_enabled`, the memory-corpus hits of a `memory_search` result that
  is not unavailable go through `memory_core/consolidation/recall.py:undecorate_search_results` and
  `record_short_term_recalls`, as upstream does only when dreaming is enabled and the memory search
  succeeded (`extensions/memory-core/src/tools.ts:491-507`). Upstream records off the reply path and
  swallows recording errors; the kit records synchronously and swallows them too. Off by default
  (`DEFAULT_DEEP_DREAMING_ENABLED = False`): no `memory/.dreams/` write. Known gap: the recall
  days are UTC dates, not dates in the kit's timezone. Upstream passes `dreaming.timezone`
  (`tools.ts:501`) and buckets the day in it (`short-term-promotion-record.ts:192`); the pin-era
  `record_short_term_recalls` takes no timezone (matrix row "Recall tracking from
  `memory_search`"), so in Europe/Istanbul a recall between 00:00 and 03:00 counts on the
  previous day.
- Returns the tool's payload unchanged, JSON-able, for the host to send back verbatim.
- Error contract, checked in this order. Model-caused errors come back as payloads, never raised:
  - invalid JSON text: `{"status": "error", "tool": name, "error": "invalid JSON arguments: <msg>"}`
    (`<msg>` is the decoder's message);
  - JSON text or a value that is not an object (`"[]"`, `"\"q\""`): `... "error": "arguments must be
    a JSON object"`;
  - a name `tools()` does not offer now (unknown, flag off, policy): `... "error": "tool <name>
    is not available"` (memory-core wording; the host's own loop owns names of its other tools);
  - `MemoryToolInputError` (bad params, refused or failed curated writes): `error.to_tool_error()`;
  - any other `Exception` raised inside a tool body: `to_tool_error(exc, tool=name)`, as
    upstream turns every thrown tool error into `{status, tool, error}`
    (`src/agents/agent-tool-definition-adapter.ts:228-284`).
- Refusals and outages the memory tools answer themselves are not error payloads: `memory_get` of
  a path outside MEMORY.md, dreams.md and `memory/**`, or a failed read, returns upstream's
  `{"path", "text": "", "disabled": true, "error"}`, and `memory_search` returns its unavailable
  (`disabled` and `unavailable` true) or paused payload. A host that counts failed calls checks
  `status == "error"` or `disabled`.
- Host programming errors raise before a tool runs: `TypeError` for a non-string `name` or an
  `arguments` of another type. `BaseException`s that are not `Exception` (cancellation,
  interrupts) propagate.
- Flags: all search flags through `memory.config` (FTS-only, vector-only, MMR, temporal decay);
  `curated_memory_writes` as above; a disabled capability makes no provider call and no write.

```python
def dispatcher(
    self, session: SessionState
) -> Callable[[str, Mapping[str, Any] | str | None], dict[str, Any]]
```

`dispatch` bound to one session: `kit.dispatcher(turn.session)(name, arguments)` is
`kit.dispatch(name, arguments, session=turn.session)`, the two-argument shape of
`FlushRequest.dispatch`, so one tool-answering helper serves a turn and its flush run. It looks
`dispatch` up at each call and adds nothing to it; a `session` that is not a `SessionState`
raises `TypeError` at once (F24).

### 3. `before_turn(session, ...)`

```python
def before_turn(
    self,
    session: SessionState,
    *,
    runtime_context: str | None = None,
    run_kind: BootstrapContextRunKind | None = None,
    context_mode: BootstrapContextMode = "full",
    has_bootstrap_file_access: bool = False,
    offer_tools: bool = True,
    ensure: bool = True,
) -> TurnContext

@dataclass(frozen=True)
class TurnContext:
    session: SessionState              # pass to after_turn when the turn completes
    system_prompt: str                 # stable part, above any prompt-cache boundary
    runtime_context: str | None        # dynamic part, below it
    tools: tuple[dict[str, Any], ...]  # what the host offers this turn
    memory_recall: tuple[str, ...]     # the Memory Recall lines inside system_prompt
    workspace: WorkspaceContext        # the core result (files, truncation, bootstrap mode)
    workspace_init: WorkspaceInitResult | None  # None with ensure=False
```

- Composes, in order:
  1. with `ensure=True` (default), `ensure()`. `ensure=False` makes the call read-only: an
     inspector or prompt preview must not seed or delete BOOTSTRAP.md, and a host that already
     ran `ensure()` for this turn (the Lab, inside its own event tracking) does not run it twice.
  2. `memory_core/bootstrap/context.py:build_workspace_context(root, layout, session_kind=kind,
     run_kind, context_mode, context_injection, has_completed_bootstrap_turn,
     has_bootstrap_file_access, max_chars, total_max_chars, truncation_warning_mode,
     seen_truncation_signatures, identity)`. `run_kind` defaults from the session kind, as the core
     does (`heartbeat` -> heartbeat, `cron` -> cron, else default); a host running a cron or
     heartbeat job in a main session passes it.
  3. `tools` = `tools()`, or `()` with `offer_tools=False` (a model or transport without tool
     calling; the Lab's scripted engine).
  4. `memory_core/prompt_section.py:build_prompt_section(names of tools,
     citations_mode=config.citation_mode)`, skipped for the minimal prompt kinds `subagent` and
     `cron` (upstream `buildMemorySection` returns nothing in minimal mode,
     `src/agents/system-prompt.ts:202-225`; the set moves here from
     `demo/lab_runtime.py:MINIMAL_PROMPT_KINDS`). No tools, no section.
  5. `system_prompt` = the Memory Recall lines, then `WorkspaceContext.prompt_text`, joined by a
     blank line (upstream puts the memory section before the workspace sections,
     `system-prompt.ts:1059`).
  6. `runtime_context` = `memory_core/runtime_context_prompt.py:build_runtime_context_system_context`
     of the host's text (the identity's begin/end markers, so strip helpers remove it), or `None`.
  7. `session` = the input with `seen_truncation_signatures` from
     `WorkspaceContext.prompt_warning.warning_signatures_seen` and `completed_bootstrap_turn`
     set when `record_completed_bootstrap_turn` asks for it. The host passes this state to
     `after_turn` only for a turn that completed, so a failed turn records nothing.
- The Memory Recall section is pin-era code: `memory_core/prompt_section.py` does not match the tag's
  `buildMemoryPromptSection` (`extensions/memory-core/src/memory-tool-contract.ts:110-145`: other
  guidance wording, the session-hit guidance lines and "Report partial, unavailable, or stale
  recall"). The matrix row "Prompt memory tool section" is `partial` with the oracle "Not added";
  port plan area 5 ports it with the planned `memoryPromptSection` op. Until then the kit's section
  is the pin-era text, labelled in "Parity labels".
- No recall injection: upstream's model recalls through the memory tools, and so does the kit's.
  Startup context exists upstream only on the bare `/new` / `/reset` turn, so it comes from
  `on_new_session`, not from here.
- Where the runtime context goes (F22): send `runtime_context` as a user-role message
  immediately before the turn's user message, on every model call of the turn, and never record
  it in the transcript. Upstream binds its runtime-context carrier to the turn's user message and
  inserts it before that message (`src/agents/embedded-agent-runner/run/attempt-llm-boundary.ts:240-268`;
  `findActiveUserMessageIndex` finds the message only on a retry, where none means no carrier),
  sends that custom message as a user message (`packages/agent-core/src/harness/messages.ts:139-153`)
  and strips carriers of earlier turns from replays (`src/agents/internal-runtime-context.ts:379-400`).
  The block's header text ("... for the immediately preceding user message") is upstream's wording
  and does not change the placement.
- A turn whose steps run apart (F2, F3): `TurnContext` holds the `WorkspaceContext` and does not
  serialize, so a host with durable steps (a LangGraph graph, a queue worker) keeps
  `TurnState.from_context(context, reset=...)` and its `to_json()`, which carries the session,
  the system prompt, the runtime context, the tools and the reset turn (`memory_core/host/turn.py`;
  `from_json` needs `session`, `systemPrompt` and `tools`, reads missing optional keys as null and
  ignores unknown keys; the JSON is unversioned and changes stay additive). On every model call of
  a reset turn, the turn's active user message (upstream's `findActiveUserMessageIndex`,
  `attempt-history.ts:350-383`: the last user message unless an assistant reply without tool
  calls follows it) gets `reset.model_prompt` in place of its text while that text is
  `reset.transcript_prompt` and the model prompt is not blank and differs from it (upstream's
  `installModelPromptTransform`, `attempt-llm-boundary.ts:384-460`). Find that message on the
  stored history and then in `repair_tool_calls`' copy by identity: upstream fixes the target
  prompt at the turn's first model call and finds it again on later calls (`:407-415`), and the
  repair can leave a tool round's assistant message without calls, which would end the turn
  early on the copy.
- A turn that failed between a tool-call reply and its tool results leaves calls without results;
  send `kit.repair_tool_calls(history).messages` to the model instead of the history (upstream
  repairs the replayed history the same way at the start of each attempt, F26):

```python
def repair_tool_calls(
    self,
    messages: Sequence[Mapping[str, Any]],
    *,
    allowed_tool_names: Iterable[str] | None = None,
) -> ToolCallRepair

@dataclass(frozen=True)
class ToolCallRepair:
    messages: tuple[Mapping[str, Any], ...]  # the rows to send the model, in order
    sources: tuple[int | None, ...]          # per row: the host row it is or copies; None: synthetic
```

  It maps the chat-completions rows to upstream's message shape, runs
  `memory_core/replay_repair.py:sanitize_tool_call_inputs` and then
  `sanitize_tool_use_result_pairing_for_model` (upstream's order, `replay-history.ts:793,819`)
  and maps back (`memory_core/host/tool_calls.py`): unchanged rows are the host's own objects, a
  changed assistant row keeps only its kept calls (trimmed names; no `tool_calls` key when none is
  left), a tool row without an id (none, or blank once trimmed) paired by its frame's only call
  gets that call's `tool_call_id` and, when it has a `status`, `"error"` (upstream's `isError`),
  dropped rows are left out, and a missing result is `{"role": "tool", "tool_call_id", "content"}` with
  upstream's `DEFAULT_MISSING_TOOL_RESULT_TEXT` for every identity (K3). `allowed_tool_names`
  keeps unanswered calls to those tools only (upstream passes the run's tool names). The host
  keeps its stored transcript as it is; the kit reads no file. Labelled gaps: host rows carry no
  stop reason, tool-call blocks in a content list and a legacy `function_call` are neither read nor
  rewritten, the Responses-API steps are not offered, and a row without a `status` cannot carry
  upstream's `isError` (LangGraph findings › Parity labels).
- `has_bootstrap_file_access` defaults to `False` because no kit tool can read BOOTSTRAP.md
  (`memory_get` reads only MEMORY.md, dreams.md and `memory/**`); upstream's
  `hasBootstrapFileAccess` is "the run's tools include `read`" (`attempt-bootstrap-prepare.ts`).
  A host with its own read tool passes `True`. Non-empty BOOTSTRAP.md still counts as access
  (core rule).
- Errors: `WorkspaceStateMigrationRequiredError` while upstream's retired JSON setup state is in
  the workspace (fail closed, the host runs `migrate_legacy_workspace_state`); `OSError` from the
  filesystem; `ValueError` for an unknown session kind, run kind or context mode (host errors). No
  model is involved, so nothing is a payload here.

### 4. `after_turn(session, ...)` and the flush request

```python
def after_turn(
    self,
    session: SessionState,
    *,
    transcript: Sequence[Mapping[str, Any]],
    usage: TurnUsage | None,
    context_window_tokens: int | None = None,
    transcript_bytes: int | None = None,
    redact: Callable[[str], str] | None = None,
) -> TurnRecord

@dataclass(frozen=True)
class TurnRecord:
    session: SessionState                      # with this turn's token snapshot
    flush_plan: MemoryFlushPlan                # the plan for this window (meter terms)
    flush_decision: MemoryFlushTriggerDecision
    flush: FlushRequest | None                 # set when the decision flushes
    flush_failure: MemoryFlushFailureOutcome | None  # the flush was due but its setup failed
```

Where upstream decides the flush. At v2026.9.6 a completed reply schedules session maintenance
(`src/auto-reply/reply/agent-runner-result-complete.ts:288`,
`agent-runner-maintenance.ts:11-73`: not for heartbeats, failed or aborted runs, runs that
auto-compacted, or with compaction disabled), and maintenance calls `runMemoryFlushIfNeeded`
with `promptForEstimate: ""` (`src/agents/session-maintenance/run.ts:218-232`), then compaction.
The other call site is the checkpoint before preflight compaction
(`agent-runner-execute.ts:145-176`), which runs only when that compaction runs
(`agent-runner-memory.ts:875-889`). `after_turn` is the first site; the second needs host
compaction and is a non-goal. The Lab follows this order since Task 9a (decision Q1); its
pre-turn flush with the incoming prompt's estimate was the pin-era order.

- Composes:
  1. the token snapshot: `usage.prompt_tokens > 0` becomes a fresh v1 total (`totalTokens`,
     `totalTokensFresh: True`, `totalTokensVersion: SESSION_TOTAL_TOKENS_VERSION`) and
     `completion_tokens` the session's `last_output_tokens`; otherwise `totalTokensFresh: False`;
  2. `memory_core/memory_flush.py:build_memory_flush_plan(now_ms, timezone, context_window_tokens,
     time_format)`; `context_window_tokens` defaults to upstream `DEFAULT_CONTEXT_TOKENS`
     (200,000, `src/agents/defaults.ts:6`; the constant moves here from `demo/lab_runtime.py`);
  3. `explain_memory_flush_trigger(entry, plan, context_window_tokens, token_count,
     transcript_byte_size=transcript_bytes, is_heartbeat=kind == "heartbeat")` with
     `token_count` = the fresh total plus `last_output_tokens` (none without a fresh total, as
     the Lab computes it today). No prompt estimate: maintenance computes
     `resolveEffectivePromptTokens(base, output, undefined)`
     (`src/auto-reply/reply/memory-flush.ts:28-39`). Without `transcript_bytes` the
     transcript-size gate stays off (unknown size never forces);
  4. when the decision flushes, `ensure_memory_flush_target_file(root, plan.relative_path)`, then
     the `FlushRequest`. Upstream creates `memory/` and opens the target for append before the flush
     run (`agent-runner-memory.ts:1447-1451`, `memory-flush-session.ts:64-96`), so an empty daily
     file exists even when the model answers `NO_REPLY`, and `memory/` is setup evidence: the next
     ensure completes the bootstrap. If the ensure raises (`UnsafeMemoryPathError`, `OSError`), the
     kit records a failure strike like upstream's `recordFailure` for a failed preparation:
     `flush` is `None`, `flush_failure` the outcome, and `session` carries the failed entry.
     `redact` maps that failure's message (`record_memory_flush_failure(..., redact=redact)`, as
     `FlushRequest.complete(redact=)` does; it is applied before the truncation, upstream's
     order); only `flush_failure.error` changes (F21).
- The window (F12): the default is upstream's `DEFAULT_CONTEXT_TOKENS` and is right only for a
  model with a 200,000-token window. From an 80,000-token window up the flush threshold is the
  window minus the reserve floor (20,000) and the soft threshold (4,000): the default puts it at
  176,000, above a 128,000-token model's window (whose own threshold is 104,000), so that model's
  flush never runs. Pass the model's window.
- `after_turn` has only upstream inputs. The one forced flush is the extension below.

```python
def request_flush(
    self, session: SessionState, *, transcript: Sequence[Mapping[str, Any]]
) -> FlushRequest | None
```

A memory-core extension (decision Q6; upstream has no forced flush), for a host action such as the
Lab's `/flush`. It does not touch the token snapshot and keeps the two guards a forced run must
not skip: a `heartbeat` session gets `None`, and so does a compaction cycle that already flushed or
failed three times (`has_already_flushed_for_current_compaction`). Otherwise it returns the
request `after_turn` builds for a due flush (target file first, the same messages and tool), with
`reason` `forced`. A target that cannot be created raises (`UnsafeMemoryPathError`, `OSError`) and
records nothing: the forced run is outside upstream's gate, so there is no strike to mirror.

`memory_core/memory_flush.py:ensure_memory_flush_target_file(root, relative_path)` (new port of
`ensureMemoryFlushTargetFile`): a blank or absolute path raises `UnsafeMemoryPathError("Invalid
memory flush target path")`, one that resolves outside the root raises `... "Memory flush target
path must stay inside the workspace"` (upstream messages, script-extracted); it then creates the
parent directories and opens the file for append, creating it empty. Stricter than upstream
(documented deviation): it refuses a symlinked or non-directory parent and a target that is a
symlink, a non-regular file or has more than one hard link, the same refusal as the flush write.

Flush execution: a returned request object, not a host callable. Reasons:

- The host owns the model call, model choice (`TurnRecord.flush_plan.model` is only a hint),
  streaming, tool-call transport, timeouts, cancellation and provider fallback
  (docs/package_boundary.md). A callable would make the kit run the tool loop, which adapters
  never own, and would force one sync or async signature on every host.
- Upstream runs the flush as detached maintenance after the reply is delivered, in its own
  session view (`src/auto-reply/reply/memory-flush-session.ts:17-47`). A request can be run later
  in the same process (a background task or thread); a callable inside `after_turn` would sit on
  the reply path. A request holds the workspace's `Memory` and its own appends, so it does not
  cross processes: a host that hands maintenance to another process (a queue worker) sends the
  worker the session state (`SessionState.to_json`) and the transcript, and the worker calls
  `after_turn`, runs the flush and calls `complete()` on its own kit for the same root.
- The request is data plus two sync methods, so asyncio hosts await their own model between
  them and the kit stays sync; tests assert the request without a stub model.

```python
class FlushRequest:
    target: str                                 # plan.relative_path, memory/YYYY-MM-DD.md
    reason: str                                 # the trigger's reason, or forced (request_flush)
    messages: tuple[dict[str, str], ...]        # system, transcript text rows, user
    tools: tuple[dict[str, Any], ...]           # the append-only write tool only

    def dispatch(self, name: str, arguments: Mapping[str, Any] | str | None) -> dict[str, Any]
    def complete(
        self,
        session: SessionState,
        *,
        error: BaseException | str | None = None,
        redact: Callable[[str], str] | None = None,
    ) -> FlushOutcome

@dataclass(frozen=True)
class FlushOutcome:
    session: SessionState
    wrote: bool
    entries: tuple[str, ...]                    # appended texts, in order
    failure: MemoryFlushFailureOutcome | None
```

The plan, the decision and the session live on `TurnRecord`; the request carries only what the
flush run needs. The flush run's model output is never delivered: a host that streams model output
(a framework's token stream, server-sent events) tags the flush run's model calls out of that
stream or runs them outside it (LangGraph: `TAG_NOSTREAM`). Upstream runs the flush as detached
maintenance whose output no channel sees (F7).

- `messages`: one system message, the text of the transcript's user and assistant rows (string
  content, or the `text`, `input_text` and `output_text` blocks of a content list joined as
  upstream's `resolveMessageText` joins them, `src/auto-reply/heartbeat-filter.ts:221`; rows
  without text and every other role are dropped, runtime-context custom rows included), then
  `plan.prompt` as the user message.
  Upstream's flush turn is a full agent run whose system prompt carries
  `[run.extraSystemPrompt, plan.systemPrompt]` as extra context under `## Conversation Context`
  (`agent-runner-memory.ts:1452-1454`, `system-prompt.ts:1254-1257`; the flush session's key is an
  internal effects key, so the prompt mode is full and the header is not `## Subagent Context`).
  The kit's system message is the session's Project Context (`build_workspace_context` for the
  session kind, `is_interactive_user_facing=False`, so bootstrap mode `none`; the flush run offers
  no memory tools, so no Memory Recall section; `seen_truncation_signatures` from the session, as
  upstream passes `bootstrapPromptWarningSignaturesSeen`), then `## Conversation Context` and
  `plan.system_prompt`. The header is script-extracted into `memory_core/_memory_flush_constants.py`.
  Labelled deviations: text only (upstream's bounded view also replays tool calls, tool results and
  non-text content; it fails with `Memory flush exceeds the bounded conversation view.`, a non-goal
  here), and no host system prompt (upstream prepends the run's `extraSystemPrompt`; a host with
  one prepends it to the system message itself).
- `tools`: upstream offers a flush run only `read` and an append-only `write`
  (`src/agents/agent-tools.ts:91,665-692`). memory-core has no generic `read`, so the kit offers the
  `write` tool alone: upstream's schema and description (`src/agents/sessions/tools/write.ts:42-47,
  523-525`) plus the wrapper's suffix `During memory flush, this tool may only append to <target>.`
  (`src/agents/agent-tools.read.ts:760`), script-extracted. It replaces the Lab's own wording in
  `demo/chat_engine.py:_memory_write_tool`.
- `dispatch("write", {path, content})`, after the argument checks of `HostKit.dispatch`:
  - `path` must be a non-blank string and `content` a string (empty allowed, as upstream's
    `allowEmpty`); otherwise an error payload (`path required`, `content required`; memory-core wording,
    upstream's message adds a retry hint and the received keys);
  - a path starting with `@`, or one that does not resolve to the target (relative to the root, or
    absolute), returns upstream's `Memory flush writes are restricted to <target>; use that path
    only.` (`agent-tools.read.ts:787-790`); an absolute path that resolves to the target is accepted;
  - empty content, and content whose stripped text is exactly `NO_REPLY` (decision Q12; the same
    rule as `MemoryCurator.append_daily_note`, which shares the append), writes nothing and returns
    `{"status": "ok", "tool": "write", "path": target, "action": "skipped"}` (memory-core's write rule;
    `NO_REPLY_FACTS: ...` and other text that only starts with the token is appended);
  - otherwise the content is appended through the shared locked daily append (the path
    `MemoryCurator.append_daily_note` uses, so both refuse the same symlinks and hard links), the
    store is reindexed, and the payload is `{"status": "ok", "tool": "write", "path": target,
    "action": "appended", "text": "Appended content to <target>."}` (upstream's text, `:828`;
    script-extracted). A reindex failure keeps the ok payload and adds `afterWriteError`, as curated
    writes do;
  - other names return `tool <name> is not available`; errors of the append are payloads.
- `complete(session, ...)` writes the session entry of the host's current state for this session
  (the flush may run detached while the next turn's `before_turn`, tool calls and model call run and
  update the state; a different `session_id` raises `ValueError`):
  `record_memory_flush_success(entry, flushed_compaction_count=<the count when the
  request was made>)`, as upstream stamps `flushedCompactionCount`, or with `error`
  `record_memory_flush_failure(entry, error=..., redact=...)` (three strikes mark the cycle
  flushed). The flush reply's text is never delivered and never enters the transcript (upstream
  also treats an empty reply as silent). A cancelled run is not completed: upstream records nothing
  for a cancelled flush. A second `complete()`, or a `dispatch` after it, raises `RuntimeError`
  (host error).
- One maintenance lane per session: the kit keeps no pending-flush state, so until `complete()`
  stamps the cycle, `after_turn` on a session over the threshold returns another request for the
  same cycle. The host runs a session's next `after_turn` only after the pending flush completed or
  was abandoned (an abandoned run records nothing, so that `after_turn` requests the flush again).
  Upstream serializes session maintenance per session key the same way: a maintenance run waits
  for its predecessors' writes (`src/agents/session-maintenance/run.ts:144`,
  `coordinator.ts:101-160`) and then reads the stamped entry (`already_flushed`). Replies are not
  held back: the next turn's `before_turn`, tool calls and model call may run while the flush runs.
- Flags: flush never depends on `curated_memory_writes`, and the curation tools are not offered
  during a flush (upstream restricts flush runs; `MemoryCurator` refuses `memory_flush=True`).

### 5. `on_new_session(ending, ...)`

```python
def on_new_session(
    self,
    ending: SessionState,
    *,
    command: Literal["new", "reset"],
    session_id: str,
    transcript: Sequence[Mapping[str, Any]] | None = None,
    session_file: str | os.PathLike[str] | None = None,
    text: str | None = None,
    source: str | None = None,
    slug_generator: SlugGenerator | None = None,
    redactor: Callable[[str], str] | None = None,
    has_bootstrap_file_access: bool = False,
) -> NewSession

@dataclass(frozen=True)
class NewSession:
    session: SessionState              # same key and kind, the new id, a fresh entry
    saved: SessionMemoryResult         # memory/<date>-<slug>.md of the ending session
    workspace_init: WorkspaceInitResult
    reset: ResetTurn | None            # bare command only

@dataclass(frozen=True)
class ResetTurn:
    model_prompt: str                  # [startup context, reset prompt]: the next user message
    transcript_prompt: str             # "[memory-core session new]": what the transcript records
    bootstrap_mode: BootstrapMode
    startup_context: str | None
    prompt: str                        # the reset prompt alone (model_prompt without the prelude)
```

- Composes, in the kit's order: `memory_core/session_memory.py:save_session_memory(root,
  session_key, session_id, messages=transcript | session_file, source, now_ms, timezone,
  slug_generator, redactor)`; a reindex, so `memory_search` finds the new file;
  `ensure()` (upstream's ensure runs before the reset reply, `get-reply.ts:443-448`; it stays here
  because the reset prompt's bootstrap mode must see the file just saved); for a bare command
  (`text` empty) `memory_core/bootstrap/startup.py:resolve_bare_session_reset_prompt_state(root, now_ms,
  timezone, time_format, layout, is_primary_run=kind != "subagent", has_bootstrap_file_access)`,
  `build_startup_context(root, now_ms, timezone)` when the state says to prepend and
  `should_apply_startup_context(command)`, and `format_session_reset_transcript_prompt(command,
  identity)`. `model_prompt` joins the startup prelude and the reset prompt with a blank line, as
  `prompt-prelude.ts:200-212` builds the model's message (the transcript row: `:224-225`).
- The saved file is written before the startup context is read, so the next session's prelude
  can quote it. Upstream writes it from a background queue, so its order is not fixed.
- The reset turn then runs like any turn: the host sends `reset.model_prompt` through
  `before_turn` and its model, and records `reset.transcript_prompt` instead. That turn's ensure
  runs again (cheap and idempotent). `ResetTurn.to_json` / `from_json` carry it to the step that
  runs the turn, and `TurnState.reset` carries it through the turn's model calls (entry point 3).
- Errors propagate from `save_session_memory` (documented deviation from upstream's logging:
  `ValueError` for an unknown zone, `UnsafeMemoryPathError`, `OSError`); a slug generator failure
  falls back to the timestamp slug. Passing both `transcript` and `session_file` raises
  `ValueError`.
- The raw recent lines are stored, as upstream (`## Conversation Summary` is not a model
  summary); `redactor` maps each line first. Auto-reset (upstream's `session:auto-reset` event
  for daily and idle expiry) is a follow-up (port plan area 9).

### 6. `heartbeat_prompt(session, ...)`

```python
def heartbeat_prompt(
    self,
    session: SessionState,
    *,
    source: str | None = None,
    reason: str | None = None,
    context_mode: BootstrapContextMode = "full",
    runtime_context: str | None = None,
    offer_tools: bool = True,
    schedule_now_ms: int | None = None,
    ensure: bool = True,
) -> HeartbeatRun

class HeartbeatRun:
    session: SessionState
    turn: HeartbeatTurn                         # skip_reason, message, scheduled tasks
    jobs: tuple[AutomationJob, ...]             # due jobs whose tasks are in the turn
    host_jobs: tuple[AutomationJob, ...]        # other due jobs: the host's to run
    context: TurnContext | None                 # None when skipped: no model call
    transcript_prompt: str                      # identity.heartbeat_transcript_prompt
    started_at_ms: int

    def complete(
        self,
        reply: str | None,
        *,
        usage: TurnUsage | None = None,
        response_prefix: str | None = None,
        ended_at_ms: int | None = None,
    ) -> HeartbeatOutcome

@dataclass(frozen=True)
class HeartbeatOutcome:
    session: SessionState                       # with the run's token snapshot
    decision: HeartbeatReplyDecision
    jobs_recorded: tuple[AutomationJob, ...]
    transcript: tuple[dict[str, str], ...]      # user transcript_prompt, assistant reply
```

- Composes: `memory_core/automation.py:due_automation_jobs(store.list_jobs(agent_id), schedule_now_ms)`,
  `heartbeat_scheduled_tasks`, `memory_core/heartbeat.py:prepare_heartbeat_turn(now_ms, scratch=
  store.read_scratch(agent_id), scheduled_tasks, source, reason, timezone, time_format)`, and,
  unless skipped, the `before_turn` composition with `run_kind="heartbeat"` for the session's kind
  (the Lab's heartbeat session has kind `heartbeat`; upstream runs heartbeats in the main session,
  which the run kind covers), `offer_tools` (`False` for a model without tool calling, as in
  `before_turn`) and `ensure` (`False` for a preview that never completes the run, as
  `before_turn(ensure=False)`: no workspace write). There is no `has_bootstrap_file_access`: the
  heartbeat run kind resolves the bootstrap mode to `none` before file access is read (`resolve_bootstrap_mode` in
  `memory_core/bootstrap/files.py`, upstream `bootstrap-mode.ts`). `schedule_now_ms` is the
  scheduler's instant for due checks and job runs (default: the kit clock); the prompt's
  `Current time:` line always uses the kit clock, which keeps the Lab's virtual heartbeat clock
  working without a Lab concept in the kit.
- `complete(reply)`: `decide_heartbeat_reply(reply, response_prefix)`; the host delivers only
  when `decision.deliver` (canonical `NO_REPLY`, a legacy `HEARTBEAT_OK` ack within 300 chars and
  a stream-error placeholder are not delivered; a trailing `notify=false` line makes it silent);
  `record_automation_job_run(job, started_at_ms, ended_at_ms)` for `jobs` only, saved in one
  `store.save_jobs` call; the token snapshot as `after_turn` writes it, with no flush decision
  (upstream skips maintenance for heartbeats). Before recording, `complete` re-reads
  `store.list_jobs(agent_id)` and records a run only for a job that is still present and unchanged
  (equal to the copy `heartbeat_prompt` loaded, so its `updated_at_ms` too): a job the host edited
  or removed while the run was in flight is neither written back stale nor brought back.
  `transcript` is what the host records: the identity's heartbeat row and the raw reply, so the
  session corpus filter drops both. A second `complete()` raises `RuntimeError`.
- A skipped turn (`empty-heartbeat-file`, `no-pending-event`) has no due tasks, so nothing is
  recorded, no ensure runs and no model call follows. A failed model call is not reported: the jobs
  stay due and retry backoff is the host's.
- Tool calls during the run go through `HostKit.dispatch` with `run.session`.

## Cross-cutting contracts

### Errors

| Situation | Behaviour |
| --- | --- |
| model sends bad tool input, unknown tool, invalid JSON, a tool raises | payload `{"status": "error", "tool", "error"}` |
| memory search outage, paused index, cooldown | the tool's own unavailable or paused payload |
| `memory_get` outside the memory files, a failed read | `{"path", "text": "", "disabled": true, "error"}` (upstream's shape) |
| host passes wrong types, calls `complete()` twice, both transcript sources, another session to `complete()` | raise (`TypeError`, `RuntimeError`, `ValueError`) |
| retired upstream setup state in the workspace | raise `WorkspaceStateMigrationRequiredError` (fail closed) |
| filesystem failure outside a tool | raise `OSError` |
| flush target cannot be created | `after_turn`: `TurnRecord.flush_failure`, one strike (upstream `recordFailure`); `request_flush`: raise, no strike |
| a reindex fails after a committed curated or flush write | ok payload with `afterWriteError` (core rule) |

### Flags

| Flag | Where the kit honours it | Negative test |
| --- | --- | --- |
| `vector_search`, `text_search`, `mmr`, `temporal_decay` | `memory_search` through `memory.config` | vector off: the embedder is never called by any entry point |
| `curated_memory_writes` | `tools()`, `dispatch`, `before_turn` (tool names in the Memory Recall section) | off: no curation tools, `dispatch` returns an error payload, workspace bytes unchanged, no reindex |
| `subject_promotion` | not used (live subjects are out of scope) | none |
| kit option `dreaming_enabled` (upstream `dreaming.enabled`) | recall tracking in `dispatch` | off: no `memory/.dreams/short-term-recall.json` |

### Sync and async

Every entry point and handle method is synchronous and does blocking file, SQLite and embedding
I/O; none of them waits for a model. An asyncio host calls them with `await
asyncio.to_thread(kit.before_turn, state, ...)` and awaits its own model in between. There is no
async twin of any method: the core is synchronous (sqlite3, the sync embedding client,
`memory_search`'s own deadline worker), so async wrappers would only duplicate the surface.
`memory_core.live.SubjectMemory.stream_live_turn` stays the async streaming adapter for voice hosts.

### Thread safety

- A `HostKit` is immutable after construction and safe to share across threads.
- Writes in one process are serialized per file: the flush write and the curated daily note
  share one per-file lock (moved out of `memory_core/curation.py:_target_lock` into
  `memory_core/workspace.py`, next to the shared locked daily append), MEMORY.md, USER.md and
  PROACTIVE_PREFERENCES.md keep curation's per-file locks, `FileAutomationStore` keeps its lock,
  and every read-modify-write of the short-term recall store (recall recording, the promotion's
  `promotedAt` marks, repair) holds `memory_core/consolidation/store.py:recall_store_lock`, so parallel
  `memory_search` calls with `dreaming_enabled` lose no recall.
  Task 2 adds a two-thread reindex test; if it fails, the fix is a per-store lock inside
  `SQLiteMemoryStore.reindex`.
- Different sessions may run in parallel. Calls for one session must be serialized by the host,
  as upstream runs one reply per session lane; `SessionState` is a value, so the last writer wins
  (the detached flush's `complete(session)` takes the current state for that reason). The detached
  flush belongs to the session's maintenance lane: the session's next `after_turn` waits for its
  `complete()` (entry point 4), while the next turn's other calls may run meanwhile.
- `FlushRequest` and `HeartbeatRun` are used by one run at a time; their tool calls may run in
  parallel (appends are locked).
- Across processes nothing is locked beyond the core's re-read checks and the automation store's
  advisory lock.

### Tenancy

| Scope | What | Owner |
| --- | --- | --- |
| process | `memory_search` cooldowns (keyed by store path and agent id), per-file write locks | memory-core |
| workspace (one agent) | `HostKit`: root, layout, `Memory` (config, flags, store), curation policy, automation store, timezone, time format | the host opens one kit per workspace root |
| session | `SessionState` | the host stores it; the kit returns new copies |
| transcript | the messages | the host; the kit reads them and never stores them |
| subject (live) | `memory_core.live.SubjectMemory`, one `subjects/<id>/` workspace each | not served by the kit in this stage |

A multi-tenant host (one agent per customer, per Slack team) opens one kit per workspace root;
kits share nothing but the process-wide caches above.

## What stays host-owned

The agent loop and the tool loop, the model call and model choice, streaming, tool-call transport
and argument validation against the schema, provider fallback and retries, history windowing
(`limit_history_turns` stays a core helper), compaction (and with it `SessionState.after_compaction`:
known gap, a host that never compacts flushes once per session, see Turn lifecycle), scheduling
(heartbeat cadence, active hours, job timers, backoff), delivery and visibility, ASR and TTS,
workflow state, trace storage, secret redaction policy (the kit takes the host's `redact` and
`redactor`), and session storage.

## `Memory.prepare_turn`, `Memory.chat`, `Memory.record_turn`: removed

Decision: keep `Memory` as the core handle (`from_workspace`, `search`, `get`, `curator`;
`langgraph_recall` was removed later in 0.2.0, confirmed by Doruk on 2026-09-29, docs/integrations/langgraph.md L1). `prepare_turn`, `chat` and
`record_turn` were deprecated in this stage (a `DeprecationWarning` naming `memory_core.host`,
behaviour unchanged, Task 7) and removed in the packaging stage (0.2.0, decision Q7) with
`MemoryChatTurn`, `MemoryChatResult`, `MemoryRecordResult`, `DEFAULT_CHAT_SYSTEM_PROMPT`,
`examples/chatbot_memory.py` and `docs/feature_storybook.md`.

- `prepare_turn` injected search results as `Relevant memory:` into every prompt. Upstream has no
  such injection; its model recalls through the tools. The kit offers the upstream shape.
- `record_turn` appended the flush model's plain text to the daily file, with no gate, no session
  entry and no `write` tool; next to `FlushRequest` it was a second flush write path.
- `chat` owned the model call and was sync-only; the kit never calls a model. Its
  `force_flush=True` went through `record_turn`; the kit's only forced flush is the labelled
  `request_flush` extension (decision Q6), which keeps the heartbeat skip and the
  one-flush-per-cycle guard.
- Delegating the three to the kit would have silently changed what they write (plain text versus
  a `write` call, forced versus gated), a breaking change hidden behind old names; the warning and
  then the removal made the change loud.
- `LangGraphMemoryRecall` (`Memory.langgraph_recall`) injected search results the way
  `prepare_turn` did. It stayed at first as an explicit, labelled adapter-only auto-recall; on
  2026-09-29 it was removed in 0.2.0 with `format_memory_context`, since it also read only role
  dicts (a LangGraph state of LangChain messages recalled nothing) and the LangGraph host
  integration uses the kit's tools (docs/integrations/langgraph.md › Fate of
  `LangGraphMemoryRecall`; Doruk confirms it as L1 there).

## How the Lab dogfoods the kit

The Lab keeps what a host keeps (provider resolution, sessions and transcripts, the tool loop over
its OpenAI-compatible engine, the event bus, snapshots, diffs and reverts, the editor, demo-only
auto-recall and transcript window, the virtual heartbeat clock) and takes every memory decision
from the kit. As built (Tasks 8 and 9, 2026-09-28):

| Lab code before the kit | Now |
| --- | --- |
| `demo/lab_tools.py`: `lab_curator`, `LabToolbox.definitions`, `_memory_search` (recall recording), `_memory_get`, `_curate`'s dispatch | `kit.tools()`, `kit.dispatch()` with `dreaming_enabled=True`; `_target` builds the daily path from `kit.curator.today()` for the before-snapshot; the toolbox keeps call records, snapshots and events (it reads them from the payloads) |
| `lab.reindex(store)` bookkeeping (`index_status`, `_index_revisions`, the `index.reindexed` event, read by `index_is_stale`) | a `LabStore(SQLiteMemoryStore)` whose `reindex` does the bookkeeping and emits the event, so kit writes (curated, flush, session memory) that call `store.reindex` keep the Lab index fresh; the Lab builds `Memory(config, workspace, store=LabStore(...))` |
| `LabRuntime.config()` without `curated_memory_writes` (the flag reached the curator through `lab_curator`) | `LabRuntime.config()` flags carry `curated_memory_writes` from `lab.settings.flags`, since the kit reads `memory.config` flags |
| `LabRuntime.ensure` (`initialize_agent_workspace` with the Lab templates) | `kit.ensure()` inside `LabRuntime.lifecycle`, which tracks the block and emits the `bootstrap.*` events of any kit call that ensures (`ensure`, `on_new_session`, `heartbeat_prompt`) |
| `demo/lab_prompt.py:lab_workspace_context`, the prompt stage's `build_prompt_section` | `kit.before_turn(state, ensure=False, ...)` at the prompt stage (the ensure stage already ran `kit.ensure()`); `offer_tools=False` for the scripted engine, which offers no tools; the prompt preview and the explorer use `ensure=False` too, so an inspector never seeds or deletes BOOTSTRAP.md |
| `demo/lab_chat.py` stages `flush_decision` and `flush` before the main run; `_persist`'s token snapshot | `kit.after_turn` after `persist` (inside `tracked("flush")`, so the empty target file shows as a flush change); the flush turn runs `FlushRequest.messages` and `.tools` through `run_tool_loop` on the turn's engine and ends with `complete()` (`demo/lab_flush.py:run_flush`); the scripted engine abandons the request |
| `demo/lab_flush.py` (plan, decision, token snapshot, flush run, forced guard, prompt estimate) | only host code is left: the `TurnUsage` from the provider's usage or the labelled chars/4 estimate, the transcript size, the gate view (the status-bar meter shows the current window's terms, the session's last `TurnRecord` and its `memoryFlush` state), the flush run and its events |
| `demo/memory_flush.py`, `ChatEngine.flush`, `_memory_flush_write_tool`, `_extract_write_tool_calls`, `FlushModelOutput`, `FlushWriteCall` | deleted; the flush is an ordinary tool-loop run |
| `/api/chat/flush` (`lab_forced`) | a labelled Lab extension over `HostKit.request_flush` (decision Q6): reason `forced`, `extension: true` and a label in the response, "Lab extension" in the UI |
| `demo/lab_api.py:start_new_session` composition | `kit.on_new_session` with the Lab's index store; the endpoint keeps its events (`session.new` now carries both session ids) and its payload |
| `demo/lab_heartbeat.py:_prepare_turn`, the run's flush decision, job recording | `kit.heartbeat_prompt(schedule_now_ms=<virtual clock>)` and `HeartbeatRun.complete`, then `after_turn` for the flush report; the preflight and the prompt inspector use `heartbeat_prompt(ensure=False)`; scratch editing, migrations and the legacy-file action stay Lab actions over the core |
| `LabSession.flush_entry`, `last_output_tokens`, `seen_truncation_signatures`, `completed_bootstrap_turn` | one `LabSession.state: SessionState` plus `last_turn: TurnRecord` |
| `demo/lab_runtime.py:DEFAULT_CONTEXT_WINDOW_TOKENS`, `MINIMAL_PROMPT_KINDS` | moved into the kit |

Kit changes Task 9 needed, each tested first: `request_flush` (decision Q6), `FlushRequest.reason`
(the trigger's reason or `forced`), `ResetTurn.prompt` (the reset prompt alone, which the Lab shows
next to the startup context) and `heartbeat_prompt(ensure=False)` (the read-only preview). The Lab
passes the kit its own clock (`now_ms`), so the flush target, the reset prompt and the curator's
day follow the Lab clock.

Observable Lab changes (Task 9), each with its tests/demo assertions:

1. The flush is decided and run after the reply (v2026.9.6 maintenance order), without the
   incoming prompt's estimate. Stage order: ensure, compaction (skip), reindex, recall, prompt,
   stream, persist, flush_decision, flush (Q1). The flush runs in the same request after the
   reply streamed and before `turn_done`; upstream runs it detached after delivery.
2. The flush turn gets the Project Context plus the `## Conversation Context` flush section and
   upstream's `write` tool wording (Q5); the prompt inspector shows its system message.
3. A chat turn in a `heartbeat` session and a heartbeat run report `runtime_skip:heartbeat` after
   the run instead of before it; a skipped heartbeat run reports no flush decision.
4. The manual `/flush` reason reads `forced` instead of `lab_forced`, labelled as a Lab extension
   (Q6); a heartbeat session gets `runtime_skip:heartbeat` without a run.
5. A due flush creates the empty daily file before the flush run, so a `NO_REPLY` flush (and a
   scripted turn's abandoned flush) leaves an empty `memory/<today>.md` (upstream
   `ensureMemoryFlushTargetFile`).
6. Without provider usage the Lab passes its labelled chars/4 estimate as `TurnUsage`, so the
   `tokenSource` label stays.
7. `/new` keeps the session key: the Lab key is `lab:<kind>` for every session of a kind, as
   upstream keeps `sessionKey` across `/new` (it was `lab:<kind>:<id>`). This shows in the
   `session.new` event (`oldSessionKey` equals `sessionKey`), in the key line of the saved
   session-memory file and in the fallback key of the `memory_search` cooldown (Q10).
8. `/new` runs an ensure and a reindex after saving the session memory (it ran neither), so the
   saved file is searchable at once and a pending bootstrap reconciles before the reset prompt is
   built: a bare `/new` in a fresh workspace now gets bootstrap mode `none`, not `limited`.
9. A heartbeat run with the scripted engine is offered no tools, as a scripted chat turn; a
   skipped heartbeat run runs no ensure.

The Lab records no `daily` recall signals after a flush write (decision Q3). Nothing else used
`record_daily_memory_flush` (memory-core's light phase records no daily signals), so it is gone; the
promotion fixtures record their daily signal with `record_short_term_recalls(signal_type="daily")`,
upstream's `recordShortTermRecalls` with `signalType: "daily"`.

## Parity labels

The kit is adapter-only code. The orders and inputs it takes from upstream (post-reply flush,
the flush target file, flush-run tool set and wording, recall tracking only with dreaming, minimal
kinds without the Memory Recall section) are source-backed with the anchors above; no matrix row
claims `match` for kit composition. Oracle results must not change: task 10 re-runs the suite.
`HostKit.request_flush` is a memory-core extension (decision Q6) with no upstream counterpart.
`TurnState`, `HostKit.dispatcher`, `after_turn(redact=)` and `HostKit.repair_tool_calls` (LangGraph
findings, 2026-09-29) are adapter-only kit code too; `repair_tool_calls` composes two core ports
(`sanitize_tool_call_inputs` and `repair_tool_use_result_pairing`, oracle-backed for their
fixtures at `64770c7`), and its labelled gaps are listed in LangGraph findings › Parity labels.

Pin-era parts the kit ships until port plan area 5 lands: the `memory_search` and `memory_get`
tool definitions and the Memory Recall section (`memory_core/prompt_section.py`, pin `4c428153`); the
tag's `buildMemoryPromptSection` wording differs (entry points 1 and 3). Recall tracking uses the
pin-era `record_short_term_recalls`, whose recall days are UTC dates (entry point 2).

Labelled deviations of the flush run (entry point 4):

- Bytes: upstream appends the content verbatim and inserts one newline only when the file is not
  empty, lacks a trailing newline and the content does not start with one
  (`agent-tools.read.ts:716-720`, `@openclaw/fs-safe` `prependNewlineIfNeeded`);
  `append_daily_memory` inserts the separator whenever a non-empty file lacks a trailing newline
  (also before content that starts with one), strips the content's trailing newlines and always
  ends the entry with `\n`.
- Empty content and the exact `NO_REPLY` token write nothing (memory-core's write rule, decision Q12;
  upstream appends even the token verbatim).
- The missing-parameter messages are memory-core's.
- Messages carry the rows' text only, and no host system prompt.
- The target file and the write refuse symlinks and hard links (stricter than upstream).

## Non-goals

Compaction and the pre-compaction checkpoint flush; a generic `read` tool; the
`heartbeat_respond` tool and system events; the upstream bounded flush view
(`Memory flush exceeds the bounded conversation view.`); auto-recall; async variants; live subject
workspaces; wiki supplements (`memory_search` supplements stay a core option the kit does not
expose yet); session auto-reset; inbound-context prefixes (`build_current_inbound_prompt`).

## Decisions (Doruk, 2026-09-28)

Doruk answered Q1-Q12 on 2026-09-28 with the recommendations:

- Q1. Flush timing: the Lab flushes after the reply, as v2026.9.6 (post-reply maintenance, no
  prompt estimate). The pin-era pre-turn flush goes (Task 9a).
- Q2. Compaction: no pre-compaction checkpoint flush now; it comes later with a compaction adapter.
- Q3. The Lab drops its `daily` recall signals after a flush write (`record_daily_memory_flush` on
  the Lab flush path). The function stays only if something else (light dreaming) still uses it;
  otherwise it goes with its tests.
- Q4. `seed_bootstrap`: the implemented default stays (`None`: BOOTSTRAP.md is seeded only when the
  host's `templates` supply it); the Lab passes `True`.
- Q5. The flush turn keeps upstream's shape with the Project Context.
- Q6. The Lab keeps `/flush` as a labelled Lab extension over one kit extension method,
  `HostKit.request_flush(session, *, transcript) -> FlushRequest | None`: no token-snapshot change,
  the heartbeat skip and the one-flush-per-cycle guard kept (`None` when the cycle already
  flushed), reason `forced`. It is labelled as an extension in code, docs and the Lab UI.
- Q7. The facade's `prepare_turn`, `chat` and `record_turn` are removed in the packaging stage (not
  in Task 9).
- Q8. `dreaming_enabled` stays a kit option.
- Q9. The kit keeps upstream's rule: history windowing does not count as a compaction; hosts that
  compact call `SessionState.after_compaction()`.
- Q10. `/new` in the Lab uses upstream's stable `sessionKey` instead of the rotating
  `lab:<kind>:<id>` key.
- Q11. The documented lane rule stays (a session's next `after_turn` waits for `complete()`); no
  pending marker.
- Q12. The flush write and the curated daily note skip only the exact `NO_REPLY` token
  (`content.strip() == "NO_REPLY"`), not a prefix, so `NO_REPLY_FACTS: ...` writes. The remaining
  deviation stays labelled: upstream's `write` appends even the exact token verbatim.

Review points not taken, with the reason:

- Port `buildMemoryPromptSection` as a Task 0: not taken; it is a parity port with its own oracle
  op and matrix row, which belongs to port plan area 5 and an oracle run. The kit labels the
  pin-era section instead.
- Return the flush run's updated truncation signatures in `FlushOutcome.session`: not taken.
  Upstream reassigns `bootstrapPromptWarningSignaturesSeen` only across fallback candidates inside
  the detached flush run (`agent-runner-memory.ts:1640-1650`) and returns only the session entry
  with `memoryFlush`; the parent session's signatures come from its own runs. The kit takes the
  session's signatures as input and leaves them unchanged.
- One `before_turn` call at the Lab's ensure stage: replaced by `kit.ensure()` there and
  `before_turn(ensure=False)` at the prompt stage, which keeps the Lab's prompt built after the
  reindex and recall stages with the same single ensure and the same events.

## Open questions

- Q13. The Lab runs the flush inside the chat request, after the reply has streamed and before
  `turn_done`, so `turn_done` waits for the flush model call, and a Stop before the flush run
  abandons its request (the turn itself stays completed with its reply). Upstream runs session
  maintenance detached after delivery. Keep it in the request (every flush event lands in its
  turn), or run it on a background thread with its own events (closer to upstream; the next turn
  may then start before `complete()`, which the kit's lane rule allows)?
- Q14. After a heartbeat run the Lab calls `after_turn` only to show `runtime_skip:heartbeat`
  (observable change 3); `HeartbeatRun.complete` has already recorded the token snapshot, and
  upstream skips maintenance for heartbeats without evaluating the gate. Keep that report, or
  show "no maintenance (heartbeat)" without the gate call?

# Part 2: TDD plan

Each task: write the named tests first and watch them fail, implement, run the offline suite
(baseline at `b829bad`: 1218 passed, 311 skipped) and `ruff check . --no-cache`, then commit that
task alone. Every test that touches a ported algorithm asserts equality with a direct call of the
core function on the same inputs, which is what "only composes" means in code. Tests are offline
and deterministic (`FeatureFlags(vector_search=False)` or `FakeEmbeddingProvider`, stub clocks).

Cut line for the first night (2026-09-28): Tasks 1-7, the kit parts of Task 10's docs, and Task 8
if time allows. Task 9 waited for Doruk's answers to Q1, Q3, Q5 and Q6 (given 2026-09-28); it splits
into 9a (flush), 9b (`/new`, with Q10) and 9c (heartbeat), one commit each. Task 10's oracle re-run
follows Task 9.

### Task 1: session state, construction, `tools()`

- Goal: the package skeleton and the two value types; `HostKit.__init__`, `HostKit.open`,
  `HostKit.ensure`, `tools()`.
- Files: `memory_core/host/__init__.py`, `memory_core/host/session.py`, `memory_core/host/kit.py`,
  `tests/unit/test_host_kit_tools.py`.
- Tests first: `test_session_state_round_trips_json`,
  `test_session_state_new_starts_a_fresh_flush_entry`,
  `test_session_state_entry_is_a_private_read_only_copy`,
  `test_after_compaction_starts_the_next_cycle`,
  `test_open_seeds_bootstrap_before_any_memory_file_exists` (templates with BOOTSTRAP.md),
  `test_open_without_bootstrap_template_completes_setup` (`seed_bootstrap=None`),
  `test_seed_bootstrap_true_seeds_an_empty_file`,
  `test_open_with_a_bad_store_config_creates_nothing`, `test_open_fts_only_needs_no_embedder`,
  `test_init_does_no_io`, `test_tools_lists_memory_tools_then_the_allowed_curation_tools`,
  `test_tools_omit_curation_tools_when_the_flag_is_off`, `test_tools_are_json_serializable`.
- Done: tests pass; `memory_core.host.__all__` lists the kit and its dataclasses; root `memory_core.__all__`
  unchanged.

### Task 2: `dispatch()`

- Goal: one tool-call entry point with the error contract and recall tracking.
- Files: `memory_core/host/kit.py`, `tests/unit/test_host_kit_dispatch.py`.
- Tests first: `test_dispatch_memory_search_equals_execute_memory_search_tool`,
  `test_dispatch_accepts_mappings_json_text_and_none`,
  `test_dispatch_invalid_json_returns_an_error_payload`,
  `test_dispatch_non_object_json_returns_an_error_payload`,
  `test_dispatch_bad_params_return_the_upstream_error_payload`,
  `test_dispatch_unoffered_tool_returns_an_error_payload`,
  `test_dispatch_curation_with_the_flag_off_writes_nothing`,
  `test_dispatch_curated_write_is_found_by_the_next_search`,
  `test_dispatch_tool_exception_becomes_an_error_payload`,
  `test_dispatch_rejects_a_non_string_name`,
  `test_dispatch_records_recalls_only_with_dreaming_enabled`,
  `test_dispatch_with_vector_search_off_never_calls_the_embedder`,
  `test_parallel_reindexes_leave_a_consistent_index`.
- Done: tests pass; if the parallel reindex test fails, a per-store lock in
  `SQLiteMemoryStore.reindex` makes it pass without changing any search result.

### Task 3: `before_turn()`

- Goal: the per-turn ensure, the stable system prompt, the runtime block and the session fold.
- Files: `memory_core/host/kit.py`, `tests/unit/test_host_kit_before_turn.py`.
- Tests first: `test_before_turn_runs_the_ensure_every_turn` (BOOTSTRAP.md reconciled away once
  `memory/` exists), `test_before_turn_without_ensure_writes_nothing`,
  `test_before_turn_prompt_equals_the_core_composition`,
  `test_minimal_kinds_get_no_memory_recall_section`,
  `test_memory_recall_section_follows_the_offered_tools`,
  `test_offer_tools_false_offers_no_tools_and_no_section`,
  `test_run_kind_overrides_the_session_default`,
  `test_runtime_context_is_wrapped_in_the_identity_markers`,
  `test_before_turn_injects_no_search_results`,
  `test_before_turn_folds_signatures_and_the_bootstrap_turn_into_the_session`,
  `test_pending_bootstrap_without_file_access_is_limited`,
  `test_retired_workspace_state_fails_closed`.
- Done: tests pass.

### Task 4a: `after_turn()` snapshot and decision

- Goal: the post-reply token snapshot and flush decision (no flush request yet).
- Files: `memory_core/host/kit.py`, `memory_core/host/session.py`, `tests/unit/test_host_kit_after_turn.py`.
- Tests first: `test_after_turn_records_a_fresh_token_snapshot`,
  `test_after_turn_without_usage_reports_missing_tokens`,
  `test_after_turn_decision_equals_explain_memory_flush_trigger` (a table of entries, windows and
  sizes), `test_after_turn_uses_no_prompt_estimate`,
  `test_after_turn_defaults_to_the_upstream_context_window`,
  `test_heartbeat_sessions_never_flush`, `test_after_turn_is_idempotent`,
  `test_after_turn_does_not_share_the_entry`.
- Done: tests pass; `TurnRecord.flush` is always `None` until 4b.

### Task 4b: `FlushRequest`, the write tool and constant extraction

- Goal: the flush run's request, the target file, the write tool and completion.
- Files: `memory_core/host/flush.py`, `memory_core/host/kit.py`, `memory_core/memory_flush.py`
  (`ensure_memory_flush_target_file`), `memory_core/workspace.py` (the shared locked daily append and
  lock), `memory_core/curation.py` (uses them), `scripts/extract_upstream_constants.py`,
  `memory_core/_memory_flush_constants.py`, `tests/unit/test_host_kit_flush.py`,
  `tests/unit/test_memory_flush_plan.py`.
- First step: read the tag for the flush run's prompt mode and the `## Conversation Context`
  header (`system-prompt.ts:1254-1257` with trigger `memory`), the `write` tool texts and the
  target-file messages; extract them by script. If upstream contradicts this spec, stop and report.
- Tests first: `test_flush_request_creates_the_empty_target_file`,
  `test_flush_target_file_refuses_paths_outside_the_workspace_and_symlinks`,
  `test_flush_setup_failure_records_a_strike`,
  `test_flush_messages_carry_context_transcript_and_prompt`,
  `test_flush_transcript_drops_runtime_context_rows`,
  `test_flush_offers_only_the_upstream_write_tool`,
  `test_flush_write_appends_to_the_target_and_reindexes`,
  `test_flush_write_accepts_the_absolute_target_path`,
  `test_flush_write_elsewhere_returns_the_upstream_restriction` (an `@` prefix too),
  `test_flush_write_skips_empty_and_no_reply_content`,
  `test_flush_write_refuses_a_symlinked_daily_file`,
  `test_flush_complete_marks_the_cycle_flushed` (on the host's current state),
  `test_flush_complete_rejects_another_session`,
  `test_flush_failures_strike_three_times_and_redact`, `test_flush_complete_twice_raises`.
- Done: tests pass; the curated daily note keeps its existing tests green on the shared append,
  whose checks (`check_writable_memory_file`) now word its model-facing symlink refusals:
  `memory/ is a symlink; memory writes never follow symlinks` (was `... curated writes never
  follow symlinks`) and `memory/<date>.md is a symlink; memory writes never follow symlinks` (was
  `memory path is a symlink: memory/<date>.md`), pinned in `tests/unit/test_curation.py`;
  then `tests/integration/test_extracted_upstream_constants.py` runs with
  `OPENCLAW_ORACLE_REPO=/tmp/openclaw-head` (a source comparison, no Node run) and passes.

### Task 5: `on_new_session()`

- Goal: the session-memory save and the bare reset turn.
- Files: `memory_core/host/kit.py`, `tests/unit/test_host_kit_new_session.py`.
- Tests first: `test_new_session_saves_the_ending_session_and_reindexes`,
  `test_new_session_keeps_the_key_and_starts_a_fresh_entry`,
  `test_bare_reset_returns_the_upstream_prompt_and_transcript_row`,
  `test_startup_context_quotes_the_saved_session_memory` (the saved file is `memory/` evidence,
  so the ensure always completes a pending bootstrap and the mode is `none`),
  `test_new_session_reconciles_a_pending_bootstrap`,
  `test_command_with_text_has_no_reset_turn`,
  `test_new_session_passes_the_redactor_and_the_slug_generator`,
  `test_new_session_uses_the_host_timezone_and_time_format`,
  `test_both_transcript_sources_raise`.
- Done: tests pass.

### Task 6: `heartbeat_prompt()` and `HeartbeatRun`

- Goal: the heartbeat turn, its context and the reply report.
- Files: `memory_core/host/heartbeat_run.py`, `memory_core/host/kit.py`,
  `tests/unit/test_host_kit_heartbeat.py`.
- Tests first: `test_heartbeat_message_equals_prepare_heartbeat_turn`,
  `test_empty_scratch_skips_without_context`,
  `test_due_heartbeat_tasks_reach_the_turn_and_other_jobs_stay_with_the_host`,
  `test_heartbeat_context_uses_run_kind_heartbeat`,
  `test_light_context_injects_no_bootstrap_file`,
  `test_schedule_clock_is_separate_from_the_prompt_clock`,
  `test_complete_records_only_the_jobs_in_the_turn`,
  `test_complete_skips_jobs_changed_or_removed_during_the_run`,
  `test_no_reply_and_ack_are_not_delivered`, `test_complete_records_usage_without_a_flush`,
  `test_heartbeat_complete_twice_raises`.
- Done: tests pass.

### Task 7: deprecate the facade's turn helpers

- Goal: `Memory.prepare_turn`, `chat`, `record_turn` warn and point to `memory_core.host`; behaviour
  unchanged.
- Files: `memory_core/client.py`, `tests/unit/test_client.py`, `tests/unit/test_examples.py`.
- Tests first: `test_prepare_turn_warns_deprecated`, `test_chat_warns_deprecated`,
  `test_record_turn_warns_deprecated`; the existing facade and example tests run under
  `pytest.deprecated_call()`.
- Done: tests pass; nothing in `memory_core/` or `demo/` calls the deprecated methods (the examples
  keep them until the quickstart rewrite). The packaging stage removed the three methods, their
  tests and `examples/chatbot_memory.py` (decision Q7).

### Task 8: Lab switch, part 1 (tools, dispatch, prompt, index bookkeeping)

- Goal: the Lab's tool loop, ensure and prompt stage run on the kit.
- Files: `demo/lab_tools.py`, `demo/lab_prompt.py`, `demo/lab_chat.py`, `demo/lab_api.py`,
  `demo/lab_kept_api.py`, `demo/lab_heartbeat.py`, `demo/lab_runtime.py`,
  `tests/demo/test_demo_app.py`.
- Wiring: `LabRuntime.config()` flags carry `curated_memory_writes` from the Lab settings;
  `LabStore` does the index bookkeeping; `LabRuntime.kit(...)` builds the kit per request from the
  Lab settings (layout, templates, `seed_bootstrap=True`, caps, injection, warning mode,
  `timezone=LAB_TIMEZONE`, `time_format=LAB_TIME_FORMAT`, `dreaming_enabled=True`); `LabSession`
  keeps its fields and gives `before_turn` a `SessionState` built from them (Task 9a replaces them).
- Tests first: `test_lab_tools_come_from_the_host_kit`,
  `test_lab_prompt_stage_uses_before_turn`, `test_prompt_preview_writes_nothing`,
  `test_kit_writes_keep_the_lab_index_fresh`; every existing tool-loop, curation-flag (flag off:
  no curation tools, no write), recall-recording and prompt-inspector test stays green unchanged.
- Done: `lab_curator`, `lab_workspace_context`, `LabToolbox._memory_get`, the Lab's own recall
  recording, its `initialize_agent_workspace` calls and the turn prompts' `build_prompt_section`
  calls are gone; tests pass. The kept `/api/prompt-preview` playground (the Memory Recall lines
  for any tool set the caller names) still calls `build_prompt_section` directly, like the other
  kept playgrounds over core functions (`/api/search`, `/api/get`). Side effect of `LabStore`: the
  pre-turn flush's reindex now also updates the Lab index status and emits `index.reindexed`
  for its turn (before, it left the index reported as stale). Side effect of the kit's error
  contract: the Lab records every error payload of an offered curated-write tool as a refused
  write with `curation.refused`. Besides the curator's refusals and failed writes
  (`MemoryToolInputError`, `write failed: ...` for an `OSError`, as before) that now includes
  invalid JSON or non-object arguments and any other exception of the write; before, those came
  back unrecorded or reached the tool loop's generic handler.

### Task 9: Lab switch, part 2 (after the decisions on Q1, Q3, Q5, Q6, Q10)

- 9a flush: `demo/lab_chat.py`, `demo/lab_flush.py`, `demo/lab_kept_api.py`, `demo/lab_runtime.py`,
  `demo/chat_engine.py`, `demo/memory_flush.py` (deleted), `tests/demo/test_chat_memory_flush.py`
  (deleted), `tests/demo/test_chat_engine.py`, `tests/demo/test_demo_app.py`, and
  `demo/static/lab/` / `demo/templates/` where stage order or labels show. Tests first (rewritten
  expectations): `test_flush_runs_after_the_reply_once_per_compaction_cycle` (S11 window 5,333: the
  flush follows the first turn over 2,000 tokens), `test_flush_write_elsewhere_is_refused_to_the_model`,
  `test_flush_without_usage_uses_the_labelled_estimate`, `test_heartbeat_kind_skips_the_flush`,
  `test_manual_flush_is_forced_once_per_cycle` (if `/flush` stays),
  `test_failed_flush_reports_the_cause_chain_redacted`, `test_no_reply_flush_leaves_an_empty_daily_file`.
- 9b `/new`: `demo/lab_api.py`, `tests/demo/test_demo_app.py`; `test_session_new_runs_the_host_kit`,
  the key behaviour of Q10.
- 9c heartbeat: `demo/lab_heartbeat.py`, `tests/demo/test_demo_app.py`; the heartbeat run tests
  with the decision after the run.
- Locked CSS strings stay. Done: the rows of the dogfood table are true in the code; tests pass; a
  real-browser check of the chat, flush, `/new` and heartbeat flows on the :8010 preview at 1280,
  820 and 640 px (the Lab's breakpoints), with the scripted engine named as scripted.
- Landed 2026-09-28: 9a `7f78de1` (with `a5906cf` for Q12, `8a00d00` for `request_flush` and
  `363d471` removing `record_daily_memory_flush`), 9b `5ffee1c`, 9c `ca54643`. The flush test's
  window 5,333 flushes after the second turn, the first whose usage (1,990 + 40) passes 2,000.
  Tests added beyond the list: `test_scripted_turn_decides_the_flush_but_runs_no_flush_turn`,
  `test_manual_flush_skips_a_heartbeat_session`,
  `test_bare_new_reconciles_a_pending_bootstrap_before_the_reset_prompt`,
  `test_heartbeat_preview_writes_nothing_and_the_run_ensures`, and kit tests for `request_flush`,
  `ResetTurn.prompt`, `heartbeat_prompt(ensure=False)` and a failed reindex after a flush write.
  Checked over HTTP on a private port (no key; the scripted engine and a local scripted stub of
  an OpenAI-compatible endpoint): a scripted turn decides `token_threshold` after the reply and
  abandons the request, a stub turn streams its reply and then writes the daily file, `/flush`
  reads `already_flushed`, `runtime_skip:heartbeat` or `forced` (and writes after `/new`), `/new`
  keeps `lab:main` with a new id and an index that is not stale, and a heartbeat run reports
  `runtime_skip:heartbeat` after its reply. The real-browser check is still open.

### Task 10: docs, matrix, re-measure

- Goal: the docs describe the kit as built; oracle results unchanged.
- Files: `docs/host_kit.md` (status and labels), `docs/package_boundary.md` (the kit exists; the
  Lab's host role; `LangGraphMemoryRecall` labelled adapter-only auto-recall), `docs/lab.md` (A chat
  turn), `docs/feature_flags.md` (`curated_memory_writes` and the kit), `docs/parity_matrix.md` (rows
  Runtime flush trigger, Recall tracking from `memory_search`, Session-memory hook, Prompt memory
  tool section (the kit ships the pin-era section until area 5), the heartbeat rows, the LangGraph
  row; audit note), `README.md` (the Install and Quickstart sections over
  `examples/quickstart.py`).
- Tests: `tests/parity/test_parity_matrix_evidence.py`; the full offline suite; the oracle suite
  (`tests/integration` with `OPENCLAW_ORACLE_REPO=/tmp/openclaw-head` and Node 24) must report
  254 passed, 81 xfailed, 2 skipped, 0 failed, after Task 9.
- Done: all green with measured numbers in the commit body.

## Follow-ups (later stages)

The packaging stage (0.2.0, CHANGELOG.md) built the package with a `demo` extra, trimmed the
package root to the kit and the core handle (the kit classes are exported there) and removed the
facade's turn helpers; the quickstart stage added `examples/quickstart.py` and the README
Quickstart over the kit. Later: live subject workspaces on the kit, the pre-compaction checkpoint
flush with a compaction adapter, session auto-reset, memory-search supplements on the kit, and
port plan area 5 (tool definitions and the Memory Recall section at the tag).

# LangGraph findings (2026-09-29)

Status: specification and TDD plan, written 2026-09-29 on `feat/kit-langgraph-fixes` (from
`main` `807508d`; first draft `9b90245`), revised after review the same day (`2d63f20`) and
implemented the same day: Task 1 `14dbdcb`, Task 2 `dcba413`, Task 3 `76dfdd7`, Task 4
`0869989`, Task 5 `89945b3`, Task 6 `9e1b00c`, Task 7 `7e1d23b`, Task 8 (docs) `0ba1cfc`; the
review fixes after it are `a851890`..`64770c7`. Each open question K1-K7 was built as its
recommendation, K3 as the recorded decision `f2351d5`; Doruk accepted all of them on 2026-09-29. Task 9:
offline 1483 passed, 325 skipped at `64770c7`; the oracle suite 268 passed, 80 xfailed, 3 skipped, 0 failed of 351 at `64770c7` (v2026.9.6, Node 24, 43 min, no rerun), the
expected counts, so both ports are oracle-backed for their fixtures. Doruk's decision L10
(docs/integrations/langgraph.md › Decisions) takes the kit changes the LangGraph findings
recommend; `F<n>` are the rows of docs/integrations/langgraph.md › Findings. Upstream anchors are v2026.9.6 (`/tmp/openclaw-head`). Task 1 needs no decision,
Task 2 needs K4 and K7, Task 3 (the adapter and the example on the turn state) K5; Tasks 4-7
(the repair) need K1-K3 and K6 (Open questions below). Each task follows its question's
recommendation (K3: the recorded decision it cites) unless Doruk answers otherwise. The review
split the first draft's Task 6 into Tasks 3 and 7, so the branch never holds two turn types.

## Scope

| Finding | Change | Kind |
| --- | --- | --- |
| F2, F3 | `TurnState`, the turn in flight as JSON (session, system prompt, runtime context, tools, the reset turn), and `ResetTurn.to_json` / `from_json`; the adapter's `PendingTurn` goes | kit, additive; adapter: `PendingTurn` removed (unreleased, 0.2.0) |
| F21 | `after_turn(..., redact=)` | kit, additive |
| F24 | `HostKit.dispatcher(session)` | kit, additive |
| F26 | `HostKit.repair_tool_calls(messages)` over host message rows: upstream's model-replay repair, composed of `sanitize_tool_call_inputs` (a new port, K2) and `repair_tool_use_result_pairing` (the existing port, brought to the tag first, K1); `ToolCallRepair`; the synthetic result's text is upstream's (K3) | core: one ported algorithm changes toward the tag and one is added (named below); kit, additive |
| F1, F7, F12, F22 | doc lines in Part 1 of this file (text below) | docs |

Everything else keeps its behaviour: the six entry points' existing parameters and results, every
other ported algorithm and every oracle result, except that the repair fixture Task 4 re-ports
turns from a strict xfail into a pass. The package root grows from 24 to 26 names (`TurnState`,
`ToolCallRepair`): every kit class is exported there (`tests/unit/test_public_api.py`).

## F2, F3: `TurnState`

```python
@dataclass(frozen=True)
class TurnState:
    session: SessionState                  # TurnContext.session: for dispatcher() and after_turn
    system_prompt: str                     # TurnContext.system_prompt
    runtime_context: str | None            # TurnContext.runtime_context (marker-wrapped)
    tools: tuple[dict[str, Any], ...]      # TurnContext.tools
    reset: ResetTurn | None = None         # the NewSession.reset this turn runs, if any

    @classmethod
    def from_context(cls, context: TurnContext, *, reset: ResetTurn | None = None) -> TurnState
    def to_json(self) -> dict[str, Any]
    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> TurnState   # ValueError: not a turn state


class ResetTurn:                           # fields unchanged (entry point 5)
    def to_json(self) -> dict[str, Any]
    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> ResetTurn   # ValueError: not a reset turn
```

- Module `memory_core/host/turn.py` (it imports `TurnContext` and `ResetTurn` from `kit.py`;
  `kit.py` does not import it). Exported by `memory_core.host` and the package root.
- It holds what the steps after `before_turn` read: each model call (`system_prompt`,
  `runtime_context`, `tools`, `reset.model_prompt`), each tool call (`session`, through
  `dispatcher`) and `after_turn` (`session`). Not `memory_recall` (already inside
  `system_prompt`), `workspace` or `workspace_init` (inspection results of `before_turn`, which
  hold a `WorkspaceContext` and do not serialize: F2's cause).
- `from_context` copies the four context fields (the tools deep-copied); `reset` is passed by
  the host, so `before_turn` stays unchanged and knows nothing of resets. `__post_init__` raises
  `TypeError` for a field of the wrong type.
- JSON, camelCase as `SessionState.to_json`: `{"session": <SessionState.to_json()>,
  "systemPrompt", "runtimeContext", "tools": [...], "reset": <ResetTurn.to_json()> | null}` and
  `{"modelPrompt", "transcriptPrompt", "bootstrapMode", "startupContext", "prompt"}`. Both round
  trip exactly and survive `json.dumps` / `json.loads`. `from_json` needs `session`,
  `systemPrompt` and `tools` (a reset turn: `modelPrompt`, `transcriptPrompt`, `bootstrapMode`
  and `prompt`); a missing `runtimeContext`, `reset` or `startupContext` reads as null and
  unknown keys are ignored, as `SessionState.from_json` does. It raises `ValueError` for a
  non-object, a missing required key, a text that is not a string (`runtimeContext` and
  `startupContext` may be null), tools that are not a list of objects, a `reset` that is neither
  an object nor null, a `bootstrapMode` outside `full`, `limited`, `none`, and whatever
  `SessionState.from_json` refuses. The JSON is unversioned, like `SessionState`'s: changes stay
  additive (new optional keys), and an incompatible change adds a `version` key, since a durable
  checkpointer keeps these values across an upgrade.
- The reset turn (F3) follows upstream's `installModelPromptTransform`
  (`src/agents/embedded-agent-runner/run/attempt-llm-boundary.ts:384-460`): on every model call
  of the turn, tool rounds included, the turn's active user message gets `reset.model_prompt` in
  place of its text, while the transcript keeps `reset.transcript_prompt` there. The active user
  message is upstream's `findActiveUserMessageIndex`
  (`src/agents/embedded-agent-runner/run/attempt-history.ts:350-383`): the last user message,
  unless an assistant message without tool calls follows it (then none). The replacement has
  upstream's guard: nothing happens when `model_prompt` is blank or equals `transcript_prompt`,
  and the text is replaced only while it is `transcript_prompt` (`replace: text ===
  params.transcriptPrompt`, via `replaceUserTextPrompt`, `:316-365`), so another active user
  message is left alone. For the turn a bare `/new` starts, the active user message is the reset
  row, so the adapter's `model_prompt_message_id` goes (K5). Placing the prompt is the host's (it
  assembles the model input); the example does it in `model_input`.
- Not serialized, on purpose: `FlushRequest` (it holds the workspace's `Memory` and its appends,
  so the flush still completes where `after_turn` ran, entry point 4) and `HeartbeatRun` (its
  jobs and `complete`). A heartbeat turn's context carries as `TurnState.from_context(run.context)`.

## F21: `after_turn(redact=)`

```python
def after_turn(
    self,
    session: SessionState,
    *,
    transcript: Sequence[Mapping[str, Any]],
    usage: TurnUsage | None,
    context_window_tokens: int | None = None,
    transcript_bytes: int | None = None,
    redact: Callable[[str], str] | None = None,
) -> TurnRecord
```

- `redact` goes to `record_memory_flush_failure(entry, error=error, redact=redact)` for a flush
  target that cannot be created, the one failure `after_turn` records, as
  `FlushRequest.complete(redact=)` passes it (`truncate_memory_flush_error_message` applies it
  before truncation, upstream's order). It changes only `TurnRecord.flush_failure.error`; the
  entry stores no message. `None` (default) keeps today's behaviour.

## F24: `HostKit.dispatcher(session)`

```python
def dispatcher(
    self, session: SessionState
) -> Callable[[str, Mapping[str, Any] | str | None], dict[str, Any]]
```

- Returns `lambda name, arguments: self.dispatch(name, arguments, session=session)`: the same
  two-argument shape as `FlushRequest.dispatch`, so one tool-answering helper serves both runs.
  It looks `self.dispatch` up at each call (a test that replaces `kit.dispatch` still reaches
  the replacement) and adds no behaviour beyond a `TypeError` at once for a `session` that is not
  a `SessionState` (`dispatch` would fail only at a `memory_search` call).
- On the kit, not on the turn object: a `TurnState` restored with `from_json` in another step has
  no kit, and a method bound inside `TurnContext` would work only in the process that built it
  (K4).

## F26: repair unanswered tool calls in host messages

### What upstream does

- Upstream repairs the replayed session history once per attempt, on a copy, and keeps that copy
  as the attempt's in-memory messages; the stored transcript is not rewritten.
  `sanitizeSessionHistory` runs at the start of an attempt
  (`src/agents/embedded-agent-runner/run/attempt-history-prepare.ts:78`), its result is limited
  and paired once more (`:165-169`) and becomes `agent.state.messages` (`:173`); tool rounds
  inside the attempt bypass that path (`run/attempt-stream.ts:243`). The replay pipeline runs
  `sanitizeToolCallInputs` (`src/agents/embedded-agent-runner/replay-history.ts:793`), then
  `sanitizeToolUseResultPairingForModel(messages, isOpenAIResponsesApi)` (`:803` for the
  Responses API, `:819` otherwise; `repairToolUseResultPairing: true` is the default policy,
  `src/agents/transcript-policy.ts:51`). The model-facing options are
  `erroredAssistantResultPolicy: "drop"` and, for the Responses API only, the missing-result
  text `aborted` (`src/agents/session-transcript-repair.ts:367-376`); on the Responses path
  `normalizeOpenAIResponsesToolCallIds` and `downgradeOpenAIFunctionCallReasoningPairs` follow
  (`replay-history.ts:805-816`).
- `repairToolUseResultPairing` (`session-transcript-repair.ts:391-480`, over
  `classifyToolUseResultPairing`, `packages/agent-core/src/harness/session/tool-result-pairing.ts:234-391`)
  moves each call's results right after its assistant message, drops orphan and duplicate
  results, pairs repeated provider ids by occurrence, lets a later real result replace a
  synthetic one, and inserts a synthetic error result (`makeMissingToolResult`, `:149-163`) for
  each call without one, except in a failed (`error` or `aborted`) assistant turn.
- `repairToolCallInputs` (`session-transcript-repair.ts:219-351`) drops a non-object message
  (`:234-237`) and a tool-call block (any of the six types of `src/shared/tool-block-contract.ts:3-10`)
  without an id (`collectToolCallIds`, `:61-70`), without input (`hasToolCallInput`,
  `src/agents/tool-call-id.ts:91-96`) or with a name that is not allowed (`session-transcript-repair.ts:285-295`; a name must
  match `TOOL_CALL_NAME_RE` and fit `TOOL_CALL_NAME_MAX_CHARS`, `src/agents/tool-call-shared.ts:10-11,33-51`,
  and be in `allowedToolNames` when given, compared lower-cased, `:14-30,47-51`, unless the call
  already has a real result, `:54-58`), strips a finalized Responses call's `partialJson` and drops
  any other block with one, trims names, and drops an assistant message left with no content
  (`session-transcript-repair.ts:327-331`).
- The stored transcript is not repaired for an OpenAI-compatible provider: the session guard
  persists synthetic results only with `allowSyntheticToolResults`, which the default policy
  leaves off and only Google, Anthropic and Responses-API models turn on
  (`transcript-policy.ts:60,162`; `src/agents/session-tool-result-guard.ts:752-790`). The guard
  does run `sanitizeToolCallInputs` on each assistant message it appends (`:804-813`).

So upstream never removes an assistant message for an unanswered call: the model copy gets a
synthetic error result after it, and a call without an id is dropped from the copy. The example's
`RemoveMessage` is the deviation; the upstream shape is a repair of the model input.

### The existing port lags the tag (K1)

`memory_core/replay_repair.py` is pin-era (`4c428153`): its oracle fixture
`repair_tool_use_result_pairing_matches_python` is a strict xfail at the tag
(`tests/integration/oracle_worklist.py`, area 10). Probe of 2026-09-29 on `807508d` (the real TS
function through the oracle runner, Node 24.21.0), three fixtures:

| Fixture | Tag | Pin-era port |
| --- | --- | --- |
| the oracle fixture (a displaced result, one missing) | synthetic result `details` `{"openclawSyntheticMissingToolResult": true, "reason": "missing_tool_result"}` | the same without `reason`; everything else equal |
| an unanswered call, then a user message, policy `drop` | synthetic result after the call, `reason` set | the same without `reason` |
| one provider id on two turns (`c1`, result, user, `c1`, result) | unchanged: both results kept, `droppedDuplicateCount` 0 | the second real result and its synthetic replacement dropped as duplicates (`droppedDuplicateCount` 2), the second `c1` left unanswered |

The last row decides it: a repair over the pin-era port breaks a valid history whose provider
reuses call ids (the port keeps one global id set) and hands the provider exactly the unanswered
call the repair exists to remove. The kit therefore composes the port only after Task 4 brings it
to the tag. That is a behaviour change of a ported algorithm, required by F26 and taken toward
upstream, with the tag's oracle as evidence. Source reading adds one more change: a second result
for a call within its frame counts in `droppedDuplicateCount` at the tag (upstream's test "changed
flag is true when duplicates are dropped", `session-transcript-repair.test.ts:827-838`), where the
pin-era port drops it silently; the existing unit test that pins 0 moves to 1.

### Signature and composition

```python
def repair_tool_calls(
    self,
    messages: Sequence[Mapping[str, Any]],
    *,
    allowed_tool_names: Iterable[str] | None = None,
) -> ToolCallRepair


@dataclass(frozen=True)
class ToolCallRepair:
    messages: tuple[Mapping[str, Any], ...]  # the rows to send the model, in order
    sources: tuple[int | None, ...]          # per row: the index of the host row it is or copies;
                                             # None for a synthetic tool result
```

- A `HostKit` method, next to the other per-turn calls; it reads no file, writes nothing and
  depends on no kit option (K3: the text is upstream's for every identity). Implemented in
  `memory_core/host/tool_calls.py` (the row mapping; the plan named it `_tool_calls.py`) over
  the two core functions, as entry point 2 composes the tools. Upstream's Responses-API steps are not offered (Parity labels).
- Host rows are the chat-completions message shape the kit already reads:
  - `{"role": "assistant", "content", "tool_calls": [...]}`, each call either
    `{"id", "type": "function", "function": {"name", "arguments"}}` or the flat
    `{"id", "name", "args" | "arguments"}` (LangChain's dict form). Tool calls are read from
    `tool_calls` only (a legacy `function_call` is neither read nor rewritten). The content is a
    string, which counts as content when it is not empty, or a list whose blocks are carried
    except the six tool-call block types of `tool-block-contract.ts:3-10`: those are neither read
    nor rewritten, so a call is never counted twice (an Anthropic-style message carries its calls
    in both places);
  - `{"role": "tool", "tool_call_id", "content", "status"?, ...}`;
  - any other row passes through.
  A row that is not a mapping raises `TypeError` (host error).
- Composition, in upstream's order:
  1. map each row to upstream's message shape: an assistant row becomes `{"role": "assistant",
     "content": [<a text block of a non-empty string, or the list's other blocks>, {"type":
     "toolCall", "id", "name", "arguments"} ...]}`, a tool row `{"role": "toolResult",
     "toolCallId" (when a string), "toolName" (its `name`, when present), "content", "isError":
     status == "error"}`, any other row a role-less stand-in both repairs pass through. Each
     mapped message and call carries a private index key, which the repairs' copies keep and
     the kit never returns. Host rows carry no stop reason, so no frame is failed;
  2. `memory_core/replay_repair.py:sanitize_tool_call_inputs(mapped, allowed_tool_names=...)`
     (Task 5, upstream `sanitizeToolCallInputs`);
  3. `repair_tool_use_result_pairing(..., errored_assistant_result_policy="drop")` with
     upstream's default text (Task 4), as `sanitizeToolUseResultPairingForModel` calls it off
     the Responses path;
  4. map back by the index keys: an unchanged host row is returned as the same object, and so is
     a tool row changed only by the tool-name normalization; an assistant row the input repair
     changed is a shallow copy `{**row, "tool_calls": <kept calls>}`, the kept calls being the
     input call mappings when unchanged, else shallow copies with the trimmed name (`{**call,
     "name": ...}`, or `function.name` in the OpenAI shape), in their order; when no call is
     kept the copy has no `tool_calls` key (an empty array is rejected by OpenAI); an assistant
     row it dropped, and every dropped orphan or duplicate tool row, is left out; moved tool rows
     keep their objects; a tool row without an id (no `tool_call_id` string, or a blank one,
     which `extractToolResultIds` trims to nothing) that the legacy-id normalization
     (`normalizeLegacyToolResultId`) paired comes back as `{**row, "tool_call_id": <id>}`, with
     `"status": "error"` when the row has a `status` (upstream returns it with `isError: true`;
     the review fix after `0ba1cfc`); a
     synthetic result is a new row `{"role": "tool", "tool_call_id", "content": <text>}`, the plain
     chat-completions shape (a strict validator rejects extra keys such as `status`).
- Nothing to repair: `messages` are the input rows themselves in order, `sources` `0..n-1`.
- Where a host uses it: on the history of every model call of a turn, before the runtime
  context and the reset prompt are placed. That is a superset of upstream's once-per-attempt
  repair: a well-formed tool round inside the turn comes back unchanged. The host keeps its
  stored transcript as it is (upstream's default for OpenAI-compatible providers, K6);
  `after_turn`, `request_flush` and `on_new_session` read only the text of user and assistant
  rows, so an unanswered call there changes nothing.
- Kit docs line (entry point 3): "A turn that failed between a tool-call reply and its tool
  results leaves calls without results; send `kit.repair_tool_calls(history).messages` to the
  model instead of the history (upstream repairs the replayed history the same way at the start
  of each attempt)."

### Core changes

- Task 4, re-port `repair_tool_use_result_pairing` to v2026.9.6 (port plan area 10):
  `classifyToolUseResultPairing` with its occurrence queue, synthetic-to-real replacement,
  results displaced into a later frame claimed by the one unresolved occurrence that owns them,
  `preserve_unframed_tool_results` (upstream `preserveUnframedToolResults`), the `discarded`
  list on `ToolUseRepairReport` (a new field, last, with `field(default_factory=list)`), and
  `reason: "missing_tool_result"` in the synthetic `details`; also `is_synthetic_missing_tool_result`
  and `collect_completed_tool_call_blocks` (upstream `isSyntheticMissingToolResult`,
  `collectCompletedToolCallBlocks`, `tool-result-pairing.ts:165-192,394-407`), which Task 5
  needs. `DEFAULT_MISSING_TOOL_RESULT_TEXT` and `SYNTHETIC_MISSING_TOOL_RESULT_DETAIL_KEY` become
  script-extracted constants (`scripts/extract_upstream_constants.py`, a new output
  `memory_core/_transcript_repair_constants.py`, checked by
  `tests/integration/test_extracted_upstream_constants.py`). Named behaviour changes: repeated
  ids pair by occurrence (the probe's third row), a later real result replaces a synthetic one,
  a displaced result can cross into a later frame, a second result within a frame counts as a
  duplicate, and the synthetic `details` carry `reason`. No caller in `memory_core/` or `demo/`
  uses the port today, so only its tests move.
- Task 5, port `sanitize_tool_call_inputs(messages, *, allowed_tool_names=None) -> list` (upstream
  `sanitizeToolCallInputs` over `repairToolCallInputs`, `session-transcript-repair.ts:36-92,219-358`,
  with `collectToolCallIds` and the six block types of `tool-block-contract.ts:3-70`,
  `hasToolCallInput` of `tool-call-id.ts:91-96`, `normalizeAllowedToolNames`,
  `isAllowedToolCallName` and `createCompletedToolCallPredicate` of `tool-call-shared.ts:10-58`,
  and `safeParseJsonRecord` of `packages/normalization-core/src/json-coercion.ts:13-15`): the
  general branch (the id, input and name rules with the completed-call exemption over Task 4's
  classifier, the finalized-Responses `partialJson` strip, name trimming, dropping an emptied
  assistant message and a non-object message). Not ported, labelled at the code site: the
  provider-owned thinking replay branch (`allowProviderOwnedThinkingReplay`, `:244-277`) and the
  compaction replay checkpoint rewrite of `replaceCompactionReplayOwnerContent` (a message
  without `providerReplay` is `{...message, content}`, which is what the port does). New oracle
  op `sanitizeToolCallInputs` in `scripts/openclaw_oracle_runner.ts` (the real TS function);
  `TOOL_CALL_NAME_MAX_CHARS` and `TOOL_CALL_NAME_RE` script-extracted into the same constants
  file.
- The synthetic text (K3): the kit uses upstream's `DEFAULT_MISSING_TOOL_RESULT_TEXT` for every
  identity, the port's default. MEMORY.md › Durable decisions (`f2351d5`) keeps
  "[openclaw] missing tool result" as a parity-bound marker, and upstream recognises a stored
  synthetic result by that text when its `details` are gone (`isSyntheticMissingToolResult`,
  `tool-result-pairing.ts:165-192`). No `RuntimeIdentity` field is added.

## Doc lines in Part 1

- F1, under `SessionState`: "A framework whose state must serialize keeps `to_json()` there and
  reads it with `from_json` in each step: a LangGraph checkpointer refuses the object itself
  (`TypeError: Type is not msgpack serializable: SessionState`). `TurnState` and `ResetTurn`
  carry a turn and a reset the same way."
- F7, next to `FlushRequest`: "The flush run's model output is never delivered: a host that
  streams model output (a framework's token stream, server-sent events) tags the flush run's
  model calls out of that stream or runs them outside it (LangGraph: `TAG_NOSTREAM`). Upstream
  runs the flush as detached maintenance whose output no channel sees."
- F12, under `after_turn`: "The default window is upstream's `DEFAULT_CONTEXT_TOKENS` and is
  right only for a model with a 200,000-token window. From an 80,000-token window up the flush
  threshold is the window minus the reserve floor (20,000) and the soft threshold (4,000): the
  default puts it at 176,000, above a 128,000-token model's window (whose own threshold is
  104,000), so that model's flush never runs. Pass the model's window."
- F22, under `before_turn` and in the Turn lifecycle diagram (`model call (host): system_prompt,
  history, runtime_context, user message`): "Send `runtime_context` as a user-role message
  immediately before the turn's user message, on every model call of the turn, and never record
  it in the transcript: upstream binds its runtime-context carrier to the turn's user message and
  inserts it before that message (`src/agents/embedded-agent-runner/run/attempt-llm-boundary.ts:240-268`;
  `findActiveUserMessageIndex` finds the message only on a retry, where none means no carrier),
  sends that custom message as a user message (`packages/agent-core/src/harness/messages.ts:139-153`)
  and strips carriers of earlier turns from replays (`src/agents/internal-runtime-context.ts:379-400`).
  The block's header text ("... for the immediately preceding user message") is upstream's
  wording and does not change the placement." The README line ("the dynamic part to send after
  the stable `turn.system_prompt`") gets the same placement.

## Adapter and example

`memory_core/adapters/langgraph.py`:

- `PendingTurn` is removed (Task 3; `TurnState` replaces it; sterile, no second turn type).
- `transcript_rows` is unchanged: `after_turn`, `on_new_session` and the session-memory file
  read the same rows as before.
- New `repair_tool_calls(messages, repair) -> list[Any]` (Task 7), with `repair` =
  `kit.repair_tool_calls` or a function that passes it `allowed_tool_names`. It maps the messages
  to host rows (`transcript_rows`' mapping, plus an AI message's calls as `tool_calls`: its valid
  calls `{"id", "name", "args"}`, then its invalid ones with their raw `args` text, the order
  `tool_messages` answers them in, each with a private index key; and a tool message's
  `status`), runs `repair`, and maps back by `ToolCallRepair.sources`:
  - a row returned unchanged is its original message object;
  - a changed AI message is a copy with only the kept calls: `tool_calls` and
    `invalid_tool_calls` rebuilt from the original calls by the index keys (trimmed names
    applied), `additional_kwargs["tool_calls"]` filtered by the kept ids, and
    `additional_kwargs["function_call"]` and `tool_call_chunks` dropped when no call is kept
    (langchain-openai 1.6.6 sends `additional_kwargs["tool_calls"]` when both lists are empty,
    `langchain_openai/chat_models/base.py:490-498`); `model_copy(update=...)` for a message
    object, a dict copy for its dict forms, and the kit's row for a role dict;
  - a tool message without an id (none, or blank) that the kit paired with its frame's only call
    is a copy with that call's `tool_call_id` and `status: "error"` (the review fix after
    `0ba1cfc`);
  - a synthetic result is a tool dict with the owning call's `name` and `status: "error"` added
    (the shape `tool_messages` emits; langchain-core 1.6.5 converts it to
    `ToolMessage(status="error")`).
  The exports stay five names: `transcript_rows`, `turn_usage`, `has_tool_calls`,
  `tool_messages`, `repair_tool_calls` (four between Tasks 3 and 7).
- `tool_messages`' docstring names `kit.dispatcher(session)` instead of `functools.partial`.

`examples/langgraph_agent.py`:

- Task 3: `memory_turn` holds `TurnState.to_json()`, `memory_reset` holds
  `NewSession.reset.to_json()`; `prepare` builds `TurnState.from_context(kit.before_turn(...),
  reset=ResetTurn.from_json(...))`. `new_session` no longer makes a message id for the reset row
  (one `new_id()` call less per `/new`; the tests' fixed id sequences shift accordingly).
  `model_input(turn, messages)` finds the active user message (upstream's rule, above, read on
  message objects and dicts alike: a user is type `human` or role `user`, an assistant type `ai`
  or role `assistant`, with tool calls by `has_tool_calls`), gives it `turn.reset.model_prompt`
  under upstream's guard, and puts the runtime context right before it; with no active user
  message it appends the runtime context at the end (the example's choice: the agent node always
  has the turn's user message). `tools` answers through `tool_messages(last,
  kit.dispatcher(turn.session))`, so the `functools` import goes. `maintain` passes
  `redact=redact` to `after_turn` and drops its own rebuild of the `MemoryFlushFailureOutcome`
  and that import.
- Task 7: `model_input(turn, messages, repair)` starts from `repair_tool_calls(messages,
  repair)`, and the agent passes `lambda rows: kit.repair_tool_calls(rows,
  allowed_tool_names=[tool["name"] for tool in turn.tools])`, as upstream passes the run's tool
  names (`replayAllowedToolNames`). `unanswered_tool_calls` and the `RemoveMessage` in `prepare`
  go: the stored `messages` keep a failed turn's AI message, and every model call gets the
  repaired copy. A call without an id still makes `tool_messages` raise (F19), so
  `graph.invoke(None, config)` still reruns that failure; the next message works, because the
  input repair drops the call from the copy.
- The labelled deviation "an AI message whose tool calls a failed turn left unanswered is
  removed" leaves docs/integrations/langgraph.md › Parity labels, and audit note 24 follows note
  23.

## Parity labels

`TurnState`, `dispatcher`, `repair_tool_calls` and its row mapping are adapter-only kit code; the
orders and options they take from upstream are source-backed with the anchors above, and no row
claims `match` for them. The two core ports are oracle-backed for their fixtures since Task 9
ran them at `64770c7`: `repairToolUseResultPairing` (both existing fixtures plus Task 4's) and
the new `sanitizeToolCallInputs` op. docs/parity_matrix.md
row "Active transcript and context injection" keeps `partial`: its oracle column gains
`sanitizeToolCallInputs`, its note counts the repair fixtures, and its "Remaining HEAD gaps" lose
the synthetic-vs-real replacement and the `partialJson` handling. Labelled gaps of the kit's
repair: host rows carry no stop reason (no failed frame); tool-call blocks inside a content list
and a legacy `function_call` are neither read nor rewritten (a dropped call's content block stays
in the copy); the thinking-replay branch and the compaction replay checkpoint rewrite of the input
repair are not ported; upstream's Responses-API steps (the `aborted` text,
`normalizeOpenAIResponsesToolCallIds`, `downgradeOpenAIFunctionCallReasoningPairs`) are not
offered; a host that stores its transcript does not get upstream's persisted synthetic results for
Google, Anthropic or Responses-API models (K6); and a stored synthetic row of the kit's plain
shape (no `status`) reads as a real result on a later repair, since upstream's recognition needs
`isError`, while the adapter's row (`status: "error"`) is recognised by upstream's text; likewise
a paired id-less row without a `status` goes back without upstream's `isError: true` (a row with
one, and every LangChain `ToolMessage`, gets `status: "error"`).

## TDD plan

Each task: the named tests first (watch them fail), implement, the offline suite (baseline at
`807508d`: 1396 passed, 312 skipped), `ruff check . --no-cache`,
`scripts/rename_project.py --check`, then one commit. A task that changes the extracted constants
also runs `tests/integration/test_extracted_upstream_constants.py` (Python only, it needs
`OPENCLAW_ORACLE_REPO`); a task that changes the matrix runs `tests/parity`. The oracle fixtures of
Tasks 4 and 5 run in Task 9 (the implementation stage runs no oracle).

### Task 1: `TurnState` and the reset turn's JSON (F2, F3)

- Files: `memory_core/host/turn.py`, `memory_core/host/kit.py` (`ResetTurn.to_json` /
  `from_json`), `memory_core/host/__init__.py`, `memory_core/__init__.py`,
  `tests/unit/test_host_kit_turn_state.py`, `tests/unit/test_public_api.py` (`ROOT_API`).
- Tests first: `test_turn_state_round_trips_json`,
  `test_turn_state_survives_json_text`, `test_turn_state_from_context_keeps_what_later_steps_need`,
  `test_turn_state_carries_the_reset_turn`, `test_turn_state_tools_are_private_copies`,
  `test_turn_state_rejects_a_field_of_the_wrong_type`,
  `test_turn_state_from_json_rejects_a_bad_shape` (parametrized),
  `test_turn_state_from_json_reads_missing_optional_keys_as_null_and_ignores_unknown_keys`,
  `test_reset_turn_round_trips_json`, `test_reset_turn_from_json_rejects_a_bad_shape`
  (an unknown bootstrap mode among them), `test_root_exports_exactly_the_host_surface` (with
  `TurnState`).
- Done: tests pass; `before_turn`'s results unchanged.

### Task 2: `dispatcher` and `after_turn(redact=)` (F24, F21; K4, K7)

- Files: `memory_core/host/kit.py`, `tests/unit/test_host_kit_dispatch.py`,
  `tests/unit/test_host_kit_after_turn.py`; with K7 `examples/quickstart.py`, README.md
  (Quickstart) and `tests/unit/test_examples.py`.
- Tests first: `test_dispatcher_equals_dispatch_with_the_session` (every error payload of entry
  point 2 too), `test_dispatcher_reaches_a_replaced_dispatch`,
  `test_dispatcher_rejects_a_session_that_is_not_a_session_state`,
  `test_after_turn_redacts_a_flush_target_failure`,
  `test_after_turn_without_redact_keeps_the_failure_message`.
- Done: tests pass.

### Task 3: the adapter and the example on the turn state (F2, F3, F21, F24; K5)

- Files: `memory_core/adapters/langgraph.py`, `memory_core/adapters/__init__.py`,
  `examples/langgraph_agent.py`, `tests/unit/test_langgraph_adapter.py`,
  `tests/unit/test_langgraph_agent.py`, docs/integrations/langgraph.md (the adapter table the
  doc test reads).
- Tests first: `test_reset_turn_substitutes_the_active_user_message_on_every_call` (a reset turn
  with a tool round), `test_model_input_replaces_only_the_transcript_prompt` (another active user
  message is left alone; a blank model prompt changes nothing),
  `test_model_input_reads_dict_rows` (a tool dict before the active user message),
  `test_redact_maps_a_flush_target_failure` (now through `after_turn(redact=)`),
  `test_langgraph_doc_lists_the_adapter_exports` (four names); the three `PendingTurn` tests go;
  every other graph test stays green with the shifted ids.
- Done: tests pass; nothing in the example imports `functools`, `PendingTurn` or
  `MemoryFlushFailureOutcome`.

### Task 4: re-port the tool-result pairing repair to the tag (K1)

- Files: `memory_core/replay_repair.py`, `scripts/extract_upstream_constants.py`,
  `memory_core/_transcript_repair_constants.py`, `scripts/openclaw_oracle_runner.ts` (pass
  `preserveUnframedToolResults`, return `discarded`), `tests/unit/test_replay_repair.py`,
  `tests/integration/test_openclaw_ts_oracle.py`, `tests/integration/oracle_worklist.py` (the
  fixture leaves area 10's tuple), `tests/integration/test_extracted_upstream_constants.py`,
  docs/parity_matrix.md (the row and audit note 24), docs/upstream_port_v2026_9_6.md (area 10).
- First step: re-read `tool-result-pairing.ts` and `session-transcript-repair.ts:391-480` at the
  tag; if either contradicts this section, stop and report.
- Tests first (unit, cases from upstream's `session-transcript-repair.test.ts` where they apply):
  `test_repeated_provider_ids_pair_by_occurrence`,
  `test_a_later_real_result_replaces_a_synthetic_one`,
  `test_a_displaced_result_is_claimed_by_its_unresolved_call`,
  `test_ambiguous_displaced_results_are_dropped`,
  `test_unframed_results_are_kept_with_preserve_unframed`,
  `test_synthetic_results_carry_the_missing_result_reason`,
  `test_discarded_lists_dropped_results_in_source_order`,
  `test_a_second_result_within_a_frame_counts_as_a_duplicate` (the existing test's 0 becomes 1);
  the other three existing tests stay green. Oracle: `repair_tool_use_result_pairing_matches_python`
  passes (no longer xfail), both existing fixtures compare `discarded` too, and new fixtures
  `repair_tool_use_result_pairing_repeated_ids_match_python`,
  `..._synthetic_replacement_matches_python`, `..._displaced_across_frames_matches_python`,
  `..._preserve_unframed_matches_python`.
- Done: tests pass; the constants check passes.

### Task 5: port the tool-call input repair (K2)

- Files: `memory_core/replay_repair.py`, `scripts/extract_upstream_constants.py`,
  `memory_core/_transcript_repair_constants.py`, `scripts/openclaw_oracle_runner.ts` (op
  `sanitizeToolCallInputs`), `tests/unit/test_replay_repair.py`,
  `tests/integration/test_openclaw_ts_oracle.py`, docs/parity_matrix.md.
- Tests first (unit): `test_input_repair_drops_calls_without_an_id_or_input`,
  `test_input_repair_drops_calls_with_a_bad_name`,
  `test_input_repair_matches_allowed_names_case_insensitively`,
  `test_input_repair_keeps_a_completed_call_outside_the_allowed_names`,
  `test_input_repair_drops_an_emptied_assistant_message`,
  `test_input_repair_trims_names`, `test_input_repair_strips_a_finalized_responses_partial_json`,
  `test_input_repair_reads_snake_case_block_types`,
  `test_input_repair_returns_the_input_list_when_nothing_changes`. Oracle:
  `sanitize_tool_call_inputs_matches_python` (parametrized over those nine cases).
- Done: tests pass; the constants check passes.

### Task 6: `HostKit.repair_tool_calls` (F26, K3, K6)

- Files: `memory_core/host/tool_calls.py` (planned as `_tool_calls.py`), `memory_core/host/kit.py`,
  `memory_core/host/__init__.py`, `memory_core/__init__.py`, `tests/unit/test_host_kit_repair.py`,
  `tests/unit/test_public_api.py`.
- Tests first: `test_repair_equals_the_core_repair_of_the_mapped_messages` (a table of host
  transcripts: the mapped output of steps 2-3 called directly),
  `test_repair_answers_an_unanswered_call_after_its_assistant_row`,
  `test_repair_moves_a_displaced_tool_row_before_the_next_user_row`,
  `test_repair_drops_orphan_and_duplicate_tool_rows`,
  `test_repair_keeps_repeated_provider_ids_on_later_turns`,
  `test_repair_drops_a_call_without_an_id_and_an_emptied_assistant_row`,
  `test_repair_removes_the_tool_calls_key_when_no_call_is_kept`,
  `test_repair_reads_openai_and_flat_tool_call_shapes` (trimmed names in both),
  `test_repair_gives_a_paired_legacy_tool_row_its_call_id`,
  `test_repair_leaves_content_tool_call_blocks_unread`,
  `test_repair_passes_the_allowed_tool_names`,
  `test_repair_returns_the_host_rows_themselves_when_nothing_changes`,
  `test_repair_sources_point_at_the_host_rows`,
  `test_repair_synthetic_row_is_plain_chat_completions` (upstream's text under both identities),
  `test_repair_rejects_a_row_that_is_not_a_mapping`, `test_repair_touches_no_file`.
- Done: tests pass.

### Task 7: the adapter's repair and the example on it (F26; K6)

- Files: `memory_core/adapters/langgraph.py`, `memory_core/adapters/__init__.py`,
  `examples/langgraph_agent.py`, `tests/unit/test_langgraph_adapter.py`,
  `tests/unit/test_langgraph_agent.py`, docs/integrations/langgraph.md (the adapter table).
- Tests first (adapter): `test_repair_tool_calls_returns_the_original_messages_when_nothing_changes`,
  `test_repair_tool_calls_inserts_a_synthetic_tool_message`,
  `test_repair_tool_calls_copies_an_ai_message_without_its_dropped_calls` (both call lists and
  `additional_kwargs`; langchain-openai's request dict of the copy has no dropped call),
  `test_repair_tool_calls_reads_role_and_type_dicts`.
  Tests first (graph): `test_next_message_after_a_failed_tools_node_repairs_the_unanswered_call`
  (replaces `..._drops_the_unanswered_call`; dispatch raises: the model gets `[system, human,
  ai(call-1), tool(synthetic, status error), human]` and `messages` keep the AI message; a call
  without an id: the model gets `[system, human, human]`),
  `test_langgraph_doc_lists_the_adapter_exports` (five names); every other graph test stays
  green.
- Done: tests pass; `unanswered_tool_calls` is gone.

### Task 8: docs

- docs/host_kit.md: the doc lines above into Part 1, entry-point text for `TurnState`,
  `dispatcher`, `redact` and `repair_tool_calls`, the Status line.
- docs/integrations/langgraph.md: F2, F3, F7, F12, F21, F22, F24, F26 and F1 marked addressed with
  their commits; Usage, State schema, Kit calls per node, Adapter surface, Error handling and
  Parity labels follow the new code; the stale lines that `build_graph` takes the kit's default
  for `None` (L11 made the window required).
- README.md: the runtime-context placement.
- CHANGELOG.md › 0.2.0: Added (`TurnState`, `ResetTurn.to_json` / `from_json`,
  `HostKit.dispatcher`, `after_turn(redact=)`, `HostKit.repair_tool_calls`, `ToolCallRepair`,
  `sanitize_tool_call_inputs`, the adapter's `repair_tool_calls` in place of `PendingTurn`);
  Changed (the pairing repair's behaviour changes, named); the root count 24 to 26.
- docs/package_boundary.md (the adapter's names), docs/parity_matrix.md audit note 24 and
  `tests/parity`.

### Task 9: verify

- The full offline suite, ruff, the name check, `tests/parity`, and the oracle suite
  (`tests/integration`, `OPENCLAW_ORACLE_REPO=/tmp/openclaw-head`,
  `OPENCLAW_ORACLE_NODE=/opt/homebrew/opt/node@24/bin/node`). Expected against the reference
  (254 passed, 81 xfailed, 3 skipped, 0 failed of 338): 351 tests, 268 passed (the reference,
  Task 4's worklist fixture, its four new fixtures and the nine `sanitize_tool_call_inputs`
  cases), 80 xfailed, 3 skipped, 0 failed. A lone 20 s runner timeout gets one rerun of that test
  id, reported as such. The measured numbers go into the commit body,
  docs/integrations/langgraph.md and the audit note. The main session runs the live LangGraph
  test.

## Open questions

Answered on 2026-09-29: Doruk accepted K1-K7 as recommended (K3 as the recorded decision
`f2351d5`).

- K1. Re-port `repair_tool_use_result_pairing` to the tag in this branch (recommended: the kit
  cannot compose the pin-era port, which breaks histories with repeated provider ids, probe
  above), or keep the pin-era port and ship the kit repair with that as a known gap, or leave
  F26 to port plan area 10?
- K2. Port upstream's input repair (`sanitizeToolCallInputs`, the general branch, with a new
  oracle op; recommended: it is the first step of upstream's replay repair and the only upstream
  treatment of a call without an id), or skip it and have the adapter drop calls without an id
  from the model's copy (a labelled slice of one rule)?
- K3. The synthetic result's text in the kit: upstream's `DEFAULT_MISSING_TOOL_RESULT_TEXT`
  ("[openclaw] missing tool result ...") for every identity, which the recorded decision
  `f2351d5` keeps as a parity-bound marker (the implementation follows it), or reverse `f2351d5`
  for the kit with a `RuntimeIdentity.missing_tool_result_text` reading "[memory-core] missing
  tool result ..." (the pattern of the heartbeat and reset rows)? The text is model-facing, not
  user-facing UI (USER.md bans the brand there), though a model may quote it. A memory-core text
  would also make upstream's `isSyntheticMissingToolResult` miss a stored kit row (it matches the
  `details` key or that exact text), so a later repair would treat it as a real result.
- K4. `HostKit.dispatcher(session)` (recommended: it works for a `TurnState` restored from JSON)
  or a `TurnContext.dispatch` bound method (in-process only)?
- K5. The reset prompt replaces the turn's active user message under upstream's guard
  (upstream's rule; recommended), dropping the adapter's message id, or does `TurnState` keep an
  opaque host reference to the message?
- K6. The kit repairs the model's copy only and the host keeps its transcript (recommended:
  upstream's default policy for OpenAI-compatible providers), or does the kit also offer the
  persisted synthetic results upstream's guard writes for Google, Anthropic and Responses-API
  models?
- K7. Switch `examples/quickstart.py` and the README Quickstart that shows it from its lambda to
  `kit.dispatcher(turn.session)` in Task 2 (recommended: the quickstart then shows the kit's own
  idiom; one line each)?
