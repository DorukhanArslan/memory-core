from copy import deepcopy
from dataclasses import replace
import json

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.tools.common import MemoryToolError, MemoryToolInputError
from memory_core.tools.memory_search import MemorySearchToolContext, reset_memory_search_tool_cooldowns
from memory_core.tools.search_factory import (
    create_memory_search_tool,
    prepare_memory_search_arguments,
    serialize_search_tool_result,
)
from memory_core.workspace import MemoryWorkspace


@pytest.fixture
def indexed_store(tmp_path):
    config = MemoryConfig(
        workspace_dir=tmp_path, session_search=False, citation_mode="off", search_min_score=0,
        flags=FeatureFlags(vector_search=False, text_search=True, mmr=False, temporal_decay=False),
    )
    (tmp_path / "MEMORY.md").write_text("Cedar tea is the saved preference.\n", encoding="utf-8")
    store = SQLiteMemoryStore(config, None)
    store.reindex(MemoryWorkspace(tmp_path))
    reset_memory_search_tool_cooldowns()
    yield config, store
    reset_memory_search_tool_cooldowns()


@pytest.mark.parametrize("params", [None, 5, [], {}, {"query": "cedar", "unknown": 7}])
def test_argument_preparation_returns_original_input_when_no_alias_is_present(params):
    assert prepare_memory_search_arguments(params) is params


def test_argument_preparation_copies_aliases_and_keeps_invalid_camel_values():
    params = {"query": "cedar", "max_results": 3, "maxResults": None,
              "min_score": "0.25", "unknown": {"nested": "kept"}}
    original = deepcopy(params)
    assert prepare_memory_search_arguments(params) == {
        "query": "cedar", "maxResults": None, "minScore": "0.25", "unknown": {"nested": "kept"},
    }
    assert params == original


def test_json_envelope_preserves_complete_details_and_native_pretty_text():
    payload = {"results": [{"path": "memory/世界.md", "score": 0.75}],
               "debug": {"untouched": [True, None, "🌱"]}}
    result = serialize_search_tool_result(payload)
    assert result["details"] is payload
    assert result["content"] == [{"type": "text", "text": json.dumps(payload, ensure_ascii=False,
                                                                          indent=2)}]


def test_factory_omits_missing_or_disabled_memory_before_store_work(indexed_store):
    config, store = indexed_store
    assert create_memory_search_tool(None, store) is None
    assert create_memory_search_tool(config, store, get_config=lambda: None) is None
    assert create_memory_search_tool(config, store, context=MemorySearchToolContext(enabled=False)) is None
    assert create_memory_search_tool(
        replace(config, flags=replace(config.effective_flags(), memory=False)), store,
    ) is None


def test_factory_definition_includes_configured_sources_and_is_independent(indexed_store):
    config, store = indexed_store
    tool = create_memory_search_tool(replace(config, session_search=True), store,
                                     extra_paths=["notes", "archive"])
    assert tool is not None
    definition = tool.definition
    assert definition["name"] == "memory_search"
    assert definition["label"] == "Memory Search"
    assert tool.name == definition["name"]
    assert tool.label == definition["label"]
    assert tool.description == definition["description"]
    assert tool.parameters == definition["parameters"]
    assert "memory/, configured extra paths, indexed session transcripts" in definition["description"]
    assert definition["parameters"]["properties"]["corpus"]["enum"] == [
        "memory", "wiki", "all", "sessions",
    ]
    definition["parameters"]["required"].append("corpus")
    assert tool.definition["parameters"]["required"] == ["query"]
    parameters = tool.parameters
    parameters["required"].append("corpus")
    assert tool.parameters["required"] == ["query"]


def test_factory_executes_real_index_and_preserves_full_host_envelope(indexed_store):
    config, store = indexed_store
    tool = create_memory_search_tool(config, store,
                                     context=MemorySearchToolContext(manager_ms=0, clock=lambda: 1000))
    result = tool.execute("call-1", {"query": "cedar", "corpus": "memory"})
    assert json.loads(result["content"][0]["text"]) == result["details"]
    payload = result["details"]
    assert payload["results"][0]["path"] == "MEMORY.md"
    assert payload["results"][0]["snippet"] == "Cedar tea is the saved preference.\n"
    assert payload["provider"] == "none"


