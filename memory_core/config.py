from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from memory_core.flags import FeatureFlags
from memory_core.project_name import STATE_DIRNAME

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
        """Where the SQLite memory index lives.

        Documented deviation (decision Q15): ``store_path`` stays configurable
        and defaults to ``<workspace>/.memory-core/<agent_id>.sqlite``. OpenClaw at
        pin 4c428153 ignores ``memorySearch.store.path`` and always keeps the
        index in the per-agent state database
        ``<stateDir>/agents/<agentId>/agent/openclaw-agent.sqlite``
        (``src/state/openclaw-agent-db.paths.ts`` resolveOpenClawAgentSqlitePath).
        Hosts embed memory-core next to their own storage, so the path is theirs to
        choose; the stored index identity still pauses search when a store is
        reopened with another provider, model or settings.
        """
        if self.store_path is not None:
            return self.store_path
        if not SAFE_AGENT_ID_RE.match(self.agent_id):
            raise ValueError(f"agent_id is not filename-safe: {self.agent_id}")
        return self.workspace_dir / STATE_DIRNAME / f"{self.agent_id}.sqlite"
