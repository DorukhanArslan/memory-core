"""Workspace bootstrap files: layout, loading, filtering and budget.

Ports the OpenClaw workspace bootstrap surface at pin 4c42815348 (see each
module's docstring for upstream anchors) and adds the memory-core layout as the
default. memory-core additions are an extension (provisional: no upstream reference).
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
    trim_bootstrap_content,
)
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
    "WorkspaceLayout",
    "analyze_bootstrap_budget",
    "append_bootstrap_prompt_warning",
    "apply_context_mode_filter",
    "build_bootstrap_context_files",
    "build_bootstrap_injection_stats",
    "build_bootstrap_prompt_warning",
    "build_bootstrap_prompt_warning_notice",
    "clamp_to_budget",
    "filter_bootstrap_files",
    "filter_bootstrap_files_for_session",
    "filter_completed_bootstrap_file",
    "filter_heartbeat_bootstrap_file",
    "format_bootstrap_truncation_warning_lines",
    "load_workspace_bootstrap_files",
    "resolve_bootstrap_mode",
    "resolve_context_injection",
    "trim_bootstrap_content",
]
