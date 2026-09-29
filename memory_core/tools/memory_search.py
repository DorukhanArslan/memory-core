"""The ``memory_search`` tool (OpenClaw ``extensions/memory-core/src/tools.ts``).

``createMemorySearchTool`` reads its params before any search work
(``readStringParam`` / ``readPositiveIntegerParam`` / ``readFiniteNumberParam``,
``src/agents/tools/common.ts``). Invalid input raises
:class:`~memory_core.tools.common.MemoryToolInputError`; a host tool loop turns it
into ``{"status": "error", "tool": "memory_search", "error": ...}`` with
``to_tool_error()``.

``corpus`` is checked against the tool's closed enum ``memory|wiki|all|sessions``
(``readCorpusParam``, tools.ts:86-98): an unknown corpus raises
``corpus must be one of: memory, wiki, all, sessions``, and a blank or
non-string one reads as omitted. An omitted corpus searches every indexed
source and skips supplements.

The search runs under a 15 s deadline in a worker thread. On timeout the
caller gets the unavailable result at once and the worker's
:class:`~memory_core.cancellation.CancellationSignal` is aborted, which interrupts
the open SQLite statement and stops the store at its next checkpoint; the
abandoned worker only reads, so nothing is left half-written. A timeout or an
error puts the store on a process-wide 60 s cooldown during which memory is
not searched (``corpus=wiki`` never reads or records it; ``corpus=all`` still
searches supplements). Upstream keys the cooldown by
``agentId ?? agentSessionKey ?? "default"``, and an agent there owns exactly
one workspace and one index. memory-core hosts open many stores with the default
``agent_id`` (one per workspace or subject), so the key is that upstream value
scoped by the store's resolved path (documented deviation,
:func:`memory_search_tool_cooldown_key`).

An index whose stored identity is missing or no longer matches the store's
provider/model/settings returns the paused result (no cooldown) until
``SQLiteMemoryStore.reindex`` writes fresh metadata.
"""

from __future__ import annotations

import copy
import math
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_core.bootstrap._js import js_trim, locale_sort_key
from memory_core.cancellation import CancellationSignal
from memory_core.config import MemoryConfig
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.project_name import DIST_NAME
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.supplements import MemoryCorpusResult, MemoryCorpusSupplement, sort_corpus_results
from memory_core.tools.citations import citation_label, clamp_text, source_label
from memory_core.tools.common import (
    MemoryToolInputError,
    as_tool_params_record,
    format_error_message,
    read_corpus_param,
    read_finite_number_param,
    read_positive_integer_param,
    read_string_param,
)
from memory_core.tools._memory_tool_constants import MEMORY_SEARCH_CORPORA

MEMORY_SEARCH_TOOL_NAME = "memory_search"
# tools.ts createMemorySearchTool description (verbatim).
MEMORY_SEARCH_TOOL_DESCRIPTION = (
    "Mandatory recall step: semantically search MEMORY.md + memory/*.md (and optional "
    "session transcripts) before answering questions about prior work, decisions, dates, "
    "people, preferences, or todos. Optional `corpus=wiki` or `corpus=all` also searches "
    "registered compiled-wiki supplements. `corpus=memory` restricts hits to indexed memory "
    "files (excludes session transcript chunks from ranking). `corpus=sessions` restricts "
    "hits to indexed session transcripts (same visibility rules as session history tools). "
    "If response has disabled=true, memory retrieval is unavailable; you must tell the user "
    "and include the warning/action guidance."
)
# tools.shared.ts MemorySearchSchema as JSON Schema (TypeBox output;
# optionalFiniteNumberSchema is a plain number).
MEMORY_SEARCH_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "required": ["query"],
    "properties": {
        "query": {"type": "string"},
        "maxResults": {"type": "integer", "minimum": 1},
        "minScore": {"type": "number"},
        "corpus": {"type": "string", "enum": ["memory", "wiki", "all", "sessions"]},
    },
}

# tools.ts:49-50.
MEMORY_SEARCH_TOOL_TIMEOUT_MS = 15_000
MEMORY_SEARCH_TOOL_COOLDOWN_MS = 60_000

