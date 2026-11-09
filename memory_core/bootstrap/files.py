"""Loading and per-run filtering of workspace bootstrap files.

Ports, at the parity pin v2026.9.6:

- ``loadWorkspaceBootstrapFiles`` (``src/agents/workspace.ts``): the layout's file set in load
  order; USER.md and MEMORY.md (and the memory-core extension files) are skipped unless the
  directory lists the exact name, a missing file becomes a ``[MISSING]`` placeholder and any
  other failed guarded read becomes the content ``[UNREADABLE: <reason>]`` (``missing`` false);
- the guarded read ``readWorkspaceFileWithGuards`` (``src/agents/workspace-file-read.ts``) with
  ``openRootFile``'s ``follow-parents-within-root`` policy (``@openclaw/fs-safe`` 0.18.1): a
  final-component symlink, a non-regular file and a hard-linked file are refused, and the
  read is bounded to 2 MiB (``src/agents/workspace-bootstrap-read.ts``);
- ``filterBootstrapFilesForSession`` (``src/agents/workspace.ts``) with the session kind
  supplied by the host instead of parsed from an OpenClaw session key, including the root
  MEMORY.md privacy filter for subagent, cron, group and channel sessions
  (``filterRootMemoryBootstrapFiles``, d06fc25a0c5, #119198);
- the run pipeline of ``resolveBootstrapFilesForRun`` (``src/agents/bootstrap-files.ts``):
  configured automatic-memory provenance classification, session filter, completed-BOOTSTRAP filter, lightweight context mode (no bootstrap files at
  all; the heartbeat monitor scratch is injected by the heartbeat runner), path dedupe;
- ``resolveBootstrapMode`` (``src/agents/bootstrap-mode.ts``) and the contextInjection decision
  of ``resolveAttemptBootstrapContext``
  (``src/agents/embedded-agent-runner/run/attempt-context-engine-helpers.ts``).

Not ported: the ``agent:bootstrap`` hook and ``bootstrap-extra-files`` globs, the per-session
snapshot cache and the workspace file cache, the authenticated personal
``users/<profile-id>/USER.md`` overlay (``workspace-personal-bootstrap.ts``; memory-core's
``user/`` folder is a separate extension), third-party registered memory runtimes,
remote workspace access, the transient-read retries, and the transcript scan behind
``hasCompletedBootstrapTurn`` (the host passes that answer in). OS read errors other than
the ones :func:`read_workspace_bootstrap_file` names get upstream's generic fallback reason
instead of Node's error text.
"""

from __future__ import annotations

import errno
import os
import re
import stat
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from memory_core.bootstrap._js import JS_SPACE, js_trim, truncate_utf16_safe
from memory_core.bootstrap.layout import DEFAULT_WORKSPACE_LAYOUT, WorkspaceLayout

if TYPE_CHECKING:
    from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore

MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES = 2 * 1024 * 1024
# workspace.ts loadWorkspaceBootstrapFiles: the unreadable reason is capped at 300 UTF-16 units.
UNREADABLE_REASON_MAX_CHARS = 300

SessionKind = Literal["main", "group", "channel", "direct", "heartbeat", "subagent", "cron"]
BootstrapContextMode = Literal["full", "lightweight"]
BootstrapContextRunKind = Literal["default", "heartbeat", "cron"]
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
# filterBootstrapFilesForSession: subagent, cron, group and channel sessions are not private.
NON_PRIVATE_SESSION_KINDS = frozenset({"subagent", "cron", "group", "channel"})


@dataclass(frozen=True)
class WorkspaceBootstrapFile:
    """One workspace bootstrap file (upstream ``WorkspaceBootstrapFile``).

    ``unreadable_reason`` is memory-core metadata: set when the guarded read refused the file, in
    which case ``content`` is upstream's ``[UNREADABLE: <reason>]`` text and ``missing`` is
    false, exactly as upstream loads it. Hosts can mark a supplied personal USER.md overlay
    with ``personal_user``; authenticated overlay discovery is not ported.
    """

    name: str
    path: str
    content: str | None = None
    missing: bool = False
    unreadable_reason: str | None = None
    personal_user: bool = False


