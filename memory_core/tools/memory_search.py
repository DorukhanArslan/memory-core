"""The ``memory_search`` tool (OpenClaw ``extensions/memory-core/src/tools.ts``).

``createMemorySearchTool`` reads its params before any search work
(``readStringParam`` / ``readPositiveIntegerParam`` / ``readFiniteNumberParam``,
``src/agents/tools/common.ts``). Invalid input raises
:class:`~memory_core.tools.common.MemoryToolInputError`; a host tool loop turns it
into ``{"status": "error", "tool": "memory_search", "error": ...}`` with
``to_tool_error()``.

``corpus`` has no enum check in the tool itself (the schema enum
``memory|wiki|all|sessions`` in ``tools.shared.ts`` is enforced by the agent
loop's argument validation, which the host owns). An omitted or unknown corpus
searches every indexed source and skips supplements, as upstream.

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
from memory_core.tools.corpus import (
    CorpusAttempt,
    CorpusFailure,
    compose_memory_corpus_metadata,
    error_code,
    settle_supplements,
)
from memory_core.tools.memory_get import (
    MEMORY_TOOL_CORPUS_OUTCOME_GUIDANCE,
    MEMORY_TOOL_FILES_DESCRIPTION,
)
from memory_core.tools.common import (
    MemoryToolInputError,
    as_tool_params_record,
    format_error_message,
    read_corpus_param,
    read_finite_number_param,
    read_positive_integer_param,
    read_string_param,
)

MEMORY_SEARCH_TOOL_NAME = "memory_search"
MEMORY_SEARCH_CORPORA = ("memory", "wiki", "all", "sessions")
# MEMORY_SEARCH_TOOL_CONTRACT.describe (memory-tool-contract.ts), verbatim; the
# `{search}` source list is the files, plus ", indexed session transcripts" when the
# host indexes sessions.
MEMORY_SEARCH_TOOL_DESCRIPTION_TEMPLATE = (
    "Mandatory recall step: semantically search {search} before answering questions about "
    "prior work, decisions, dates, people, preferences, or todos. Session results are "
    "transcript search references, not readable memory-file paths. Optional `corpus=wiki` or "
    "`corpus=all` also searches registered compiled-wiki supplements. `corpus=memory` "
    "restricts hits to indexed memory files (excludes session transcript chunks from "
    "ranking). `corpus=sessions` searches indexed session transcripts under the same "
    "visibility rules as session history tools and returns unavailable when semantic session "
    "indexing is disabled. " + MEMORY_TOOL_CORPUS_OUTCOME_GUIDANCE + " If response has "
    "disabled=true or stale=true, tell the user and include the warning/action guidance."
)
MEMORY_SEARCH_TOOL_DESCRIPTION = MEMORY_SEARCH_TOOL_DESCRIPTION_TEMPLATE.format(
    search=MEMORY_TOOL_FILES_DESCRIPTION
)
# MemorySearchSchema (memory-tool-contract.ts) as JSON Schema.
MEMORY_SEARCH_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "maxResults": {"type": "integer", "minimum": 1},
        "minScore": {"type": "number"},
        "corpus": {"type": "string", "enum": ["memory", "wiki", "all", "sessions"]},
    },
    "required": ["query"],
    "additionalProperties": False,
}

# tools.ts MEMORY_SEARCH_TOOL_COOLDOWN_MS and memory/search-deadline.ts
# DEFAULT_MEMORY_SEARCH_TIMEOUT_MS (15 s at the pin).
MEMORY_SEARCH_TOOL_TIMEOUT_MS = 30_000
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
MEMORY_SEARCH_DEADLINE_WARNING = "Memory search did not finish within its time limit."
MEMORY_SEARCH_PARTIAL_WARNING = (
    "Only memory-file keyword matches are included; semantic memory retrieval did not finish "
    "within the search time limit. Session transcript results are not included."
)
MEMORY_SEARCH_SESSIONS_DISABLED_REASON = "Session transcript search is not enabled."
MEMORY_SEARCH_SESSIONS_DISABLED_WARNING = (
    "Session transcript search is unavailable for this agent."
)
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


def memory_search_tool_definition(*, index_sessions: bool = False) -> dict[str, Any]:
    """``{"name", "description", "parameters"}`` of the upstream ``memory_search`` tool.

    Same provider-neutral shape as ``MemoryCurator.tool_definitions()``; wrap it
    in the host's tool format. The description tells the model to pass on the
    unavailable/paused ``warning`` and ``action``. The schema's ``corpus`` enum
    is enforced by the host's argument validation, not by
    :func:`execute_memory_search_tool`.
    """
    return {
        "name": MEMORY_SEARCH_TOOL_NAME,
        "description": (
            MEMORY_SEARCH_TOOL_DESCRIPTION_TEMPLATE.format(
                search=f"{MEMORY_TOOL_FILES_DESCRIPTION}, indexed session transcripts"
            )
            if index_sessions
            else MEMORY_SEARCH_TOOL_DESCRIPTION
        ),
        "parameters": copy.deepcopy(MEMORY_SEARCH_TOOL_PARAMETERS),
    }


def build_memory_search_unavailable_result(
    error: str | None,
    *,
    warning: str | None = None,
    action: str | None = None,
    agent_id: str | None = None,
    deadline: bool = False,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict:
    """``buildMemorySearchUnavailableResult`` (tools.shared.ts:92-150).

    The warning/action pair is picked from the lower-cased reason (quota,
    missing SQLite runtime, anything else) unless overridden. The SQLite pair
    and the deadline action name the runtime, so they come from ``runtime_identity``.
    ``deadline`` is the deadline owner's provenance, never read from the message: a
    provider error can read exactly like this tool's timeout.
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
        elif deadline:
            warning = MEMORY_SEARCH_DEADLINE_WARNING
        else:
            warning = MEMORY_SEARCH_PROVIDER_ERROR_WARNING
    if action is None:
        if is_quota_error:
            action = MEMORY_SEARCH_QUOTA_ACTION
        elif is_missing_sqlite:
            action = runtime_identity.memory_search_sqlite_unavailable_action
        elif deadline:
            action = (
                runtime_identity.memory_search_deadline_action_for_agent.format(agent_id=agent_id)
                if agent_id
                else runtime_identity.memory_search_deadline_action
            )
        else:
            action = MEMORY_SEARCH_PROVIDER_ERROR_ACTION
    return {
        "results": [],
        "disabled": True,
        "unavailable": True,
        **({"timedOut": True, "timeoutMs": MEMORY_SEARCH_TOOL_TIMEOUT_MS} if deadline else {}),
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


# Process-wide cooldowns (tools.ts memorySearchToolCooldowns): the failure that paused the
# store, so a repeated call reports the same error, code and deadline provenance.
_cooldowns: dict[str, tuple[float, CorpusFailure]] = {}
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

    Deviation from tools.ts, which keys by agent alone (and by the runtime
    configuration): upstream's agent stands for one workspace and one index, while
    memory-core keeps one index per store path, and every ``Memory.from_workspace()``
    store defaults to ``agent_id="main"``. Keying by agent alone would let one
    workspace's provider error or timeout pause every other workspace in the process.
    The key is the store's resolved path (``config.resolved_store_path()`` for a
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


def read_memory_search_tool_cooldown_failure(key: str) -> CorpusFailure | None:
    """The failure of an active cooldown for ``key``, dropping it once expired."""
    with _cooldowns_lock:
        entry = _cooldowns.get(key)
        if entry is None:
            return None
        until, failure = entry
        if until <= _now_ms():
            del _cooldowns[key]
            return None
        return failure


def read_memory_search_tool_cooldown(key: str) -> str | None:
    """The cooldown error for ``key``, dropping it once expired (tools.ts:83-93)."""
    failure = read_memory_search_tool_cooldown_failure(key)
    return failure.error if failure is not None else None


def memory_search_tool_cooldown_remaining(key: str) -> tuple[float, str] | None:
    """``(remaining_ms, error)`` of an active cooldown for ``key``, or ``None``.

    Read-only view for host status displays; like
    :func:`read_memory_search_tool_cooldown` it drops an expired entry.
    """
    with _cooldowns_lock:
        entry = _cooldowns.get(key)
        if entry is None:
            return None
        until, failure = entry
        remaining = until - _now_ms()
        if remaining <= 0:
            del _cooldowns[key]
            return None
        return remaining, failure.error


def record_memory_search_tool_cooldown(
    key: str, error: str, *, deadline: bool = False, code: str | None = None
) -> None:
    """tools.ts:95-100: pause memory search for ``key`` for 60 s."""
    with _cooldowns_lock:
        _cooldowns[key] = (
            _now_ms() + MEMORY_SEARCH_TOOL_COOLDOWN_MS,
            CorpusFailure(error=error, deadline=deadline, code=code),
        )


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
    value: Any = None
    error: str | None = None
    code: str | None = None
    deadline: bool = False


class _DeadlineWorker:
    """``runMemoryCorpusDeadline`` (memory-corpus.ts) on a worker thread.

    Works from any thread and inside a running event loop (no signals, no loop
    access). :meth:`wait` settles the outcome first and only then aborts the signal,
    so an abort-aware store cannot replace the stable timeout error.
    """

    def __init__(self, label: str, run: Callable[[CancellationSignal], Any]) -> None:
        self.label = label
        self.signal = CancellationSignal()
        self._done = threading.Event()
        self._box: dict[str, Any] = {}
        self._started_at = time.monotonic()
        self._run = run
        threading.Thread(
            target=self._work, name=f"{DIST_NAME}-memory-{label}", daemon=True
        ).start()

    def _work(self) -> None:
        try:
            self._box["value"] = self._run(self.signal)
        except BaseException as error:  # reported to the caller as unavailable
            self._box["error"] = error
        finally:
            self._done.set()

    def wait(self, timeout_ms: int) -> _DeadlineOutcome:
        timeout_message = f"{self.label} timed out after {_js_round(timeout_ms / 1000)}s"
        remaining = max(0.0, _deadline_seconds(timeout_ms) - (time.monotonic() - self._started_at))
        if not self._done.wait(remaining):
            outcome = _DeadlineOutcome(status="unavailable", error=timeout_message, deadline=True)
            self.signal.abort(timeout_message)
            return outcome
        if "error" in self._box:
            error = self._box["error"]
            return _DeadlineOutcome(
                status="unavailable", error=format_error_message(error), code=error_code(error)
            )
        return _DeadlineOutcome(status="ok", value=self._box["value"])


@dataclass(frozen=True)
class MemorySearchParams:
    """Validated ``memory_search`` params; ``None`` means the caller omitted it."""

    query: str
    max_results: int | None
    min_score: float | None
    corpus: str | None


def read_memory_search_params(params: object) -> MemorySearchParams:
    """Read tool-call params exactly like ``createMemorySearchTool`` (tools.ts:402-412).

    Accepts camelCase keys and their snake_case aliases (``max_results``,
    ``min_score``) and strict numeric strings (``"5"``, ``"0.3"``). Raises
    :class:`MemoryToolInputError` with the upstream message on invalid input.
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


def _memory_sources_for_corpus(corpus: str | None, *, session_search: bool) -> set[str] | None:
    if corpus == "sessions":
        return {"sessions"}
    if corpus == "memory":
        return {"memory"}
    # No corpus (or all): the default sources, which leave sessions out when session
    # search is off.
    return None if session_search else {"memory"}


def _failure_attempt(corpus: str, failure: CorpusFailure, value: Any = None) -> CorpusAttempt:
    return CorpusAttempt(
        corpus=corpus,
        outcome="unavailable",
        value=value,
        error=failure.error,
        code=failure.code,
        deadline=failure.deadline,
    )


def _run_memory_search_tool(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    params: MemorySearchParams,
    *,
    supplements: list[MemoryCorpusSupplement],
    agent_session_key: str | None,
    runtime_identity: RuntimeIdentity,
) -> dict:
    """``createMemorySearchTool``'s execute (tools.ts:402-702).

    Memory and the wiki supplements are separate corpora, each with its own deadline
    and outcome; the result reports every corpus it covered (``corpora``), so a failed
    corpus is surfaced next to the results of the other. Deviations: no staleness,
    rebuild notices or recall recording (the host owns the index), and a deadline
    leaves the keyword-only pass to a fresh FTS query instead of a snapshot of the
    manager's first stage.
    """
    requested_corpus = params.corpus
    if requested_corpus == "sessions" and not config.session_search:
        return build_memory_search_unavailable_result(
            MEMORY_SEARCH_SESSIONS_DISABLED_REASON,
            warning=MEMORY_SEARCH_SESSIONS_DISABLED_WARNING,
            action=runtime_identity.memory_search_sessions_disabled_action,
            runtime_identity=runtime_identity,
        )
    cooldown_key = memory_search_tool_cooldown_key(
        config, store, agent_session_key=agent_session_key
    )
    searches_memory = requested_corpus != "wiki"
    searches_wiki = requested_corpus in {"wiki", "all"}
    cooldown = (
        read_memory_search_tool_cooldown_failure(cooldown_key) if searches_memory else None
    )
    max_results = (
        params.max_results if params.max_results is not None else DEFAULT_MEMORY_SEARCH_MAX_RESULTS
    )
    min_score = (
        params.min_score if params.min_score is not None else DEFAULT_MEMORY_SEARCH_MIN_SCORE
    )

    def search_memory_worker(signal: CancellationSignal) -> dict:
        hits = store.search(
            params.query,
            max_results=max_results,
            min_score=min_score,
            sources=_memory_sources_for_corpus(
                requested_corpus, session_search=config.session_search
            ),
            signal=signal,
        )
        # tools.ts:563-568: a missing or mismatched index identity pauses search
        # (no cooldown). Upstream's empty-result forced sync retry has no
        # counterpart: memory-core reindexes only when the host asks.
        paused = resolve_paused_memory_index_identity_reason(store.index_identity())
        if paused is not None:
            return {"paused": paused}
        # OpenClaw reports FTS-only mode as provider "none" / model "fts-only" when no
        # embedding provider is configured.
        embeddings = store.embeddings
        return {
            "results": [_serialize_result(config, item) for item in hits],
            "provider": embeddings.provider_id if embeddings is not None else "none",
            "model": embeddings.model if embeddings is not None else "fts-only",
        }

    def wiki_worker(signal: CancellationSignal) -> CorpusAttempt:
        del signal
        limit = max(1, params.max_results if params.max_results is not None else 10)

        def run(supplement: MemoryCorpusSupplement) -> list[MemoryCorpusResult]:
            return supplement.search(query=params.query, max_results=limit, corpus=requested_corpus or "")

        return settle_supplements(
            supplements,
            run,
            lambda batches: sort_corpus_results([item for batch in batches for item in batch])[:limit],
        )

    memory_worker = (
        _DeadlineWorker("memory_search", search_memory_worker)
        if searches_memory and cooldown is None
        else None
    )
    wiki_deadline_worker = (
        _DeadlineWorker("memory_search", wiki_worker) if searches_wiki else None
    )

    memory: CorpusAttempt | None = None
    if searches_memory:
        if cooldown is not None:
            memory = _failure_attempt("memory", cooldown)
        else:
            assert memory_worker is not None
            memory = _settle_memory_attempt(
                memory_worker.wait(MEMORY_SEARCH_TOOL_TIMEOUT_MS),
                store=store,
                config=config,
                params=params,
                max_results=max_results,
                min_score=min_score,
                cooldown_key=cooldown_key,
                runtime_identity=runtime_identity,
            )
    wiki: CorpusAttempt | None = None
    if wiki_deadline_worker is not None:
        outcome = wiki_deadline_worker.wait(MEMORY_SEARCH_TOOL_TIMEOUT_MS)
        wiki = (
            outcome.value
            if outcome.status == "ok"
            else CorpusAttempt(
                corpus="wiki",
                outcome="unavailable",
                value=[],
                error=outcome.error,
                code=outcome.code,
                deadline=outcome.deadline,
            )
        )

    memory_value: dict | None = (
        memory.value if memory is not None and memory.outcome != "not-registered" else None
    )
    if searches_memory and not searches_wiki and memory is not None and memory.outcome == "unavailable":
        return (memory_value or {}).get("unavailableResult") or build_memory_search_unavailable_result(
            memory.error,
            agent_id=config.agent_id,
            deadline=memory.deadline,
            runtime_identity=runtime_identity,
        )
    wiki_results = [] if wiki is None or wiki.outcome == "not-registered" else (wiki.value or [])
    # Equal scores break by the path's locale order, which the manager's ranking does at the tag
    # (stage 2 area 6 ports that ranking).
    memory_results = _sort_by_score_then_path((memory_value or {}).get("results", []))
    if searches_wiki:
        results = _merge_corpus_results(
            memory_results=memory_results,
            supplement_results=[dict(item) for item in wiki_results],
            max_results=max(1, params.max_results if params.max_results is not None else 10),
            balance_corpora=requested_corpus == "all",
        )
    else:
        results = memory_results

    attempts = [
        attempt
        for attempt in (
            memory
            if memory is not None and (requested_corpus == "all" or memory.outcome == "partial")
            else None,
            wiki,
        )
        if attempt is not None
    ]
    recovery = (memory_value or {}).get("unavailableResult")
    response: dict[str, Any] = {"results": results}
    # provider/model stay unset when memory was not searched (tools.ts:677-685).
    if memory_value is not None and "provider" in memory_value:
        response["provider"] = memory_value["provider"]
        response["model"] = memory_value["model"]
    response["citations"] = config.citation_mode
    if attempts:
        response.update(
            compose_memory_corpus_metadata(
                attempts,
                [
                    *([recovery["warning"]] if recovery and recovery.get("warning") else []),
                    *(
                        [MEMORY_SEARCH_PARTIAL_WARNING]
                        if memory is not None and memory.outcome == "partial"
                        else []
                    ),
                ],
            )
        )
    if memory is not None and memory.outcome == "partial":
        response["partial"] = True
    # Another corpus can succeed while primary memory still needs repair.
    if recovery and recovery.get("action"):
        response["action"] = recovery["action"]
    return response


def _settle_memory_attempt(
    outcome: _DeadlineOutcome,
    *,
    store: SQLiteMemoryStore,
    config: MemoryConfig,
    params: MemorySearchParams,
    max_results: int,
    min_score: float,
    cooldown_key: str,
    runtime_identity: RuntimeIdentity,
) -> CorpusAttempt:
    """The memory corpus's attempt from its worker's outcome (``attemptMemoryCorpus``)."""
    if outcome.status == "ok":
        value = outcome.value
        if "paused" in value:
            unavailable = build_paused_memory_index_unavailable_result(
                value["paused"], runtime_identity=runtime_identity
            )
            # Neither a cooldown nor a failure of the search itself.
            return CorpusAttempt(
                corpus="memory",
                outcome="unavailable",
                value={"results": [], "unavailableResult": unavailable},
                error=unavailable["error"],
            )
        return CorpusAttempt(corpus="memory", outcome="ok", value=value)
    if outcome.deadline:
        # The keyword pass is what a deadline leaves: memory-file FTS hits without the
        # query embedding. A failed or empty pass is an ordinary unavailable corpus.
        try:
            keyword_hits = store.search_memory_keywords(
                params.query, max_results=max_results, min_score=min_score
            )
        except Exception:
            keyword_hits = []
        if keyword_hits:
            embeddings = store.embeddings
            return CorpusAttempt(
                corpus="memory",
                outcome="partial",
                value={
                    "results": [_serialize_result(config, item) for item in keyword_hits],
                    "provider": embeddings.provider_id if embeddings is not None else "none",
                    "model": embeddings.model if embeddings is not None else "fts-only",
                },
                error=outcome.error,
                deadline=True,
            )
    record_memory_search_tool_cooldown(
        cooldown_key, outcome.error or "", deadline=outcome.deadline, code=outcome.code
    )
    return CorpusAttempt(
        corpus="memory",
        outcome="unavailable",
        value={"results": []},
        error=outcome.error,
        code=outcome.code,
        deadline=outcome.deadline,
    )


def _sort_by_score_then_path(results: list[dict]) -> list[dict]:
    # Score descending, then `left.path.localeCompare(right.path)` (stable, like toSorted).
    return sorted(
        results,
        key=lambda item: (-float(item.get("score", 0)), locale_sort_key(item.get("path", ""))),
    )


def _merge_ranked_streams(memory_results: list[dict], supplement_results: list[dict]) -> list[dict]:
    """``mergeRankedMemorySearchToolStreams``: each backend owns its ranking.

    Only the heads of the two streams are compared; a stream is never reordered.
    """
    merged: list[dict] = []
    memory_index = 0
    supplement_index = 0
    while memory_index < len(memory_results) and supplement_index < len(supplement_results):
        if float(memory_results[memory_index].get("score", 0)) >= float(
            supplement_results[supplement_index].get("score", 0)
        ):
            merged.append(memory_results[memory_index])
            memory_index += 1
        else:
            merged.append(supplement_results[supplement_index])
            supplement_index += 1
    merged.extend(memory_results[memory_index:])
    merged.extend(supplement_results[supplement_index:])
    return merged


def _merge_corpus_results(
    *,
    memory_results: list[dict],
    supplement_results: list[dict],
    max_results: int,
    balance_corpora: bool,
) -> list[dict]:
    """``mergeMemorySearchCorpusResults`` (tools.ts)."""
    if not balance_corpora or not memory_results or not supplement_results:
        return _merge_ranked_streams(memory_results, supplement_results)[:max_results]
    per_corpus_cap = -(-max_results // 2)
    memory_take = min(per_corpus_cap, len(memory_results))
    supplement_take = min(per_corpus_cap, len(supplement_results))
    while memory_take + supplement_take < max_results:
        memory = memory_results[memory_take] if memory_take < len(memory_results) else None
        supplement = (
            supplement_results[supplement_take] if supplement_take < len(supplement_results) else None
        )
        if memory is None and supplement is None:
            break
        if supplement is None or (
            memory is not None
            and float(memory.get("score", 0)) >= float(supplement.get("score", 0))
        ):
            memory_take += 1
        else:
            supplement_take += 1
    return _merge_ranked_streams(
        memory_results[:memory_take], supplement_results[:supplement_take]
    )[:max_results]


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
