# memory-core host kit (`memory_core.host`)

Status: specification and TDD plan, written 2026-09-28 on `feat/host-kit` (from `main`
`b829bad`). Nothing in this document is implemented yet. Upstream anchors are OpenClaw
v2026.9.6 (`eb377ac59e6`, checkout `/tmp/openclaw-head`) unless a line says otherwise.

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
- It writes only through the existing write paths: `MemoryWorkspace.append_daily_memory`, the
  curation tools behind `FeatureFlags.curated_memory_writes`, `save_session_memory`, the
  automation store.

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
        seed_bootstrap: bool = True,
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
        # plus every keyword option of __init__, spelled out
    ) -> HostKit: ...
```

- Every option is an input some core function already takes. The Lab uses each of them except
  `identity` (memory-core's compat markers), `seed_bootstrap` (hosts without a bootstrap ritual, Q4)
  and `now_ms` (deterministic tests):
  `layout`, `templates`, `seed_bootstrap` (`initialize_agent_workspace`); `timezone` and
  `time_format` (the flush plan, the curator's "today", the session-memory stamp, the startup
  context, the reset prompt and the heartbeat time line all take the one host value, as
  `memory_core/current_time.py` asks); `identity` (context markers, transcript rows);
  `curation_policy` (`MemoryCurator`, default `CurationPolicy.for_layout(layout)`); the
  bootstrap caps, `context_injection` and `truncation_warning_mode`
  (`build_workspace_context`); `dreaming_enabled` (recall tracking, see `dispatch`);
  `automation_store` (default `FileAutomationStore(root)`); `now_ms` (epoch-ms clock, as
  `MemoryCurator` takes it). The agent id is `memory.config.agent_id`.
- `__init__` does no I/O beyond validating the timezone and the curation policy against the
  layout, so a host whose settings change (the Lab) builds a new kit per request.
- `open` checks the store config first (`validate_store_config`, so a call that raises leaves no
  file behind), runs `initialize_agent_workspace`, then `Memory.from_workspace(...,
  initialize=False, reindex=True)`. The order matters: `initialize_memory_core_workspace`
  writes MEMORY.md, which counts as setup evidence, so opening `Memory` first would stop
  BOOTSTRAP.md from ever being seeded (`memory_core/bootstrap/lifecycle.py:initialize_agent_workspace`
  docstring). Hosts that build their own `Memory` (the Lab, one store per search mode) use
  `HostKit(memory, ...)` and keep the same order themselves.

### `SessionState`: one per session, stored by the host

```python
@dataclass(frozen=True)
class SessionState:
    session_key: str                 # upstream sessionKey; stays the same across /new
    session_id: str                  # upstream sessionId; new on /new and /reset
    kind: SessionKind = "main"       # main, group, channel, direct, heartbeat, subagent, cron
    entry: Mapping[str, Any] = field(default_factory=dict)  # SessionEntry fields of the flush gate
    last_output_tokens: int | None = None
    seen_truncation_signatures: tuple[str, ...] = ()
    completed_bootstrap_turn: bool = False

    @classmethod
    def new(cls, *, session_key: str, session_id: str, kind: SessionKind = "main") -> SessionState
    def to_json(self) -> dict[str, Any]
    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SessionState
