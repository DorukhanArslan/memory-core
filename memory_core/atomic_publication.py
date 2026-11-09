"""Checked memory-file publication, including the outcome of dispatched renames.

The default commit owner follows OpenClaw's commitMemoryContent and its pinned
fs-safe replacement primitive. A refused rename whose preimage is still current
is distinct from an uncertain dispatched mutation and an accepted publication
whose later verification or cleanup failed. Original IO exceptions remain as
causes, rather than being classified from a caller's later filesystem guess.

Source semantics: extensions/memory-core/src/short-term-promotion-memory-write.ts
and @openclaw/fs-safe 0.21.1 replace-file/descriptor/temp-owner/identity owners.
Their MIT notices are retained in LICENSE.openclaw.
"""
from __future__ import annotations

from collections.abc import Callable
import errno
import hashlib
import os
from pathlib import Path
import secrets
import stat
import threading

from memory_core._memory_scan_error_facts import MESSAGES
from memory_core.bootstrap._js import js_utf8_encode


class MemoryWriteConflictError(RuntimeError):
    name = "MemoryWriteConflictError"

    def __init__(self, message: str = "MEMORY.md changed before the dreaming write could commit"):
        super().__init__(message)


class MemoryAtomicPublicationError(RuntimeError):
    """The real owner dispatched a rename or completed its publication."""

    def __init__(self, publication: str, cause: BaseException):
        if publication not in {"uncertain", "committed"}:
            raise ValueError("Unknown atomic publication state")
        self.publication, self.cause = publication, cause
        self.name = getattr(cause, "name", type(cause).__name__)
        self.code = _code(cause)
        super().__init__(str(cause))


class MemoryPublicationPathError(RuntimeError):
    name = "FsSafeError"

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class _PublicationIOError(OSError):
    name = "Error"

    def __init__(self, original: OSError, operation: str, path: Path | None, destination: Path | None):
        self.original_exception = original
        self.code, self.syscall = errno.errorcode[original.errno], operation
        # A standard descriptor error has no public pathname in Node either.
        message = f"{self.code}: {MESSAGES[self.code]}, {operation}"
        if path is not None:
            self.path = str(path)
            message += f" '{path}'"
        if destination is not None:
            self.dest = str(destination)
            message += f" -> '{destination}'"
        super().__init__(message)
        self.errno = -abs(original.errno)
        self.cause = None


class _PublicationAggregateError(RuntimeError):
    name = "AggregateError"

    def __init__(self, errors: list[BaseException], message: str):
        self.errors = errors
        super().__init__(message)


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _code(error: BaseException) -> str | None:
    value = getattr(error, "code", None)
    return value if isinstance(value, str) else errno.errorcode.get(getattr(error, "errno", None))


def _io(operation: str, path: Path | None, function, *args, destination: Path | None = None):
    try:
        return function(*args)
    except OSError as error:
        number = error.errno
        code = errno.errorcode.get(number)
        if (type(number) is int and code in MESSAGES and not isinstance(getattr(error, "code", None), str)
                and error.strerror == os.strerror(number)):
            raise _PublicationIOError(error, operation, path, destination) from error
        raise


def hash_memory_content(content: str) -> str:
    return hashlib.sha256(js_utf8_encode(content)).hexdigest()


def _read_content(path: Path) -> str:
    try:
        return _io("open", path, path.read_bytes).decode("utf-8", errors="replace")
    except OSError as error:
        if _code(error) == "ENOENT":
            return ""
        raise


def _identity(info, path: Path, *, pathname: bool = False) -> tuple[int, int]:
    if stat.S_ISLNK(info.st_mode):
        raise MemoryPublicationPathError("symlink", f"Atomic replace owned file became a symlink: {path}")
    if not stat.S_ISREG(info.st_mode):
        raise MemoryPublicationPathError("not-file", f"Atomic replace owned file must remain regular: {path}")
    if info.st_nlink > 1 or (pathname and info.st_nlink != 1):
        raise MemoryPublicationPathError("hardlink", f"Atomic replace owned file must retain one link: {path}")
    return info.st_dev, info.st_ino


def _assert_current(fd: int, path: Path, identity: tuple[int, int]) -> None:
    opened = _io("fstat", None, os.fstat, fd)
    if _identity(opened, path) != identity:
        raise MemoryPublicationPathError("path-mismatch", "file identity changed or could not be verified")
    try:
        current = _io("lstat", path, os.lstat, path)
    except OSError as error:
        if _code(error) == "ENOENT":
            missing = MemoryPublicationPathError("path-mismatch", f"Atomic replace owned file disappeared: {path}")
            missing.cause = error
            raise missing from error
        raise
    if _identity(current, path, pathname=True) != identity:
        raise MemoryPublicationPathError("path-mismatch", "file identity changed or could not be verified")


