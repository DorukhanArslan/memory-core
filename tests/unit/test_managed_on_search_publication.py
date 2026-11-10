"""Real publication and reader ownership for the optional on-search profile."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import threading

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.lifecycle import HostModelResult
from memory_core.host.managed_session import ManagedHostSession
from memory_core.host.session import SessionState, TurnUsage
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.session_visibility import resolve_memory_search_source_policy


NOW = 1_794_182_400_000
KEY = "agent:main:dm:on-search-publication"
ID = "on-search-publication"
STATE = SessionState.new(session_key=KEY, session_id=ID)
SEED = "My bicycle label is CEDAR-OLD-731."
FRESH = "My tea preference is MAPLE-NEW-942 without sugar."


def _owner(tmp_path, *, sessions=False):
    root = tmp_path / "workspace"
    root.mkdir()
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW)
    config = MemoryConfig(root, store_path=tmp_path / "index.sqlite", citation_mode="off",
                          flags=FeatureFlags(vector_search=False, temporal_decay=False))
    policy = resolve_memory_search_source_policy(["memory"], remember_across_conversations=sessions)
    return ManagedHostSession.open(root, catalog=catalog, config=config, source_policy=policy,
        memory_publication="on-search", identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY,
        timezone="UTC", now_ms=lambda: NOW)


def _append(owner, text, *, section="Preferences"):
    return owner.kit.dispatch("add_memory_entry", {"section": section, "text": text}, session=STATE)


def _search(owner, query):
    return owner.kit.dispatch("memory_search", {"query": query, "minScore": 0, "maxResults": 5}, session=STATE)


def _memory(owner):
    return owner.store.lifecycle_snapshot()["memoryPublication"]


def _wait_settled(owner):
    # This joins admitted work after its compared read; it neither starts a
    # refresh nor drains a future timer.
    with owner.store._condition:
        assert owner.store._condition.wait_for(lambda: not _memory(owner)["active"], timeout=5)
    return _memory(owner)


def _warm(owner):
    saved = _append(owner, SEED, section="Facts")
    assert saved["status"] == "ok" and saved["indexStatus"] == "pending"
    assert _search(owner, "CEDAR-OLD-731")["results"]
    _wait_settled(owner)
    assert owner.store.index_identity()["status"] == "valid"
    assert owner.store.read_published_index()["chunks"]


def _hold_publisher(owner, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = owner.store._run_memory_publication

    def hold(*args, **kwargs):
        entered.set()
        assert release.wait(5), "The test must release the actual admitted memory publisher"
        return original(*args, **kwargs)

    monkeypatch.setattr(owner.store, "_run_memory_publication", hold)
    return entered, release


@pytest.mark.parametrize("policy", ["later", None])
def test_invalid_publication_policy_refuses_before_workspace_or_index_io(tmp_path, policy):
    root = tmp_path / "absent-workspace"
    index = tmp_path / "absent-index.sqlite"
    config = MemoryConfig(root, store_path=index, flags=FeatureFlags(vector_search=False))
    catalog = MemorySessionCatalog(tmp_path / "catalog.sqlite", clock_ms=lambda: NOW)
    with pytest.raises(ValueError, match="publication"):
        ManagedHostSession.open(root, catalog=catalog, config=config, memory_publication=policy)
    assert not root.exists() and not index.exists()


def test_cold_real_host_save_is_recalled_by_its_immediate_natural_search(tmp_path):
    async def scenario():
        owner = _owner(tmp_path)
        runner = owner.runner(STATE)
        seen = {}

        async def save(turn):
            args = {"section": "Preferences", "text": FRESH}
            turn.record_message({"role": "assistant", "content": [{"type": "toolCall",
                "id": "save", "name": "add_memory_entry", "arguments": deepcopy(args)}]})
            seen["save"] = await turn.dispatch_async("save", "add_memory_entry", args)
            turn.record_message({"role": "assistant", "content": "Saved."})
            return HostModelResult(TurnUsage(20, 3))

        async def recall(turn):
            seen["index_at_next_model"] = owner.store.read_index_meta()
            args = {"query": "MAPLE-NEW-942", "minScore": 0, "maxResults": 5}
            turn.record_message({"role": "assistant", "content": [{"type": "toolCall",
                "id": "search", "name": "memory_search", "arguments": deepcopy(args)}]})
            seen["search"] = await turn.dispatch_async("search", "memory_search", args)
            hit = seen["search"]["results"][0]
            args = {"path": hit["path"], "from": hit["startLine"], "lines": hit["endLine"] - hit["startLine"] + 1}
            turn.record_message({"role": "assistant", "content": [{"type": "toolCall",
                "id": "get", "name": "memory_get", "arguments": deepcopy(args)}]})
            seen["get"] = await turn.dispatch_async("get", "memory_get", args)
            turn.record_message({"role": "assistant", "content": seen["get"]["text"]})
            return HostModelResult(TurnUsage(20, 3))

        try:
            saved = await runner.run_turn("Remember my tea preference.", execute=save, request_id="save")
            assert saved.memory_writes_committed and not saved.failures
            assert saved.index_status == "pending" and seen["save"]["indexStatus"] == "pending"
            assert owner.store.read_index_meta() is None
            recalled = await runner.run_turn("How do I take tea?", execute=recall, request_id="recall")
            assert seen["index_at_next_model"] is None
            assert FRESH in seen["get"]["text"]
            assert not recalled.failures
        finally:
            await owner.aclose()

    asyncio.run(scenario())


def test_warm_search_uses_pinned_old_generation_then_real_background_publication(tmp_path, monkeypatch):
    owner = _owner(tmp_path)
    release = None
    try:
        _warm(owner)
        before = owner.store.read_published_index()
        saved = _append(owner, FRESH)
        assert saved["status"] == "ok" and saved["indexStatus"] == "pending"
        assert FRESH in (owner.kit.memory.workspace.root / "MEMORY.md").read_text()
        assert owner.store.read_published_index() == before
        assert _memory(owner)["dirty"] is True and not _memory(owner)["active"]
        assert owner.publication_status()["memoryIndexStatus"] == "pending"

        entered, release = _hold_publisher(owner, monkeypatch)
        old = _search(owner, "MAPLE-NEW-942")
        assert entered.wait(5)
        assert old["results"] == []
        state = _memory(owner)
        assert state["active"] and state["jobs"][-1]["readRevision"] == before["revision"]
        assert owner.store.read_published_index() == before

        release.set()
        settled = _wait_settled(owner)
        assert settled["jobs"][-1]["state"] == "completed" and not settled["dirty"]
        assert owner.store.index_revision() > before["revision"]
        assert any(FRESH in row["text"] for row in owner.store.read_published_index()["chunks"])
        current = _search(owner, "MAPLE-NEW-942")
        assert any(FRESH in hit["snippet"] for hit in current["results"])
        assert "stale" not in current
    finally:
        if release is not None:
            release.set()
        owner.close()


def test_actual_publication_failure_is_stale_and_later_search_recovers_without_manual_refresh(tmp_path):
    owner = _owner(tmp_path)
    journal = Path(str(owner.store.path) + "-journal")
    try:
        _warm(owner)
        before = owner.store.read_published_index()
        assert _append(owner, FRESH)["indexStatus"] == "pending"
        journal.symlink_to(tmp_path / "missing-journal-directory" / "journal")
        assert _search(owner, "MAPLE-NEW-942")["results"] == []
        failed = _wait_settled(owner)
        assert failed["dirty"] and failed["jobs"][-1]["state"] == "failed"
        assert owner.store.status()["lastSyncError"] == "unable to open database file"
        assert owner.store.read_published_index() == before

        stale = _search(owner, "MAPLE-NEW-942")
        assert stale["stale"] is True and "unable to open database file" in stale["warning"]
        assert stale["results"] == [] and "action" in stale
        _wait_settled(owner)
        journal.unlink()

        # A successful sessions-only publication does not certify changed memory.
        owner.store.reindex_sources(owner.kit.memory.workspace, sources={"sessions"})
        assert _memory(owner)["dirty"]
        assert owner.store.status()["lastSyncError"] == "unable to open database file"

        recovery_read = _search(owner, "MAPLE-NEW-942")
        assert recovery_read["results"] == [] and recovery_read["stale"] is True
        recovered = _wait_settled(owner)
        assert recovered["jobs"][-1]["state"] == "completed" and not recovered["dirty"]
        assert "lastSyncError" not in owner.store.status()
        current = _search(owner, "MAPLE-NEW-942")
        assert any(FRESH in hit["snippet"] for hit in current["results"])
        assert "stale" not in current
    finally:
        journal.unlink(missing_ok=True)
        owner.close()


def test_reader_stays_on_its_sql_generation_after_real_background_commit(tmp_path, monkeypatch):
    owner = _owner(tmp_path)
    try:
        _warm(owner)
        # WAL lets the real publisher commit while this search keeps its read
        # transaction. The old answer must therefore come from SQLite's pinned
        # generation, rather than merely winning a race against a delayed job.
        with owner.store.connect() as db:
            assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        before = owner.store.index_revision()
        _append(owner, FRESH)
        original = owner.store._on_search_snapshot
        read_revisions = []

        def let_publisher_commit(db):
            read_revisions.append(owner.store.index_revision(db=db))
            original(db)
            settled = _wait_settled(owner)
            assert settled["jobs"][-1]["state"] == "completed"
            assert owner.store.index_revision() > before
            assert owner.store.index_revision(db=db) == before
            assert any(FRESH in row["text"] for row in owner.store.read_published_index()["chunks"])

        monkeypatch.setattr(owner.store, "_on_search_snapshot", let_publisher_commit)
        assert _search(owner, "MAPLE-NEW-942")["results"] == []
        assert read_revisions == [before]
        monkeypatch.setattr(owner.store, "_on_search_snapshot", original)
        assert any(FRESH in hit["snippet"] for hit in _search(owner, "MAPLE-NEW-942")["results"])
    finally:
        owner.close()


def test_restoring_indexed_source_does_not_clear_a_real_failure_without_publication(tmp_path, monkeypatch):
    owner = _owner(tmp_path)
    journal = Path(str(owner.store.path) + "-journal")
    release = None
    try:
        _warm(owner)
        source = owner.kit.memory.workspace.root / "MEMORY.md"
        original_bytes, original_stat = source.read_bytes(), source.stat()
        before = owner.store.read_published_index()
        _append(owner, FRESH)
        journal.symlink_to(tmp_path / "missing-journal-directory" / "journal")
        assert _search(owner, "MAPLE-NEW-942")["results"] == []
        failed = _wait_settled(owner)
        assert failed["jobs"][-1]["state"] == "failed"
        assert owner.store.status()["lastSyncError"] == "unable to open database file"

        journal.unlink()
        source.write_bytes(original_bytes)
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        assert owner.store.read_published_index() == before
        assert owner.store.status()["lastSyncError"] == "unable to open database file"
        entered, release = _hold_publisher(owner, monkeypatch)
        recovered_read = _search(owner, "CEDAR-OLD-731")
        assert recovered_read["results"] and recovered_read["stale"] is True
        assert entered.wait(5)
        assert owner.store.status()["lastSyncError"] == "unable to open database file"
        release.set()
        recovered = _wait_settled(owner)
        assert recovered["jobCount"] == failed["jobCount"] + 1
        assert recovered["jobs"][-1]["state"] == "completed"
        assert not recovered["dirty"]
        assert "lastSyncError" not in owner.store.status()
        assert source.read_bytes() == original_bytes
    finally:
        if release is not None:
            release.set()
        journal.unlink(missing_ok=True)
        owner.close()


def test_close_joins_a_publisher_admitted_before_its_worker_enters(tmp_path, monkeypatch):
    owner = _owner(tmp_path)
    release = None
    try:
        _warm(owner)
        _append(owner, FRESH)
        entered, release = _hold_publisher(owner, monkeypatch)
        assert _search(owner, "MAPLE-NEW-942")["results"] == []
        assert entered.wait(5)
        with ThreadPoolExecutor(max_workers=1) as executor:
            closing = executor.submit(owner.close)
            try:
                with owner.store._condition:
                    assert owner.store._condition.wait_for(lambda: owner.store._closing, timeout=5)
                assert not closing.done() and not owner.store.closed
                with pytest.raises(RuntimeError, match="closed"):
                    owner.store.search("MAPLE-NEW-942")
                # HostKit reports the same refusal through its real tool
                # envelope rather than leaking the store's Python exception.
                refused = _search(owner, "MAPLE-NEW-942")
                assert "closed" in refused["error"] and refused.get("results", []) == []
            finally:
                release.set()
            closing.result(timeout=5)
        assert owner.store.closed and owner.publication_status()["closed"]
        assert not _memory(owner)["active"]
        assert _memory(owner)["jobs"][-1]["state"] == "completed"
        assert any(FRESH in row["text"] for row in owner.store.read_published_index()["chunks"])
    finally:
        if release is not None:
            release.set()
        owner.close()


def test_newer_committed_write_is_retained_while_an_admitted_publication_is_queued(tmp_path, monkeypatch):
    owner = _owner(tmp_path)
    release = None
    newer = "My newer bicycle preference is BIRCH-LATEST-395."
    try:
        _warm(owner)
        _append(owner, FRESH)
        entered, release = _hold_publisher(owner, monkeypatch)
        assert _search(owner, "MAPLE-NEW-942")["results"] == []
        assert entered.wait(5)
        assert _append(owner, newer)["indexStatus"] == "pending"
        assert _memory(owner)["dirty"] and _memory(owner)["active"]
        assert all(newer not in row["text"] for row in owner.store.read_published_index()["chunks"])
        release.set()
        settled = _wait_settled(owner)
        assert not settled["dirty"]
        rows = owner.store.read_published_index()["chunks"]
        assert any(FRESH in row["text"] for row in rows)
        assert any(newer in row["text"] for row in rows)
    finally:
        if release is not None:
            release.set()
        owner.close()


@pytest.mark.parametrize("operation", ["reindex", "synchronize"])
def test_explicit_managed_publication_still_publishes_real_memory(tmp_path, operation):
    owner = _owner(tmp_path)
    try:
        _warm(owner)
        before = owner.store.index_revision()
        _append(owner, FRESH)
        assert _memory(owner)["dirty"] and _memory(owner)["jobCount"] == 0
        result = getattr(owner, operation)()
        if operation == "synchronize":
            assert result["memoryIndexStatus"] == "ready"
        assert owner.store.index_revision() > before
        assert not _memory(owner)["dirty"]
        assert any(FRESH in row["text"] for row in owner.store.read_published_index()["chunks"])
        assert _memory(owner)["jobCount"] == 0
    finally:
        owner.close()


def test_older_failed_worker_cannot_resurrect_error_after_real_matching_recovery(tmp_path, monkeypatch):
    owner = _owner(tmp_path)
    journal = Path(str(owner.store.path) + "-journal")
    finished, release = threading.Event(), threading.Event()
    original_operation = owner.store._operation

    @contextmanager
    def hold_failed_worker_settlement(name):
        try:
            with original_operation(name) as operation:
                yield operation
        finally:
            if name == "memory-background-publication":
                # The real publication and its workspace guard have settled.
                # Keep only this worker's final historical receipt outstanding.
                finished.set()
                assert release.wait(5), "The test must release the failed worker's final settlement"

    try:
        _warm(owner)
        _append(owner, FRESH)
        journal.symlink_to(tmp_path / "missing-journal-directory" / "journal")
        monkeypatch.setattr(owner.store, "_operation", hold_failed_worker_settlement)
        assert _search(owner, "MAPLE-NEW-942")["results"] == []
        assert finished.wait(5)
        assert _memory(owner)["active"]
        assert owner.store.status()["lastSyncError"] == "unable to open database file"

        journal.unlink()
        owner.store.reindex_sources(owner.kit.memory.workspace, sources={"memory"})
        assert not _memory(owner)["dirty"]
        assert "lastSyncError" not in owner.store.status()
        assert any(FRESH in row["text"] for row in owner.store.read_published_index()["chunks"])

        release.set()
        settled = _wait_settled(owner)
        assert settled["jobs"][-1]["state"] == "failed"
        assert settled["jobs"][-1]["error"]["message"] == "unable to open database file"
        assert settled["lastError"] is None and not settled["dirty"]
        assert "lastSyncError" not in owner.store.status()
        assert "memoryScopeSyncFailure" not in owner.store.lifecycle_snapshot()
        assert owner.publication_status()["ready"] is True
    finally:
        journal.unlink(missing_ok=True)
        release.set()
        owner.close()


def test_real_executor_admission_failure_needs_actual_complete_memory_publication(tmp_path):
    owner = _owner(tmp_path)
    try:
        _warm(owner)
        before = owner.store.read_published_index()
        _append(owner, FRESH)
        executor = ThreadPoolExecutor(max_workers=1)
        executor.shutdown(wait=True)
        owner.store._memory_executor = executor

        # This real closed executor refuses submission before any publication.
        assert _search(owner, "MAPLE-NEW-942")["results"] == []
        failed = _memory(owner)
        assert failed["jobs"][-1]["state"] == "failed" and not failed["active"]
        assert "shutdown" in failed["lastError"]
        assert "memoryScopeSyncFailure" not in owner.store.lifecycle_snapshot()
        assert owner.store.read_published_index() == before
        retained_error = owner.store.status()["lastSyncError"]
        assert retained_error == failed["lastError"]

        owner.store.reindex_sources(owner.kit.memory.workspace, sources={"sessions"})
        owner.store.reindex_sources(owner.kit.memory.workspace, sources={"memory"}, paths=())
        assert owner.store.status()["lastSyncError"] == retained_error
        assert _memory(owner)["dirty"]
        assert owner.publication_status()["ready"] is False

        owner.store.reindex_sources(owner.kit.memory.workspace, sources={"memory"})
        assert "lastSyncError" not in owner.store.status()
        assert _memory(owner)["lastError"] is None and not _memory(owner)["dirty"]
        assert any(FRESH in row["text"] for row in owner.store.read_published_index()["chunks"])
        assert owner.publication_status()["ready"] is True
    finally:
        owner.close()
