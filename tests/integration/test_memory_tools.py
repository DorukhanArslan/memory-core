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


def test_memory_get_rejects_non_memory_workspace_file(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("not memory\n", encoding="utf-8")

    result = memory_get(MemoryConfig(workspace_dir=tmp_path), path="notes.txt")

    assert result["disabled"] is True
    assert result["text"] == ""
    assert "not an allowed memory file" in result["error"]


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
    assert result["results"][0]["citation"] == "Source: MEMORY.md#1"


def test_memory_search_clamps_snippets_and_reports_truncation(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "User likes lemon pepper wings with blue cheese.\n", encoding="utf-8"
    )
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "memory.sqlite",
        memory_get_max_chars=10,
    )
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))

    result = memory_search(cfg, store, query="lemon pepper", max_results=1, min_score=0.0)

    first = result["results"][0]
    assert first["snippet"] == "User likes"
    assert first["truncated"] is True
    assert first["originalChars"] > 10
    assert first["citation"] == "Source: MEMORY.md#1"


def test_temporal_decay_affects_store_search_order(tmp_path: Path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2000-01-01.md").write_text("alpha beta\n", encoding="utf-8")
    (tmp_path / "memory" / "2999-01-01.md").write_text("alpha beta\n", encoding="utf-8")
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "memory.sqlite",
        temporal_decay_enabled=True,
        temporal_decay_half_life_days=1,
    )
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))

    results = store.search("alpha beta", max_results=2, min_score=0.0)

    assert results[0].path == "memory/2999-01-01.md"
    assert results[0].score > results[1].score


def test_mmr_config_is_applied_to_store_search(tmp_path: Path, monkeypatch):
    (tmp_path / "MEMORY.md").write_text("alpha\nbeta\n", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2999-01-01.md").write_text("alpha\ngamma\n", encoding="utf-8")
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "memory.sqlite",
        mmr_enabled=True,
    )
    store = SQLiteMemoryStore(cfg, FakeEmbeddingProvider(dimensions=8))
    store.reindex(MemoryWorkspace(tmp_path))
    calls = []

    def fake_mmr(items, *, enabled, lambda_):
        calls.append((enabled, lambda_, len(items)))
        return list(reversed(items))

    monkeypatch.setattr("memory_core.index.sqlite_store.mmr_rerank", fake_mmr)

    store.search("alpha", max_results=2, min_score=0.0)

    assert calls == [(True, 0.7, 2)]
