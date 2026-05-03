from pathlib import Path

from memory_core.config import MemoryConfig


def test_default_config_matches_first_slice_requirements(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path)
    assert cfg.agent_id == "main"
    assert cfg.embedding_provider == "openai-compatible"
    assert cfg.embedding_model == "text-embedding-3-small"
    assert cfg.vector_weight == 0.5
    assert cfg.text_weight == 0.5
    assert cfg.memory_get_max_chars == 20_000
    assert cfg.memory_get_default_lines == 120
