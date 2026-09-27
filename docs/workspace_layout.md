# Workspace Layout

`memory_core.bootstrap` seeds an agent workspace, runs the BOOTSTRAP.md lifecycle,
and renders the workspace files a turn injects into the system prompt. It is a
port of the OpenClaw workspace bootstrap code at the parity pin, release tag
`v2026.9.6` (`src/agents/workspace-bootstrap-policy.ts`, `src/agents/workspace.ts`,
`src/agents/bootstrap-files.ts`, `src/agents/embedded-agent-helpers/bootstrap.ts`,
`src/agents/system-prompt.ts`, `src/agents/system-prompt-context-files.ts`), plus
memory-core extensions that have no upstream reference. Parity status per behaviour
lives in [the parity matrix](parity_matrix.md) (rows "Workspace bootstrap files"
and "Bootstrap truncation").

```python
from memory_core.bootstrap import build_workspace_context, initialize_agent_workspace

# Every turn, like upstream's ensureAgentWorkspace in the reply path:
initialize_agent_workspace(root, templates=host_templates)
context = build_workspace_context(root, session_kind="main")
system_prompt = context.prompt_text
```

`build_workspace_context` only reads. Upstream runs `ensureAgentWorkspace` on
every reply turn, and that call is where a configured workspace (a changed
SOUL/IDENTITY/USER, `memory/`, `MEMORY.md`, a skill) gets its BOOTSTRAP.md
deleted and setup marked complete. A host that initializes only once keeps
injecting BOOTSTRAP.md and `## Bootstrap Pending`; call
`initialize_agent_workspace` with the same templates before each
`build_workspace_context`.

## Layouts

Two presets ship; `DEFAULT_WORKSPACE_LAYOUT` is `MEMORY_CORE_WORKSPACE_LAYOUT`.

| File | Load / render order | Render priority | Seeded | Absent | subagent | cron |
|---|---|---|---|---|---|---|
| AGENTS.md | 1 | 10 | always | `[MISSING]` | yes | yes |
| SOUL.md | 2 | 20 | optional | `[MISSING]` | no | yes |
| IDENTITY.md | 3 | 30 | optional | `[MISSING]` | no | yes |
| USER.md | 4 | 40 | optional | skipped | no | yes |
| PROACTIVE_PREFERENCES.md (memory-core extension) | 5 | 45 | optional | skipped | no | yes |
| BOOTSTRAP.md | 6 | 60 | first run only | `[MISSING]` | no | no |
| MEMORY.md | 7 | 70 | never | skipped | no | no |

- `OPENCLAW_COMPAT_LAYOUT` is upstream's map alone: `WORKSPACE_BOOTSTRAP_FILENAMES`
  (AGENTS, SOUL, IDENTITY, USER, BOOTSTRAP, MEMORY), the generated owner documents
  `GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES` (AGENTS, SOUL, IDENTITY, USER), and the
  rows above without PROACTIVE_PREFERENCES.md.
- `MEMORY_CORE_WORKSPACE_LAYOUT` adds PROACTIVE_PREFERENCES.md (when and how the agent
  may act or reach out unprompted) and the folders `user/` (user-supplied files) and
  `workspace/` (agent-made artifacts). The folders are created on initialization and
  are never injected or indexed. These are memory-core extensions with no upstream
  reference; PROACTIVE_PREFERENCES.md loads after USER.md, follows USER.md into cron
  sessions and is not setup evidence. Two newer upstream features overlap them and are
  kept apart, not renamed: the AGENTS.md template section "Automations - Be
  Proactive" (PROACTIVE_PREFERENCES.md) and the authenticated personal
  `users/<profile-id>/USER.md` overlay, which memory-core does not port (`user/`).
- Load order equals render order at v2026.9.6. Files consume the per-file (20,000)
  and total (60,000) budget in that order; USER.md is capped at
  `min(max_chars, 4000)`. Unknown basenames a host passes render after the known
  ones (`tools.md` keeps priority 50 for a host-supplied TOOLS.md). Lengths are UTF-16
  code units.
