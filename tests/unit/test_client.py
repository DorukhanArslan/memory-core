from pathlib import Path

import pytest

from memory_core import MemoryCoreMemory
from memory_core.embeddings.base import FakeEmbeddingProvider


def test_from_workspace_reads_host_memory_files(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "# Memory\n\n- User prefers to be addressed as Doruk.\n",
        encoding="utf-8",
    )

    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=False,
    )

    result = memory.search("preferred name")

    assert memory.workspace.root == tmp_path
    assert memory.config.workspace_dir == tmp_path
    assert memory.store.path == tmp_path / ".openclaw-memory" / "main.sqlite"
    assert result["results"][0]["path"] == "MEMORY.md"
    assert "Doruk" in result["results"][0]["snippet"]


def test_from_workspace_can_build_langgraph_recall_node(tmp_path: Path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-05-30.md").write_text(
        "# 2026-05-30\n\n- User prefers to be addressed as Doruk.\n",
        encoding="utf-8",
    )

    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=False,
    )

    patch = memory.langgraph_recall()({"input": "Bana nasil hitap edeceksin?"})

    assert "Doruk" in patch["memory_context"]


def test_from_workspace_initialize_creates_memory_core_files(tmp_path: Path):
    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=True,
    )

    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8").startswith("# MEMORY.md")
    assert (tmp_path / "memory").is_dir()
    assert (tmp_path / ".openclaw-memory").is_dir()
    assert memory.store.path == tmp_path / ".openclaw-memory" / "main.sqlite"


def test_from_workspace_initialize_does_not_overwrite_existing_memory(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("# Existing\n\n- Keep me.\n", encoding="utf-8")

    MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=True,
    )

    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == "# Existing\n\n- Keep me.\n"


def test_from_workspace_creates_memory_files_by_default(tmp_path: Path):
    MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )

    assert (tmp_path / "MEMORY.md").exists()
    assert (tmp_path / "memory").is_dir()


def test_from_workspace_can_disable_initialization(tmp_path: Path):
    MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=False,
    )

    assert not (tmp_path / "MEMORY.md").exists()
    assert not (tmp_path / "memory").exists()


def test_from_workspace_defaults_to_current_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)

    memory = MemoryCoreMemory.from_workspace(
        embedding_provider=FakeEmbeddingProvider(),
    )

    assert memory.workspace.root == tmp_path
    assert (tmp_path / "MEMORY.md").exists()
    assert (tmp_path / "memory").is_dir()


def test_prepare_turn_injects_recalled_memory_into_chat_messages(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "# MEMORY.md\n\n- User prefers to be addressed as Doruk.\n",
        encoding="utf-8",
    )
    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )

    turn = memory.prepare_turn("Bana nasil hitap edeceksin?")

    assert turn.user_message == "Bana nasil hitap edeceksin?"
    assert turn.memory_results[0]["path"] == "MEMORY.md"
    assert "Doruk" in turn.memory_context
    assert turn.messages[0] == {
        "role": "system",
        "content": (
            "Use relevant memory when it helps answer the user. "
            "Do not mention memory unless useful."
        ),
    }
    assert turn.messages[1]["role"] == "system"
    assert turn.messages[1]["content"].startswith("Relevant memory:\nMemory recall:")
    assert turn.messages[2] == {
        "role": "user",
        "content": "Bana nasil hitap edeceksin?",
    }


def test_prepare_turn_omits_memory_message_when_no_results(tmp_path: Path):
    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=False,
    )

    turn = memory.prepare_turn("Yeni bir soru")

    assert turn.memory_results == []
    assert turn.memory_context == ""
    assert turn.messages == [
        {
            "role": "system",
            "content": (
                "Use relevant memory when it helps answer the user. "
                "Do not mention memory unless useful."
            ),
        },
        {"role": "user", "content": "Yeni bir soru"},
    ]


def test_chat_runs_answer_then_memory_flush_and_reindexes(tmp_path: Path):
    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )
    calls = []

    def fake_llm(messages):
        calls.append(messages)
        if messages[0]["content"].startswith("Pre-compaction memory flush turn."):
            return "- User prefers to be addressed as Doruk."
        return "Tamam Doruk."

    result = memory.chat(
        "Bana Doruk diye hitap et.",
        llm=fake_llm,
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert result.assistant_message == "Tamam Doruk."
    assert result.flush_result.wrote is True
    assert result.flush_result.path == "memory/2026-05-03.md"
    assert (tmp_path / "memory" / "2026-05-03.md").read_text(encoding="utf-8") == (
        "- User prefers to be addressed as Doruk.\n"
    )
    assert len(calls) == 2
    assert calls[1][0]["role"] == "system"
    assert "Pre-compaction memory flush turn." in calls[1][0]["content"]
    assert "memory/2026-05-03.md" in calls[1][0]["content"]
    assert calls[1][1]["role"] == "user"
    assert "User: Bana Doruk diye hitap et." in calls[1][1]["content"]
    assert "Assistant: Tamam Doruk." in calls[1][1]["content"]
    assert memory.search("addressed as Doruk")["results"][0]["path"] == "memory/2026-05-03.md"


def test_chat_can_use_separate_flush_model(tmp_path: Path):
    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )
    answer_calls = []
    flush_calls = []

    def answer_llm(messages):
        answer_calls.append(messages)
        return "Tamam Doruk."

    def flush_llm(messages):
        flush_calls.append(messages)
        return "- User prefers to be addressed as Doruk."

    result = memory.chat(
        "Bana Doruk diye hitap et.",
        llm=answer_llm,
        flush_llm=flush_llm,
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert result.assistant_message == "Tamam Doruk."
    assert result.flush_result.wrote is True
    assert len(answer_calls) == 1
    assert answer_calls[0][-1] == {"role": "user", "content": "Bana Doruk diye hitap et."}
    assert len(flush_calls) == 1
    assert flush_calls[0][0]["content"].startswith("Pre-compaction memory flush turn.")
    assert "Recent turn transcript:" in flush_calls[0][1]["content"]
    assert "Assistant: Tamam Doruk." in flush_calls[0][1]["content"]


def test_chat_can_skip_automatic_flush(tmp_path: Path):
    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )
    flush_calls = []

    result = memory.chat(
        "Bana Doruk diye hitap et.",
        llm=lambda messages: "Tamam Doruk.",
        flush_llm=lambda messages: flush_calls.append(messages) or "- User prefers Doruk.",
        auto_flush=False,
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert result.assistant_message == "Tamam Doruk."
    assert result.flush_result.wrote is False
    assert result.flush_result.path == "memory/2026-05-03.md"
    assert result.flush_result.raw_text == ""
    assert flush_calls == []
    assert not (tmp_path / "memory" / "2026-05-03.md").exists()


def test_record_turn_skips_write_when_flush_model_returns_no_reply(tmp_path: Path):
    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )

    result = memory.record_turn(
        "Selam",
        "Selam Doruk.",
        flush_llm=lambda messages: "NO_REPLY",
        now_ms=1777824000000,
        timezone="Europe/Istanbul",
    )

    assert result.wrote is False
    assert result.path == "memory/2026-05-03.md"
    assert not (tmp_path / "memory" / "2026-05-03.md").exists()
