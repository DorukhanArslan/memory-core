from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from memory_core.flags import FeatureFlags

SAFE_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class MemoryConfig:
    workspace_dir: Path
    agent_id: str = "main"
    store_path: Path | None = None
    citation_mode: str = "on"
    memory_get_max_chars: int = 12_000
    memory_get_default_lines: int = 120
    vector_weight: float = 0.5
    text_weight: float = 0.5
    mmr_enabled: bool = False
    mmr_lambda: float = 0.7
    temporal_decay_enabled: bool = False
    temporal_decay_half_life_days: float = 30.0
    flags: FeatureFlags | None = None

    def effective_flags(self) -> FeatureFlags:
        """Resolve feature flags; explicit `flags` wins over legacy booleans."""
        if self.flags is not None:
            return self.flags
        return FeatureFlags(
            mmr=self.mmr_enabled,
            temporal_decay=self.temporal_decay_enabled,
        )

    def resolved_store_path(self) -> Path:
        if self.store_path is not None:
            return self.store_path
        if not SAFE_AGENT_ID_RE.match(self.agent_id):
            raise ValueError(f"agent_id is not filename-safe: {self.agent_id}")
        return self.workspace_dir / ".memory-core" / f"{self.agent_id}.sqlite"
