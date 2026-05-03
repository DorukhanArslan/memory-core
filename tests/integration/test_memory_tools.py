from pathlib import Path

from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.tools.memory_get import memory_get
from memory_core.tools.memory_search import memory_search
from memory_core.workspace import MemoryWorkspace


def test_memory_get_reads_line_window(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    result = memory_get(
        MemoryConfig(workspace_dir=tmp_path), path="MEMORY.md", from_line=2, lines=1
    )
    assert result["path"] == "MEMORY.md"
    assert result["text"] == "beta\n"
    assert result["startLine"] == 2
    assert result["endLine"] == 2


def test_memory_search_returns_hybrid_results(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "User likes lemon pepper wings.\n", encoding="utf-8"
    )
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))

    result = memory_search(cfg, store, query="lemon pepper", max_results=3, min_score=0.0)

    assert result["provider"] == "fake"
    assert result["model"] == "fake-deterministic"
    assert result["results"][0]["path"] == "MEMORY.md"
    assert result["results"][0]["corpus"] == "memory"
