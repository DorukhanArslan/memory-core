from pathlib import Path

from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


def test_forced_reindex_indexes_memory_files(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "User prefers blue cheese with wings.\n", encoding="utf-8"
    )
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-05-03.md").write_text(
        "Discussed router VLANs.\n", encoding="utf-8"
    )
    cfg = MemoryConfig(workspace_dir=tmp_path, store_path=tmp_path / "memory.sqlite")
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))

    indexed = store.reindex(MemoryWorkspace(tmp_path))

    assert indexed == 2
    assert store.count_chunks() >= 2
