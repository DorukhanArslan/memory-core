"""Cooperative cancellation for work that a caller may stop waiting for.

The port's stand-in for the ``AbortSignal`` OpenClaw hands to
``manager.search`` (``extensions/memory-core/src/tools.ts``
``runMemorySearchToolWithDeadline``): when the deadline fires, the caller
aborts the signal, listeners run (the SQLite store interrupts its open
connection) and the worker stops at its next checkpoint instead of finishing
work nobody will read.
"""

from __future__ import annotations

import threading
from collections.abc import Callable


class OperationAbortedError(RuntimeError):
    """Raised at a checkpoint after the signal was aborted."""

    name = "Error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CancellationSignal:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reason: object = None
        self._aborted = False
        self._listeners: list[Callable[[], None]] = []

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def reason(self) -> object:
        return self._reason

    def abort(self, reason: object = None) -> None:
        with self._lock:
            if self._aborted:
                return
            self._reason = reason
            self._aborted = True
            listeners, self._listeners = self._listeners, []
        for listener in listeners:
            try:
                listener()
            except Exception:
                # Best-effort cleanup must not mask the abort itself.
                pass

    def throw_if_aborted(self) -> None:
        if self._aborted:
            raise resolve_memory_search_abort_error(self)

    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Call ``callback`` on abort (now, if already aborted); returns a remover."""
        with self._lock:
            if not self._aborted:
                self._listeners.append(callback)
                registered = True
            else:
                registered = False
        if not registered:
            try:
                callback()
            except Exception:
                pass

        def remove() -> None:
            with self._lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)

        return remove


def resolve_memory_search_abort_error(signal: CancellationSignal) -> BaseException:
    """Preserve an exception reason; strings and other values use native errors."""
    reason = signal.reason
    if isinstance(reason, BaseException):
        return reason
    return OperationAbortedError(reason if isinstance(reason, str) else "memory search aborted")
