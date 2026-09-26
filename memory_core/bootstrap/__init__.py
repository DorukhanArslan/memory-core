"""Workspace bootstrap files: layout, seeding, loading, budget and rendering.

Ports the OpenClaw workspace bootstrap surface at pin 4c42815348 (see each
module's docstring for upstream anchors) and adds the memory-core layout as the
default. memory-core additions are an extension (provisional: no upstream reference).

Typical host flow, every turn (upstream runs ``ensureAgentWorkspace`` on each
reply, ``src/auto-reply/reply/get-reply.ts:418-425``, which is where a configured
workspace gets BOOTSTRAP.md reconciled away; ``build_workspace_context`` only
reads)::

    from memory_core.bootstrap import build_workspace_context, initialize_agent_workspace

    initialize_agent_workspace(root, templates=host_templates)
    context = build_workspace_context(root, session_kind="main")
    system_prompt = context.prompt_text  # no prompt cache boundary
    # With a cache boundary: bootstrap_text, workspace_files_text and
    # stable_text above it (render_workspace_prompt), dynamic_text below it.
"""

from memory_core.bootstrap.budget import (
    DEFAULT_BOOTSTRAP_MAX_CHARS,
    DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
    BootstrapAnalyzedFile,
    BootstrapBudgetAnalysis,
    BootstrapContextFilesResult,
    BootstrapInjectionStat,
    BootstrapPromptWarning,
    ContextFile,
    TrimBootstrapResult,
    analyze_bootstrap_budget,
    append_bootstrap_prompt_warning,
    build_bootstrap_context_files,
    build_bootstrap_injection_stats,
    build_bootstrap_prompt_warning,
    build_bootstrap_prompt_warning_notice,
    clamp_to_budget,
    format_bootstrap_truncation_warning_lines,
    resolve_bootstrap_char_limit,
    trim_bootstrap_content,
)
from memory_core.bootstrap.context import WorkspaceContext, build_workspace_context
from memory_core.bootstrap.files import (
    MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES,
    ContextInjectionDecision,
    WorkspaceBootstrapFile,
    apply_context_mode_filter,
    filter_bootstrap_files,
    filter_bootstrap_files_for_session,
    filter_completed_bootstrap_file,
    filter_heartbeat_bootstrap_file,
    load_workspace_bootstrap_files,
    resolve_bootstrap_mode,
    resolve_context_injection,
)
from memory_core.bootstrap.layout import (
    DEFAULT_WORKSPACE_LAYOUT,
    MEMORY_CORE_WORKSPACE_LAYOUT,
    OPENCLAW_PIN_LAYOUT,
    PROACTIVE_PREFERENCES_FILENAME,
    WorkspaceLayout,
)
from memory_core.bootstrap.lifecycle import (
    WorkspaceInitResult,
    WorkspaceSetupState,
    bootstrap_status,
    has_workspace_user_content_evidence,
    initialize_agent_workspace,
    is_workspace_setup_completed,
    read_workspace_setup_state,
    strip_template_front_matter,
    workspace_profile_looks_configured,
)
from memory_core.bootstrap.render import (
    build_bootstrap_prompt_section_lines,
    render_bootstrap_prompt_sections,
    render_project_context,
    render_workspace_files_injected,
    render_workspace_prompt,
    sort_context_files,
)
from memory_core.bootstrap.startup import build_startup_context, should_apply_startup_context

__all__ = [
    "DEFAULT_BOOTSTRAP_MAX_CHARS",
    "DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS",
    "DEFAULT_WORKSPACE_LAYOUT",
    "MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES",
    "MEMORY_CORE_WORKSPACE_LAYOUT",
    "OPENCLAW_PIN_LAYOUT",
    "PROACTIVE_PREFERENCES_FILENAME",
    "BootstrapAnalyzedFile",
    "BootstrapBudgetAnalysis",
    "BootstrapContextFilesResult",
    "BootstrapInjectionStat",
    "BootstrapPromptWarning",
    "ContextFile",
    "ContextInjectionDecision",
    "TrimBootstrapResult",
    "WorkspaceBootstrapFile",
    "WorkspaceContext",
    "WorkspaceInitResult",
    "WorkspaceLayout",
    "WorkspaceSetupState",
    "analyze_bootstrap_budget",
    "append_bootstrap_prompt_warning",
    "apply_context_mode_filter",
    "bootstrap_status",
    "build_bootstrap_context_files",
    "build_bootstrap_injection_stats",
    "build_bootstrap_prompt_section_lines",
    "build_bootstrap_prompt_warning",
    "build_bootstrap_prompt_warning_notice",
    "build_startup_context",
    "build_workspace_context",
    "clamp_to_budget",
    "filter_bootstrap_files",
    "filter_bootstrap_files_for_session",
    "filter_completed_bootstrap_file",
    "filter_heartbeat_bootstrap_file",
    "format_bootstrap_truncation_warning_lines",
    "has_workspace_user_content_evidence",
    "initialize_agent_workspace",
    "is_workspace_setup_completed",
    "load_workspace_bootstrap_files",
    "read_workspace_setup_state",
    "render_bootstrap_prompt_sections",
    "render_project_context",
    "render_workspace_files_injected",
    "render_workspace_prompt",
    "resolve_bootstrap_char_limit",
    "resolve_bootstrap_mode",
    "resolve_context_injection",
    "should_apply_startup_context",
    "sort_context_files",
    "strip_template_front_matter",
    "trim_bootstrap_content",
    "workspace_profile_looks_configured",
]
