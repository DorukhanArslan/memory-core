from __future__ import annotations

import os
from pathlib import Path

from memory_core import MemoryCoreMemory
from memory_core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider


def build_memory(workspace_dir: str | Path = ".") -> MemoryCoreMemory:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for the live embedding example")

    provider = OpenAICompatibleEmbeddingProvider(
        api_key=api_key,
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        model=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
    )
    return MemoryCoreMemory.from_workspace(workspace_dir, embedding_provider=provider)


def main() -> None:
    memory = build_memory()
    results = memory.search("preferred name", max_results=5)
    print(results)


if __name__ == "__main__":
    main()