```

- `entry` is upstream's `SessionEntry` subset as `memory_core.memory_flush` reads it:
  `sessionId`, `compactionCount`, `totalTokens`, `totalTokensFresh`, `totalTokensVersion`,
  `memoryFlush`. `new` starts it as `{"sessionId": ..., "compactionCount": 0}`. A host that
  compacts bumps `compactionCount` itself (upstream `incrementCompactionCount`); the kit never
  compacts.
- `to_json` / `from_json` round-trip exactly, so a host can keep the state in any store.

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
  before_turn(state, runtime_context)  ->  initialize_agent_workspace
                                           build_workspace_context
                                           build_prompt_section
                                           build_runtime_context_system_context
  <- TurnContext(system_prompt, runtime_context, tools, session')
  model call (host): system_prompt, runtime_context, history, user message
    each tool call:
    dispatch(name, args, session)      ->  execute_memory_search_tool (+ recall signals)
                                           execute_memory_get_tool
                                           MemoryCurator.dispatch (+ reindex)
    <- JSON payload, sent back to the model
  deliver the reply (host)
  after_turn(session', usage, ...)     ->  token snapshot
                                           build_memory_flush_plan
                                           explain_memory_flush_trigger
  <- TurnRecord(session'', flush_decision, flush)
  if flush: model run (host, detached, off the reply path) with flush.messages, flush.tools
    each tool call:
    flush.dispatch("write", args)      ->  locked append_daily_memory (+ reindex)
    flush.complete(error=None | exc)   ->  record_memory_flush_success / _failure
    <- FlushOutcome(session''')

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
  `MemoryCurator.dispatch(name, args)` on the curator from `Memory.curator(layout, policy,
  timezone, now_ms)` (whose `after_write` reindexes after MEMORY.md and daily-note writes).
- Arguments: a mapping, its JSON text (parsed once for every tool) or `None` (read as `{}`).
- Recall tracking: with `dreaming_enabled`, the memory-corpus hits of a `memory_search` result go
  through `memory_core/consolidation/recall.py:undecorate_search_results` and
  `record_short_term_recalls`, as upstream does only when dreaming is enabled
  (`extensions/memory-core/src/tools.ts:491-507`). Off by default
  (`DEFAULT_DEEP_DREAMING_ENABLED = False`): no `memory/.dreams/` write.
- Returns the tool's payload unchanged, JSON-able, for the host to send back verbatim.
- Error contract. Model-caused errors come back as payloads, never raised:
  - invalid JSON text: `{"status": "error", "tool": name, "error": "invalid JSON arguments: ..."}`;
  - a name `tools()` does not offer now (unknown, flag off, policy): `... "error": "tool <name>
    is not available"` (memory-core wording; the host's own loop owns names of its other tools);
  - `MemoryToolInputError` (bad params, refused or failed curated writes): `error.to_tool_error()`;
  - any other `Exception` raised inside a tool body: `to_tool_error(exc, tool=name)`, as
    upstream turns every thrown tool error into `{status, tool, error}`
    (`src/agents/agent-tool-definition-adapter.ts:228-284`).
- Search outages are not errors: `memory_search` already returns its unavailable or paused
  payload.
- Host programming errors raise before a tool runs: `TypeError` for a non-string `name` or an
  `arguments` of another type. `BaseException`s that are not `Exception` (cancellation,
  interrupts) propagate.
- Flags: all search flags through `memory.config` (FTS-only, vector-only, MMR, temporal decay);
  `curated_memory_writes` as above; a disabled capability makes no provider call and no write.

### 3. `before_turn(session, ...)`

```python
def before_turn(
    self,
    session: SessionState,
    *,
    runtime_context: str | None = None,
    context_mode: BootstrapContextMode = "full",
    has_bootstrap_file_access: bool = False,
) -> TurnContext

@dataclass(frozen=True)
class TurnContext:
    session: SessionState              # pass to after_turn when the turn completes
    system_prompt: str                 # stable part, above any prompt-cache boundary
    runtime_context: str | None        # dynamic part, below it
    tools: tuple[dict[str, Any], ...]  # tools() at this moment
    workspace: WorkspaceContext        # the core result (files, truncation, bootstrap mode)
    workspace_init: WorkspaceInitResult
```

- Composes, in order:
  1. `memory_core/bootstrap/lifecycle.py:initialize_agent_workspace(root, layout, templates,
     seed_bootstrap, now_ms)`: upstream runs `ensureAgentWorkspace` on every reply
     (`src/auto-reply/reply/get-reply.ts:443-448`), which is where BOOTSTRAP.md is reconciled away.
  2. `memory_core/bootstrap/context.py:build_workspace_context(root, layout, session_kind=kind,
     context_mode, context_injection, has_completed_bootstrap_turn, has_bootstrap_file_access,
     max_chars, total_max_chars, truncation_warning_mode, seen_truncation_signatures, identity)`.
  3. `memory_core/prompt_section.py:build_prompt_section(tool names,
     citations_mode=config.citation_mode)`, skipped for the minimal prompt kinds `subagent` and
     `cron` (upstream `buildMemorySection` returns nothing in minimal mode,
     `src/agents/system-prompt.ts:202-225`; the set moves here from
     `demo/lab_runtime.py:MINIMAL_PROMPT_KINDS`).
  4. `system_prompt` = the Memory Recall lines, then `WorkspaceContext.prompt_text` (upstream puts
     the memory section before the workspace sections, `system-prompt.ts:1059`).
  5. `runtime_context` = `memory_core/runtime_context_prompt.py:build_runtime_context_system_context`
     of the host's text (the identity's begin/end markers, so strip helpers remove it), or `None`.
  6. `session` = the input with `seen_truncation_signatures` from
     `WorkspaceContext.prompt_warning.warning_signatures_seen` and `completed_bootstrap_turn`
     set when `record_completed_bootstrap_turn` asks for it. The host passes this state to
     `after_turn` only for a turn that completed, so a failed turn records nothing.
