import asyncio
import dataclasses
import threading
from pathlib import Path

import pytest

import memory_core.tools.memory_search as memory_search_module
from memory_core.cancellation import CancellationSignal, OperationAbortedError
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.project_name import DISPLAY_NAME
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY, MEMORY_CORE_RUNTIME_IDENTITY
from memory_core.tools.common import format_error_message
from memory_core.tools.memory_search import (
    MEMORY_SEARCH_TOOL_COOLDOWN_MS,
    MEMORY_SEARCH_TOOL_TIMEOUT_MS,
    build_memory_search_unavailable_result,
    memory_search,
    memory_search_tool_config_key,
    memory_search_tool_cooldown_key,
    memory_search_tool_cooldown_remaining,
    merge_memory_search_corpus_results,
    read_memory_search_tool_cooldown,
    record_memory_search_tool_cooldown,
)
from memory_core.workspace import MemoryWorkspace


class _ControlledProvider(FakeEmbeddingProvider):
    def __init__(self):
        super().__init__(dimensions=8)
        self.error: Exception | None = None
        self.hang = False
        self.release = threading.Event()
        self.calls = 0

    def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.hang:
            self.release.wait(10)
        return super().embed_query(text)


class _RecordingStore(SQLiteMemoryStore):
    """Records how each search ended, including abandoned ones."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes: list[BaseException | None] = []
        self.finished = threading.Event()

    def search(self, *args, **kwargs):
        try:
            result = super().search(*args, **kwargs)
        except BaseException as error:
            self.outcomes.append(error)
            self.finished.set()
            raise
        self.outcomes.append(None)
        self.finished.set()
        return result


@pytest.fixture
def clock(monkeypatch):
    state = {"now": 5_000_000.0}
    monkeypatch.setattr(memory_search_module, "_now_ms", lambda: state["now"])
    return state


def _vector_store(tmp_path: Path, provider, *, agent_id: str = "main", store_cls=SQLiteMemoryStore):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "MEMORY.md").write_text("- Glacier storage keeps backups cold.\n", encoding="utf-8")
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        agent_id=agent_id,
        store_path=tmp_path / f"{agent_id}.sqlite",
    )
    store = store_cls(cfg, provider)
    store.reindex(MemoryWorkspace(tmp_path))
    return cfg, store


def test_unavailable_result_shape_and_reason_defaults():
    assert build_memory_search_unavailable_result(None) == {
        "results": [],
        "disabled": True,
        "unavailable": True,
        "error": "memory search unavailable",
        "warning": "Memory search is unavailable due to an embedding/provider error.",
        "action": "Check embedding provider configuration and retry memory_search.",
        "debug": {
            "warning": "Memory search is unavailable due to an embedding/provider error.",
            "action": "Check embedding provider configuration and retry memory_search.",
            "error": "memory search unavailable",
        },
    }
    assert build_memory_search_unavailable_result(" ﻿")["error"] == "memory search unavailable"
    assert build_memory_search_unavailable_result("  boom \n")["error"] == "boom"


def test_unavailable_result_classifies_quota_and_sqlite_reasons():
    quota = build_memory_search_unavailable_result("HTTP 429 from provider")
    assert quota["warning"] == (
        "Memory search is unavailable because the embedding provider quota is exhausted."
    )
    assert quota["action"] == "Top up or switch embedding provider, then retry memory_search."

    reason = "No such built-in module: node:sqlite"
    memory_core = build_memory_search_unavailable_result(reason)
    compat = build_memory_search_unavailable_result(
        reason, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY
    )
    assert memory_core["warning"] == MEMORY_CORE_RUNTIME_IDENTITY.memory_search_sqlite_unavailable_warning
    assert DISPLAY_NAME in memory_core["warning"] and "OpenClaw" not in memory_core["action"]
    assert compat["warning"] == (
        "Memory search is unavailable because this OpenClaw Node runtime does not provide "
        "SQLite support."
    )
    assert compat["action"] == (
        "Run OpenClaw with a Node runtime that includes node:sqlite, then retry memory_search."
    )


def test_unavailable_result_overrides_win():
    result = build_memory_search_unavailable_result("quota", warning="W", action="A")
    assert (result["warning"], result["action"]) == ("W", "A")
    assert result["debug"] == {"warning": "W", "action": "A", "error": "quota"}


def test_a_deadline_flag_adds_timed_out_and_the_deadline_guidance():
    # tools.shared.ts:108-140 (d46f9ebf2b2 #147702): the flag, never the text, marks the
    # tool's own deadline; with an agent the action names the agent's index.
    compat = build_memory_search_unavailable_result(
        "memory_search timed out after 30s",
        agent_id="main",
        deadline=True,
        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )
    assert list(compat) == [
        "results", "disabled", "unavailable", "timedOut", "timeoutMs", "error", "warning",
        "action", "debug",
    ]
    assert (compat["timedOut"], compat["timeoutMs"]) == (True, 30_000)
    assert compat["warning"] == "Memory search did not finish within its time limit."
    assert compat["action"] == (
        "Retry memory_search after a short wait: a memory-corpus timeout pauses retries for up "
        "to a minute. If memory-corpus timeouts persist, run: openclaw memory status --deep "
        "--agent main, and rebuild with openclaw memory index --force --agent main only if it "
        "reports the index dirty or incomplete"
    )
    default = build_memory_search_unavailable_result(
        "memory_search timed out after 30s", agent_id="main", deadline=True
    )
    assert default["action"] == MEMORY_CORE_RUNTIME_IDENTITY.memory_search_deadline_agent_action.format(
        agent_id="main"
    )
    assert "openclaw" not in default["action"].lower()
    # No agent (or a blank one): the agent-free action, the same under both identities.
    for agent_id in (None, ""):
        result = build_memory_search_unavailable_result("x", agent_id=agent_id, deadline=True)
        assert result["action"] == (
            "Retry memory_search after a short wait. If memory-corpus timeouts persist, inspect "
            "this agent's memory index before rebuilding it."
        )
    # The same words without the flag are a provider error.
    text_only = build_memory_search_unavailable_result("memory_search timed out after 30s")
    assert "timedOut" not in text_only
    assert text_only["warning"] == "Memory search is unavailable due to an embedding/provider error."
    # Quota and SQLite reasons keep their guidance; the flag still adds timedOut.
    quota = build_memory_search_unavailable_result("insufficient_quota", deadline=True)
    assert quota["timedOut"] is True
    assert quota["action"] == "Top up or switch embedding provider, then retry memory_search."


def test_the_canonical_key_code_wins_over_every_reason():
    compat = build_memory_search_unavailable_result(
        "quota",
        code="SESSION_CANONICAL_KEY_MIGRATION_REQUIRED",
        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )
    assert compat["warning"] == (
        "Memory search is unavailable because the session catalog requires canonical-key "
        "migration."
    )
    assert compat["action"] == (
        "Stop the Gateway and run openclaw doctor --fix, then restart the Gateway and retry "
        "memory_search."
    )
    default = build_memory_search_unavailable_result(
        "quota", code="SESSION_CANONICAL_KEY_MIGRATION_REQUIRED"
    )
    assert default["warning"] == compat["warning"]
    assert default["action"] == (
        MEMORY_CORE_RUNTIME_IDENTITY.memory_search_canonical_key_migration_action
    )
    assert "openclaw" not in default["action"].lower()
    other_code = build_memory_search_unavailable_result("boom", code="EACCES")
    assert other_code == build_memory_search_unavailable_result("boom")


def _short_deadline(monkeypatch):
    # Wait 50 ms instead of the 30 s budget; the deadline and its message stay the real ones.
    monkeypatch.setattr(
        memory_search_module, "_deadline_wait_seconds", lambda remaining: min(remaining, 0.05)
    )


def test_deadline_returns_the_timeout_result_and_abandons_the_search(tmp_path, monkeypatch):
    _short_deadline(monkeypatch)
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider, store_cls=_RecordingStore)
    provider.hang = True

    try:
        # No keyword hit, so the deadline leaves nothing partial (see the partial test below).
        result = memory_search(cfg, store, query="zzzunmatched", corpus="memory")
    finally:
        provider.release.set()

    assert MEMORY_SEARCH_TOOL_TIMEOUT_MS == 30_000
    assert result["unavailable"] is True
    assert result["error"] == "memory_search timed out after 30s"
    # d46f9ebf2b2 (#147702): the deadline flag adds timedOut and the deadline guidance.
    assert (result["timedOut"], result["timeoutMs"]) == (True, 30_000)
    assert result["warning"] == "Memory search did not finish within its time limit."
    assert result["action"] == MEMORY_CORE_RUNTIME_IDENTITY.memory_search_deadline_agent_action.format(
        agent_id="main"
    )
    # The abandoned worker stops at the checkpoint after the embedding call.
    assert store.finished.wait(5)
    assert isinstance(store.outcomes[-1], OperationAbortedError)
    assert str(store.outcomes[-1]) == "memory_search timed out after 30s"


def test_timeout_records_a_cooldown_that_skips_the_provider(tmp_path, monkeypatch, clock):
    _short_deadline(monkeypatch)
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)
    provider.hang = True
    try:
        memory_search(cfg, store, query="zzzunmatched", corpus="memory")
    finally:
        provider.release.set()
    provider.hang = False
    calls = provider.calls

    paused = memory_search(cfg, store, query="glacier", corpus="memory")

    # The cooldown keeps the failure's deadline flag (tools.ts:370-378).
    assert paused["error"] == "memory_search timed out after 30s"
    assert paused["timedOut"] is True
    assert provider.calls == calls


def test_store_errors_become_unavailable_results_with_a_cooldown(tmp_path, clock):
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)
    provider.error = RuntimeError("provider exploded")

    first = memory_search(cfg, store, query="glacier")
    provider.error = None
    second = memory_search(cfg, store, query="glacier", corpus="sessions")
    wiki = memory_search(cfg, store, query="glacier", corpus="wiki")
    all_corpora = memory_search(cfg, store, query="glacier", corpus="all")

    memory_down = {
        "results": [],
        "citations": "on",
        "corpora": [
            {"corpus": "memory", "outcome": "unavailable", "error": "provider exploded"},
            {"corpus": "wiki", "outcome": "not-registered"},
        ],
        "warning": "Memory corpus unavailable: provider exploded",
        "error": "provider exploded",
    }
    # The facade's corpus="all" keeps the other corpus and reports memory per corpus.
    assert first == memory_down
    assert second["unavailable"] is True and second["error"] == "provider exploded"
    assert provider.calls == 1
    # corpus=wiki never reads the cooldown; corpus=all skips memory during it and reports no
    # provider/model because memory was not searched.
    assert wiki == {
        "results": [],
        "citations": "on",
        "corpora": [{"corpus": "wiki", "outcome": "not-registered"}],
        "warning": "Wiki corpus is not registered; results do not cover that requested corpus.",
    }
    assert all_corpora == memory_down


def test_cooldown_expires_when_until_is_reached(tmp_path, clock):
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)
    provider.error = RuntimeError("provider exploded")
    memory_search(cfg, store, query="glacier", corpus="memory")
    provider.error = None

    clock["now"] += MEMORY_SEARCH_TOOL_COOLDOWN_MS - 1
    assert memory_search(cfg, store, query="glacier", corpus="memory")["error"] == (
        "provider exploded"
    )
    clock["now"] += 1  # `until <= Date.now()` expires the entry (tools.ts:88)
    assert [hit["path"] for hit in memory_search(cfg, store, query="glacier")["results"]] == [
        "MEMORY.md"
    ]
    assert (
        read_memory_search_tool_cooldown(
            memory_search_tool_cooldown_key(cfg, store), memory_search_tool_config_key(cfg, store)
        )
        is None
    )


def test_cooldown_is_keyed_by_agent_id(tmp_path, clock):
    provider = _ControlledProvider()
    cfg_a, store_a = _vector_store(tmp_path / "a", provider, agent_id="alpha")
    cfg_b, store_b = _vector_store(tmp_path / "b", provider, agent_id="beta")
    provider.error = RuntimeError("provider exploded")
    memory_search(cfg_a, store_a, query="glacier", corpus="memory")
    provider.error = None

    assert memory_search(cfg_a, store_a, query="glacier", corpus="memory")["unavailable"] is True
    assert memory_search(cfg_b, store_b, query="glacier", corpus="memory")["results"]


def test_cooldown_is_scoped_to_the_store_not_shared_across_workspaces(tmp_path, clock):
    # Deviation from tools.ts:76-81 (agent-only key): two workspaces with the
    # default agent_id "main" have two indexes, so one failing must not pause
    # the other (with corpus="all" that pause would be a silent empty success).
    failing = _ControlledProvider()
    healthy = _ControlledProvider()
    cfg_1 = MemoryConfig(workspace_dir=tmp_path / "ws1")
    cfg_2 = MemoryConfig(workspace_dir=tmp_path / "ws2")
    stores = []
    for cfg, provider in ((cfg_1, failing), (cfg_2, healthy)):
        cfg.workspace_dir.mkdir()
        (cfg.workspace_dir / "MEMORY.md").write_text("- Glacier backups.\n", encoding="utf-8")
        store = SQLiteMemoryStore(cfg, provider)
        store.reindex(MemoryWorkspace(cfg.workspace_dir))
        stores.append(store)
    store_1, store_2 = stores
    assert cfg_1.agent_id == cfg_2.agent_id == "main"
    failing.error = RuntimeError("provider exploded")

    assert memory_search(cfg_1, store_1, query="glacier")["error"] == "provider exploded"
    assert [hit["path"] for hit in memory_search(cfg_2, store_2, query="glacier")["results"]] == [
        "MEMORY.md"
    ]
    assert "disabled" not in memory_search(cfg_2, store_2, query="glacier", corpus="memory")
    assert memory_search(cfg_1, store_1, query="glacier", corpus="memory")["error"] == (
        "provider exploded"
    )
    assert (
        read_memory_search_tool_cooldown(
            memory_search_tool_cooldown_key(cfg_2, store_2),
            memory_search_tool_config_key(cfg_2, store_2),
        )
        is None
    )


def test_stores_on_the_same_index_file_share_a_cooldown(tmp_path, clock):
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)
    same_index = SQLiteMemoryStore(cfg, provider)
    provider.error = RuntimeError("provider exploded")
    memory_search(cfg, store, query="glacier", corpus="memory")
    provider.error = None

    assert memory_search_tool_cooldown_key(cfg, same_index) == memory_search_tool_cooldown_key(
        cfg, store
    )
    assert memory_search(cfg, same_index, query="glacier", corpus="memory")["error"] == (
        "provider exploded"
    )
    # v2026.9.6 keys the cooldown by agent alone (tools.ts:269): no session-key fallback.
    assert memory_search_tool_cooldown_key(cfg, store).endswith("\0main")
    assert memory_search(
        cfg, store, query="glacier", corpus="memory", agent_session_key="agent:main:other"
    )["error"] == "provider exploded"


def test_default_corpus_all_reports_a_cooldown_per_corpus(tmp_path, clock):
    # tools.ts:436-550: with a cooldown, corpus=all skips memory, keeps the supplement hits and
    # marks memory unavailable in `corpora`. The facade default is corpus="all" (decision D8);
    # upstream's omitted corpus returns the unavailable result instead.
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)
    provider.error = RuntimeError("provider exploded")
    assert memory_search(cfg, store, query="glacier", corpus=None)["unavailable"] is True
    provider.error = None

    during = memory_search(cfg, store, query="glacier")
    assert during["results"] == [] and "unavailable" not in during
    assert during["corpora"][0] == {
        "corpus": "memory", "outcome": "unavailable", "error": "provider exploded"
    }
    assert memory_search(cfg, store, query="glacier", corpus=None)["error"] == "provider exploded"


def test_a_cooldown_belongs_to_the_configuration_that_recorded_it(tmp_path, clock):
    # tools.ts:100-118: a cooldown recorded under another runtime configuration is dropped.
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)
    provider.error = RuntimeError("provider exploded")
    memory_search(cfg, store, query="glacier", corpus="memory")
    provider.error = None
    other = dataclasses.replace(cfg, citation_mode="off")
    key = memory_search_tool_cooldown_key(cfg, store)

    assert memory_search_tool_config_key(other, store) != memory_search_tool_config_key(cfg, store)
    assert [hit["path"] for hit in memory_search(other, store, query="glacier", corpus="memory")[
        "results"
    ]] == ["MEMORY.md"]
    # The read under the other configuration dropped the entry.
    assert read_memory_search_tool_cooldown(key, memory_search_tool_config_key(cfg, store)) is None


def test_supplement_failure_under_corpus_all_records_no_cooldown(tmp_path, clock):
    class _BrokenWiki:
        def search(self, **_):
            raise RuntimeError("wiki down")

        def get(self, **_):
            return None

    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)

    failed = memory_search(cfg, store, query="glacier", corpus="all", supplements=[_BrokenWiki()])
    wiki_failed = memory_search(
        cfg, store, query="glacier", corpus="wiki", supplements=[_BrokenWiki()]
    )

    assert failed["error"] == wiki_failed["error"] == "wiki down"
    assert failed["corpora"] == [
        {"corpus": "memory", "outcome": "ok"},
        {"corpus": "wiki", "outcome": "unavailable", "error": "wiki down"},
    ]
    assert [hit["path"] for hit in failed["results"]] == ["MEMORY.md"]
    key = memory_search_tool_cooldown_key(cfg, store)
    config_key = memory_search_tool_config_key(cfg, store)
    assert read_memory_search_tool_cooldown(key, config_key) is None
    record_memory_search_tool_cooldown(key, config_key, {"error": "x", "deadline": False, "code": "E"})
    assert read_memory_search_tool_cooldown(key, config_key) == {
        "error": "x", "deadline": False, "code": "E"
    }


def test_deadline_runs_from_an_event_loop_and_from_other_threads(tmp_path):
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "fts.sqlite",
        flags=FeatureFlags(vector_search=False),
    )
    (tmp_path / "MEMORY.md").write_text("- Glacier storage.\n", encoding="utf-8")
    store = SQLiteMemoryStore(cfg, None)
    store.reindex(MemoryWorkspace(tmp_path))

    async def inside_loop():
        return memory_search(cfg, store, query="glacier")

    from_loop = asyncio.run(inside_loop())
    from_thread = {}
    worker = threading.Thread(
        target=lambda: from_thread.update(memory_search(cfg, store, query="glacier"))
    )
    worker.start()
    worker.join(5)

    assert [hit["path"] for hit in from_loop["results"]] == ["MEMORY.md"]
    assert from_thread == from_loop


def test_store_search_honours_an_aborted_signal(tmp_path):
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "fts.sqlite",
        flags=FeatureFlags(vector_search=False),
    )
    store = SQLiteMemoryStore(cfg, None)
    signal = CancellationSignal()
    signal.abort("stop")

    with pytest.raises(OperationAbortedError, match="^stop$"):
        store.search("glacier", signal=signal)


def test_cancellation_signal_runs_listeners_once():
    signal = CancellationSignal()
    seen = []
    remove = signal.add_listener(lambda: seen.append("a"))
    signal.add_listener(lambda: seen.append("b"))
    remove()

    signal.abort("first")
    signal.abort("second")
    signal.add_listener(lambda: seen.append("late"))

    assert signal.aborted and signal.reason == "first"
    assert seen == ["b", "late"]


def test_format_error_message_follows_the_explicit_cause_chain():
    class _CodedError(Exception):
        code = "ECONNRESET"

    try:
        try:
            raise _CodedError("socket closed")
        except _CodedError as inner:
            raise RuntimeError("embedding failed") from inner
    except RuntimeError as outer:
        assert format_error_message(outer) == "embedding failed | socket closed | ECONNRESET"

    assert format_error_message(ValueError()) == "ValueError"
    assert format_error_message("plain") == "plain"


def test_cooldown_remaining_reports_the_time_left_and_expires(tmp_path, clock):
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)
    key = memory_search_tool_cooldown_key(cfg, store)
    assert memory_search_tool_cooldown_remaining(key) is None
    provider.error = RuntimeError("provider exploded")
    memory_search(cfg, store, query="glacier", corpus="memory")

    clock["now"] += 1_000
    assert memory_search_tool_cooldown_remaining(key) == (
        MEMORY_SEARCH_TOOL_COOLDOWN_MS - 1_000, {"error": "provider exploded", "deadline": False}
    )
    assert memory_search_tool_cooldown_remaining(key, "another configuration") is None
    assert memory_search_tool_cooldown_remaining(key) is None  # dropped by the read above
    provider.error = RuntimeError("provider exploded")
    memory_search(cfg, store, query="glacier", corpus="memory")
    clock["now"] += MEMORY_SEARCH_TOOL_COOLDOWN_MS
    assert memory_search_tool_cooldown_remaining(key) is None


def _hit(path: str, score: float | None, corpus: str = "memory") -> dict:
    return {"corpus": corpus, "path": path, **({} if score is None else {"score": score})}


def test_merge_keeps_each_stream_order_and_compares_only_the_heads():
    # tools.ts:168-230 mergeMemorySearchCorpusResults. Memory scores need not be sorted: each
    # stream keeps its own order.
    memory = [_hit("m1", 0.2), _hit("m2", 0.9), _hit("m3", 0.1)]
    wiki = [_hit("w1", 0.5, "wiki"), _hit("w2", 0.4, "wiki")]

    unbalanced = merge_memory_search_corpus_results(
        memory_results=memory, supplement_results=wiki, max_results=4, balance_corpora=False
    )
    balanced = merge_memory_search_corpus_results(
        memory_results=memory, supplement_results=wiki, max_results=3, balance_corpora=True
    )
    more_budget = merge_memory_search_corpus_results(
        memory_results=memory, supplement_results=wiki, max_results=5, balance_corpora=True
    )

    assert [item["path"] for item in unbalanced] == ["w1", "w2", "m1", "m2"]
    # ceil(3/2) = 2 per corpus; the merge of m1,m2 with w1,w2 by heads, cut to 3.
    assert [item["path"] for item in balanced] == ["w1", "w2", "m1"]
    assert [item["path"] for item in more_budget] == ["w1", "w2", "m1", "m2", "m3"]


def test_balanced_merge_gives_the_spare_budget_to_the_higher_next_item():
    memory = [_hit("m1", 0.9), _hit("m2", 0.8), _hit("m3", 0.7), _hit("m4", 0.6)]
    wiki = [_hit("w1", 0.5, "wiki")]
    unscored = [_hit("u1", None, "wiki"), _hit("u2", None, "wiki")]

    assert [
        item["path"]
        for item in merge_memory_search_corpus_results(
            memory_results=memory, supplement_results=wiki, max_results=4, balance_corpora=True
        )
    ] == ["m1", "m2", "m3", "w1"]
    # An unscored supplement item never outranks a scored memory item (`>=` with undefined is
    # false, the stream heads compare `score ?? 0`).
    assert [
        item["path"]
        for item in merge_memory_search_corpus_results(
            memory_results=memory[:1], supplement_results=unscored, max_results=3,
            balance_corpora=True,
        )
    ] == ["m1", "u1", "u2"]
    assert merge_memory_search_corpus_results(
        memory_results=[], supplement_results=wiki, max_results=3, balance_corpora=True
    ) == wiki


def test_sessions_search_needs_sessions_in_the_search_sources(tmp_path):
    # tools.ts:255-267 (decision D1: memory-core searches sessions by default).
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)

    default = memory_search(cfg, store, query="glacier", corpus="sessions", search_sources=["memory"])
    compat = memory_search(
        cfg,
        store,
        query="glacier",
        corpus="sessions",
        search_sources=["memory"],
        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )
    searched = memory_search(cfg, store, query="glacier", corpus="sessions")

    assert provider.calls == 1
    assert default["error"] == "Session transcript search is not enabled."
    assert default["warning"] == "Session transcript search is unavailable for this agent."
    assert default["action"] == MEMORY_CORE_RUNTIME_IDENTITY.session_search_not_enabled_action
    assert "memory.search" not in default["action"]
    assert compat["action"] == (
        "If an exact session-history capability is available for this run, use it. Otherwise, "
        "ask the operator to enable semantic session search by enabling "
        'memory.search.experimental.sessionMemory and adding "sessions" to memory.search.sources.'
    )
    assert searched["results"] == [] and "unavailable" not in searched


def test_on_recall_gets_the_returned_memory_hits_of_an_ok_search_only(tmp_path, clock):
    # tools.ts:477-508: only memory-corpus evidence actually returned earns a recall signal,
    # and only when the memory search was ok or partial.
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-09-30.md").write_text("- Glacier trip notes.\n", encoding="utf-8")
    store.reindex(MemoryWorkspace(tmp_path))

    class _Wiki:
        def search(self, **_):
            return [{"corpus": "wiki", "path": "w.md", "score": 99, "snippet": "glacier"}]

        def get(self, **_):
            return None

    recalls: list[list[dict]] = []
    ok = memory_search(
        cfg, store, query="glacier", max_results=2, corpus="all", supplements=[_Wiki()],
        on_recall=recalls.append,
    )
    provider.error = RuntimeError("provider exploded")
    memory_search(cfg, store, query="glacier", corpus="all", supplements=[_Wiki()],
                  on_recall=recalls.append)
    provider.error = None

    def boom(_hits):
        raise RuntimeError("recording failed")

    clock["now"] += MEMORY_SEARCH_TOOL_COOLDOWN_MS
    still_ok = memory_search(cfg, store, query="glacier", corpus="memory", on_recall=boom)

    assert [item["path"] for item in ok["results"]] == ["w.md", "MEMORY.md"]
    assert len(recalls) == 1
    assert [item["path"] for item in recalls[0]] == ["MEMORY.md"]
    assert recalls[0][0] is ok["results"][1]
    assert still_ok["results"]


def test_a_deadline_after_the_keyword_leg_is_a_partial_result(tmp_path, monkeypatch, clock):
    # tools.ts:297-365 and 509-550 with memory-search-tool-query.ts:133-160 (d46f9ebf2b2 #147702):
    # the keyword leg publishes the memory-file hits before the query is embedded; the deadline
    # then leaves a partial memory corpus, which records no cooldown.
    _short_deadline(monkeypatch)
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)
    provider.hang = True
    try:
        partial = memory_search(cfg, store, query="glacier", corpus="memory")
    finally:
        provider.release.set()
    provider.hang = False
    calls = provider.calls
    after = memory_search(cfg, store, query="glacier", corpus="memory")

    assert [hit["path"] for hit in partial["results"]] == ["MEMORY.md"]
    assert partial["partial"] is True and "unavailable" not in partial
    assert (partial["timedOut"], partial["timeoutMs"]) == (True, 30_000)
    assert partial["corpora"] == [
        {"corpus": "memory", "outcome": "partial", "error": "memory_search timed out after 30s"}
    ]
    assert partial["warning"] == (
        "Memory corpus partial: memory_search timed out after 30s Only memory-file keyword "
        "matches are included; semantic memory retrieval did not finish within the search time "
        "limit. Session transcript results are not included."
    )
    assert (partial["provider"], partial["model"]) == ("fake", "fake-deterministic")
    assert after["results"] and provider.calls == calls + 1


def test_no_keyword_hit_or_no_keyword_leg_leaves_the_deadline_unavailable(tmp_path, monkeypatch):
    _short_deadline(monkeypatch)
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)
    vector_only = dataclasses.replace(cfg, flags=FeatureFlags(text_search=False))
    provider.hang = True
    try:
        no_hit = memory_search(cfg, store, query="zzzunmatched", corpus="memory")
        memory_search_module.reset_memory_search_tool_cooldowns()
        no_leg = memory_search(
            vector_only, SQLiteMemoryStore(vector_only, provider), query="glacier",
            corpus="memory",
        )
    finally:
        provider.release.set()

    assert no_hit["unavailable"] is True and no_hit["timedOut"] is True
    assert no_leg["unavailable"] is True and no_leg["error"] == "memory_search timed out after 30s"


def test_the_store_publishes_memory_keyword_hits_before_embedding(tmp_path):
    provider = _ControlledProvider()
    cfg, store = _vector_store(tmp_path, provider)
    events: list[object] = []
    provider_embed = provider.embed_query
    provider.embed_query = lambda text: events.append("embed") or provider_embed(text)

    hits = store.search("glacier", on_partial_results=lambda partial: events.append(partial))
    provider.error = RuntimeError("provider exploded")
    with pytest.raises(RuntimeError):
        store.search("glacier", on_partial_results=lambda partial: events.append(partial))

    first, second, third, fourth, fifth = events
    assert [item.path for item in first] == ["MEMORY.md"] and second == "embed"
    # A failed embedding invalidates the snapshot; keyword-only stores publish nothing.
    assert [item.path for item in third] == ["MEMORY.md"] and fourth == "embed"
    assert fifth is None
    assert [item.path for item in hits] == ["MEMORY.md"]
    fts_cfg = MemoryConfig(
        workspace_dir=tmp_path, store_path=tmp_path / "fts.sqlite",
        flags=FeatureFlags(vector_search=False),
    )
    fts = SQLiteMemoryStore(fts_cfg, None)
    fts.reindex(MemoryWorkspace(tmp_path))
    published: list[object] = []
    assert fts.search("glacier", on_partial_results=published.append) and published == []
