# memory-core host kit (`memory_core.host`)

Status: specification and TDD plan, written 2026-09-28 on `feat/host-kit` (from `main`
`b829bad`), revised after review the same day. Implemented on that branch the same night:
Tasks 1-8 and the kit parts of Task 10's docs. Task 9 (the Lab's flush, `/new` and heartbeat run)
is blocked on Q1, Q3, Q5, Q6 and Q10; Task 10's oracle re-run follows it. Upstream anchors are
OpenClaw v2026.9.6 (`eb377ac59e6`, checkout `/tmp/openclaw-head`) unless a line says otherwise.

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
  `memory_core/current_time.py` asks); `identity` (context markers, transcript rows);
  `curation_policy` (`MemoryCurator`, default `CurationPolicy.for_layout(layout)`); the
  bootstrap caps, `context_injection` and `truncation_warning_mode`
  (`build_workspace_context`); `dreaming_enabled` (recall tracking, see `dispatch`);
  `automation_store` (default `FileAutomationStore(root)`); `now_ms` (epoch-ms clock, as
  `MemoryCurator` takes it). The agent id is `memory.config.agent_id`. The Lab uses each of them
  except `identity` (memory-core's compat markers) and `now_ms` (deterministic tests).
- `seed_bootstrap=None` (default) seeds BOOTSTRAP.md only when `templates` supplies the layout's
  bootstrap file. memory-core has no ritual text of its own, so an empty BOOTSTRAP.md would leave a
  host without a ritual in limited-mode "Bootstrap Pending" on every turn until `memory/`
  appears (open question Q4). `False` marks setup complete at once (the core extension);
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
  the future quickstart shows both.
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
the first time. Hosts that compact or window history call `after_compaction()` when they do;
whether history windowing with `limit_history_turns` should count as compaction is open question
Q9.

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
  (`DEFAULT_DEEP_DREAMING_ENABLED = False`): no `memory/.dreams/` write.
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
     transcript-size gate stays off (unknown size never forces);
  4. when the decision flushes, `ensure_memory_flush_target_file(root, plan.relative_path)`, then
     the `FlushRequest`. Upstream creates `memory/` and opens the target for append before the flush
     run (`agent-runner-memory.ts:1447-1451`, `memory-flush-session.ts:64-96`), so an empty daily
     file exists even when the model answers `NO_REPLY`, and `memory/` is setup evidence: the next
     ensure completes the bootstrap. If the ensure raises (`UnsafeMemoryPathError`, `OSError`), the
     kit records a failure strike like upstream's `recordFailure` for a failed preparation:
     `flush` is `None`, `flush_failure` the outcome, and `session` carries the failed entry.
- There is no forced flush. `after_turn` has only upstream inputs; the Lab's `/flush` is a labelled
  Lab action pending Q6 (see "How the Lab dogfoods the kit").

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
flush run needs.

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
  - empty or `NO_REPLY` content writes nothing and returns
    `{"status": "ok", "tool": "write", "path": target, "action": "skipped"}` (memory-core's write rule);
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
  runs again (cheap and idempotent).
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
| host passes wrong types, calls `complete()` twice, both transcript sources, another session to `complete()` | raise (`TypeError`, `RuntimeError`, `ValueError`) |
| retired upstream setup state in the workspace | raise `WorkspaceStateMigrationRequiredError` (fail closed) |
| filesystem failure outside a tool | raise `OSError` |
| flush target cannot be created | `TurnRecord.flush_failure`, one strike (upstream `recordFailure`) |
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
  PROACTIVE_PREFERENCES.md keep curation's per-file locks, `FileAutomationStore` keeps its lock.
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

## `Memory.prepare_turn`, `Memory.chat`, `Memory.record_turn`: deprecate

Decision: keep `Memory` as the core handle (`from_workspace`, `search`, `get`, `curator`,
`langgraph_recall`); deprecate `prepare_turn`, `chat` and `record_turn` in this stage (a
`DeprecationWarning` naming `memory_core.host`, behaviour unchanged) and remove them in the packaging
stage, together with the quickstart rewrite and before the first release.

- `prepare_turn` injects search results as `Relevant memory:` into every prompt. Upstream has no
  such injection; its model recalls through the tools. The kit offers the upstream shape.
- `record_turn` appends the flush model's plain text to the daily file, with no gate, no session
  entry and no `write` tool. Keeping it next to `FlushRequest` would leave two flush write paths.
- `chat` owns the model call and is sync-only; the kit never calls a model. Its
  `force_flush=True` goes through `record_turn` and stays unchanged until the removal; the kit has
  no forced flush (Q6).
- Delegating the three to the kit would silently change what they write (plain text versus a
  `write` call, forced versus gated), a breaking change hidden behind old names. The warning makes
  the change loud.
- `LangGraphMemoryRecall` (`Memory.langgraph_recall`) injects search results the same way
  `prepare_turn` does. It stays as an explicit, labelled adapter-only auto-recall (not upstream
  behaviour; a LangGraph host that wants the upstream shape uses the kit's tools instead); the
  matrix and docs/package_boundary.md label it so in Task 10.

## How the Lab dogfoods the kit

The Lab keeps what a host keeps (provider resolution, sessions and transcripts, the tool loop over
its OpenAI-compatible engine, the event bus, snapshots, diffs and reverts, the editor, demo-only
auto-recall and transcript window, the virtual heartbeat clock) and takes every memory decision
from the kit.

| Lab code today | After the switch |
| --- | --- |
| `demo/lab_tools.py`: `lab_curator`, `LabToolbox.definitions`, `_memory_search` (recall recording), `_memory_get`, `_curate`'s dispatch | `kit.tools()`, `kit.dispatch()` with `dreaming_enabled=True`; `_target` builds the daily path from `kit.curator.today()` for the before-snapshot; the toolbox keeps call records, snapshots and events (it reads them from the payloads) |
| `lab.reindex(store)` bookkeeping (`index_status`, `_index_revisions`, the `index.reindexed` event, read by `index_is_stale`, `demo/lab_kept_api.py:318,370`) | a `LabStore(SQLiteMemoryStore)` whose `reindex` does the bookkeeping and emits the event, so kit writes (curated, flush, session memory) that call `store.reindex` keep the Lab index fresh; the Lab builds `Memory(config, workspace, store=LabStore(...))` |
| `LabRuntime.config()` without `curated_memory_writes` (the flag reached the curator through `lab_curator`) | `LabRuntime.config()` flags carry `curated_memory_writes` from `lab.settings.flags`, since the kit reads `memory.config` flags |
| `LabRuntime.ensure` (`initialize_agent_workspace` with the Lab templates) | `kit.ensure()` inside the same `tracked("lifecycle")` block with the same `bootstrap.*` events |
| `demo/lab_prompt.py:lab_workspace_context`, the prompt stage's `build_prompt_section` | `kit.before_turn(state, ensure=False, ...)` at the prompt stage (the ensure stage already ran `kit.ensure()`); `offer_tools=False` for the scripted engine, which offers no tools; the prompt preview and the explorer use `ensure=False` too, so an inspector never seeds or deletes BOOTSTRAP.md |
| `demo/lab_chat.py` stages `flush_decision` and `flush` before the main run; `_persist`'s token snapshot | `kit.after_turn` after `persist`; the flush turn runs `FlushRequest.messages` and `.tools` through the existing `run_tool_loop` and ends with `complete()` (Task 9a) |
| `demo/lab_flush.py` (plan, decision, token snapshot, flush run, forced guard, prompt estimate) | deleted except the inspector serializers; the status-bar meter reads the session's last `TurnRecord` (Task 9a) |
| `demo/memory_flush.py`, `ChatEngine.flush`, `_memory_flush_write_tool`, `_extract_write_tool_calls`, `FlushModelOutput`, `FlushWriteCall` | deleted; the flush is an ordinary tool-loop run (Task 9a) |
| `/api/chat/flush` (`lab_forced`) | a labelled Lab action over `HostKit.request_flush` if Doruk keeps it (Q6), else removed (Task 9a) |
| `demo/lab_api.py:start_new_session` composition | `kit.on_new_session`; the endpoint keeps its events and payload (Task 9b) |
| `demo/lab_heartbeat.py:_prepare_turn`, the run's flush decision, job recording | `kit.heartbeat_prompt` and `HeartbeatRun.complete`; scratch editing, migrations and the legacy-file action stay Lab actions over the core (Task 9c) |
| `LabSession.flush_entry`, `last_output_tokens`, `seen_truncation_signatures`, `completed_bootstrap_turn` | one `LabSession.state: SessionState` (Task 9a; Task 8 builds the state from the fields and folds `before_turn`'s result back) |
| `demo/lab_runtime.py:DEFAULT_CONTEXT_WINDOW_TOKENS`, `MINIMAL_PROMPT_KINDS` | moved into the kit |

If Doruk keeps `/flush` (Q6), the kit gains one labelled extension method,
`request_flush(session, *, transcript) -> FlushRequest | None`: it does not touch the token
snapshot, keeps the heartbeat skip and the one-flush-per-compaction guard (it returns `None` when
the cycle already flushed) and uses reason `forced`.

Observable Lab changes, each updated with its tests/demo assertions (all in Task 9, blocked on
Doruk's answers):

1. The flush is decided and run after the reply (v2026.9.6 maintenance order), without the
   incoming prompt's estimate. Stage order becomes ensure, compaction (skip), reindex, recall,
   prompt, stream, persist, flush_decision, flush (Q1).
2. The flush turn gets the Project Context plus the `## Conversation Context` flush section and
   upstream's `write` tool wording (Q5).
3. A chat turn in a `heartbeat` session and a heartbeat run report `runtime_skip:heartbeat` after
   the run instead of before it.
4. The manual `/flush` reason reads `forced` instead of `lab_forced`, or `/flush` goes (Q6).
5. A due flush creates the empty daily file before the flush run, so a `NO_REPLY` flush leaves an
   empty `memory/<today>.md` (upstream `ensureMemoryFlushTargetFile`).
6. Without provider usage the Lab passes its labelled chars/4 estimate as `TurnUsage`, so the
   `tokenSource` label stays.
7. `/new` keeps the session key: the Lab key becomes `lab:<kind>` for every session of a kind, as
   upstream keeps `sessionKey` across `/new` (today `lab:<kind>:<id>` changes). This shows in the
   `session.new` event (`oldSessionKey` equals `sessionKey`), in the key line of the saved
   session-memory file and in the fallback key of the `memory_search` cooldown (Q10).
8. `/new` runs an ensure and a reindex after saving the session memory (today it runs neither),
   so the saved file is searchable at once and a pending bootstrap reconciles before the reset
   prompt is built.

Kept Lab-side and labelled, pending Doruk: `record_daily_memory_flush` after a flush write (Q3).

## Parity labels

The kit is adapter-only code. The orders and inputs it takes from upstream (post-reply flush,
the flush target file, flush-run tool set and wording, recall tracking only with dreaming, minimal
kinds without the Memory Recall section) are source-backed with the anchors above; no matrix row
claims `match` for kit composition. Oracle results must not change: task 10 re-runs the suite.

Pin-era parts the kit ships until port plan area 5 lands: the `memory_search` and `memory_get`
tool definitions and the Memory Recall section (`memory_core/prompt_section.py`, pin `4c428153`); the
tag's `buildMemoryPromptSection` wording differs (entry points 1 and 3).

Labelled deviations of the flush run (entry point 4):

- Bytes: upstream appends the content verbatim and inserts one newline only when the file is not
  empty, lacks a trailing newline and the content does not start with one
  (`agent-tools.read.ts:716-720`, `@openclaw/fs-safe` `prependNewlineIfNeeded`);
  `append_daily_memory` inserts the separator whenever a non-empty file lacks a trailing newline
  (also before content that starts with one), strips the content's trailing newlines and always
  ends the entry with `\n`.
- Empty and `NO_REPLY` content writes nothing (memory-core's write rule; upstream appends it).
- The missing-parameter messages are memory-core's.
- Messages carry the rows' text only, and no host system prompt.
- The target file and the write refuse symlinks and hard links (stricter than upstream).

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
  the Lab in Task 9a once you agree; say if you want the old order kept as a labelled Lab
  approximation instead.
- Q2. Compaction. Upstream also flushes as a checkpoint right before preflight compaction. That
  needs a host that compacts; add it with a compaction adapter later, or never?
- Q3. The Lab records `daily` recall signals after each flush write
  (`record_daily_memory_flush`). Upstream records daily signals only in the light dreaming phase
  (`extensions/memory-core/src/dreaming-phases.ts:760,948,1067`), and they raise promotion scores.
  The kit does not do it; drop it from the Lab too (recommended), or keep it labelled demo-only?
- Q4. `seed_bootstrap` default. Upstream seeds BOOTSTRAP.md from its ritual template. memory-core has
  no ritual text, so seeding by default gives a host without templates an empty BOOTSTRAP.md and
  the limited-mode "Bootstrap Pending" notice on every turn, with no ritual to follow, until
  `memory/` appears. Recommended and implemented as the default (`None`): seed only when
  `templates` supplies BOOTSTRAP.md; the Lab passes `True`. Keep that, or always seed like upstream?
- Q5. The flush turn with Project Context costs the bootstrap files' tokens on every flush, as
  upstream. Keep upstream's shape (recommended) or send only the flush system prompt as the Lab
  does today?
- Q6. The Lab's `/flush` (`/api/chat/flush`, reason `lab_forced`) has no upstream counterpart, and
  the kit has no forced flush. Keep `/flush` as a labelled Lab action over one kit extension method
  `request_flush` (no token-snapshot change, heartbeat skip and same-cycle guard kept, reason
  `forced`), or drop it? `Memory.chat(force_flush=True)` is unaffected until the facade's removal.
- Q7. Memory facade: deprecate now and remove at packaging (recommended), or keep
  `prepare_turn`/`chat`/`record_turn` as labelled adapter-only helpers?
- Q8. Should `dreaming_enabled` be a `FeatureFlags` field instead of a kit option? It mirrors
  upstream config rather than a memory-core capability, which is why the spec keeps it on the kit.
- Q9. A host that never compacts flushes once per session (Turn lifecycle, known gap). Should
  history windowing with `limit_history_turns` count as a compaction (the host then calls
  `SessionState.after_compaction()` when the window drops turns), or should the kit stay at the
  upstream rule and leave compaction to hosts?
- Q10. `/new` in the Lab: keep the rotating `lab:<kind>:<id>` key (the Lab passes its own key per
  session) or move to upstream's stable `sessionKey` (observable change 7)?
- Q11. A pending flush. The kit follows upstream's rule (one maintenance lane per session, entry
  point 4): a host that calls `after_turn` again before `complete()` gets a second request for the
  same cycle and both runs append. A kit-level guard would be a pending marker in `SessionState`,
  plus a way to clear it for an abandoned run and after a crash (a stored marker would otherwise
  block the cycle). Keep the documented lane rule (implemented), or add the marker?

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
  flush and reindex stages, as today, with the same single ensure and the same events.

# Part 2: TDD plan

Each task: write the named tests first and watch them fail, implement, run the offline suite
(baseline at `b829bad`: 1218 passed, 311 skipped) and `ruff check . --no-cache`, then commit that
task alone. Every test that touches a ported algorithm asserts equality with a direct call of the
core function on the same inputs, which is what "only composes" means in code. Tests are offline
and deterministic (`FeatureFlags(vector_search=False)` or `FakeEmbeddingProvider`, stub clocks).

Cut line for the first night (2026-09-28): Tasks 1-7, the kit parts of Task 10's docs, and Task 8
if time allows. Task 9 is blocked until Doruk answers Q1, Q3, Q5 and Q6; when unblocked it splits
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
- Done: tests pass; the curated daily note keeps its existing tests green on the shared append;
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
  keep them until the quickstart rewrite).

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
  for its turn (before, it left the index reported as stale).

### Task 9: Lab switch, part 2 (blocked: Q1, Q3, Q5, Q6, Q10)

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

### Task 10: docs, matrix, re-measure

- Goal: the docs describe the kit as built; oracle results unchanged.
- Files: `docs/host_kit.md` (status and labels), `docs/package_boundary.md` (the kit exists; the
  Lab's host role; `LangGraphMemoryRecall` labelled adapter-only auto-recall), `docs/lab.md` (A chat
  turn), `docs/feature_flags.md` (`curated_memory_writes` and the kit), `docs/parity_matrix.md` (rows
  Runtime flush trigger, Recall tracking from `memory_search`, Session-memory hook, Prompt memory
  tool section (the kit ships the pin-era section until area 5), the heartbeat rows, the LangGraph
  row; audit note), `README.md` (a short host-kit section; the deprecated calls marked).
- Tests: `tests/parity/test_parity_matrix_evidence.py`; the full offline suite; the oracle suite
  (`tests/integration` with `OPENCLAW_ORACLE_REPO=/tmp/openclaw-head` and Node 24) must report
  254 passed, 81 xfailed, 2 skipped, 0 failed, after Task 9.
- Done: all green with measured numbers in the commit body.

## Follow-ups (later stages)

Packaging (`[build-system]`, a demo extra so the core stops depending on FastAPI), the root
`__all__` shrink with `memory_core.host` exported, the framework quickstart and example rewrite
(removing the deprecated facade methods), live subject workspaces on the kit, the
pre-compaction checkpoint flush with a compaction adapter, session auto-reset, memory-search
supplements on the kit, and port plan area 5 (tool definitions and the Memory Recall section at the
tag).
