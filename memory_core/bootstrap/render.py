"""Project Context rendering for injected workspace files.

Port of OpenClaw ``src/agents/system-prompt.ts`` at pin 4c42815348:
``CONTEXT_FILE_ORDER`` / dynamic basenames (69-79), context-file sorting and
sanitizing (161-200), ``buildProjectContextSection`` (202-238),
``buildAgentBootstrapSystemContext`` / ``buildAgentBootstrapSystemPromptSections``
(301-356, prompt lines from ``src/agents/bootstrap-prompt.ts``), the
``## Workspace Files (injected)`` lines (1231-1232) and the blank-line
filtering of the prompt assembly (``lines.filter(Boolean).join("\\n")``,
1267 and 1356). The OpenClaw brand in the Workspace Files line goes through
:class:`~memory_core.runtime_identity.RuntimeIdentity`.
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
DYNAMIC_PROJECT_CONTEXT_HEADING = "# Dynamic Project Context"
PROJECT_CONTEXT_INTRO_LINE = "The following project context files have been loaded:"
PROJECT_CONTEXT_SOUL_LINE = (
    "SOUL.md: persona/tone. Follow it unless higher-priority instructions override."
)
PROJECT_CONTEXT_MEMORY_LINE = (
    "MEMORY.md: durable user preferences and behavior guidance. Keep following it "
    "throughout the session unless higher-priority instructions override."
)
DYNAMIC_PROJECT_CONTEXT_INTRO_LINE = (
    "The following frequently-changing project context files are kept below the cache "
    "boundary when possible:"
)
WORKSPACE_FILES_INJECTED_HEADING = "## Workspace Files (injected)"
BOOTSTRAP_PENDING_HEADING = "## Bootstrap Pending"
BOOTSTRAP_CONTEXT_NOTICE_HEADING = "## Bootstrap Context Notice"
WORKSPACE_BOOTSTRAP_COMMIT_REMINDER = "Reminder: commit your changes in this workspace after edits."
# Stripped from every context file before rendering (system-prompt.ts:80-81,166-171).
DEFAULT_HEARTBEAT_PROMPT_CONTEXT_BLOCK = (
    "Default heartbeat prompt:\n`Read HEARTBEAT.md if it exists (workspace context). Follow it "
    "strictly. Do not infer or repeat old tasks from prior chats. If nothing needs attention, "
    "reply HEARTBEAT_OK.`"
)

_BOOTSTRAP_FULL_FIXED_LINES = (
    "If this run can complete the BOOTSTRAP.md workflow, do so.",
    "If it cannot, explain the blocker briefly, continue with any bootstrap steps that are still "
    "possible here, and offer the simplest next step.",
    "Do not pretend bootstrap is complete when it is not.",
    "Do not use a generic first greeting or reply normally until after you have handled "
    "BOOTSTRAP.md.",
)
BOOTSTRAP_IN_CONTEXT_READ_LINE = (
    "BOOTSTRAP.md is included below in Project Context; follow it before replying normally."
)
BOOTSTRAP_READ_FILE_LINE = (
    "Please read BOOTSTRAP.md from the workspace and follow it before replying normally."
)
BOOTSTRAP_FIRST_REPLY_LINE = (
    "Your first user-visible reply for a bootstrap-pending workspace must follow BOOTSTRAP.md, "
    "not a generic greeting."
)
BOOTSTRAP_LIMITED_INTRO_LINE = (
    "Bootstrap is still pending for this workspace, but this run cannot safely complete the full "
    "BOOTSTRAP.md workflow here."
)
_BOOTSTRAP_LIMITED_FIXED_LINES = (
    "Do not claim bootstrap is complete, and do not use a generic first greeting.",
    "Briefly explain the limitation, continue only with any bootstrap steps that are still safely "
    "possible here, and offer the simplest next step.",
)
BOOTSTRAP_LIMITED_NEXT_STEP_LINE = (
    "Typical next steps include switching to a primary interactive run with normal workspace "
    "access or having the user complete the canonical BOOTSTRAP.md deletion afterward."
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
        "\n\n", content.replace(DEFAULT_HEARTBEAT_PROMPT_CONTEXT_BLOCK, "")
    )


def sort_context_files(
    files: Iterable[ContextFile], layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT
) -> list[ContextFile]:
    """Render order: layout priority, then basename, then path (ICU-like compare)."""
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
        return locale_compare(_normalize_context_path(left.path), _normalize_context_path(right.path))

    return sorted(files, key=cmp_to_key(compare))


@dataclass(frozen=True)
class PreparedContextFiles:
    ordered: tuple[ContextFile, ...]
    stable: tuple[ContextFile, ...]
    dynamic: tuple[ContextFile, ...]


def prepare_context_files(
    files: Iterable[ContextFile], layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT
) -> PreparedContextFiles:
    """Port of ``prepareContextFilesForPrompt`` (system-prompt.ts:191-200)."""
    ordered = sort_context_files(
        (file for file in files if isinstance(file.path, str) and js_trim(file.path)), layout
    )
    stable = tuple(f for f in ordered if not layout.is_dynamic(context_file_basename(f.path)))
    dynamic = tuple(f for f in ordered if layout.is_dynamic(context_file_basename(f.path)))
    return PreparedContextFiles(tuple(ordered), stable, dynamic)


def build_project_context_lines(
    files: Sequence[ContextFile], *, heading: str, dynamic: bool
) -> list[str]:
    """Port of ``buildProjectContextSection`` (system-prompt.ts:202-238)."""
    if not files:
        return []
    lines = [heading, ""]
    if dynamic:
        lines.extend([DYNAMIC_PROJECT_CONTEXT_INTRO_LINE, ""])
    else:
        lines.append(PROJECT_CONTEXT_INTRO_LINE)
        if any(context_file_basename(file.path) == "soul.md" for file in files):
            lines.append(PROJECT_CONTEXT_SOUL_LINE)
        if any(context_file_basename(file.path) == "memory.md" for file in files):
            lines.append(PROJECT_CONTEXT_MEMORY_LINE)
        lines.append("")
    for file in files:
        lines.extend([f"## {file.path}", "", sanitize_context_file_content(file.content), ""])
    return lines


def render_project_context(
    files: Iterable[ContextFile], layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT
) -> tuple[str, str]:
    """Render ``(stable_text, dynamic_text)`` for already-budgeted context files.

    The stable block is ``# Project Context``; dynamic files (HEARTBEAT.md)
    render below the prompt cache boundary as ``# Dynamic Project Context``, or
    as ``# Project Context`` when there is no stable file.
    """
    prepared = prepare_context_files(files, layout)
    stable = join_prompt_lines(
        build_project_context_lines(prepared.stable, heading=PROJECT_CONTEXT_HEADING, dynamic=False)
    )
    dynamic = join_prompt_lines(
        build_project_context_lines(
            prepared.dynamic,
            heading=DYNAMIC_PROJECT_CONTEXT_HEADING if prepared.stable else PROJECT_CONTEXT_HEADING,
            dynamic=True,
        )
    )
    return stable, dynamic


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
    dynamic_text: str = "",
) -> str:
    """Join the workspace parts of the system prompt in upstream order.

    ``buildAgentSystemPrompt`` (system-prompt.ts:1230-1278) emits the bootstrap
    sections, the ``## Workspace Files (injected)`` lines, the stable
    ``# Project Context`` block, the cache boundary and then the dynamic block,
    joined with ``lines.filter(Boolean).join("\\n")``. Sections memory-core does
    not render (output directives, reasoning format, ``## Silent Replies``) and
    the cache boundary marker are left out, so this is the upstream order and
    line format of the workspace parts only, not a whole system prompt.
    """
    return join_prompt_lines((bootstrap_text, workspace_files_text, stable_text, dynamic_text))


def build_bootstrap_system_context_lines(
    bootstrap_mode: BootstrapMode | None, *, bootstrap_in_context: bool
) -> list[str]:
    """Port of ``buildAgentBootstrapSystemContext`` (system-prompt.ts:301-331)."""
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
    """Port of ``buildAgentBootstrapSystemPromptSections`` (system-prompt.ts:333-356)."""
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
