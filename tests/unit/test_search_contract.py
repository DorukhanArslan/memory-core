"""Whole-tool regressions for the pinned native memory_search contract.

These drive the production executor and a real indexed SQLite store. Separate
equivalence tests compare the same public payload with the native factory.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.hybrid import HybridResult
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.supplements import StaticMemoryCorpusSupplement
from memory_core.tools.common import MemoryToolError
from memory_core.tools.memory_search import (
    MEMORY_SEARCH_SESSION_MIGRATION_CODE,
    MemorySearchToolContext,
    build_memory_search_unavailable_result,
    execute_memory_search_tool,
)
from memory_core.workspace import MemoryWorkspace


def indexed_store(tmp_path: Path, **overrides) -> tuple[MemoryConfig, SQLiteMemoryStore]:
    (tmp_path / "MEMORY.md").write_text("Cobalt router is in the rack.\n", encoding="utf-8")
    config = MemoryConfig(
        workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False),
        session_search=False, **overrides,
    )
    store = SQLiteMemoryStore(config, None)
    store.reindex(MemoryWorkspace(tmp_path))
    return config, store


def test_raw_tool_resolves_query_defaults_and_explicit_values(tmp_path, monkeypatch):
    config, store = indexed_store(tmp_path)
    search = store.search
    observed = []

    def record(query, **options):
        observed.append((query, options.copy()))
        return search(query, **options)

    monkeypatch.setattr(store, "search", record)
    context = MemorySearchToolContext(clock=lambda: 100)
    execute_memory_search_tool(config, store, {"query": " cobalt "}, context=context)
    configured = replace(config, search_max_results=3, search_min_score=0.2)
    execute_memory_search_tool(configured, store, {"query": "cobalt"}, context=context)
    execute_memory_search_tool(
        configured, store, {"query": "cobalt", "max_results": "2", "minScore": 0},
        context=context,
    )

    assert [(query, opts["max_results"], opts["min_score"]) for query, opts in observed] == [
        ("cobalt", 6, 0.35), ("cobalt", 3, 0.2), ("cobalt", 2, 0),
    ]


def test_real_store_result_and_full_debug_have_native_field_presence(tmp_path):
    config, store = indexed_store(tmp_path, memory_get_max_chars=1)
    clock = iter([100, 101, 105, 111])
    result = execute_memory_search_tool(
        config, store, {"query": "cobalt", "minScore": 0},
        context=MemorySearchToolContext(clock=lambda: next(clock), manager_ms=2),
    )

    assert result["provider"] == "none"
    assert "model" not in result
    assert result["citations"] == "auto"
    assert "mode" not in result
    assert result["debug"] == {
        "backend": "builtin", "effectiveMode": "n/a", "managerMs": 2,
        "searchMs": 4, "hits": 1, "candidateHits": 1, "withheldHits": 0,
        "searchWindow": 6, "toolMs": 11, "outsideSearchMs": 7,
    }
    hit = result["results"][0]
    assert hit["citation"] == "MEMORY.md#L1-L2"
    assert hit["snippet"].startswith("Cobalt router is in the rack.")
    assert hit["snippet"].endswith("\n\nSource: MEMORY.md#L1-L2")
    assert hit["corpus"] == "memory"
    assert "textScore" in hit
    assert "vectorScore" not in hit
    assert not {"sourceMtime", "truncated", "originalChars"}.intersection(hit)


@pytest.mark.parametrize("mode,session_key,included", [
    ("on", "agent:main:discord:channel:7", True),
    ("off", "agent:main:main", False),
    ("auto", "agent:main:main", True),
    ("auto", "agent:main:discord:channel:7", False),
    ("auto", "agent:main:telegram:group:7", False),
    ("invalid-host-mode", "agent:main:main", True),
])
def test_citation_policy_runs_on_whole_tool(tmp_path, mode, session_key, included):
    config, store = indexed_store(tmp_path, citation_mode=mode)
    result = execute_memory_search_tool(
        config, store, {"query": "cobalt", "minScore": 0},
        agent_session_key=session_key, context=MemorySearchToolContext(clock=lambda: 100),
    )
    hit = result["results"][0]
    assert ("citation" in hit) is included
    assert ("\n\nSource: " in hit["snippet"]) is included
    assert result["citations"] == ("auto" if mode == "invalid-host-mode" else mode)


def test_custom_result_keeps_native_branch_metadata_without_search_clamp(tmp_path, monkeypatch):
    config, store = indexed_store(tmp_path, memory_get_max_chars=1)
    vector = HybridResult(
        path="memory/a.md", start_line=2, end_line=4, score=0.8,
        vector_score=0.8, text_score=0, snippet="  Cobalt survives.  \n",
        source="memory", importance=None, triggers="router", project_key=None,
        provenance={"originClass": "owner", "sessionKind": "interactive", "observedAt": 42},
        source_mtime=123, _vector_id="chunk-vector", _retrieval_mode="vector",
    )
    monkeypatch.setattr(store, "search", lambda *args, **kwargs: [vector])
    result = execute_memory_search_tool(
        config, store, {"query": "cobalt"}, context=MemorySearchToolContext(clock=lambda: 100),
    )
    assert result["results"] == [{
        "id": "chunk-vector", "path": "memory/a.md", "startLine": 2, "endLine": 4,
        "score": 0.8, "snippet": "  Cobalt survives.\n\nSource: memory/a.md#L2-L4",
        "source": "memory", "corpus": "memory", "citation": "memory/a.md#L2-L4",
        "importance": None, "triggers": "router", "projectKey": None,
        "provenance": {"originClass": "owner", "sessionKind": "interactive", "observedAt": 42},
    }]


def test_live_status_and_debug_events_are_preserved_and_rebuild_notice_is_transitioned(
    tmp_path, monkeypatch,
):
    config, store = indexed_store(tmp_path)
    notice = {"sequence": 0, "warning": "Old repair notice."}
    status = {
        "backend": "builtin", "provider": "none", "model": "fts-only",
        "fallback": {"from": "remote", "reason": "offline"},
        "custom": {"indexIdentity": store.index_identity(), "automaticRebuildNotice": notice},
    }
    events = []
    search = store.search

    def repaired(query, **options):
        results = search(query, **options)
        notice.update(sequence=1, warning="Memory index was rebuilt.")
        status["lastSyncError"] = "  background sync failed  "
        events.append({"configuredMode": "hybrid", "effectiveMode": "keyword-only",
                       "fallback": "provider unavailable", "embeddingBootstrap": {"attempts": 2}})
        return results

    monkeypatch.setattr(store, "search", repaired)
    result = execute_memory_search_tool(
        config, store, {"query": "cobalt", "corpus": "all", "minScore": 0},
        context=MemorySearchToolContext(
            status=lambda: status, runtime_debug=lambda: events, clock=lambda: 100,
        ), runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )

    assert result["fallback"] == {"from": "remote", "reason": "offline"}
    assert result["mode"] == "keyword-only"
    assert result["stale"] is True
    assert result["action"] == (
        "Run: openclaw memory status --index --agent main. "
        "Rebuilding uses keyword indexing only and does not call an embedding provider."
    )
    assert result["warning"] == (
        "Memory index was rebuilt. Memory index is stale: background sync failed. "
        "Search results may be incomplete."
    )
    assert result["debug"]["configuredMode"] == "hybrid"
    assert result["debug"]["effectiveMode"] == "n/a"
    assert result["debug"]["fallback"] == "provider unavailable"
    assert result["debug"]["embeddingBootstrap"] == {"attempts": 2}


def test_existing_rebuild_notice_is_not_replayed_and_wiki_keeps_its_presentation(tmp_path):
    config, store = indexed_store(tmp_path)
    status = {
        "provider": "none", "model": "fts-only",
        "custom": {"indexIdentity": store.index_identity(), "automaticRebuildNotice": {
            "sequence": 3, "warning": "Already announced.",
        }},
    }
    wiki = StaticMemoryCorpusSupplement([{
        "path": "guide.md", "corpus": "wiki", "snippet": "Wiki evidence", "score": 9,
        "citation": "host-wiki-reference", "pluginExtra": {"answer": 42},
    }])
    result = execute_memory_search_tool(
        config, store, {"query": "cobalt", "corpus": "all", "minScore": 0},
        supplements=[wiki], context=MemorySearchToolContext(status=lambda: status, clock=lambda: 100),
    )
    assert "warning" not in result
    assert result["results"][0] == {
        "path": "guide.md", "corpus": "wiki", "snippet": "Wiki evidence", "score": 9,
        "citation": "host-wiki-reference", "pluginExtra": {"answer": 42},
    }


def test_host_only_corpus_override_prevents_model_broadening(tmp_path, monkeypatch):
    config, store = indexed_store(tmp_path)
    observed = []

    def search(query, **options):
        observed.append(options)
        return []

    monkeypatch.setattr(store, "search", search)
    result = execute_memory_search_tool(
        config, store, {"query": "cobalt", "corpus": "all"},
        context=MemorySearchToolContext(conversation_recall_corpus="sessions", clock=lambda: 100),
    )
    assert observed[0]["sources"] == {"sessions"}
    assert result["results"] == []
    assert "corpora" not in result


def test_live_disable_precedes_argument_validation(tmp_path):
    config, store = indexed_store(tmp_path)
    with pytest.raises(MemoryToolError, match="Memory is disabled") as raised:
        execute_memory_search_tool(
            config, store, {"query": ""}, context=MemorySearchToolContext(enabled=lambda: False),
        )
    assert raised.value.name == "Error"
    assert not hasattr(raised.value, "status")


def test_canonical_session_failure_code_reaches_whole_tool_warning(tmp_path, monkeypatch):
    config, store = indexed_store(tmp_path)

    class MigrationRequired(RuntimeError):
        code = MEMORY_SEARCH_SESSION_MIGRATION_CODE

    def failed(*args, **kwargs):
        raise MigrationRequired("  429 canonical session keys required  ")

    monkeypatch.setattr(store, "search", failed)
    result = execute_memory_search_tool(
        config, store, {"query": "cobalt"}, runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
    )
    assert result == {
        "results": [], "disabled": True, "unavailable": True,
        "error": "429 canonical session keys required",
        "warning": "Memory search is unavailable because the session catalog requires canonical-key migration.",
        "action": "Stop the Gateway and run openclaw doctor --fix, then restart the Gateway and retry memory_search.",
        "debug": {
            "error": "429 canonical session keys required",
            "warning": "Memory search is unavailable because the session catalog requires canonical-key migration.",
            "action": "Stop the Gateway and run openclaw doctor --fix, then restart the Gateway and retry memory_search.",
        },
    }


def test_timeout_warning_uses_deadline_provenance_not_message():
    provider = build_memory_search_unavailable_result("memory_search timed out after 30s")
    deadline = build_memory_search_unavailable_result("memory_search timed out after 30s", deadline=True)
    assert "timedOut" not in provider
    assert provider["warning"] == "Memory search is unavailable due to an embedding/provider error."
    assert deadline["timedOut"] is True
    assert deadline["timeoutMs"] == 30_000
    assert deadline["warning"] == "Memory search did not finish within its time limit."
