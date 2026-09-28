import asyncio
from pathlib import Path

import examples.basic_usage as basic_usage
import examples.live_streaming as live_streaming
from memory_core.live import LiveIdentityStore


class _FakeProvider:
    # Stands in for OpenAICompatibleEmbeddingProvider (EmbeddingProvider protocol).
    provider_id = "openai-compatible"

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


def test_live_streaming_example_emits_tts_sentences(tmp_path: Path):
    live_streaming.seed_identity(tmp_path)

    sentences = asyncio.run(live_streaming.run_live_turn(tmp_path))

    assert sentences == [
        "Tabii, yardimci olayim.",
        "Once kimliginizi dogrulayalim.",
    ]
    assert (tmp_path / "trace" / "session_456.jsonl").exists()


def test_live_streaming_example_seeds_the_default_layout(tmp_path: Path):
    live_streaming.seed_identity(tmp_path)

    identity = LiveIdentityStore(tmp_path, required_files=["AGENTS.md"]).load()
    prompt = identity.to_prompt_section()

    assert not (tmp_path / "BOOTSTRAP.md").exists()
    assert (tmp_path / "PROACTIVE_PREFERENCES.md").read_text(encoding="utf-8") == ""
    assert [Path(path).name for path, _ in identity.sections] == ["AGENTS.md", "SOUL.md"]
    assert "[MISSING]" not in prompt
    assert "Bootstrap Pending" not in prompt


def test_live_streaming_example_records_session_summary(tmp_path: Path):
    memory_path = asyncio.run(live_streaming.record_session_summary(tmp_path))

    assert memory_path.startswith("memory/")
    memory_file = tmp_path / "subjects" / "subj_123" / memory_path
    assert "evening delivery" in memory_file.read_text(encoding="utf-8")
