import asyncio
from pathlib import Path

import examples.basic_usage as basic_usage
import examples.chatbot_memory as chatbot_memory
import examples.live_streaming as live_streaming
from memory_core import Memory
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
    memory = Memory.from_workspace(
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
    memory = Memory.from_workspace(
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
        force_flush=True,
    )

    assert result.assistant_message == "Tamam Doruk."
    assert result.flush_result.wrote is True
    assert "Doruk" in (tmp_path / result.flush_result.path).read_text(encoding="utf-8")


def test_chatbot_memory_exposes_force_flush_without_test_clock_controls(tmp_path: Path):
    memory = Memory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )
    flush_calls = []

    result = chatbot_memory.chat_with_memory(
        memory,
        "Bana Doruk diye hitap et.",
        lambda messages: "Tamam Doruk.",
        flush_chat=lambda messages: flush_calls.append(messages) or "- User prefers Doruk.",
        force_flush=True,
        timezone="Europe/Istanbul",
    )

    assert result.assistant_message == "Tamam Doruk."
    assert result.flush_result.wrote is True
    assert result.flush_result.path.startswith("memory/")
    assert len(flush_calls) == 1


def test_chatbot_memory_does_not_expose_test_clock_control(tmp_path: Path):
    memory = Memory.from_workspace(
        tmp_path,
        embedding_provider=FakeEmbeddingProvider(),
    )

    try:
        chatbot_memory.chat_with_memory(
            memory,
            "Bana Doruk diye hitap et.",
            lambda messages: "Tamam Doruk.",
            now_ms=1777824000000,
        )
    except TypeError as exc:
        assert "now_ms" in str(exc)
    else:
        raise AssertionError("chat_with_memory should not expose now_ms")


def test_live_streaming_example_emits_tts_sentences(tmp_path: Path):
    identity_dir = tmp_path / "identity"
    live_streaming.seed_identity(identity_dir)

    sentences = asyncio.run(live_streaming.run_live_turn(tmp_path, identity_dir))

    assert sentences == [
        "Tabii, yardimci olayim.",
        "Once kimliginizi dogrulayalim.",
    ]
    assert (tmp_path / "trace" / "session_456.jsonl").exists()


def test_live_streaming_example_records_session_summary(tmp_path: Path):
    memory_path = asyncio.run(live_streaming.record_session_summary(tmp_path))

    assert memory_path.startswith("memory/")
    memory_file = tmp_path / "subjects" / "subj_123" / memory_path
    assert "evening delivery" in memory_file.read_text(encoding="utf-8")
