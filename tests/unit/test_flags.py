from __future__ import annotations

from pathlib import Path

import pytest

from memory_core import FeatureFlags, Memory, MemoryConfig
from memory_core.embeddings import FakeEmbeddingProvider


class SpyEmbeddingProvider:
    provider_id = "spy"
    model = "spy-model"

    def __init__(self):
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(f"query:{text}")
        return [0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(f"documents:{len(texts)}")
        return [[0.0] for _ in texts]


def _seed_workspace(root: Path) -> None:
    (root / "memory").mkdir(parents=True)
    (root / "MEMORY.md").write_text(
        "# MEMORY.md\n\n- Refund policy exception requires supervisor approval.\n",
        encoding="utf-8",
    )
    (root / "memory" / "2026-07-05.md").write_text(
        "## Tool failure\n\nCRM update failed with ERR_CRM_409_CONFLICT.\n",
        encoding="utf-8",
    )


def _fts_only_memory(tmp_path: Path, **flag_overrides) -> Memory:
    _seed_workspace(tmp_path)
    config = MemoryConfig(
        workspace_dir=tmp_path,
        flags=FeatureFlags(vector_search=False, **flag_overrides),
    )
    return Memory.from_workspace(tmp_path, config=config)


def test_vector_disabled_never_calls_embedder(tmp_path):
    _seed_workspace(tmp_path)
    spy = SpyEmbeddingProvider()
    config = MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(tmp_path, embedding_provider=spy, config=config)

    memory.search("ERR_CRM_409_CONFLICT")
    memory.store.reindex(memory.workspace)

    assert spy.calls == []


def test_fts_only_works_without_embedding_provider(tmp_path):
    memory = _fts_only_memory(tmp_path)

    result = memory.search("ERR_CRM_409_CONFLICT")

    assert result["provider"] == "none"
    assert result["model"] == "fts-only"
    assert [item["path"] for item in result["results"]] == ["memory/2026-07-05.md"]


def test_fts_only_keyword_hits_keep_full_text_score(tmp_path):
    memory = _fts_only_memory(tmp_path)

    results = memory.search("ERR_CRM_409_CONFLICT")["results"]

    assert results
    for item in results:
        assert item["score"] == item["textScore"] > 0
        assert item["vectorScore"] == 0


def test_fts_only_relaxes_min_score_when_strict_pass_is_empty(tmp_path):
    memory = _fts_only_memory(tmp_path)

    results = memory.search("ERR_CRM_409_CONFLICT", min_score=0.99)["results"]

    assert [item["path"] for item in results] == ["memory/2026-07-05.md"]


def test_fts_only_search_is_deterministic(tmp_path):
    memory = _fts_only_memory(tmp_path)

    first = memory.search("supervisor approval refund exception")
    second = memory.search("supervisor approval refund exception")

    assert first == second


def test_vector_search_enabled_requires_embedding_provider(tmp_path):
    _seed_workspace(tmp_path)

    with pytest.raises(ValueError, match="vector_search is enabled"):
        Memory.from_workspace(tmp_path)


def test_missing_embedding_provider_raises_before_creating_any_file(tmp_path):
    workspace = tmp_path / "fresh"

    with pytest.raises(ValueError, match="vector_search is enabled"):
        Memory.from_workspace(workspace)

    assert not workspace.exists()


def test_missing_embedding_provider_leaves_existing_workspace_untouched(tmp_path):
    (tmp_path / "AGENTS.md").write_text("rules\n", encoding="utf-8")

    with pytest.raises(ValueError, match="vector_search is enabled"):
        Memory.from_workspace(tmp_path)

    assert sorted(path.name for path in tmp_path.iterdir()) == ["AGENTS.md"]


def test_unsafe_agent_id_raises_before_creating_any_file(tmp_path):
    workspace = tmp_path / "fresh"
    config = MemoryConfig(
        workspace_dir=workspace,
        agent_id="../outside",
        flags=FeatureFlags(vector_search=False),
    )

    with pytest.raises(ValueError, match="agent_id is not filename-safe"):
        Memory.from_workspace(workspace, config=config)

    assert not workspace.exists()


def test_text_search_disabled_uses_vector_only_scores(tmp_path):
    _seed_workspace(tmp_path)
    config = MemoryConfig(workspace_dir=tmp_path, flags=FeatureFlags(text_search=False))
    memory = Memory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        config=config,
    )

    results = memory.search("supervisor approval")["results"]

    assert results
    for item in results:
        assert item["score"] == item["vectorScore"]
        assert item["textScore"] == 0


def test_both_search_modes_disabled_is_invalid():
    with pytest.raises(ValueError, match="at least one"):
        FeatureFlags(vector_search=False, text_search=False)


def test_effective_flags_derive_from_legacy_config_fields(tmp_path):
    config = MemoryConfig(
        workspace_dir=tmp_path,
        mmr_enabled=True,
        temporal_decay_enabled=True,
    )

    flags = config.effective_flags()

    assert flags == FeatureFlags(mmr=True, temporal_decay=True)


def test_explicit_flags_override_legacy_config_fields(tmp_path):
    config = MemoryConfig(
        workspace_dir=tmp_path,
        mmr_enabled=True,
        temporal_decay_enabled=True,
        flags=FeatureFlags(),
    )

    assert config.effective_flags() == FeatureFlags(mmr=False, temporal_decay=False)


def test_temporal_decay_disabled_leaves_fts_only_scores_untouched(tmp_path):
    _seed_workspace(tmp_path)
    (tmp_path / "memory" / "2020-01-01.md").write_text(
        "Old note about ERR_CRM_409_CONFLICT retries.\n",
        encoding="utf-8",
    )

    def _score(flags: FeatureFlags) -> float:
        config = MemoryConfig(workspace_dir=tmp_path, flags=flags)
        memory = Memory.from_workspace(tmp_path, config=config)
        results = memory.search("ERR_CRM_409_CONFLICT")["results"]
        return next(
            item["score"] for item in results if item["path"] == "memory/2020-01-01.md"
        )

    plain = _score(FeatureFlags(vector_search=False))
    decayed = _score(FeatureFlags(vector_search=False, temporal_decay=True))

    assert decayed < plain