- TOOLS.md and HEARTBEAT.md are no longer bootstrap files. Local tool notes live in
  the `## Tools` section of AGENTS.md: `migrate_tools_md(root)` ports upstream's doctor
  migration (customised notes are appended verbatim under `### Local notes (migrated
  from TOOLS.md)`, stock templates and blank files are only archived, the original is
  archived under `.memory-core/backups/tools-md-migration/` and removed after a hash
  check). HEARTBEAT.md moved to a heartbeat monitor scratch upstream; `memory_core.heartbeat`
  still reads the file until that port lands.
- BOOT.md and DREAMS.md are upstream workspace files that are never injected.
  Daily notes in `memory/YYYY-MM-DD.md` are read on demand, not injected.

## Seeding and lifecycle

`initialize_agent_workspace` follows `ensureAgentWorkspace`:

1. Write a missing AGENTS.md and the missing optional files from `templates`.
   Existing files are never overwritten, and once setup is complete optional files a
   user removed are not recreated. Templates come from the host and default to empty
   strings; memory-core ships no seed text.
2. Write BOOTSTRAP.md only when the state has no marker, the file is absent, and there
   is no setup evidence: a SOUL/IDENTITY/USER file that differs from its template,
   `memory/`, `MEMORY.md`, a `skills/*/SKILL.md`, or `.git`.
3. When the same evidence (without `.git`) appears while BOOTSTRAP.md exists, mark
   setup complete and delete BOOTSTRAP.md. When BOOTSTRAP.md was seeded and is gone
   (the agent deleted it), mark setup complete.

Setup state. Upstream keeps it in its shared SQLite state database; memory-core keeps
`{version, bootstrapSeededAt, setupCompletedAt}` in `.memory-core/workspace-state.json`
(documented deviation). Upstream's retired JSON state (`openclaw-workspace-state.json`,
`.openclaw/workspace-state.json`, or an interrupted doctor claim of either) makes every
lifecycle call raise `WorkspaceStateMigrationRequiredError`, as upstream refuses the
workspace until `openclaw doctor --fix`; `migrate_legacy_workspace_state(root)` ports
doctor's strict import (imports the first source unless memory-core already has state,
archives each source beside itself as `<source>.migrated.<sha256>.<uuid>`, removes it).
A `.memory-core` that is not a directory reads as no state; writing the state then fails.

- Create memory files after initialization, or the workspace counts as set up and no
  BOOTSTRAP.md is written.
- An empty BOOTSTRAP.md still reports `pending`; with file access the prompt asks the
  model to read it, without it the prompt carries the `limited` lines. Hosts without a
  first-run ritual pass `seed_bootstrap=False` (extension): where BOOTSTRAP.md would be
  written, setup is marked complete instead, so optional files a user removes later
  are not recreated. An existing BOOTSTRAP.md is still honoured.

## Per-turn filters

`build_workspace_context` applies upstream's run pipeline:

- Loading: USER.md and MEMORY.md (and the extension file) are skipped unless the
  directory lists the exact name. A missing file renders `[MISSING] Expected at:
  <path>`; a file the guarded read refuses (any final symlink, a hard link, a
  directory, over 2 MiB, a permission error) renders `[UNREADABLE: <reason>]`; empty
  files are not injected.
- Session kind: `subagent` keeps AGENTS.md; `cron` keeps AGENTS, SOUL, IDENTITY, USER
  (plus the extension); `subagent`, `cron`, `group` and `channel` never get the root
  MEMORY.md; `main`, `direct` and `heartbeat` keep everything.
