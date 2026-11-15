"""A separate origins writer orders real index publication against forget markers."""
from __future__ import annotations

from contextlib import closing
import multiprocessing
import signal
import threading

import pytest

from memory_core.config import MemoryConfig
from memory_core.consolidation.origins import MemoryEntryOriginLedger, MemoryIndexRevisionConflictError
from memory_core.flags import FeatureFlags
from memory_core.index.publication import PreparedIndexRevision
from memory_core.index.sqlite_store import SQLiteMemoryStore
from memory_core.workspace import MemoryWorkspace


def owner(tmp_path, *, same_database=False):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    (root / "memory/fact.md").write_text("A durable baseline fact.\n", encoding="utf8")
    config = MemoryConfig(root, store_path=tmp_path / "index.sqlite", flags=FeatureFlags(vector_search=False))
    ledger_path = config.store_path if same_database else tmp_path / "origins.sqlite"
    ledger = MemoryEntryOriginLedger(lambda _agent: ledger_path)
    store = SQLiteMemoryStore(config, None, revision_fence=ledger.revision_fence("main"))
    return store, MemoryWorkspace(root), ledger


def thread_task(function, errors, *, name):
    def run():
        try:
            function()
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=run, name=name)
    thread.start()
    return thread


def join(thread):
    thread.join(5)
    assert not thread.is_alive(), "A real database writer failed to settle"


def test_forget_waits_for_checked_split_index_commit(tmp_path, monkeypatch):
    store, workspace, ledger = owner(tmp_path)
    assert store.reindex(workspace) == 1
    before = ledger.index_revision("main")
    written, release, marker_attempted, marker_done = (threading.Event() for _ in range(4))
    errors = []
    original_open = ledger._open_write

    def traced_open(agent):
        if threading.current_thread().name == "forget":
            marker_attempted.set()
        return original_open(agent)

    def pause_publication(_db, **_options):
        written.set()
        assert release.wait(5)

    def forget():
        assert ledger.record_session_tombstones_if_lineage_current(
            "main", ["forgotten"], is_current=lambda _origins: True, created_at=123,
        )
        marker_done.set()

    monkeypatch.setattr(ledger, "_open_write", traced_open)
    monkeypatch.setattr(store, "_on_index_publication_write", pause_publication)
    (workspace.root / "memory/fact.md").write_text("A genuinely changed source.\n", encoding="utf8")
    builder = thread_task(lambda: store.reindex(workspace, force=True), errors, name="publisher")
    marker = None
    try:
        assert written.wait(5)
        marker = thread_task(forget, errors, name="forget")
        assert marker_attempted.wait(5)
        assert not marker_done.wait(0.05)
    finally:
        release.set()
        join(builder)
        if marker is not None:
            join(marker)
    assert errors == [] and marker_done.is_set()
    assert ledger.index_revision("main") == before + 2
    assert [row.session_id for row in ledger.list_session_tombstones("main")] == ["forgotten"]
    assert store.read_published_index()["chunks"][0]["text"] == "A genuinely changed source.\n"


def test_split_publisher_waits_for_marker_without_holding_index_writer(tmp_path, monkeypatch):
    store, workspace, ledger = owner(tmp_path)
    store.reindex(workspace)
    before = store.read_published_index()
    prepared, enter_publication, marker_open, release_marker, publisher_attempted = (
        threading.Event() for _ in range(5)
    )
    errors = []
    original_publish, original_open = store.publish_prepared_index, ledger._open_write

    def pause_before_publication(*args, **options):
        prepared.set()
        assert enter_publication.wait(5)
        return original_publish(*args, **options)

    def traced_open(agent):
        db = original_open(agent)
        if threading.current_thread().name == "publisher":
            db.set_trace_callback(lambda sql: publisher_attempted.set() if sql == "BEGIN IMMEDIATE" else None)
        return db

    def hold_marker(_origins):
        marker_open.set()
        assert release_marker.wait(5)
        return True

    monkeypatch.setattr(store, "publish_prepared_index", pause_before_publication)
    monkeypatch.setattr(ledger, "_open_write", traced_open)
    builder = thread_task(lambda: store.reindex(workspace, force=True), errors, name="publisher")
    marker = None
    try:
        assert prepared.wait(5)
        marker = thread_task(lambda: ledger.record_session_tombstones_if_lineage_current(
            "main", ["forgotten"], is_current=hold_marker, created_at=123,
        ), errors, name="forget")
        assert marker_open.wait(5)
        enter_publication.set()
        assert publisher_attempted.wait(5)
        # A waiting split publisher must acquire origins before it owns index.
        with closing(store.connect()) as db:
            db.execute("PRAGMA busy_timeout=50")
            db.execute("BEGIN IMMEDIATE")
            db.rollback()
    finally:
        enter_publication.set()
        release_marker.set()
        join(builder)
        if marker is not None:
            join(marker)
    assert len(errors) == 1 and isinstance(errors[0], MemoryIndexRevisionConflictError)
    assert store.read_published_index() == before
    assert [row.session_id for row in ledger.list_session_tombstones("main")] == ["forgotten"]


