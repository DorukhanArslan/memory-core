from pathlib import Path

from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.flags import FeatureFlags
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


def _text_only_store(tmp_path: Path) -> SQLiteMemoryStore:
    cfg = MemoryConfig(
        workspace_dir=tmp_path,
        store_path=tmp_path / "memory.sqlite",
        vector_weight=0,
        text_weight=1,
        flags=FeatureFlags(vector_search=False),
    )
    store = SQLiteMemoryStore(cfg, None)
    store.reindex(MemoryWorkspace(tmp_path))
    return store


def test_keyword_fallback_recovers_conversational_query(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "# Long-Term Memory\n\n- Move backups to S3 Glacier cold storage.\n",
        encoding="utf-8",
    )
    store = _text_only_store(tmp_path)

    # The strict AND query fails ("please"/"thing" never appear in the note);
    # the per-keyword fallback probes "glacier" and "backups" separately.
    results = store.search("please find the glacier backups thing", min_score=0)

    assert [item.path for item in results] == ["MEMORY.md"]
    assert results[0].text_score > 0


def test_keyword_fallback_dedupes_chunks_hit_by_multiple_terms(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "# Long-Term Memory\n\n- Move backups to S3 Glacier cold storage.\n",
        encoding="utf-8",
    )
    store = _text_only_store(tmp_path)

    results = store.search("please show the glacier backups storage thing", min_score=0)

    assert [item.path for item in results] == ["MEMORY.md"]


def test_keyword_fallback_caps_probes_at_six_terms(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "# Long-Term Memory\n\n- Zephyr rollout is paused.\n",
        encoding="utf-8",
    )
    store = _text_only_store(tmp_path)

    # Seven keywords; only the seventh ("zephyr") appears in the note, but the
    # fallback only probes the first six terms.
    results = store.search("kappa lambda sigma theta omega gamma zephyr", min_score=0)

    assert results == []
