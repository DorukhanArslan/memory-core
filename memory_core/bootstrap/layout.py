"""Workspace layouts: which bootstrap files exist, in which order they load and render.

Two presets ship:

- ``OPENCLAW_PIN_LAYOUT``: the OpenClaw file set at the pinned commit
  4c42815348 (``src/agents/workspace.ts:31-47,195-211,1045-1078``;
  render order ``src/agents/system-prompt.ts:69-79``).
- ``MEMORY_CORE_WORKSPACE_LAYOUT`` (default): the pin layout plus the memory-core
  extensions ``PROACTIVE_PREFERENCES.md`` (when and how the agent may act or
  reach out unprompted) and the ``user/`` (user-supplied files) and
  ``workspace/`` (agent-made artifacts) folders. They have no upstream
  reference: PROACTIVE_PREFERENCES.md loads after USER.md, renders at priority
  45, is kept for cron sessions like USER.md and is an optional seed; the
  folders are created on initialization but never injected into context and
  never indexed. An
  absent PROACTIVE_PREFERENCES.md is skipped like an absent MEMORY.md (no
  ``[MISSING]`` marker), so upstream-shaped workspaces render unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

AGENTS_FILENAME = "AGENTS.md"
SOUL_FILENAME = "SOUL.md"
TOOLS_FILENAME = "TOOLS.md"
IDENTITY_FILENAME = "IDENTITY.md"
USER_FILENAME = "USER.md"
HEARTBEAT_FILENAME = "HEARTBEAT.md"
BOOTSTRAP_FILENAME = "BOOTSTRAP.md"
MEMORY_FILENAME = "MEMORY.md"
# memory-core extension (no upstream reference).
PROACTIVE_PREFERENCES_FILENAME = "PROACTIVE_PREFERENCES.md"


def _is_plain_basename(value: object) -> bool:
    return (
        isinstance(value, str)
        and value not in ("", ".", "..")
        and not any(char in value for char in ("/", "\\", "\0"))
        and not os.path.isabs(value)
        and not os.path.splitdrive(value)[0]
    )


@dataclass(frozen=True)
class WorkspaceLayout:
    """Frozen description of a workspace's bootstrap files.

    ``load_order`` is the load and budget order (per-file and total caps are
    consumed in this order). ``render_priorities`` maps lower-cased basenames to
    the Project Context sort priority; unknown basenames sort after every known
    one, by basename then by path. ``dynamic_files`` render below the prompt
    cache boundary instead of in the stable Project Context block.
    ``required_files`` are always seeded when missing; ``optional_files`` are
    seeded unless skipped or setup is complete. ``profile_files`` are compared
    with their templates to detect a configured workspace. ``subagent_files``
    and ``cron_files`` are the allowlists for those session kinds.
    ``extra_dirs`` are created on initialization and never loaded.
    ``extension_files`` have no upstream counterpart; like MEMORY.md they are
    skipped (no ``[MISSING]`` marker) unless the directory lists the exact
    name, so an upstream-shaped workspace renders as it does upstream.
    """

    name: str
    load_order: tuple[str, ...]
    render_priorities: tuple[tuple[str, int], ...]
    dynamic_files: frozenset[str]
    required_files: tuple[str, ...]
    optional_files: tuple[str, ...]
    profile_files: tuple[str, ...]
    subagent_files: frozenset[str]
    cron_files: frozenset[str]
    extra_dirs: tuple[str, ...] = ()
    extension_files: frozenset[str] = frozenset()
    bootstrap_file: str = BOOTSTRAP_FILENAME
    memory_file: str = MEMORY_FILENAME
    heartbeat_file: str = HEARTBEAT_FILENAME

    def __post_init__(self) -> None:
        # Seeding writes root / name and mkdirs root / dirname: only plain
        # basenames keep those writes inside the workspace root.
        names: dict[str, tuple[str, ...]] = {
            "load_order": self.load_order,
            "required_files": self.required_files,
            "optional_files": self.optional_files,
            "profile_files": self.profile_files,
            "subagent_files": tuple(self.subagent_files),
            "cron_files": tuple(self.cron_files),
            "extension_files": tuple(self.extension_files),
            "extra_dirs": self.extra_dirs,
            "bootstrap_file": (self.bootstrap_file,),
            "memory_file": (self.memory_file,),
            "heartbeat_file": (self.heartbeat_file,),
        }
        for field_name, values in names.items():
            for value in values:
                if not _is_plain_basename(value):
                    raise ValueError(
                        f"WorkspaceLayout.{field_name} entries must be plain basenames: {value!r}"
                    )

    def render_priority(self, basename: str) -> int | None:
        lowered = basename.lower()
        for name, priority in self.render_priorities:
            if name == lowered:
                return priority
        return None

    def is_dynamic(self, basename: str) -> bool:
        return basename.lower() in self.dynamic_files

    @property
    def seed_order(self) -> tuple[str, ...]:
        seeded = set(self.required_files) | set(self.optional_files)
        return tuple(name for name in self.load_order if name in seeded)


OPENCLAW_PIN_LAYOUT = WorkspaceLayout(
    name="openclaw-pin",
    load_order=(
        AGENTS_FILENAME,
        SOUL_FILENAME,
        TOOLS_FILENAME,
        IDENTITY_FILENAME,
        USER_FILENAME,
        HEARTBEAT_FILENAME,
        BOOTSTRAP_FILENAME,
        MEMORY_FILENAME,
    ),
    render_priorities=(
        ("agents.md", 10),
        ("soul.md", 20),
        ("identity.md", 30),
        ("user.md", 40),
        ("tools.md", 50),
        ("bootstrap.md", 60),
        ("memory.md", 70),
    ),
    dynamic_files=frozenset({"heartbeat.md"}),
    required_files=(AGENTS_FILENAME, TOOLS_FILENAME),
    optional_files=(SOUL_FILENAME, IDENTITY_FILENAME, USER_FILENAME, HEARTBEAT_FILENAME),
    profile_files=(SOUL_FILENAME, IDENTITY_FILENAME, USER_FILENAME),
    subagent_files=frozenset({AGENTS_FILENAME, TOOLS_FILENAME}),
    cron_files=frozenset(
        {AGENTS_FILENAME, TOOLS_FILENAME, SOUL_FILENAME, IDENTITY_FILENAME, USER_FILENAME}
    ),
)

MEMORY_CORE_WORKSPACE_LAYOUT = WorkspaceLayout(
    name="memory-core",
    load_order=(
        AGENTS_FILENAME,
        SOUL_FILENAME,
        TOOLS_FILENAME,
        IDENTITY_FILENAME,
        USER_FILENAME,
        PROACTIVE_PREFERENCES_FILENAME,
        HEARTBEAT_FILENAME,
        BOOTSTRAP_FILENAME,
        MEMORY_FILENAME,
    ),
    render_priorities=(
        ("agents.md", 10),
        ("soul.md", 20),
        ("identity.md", 30),
        ("user.md", 40),
        ("proactive_preferences.md", 45),
        ("tools.md", 50),
        ("bootstrap.md", 60),
        ("memory.md", 70),
    ),
    dynamic_files=frozenset({"heartbeat.md"}),
    required_files=(AGENTS_FILENAME, TOOLS_FILENAME),
    optional_files=(
        SOUL_FILENAME,
        IDENTITY_FILENAME,
        USER_FILENAME,
        PROACTIVE_PREFERENCES_FILENAME,
        HEARTBEAT_FILENAME,
    ),
    # Upstream's onboarding profile set; PROACTIVE_PREFERENCES.md (an
    # extension) is not treated as setup-completion evidence.
    profile_files=(SOUL_FILENAME, IDENTITY_FILENAME, USER_FILENAME),
    subagent_files=frozenset({AGENTS_FILENAME, TOOLS_FILENAME}),
    # Extension choice: preferences follow USER.md into cron sessions.
    cron_files=frozenset(
        {
            AGENTS_FILENAME,
            TOOLS_FILENAME,
            SOUL_FILENAME,
            IDENTITY_FILENAME,
            USER_FILENAME,
            PROACTIVE_PREFERENCES_FILENAME,
        }
    ),
    extra_dirs=("user", "workspace"),
    # Extension: an absent PROACTIVE_PREFERENCES.md renders nothing, so a
    # pin-era workspace without it gets exactly upstream's Project Context.
    extension_files=frozenset({PROACTIVE_PREFERENCES_FILENAME}),
)

DEFAULT_WORKSPACE_LAYOUT = MEMORY_CORE_WORKSPACE_LAYOUT
