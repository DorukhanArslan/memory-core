from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureFlags:
    """Central switchboard for optional memory-core capabilities.

    Disabled means inert: a disabled capability must not call its backing
    provider, alter scores, or leave side effects. `vector_search=False`
    mirrors OpenClaw's `provider: "none"` FTS-only mode, where keyword
    results keep their full text score and no embedder is ever invoked.

    `subject_promotion` gates scored consolidation on live subject workspaces
    (`memory_core.live.SubjectConsolidation`, a Q16 extension without an upstream
    counterpart, off by default): disabled means every call raises before
    touching the subject workspace.
    """

    vector_search: bool = True
    text_search: bool = True
    mmr: bool = False
    temporal_decay: bool = False
    subject_promotion: bool = False

    def __post_init__(self) -> None:
        if not self.vector_search and not self.text_search:
            raise ValueError(
                "at least one of vector_search or text_search must be enabled"
            )
