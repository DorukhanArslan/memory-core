# Workspace Layout

`memory_core.bootstrap` seeds an agent workspace, runs the BOOTSTRAP.md lifecycle,
and renders the workspace files a turn injects into the system prompt. It is a
port of the OpenClaw workspace bootstrap code at pin `4c42815348`
(`src/agents/workspace.ts`, `src/agents/bootstrap-files.ts`,
`src/agents/embedded-agent-helpers/bootstrap.ts`, `src/agents/system-prompt.ts`),
plus memory-core extensions that have no upstream reference. Parity status per
behaviour lives in [the parity matrix](parity_matrix.md) (rows "Workspace
bootstrap files" and "Bootstrap truncation").

```python
from memory_core.bootstrap import build_workspace_context, initialize_agent_workspace

# Every turn, like upstream's ensureAgentWorkspace in the reply path:
initialize_agent_workspace(root, templates=host_templates)
context = build_workspace_context(root, session_kind="main")
system_prompt = context.prompt_text
```

`build_workspace_context` only reads. Upstream runs `ensureAgentWorkspace` on
every reply turn (`src/auto-reply/reply/get-reply.ts:418-425`), and that call
is where a configured workspace (a changed SOUL/IDENTITY/USER, `memory/`,
`MEMORY.md`, a skill) gets its BOOTSTRAP.md deleted and setup marked complete.
A host that initializes only once keeps injecting BOOTSTRAP.md and `## Bootstrap
Pending`; call `initialize_agent_workspace` with the same templates before each
`build_workspace_context`.

## Layouts

Two presets ship; `DEFAULT_WORKSPACE_LAYOUT` is `MEMORY_CORE_WORKSPACE_LAYOUT`.

| File | Load / budget order | Render priority | Seeded | subagent | cron |
|---|---|---|---|---|---|
| AGENTS.md | 1 | 10 | always | yes | yes |
| SOUL.md | 2 | 20 | optional | no | yes |
| TOOLS.md | 3 | 50 | always | yes | yes |
| IDENTITY.md | 4 | 30 | optional | no | yes |
| USER.md | 5 | 40 | optional | no | yes |
| PROACTIVE_PREFERENCES.md (memory-core extension) | 6 | 45 | optional | no | yes |
| HEARTBEAT.md | 7 | dynamic, below the cache boundary | optional | no | no |
| BOOTSTRAP.md | 8 | 60 | first run only | no | no |
| MEMORY.md | 9 | 70 | never | no | no |

- `OPENCLAW_PIN_LAYOUT` is the pin's file set: the same rows without
  PROACTIVE_PREFERENCES.md, so its load order has 8 entries.
- `MEMORY_CORE_WORKSPACE_LAYOUT` adds PROACTIVE_PREFERENCES.md (when and how the
  agent may act or reach out unprompted) and the folders `user/` (user-supplied
  files) and `workspace/` (agent-made artifacts). The folders are created on
  initialization and are never injected or indexed. These are memory-core
  extensions with no upstream reference; PROACTIVE_PREFERENCES.md loads after
  USER.md, follows USER.md into cron sessions and is not setup evidence.
- Two orders exist upstream. Files consume the per-file (20,000) and total
  (60,000) budget in load order, then render in priority order; unknown
  basenames sort last. Lengths are UTF-16 code units.
- BOOT.md and DREAMS.md are upstream workspace files that are never injected.
  Daily notes in `memory/YYYY-MM-DD.md` are read on demand, not injected.

## Seeding and lifecycle

`initialize_agent_workspace` follows `ensureAgentWorkspace`:

1. Write missing required files (AGENTS.md, TOOLS.md) and optional files from
   `templates`. Existing files are never overwritten, and once setup is
   complete optional files a user removed are not recreated. Templates come
   from the host and default to empty strings; memory-core ships no seed text.
2. Write BOOTSTRAP.md only when the state has no marker, the file is absent,
   and there is no setup evidence: a SOUL/IDENTITY/USER file that differs from
   its template, `memory/`, `MEMORY.md`, a `skills/*/SKILL.md`, or `.git`.
3. When the same evidence (without `.git`) appears while BOOTSTRAP.md exists,
   mark setup complete and delete BOOTSTRAP.md. When BOOTSTRAP.md was seeded
   and is gone (the agent deleted it), mark setup complete.

State lives in `.memory-core/workspace-state.json` (`{version, bootstrapSeededAt,
setupCompletedAt}`); upstream's `openclaw-workspace-state.json` and
`.openclaw/workspace-state.json` are read as fallbacks and migrated. The
migration is a one-way snapshot: once `initialize_agent_workspace` has copied a
marker-bearing upstream state into `.memory-core/`, memory-core reads only its own
file, so later state changes by an OpenClaw runtime sharing the workspace are
not seen. A `.memory-core` that is not a directory reads as no state; writing the
state then fails.

- Create memory files after initialization, or the workspace counts as set up
  and no BOOTSTRAP.md is written.
- An empty BOOTSTRAP.md still reports `pending`; with file access the prompt
  asks the model to read it, without it the prompt carries the `limited` lines.
  Hosts without a first-run ritual pass `seed_bootstrap=False` (extension):
  where BOOTSTRAP.md would be written, setup is marked complete instead, so
  optional files a user removes later are not recreated. An existing
  BOOTSTRAP.md is still honoured.

## Per-turn filters

`build_workspace_context` applies upstream's run pipeline:

- Session kind: `subagent` keeps AGENTS.md and TOOLS.md; `cron` keeps the cron
  column above; `main`, `group`, `channel`, `direct` and `heartbeat` keep
  everything, MEMORY.md included (upstream enforces "main session only" in
  template prose, not in code).
- BOOTSTRAP.md is dropped once setup is complete, and stays in Project Context
  only when the bootstrap mode is `full`. The mode follows
  `resolveBootstrapMode` as the attempt routes it: `none` unless the workspace
  is pending on a primary interactive run; then `limited` when
  `has_bootstrap_file_access=False` (upstream: the run has no `read` tool) or
  `is_canonical_workspace=False`, else `full`. A BOOTSTRAP.md with content
  counts as file access. Both inputs come from the host (default `True` here,
  `has_bootstrap_file_access=False` in `memory_core.live` and the Lab chat, which
  give the model no read tool).
- `context_mode="lightweight"` keeps only HEARTBEAT.md on heartbeat runs and
  nothing otherwise; `commitment-only` runs drop HEARTBEAT.md.
- `context_injection` is `always`, `continuation-skip` or `never`.
- A missing file renders `[MISSING] Expected at: <path>`; a missing MEMORY.md
  is skipped, and so is a missing extension file (PROACTIVE_PREFERENCES.md,
  `WorkspaceLayout.extension_files`), so a pin-era workspace renders as it does
  upstream; empty files are not injected.
- `exclude_files` drops basenames before budgeting (host policy, no upstream
  equivalent).

`prompt_text` joins the bootstrap sections, `## Workspace Files (injected)`,
`# Project Context` and the dynamic block in upstream order. Upstream sections
memory-core does not own (output directives, Silent Replies) and the cache boundary
marker are not rendered; hosts with a prompt cache place `dynamic_text` below
their boundary.

`truncation_warning_lines` end with upstream's config hint, which names
OpenClaw's `agents.defaults.bootstrapMaxChars` and
`agents.defaults.bootstrapTotalMaxChars`. With the default MEMORY-CORE runtime
identity the line names the per-file and total limits instead; in memory-core they
are `max_chars` / `total_max_chars` (`max_chars_per_file` / `total_max_chars`
in `memory_core.live`). `identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY` keeps the
upstream text, like the Workspace Files intro line.

`build_startup_context` ports the bare `/new` / `/reset` daily-memory prelude;
the host passes the timezone (default UTC).

Upstream's head/tail slices (and the 1,200-unit startup cut) are plain UTF-16
slices that can split a surrogate pair. `build_bootstrap_context_files` keeps
that byte-exact, but every string `build_workspace_context` and
`build_startup_context` hand to the host is well-formed: a lone surrogate
becomes U+FFFD (`String.prototype.toWellFormed`). Node writes the same UTF-8
bytes for the upstream string; Python could not encode it at all
(`str.encode`, `json.dumps(ensure_ascii=False)`), so this is a transport-boundary
deviation, not a content change.

## Consumers

- `memory_core.live.LiveIdentity` renders a live subject prompt through
  `build_workspace_context` and keeps the agent's root MEMORY.md out unless
  `include_agent_memory=True` (deliberate deviation, see
  [Live SDK Integration](integrations/live.md)).
- The Lab demo (`demo/workspace_context.py`) passes its own seed texts as
  templates and injects `prompt_text` on every chat turn.

## Not ported

- Workspace attestations and the `WorkspaceVanishedError` guard.
- `git init` for brand-new workspaces and the `ensureBootstrapFiles: false`
  mode.
- The `agent:bootstrap` hook, `bootstrap-extra-files` globs and the
  per-session snapshot cache.
- The transcript scan behind `hasCompletedBootstrapTurn`: the host passes
  `has_completed_bootstrap_turn` and persists the marker when
  `record_completed_bootstrap_turn` is set.
- The heartbeat-guidance decision: the host passes `include_heartbeat`.
- `localeCompare` is approximated for non-ASCII text; it only breaks ties
  between paths. It is exact for ASCII. Non-ASCII letters without a
  decomposition (ı, ø, ß, æ) and non-ASCII punctuation (the en dash) sort after
  `z` by code point, where ICU puts them next to their base letters or before
  letters. Layout files under one root never hit this, but unknown non-ASCII
  basenames a host passes to `render_project_context` or `sort_context_files`
  can render in a different order than upstream (for example Turkish `ılık`
  after `zeta`).
- `WorkspaceContext.workspace_notes` holds upstream's
  `Reminder: commit your changes in this workspace after edits.` note
  (`attempt.ts:1489-1495`) but `prompt_text` does not render it: upstream puts
  it into the `## Workspace` section of the full system prompt
  (`system-prompt.ts:1157-1161`), which memory-core does not build. Hosts that
  render that section add the note themselves.
