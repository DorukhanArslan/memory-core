from dataclasses import replace
import json

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.supplements import RegisteredMemoryCorpusSupplement, StaticMemoryCorpusSupplement
from memory_core.tools.common import MemoryToolError, MemoryToolInputError
from memory_core.tools.get_factory import create_memory_get_tool, serialize_get_tool_result


@pytest.fixture
def workspace_config(tmp_path):
    (tmp_path / "MEMORY.md").write_text("First saved fact.\nSecond saved fact.\n", encoding="utf-8")
    return MemoryConfig(workspace_dir=tmp_path)


def test_factory_omits_missing_or_disabled_current_configuration(workspace_config):
    config = workspace_config
    assert create_memory_get_tool(None) is None
    assert create_memory_get_tool(config, get_config=lambda: None) is None
    assert create_memory_get_tool(replace(config, flags=FeatureFlags(memory=False))) is None


def test_factory_prefers_the_live_getter_over_the_snapshot(workspace_config):
    tool = create_memory_get_tool(None, get_config=lambda: workspace_config)
    assert tool is not None
    assert tool.execute("call-1", {"path": "MEMORY.md"})["details"]["status"] == "ok"


def test_definition_matches_the_read_tool_and_has_no_preparation_hook(workspace_config):
    tool = create_memory_get_tool(workspace_config, extra_paths=["notes"])
    definition = tool.definition
    assert tool.name == definition["name"] == "memory_get"
    assert tool.label == definition["label"] == "Memory Get"
    assert tool.description == definition["description"]
    assert "memory/, configured extra paths" in tool.description
    assert "indexed session transcripts" not in tool.description
    assert tool.parameters == definition["parameters"]
    assert tool.parameters["properties"]["corpus"]["enum"] == ["memory", "wiki", "all"]
    assert tool.parameters["required"] == ["path"]
    assert not hasattr(tool, "prepare_arguments")
    assert not hasattr(tool, "prepareArguments")


def test_definition_and_parameter_reads_cannot_change_the_captured_schema(workspace_config):
    tool = create_memory_get_tool(workspace_config)
    definition, parameters = tool.definition, tool.parameters
    definition["parameters"]["required"].append("corpus")
    parameters["properties"]["path"]["type"] = "number"
    assert tool.parameters["required"] == ["path"]
    assert tool.parameters["properties"]["path"]["type"] == "string"


def test_factory_reads_actual_files_and_returns_the_entire_json_envelope(workspace_config):
    tool = create_memory_get_tool(workspace_config)
    params = {"path": "\ufeff MEMORY.md \n", "from": "2", "lines": "1"}
    original = dict(params)
    result = tool.execute("call-1", params)
    assert result["details"] == {
        "status": "ok", "text": "Second saved fact.", "path": "MEMORY.md", "from": 2, "lines": 1,
    }
    assert json.loads(result["content"][0]["text"]) == result["details"]
    assert params == original


def test_read_failure_is_a_complete_result_instead_of_a_factory_exception(workspace_config):
    tool = create_memory_get_tool(workspace_config)
    result = tool.execute("call-1", {"path": "memory/missing.md"})
    assert result["details"] == {
        "status": "not_found", "text": "", "path": "memory/missing.md",
    }
    assert json.loads(result["content"][0]["text"]) == result["details"]


def test_factory_preserves_native_input_error_fields(workspace_config):
    tool = create_memory_get_tool(workspace_config)
    with pytest.raises(MemoryToolInputError) as raised:
        tool.execute("call-1", {"path": False})
    assert raised.value.name == "ToolInputError"
    assert raised.value.message == "path required"
    assert raised.value.status == 400
    assert raised.value.tool == "memory_get"


def test_unknown_corpus_retains_ordinary_error_fields(workspace_config):
    tool = create_memory_get_tool(workspace_config)
    with pytest.raises(MemoryToolError) as raised:
        tool.execute("call-1", {"path": "MEMORY.md", "corpus": "sessions"})
    assert raised.value.name == "Error"
    assert raised.value.message == "corpus must be one of: memory, wiki, all"
    assert raised.value.tool == "memory_get"
    assert not hasattr(raised.value, "status")


@pytest.mark.parametrize("disable", ["missing", "flag"])
def test_live_revocation_precedes_raw_argument_validation(workspace_config, disable):
    current = [workspace_config]
    tool = create_memory_get_tool(workspace_config, get_config=lambda: current[0])
    current[0] = None if disable == "missing" else replace(
        workspace_config, flags=FeatureFlags(memory=False),
    )
    with pytest.raises(MemoryToolError) as raised:
        tool.execute("call-1", {"path": False, "lines": 0})
    assert raised.value.name == "Error"
    assert raised.value.message == (
        "Memory is disabled for this agent. Enable memory search for this agent, then retry."
    )
    assert not hasattr(raised.value, "status")


@pytest.mark.parametrize("change", ["workspace", "agent"])
def test_live_config_cannot_route_the_captured_tool_to_another_owner(workspace_config, change):
    current = [workspace_config]
    tool = create_memory_get_tool(workspace_config, get_config=lambda: current[0])
    current[0] = (
        replace(workspace_config, workspace_dir=workspace_config.workspace_dir / "other")
        if change == "workspace" else replace(workspace_config, agent_id="another")
    )
    with pytest.raises(MemoryToolError, match="different workspace or agent"):
        tool.execute("call-1", {"path": "MEMORY.md"})


def test_builtin_get_does_not_require_an_index_or_embedding_provider(workspace_config):
    # An unused store path can change; this factory owns files, not a search manager.
    current = [workspace_config]
    tool = create_memory_get_tool(workspace_config, get_config=lambda: current[0])
    current[0] = replace(workspace_config, store_path=workspace_config.workspace_dir / "other.sqlite")
    assert tool.execute("call-1", {"path": "MEMORY.md"})["details"]["status"] == "ok"
    assert not current[0].resolved_store_path().exists()