# Used when the caller omits maxResults/minScore. Upstream falls back to the
# agent's memorySearch.query config (6 / 0.35, src/agents/memory-search.ts);
# memory-core keeps its facade defaults (documented deviation).
DEFAULT_MEMORY_SEARCH_MAX_RESULTS = 5
DEFAULT_MEMORY_SEARCH_MIN_SCORE = 0.0
# tools.ts: `Math.max(1, maxResults ?? 10)` caps the merged memory+supplement list.
MEMORY_SEARCH_MERGE_DEFAULT_MAX_RESULTS = 10

# tools.shared.ts buildMemorySearchUnavailableResult (verbatim).
MEMORY_SEARCH_UNAVAILABLE_REASON = "memory search unavailable"
MEMORY_SEARCH_QUOTA_WARNING = (
    "Memory search is unavailable because the embedding provider quota is exhausted."
)
MEMORY_SEARCH_QUOTA_ACTION = "Top up or switch embedding provider, then retry memory_search."
MEMORY_SEARCH_PROVIDER_ERROR_WARNING = (
    "Memory search is unavailable due to an embedding/provider error."
)
MEMORY_SEARCH_PROVIDER_ERROR_ACTION = (
    "Check embedding provider configuration and retry memory_search."
)
# tools.ts:168-188 (the action names the runtime's reindex command, so it
# comes from RuntimeIdentity).
PAUSED_MEMORY_INDEX_WARNING = (
    "Tell the user: memory search is paused because the memory index was built with a "
    "different embedding provider/model/settings."
)
PAUSED_MEMORY_INDEX_REASON = "memory index identity is missing or mismatched"
_QUOTA_ERROR_RE = re.compile(r"insufficient_quota|quota|429")
_MISSING_SQLITE_RE = re.compile(r"missing node:sqlite|no such built-?in module: node:sqlite")


def memory_search_tool_definition() -> dict[str, Any]:
    """``{"name", "description", "parameters"}`` of the upstream ``memory_search`` tool.

    Same provider-neutral shape as ``MemoryCurator.tool_definitions()``; wrap it
    in the host's tool format. The description tells the model to pass on the
    unavailable/paused ``warning`` and ``action``. The schema's ``corpus`` enum
    is enforced by the host's argument validation, not by
    :func:`execute_memory_search_tool`.
    """
    return {
        "name": MEMORY_SEARCH_TOOL_NAME,
        "description": MEMORY_SEARCH_TOOL_DESCRIPTION,
        "parameters": copy.deepcopy(MEMORY_SEARCH_TOOL_PARAMETERS),
    }


