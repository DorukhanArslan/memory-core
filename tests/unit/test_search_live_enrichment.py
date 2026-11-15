"""Real publication interleavings during keyword retrieval and enrichment."""
from contextlib import closing
import sqlite3
import threading
import time

from memory_core.config import MemoryConfig
from memory_core.consolidation.forget import forget_memory_entries
from memory_core.consolidation.origins import MemoryEntryOrigin, MemoryEntryOriginLedger
from memory_core.consolidation.store import read_recall_store, recall_store_path
from memory_core.flags import FeatureFlags
from memory_core.index.sqlite_store import SQLiteMemoryStore, _source_filter_clause
from memory_core.tools.memory_search import MemorySearchToolContext
from memory_core.tools.search_factory import create_memory_search_tool
from memory_core.workspace import MemoryWorkspace

NOW = 1794614400000
QUERY = "aurorafresh"


def _owners(tmp_path, *, retained_matches=False, wal=True):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    (root / "MEMORY.md").write_text(
        "# Notes\n\n<!-- memory-core-memory-promotion:chosen -->\n"
        f"- A durable {QUERY} preference.\n", encoding="utf8")
    (root / "memory/retained.md").write_text(
        f"- Independent {QUERY if retained_matches else 'retainedcontrol'} preference.\n", encoding="utf8")
    config = MemoryConfig(root, store_path=tmp_path / "index.sqlite", search_min_score=0,
        flags=FeatureFlags(vector_search=False, temporal_decay=False, mmr=False))
    ledger = MemoryEntryOriginLedger(lambda _agent: tmp_path / "origins.sqlite")
    ledger.record("main", [MemoryEntryOrigin("chosen", "main", "forgotten",
        "agent:main:direct:forgotten", "owner", NOW)])
    reader = SQLiteMemoryStore(config, None, revision_fence=ledger.revision_fence("main"))
    writer = SQLiteMemoryStore(config, None, revision_fence=ledger.revision_fence("main"))
    reader.reindex(MemoryWorkspace(root))
    with closing(reader.connect()) as db:
        mode = db.execute("PRAGMA journal_mode=WAL" if wal else "PRAGMA journal_mode").fetchone()[0]
        assert mode == ("wal" if wal else "delete")
    return reader, writer, ledger


def _forget(writer, ledger):
    report = forget_memory_entries(config=writer.config, agent_id="main", origins=ledger,
        session_ids=["forgotten"], store=writer, now_ms=NOW)
    assert report.artifacts["indexChunks"] >= 1
    assert ledger.list_session_tombstones("main", ["forgotten"])
    return report


