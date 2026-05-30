from pathlib import Path

import examples.basic_usage as basic_usage
import examples.chatbot_memory as chatbot_memory
from memory_core import MemoryCoreMemory
from memory_core.embeddings.base import FakeEmbeddingProvider


class _FakeProvider:
    def __init__(self, *, api_key, base_url, model):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def embed_query(self, text):
        return [0.1, 0.2]

    def embed_documents(self, texts):
        return [[0.1, 0.2] for _ in texts]


def test_basic_usage_builds_memory_from_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setattr(basic_usage, "OpenAICompatibleEmbeddingProvider", _FakeProvider)

    memory = basic_usage.build_memory(tmp_path)

    assert memory.workspace.root == tmp_path
    assert (tmp_path / "MEMORY.md").exists()
    assert (tmp_path / "memory").is_dir()
    assert memory.store.embeddings.api_key == "sk-test"
    assert memory.store.embeddings.base_url == "https://example.test/v1"
    assert memory.store.embeddings.model == "text-embedding-3-small"


def test_basic_usage_requires_openai_api_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    try:
        basic_usage.build_memory(tmp_path)
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:
        raise AssertionError("expected OPENAI_API_KEY error")


def test_chatbot_memory_prepares_messages_for_llm(tmp_path: Path):
    chatbot_memory.seed_demo_memory(tmp_path)
    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )
    captured = {}

    def fake_chat(messages):
        captured["messages"] = messages
        return "Doruk diye hitap edecegim."

    answer = chatbot_memory.answer_with_memory(
        memory,
        "Bana nasil hitap edeceksin?",
        fake_chat,
    )

    assert answer == "Doruk diye hitap edecegim."
    assert captured["messages"][1]["content"].startswith("Relevant memory:")
    assert "Doruk" in captured["messages"][1]["content"]


def test_chatbot_memory_can_run_answer_and_flush(tmp_path: Path):
    memory = MemoryCoreMemory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )

    def fake_chat(messages):
        if messages[0]["content"].startswith("Pre-compaction memory flush turn."):
            return "- User prefers to be addressed as Doruk."
        return "Tamam Doruk."

    result = chatbot_memory.chat_with_memory(
        memory,
        "Bana Doruk diye hitap et.",
        fake_chat,
    )

    assert result.assistant_message == "Tamam Doruk."
    assert result.flush_result.wrote is True
    assert "Doruk" in (tmp_path / result.flush_result.path).read_text(encoding="utf-8")
