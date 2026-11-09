from __future__ import annotations

import httpx


class OpenAICompatibleEmbeddingProvider:
    provider_id = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
        max_input_tokens: int | float | None = None,
    ):
        if not api_key:
            raise ValueError("api_key is required for OpenAI-compatible embeddings")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_input_tokens = max_input_tokens

    def cache_key_data(self) -> dict[str, str]:
        # Hashed into the index identity's providerKey, so an index built for
        # another endpoint pauses search (OpenClaw openai memory-embedding-adapter
        # cacheKeyData; the API key is never part of it).
        return {"provider": self.provider_id, "baseUrl": self.base_url, "model": self.model}

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        response = httpx.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": inputs},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return [
            item["embedding"]
            for item in sorted(payload["data"], key=lambda item: item["index"])
        ]

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)
