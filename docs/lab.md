# memory-core Lab (backend)

The Lab is a FastAPI app (`demo/`) over the `memory-core` package. It holds what a
host holds (paths, settings, sessions, provider keys, an event log, file
snapshots, the index bookkeeping) and calls the package for every memory
decision; it dogfoods the host kit (`memory_core.host`, docs/host_kit.md) for the
tools, their dispatch, the per-turn ensure, the prompt, the flush after the reply,
`/new` and `/reset`, and the heartbeat run. The UI talks only to
`/api/lab/*` and the kept `/api/*` endpoints below. Design: DESIGN §4 (API
contract), §8 and §10 of the Lab v2 design.

## Run it

```bash
.venv/bin/python -m uvicorn demo.app:app --port 8000   # Doruk's server
.venv/bin/python -m uvicorn demo.app:app --port 8010   # agent preview (.claude/launch.json "memory-core-demo")
```

Run from the checkout whose code you want (the launch config runs the repo root).
Python changes need a restart (no `--reload` on :8000). State is in process memory;
the workspaces are in the system temp dir:

| Workspace | Path | Used by |
|---|---|---|
| Lab | `$TMPDIR/memory-core-lab-workspace` (renamed from the legacy name, D3) | chat, files, heartbeat, consolidation |
| Live task | `$TMPDIR/memory-core-live-task-demo-workspace` | `/api/live-task/*` |

Environment (read-only; `.env` in the repo root is loaded at startup, names
already set win; nothing is ever written back):

| Name | Default | Meaning |
|---|---|---|
| `MEMORY_CORE_DEMO_OPENAI_BASE_URL` | `https://openrouter.ai/api/v1` | chat endpoint |
| `MEMORY_CORE_DEMO_OPENAI_API_KEY` | none | chat key (or `openai.apiKey` per request) |
| `MEMORY_CORE_DEMO_OPENAI_MODEL` | `openai/gpt-6-luna` | chat model |
| `MEMORY_CORE_DEMO_OPENAI_EMBEDDING_BASE_URL` | the chat URL | embeddings endpoint |
| `MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY` | none | embeddings key (or `embedding.apiKey`) |
| `MEMORY_CORE_DEMO_OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | embeddings model |
| `MEMORY_CORE_LAB_PARITY_RESULTS` | `$TMPDIR/memory-core-lab/parity-results.json` | parity results file |
| `OPENCLAW_ORACLE_REPO` | `/tmp/openclaw-head` | oracle checkout (a checkout of the parity pin, tag `v2026.9.6`) used by the parity view and the oracle tests |
| `OPENCLAW_ORACLE_NODE` | first `node` on `PATH` | node binary the oracle runner and the run-loop Vitest run with; must be named `node` (or a symlink named `node`) and be in the checkout's `engines.node` range |

Default model (D4, Q10): the newest OpenAI GPT chat model in OpenRouter's public
model list (`GET https://openrouter.ai/api/v1/models`, no auth), checked
**2026-09-26**: `openai/gpt-6-luna`, created 2026-09-22T18:13:06Z. Rule: newest
`created` among `openai/gpt-*` ids with tool support, without a `:variant` suffix
and without a `-pro` serving variant (`openai/gpt-6-luna-pro` is listed five
seconds later as the same model with reasoning mode pro). Recorded in
`demo/chat_engine.py` as `DEFAULT_OPENAI_MODEL` / `DEFAULT_OPENAI_MODEL_SOURCE`.

## What is real, what is not

