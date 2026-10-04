"""Per-corpus outcomes of the memory tools (OpenClaw ``extensions/memory-core/src/memory-corpus.ts``).

``memory_get`` and ``memory_search`` read up to two corpora, the memory index
(``memory``) and the registered compiled-wiki supplements (``wiki``). Each read is
a :class:`CorpusAttempt`; :func:`compose_memory_corpus_metadata` turns the attempts
into the ``corpora`` / ``warning`` / ``error`` / ``timedOut`` fields the tool
results carry, so a failed corpus is reported instead of hidden by a successful one.

Deviation: upstream orders and labels supplements by plugin id; memory-core's
supplements are anonymous, so they keep the host's list order and a failure of more
than one is joined without a prefix.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from memory_core.tools.common import format_error_message

# memory/search-deadline.ts DEFAULT_MEMORY_SEARCH_TIMEOUT_MS.
MEMORY_CORPUS_TIMEOUT_MS = 30_000

T = TypeVar("T")


@dataclass(frozen=True)
class CorpusAttempt:
    """``MemoryCorpusAttempt``: ``outcome`` is ok, unavailable, partial or not-registered."""

    corpus: str
    outcome: str
    value: Any = None
    error: str | None = None
    code: str | None = None
    deadline: bool = False

    @property
    def failed(self) -> bool:
        return self.error is not None


@dataclass(frozen=True)
class CorpusFailure:
    """``MemoryCorpusFailure``: why a corpus was unavailable, kept by the search cooldown."""

    error: str
    deadline: bool = False
    code: str | None = None


def error_code(error: BaseException) -> str | None:
    """``extractErrorCode``: the error's own string ``code``, an errno name for an OS error."""
    import errno

    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code
    if isinstance(error, OSError) and error.errno in errno.errorcode:
        return errno.errorcode[error.errno]
    return None


def unavailable_corpus(
    corpus: str, value: Any, error: BaseException | str, *, deadline: bool = False
) -> CorpusAttempt:
    """``unavailableMemoryCorpus``."""
    return CorpusAttempt(
        corpus=corpus,
        outcome="unavailable",
        value=value,
        error=error if isinstance(error, str) else format_error_message(error),
        code=None if isinstance(error, str) else error_code(error),
        deadline=deadline,
    )


def attempt_corpus(corpus: str, unavailable_value: T, run: Callable[[], T]) -> CorpusAttempt:
    """``attemptMemoryCorpus`` without a signal: an exception is an unavailable corpus."""
    try:
        return CorpusAttempt(corpus=corpus, outcome="ok", value=run())
    except Exception as error:
        return unavailable_corpus(corpus, unavailable_value, error)


def settle_supplements(
    supplements: Sequence[Any],
    run: Callable[[Any], T],
    merge: Callable[[list[T]], T],
) -> CorpusAttempt:
    """``settleMemorySupplements``: run every supplement, keep the ones that succeeded."""
    if not supplements:
        return CorpusAttempt(corpus="wiki", outcome="not-registered")
    completed: list[T] = []
    failures: list[str] = []
    for supplement in supplements:
        try:
            completed.append(run(supplement))
        except Exception as error:
            failures.append(format_error_message(error))
    value = merge(completed)
    if not failures:
        return CorpusAttempt(corpus="wiki", outcome="ok", value=value)
    # A supplement's failure is the plugin's, never this tool's deadline.
    return CorpusAttempt(
        corpus="wiki", outcome="unavailable", value=value, error="; ".join(failures)
    )


def compose_memory_corpus_metadata(
    attempts: Sequence[CorpusAttempt], extra_warnings: Sequence[str] = ()
) -> dict[str, Any]:
    """``composeMemoryCorpusMetadata``: memory sorts before wiki."""
    ordered = sorted(attempts, key=lambda attempt: attempt.corpus == "wiki")
    warnings: list[str] = []
    for attempt in ordered:
        label = "Memory" if attempt.corpus == "memory" else "Wiki"
        if attempt.failed:
            warnings.append(f"{label} corpus {attempt.outcome}: {attempt.error}")
        elif attempt.outcome == "not-registered" and len(ordered) == 1:
            warnings.append(
                f"{label} corpus is not registered; results do not cover that requested corpus."
            )
    warnings.extend(extra_warnings)
    errors = [attempt.error for attempt in ordered if attempt.failed]
    metadata: dict[str, Any] = {
        "corpora": [
            {"corpus": a.corpus, "outcome": a.outcome, "error": a.error}
            if a.failed
            else {"corpus": a.corpus, "outcome": a.outcome}
            for a in ordered
        ]
    }
    if warnings:
        metadata["warning"] = " ".join(warnings)
    if errors:
        metadata["error"] = "; ".join(errors)
    if any(attempt.deadline for attempt in ordered):
        metadata["timedOut"] = True
        metadata["timeoutMs"] = MEMORY_CORPUS_TIMEOUT_MS
    return metadata
