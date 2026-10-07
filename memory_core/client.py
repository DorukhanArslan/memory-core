from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from memory_core.bootstrap import DEFAULT_WORKSPACE_LAYOUT, WorkspaceLayout
from memory_core.config import MemoryConfig
from memory_core.consolidation.origins import IndexRevisionFence
from memory_core.curation import CurationPolicy, CurationResult, MemoryCurator
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore, validate_store_config
from memory_core.project_name import STATE_DIRNAME
from memory_core.tools.memory_get import memory_get
from memory_core.tools.memory_search import memory_search
from memory_core.workspace import MemoryWorkspace

DEFAULT_MEMORY_MD_TEMPLATE = """# MEMORY.md

Curated long-term memory for durable facts, preferences, decisions, and summaries.

Keep detailed daily notes in memory/YYYY-MM-DD.md.
"""


@dataclass(frozen=True)
class Memory:
    config: MemoryConfig
    workspace: MemoryWorkspace
    store: SQLiteMemoryStore

    @classmethod
    def from_workspace(
        cls,
        workspace_dir: str | Path = ".",
        *,
        embedding_provider: EmbeddingProvider | None = None,
        config: MemoryConfig | None = None,
        initialize: bool = True,
        reindex: bool = True,
        revision_fence: IndexRevisionFence | None = None,
    ) -> Memory:
        workspace = MemoryWorkspace(Path(workspace_dir))
        resolved_config = config or MemoryConfig(workspace_dir=workspace.root)
        # Raise on an invalid provider/flag/agent-id combination before any
        # directory or MEMORY.md is created.
        validate_store_config(resolved_config, embedding_provider)
        if initialize:
            initialize_memory_core_workspace(workspace.root)
        store = SQLiteMemoryStore(resolved_config, embedding_provider, revision_fence=revision_fence)
        if reindex:
            store.reindex(workspace)
        return cls(config=resolved_config, workspace=workspace, store=store)

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        min_score: float = 0.0,
        corpus: str = "all",
    ) -> dict:
        return memory_search(
            self.config,
            self.store,
            query=query,
            max_results=max_results,
            min_score=min_score,
            corpus=corpus,
        )

    def get(
        self,
        path: str,
        *,
        from_line: int | None = None,
        lines: int | None = None,
        corpus: str = "memory",
    ) -> dict:
        return memory_get(
            self.config,
            path=path,
            from_line=from_line,
            lines=lines,
            corpus=corpus,
        )

    def curator(
        self,
        *,
        layout: WorkspaceLayout = DEFAULT_WORKSPACE_LAYOUT,
        policy: CurationPolicy | None = None,
        timezone: str = "UTC",
        now_ms: Callable[[], int] | None = None,
    ) -> MemoryCurator:
        """Curated writes for this workspace (memory-core extension, see memory_core.curation).

        The curator uses this memory's feature flags and reindexes the store
        after each write to MEMORY.md or a daily note, the files memory_search
        indexes; USER.md and PROACTIVE_PREFERENCES.md writes skip the reindex.
        The reindex runs after the write is committed and re-embeds the whole
        corpus synchronously; if it fails, the write stands and the result
        carries ``after_write_error`` (``afterWriteError`` in the tool payload).
        """

        def reindex(result: CurationResult) -> None:
            if result.path == layout.memory_file or result.path.startswith("memory/"):
                self.store.reindex(self.workspace)

        return MemoryCurator(
            self.workspace.root,
            layout=layout,
            policy=policy,
            flags=self.config.effective_flags(),
            after_write=reindex,
            timezone=timezone,
            now_ms=now_ms,
        )


def initialize_memory_core_workspace(workspace_dir: str | Path) -> None:
    root = Path(workspace_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(exist_ok=True)
    (root / STATE_DIRNAME).mkdir(exist_ok=True)
    memory_path = root / "MEMORY.md"
    if not memory_path.exists():
        memory_path.write_text(DEFAULT_MEMORY_MD_TEMPLATE, encoding="utf-8")
