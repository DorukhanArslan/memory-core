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

    def __init__(self, code: str, message: str, cause: BaseException | None = None, *, details: dict | None = None):
        self.code = code
        self.category = "operational" if code in {
            "helper-failed", "helper-unavailable", "not-empty", "not-found", "not-removable",
            "permission-unverified", "read-failed", "timeout", "unsupported-platform",
        } else "policy"
        if cause is not None:
            self.cause = cause
        if details is not None:
            self.details = details
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
        descriptor = _io("open", path, os.open, path, os.O_RDONLY)
    except OSError as error:
        if _code(error) == "ENOENT":
            return ""
        raise
    try:
        parts = []
        while part := _io("read", None, os.read, descriptor, 1 << 16):
            parts.append(part)
        return b"".join(parts).decode("utf-8", errors="replace")
    finally:
        _io("close", None, os.close, descriptor)


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


def _write_all(
    descriptor: int, content: bytes, *, before_write: Callable[[], None] | None = None,
    chunk_bytes: int | None = None, zero_progress_error: BaseException | None = None,
) -> None:
    data = memoryview(content)
    while data:
        if before_write is not None:
            before_write()
        window = data if chunk_bytes is None else data[:chunk_bytes]
        written = _io("write", None, os.write, descriptor, window)
        if written <= 0:
            if zero_progress_error is not None:
                raise zero_progress_error
            raise OSError(errno.EIO, "write made no progress")
        data = data[written:]


def _assert_parent(parent: Path, descriptor: int, identity: tuple[int, int]) -> None:
    opened = _io("fstat", None, os.fstat, descriptor)
    current = _io("lstat", parent, os.lstat, parent)
    if (not stat.S_ISDIR(current.st_mode) or stat.S_ISLNK(current.st_mode)
            or (current.st_dev, current.st_ino) != identity or (opened.st_dev, opened.st_ino) != identity):
        raise MemoryPublicationPathError("path-mismatch", "root path changed during operation")


