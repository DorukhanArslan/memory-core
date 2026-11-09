"""Real dispatch/cache effects of bounded embedding retry and batch admission."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from memory_core.cancellation import CancellationSignal
from memory_core.config import MemoryConfig
from memory_core.embeddings.base import FakeEmbeddingProvider
from memory_core.index.embedding_policy import (
    build_memory_embedding_batches,
    is_splittable_memory_embedding_batch_error,
    run_memory_embedding_batch_retry_with_split,
    run_memory_embedding_retry_loop,
)
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


def failure(message="provider failure", **fields):
    error = RuntimeError(message)
    for name, value in fields.items():
        setattr(error, name, value)
    return error


def test_byte_budget_preserves_items_and_source_unicode():
    items = ["a" * 4_000, "b" * 4_000, "𐐀" * 1_000, "x" * 4_001, "z" * 8_001]
    assert build_memory_embedding_batches(items, lambda item: item) == [items[:2], items[2:3], items[3:4], items[4:]]
    assert build_memory_embedding_batches(["\ud800", "a"], lambda item: item, 3) == [["\ud800"], ["a"]]


@pytest.mark.parametrize("fields,message,expected_calls", [
    ({"status": 503}, "temporary provider failure", 3),
    ({"statusCode": 503.0}, "temporary provider failure", 3),
    ({"status": 403}, "provider message mentions 503 ECONNRESET", 1),
    ({"status": "503"}, "ordinary terminal refusal", 1),
    ({"response": SimpleNamespace(status_code=403)}, "provider message mentions503", 1),
    ({"code": "quota_exceeded", "status": 429}, "rate limit", 1),
    ({"status": True}, "ordinary terminal refusal", 1),
    ({"status": 10**1000}, "ordinary terminal refusal", 1),
    ({}, "ECONNRESET synthetic connection reset", 3),
    ({}, "β503β", 3),
    ({}, "ſocket hang up", 1),
])
def test_retry_classification_respects_explicit_status_and_quota(fields, message, expected_calls):
    calls, waits = [], []
    error = failure(message, **fields)

    def run():
        calls.append("dispatch")
        raise error

    with pytest.raises(RuntimeError) as caught:
        run_memory_embedding_retry_loop(run, profile="index", wait_for_retry=waits.append, random=lambda: .5)
    assert caught.value is error
    assert len(calls) == expected_calls
    assert len(waits) == expected_calls - 1
    if expected_calls == 3:
        assert waits == [500, 1_000]


def test_query_retry_after_has_one_shared_eight_second_wait_budget():
    calls, waits = [], []
    error = failure("rate limit", status=429, code="insufficient_quota", retryAfterMs=8_000.0)

    def run():
        calls.append("dispatch")
        raise error

    with pytest.raises(RuntimeError) as caught:
        run_memory_embedding_retry_loop(run, profile="query", wait_for_retry=waits.append, random=lambda: 0)
    assert caught.value is error
    assert calls == ["dispatch"] * 3
    assert waits == [8_000, 0]


def test_abort_during_retry_wait_prevents_another_provider_call():
    signal = CancellationSignal()
    calls = []
    reason = RuntimeError("caller stopped while waiting")

    def run():
        calls.append("dispatch")
        raise failure("ECONNRESET synthetic failure")

    def wait(_delay):
        signal.abort(reason)

    with pytest.raises(RuntimeError) as caught:
        run_memory_embedding_retry_loop(run, profile="query", signal=signal, wait_for_retry=wait)
    assert caught.value is reason
    assert calls == ["dispatch"]


@pytest.mark.parametrize("message,eligible", [
    ("input array max 1", True), ("input array max 10'}", True),
    ("input array max 1 tokens per item", False), ("input array max 1x", False),
    ("HTTP413 payload too large", False), ("batch size is invalid, it should not be larger than 1", True),
    ("input array max\u00a01\ufeff", True), ("input array max\u001c1", False),
])
def test_item_cap_split_requires_original_whole_count_boundary(message, eligible):
    assert is_splittable_memory_embedding_batch_error(message) is eligible


def test_success_callback_failure_is_never_retried_or_split():
    requests, accepted = [], []
    error = failure("ECONNRESET in cache admission")

    def dispatch(items):
        requests.append(list(items))
        return [[1] for _ in items]

    def accept(items, _vectors):
        accepted.append(list(items))
        raise error

    with pytest.raises(RuntimeError) as caught:
        run_memory_embedding_batch_retry_with_split(["a", "b"], dispatch, on_success=accept)
    assert caught.value is error
    assert requests == accepted == [["a", "b"]]


class RecordingProvider(FakeEmbeddingProvider):
    provider_id = "embedding-policy-test"
    model = "generic-test-model"

    def __init__(self):
        super().__init__(4)
        self.calls, self.successes, self.query_calls = [], [], []
        self.max_items = None
        self.fail_marker = None
        self.query_failures = 0

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        if self.max_items is not None and len(texts) > self.max_items:
            raise failure(f"input array max {self.max_items}")
        if self.fail_marker and any(self.fail_marker in text for text in texts):
            raise failure("terminal synthetic document refusal")
        result = super().embed_documents(texts)
        self.successes.extend(zip(texts, result, strict=True))
        return result

    def embed_query(self, text):
        self.query_calls.append(text)
        if self.query_failures:
            self.query_failures -= 1
            raise failure("synthetic service failure", status=503)
        return super().embed_query(text)


def make_store(tmp_path, texts):
    root = tmp_path / "workspace"
    root.mkdir()
    for filename, text in texts.items():
        target = root / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    provider = RecordingProvider()
    return SQLiteMemoryStore(MemoryConfig(workspace_dir=root, store_path=tmp_path / "index.sqlite"), provider), MemoryWorkspace(root), provider


def test_real_refresh_preserves_distinct_source_requests_and_byte_budget(tmp_path):
    large = "".join(f"line{index:03}: forest cedar maple " + "leaf " * 16 + "\n" for index in range(160))
    store, workspace, provider = make_store(tmp_path, {"memory/a.md": "source A", "memory/b.md": large})
    assert store.reindex(workspace) == 2
    assert ["source A"] in provider.calls
    assert len(provider.calls) > 2
    assert all(sum(len(text.encode()) for text in call) <= 8_000 for call in provider.calls)
    assert all("source A" not in call or call == ["source A"] for call in provider.calls)
    before = list(provider.calls)
    assert store.reindex(workspace) == 2
    assert provider.calls == before


def test_real_partial_split_cache_survives_terminal_leaf_and_recovery(tmp_path):
    text = "".join(f"row{index:03}: forest cedar maple " + "leaf " * 16 + "\n" for index in range(160))
    store, workspace, provider = make_store(tmp_path, {"memory/forest.md": text})
    provider.max_items = 1
    provider.fail_marker = "row080:"
    with pytest.raises(RuntimeError, match="terminal synthetic"):
        store.reindex(workspace)
    assert store.count_chunks() == 0
    successful_texts = {text for text, _vector in provider.successes}
    assert successful_texts
    with store.connect() as db:
        cached_before = {row[0] for row in db.execute("SELECT hash FROM memory_embedding_cache")}
    assert cached_before == {hashlib.sha256(text.encode()).hexdigest() for text in successful_texts}
    before = len(provider.calls)
    provider.max_items, provider.fail_marker = None, None
    assert store.reindex(workspace) == 1
    assert store.count_chunks() > len(cached_before)
    recovered_requests = [text for call in provider.calls[before:] for text in call]
    assert recovered_requests and successful_texts.isdisjoint(recovered_requests)
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM memory_embedding_cache").fetchone()[0] == store.count_chunks()


def test_real_query_retries_without_adding_query_cache_entries(tmp_path, monkeypatch):
    store, workspace, provider = make_store(tmp_path, {"memory/a.md": "source A forest"})
    store.reindex(workspace)
    waits = []
    monkeypatch.setattr("memory_core.index.embedding_policy._wait", lambda delay, signal: waits.append(delay))
    provider.query_failures = 1
    store.search("forest", min_score=0)
    store.search("forest", min_score=0)
    assert provider.query_calls == ["forest", "forest", "forest"]
    assert len(waits) == 1 and 500 <= waits[0] <= 600
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM memory_embedding_cache").fetchone()[0] == 1


def test_refresh_retry_retains_original_provider_instance(tmp_path, monkeypatch):
    store, workspace, first = make_store(tmp_path, {"memory/a.md": "source A forest"})
    replacement = RecordingProvider()
    original = first.embed_documents
    attempts = []
    monkeypatch.setattr("memory_core.index.embedding_policy._wait", lambda *_: None)

    def dispatch(texts):
        attempts.append(list(texts))
        if len(attempts) == 1:
            store.embeddings = replacement
            raise failure("temporary service failure", status=503)
        return original(texts)

    first.embed_documents = dispatch
    assert store.reindex(workspace) == 1
    assert attempts == [["source A forest"], ["source A forest"]]
    assert replacement.calls == []


def test_query_retry_retains_original_provider_instance(tmp_path, monkeypatch):
    store, workspace, first = make_store(tmp_path, {"memory/a.md": "source A forest"})
    store.reindex(workspace)
    replacement = RecordingProvider()
    original = first.embed_query
    attempts = []
    monkeypatch.setattr("memory_core.index.embedding_policy._wait", lambda *_: None)

    def dispatch(text):
        attempts.append(text)
        if len(attempts) == 1:
            store.embeddings = replacement
            raise failure("temporary service failure", status=503)
        return original(text)

    first.embed_query = dispatch
    store.search("forest", min_score=0)
    assert attempts == ["forest", "forest"]
    assert replacement.query_calls == []