def _sync_parent(parent: Path) -> None:
    descriptor = None
    try:
        descriptor = _io("open", parent, os.open, parent, os.O_RDONLY)
        _io("fsync", None, os.fsync, descriptor)
    except OSError:
        pass
    finally:
        if descriptor is not None:
            try:
                _io("close", None, os.close, descriptor)
            except OSError:
                pass


def commit_memory_content(
    path: Path, *, content: str | None, expected_content: str | None = None,
    expected_hash: str | None = None, conflict_message: str | None = None,
    temp_prefix: str = ".fs-safe-replace", before_publish: Callable[[], None] | None = None,
) -> None:
    """Publish one checked replacement; promotion's in-place fallback is separate."""
    path = Path(path)
    if not temp_prefix or temp_prefix in {".", ".."} or any(char in temp_prefix for char in "/\\\x00"):
        raise ValueError("Atomic replace temp prefix must be a safe path segment")
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(os.path.abspath(path), threading.RLock())
    with lock:
        _commit(path, content, expected_content, expected_hash, conflict_message, temp_prefix, before_publish)


def _commit(path, content, expected_content, expected_hash, conflict_message, temp_prefix, before_publish):
    if conflict_message is None:
        conflict_message = "MEMORY.md changed before the dreaming write could commit"
    if content is None:
        if _read_content(path) != expected_content:
            raise MemoryWriteConflictError(conflict_message)
        _io("unlink", path, os.unlink, path)
        return
    parent = path.parent
    parent_mode = _io("stat", parent, os.stat, parent).st_mode
    if not stat.S_ISDIR(parent_mode) or stat.S_ISLNK(_io("lstat", parent, os.lstat, parent).st_mode):
        raise MemoryPublicationPathError("not-file", f"Atomic replace parent must be a real directory: {parent}")
    try:
        previous = _io("lstat", path, os.lstat, path)
    except OSError as error:
        if _code(error) != "ENOENT":
            raise
        mode = 0o600
    else:
        if stat.S_ISLNK(previous.st_mode):
            raise MemoryPublicationPathError("symlink", "atomic replace destination must not be a symbolic link")
        if not stat.S_ISREG(previous.st_mode):
            raise MemoryPublicationPathError("not-file", "atomic replace destination must be a regular file")
        mode = previous.st_mode & 0o777
    temporary = parent / f"{temp_prefix}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
    descriptor, identity, exists, failure, publication = None, None, False, None, "unattempted"
    try:
        descriptor = _io("open", temporary, os.open, temporary,
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
        exists = True
        identity = _identity(_io("fstat", None, os.fstat, descriptor), temporary)
        data = memoryview(js_utf8_encode(content))
        while data:
            written = _io("write", None, os.write, descriptor, data)
            if written <= 0:
                raise OSError(errno.EIO, "write made no progress")
            data = data[written:]
        _io("fchmod", None, os.fchmod, descriptor, mode)
        try:
            _io("fsync", None, os.fsync, descriptor)
        except OSError as error:
            if _code(error) != "EPERM":
                raise
        _assert_current(descriptor, temporary, identity)
        if before_publish is not None:
            before_publish()
        if expected_hash and hash_memory_content(_read_content(path)) != expected_hash:
            raise MemoryWriteConflictError(conflict_message)
        _assert_current(descriptor, temporary, identity)
        publication = "uncertain"
        try:
            _io("rename", temporary, os.replace, temporary, path, destination=path)
        except OSError as error:
            if _code(error) in {"EACCES", "EPERM", "EEXIST", "EROFS"} and expected_hash and hash_memory_content(content) != expected_hash:
                try:
                    if hash_memory_content(_read_content(path)) == expected_hash:
                        publication = "unchanged-after-rejection"
                except OSError:
                    pass
            raise
        publication, exists = "committed", False
        _assert_current(descriptor, path, identity)
        _sync_parent(parent)
        _assert_current(descriptor, path, identity)
    except BaseException as error:
        failure = error
    finally:
        if exists and identity is not None:
            try:
                current = _io("lstat", temporary, os.lstat, temporary)
                if (stat.S_ISREG(current.st_mode) and current.st_nlink == 1
                        and (current.st_dev, current.st_ino) == identity):
                    _io("unlink", temporary, os.unlink, temporary)
            except OSError as cleanup:
                if _code(cleanup) != "ENOENT":
                    if failure is not None:
                        combined = RuntimeError(f"Atomic file replace failed ({getattr(failure, 'name', type(failure).__name__)}: {failure}); cleanup also failed ({getattr(cleanup, 'name', type(cleanup).__name__)}: {cleanup})")
                        combined.name, combined.cause = "Error", failure
                        failure = combined
                    else:
                        failure = cleanup
        if descriptor is not None:
            try:
                _io("close", None, os.close, descriptor)
            except OSError as close:
                failure = _PublicationAggregateError([failure, close], "Atomic file replace and close failed") if failure is not None else close
    if failure is not None:
        if publication in {"uncertain", "committed"}:
            raise MemoryAtomicPublicationError(publication, failure) from failure
        raise failure
