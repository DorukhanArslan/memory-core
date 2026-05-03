import pytest

from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider


def test_fake_embedding_provider_is_deterministic():
    provider = FakeEmbeddingProvider(dimensions=6)
    assert provider.embed_query("alpha") == provider.embed_query("alpha")
    assert provider.embed_query("alpha") != provider.embed_query("beta")


def test_openai_provider_requires_api_key():
    with pytest.raises(ValueError, match="api_key"):
        OpenAICompatibleEmbeddingProvider(api_key="", model="text-embedding-3-small")