- No recall injection: upstream's model recalls through the memory tools, and so does the kit's.
  Startup context exists upstream only on the bare `/new` / `/reset` turn, so it comes from
  `on_new_session`, not from here.
- `has_bootstrap_file_access` defaults to `False` because no kit tool can read BOOTSTRAP.md
  (`memory_get` reads only MEMORY.md, dreams.md and `memory/**`); upstream's
  `hasBootstrapFileAccess` is "the run's tools include `read`" (`attempt-bootstrap-prepare.ts`).
  A host with its own read tool passes `True`. Non-empty BOOTSTRAP.md still counts as access
  (core rule).
- Errors: `WorkspaceStateMigrationRequiredError` while upstream's retired JSON setup state is in
  the workspace (fail closed, the host runs `migrate_legacy_workspace_state`); `OSError` from the
  filesystem; `ValueError` for an unknown session kind or context mode (host errors). No model is
  involved, so nothing is a payload here.

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
    force_flush: bool = False,
) -> TurnRecord

@dataclass(frozen=True)
class TurnRecord:
    session: SessionState                      # with this turn's token snapshot
    flush_plan: MemoryFlushPlan                # the plan for this window (meter terms)
    flush_decision: MemoryFlushTriggerDecision
    flush: FlushRequest | None                 # set when the decision flushes
```

Where upstream decides the flush. At v2026.9.6 a completed reply schedules session maintenance
(`src/auto-reply/reply/agent-runner-result-complete.ts:288`,
`agent-runner-maintenance.ts:11-73`: not for heartbeats, failed or aborted runs, runs that
auto-compacted, or with compaction disabled), and maintenance calls `runMemoryFlushIfNeeded`
with `promptForEstimate: ""` (`src/agents/session-maintenance/run.ts:218-232`), then compaction.
The other call site is the checkpoint before preflight compaction
(`agent-runner-execute.ts:145-176`), which runs only when that compaction runs
(`agent-runner-memory.ts:875-889`). `after_turn` is the first site; the second needs host
compaction and is a non-goal. The Lab's current pre-turn flush with the incoming prompt's
estimate follows the pin-era order and changes with the dogfood switch (open question Q1).

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
     transcript-size gate stays off (unknown size never forces).
- `force_flush` skips only the token and transcript-size gates; the runtime skips and the
  one-flush-per-compaction-cycle guard stay; the reason is `forced`. It is the one non-upstream
  input of `after_turn`, kept because `Memory.chat(force_flush=True)` (b6d4d3f) already offers a
  forced flush and the facade's deprecation must not drop it (open question Q6). Calling
  `after_turn` twice with the same inputs is idempotent, which is how the Lab's between-turns
  `/flush` uses it.

Flush execution: a returned request object, not a host callable. Reasons:

- The host owns the model call, model choice (`plan.model` is only a hint), streaming, tool-call
  transport, timeouts, cancellation and provider fallback (docs/package_boundary.md). A callable
  would make the kit run the tool loop, which adapters never own, and would force one sync or
  async signature on every host.
- Upstream runs the flush as detached maintenance after the reply is delivered, in its own
  session view (`src/auto-reply/reply/memory-flush-session.ts:17-47`). A request can be run later
  and elsewhere (a background task, a worker); a callable inside `after_turn` would sit on the
  reply path.
- The request is data plus two sync methods, so asyncio hosts await their own model between
  them and the kit stays sync; tests assert the request without a stub model.

```python
class FlushRequest:
    session: SessionState
    plan: MemoryFlushPlan
    decision: MemoryFlushTriggerDecision
    target: str                                 # plan.relative_path, memory/YYYY-MM-DD.md
    messages: tuple[dict[str, str], ...]        # system, transcript rows, user
    tools: tuple[dict[str, Any], ...]           # the append-only write tool only

    def dispatch(self, name: str, arguments: Mapping[str, Any] | str | None) -> dict[str, Any]
    def complete(
        self,
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

- `messages`: one system message, the transcript's user and assistant text rows (runtime-context
  custom rows dropped with `strip_runtime_context_custom_messages`), then `plan.prompt` as the
  user message. Upstream's flush turn is a full agent run whose system prompt carries the flush
  system prompt as extra context (`agent-runner-memory.ts:1452-1454`, `system-prompt.ts:1254-1257`,
  header `## Conversation Context`), so the system message is the session's Project Context
  (`build_workspace_context` for the session kind, not interactive, so bootstrap mode `none`)
  followed by that section. Task 4 confirms the header and prompt mode for trigger `memory` from
  upstream and takes the header by script (`scripts/extract_upstream_constants.py` into
  `memory_core/_memory_flush_constants.py`).
