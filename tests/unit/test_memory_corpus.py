"""memory_core.tools.corpus: the deadline, attempts and supplement settle step.

The metadata shape is oracle-compared (memoryCorpusMetadata) and so are the memory_get corpus
reads with no, a missing or a failing supplement (memoryGet); these cover the timing and
concurrency rules a fixture cannot drive from the runner: the deadline expiry, a deadline error
known by its type, completed supplement results surviving a failure, and several failures.
"""

from __future__ import annotations

import threading
import time

import pytest

from memory_core.tools.corpus import (
    MemoryCorpusAttempt,
    MemorySearchDeadlineError,
    attempt_memory_corpus,
    compose_memory_corpus_metadata,
    is_memory_search_deadline_error,
    read_memory_corpus_supplements,
    run_memory_corpus_deadline,
    settle_memory_supplements,
)


def _short(remaining: float) -> float:
    # Wait 50 ms instead of the 30 s budget; the deadline error text stays the real one.
    return min(remaining, 0.05)


def test_a_task_past_the_deadline_is_an_unavailable_attempt_with_the_deadline_flag():
    release = threading.Event()

    def hang() -> str:
        release.wait(5)
        return "late"

    attempt = run_memory_corpus_deadline(
        "memory_get",
        lambda deadline: attempt_memory_corpus(
            corpus="memory", deadline=deadline, unavailable_value=None, run=hang
        ),
        wait_seconds=_short,
    )
    release.set()

    assert attempt == MemoryCorpusAttempt(
        corpus="memory",
        outcome="unavailable",
        value=None,
        error="memory_get timed out after 30s",
        code=None,
        deadline=True,
    )
    assert compose_memory_corpus_metadata([attempt])["timedOut"] is True
    assert compose_memory_corpus_metadata([attempt])["timeoutMs"] == 30_000


def test_a_provider_error_with_the_deadline_text_is_not_the_deadline():
    def provider() -> str:
        raise RuntimeError("memory_get timed out after 30s")

    attempt = run_memory_corpus_deadline(
        "memory_get",
        lambda deadline: attempt_memory_corpus(
            corpus="memory", deadline=deadline, unavailable_value=None, run=provider
        ),
    )

    assert (attempt.outcome, attempt.deadline) == ("unavailable", False)
    assert not is_memory_search_deadline_error(RuntimeError("memory_get timed out after 30s"))
    assert is_memory_search_deadline_error(MemorySearchDeadlineError("x"))
    assert "timedOut" not in compose_memory_corpus_metadata([attempt])


def test_a_deadline_with_usable_results_is_partial():
    def hang() -> list:
        time.sleep(1)
        return []

    attempt = run_memory_corpus_deadline(
        "memory_search",
        lambda deadline: attempt_memory_corpus(
            corpus="memory",
            deadline=deadline,
            unavailable_value=None,
            run=hang,
            get_partial_value=lambda: ["keyword hit"],
        ),
        wait_seconds=_short,
    )

    assert (attempt.outcome, attempt.value, attempt.deadline) == ("partial", ["keyword hit"], True)
    assert attempt.error == "memory_search timed out after 30s"


class _Supplement:
    def __init__(self, result=None, error: str | None = None, delay: float = 0.0):
        self.result, self.error, self.delay = result, error, delay

    def search(self, *, query: str, max_results: int, corpus: str) -> list:
        return []

    def get(self, *, path: str, corpus: str):
        time.sleep(self.delay)
        if self.error is not None:
            raise RuntimeError(self.error)
        return self.result


def test_completed_supplement_reads_survive_a_failing_one():
    found = {"corpus": "wiki", "path": "w.md", "content": "rule"}

    attempt = run_memory_corpus_deadline(
        "memory_get",
        lambda deadline: read_memory_corpus_supplements(
            supplements=[_Supplement(error="offline"), _Supplement(found)],
            deadline=deadline,
            lookup="w.md",
            corpus="wiki",
            to_read_result=lambda result: {"status": "ok", "text": result["content"]},
        ),
    )

    # memory-corpus.ts:260-272: the attempt is unavailable with the one failure, unlabelled,
    # and never this tool's deadline, but keeps the completed read.
    assert attempt == MemoryCorpusAttempt(
        corpus="wiki",
        outcome="unavailable",
        value={"status": "ok", "text": "rule"},
        error="offline",
        deadline=False,
    )


def test_several_failures_are_joined_in_the_callers_order_without_plugin_labels():
    attempt = run_memory_corpus_deadline(
        "memory_get",
        lambda deadline: settle_memory_supplements(
            supplements=[_Supplement(error="first", delay=0.02), _Supplement(error="second")],
            deadline=deadline,
            run=lambda supplement: supplement.get(path="x", corpus="wiki"),
            merge=lambda results: next((r for r in results if r is not None), None),
        ),
    )

    # Upstream labels each failure with its pluginId and sorts by it; Python supplements have
    # no plugin id (decision D7), so the errors keep the list order, unlabelled.
    assert (attempt.outcome, attempt.error) == ("unavailable", "first; second")


def test_at_most_four_supplements_run_at_once_and_none_registered_is_not_registered():
    running = 0
    peak = 0
    lock = threading.Lock()

    def run(_supplement) -> None:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.02)
        with lock:
            running -= 1

    attempt = run_memory_corpus_deadline(
        "memory_get",
        lambda deadline: settle_memory_supplements(
            supplements=[_Supplement() for _ in range(6)],
            deadline=deadline,
            run=run,
            merge=lambda results: None,
        ),
    )
    empty = run_memory_corpus_deadline(
        "memory_get",
        lambda deadline: settle_memory_supplements(
            supplements=[], deadline=deadline, run=run, merge=lambda results: None
        ),
    )

    assert (attempt.outcome, peak) == ("ok", 4)
    assert empty == MemoryCorpusAttempt(corpus="wiki", outcome="not-registered")


def test_a_run_that_returns_past_an_unexpired_deadline_fails_with_it():
    # memory-corpus.ts:175-179: a synchronous run that finished after the budget without the
    # timer firing still fails with the deadline.
    ticks = iter([0.0, 31.0])

    with pytest.raises(MemorySearchDeadlineError, match="^memory_get timed out after 30s$"):
        run_memory_corpus_deadline("memory_get", lambda deadline: "done", clock=lambda: next(ticks))
