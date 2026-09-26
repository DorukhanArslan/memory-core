from pathlib import Path

import pytest

from memory_core.config import MemoryConfig


def test_default_config_matches_first_slice_requirements(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path)
    assert cfg.agent_id == "main"
    assert cfg.vector_weight == 0.5
    assert cfg.text_weight == 0.5
    assert cfg.memory_get_max_chars == 12_000
    assert cfg.memory_get_default_lines == 120


def test_resolved_store_path_rejects_unsafe_agent_id(tmp_path: Path):
    cfg = MemoryConfig(workspace_dir=tmp_path, agent_id="../../outside")

    with pytest.raises(ValueError):
        cfg.resolved_store_path()


def test_store_path_stays_configurable(tmp_path: Path):
    # Documented deviation from OpenClaw's fixed per-agent openclaw-agent.sqlite.
    assert MemoryConfig(workspace_dir=tmp_path).resolved_store_path() == (
        tmp_path / ".memory-core" / "main.sqlite"
    )
    assert MemoryConfig(workspace_dir=tmp_path, agent_id="ops").resolved_store_path() == (
        tmp_path / ".memory-core" / "ops.sqlite"
    )
    custom = tmp_path / "elsewhere" / "index.sqlite"
    assert MemoryConfig(
        workspace_dir=tmp_path, agent_id="ops", store_path=custom
    ).resolved_store_path() == custom
