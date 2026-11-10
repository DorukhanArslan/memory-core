"""Optional per-session work with foreground priority and real settlement custody.

This is an in-process coordinator. It shares the exact conversation lane key
across managed owners; it does not claim cross-process execution authority.
Cancellation withdraws the model callback once. The separate settlement task
keeps every accepted physical dispatch until its actual completion.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from concurrent.futures import Future
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
import threading
import time
from typing import Any

from memory_core.tools.common import format_error_message


LaneKey = tuple[str, str, str]
_guard = threading.RLock()
_sessions: dict[LaneKey, _Session] = {}
_sequence = 0


@dataclass
class _Session:
    loop: asyncio.AbstractEventLoop
    available: asyncio.Event
    foreground: int = 0
    jobs: list[OptionalMaintenance] = field(default_factory=list)


def _session(key: LaneKey) -> _Session:
    loop = asyncio.get_running_loop()
    session = _sessions.get(key)
    if session is not None and session.loop is not loop:
        raise RuntimeError("This session has active optional maintenance in another event loop")
    if session is None:
        session = _Session(loop, asyncio.Event())
        session.available.set()
        _sessions[key] = session
    return session


def _release_session(key: LaneKey, session: _Session) -> None:
    if not session.foreground and not session.jobs and _sessions.get(key) is session:
        del _sessions[key]


class OptionalMaintenance:
    """One registered job; ``done`` resolves only after its settlement body exits."""

    def __init__(self, key: LaneKey, session: _Session, identifier: int) -> None:
        self.key, self.loop, self.identifier = key, session.loop, identifier
        self.cancel_requested = asyncio.Event()
        self.done: Future[Any] = Future()
        self.running = False
        self.state = "pending"
        self.outcome: Any = None
        self.error: BaseException | None = None
        self._session = session
        self._abort: Callable[[], Any] | None = None
        self._abort_called = False
        self._task: asyncio.Task[None] | None = None
        self._events: list[dict[str, Any]] = []
        self._record("pending")

    def _record(self, phase: str) -> None:
        self._events.append({"phase": phase, "atNs": str(time.monotonic_ns()),
                             "running": self.running, "cancelRequested": self.cancel_requested.is_set()})

    def bind_model_abort(self, abort: Callable[[], Any] | None) -> None:
        """Attach the actual provider task without exposing the settlement task."""
        with _guard:
            self._abort = abort
            self._abort_model()

    def _abort_model(self) -> None:
        if self.cancel_requested.is_set() and self._abort is not None and not self._abort_called:
            self._abort_called = True
            self._record("provider-abort-requested")
            self._abort()

    def request_cancel(self) -> None:
        def withdraw() -> None:
            with _guard:
                if self.done.done() or self.cancel_requested.is_set():
                    return
                self.cancel_requested.set()
                self._record("foreground-preemption-requested")
                self._session.available.set()
                self._abort_model()

        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is self.loop:
            withdraw()
        else:
            self.loop.call_soon_threadsafe(withdraw)

    async def join(self) -> Any:
        return await asyncio.shield(asyncio.wrap_future(self.done))

    def snapshot(self) -> dict[str, Any]:
        with _guard:
            return {"id": self.identifier, "state": self.state, "running": self.running,
                    "cancelRequested": self.cancel_requested.is_set(), "settled": self.done.done(),
                    "outcome": _receipt(self.outcome), "error": _receipt(self.error),
                    "events": deepcopy(self._events)}


def _receipt(value: Any) -> Any:
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": format_error_message(value)}
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _receipt(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {key: _receipt(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_receipt(item) for item in value]
    return deepcopy(value)


class ForegroundReservation:
    def __init__(self, key: LaneKey, session: _Session, jobs: tuple[OptionalMaintenance, ...]) -> None:
        self.key, self.session, self.jobs = key, session, jobs
        self.released = False

    async def join_predecessors(self) -> None:
        for job in self.jobs:
            await job.join()

    def release(self) -> None:
        with _guard:
            if self.released:
                return
            self.released = True
            self.session.foreground -= 1
            if not self.session.foreground:
                self.session.available.set()
            _release_session(self.key, self.session)


def reserve_foreground(key: LaneKey) -> ForegroundReservation:
    """Reserve priority synchronously before either joining work or queueing a lane."""
    with _guard:
        session = _session(key)
        session.foreground += 1
        session.available.clear()
        jobs = tuple(session.jobs)
        reservation = ForegroundReservation(key, session, jobs)
        try:
            for job in jobs:
                job.request_cancel()
        except BaseException:
            reservation.release()
            raise
        return reservation


def schedule_optional(key: LaneKey, run: Callable[[OptionalMaintenance], Awaitable[Any]],
                      settled: Callable[[OptionalMaintenance], None]) -> OptionalMaintenance:
    """Register before returning; a task cannot enter while foreground is reserved."""
    global _sequence
    with _guard:
        session = _session(key)
        _sequence += 1
        job = OptionalMaintenance(key, session, _sequence)
        session.jobs.append(job)

    async def drive() -> None:
        try:
            while True:
                with _guard:
                    if job.cancel_requested.is_set():
                        job.state = "cancelled"
                        return
                    if not session.foreground:
                        job.running = True
                        job.state = "running"
                        job._record("started")
                        break
                    session.available.clear()
                await session.available.wait()
            job.outcome = await run(job)
            job.state = "cancelled" if (job.cancel_requested.is_set()
                or getattr(job.outcome, "cancelled", False)) else "completed"
        except BaseException as error:
            job.error = error
            job.state = "cancelled" if isinstance(error, asyncio.CancelledError) else "failed"
        finally:
            with _guard:
                job.running = False
            try:
                settled(job)
            finally:
                with _guard:
                    session.jobs.remove(job)
                    _release_session(key, session)
                    job._record("settled")
                    job.done.set_result(job.outcome)

    try:
        job._task = session.loop.create_task(drive())
    except BaseException:
        with _guard:
            session.jobs.remove(job)
            _release_session(key, session)
        raise
    return job
