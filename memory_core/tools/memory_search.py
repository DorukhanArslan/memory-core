"""The ``memory_search`` tool (OpenClaw ``extensions/memory-core/src/tools.ts``, v2026.9.6).

``createMemorySearchTool`` reads its params before any search work
(``readStringParam`` / ``readPositiveIntegerParam`` / ``readFiniteNumberParam``,
``src/agents/tools/common.ts``). Invalid input raises
:class:`~memory_core.tools.common.MemoryToolInputError`; a host tool loop turns it
into ``{"status": "error", "tool": "memory_search", "error": ...}`` with
``to_tool_error()``.

``corpus`` is checked against the tool's closed enum ``memory|wiki|all|sessions``
(``readCorpusParam``, tools.ts:86-98): an unknown corpus raises
``corpus must be one of: memory, wiki, all, sessions``, and a blank or
non-string one reads as omitted. An omitted corpus searches the search sources
(memory files and session transcripts in memory-core) and skips supplements;
``corpus=sessions`` without sessions in the search sources is the not-enabled result.

One call runs under the 30 s deadline of :mod:`memory_core.tools.corpus`
(``runMemoryCorpusDeadline``, d46f9ebf2b2 #147702): the memory search and, for
``wiki``/``all``, the supplement search run at once, each as a corpus attempt,
the supplements under a deadline of their own. A memory task still running at the
deadline is abandoned: its :class:`~memory_core.cancellation.CancellationSignal` is
aborted, which interrupts the open SQLite statement and stops the store at its next
checkpoint (the abandoned worker only reads). A memory failure (an error or the
deadline) records a process-wide 60 s cooldown during which memory is not searched;
a supplement failure never does, and ``corpus=wiki`` never reads it. A memory-only
call returns the unavailable result; ``wiki``/``all`` keep the other corpus and
report each one in ``corpora`` (``composeMemoryCorpusMetadata``). The cooldown
belongs to the configuration that recorded it (upstream's runtime config key):
another :class:`MemoryConfig` or embedding provider ignores it. Upstream keys the
cooldown by agent id, and an agent there owns exactly one workspace and one index;
memory-core hosts open many stores with the default ``agent_id`` (one per workspace
or subject), so the key is the agent id scoped by the store's resolved path
(documented deviation, :func:`memory_search_tool_cooldown_key`).

An index whose stored identity is missing or no longer matches the store's
provider/model/settings/format returns the paused result (no cooldown) until
``SQLiteMemoryStore.reindex`` writes fresh metadata; under ``corpus=all`` the memory
corpus is ``unavailable`` and the paused guidance joins the warning and ``action``.

Not ported (docs/parity_matrix.md): the deadline's pause/resume for a managed local
embedding service, a caller ``AbortSignal``, the ``debug``/``fallback``/``mode``
result fields, session-visibility filtering and the ``auto`` citations mode.
"""

from __future__ import annotations

