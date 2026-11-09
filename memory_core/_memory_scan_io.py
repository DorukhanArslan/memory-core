"""Native system-error semantics at actual memory-discovery IO boundaries.

Node's original scan owner preserves the underlying system-error message and
cause. This bridge presents the same public IO facts while keeping the original
Python exception, traceback and OS attributes available as original_exception.
The error-message construction follows Node's attributed internal/errors owner;
its version/hash and factual labels are recorded in _memory_scan_error_facts.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path

from memory_core._memory_scan_error_facts import MESSAGES


class MemorySourceIOError(RuntimeError):
    """Public Node-compatible system error, with its original Python exception."""

    name = "Error"

    def __init__(self, original: OSError, operation: str, path: Path | None, code: str):
        self.original_exception = original
        self.errno = -abs(original.errno)
        self.code, self.syscall = code, operation
        if path is not None:
            self.path = str(path)
        super().__init__(f"{code}: {MESSAGES[code]}, {operation}" + (f" '{path}'" if path is not None else ""))


def bridge_scan_io_error(original: OSError, operation: str | None, path: Path) -> OSError | MemorySourceIOError:
    """Bridge standard OS errors only; supplied/custom Error messages stay literal."""
    if operation not in {"scandir", "lstat", "realpath"}:
        return original
    return bridge_memory_read_io_error(original, operation, path)


def bridge_memory_read_io_error(
    original: OSError, operation: str, path: Path | None,
) -> OSError | MemorySourceIOError:
    """Use the same attributed Node IO formatter at actual secure-read calls.

    Original Python exceptions remain available as ``original_exception`` rather
    than an extra public cause. Explicit policy errors attach this IO error as
    their native-shaped cause when the original owner does so.
    """
    number = original.errno
    code = errno.errorcode.get(number)
    if (operation not in {"scandir", "lstat", "realpath", "stat", "open", "fstat", "read", "close"} or type(number) is not int
            or code not in MESSAGES or isinstance(getattr(original, "code", None), str)
            or original.strerror != os.strerror(number)):
        return original
    return MemorySourceIOError(original, operation, path, code)