def build_memory_search_unavailable_result(
    error: str | None,
    *,
    warning: str | None = None,
    action: str | None = None,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict:
    """``buildMemorySearchUnavailableResult`` (tools.shared.ts:112-152).

    The warning/action pair is picked from the lower-cased reason (quota,
    missing SQLite runtime, anything else) unless overridden. The SQLite pair
    names the runtime, so it comes from ``runtime_identity``.
    """
    reason = js_trim(error if error is not None else MEMORY_SEARCH_UNAVAILABLE_REASON)
    reason = reason or MEMORY_SEARCH_UNAVAILABLE_REASON
    normalized_reason = reason.lower()
    is_quota_error = _QUOTA_ERROR_RE.search(normalized_reason) is not None
    is_missing_sqlite = _MISSING_SQLITE_RE.search(normalized_reason) is not None
    if warning is None:
        if is_quota_error:
            warning = MEMORY_SEARCH_QUOTA_WARNING
        elif is_missing_sqlite:
            warning = runtime_identity.memory_search_sqlite_unavailable_warning
        else:
            warning = MEMORY_SEARCH_PROVIDER_ERROR_WARNING
    if action is None:
        if is_quota_error:
            action = MEMORY_SEARCH_QUOTA_ACTION
        elif is_missing_sqlite:
            action = runtime_identity.memory_search_sqlite_unavailable_action
        else:
            action = MEMORY_SEARCH_PROVIDER_ERROR_ACTION
    return {
        "results": [],
        "disabled": True,
        "unavailable": True,
        "error": reason,
        "warning": warning,
        "action": action,
        "debug": {"warning": warning, "action": action, "error": reason},
    }


def resolve_paused_memory_index_identity_reason(identity: Mapping[str, Any]) -> str | None:
    """``resolvePausedMemoryIndexIdentityReason`` (tools.ts:173-181)."""
    if identity.get("status") not in {"mismatched", "missing"}:
        return None
    reason = identity.get("reason")
    if isinstance(reason, str) and js_trim(reason):
        return js_trim(reason)
    return PAUSED_MEMORY_INDEX_REASON


def build_paused_memory_index_unavailable_result(
    reason: str, *, runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY
) -> dict:
    """``buildPausedMemoryIndexUnavailableResult`` (tools.ts:183-188)."""
    return build_memory_search_unavailable_result(
        reason,
        warning=PAUSED_MEMORY_INDEX_WARNING,
        action=runtime_identity.memory_search_paused_action,
        runtime_identity=runtime_identity,
    )


# Process-wide cooldowns (tools.ts:52 memorySearchToolCooldowns).
_cooldowns: dict[str, tuple[float, str]] = {}
_cooldowns_lock = threading.Lock()


def _now_ms() -> float:
    # Monotonic clock (upstream reads Date.now()); tests replace it.
    return time.monotonic() * 1000


def resolve_memory_search_tool_cooldown_key(
    *, agent_id: str | None, agent_session_key: str | None
) -> str:
    """tools.ts:76-81: ``agentId ?? agentSessionKey ?? "default"``."""
    if agent_id is not None:
        return agent_id
    if agent_session_key is not None:
        return agent_session_key
    return "default"


def memory_search_tool_cooldown_key(
    config: MemoryConfig, store: SQLiteMemoryStore, *, agent_session_key: str | None = None
) -> str:
    """The cooldown key ``memory_search`` reads and records for ``store``.

    Deviation from tools.ts:76-81, which keys by agent alone: upstream's agent
    stands for one workspace and one index, while memory-core keeps one index per
    store path, and every ``Memory.from_workspace()`` store defaults to
    ``agent_id="main"``. Keying by agent alone would let one workspace's
    provider error or timeout pause every other workspace in the process. The
    key is the store's resolved path (``config.resolved_store_path()`` for a
    store object without ``path``), a NUL separator, then
    :func:`resolve_memory_search_tool_cooldown_key`; stores that open the same
    index file share a cooldown.
    """
    store_path = getattr(store, "path", None)
    if store_path is None:
        store_path = config.resolved_store_path()
    agent_key = resolve_memory_search_tool_cooldown_key(
        agent_id=config.agent_id, agent_session_key=agent_session_key
    )
    return f"{Path(store_path).resolve()}\0{agent_key}"


def read_memory_search_tool_cooldown(key: str) -> str | None:
    """The cooldown error for ``key``, dropping it once expired (tools.ts:83-93)."""
    with _cooldowns_lock:
        entry = _cooldowns.get(key)
        if entry is None:
            return None
        until, error = entry
        if until <= _now_ms():
            del _cooldowns[key]
            return None
        return error


def memory_search_tool_cooldown_remaining(key: str) -> tuple[float, str] | None:
    """``(remaining_ms, error)`` of an active cooldown for ``key``, or ``None``.

    Read-only view for host status displays; like
    :func:`read_memory_search_tool_cooldown` it drops an expired entry.
    """
    with _cooldowns_lock:
        entry = _cooldowns.get(key)
        if entry is None:
            return None
        until, error = entry
        remaining = until - _now_ms()
        if remaining <= 0:
            del _cooldowns[key]
            return None
        return remaining, error


def record_memory_search_tool_cooldown(key: str, error: str) -> None:
    """tools.ts:95-100: pause memory search for ``key`` for 60 s."""
    with _cooldowns_lock:
        _cooldowns[key] = (_now_ms() + MEMORY_SEARCH_TOOL_COOLDOWN_MS, error)


def reset_memory_search_tool_cooldowns() -> None:
    """``testing.resetMemorySearchToolCooldowns`` (tools.ts:102-106)."""
    with _cooldowns_lock:
        _cooldowns.clear()


def _js_round(value: float) -> int:
    # Math.round: halves round towards +infinity.
    return math.floor(value + 0.5)


def _deadline_seconds(timeout_ms: int) -> float:
    # How long the caller waits; tests shorten it without changing the message.
    return timeout_ms / 1000


@dataclass(frozen=True)
class _DeadlineOutcome:
    status: str
    value: dict | None = None
    error: str | None = None


def _run_with_deadline(
    *, timeout_ms: int, run: Callable[[CancellationSignal], dict]
) -> _DeadlineOutcome:
    """``runMemorySearchToolWithDeadline`` (tools.ts:126-166) on a worker thread.

    Works from any thread and inside a running event loop (no signals, no
    loop access). On timeout the result is settled first, then the signal is
    aborted, so an abort-aware store cannot replace the stable timeout error.
    """
    timeout_message = f"memory_search timed out after {_js_round(timeout_ms / 1000)}s"
    signal = CancellationSignal()
    done = threading.Event()
    box: dict[str, Any] = {}

    def worker() -> None:
        try:
            box["value"] = run(signal)
        except BaseException as error:  # reported to the caller as unavailable
            box["error"] = error
        finally:
            done.set()

    threading.Thread(target=worker, name=f"{DIST_NAME}-memory-search", daemon=True).start()
    if not done.wait(_deadline_seconds(timeout_ms)):
        outcome = _DeadlineOutcome(status="unavailable", error=timeout_message)
        signal.abort(timeout_message)
        return outcome
    if "error" in box:
        return _DeadlineOutcome(status="unavailable", error=format_error_message(box["error"]))
    return _DeadlineOutcome(status="ok", value=box["value"])


@dataclass(frozen=True)
class MemorySearchParams:
    """Validated ``memory_search`` params; ``None`` means the caller omitted it."""

    query: str
    max_results: int | None
    min_score: float | None
    corpus: str | None


def read_memory_search_params(params: object) -> MemorySearchParams:
    """Read tool-call params exactly like ``createMemorySearchTool`` (tools.ts:239-251).

    Accepts camelCase keys and their snake_case aliases (``max_results``,
    ``min_score``), strict numeric strings (``"5"``, ``"0.3"``) and blank strings
    as omitted numbers; the corpus must be one of the tool's enum. Raises
    :class:`MemoryToolInputError` with the upstream message on invalid input, in
    upstream's order: query, maxResults, minScore, corpus.
    """
    raw = as_tool_params_record(params)
    try:
        query = read_string_param(raw, "query", required=True)
        max_results = read_positive_integer_param(raw, "maxResults")
        min_score = read_finite_number_param(raw, "minScore")
        corpus = read_corpus_param(raw, MEMORY_SEARCH_CORPORA)
    except MemoryToolInputError as error:
        error.tool = MEMORY_SEARCH_TOOL_NAME
        raise
    return MemorySearchParams(
        query=query,
        max_results=max_results,
        min_score=min_score,
        corpus=corpus,
    )


def execute_memory_search_tool(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    params: Mapping[str, Any] | None,
    *,
    supplements: list[MemoryCorpusSupplement] | None = None,
    agent_session_key: str | None = None,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict:
    """Run ``memory_search`` on raw tool-call params (the model's arguments).

    The cooldown key is :func:`memory_search_tool_cooldown_key`: the store's
    resolved path plus ``config.agent_id`` (upstream's resolved session agent
    id), falling back to ``agent_session_key`` and then ``"default"``. Only
    stores that open the same index file with the same agent id share it.
    """
    parsed = read_memory_search_params(params)
    return _run_memory_search_tool(
        config,
        store,
        parsed,
        supplements=supplements or [],
        agent_session_key=agent_session_key,
        runtime_identity=runtime_identity,
    )


def memory_search(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    *,
    query: str,
    max_results: int | None = DEFAULT_MEMORY_SEARCH_MAX_RESULTS,
    min_score: float | None = DEFAULT_MEMORY_SEARCH_MIN_SCORE,
    corpus: str | None = "all",
    supplements: list[MemoryCorpusSupplement] | None = None,
    agent_session_key: str | None = None,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict:
    """Python-call form of the tool; ``None`` for a param means "omitted"."""
    return execute_memory_search_tool(
        config,
        store,
        {"query": query, "maxResults": max_results, "minScore": min_score, "corpus": corpus},
        supplements=supplements,
        agent_session_key=agent_session_key,
        runtime_identity=runtime_identity,
    )


def _memory_sources_for_corpus(corpus: str | None) -> set[str] | None:
    if corpus == "sessions":
        return {"sessions"}
    if corpus == "memory":
        return {"memory"}
    return None


class _PhaseTracker:
    """Which phase ran or failed when the deadline fired (tools.ts:424-441)."""

    def __init__(self) -> None:
        self.active: str | None = None
        self.failed: str | None = None

    def run(self, phase: str, task: Callable[[], Any]) -> Any:
        self.active = phase
        try:
            return task()
        except BaseException:
            self.failed = phase
            raise
        finally:
            if self.active == phase:
                self.active = None


def _run_memory_search_tool(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    params: MemorySearchParams,
    *,
    supplements: list[MemoryCorpusSupplement],
    agent_session_key: str | None,
    runtime_identity: RuntimeIdentity,
) -> dict:
    requested_corpus = params.corpus
    cooldown_key = memory_search_tool_cooldown_key(
        config, store, agent_session_key=agent_session_key
    )
    cooldown_error = (
        None if requested_corpus == "wiki" else read_memory_search_tool_cooldown(cooldown_key)
    )
    phases = _PhaseTracker()

    def run(signal: CancellationSignal) -> dict:
        should_query_supplements = requested_corpus in {"wiki", "all"}
        should_query_memory = requested_corpus != "wiki" and cooldown_error is None
        if cooldown_error is not None and not should_query_supplements:
            return build_memory_search_unavailable_result(
                cooldown_error, runtime_identity=runtime_identity
            )

        response: dict[str, Any] = {}
        memory_results: list[dict] = []
        paused: dict[str, str | None] = {"reason": None}
        if should_query_memory:

            def search_memory() -> None:
                hits = store.search(
                    params.query,
                    max_results=(
                        params.max_results
                        if params.max_results is not None
                        else DEFAULT_MEMORY_SEARCH_MAX_RESULTS
                    ),
                    min_score=(
                        params.min_score
                        if params.min_score is not None
                        else DEFAULT_MEMORY_SEARCH_MIN_SCORE
                    ),
                    sources=_memory_sources_for_corpus(requested_corpus),
                    signal=signal,
                )
                # tools.ts:563-568: a missing or mismatched index identity pauses
                # search (no cooldown). Upstream's empty-result forced sync retry
                # has no counterpart: memory-core reindexes only when the host asks.
                paused["reason"] = resolve_paused_memory_index_identity_reason(
                    store.index_identity()
                )
                if paused["reason"] is not None:
                    return
                memory_results.extend(_serialize_result(config, item) for item in hits)
                # OpenClaw reports FTS-only mode as provider "none" / model
                # "fts-only" when no embedding provider is configured.
                embeddings = store.embeddings
                response["provider"] = (
                    embeddings.provider_id if embeddings is not None else "none"
                )
                response["model"] = embeddings.model if embeddings is not None else "fts-only"

            phases.run("memory", search_memory)
            if paused["reason"] is not None:
                return build_paused_memory_index_unavailable_result(
                    paused["reason"], runtime_identity=runtime_identity
                )
        supplement_results = (
            phases.run(
                "supplement",
                lambda: _search_supplements(
                    supplements,
                    query=params.query,
                    max_results=params.max_results,
                    corpus=requested_corpus,
                ),
            )
            if should_query_supplements
            else []
        )
        results = _merge_corpus_results(
            memory_results=memory_results,
            supplement_results=supplement_results,
            max_results=max(
                1,
                params.max_results
                if params.max_results is not None
                else MEMORY_SEARCH_MERGE_DEFAULT_MAX_RESULTS,
            ),
            balance_corpora=requested_corpus == "all",
        )
        # provider/model stay unset when memory was not searched (tools.ts:677-685).
        return {"results": results, **response, "citations": config.citation_mode}

    outcome = _run_with_deadline(timeout_ms=MEMORY_SEARCH_TOOL_TIMEOUT_MS, run=run)
    if outcome.status == "unavailable":
        unavailable_phase = phases.failed or phases.active
        should_record_cooldown = requested_corpus != "wiki" and (
            requested_corpus != "all" or unavailable_phase == "memory"
        )
        if should_record_cooldown:
            record_memory_search_tool_cooldown(cooldown_key, outcome.error or "")
        return build_memory_search_unavailable_result(
            outcome.error, runtime_identity=runtime_identity
        )
    return outcome.value or {}


def _search_supplements(
    supplements: list[MemoryCorpusSupplement],
    *,
    query: str,
    max_results: int | None,
    corpus: str | None,
) -> list[MemoryCorpusResult]:
    # tools.shared.ts searchMemoryCorpusSupplements.
    if corpus in {"memory", "sessions"}:
        return []
    limit = max(1, max_results if max_results is not None else MEMORY_SEARCH_MERGE_DEFAULT_MAX_RESULTS)
    results: list[MemoryCorpusResult] = []
    for supplement in supplements:
        results.extend(supplement.search(query=query, max_results=limit, corpus=corpus or ""))
    return sort_corpus_results(results)[:limit]
def _merge_corpus_results(
    *,
    memory_results: list[dict],
    supplement_results: list[MemoryCorpusResult],
    max_results: int,
    balance_corpora: bool,
) -> list[dict]:
    sorted_memory = _sort_tool_results(memory_results)
    sorted_supplements = _sort_tool_results([dict(item) for item in supplement_results])
    if not balance_corpora or not sorted_memory or not sorted_supplements:
        return _sort_tool_results([*sorted_memory, *sorted_supplements])[:max_results]

    per_corpus_cap = _ceil_div(max_results, 2)
    selected_memory = sorted_memory[:per_corpus_cap]
    selected_supplements = sorted_supplements[:per_corpus_cap]
    selected = [*selected_memory, *selected_supplements]
    if len(selected) < max_results:
        selected.extend(
            _sort_tool_results(
                [
                    *sorted_memory[len(selected_memory):],
                    *sorted_supplements[len(selected_supplements):],
                ]
            )[: max_results - len(selected)]
        )
    return _sort_tool_results(selected)[:max_results]


def _sort_tool_results(results: list[dict]) -> list[dict]:
    # tools.ts sortMemorySearchToolResults: score descending, then
    # `left.path.localeCompare(right.path)` (stable, like toSorted).
    return sorted(
        results,
        key=lambda item: (-float(item.get("score", 0)), locale_sort_key(item.get("path", ""))),
    )


def _ceil_div(value: int, divisor: int) -> int:
    return -(-value // divisor)


def _serialize_result(config: MemoryConfig, item) -> dict:
    snippet = clamp_text(item.snippet, max_chars=config.memory_get_max_chars)
    citation = citation_label(item.path, item.start_line, item.end_line)
    snippet_text = snippet.text
    if config.citation_mode == "on":
        snippet_text = f"{snippet.text.strip()}\n\nSource: {citation}"
    return {
        "corpus": item.source,
        "path": item.path,
        "startLine": item.start_line,
        "endLine": item.end_line,
        "score": item.score,
        "vectorScore": item.vector_score,
        "textScore": item.text_score,
        "snippet": snippet_text,
        "source": item.source,
        "citation": source_label(item.path, item.start_line, item.end_line),
        "truncated": snippet.truncated,
        "originalChars": snippet.original_chars,
    }