@pytest.mark.parametrize(("manager_ms", "expected"), [(None, 7), (23, 23)])
def test_factory_measures_ready_store_acquisition_and_preserves_explicit_manager_time(
    indexed_store, manager_ms, expected,
):
    config, store = indexed_store
    ticks = iter(range(100, 1000, 7))
    tool = create_memory_search_tool(
        config, store,
        context=MemorySearchToolContext(manager_ms=manager_ms, clock=lambda: next(ticks)),
    )
    result = tool.execute("call-1", {"query": "cedar", "corpus": "memory"})
    assert result["details"]["results"][0]["path"] == "MEMORY.md"
    assert result["details"]["debug"]["managerMs"] == expected


def test_live_config_revocation_precedes_invalid_argument_validation(indexed_store):
    config, store = indexed_store
    current = [config]
    tool = create_memory_search_tool(config, store, get_config=lambda: current[0])
    current[0] = None
    with pytest.raises(MemoryToolError) as raised:
        tool.execute("call-2", {"maxResults": "invalid"})
    assert raised.value.message == (
        "Memory is disabled for this agent. Enable memory search for this agent, then retry."
    )
    assert raised.value.name == "Error"
    assert not hasattr(raised.value, "status")


def test_live_enable_policy_is_read_once_per_boundary_resolution(indexed_store):
    config, store = indexed_store
    calls = []
    enabled = [True]

    def is_enabled():
        calls.append(True)
        return enabled[0]

    tool = create_memory_search_tool(config, store,
                                     context=MemorySearchToolContext(enabled=is_enabled))
    assert len(calls) == 1
    tool.execute("call-1", {"query": "cedar"})
    assert len(calls) == 2
    enabled[0] = False
    with pytest.raises(MemoryToolError, match="^Memory is disabled for this agent"):
        tool.execute("call-2", {"query": "cedar"})
    assert len(calls) == 3


def test_live_feature_flag_revokes_before_parameter_validation_and_search(indexed_store):
    config, store = indexed_store
    current = [config]
    tool = create_memory_search_tool(config, store, get_config=lambda: current[0])
    current[0] = replace(config, flags=replace(config.effective_flags(), memory=False))
    with pytest.raises(MemoryToolError) as raised:
        tool.execute("call-1", {"query": False, "maxResults": "invalid"})
    assert raised.value.name == "Error"
    assert raised.value.message == (
        "Memory is disabled for this agent. Enable memory search for this agent, then retry."
    )
    assert not hasattr(raised.value, "status")


def test_live_config_policy_changes_are_used_without_changing_the_store_owner(indexed_store):
    config, store = indexed_store
    current = [config]
    tool = create_memory_search_tool(config, store, get_config=lambda: current[0])
    current[0] = replace(config, citation_mode="on")
    result = tool.execute("call-1", {"query": "cedar", "corpus": "memory"})
    assert result["details"]["results"][0]["citation"] == "MEMORY.md#L1-L2"


@pytest.mark.parametrize("change", ["workspace", "index", "agent"])
def test_live_config_cannot_reuse_the_captured_store_for_another_owner(indexed_store, change):
    config, store = indexed_store
    current = [config]
    tool = create_memory_search_tool(config, store, get_config=lambda: current[0])
    current[0] = {
        "workspace": replace(config, workspace_dir=config.workspace_dir / "other"),
        "index": replace(config, store_path=config.workspace_dir / "another.sqlite"),
        "agent": replace(config, agent_id="another"),
    }[change]
    with pytest.raises(MemoryToolError, match="different workspace or index"):
        tool.execute("call-1", {"query": "cedar"})


def test_initial_factory_cannot_mislabel_another_workspace_store(indexed_store):
    config, store = indexed_store
    with pytest.raises(MemoryToolError, match="different workspace or index"):
        create_memory_search_tool(replace(config, workspace_dir=config.workspace_dir / "other"), store)


def test_prepared_invalid_camel_value_is_still_rejected_by_the_real_tool(indexed_store):
    config, store = indexed_store
    tool = create_memory_search_tool(config, store)
    params = tool.prepare_arguments({"query": "cedar", "maxResults": "invalid", "max_results": 2})
    with pytest.raises(MemoryToolInputError, match="maxResults must be a positive integer"):
        tool.execute("call-1", params)


def test_trusted_conversation_recall_restricts_model_requested_corpus(indexed_store):
    config, store = indexed_store
    tool = create_memory_search_tool(config, store, conversation_recall={"corpus": "sessions"})
    result = tool.execute("call-1", {"query": "cedar", "corpus": "memory"})
    assert result["details"]["results"] == []
    assert result["details"]["provider"] == "none"
    assert "disabled" not in result["details"]