- `tools`: upstream offers a flush run only `read` and an append-only `write`
  (`src/agents/agent-tools.ts:91,665-692`). memory-core has no generic `read`, so the kit offers the
  `write` tool alone: upstream's schema and description (`src/agents/sessions/tools/write.ts:42-47,
  523-525`) plus the wrapper's suffix `During memory flush, this tool may only append to <target>.`
  (`src/agents/agent-tools.read.ts:760`), script-extracted. It replaces the Lab's own wording in
  `demo/chat_engine.py:_memory_write_tool`.
- `dispatch("write", {path, content})` appends through the shared locked append of
  `MemoryCurator.append_daily_note` (task 4 extracts it, so both paths refuse the same symlinks and
  hard links), then reindexes. A path other than the target returns upstream's
  `Memory flush writes are restricted to <target>; use that path only.`
  (`agent-tools.read.ts:787-790`); empty or `NO_REPLY` content writes nothing (the package's write
  rule). Other names and bad arguments return error payloads like `HostKit.dispatch`.
- `complete()` writes the session entry: `record_memory_flush_success`, or with `error`
  `record_memory_flush_failure(entry, error=..., redact=...)` (three strikes mark the cycle
  flushed). The flush reply's text is never delivered and never enters the transcript (upstream
  also treats an empty reply as silent). A second `complete()` raises `RuntimeError` (host error).
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
```

