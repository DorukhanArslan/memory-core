"""Input limits and dispatch must use the same admitted provider instance."""
from __future__ import annotations

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


class BoundedProvider:
    provider_id = "captured-provider-test"
    model = "same-canonical-model"

    def __init__(self, maximum):
        self.max_input_tokens = maximum
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        if any(len(text.encode()) > self.max_input_tokens for text in texts):
            raise RuntimeError("permanent local input-size refusal")
        return [[1, 0] for _ in texts]

    def embed_query(self, _text):
        raise AssertionError("Preparation must not execute a query")


@pytest.mark.parametrize("reload_during_discovery", [False, True])
def test_preparation_retains_the_provider_captured_for_document_dispatch(tmp_path, reload_during_discovery):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    (root / "memory/source.md").write_text("abcdefghijklmnopqrstuvwxyz" * 4)
    admitted, replacement = BoundedProvider(8), BoundedProvider(1_000)
    store = SQLiteMemoryStore(MemoryConfig(root, flags=FeatureFlags(vector_search=True)), admitted)

    class ReloadingWorkspace(MemoryWorkspace):
        reloaded = False

        def discover_indexable_files(self):
            files = super().discover_indexable_files()
            if reload_during_discovery and not self.reloaded:
                self.reloaded = True
                store.embeddings = replacement
            return files

    assert store.reindex(ReloadingWorkspace(root)) == 1
    assert store.count_chunks() == 13
    assert admitted.calls and all(len(text.encode()) <= 8 for call in admitted.calls for text in call)
    assert replacement.calls == []
    assert store.index_identity() == {"status": "valid"}
