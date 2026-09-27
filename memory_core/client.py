from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from memory_core.adapters.langgraph import LangGraphMemoryRecall, format_memory_context
from memory_core.bootstrap import DEFAULT_WORKSPACE_LAYOUT, WorkspaceLayout
from memory_core.config import MemoryConfig
from memory_core.curation import CurationPolicy, CurationResult, MemoryCurator
from memory_core.current_time import DEFAULT_TIME_FORMAT
from memory_core.embeddings.base import EmbeddingProvider
from memory_core.index.sqlite_store import SQLiteMemoryStore, validate_store_config
from memory_core.memory_flush import SILENT_REPLY_TOKEN, build_memory_flush_plan
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
class MemoryRecordResult:
    wrote: bool
    path: str
    text: str
    raw_text: str


@dataclass(frozen=True)
class MemoryChatResult:
    turn: MemoryChatTurn
    assistant_message: str
    flush_result: MemoryRecordResult


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
    ) -> Memory:
        workspace = MemoryWorkspace(Path(workspace_dir))
        resolved_config = config or MemoryConfig(workspace_dir=workspace.root)
        # Raise on an invalid provider/flag/agent-id combination before any
        # directory or MEMORY.md is created.
        validate_store_config(resolved_config, embedding_provider)
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

    def record_turn(
        self,
        user_message: str,
        assistant_message: str,
        *,
        flush_llm: Callable[[list[dict[str, str]]], str],
        now_ms: int | None = None,
        timezone: str = "UTC",
        time_format: str = DEFAULT_TIME_FORMAT,
    ) -> MemoryRecordResult:
        plan = build_memory_flush_plan(
            workspace_dir=self.workspace.root,
            now_ms=now_ms,
            timezone=timezone,
            time_format=time_format,
        )
        flush_messages = [
            {"role": "system", "content": plan.system_prompt},
            {
                "role": "user",
                "content": (
                    f"{plan.prompt}\n\n"
                    "Recent turn transcript:\n"
                    f"User: {user_message}\n"
                    f"Assistant: {assistant_message}"
                ),
            },
        ]
        raw_text = flush_llm(flush_messages)
        text = raw_text.strip()
        if not text or text.startswith(SILENT_REPLY_TOKEN):
            return MemoryRecordResult(
                wrote=False,
                path=plan.relative_path,
                text="",
                raw_text=raw_text,
            )

        self.workspace.append_daily_memory(plan.relative_path, text)
        self.store.reindex(self.workspace)
        return MemoryRecordResult(
            wrote=True,
            path=plan.relative_path,
            text=text,
            raw_text=raw_text,
        )

    def chat(
        self,
        user_message: str,
        *,
        llm: Callable[[list[dict[str, str]]], str],
        flush_llm: Callable[[list[dict[str, str]]], str] | None = None,
        system_prompt: str = DEFAULT_CHAT_SYSTEM_PROMPT,
        max_results: int = 5,
        min_score: float = 0.0,
        corpus: str = "all",
        force_flush: bool = False,
        timezone: str = "UTC",
        time_format: str = DEFAULT_TIME_FORMAT,
    ) -> MemoryChatResult:
        turn = self.prepare_turn(
            user_message,
            system_prompt=system_prompt,
            max_results=max_results,
            min_score=min_score,
            corpus=corpus,
        )
        assistant_message = llm(turn.messages)
        if force_flush:
            flush_result = self.record_turn(
                user_message,
                assistant_message,
                flush_llm=flush_llm or llm,
                timezone=timezone,
                time_format=time_format,
            )
        else:
            plan = build_memory_flush_plan(
                workspace_dir=self.workspace.root,
                timezone=timezone,
                time_format=time_format,
            )
            flush_result = MemoryRecordResult(
                wrote=False,
                path=plan.relative_path,
                text="",
                raw_text="",
            )
        return MemoryChatResult(
            turn=turn,
            assistant_message=assistant_message,
            flush_result=flush_result,
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
    (root / ".memory-core").mkdir(exist_ok=True)
    memory_path = root / "MEMORY.md"
    if not memory_path.exists():
        memory_path.write_text(DEFAULT_MEMORY_MD_TEMPLATE, encoding="utf-8")