def _hold_keyword(reader, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    retained = {"metadata": [], "metadataReaders": [], "admissions": 0}
    original = reader._search_keyword_with_fallback
    metadata = reader.read_recall_metadata
    admitted = reader._on_search_snapshot

    def keyword_return(db, *arguments, **options):
        hits = original(db, *arguments, **options)
        retained.update(db=db, ids=[hit.id for hit in hits])
        assert hits and db.in_transaction
        entered.set()
        assert release.wait(5), "The actual keyword return was not released"
        marks = ",".join("?" for _ in hits)
        retained["oldVisibleAfterCommit"] = {row[0] for row in db.execute(
            f"SELECT id FROM chunks WHERE id IN ({marks})", retained["ids"])}
        return hits

    def live_metadata(ids, *, db=None):
        retained["metadataReaders"].append({"sameConnection": db is retained["db"],
            "retrievalStillOpen": retained["db"].in_transaction, "metadataTransaction": db.in_transaction})
        actual = metadata(ids, db=db)
        retained["metadata"].append(set(actual))
        return actual

    def admission(db):
        retained["admissions"] += 1
        return admitted(db)

    monkeypatch.setattr(reader, "_search_keyword_with_fallback", keyword_return)
    monkeypatch.setattr(reader, "read_recall_metadata", live_metadata)
    monkeypatch.setattr(reader, "_on_search_snapshot", admission)
    return entered, release, retained


def _start(call):
    result = {}

    def run():
        try:
            result["returned"] = call()
        except BaseException as error:
            result["error"] = error

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    return worker, result


def test_committed_forget_drops_held_keyword_hits_from_whole_tool_result_and_recall(tmp_path, monkeypatch):
    reader, writer, ledger = _owners(tmp_path)
    events = []
    tool = create_memory_search_tool(reader.config, reader,
        context=MemorySearchToolContext(clock=lambda: NOW), agent_session_key="agent:main:direct:requester",
        recall_origins=ledger, on_event=events.append)
    assert tool is not None
    entered, release, held = _hold_keyword(reader, monkeypatch)
    worker, result = _start(lambda: tool.execute("held-search", {"query": QUERY, "minScore": 0}))
    try:
        assert entered.wait(5)
        _forget(writer, ledger)
        with closing(writer.connect()) as db:
            current = {row[0] for row in db.execute("SELECT id FROM chunks")}
        assert not current.intersection(held["ids"])
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and "error" not in result, result
    tool.wait_for_recalls(timeout=5)
    details = result["returned"]["details"]
    assert details["results"] == []
    assert details["debug"]["candidateHits"] == details["debug"]["hits"] == 0
    assert not details.get("error") and not details.get("disabled")
    assert held["oldVisibleAfterCommit"] == set(held["ids"])
    assert held["metadata"] == [set()] and held["admissions"] == 1
    assert held["metadataReaders"] == [{"sameConnection": False,
        "retrievalStillOpen": True, "metadataTransaction": True}]
    assert read_recall_store(recall_store_path(reader.config.workspace_dir), NOW)["entries"] == {}
    assert events == []


def test_fresh_enrichment_preserves_whole_retained_hit_without_repeating_fts_or_admission(tmp_path, monkeypatch):
    reader, writer, ledger = _owners(tmp_path, retained_matches=True)
    before = next(hit.to_payload() for hit in reader.search(QUERY, min_score=0)
                  if hit.path == "memory/retained.md")
    entered, release, held = _hold_keyword(reader, monkeypatch)
    worker, result = _start(lambda: reader.search(QUERY, min_score=0))
    try:
        assert entered.wait(5)
        assert len(held["ids"]) == 2
        _forget(writer, ledger)
        with closing(writer.connect()) as db:
            current = {row[0] for row in db.execute("SELECT id FROM chunks")}
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and "error" not in result, result
    assert [hit.to_payload() for hit in result["returned"]] == [before]
    assert held["oldVisibleAfterCommit"] == set(held["ids"])
    assert held["metadata"] == [current.intersection(held["ids"])]
    assert len(held["metadata"][0]) == 1 and held["admissions"] == 1
    assert held["metadataReaders"] == [{"sameConnection": False,
        "retrievalStillOpen": True, "metadataTransaction": True}]


def test_explicit_metadata_connection_keeps_its_caller_owned_snapshot_after_forget(tmp_path):
    reader, writer, ledger = _owners(tmp_path)
    with reader._search_connection(None) as db:
        candidates = reader._search_keyword_with_fallback(db, QUERY, 200, _source_filter_clause(None), None)
        assert candidates and db.in_transaction
        _forget(writer, ledger)
        assert reader.attach_recall_metadata(candidates, db=db)
        assert reader.attach_recall_metadata(candidates) == []
        assert db.in_transaction


def test_default_rollback_reader_finishes_while_publication_waits_to_commit(tmp_path, monkeypatch):
    reader, writer, _ = _owners(tmp_path, wal=False)
    path = reader.config.workspace_dir / "MEMORY.md"
    old_text = path.read_text()
    new_text = old_text.replace("durable", "replacement")
    original_keyword = reader._search_keyword_with_fallback
    original_written = writer._on_index_publication_write
    written = threading.Event()
    worker, outcome = None, {}

    def publication_written(*arguments, **options):
        returned = original_written(*arguments, **options)
        written.set()
        return returned

    def publish_after_keyword(db, *arguments, **options):
        nonlocal worker, outcome
        hits = original_keyword(db, *arguments, **options)
        assert hits and db.in_transaction
        path.write_text(new_text)
        worker, outcome = _start(lambda: writer.reindex(MemoryWorkspace(path.parent)))
        assert written.wait(2), "The real publisher did not reach its commit boundary"
        deadline = time.monotonic() + 2
        with closing(sqlite3.connect(reader.path, timeout=0)) as probe:
            while True:
                try:
                    with closing(probe.execute("SELECT id FROM chunks LIMIT 1")) as cursor:
                        cursor.fetchall()
                except sqlite3.OperationalError as error:
                    assert error.sqlite_errorcode == sqlite3.SQLITE_BUSY
                    # RESERVED permits new readers; BUSY proves the writer is
                    # now PENDING while this real retrieval reader stays open.
                    break
                assert time.monotonic() < deadline, "The writer never blocked a new reader"
                time.sleep(0.001)
        return hits

    monkeypatch.setattr(writer, "_on_index_publication_write", publication_written)
    monkeypatch.setattr(reader, "_search_keyword_with_fallback", publish_after_keyword)
    try:
        hits = reader.search(QUERY, min_score=0)
    finally:
        if worker is not None:
            worker.join(6)
    assert worker is not None and not worker.is_alive()
    assert "error" not in outcome, outcome
    assert any("durable" in hit.snippet for hit in hits)
    assert any("replacement" in row["text"] for row in writer.read_published_index()["chunks"])
    monkeypatch.setattr(reader, "_search_keyword_with_fallback", original_keyword)
    assert any("replacement" in hit.snippet for hit in reader.search(QUERY, min_score=0))