- Composes, in the Lab's order: `memory_core/session_memory.py:save_session_memory(root,
  session_key, session_id, messages=transcript | session_file, source, now_ms, timezone,
  slug_generator, redactor)`; a reindex, so `memory_search` finds the new file;
  `initialize_agent_workspace` (upstream's ensure runs before the reset reply,
  `get-reply.ts:443-448`); for a bare command (`text` empty)
  `memory_core/bootstrap/startup.py:resolve_bare_session_reset_prompt_state(root, now_ms, timezone,
  time_format, layout, is_primary_run=kind != "subagent", has_bootstrap_file_access)`,
  `build_startup_context(root, now_ms, timezone)` when the state says to prepend and
  `should_apply_startup_context(command)`, and `format_session_reset_transcript_prompt(command,
  identity)`. `model_prompt` joins the startup prelude and the reset prompt with a blank line, as
  `prompt-prelude.ts:200-212` builds the model's message (the transcript row: `:224-225`).
- The saved file is written before the startup context is read, so the next session's prelude
  can quote it. Upstream writes it from a background queue, so its order is not fixed.
- The reset turn then runs like any turn: the host sends `reset.model_prompt` through
  `before_turn` and its model, and records `reset.transcript_prompt` instead.
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
    schedule_now_ms: int | None = None,
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
  which the run kind covers). `schedule_now_ms` is the scheduler's instant for due checks and job
  runs (default: the kit clock); the prompt's `Current time:` line always uses the kit clock, which
  keeps the Lab's virtual heartbeat clock working without a Lab concept in the kit.
- `complete(reply)`: `decide_heartbeat_reply(reply, response_prefix)`; the host delivers only
  when `decision.deliver` (canonical `NO_REPLY`, a legacy `HEARTBEAT_OK` ack within 300 chars and
  a stream-error placeholder are not delivered; a trailing `notify=false` line makes it silent);
  `record_automation_job_run(job, started_at_ms, ended_at_ms)` for `jobs` only, saved in one
  `store.save_jobs` call; the token snapshot as `after_turn` writes it, with no flush decision
  (upstream skips maintenance for heartbeats). `transcript` is what the host records: the
  identity's heartbeat row and the raw reply, so the session corpus filter drops both. A second
  `complete()` raises `RuntimeError`.
- A skipped turn (`empty-heartbeat-file`, `no-pending-event`) has no due tasks, so nothing is
  recorded and no model call follows. A failed model call is not reported: the jobs stay due and
  retry backoff is the host's.
- Tool calls during the run go through `HostKit.dispatch` with `run.session`.

## Cross-cutting contracts

### Errors

| Situation | Behaviour |
| --- | --- |
| model sends bad tool input, unknown tool, invalid JSON, a tool raises | payload `{"status": "error", "tool", "error"}` |
| memory search outage, paused index, cooldown | the tool's own unavailable or paused payload |
| host passes wrong types, calls `complete()` twice, both transcript sources | raise (`TypeError`, `RuntimeError`, `ValueError`) |
| retired upstream setup state in the workspace | raise `WorkspaceStateMigrationRequiredError` (fail closed) |
| filesystem failure outside a tool | raise `OSError` |
| a reindex fails after a committed curated write | ok payload with `afterWriteError` (core rule) |

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
  share one per-file lock (moved out of `memory_core/curation.py:_target_lock`), MEMORY.md, USER.md and
  PROACTIVE_PREFERENCES.md keep curation's per-file locks, `FileAutomationStore` keeps its lock.
  Task 2 adds a two-thread reindex test; if it fails, the fix is a per-store lock inside
  `SQLiteMemoryStore.reindex`.
- Different sessions may run in parallel. Calls for one session must be serialized by the host,
  as upstream runs one reply per session lane; `SessionState` is a value, so the last writer wins.
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
(`limit_history_turns` stays a core helper), compaction, scheduling (heartbeat cadence, active
hours, job timers, backoff), delivery and visibility, ASR and TTS, workflow state, trace
storage, secret redaction policy (the kit takes the host's `redact` and `redactor`), and session
storage.

## `Memory.prepare_turn`, `Memory.chat`, `Memory.record_turn`: deprecate

Decision: keep `Memory` as the core handle (`from_workspace`, `search`, `get`, `curator`,
`langgraph_recall`); deprecate `prepare_turn`, `chat` and `record_turn` in this stage (a
`DeprecationWarning` naming `memory_core.host`, behaviour unchanged) and remove them in the packaging
stage, together with the quickstart rewrite and before the first release.

- `prepare_turn` injects search results as `Relevant memory:` into every prompt. Upstream has no
  such injection; its model recalls through the tools. The kit offers the upstream shape.
- `record_turn` appends the flush model's plain text to the daily file, with no gate, no session
  entry and no `write` tool. Keeping it next to `FlushRequest` would leave two flush write paths.
- `chat` owns the model call and is sync-only; the kit never calls a model.
- Delegating the three to the kit would silently change what they write (plain text versus a
  `write` call, forced versus gated), a breaking change hidden behind old names. The warning makes
  the change loud; `LangGraphMemoryRecall` stays as the explicit recall adapter.

## How the Lab dogfoods the kit

The Lab keeps what a host keeps (provider resolution, sessions and transcripts, the tool loop over
its OpenAI-compatible engine, the event bus, snapshots, diffs and reverts, the editor, demo-only
auto-recall and transcript window, the virtual heartbeat clock) and takes every memory decision
from the kit.

| Lab code today | After the switch |
| --- | --- |
| `demo/lab_tools.py`: `lab_curator`, `LabToolbox.definitions`, `_memory_search` (recall recording), `_memory_get`, `_curate`'s dispatch, `_target` | `kit.tools()`, `kit.dispatch()` with `dreaming_enabled=True`; `_target` is replaced by a public `MemoryCurator.target_for` (rename of `_target_for`) for the snapshot; the toolbox keeps call records, snapshots and events |
| `demo/lab_prompt.py:lab_workspace_context`, the prompt stage's `build_prompt_section` | `kit.before_turn(...).workspace` and `.system_prompt`; the prompt preview uses `before_turn` too, so it shows what the next turn injects (its ensure is the one the next turn would run) |
| `demo/lab_chat.py` stages `flush_decision` and `flush` before the main run; `_persist`'s token snapshot | `kit.after_turn` after `persist`; the flush turn runs `FlushRequest.messages` and `.tools` through the existing `run_tool_loop` and ends with `complete()` |
| `demo/lab_flush.py` (plan, decision, token snapshot, flush run, forced guard, prompt estimate) | deleted except the inspector serializers; the status-bar meter reads the session's last `TurnRecord` |
| `demo/memory_flush.py`, `ChatEngine.flush`, `_memory_flush_write_tool`, `_extract_write_tool_calls`, `FlushModelOutput`, `FlushWriteCall` | deleted; the flush is an ordinary tool-loop run |
| `demo/lab_api.py:start_new_session` composition | `kit.on_new_session`; the endpoint keeps its events and payload |
| `demo/lab_heartbeat.py:_prepare_turn`, the run's flush decision, job recording | `kit.heartbeat_prompt` and `HeartbeatRun.complete`; scratch editing, migrations and the legacy-file action stay Lab actions over the core |
| `LabSession.flush_entry`, `last_output_tokens`, `seen_truncation_signatures`, `completed_bootstrap_turn` | one `LabSession.state: SessionState` |
| `demo/lab_runtime.py:DEFAULT_CONTEXT_WINDOW_TOKENS`, `MINIMAL_PROMPT_KINDS` | moved into the kit |

Observable Lab changes, each updated with its tests/demo assertions:

1. The flush is decided and run after the reply (v2026.9.6 maintenance order), without the
   incoming prompt's estimate. Stage order becomes ensure, compaction (skip), reindex, recall,
   prompt, stream, persist, flush_decision, flush (Q1).
2. The flush turn gets the Project Context plus the flush section and upstream's `write` tool
   wording (Q5).
3. A chat turn in a `heartbeat` session and a heartbeat run report `runtime_skip:heartbeat` after
   the run instead of before it.
4. The manual `/flush` reason reads `forced` instead of `lab_forced` (Q6).
5. The prompt preview runs the per-turn ensure.
6. Without provider usage the Lab passes its labelled chars/4 estimate as `TurnUsage`, so the
   `tokenSource` label stays.

Kept Lab-side and labelled, pending Doruk: `record_daily_memory_flush` after a flush write (Q3).

## Parity labels

The kit is adapter-only code. The orders and inputs it takes from upstream (post-reply flush,
flush-run tool set and wording, recall tracking only with dreaming, minimal kinds without the
Memory Recall section) are source-backed with the anchors above; no matrix row claims `match` for
kit composition. Oracle results must not change: task 10 re-runs the suite.

## Non-goals

Compaction and the pre-compaction checkpoint flush; a generic `read` tool; the
`heartbeat_respond` tool and system events; the upstream bounded flush view
(`Memory flush exceeds the bounded conversation view.`); auto-recall; async variants; live subject
workspaces; wiki supplements (`memory_search` supplements stay a core option the kit does not
expose yet); session auto-reset; inbound-context prefixes (`build_current_inbound_prompt`);
packaging, `__all__` shrinking and the quickstart (next stage).

## Open questions for Doruk

- Q1. Flush timing. The kit follows v2026.9.6: flush after the reply, no prompt estimate. The Lab
  today flushes before the next turn with the prompt's estimate (pin-era order). The plan switches
  the Lab; say if you want the old order kept as a labelled Lab approximation instead.
- Q2. Compaction. Upstream also flushes as a checkpoint right before preflight compaction. That
  needs a host that compacts; add it with a compaction adapter later, or never?
- Q3. The Lab records `daily` recall signals after each flush write
  (`record_daily_memory_flush`). Upstream records daily signals only in the light dreaming phase
  (`extensions/memory-core/src/dreaming-phases.ts:760,948,1067`), and they raise promotion scores.
  The kit does not do it; drop it from the Lab too (recommended), or keep it labelled demo-only?
- Q4. `seed_bootstrap` default. Upstream seeds BOOTSTRAP.md (the kit's default `True`); a host
  without a bootstrap ritual then sees the limited-mode Bootstrap Pending notice on every turn until
  the profile is configured. Keep `True`, or default the kit to `False`?
- Q5. The flush turn with Project Context costs the bootstrap files' tokens on every flush, as
  upstream. Keep upstream's shape (recommended) or send only the flush system prompt as the Lab
  does today?
- Q6. `force_flush` has no upstream counterpart; it keeps the facade's forced flush and the Lab's
  `/flush`. Keep it, or drop both with the facade?
- Q7. Memory facade: deprecate now and remove at packaging (recommended), or keep
  `prepare_turn`/`chat`/`record_turn` as labelled adapter-only helpers?
- Q8. Should `dreaming_enabled` be a `FeatureFlags` field instead of a kit option? It mirrors
  upstream config rather than a memory-core capability, which is why the spec keeps it on the kit.

# Part 2: TDD plan

Each task: write the named tests first and watch them fail, implement, run the offline suite
(baseline at `b829bad`: 1218 passed, 311 skipped) and `ruff check . --no-cache`, then commit that
task alone. Every test that touches a ported algorithm asserts equality with a direct call of the
core function on the same inputs, which is what "only composes" means in code. Tests are offline
and deterministic (`FeatureFlags(vector_search=False)` or `FakeEmbeddingProvider`, stub clocks).

### Task 1: session state, construction, `tools()`

- Goal: the package skeleton and the two value types; `HostKit.__init__`, `HostKit.open`,
  `tools()`.
- Files: `memory_core/host/__init__.py`, `memory_core/host/session.py`, `memory_core/host/kit.py`,
  `tests/unit/test_host_kit_tools.py`.
- Tests first: `test_session_state_round_trips_json`,
  `test_session_state_new_starts_a_fresh_flush_entry`,
  `test_open_seeds_bootstrap_before_any_memory_file_exists`,
  `test_open_with_a_bad_store_config_creates_nothing`, `test_init_does_no_io`,
  `test_tools_lists_memory_tools_then_the_allowed_curation_tools`,
  `test_tools_omit_curation_tools_when_the_flag_is_off`, `test_tools_are_json_serializable`.
- Done: tests pass; `memory_core.host.__all__` lists the kit and its dataclasses; root `memory_core.__all__`
  unchanged.

### Task 2: `dispatch()`

- Goal: one tool-call entry point with the error contract and recall tracking.
- Files: `memory_core/host/kit.py`, `tests/unit/test_host_kit_dispatch.py`.
- Tests first: `test_dispatch_memory_search_equals_execute_memory_search_tool`,
  `test_dispatch_accepts_mappings_json_text_and_none`,
  `test_dispatch_invalid_json_returns_an_error_payload`,
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
  `memory/` exists), `test_before_turn_prompt_equals_the_core_composition`,
  `test_minimal_kinds_get_no_memory_recall_section`,
  `test_memory_recall_section_follows_the_offered_tools`,
  `test_runtime_context_is_wrapped_in_the_identity_markers`,
  `test_before_turn_injects_no_search_results`,
  `test_before_turn_folds_signatures_and_the_bootstrap_turn_into_the_session`,
  `test_pending_bootstrap_without_file_access_is_limited`,
  `test_retired_workspace_state_fails_closed`.
- Done: tests pass.

### Task 4: `after_turn()` and `FlushRequest`

- Goal: the post-reply flush decision and the flush run's request, write tool and completion.
- Files: `memory_core/host/flush.py`, `memory_core/host/kit.py`, `memory_core/curation.py` (the shared locked
  daily append and lock), `scripts/extract_upstream_constants.py`,
  `memory_core/_memory_flush_constants.py`, `tests/integration/test_extracted_upstream_constants.py`,
  `tests/unit/test_host_kit_flush.py`.
- First step: read the tag for the flush run's prompt mode and the `## Conversation Context`
  header (`system-prompt.ts:1254-1257` with trigger `memory`) and the `write` tool texts; extract
  them by script. If upstream contradicts this spec, stop and report.
