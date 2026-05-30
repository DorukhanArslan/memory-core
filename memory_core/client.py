from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from memory_core.adapters.langgraph import LangGraphMemoryRecall, format_memory_context
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.tools.memory_get import memory_get
from memory_core.tools.memory_search import memory_search
from memory_core.workspace import MemoryWorkspace

DEFAULT_MEMORY_MD_TEMPLATE = """# MEMORY.md

Curated long-term memory for durable facts, preferences, decisions, and summaries.

Keep detailed daily notes in memory/YYYY-MM-DD.md.
"""

DEFAULT_CHAT_SYSTEM_PROMPT = (
    "Use relevant memory when it helps answer the user. Do not mention memory unless useful."
)


@dataclass(frozen=True)
class MemoryChatTurn:
    user_message: str
    memory_results: list[dict]
    memory_context: str
    messages: list[dict[str, str]]


@dataclass(frozen=True)
class MemoryCoreMemory:
    config: MemoryConfig
    workspace: MemoryWorkspace
    store: SQLiteMemoryStore

    @classmethod
    def from_workspace(
        cls,
        workspace_dir: str | Path = ".",
        *,
        embedding_provider: EmbeddingProvider,
        config: MemoryConfig | None = None,
        initialize: bool = True,
        reindex: bool = True,
    ) -> MemoryCoreMemory:
        workspace = MemoryWorkspace(Path(workspace_dir))
        resolved_config = config or MemoryConfig(workspace_dir=workspace.root)
        if initialize:
            initialize_memory_core_workspace(workspace.root)
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

    def prepare_turn(
        self,
        user_message: str,
        *,
        system_prompt: str = DEFAULT_CHAT_SYSTEM_PROMPT,
        max_results: int = 5,
        min_score: float = 0.0,
        corpus: str = "all",
    ) -> MemoryChatTurn:
        search_result = self.search(
            user_message,
            max_results=max_results,
            min_score=min_score,
            corpus=corpus,
        )
        memory_results = search_result.get("results", [])
        memory_context = format_memory_context(memory_results)
        messages = [{"role": "system", "content": system_prompt}]
        if memory_context:
            messages.append({"role": "system", "content": f"Relevant memory:\n{memory_context}"})
        messages.append({"role": "user", "content": user_message})
        return MemoryChatTurn(
            user_message=user_message,
            memory_results=memory_results,
            memory_context=memory_context,
            messages=messages,
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


def initialize_memory_core_workspace(workspace_dir: str | Path) -> None:
    root = Path(workspace_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(exist_ok=True)
    (root / ".openclaw-memory").mkdir(exist_ok=True)
    memory_path = root / "MEMORY.md"
    if not memory_path.exists():
        memory_path.write_text(DEFAULT_MEMORY_MD_TEMPLATE, encoding="utf-8")
