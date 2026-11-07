"""Memory.curator(): flags from the config and reindexing after memory writes."""

from __future__ import annotations

import pytest

from memory_core import FeatureFlags, Memory, MemoryConfig, MemoryToolInputError
from memory_core.curation import CurationUnavailableError, MemoryCurator
from memory_core.embeddings import FakeEmbeddingProvider
from memory_core.tools.memory_search import execute_memory_search_tool

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
    assert calls == [memory.workspace]
    curator.set_proactive_preferences("alpha")
    curator.upsert_user_directive("Prefer delta.")
    assert calls == [memory.workspace]
    curator.add_memory_entry("Decisions", "delta")
    curator.append_daily_note("alpha")
    assert calls == [memory.workspace, memory.workspace, memory.workspace]


def test_curated_user_directive_is_searchable_before_the_next_turn(tmp_path):
    memory = _memory(tmp_path)
    curator = memory.curator(now_ms=lambda: NOW_MS)
    assert memory.search("quartznectar")["results"] == []

    result = curator.upsert_user_directive("Prefer quartznectar in the morning.")
    assert result.changed and result.after_write_error is None
    assert [hit["path"] for hit in memory.search("quartznectar")["results"]] == ["USER.md"]

    # The new profile remains indexed when the store is reopened without a
    # rebuild, proving publication rather than a process-local read shortcut.
    reopened = Memory.from_workspace(tmp_path, config=memory.config, reindex=False)
    assert [hit["path"] for hit in reopened.search("quartznectar")["results"]] == ["USER.md"]


def test_the_config_flag_disables_the_curator(tmp_path):
    memory = _memory(tmp_path, curated_memory_writes=False)
    curator = memory.curator()
    before = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")

    assert curator.available_operations() == ()
    assert curator.tool_definitions() == []
    with pytest.raises(CurationUnavailableError, match="disabled"):
        curator.add_memory_entry("Decisions", "delta")
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == before


def test_one_host_handler_serializes_search_and_curation_tool_errors(tmp_path):
    memory = _memory(tmp_path)
    curator = memory.curator(now_ms=lambda: NOW_MS)
    tools = {
        "memory_search": lambda args: execute_memory_search_tool(memory.config, memory.store, args),
        **{name: (lambda args, name=name: curator.dispatch(name, args))
           for name in curator.available_operations()},
    }

    def run_tool(name, args):
        try:
            return tools[name](args)
        except MemoryToolInputError as error:
            return error.to_tool_error()

    assert run_tool("memory_search", {"query": "  "}) == {
        "status": "error",
        "tool": "memory_search",
        "error": "query required",
    }
    assert run_tool("add_memory_entry", {"section": "Decisions"}) == {
        "status": "error",
        "tool": "add_memory_entry",
        "error": "text required",
    }
    assert run_tool("remove_memory_entry", {"entry": "absent"}) == {
        "status": "error",
        "tool": "remove_memory_entry",
        "error": "entry not found in MEMORY.md",
    }
    assert run_tool("add_memory_entry", {"section": "Decisions", "text": "delta"})["status"] == "ok"


class _FailingDocumentsProvider(FakeEmbeddingProvider):
    def __init__(self):
        super().__init__(dimensions=8)
        self.fail = False

    def embed_documents(self, texts):
        if self.fail:
            raise RuntimeError("provider down")
        return super().embed_documents(texts)


def test_a_failed_reindex_does_not_turn_a_committed_write_into_an_error(tmp_path):
    # The write is committed before after_write runs; a provider error in the
    # reindex must neither escape dispatch nor read as a failed write (the
    # model would retry add_memory_entry and duplicate the entry).
    provider = _FailingDocumentsProvider()
    memory = Memory.from_workspace(tmp_path, embedding_provider=provider)
    curator = memory.curator(now_ms=lambda: NOW_MS)
    provider.fail = True

    payload = curator.dispatch("add_memory_entry", {"section": "Decisions", "text": "delta"})
    direct = curator.append_daily_note("quokkabyte arrived")

    assert payload["status"] == "ok"
    assert payload["action"] == "added"
    assert payload["afterWriteError"] == "provider down"
    assert "- delta" in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert direct.changed is True
    assert direct.after_write_error == "provider down"
    assert "quokkabyte" in (tmp_path / "memory" / "2026-09-25.md").read_text(encoding="utf-8")


def test_an_os_error_in_after_write_is_not_reported_as_a_failed_write(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    curator = memory.curator(now_ms=lambda: NOW_MS)

    def unreadable(workspace):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(memory.store, "reindex", unreadable)
    payload = curator.dispatch("add_memory_entry", {"section": "Decisions", "text": "delta"})

    assert payload["status"] == "ok"
    assert payload["afterWriteError"] == "[Errno 13] Permission denied"
    assert "write failed" not in payload["afterWriteError"]
    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8").count("- delta") == 1
    monkeypatch.undo()
    assert "afterWriteError" not in curator.dispatch(
        "add_memory_entry", {"section": "Decisions", "text": "epsilon"}
    )
