from __future__ import annotations

from contextlib import nullcontext
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
from memory_core.workspace import MemoryWorkspace, workspace_index_lock

DEFAULT_MEMORY_MD_TEMPLATE = """# MEMORY.md

Curated long-term memory for durable facts, preferences, decisions, and summaries.

Keep detailed daily notes in memory/YYYY-MM-DD.md.
"""


class _IndexedMemoryCurator(MemoryCurator):
    """Guard only the SDK's own synchronous write-and-index operation.

    Arbitrary after-write callbacks keep the generic curator's unlocked
    contract, including callbacks which join a refresh in another thread.
    """

    _index_after_write: Callable[[CurationResult], None] | None = None

    def _edit(
        self, operation: str, name: str, edit: Callable[[str], tuple[str, str]],
        *, memory_flush: bool, require_existing: bool = False,
    ) -> CurationResult:
        guard = (workspace_index_lock(self.root)
                 if self.after_write is self._index_after_write else nullcontext())
        with guard:
            return super()._edit(operation, name, edit, memory_flush=memory_flush,
                                 require_existing=require_existing)

    def append_daily_note(
        self, text: str, *, date: str | None = None, memory_flush: bool = False,
    ) -> CurationResult:
        guard = (workspace_index_lock(self.root)
                 if self.after_write is self._index_after_write else nullcontext())
        with guard:
            return super().append_daily_note(text, date=date, memory_flush=memory_flush)


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
        after each write to MEMORY.md, USER.md or a daily note, the default
        files memory_search indexes. PROACTIVE_PREFERENCES.md writes skip it.
        The refresh runs synchronously after the write is committed, reusing
        unchanged chunks and cached document embeddings. If it fails, the write
        stands and the result carries ``after_write_error`` (``afterWriteError``
        in the tool payload).
        The default write and refresh serialize per workspace in this process.
        Replacing ``after_write`` restores the generic unlocked callback contract.
        """

        def reindex(result: CurationResult) -> None:
            if result.path in (layout.memory_file, "USER.md") or result.path.startswith("memory/"):
                self.store.reindex(self.workspace)

        curator = _IndexedMemoryCurator(
            self.workspace.root,
            layout=layout,
            policy=policy,
            flags=self.config.effective_flags(),
            after_write=reindex,
            timezone=timezone,
            now_ms=now_ms,
        )
        curator._index_after_write = reindex
        return curator


def initialize_memory_core_workspace(workspace_dir: str | Path) -> None:
    root = Path(workspace_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(exist_ok=True)
    (root / STATE_DIRNAME).mkdir(exist_ok=True)
    memory_path = root / "MEMORY.md"
    if not memory_path.exists():
        memory_path.write_text(DEFAULT_MEMORY_MD_TEMPLATE, encoding="utf-8")
