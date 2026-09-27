"""Workspace layouts: which bootstrap files exist, in which order they load and render.

Two presets ship, both following the OpenClaw workspace map of the parity pin, release tag
v2026.9.6 (``memory_core.parity.upstream.LATEST_INSPECTED_COMMIT``):

- ``OPENCLAW_COMPAT_LAYOUT``: upstream's file set and nothing else.
  ``WORKSPACE_BOOTSTRAP_FILENAMES`` (``src/agents/workspace-bootstrap-policy.ts``: AGENTS,
  SOUL, IDENTITY, USER, BOOTSTRAP, MEMORY; load order = prompt order since 78d7a8489cd,
  #114436), the generated owner documents ``GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES`` (AGENTS,
  SOUL, IDENTITY, USER), the seeding of ``ensureAgentWorkspace`` (AGENTS.md always, SOUL,
  IDENTITY and USER unless skipped, ``src/agents/workspace.ts``), the loader's skip-when-absent
  set (USER.md and MEMORY.md, ``loadWorkspaceBootstrapFiles``), the session allowlists
  (``SUBAGENT_BOOTSTRAP_ALLOWLIST``, ``CRON_BOOTSTRAP_ALLOWLIST``) and the render priorities of
  ``CONTEXT_FILE_ORDER`` (``src/agents/system-prompt-context-files.ts``). TOOLS.md left the
  set in 669db2968fc (#113966: local tool notes live in AGENTS.md ``## Tools``; migrate an old
  file with :func:`memory_core.bootstrap.migrate_tools_md`), HEARTBEAT.md in 3e2b3ea4d5e (#112967:
  the heartbeat monitor scratch). ``tools.md`` keeps render priority 50 because upstream's
  ``CONTEXT_FILE_ORDER`` still sorts a hook-supplied TOOLS.md there.
- ``MEMORY_CORE_WORKSPACE_LAYOUT`` (default): the same map plus the memory-core extensions
  ``PROACTIVE_PREFERENCES.md`` (when and how the agent may act or reach out unprompted) and
  the ``user/`` (user-supplied files) and ``workspace/`` (agent-made artifacts) folders. They
  have no upstream reference: PROACTIVE_PREFERENCES.md loads after USER.md, renders at
  priority 45, is kept for cron sessions like USER.md, is an optional seed and, like USER.md,
  is skipped (no ``[MISSING]`` marker) when absent, so upstream-shaped workspaces render
  unchanged; the folders are created on initialization but never injected into context and
  never indexed. Overlaps with newer upstream features are kept and documented, not renamed
  (Doruk, 2026-09-27): PROACTIVE_PREFERENCES.md next to the AGENTS.md "Automations - Be
  Proactive" template section, ``user/`` next to upstream's authenticated personal
  ``users/<profile-id>/USER.md`` overlay (``src/agents/workspace-personal-bootstrap.ts``,
  not ported).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

AGENTS_FILENAME = "AGENTS.md"
SOUL_FILENAME = "SOUL.md"
IDENTITY_FILENAME = "IDENTITY.md"
USER_FILENAME = "USER.md"
BOOTSTRAP_FILENAME = "BOOTSTRAP.md"
MEMORY_FILENAME = "MEMORY.md"
# Retired upstream (669db2968fc, #113966); only the TOOLS.md migration still names it.
TOOLS_FILENAME = "TOOLS.md"
# memory-core extension (no upstream reference).
PROACTIVE_PREFERENCES_FILENAME = "PROACTIVE_PREFERENCES.md"

# src/agents/workspace-bootstrap-policy.ts at v2026.9.6.
WORKSPACE_BOOTSTRAP_FILENAMES = (
    AGENTS_FILENAME,
    SOUL_FILENAME,
    IDENTITY_FILENAME,
    USER_FILENAME,
    BOOTSTRAP_FILENAME,
    MEMORY_FILENAME,
)
GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES = (
    AGENTS_FILENAME,
    SOUL_FILENAME,
    IDENTITY_FILENAME,
    USER_FILENAME,
)


def _is_plain_basename(value: object) -> bool:
    return (
        isinstance(value, str)
        and value not in ("", ".", "..")
        and not any(char in value for char in ("/", "\\", "\0"))
        and not os.path.isabs(value)
        and not os.path.splitdrive(value)[0]
    )


def _is_relative_policy_path(value: str) -> bool:
    # workspace-bootstrap-policy.ts isRelativePath.
    return (
        isinstance(value, str)
        and len(value) > 0
        and not os.path.isabs(value)
        and "\\" not in value
        and "\0" not in value
        and all(part not in ("", ".", "..") for part in value.split("/"))
    )


@dataclass(frozen=True)
class WorkspaceLayout:
    """Frozen description of a workspace's bootstrap files.

    ``load_order`` is the load and budget order (per-file and total caps are consumed in this
    order). ``render_priorities`` maps lower-cased basenames to the Project Context sort
    priority; unknown basenames sort after every known one, by basename then by path.
    ``required_files`` are always seeded when missing; ``optional_files`` are seeded unless
    skipped or setup is complete. ``generated_files`` are the owner documents upstream
    generates and attests (``GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES``). ``profile_files`` are
    compared with their templates to detect a configured workspace. ``subagent_files`` and
    ``cron_files`` are the allowlists for those session kinds. ``skip_absent_files`` are left
    out of the load (no ``[MISSING]`` marker) unless the directory lists the exact name, like
    upstream's USER.md and MEMORY.md. ``expected_absent_files`` are the files whose absence is
    a normal state for an editor (``isExpectedAbsentBootstrapFile``). ``extra_dirs`` are
    created on initialization and never loaded. ``extension_files`` have no upstream
    counterpart.
    """

    name: str
    load_order: tuple[str, ...]
    render_priorities: tuple[tuple[str, int], ...]
    required_files: tuple[str, ...]
    optional_files: tuple[str, ...]
    generated_files: tuple[str, ...]
    profile_files: tuple[str, ...]
    subagent_files: frozenset[str]
    cron_files: frozenset[str]
    skip_absent_files: frozenset[str]
    expected_absent_files: frozenset[str]
    extra_dirs: tuple[str, ...] = ()
    extension_files: frozenset[str] = frozenset()
    bootstrap_file: str = BOOTSTRAP_FILENAME
    memory_file: str = MEMORY_FILENAME

    def __post_init__(self) -> None:
        # Seeding writes root / name and mkdirs root / dirname: only plain
        # basenames keep those writes inside the workspace root.
        names: dict[str, tuple[str, ...]] = {
            "load_order": self.load_order,
            "required_files": self.required_files,
            "optional_files": self.optional_files,
            "generated_files": self.generated_files,
            "profile_files": self.profile_files,
            "subagent_files": tuple(self.subagent_files),
            "cron_files": tuple(self.cron_files),
            "skip_absent_files": tuple(self.skip_absent_files),
            "expected_absent_files": tuple(self.expected_absent_files),
            "extension_files": tuple(self.extension_files),
            "extra_dirs": self.extra_dirs,
            "bootstrap_file": (self.bootstrap_file,),
            "memory_file": (self.memory_file,),
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

    @property
    def seed_order(self) -> tuple[str, ...]:
        seeded = set(self.required_files) | set(self.optional_files)
        return tuple(name for name in self.load_order if name in seeded)

    def is_expected_absent(self, name: str) -> bool:
        """Port of ``isExpectedAbsentBootstrapFile`` (``src/agents/workspace.ts``)."""
        return name in self.expected_absent_files

    def can_read(self, relative_path: str) -> bool:
        """``createWorkspaceBootstrapFilePolicy().canRead`` without extra-file patterns.

        memory-core has no ``bootstrap-extra-files`` hook, so only the layout's own root files are
        readable bootstrap paths (``workspace-bootstrap-policy.ts``).
        """
        return _is_relative_policy_path(relative_path) and relative_path in self.load_order

    def can_write(self, relative_path: str) -> bool:
        """``createWorkspaceBootstrapFilePolicy().canWrite``: the generated owner documents."""
        return relative_path in self.generated_files


# CONTEXT_FILE_ORDER, src/agents/system-prompt-context-files.ts at v2026.9.6.
_OPENCLAW_RENDER_PRIORITIES = (
    ("agents.md", 10),
    ("soul.md", 20),
    ("identity.md", 30),
    ("user.md", 40),
    ("tools.md", 50),
    ("bootstrap.md", 60),
    ("memory.md", 70),
)

OPENCLAW_COMPAT_LAYOUT = WorkspaceLayout(
    name="openclaw",
    load_order=WORKSPACE_BOOTSTRAP_FILENAMES,
    render_priorities=_OPENCLAW_RENDER_PRIORITIES,
    required_files=(AGENTS_FILENAME,),
    optional_files=(SOUL_FILENAME, IDENTITY_FILENAME, USER_FILENAME),
    generated_files=GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES,
    profile_files=(SOUL_FILENAME, IDENTITY_FILENAME, USER_FILENAME),
    subagent_files=frozenset({AGENTS_FILENAME}),
    cron_files=frozenset({AGENTS_FILENAME, SOUL_FILENAME, IDENTITY_FILENAME, USER_FILENAME}),
    skip_absent_files=frozenset({USER_FILENAME, MEMORY_FILENAME}),
    expected_absent_files=frozenset(
        {SOUL_FILENAME, IDENTITY_FILENAME, USER_FILENAME, MEMORY_FILENAME}
    ),
)

MEMORY_CORE_WORKSPACE_LAYOUT = WorkspaceLayout(
    name="memory-core",
    load_order=(
        AGENTS_FILENAME,
        SOUL_FILENAME,
        IDENTITY_FILENAME,
        USER_FILENAME,
        PROACTIVE_PREFERENCES_FILENAME,
        BOOTSTRAP_FILENAME,
        MEMORY_FILENAME,
    ),
    render_priorities=(
        *_OPENCLAW_RENDER_PRIORITIES[:4],
        ("proactive_preferences.md", 45),
        *_OPENCLAW_RENDER_PRIORITIES[4:],
    ),
    required_files=(AGENTS_FILENAME,),
    optional_files=(
        SOUL_FILENAME,
        IDENTITY_FILENAME,
        USER_FILENAME,
        PROACTIVE_PREFERENCES_FILENAME,
    ),
    # Upstream's generated owner documents; the extension is host-owned.
    generated_files=GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES,
    # Upstream's onboarding profile set; PROACTIVE_PREFERENCES.md (an
    # extension) is not treated as setup-completion evidence.
    profile_files=(SOUL_FILENAME, IDENTITY_FILENAME, USER_FILENAME),
    subagent_files=frozenset({AGENTS_FILENAME}),
    # Extension choice: preferences follow USER.md into cron sessions.
    cron_files=frozenset(
        {
            AGENTS_FILENAME,
            SOUL_FILENAME,
            IDENTITY_FILENAME,
            USER_FILENAME,
            PROACTIVE_PREFERENCES_FILENAME,
        }
    ),
    # Extension: an absent PROACTIVE_PREFERENCES.md renders nothing, like an absent USER.md,
    # so a workspace without it gets exactly upstream's Project Context.
    skip_absent_files=frozenset({USER_FILENAME, PROACTIVE_PREFERENCES_FILENAME, MEMORY_FILENAME}),
    expected_absent_files=frozenset(
        {
            SOUL_FILENAME,
            IDENTITY_FILENAME,
            USER_FILENAME,
            PROACTIVE_PREFERENCES_FILENAME,
            MEMORY_FILENAME,
        }
    ),
    extra_dirs=("user", "workspace"),
    extension_files=frozenset({PROACTIVE_PREFERENCES_FILENAME}),
)

DEFAULT_WORKSPACE_LAYOUT = MEMORY_CORE_WORKSPACE_LAYOUT
