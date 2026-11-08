"""Trusted plain extra roots for the memory-file read tool.

Workspace memory paths retain their existing policy. A configured file or
directory can authorize additional Markdown reads; extra-root descendants do
not follow symlinks. Pattern entries and descriptor race equivalence belong to
the separate storage contracts.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Sequence
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
    is_memory_path,
)


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
    extra_paths: Sequence[str | Path] = (),
) -> tuple[str, Path | None, bool]:
    """Resolve a built-in memory file or an explicitly configured extra root.

    The result includes whether a hard-truncation notice may suggest the raw
    source reader. Model arguments cannot configure these roots. Existing
    workspace refusals take precedence over additional root authorization.
    """
    workspace = MemoryWorkspace(workspace_dir)
    try:
        relative, candidate = workspace.resolve_memory_read_path(raw_path)
        return relative, candidate, True
    except MemoryPathNotAllowedError:
        candidate = _lexical_path(workspace.root, js_trim(raw_path))
        relative = os.path.relpath(candidate, workspace.root).replace("\\", "/")
        if relative == ".":
            relative = ""
        in_workspace = bool(relative) and not relative.startswith("..") and not os.path.isabs(relative)
        if in_workspace and is_memory_path(relative):
            raise

    first_error: Exception | None = None
    for configured in extra_paths:
        if not isinstance(configured, (str, Path)):
            raise TypeError("Extra memory read roots must be plain file or directory paths")
        configured_text = js_trim(str(configured))
        if not configured_text:
            continue
        configured_path = _lexical_path(workspace.root, os.path.expanduser(configured_text))
        matches_file = candidate == configured_path and str(candidate).endswith(".md")
        matches_directory = str(candidate).endswith(".md") and candidate.is_relative_to(configured_path)
        if not matches_file and not matches_directory:
            continue
        try:
            info = configured_path.lstat()
            if stat.S_ISLNK(info.st_mode):
                continue
            if stat.S_ISDIR(info.st_mode) and matches_directory:
                return relative, _extra_leaf(configured_path, candidate), False
            if stat.S_ISREG(info.st_mode) and matches_file:
                return relative, _extra_leaf(configured_path.parent, candidate), False
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
