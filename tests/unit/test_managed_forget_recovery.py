"""Durable forget invalidation survives a real owner/process restart."""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys

from memory_core.config import MemoryConfig
from memory_core.consolidation.forget import forget_memory_entries
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger
from memory_core.flags import FeatureFlags
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.index.identity import INDEX_SYNC_TABLE, MEMORY_INDEX_META_KEY
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY
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


def test_fresh_process_natural_query_repairs_real_forget_without_a_scoped_failure(tmp_path):
    config = _invalidated(tmp_path)
    source = """
import json,sys
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
try:
    result=query('retainedcedar731')
    absent=query('forgottenwillow942')
    with store.connect() as db:
        needs_rebuild=bool(db.execute(f'SELECT needs_rebuild FROM {INDEX_SYNC_TABLE} WHERE id=1').fetchone()[0])
    print(json.dumps({'result':result,'absent':absent,'needsRebuild':needs_rebuild,
                      'lifecycle':store.lifecycle_snapshot()}))
finally:
    store.close()
"""
    project = Path(__file__).resolve().parents[2]
    process = subprocess.run([sys.executable, "-c", source, str(config.workspace_dir), str(config.store_path)],
        cwd=project, env={**os.environ, "PYTHONPATH": str(project)}, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    assert process.returncode == 0, process.stderr
    actual = json.loads(process.stdout)
    assert {hit["path"] for hit in actual["result"]["results"]} == {
        "MEMORY.md", "memory/topics/retained.md"}
    assert actual["absent"]["results"] == []
    assert not actual["needsRebuild"]
    assert "stale" not in actual["result"] and "action" not in actual["result"]
    assert "warning" not in actual["result"]
    assert actual["lifecycle"]["repairs"][0]["reason"] == "search-invalidated"
    assert actual["lifecycle"]["repairs"][0]["state"] == "completed"
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
        assert actual["stale"] is True and "unable to open database file" in actual["warning"]
        assert _needs_rebuild(store)
        assert store.status()["lastSyncError"] == "unable to open database file"
        assert store.lifecycle_snapshot()["repairs"][0]["state"] == "failed"
        with store._condition:
            assert store._condition.wait_for(lambda: not store._memory_active, timeout=5)
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