def _is_inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def read_workspace_file_guarded(
    file_path: str | os.PathLike[str],
    root: str | os.PathLike[str],
    *,
    max_bytes: int = MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES,
) -> str | None:
    """Read a workspace file inside ``root``, or ``None`` (startup-context daily files).

    The real path must stay inside the real workspace root, be a regular file with a single
    hard link and at most ``max_bytes`` bytes. Content is decoded as UTF-8 with replacement
    characters and without newline translation (Node ``readFileSync(fd, "utf-8")``). Symlinks
    that resolve inside the root are followed. Bootstrap files use the stricter
    :func:`read_workspace_bootstrap_file`.
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
            data = _read_all(fd)
        finally:
            os.close(fd)
    except OSError:
        return None
    return data.decode("utf-8", errors="replace")


def _read_all(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1 << 16)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


# @openclaw/fs-safe 0.18.1 FsSafeError messages (dist/root-path.js, dist/pinned-open.js) and
# the bounded-read RangeError of src/infra/boundary-file-read.ts.
FS_SAFE_SYMLINK_MESSAGE = "symlink path component not allowed"
FS_SAFE_NOT_FILE_MESSAGE = "path does not have the required file type"
FS_SAFE_HARDLINK_MESSAGE = "path must not be hardlinked"
# libuv (uv_strerror) texts Node puts into an open() error message: "<CODE>: <text>, open '<p>'".
_NODE_OPEN_ERROR_TEXT = {
    errno.EACCES: "permission denied",
    errno.EPERM: "operation not permitted",
    errno.EIO: "i/o error",
    errno.EMFILE: "too many open files",
    errno.ENFILE: "file table overflow",
}


@dataclass(frozen=True)
class BootstrapFileRead:
    """Outcome of :func:`read_workspace_bootstrap_file`."""

    status: Literal["ok", "missing", "unreadable"]
    content: str | None = None
    reason: str | None = None


def _unreadable(message: str | None, fallback_kind: str) -> BootstrapFileRead:
    fallback = f"workspace file could not be read ({fallback_kind})"
    collapsed = js_trim(re.sub(f"{JS_SPACE}+", " ", message or "")) or fallback
    return BootstrapFileRead("unreadable", reason=truncate_utf16_safe(collapsed, UNREADABLE_REASON_MAX_CHARS))


def read_workspace_bootstrap_file(
    file_path: str | os.PathLike[str],
    root: str | os.PathLike[str],
    *,
    max_bytes: int = MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES,
) -> BootstrapFileRead:
    """Guarded bootstrap read (``readWorkspaceFileWithGuards`` + ``openRootFile``).

    Parent components may be symlinks that stay inside the real root; the final component
    must not be a symlink (even one pointing inside the root), must be a regular file and must
    have one hard link. ENOENT/ENOTDIR mean ``missing``; every other failure is
    ``unreadable`` with upstream's reason text: ``symlink path component not allowed``,
    ``path does not have the required file type``, ``path must not be hardlinked``,
    ``File exceeds 2097152 bytes``, or Node's ``EACCES: permission denied, open '<real path>'``
    for the open errors in ``_NODE_OPEN_ERROR_TEXT``.
    """
    path_value = os.fspath(file_path)
    try:
        real_root = os.path.realpath(root)
        parent = os.path.realpath(os.path.dirname(path_value) or ".")
        if not _is_inside(parent, real_root):
            return _unreadable(None, "validation")
        candidate = os.path.join(parent, os.path.basename(path_value))
        info = os.lstat(candidate)
    except (FileNotFoundError, NotADirectoryError):
        return BootstrapFileRead("missing")
    except OSError as exc:
        return _unreadable(None, "io" if not isinstance(exc, PermissionError) else "validation")
    if stat.S_ISLNK(info.st_mode):
        return _unreadable(FS_SAFE_SYMLINK_MESSAGE, "validation")
    if not stat.S_ISREG(info.st_mode):
        return _unreadable(FS_SAFE_NOT_FILE_MESSAGE, "validation")
    if info.st_nlink > 1:
        return _unreadable(FS_SAFE_HARDLINK_MESSAGE, "validation")
    try:
        fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        text = _NODE_OPEN_ERROR_TEXT.get(exc.errno or 0)
        if text is None:
            return _unreadable(None, "io")
        code = errno.errorcode.get(exc.errno or 0, "EIO")
        return _unreadable(f"{code}: {text}, open '{candidate}'", "io")
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink > 1
            or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
        ):
            return _unreadable(None, "validation")
        if opened.st_size > max_bytes:
            return _unreadable(f"File exceeds {max_bytes} bytes", "validation")
        data = b""
        while len(data) <= max_bytes:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            data += chunk
        if len(data) > max_bytes:
            return _unreadable(f"File exceeds {max_bytes} bytes", "validation")
    except OSError:
        return _unreadable(None, "io")
    finally:
        os.close(fd)
    return BootstrapFileRead("ok", content=data.decode("utf-8", errors="replace"))


def exact_workspace_entry_exists(root: str | os.PathLike[str], name: str) -> bool:
    """Port of ``exactWorkspaceEntryExists`` (src/memory/root-memory-files.ts)."""
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
    names: Iterable[str] | None = None,
    max_bytes: int = MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES,
) -> list[WorkspaceBootstrapFile]:
    """Load the layout's bootstrap files in load order (``loadWorkspaceBootstrapFiles``).

    ``names`` restricts the load to those files, keeping load order. A file in
    ``layout.skip_absent_files`` (USER.md, MEMORY.md, the extensions) is skipped entirely
    unless the directory lists its exact name. A missing file is returned with
    ``missing=True``; a file the guarded read refuses carries ``[UNREADABLE: <reason>]``.
    """
    display_root = _display_root(root)
    wanted = None if names is None else set(names)
    files: list[WorkspaceBootstrapFile] = []
    for name in layout.load_order:
        if wanted is not None and name not in wanted:
            continue
        file_path = os.path.join(display_root, name)
        if name in layout.skip_absent_files and not exact_workspace_entry_exists(
            display_root, name
        ):
            continue
        read = read_workspace_bootstrap_file(file_path, display_root, max_bytes=max_bytes)
        if read.status == "ok":
            files.append(WorkspaceBootstrapFile(name=name, path=file_path, content=read.content))
        elif read.status == "missing":
            files.append(WorkspaceBootstrapFile(name=name, path=file_path, missing=True))
        else:
            files.append(
                WorkspaceBootstrapFile(
                    name=name,
                    path=file_path,
                    content=f"[UNREADABLE: {read.reason}]",
                    unreadable_reason=read.reason,
                )
            )
    return files


def _resolve_under_root(path_value: str, root: str) -> str:
    if os.path.isabs(path_value):
        return os.path.normpath(path_value)
    if path_value.startswith("~"):
        return os.path.abspath(os.path.expanduser(path_value))
    return os.path.normpath(os.path.join(root, path_value))


def filter_root_memory_bootstrap_files(
    files: Iterable[WorkspaceBootstrapFile],
    root: str | os.PathLike[str] | None = None,
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
) -> list[WorkspaceBootstrapFile]:
    """Port of ``filterRootMemoryBootstrapFiles`` (``src/agents/workspace.ts``).

    Without ``root`` every file named MEMORY.md is dropped; with it only the file whose
    resolved path is ``<root>/MEMORY.md`` (a blank path is kept).
    """
    items = list(files)
    if root is None:
        return [file for file in items if file.name != layout.memory_file]
    display_root = _display_root(root)
    root_memory = os.path.join(display_root, layout.memory_file)
    kept: list[WorkspaceBootstrapFile] = []
    for file in items:
        path_value = js_trim(file.path) if isinstance(file.path, str) else ""
        if not isinstance(file.path, str) or not path_value:
            kept.append(file)
            continue
        if _resolve_under_root(path_value, display_root) != root_memory:
            kept.append(file)
    return kept


def filter_bootstrap_files_for_session(
    files: Iterable[WorkspaceBootstrapFile],
    session_kind: SessionKind | None,
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
    *,
    root: str | os.PathLike[str] | None = None,
) -> list[WorkspaceBootstrapFile]:
    """Port of ``filterBootstrapFilesForSession`` keyed by host session kind.

    Subagent, cron, group and channel sessions lose the root MEMORY.md (d06fc25a0c5, #119198;
    ``root`` as upstream's session ``workspaceDir``, see
    :func:`filter_root_memory_bootstrap_files`). ``subagent`` then keeps the layout's subagent
    allowlist (AGENTS.md) and ``cron`` its cron allowlist (AGENTS, SOUL, IDENTITY, USER); main,
    direct and heartbeat sessions keep every file.
    """
    items = list(files)
    if session_kind is None:
        return items
    if session_kind not in SESSION_KINDS:
        raise ValueError(f"unknown session kind: {session_kind}")
    if session_kind in NON_PRIVATE_SESSION_KINDS:
        items = filter_root_memory_bootstrap_files(items, root, layout)
    if session_kind == "subagent":
        return [file for file in items if file.name in layout.subagent_files]
    if session_kind == "cron":
        return [file for file in items if file.name in layout.cron_files]
    return items


def filter_completed_bootstrap_file(
    files: Iterable[WorkspaceBootstrapFile],
    *,
    setup_completed: bool,
    root: str | os.PathLike[str],
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
) -> list[WorkspaceBootstrapFile]:
    """Drop the root BOOTSTRAP.md once setup is complete (``filterCompletedWorkspaceBootstrapFile``)."""
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
) -> list[WorkspaceBootstrapFile]:
    """Port of ``applyContextModeFilter`` (``src/agents/bootstrap-files.ts``).

    ``lightweight`` runs get no bootstrap files at all, heartbeat runs included: the
    heartbeat monitor scratch is injected by the heartbeat runner, not as a bootstrap file.
    """
    items = list(files)
    return [] if context_mode == "lightweight" else items


def dedupe_bootstrap_files(
    files: Iterable[WorkspaceBootstrapFile],
    root: str | os.PathLike[str],
    *,
    warn: Callable[[str], None] | None = None,
) -> list[WorkspaceBootstrapFile]:
    """Port of ``sanitizeBootstrapFiles`` path dedupe (``src/agents/bootstrap-files.ts``).

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
        result.append(replace(file, path=resolved))
    return result


