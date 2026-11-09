"""Trusted extra roots for the memory-file read tool.

Workspace memory paths retain their existing policy. A configured file or
directory can authorize additional Markdown reads; extra-root descendants do
not follow symlinks. Path/pattern entries use the discovery owner's normalization
and POSIX matcher; patterns authorize files only within their configured root.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from memory_core.bootstrap._js import js_trim
from memory_core.memory_paths import (
    MemoryPathNotAllowedError,
    MemoryReadPathError,
    UnsafeMemoryPathError,
)
from memory_core.workspace import (
    MEMORY_PATH_NOT_ALLOWED_ERROR,
    MEMORY_PATH_NOT_REGULAR_FILE_ERROR,
    MemoryWorkspace,
    _extra_memory_paths,
    _matches_extra_path,
    is_memory_path,
)


@dataclass(frozen=True)
class MemoryGetReadPath:
    """One admitted read target and the exact root/policy selected by its owner."""

    rel_path: str
    path: Path | None
    root: Path
    suggest_read_fallback: bool
    follow_parent_symlinks: bool


def _lexical_path(root: Path, value: str) -> Path:
    return Path(os.path.abspath(os.path.join(root, value)))


def _extra_leaf(root: Path, candidate: Path) -> Path | None:
    """Resolve one authorized root, refusing symlinks below that root."""
    physical_root = root.resolve(strict=True)
    relative = candidate.relative_to(root)
    current = physical_root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            raise MemoryReadPathError("symlink", "symlink path component not allowed")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise MemoryReadPathError("outside-workspace", "file is outside workspace root")
    if not current.is_file():
        raise UnsafeMemoryPathError(MEMORY_PATH_NOT_REGULAR_FILE_ERROR) from MemoryReadPathError(
            "not-file", "not a file",
        )
    return current


def resolve_memory_get_path(
    workspace_dir: Path,
    raw_path: str,
    extra_paths: Sequence[str | Path | Mapping[str, str]] = (),
) -> tuple[str, Path | None, bool]:
    """Resolve a built-in memory file or an explicitly configured extra root.

    The result includes whether a hard-truncation notice may suggest the raw
    source reader. Model arguments cannot configure these roots. Existing
    workspace refusals take precedence over additional root authorization.
    """
    admitted = resolve_memory_get_read_path(workspace_dir, raw_path, extra_paths)
    return admitted.rel_path, admitted.path, admitted.suggest_read_fallback


def resolve_memory_get_read_path(
    workspace_dir: Path,
    raw_path: str,
    extra_paths: Sequence[str | Path | Mapping[str, str]] = (),
) -> MemoryGetReadPath:
    """Resolve a read while retaining its selected root and parent-link policy.

    The built-in policy has priority over extra-root authorization. Configured
    roots retain distinct patterns, with matches under one root forming a union.
    An explicitly configured Markdown file is admitted independently of pattern.
    """
    workspace = MemoryWorkspace(workspace_dir)
    try:
        relative, candidate = workspace.resolve_memory_read_path(raw_path)
        return MemoryGetReadPath(relative, candidate, workspace.root, True, True)
    except MemoryPathNotAllowedError:
        candidate = _lexical_path(workspace.root, js_trim(raw_path))
        relative = os.path.relpath(candidate, workspace.root).replace("\\", "/")
        if relative == ".":
            relative = ""
        in_workspace = bool(relative) and not relative.startswith("..") and not os.path.isabs(relative)
        if in_workspace and is_memory_path(relative):
            raise

    first_error: Exception | None = None
    configured_entries = [str(entry) if isinstance(entry, Path) else entry for entry in extra_paths]
    for configured_path, entries in _extra_memory_paths(workspace.root, configured_entries).items():
        matches_file = candidate == configured_path and str(candidate).endswith(".md")
        matches_directory = (str(candidate).endswith(".md")
                             and candidate.is_relative_to(configured_path)
                             and any(_matches_extra_path(entry, candidate) for entry in entries))
        if not matches_file and not matches_directory:
            continue
        try:
            info = configured_path.lstat()
            if stat.S_ISLNK(info.st_mode):
                continue
            if stat.S_ISDIR(info.st_mode) and matches_directory:
                resolved = _extra_leaf(configured_path, candidate)
                return MemoryGetReadPath(relative, resolved, configured_path.resolve(strict=True), False, False)
            if stat.S_ISREG(info.st_mode) and matches_file:
                resolved = _extra_leaf(configured_path.parent, candidate)
                return MemoryGetReadPath(relative, resolved, configured_path.parent.resolve(strict=True), False, False)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except MemoryReadPathError as error:
            if error.code not in {"symlink", "outside-workspace"} and first_error is None:
                first_error = error
        except Exception as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error
    raise MemoryPathNotAllowedError(MEMORY_PATH_NOT_ALLOWED_ERROR)