- BOOTSTRAP.md is dropped once setup is complete, and stays in Project Context only
  when the bootstrap mode is `full`. The mode follows `resolveBootstrapMode` as the
  attempt routes it: `none` unless the workspace is pending on a primary interactive
  run; then `limited` when `has_bootstrap_file_access=False` (upstream: the run has no
  `read` tool) or `is_canonical_workspace=False`, else `full`. A BOOTSTRAP.md with
  content counts as file access. Both inputs come from the host (default `True` here,
  `has_bootstrap_file_access=False` in `memory_core.live` and the Lab chat, which give the
  model no read tool).
- `context_mode="lightweight"` injects no bootstrap file at all (upstream injects the
  heartbeat monitor scratch through the heartbeat runner instead).
- `context_injection` is `always`, `continuation-skip` or `never`.
- `exclude_files` drops basenames before budgeting (host policy, no upstream
  equivalent).

`prompt_text` joins the bootstrap sections, `## Workspace Files (injected)` and
`# Project Context` in upstream order; all of it sits above upstream's prompt cache
boundary (v2026.9.6 has no dynamic Project Context). Upstream sections memory-core does
not own (reasoning format, output directives, Silent Replies) and the boundary marker
are not rendered.

`truncation_warning_lines` end with upstream's config hint, which names OpenClaw's
`agents.defaults.bootstrapMaxChars` and `agents.defaults.bootstrapTotalMaxChars`, when
a limit the host can raise applied; a USER.md cut by its fixed cap gets upstream's
"fixed 4000-character bootstrap cap" line instead. With the default MEMORY-CORE runtime
identity the config line names the per-file and total limits; in memory-core they are
`max_chars` / `total_max_chars` (`max_chars_per_file` / `total_max_chars` in
`memory_core.live`). `identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY` keeps the upstream text,
like the Workspace Files intro line.

`build_startup_context` ports the bare `/new` / `/reset` daily-memory prelude; the
host passes the timezone (default UTC).

Head and tail slices are surrogate-safe at v2026.9.6 (`sliceUtf16Safe`). Every string
`build_workspace_context` and `build_startup_context` hand to the host still passes
through `String.prototype.toWellFormed` semantics as a transport guard, because
Python cannot UTF-8 encode a lone surrogate (the pin-era 1,200-unit startup cut in
`build_startup_context` can still leave one; its re-port is on the v2026.9.6 worklist).

## Consumers

- `memory_core.live.LiveIdentity` renders a live subject prompt through
  `build_workspace_context` and keeps the agent's root MEMORY.md out unless
  `include_agent_memory=True` (deliberate deviation, see
  [Live SDK Integration](integrations/live.md)).
- The Lab demo (`demo/workspace_context.py`) passes its own seed texts as templates
  and injects `prompt_text` on every chat turn; its explorer offers the TOOLS.md
  migration on a TOOLS.md row.

## Not ported

- Workspace attestations, the `WorkspaceVanishedError` guard and doctor's attestation
  sources.
- `git init` for brand-new workspaces, the `ensureBootstrapFiles: false` and
  runtime-managed modes, the custom-agent `purpose`.
- The `agent:bootstrap` hook, `bootstrap-extra-files` globs (so
  `WorkspaceLayout.can_read` allows only the layout's root files) and the per-session
  snapshot and file caches.
- The personal `users/<profile-id>/USER.md` overlay, the automatic-memory provenance
  filter and the per-project curated MEMORY.md filter.
- The transcript scan behind `hasCompletedBootstrapTurn`: the host passes
  `has_completed_bootstrap_turn` and persists the marker when
  `record_completed_bootstrap_turn` is set.
- `localeCompare` is approximated for non-ASCII text; it only breaks ties between
  paths and is exact for ASCII. Unknown non-ASCII basenames a host passes to
  `render_project_context` or `sort_context_files` can render in a different order
  than upstream (for example Turkish `ılık` after `zeta`).
- `WorkspaceContext.workspace_notes` holds upstream's `Reminder: commit your changes
  in this workspace after edits.` note but `prompt_text` does not render it: upstream
  puts it into the `## Workspace` section of the full system prompt, which memory-core
  does not build. Hosts that render that section add the note themselves.
