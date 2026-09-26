from pathlib import Path

from memory_core import MemoryConfig
from memory_core.adapters.langgraph import LangGraphMemoryRecall, format_memory_context


class _Embeddings:
    provider_id = "fake"
    model = "fake-model"


class _Store:
    embeddings = _Embeddings()

    def __init__(self, *, max_results=5, min_score=0.0):
        self.max_results = max_results
        self.min_score = min_score

    def search(self, query, *, max_results, min_score, sources):
        assert query == "Bana nasil hitap edeceksin?"
        assert max_results == self.max_results
        assert min_score == self.min_score
        # corpus="all" passes no source filter (tools.ts: searchSources undefined).
        assert sources is None
        return [
            type(
                "SearchResult",
                (),
                {
                    "source": "memory",
                    "path": "memory/2026-05-30.md",
                    "start_line": 3,
                    "end_line": 3,
                    "score": 0.91,
                    "vector_score": 0.9,
                    "text_score": 0.8,
                    "snippet": "User prefers to be addressed as Doruk.",
                },
            )()
        ]


def test_langgraph_memory_recall_returns_state_patch(tmp_path: Path):
    adapter = LangGraphMemoryRecall(
        config=MemoryConfig(workspace_dir=tmp_path),
        store=_Store(max_results=2, min_score=0.25),
        max_results=2,
        min_score=0.25,
    )

    patch = adapter({"input": "Bana nasil hitap edeceksin?"})

    assert patch["memory_results"][0]["path"] == "memory/2026-05-30.md"
    assert patch["memory_context"] == (
        "Memory recall:\n"
        "- memory/2026-05-30.md:3-3 score=0.91\n"
        "  User prefers to be addressed as Doruk.\n\n"
        "Source: memory/2026-05-30.md#L3"
    )


def test_langgraph_memory_recall_can_read_latest_user_message(tmp_path: Path):
    adapter = LangGraphMemoryRecall(
        config=MemoryConfig(workspace_dir=tmp_path),
        store=_Store(),
        input_key="missing",
    )

    patch = adapter(
        {
            "messages": [
                {"role": "user", "content": "Selam"},
                {"role": "assistant", "content": "Selam Doruk."},
                {"role": "user", "content": "Bana nasil hitap edeceksin?"},
            ]
        }
    )

    assert "Doruk" in patch["memory_context"]


def test_format_memory_context_empty_results_returns_empty_string():
    assert format_memory_context([]) == ""
