"""Deadline ownership shared by memory tools, independent of provider failures.

The host can supply monotonic time, a timer scheduler and an event wait primitive.
Defaults use real daemon timers and worker threads; controlled hosts exercise the
same owner with their scheduler. Only this module records deadline error identity.
"""

from __future__ import annotations

import math
import threading
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from memory_core.cancellation import (
    CancellationSignal, OperationAbortedError, resolve_memory_search_abort_error,
)
from memory_core.tools.common import format_error_message

DEFAULT_MEMORY_TOOL_TIMEOUT_MS = 30_000
T = TypeVar("T")
_identity_lock = threading.RLock()
_owned_errors: dict[int, weakref.ReferenceType[BaseException]] = {}
_deadline_checks: dict[int, tuple[weakref.ReferenceType[CancellationSignal], Callable[[], None]]] = {}


def create_memory_search_deadline_error(message: str) -> OperationAbortedError:
    error = OperationAbortedError(message)
    identity = id(error)

    def discard(reference: weakref.ReferenceType[BaseException]) -> None:
        with _identity_lock:
            if _owned_errors.get(identity) is reference:
                _owned_errors.pop(identity, None)

    with _identity_lock:
        _owned_errors[identity] = weakref.ref(error, discard)
    return error


def is_memory_search_deadline_error(error: object) -> bool:
    with _identity_lock:
        reference = _owned_errors.get(id(error))
        return reference is not None and reference() is error


def _clock_ms() -> float:
    return time.monotonic() * 1000


def _schedule(delay_ms: float, callback: Callable[[], None]) -> Callable[[], None]:
    timer = threading.Timer(max(0, delay_ms) / 1000, callback)
    timer.daemon = True
    timer.start()
    return timer.cancel


def _wait(event: threading.Event, seconds: float | None) -> bool:
    return event.wait(seconds)


@dataclass(frozen=True)
class MemoryToolDeadlineContext:
    """Trusted execution dependencies; ``clock`` and scheduled delays use milliseconds."""

    signal: CancellationSignal | None = None
    clock: Callable[[], float] = _clock_ms
    schedule: Callable[[float, Callable[[], None]], Callable[[], None]] = _schedule
    wait: Callable[[threading.Event, float | None], bool] = _wait