import copy
import re
import threading
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memory_core.bootstrap._js import js_json_stringify, js_trim
from memory_core.cancellation import CancellationSignal
from memory_core.config import MemoryConfig
from memory_core.index.identity import (
    is_chunking_upgrade_keyword_only,
    resolve_memory_index_identity_diagnostic,
    resolve_memory_index_search_diagnostic,
    resolve_memory_search_staleness,
)
from memory_core.index.sqlite_store import CONFIGURED_SOURCES, SQLiteMemoryStore
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, RuntimeIdentity
from memory_core.supplements import MemoryCorpusSupplement
from memory_core.tools.citations import citation_label, clamp_text, source_label
from memory_core.tools.common import (
    MemoryToolInputError,
    as_tool_params_record,
    read_corpus_param,
    read_finite_number_param,
    read_positive_integer_param,
    read_string_param,
)
from memory_core.tools._memory_tool_constants import (
    DEFAULT_MEMORY_SEARCH_TIMEOUT_MS,
    MEMORY_SEARCH_CORPORA,
    MEMORY_SEARCH_DEADLINE_ACTION,
    MEMORY_SEARCH_DEADLINE_WARNING,
    MEMORY_SEARCH_MERGE_DEFAULT_MAX_RESULTS,
    MEMORY_SEARCH_MISSING_SQLITE_PATTERN,
    MEMORY_SEARCH_PARTIAL_WARNING,
    MEMORY_SEARCH_PROVIDER_ERROR_ACTION,
    MEMORY_SEARCH_PROVIDER_ERROR_WARNING,
    MEMORY_SEARCH_QUOTA_ACTION,
    MEMORY_SEARCH_QUOTA_ERROR_PATTERN,
    MEMORY_SEARCH_QUOTA_WARNING,
    MEMORY_SEARCH_TOOL_COOLDOWN_MS,
    MEMORY_SEARCH_TOOL_DESCRIPTION_TEMPLATE,
    MEMORY_SEARCH_TOOL_NAME,
    MEMORY_SEARCH_UNAVAILABLE_REASON,
    MEMORY_SOURCE_FILES,
    MEMORY_SOURCE_SEARCH_TEMPLATE,
    SESSION_CANONICAL_KEY_MIGRATION_REQUIRED,
    SESSION_CANONICAL_KEY_MIGRATION_WARNING,
    SESSION_SEARCH_NOT_ENABLED_ERROR,
    SESSION_SEARCH_NOT_ENABLED_WARNING,
)
from memory_core.tools.corpus import (
    MemoryCorpusAttempt,
    MemoryCorpusDeadline,
    attempt_memory_corpus,
    compose_memory_corpus_metadata,
    run_concurrently,
    run_memory_corpus_deadline,
    search_memory_corpus_supplements,
    unavailable_memory_corpus,
)

# memory-tool-contract.ts:23-33 MemorySearchSchema (a plain JSON schema since 16bec3c7272).
MEMORY_SEARCH_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "maxResults": {"type": "integer", "minimum": 1},
        "minScore": {"type": "number"},
        "corpus": {"type": "string", "enum": list(MEMORY_SEARCH_CORPORA)},
    },
    "required": ["query"],
    "additionalProperties": False,
}

# memory/search-deadline.ts:1 DEFAULT_MEMORY_SEARCH_TIMEOUT_MS (30 s since d46f9ebf2b2 #147702).
MEMORY_SEARCH_TOOL_TIMEOUT_MS = DEFAULT_MEMORY_SEARCH_TIMEOUT_MS

# Used when the caller omits maxResults/minScore. Upstream falls back to the
# agent's memorySearch.query config (6 / 0.35, src/agents/memory-search.ts);
# memory-core keeps its facade defaults (documented deviation).
DEFAULT_MEMORY_SEARCH_MAX_RESULTS = 5
DEFAULT_MEMORY_SEARCH_MIN_SCORE = 0.0
# tools.shared.ts:104-107, the inline regex literals of buildMemorySearchUnavailableResult.
_QUOTA_ERROR_RE = re.compile(MEMORY_SEARCH_QUOTA_ERROR_PATTERN)
_MISSING_SQLITE_RE = re.compile(MEMORY_SEARCH_MISSING_SQLITE_PATTERN)


def resolve_memory_source_contract(search_sources: Collection[str]) -> tuple[str, str]:
    """``resolveMemorySourceContract`` (memory-tool-contract.ts:47-64): ``(files, search)``.

    ``files`` names the memory files ``memory_get`` reads; ``search`` adds ``indexed session
    transcripts`` when ``search_sources`` has ``sessions``. Upstream also names ``configured
    extra paths`` when ``extraPaths`` is set; memory-core has no extra memory roots, so that part
    is never added.
    """
    files = MEMORY_SOURCE_FILES
    search = (
        MEMORY_SOURCE_SEARCH_TEMPLATE.format(files=files) if "sessions" in search_sources else files
    )
    return files, search


def memory_search_tool_definition(
    *, search_sources: Collection[str] = CONFIGURED_SOURCES
) -> dict[str, Any]:
    """``{"name", "description", "parameters"}`` of the upstream ``memory_search`` tool.

    ``MEMORY_SEARCH_TOOL_CONTRACT`` (memory-tool-contract.ts:88-94, 16bec3c7272 #126552 and
    3fe833dfa40 #126530): the description names the searched sources and the per-corpus
    outcome guidance. ``search_sources`` defaults to what memory-core searches (memory files and
    session transcripts, ``sqlite_store.CONFIGURED_SOURCES``); upstream searches sessions only
    when configured (decision D1). Same provider-neutral shape as
    ``MemoryCurator.tool_definitions()`` (no ``label``); wrap it in the host's tool format.
    """
    _, search = resolve_memory_source_contract(search_sources)
    return {
        "name": MEMORY_SEARCH_TOOL_NAME,
        "description": MEMORY_SEARCH_TOOL_DESCRIPTION_TEMPLATE.format(search=search),
        "parameters": copy.deepcopy(MEMORY_SEARCH_TOOL_PARAMETERS),
    }


