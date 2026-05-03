import pytest

from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider


def test_fake_embedding_provider_is_deterministic():
    provider = FakeEmbeddingProvider(dimensions=6)
    assert provider.embed_query("alpha") == provider.embed_query("alpha")
    assert provider.embed_query("alpha") != provider.embed_query("beta")


def test_fake_embedding_provider_metadata_and_dimensions():
    provider = FakeEmbeddingProvider(dimensions=6)

    assert provider.provider_id == "fake"
    assert provider.model == "fake-deterministic"
    assert len(provider.embed_query("alpha")) == 6


def test_fake_embedding_provider_embeds_one_vector_per_document_with_document_prefix():
    provider = FakeEmbeddingProvider(dimensions=6)

    document_embeddings = provider.embed_documents(["alpha", "beta"])

    assert len(document_embeddings) == 2
    assert all(len(embedding) == 6 for embedding in document_embeddings)
    assert document_embeddings[0] != provider.embed_query("alpha")


def test_openai_provider_requires_api_key():
    with pytest.raises(ValueError, match="api_key"):
        OpenAICompatibleEmbeddingProvider(api_key="", model="text-embedding-3-small")


def test_openai_provider_default_base_url_and_timeout():
    provider = OpenAICompatibleEmbeddingProvider(
        api_key="key",
        model="text-embedding-3-small",
    )

    assert provider.base_url == "https://api.openai.com/v1"
    assert provider.timeout == 30.0


def test_openai_provider_defaults_and_strips_base_url():
    provider = OpenAICompatibleEmbeddingProvider(
        api_key="test-key",
        model="text-embedding-3-small",
        base_url="https://example.test/v1/",
    )

    assert provider.provider_id == "openai-compatible"
    assert provider.base_url == "https://example.test/v1"
    assert provider.timeout == 30.0
    assert provider.model == "text-embedding-3-small"


def test_openai_provider_posts_embedding_request_and_sorts_by_index(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"index": 1, "embedding": [0.2, 0.3]},
                    {"index": 0, "embedding": [0.0, 0.1]},
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("memory_core.embeddings.openai_compatible.httpx.post", fake_post)
    provider = OpenAICompatibleEmbeddingProvider(
        api_key="test-key",
        model="text-embedding-3-small",
        base_url="https://example.test/v1/",
        timeout=12.5,
    )

    embeddings = provider.embed_documents(["alpha", "beta"])

    assert captured == {
        "url": "https://example.test/v1/embeddings",
        "headers": {"Authorization": "Bearer test-key"},
        "json": {"model": "text-embedding-3-small", "input": ["alpha", "beta"]},
        "timeout": 12.5,
    }
    assert embeddings == [[0.0, 0.1], [0.2, 0.3]]
