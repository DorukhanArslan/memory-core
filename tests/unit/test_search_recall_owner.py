"""Search recall policy over real stores, ledgers, events and host boundaries."""

from dataclasses import replace
import threading

import pytest

import memory_core.tools.memory_search as search_module
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.consolidation.origins import MemoryEntryOriginLedger
from memory_core.consolidation.store import read_recall_store, recall_store_path
from memory_core.flags import FeatureFlags
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.host import HostKit, SessionState
from memory_core.runtime_identity import MEMORY_CORE_RUNTIME_IDENTITY, OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_visibility import SessionVisibilityContext, SessionVisibilityPolicy
from memory_core.supplements import StaticMemoryCorpusSupplement
from memory_core.tools.memory_search import MemorySearchToolContext, execute_memory_search_tool, reset_memory_search_tool_cooldowns
from memory_core.tools.common import MemoryToolError
from memory_core.tools.search_factory import create_memory_search_tool

NOW = 1794614400000
REQUESTER = "agent:main:direct:requester"


@pytest.fixture
def memory(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory/2026-11-13.md").write_text("- Cedar maple is the durable preference.\n")
    config = MemoryConfig(tmp_path, citation_mode="on", search_min_score=0,
                          flags=FeatureFlags(vector_search=False, mmr=False, temporal_decay=False))
    value = Memory.from_workspace(tmp_path, config=config, initialize=False)
    reset_memory_search_tool_cooldowns()
    yield value
    reset_memory_search_tool_cooldowns()


def _tool(memory, **options):
    return create_memory_search_tool(memory.config, memory.store,
        context=MemorySearchToolContext(clock=lambda: NOW), agent_session_key=REQUESTER, **options)


def _entries(memory):
    return read_recall_store(recall_store_path(memory.workspace.root), NOW)["entries"]


@pytest.mark.parametrize("identity", [MEMORY_CORE_RUNTIME_IDENTITY, OPENCLAW_COMPAT_RUNTIME_IDENTITY])
def test_factory_default_records_raw_surfaced_hit_once_with_actual_event_and_timezone(memory, identity):
    events = []
    tool = _tool(memory, runtime_identity=identity, on_event=events.append, dreaming_timezone="America/Los_Angeles")
    details = tool.execute("search", {"query": "cedar", "minScore": 0})["details"]
    tool.wait_for_recalls(timeout=5)

    hit = details["results"][0]
    entry, = _entries(memory).values()
    assert hit["snippet"].endswith("Source: memory/2026-11-13.md#L1-L2")
    assert entry["snippet"] == "- Cedar maple is the durable preference."
    assert entry["recallCount"] == 1 and entry["recallDays"] == ["2026-11-13"]
    assert events == [{"type": "memory.recall.recorded", "timestamp": "2026-11-14T00:00:00.000Z",
                       "query": "cedar", "resultCount": 1, "results": [{
                           "path": hit["path"], "startLine": hit["startLine"], "endLine": hit["endLine"],
                           "score": hit["score"]}]}]


def test_direct_retrieval_and_explicit_factory_off_remain_without_recall_side_effects(memory):
    events = []
    assert memory.store.search("cedar")
    assert execute_memory_search_tool(memory.config, memory.store, {"query": "cedar"})["results"]
    tool = _tool(memory, dreaming_enabled=False, on_event=events.append)
    assert tool.execute("off", {"query": "cedar"})["details"]["results"]
    tool.wait_for_recalls(timeout=5)
    assert not recall_store_path(memory.workspace.root).exists() and events == []


def test_live_dreaming_policy_can_revoke_recording_without_revoking_search(memory):
    enabled = [True]
    resolutions = []

    def policy():
        resolutions.append(enabled[0])
        return enabled[0]

    tool = _tool(memory, dreaming_enabled=policy)
    tool.execute("enabled", {"query": "cedar"})
    tool.wait_for_recalls(timeout=5)
    enabled[0] = False
    assert tool.execute("disabled", {"query": "cedar"})["details"]["results"]
    tool.wait_for_recalls(timeout=5)
    assert resolutions == [True, False]
    assert next(iter(_entries(memory).values()))["recallCount"] == 1


@pytest.mark.parametrize("failure", [False, True])
def test_no_results_or_unavailable_search_does_not_emit_or_record(memory, monkeypatch, failure):
    events = []
    if failure:
        def fail(*arguments, **options):
            raise RuntimeError("Actual search provider failed")
        monkeypatch.setattr(memory.store, "search", fail)
    tool = _tool(memory, on_event=events.append)
    result = tool.execute("empty", {"query": "absent-spruce-token"})["details"]
    tool.wait_for_recalls(timeout=5)
    assert result["results"] == []
    assert bool(result.get("unavailable")) is failure
    assert events == [] and not recall_store_path(memory.workspace.root).exists()


def test_factory_persistence_is_off_reply_path_and_event_failure_does_not_change_search(memory):
    entered, release = threading.Event(), threading.Event()

    def blocked_sink(event):
        entered.set()
        assert release.wait(5)
        raise RuntimeError("The real host event sink failed after the recall commit")

    tool = _tool(memory, on_event=blocked_sink)
    try:
        result = tool.execute("async", {"query": "cedar"})["details"]
        assert result["results"] and "unavailable" not in result
        assert entered.wait(5) and not release.is_set()
    finally:
        release.set()
        tool.wait_for_recalls(timeout=5)
    assert next(iter(_entries(memory).values()))["recallCount"] == 1
    assert "unavailable" not in tool.execute("subsequent", {"query": "cedar"})["details"]
    tool.wait_for_recalls(timeout=5)


def test_only_primary_hits_remaining_after_corpus_blending_earn_recalls(memory):
    (memory.workspace.root / "memory/2026-11-12.md").write_text("- Cedar maple is another preference.\n")
    memory.store.reindex(memory.workspace)
    events = []
    wiki = StaticMemoryCorpusSupplement([{"path": "wiki/cedar", "snippet": "Wiki cedar", "corpus": "wiki", "score": 10}])
    tool = _tool(memory, on_event=events.append, supplements=[wiki])
    result = tool.execute("blended", {"query": "cedar", "corpus": "all", "maxResults": 2})["details"]
    tool.wait_for_recalls(timeout=5)
    primary = [hit for hit in result["results"] if hit.get("corpus") == "memory"]
    assert len(primary) == 1 and len(result["results"]) == 2
    assert {entry["path"] for entry in _entries(memory).values()} == {hit["path"] for hit in primary}
    assert [event["resultCount"] for event in events] == [1]


def test_actual_keyword_partial_after_provider_deadline_records_its_surfaced_hit(memory, monkeypatch):
    class BlockedProvider(FakeEmbeddingProvider):
        def __init__(self):
            super().__init__(dimensions=4)
            self.release = threading.Event()

        def embed_query(self, text):
            assert self.release.wait(5)
            return super().embed_query(text)

    provider = BlockedProvider()
    config = replace(memory.config, flags=replace(memory.config.effective_flags(), vector_search=True))
    vector_memory = Memory.from_workspace(memory.workspace.root, config=config, initialize=False,
                                           embedding_provider=provider)
    monkeypatch.setattr(search_module, "_deadline_seconds", lambda ms: 0.05)
    events = []
    tool = _tool(vector_memory, on_event=events.append)
    try:
        result = tool.execute("partial", {"query": "cedar", "corpus": "memory"})["details"]
        tool.wait_for_recalls(timeout=5)
    finally:
        provider.release.set()
    assert result["partial"] is True and result["timedOut"] is True
    assert [event["resultCount"] for event in events] == [1]
    assert next(iter(_entries(vector_memory).values()))["recallCount"] == 1


def test_real_session_visibility_limits_do_not_record_hidden_or_session_hits(memory, tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW)
    for key, session_id in ((REQUESTER, "requester"), ("agent:main:direct:peer", "peer")):
        catalog.upsert_session(key, {"sessionId": session_id, "chatType": "direct"})
        catalog.replace_events(session_id, [{"type": "message", "id": session_id,
            "message": {"role": "user", "content": "Cedar private preference."}}])
    visibility = SessionVisibilityContext.from_catalog(catalog, SessionVisibilityPolicy(visibility="self"))
    session_memory = Memory.from_workspace(tmp_path, config=memory.config, initialize=False,
                                           session_catalog=catalog, session_visibility=visibility)
    events = []
    tool = create_memory_search_tool(session_memory.config, session_memory.store,
        context=MemorySearchToolContext(clock=lambda: NOW, session_visibility=visibility),
        agent_session_key=REQUESTER, on_event=events.append)
    result = tool.execute("visible", {"query": "cedar", "corpus": "sessions", "maxResults": 1})["details"]
    tool.wait_for_recalls(timeout=5)
    assert [hit["path"] for hit in result["results"]] == ["sessions/main/requester.jsonl"]
    assert result["debug"]["withheldHits"] == 1
    assert events == [] and not recall_store_path(tmp_path).exists()


def test_explicit_split_ledger_admits_retained_origin_and_rejects_forgotten_origin(memory, tmp_path, monkeypatch):
    ledger_path = tmp_path / "independent-ledger.sqlite"
    ledger = MemoryEntryOriginLedger(lambda agent: ledger_path)
    ledger.record_session_tombstones("main", ["forgotten"], created_at=NOW)
    original_search = memory.store.search
    source = {"sessionId": "forgotten"}

    def host_annotated_hits(*arguments, **options):
        # A supported custom host result carries explicit source facts. They
        # are independent of the requester key and never inferred by the tool.
        return [{**hit.to_payload(), "sessionOrigin": {"agentId": "main", **source,
                    "sessionKey": "agent:main:direct:source"}} for hit in original_search(*arguments, **options)]

    monkeypatch.setattr(memory.store, "search", host_annotated_hits)
    events = []
    tool = _tool(memory, recall_origins=ledger, on_event=events.append)
    assert tool.execute("forgotten", {"query": "cedar"})["details"]["results"]
    tool.wait_for_recalls(timeout=5)
    assert not _entries(memory) and ledger.list("main") == [] and events == []
    source["sessionId"] = "retained"
    tool.execute("retained", {"query": "cedar"})
    tool.wait_for_recalls(timeout=5)
    row, = ledger.list("main")
    assert row.session_id == "retained" and row.session_key == "agent:main:direct:source"
    assert row.session_key != REQUESTER and row.entry_key in _entries(memory)
    assert len(events) == 1
    assert memory.store.path.resolve() != ledger_path.resolve()


def test_host_kit_explicit_policy_records_once_and_returns_settled_event_state(memory):
    session = SessionState.new(session_key=REQUESTER, session_id="requester")
    events = []
    off = HostKit(memory, now_ms=lambda: NOW, on_event=events.append)
    assert off.dispatch("memory_search", {"query": "cedar"}, session=session)["results"]
    assert not _entries(memory) and events == []
    on = HostKit(memory, now_ms=lambda: NOW, dreaming_enabled=True, on_event=events.append)
    assert on.dispatch("memory_search", {"query": "cedar"}, session=session)["results"]
    entry, = _entries(memory).values()
    assert entry["recallCount"] == 1 and len(events) == 1


def test_host_kit_uses_the_actual_bound_fence_ledger_for_recall_lineage(memory, tmp_path, monkeypatch):
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / "actual-split-ledger.sqlite")
    fence = ledger.revision_fence("main")
    fenced = Memory.from_workspace(tmp_path, config=memory.config, initialize=False, revision_fence=fence)
    original_search = fenced.store.search

    def annotated(*arguments, **options):
        return [{**hit.to_payload(), "sessionOrigin": {"agentId": "main", "sessionId": "actual-source"}}
                for hit in original_search(*arguments, **options)]

    monkeypatch.setattr(fenced.store, "search", annotated)
    events = []
    kit = HostKit(fenced, now_ms=lambda: NOW, dreaming_enabled=True, on_event=events.append)
    result = kit.dispatch("memory_search", {"query": "cedar"},
                          session=SessionState.new(session_key=REQUESTER, session_id="requester"))
    assert result["results"] and len(events) == 1
    assert fence.ledger is ledger
    row, = ledger.list("main")
    assert row.session_id == "actual-source" and row.entry_key in _entries(fenced)
    assert next(iter(_entries(fenced).values()))["recallCount"] == 1


