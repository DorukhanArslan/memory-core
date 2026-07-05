"""Embedding provider adapters."""

from memory_core.embeddings.base import EmbeddingProvider, FakeEmbeddingProvider
from memory_core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider

__all__ = [
    "EmbeddingProvider",
    "FakeEmbeddingProvider",
    "OpenAICompatibleEmbeddingProvider",
]
