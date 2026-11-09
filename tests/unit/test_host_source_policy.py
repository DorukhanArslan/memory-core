"""Host clock and protected source policy over actual catalog/index/search owners."""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from memory_core.config import MemoryConfig
from memory_core.client import Memory
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, HostModelResult, HostSessionRunner, SessionState
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_visibility import (
    SessionVisibilityContext,
    SessionVisibilityPolicy,
    resolve_memory_search_source_policy,
)


NOW = 1_794_182_400_000
KEY = "agent:main:dm:source-policy"
STATE = SessionState.new(session_key=KEY, session_id="source-policy-writer")


def _config(workspace, *, session_search=False):
    return MemoryConfig(workspace_dir=workspace, citation_mode="off",
        session_search=session_search, flags=FeatureFlags(vector_search=False, temporal_decay=False))


def _assert_fixed_elapsed(result):
    assert {key: result["debug"][key] for key in ("searchMs", "toolMs", "outsideSearchMs")} == {
        "searchMs": 0, "toolMs": 0, "outsideSearchMs": 0,
    }


def test_injected_host_clock_reaches_real_search_without_optional_context(tmp_path):
    # There is no catalog, visibility override or source-policy override here:
    # the kit's clock must still govern its actual memory-tool execution.
    kit = HostKit.open(tmp_path, config=_config(tmp_path), now_ms=lambda: NOW)
    saved = kit.dispatch("append_daily_note", {"text": "My drink preference is cedar tea."}, session=STATE)
    assert saved["status"] == "ok"

    actual = kit.dispatch("memory_search", {"query": "drink preference", "corpus": "memory", "minScore": 0}, session=STATE)

    assert actual["results"][0]["path"] == "memory/2026-11-09.md"
    assert actual["results"][0]["snippet"] == "My drink preference is cedar tea.\n"
    _assert_fixed_elapsed(actual)


def test_host_search_measures_actual_captured_store_acquisition(tmp_path):
    readings = []
    instants = []

    def clock():
        instant = instants.pop(0) if instants else NOW + 7
        readings.append(instant)
        return instant

    kit = HostKit.open(tmp_path, config=_config(tmp_path), now_ms=clock)
    kit.dispatch("append_daily_note", {"text": "My drink preference is cedar tea."}, session=STATE)
    instants.extend([NOW, NOW + 7])
    readings.clear()

    actual = kit.dispatch("memory_search", {"query": "drink preference", "minScore": 0}, session=STATE)

    assert actual["results"][0]["path"] == "memory/2026-11-09.md"
    assert readings[:2] == [NOW, NOW + 7]
    assert actual["debug"]["managerMs"] == 7
    _assert_fixed_elapsed(actual)


def test_host_registered_search_refuses_a_store_bound_to_another_owner(tmp_path):
    workspace = tmp_path / "workspace"
    memory = Memory.from_workspace(workspace, config=_config(workspace), initialize=False)
    mismatched = replace(memory, config=replace(memory.config, workspace_dir=tmp_path / "another-workspace"))
    kit = HostKit(mismatched, now_ms=lambda: NOW)

    refused = kit.dispatch("memory_search", {"query": "cedar"}, session=STATE)

    assert refused == {"status": "error", "tool": "memory_search",
        "error": "Memory search configuration belongs to a different workspace or index; create a new tool with its matching store."}
    assert not (tmp_path / "another-workspace").exists()


def test_host_registered_search_revocation_precedes_invalid_model_arguments(tmp_path):
    config = replace(_config(tmp_path), flags=FeatureFlags(vector_search=False, memory=False))
    kit = HostKit.open(tmp_path, config=config, now_ms=lambda: NOW)

    refused = kit.dispatch("memory_search", {"query": False, "maxResults": "invalid"}, session=STATE)

    assert refused == {"status": "error", "tool": "memory_search",
        "error": "Memory is disabled for this agent. Enable memory search for this agent, then retry."}


