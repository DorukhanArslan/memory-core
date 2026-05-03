from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoryConfig:
    workspace_dir: Path
    agent_id: str = "main"
    store_path: Path | None = None
    embedding_provider: str = "openai-compatible"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"
    citation_mode: str = "on"
    memory_get_max_chars: int = 20_000
    memory_get_default_lines: int = 120
    vector_weight: float = 0.5
    text_weight: float = 0.5
    mmr_enabled: bool = False
    mmr_lambda: float = 0.7
    temporal_decay_enabled: bool = False
    temporal_decay_half_life_days: float = 30.0

    def resolved_store_path(self) -> Path:
        if self.store_path is not None:
            return self.store_path
        return self.workspace_dir / ".openclaw-memory" / f"{self.agent_id}.sqlite"
