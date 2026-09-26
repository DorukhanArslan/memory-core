from pathlib import Path

import pytest

from memory_core import Memory
from memory_core.embeddings.base import FakeEmbeddingProvider


def test_from_workspace_reads_host_memory_files(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "# Memory\n\n- User prefers to be addressed as Doruk.\n",
        encoding="utf-8",
    )

    memory = Memory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=False,
    )

    result = memory.search("preferred name")

    assert memory.workspace.root == tmp_path
    assert memory.config.workspace_dir == tmp_path
    assert memory.store.path == tmp_path / ".memory-core" / "main.sqlite"
    assert result["results"][0]["path"] == "MEMORY.md"
    assert "Doruk" in result["results"][0]["snippet"]


def test_from_workspace_can_build_langgraph_recall_node(tmp_path: Path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-05-30.md").write_text(
        "# 2026-05-30\n\n- User prefers to be addressed as Doruk.\n",
        encoding="utf-8",
    )

    memory = Memory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=False,
    )

    patch = memory.langgraph_recall()({"input": "Bana nasil hitap edeceksin?"})

    assert "Doruk" in patch["memory_context"]


def test_from_workspace_initialize_creates_memory_core_files(tmp_path: Path):
    memory = Memory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=True,
    )

    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8").startswith("# MEMORY.md")
    assert (tmp_path / "memory").is_dir()
    assert (tmp_path / ".memory-core").is_dir()
    assert memory.store.path == tmp_path / ".memory-core" / "main.sqlite"


def test_from_workspace_initialize_does_not_overwrite_existing_memory(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("# Existing\n\n- Keep me.\n", encoding="utf-8")

    Memory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=True,
    )

    assert (tmp_path / "MEMORY.md").read_text(encoding="utf-8") == "# Existing\n\n- Keep me.\n"


def test_from_workspace_creates_memory_files_by_default(tmp_path: Path):
    Memory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )

    assert (tmp_path / "MEMORY.md").exists()
    assert (tmp_path / "memory").is_dir()


def test_from_workspace_can_disable_initialization(tmp_path: Path):
    Memory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=False,
    )

    assert not (tmp_path / "MEMORY.md").exists()
    assert not (tmp_path / "memory").exists()


def test_from_workspace_defaults_to_current_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)

    memory = Memory.from_workspace(
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
    memory = Memory.from_workspace(
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
    memory = Memory.from_workspace(
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


def test_chat_runs_answer_then_forced_memory_flush_and_reindexes(tmp_path: Path):
    memory = Memory.from_workspace(
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
        force_flush=True,
        timezone="Europe/Istanbul",
    )

    assert result.assistant_message == "Tamam Doruk."
    assert result.flush_result.wrote is True
    assert result.flush_result.path.startswith("memory/")
    assert (tmp_path / result.flush_result.path).read_text(encoding="utf-8") == (
        "- User prefers to be addressed as Doruk.\n"
    )
    assert len(calls) == 2
    assert calls[1][0]["role"] == "system"
    assert "Pre-compaction memory flush turn." in calls[1][0]["content"]
    assert result.flush_result.path in calls[1][0]["content"]
    assert calls[1][1]["role"] == "user"
    assert "User: Bana Doruk diye hitap et." in calls[1][1]["content"]
    assert "Assistant: Tamam Doruk." in calls[1][1]["content"]
    assert memory.search("addressed as Doruk")["results"][0]["path"] == result.flush_result.path


def test_chat_can_use_separate_flush_model(tmp_path: Path):
    memory = Memory.from_workspace(
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
        force_flush=True,
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


def test_chat_does_not_flush_without_force_flush(tmp_path: Path):
    memory = Memory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )
    flush_calls = []

    result = memory.chat(
        "Bana Doruk diye hitap et.",
        llm=lambda messages: "Tamam Doruk.",
        flush_llm=lambda messages: flush_calls.append(messages) or "- User prefers Doruk.",
        timezone="Europe/Istanbul",
    )

    assert result.assistant_message == "Tamam Doruk."
    assert result.flush_result.wrote is False
    assert result.flush_result.path.startswith("memory/")
    assert result.flush_result.raw_text == ""
    assert flush_calls == []
    assert not any((tmp_path / "memory").glob("*.md"))


def test_chat_does_not_expose_test_clock_control(tmp_path: Path):
    memory = Memory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )

    try:
        memory.chat(
            "Bana Doruk diye hitap et.",
            llm=lambda messages: "Tamam Doruk.",
            now_ms=1777824000000,
        )
    except TypeError as exc:
        assert "now_ms" in str(exc)
    else:
        raise AssertionError("chat should not expose now_ms")


def test_record_turn_skips_write_when_flush_model_returns_no_reply(tmp_path: Path):
    memory = Memory.from_workspace(
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


def test_from_workspace_indexes_markdown_that_is_not_valid_utf8(tmp_path: Path):
    # buildFileEntry decodes with Buffer.toString("utf-8"), which replaces
    # invalid bytes: an AppleDouble `._*.md` (written by macOS on SMB/exFAT)
    # or a Latin-1 note under memory/ must not fail the reindex.
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "2026-09-26.md").write_text("- Glacier backups run nightly.\n", encoding="utf-8")
    (memory_dir / "._2026-09-26.md").write_bytes(b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X\xff\xfe")
    (memory_dir / "latin1.md").write_bytes("- Caf\xe9 glacier notes.\n".encode("latin-1"))

    memory = Memory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
        initialize=False,
    )
    result = memory.search("glacier", corpus="memory")

    assert memory.store.reindex(memory.workspace) == 3
    snippets = {item["path"]: item["snippet"] for item in result["results"]}
    assert "Caf\ufffd glacier notes." in snippets["memory/latin1.md"]
    assert "memory/2026-09-26.md" in snippets


def test_reindex_skips_a_file_that_vanished_after_discovery(tmp_path: Path, monkeypatch):
    (tmp_path / "MEMORY.md").write_text("- Glacier backups.\n", encoding="utf-8")
    memory = Memory.from_workspace(
        tmp_path, embedding_provider=FakeEmbeddingProvider(), initialize=False
    )
    discover = memory.workspace.discover_indexable_files

    def discover_with_a_vanished_file():
        files = discover()
        gone = files[0].__class__("memory/gone.md", tmp_path / "memory" / "gone.md")
        return [*files, gone]

    monkeypatch.setattr(memory.workspace, "discover_indexable_files", discover_with_a_vanished_file)

    assert memory.store.reindex(memory.workspace) == 1
    assert [item["path"] for item in memory.search("glacier")["results"]] == ["MEMORY.md"]
