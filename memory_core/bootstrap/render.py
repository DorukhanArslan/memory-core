"""Project Context rendering for injected workspace files.

Port of OpenClaw at the parity pin v2026.9.6:

- ``src/agents/system-prompt-context-files.ts``: ``CONTEXT_FILE_ORDER`` (the layout's render
  priorities), ``prepareContextFilesForPrompt`` (sort by priority, basename, then path; two
  ``USER.md`` files keep loader order), the heartbeat-prompt block sanitizer and
  ``buildProjectContextSection`` (``Loaded project context:`` plus the SOUL.md, MEMORY.md and
  USER.md guidance lines);
- ``src/agents/system-prompt.ts``: ``buildAgentBootstrapSystemContext`` /
  ``buildAgentBootstrapSystemPromptSections`` with the prompt lines of
  ``src/agents/bootstrap-prompt.ts``, the ``## Workspace Files (injected)`` lines and the
  blank-line filtering of the stable prefix (``lines.filter(Boolean).join("\\n")``,
  system-prompt.ts:1143).

The tag has no dynamic Project Context: everything renders in the stable block right before
the prompt cache boundary (the pin's ``# Dynamic Project Context`` for HEARTBEAT.md went with
the heartbeat monitor scratch). The OpenClaw brand in the Workspace Files line goes through
:class:`~memory_core.runtime_identity.RuntimeIdentity`.

Not ported: the authenticated personal ``users/<profile-id>/USER.md`` guidance line (no
personal USER loader in memory-core) and the per-project curated MEMORY.md entry filter
(``filterProjectScopedCuratedContextFiles``, ``src/agents/project-memory-bootstrap.ts``,
d41a56fca1f #115438; stage-2 area "short-term recall and promotion"): with no active project
keys upstream drops MEMORY.md entries annotated with a project, memory-core renders them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cmp_to_key

from memory_core.bootstrap._js import js_iu_keyword_pattern, js_trim, locale_compare
from memory_core.bootstrap.budget import ContextFile
from memory_core.bootstrap.files import BootstrapMode
from memory_core.bootstrap.layout import DEFAULT_WORKSPACE_LAYOUT, WorkspaceLayout
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity

PROJECT_CONTEXT_HEADING = "# Project Context"
PROJECT_CONTEXT_INTRO_LINE = "Loaded project context:"
PROJECT_CONTEXT_SOUL_LINE = (
    "SOUL.md: persona/tone. Follow it unless higher-priority instructions override."
)
PROJECT_CONTEXT_MEMORY_LINE = (
    "MEMORY.md: durable non-profile facts and decisions; use when relevant unless "
    "higher-priority instructions override."
)
PROJECT_CONTEXT_USER_LINE = (
    "USER.md: durable user preferences and profile directives; follow unless higher-priority "
    "instructions override."
)
WORKSPACE_FILES_INJECTED_HEADING = "## Workspace Files (injected)"
BOOTSTRAP_PENDING_HEADING = "## Bootstrap Pending"
BOOTSTRAP_CONTEXT_NOTICE_HEADING = "## Bootstrap Context Notice"
WORKSPACE_BOOTSTRAP_COMMIT_REMINDER = "Reminder: commit your changes in this workspace after edits."
# Stripped from every context file before rendering: the legacy and the monitor-scratch
# default heartbeat prompts (system-prompt-context-files.ts DEFAULT_HEARTBEAT_PROMPT_CONTEXT_BLOCK).
DEFAULT_HEARTBEAT_PROMPT_CONTEXT_BLOCK_RE = re.compile(
    r"Default heartbeat prompt:\r?\n`(?:Read HEARTBEAT\.md if it exists|Follow the heartbeat "
    r"monitor scratch context when provided\.)[^`\r\n]*HEARTBEAT_OK\.`"
)

# src/agents/bootstrap-prompt.ts buildFullBootstrapPromptLines / buildLimitedBootstrapPromptLines.
_BOOTSTRAP_FULL_FIXED_LINES = (
    "Can finish BOOTSTRAP.md here: do it.",
    "Cannot: brief blocker, safe possible steps, simplest next step.",
    "Never claim completion early. No generic greeting/normal reply before BOOTSTRAP.md handling.",
)
_BOOTSTRAP_LIMITED_FIXED_LINES = (
    "Never claim complete; no generic first greeting.",
    "Brief limitation; only safe possible steps; simplest next step.",
)
# src/agents/system-prompt.ts buildAgentBootstrapSystemContext.
BOOTSTRAP_IN_CONTEXT_READ_LINE = "BOOTSTRAP.md below; follow before normal reply."
BOOTSTRAP_READ_FILE_LINE = "Read workspace BOOTSTRAP.md; follow before normal reply."
BOOTSTRAP_FIRST_REPLY_LINE = "First visible reply must follow BOOTSTRAP.md; no generic greeting."
BOOTSTRAP_LIMITED_INTRO_LINE = (
    "Bootstrap pending; this run cannot safely finish full BOOTSTRAP.md."
)
BOOTSTRAP_LIMITED_NEXT_STEP_LINE = (
    "Next: primary interactive run with normal workspace access, or user deletes canonical "
    "BOOTSTRAP.md after completion."
)

_BOOTSTRAP_PATH_RE = re.compile(
    "(?:^|[\\\\/])" + js_iu_keyword_pattern("BOOTSTRAP.md") + r"\Z"
)
_TRIPLE_NEWLINE_RE = re.compile(r"\n{3,}")


def join_prompt_lines(lines: Iterable[str]) -> str:
    """``lines.filter(Boolean).join("\\n")``: empty entries vanish."""
    return "\n".join(line for line in lines if line)


def _normalize_context_path(path: str) -> str:
    return js_trim(path).replace("\\", "/")


def context_file_basename(path: str) -> str:
    normalized = _normalize_context_path(path)
    return js_trim(normalized.split("/")[-1]).lower()


def is_bootstrap_context_path(path: str) -> bool:
    return _BOOTSTRAP_PATH_RE.search(js_trim(path)) is not None


def sanitize_context_file_content(content: str) -> str:
    return _TRIPLE_NEWLINE_RE.sub(
        "\n\n", DEFAULT_HEARTBEAT_PROMPT_CONTEXT_BLOCK_RE.sub("", content)
    )


def sort_context_files(
    files: Iterable[ContextFile], layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT
) -> list[ContextFile]:
    """Render order: layout priority, then basename, then path (ICU-like compare).

    Two files with the basename ``user.md`` keep their given order (upstream keeps the shared
    USER.md before a personal overlay, ``prepareContextFilesForPrompt``); the sort is stable.
    """
    unknown = 2**53 - 1  # Number.MAX_SAFE_INTEGER

    def compare(left: ContextFile, right: ContextFile) -> int:
        left_base = context_file_basename(left.path)
        right_base = context_file_basename(right.path)
        left_order = layout.render_priority(left_base)
        right_order = layout.render_priority(right_base)
        left_value = unknown if left_order is None else left_order
        right_value = unknown if right_order is None else right_order
        if left_value != right_value:
            return left_value - right_value
        if left_base != right_base:
            return locale_compare(left_base, right_base)
        if left_base == "user.md":
            return 0
        return locale_compare(_normalize_context_path(left.path), _normalize_context_path(right.path))

    return sorted(files, key=cmp_to_key(compare))


@dataclass(frozen=True)
class PreparedContextFiles:
    ordered: tuple[ContextFile, ...]


def prepare_context_files(
    files: Iterable[ContextFile], layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT
) -> PreparedContextFiles:
    """Drop blank paths (system-prompt.ts) and sort (``prepareContextFilesForPrompt``)."""
    ordered = sort_context_files(
        (file for file in files if isinstance(file.path, str) and js_trim(file.path)), layout
    )
    return PreparedContextFiles(tuple(ordered))


def build_project_context_lines(files: Sequence[ContextFile]) -> list[str]:
    """Port of ``buildProjectContextSection`` (system-prompt-context-files.ts)."""
    if not files:
        return []
    basenames = {context_file_basename(file.path) for file in files}
    lines = [PROJECT_CONTEXT_HEADING, "", PROJECT_CONTEXT_INTRO_LINE]
    if "soul.md" in basenames:
        lines.append(PROJECT_CONTEXT_SOUL_LINE)
    if "memory.md" in basenames:
        lines.append(PROJECT_CONTEXT_MEMORY_LINE)
    if "user.md" in basenames:
        lines.append(PROJECT_CONTEXT_USER_LINE)
    lines.append("")
    for file in files:
        lines.extend([f"## {file.path}", "", sanitize_context_file_content(file.content), ""])
    return lines


def render_project_context(
    files: Iterable[ContextFile], layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT
) -> str:
    """Render ``# Project Context`` for already-budgeted context files ("" without files)."""
    prepared = prepare_context_files(files, layout)
    return join_prompt_lines(build_project_context_lines(prepared.ordered))