def test_real_ledger_failure_leaves_no_staged_recall_or_search_failure(memory, tmp_path, monkeypatch):
    ledger = MemoryEntryOriginLedger(lambda agent: tmp_path / "split-ledger.sqlite")
    original_search = memory.store.search

    def annotated(*arguments, **options):
        return [{**hit.to_payload(), "sessionOrigin": {"agentId": "main", "sessionId": "source"}}
                for hit in original_search(*arguments, **options)]

    def ledger_down(*arguments, **options):
        raise RuntimeError("The source ledger failed")

    monkeypatch.setattr(memory.store, "search", annotated)
    monkeypatch.setattr(ledger, "record", ledger_down)
    events = []
    tool = _tool(memory, recall_origins=ledger, on_event=events.append)
    result = tool.execute("ledger-failure", {"query": "cedar"})["details"]
    tool.wait_for_recalls(timeout=5)
    assert result["results"] and "unavailable" not in result
    assert _entries(memory) == {} and events == []


def test_factory_owner_rejection_cannot_record_into_a_different_workspace(memory, tmp_path):
    current = [memory.config]
    events = []
    tool = _tool(memory, get_config=lambda: current[0], on_event=events.append)
    current[0] = replace(memory.config, workspace_dir=tmp_path / "other")
    with pytest.raises(MemoryToolError, match="different workspace or index"):
        tool.execute("foreign", {"query": "cedar"})
    tool.wait_for_recalls(timeout=5)
    assert not _entries(memory) and events == [] and not (tmp_path / "other").exists()
