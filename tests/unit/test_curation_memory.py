"""Memory.curator(): flags from the config and reindexing after memory writes."""

from __future__ import annotations

import pytest

from memory_core import CurationUnavailableError, FeatureFlags, Memory, MemoryConfig, MemoryCurator

NOW_MS = 1790375400000  # 2026-09-25 22:30 UTC


def _memory(tmp_path, **flags) -> Memory:
    config = MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False, **flags))
    return Memory.from_workspace(tmp_path, config=config)


def test_curated_memory_writes_are_searchable_right_away(tmp_path):
    memory = _memory(tmp_path)
    curator = memory.curator(now_ms=lambda: NOW_MS)

    assert isinstance(curator, MemoryCurator)
    assert memory.search("zephyrquartz")["results"] == []
    curator.add_memory_entry("Decisions", "zephyrquartz stays paused")
    assert [hit["path"] for hit in memory.search("zephyrquartz")["results"]] == ["MEMORY.md"]
    curator.append_daily_note("quokkabyte arrived")
    assert [hit["path"] for hit in memory.search("quokkabyte")["results"]] == [
        "memory/2026-09-25.md"
    ]
    curator.remove_memory_entry("zephyrquartz stays paused")
    assert memory.search("zephyrquartz")["results"] == []


def test_only_indexed_files_trigger_a_reindex(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    curator = memory.curator(now_ms=lambda: NOW_MS)
    calls = []
    monkeypatch.setattr(memory.store, "reindex", lambda workspace: calls.append(workspace))

    curator.upsert_user_directive("Prefer delta.")
    curator.set_proactive_preferences("alpha")
    curator.upsert_user_directive("Prefer delta.")
    assert calls == []
    curator.add_memory_entry("Decisions", "delta")
    curator.append_daily_note("alpha")
    assert calls == [memory.workspace, memory.workspace]


def test_the_config_flag_disables_the_curator(tmp_path):
    memory = _memory(tmp_path, curated_memory_writes=False)
    curator = memory.curator()
    before = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    assert curator.available_operations() == ()
    assert curator.tool_definitions() == []
    with pytest.raises(CurationUnavailableError, match="disabled"):
        curator.add_memory_entry("Decisions", "delta")
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == before