@pytest.mark.parametrize("same_database", [False, True])
def test_explicit_missing_revision_is_not_recaptured_at_publication(tmp_path, same_database):
    store, workspace, ledger = owner(tmp_path, same_database=same_database)
    assert ledger.index_revision("main") is None
    prepared = PreparedIndexRevision((), "{}", workspace=str(workspace.root.resolve()))
    generation = store.index_revision()
    ledger.record_session_tombstones_if_lineage_current(
        "main", ["forgotten"], is_current=lambda _origins: True, created_at=123,
    )
    with pytest.raises(MemoryIndexRevisionConflictError, match="expected revision None, found 1"):
        store.publish_prepared_index(prepared, generation, expected_fence_revision=None)
    assert store.index_revision() == generation
    assert store.read_published_index()["chunks"] == []


def commit_marker_then_wait(path, connection):
    ledger = MemoryEntryOriginLedger(lambda _agent: path)
    ledger.record_session_tombstones_if_lineage_current(
        "main", ["forgotten"], is_current=lambda _origins: True, created_at=123,
    )
    connection.send((ledger.index_revision("main"), ledger.list_session_tombstones("main")))
    connection.recv()


@pytest.mark.parametrize("same_database", [False, True])
def test_committed_marker_survives_process_kill_and_rejects_old_frame(tmp_path, monkeypatch, same_database):
    store, workspace, ledger = owner(tmp_path, same_database=same_database)
    store.reindex(workspace)
    before = store.read_published_index()
    revision = ledger.index_revision("main")
    original = store.publish_prepared_index
    observed = []

    def publish_after_marker_process_death(*args, **options):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=commit_marker_then_wait, args=(ledger.database_path("main"), child))
        process.start()
        child.close()
        try:
            assert parent.poll(5), "The child did not commit its actual forget marker"
            observed.append(parent.recv())
            process.kill()
            process.join(5)
            assert process.exitcode == -signal.SIGKILL
        finally:
            if process.is_alive():
                process.kill()
                process.join(5)
            parent.close()
        return original(*args, **options)

    monkeypatch.setattr(store, "publish_prepared_index", publish_after_marker_process_death)
    with pytest.raises(MemoryIndexRevisionConflictError):
        store.reindex(workspace, force=True)
    assert observed[0][0] == revision + 1
    assert store.read_published_index() == before
    assert ledger.list_session_tombstones("main") == observed[0][1]
    monkeypatch.setattr(store, "publish_prepared_index", original)
    reopened = SQLiteMemoryStore(store.config, None, revision_fence=ledger.revision_fence("main"))
    assert reopened.reindex(MemoryWorkspace(workspace.root), force=True) == 1
    assert ledger.index_revision("main") == revision + 2


def test_repeated_actual_marker_preserves_tombstone_and_advances_revision(tmp_path):
    store, _workspace, ledger = owner(tmp_path)
    fence = store.revision_fence
    assert fence.ledger is ledger
    assert ledger.record_session_tombstones_if_lineage_current(
        "main", ["forgotten"], is_current=lambda _origins: True, created_at=123,
    )
    before = ledger.list_session_tombstones("main")
    revision = fence.read()
    assert ledger.record_session_tombstones_if_lineage_current(
        "main", ["forgotten"], is_current=lambda _origins: True, created_at=999,
    )
    assert ledger.list_session_tombstones("main") == before
    assert fence.read() == revision + 1


@pytest.mark.parametrize("marker_exists", [False, True])
def test_on_search_reads_actual_marker_clock_without_an_explicit_fence(tmp_path, monkeypatch, marker_exists):
    from memory_core.host.managed_index import ManagedSQLiteMemoryStore

    base, workspace, ledger = owner(tmp_path, same_database=True)
    if marker_exists:
        ledger.record_session_tombstones_if_lineage_current(
            "main", ["forgotten"], is_current=lambda _origins: True, created_at=123,
        )
    with closing(ManagedSQLiteMemoryStore(base.config, workspace, memory_publication="on-search")) as store:
        assert store.revision_fence is None
        store.reindex(workspace)
        before = store.read_published_index()
        original = store.publish_prepared_index
        expected = ledger.index_revision("main")
        old_tombstones = ledger.list_session_tombstones("main")

        def publish_after_marker(*args, **options):
            ledger.record_session_tombstones_if_lineage_current(
                "main", ["forgotten"], is_current=lambda _origins: True, created_at=999,
            )
            return original(*args, **options)

        monkeypatch.setattr(store, "publish_prepared_index", publish_after_marker)
        with pytest.raises(MemoryIndexRevisionConflictError, match=f"expected revision {expected}, found"):
            store.reindex(workspace, force=True)
        assert store.read_published_index() == before
        if marker_exists:
            assert ledger.list_session_tombstones("main") == old_tombstones
        monkeypatch.setattr(store, "publish_prepared_index", original)
        assert store.reindex(workspace, force=True) == 1


