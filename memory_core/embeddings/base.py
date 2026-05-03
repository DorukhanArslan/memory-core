from __future__ import annotations

import hashlib
from typing import Protocol


class EmbeddingProvider(Protocol):
    provider_id: str
    model: str

    def embed_query(self, text: str) -> list[float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...


class FakeEmbeddingProvider:
    provider_id = "fake"
    model = "fake-deterministic"

    def __init__(self, dimensions: int = 16):
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = [digest[i % len(digest)] / 255 for i in range(self.dimensions)]
        return values

    def embed_query(self, text: str) -> list[float]:
        return self._embed(f"query:{text}")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(f"document:{text}") for text in texts]