@pytest.mark.parametrize("remember", [False, True])
def test_real_host_index_sources_and_ordinary_query_sources_stay_distinct(tmp_path, remember):
    policy = resolve_memory_search_source_policy(["memory"], remember_across_conversations=remember)
    catalog = MemorySessionCatalog(tmp_path / "sessions.sqlite", clock_ms=lambda: NOW)
    workspace = tmp_path / "workspace"
    runner = HostSessionRunner.open(workspace, config=_config(workspace, session_search=policy["sessionMemory"]),
        catalog=catalog, session=STATE, source_policy=policy, now_ms=lambda: NOW)

    async def save(turn):
        arguments = {"text": "My drink preference is cedar tea."}
        turn.record_message({"role": "assistant", "content": [{"type": "toolCall", "id": "save", "name": "append_daily_note", "arguments": arguments}]})
        result = await turn.dispatch_async("save", "append_daily_note", arguments)
        assert result["status"] == "ok"
        turn.record_message({"role": "assistant", "content": [{"type": "text", "text": "Saved."}]})
        return HostModelResult()

    outcome = asyncio.run(runner.run_turn("Please remember that my drink preference is cedar tea.", execute=save))
    assert outcome.ready and outcome.memory_writes_committed
    published = runner.kit.memory.store.read_published_index()
    assert {row["source"] for row in published["chunks"]} == ({"memory", "sessions"} if remember else {"memory"})
    if remember:
        session_chunk = next(row for row in published["chunks"] if row["source"] == "sessions")
        assert session_chunk["text"] == "User: Please remember that my drink preference is cedar tea.\nAssistant: Saved."

    # Neither later mutation of caller-owned policy nor model-authored routing
    # keys may widen the kit's ordinary query to its privately indexed sessions.
    policy["searchSources"].append("sessions")
    actual = runner.kit.dispatch("memory_search", {"query": "drink preference", "minScore": 0,
        "sources": ["sessions"], "sourcePolicy": {"searchSources": ["sessions"]}}, session=runner.session)
    assert actual["results"] and {hit["source"] for hit in actual["results"]} == {"memory"}
    _assert_fixed_elapsed(actual)
    disabled = runner.kit.dispatch("memory_search", {"query": "drink preference", "corpus": "sessions", "minScore": 0}, session=runner.session)
    assert disabled["unavailable"] is True
    assert disabled["error"] == "Session transcript search is not enabled."


def test_host_clock_context_preserves_authoritative_session_visibility(tmp_path):
    catalog = MemorySessionCatalog(tmp_path / "sessions.sqlite", clock_ms=lambda: NOW)
    other = "agent:main:dm:hidden"
    for key, identifier, text in ((KEY, STATE.session_id, "Shared cedar marker visible."),
                                  (other, "hidden-session", "Shared cedar marker hidden.")):
        catalog.upsert_session(key, {"sessionId": identifier})
        catalog.append_message(identifier, {"role": "user", "content": text}, session_key=key, event_id=identifier, now_ms=NOW)
    visibility = SessionVisibilityContext.from_catalog(catalog, SessionVisibilityPolicy(visibility="self"))
    policy = resolve_memory_search_source_policy(["memory", "sessions"], configured_session_memory=True)
    workspace = tmp_path / "workspace"
    kit = HostKit.open(workspace, config=_config(workspace, session_search=True), session_catalog=catalog,
        session_visibility=visibility, source_policy=policy, now_ms=lambda: NOW)

    result = kit.dispatch("memory_search", {"query": "Shared cedar marker", "corpus": "sessions", "minScore": 0,
        "requesterSessionKey": other, "visibility": "all"}, session=STATE)

    assert len(result["results"]) == 1
    assert "visible" in result["results"][0]["snippet"]
    assert "hidden" not in result["results"][0]["snippet"]
    assert result["debug"]["candidateHits"] == 2
    assert result["debug"]["withheldHits"] == 1
    _assert_fixed_elapsed(result)
