"""Workspace bootstrap files: layout, seeding, loading, budget and rendering.

Ports the OpenClaw workspace bootstrap surface at the parity pin v2026.9.6 (see each
module's docstring for upstream anchors) and adds memory-core's default layout
(``MEMORY_CORE_WORKSPACE_LAYOUT``) with extensions that have no upstream reference.
``OPENCLAW_COMPAT_LAYOUT`` is upstream's map alone. ``migrate_tools_md`` retires a
TOOLS.md into AGENTS.md ``## Tools`` (``tools_md_migration_findings`` and
``WorkspaceContext.migration_findings`` report one that is still there);
``migrate_legacy_workspace_state`` imports upstream's retired JSON setup state.

Typical host flow, every turn (upstream runs ``ensureAgentWorkspace`` on each
reply, ``src/auto-reply/reply/get-reply.ts:418-425``, which is where a configured
workspace gets BOOTSTRAP.md reconciled away; ``build_workspace_context`` only
reads)::

    from memory_core.bootstrap import build_workspace_context, initialize_agent_workspace

    initialize_agent_workspace(root, templates=host_templates)
    context = build_workspace_context(root, session_kind="main")
    system_prompt = context.prompt_text  # above any prompt cache boundary
"""

from memory_core.bootstrap.budget import (
    DEFAULT_BOOTSTRAP_MAX_CHARS,
    DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
    USER_BOOTSTRAP_MAX_CHARS,
    BootstrapAnalyzedFile,
    BootstrapBudgetAnalysis,
    BootstrapContextFilesResult,
    BootstrapInjectionStat,
    BootstrapPromptWarning,
    ContextFile,
    TrimBootstrapResult,
    analyze_bootstrap_budget,
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
    BootstrapFileRead,
    ContextInjectionDecision,
    WorkspaceBootstrapFile,
    apply_context_mode_filter,
    filter_bootstrap_files,
    filter_bootstrap_files_for_session,
    filter_completed_bootstrap_file,
    filter_root_memory_bootstrap_files,
    load_workspace_bootstrap_files,
    read_workspace_bootstrap_file,
    resolve_bootstrap_mode,
    resolve_context_injection,
)
from memory_core.bootstrap.layout import (
    DEFAULT_WORKSPACE_LAYOUT,
    GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES,
    OPENCLAW_COMPAT_LAYOUT,
    PROACTIVE_PREFERENCES_FILENAME,
    MEMORY_CORE_WORKSPACE_LAYOUT,
    WORKSPACE_BOOTSTRAP_FILENAMES,
    WorkspaceLayout,
)
from memory_core.bootstrap.lifecycle import (
    LegacyWorkspaceStateMigration,
    WorkspaceBootstrapSeedConflictError,
    WorkspaceInitResult,
    WorkspaceSetupState,
    WorkspaceStateMigrationError,
    WorkspaceStateMigrationRequiredError,
    assert_no_unmigrated_workspace_state,
    bootstrap_status,
    has_workspace_user_content_evidence,
    initialize_agent_workspace,
    is_workspace_setup_completed,
    migrate_legacy_workspace_state,
    read_stored_workspace_setup_state,
    read_workspace_setup_state,
    strip_template_front_matter,
    workspace_profile_looks_configured,
)
from memory_core.bootstrap.tools_md import (
    ToolsMdMigrationFinding,
    ToolsMdMigrationResult,
    merge_tools_md_into_agents_md,
    migrate_tools_md,
    should_merge_tools_md,
    tools_md_migration_findings,
)
from memory_core.bootstrap.render import (
    build_bootstrap_prompt_section_lines,
    render_bootstrap_prompt_sections,
    render_project_context,
    render_workspace_files_injected,
    render_workspace_prompt,
    sort_context_files,
)
from memory_core.bootstrap.startup import (
    BARE_SESSION_RESET_PROMPT_BASE,
    BareSessionResetPromptState,
    append_cron_style_current_time_line,
    build_bare_session_reset_prompt,
    build_startup_context,
    format_session_reset_transcript_prompt,
    resolve_bare_session_reset_prompt_state,
    should_apply_startup_context,
)
from memory_core.bootstrap.classification import (
    UnsupportedBootstrapMemoryRuntimeError,
    classify_workspace_memory_paths,
)

__all__ = [
    "BARE_SESSION_RESET_PROMPT_BASE",
    "BareSessionResetPromptState",
    "DEFAULT_BOOTSTRAP_MAX_CHARS",
    "DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS",
    "USER_BOOTSTRAP_MAX_CHARS",
    "DEFAULT_WORKSPACE_LAYOUT",
    "GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES",
    "MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES",
    "OPENCLAW_COMPAT_LAYOUT",
    "PROACTIVE_PREFERENCES_FILENAME",
    "MEMORY_CORE_WORKSPACE_LAYOUT",
    "WORKSPACE_BOOTSTRAP_FILENAMES",
    "BootstrapAnalyzedFile",
    "BootstrapBudgetAnalysis",
    "BootstrapContextFilesResult",
    "BootstrapFileRead",
    "BootstrapInjectionStat",
    "BootstrapPromptWarning",
    "ContextFile",
    "ContextInjectionDecision",
    "LegacyWorkspaceStateMigration",
    "ToolsMdMigrationFinding",
    "ToolsMdMigrationResult",
    "TrimBootstrapResult",
    "WorkspaceBootstrapFile",
    "WorkspaceBootstrapSeedConflictError",
    "WorkspaceContext",
    "WorkspaceInitResult",
    "WorkspaceLayout",
    "WorkspaceSetupState",
    "WorkspaceStateMigrationError",
    "WorkspaceStateMigrationRequiredError",
    "UnsupportedBootstrapMemoryRuntimeError",
    "analyze_bootstrap_budget",
    "append_cron_style_current_time_line",
    "apply_context_mode_filter",
    "assert_no_unmigrated_workspace_state",
    "bootstrap_status",
    "build_bare_session_reset_prompt",
    "build_bootstrap_context_files",
    "build_bootstrap_injection_stats",
    "build_bootstrap_prompt_section_lines",
    "build_bootstrap_prompt_warning",
    "build_bootstrap_prompt_warning_notice",
    "build_startup_context",
    "build_workspace_context",
    "clamp_to_budget",
    "classify_workspace_memory_paths",
    "filter_bootstrap_files",
    "filter_bootstrap_files_for_session",
    "filter_completed_bootstrap_file",
    "filter_root_memory_bootstrap_files",
    "format_bootstrap_truncation_warning_lines",
    "format_session_reset_transcript_prompt",
    "has_workspace_user_content_evidence",
    "initialize_agent_workspace",
    "is_workspace_setup_completed",
    "load_workspace_bootstrap_files",
    "merge_tools_md_into_agents_md",
    "migrate_legacy_workspace_state",
    "migrate_tools_md",
    "read_workspace_bootstrap_file",
    "read_stored_workspace_setup_state",
    "read_workspace_setup_state",
    "render_bootstrap_prompt_sections",
    "render_project_context",
    "render_workspace_files_injected",
    "render_workspace_prompt",
    "resolve_bare_session_reset_prompt_state",
    "resolve_bootstrap_char_limit",
    "resolve_bootstrap_mode",
    "resolve_context_injection",
    "should_apply_startup_context",
    "should_merge_tools_md",
    "sort_context_files",
    "strip_template_front_matter",
    "tools_md_migration_findings",
    "trim_bootstrap_content",
    "workspace_profile_looks_configured",
]