def build_memory_search_unavailable_result(
    error: str | None,
    *,
    warning: str | None = None,
    action: str | None = None,
    agent_id: str | None = None,
    deadline: bool = False,
    code: str | None = None,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict:
    """``buildMemorySearchUnavailableResult`` (tools.shared.ts:92-150, v2026.9.6).

    The warning/action pair is picked, unless overridden, in upstream's order: the session
    catalog's canonical-key ``code``, then the lower-cased reason (quota, missing SQLite
    runtime), then ``deadline`` (this tool's own deadline, known by the flag and never by the
    text, d46f9ebf2b2 #147702), else the provider error. A deadline adds ``timedOut`` and
    ``timeoutMs``, and its action names the agent's index when ``agent_id`` is set. The SQLite
    pair, the deadline action with an agent and the canonical-key action name the runtime, so
    they come from ``runtime_identity``.
    """
    reason = js_trim(error if error is not None else MEMORY_SEARCH_UNAVAILABLE_REASON)
    reason = reason or MEMORY_SEARCH_UNAVAILABLE_REASON
    normalized_reason = reason.lower()
    is_quota_error = _QUOTA_ERROR_RE.search(normalized_reason) is not None
    is_missing_sqlite = _MISSING_SQLITE_RE.search(normalized_reason) is not None
    is_search_deadline = deadline is True
    is_canonical_key_migration = code == SESSION_CANONICAL_KEY_MIGRATION_REQUIRED
    deadline_action = (
        runtime_identity.memory_search_deadline_agent_action.format(agent_id=agent_id)
        if agent_id
        else MEMORY_SEARCH_DEADLINE_ACTION
    )
    if warning is None:
        if is_canonical_key_migration:
            warning = SESSION_CANONICAL_KEY_MIGRATION_WARNING
        elif is_quota_error:
            warning = MEMORY_SEARCH_QUOTA_WARNING
        elif is_missing_sqlite:
            warning = runtime_identity.memory_search_sqlite_unavailable_warning
        elif is_search_deadline:
            warning = MEMORY_SEARCH_DEADLINE_WARNING
        else:
            warning = MEMORY_SEARCH_PROVIDER_ERROR_WARNING
    if action is None:
        if is_canonical_key_migration:
            action = runtime_identity.memory_search_canonical_key_migration_action
        elif is_quota_error:
            action = MEMORY_SEARCH_QUOTA_ACTION
        elif is_missing_sqlite:
            action = runtime_identity.memory_search_sqlite_unavailable_action
        elif is_search_deadline:
            action = deadline_action
        else:
            action = MEMORY_SEARCH_PROVIDER_ERROR_ACTION
    return {
        "results": [],
        "disabled": True,
        "unavailable": True,
        **(
            {"timedOut": True, "timeoutMs": DEFAULT_MEMORY_SEARCH_TIMEOUT_MS}
            if is_search_deadline
            else {}
        ),
        "error": reason,
        "warning": warning,
        "action": action,
        "debug": {"warning": warning, "action": action, "error": reason},
    }


def build_paused_memory_index_unavailable_result(
    diagnostic: Mapping[str, Any],
    *,
    status: Mapping[str, Any],
    agent_id: str | None,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict:
    """``buildPausedMemoryIndexUnavailableResult`` (memory-search-tool-query.ts:23-39): the
    unavailable result whose error, warning and action come from the index search diagnostic
    (``resolveMemoryIndexSearchDiagnostic``, packages/memory-host-sdk/src/host/types.ts)."""
    guidance = resolve_memory_index_search_diagnostic(
        diagnostic, status, agent_id, runtime_identity=runtime_identity
    )
    return build_memory_search_unavailable_result(
        guidance["error"],
        warning=guidance["warning"],
        action=guidance["action"],
        runtime_identity=runtime_identity,
    )


@dataclass(frozen=True)
class _CooldownEntry:
    until: float
    config_key: str
    failure: dict[str, Any]


# Process-wide cooldowns (tools.ts:75-78 memorySearchToolCooldowns).
_cooldowns: dict[str, _CooldownEntry] = {}
_cooldowns_lock = threading.Lock()


def _now_ms() -> float:
    # Monotonic clock (upstream reads Date.now()); tests replace it.
    return time.monotonic() * 1000


def _deadline_wait_seconds(remaining_seconds: float) -> float:
    # How long a corpus task waits for the rest of the 30 s budget; tests shorten it without
    # changing the deadline or its message.
    return remaining_seconds


def memory_search_tool_cooldown_key(config: MemoryConfig, store: SQLiteMemoryStore) -> str:
    """The cooldown key ``memory_search`` reads and records for ``store``.

    Deviation from tools.ts:269 and 378, which key by the agent id alone: upstream's agent
    stands for one workspace and one index, while memory-core keeps one index per store path,
    and every ``Memory.from_workspace()`` store defaults to ``agent_id="main"``. Keying by agent
    alone would let one workspace's provider error or timeout pause every other workspace in the
    process. The key is the store's resolved path (``config.resolved_store_path()`` for a store
    object without ``path``), a NUL separator, then ``config.agent_id``; stores that open the
    same index file with the same agent share a cooldown.
    """
    store_path = getattr(store, "path", None)
    if store_path is None:
        store_path = config.resolved_store_path()
    return f"{Path(store_path).resolve()}\0{config.agent_id}"


def memory_search_tool_config_key(config: MemoryConfig, store: SQLiteMemoryStore) -> str:
    """The configuration a cooldown belongs to (upstream ``resolveRuntimeConfigCacheKey(cfg)``,
    tools.ts:108-130): the frozen :class:`MemoryConfig` and the store's provider identity. A
    cooldown recorded under another configuration is dropped at the next read."""
    identity = store.provider_identity() if hasattr(store, "provider_identity") else {}
    return f"{config!r}\0{js_json_stringify(identity)}"


def read_memory_search_tool_cooldown(key: str, config_key: str) -> dict[str, Any] | None:
    """``readMemorySearchToolCooldown`` (tools.ts:100-118): the recorded failure (``error``,
    ``deadline`` and ``code`` when set) of an active cooldown for ``key`` recorded under
    ``config_key``; an expired entry or one of another configuration is dropped."""
    with _cooldowns_lock:
        entry = _cooldowns.get(key)
        if entry is None:
            return None
        if entry.until <= _now_ms() or entry.config_key != config_key:
            del _cooldowns[key]
            return None
        return dict(entry.failure)


def memory_search_tool_cooldown_remaining(
    key: str, config_key: str | None = None
) -> tuple[float, dict[str, Any]] | None:
    """``(remaining_ms, failure)`` of an active cooldown for ``key``, or ``None``.

    Read-only view for host status displays; like :func:`read_memory_search_tool_cooldown` it
    drops an expired entry (and, when ``config_key`` is given, one of another configuration).
    """
    with _cooldowns_lock:
        entry = _cooldowns.get(key)
        if entry is None:
            return None
        remaining = entry.until - _now_ms()
        if remaining <= 0 or (config_key is not None and entry.config_key != config_key):
            del _cooldowns[key]
            return None
        return remaining, dict(entry.failure)


def record_memory_search_tool_cooldown(
    key: str, config_key: str, failure: Mapping[str, Any]
) -> None:
    """``recordMemorySearchToolCooldown`` (tools.ts:120-130): pause memory search for ``key``
    for 60 s under ``config_key``; ``failure`` is ``{"error", "deadline", "code"?}``."""
    stored = {"error": failure.get("error"), "deadline": failure.get("deadline") is True}
    if failure.get("code"):
        stored["code"] = failure["code"]
    with _cooldowns_lock:
        _cooldowns[key] = _CooldownEntry(
            until=_now_ms() + MEMORY_SEARCH_TOOL_COOLDOWN_MS, config_key=config_key, failure=stored
        )


def reset_memory_search_tool_cooldowns() -> None:
    """``testing.resetMemorySearchToolCooldowns`` (tools.ts:132-136)."""
    with _cooldowns_lock:
        _cooldowns.clear()


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


RecallCallback = Callable[[list[dict[str, Any]]], None]


def execute_memory_search_tool(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    params: Mapping[str, Any] | None,
    *,
    supplements: list[MemoryCorpusSupplement] | None = None,
    agent_session_key: str | None = None,
    search_sources: Collection[str] = CONFIGURED_SOURCES,
    on_recall: RecallCallback | None = None,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict:
    """Run ``memory_search`` on raw tool-call params (the model's arguments).

    ``search_sources`` is upstream's ``searchSources`` (what an omitted or ``all`` corpus
    searches, and whether ``corpus=sessions`` is enabled); it defaults to what memory-core
    indexes, memory files and session transcripts (decision D1). ``on_recall`` receives the
    memory-corpus hits the result returns, when the memory search was ok or partial
    (tools.ts:477-508, where they become short-term recall signals with dreaming enabled);
    an error it raises is ignored, as upstream's recall recording never fails the search.
    ``agent_session_key`` is accepted for upstream's ``agentSessionKey``; at v2026.9.6 the
    cooldown is keyed by agent, and memory-core has neither session-visibility filtering nor
    supplement context (decision D7), so nothing reads it.
    """
    del agent_session_key
    parsed = read_memory_search_params(params)
    return _run_memory_search_tool(
        config,
        store,
        parsed,
        supplements=supplements or [],
        search_sources=tuple(search_sources),
        on_recall=on_recall,
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
    search_sources: Collection[str] = CONFIGURED_SOURCES,
    on_recall: RecallCallback | None = None,
    runtime_identity: RuntimeIdentity = MEMORY_CORE_RUNTIME_IDENTITY,
) -> dict:
    """Python-call form of the tool; ``None`` for a param means "omitted".

    The default ``corpus="all"`` (decision D8, unchanged) adds the wiki attempt, the balanced
    merge and the per-corpus ``corpora`` metadata upstream reports for ``all``; pass
    ``corpus=None`` for upstream's omitted corpus.
    """
    return execute_memory_search_tool(
        config,
        store,
        {"query": query, "maxResults": max_results, "minScore": min_score, "corpus": corpus},
        supplements=supplements,
        agent_session_key=agent_session_key,
        search_sources=search_sources,
        on_recall=on_recall,
        runtime_identity=runtime_identity,
    )


def _explicit_memory_sources(
    corpus: str | None, search_sources: tuple[str, ...]
) -> set[str] | None:
    # tools.ts:319-325 explicitSources, then memory-search-tool-query.ts:91-99 searchSources.
    if corpus == "sessions" and "sessions" in search_sources:
        return {"sessions"}
    if corpus == "memory":
        return {"memory"}
    if corpus is None or corpus == "all":
        return set(search_sources)
    return None


@dataclass
class _MemoryQuery:
    """``executeMemorySearchToolQuery``'s finalized result (memory-search-tool-query.ts:194-272)."""

    raw_results: list[dict[str, Any]]
    status: Mapping[str, Any]
    paused: Mapping[str, Any] | None = None
    provider: str | None = None
    model: str | None = None


def _execute_memory_query(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    params: MemorySearchParams,
    *,
    search_sources: tuple[str, ...],
    signal: CancellationSignal,
) -> _MemoryQuery:
    sources = _explicit_memory_sources(params.corpus, search_sources)
    result_limit = (
        params.max_results if params.max_results is not None else DEFAULT_MEMORY_SEARCH_MAX_RESULTS
    )
    hits = store.search(
        params.query,
        max_results=result_limit,
        min_score=(
            params.min_score if params.min_score is not None else DEFAULT_MEMORY_SEARCH_MIN_SCORE
        ),
        sources=sources,
        signal=signal,
    )
    return _finalize_memory_query(config, store, params, hits, sources=sources)


def _finalize_memory_query(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    params: MemorySearchParams,
    hits: list[Any],
    *,
    sources: set[str] | None,
) -> _MemoryQuery:
    # memory-search-tool-query.ts:194-272 finalizeMemorySearchToolQuery: a missing or mismatched
    # index identity pauses search (no cooldown), except a pending chunking upgrade that searched
    # keyword-only. Upstream's search-time repair has no counterpart (decision D3): memory-core
    # reindexes only when the host asks.
    status = store.search_status()
    diagnostic = resolve_memory_index_identity_diagnostic(status)
    if diagnostic is not None and not (
        is_chunking_upgrade_keyword_only(diagnostic) and store.flags.text_search
    ):
        return _MemoryQuery(raw_results=[], status=status, paused=diagnostic)
    filtered = [hit for hit in hits if sources is None or hit.source in sources]
    if params.corpus == "sessions":
        filtered = [hit for hit in filtered if hit.source == "sessions"]
    elif params.corpus == "memory":
        filtered = [hit for hit in filtered if hit.source == "memory"]
    result_limit = (
        params.max_results if params.max_results is not None else DEFAULT_MEMORY_SEARCH_MAX_RESULTS
    )
    # OpenClaw reports FTS-only mode as provider "none" / model "fts-only".
    identity = store.provider_identity()
    return _MemoryQuery(
        raw_results=[_serialize_result(config, hit) for hit in filtered[:result_limit]],
        status=status,
        provider=identity["provider"],
        model=identity["model"],
    )


def _run_memory_search_tool(
    config: MemoryConfig,
    store: SQLiteMemoryStore,
    params: MemorySearchParams,
    *,
    supplements: list[MemoryCorpusSupplement],
    search_sources: tuple[str, ...],
    on_recall: RecallCallback | None,
    runtime_identity: RuntimeIdentity,
) -> dict:
    """``createMemorySearchTool``'s execute (tools.ts:238-580) after the param readers."""
    requested_corpus = params.corpus
    agent_id = config.agent_id
    # tools.ts:255-267: an explicit sessions search needs sessions in the search sources.
    if requested_corpus == "sessions" and "sessions" not in search_sources:
        return build_memory_search_unavailable_result(
            SESSION_SEARCH_NOT_ENABLED_ERROR,
            warning=SESSION_SEARCH_NOT_ENABLED_WARNING,
            action=runtime_identity.session_search_not_enabled_action,
            runtime_identity=runtime_identity,
        )
    cooldown_key = memory_search_tool_cooldown_key(config, store)
    config_key = memory_search_tool_config_key(config, store)
    cooldown = (
        None
        if requested_corpus == "wiki"
        else read_memory_search_tool_cooldown(cooldown_key, config_key)
    )
    searches_memory = requested_corpus != "wiki"
    searches_wiki = requested_corpus in ("wiki", "all")

    def search_memory(deadline: MemoryCorpusDeadline) -> MemoryCorpusAttempt:
        # tools.ts:290-429.
        if cooldown is not None:
            return MemoryCorpusAttempt(
                corpus="memory",
                outcome="unavailable",
                value=None,
                error=cooldown["error"],
                code=cooldown.get("code"),
                deadline=cooldown["deadline"],
            )
        attempted = attempt_memory_corpus(
            corpus="memory",
            deadline=deadline,
            unavailable_value=None,
            run=lambda: _execute_memory_query(
                config, store, params, search_sources=search_sources, signal=deadline.signal
            ),
        )
        if attempted.outcome not in ("ok", "partial"):
            failure = {"error": attempted.error, "deadline": attempted.deadline}
            if attempted.code:
                failure["code"] = attempted.code
            record_memory_search_tool_cooldown(cooldown_key, config_key, failure)
            return MemoryCorpusAttempt(
                corpus="memory",
                outcome="unavailable",
                value={"results": []},
                error=attempted.error,
                code=attempted.code,
                deadline=attempted.deadline,
            )
        executed: _MemoryQuery = attempted.value
        if executed.paused is not None:
            unavailable_result = build_paused_memory_index_unavailable_result(
                executed.paused,
                status=executed.status,
                agent_id=agent_id,
                runtime_identity=runtime_identity,
            )
            # unavailableMemoryCorpus over the paused result's error text (no code, no deadline).
            return MemoryCorpusAttempt(
                corpus="memory",
                outcome="unavailable",
                value={"results": [], "unavailable_result": unavailable_result},
                error=unavailable_result["error"],
            )
        return MemoryCorpusAttempt(
            corpus="memory",
            outcome=attempted.outcome,
            value={
                "results": executed.raw_results,
                "provider": executed.provider,
                "model": executed.model,
                "staleness": resolve_memory_search_staleness(
                    executed.status, agent_id, runtime_identity=runtime_identity
                ),
            },
            error=attempted.error,
            code=attempted.code,
            deadline=attempted.deadline,
        )

    def search_wiki() -> MemoryCorpusAttempt:
        # tools.ts:438-452: the wiki attempt runs under its own deadline.
        return run_memory_corpus_deadline(
            MEMORY_SEARCH_TOOL_NAME,
            lambda wiki_deadline: search_memory_corpus_supplements(
                supplements=supplements,
                deadline=wiki_deadline,
                query=params.query,
                max_results=params.max_results,
                corpus=requested_corpus or "",
            ),
            wait_seconds=_wait_seconds,
        )

    def run(deadline: MemoryCorpusDeadline) -> dict:
        memory, wiki = run_concurrently(
            [
                (lambda: search_memory(deadline)) if searches_memory else (lambda: None),
                search_wiki if searches_wiki else (lambda: None),
            ]
        )
        return _compose_memory_search_result(
            config,
            params,
            memory=memory,
            wiki=wiki,
            searches_memory=searches_memory,
            searches_wiki=searches_wiki,
            on_recall=on_recall,
            runtime_identity=runtime_identity,
        )

    try:
        return run_memory_corpus_deadline(
            MEMORY_SEARCH_TOOL_NAME, run, wait_seconds=_wait_seconds
        )
    except Exception as error:
        # tools.ts:553-568: a failure of the whole call is a memory failure.
        failed = unavailable_memory_corpus("memory", None, error)
        if requested_corpus != "wiki":
            failure = {"error": failed.error, "deadline": failed.deadline}
            if failed.code:
                failure["code"] = failed.code
            record_memory_search_tool_cooldown(cooldown_key, config_key, failure)
        return build_memory_search_unavailable_result(
            failed.error,
            agent_id=agent_id,
            deadline=failed.deadline,
            code=failed.code,
            runtime_identity=runtime_identity,
        )


def _wait_seconds(remaining_seconds: float) -> float:
    return _deadline_wait_seconds(remaining_seconds)


def _compose_memory_search_result(
    config: MemoryConfig,
    params: MemorySearchParams,
    *,
    memory: MemoryCorpusAttempt | None,
    wiki: MemoryCorpusAttempt | None,
    searches_memory: bool,
    searches_wiki: bool,
    on_recall: RecallCallback | None,
    runtime_identity: RuntimeIdentity,
) -> dict:
    # tools.ts:455-550.
    requested_corpus = params.corpus
    memory_value: Mapping[str, Any] | None = (
        None if memory is None or memory.outcome == "not-registered" else memory.value
    )
    if searches_memory and not searches_wiki and memory is not None:
        if memory.outcome == "unavailable":
            unavailable_result = (memory_value or {}).get("unavailable_result")
            return unavailable_result or build_memory_search_unavailable_result(
                memory.error,
                agent_id=config.agent_id,
                deadline=memory.deadline,
                code=memory.code,
                runtime_identity=runtime_identity,
            )
    memory_results: list[dict[str, Any]] = list((memory_value or {}).get("results") or [])
    wiki_results = (
        []
        if wiki is None or wiki.outcome == "not-registered"
        else [dict(item) for item in wiki.value or []]
    )
    # Primary results already own their configured limit; only wiki/all need aggregation.
    results = (
        merge_memory_search_corpus_results(
            memory_results=memory_results,
            supplement_results=wiki_results,
            max_results=(
                params.max_results
                if params.max_results is not None
                else MEMORY_SEARCH_MERGE_DEFAULT_MAX_RESULTS
            ),
            balance_corpora=requested_corpus == "all",
        )
        if searches_wiki
        else memory_results
    )
    # Only evidence actually returned to the model earns a recall signal (by identity).
    surfaced = {id(result) for result in results}
    recalled = [result for result in memory_results if id(result) in surfaced]
    if on_recall is not None and memory is not None and memory.outcome in ("ok", "partial"):
        try:
            on_recall(recalled)
        except Exception:
            pass  # recall persistence never fails the search (tools.ts:503-507)
    attempts = [
        *(
            [memory]
            if memory is not None and (requested_corpus == "all" or memory.outcome == "partial")
            else []
        ),
        *([wiki] if wiki is not None else []),
    ]
    staleness = (memory_value or {}).get("staleness")
    recovery = (memory_value or {}).get("unavailable_result")
    metadata = compose_memory_corpus_metadata(
        attempts,
        [
            *([staleness["warning"]] if staleness and staleness.get("warning") else []),
            *([recovery["warning"]] if recovery and recovery.get("warning") else []),
            *(
                [MEMORY_SEARCH_PARTIAL_WARNING]
                if memory is not None and memory.outcome == "partial"
                else []
            ),
        ],
    )
    payload: dict[str, Any] = {"results": results}
    if (memory_value or {}).get("provider") is not None:
        payload["provider"] = memory_value["provider"]
        payload["model"] = memory_value["model"]
    payload["citations"] = config.citation_mode
    payload.update(staleness or {})
    if attempts:
        payload.update(metadata)
    if memory is not None and memory.outcome == "partial":
        payload["partial"] = True
    # Another corpus can succeed while primary memory still needs repair.
    if recovery and recovery.get("action"):
        payload["action"] = recovery["action"]
    return payload


def _js_score(item: Mapping[str, Any]) -> Any:
    return item.get("score")


def _score_or_zero(item: Mapping[str, Any] | None) -> Any:
    # `(result?.score ?? 0)`.
    score = None if item is None else item.get("score")
    return 0 if score is None else score


def _merge_ranked_streams(
    memory_results: list[dict[str, Any]], supplement_results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """``mergeRankedMemorySearchToolStreams`` (tools.ts:168-194): each backend owns its ranking,
    so only the stream heads are compared and neither stream is reordered."""
    merged: list[dict[str, Any]] = []
    memory_index = supplement_index = 0
    while memory_index < len(memory_results) and supplement_index < len(supplement_results):
        memory = memory_results[memory_index]
        supplement = supplement_results[supplement_index]
        if _score_or_zero(memory) >= _score_or_zero(supplement):
            merged.append(memory)
            memory_index += 1
        else:
            merged.append(supplement)
            supplement_index += 1
    merged.extend(memory_results[memory_index:])
    merged.extend(supplement_results[supplement_index:])
    return merged


def merge_memory_search_corpus_results(
    *,
    memory_results: list[dict[str, Any]],
    supplement_results: list[dict[str, Any]],
    max_results: int,
    balance_corpora: bool,
) -> list[dict[str, Any]]:
    """``mergeMemorySearchCorpusResults`` (tools.ts:196-230).

    Unbalanced (or one stream empty): the two streams merged by their heads, cut to
    ``max_results``. Balanced (``corpus=all``): each stream first gets up to
    ``ceil(max_results / 2)`` of its own items in its own order, the rest of the budget goes to
    whichever next item scores higher, then the taken items are merged by their heads.
    """
    if not balance_corpora or not memory_results or not supplement_results:
        return _merge_ranked_streams(memory_results, supplement_results)[:max_results]
    per_corpus_cap = -(-max_results // 2)
    memory_take = min(per_corpus_cap, len(memory_results))
    supplement_take = min(per_corpus_cap, len(supplement_results))
    while memory_take + supplement_take < max_results:
        memory = memory_results[memory_take] if memory_take < len(memory_results) else None
        supplement = (
            supplement_results[supplement_take]
            if supplement_take < len(supplement_results)
            else None
        )
        if memory is None and supplement is None:
            break
        if supplement is None or (memory is not None and _js_ge(_js_score(memory), _js_score(supplement))):
            memory_take += 1
        else:
            supplement_take += 1
    return _merge_ranked_streams(
        memory_results[:memory_take], supplement_results[:supplement_take]
    )[:max_results]


def _js_ge(left: Any, right: Any) -> bool:
    # `memory.score >= supplement.score` with an undefined operand is false.
    if left is None or right is None:
        return False
    return left >= right


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