def test_registered_supplements_remain_usable_through_the_factory(workspace_config):
    supplement = RegisteredMemoryCorpusSupplement("wiki-provider", StaticMemoryCorpusSupplement([
        {"path": "wiki.md", "corpus": "wiki", "content": "A wiki fact."},
    ]))
    tool = create_memory_get_tool(workspace_config, supplements=[supplement])
    result = tool.execute("call-1", {"path": "wiki.md", "corpus": "wiki"})
    assert result["details"]["text"] == "A wiki fact."
    assert result["details"]["corpora"] == [{"corpus": "wiki", "outcome": "ok"}]
    assert json.loads(result["content"][0]["text"]) == result["details"]


def test_registered_excerpt_reader_receives_only_present_options():
    calls = []

    def reader(**options):
        calls.append(options)
        return None

    supplement = RegisteredMemoryCorpusSupplement(
        "wiki-provider", StaticMemoryCorpusSupplement([]), reader=reader,
    )
    assert supplement.read(lookup="wiki.md") is None
    assert calls == [{"lookup": "wiki.md"}]
    supplement.read(lookup="wiki.md", from_line=2, line_count=3, sandboxed=False)
    assert calls[1] == {"lookup": "wiki.md", "from_line": 2, "line_count": 3, "sandboxed": False}


def test_registered_excerpt_reader_fallback_preserves_the_legacy_get_signature():
    calls = []

    class LegacyProvider:
        def get(self, *, path, corpus):
            calls.append({"path": path, "corpus": corpus})
            return {"path": path, "content": "already selected"}

    supplement = RegisteredMemoryCorpusSupplement("legacy-provider", LegacyProvider())
    assert supplement.read(lookup="wiki.md", from_line=2, line_count=3, sandboxed=False) == {
        "path": "wiki.md", "content": "already selected",
    }
    assert calls == [{"path": "wiki.md", "corpus": "wiki"}]
    supplement.get(path="another.md", corpus="all")
    assert calls[-1] == {"path": "another.md", "corpus": "all"}


def test_factory_preserves_provider_excerpt_metadata_and_trusted_host_context(workspace_config):
    calls = []
    provider_result = {
        "path": "provider/canonical.md", "content": "Already selected.\nAnother line.",
        "corpus": "wiki", "from": 40, "lines": 2, "nextFrom": 42, "truncated": True,
        "providerMetadata": {"revision": "r7", "optional": None},
    }

    def reader(**options):
        calls.append(options)
        return provider_result

    supplement = RegisteredMemoryCorpusSupplement(
        "wiki-provider", StaticMemoryCorpusSupplement([]), reader=reader,
    )
    tool = create_memory_get_tool(
        workspace_config, supplements=[supplement],
        agent_session_key="agent:main:trusted", sandboxed=False,
    )
    result = tool.execute("call-1", {
        "path": " wiki.md ", "corpus": "wiki", "from": 2, "lines": 1,
        "agentSessionKey": "agent:main:forged", "sandboxed": True,
    })
    assert calls == [{
        "lookup": "wiki.md", "from_line": 2, "line_count": 1, "agent_id": "main",
        "agent_session_key": "agent:main:trusted", "sandboxed": False,
    }]
    expected = {key: value for key, value in provider_result.items() if key != "content"}
    assert result["details"] == {
        **expected, "status": "ok", "text": provider_result["content"],
        "corpora": [{"corpus": "wiki", "outcome": "ok"}],
    }
    assert provider_result["content"] == "Already selected.\nAnother line."


def test_provider_empty_content_is_preserved_instead_of_replaced_by_snippet(workspace_config):
    supplement = RegisteredMemoryCorpusSupplement(
        "wiki-provider", StaticMemoryCorpusSupplement([]),
        reader=lambda **_: {"path": "wiki.md", "content": "", "snippet": "display-only"},
    )
    tool = create_memory_get_tool(workspace_config, supplements=[supplement])
    result = tool.execute("call-1", {"path": "wiki.md", "corpus": "wiki"})
    assert result["details"]["text"] == ""
    assert result["details"]["snippet"] == "display-only"


def test_get_serializer_preserves_unknown_metadata_and_unicode():
    payload = {"status": "ok", "text": "世界 🌱", "pluginMetadata": {"optional": None}}
    result = serialize_get_tool_result(payload)
    assert result["details"] is payload
    assert result["content"] == [{"type": "text", "text": json.dumps(payload, ensure_ascii=False,
                                                                          indent=2)}]


def test_only_host_configuration_can_authorize_an_extra_read_root(tmp_path):
    workspace = tmp_path / "workspace"
    configured = tmp_path / "configured"
    workspace.mkdir()
    configured.mkdir()
    file = configured / "note.md"
    file.write_text("Host-selected content.\n", encoding="utf-8")
    config = MemoryConfig(workspace_dir=workspace)
    restricted = create_memory_get_tool(config)
    authorized = create_memory_get_tool(config, extra_paths=[configured])
    forged = {
        "path": str(file), "extra_paths": [str(configured)], "extraPaths": [str(configured)],
    }

    refused = restricted.execute("forged", forged)["details"]
    assert refused["status"] == "error"
    assert refused["code"] == "MEMORY_PATH_NOT_ALLOWED"
    assert authorized.execute("authorized", {"path": str(file)})["details"] == {
        "status": "ok", "path": "../configured/note.md", "text": "Host-selected content.",
        "from": 1, "lines": 1,
    }