- Tests first: `test_after_turn_records_a_fresh_token_snapshot`,
  `test_after_turn_without_usage_reports_missing_tokens`,
  `test_after_turn_decision_equals_explain_memory_flush_trigger` (a table of entries, windows and
  sizes), `test_after_turn_uses_no_prompt_estimate`,
  `test_after_turn_defaults_to_the_upstream_context_window`,
  `test_heartbeat_sessions_never_flush`, `test_force_flush_skips_only_the_gates`,
  `test_after_turn_is_idempotent`, `test_flush_messages_carry_context_transcript_and_prompt`,
  `test_flush_transcript_drops_runtime_context_rows`,
  `test_flush_offers_only_the_upstream_write_tool`,
  `test_flush_write_appends_to_the_target_and_reindexes`,
  `test_flush_write_elsewhere_returns_the_upstream_restriction`,
  `test_flush_write_skips_empty_and_no_reply_content`,
  `test_flush_write_refuses_a_symlinked_daily_file`,
  `test_flush_complete_marks_the_cycle_flushed`,
  `test_flush_failures_strike_three_times_and_redact`, `test_flush_complete_twice_raises`.
- Done: tests pass; the curated daily note keeps its existing tests green on the shared append.

### Task 5: `on_new_session()`

- Goal: the session-memory save and the bare reset turn.
- Files: `memory_core/host/kit.py`, `tests/unit/test_host_kit_new_session.py`.
- Tests first: `test_new_session_saves_the_ending_session_and_reindexes`,
  `test_new_session_keeps_the_key_and_starts_a_fresh_entry`,
  `test_bare_reset_returns_the_upstream_prompt_and_transcript_row`,
  `test_startup_context_is_prepended_only_in_bootstrap_mode_none`,
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
  keep them until the quickstart rewrite).

