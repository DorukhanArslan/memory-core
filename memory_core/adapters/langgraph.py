from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from memory_core.config import MemoryConfig
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.tools.memory_search import memory_search


@dataclass(frozen=True)
class LangGraphMemoryRecall:
    """LangGraph-style node callable that retrieves memory into a state patch.

    This adapter intentionally does not depend on LangGraph. Host applications
    can use the instance directly as a node because it accepts a state mapping
    and returns a partial state update.
    """

    config: MemoryConfig
    store: SQLiteMemoryStore
    input_key: str = "input"
    messages_key: str = "messages"
    context_key: str = "memory_context"
    results_key: str = "memory_results"
    max_results: int = 5
    min_score: float = 0.0
    corpus: str = "all"

    def __call__(self, state: Mapping[str, Any]) -> dict[str, Any]:
        query = _query_from_state(state, input_key=self.input_key, messages_key=self.messages_key)
        if not query:
            return {self.context_key: "", self.results_key: []}

        response = memory_search(
            self.config,
            self.store,
            query=query,
            max_results=self.max_results,
            min_score=self.min_score,
            corpus=self.corpus,
        )
        results = response.get("results", [])
        return {
            self.context_key: format_memory_context(results),
            self.results_key: results,
        }


def format_memory_context(results: list[Mapping[str, Any]]) -> str:
    if not results:
        return ""

    lines = ["Memory recall:"]
    for result in results:
        path = result.get("path", "")
        start_line = result.get("startLine")
        end_line = result.get("endLine")
        score = float(result.get("score", 0))
        snippet = str(result.get("snippet", "")).strip()
        lines.append(f"- {path}:{start_line}-{end_line} score={score:.2f}")
        if snippet:
            lines.append(f"  {snippet}")
    return "\n".join(lines)


def _query_from_state(
    state: Mapping[str, Any],
    *,
    input_key: str,
    messages_key: str,
) -> str:
    value = state.get(input_key)
    if isinstance(value, str):
        return value.strip()

    messages = state.get(messages_key)
    if isinstance(messages, list):
        for message in reversed(messages):
            if not isinstance(message, Mapping):
                continue
            if message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
    return ""
