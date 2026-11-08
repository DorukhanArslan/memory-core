"""Real indexed partial snapshots, provider waits and publication interleavings."""
from __future__ import annotations

from copy import deepcopy
import threading

import pytest

from memory_core.cancellation import CancellationSignal, OperationAbortedError
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.flags import FeatureFlags
from memory_core.index.hybrid import HYBRID_METADATA_MISSING
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


class _BlockingEmbedding(FakeEmbeddingProvider):
    def __init__(self):
        super().__init__(dimensions=4)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.failure = None
        self.calls = 0

    def embed_query(self, text):
        self.calls += 1
        self.entered.set()
        if not self.release.wait(3):
            raise TimeoutError("Test provider was not released")
        if self.failure is not None:
            raise self.failure
        return super().embed_query(text)


class _CountingStore(SQLiteMemoryStore):
    def __init__(self, *args, **kwargs):
        self.keyword_calls = 0
        super().__init__(*args, **kwargs)

    def _search_keyword_with_fallback(self, *args, **kwargs):
        self.keyword_calls += 1
        return super()._search_keyword_with_fallback(*args, **kwargs)


@pytest.fixture
def indexed(tmp_path):
    (tmp_path / "MEMORY.md").write_text("- Cobalt original durable fact.\n", encoding="utf-8")
    sessions = tmp_path / "memory" / ".dreams" / "session-corpus"
    sessions.mkdir(parents=True)
    (sessions / "2026-11-08.md").write_text("- Cobalt private transcript fact.\n", encoding="utf-8")
    provider = _BlockingEmbedding()
    config = MemoryConfig(
        workspace_dir=tmp_path, flags=FeatureFlags(temporal_decay=False, mmr=False),
    )
    store = _CountingStore(config, provider)
    workspace = MemoryWorkspace(tmp_path)
    store.reindex(workspace)
    return store, provider, workspace


def _start(store, callback, *, signal=None):
    box = {}

    def run():
        try:
            box["result"] = store.search(
                "cobalt", max_results=10, min_score=0, signal=signal,
                on_partial_results=callback,
            )
        except BaseException as error:
            box["error"] = error

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    return worker, box


def _finish(provider, worker):
    provider.release.set()
    worker.join(3)
    assert not worker.is_alive()


def test_snapshot_precedes_embedding_and_excludes_sessions_and_private_mtimes(indexed):
    store, provider, _workspace = indexed
    partials = []
    worker, box = _start(store, partials.append)
    try:
        assert provider.entered.wait(3)
        assert len(partials) == 1
        snapshot = partials[0]
        assert [hit.path for hit in snapshot] == ["MEMORY.md"]
        assert all(hit.source == "memory" for hit in snapshot)
        assert "original durable fact" in snapshot[0].snippet
        assert snapshot[0].source_mtime is HYBRID_METADATA_MISSING
        assert snapshot[0].provenance["originClass"] == "agent"
        # A consumer cannot alter metadata retained for the complete result.
        snapshot[0].provenance["originClass"] = "untrusted"
    finally:
        _finish(provider, worker)
    assert "error" not in box
    assert {hit.source for hit in box["result"]} == {"memory", "sessions"}
    memory = [hit for hit in box["result"] if hit.source == "memory"]
    assert all(hit.provenance["originClass"] == "agent" for hit in memory)
    assert store.keyword_calls == 1
    assert provider.calls == 1


def test_cancelled_provider_holds_no_read_lock_and_does_not_query_again(indexed):
    store, provider, workspace = indexed
    signal = CancellationSignal()
    partials = []
    worker, box = _start(store, lambda value: partials.append(deepcopy(value)), signal=signal)
    try:
        assert provider.entered.wait(3)
        before = deepcopy(partials)
        signal.abort("Caller stopped waiting")
        (workspace.root / "MEMORY.md").write_text("- Cobalt updated durable fact.\n", encoding="utf-8")
        # This real writer must finish while query embedding is still blocked.
        store.reindex(workspace)
        assert not provider.release.is_set()
        assert partials == before
        assert store.keyword_calls == 1
    finally:
        _finish(provider, worker)
    assert isinstance(box["error"], OperationAbortedError)
    assert store.keyword_calls == 1
    later = store.search("cobalt", min_score=0)
    assert any("updated durable fact" in hit.snippet for hit in later)


def test_publication_during_embedding_invalidates_old_partial_and_never_mixes_generations(indexed):
    store, provider, workspace = indexed
    partials = []
    worker, box = _start(store, lambda value: partials.append(deepcopy(value)))
    try:
        assert provider.entered.wait(3)
        assert len(partials) == 1
        (workspace.root / "MEMORY.md").write_text("- Cobalt replacement durable fact.\n", encoding="utf-8")
        store.reindex(workspace)
    finally:
        _finish(provider, worker)
    assert "error" not in box
    assert partials[-1] is None
    assert any("replacement durable fact" in hit.snippet for hit in box["result"])
    assert not any("original durable fact" in hit.snippet for hit in box["result"])
    assert store.keyword_calls == 2


def test_provider_failure_invalidates_partial_without_mislabeling_timeout_text(indexed):
    store, provider, _workspace = indexed
    provider.failure = RuntimeError("memory_search timed out after 30s")
    partials = []
    worker, box = _start(store, partials.append)
    try:
        assert provider.entered.wait(3)
        assert partials and partials[0]
    finally:
        _finish(provider, worker)
    assert box["error"] is provider.failure
    assert partials[-1] is None
    assert store.keyword_calls == 1


def test_provider_identity_change_invalidates_the_retained_snapshot(indexed):
    store, provider, _workspace = indexed
    partials = []
    worker, box = _start(store, partials.append)
    try:
        assert provider.entered.wait(3)
        assert partials and partials[0]
        provider.model = "a-different-model"
    finally:
        _finish(provider, worker)
    assert "error" not in box
    assert box["result"] == []
    assert partials[-1] is None
    assert store.keyword_calls == 1
