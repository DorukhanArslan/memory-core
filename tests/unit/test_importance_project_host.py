"""Trusted project context reaches real storage and survives tool serialization."""
from __future__ import annotations

import importlib
import threading

import pytest

from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, SessionState
from memory_core.tools.memory_search import (
    MemorySearchToolContext, execute_memory_search_tool, memory_search_tool_definition,
)


_ALPHA = "github.com/acme/Alpha"
_BETA = "github.com/acme/Beta"
_SESSION = SessionState.new(session_key="agent:main:main", session_id="project-host")
_TOOLS = importlib.import_module("memory_core.tools.memory_search")


class _ConstantEmbedding:
    provider_id = "host-project-fixture"
    model = "fixture-model"

    def embed_query(self, _query):
        return [1.0, 0.0]

    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _memory(root, mode="keyword"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "MEMORY.md").write_text(
        "# MEMORY.md\n\n"
        "- emberquartz Alpha keeps the deployment schedule. "
        f"<!-- importance: 8 --><!-- trigger: launch; release --><!-- project: {_ALPHA} -->\n"
        "- emberquartz Beta keeps the deployment schedule. "
        f"<!-- importance: 8 --><!-- trigger: launch; release --><!-- project: {_BETA} -->\n",
        encoding="utf-8",
    )
    flags = FeatureFlags(vector_search=mode != "keyword", text_search=mode != "vector",
                         temporal_decay=False, mmr=False)
    return Memory.from_workspace(
        root, initialize=False,
        config=MemoryConfig(workspace_dir=root, flags=flags, citation_mode="off"),
        embedding_provider=None if mode == "keyword" else _ConstantEmbedding(),
    )


@pytest.mark.parametrize("mode,components", [
    ("keyword", {"textScore"}), ("vector", set()),
    ("hybrid", {"textScore", "vectorScore"}),
])
def test_public_memory_api_routes_host_projects_and_preserves_metadata(tmp_path, mode, components):
    memory = _memory(tmp_path, mode)

    beta = memory.search("emberquartz", max_results=2, active_project_keys=[_BETA])
    alpha = memory.search("emberquartz", max_results=2, active_project_keys=[_ALPHA])

    assert beta["results"][0]["projectKey"] == _BETA
    assert alpha["results"][0]["projectKey"] == _ALPHA
    for hit in beta["results"]:
        assert hit["importance"] == 8
        assert hit["triggers"] == "launch; release"
        assert hit["projectKey"] in {_ALPHA, _BETA}
        assert set(hit["provenance"]) == {"originClass", "sessionKind", "observedAt"}
        assert hit["provenance"]["originClass"] == "agent"
        assert "sourceMtime" not in hit
        assert set(hit) & {"textScore", "vectorScore"} == components


def test_model_project_arguments_cannot_override_trusted_host_context(tmp_path):
    memory = _memory(tmp_path)
    context = MemorySearchToolContext(clock=lambda: 1_738_368_000_000)
    arguments = {"query": "emberquartz", "maxResults": 2,
                 "activeProjectKeys": [_BETA], "active_project_keys": [_BETA]}

    trusted = execute_memory_search_tool(
        memory.config, memory.store, arguments, active_project_keys=[_ALPHA], context=context,
    )
    untrusted_only = execute_memory_search_tool(
        memory.config, memory.store, arguments, context=context,
    )
    ordinary = execute_memory_search_tool(
        memory.config, memory.store, {"query": "emberquartz", "maxResults": 2},
        context=context,
    )

    assert trusted["results"][0]["projectKey"] == _ALPHA
    assert untrusted_only == ordinary
    properties = memory_search_tool_definition()["parameters"]["properties"]
    assert "activeProjectKeys" not in properties
    assert "active_project_keys" not in properties


def test_host_kit_snapshots_host_context_and_ignores_model_override(tmp_path):
    memory = _memory(tmp_path)
    active = [_BETA]
    kit = HostKit(memory, active_project_keys=active, seed_bootstrap=False)
    active[:] = [_ALPHA]

    result = kit.dispatch("memory_search", {
        "query": "emberquartz", "maxResults": 2, "activeProjectKeys": [_ALPHA],
    }, session=_SESSION)

    assert result["results"][0]["projectKey"] == _BETA
    assert memory.search("emberquartz", active_project_keys=[_ALPHA])["results"][0]["projectKey"] == _ALPHA


def test_deadline_keyword_fallback_retains_the_same_host_project_context(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    release = threading.Event()
    finished = threading.Event()
    seen = []

    def blocked_search(_query, *, signal, **options):
        seen.append(options["active_project_keys"])
        try:
            assert release.wait(3)
            signal.throw_if_aborted()
        finally:
            finished.set()

    monkeypatch.setattr(memory.store, "search", blocked_search)
    monkeypatch.setattr(_TOOLS, "_deadline_seconds", lambda _milliseconds: 0.02)
    try:
        result = execute_memory_search_tool(
            memory.config, memory.store,
            {"query": "emberquartz", "maxResults": 2, "activeProjectKeys": [_ALPHA]},
            active_project_keys=[_BETA],
        )
    finally:
        release.set()
        assert finished.wait(3)

    assert seen == [(_BETA,)]
    assert result["partial"] is True
    assert result["results"][0]["projectKey"] == _BETA
    assert result["results"][0]["importance"] == 8
    assert "sourceMtime" not in result["results"][0]


def test_omitted_host_projects_do_not_add_a_keyword_to_legacy_search_backend(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    actual_search = memory.store.search
    calls = []

    def legacy_search(query, *, max_results, min_score, sources, signal):
        calls.append(query)
        return actual_search(query, max_results=max_results, min_score=min_score,
                             sources=sources, signal=signal)

    monkeypatch.setattr(memory.store, "search", legacy_search)
    result = memory.search("emberquartz", max_results=2)

    assert calls == ["emberquartz"]
    assert len(result["results"]) == 2
