"""Loading and per-run filtering of workspace bootstrap files.

Ports, at OpenClaw pin 4c42815348:

- ``loadWorkspaceBootstrapFiles`` (``src/agents/workspace.ts:1039-1104``) and the
  guarded read (``:68-104``: workspace-root boundary, 2 MiB cap);
- ``filterBootstrapFilesForSession`` (``:1106-1130``), with the session kind
  supplied by the host instead of parsed from an OpenClaw session key;
- the run pipeline of ``resolveBootstrapFilesForRun``
  (``src/agents/bootstrap-files.ts:201-339``): completed-BOOTSTRAP filter,
  lightweight context mode, heartbeat exclusion, path dedupe;
- ``resolveBootstrapMode`` (``src/agents/bootstrap-mode.ts:11-33``) and the
  contextInjection decision of ``resolveAttemptBootstrapContext``
  (``src/agents/embedded-agent-runner/run/attempt.context-engine-helpers.ts:34-75``).

Not ported: the ``agent:bootstrap`` hook and ``bootstrap-extra-files``
globs, the per-session snapshot cache, and the transcript scan behind
``hasCompletedBootstrapTurn`` (the host passes that answer in).
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from memory_core.bootstrap._js import js_trim
from memory_core.bootstrap.layout import DEFAULT_WORKSPACE_LAYOUT, WorkspaceLayout

MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES = 2 * 1024 * 1024

SessionKind = Literal["main", "group", "channel", "direct", "heartbeat", "subagent", "cron"]
BootstrapContextMode = Literal["full", "lightweight"]
BootstrapContextRunKind = Literal["default", "heartbeat", "cron", "commitment-only"]
BootstrapMode = Literal["full", "limited", "none"]
ContextInjectionMode = Literal["always", "continuation-skip", "never"]

SESSION_KINDS: tuple[str, ...] = (
    "main",
    "group",
    "channel",
    "direct",
    "heartbeat",
    "subagent",
    "cron",
)


@dataclass(frozen=True)
class WorkspaceBootstrapFile:
    """One workspace bootstrap file (upstream ``WorkspaceBootstrapFile``)."""

    name: str
    path: str
    content: str | None = None
    missing: bool = False


def _is_inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def read_workspace_file_guarded(
    file_path: str | os.PathLike[str],
    root: str | os.PathLike[str],
    *,
    max_bytes: int = MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES,
) -> str | None:
    """Read a workspace file like upstream's ``openRootFile`` guard, or ``None``.

    The real path must stay inside the real workspace root, be a regular file
    with a single hard link and at most ``max_bytes`` bytes. Content is decoded
    as UTF-8 with replacement characters and without newline translation (Node
    ``readFileSync(fd, "utf-8")``). Symlinks that resolve inside the root are
    followed; upstream's finer alias policy is not ported.
    """
    try:
        real_root = os.path.realpath(root)
        real_path = os.path.realpath(file_path)
        if not _is_inside(real_path, real_root):
            return None
        info = os.lstat(real_path)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1 or info.st_size > max_bytes:
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(real_path, flags)
        try:
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink > 1
                or opened.st_size > max_bytes
                or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
            ):
                return None
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 1 << 16)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            os.close(fd)
    except OSError:
        return None
    return b"".join(chunks).decode("utf-8", errors="replace")


def exact_workspace_entry_exists(root: str | os.PathLike[str], name: str) -> bool:
    """Port of ``exactWorkspaceEntryExists`` (src/memory/root-memory-files.ts:31-38)."""
    try:
        return name in os.listdir(root)
    except OSError:
        return False


def _display_root(root: str | os.PathLike[str]) -> str:
    # resolveUserPath: expand "~" and resolve lexically, without following
    # symlinks, so injected paths match what the host passed in.
    return os.path.abspath(os.path.expanduser(os.fspath(root)))


def load_workspace_bootstrap_files(
    root: str | os.PathLike[str],
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
    *,
    max_bytes: int = MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES,
) -> list[WorkspaceBootstrapFile]:
    """Load the layout's bootstrap files in load order.

    MEMORY.md is skipped entirely (no missing marker) unless the directory lists
    the exact name ``MEMORY.md``; the layout's ``extension_files`` (no upstream
    counterpart) are skipped the same way. Any other file that fails the
    guarded read is returned with ``missing=True``.
    """
    display_root = _display_root(root)
    files: list[WorkspaceBootstrapFile] = []
    for name in layout.load_order:
        file_path = os.path.join(display_root, name)
        skip_when_absent = name == layout.memory_file or name in layout.extension_files
        if skip_when_absent and not exact_workspace_entry_exists(display_root, name):
            continue
        content = read_workspace_file_guarded(file_path, display_root, max_bytes=max_bytes)
        if content is None:
            files.append(WorkspaceBootstrapFile(name=name, path=file_path, missing=True))
        else:
            files.append(WorkspaceBootstrapFile(name=name, path=file_path, content=content))
    return files


def filter_bootstrap_files_for_session(
    files: Iterable[WorkspaceBootstrapFile],
    session_kind: SessionKind | None,
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
) -> list[WorkspaceBootstrapFile]:
    """Port of ``filterBootstrapFilesForSession`` keyed by host session kind.

    ``subagent`` keeps the layout's subagent allowlist (AGENTS.md, TOOLS.md),
    ``cron`` keeps the cron allowlist; every other kind keeps all files. Group
    and channel sessions keep MEMORY.md: upstream enforces "main session only"
    in template prose, not in code.
    """
    items = list(files)
    if session_kind is None:
        return items
    if session_kind not in SESSION_KINDS:
        raise ValueError(f"unknown session kind: {session_kind}")
    if session_kind == "subagent":
        return [file for file in items if file.name in layout.subagent_files]
    if session_kind == "cron":
        return [file for file in items if file.name in layout.cron_files]
    return items


def _resolve_under_root(path_value: str, root: str) -> str:
    if os.path.isabs(path_value):
        return os.path.normpath(path_value)
    if path_value.startswith("~"):
        return os.path.abspath(os.path.expanduser(path_value))
    return os.path.normpath(os.path.join(root, path_value))


def filter_completed_bootstrap_file(
    files: Iterable[WorkspaceBootstrapFile],
    *,
    setup_completed: bool,
    root: str | os.PathLike[str],
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
) -> list[WorkspaceBootstrapFile]:
    """Drop the root BOOTSTRAP.md once setup is complete (bootstrap-files.ts:256-281)."""
    items = list(files)
    if not setup_completed:
        return items
    display_root = _display_root(root)
    root_bootstrap = os.path.join(display_root, layout.bootstrap_file)
    kept: list[WorkspaceBootstrapFile] = []
    for file in items:
        if file.name != layout.bootstrap_file:
            kept.append(file)
            continue
        path_value = js_trim(file.path) if isinstance(file.path, str) else ""
        if not path_value or _resolve_under_root(path_value, display_root) != root_bootstrap:
            kept.append(file)
    return kept


def apply_context_mode_filter(
    files: Iterable[WorkspaceBootstrapFile],
    *,
    context_mode: BootstrapContextMode = "full",
    run_kind: BootstrapContextRunKind = "default",
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
) -> list[WorkspaceBootstrapFile]:
    """Port of ``applyContextModeFilter`` (bootstrap-files.ts:201-216)."""
    items = list(files)
    if context_mode != "lightweight":
        return items
    if run_kind == "heartbeat":
        return [file for file in items if file.name == layout.heartbeat_file]
    return []


def filter_heartbeat_bootstrap_file(
    files: Iterable[WorkspaceBootstrapFile],
    *,
    run_kind: BootstrapContextRunKind = "default",
    include_heartbeat: bool = True,
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
) -> list[WorkspaceBootstrapFile]:
    """HEARTBEAT.md exclusion (bootstrap-files.ts:218-254).

    ``commitment-only`` runs always drop it and ``heartbeat`` runs always keep
    it. For other runs ``include_heartbeat`` stands in for upstream's
    ``shouldIncludeHeartbeatGuidanceForSystemPrompt`` (default agent, heartbeat
    policy, cadence), which is host configuration here.
    """
    items = list(files)
    if run_kind == "commitment-only":
        exclude = True
    elif run_kind == "heartbeat":
        exclude = False
    else:
        exclude = not include_heartbeat
    if not exclude:
        return items
    return [file for file in items if file.name != layout.heartbeat_file]


def dedupe_bootstrap_files(
    files: Iterable[WorkspaceBootstrapFile],
    root: str | os.PathLike[str],
    *,
    warn: Callable[[str], None] | None = None,
) -> list[WorkspaceBootstrapFile]:
    """Port of ``sanitizeBootstrapFiles`` path dedupe (bootstrap-files.ts:170-199).

    A file with a blank path is dropped after upstream's warning, passed to
    ``warn`` when given.
    """
    display_root = _display_root(root)
    seen: set[str] = set()
    result: list[WorkspaceBootstrapFile] = []
    for file in files:
        path_value = js_trim(file.path) if isinstance(file.path, str) else ""
        if not path_value:
            if warn is not None:
                warn(
                    f'skipping bootstrap file "{file.name}" — missing or invalid "path" field '
                    '(hook may have used "filePath" instead)'
                )
            continue
        resolved = _resolve_under_root(path_value, display_root)
        key = os.path.normpath(os.path.relpath(resolved, display_root))
        if key in seen:
            continue
        seen.add(key)
        result.append(WorkspaceBootstrapFile(file.name, resolved, file.content, file.missing))
    return result


def filter_bootstrap_files(
    files: Sequence[WorkspaceBootstrapFile],
    *,
    root: str | os.PathLike[str],
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
    session_kind: SessionKind | None = "main",
    setup_completed: bool = False,
    context_mode: BootstrapContextMode = "full",
    run_kind: BootstrapContextRunKind = "default",
    include_heartbeat: bool = True,
    warn: Callable[[str], None] | None = None,
) -> list[WorkspaceBootstrapFile]:
    """The ``resolveBootstrapFilesForRun`` filter chain, in upstream order.

    ``warn`` receives the path-dedupe warnings, like upstream's ``warn`` option.
    """
    filtered = filter_bootstrap_files_for_session(files, session_kind, layout)
    filtered = filter_completed_bootstrap_file(
        filtered, setup_completed=setup_completed, root=root, layout=layout
    )
    filtered = apply_context_mode_filter(
        filtered, context_mode=context_mode, run_kind=run_kind, layout=layout
    )
    filtered = filter_heartbeat_bootstrap_file(
        filtered, run_kind=run_kind, include_heartbeat=include_heartbeat, layout=layout
    )
    return dedupe_bootstrap_files(filtered, root, warn=warn)


def is_heartbeat_lifecycle_run_kind(run_kind: BootstrapContextRunKind | None) -> bool:
    return run_kind in ("heartbeat", "commitment-only")


def resolve_bootstrap_mode(
    *,
    bootstrap_pending: bool,
    run_kind: BootstrapContextRunKind = "default",
    is_interactive_user_facing: bool = True,
    is_primary_run: bool = True,
    is_canonical_workspace: bool = True,
    has_bootstrap_file_access: bool = True,
) -> BootstrapMode:
    """Port of ``resolveBootstrapMode`` (src/agents/bootstrap-mode.ts:11-33)."""
    if not bootstrap_pending:
        return "none"
    if is_heartbeat_lifecycle_run_kind(run_kind) or run_kind == "cron":
        return "none"
    if not is_primary_run or not is_interactive_user_facing:
        return "none"
    if not has_bootstrap_file_access:
        return "limited"
    return "full" if is_canonical_workspace else "limited"


@dataclass(frozen=True)
class ContextInjectionDecision:
    skip_injection: bool
    is_continuation_turn: bool
    record_completed_bootstrap_turn: bool


def resolve_context_injection(
    context_injection: ContextInjectionMode,
    *,
    bootstrap_mode: BootstrapMode,
    run_kind: BootstrapContextRunKind = "default",
    context_mode: BootstrapContextMode = "full",
    has_completed_bootstrap_turn: bool = False,
) -> ContextInjectionDecision:
    """Port of the ``resolveAttemptBootstrapContext`` decision.

    ``has_completed_bootstrap_turn`` is the host's answer to upstream's
    transcript scan for a full-bootstrap marker that no later compaction
    invalidated. ``record_completed_bootstrap_turn`` tells the host to persist
    that marker after a clean, non-compaction turn.
    """
    if context_injection not in ("always", "continuation-skip", "never"):
        raise ValueError(f"unknown context injection mode: {context_injection}")
    heartbeat_lifecycle = is_heartbeat_lifecycle_run_kind(run_kind)
    is_continuation = (
        bootstrap_mode != "full"
        and context_injection == "continuation-skip"
        and not heartbeat_lifecycle
        and bool(has_completed_bootstrap_turn)
    )
    skip = context_injection == "never" or is_continuation
    record = (
        not skip
        and context_mode != "lightweight"
        and not heartbeat_lifecycle
        and bootstrap_mode == "full"
    )
    return ContextInjectionDecision(skip, is_continuation, record)


def display_path(path: str, root: str | os.PathLike[str], path_style: str) -> str:
    if path_style == "absolute":
        return path
    if path_style == "relative":
        display_root = _display_root(root)
        try:
            relative = os.path.relpath(path, display_root)
        except ValueError:
            return path
        if relative.startswith(".."):
            return path
        return Path(relative).as_posix()
    raise ValueError(f"unknown path style: {path_style}")
