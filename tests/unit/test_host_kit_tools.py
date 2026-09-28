"""memory_core.host: SessionState, HostKit construction and tools() (docs/host_kit.md, Task 1)."""

from __future__ import annotations

import dataclasses
import json

import pytest

from memory_core.bootstrap import (
    bootstrap_status,
    initialize_agent_workspace,
    read_workspace_setup_state,
)
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.curation import APPEND_DAILY_NOTE, CurationPolicy, MemoryCurator
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, SessionState, TurnUsage
from memory_core.memory_flush import has_already_flushed_for_current_compaction
from memory_core.tools.memory_get import memory_get_tool_definition
from memory_core.tools.memory_search import memory_search_tool_definition

NOW_MS = 1_790_375_400_000  # 2026-09-25 22:30 UTC


def _fts_config(root, **flags) -> MemoryConfig:
    return MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False, **flags))


def _files(root) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _memory(root, **flags) -> Memory:
    return Memory.from_workspace(
        root, config=_fts_config(root, **flags), initialize=False, reindex=False
    )


# --- SessionState -----------------------------------------------------------------------------


def test_session_state_round_trips_json():
    state = SessionState(
        session_key="agent:main:main",
        session_id="s1",
        kind="group",
        entry={
            "sessionId": "s1",
            "compactionCount": 2,
            "totalTokens": 5000,
            "totalTokensFresh": True,
            "totalTokensVersion": 1,
            "memoryFlush": {"kind": "failed", "compactionCount": 1, "failureCount": 2},
        },
        last_output_tokens=120,
        seen_truncation_signatures=("sig-a", "sig-b"),
        completed_bootstrap_turn=True,
    )

    data = state.to_json()

    assert json.loads(json.dumps(data)) == data
    assert SessionState.from_json(data) == state
    assert SessionState.from_json(json.loads(json.dumps(data))) == state


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("lastOutputTokens", "12", "lastOutputTokens"),
        ("completedBootstrapTurn", "yes", "completedBootstrapTurn"),
        ("entry", {"compactionCount": "1"}, "entry.compactionCount must be an integer"),
        ("entry", {"compactionCount": True}, "entry.compactionCount must be an integer"),
        ("entry", {"totalTokens": 5000.5}, "entry.totalTokens must be an integer"),
        ("entry", {"totalTokensFresh": "true"}, "entry.totalTokensFresh must be a boolean"),
        ("entry", {"totalTokensVersion": "1"}, "entry.totalTokensVersion must be an integer"),
        ("entry", {"memoryFlush": []}, "entry.memoryFlush must be an object"),
        ("entry", {"sessionId": 7}, "entry.sessionId must be a string"),
        ("entry", [], "entry must be a mapping"),
    ],
)
def test_session_state_from_json_rejects_wrong_field_types(field, value, message):
    data = {**SessionState.new(session_key="k", session_id="s1").to_json(), field: value}

    with pytest.raises(ValueError, match=message):
        SessionState.from_json(data)


def test_session_state_new_starts_a_fresh_flush_entry():
    state = SessionState.new(session_key="k", session_id="s1")

    assert state == SessionState(
        session_key="k", session_id="s1", entry={"sessionId": "s1", "compactionCount": 0}
    )
    assert state.kind == "main"
    assert state.last_output_tokens is None
    assert state.seen_truncation_signatures == ()
    assert state.completed_bootstrap_turn is False
    assert SessionState.new(session_key="k", session_id="s2", kind="cron").kind == "cron"
    with pytest.raises(ValueError, match="session kind"):
        SessionState.new(session_key="k", session_id="s1", kind="thread")  # type: ignore[arg-type]


def test_session_state_entry_is_a_private_read_only_copy():
    source = {"sessionId": "s1", "compactionCount": 0, "memoryFlush": {"kind": "succeeded"}}
    state = SessionState(session_key="k", session_id="s1", entry=source)

    source["compactionCount"] = 9
    source["memoryFlush"]["kind"] = "failed"
    assert state.entry["compactionCount"] == 0
    assert state.entry["memoryFlush"] == {"kind": "succeeded"}
    with pytest.raises(TypeError):
        state.entry["compactionCount"] = 1  # type: ignore[index]

    copy = dataclasses.replace(state, kind="direct")
    assert copy.entry == state.entry
    assert copy.entry["memoryFlush"] is not state.entry["memoryFlush"]
    assert state.to_json()["entry"]["memoryFlush"] is not state.entry["memoryFlush"]


def test_after_compaction_starts_the_next_cycle():
    state = SessionState(
        session_key="k",
        session_id="s1",
        entry={
            "sessionId": "s1",
            "compactionCount": 0,
            "totalTokens": 5000,
            "totalTokensFresh": True,
            "totalTokensVersion": 1,
            "memoryFlush": {"kind": "succeeded", "compactionCount": 0},
        },
        last_output_tokens=40,
    )
    assert has_already_flushed_for_current_compaction(dict(state.entry))

    compacted = state.after_compaction()

    assert compacted.entry["compactionCount"] == 1
    assert compacted.entry["totalTokens"] == 5000
    assert compacted.entry["totalTokensFresh"] is False
    assert "totalTokensVersion" not in compacted.entry
    assert compacted.last_output_tokens is None
    assert not has_already_flushed_for_current_compaction(dict(compacted.entry))
    assert state.entry["compactionCount"] == 0

    fresh = state.after_compaction(tokens_after=1200.7)
    assert fresh.entry["compactionCount"] == 1
    assert fresh.entry["totalTokens"] == 1200
    assert fresh.entry["totalTokensFresh"] is True
    assert fresh.entry["totalTokensVersion"] == 1
    assert SessionState.new(session_key="k", session_id="s").after_compaction().entry[
        "compactionCount"
    ] == 1


