from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from memory_core.adapters.langgraph import LangGraphMemoryRecall
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.tools.memory_get import memory_get
from memory_core.tools.memory_search import memory_search
from memory_core.workspace import MemoryWorkspace


@dataclass(frozen=True)
class MemoryCoreMemory:
    config: MemoryConfig
    workspace: MemoryWorkspace
    store: SQLiteMemoryStore

    @classmethod
    def from_workspace(
        cls,
        workspace_dir: str | Path,
        *,
        embedding_provider: EmbeddingProvider,
        config: MemoryConfig | None = None,
        reindex: bool = True,
    ) -> MemoryCoreMemory:
        workspace = MemoryWorkspace(Path(workspace_dir))
        resolved_config = config or MemoryConfig(workspace_dir=workspace.root)
        store = SQLiteMemoryStore(resolved_config, embedding_provider)
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

    def langgraph_recall(
        self,
        *,
        input_key: str = "input",
        messages_key: str = "messages",
        context_key: str = "memory_context",
        results_key: str = "memory_results",
        max_results: int = 5,
        min_score: float = 0.0,
        corpus: str = "all",
    ) -> LangGraphMemoryRecall:
        return LangGraphMemoryRecall(
            config=self.config,
            store=self.store,
            input_key=input_key,
            messages_key=messages_key,
            context_key=context_key,
            results_key=results_key,
            max_results=max_results,
            min_score=min_score,
            corpus=corpus,
        )