### Task 8: Lab switch, part 1 (tools, dispatch, prompt)

- Goal: the Lab's tool loop and prompt stage run on the kit.
- Files: `demo/lab_tools.py`, `demo/lab_prompt.py`, `demo/lab_chat.py`, `demo/lab_api.py`,
  `demo/lab_kept_api.py`, `demo/lab_runtime.py`, `memory_core/curation.py` (`target_for`),
  `tests/demo/test_demo_app.py`.
- Tests first: `test_lab_tools_come_from_the_host_kit`,
  `test_lab_prompt_stage_uses_before_turn`, `test_prompt_preview_runs_the_ensure`; every existing
  tool-loop, curation-flag, recall-recording and prompt-inspector test stays green unchanged.
- Done: `lab_curator`, `lab_workspace_context`, `LabToolbox._memory_search`, `_memory_get` and
  `_target` are gone; tests pass.

### Task 9: Lab switch, part 2 (flush, `/new`, heartbeat)

- Goal: the Lab's flush, session reset and heartbeat run on the kit; the demo flush code goes.
- Files: `demo/lab_chat.py`, `demo/lab_flush.py`, `demo/lab_heartbeat.py`, `demo/lab_api.py`,
  `demo/lab_kept_api.py`, `demo/lab_runtime.py`, `demo/chat_engine.py`, `demo/memory_flush.py`
  (deleted), `demo/static/lab/` and `demo/templates/` where stage order or labels show,
  `tests/demo/test_demo_app.py`, `tests/demo/test_lab_shell.py`,
  `tests/demo/test_chat_memory_flush.py` (deleted), `tests/demo/test_chat_engine.py`.