def append_memory_content(
    path: Path, content: str, *, prepend_newline_if_needed: bool = False,
    before_write: Callable[[], None] | None = None,
) -> None:
    """Append through a checked descriptor; dispatched partial writes remain visible.

    This follows Root.append, including strict file fsync. It does not turn a
    plain append failure into a rename-publication receipt or restore its bytes.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        previous = _io("lstat", path, os.lstat, path)
    except OSError as error:
        if _code(error) != "ENOENT":
            raise
        previous = None
    if previous is not None:
        if stat.S_ISLNK(previous.st_mode):
            raise MemoryPublicationPathError("symlink", "symlink path component not allowed")
        if not stat.S_ISREG(previous.st_mode):
            raise MemoryPublicationPathError("not-file", "not a file")
        if previous.st_nlink > 1:
            raise MemoryPublicationPathError("hardlink", "hardlinked path not allowed")
    flags = os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    flags |= os.O_CREAT | os.O_EXCL if previous is None else 0
    if previous is None and before_write is not None:
        before_write()
    descriptor = _io("open", path, os.open, path, flags, 0o600)
    identity, dispatched = None, False
    try:
        opened = _io("fstat", None, os.fstat, descriptor)
        identity = _identity(opened, path)
        if previous is not None and identity != (previous.st_dev, previous.st_ino):
            raise MemoryPublicationPathError("path-mismatch", "file identity changed or could not be verified")
        _assert_current(descriptor, path, identity)
        if previous is None:
            _io("fchmod", None, os.fchmod, descriptor, 0o600)
        payload = js_utf8_encode(content)
        if prepend_newline_if_needed and opened.st_size and payload and not payload.startswith(b"\n"):
            tail = _io("read", None, os.pread, descriptor, 1, opened.st_size - 1)
            if tail != b"\n":
                payload = b"\n" + payload
        _assert_current(descriptor, path, identity)

        def assert_write() -> None:
            nonlocal dispatched
            if before_write is not None:
                before_write()
            dispatched = True

        _write_all(descriptor, payload, before_write=assert_write, chunk_bytes=512 * 1024,
                   zero_progress_error=MemoryPublicationPathError("helper-failed", "file write made no progress"))
        dispatched = True
        _io("fsync", None, os.fsync, descriptor)
        if previous is None:
            _sync_parent(path.parent)
    finally:
        try:
            _io("close", None, os.close, descriptor)
        finally:
            if previous is None and not dispatched and identity is not None:
                try:
                    current = _io("lstat", path, os.lstat, path)
                    if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == identity:
                        _io("unlink", path, os.unlink, path)
                except OSError as error:
                    if _code(error) != "ENOENT":
                        raise


def _root_write_error(error: BaseException) -> BaseException:
    if isinstance(error, MemoryPublicationPathError):
        return error
    code = _code(error)
    if code in {"ENOENT", "ENOTDIR"}:
        return MemoryPublicationPathError("not-found", "file not found", error)
    labels = {"EACCES": "permission denied", "EPERM": "permission denied",
              "EROFS": "read-only filesystem", "ENOSPC": "no space left on device"}
    message = f"{labels.get(code, 'filesystem write failed')} ({code})" if code else "path is not a regular file under root"
    return MemoryPublicationPathError("invalid-path", message, error)


def publish_bootstrap_file(path: Path, content: str) -> bool:
    """Stage complete private bootstrap bytes, then exclusively publish them.

    Existing entries are a no-op. A failed staged write never creates a partial
    destination. This is the real owner used by workspace lifecycle seeding.
    """
    path = Path(path)
    parent = _io("realpath", path.parent, path.parent.resolve, True)
    target = parent / path.name
    try:
        _io("lstat", target, os.lstat, target)
    except OSError as error:
        if _code(error) != "ENOENT":
            raise
    else:
        return False
    temporary = parent / f".fs-safe-{secrets.token_hex(16)}.tmp"
    parent_fd, descriptor, identity, linked, failure = None, None, None, False, None
    publication = {"status": "not-published"}
    try:
        parent_fd = _io("open", parent, os.open, parent,
                        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
        parent_stat = _io("fstat", None, os.fstat, parent_fd)
        parent_identity = parent_stat.st_dev, parent_stat.st_ino
        _assert_parent(parent, parent_fd, parent_identity)
        descriptor = _io("open", temporary, os.open, temporary,
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        identity = _identity(_io("fstat", None, os.fstat, descriptor), temporary)
        _write_all(descriptor, js_utf8_encode(content),
                   zero_progress_error=MemoryPublicationPathError("helper-failed", "file write made no progress"))
        _io("fchmod", None, os.fchmod, descriptor, 0o600)
        _io("fsync", None, os.fsync, descriptor)
        _assert_current(descriptor, temporary, identity)
        _assert_parent(parent, parent_fd, parent_identity)
        staged_stat = _io("fstat", None, os.fstat, descriptor)
        staged = {
            "directory": {"path": str(parent), "realPath": str(parent),
                          "identity": {"dev": parent_stat.st_dev, "ino": parent_stat.st_ino}},
            "temporaryBasename": temporary.name,
            "identity": {
                "dev": staged_stat.st_dev, "ino": staged_stat.st_ino, "mode": stat.S_IMODE(staged_stat.st_mode),
                "nlink": staged_stat.st_nlink, "size": staged_stat.st_size,
                "uid": staged_stat.st_uid, "gid": staged_stat.st_gid,
                "mtimeNs": staged_stat.st_mtime_ns, "ctimeNs": staged_stat.st_ctime_ns,
            },
        }
        try:
            _io("link", temporary, os.link, temporary, target, destination=target)
        except OSError as error:
            if _code(error) != "EEXIST":
                raise
        else:
            linked = True
            publication = {"status": "published", "staged": staged, "basename": target.name, "overwrite": False}
        _io("unlink", temporary, os.unlink, temporary)
        if linked:
            _assert_current(descriptor, target, identity)
            # Native retained-directory staging ignores only EPERM here. Unlike
            # append/replacement compatibility helpers, other failures surface
            # the already-published receipt to the real bootstrap caller.
            try:
                _io("fsync", None, os.fsync, parent_fd)
            except OSError as error:
                if _code(error) != "EPERM":
                    raise
            _assert_parent(parent, parent_fd, parent_identity)
            _assert_current(descriptor, target, identity)
    except BaseException as error:
        failure = (MemoryPublicationPathError(
            error.code if isinstance(error, MemoryPublicationPathError) else "helper-failed",
            "staged file publish failed", error,
            details={"phase": "publish", "publication": publication},
        ) if linked else error)
    finally:
        if identity is not None:
            try:
                current = _io("lstat", temporary, os.lstat, temporary)
                if stat.S_ISREG(current.st_mode) and current.st_nlink == 1 and (current.st_dev, current.st_ino) == identity:
                    _io("unlink", temporary, os.unlink, temporary)
            except OSError as error:
                if _code(error) != "ENOENT" and failure is None:
                    failure = error
        for opened in (descriptor, parent_fd):
            if opened is not None:
                try:
                    _io("close", None, os.close, opened)
                except OSError as error:
                    if failure is None:
                        failure = error
    if failure is not None:
        converted = _root_write_error(failure)
        underlying = getattr(converted, "cause", None) if isinstance(converted, MemoryPublicationPathError) else converted
        if isinstance(underlying, BaseException) and _code(underlying) in {"EPERM", "EXDEV", "ENOTSUP", "EOPNOTSUPP", "ENOSYS"}:
            unsupported = RuntimeError(
                "Workspace filesystem does not support atomic bootstrap publication. "
                "Use a workspace on a filesystem with hard-link support."
            )
            unsupported.name, unsupported.cause = "Error", converted
            raise unsupported from converted
        if converted is failure:
            raise failure
        raise converted from failure
    return linked


def commit_memory_content(
    path: Path, *, content: str | None, expected_content: str | None = None,
    expected_hash: str | None = None, conflict_message: str | None = None,
    temp_prefix: str = ".fs-safe-replace", before_publish: Callable[[], None] | None = None,
    allow_in_place_fallback: bool = False,
) -> None:
    """Publish one checked replacement; only promotion opts into in-place repair."""
    path = Path(path)
    if not temp_prefix or temp_prefix in {".", ".."} or any(char in temp_prefix for char in "/\\\x00"):
        raise ValueError("Atomic replace temp prefix must be a safe path segment")
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(os.path.abspath(path), threading.RLock())
    with lock:
        _commit(path, content, expected_content, expected_hash, conflict_message, temp_prefix, before_publish,
                allow_in_place_fallback)


def _write_existing_in_place(path: Path, expected: str, content: str, conflict_message: str) -> bool:
    if _read_content(path) != expected:
        raise MemoryWriteConflictError(conflict_message)
    try:
        descriptor = _io("open", path, os.open, path, os.O_RDWR)
    except OSError:
        return False
    try:
        try:
            replacement = js_utf8_encode(content)
            _write_all(descriptor, replacement)
            _io("ftruncate", None, os.ftruncate, descriptor, len(replacement))
            _io("fsync", None, os.fsync, descriptor)
            return True
        except BaseException:
            try:
                original = memoryview(js_utf8_encode(expected))
                offset = 0
                while offset < len(original):
                    written = _io("write", None, os.pwrite, descriptor, original[offset:], offset)
                    if written <= 0:
                        raise OSError(errno.EIO, "write made no progress")
                    offset += written
                _io("ftruncate", None, os.ftruncate, descriptor, len(original))
                _io("fsync", None, os.fsync, descriptor)
            except BaseException as restore:
                error = RuntimeError(f"{path.name} in-place write failed and restoring the original content also failed")
                error.name, error.cause = "Error", restore
                raise error from restore
            raise
    finally:
        _io("close", None, os.close, descriptor)


def _commit(path, content, expected_content, expected_hash, conflict_message, temp_prefix, before_publish,
            allow_in_place_fallback):
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
        _write_all(descriptor, js_utf8_encode(content))
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
        if (allow_in_place_fallback and expected_content is not None
                and _code(failure) in {"EACCES", "EPERM", "EEXIST", "EROFS"}
                and _write_existing_in_place(path, expected_content, content, conflict_message)):
            return
        if publication in {"uncertain", "committed"}:
            raise MemoryAtomicPublicationError(publication, failure) from failure
        raise failure
