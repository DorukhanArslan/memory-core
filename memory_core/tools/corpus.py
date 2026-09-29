"""Per-corpus outcomes of the memory tools (``extensions/memory-core/src/memory-corpus.ts``).

A tool call that covers more than one corpus (``memory`` and the ``wiki`` supplements) reports
one attempt per corpus instead of failing as a whole (d46f9ebf2b2 #147702, v2026.9.6):

- :class:`MemoryCorpusAttempt`: ``ok``, ``unavailable`` (with the error, its code and whether
  it was this tool's own deadline), ``partial`` (a deadline that left usable results) or
  ``not-registered`` (no supplement exists);
- :func:`compose_memory_corpus_metadata`: the ``corpora``/``warning``/``error``/``timedOut``
  fields a result carries (``composeMemoryCorpusMetadata``);
- :class:`MemoryCorpusDeadline` / :func:`run_memory_corpus_deadline`: the 30 s deadline of one
  call (``runMemoryCorpusDeadline``, ``memory/search-deadline.ts``); a corpus task that does not
  finish in time fails with the deadline error, which is recognised by its type, never by its
  text (``isMemorySearchDeadlineError``: a provider may emit the same words);
- :func:`search_memory_corpus_supplements` / :func:`read_memory_corpus_supplements`: the settle
  step over the registered supplements for a ``memory_search`` or a ``memory_get`` call
  (``settleMemorySupplements`` + ``searchMemoryCorpusSupplements`` /
  ``readMemoryCorpusSupplements``).

Deviations, documented in docs/parity_matrix.md (``memory_get`` row): Python supplements have no
``pluginId`` and keep memory-core's ``MemoryCorpusSupplement`` protocol (decision D7 of
docs/upstream_port_v2026_9_6.md), so the settle step keeps the caller's order instead of sorting
by plugin id and joins several failures with ``; `` without the ``<pluginId>: `` labels; a
supplement search receives memory-core's ``max_results`` (an int, ``max(1, maxResults ?? 10)``)
and the requested corpus instead of upstream's optional ``maxResults`` and agent context; a
supplement read returns its result re-sliced by memory-core (``memory_get``). The deadline's
pause/resume for a managed local embedding service is not ported (memory-core has none), and no
caller ``AbortSignal`` exists in the Python API.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from memory_core.cancellation import CancellationSignal
from memory_core.project_name import DIST_NAME
from memory_core.supplements import (
    MemoryCorpusResult,
    MemoryCorpusSupplement,
    sort_corpus_results,
)
from memory_core.tools._memory_tool_constants import (
    DEFAULT_MEMORY_SEARCH_TIMEOUT_MS,
    MEMORY_CORPUS_FAILURE_WARNING_TEMPLATE,
    MEMORY_CORPUS_MEMORY_LABEL,
    MEMORY_CORPUS_NOT_REGISTERED_WARNING_TEMPLATE,
    MEMORY_CORPUS_SUPPLEMENT_CONCURRENCY,
    MEMORY_CORPUS_SUPPLEMENT_DEFAULT_MAX_RESULTS,
    MEMORY_CORPUS_TIMEOUT_TEMPLATE,
    MEMORY_CORPUS_WIKI_LABEL,
)
from memory_core.tools.common import extract_error_code, format_error_message

_T = TypeVar("_T")

MemoryCorpus = Literal["memory", "wiki"]
_UNSET = object()
MemoryCorpusOutcome = Literal["ok", "unavailable", "partial", "not-registered"]


class MemorySearchDeadlineError(Exception):
    """This tool's own deadline (``createMemorySearchDeadlineError``, search-deadline.ts:18-22).

    Only :class:`MemoryCorpusDeadline` creates one; an error of another type with the same text
    (a provider's own timeout) is not a deadline.
    """


def is_memory_search_deadline_error(error: object) -> bool:
    """``isMemorySearchDeadlineError`` (search-deadline.ts:30-32), by type instead of by a
    WeakSet of instances."""
    return isinstance(error, MemorySearchDeadlineError)


@dataclass(frozen=True)
class MemoryCorpusAttempt:
    """One corpus of a tool call (memory-corpus.ts:29-40 ``MemoryCorpusAttempt``).

    ``error``, ``code`` and ``deadline`` are set for ``unavailable`` and ``partial``;
    ``value`` is unset for ``not-registered``.
    """

    corpus: MemoryCorpus
    outcome: MemoryCorpusOutcome
    value: Any = None
    error: str | None = None
    code: str | None = None
    deadline: bool = False

    @property
    def failed(self) -> bool:
        # `"error" in attempt` upstream: unavailable and partial attempts carry an error.
        return self.outcome in ("unavailable", "partial")


def unavailable_memory_corpus(
    corpus: MemoryCorpus, value: Any, error: BaseException, deadline: bool | None = None
) -> MemoryCorpusAttempt:
    """``unavailableMemoryCorpus`` (memory-corpus.ts:49-64): the deadline flag is taken from the
    error object while it is still here, before its text is flattened."""
    return MemoryCorpusAttempt(
        corpus=corpus,
        outcome="unavailable",
        value=value,
        error=format_error_message(error),
        code=extract_error_code(error),
        deadline=is_memory_search_deadline_error(error) if deadline is None else deadline,
    )


class MemoryCorpusDeadline:
    """The deadline of one tool call (``runMemoryCorpusDeadline``, memory-corpus.ts:111-189).

    :meth:`race` runs one corpus task on a worker thread and waits no longer than the time
    left; when the time is up the call's :class:`CancellationSignal` is aborted (the SQLite
    store interrupts its statement) and the task fails with the deadline error
    ``<operation> timed out after 30s``. A task that finishes after the deadline passed (a
    synchronous database call the timer could not interrupt) fails the same way
    (``checkDeadline``).
    """

    def __init__(
        self,
        operation: str,
        *,
        timeout_ms: int = DEFAULT_MEMORY_SEARCH_TIMEOUT_MS,
        clock: Callable[[], float] = time.monotonic,
        wait_seconds: Callable[[float], float] | None = None,
    ) -> None:
        self.operation = operation
        self.timeout_ms = timeout_ms
        self.signal = CancellationSignal()
        self.timeout_error = MemorySearchDeadlineError(
            MEMORY_CORPUS_TIMEOUT_TEMPLATE.format(
                operation=operation, seconds=_js_seconds(timeout_ms)
            )
        )
        self._clock = clock
        self._started = clock()
        # How long a race waits for the remaining budget; tests shorten it.
        self._wait_seconds = wait_seconds or (lambda remaining: remaining)

    def remaining_seconds(self) -> float:
        return max(0.0, self.timeout_ms / 1000 - (self._clock() - self._started))

    def expire(self) -> None:
        self.signal.abort(str(self.timeout_error))

    def check(self) -> None:
        # checkDeadline: an overdue deadline expires even when no timer fired.
        if not self.signal.aborted and self.remaining_seconds() <= 0:
            self.expire()

    def race(self, task: Callable[[], _T]) -> _T:
        """``raceMemoryCorpusSignal`` (memory-corpus.ts:66-87)."""
        if self.signal.aborted:
            raise self.timeout_error
        box: dict[str, Any] = {}
        done = threading.Event()

        def worker() -> None:
            try:
                box["value"] = task()
            except BaseException as error:  # reported to the attempt
                box["error"] = error
            finally:
                done.set()

        threading.Thread(target=worker, name=f"{DIST_NAME}-memory-corpus", daemon=True).start()
        if not done.wait(self._wait_seconds(self.remaining_seconds())):
            self.expire()
            raise self.timeout_error
        if "error" in box:
            raise box["error"]
        self.check()
        if self.signal.aborted:
            raise self.timeout_error
        return box["value"]


def _js_seconds(timeout_ms: int) -> str:
    # `${DEFAULT_MEMORY_SEARCH_TIMEOUT_MS / 1000}`: JavaScript prints 30, not 30.0.
    seconds = timeout_ms / 1000
    return str(int(seconds)) if float(seconds).is_integer() else repr(seconds)


def run_memory_corpus_deadline(
    operation: str,
    run: Callable[[MemoryCorpusDeadline], _T],
    *,
    timeout_ms: int = DEFAULT_MEMORY_SEARCH_TIMEOUT_MS,
    wait_seconds: Callable[[float], float] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> _T:
    """``runMemoryCorpusDeadline``: run ``run`` under one deadline.

    The corpus tasks inside ``run`` race the deadline (:meth:`MemoryCorpusDeadline.race`) and
    report its expiry as an ``unavailable`` attempt, so ``run`` normally returns. When ``run``
    returns with the deadline already overdue but not yet expired, the call fails with the
    deadline error, as upstream (memory-corpus.ts:170-180).
    """
    deadline = MemoryCorpusDeadline(
        operation, timeout_ms=timeout_ms, clock=clock, wait_seconds=wait_seconds
    )
    result = run(deadline)
    already_aborted = deadline.signal.aborted
    deadline.check()
    if not already_aborted and deadline.signal.aborted:
        raise deadline.timeout_error
    return result


def attempt_memory_corpus(
    *,
    corpus: MemoryCorpus,
    deadline: MemoryCorpusDeadline,
    unavailable_value: Any,
    run: Callable[[], Any],
    get_partial_value: Callable[[], Any] | None = None,
) -> MemoryCorpusAttempt:
    """``attemptMemoryCorpus`` (memory-corpus.ts:89-109): ``ok`` with the value, else
    ``partial`` when a deadline left usable results, else ``unavailable``."""
    try:
        return MemoryCorpusAttempt(corpus=corpus, outcome="ok", value=deadline.race(run))
    except Exception as error:
        partial = (
            get_partial_value()
            if get_partial_value is not None and is_memory_search_deadline_error(error)
            else None
        )
        if partial is not None:
            attempt = unavailable_memory_corpus(corpus, partial, error)
            return MemoryCorpusAttempt(
                corpus=corpus,
                outcome="partial",
                value=partial,
                error=attempt.error,
                code=attempt.code,
                deadline=attempt.deadline,
            )
        return unavailable_memory_corpus(corpus, unavailable_value, error)


def run_concurrently(tasks: Sequence[Callable[[], _T]]) -> list[_T]:
    """``Promise.all`` over tasks that never raise (attempts catch their own errors)."""
    if len(tasks) <= 1:
        return [task() for task in tasks]
    with ThreadPoolExecutor(
        max_workers=len(tasks), thread_name_prefix=f"{DIST_NAME}-memory-corpora"
    ) as pool:
        return [future.result() for future in [pool.submit(task) for task in tasks]]


def _corpus_label(corpus: MemoryCorpus) -> str:
    return MEMORY_CORPUS_MEMORY_LABEL if corpus == "memory" else MEMORY_CORPUS_WIKI_LABEL


def compose_memory_corpus_metadata(
    attempts: Sequence[MemoryCorpusAttempt], extra_warnings: Sequence[str] = ()
) -> dict[str, Any]:
    """``composeMemoryCorpusMetadata`` (memory-corpus.ts:191-221).

    Attempts are ordered memory first (a stable sort), a failed attempt adds ``<Label> corpus
    <outcome>: <error>`` to the warning and its error to ``error`` (joined with ``; ``), a lone
    ``not-registered`` attempt warns that the requested corpus is not covered, and a deadline
    anywhere adds ``timedOut``/``timeoutMs``.
    """
    ordered = sorted(attempts, key=lambda attempt: attempt.corpus == "wiki")
    warnings: list[str] = []
    for attempt in ordered:
        label = _corpus_label(attempt.corpus)
        if attempt.failed:
            warnings.append(
                MEMORY_CORPUS_FAILURE_WARNING_TEMPLATE.format(
                    label=label, outcome=attempt.outcome, error=attempt.error
                )
            )
        elif attempt.outcome == "not-registered" and len(ordered) == 1:
            warnings.append(MEMORY_CORPUS_NOT_REGISTERED_WARNING_TEMPLATE.format(label=label))
    warnings.extend(extra_warnings)
    errors = [attempt.error for attempt in ordered if attempt.failed]
    metadata: dict[str, Any] = {
        "corpora": [
            {"corpus": attempt.corpus, "outcome": attempt.outcome, "error": attempt.error}
            if attempt.failed
            else {"corpus": attempt.corpus, "outcome": attempt.outcome}
            for attempt in ordered
        ]
    }
    if warnings:
        metadata["warning"] = " ".join(warnings)
    if errors:
        metadata["error"] = "; ".join(str(error) for error in errors)
    if any(attempt.deadline for attempt in ordered):
        metadata["timedOut"] = True
        metadata["timeoutMs"] = DEFAULT_MEMORY_SEARCH_TIMEOUT_MS
    return metadata


def settle_memory_supplements(
    *,
    supplements: Sequence[MemoryCorpusSupplement],
    deadline: MemoryCorpusDeadline,
    run: Callable[[MemoryCorpusSupplement], _T],
    merge: Callable[[list[_T]], _T],
) -> MemoryCorpusAttempt:
    """``settleMemorySupplements`` (memory-corpus.ts:223-273).

    No supplement: ``not-registered``. Otherwise every supplement runs (at most 4 at once) under
    the call's deadline; completed results survive a failure. One failing supplement makes the
    attempt ``unavailable`` with its error (never this tool's deadline); several are joined with
    ``; `` (unlabelled: Python supplements have no plugin id, D7). A deadline makes it
    ``unavailable`` with the deadline flag and the results completed so far.
    """
    if not supplements:
        return MemoryCorpusAttempt(corpus="wiki", outcome="not-registered")
    completed: list[Any] = [_UNSET] * len(supplements)
    failures: list[tuple[int, str]] = []
    lock = threading.Lock()

    def settle_all() -> None:
        def one(index: int) -> None:
            try:
                completed[index] = run(supplements[index])
            except Exception as error:
                with lock:
                    failures.append((index, format_error_message(error)))

        workers = min(MEMORY_CORPUS_SUPPLEMENT_CONCURRENCY, len(supplements))
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix=f"{DIST_NAME}-memory-supplement"
        ) as pool:
            list(pool.map(one, range(len(supplements))))

    def finished() -> list[_T]:
        return [result for result in completed if result is not _UNSET]

    try:
        deadline.race(settle_all)
    except Exception as error:
        return unavailable_memory_corpus("wiki", merge(finished()), error)
    value = merge(finished())
    if not failures:
        return MemoryCorpusAttempt(corpus="wiki", outcome="ok", value=value)
    ordered = [message for _, message in sorted(failures)]
    return MemoryCorpusAttempt(
        corpus="wiki", outcome="unavailable", value=value, error="; ".join(ordered), deadline=False
    )


def search_memory_corpus_supplements(
    *,
    supplements: Sequence[MemoryCorpusSupplement],
    deadline: MemoryCorpusDeadline,
    query: str,
    max_results: int | None,
    corpus: str,
) -> MemoryCorpusAttempt:
    """``searchMemoryCorpusSupplements`` (memory-corpus.ts:275-293): every supplement's hits in
    one list, score descending, then ``path.localeCompare``, cut to ``max(1, maxResults ?? 10)``.
    """
    limit = max(
        1, max_results if max_results is not None else MEMORY_CORPUS_SUPPLEMENT_DEFAULT_MAX_RESULTS
    )

    def search(supplement: MemoryCorpusSupplement) -> list[MemoryCorpusResult]:
        return list(supplement.search(query=query, max_results=limit, corpus=corpus))

    def merge(results: list[list[MemoryCorpusResult]]) -> list[MemoryCorpusResult]:
        return sort_corpus_results([hit for hits in results for hit in hits])[:limit]

    return settle_memory_supplements(
        supplements=supplements, deadline=deadline, run=search, merge=merge
    )


def read_memory_corpus_supplements(
    *,
    supplements: Sequence[MemoryCorpusSupplement],
    deadline: MemoryCorpusDeadline,
    lookup: str,
    corpus: str,
    to_read_result: Callable[[MemoryCorpusResult], dict[str, Any]],
) -> MemoryCorpusAttempt:
    """``readMemoryCorpusSupplements`` (memory-corpus.ts:295-317): the first supplement result
    that is not ``None``, in the caller's order, shaped by ``to_read_result`` (upstream returns
    ``{...details, status: "ok", text: content}``; memory-core's ``memory_get`` re-slices the
    content, D7)."""

    def read(supplement: MemoryCorpusSupplement) -> dict[str, Any] | None:
        result = supplement.get(path=lookup, corpus=corpus)
        return None if result is None else to_read_result(result)

    def first(results: list[dict[str, Any] | None]) -> dict[str, Any] | None:
        return next((result for result in results if result is not None), None)

    return settle_memory_supplements(
        supplements=supplements, deadline=deadline, run=read, merge=first
    )