def test_on_search_fencing_does_not_create_ledger_schema(tmp_path):
    from memory_core.host.managed_index import ManagedSQLiteMemoryStore

    base, workspace, _ledger = owner(tmp_path)
    with closing(ManagedSQLiteMemoryStore(base.config, workspace, memory_publication="on-search")) as store:
        assert store.reindex(workspace) == 1
        with closing(store.connect()) as db:
            assert db.execute(
                "SELECT name FROM sqlite_schema WHERE name IN ('memory_index_state', 'memory_session_tombstones')"
            ).fetchall() == []


def test_base_store_keeps_its_explicit_no_fence_policy(tmp_path, monkeypatch):
    base, workspace, ledger = owner(tmp_path, same_database=True)
    store = SQLiteMemoryStore(base.config, None)
    store.reindex(workspace)
    original = store.publish_prepared_index

    def publish_after_marker(*args, **options):
        ledger.record_session_tombstones_if_lineage_current(
            "main", ["forgotten"], is_current=lambda _origins: True, created_at=123,
        )
        return original(*args, **options)

    monkeypatch.setattr(store, "publish_prepared_index", publish_after_marker)
    assert store.reindex(workspace, force=True) == 1
    assert ledger.index_revision("main") == 1


def test_failed_split_index_transaction_does_not_advance_ledger(tmp_path):
    store, workspace, ledger = owner(tmp_path)
    store.reindex(workspace)
    before, revision = store.read_published_index(), ledger.index_revision("main")
    prepared = PreparedIndexRevision((), "{}", workspace=str(workspace.root.resolve()))

    def fail_commit(_commit):
        raise RuntimeError("Actual publication commit was refused")

    with pytest.raises(RuntimeError, match="commit was refused"):
        store.publish_prepared_index(prepared, store.index_revision(), with_commit=fail_commit)
    assert store.read_published_index() == before
    assert ledger.index_revision("main") == revision


def test_default_tombstone_reader_uses_existing_index_and_actual_agent_scope(tmp_path):
    store, _workspace, ledger = owner(tmp_path, same_database=True)
    assert store.is_session_forgotten("forgotten") is False
    ledger.record_session_tombstones("main", ["forgotten"], created_at=123)
    ledger.record_session_tombstones("other", ["foreign"], created_at=123)
    with closing(store.connect()) as db:
        before = db.execute("SELECT * FROM memory_session_tombstones ORDER BY session_id").fetchall()
        schema = db.execute("SELECT sql FROM sqlite_schema ORDER BY name").fetchall()
    assert store.is_session_forgotten("forgotten") is True
    assert store.is_session_forgotten("foreign") is False
    assert store.is_session_forgotten("absent") is False
    with closing(store.connect()) as db:
        assert db.execute("SELECT * FROM memory_session_tombstones ORDER BY session_id").fetchall() == before
        assert db.execute("SELECT sql FROM sqlite_schema ORDER BY name").fetchall() == schema


def test_default_tombstone_reader_ignores_catalog_schema_and_never_creates_missing_index(tmp_path):
    store, _workspace, _ledger = owner(tmp_path)
    with closing(store.connect()) as db:
        db.execute("CREATE TABLE memory_session_tombstones (agent TEXT, session_id TEXT)")
        db.execute("INSERT INTO memory_session_tombstones VALUES ('main','forgotten')")
        db.commit()
    assert store.is_session_forgotten("forgotten") is False
    store.path.unlink()
    assert store.is_session_forgotten("forgotten") is False
    assert not store.path.exists()


def test_tombstone_reader_requires_an_actual_table(tmp_path):
    store, _workspace, _ledger = owner(tmp_path)
    with closing(store.connect()) as db:
        db.execute(
            "CREATE VIEW memory_session_tombstones AS SELECT "
            "'forgotten' AS session_id, 'main' AS agent_id, 'forgotten' AS reason, 123 AS created_at"
        )
        db.commit()
    assert store.is_session_forgotten("forgotten") is False