def test_turn_usage_defaults_to_no_completion_tokens():
    assert TurnUsage(prompt_tokens=10) == TurnUsage(prompt_tokens=10, completion_tokens=None)


# --- construction -----------------------------------------------------------------------------


def test_open_seeds_bootstrap_before_any_memory_file_exists(tmp_path):
    root = tmp_path / "ws"

    kit = HostKit.open(
        root,
        config=_fts_config(root),
        templates={"BOOTSTRAP.md": "Ask the user for a name.\n"},
        now_ms=lambda: NOW_MS,
    )

    assert (root / "BOOTSTRAP.md").read_text(encoding="utf-8") == "Ask the user for a name.\n"
    assert not (root / "MEMORY.md").exists()
    assert not (root / "memory").exists()
    assert bootstrap_status(root) == "pending"
    assert kit.memory.store.path.is_file()


def test_open_without_bootstrap_template_completes_setup(tmp_path):
    root = tmp_path / "ws"

    HostKit.open(root, config=_fts_config(root), now_ms=lambda: NOW_MS)

    assert not (root / "BOOTSTRAP.md").exists()
    assert bootstrap_status(root) == "complete"
    assert read_workspace_setup_state(root).setup_completed_at == "2026-09-25T22:30:00.000Z"


def test_seed_bootstrap_true_seeds_an_empty_file(tmp_path):
    root = tmp_path / "ws"

    kit = HostKit.open(root, config=_fts_config(root), seed_bootstrap=True)

    assert (root / "BOOTSTRAP.md").read_text(encoding="utf-8") == ""
    assert bootstrap_status(root) == "pending"
    assert kit.ensure().bootstrap_status == "pending"


def test_ensure_equals_initialize_agent_workspace(tmp_path):
    root = tmp_path / "ws"
    other = tmp_path / "direct"
    templates = {"AGENTS.md": "# Agents\n", "BOOTSTRAP.md": "ritual\n"}
    kit = HostKit(_memory(root), templates=templates, now_ms=lambda: NOW_MS)

    result = kit.ensure()
    expected = initialize_agent_workspace(other, templates=templates, now_ms=NOW_MS)

    assert result.created_files == expected.created_files
    assert result.created_dirs == expected.created_dirs
    assert result.bootstrap_seeded == expected.bootstrap_seeded
    assert result.state == expected.state
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == "# Agents\n"
    assert (root / "BOOTSTRAP.md").read_text(encoding="utf-8") == "ritual\n"


def test_open_with_a_bad_store_config_creates_nothing(tmp_path):
    root = tmp_path / "ws"

    with pytest.raises(ValueError, match="vector_search is enabled"):
        HostKit.open(root)

    assert not root.exists()


def test_open_fts_only_needs_no_embedder(tmp_path):
    root = tmp_path / "ws"

    kit = HostKit.open(root, config=_fts_config(root))

    assert kit.memory.store.embeddings is None
    assert kit.memory.config.effective_flags().vector_search is False


def test_init_does_no_io(tmp_path):
    root = tmp_path / "ws"
    memory = _memory(root)
    before = _files(root)

    HostKit(memory, templates={"BOOTSTRAP.md": "ritual\n"}, timezone="Europe/Istanbul")

    assert _files(root) == before
    assert not (root / "BOOTSTRAP.md").exists()


def test_init_validates_the_timezone_and_the_policy(tmp_path):
    memory = _memory(tmp_path / "ws")

    with pytest.raises(ValueError, match="timezone"):
        HostKit(memory, timezone="Mars/Olympus")
    with pytest.raises(ValueError, match="does not provide"):
        HostKit(memory, curation_policy=CurationPolicy(allowed_files={APPEND_DAILY_NOTE: ["x.md"]}))


# --- tools() ----------------------------------------------------------------------------------


def test_tools_lists_memory_tools_then_the_allowed_curation_tools(tmp_path):
    root = tmp_path / "ws"
    kit = HostKit(_memory(root))
    curator = MemoryCurator(root)

    assert kit.tools() == [
        memory_search_tool_definition(),
        memory_get_tool_definition(),
        *curator.tool_definitions(),
    ]
    assert isinstance(kit.curator, MemoryCurator)

    policy = CurationPolicy.for_layout().without(APPEND_DAILY_NOTE)
    names = [tool["name"] for tool in HostKit(_memory(root), curation_policy=policy).tools()]
    assert APPEND_DAILY_NOTE not in names
    assert names[:2] == ["memory_search", "memory_get"]


def test_tools_omit_curation_tools_when_the_flag_is_off(tmp_path):
    kit = HostKit(_memory(tmp_path / "ws", curated_memory_writes=False))

    assert [tool["name"] for tool in kit.tools()] == ["memory_search", "memory_get"]


def test_tools_are_json_serializable(tmp_path):
    tools = HostKit(_memory(tmp_path / "ws")).tools()

    assert json.loads(json.dumps(tools)) == tools
    assert all(set(tool) == {"name", "description", "parameters"} for tool in tools)