def workspace_files_injected_lines(
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> tuple[str, str]:
    """``## Workspace Files (injected)`` and its intro line (brand via RuntimeIdentity)."""
    return (WORKSPACE_FILES_INJECTED_HEADING, identity.workspace_files_injected_line)


def render_workspace_files_injected(identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY) -> str:
    return "\n".join(workspace_files_injected_lines(identity))


def render_workspace_prompt(
    *,
    bootstrap_text: str = "",
    workspace_files_text: str = "",
    stable_text: str = "",
) -> str:
    """Join the workspace parts of the system prompt in upstream order.

    ``buildAgentSystemPrompt`` (system-prompt.ts) emits the bootstrap sections, the
    ``## Workspace Files (injected)`` lines and ``# Project Context`` right before the cache
    boundary, joined with ``lines.filter(Boolean).join("\\n")``. Sections memory-core does not
    render (reasoning format, output directives, ``## Silent Replies``) and the cache boundary
    marker are left out, so this is the upstream order and line format of the workspace parts
    only, not a whole system prompt.
    """
    return join_prompt_lines((bootstrap_text, workspace_files_text, stable_text))


def build_bootstrap_system_context_lines(
    bootstrap_mode: BootstrapMode | None, *, bootstrap_in_context: bool
) -> list[str]:
    """Port of ``buildAgentBootstrapSystemContext`` (system-prompt.ts)."""
    if not bootstrap_mode or bootstrap_mode == "none":
        return []
    if bootstrap_mode == "limited":
        return [
            BOOTSTRAP_PENDING_HEADING,
            BOOTSTRAP_LIMITED_INTRO_LINE,
            *_BOOTSTRAP_LIMITED_FIXED_LINES,
            BOOTSTRAP_LIMITED_NEXT_STEP_LINE,
            "",
        ]
    return [
        BOOTSTRAP_PENDING_HEADING,
        BOOTSTRAP_IN_CONTEXT_READ_LINE if bootstrap_in_context else BOOTSTRAP_READ_FILE_LINE,
        *_BOOTSTRAP_FULL_FIXED_LINES,
        BOOTSTRAP_FIRST_REPLY_LINE,
        "",
    ]


def build_bootstrap_prompt_section_lines(
    bootstrap_mode: BootstrapMode | None,
    *,
    truncation_notice: str | None = None,
    context_files: Iterable[ContextFile] = (),
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
) -> list[str]:
    """Port of ``buildAgentBootstrapSystemPromptSections`` (system-prompt.ts)."""
    in_context = bootstrap_mode == "full" and any(
        is_bootstrap_context_path(file.path) for file in sort_context_files(context_files, layout)
    )
    lines = build_bootstrap_system_context_lines(bootstrap_mode, bootstrap_in_context=in_context)
    notice = js_trim(truncation_notice) if truncation_notice else ""
    if notice:
        lines.extend([BOOTSTRAP_CONTEXT_NOTICE_HEADING, notice, ""])
    return lines


def render_bootstrap_prompt_sections(
    bootstrap_mode: BootstrapMode | None,
    *,
    truncation_notice: str | None = None,
    context_files: Iterable[ContextFile] = (),
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
) -> str:
    return join_prompt_lines(
        build_bootstrap_prompt_section_lines(
            bootstrap_mode,
            truncation_notice=truncation_notice,
            context_files=context_files,
            layout=layout,
        )
    )
