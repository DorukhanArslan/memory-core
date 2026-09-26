"""Lab adapter over :mod:`memory_core.bootstrap` (demo-only).

The Lab keeps its own seed texts below (project-authored, not OpenClaw template
wording) and passes them to ``initialize_agent_workspace`` as host templates.
Seeding, the BOOTSTRAP.md lifecycle, the per-file/total budget and the Project
Context rendering all come from the package, so the chat prompt uses the
upstream render format and order. Nothing here is a second implementation.
"""

from __future__ import annotations

from pathlib import Path

from memory_core.bootstrap import (
    DEFAULT_WORKSPACE_LAYOUT,
    ContextFile,
    WorkspaceInitResult,
    WorkspaceLayout,
    build_workspace_context,
    initialize_agent_workspace,
)
from memory_core.bootstrap.render import prepare_context_files

DEMO_WORKSPACE_LAYOUT = DEFAULT_WORKSPACE_LAYOUT

# Lab seed texts (project-authored). PROACTIVE_PREFERENCES.md has no Lab text
# and is seeded empty, so it is not injected until someone writes to it.
DEMO_WORKSPACE_TEMPLATES = {
    "AGENTS.md": """# AGENTS.md - Operating Instructions

You are memory-core, a private workspace agent.

- Follow the user's explicit instructions unless they conflict with safety or tool limits.
- Treat workspace files as durable operator state.
- Use memory files for recall instead of guessing.
- Keep detailed daily notes in `memory/YYYY-MM-DD.md`.
- Keep curated long-term summaries in `MEMORY.md`.
""",
    "SOUL.md": """# SOUL.md - Persona and Tone

Be direct, practical, and technically precise.

- Skip filler.
- Use Turkish when the user writes Turkish.
- Prefer concise answers unless the user asks for detail.
- Call out weak assumptions early.
""",
    "TOOLS.md": """# TOOLS.md - Local Tool Conventions

This file is guidance, not an access-control list.

- Use memory search/get when a question depends on previous sessions.
- Do not store secrets in memory.
- Prefer narrow file reads over loading broad history.
""",
    "IDENTITY.md": """# IDENTITY.md - Agent Identity

Name: memory-core
Vibe: pragmatic memory lab assistant
Emoji: none
""",
    "USER.md": """# USER.md - User Profile

No stable user facts have been curated yet.
""",
    "HEARTBEAT.md": """# HEARTBEAT.md - Continuity Check

Before acting, re-read the workspace files that define current identity, user context, tools, and memory.
""",
    "BOOTSTRAP.md": """# BOOTSTRAP.md - First Run

Use this file only for first-run workspace configuration. Once identity is configured, it may be removed.
""",
}


def ensure_workspace_bootstrap_files(
    workspace_dir: Path, *, layout: WorkspaceLayout = DEMO_WORKSPACE_LAYOUT
) -> WorkspaceInitResult:
    """Seed missing layout files from the Lab templates and run the lifecycle.

    Upstream semantics (``ensureAgentWorkspace``): existing files are never
    overwritten, BOOTSTRAP.md is written only for a workspace without setup
    evidence (``memory/``, ``MEMORY.md``, a skill, or a changed SOUL/IDENTITY/
    USER file), and it is deleted once such evidence appears.
    """
    return initialize_agent_workspace(
        workspace_dir, layout=layout, templates=DEMO_WORKSPACE_TEMPLATES
    )


def workspace_file_names(layout: WorkspaceLayout = DEMO_WORKSPACE_LAYOUT) -> list[str]:
    """Layout files the Lab lists, in load order; MEMORY.md is listed as a memory file."""
    return [name for name in layout.load_order if name != layout.memory_file]


def workspace_file_contents(
    workspace_dir: Path, *, layout: WorkspaceLayout = DEMO_WORKSPACE_LAYOUT
) -> dict[str, str]:
    contents: dict[str, str] = {}
    for rel_path in workspace_file_names(layout):
        path = workspace_dir / rel_path
        contents[rel_path] = path.read_text(encoding="utf-8") if path.is_file() else ""
    return contents


def injected_file_order(layout: WorkspaceLayout = DEMO_WORKSPACE_LAYOUT) -> list[str]:
    """Project Context order of the layout's files; dynamic files (HEARTBEAT.md) last."""
    prepared = prepare_context_files(
        (ContextFile(name, "") for name in layout.load_order), layout
    )
    return [file.path for file in (*prepared.stable, *prepared.dynamic)]


def workspace_layout_summary(layout: WorkspaceLayout = DEMO_WORKSPACE_LAYOUT) -> dict[str, object]:
    return {
        "name": layout.name,
        "loadOrder": list(layout.load_order),
        "injectedOrder": injected_file_order(layout),
    }


def build_workspace_prompt(
    workspace_dir: Path, *, layout: WorkspaceLayout = DEMO_WORKSPACE_LAYOUT
) -> str:
    """The injected workspace text of a main-session turn (upstream format).

    The Lab model gets memory and curation tools but no generic ``read`` tool,
    so the run has no ``read`` access to the workspace (upstream's
    ``bootstrapHasFileAccess``, attempt.ts:1370). Lab turns build their context
    per session kind in :mod:`demo.lab_prompt`; this helper stays for tests and
    scripts that want the main-session text.
    """
    return build_workspace_context(
        workspace_dir, layout=layout, has_bootstrap_file_access=False
    ).prompt_text
