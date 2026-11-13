"""Same-owner cold bootstrap recovery through real public tools and SQLite faults."""
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3

import pytest

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.index.identity import MEMORY_INDEX_META_KEY
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.tools.memory_search import MemorySearchToolContext
from memory_core.tools.search_factory import create_memory_search_tool
from memory_core.workspace import MemoryWorkspace


NOW = 1_794_268_800_000
TEXT = "# Preference\n\nThe saved preference marker is coldhazel382.\n"


@contextmanager
def _owner(tmp_path, *, publication="on-search", source=True):
    root = tmp_path / "workspace"
    root.mkdir()
    if source:
        note = root / "memory/topics/preference.md"
        note.parent.mkdir(parents=True)
        note.write_text(TEXT, encoding="utf8")
        os.utime(note, ns=(NOW * 1_000_000,) * 2)
    config = MemoryConfig(root, store_path=tmp_path / "index.sqlite", session_search=False,
        citation_mode="off", flags=FeatureFlags(vector_search=False, temporal_decay=False))
    workspace = MemoryWorkspace(root, index_sources=["memory"])
    options = {} if publication is None else {"memory_publication": publication}
    store = ManagedSQLiteMemoryStore(config, workspace,
        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY, **options)
    tool = create_memory_search_tool(config, store, context=MemorySearchToolContext(clock=lambda: NOW),
                                     runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    journal = Path(str(store.path) + "-journal")
    try:
        yield workspace, store, tool, journal
    finally:
        if journal.is_symlink():
            journal.unlink()
        store.close()


def _query(tool):
    envelope = tool.execute("actual-query", {"query": "coldhazel382", "corpus": "memory", "minScore": 0})
    assert json.loads(envelope["content"][0]["text"]) == envelope["details"]
    return envelope["details"]


def _refuse_journal(journal):
    assert not journal.exists() and not journal.is_symlink()
    target = journal.parent / "actual-missing-journal-parent" / "journal"
    assert not target.parent.exists()
    journal.symlink_to(target)
    with pytest.raises(FileNotFoundError):
        journal.stat()


def _whole_attempts(store):
    return [row for row in store.lifecycle_snapshot()["operations"] if row["name"] == "reindex"]


def test_same_public_tool_and_owner_retry_cold_bootstrap_after_real_fault_removal(tmp_path):
    with _owner(tmp_path) as (workspace, store, tool, journal):
        source = workspace.root / "memory/topics/preference.md"
        before_source = source.stat()
        before_index = store.read_published_index()
        _refuse_journal(journal)

        failed = _query(tool)

        assert failed["unavailable"] is True and failed["results"] == []
        assert failed["error"] == "unable to open database file"
        assert store.read_published_index() == before_index
        first = store.lifecycle_snapshot()
        assert [row["state"] for row in first["repairs"]] == ["failed"]
        journal.unlink()

        recovered = _query(tool)

        assert tool._store is store and store._workspace is workspace and not store.closed
        assert recovered["results"][0]["snippet"] == TEXT
        assert "unavailable" not in recovered
        assert "lastSyncError" not in store.status()
        lifecycle = store.lifecycle_snapshot()
        assert [row["state"] for row in lifecycle["repairs"]] == ["failed", "completed"]
        assert [row["reason"] for row in lifecycle["repairs"]] == ["search-bootstrap"] * 2
        attempts = _whole_attempts(store)
        assert [row["state"] for row in attempts] == ["failed", "completed"]
        assert [row["parentOperationId"] for row in attempts] == [
            row["searchOperationId"] for row in lifecycle["repairs"]]
        assert lifecycle["memoryPublication"]["jobCount"] == 0
        assert source.read_bytes() == TEXT.encode()
        assert (source.stat().st_ino, source.stat().st_mtime_ns) == (
            before_source.st_ino, before_source.st_mtime_ns)
        published = store.read_published_index()
        assert _query(tool)["results"] == recovered["results"]
        assert store.read_published_index() == published
        assert len(_whole_attempts(store)) == 2


def test_persistent_real_refusal_attempts_once_per_query_without_partial_publication(tmp_path):
    with _owner(tmp_path) as (_, store, tool, journal):
        before = store.read_published_index()
        _refuse_journal(journal)
        fault_inode = journal.lstat().st_ino

        for attempts in range(1, 4):
            actual = _query(tool)
            assert actual["results"] == [] and actual["unavailable"] is True
            assert actual["error"] == "unable to open database file"
            assert store.read_published_index() == before
            lifecycle = store.lifecycle_snapshot()
            assert len(lifecycle["repairs"]) == len(_whole_attempts(store)) == attempts
            assert all(row["state"] == "failed" for row in lifecycle["repairs"])
            assert lifecycle["memoryPublication"]["jobCount"] == 0
            assert lifecycle["automaticRebuildNotice"]["sequence"] == 0
            assert journal.lstat().st_ino == fault_inode
        assert store.status()["lastSyncError"] == "unable to open database file"


def test_clean_repeated_queries_publish_once_and_do_not_replay_repair_notice(tmp_path):
    with _owner(tmp_path) as (_, store, tool, _):
        first = _query(tool)
        published = store.read_published_index()
        second = _query(tool)

        assert first["results"] == second["results"]
        assert first["results"][0]["snippet"] == TEXT
        assert "Automatic memory index repair was requested." in first["warning"]
        assert "warning" not in second
        assert store.read_published_index() == published
        assert [row["state"] for row in _whole_attempts(store)] == ["completed"]
        assert len(store.lifecycle_snapshot()["repairs"]) == 1


def test_default_on_write_policy_keeps_explicit_recovery_after_fault_removal(tmp_path):
    with _owner(tmp_path, publication=None) as (workspace, store, tool, journal):
        _refuse_journal(journal)
        assert _query(tool)["unavailable"] is True
        before = store.read_published_index()
        journal.unlink()

        actual = _query(tool)

        assert actual["unavailable"] is True and actual["results"] == []
        assert store.read_published_index() == before
        assert len(_whole_attempts(store)) == 1
        assert store.status()["lastSyncError"] == "unable to open database file"
        assert store.reindex(workspace, force=True) == 1
        assert "lastSyncError" not in store.status()
        assert _query(tool)["results"][0]["snippet"] == TEXT


def test_warm_on_search_whole_failure_still_requires_explicit_recovery(tmp_path):
    with _owner(tmp_path) as (workspace, store, tool, journal):
        saved = _query(tool)
        before = store.read_published_index()
        _refuse_journal(journal)
        with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
            store.reindex(workspace, force=True)
        journal.unlink()

        actual = _query(tool)

        assert actual["results"] == saved["results"] and actual["stale"] is True
        assert store.read_published_index() == before
        assert len(_whole_attempts(store)) == 2
        assert len(store.lifecycle_snapshot()["repairs"]) == 1
        assert store.status()["lastSyncError"] == "unable to open database file"
        store.reindex(workspace, force=True)
        assert "stale" not in _query(tool) and "lastSyncError" not in store.status()


@pytest.mark.parametrize("identity", ["newer", "configuration"])
def test_cold_retry_does_not_bypass_empty_index_identity_restrictions(tmp_path, identity):
    with _owner(tmp_path, source=False) as (workspace, store, tool, journal):
        assert _query(tool)["results"] == []
        metadata = store.read_index_meta()
        if identity == "newer":
            metadata["chunkingVersion"] += 1
        else:
            metadata["providerKey"] = "actual-different-configuration"
        with closing(store.connect()) as db, db:
            db.execute("UPDATE memory_index_meta SET value=? WHERE key=?",
                       (json.dumps(metadata), MEMORY_INDEX_META_KEY))
        _refuse_journal(journal)
        with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
            store.reindex(workspace, force=True)
        journal.unlink()
        before = store.read_published_index()
        repairs = store.lifecycle_snapshot()["repairs"]

        actual = _query(tool)

        assert actual["unavailable"] is True and actual["results"] == []
        assert store.read_published_index() == before
        assert store.read_index_meta() == metadata
        # The automatic request still runs, but its identity guard refuses to publish.
        updated = store.lifecycle_snapshot()["repairs"]
        assert len(updated) == len(repairs) + 1
        assert updated[:-1] == repairs
        refused = updated[-1]
        assert refused["reason"] == "search-bootstrap"
        assert refused["state"] == "completed" and refused["returned"] == 0
        assert refused["automaticRefusal"] == refused["after"]["identity"]
        assert refused["noticeSequenceAfter"] == refused["noticeSequenceBefore"]
        attempts = _whole_attempts(store)
        assert len(attempts) == 3
        assert attempts[-1]["state"] == "completed" and attempts[-1]["returned"] == 0
        assert attempts[-1]["revisionBefore"] == attempts[-1]["revisionAfter"] == before["revision"]
