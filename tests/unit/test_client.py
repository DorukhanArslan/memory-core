from pathlib import Path

from memory_core import MemoryCoreMemory
from memory_core.embeddings.base import FakeEmbeddingProvider


def test_from_workspace_reads_host_memory_files(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "# Memory\n\n- User prefers to be addressed as Doruk.\n",
        encoding="utf-8",
    )

    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )

    result = memory.search("preferred name")

    assert memory.workspace.root == tmp_path
    assert memory.config.workspace_dir == tmp_path
    assert memory.store.path == tmp_path / ".openclaw-memory" / "main.sqlite"
    assert result["results"][0]["path"] == "MEMORY.md"
    assert "Doruk" in result["results"][0]["snippet"]


def test_from_workspace_can_build_langgraph_recall_node(tmp_path: Path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-05-30.md").write_text(
        "# 2026-05-30\n\n- User prefers to be addressed as Doruk.\n",
        encoding="utf-8",
    )

    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )

    patch = memory.langgraph_recall()({"input": "Bana nasil hitap edeceksin?"})

    assert "Doruk" in patch["memory_context"]