class MemorySearchDeadlineControl:
    """Balanced pause/resume fan-out for nested phases with their own budgets."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._depth = 0
        self._listeners: list[Callable[[str], None]] = []

    def report(self, action: str) -> None:
        with self._lock:
            if action == "pause":
                self._depth += 1
                if self._depth != 1:
                    return
            elif action == "resume":
                if self._depth == 0:
                    return
                self._depth -= 1
                if self._depth != 0:
                    return
            else:
                raise ValueError("deadline control action must be pause or resume")
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(action)

    def subscribe(self, listener: Callable[[str], None]) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)
            paused = self._depth > 0
        if paused:
            listener("pause")

        def remove() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return remove


class _DeadlineScope:
    def __init__(
        self, operation: str, context: MemoryToolDeadlineContext,
        timeout_ms: float, control: MemorySearchDeadlineControl | None,
        *, round_seconds: bool = False,
    ) -> None:
        if context.signal is not None and context.signal.aborted:
            raise resolve_memory_search_abort_error(context.signal)
        self.context = context
        self.signal = CancellationSignal()
        self.control = control if control is not None else MemorySearchDeadlineControl()
        seconds = math.floor(timeout_ms / 1000 + 0.5) if round_seconds else timeout_ms / 1000
        self.timeout_error = create_memory_search_deadline_error(
            f"{operation} timed out after {seconds:g}s"
        )
        self._lock = threading.RLock()
        self._remaining_ms = timeout_ms
        self._segment_started = context.clock()
        self._paused = False
        self._closed = False
        self._generation = 0
        self._cancel_timer: Callable[[], None] | None = None
        with _identity_lock:
            _deadline_checks[id(self.signal)] = (weakref.ref(self.signal), self.check)
        self._remove_control = self.control.subscribe(self._on_control)
        self._remove_parent = (
            context.signal.add_listener(self._parent_aborted) if context.signal is not None else None
        )
        with self._lock:
            if not self._paused and not self.signal.aborted:
                self._arm_timer()

    def _parent_aborted(self) -> None:
        self.signal.abort(resolve_memory_search_abort_error(self.context.signal))

    def _arm_timer(self) -> None:
        self._segment_started = self.context.clock()
        self._generation += 1
        generation = self._generation
        self._cancel_timer = self.context.schedule(
            self._remaining_ms, lambda: self._expire(generation),
        )

    def _expire(self, generation: int | None = None) -> None:
        with self._lock:
            if generation is not None and (
                generation != self._generation or self._paused or self._closed
            ):
                return
            if generation is not None:
                self._cancel_timer = None
        self.signal.abort(self.timeout_error)

    def check(self) -> None:
        with self._lock:
            expired = (not self.signal.aborted and not self._paused
                       and self.context.clock() - self._segment_started >= self._remaining_ms)
        if expired:
            self._expire()

    def _on_control(self, action: str) -> None:
        expire = False
        with self._lock:
            if self.signal.aborted:
                return
            if action == "pause":
                self._paused = True
                self._generation += 1
                if self._cancel_timer is not None:
                    self._cancel_timer()
                    self._cancel_timer = None
                self._remaining_ms = max(
                    0, self._remaining_ms - (self.context.clock() - self._segment_started)
                )
                expire = self._remaining_ms == 0
            else:
                self._paused = False
                self._arm_timer()
        if expire:
            self._expire()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._generation += 1
            if self._cancel_timer is not None:
                self._cancel_timer()
                self._cancel_timer = None
        self._remove_control()
        if self._remove_parent is not None:
            self._remove_parent()
        with _identity_lock:
            entry = _deadline_checks.get(id(self.signal))
            if entry is not None and entry[0]() is self.signal:
                _deadline_checks.pop(id(self.signal), None)


def _check_signal_deadline(signal: CancellationSignal) -> None:
    with _identity_lock:
        entry = _deadline_checks.get(id(signal))
    if entry is not None and entry[0]() is signal:
        entry[1]()


@dataclass(frozen=True)
class DeadlineOutcome:
    status: str
    value: Any = None
    error: str | None = None
    code: str | None = None
    deadline: bool = False
    exception: BaseException | None = None


class SignalWorker:
    """Race a real worker against one existing signal; settle before later joins."""

    def __init__(
        self, signal: CancellationSignal, run: Callable[[CancellationSignal], Any], *,
        context: MemoryToolDeadlineContext | None = None,
        on_settle: Callable[[], None] | None = None,
    ) -> None:
        self.signal = signal
        self._context = context or MemoryToolDeadlineContext()
        self._lock = threading.RLock()
        self._done = threading.Event()
        self._outcome: DeadlineOutcome | None = None
        self._on_settle = on_settle
        self._remove_abort: Callable[[], None] | None = None

        def on_abort() -> None:
            self._settle(error=resolve_memory_search_abort_error(signal))

        self._remove_abort = signal.add_listener(on_abort)
        if self._outcome is not None:
            self._remove_abort()
            return

        def work() -> None:
            try:
                value = run(signal)
                _check_signal_deadline(signal)
                if signal.aborted:
                    self._settle(error=resolve_memory_search_abort_error(signal))
                else:
                    self._settle(value=value)
            except BaseException as error:
                self._settle(error=error)

        threading.Thread(target=work, name="memory-corpus-worker", daemon=True).start()

    def _settle(self, *, value: Any = None, error: BaseException | None = None) -> None:
        from memory_core.tools.corpus import error_code

        with self._lock:
            if self._outcome is not None:
                return
            if error is None and self.signal.aborted:
                error = resolve_memory_search_abort_error(self.signal)
            self._outcome = (
                DeadlineOutcome(status="ok", value=value) if error is None else DeadlineOutcome(
                    status="unavailable", error=format_error_message(error), code=error_code(error),
                    deadline=is_memory_search_deadline_error(error), exception=error,
                )
            )
            if self._remove_abort is not None:
                self._remove_abort()
            if self._on_settle is not None:
                self._on_settle()
            self._done.set()

    def wait(self) -> DeadlineOutcome:
        while not self._done.is_set():
            self._context.wait(self._done, None)
        assert self._outcome is not None
        return self._outcome


def race_memory_corpus_signal(
    signal: CancellationSignal, run: Callable[[], T], *,
    context: MemoryToolDeadlineContext | None = None,
) -> T:
    if signal.aborted:
        raise resolve_memory_search_abort_error(signal)
    outcome = SignalWorker(signal, lambda _signal: run(), context=context).wait()
    if outcome.exception is not None:
        raise outcome.exception
    return outcome.value


def run_memory_corpus_deadline(
    operation: str, run: Callable[[CancellationSignal, MemorySearchDeadlineControl], T], *,
    context: MemoryToolDeadlineContext | None = None,
    control: MemorySearchDeadlineControl | None = None,
) -> T:
    execution = context or MemoryToolDeadlineContext()
    scope = _DeadlineScope(operation, execution, DEFAULT_MEMORY_TOOL_TIMEOUT_MS, control)
    try:
        result = run(scope.signal, scope.control)
        if execution.signal is not None and execution.signal.aborted:
            raise resolve_memory_search_abort_error(execution.signal)
        already_aborted = scope.signal.aborted
        scope.check()
        if not already_aborted and scope.signal.aborted:
            raise scope.timeout_error
        return result
    finally:
        scope.close()


class DeadlineWorker:
    """One supervised worker with an absolute budget and immutable settled outcome."""

    def __init__(
        self, label: str, run: Callable[[CancellationSignal], Any], *,
        context: MemoryToolDeadlineContext | None = None, timeout_ms: float = 30_000,
        control: MemorySearchDeadlineControl | None = None,
    ) -> None:
        self._context = context or MemoryToolDeadlineContext()
        self._timeout_ms = timeout_ms
        self._scope = _DeadlineScope(label, self._context, timeout_ms, control, round_seconds=True)
        self.signal, self.control = self._scope.signal, self._scope.control
        self._worker = SignalWorker(
            self.signal, run, context=self._context, on_settle=self._scope.close,
        )

    def wait(self, timeout_ms: float | None = None) -> DeadlineOutcome:
        if timeout_ms is not None and timeout_ms != self._timeout_ms:
            raise ValueError("The worker's budget is fixed when it starts")
        return self._worker.wait()


def run_memory_search_with_deadline(
    timeout_ms: float, run: Callable[[CancellationSignal], T], *,
    context: MemoryToolDeadlineContext | None = None,
) -> T:
    """Supervise a search task, raising the actual owner or parent exception."""
    execution = context or MemoryToolDeadlineContext()
    outcome = DeadlineWorker(
        "memory_search", run, context=execution, timeout_ms=timeout_ms,
    ).wait()
    if execution.signal is not None and execution.signal.aborted:
        raise resolve_memory_search_abort_error(execution.signal)
    if outcome.exception is not None:
        raise outcome.exception
    return outcome.value
