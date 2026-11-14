"""A forget purges the generation that actually won publication while it waited."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import multiprocessing
from pathlib import Path
import sqlite3
import threading

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation import forget
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger
from memory_core.flags import FeatureFlags
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.index.identity import INDEX_SYNC_TABLE
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.session_catalog import MemorySessionCatalog
from memory_core.workspace import MemoryWorkspace


def _owner(root, index, origins, catalog_path, *, managed):
    ledger = MemoryEntryOriginLedger(lambda _agent: Path(origins))
    catalog = MemorySessionCatalog(Path(catalog_path))
    workspace = MemoryWorkspace(Path(root), session_catalog=catalog, index_sources=["memory", "sessions"],
        is_session_forgotten=lambda session: bool(ledger.list_session_tombstones("main", [session])))
    config = MemoryConfig(Path(root), store_path=Path(index),
                          flags=FeatureFlags(vector_search=False, temporal_decay=False))
    store = (ManagedSQLiteMemoryStore(config, workspace, memory_publication="on-search",
                                     revision_fence=ledger.revision_fence("main"))
             if managed else SQLiteMemoryStore(config, None, revision_fence=ledger.revision_fence("main")))
    return store, workspace, ledger, catalog


def _publish_checked_generation(root, index, origins, catalog_path, connection):
    store, workspace, _ledger, _catalog = _owner(root, index, origins, catalog_path, managed=True)
    original = store.publish_prepared_index

    def publish_with_actual_writer_held(prepared, expected_revision, **options):
        owner_check = options["owner_check"]

        def hold_after_actual_checks(db):
            owner_check(db)
            connection.send({"phase": "writer-held", "transaction": db.in_transaction,
                             "preparedChunks": sum(len(source.chunks) for source in prepared.sources),
                             "preparedIds": [chunk.id for source in prepared.sources for chunk in source.chunks]})
            if not connection.poll(10) or connection.recv() != "release":
                raise RuntimeError("The actual publisher was never released")

        return original(prepared, expected_revision, **{**options, "owner_check": hold_after_actual_checks})

    store.publish_prepared_index = publish_with_actual_writer_held
    try:
        result = store.reindex(workspace, force=True)
        connection.send({"phase": "committed", "returned": result, "published": store.read_published_index()})
    except BaseException as error:
        connection.send({"phase": "failed", "name": type(error).__name__, "message": str(error)})
        raise
    finally:
        store.close()
        connection.close()


def _receive(connection):
    assert connection.poll(5), "The genuine producer did not report its actual phase"
    return connection.recv()


def _seed(tmp_path, *, split):
    root, index, catalog_path = tmp_path / "workspace", tmp_path / "index.sqlite", tmp_path / "catalog.sqlite"
    origins = tmp_path / "origins.sqlite" if split else index
    (root / "memory").mkdir(parents=True)
    (root / "MEMORY.md").write_text("# Personal notes\n\nKeep the independent keepcedar964 note.\n", encoding="utf8")
    (root / "memory/selected.md").write_text(
        "# Selected source\n\nSession ID: forgotten\n- A durable forgetmaple742 preference.\n", encoding="utf8")
    (root / "memory/retained.md").write_text("# Retained source\n\n- A durable keeppine853 preference.\n", encoding="utf8")
    store, workspace, ledger, catalog = _owner(root, index, origins, catalog_path, managed=False)
    for session, text in (("forgotten", "A durable forgetmaple742 preference."),
                          ("retained", "A durable keeppine853 preference.")):
        key = f"agent:main:dm:{session}"
        catalog.upsert_session(key, {"sessionId": session})
        catalog.append_message(session, {"role": "user", "content": text}, session_key=key,
                               event_id=f"{session}-message", now_ms=123)
    assert store.reindex(workspace, force=True) == 5
    assert store.count_chunks() == 5
    with closing(store.connect()) as db:
        db.execute("PRAGMA journal_mode=WAL")
    ledger.record("main", [MemoryEntryOrigin("chosen", "main", "forgotten",
                  "agent:main:dm:forgotten", "owner", 123)])
    with (root / "MEMORY.md").open("a", encoding="utf8") as file:
        file.write("\n## Promoted From Short-Term Memory (2026-11-14)\n\n"
                   "<!-- memory-core-memory-promotion:chosen -->\n"
                   "- A durable forgetmaple742 preference.\n")
    return store, workspace, ledger, catalog, origins, catalog_path


@pytest.mark.parametrize("split", [False, True])
@pytest.mark.parametrize("fail_purge", [False, True])
def test_forget_replans_after_actual_publisher_commit_and_preserves_marker_retry(
    tmp_path, monkeypatch, split, fail_purge,
):
    store, workspace, ledger, catalog, origins, catalog_path = _seed(tmp_path, split=split)
    old_snapshot = store.read_published_index()
    if fail_purge:
        with closing(store.connect()) as db:
            db.execute("CREATE TRIGGER reject_current_purge BEFORE DELETE ON chunks "
                       f"WHEN (SELECT revision FROM {INDEX_SYNC_TABLE} WHERE id=1) "
                       f">= {store.index_revision() + 1} "
                       "BEGIN SELECT RAISE(ABORT, 'actual current purge failed'); END")
            db.commit()
    parent, child = multiprocessing.get_context("spawn").Pipe()
    process = multiprocessing.get_context("spawn").Process(target=_publish_checked_generation,
        args=(workspace.root, store.path, origins, catalog_path, child))
    planned, marker_attempted = threading.Event(), threading.Event()
    plans = []
    original_plan, original_open = forget.plan_memory_index, ledger._open_write

    def observe_actual_plan(*args, **options):
        plan = original_plan(*args, **options)
        db = options.get("db")
        plans.append({"chunks": list(plan.chunks), "fts": plan.fts_rows,
                      "writerOwned": db.in_transaction if db is not None else False})
        if db is None:
            planned.set()
        return plan

    def attempt_marker(agent):
        marker_attempted.set()
        return original_open(agent)

    monkeypatch.setattr(forget, "plan_memory_index", observe_actual_plan)
    monkeypatch.setattr(ledger, "_open_write", attempt_marker)
    process.start()
    child.close()
    released = False
    try:
        held = _receive(parent)
        assert held["phase"] == "writer-held" and held["transaction"] is True
        assert held["preparedChunks"] == len(held["preparedIds"]) == 7
        new_ids = set(held["preparedIds"]) - {chunk["id"] for chunk in old_snapshot["chunks"]}
        assert len(new_ids) == 2
        with ThreadPoolExecutor(max_workers=1) as executor:
            operation = executor.submit(forget.forget_memory_entries, config=store.config, agent_id="main",
                                        origins=ledger, session_ids=["forgotten"], store=store, now_ms=1234)
            try:
                assert planned.wait(5) and marker_attempted.wait(5)
                assert len(plans) == 1 and len(plans[0]["chunks"]) == plans[0]["fts"] == 3
                assert not plans[0]["writerOwned"]
                assert not operation.done()
                assert store.read_published_index() == old_snapshot
            finally:
                parent.send("release")
                released = True
            committed = _receive(parent)
            assert committed["phase"] == "committed"
            if fail_purge:
                assert len(committed["published"]["chunks"]) == 7
                with pytest.raises(sqlite3.DatabaseError, match="actual current purge failed"):
                    operation.result(timeout=5)
                assert store.read_published_index() == committed["published"]
                marked = ledger.list_session_tombstones("main")
                assert len(marked) == 1 and marked[0].session_id == "forgotten"
                assert "forgetmaple742" in (workspace.root / "MEMORY.md").read_text(encoding="utf8")
                assert ledger.list("main")
                with closing(store.connect()) as db:
                    db.execute("DROP TRIGGER reject_current_purge")
                    db.commit()
                report = forget.forget_memory_entries(config=store.config, agent_id="main", origins=ledger,
                    session_ids=["forgotten"], store=store, now_ms=9999)
                assert ledger.list_session_tombstones("main") == marked
            else:
                report = operation.result(timeout=5)
        assert report.artifacts["indexChunks"] == report.artifacts["ftsRows"] == 5
        assert any(plan["writerOwned"] and len(plan["chunks"]) == plan["fts"] == 5
                   and new_ids <= {chunk[0] for chunk in plan["chunks"]} for plan in plans)
        assert store.count_chunks() == 2
        assert store.search("forgetmaple742", min_score=0) == []
        assert store.search("keeppine853", min_score=0)
        assert not ledger.list("main")
        assert catalog.snapshot().forgotten_session_ids == frozenset()
    finally:
        if process.is_alive() and not released:
            parent.send("release")
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
        parent.close()
    assert process.exitcode == 0
