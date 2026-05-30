import os
from pathlib import Path

import pytest

from memory_core import MemoryCoreMemory
from memory_core.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider


@pytest.mark.skipif(
    os.environ.get("OPENCLAW_MEMORY_LIVE_OPENAI") != "1" or not os.environ.get("OPENAI_API_KEY"),
    reason=(
        "OPENCLAW_MEMORY_LIVE_OPENAI=1 and OPENAI_API_KEY are required for live "
        "OpenAI-compatible embedding smoke"
    ),
)
def test_live_openai_embedding_provider_indexes_and_searches(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text(
        "# MEMORY.md\n\n- User prefers to be addressed as Doruk.\n",
        encoding="utf-8",
    )
    provider = OpenAICompatibleEmbeddingProvider(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        model=os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
    )

    memory = MemoryCoreMemory.from_workspace(tmp_path, embedding_provider=provider)
    result = memory.search("preferred name", max_results=3)

    assert result["provider"] == "openai-compatible"
    assert result["model"] == provider.model
    assert result["results"]
    assert result["results"][0]["path"] == "MEMORY.md"
