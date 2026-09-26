from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureFlags:
    """Central switchboard for optional memory-core capabilities.

    Disabled means inert: a disabled capability must not call its backing
    provider, alter scores, or leave side effects. `vector_search=False`
    mirrors OpenClaw's `provider: "none"` FTS-only mode, where keyword
    results keep their full text score and no embedder is ever invoked.

    `curated_memory_writes` gates the memory-core curation tools
    (`memory_core.curation.MemoryCurator`, a Q16 extension, on by default):
    disabled means the tools are not offered and every call raises before
    touching the workspace.
    """

    vector_search: bool = True
    text_search: bool = True
    mmr: bool = False
    temporal_decay: bool = False
    curated_memory_writes: bool = True

    def __post_init__(self) -> None:
        if not self.vector_search and not self.text_search:
            raise ValueError(
                "at least one of vector_search or text_search must be enabled"
            )
