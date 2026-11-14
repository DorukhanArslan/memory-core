"""Durable forget invalidation survives a real owner/process restart."""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.forget import forget_memory_entries
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger
from memory_core.flags import FeatureFlags
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.index.identity import INDEX_SYNC_TABLE, MEMORY_INDEX_META_KEY
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.tools.memory_search import MemorySearchToolContext
from memory_core.tools.search_factory import create_memory_search_tool
from memory_core.workspace import MemoryWorkspace


NOW = 1_794_614_400_000
RETAINED = "The retained preference is retainedcedar731 tea."
FORGOTTEN = "The forgotten preference is forgottenwillow942 sugar."


def _config(root, index):
    return MemoryConfig(root, store_path=index, citation_mode="off", session_search=False,
        flags=FeatureFlags(vector_search=False, temporal_decay=False))


def _open(config, *, publication="on-search"):
    workspace = MemoryWorkspace(config.workspace_dir, index_sources=["memory"])
    return ManagedSQLiteMemoryStore(config, workspace, memory_publication=publication,
        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY), workspace


def _query(store, query="retainedcedar731"):
    tool = create_memory_search_tool(store.config, store,
        context=MemorySearchToolContext(clock=lambda: NOW),
        runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
    envelope = tool.execute("actual-search", {"query": query, "corpus": "memory", "minScore": 0})
    assert json.loads(envelope["content"][0]["text"]) == envelope["details"]
    return envelope["details"]


def _invalidated(tmp_path):
    root = tmp_path / "workspace"
    (root / "memory/topics").mkdir(parents=True)
    (root / "memory/topics/retained.md").write_text(RETAINED + "\n")
    (root / "MEMORY.md").write_text(
        "# Memory\n\n<!-- openclaw-memory-promotion:forgotten -->\n- " + FORGOTTEN
        + "\n<!-- openclaw-memory-promotion:retained -->\n- " + RETAINED + "\n")
    config = _config(root, tmp_path / "index.sqlite")
    ledger = MemoryEntryOriginLedger(lambda _agent: tmp_path / "origins.sqlite")
    ledger.record("main", [MemoryEntryOrigin("forgotten", "main", "selected-session",
        "agent:main:selected-session", "owner", NOW)])
    store, workspace = _open(config)
    try:
        store.reindex(workspace)
        assert len(_query(store)["results"]) == 2
        report = forget_memory_entries(config=config, agent_id="main", origins=ledger,
            session_ids=["selected-session"], store=store, now_ms=NOW)
        assert report.entry_keys == ["forgotten"]
        assert FORGOTTEN not in (root / "MEMORY.md").read_text()
        assert RETAINED in (root / "MEMORY.md").read_text()
        assert store.count_chunks() > 0
        assert _needs_rebuild(store)
    finally:
        store.close()
    return config


def _needs_rebuild(store):
    with closing(store.connect()) as db:
        return bool(db.execute(f"SELECT needs_rebuild FROM {INDEX_SYNC_TABLE} WHERE id=1").fetchone()[0])


def test_fresh_process_query_pins_the_purged_generation_before_its_full_background_rebuild(tmp_path):
    config = _invalidated(tmp_path)
    source = """
import json,sys,threading
from pathlib import Path
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.index.identity import INDEX_SYNC_TABLE
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.tools.memory_search import MemorySearchToolContext
from memory_core.tools.search_factory import create_memory_search_tool
from memory_core.workspace import MemoryWorkspace
config=MemoryConfig(Path(sys.argv[1]),store_path=Path(sys.argv[2]),citation_mode='off',
    session_search=False,flags=FeatureFlags(vector_search=False,temporal_decay=False))
workspace=MemoryWorkspace(config.workspace_dir,index_sources=['memory'])
store=ManagedSQLiteMemoryStore(config,workspace,memory_publication='on-search',
    runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
tool=create_memory_search_tool(config,store,context=MemorySearchToolContext(clock=lambda:1794614400000),
    runtime_identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)
def query(text):
    return tool.execute('actual-search',{'query':text,'corpus':'memory','minScore':0})['details']
entered,release=threading.Event(),threading.Event()
original=store._run_memory_publication
def held(*args):
    entered.set()
    assert release.wait(5)
    return original(*args)
store._run_memory_publication=held
try:
    result=query('retainedcedar731')
    assert entered.wait(5)
    pending=store.read_published_index()
    pending_lifecycle=store.lifecycle_snapshot()
    release.set()
    with store._condition:
        assert store._condition.wait_for(lambda:not store._memory_active,timeout=5)
    current=query('retainedcedar731')
    absent=query('forgottenwillow942')
    with store.connect() as db:
        needs_rebuild=bool(db.execute(f'SELECT needs_rebuild FROM {INDEX_SYNC_TABLE} WHERE id=1').fetchone()[0])
    print(json.dumps({'result':result,'current':current,'absent':absent,'needsRebuild':needs_rebuild,
                      'pending':pending,'pendingLifecycle':pending_lifecycle,
                      'lifecycle':store.lifecycle_snapshot()}))
finally:
    release.set()
    store.close()
"""
    project = Path(__file__).resolve().parents[2]
    process = subprocess.run([sys.executable, "-c", source, str(config.workspace_dir), str(config.store_path)],
        cwd=project, env={**os.environ, "PYTHONPATH": str(project)}, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    assert process.returncode == 0, process.stderr
    actual = json.loads(process.stdout)
    assert [hit["path"] for hit in actual["result"]["results"]] == ["memory/topics/retained.md"]
    assert {hit["path"] for hit in actual["current"]["results"]} == {
        "MEMORY.md", "memory/topics/retained.md"}
    assert [row["path"] for row in actual["pending"]["chunks"]] == ["memory/topics/retained.md"]
    assert actual["pendingLifecycle"]["memoryPublication"]["jobs"][-1]["fullRebuild"] is True
    assert actual["absent"]["results"] == []
    assert not actual["needsRebuild"]
    assert "stale" not in actual["result"] and "action" not in actual["result"]
    assert "warning" not in actual["result"]
    assert actual["lifecycle"]["repairs"] == []
    assert all(job["state"] == "completed"
               for job in actual["lifecycle"]["memoryPublication"]["jobs"])


def test_on_write_owner_keeps_explicit_recovery_for_a_populated_invalidated_index(tmp_path):
    config = _invalidated(tmp_path)
    store, workspace = _open(config, publication="on-write")
    try:
        result = _query(store)
        assert [hit["path"] for hit in result["results"]] == ["memory/topics/retained.md"]
        assert _needs_rebuild(store) and store.lifecycle_snapshot()["repairs"] == []
        store.reindex(workspace)
        assert not _needs_rebuild(store)
        assert len(_query(store)["results"]) == 2
    finally:
        store.close()


def test_only_the_actual_fresh_publication_restores_rows_while_old_query_job_is_held(tmp_path, monkeypatch):
    config = _invalidated(tmp_path)
    old, _old_workspace = _open(config)
    entered, release = threading.Event(), threading.Event()
    original = old._run_memory_publication

    def held(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(old, "_run_memory_publication", held)
    fresh = None
    try:
        purged = old.read_published_index()
        result = _query(old)
        assert entered.wait(5)
        assert [hit["path"] for hit in result["results"]] == ["memory/topics/retained.md"]
        assert old.read_published_index() == purged and _needs_rebuild(old)
        assert old.lifecycle_snapshot()["repairs"] == []

        fresh, fresh_workspace = _open(config)
        assert fresh.reindex(fresh_workspace) == 2
        assert {row["path"] for row in fresh.read_published_index()["chunks"]} == {
            "MEMORY.md", "memory/topics/retained.md"}
        assert not _needs_rebuild(fresh)
        release.set()
        with old._condition:
            assert old._condition.wait_for(lambda: not old._memory_active, timeout=5)
        assert len(_query(old)["results"]) == 2
        assert "lastSyncError" not in old.status()
    finally:
        release.set()
        if fresh is not None:
            fresh.close()
        old.close()


def test_durable_invalidation_does_not_overwrite_a_newer_identity(tmp_path):
    config = _invalidated(tmp_path)
    store, _workspace = _open(config)
    try:
        metadata = store.read_index_meta()
        metadata["chunkingVersion"] += 1
        with closing(store.connect()) as db, db:
            db.execute("UPDATE memory_index_meta SET value=? WHERE key=?",
                       (json.dumps(metadata), MEMORY_INDEX_META_KEY))
        before = store.read_published_index()
        actual = _query(store)
        assert actual["unavailable"] is True and actual["results"] == []
        assert store.read_published_index() == before and _needs_rebuild(store)
        assert store.lifecycle_snapshot()["repairs"] == []
    finally:
        store.close()


def test_failed_real_recovery_keeps_durable_invalidation_and_actual_error(tmp_path):
    config = _invalidated(tmp_path)
    store, _workspace = _open(config)
    journal = Path(str(store.path) + "-journal")
    journal.symlink_to(tmp_path / "absent-parent" / "journal")
    try:
        actual = _query(store)
        assert [hit["path"] for hit in actual["results"]] == ["memory/topics/retained.md"]
        assert "stale" not in actual and "warning" not in actual
        with store._condition:
            assert store._condition.wait_for(lambda: not store._memory_active, timeout=5)
        assert _needs_rebuild(store)
        assert store.status()["lastSyncError"] == "unable to open database file"
        assert store.lifecycle_snapshot()["repairs"] == []
        assert store._full_retry_required is False  # the journal never opened
        failed = store.lifecycle_snapshot()["memoryPublication"]["jobs"][-1]
        assert failed["fullRebuild"] is True and not failed.get("fullRetry")
        journal.unlink()
        assert _query(store)["stale"] is True  # this query retains its admitted old generation
        with store._condition:
            assert store._condition.wait_for(lambda: not store._memory_active, timeout=5)
        assert not _needs_rebuild(store) and "lastSyncError" not in store.status()
        assert len(_query(store)["results"]) == 2
    finally:
        journal.unlink(missing_ok=True)
        store.close()


@pytest.mark.parametrize("publication,explicit_predicate,expected", [
    ("on-search", None, {"retained-session"}),
    ("on-search", False, {"selected-session", "retained-session"}),
    ("on-write", None, {"selected-session", "retained-session"}),
])
def test_managed_producer_reads_existing_owned_tombstones_without_catalog_mirroring(
    tmp_path, publication, explicit_predicate, expected,
):
    root = tmp_path / "workspace"
    root.mkdir()
    config = _config(root, tmp_path / "index.sqlite")
    catalog = MemorySessionCatalog(tmp_path / "separate-catalog.sqlite", clock_ms=lambda: NOW)
    for session_id in ("selected-session", "retained-session"):
        key = f"agent:main:{session_id}"
        catalog.upsert_session(key, {"sessionId": session_id, "updatedAt": NOW})
        catalog.append_message(session_id, {"role": "user", "content": f"Actual {session_id} transcript."},
            session_key=key, event_id=f"{session_id}:1", now_ms=NOW)
    callback = None if explicit_predicate is None else lambda _session_id: explicit_predicate
    workspace = MemoryWorkspace(root, session_catalog=catalog,
        is_session_forgotten=callback, index_sources=["memory", "sessions"])
    store = ManagedSQLiteMemoryStore(config, workspace, memory_publication=publication)
    ledger = MemoryEntryOriginLedger(lambda _agent: store.path)
    try:
        ledger.record_session_tombstones("main", ["selected-session"], created_at=NOW)
        ledger.record_session_tombstones("another-agent", ["retained-session"], created_at=NOW)
        assert catalog.snapshot().forgotten_session_ids == frozenset()
        admitted = workspace.discover_session_transcript_files()
        assert {Path(item.rel_path).stem for item in admitted} == expected
        assert catalog.read_transcript("selected-session", session_key="agent:main:selected-session") is not None
        assert catalog.snapshot().forgotten_session_ids == frozenset()
        store.reindex(workspace)
        published = store.read_published_index()["chunks"]
        assert len(published) == len(expected)
        assert all(any(session_id in row["text"] for row in published) for session_id in expected)
        if callback is not None:
            assert workspace.is_session_forgotten is callback
        if publication == "on-write":
            assert workspace.is_session_forgotten is None
    finally:
        store.close()


def test_default_managed_admission_does_not_create_an_origins_table(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    store, workspace = _open(_config(root, tmp_path / "index.sqlite"))
    try:
        with closing(store.connect()) as db:
            before = db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
        assert workspace.is_session_forgotten("unknown-session") is False
        assert workspace.discover_session_transcript_files() == []
        with closing(store.connect()) as db:
            assert db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall() == before
        assert not any(name == "memory_session_tombstones" for name, _sql in before)
    finally:
        store.close()
