"""Consume an admitted memory file through its checked original descriptor.

Read-only port of @openclaw/fs-safe 0.21.1 local-file-descriptor.js,
root-read-admission.js and strict-file-identity.js, reached by the pinned
readMemoryFile owner. Their MIT notices are retained in LICENSE.openclaw.
The official source hashes/caller edges are recorded by the get read-race
bindings. Node system-error facts reuse the existing attributed IO bridge;
descriptor consumption reuses the bootstrap reader's byte loop.

Root/file/canonical-file/root admission finishes before consuming bytes, like
the original. Memory reads allow hardlinks, reject final symlinks, and never
reopen the pathname to obtain content. There is no post-read pathname gate.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
from typing import TYPE_CHECKING

from memory_core._memory_scan_io import bridge_memory_read_io_error
from memory_core.bootstrap.files import _read_all
from memory_core.memory_paths import MemoryReadPathError, UnsafeMemoryPathError

if TYPE_CHECKING:
    from memory_core.tools.get_paths import MemoryGetReadPath


def _io(operation: str, path: Path | None, call, *args):
    try:
        return call(*args)
    except OSError as error:
        bridged = bridge_memory_read_io_error(error, operation, path)
        raise bridged from None


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _mismatch() -> MemoryReadPathError:
    return MemoryReadPathError("path-mismatch", "file identity changed or could not be verified")


def _require_file(info: os.stat_result) -> None:
    if stat.S_ISLNK(info.st_mode):
        raise MemoryReadPathError("symlink", "symlink not allowed")
    if not stat.S_ISREG(info.st_mode):
        raise UnsafeMemoryPathError("path must be a regular file") from MemoryReadPathError("not-file", "not a file")


def _check_root(root: Path, expected: tuple[int, int]) -> None:
    try:
        info = _io("lstat", root, os.lstat, root)
    except Exception as error:
        raise MemoryReadPathError("path-mismatch", "root path changed during operation") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or _identity(info) != expected:
        raise MemoryReadPathError("path-mismatch", "root path changed during operation")


def _canonical_parent(root: Path, candidate: Path, follow_links: bool) -> Path:
    """Admit each actual parent and retain the original canonical open spelling."""
    try:
        parts = candidate.relative_to(root).parts
    except ValueError:
        raise MemoryReadPathError("outside-workspace", "file is outside workspace root") from None
    if not parts:
        raise MemoryReadPathError("outside-workspace", "file is outside workspace root")
    current = root
    for part in parts[:-1]:
        current = current / part
        info = _io("lstat", current, os.lstat, current)
        if stat.S_ISLNK(info.st_mode):
            if not follow_links:
                raise MemoryReadPathError("symlink", "symlink path component not allowed")
            try:
                current = Path(os.path.realpath(current, strict=True))
            except OSError as error:
                cause = bridge_memory_read_io_error(error, "realpath", current)
                if error.errno == errno.ELOOP:
                    raise MemoryReadPathError("symlink", "symlink path could not be resolved") from cause
                raise MemoryReadPathError("outside-workspace", "file is outside workspace root") from cause
            if not current.is_relative_to(root):
                raise MemoryReadPathError("outside-workspace", "file is outside workspace root")
            info = _io("stat", current, os.stat, current)
        if not stat.S_ISDIR(info.st_mode):
            raise MemoryReadPathError("outside-workspace", "file is outside workspace root") from MemoryReadPathError(
                "ENOTDIR", f"Path component is not a directory: {current}",
            )
    return current / parts[-1]


def read_memory_file_bytes(admitted: MemoryGetReadPath) -> bytes | None:
    """Pin, open, fence, and consume one actual memory read; missing stays None."""
    if admitted.path is None:
        return None
    root = admitted.root
    root_info = _io("lstat", root, os.lstat, root)
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise MemoryReadPathError("path-mismatch", "root path changed during operation")
    root_identity = _identity(root_info)
    filename = _canonical_parent(root, admitted.path, admitted.follow_parent_symlinks)
    _check_root(root, root_identity)

    # The native local descriptor owner permits an initial lookup failure to
    # fall through to the actual open, while a successful lstat pins identity.
    try:
        before = os.lstat(filename)
    except OSError:
        before = None
    if before is not None:
        _require_file(before)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(filename, flags)
    except OSError as error:
        if error.errno in {errno.ENOENT, errno.ENOTDIR}:
            return None
        if error.errno == errno.ELOOP:
            raise MemoryReadPathError("symlink", "symlink open blocked") from bridge_memory_read_io_error(error, "open", filename)
        if error.errno == errno.EISDIR:
            raise UnsafeMemoryPathError("path must be a regular file") from MemoryReadPathError("not-file", "not a file")
        raise bridge_memory_read_io_error(error, "open", filename) from None
    try:
        opened = _io("fstat", None, os.fstat, descriptor)
        _require_file(opened)
        identity = _identity(opened)
        if before is not None and identity != _identity(before):
            raise _mismatch()

        # The original final admission checks root, current path identity,
        # canonical containment/current canonical identity, then root again.
        _check_root(root, root_identity)
        current = _io("lstat", filename, os.lstat, filename)
        _require_file(current)
        if _identity(current) != identity:
            raise _mismatch()
        try:
            canonical = Path(os.path.realpath(filename, strict=True))
        except OSError as error:
            raise bridge_memory_read_io_error(error, "realpath", filename) from None
        if not canonical.is_relative_to(root):
            raise MemoryReadPathError("outside-workspace", "file is outside workspace root")
        canonical_info = _io("lstat", canonical, os.lstat, canonical)
        _require_file(canonical_info)
        if _identity(canonical_info) != identity:
            raise _mismatch()
        _check_root(root, root_identity)
        return _io("read", None, _read_all, descriptor)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass  # the original reader preserves the read outcome on close failure