| Surface | Label | Notes |
|---|---|---|
| Chat model | real | OpenAI-compatible streaming with tool calls. No key: `400 no_api_key`, no fake model. |
| `engine: "scripted"` | scripted | Explicit per request only. Fixed text, no model call, no tool call, no flush turn (the kit's flush request is abandoned: nothing recorded). |
| Tool loop | host (Lab) | `HostKit.tools()` (`memory_search`, `memory_get` with pin-era definitions until port plan area 5, curation tools) and `HostKit.dispatch`; ≤ 6 tool rounds + 1 final round without tools. |
| Curated writes | extension (Q16, D5) | `MemoryCurator`; per-target flags `curation.memory_md`, `curation.user_md`, `curation.daily_note`, `curation.proactive_preferences`, master flag `curated_memory_writes`. |
| Flush decision | upstream v2026.9.6 order (Q1) | `HostKit.after_turn` after the reply, with the flush plan built for the Lab's context window (reserve min(20,000, ⌊window/4⌋), soft threshold min(4,000, ⌊(window − reserve)/2⌋)). Token counts: provider usage stored as a fresh v1 total, else a chars/4 estimate (labelled); no prompt estimate. |
| Flush turn | host (Lab) | The kit's `FlushRequest` on the Lab's model through the Lab tool loop: Project Context plus the flush prompt, upstream's `write` tool on today's daily file only; the reply is never shown; no daily recall signals (Q3). |
| `/flush` | Lab extension (Q6) | `HostKit.request_flush`: reason `forced`, outside the token gate; no run for a heartbeat session or an already flushed cycle. |
| Compaction | known gap | The Lab never compacts, so after one flush a session reports `already_flushed` until `/new`. |
| Auto-recall | demo-only | `memory_search` on the user message; only MEMORY.md and today's/yesterday's daily file reach the prompt. Off for subagent/cron and reset turns. |
| Transcript window | demo-only | Last 40 messages, 24,000 chars. |
| Embeddings | Q9 | Real endpoint → hybrid; otherwise FTS-only (`fts-only`) and no embedder is built. Never fake vectors. |
| Session-memory file | upstream (D2) | `HostKit.on_new_session`: raw recent `role: text` lines, no redactor, labelled; the key `lab:<kind>` stays across `/new` (Q10). |
| Heartbeat | runtime-only port | `HostKit.heartbeat_prompt` and `HeartbeatRun.complete`. No scheduler (the host's job upstream); v2026.9.6 shape: monitor scratch and automation jobs in `.memory-core/automation.json` (`FileAutomationStore`; upstream uses its shared state DB). The virtual clock (demo-only) shifts due checks, job runs and migrated anchors only; the prompt's current-time lines use the real clock. |
| Promotion/dreaming | package | Manual sweeps; the view's evidence label is read from `docs/parity_matrix.md`. |
| Live task | adapter-only | Real model when a request or `.env` key resolves, else scripted replies; summaries redact the identity proof. |

## Endpoints

Errors are JSON `{error, code?, ...}` with a 4xx/5xx status; SSE streams end
with `error` or `done`/`turn_done`. Every message that can carry provider text is
checked against the configured keys (`redacted: true`). Ids (`sessionId`,
`subjectId`, `writeId`, mark ids) must match `^[A-Za-z0-9_-]{1,64}$`.

### `/api/lab/*`

| Method · path | Request | Response |
|---|---|---|
| GET `/state` | `?sessionKind=main` | LabSnapshot: `workspace`, `liveWorkspace`, `pin`, `today`, `yesterday`, `clock`, `identityName`, `bootstrap {status, mode, pendingFile, bootstrapSeededAt, setupCompletedAt}`, `session`, `sessions`, `index`, `flush` (meter), `layoutOrder`, `memoryFiles`, `turns`, `lastEventId` |
| GET `/events` | `Last-Event-ID` header (or `?lastEventId=`), `?once=true` replays and ends | SSE of LabEvent `{id, ts, type, category, summary, turnId?, data}`; frames have no `event:` line; `lab.resync` when the gap is older than the 1,000-event ring; `: ping` every 15 s |
| GET `/files` | `?sessionKind=&layout=` | FileEntry[] (badges from `HostKit.before_turn(ensure=False)`: no workspace write) |
| GET `/file` | `?path=` | `{path, content, sha256, chars, bytes, mtimeMs, writable, readOnlyReason?}` |
| PUT `/file` | `{path, content, baseSha256}` | `{path, sha256, diff, events[]}`; `409 {code:"conflict", current}`; `403 read_only` |
| POST `/file/diff-preview` | `{path, content}` | `{path, diff, charsBefore, charsAfter, budget}` |
| GET `/diff` | `?since=turn:<id>\|session\|reset\|mark:<id>` | `[{path, status, diff, added, removed, hidden, sources[]}]` |
| POST `/diff/mark` | — | `{markId}` |
| POST `/diff/revert` | `{path, since, baseSha256?}` | PUT-file shape |
| POST `/workspace/reset` | `{mode:"seeded"\|"fresh", keepMemory?}` | LabSnapshot |
| POST `/workspace/migrate-tools-md` | — | `{changes, warnings, archivePath, merged}`: `memory_core.bootstrap.migrate_tools_md` on the Lab workspace (TOOLS.md into AGENTS.md `## Tools`, archived under `.memory-core/backups/tools-md-migration/`); event `workspace.tools_md_migrated`; the explorer offers it on a TOOLS.md row |
| POST `/prompt/preview` | `{sessionKind, runKind?, contextMode?, lightContext?, contextInjection?, maxChars?, totalMaxChars?, layout?}` (`runKind`: default, heartbeat, cron; `layout`: memory-core, upstream) | PromptView |
| GET `/turns/{id}` | — | TurnDetail |
| POST `/chat/stream` | `{message, sessionKind, reset?, engine?, openai?, embedding?}` | SSE: `turn_started`, `stage`, `flush`, `recall`, `prompt`, `tool_call`, `tool_result`, `curation`, `assistant_delta`, `turn_done {turn, detail}`, `error` |
| POST `/session/new` | `{command:"new"\|"reset", text?, sessionKind}` | `{sessionId, sessionKey, bare, sessionMemory, startup, resetPrompt {text, bootstrapMode}}`: `HostKit.on_new_session`; `sessionKey` stays `lab:<kind>`; events `session_memory.written`, `index.reindexed`, `session.new {command, bare, oldSessionKey, sessionKey, oldSessionId, sessionId}`, `startup_context.loaded` |
| GET `/index/status` | — | `{files, chunks, lastReindexAt, mode, identity, embeddings, cooldown, deadlineMs, cooldownMs, stale}` |
| GET `/heartbeat` | — | `{scratch {status, currentRevision, content, bytes, maxBytes, sourceSha256, updatedAtMs}, jobs[] {id, name, displayName, everyMs, anchorMs, prompt, lastRunAtMs, nextRunAtMs, due, heartbeatTask}, skippedJobRows[] {index, id, reason} (stored rows the store cannot load; kept untouched), legacyFile, legacyArchives[] (files under `.memory-core/backups/heartbeat-migration/`), migrationFindings[], every, everyMs, ackLimit, lightContext, preflight {skipReason, prompt, message, dueTasks, dueJobs, hostDueJobs, scratchShown, scratchRevision, timeFormat}, clock, runs[], proactivePreferences, sessionKey, store, labels}`; `status` is none, unset, empty (the run skips with `empty-heartbeat-file`) or active |
| PUT `/heartbeat/scratch` | `{content, expectedRevision?}` (`content: null` unsets) | `{write {ok, currentRevision, scratch?}, scratch}`: compare-and-swap on the revision; a stale `expectedRevision` is `409 revision_conflict` with `{error, code, write {ok: false, reason: revision-conflict, currentRevision}, scratch}` (the stored scratch); `400 scratch_too_large` over 256 KiB; a lone surrogate is stored as U+FFFD; events `heartbeat.scratch_written`, `heartbeat.scratch_conflict` |
| POST `/heartbeat/migrate` | — | `{scratch {changes, warnings}, tasks {changes, warnings, jobs}}`: `migrate_heartbeat_md` (a leftover HEARTBEAT.md into the scratch, archived under `.memory-core/backups/heartbeat-migration/`) then `migrate_heartbeat_tasks` (the scratch's `tasks:` block into automation jobs, anchored on the virtual clock); event `heartbeat.migrated` |
| POST `/heartbeat/legacy-file` | `{content}` | demo-only: writes a legacy HEARTBEAT.md with the caller's text at the Lab root so the doctor migration can be seen (nothing else in the Lab creates a retired file; the file editor answers `403 read_only` for it): `{path, bytes, migrationFindings, label}`; `409 legacy_file_exists` when one is there, `400 invalid_content`, `400 too_large` over 2 MiB; event `heartbeat.legacy_file_written` and `file.changed`; scenario S09 starts here |
| POST `/heartbeat/run` | `{lightContext?, openai?}` | SSE: `skipped`, `prompt {userMessage, scratchShown, files, ...}`, `tool_call`, `tool_result`, `curation`, `assistant_delta`, `flush` (after the run: `runtime_skip:heartbeat`), `decision {kind, text?, eventStatus?, silent, delivered, silentReply, replyChars}`, `done {run}`, `error`; the due heartbeat-task jobs become the scheduled tasks and only they are rescheduled from the run (event `automation.jobs_ran`); a due job of another kind is the host's to run and stays due (`hostDueJobs` in the preview and the run) |
| POST `/heartbeat/reply` | `{text}` | `decide_heartbeat_reply` without a model: `{kind, text?, eventStatus?, silent, delivered, silentReply, legacyAck {shouldSkip, text, didStrip}}` |
| POST `/clock` | `{offsetMs}` or `{reset:true}` | `{nowMs, offsetMs}` |
| GET `/consolidation` | — | `{curated[], shortTerm, candidates[], gates, weights, lastPromotion, lastDreaming, audit, repair, labels, flags}` |
| POST `/curation/revert` | `{writeId}` | PUT-file shape; `409` when the file changed since the write |
| GET `/parity` | — | `{pin, oracleRepo, node, resultsPath, results, matrix[], commands[]}` |
| GET · PUT `/settings` | partial Settings (never a key) | Settings; `heartbeat {every, lightContext}` (`ackMaxChars` is retired at v2026.9.6: `400 retired_setting`); read-only `timezone` and `timeFormat` (the one host 12/24-hour format of every current-time line) |
| POST `/provider/check` | `{openai}` or `{embedding}` | `{ok, target, latencyMs, model?, error?, redacted?}` |

### Kept `/api/*`

| Method · path | Notes |
|---|---|
| POST `/api/seed` | `workspace/reset` in `seeded` mode |
| POST `/api/reindex` | `{mode?}`; full reindex of that mode's index |
| POST `/api/search` | `{query, maxResults?, minScore?, corpus?, mode?}`; `mode` hybrid, vector or text; adds `mode`, `flags`, `identity`, `cooldown`, `ms`, `embeddings`; param errors are `400 tool_input_error` with the verbatim tool payload; FTS-only answers `400 fts_only` for hybrid/vector |
| POST `/api/get` | `memory_get` |
| POST `/api/prompt-preview` | `build_prompt_section` |
| POST `/api/parity/trace` | `build_parity_trace` (5 steps: promotion/dreaming chain only) |
| POST `/api/chat/flush` | `{sessionKind?, openai?}`; `/flush`, a labelled Lab extension (decision Q6): `HostKit.request_flush` (reason `forced`, token snapshot untouched), then the flush run on the Lab's model; `{decision {shouldRun, reason, extension, label}, flush, entry}`; `already_flushed` in the same compaction cycle and `runtime_skip:heartbeat` for the heartbeat session, both without a run; the scripted engine answers `400 no_api_key` |
| POST `/api/memory/promote`, GET `/api/memory/audit`, POST `/api/memory/repair`, POST `/api/dreaming/run` | consolidation sweeps; emit `promotion.swept`, `audit.completed`, `repair.completed`, `dreaming.swept` |
| POST `/api/live-task/reset`, GET `/api/live-task/state`, POST `/api/live-task/turn-stream`, POST `/api/live-task/summary` | `LiveTaskDemo` over `memory_core.live`; events mirrored to the bus as `live.<type>` |

Removed: `/memory-system` (D6), `/api/chat/state`, `/api/chat/reset`,
`/api/chat/send`, `/api/chat/send-stream`.

## A chat turn

Stages, in the order the `stage` events stream them:

1. `ensure`: `HostKit.ensure` (`initialize_agent_workspace` with the Lab templates;
   upstream runs it on every reply; a configured profile deletes BOOTSTRAP.md here).
2. `compaction`: skipped, the Lab never compacts.
3. `reindex`, 4. `recall` (demo-only auto-recall), 5. `prompt`
   (`HostKit.before_turn(ensure=False)` for the session: the Memory Recall section for
   the offered tools, then the workspace context for the session kind; no generic
   `read` tool; the scripted engine is offered no tools and gets no Memory Recall),
6. `stream` (tool loop over `HostKit.dispatch`; a call counts as failed when its payload has
   `status: "error"` or `disabled: true`; every error payload of an offered curated-write tool
   is recorded as a refused write with a `curation.refused` event: a refusal, bad or invalid
   JSON arguments, a failed write or any other exception of the write), 7. `persist`
   (transcript, the kit's fold of the seen truncation signatures and the bootstrap turn).
8. `flush_decision`, after the reply (v2026.9.6 session maintenance, decision Q1):
   `HostKit.after_turn` with the turn's usage (the provider's `promptTokens` as a fresh v1
   total plus `completionTokens`, else a labelled chars/4 estimate, `tokenSource`; no prompt
   estimate), the transcript size (the UTF-8 size of the session's JSON message lines) and
   the context window (setting, else 200,000). Threshold = window − reserve − soft threshold,
   both terms derived from the window (200,000 gives 20,000 / 4,000 / 176,000; the S11 test
   window 5,333 gives 1,333 / 2,000 / 2,000). The status-bar meter shows the current window's
   terms, the last turn's decision and the session's `memoryFlush` state; the settings flush
   group and the prompt inspector show the terms too. The flush prompt's time line uses the
   Lab's host-supplied 24-hour format (`timeFormat`); upstream detects the host's 12/24-hour
   format, and the inspector says so. The Lab passes the same `LAB_TIME_FORMAT`
   (`demo/lab_runtime.py`) to the heartbeat turn and the bare `/new` / `/reset` prompt
   (`memory_core.current_time`), and settings show it read-only under Time zone. A due flush
   first creates the empty daily file (upstream `ensureMemoryFlushTargetFile`), so a
   `NO_REPLY` flush leaves an empty `memory/<today>.md`.
9. `flush`: when due, the kit's `FlushRequest` runs on the Lab's model through the same tool
   loop (`demo/lab_flush.py`): the Project Context (bootstrap mode `none`) with the flush
   system prompt under `## Conversation Context`, the transcript's text rows and the flush
   prompt (upstream's shape, decision Q5), and upstream's `write` tool, which may only append
   to today's daily file. The flush reply never reaches the chat or the transcript, and no
   `daily` recall signal is recorded (decision Q3). `FlushRequest.complete` then writes the
   session entry's `memoryFlush` state (`succeeded` with the flushed cycle, or `failed` with a
   failure count; three failures mark the cycle flushed). A failure's `error.message` is the
   SDK's truncated message with the cause chain, redacted with the Lab's key values. The
   prompt inspector shows the decision (run/skip), the flush turn's outcome and its system
   message and prompt apart: the scripted engine decides "run" and skips the turn (`scripted:
   flush turn needs a model`); its request is abandoned, so nothing is recorded and the next
   turn requests the flush again. The Lab runs the flush in the same request after the reply
   has streamed and before `turn_done` (upstream runs it detached after delivery).

Steps 8 and 9 never fail the delivered turn: an error fails only the running stage (a
`flush.failed` event with the stage), and Stop (Esc) skips the stages not done yet (`stopped
by the client`), which abandons a flush request that has not run. The turn keeps its reply.

Every reindex goes through `LabStore` (`demo/lab_runtime.py`), including the ones the
kit runs after a curated write, the flush write and `/new`, so the index status and
`index.reindexed` events stay current and `/index/status` does not report a stale
index after a write. The Lab builds its kit per request with the Lab clock; calls that
do not search (the ensure, a reset, the prompt views) get the FTS-only `LabStore`, whose
construction creates `.memory-core/lab-text.sqlite` when it is missing (an index file,
never a memory or bootstrap file).

A kind change is its own session (key `lab:<kind>`, empty transcript). Subagent and cron
get upstream's minimal prompt (no `## Memory Recall`, no auto-recall).

`/flush` (`POST /api/chat/flush`) is a labelled Lab extension (decision Q6):
`HostKit.request_flush` makes the same flush run outside the token gate, with reason
`forced`, and leaves the token snapshot alone; a heartbeat session and a compaction cycle that
already flushed get no run. A daily file the kit cannot create (a symlinked `memory/`, for
example) answers 409 `flush_target_failed` after `flush.decided` and `flush.failed` events; the
kit records no strike then, while a due flush after a chat turn records one (upstream's
`recordFailure`).

`/new` and `/reset` (`POST /api/lab/session/new`) run `HostKit.on_new_session`: the
session-memory hook (`save_session_memory` → `memory/<date>-<HHMM>.md`, raw lines, no
redactor), a reindex (the file is searchable at once), the ensure (a pending bootstrap
completes here, since `memory/` is setup evidence) and, when bare, the reset prompt
(`resolve_bare_session_reset_prompt_state`, the upstream text) plus `build_startup_context`
when the bootstrap mode is `none`. The session key stays (`lab:<kind>`, upstream's stable
`sessionKey`, decision Q10); the new session gets a new id and a fresh flush entry. The
client then streams the reset turn with `{reset: true}`; the model gets the kit's
`ResetTurn.model_prompt` (`[startup context, reset prompt]`) and the transcript keeps
`[memory-core session new]`.

A heartbeat run (`POST /api/lab/heartbeat/run`) is `HostKit.heartbeat_prompt` with the
virtual clock as the schedule instant, the same tool loop, `HeartbeatRun.complete` (the reply
decision, the runs of the jobs in the turn, the token snapshot) and then `after_turn`, which
reports `runtime_skip:heartbeat`: heartbeats never flush. A skipped run makes no model call
and runs no ensure. The preflight and the prompt inspector use `heartbeat_prompt(ensure=False)`
and never complete it, so they write nothing.

## Oracle checkout

The parity view and `tests/integration` run the real OpenClaw TypeScript through
`scripts/openclaw_oracle_runner.ts`, which supports only the parity pin, release tag
`v2026.9.6` (`eb377ac59e6`, `memory_core/parity/upstream.py`). The default checkout is
`/tmp/openclaw-head`; `OPENCLAW_ORACLE_REPO` points elsewhere. The chip in the parity view
turns amber when the checkout's HEAD is not the pin.

The tag's `package.json` asks for Node `>=24.16.0 <25 || >=26.1.0` (its SQLite state refuses
Node 25). The runner starts through the checkout's `tsx`, which runs the first `node` on
`PATH`; `OPENCLAW_ORACLE_NODE` names a node binary to use instead (its directory goes first on
`PATH` for the runner, `pnpm` and the run-loop Vitest). tsx, pnpm and Vitest start through
`#!/usr/bin/env node`, so the configured value is resolved to an absolute path (a bare name is
looked up on `PATH`) and must be a binary or symlink named `node`: an alias such as `node24`
is refused with `oracle-node-unsupported`, since the next `node` on `PATH` would run instead of
it. Before each run the oracle client checks the resolved Node against `engines.node` and fails
fast with `oracle-node-unsupported` (or `oracle-node-missing` for a binary that does not run)
instead of failing inside TS. The parity view shows the resolved Node and turns red outside the
range or for a binary not named `node`.

With `<node-dir>` a directory whose `node` is in that range (for example a version manager's
Node 24 install):

```bash
git clone https://github.com/openclaw/openclaw /tmp/openclaw-head
git -C /tmp/openclaw-head checkout v2026.9.6
(cd /tmp/openclaw-head && PATH=<node-dir>:$PATH \
  npx --yes pnpm@12.4.0 install --ignore-scripts --frozen-lockfile)
export OPENCLAW_ORACLE_REPO=/tmp/openclaw-head
export OPENCLAW_ORACLE_NODE=<node-dir>/node
```

Use a short, fresh `TMPDIR` per run (long paths break tsx's IPC sockets); the runner gives
every operation its own `OPENCLAW_STATE_DIR` and never touches `~/.openclaw`.

One accepted exception to leaving the checkout untouched: the run-loop oracle
(`demo/openclaw_run_loop_oracle.py`) writes
`src/agents/embedded-agent-runner/memory-core-overflow-run-loop.oracle.test.ts` for the length of
one Vitest run and removes it in a `finally` block, because the checkout's Vitest projects only
collect test files inside the repo and the case imports the run-loop harness by relative path.
A killed run can leave the file behind; the next run removes that stale copy and reports it (a
`RuntimeWarning` and `staleTestFileRemoved` in the result), and `git -C <checkout> status`
shows it in between. Run one run-loop oracle per checkout at a time.

## Parity results

```bash
TMPDIR=<scratch> PYTHONDONTWRITEBYTECODE=1 MEMORY_CORE_DEMO_OPENAI_API_KEY= MEMORY_CORE_DEMO_OPENAI_EMBEDDING_API_KEY= \
OPENCLAW_ORACLE_REPO=/tmp/openclaw-head OPENCLAW_ORACLE_NODE=<node-dir>/node \
.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/integration/test_openclaw_ts_oracle.py tests/integration/test_memory_tools.py \
  --junitxml=<scratch>/memory-core-lab/oracle.xml
.venv/bin/python -m demo.parity_results <scratch>/memory-core-lab/oracle.xml --out <scratch>/memory-core-lab/parity-results.json
```

`demo/parity_results.py` maps each test to an area and classifies its evidence
statically from the test source: `python_eq_ts` (oracle and memory-core in the same
test), `ts_literal` (oracle only, Python two-hop), `python_eq_source` (Python
constants against the upstream source text), `python_literal` (no oracle).

## Tests

`tests/demo/test_demo_app.py` covers the contract offline with stub engines and a
test-only embedding stand-in; `tests/demo/test_lab_shell.py` (frontend-owned)
covers the shell markup.