- Tests first (rewritten expectations): `test_flush_runs_after_the_reply_once_per_compaction_cycle`
  (S11 window 5,333: the flush follows the first turn over 2,000 tokens),
  `test_flush_write_elsewhere_is_refused_to_the_model`,
  `test_flush_without_usage_uses_the_labelled_estimate`, `test_heartbeat_kind_skips_the_flush`,
  `test_manual_flush_is_forced_once_per_cycle` (reason `forced`),
  `test_failed_flush_reports_the_cause_chain_redacted`,
  `test_session_new_runs_the_host_kit`, the heartbeat run tests with the decision after the run.
  Locked CSS strings stay.
- Done: the rows of the dogfood table are true in the code; tests pass; a real-browser check of the
  chat, flush, `/new` and heartbeat flows on the :8010 preview at 1280, 820 and 640 px (the Lab's
  breakpoints), with the scripted engine named as scripted.

### Task 10: docs, matrix, re-measure

- Goal: the docs describe the kit as built; oracle results unchanged.
- Files: `docs/host_kit.md` (status and labels), `docs/package_boundary.md` (the kit exists; the
  Lab's host role), `docs/lab.md` (A chat turn), `docs/feature_flags.md` (`curated_memory_writes`
  and the kit), `docs/parity_matrix.md` (rows Runtime flush trigger, Recall tracking from
  `memory_search`, Session-memory hook, the heartbeat rows; audit note), `README.md` (a short
  host-kit section; the deprecated calls marked).
- Tests: `tests/parity/test_parity_matrix_evidence.py`; the full offline suite; the oracle suite
  (`tests/integration` with `OPENCLAW_ORACLE_REPO=/tmp/openclaw-head` and Node 24) must report
  254 passed, 81 xfailed, 2 skipped, 0 failed.
- Done: all green with measured numbers in the commit body.

## Follow-ups (later stages)

Packaging (`[build-system]`, a demo extra so the core stops depending on FastAPI), the root
`__all__` shrink with `memory_core.host` exported, the framework quickstart and example rewrite
(removing the deprecated facade methods), live subject workspaces on the kit, the
pre-compaction checkpoint flush with a compaction adapter, session auto-reset, and memory-search
supplements on the kit.