def filter_bootstrap_files(
    files: Sequence[WorkspaceBootstrapFile],
    *,
    root: str | os.PathLike[str],
    layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
    session_kind: SessionKind | None = "main",
    setup_completed: bool = False,
    context_mode: BootstrapContextMode = "full",
    warn: Callable[[str], None] | None = None,
    config: Mapping[str, Any] | None = None,
    artifact_provenance: MemoryArtifactProvenanceStore | None = None,
) -> list[WorkspaceBootstrapFile]:
    """The ``resolveBootstrapFilesForRun`` filter chain, in upstream order.

    The built-in classifier uses actual physical paths and the supplied artifact
    provenance store when ``config`` selects it or the host explicitly supplies
    that store. It runs before the session filter, as the original caller does.
    No search manager or model is needed. Unavailable runtimes skip classification;
    classification failures exclude the candidates and report a warning.

    Session filter (with ``root`` as the session workspace), completed-BOOTSTRAP filter,
    context mode, then the path dedupe. Upstream repeats the session and completed filters
    after its bootstrap hooks; memory-core has no hooks, so the second pass changes nothing.
    ``warn`` receives the path-dedupe warnings, like upstream's ``warn`` option.
    """
    from memory_core.bootstrap.classification import filter_automatic_bootstrap_memory

    automatic = filter_automatic_bootstrap_memory(files, root=root, config=config,
        artifact_provenance=artifact_provenance, warn=warn)
    filtered = filter_bootstrap_files_for_session(automatic, session_kind, layout, root=root)
    filtered = filter_completed_bootstrap_file(
        filtered, setup_completed=setup_completed, root=root, layout=layout
    )
    filtered = apply_context_mode_filter(filtered, context_mode=context_mode)
    return dedupe_bootstrap_files(filtered, root, warn=warn)


def is_heartbeat_lifecycle_run_kind(run_kind: BootstrapContextRunKind | None) -> bool:
    """Port of ``isHeartbeatLifecycleRunKind`` (bootstrap-mode.ts; ``commitment-only`` is gone)."""
    return run_kind == "heartbeat"


def resolve_bootstrap_mode(
    *,
    bootstrap_pending: bool,
    run_kind: BootstrapContextRunKind = "default",
    is_interactive_user_facing: bool = True,
    is_primary_run: bool = True,
    is_canonical_workspace: bool = True,
    has_bootstrap_file_access: bool = True,
) -> BootstrapMode:
    """Port of ``resolveBootstrapMode`` (``src/agents/bootstrap-mode.ts``)."""
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
