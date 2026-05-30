from pathlib import Path

import pytest

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


def test_from_workspace_initialize_creates_memory_core_files(tmp_path: Path):
    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=True,
    )

    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8").startswith("# MEMORY.md")
    assert (tmp_path / "memory").is_dir()
    assert (tmp_path / ".openclaw-memory").is_dir()
    assert memory.store.path == tmp_path / ".openclaw-memory" / "main.sqlite"


def test_from_workspace_initialize_does_not_overwrite_existing_memory(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("# Existing\n\n- Keep me.\n", encoding="utf-8")

    MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=True,
    )

    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == "# Existing\n\n- Keep me.\n"


def test_from_workspace_creates_memory_files_by_default(tmp_path: Path):
    MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )

    assert (tmp_path / "MEMORY.md").exists()
    assert (tmp_path / "memory").is_dir()


def test_from_workspace_can_disable_initialization(tmp_path: Path):
    MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=False,
    )

    assert not (tmp_path / "MEMORY.md").exists()
    assert not (tmp_path / "memory").exists()


def test_from_workspace_defaults_to_current_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)

    memory = MemoryCoreMemory.from_workspace(
        embedding_provider=FakeEmbeddingProvider(),
    )

    assert memory.workspace.root == tmp_path
    assert (tmp_path / "MEMORY.md").exists()
    assert (tmp_path / "memory").is_dir()
