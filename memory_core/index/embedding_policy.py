"""Provider dispatch policy from the original memory manager.

The provider owns embedding calculation. This module supplies the conservative
8,000-byte request budget, bounded retry profiles and recursive batch splitting;
the index owner remains responsible for accepting successful results.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
import math
from random import SystemRandom
import re
import threading
import time
from typing import Literal, TypeVar

from memory_core.bootstrap._js import JS_SPACE, js_trim, js_utf8_encode
from memory_core.cancellation import CancellationSignal
from memory_core.tools.common import format_error_message

T = TypeVar("T")
R = TypeVar("R")
Profile = Literal["index", "query"]
MEMORY_EMBEDDING_BATCH_BYTES = 8_000
_MAX_SAFE_INTEGER = 2**53 - 1
_RATE_LIMIT = re.compile(r"rate[_ ]limit|too many requests|\b429\b|resource has been exhausted|tokens per day", re.I | re.ASCII)
_SERVICE = re.compile(r"\b5[0-9][0-9]\b|cloudflare", re.I | re.ASCII)
_TRANSPORT = re.compile(
    r"fetch failed|other side closed|ECONNRESET|ECONNREFUSED|ETIMEDOUT|EPIPE|UND_ERR_|socket hang up|"
    r"socket terminated|network error|read ECONN|timed out|connection (?:reset|refused|aborted|timed out)|"
    r"EHOSTUNREACH|ENETUNREACH|ECONNABORTED|EAI_AGAIN", re.I | re.ASCII,
)
_SPLIT = re.compile(
    r"request_headers_too_large|request header fields too large|other side closed|ECONNRESET|EPIPE|UND_ERR_SOCKET|"
    r"socket hang up|socket terminated|read ECONN|connection (?:reset|aborted)|"
    r"\bembeddings (?:api input limit exceeded:\s*max\s+[0-9]+\s*,\s*got\s+[0-9]+|max input length is\s+[0-9]+)\b|"
    r"\bbatch size is invalid,?\s+it should not be larger than\s+[0-9]+\b|"
    r"\binput array max\s+[0-9]+(?=\s*(?:[\"'}]|$))".replace(r"\s", JS_SPACE), re.I | re.ASCII,
)


def build_memory_embedding_batches(items: Sequence[T], text: Callable[[T], str],
                                    max_bytes: int = MEMORY_EMBEDDING_BATCH_BYTES) -> list[list[T]]:
    batches: list[list[T]] = []
    current: list[T] = []
    size = 0
    for item in items:
        estimate = len(js_utf8_encode(text(item)))
        if current and size + estimate > max_bytes:
            batches.append(current)
            current, size = [], 0
        current.append(item)
        size += estimate
    if current:
        batches.append(current)
    return batches


def is_splittable_memory_embedding_batch_error(message: str) -> bool:
    return _SPLIT.search(message) is not None


def _retry_budget(profile: Profile, error: Exception) -> tuple[int, int, int, int | None] | None:
    hint = getattr(error, "retryAfterMs", None)
    hint = (int(hint) if isinstance(hint, (int, float)) and not isinstance(hint, bool)
            and 0 <= hint <= _MAX_SAFE_INTEGER and int(hint) == hint else None)
    def integer(value: object) -> bool:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        try:
            return math.isfinite(value) and int(value) == value
        except OverflowError:
            return False

    # HTTPStatusError exposes the provider's explicit status on its response.
    # It takes precedence over retry-like words in a permanent 4xx body.
    response_status = getattr(getattr(error, "response", None), "status_code", None)
    status = next((value for value in (getattr(error, "status", None), getattr(error, "statusCode", None), response_status)
                   if integer(value)), None)
    permanent = any(isinstance(value := getattr(error, name, None), str)
                    and js_trim(value).lower() in {"quota_exceeded", "insufficient_quota"}
                    for name in ("errorCode", "code", "errorType"))
    if permanent and hint is None:
        return None
    short = (3, 500, 8_000, None)
    rate = (5, 5_000, 60_000, hint) if profile == "index" else (3, 500, 8_000, hint)
    if status == 429:
        return rate
    if status is not None:
        return short if 500 <= status <= 599 else None
    message = format_error_message(error)
    if _TRANSPORT.search(message):
        return short
    if is_splittable_memory_embedding_batch_error(message):
        return None
    if _RATE_LIMIT.search(message):
        return rate
    return short if _SERVICE.search(message) else None


def _wait(delay_ms: float, signal: CancellationSignal | None) -> None:
    if signal is None:
        time.sleep(delay_ms / 1_000)
        return
    event = threading.Event()
    remove = signal.add_listener(event.set)
    try:
        event.wait(delay_ms / 1_000)
        signal.throw_if_aborted()
    finally:
        remove()


def run_memory_embedding_retry_loop(run: Callable[[], R], *, profile: Profile,
                                     signal: CancellationSignal | None = None,
                                     wait_for_retry: Callable[[float], None] | None = None,
                                     random: Callable[[], float] | None = None) -> R:
    if profile not in {"index", "query"}:
        raise ValueError("An index or query embedding retry profile is required")
    remaining_wait = math.inf if profile == "index" else 8_000
    sleep = wait_for_retry or (lambda delay: _wait(delay, signal))
    draw = random or SystemRandom().random
    errors: list[Exception] = []
    for attempt in range(1, 6 if profile == "index" else 4):
        if signal is not None:
            signal.throw_if_aborted()
        try:
            return run()
        except Exception as error:
            errors.append(error)
            budget = _retry_budget(profile, error)
            if signal is not None and signal.aborted:
                raise
            if budget is None or attempt >= budget[0]:
                if len(errors) > 1:
                    try:
                        error._memory_embedding_attempt_errors = tuple(errors)
                    except (AttributeError, TypeError):
                        pass
                raise
            _, base, cap, hint = budget
            delay_cap = 60_000 if profile == "index" else 8_000
            delay = max(500, hint) if hint is not None else max(500, min(cap, base * 2**(attempt - 1)))
            delay = min(delay, delay_cap)
            positive = hint is not None and hint <= delay_cap
            fraction = draw()
            delay = math.ceil(delay * (1 + fraction * .2)) if positive else math.floor(delay * (1 + (fraction * 2 - 1) * .2) + .5)
            delay = min(max(delay, 500), delay_cap)
            bounded = min(delay, remaining_wait)
            remaining_wait -= bounded
            sleep(bounded)
    raise AssertionError("The embedding retry loop exhausted without an outcome")


def run_memory_embedding_batch_retry_with_split(items: list[T], run: Callable[[list[T]], list[R]], *,
                                                on_success: Callable[[list[T], list[R]], None]) -> list[R]:
    try:
        result = run_memory_embedding_retry_loop(lambda: run(items), profile="index")
    except Exception as error:
        if len(items) <= 1 or not is_splittable_memory_embedding_batch_error(format_error_message(error)):
            raise
        split_at = math.ceil(len(items) / 2)
        left = run_memory_embedding_batch_retry_with_split(items[:split_at], run, on_success=on_success)
        right = run_memory_embedding_batch_retry_with_split(items[split_at:], run, on_success=on_success)
        return left + right
    on_success(items, result)
    return result
