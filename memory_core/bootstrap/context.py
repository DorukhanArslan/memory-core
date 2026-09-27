"""One-call workspace context assembly for a host turn.

Mirrors the bootstrap part of OpenClaw's embedded attempt at the parity pin v2026.9.6
(``src/agents/embedded-agent-runner/run/attempt-bootstrap-prepare.ts``,
``src/agents/bootstrap-routing.ts``): resolve the run's bootstrap files, decide
contextInjection, apply the per-file/total budget, drop BOOTSTRAP.md unless the bootstrap mode
is ``full``, build the truncation report, and render Project Context. Everything renders above
the host's prompt cache boundary (the tag has no dynamic Project Context).

Deviation (transport boundary): the rendered files and texts are passed
through ``String.prototype.toWellFormed`` semantics, so a surrogate pair that
upstream's plain head/tail slice splits reaches the host as U+FFFD instead of
a lone surrogate. The UTF-16 lengths and the budget analysis are unchanged;
the lower-level :func:`~memory_core.bootstrap.budget.build_bootstrap_context_files`
stays byte-exact.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass

from memory_core.bootstrap._js import js_to_well_formed, js_trim
from memory_core.bootstrap.budget import (
    DEFAULT_BOOTSTRAP_MAX_CHARS,
    DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
    BootstrapBudgetAnalysis,
    BootstrapPromptWarning,
    BootstrapPromptWarningMode,
    ContextFile,
    analyze_bootstrap_budget,
    build_bootstrap_context_files,
    build_bootstrap_injection_stats,
    build_bootstrap_prompt_warning,
    build_bootstrap_prompt_warning_notice,
    resolve_bootstrap_char_limit,
)
from memory_core.bootstrap.files import (
    BootstrapContextMode,
    BootstrapContextRunKind,
    BootstrapMode,
    ContextInjectionMode,
    SessionKind,
    WorkspaceBootstrapFile,
    display_path,
    filter_bootstrap_files,
    load_workspace_bootstrap_files,
    resolve_bootstrap_mode,
    resolve_context_injection,
)
from memory_core.bootstrap.layout import DEFAULT_WORKSPACE_LAYOUT, WorkspaceLayout
from memory_core.bootstrap.lifecycle import (
    BootstrapStatus,
    bootstrap_status as resolve_bootstrap_status,
    is_workspace_setup_completed,
)
from memory_core.bootstrap.render import (
    WORKSPACE_BOOTSTRAP_COMMIT_REMINDER,
    is_bootstrap_context_path,
    render_bootstrap_prompt_sections,
    render_project_context,
    render_workspace_files_injected,
    render_workspace_prompt,
    sort_context_files,
)
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity


@dataclass(frozen=True)
class WorkspaceContext:
    """Rendered workspace context for one turn.

    ``files`` are the injected context files in render order (paths in the
    requested ``path_style``); ``bootstrap_files`` are the filtered raw files
    before budgeting. ``warnings`` are the warnings of the
    ``resolveBootstrapFilesForRun`` path dedupe and of
    ``buildBootstrapContextFiles``, in that order; ``truncation_warning_lines`` and
    ``truncation_notice`` follow ``bootstrap-budget.ts``. ``bootstrap_text``
    holds ``## Bootstrap Pending`` and ``## Bootstrap Context Notice`` when
    they apply. ``record_completed_bootstrap_turn`` asks the host to remember a
    full bootstrap turn for ``context_injection="continuation-skip"``.
    """

    stable_text: str
    workspace_files_text: str
    bootstrap_text: str
    files: tuple[ContextFile, ...]
    bootstrap_files: tuple[WorkspaceBootstrapFile, ...]
    warnings: tuple[str, ...]
    truncated: bool
    truncation_warning_lines: tuple[str, ...]
    truncation_notice: str | None
    prompt_warning: BootstrapPromptWarning
    analysis: BootstrapBudgetAnalysis
    bootstrap_mode: BootstrapMode
    bootstrap_status: BootstrapStatus
    injection_skipped: bool
    record_completed_bootstrap_turn: bool
    workspace_notes: tuple[str, ...]

    @property
    def prompt_text(self) -> str:
        """Bootstrap sections, Workspace Files lines and Project Context.

        One string in upstream order (see
        :func:`~memory_core.bootstrap.render.render_workspace_prompt`); hosts with a prompt cache
        place all of it above the boundary, as upstream does.
        """
        return render_workspace_prompt(
            bootstrap_text=self.bootstrap_text,
            workspace_files_text=self.workspace_files_text,
            stable_text=self.stable_text,
        )


def _default_run_kind(session_kind: SessionKind | None) -> BootstrapContextRunKind:
    if session_kind == "heartbeat":
        return "heartbeat"
    if session_kind == "cron":
        return "cron"
    return "default"


def build_workspace_context(
    root: str | os.PathLike[str],
    *,
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
    session_kind: SessionKind = "main",
    run_kind: BootstrapContextRunKind | None = None,
    context_mode: BootstrapContextMode = "full",
    exclude_files: Iterable[str] = (),
    context_injection: ContextInjectionMode = "always",
    has_completed_bootstrap_turn: bool = False,
    bootstrap_mode: BootstrapMode | None = None,
    is_interactive_user_facing: bool = True,
    has_bootstrap_file_access: bool = True,
    is_canonical_workspace: bool = True,
    max_chars: int | None = DEFAULT_BOOTSTRAP_MAX_CHARS,
    total_max_chars: int | None = DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
    truncation_warning_mode: BootstrapPromptWarningMode = "always",
    seen_truncation_signatures: Iterable[str] = (),
    path_style: str = "absolute",
    identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> WorkspaceContext:
    """Load, filter, budget and render a workspace's bootstrap files.

    ``run_kind`` defaults from ``session_kind`` (``heartbeat`` -> heartbeat run,
    ``cron`` -> cron run, otherwise default). ``bootstrap_mode`` defaults to
    upstream's ``resolveBootstrapMode`` (``src/agents/bootstrap-mode.ts``) as
    the attempt routes it (``src/agents/bootstrap-routing.ts``): ``none``
    unless the workspace is pending on a primary interactive run, then
    ``limited`` without file access or for a non-canonical workspace, else
    ``full``. ``has_bootstrap_file_access`` is upstream's
    ``hasBootstrapFileAccess`` (``attempt-bootstrap-prepare.ts``: the run's tools include
    ``read``); pass ``False`` when the model cannot read workspace files.
    Non-empty BOOTSTRAP.md content counts as pending and as file access, like
    upstream's hook-content rule. ``is_canonical_workspace`` is ``False`` when
    the run works in a different directory than the workspace root (upstream:
    ``effectiveWorkspace !== resolvedWorkspace``). ``path_style="absolute"``
    renders upstream's absolute paths, ``"relative"`` renders root-relative
    POSIX paths. ``max_chars`` / ``total_max_chars`` are resolved like
    upstream's config (``resolveBootstrapMaxChars``): ``None`` or a value
    ``<= 0`` falls back to 20,000 / 60,000, others are floored.

    ``exclude_files`` names basenames the host keeps out of this turn (host
    policy, no upstream equivalent). They are dropped after the session and run
    filters and before budgeting, so they consume no budget and raise no
    truncation warning; ``memory_core.live`` uses it to keep the agent's MEMORY.md
    out of subject prompts.
    """
    max_chars = resolve_bootstrap_char_limit(max_chars, DEFAULT_BOOTSTRAP_MAX_CHARS)
    total_max_chars = resolve_bootstrap_char_limit(
        total_max_chars, DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS
    )
    effective_run_kind = run_kind or _default_run_kind(session_kind)
    # resolveWorkspaceBootstrapStatus fails closed on upstream's retired JSON state
    # (WorkspaceStateMigrationRequiredError), like the upstream run's bootstrap routing.
    status = resolve_bootstrap_status(root, layout)
    setup_completed = is_workspace_setup_completed(root)
    loaded = load_workspace_bootstrap_files(root, layout)
    filter_warnings: list[str] = []
    filtered = filter_bootstrap_files(
        loaded,
        root=root,
        layout=layout,
        session_kind=session_kind,
        setup_completed=setup_completed,
        context_mode=context_mode,
        warn=filter_warnings.append,
    )
    excluded = frozenset((exclude_files,) if isinstance(exclude_files, str) else exclude_files)
    if excluded:
        filtered = [file for file in filtered if file.name not in excluded]
    if bootstrap_mode is None:
        hook_like_bootstrap = any(
            file.name == layout.bootstrap_file
            and not file.missing
            and isinstance(file.content, str)
            and js_trim(file.content)
            for file in filtered
        )
        # resolveWorkspaceBootstrapRouting (src/agents/bootstrap-routing.ts):
        # BOOTSTRAP.md content counts as both pending bootstrap and file access.
        bootstrap_mode = resolve_bootstrap_mode(
            bootstrap_pending=status == "pending" or hook_like_bootstrap,
            run_kind=effective_run_kind,
            is_interactive_user_facing=is_interactive_user_facing,
            is_primary_run=session_kind != "subagent",
            is_canonical_workspace=is_canonical_workspace,
            has_bootstrap_file_access=has_bootstrap_file_access or hook_like_bootstrap,
        )
    decision = resolve_context_injection(
        context_injection,
        bootstrap_mode=bootstrap_mode,
        run_kind=effective_run_kind,
        context_mode=context_mode,
        has_completed_bootstrap_turn=has_completed_bootstrap_turn,
    )
    bootstrap_files = [] if decision.skip_injection else filtered
    budgeted = build_bootstrap_context_files(
        bootstrap_files, max_chars=max_chars, total_max_chars=total_max_chars
    )
    include_bootstrap = bootstrap_mode == "full"
    context_files = [
        file
        for file in budgeted.files
        if include_bootstrap or not is_bootstrap_context_path(file.path)
    ]
    stats_files = [
        file for file in bootstrap_files if include_bootstrap or file.name != layout.bootstrap_file
    ]
    analysis = analyze_bootstrap_budget(
        build_bootstrap_injection_stats(stats_files, context_files),
        bootstrap_max_chars=max_chars,
        bootstrap_total_max_chars=total_max_chars,
    )
    prompt_warning = build_bootstrap_prompt_warning(
        analysis,
        mode=truncation_warning_mode,
        seen_signatures=seen_truncation_signatures,
        identity=identity,
    )
    notice = build_bootstrap_prompt_warning_notice(prompt_warning.lines)
    notes = (
        (WORKSPACE_BOOTSTRAP_COMMIT_REMINDER,)
        if any(file.name == layout.bootstrap_file and not file.missing for file in bootstrap_files)
        else ()
    )
    # Transport boundary (deviation): budgeting above is byte-exact and may leave
    # a lone surrogate where a head/tail slice split a pair (bootstrap.ts:356-357).
    # Node writes such a string as UTF-8 with U+FFFD; Python cannot encode it at
    # all, so every host-facing string is made well-formed here.
    shown_files = [
        ContextFile(
            js_to_well_formed(display_path(file.path, root, path_style)),
            js_to_well_formed(file.content),
        )
        for file in context_files
    ]
    stable_text = render_project_context(shown_files, layout)
    return WorkspaceContext(
        stable_text=stable_text,
        workspace_files_text=render_workspace_files_injected(identity),
        bootstrap_text=render_bootstrap_prompt_sections(
            bootstrap_mode, truncation_notice=notice, context_files=shown_files, layout=layout
        ),
        files=tuple(sort_context_files(shown_files, layout)),
        bootstrap_files=tuple(bootstrap_files),
        warnings=(*filter_warnings, *budgeted.warnings),
        truncated=analysis.has_truncation,
        truncation_warning_lines=prompt_warning.lines,
        truncation_notice=notice,
        prompt_warning=prompt_warning,
        analysis=analysis,
        bootstrap_mode=bootstrap_mode,
        bootstrap_status=status,
        injection_skipped=decision.skip_injection,
        record_completed_bootstrap_turn=decision.record_completed_bootstrap_turn,
        workspace_notes=notes,
    )
