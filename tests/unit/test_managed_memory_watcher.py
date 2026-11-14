"""Managed watch publication driven by real external filesystem changes."""
from contextlib import closing
import inspect
import os
import threading
import time

from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import managed_index
from memory_core.host.managed_index import ManagedSQLiteMemoryStore
from memory_core.host.memory_watcher import MemoryFileWatcher
from memory_core.workspace import MemoryWorkspace


def _fast_watch(monkeypatch, *, debounce_ms=25):
    def create(root, **options):
        return MemoryFileWatcher(root, debounce_ms=debounce_ms, poll_interval_ms=10, settle_ms=20, **options)

    monkeypatch.setattr(managed_index, "MemoryFileWatcher", create)


def _owner(tmp_path, monkeypatch, *, debounce_ms=25):
    _fast_watch(monkeypatch, debounce_ms=debounce_ms)
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "MEMORY.md").write_text("# Memory\n\n- Initial actual preference.\n")
    workspace = MemoryWorkspace(root, index_sources=("memory",))
    config = MemoryConfig(root, store_path=tmp_path / "index.sqlite",
                          flags=FeatureFlags(vector_search=False, temporal_decay=False, mmr=False))
    store = ManagedSQLiteMemoryStore(config, workspace, memory_publication="on-search")
    store.reindex(workspace)
    return root, workspace, store


def _texts(store):
    rows = store.read_published_index()["chunks"]
    result = {}
    for row in rows:
        result.setdefault(row["path"], []).append(row["text"])
    return {path: "\n".join(texts) for path, texts in result.items()}


def _wait(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    raise AssertionError("The actual managed publication did not reach the required state")


def _settled(store):
    with store._condition:
        assert store._condition.wait_for(lambda: not store._memory_active, timeout=5)
    return store.lifecycle_snapshot()["memoryPublication"]


def test_external_create_edit_atomic_rename_and_delete_publish_actual_sql_without_search(tmp_path, monkeypatch):
    root, _, store = _owner(tmp_path, monkeypatch)
    try:
        target = root / "memory" / "new" / "deep" / "fact.md"
        target.parent.mkdir(parents=True)
        target.write_text("- A newly created external fact.\n")
        _wait(lambda: "newly created external fact" in _texts(store).get("memory/new/deep/fact.md", ""))
        target.write_text("- An externally edited fact.\n")
        _wait(lambda: "externally edited fact" in _texts(store).get("memory/new/deep/fact.md", ""))
        temporary = root / "replacement.tmp"
        temporary.write_text("- Actual atomic replacement fact.\n")
        os.replace(temporary, target)
        _wait(lambda: "atomic replacement fact" in _texts(store).get("memory/new/deep/fact.md", ""))
        target.unlink()
        _wait(lambda: "memory/new/deep/fact.md" not in _texts(store))
        published = store.read_published_index()
        assert not any(row["path"] == "memory/new/deep/fact.md" for row in published["sources"])
        state = _settled(store)
        assert any(job.get("reason") == "watch" and job["state"] == "completed" for job in state["jobs"])
        assert state["lastError"] is None and state["watcher"]["alive"] is True
        assert not any(operation["name"] == "search" for operation in store.lifecycle_snapshot()["operations"])
    finally:
        store.close()


def test_cold_empty_index_is_bootstrapped_by_a_real_file_event_without_search_or_explicit_reindex(tmp_path, monkeypatch):
    _fast_watch(monkeypatch)
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = MemoryWorkspace(root, index_sources=("memory",))
    config = MemoryConfig(root, store_path=tmp_path / "index.sqlite",
                          flags=FeatureFlags(vector_search=False, temporal_decay=False, mmr=False))
    store = ManagedSQLiteMemoryStore(config, workspace, memory_publication="on-search")
    try:
        assert store.read_published_index()["chunks"] == []
        assert store.read_published_index()["sources"] == []
        assert store.index_identity()["status"] != "valid"
        target = root / "memory" / "created-after-open" / "fact.md"
        target.parent.mkdir(parents=True)
        target.write_text("- A real cold watcher bootstrap fact.\n")
        _wait(lambda: "cold watcher bootstrap fact" in _texts(store).get("memory/created-after-open/fact.md", ""))
        assert store.index_identity()["status"] == "valid"
        state = _settled(store)
        assert state["dirty"] is False and state["lastError"] is None
        assert any(job.get("reason") == "watch" and job["state"] == "completed" for job in state["jobs"])
        assert not any(operation["name"] == "search" for operation in store.lifecycle_snapshot()["operations"])
    finally:
        store.close()


def test_root_memory_user_files_and_replaced_memory_directory_reconcile_actual_sources(tmp_path, monkeypatch):
    root, _, store = _owner(tmp_path, monkeypatch)
    try:
        user = root / "USER.md"
        user.write_text("- Actual user root preference.\n")
        _wait(lambda: "user root preference" in _texts(store).get("USER.md", ""))
        (root / "MEMORY.md").unlink()
        _wait(lambda: "MEMORY.md" not in _texts(store))
        (root / "MEMORY.md").write_text("- Restored root memory.\n")
        _wait(lambda: "Restored root memory" in _texts(store).get("MEMORY.md", ""))
        user.unlink()
        _wait(lambda: "USER.md" not in _texts(store))
        old = root / "memory" / "nested" / "old.md"
        old.parent.mkdir(parents=True)
        old.write_text("- Old recursive tree.\n")
        _wait(lambda: "memory/nested/old.md" in _texts(store))
        (root / "memory").rename(root / "retired-tree")
        replacement = root / "memory" / "replacement" / "new.md"
        replacement.parent.mkdir(parents=True)
        replacement.write_text("- Replacement recursive tree.\n")
        _wait(lambda: "memory/nested/old.md" not in _texts(store)
              and "Replacement recursive tree" in _texts(store).get("memory/replacement/new.md", ""))
        assert not any(row["path"].startswith("retired-tree/") for row in store.read_published_index()["sources"])
        assert _settled(store)["lastError"] is None
    finally:
        store.close()


def test_default_on_write_never_constructs_watcher_or_background_work(tmp_path, monkeypatch):
    def forbidden(*arguments, **options):
        raise AssertionError("The default on-write owner must not construct a filesystem watcher")

    monkeypatch.setattr(managed_index, "MemoryFileWatcher", forbidden)
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "MEMORY.md"
    target.write_text("- First source.\n")
    workspace = MemoryWorkspace(root, index_sources=("memory",))
    store = ManagedSQLiteMemoryStore(MemoryConfig(root, store_path=tmp_path / "index.sqlite",
        flags=FeatureFlags(vector_search=False)), workspace)
    try:
        assert store._memory_watcher is None and store._memory_executor is None
        assert store.read_published_index()["chunks"] == []
        store.reindex(workspace)
        target.write_text("- Later external source.\n")
        assert "First source" in _texts(store)["MEMORY.md"]
        assert store._memory_watcher is None and store._memory_executor is None
        store.reindex(workspace)
        assert "Later external source" in _texts(store)["MEMORY.md"]
        assert "memoryPublication" not in store.lifecycle_snapshot()
    finally:
        store.close()


def test_close_cancels_a_genuine_pending_watch_debounce_without_publishing_early(tmp_path, monkeypatch):
    root, _, store = _owner(tmp_path, monkeypatch, debounce_ms=500)
    before = store.lifecycle_snapshot()["memoryPublication"]["watchGeneration"]
    (root / "MEMORY.md").write_text("- Pending external source.\n")
    _wait(lambda: store.lifecycle_snapshot()["memoryPublication"]["watchGeneration"] > before)
    store.close()
    state = store.lifecycle_snapshot()["memoryPublication"]
    assert "Initial actual preference" in _texts(store)["MEMORY.md"]
    assert state["watcher"]["closed"] is True and state["watcher"]["alive"] is False
    assert state["watcher"]["pendingChange"] is False and state["active"] is False


def test_close_joins_a_real_watch_worker_and_its_original_publication(tmp_path, monkeypatch):
    root, _, store = _owner(tmp_path, monkeypatch)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = store._run_memory_publication

    def held(*arguments, **options):
        entered.set()
        assert release.wait(5)
        return original(*arguments, **options)

    monkeypatch.setattr(store, "_run_memory_publication", held)
    closer = None
    try:
        (root / "MEMORY.md").write_text("- Admitted external source.\n")
        assert entered.wait(5)

        def close():
            store.close()
            finished.set()

        closer = threading.Thread(target=close)
        closer.start()
        _wait(lambda: store.lifecycle_snapshot()["closing"])
        assert not finished.wait(0.05)
        release.set()
        closer.join(5)
        assert not closer.is_alive() and finished.is_set()
        assert "Admitted external source" in _texts(store)["MEMORY.md"]
        assert store.lifecycle_snapshot()["memoryPublication"]["watcher"]["alive"] is False
    finally:
        release.set()
        if closer is not None:
            closer.join(5)
        store.close()


def test_newer_file_fact_during_actual_uncommitted_publication_gets_followup_coverage(tmp_path, monkeypatch):
    root, _, store = _owner(tmp_path, monkeypatch)
    with closing(store.connect()) as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    entered, release = threading.Event(), threading.Event()
    held_rows = []
    original = store._on_index_publication_write

    def hold_actual_write(db, *, changes, error):
        returned = original(db, changes=changes, error=error)
        if not entered.is_set() and error is None:
            held_rows.extend(row[0] for row in db.execute("SELECT text FROM chunks WHERE path='MEMORY.md'"))
            entered.set()
            assert release.wait(5)
        return returned

    monkeypatch.setattr(store, "_on_index_publication_write", hold_actual_write)
    try:
        (root / "MEMORY.md").write_text("- First external generation.\n")
        assert entered.wait(5)
        assert any("First external generation" in text for text in held_rows)
        held_generation = store.lifecycle_snapshot()["memoryPublication"]["watchReadyGeneration"]
        (root / "MEMORY.md").write_text("- Newer external generation.\n")
        _wait(lambda: store.lifecycle_snapshot()["memoryPublication"]["watchReadyGeneration"] > held_generation)
        assert "Initial actual preference" in _texts(store)["MEMORY.md"]
        release.set()
        _wait(lambda: "Newer external generation" in _texts(store).get("MEMORY.md", ""))
        state = _settled(store)
        assert state["watchPublishedGeneration"] >= state["watchReadyGeneration"]
        assert state["dirty"] is False and state["lastError"] is None
        assert (root / "MEMORY.md").read_text() == "- Newer external generation.\n"
    finally:
        release.set()
        store.close()


def test_old_postpublication_source_comparison_cannot_acknowledge_a_newer_actual_watch_fact(tmp_path, monkeypatch):
    root, _, store = _owner(tmp_path, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original = store._read_source_snapshots
    refresh_code = ManagedSQLiteMemoryStore._refresh_memory_dirty.__code__
    publisher_code = ManagedSQLiteMemoryStore._run_memory_publication.__code__
    held = {}

    def read_then_pause(*arguments, **options):
        snapshots = original(*arguments, **options)
        caller = inspect.currentframe().f_back
        publisher = caller.f_back
        if (not entered.is_set() and caller.f_code is refresh_code
                and caller.f_locals.get("self") is store
                and caller.f_locals.get("acknowledge_watch") is True
                and publisher.f_code is publisher_code
                and getattr(store._local, "memory_publisher", False)):
            # This is the final original worker comparison, after its actual
            # SQLite commit. Earlier scoped-publisher comparisons stay untouched.
            held["generation"] = store.lifecycle_snapshot()["memoryPublication"]["watchGeneration"]
            held["sourceHashes"] = {key: entry.hash for key, entry in snapshots.items()}
            held["published"] = _texts(store)
            entered.set()
            assert release.wait(5)
        return snapshots

    monkeypatch.setattr(store, "_read_source_snapshots", read_then_pause)
    try:
        (root / "MEMORY.md").write_text("- Generation one already committed.\n")
        assert entered.wait(5)
        assert "Generation one already committed" in held["published"]["MEMORY.md"]
        assert held["sourceHashes"]
        (root / "MEMORY.md").write_text("- Generation two arrived during comparison.\n")
        _wait(lambda: store.lifecycle_snapshot()["memoryPublication"]["watchReadyGeneration"] > held["generation"])
        assert store.lifecycle_snapshot()["memoryPublication"]["active"] is True
        assert "Generation one already committed" in _texts(store)["MEMORY.md"]
        release.set()
        _wait(lambda: "Generation two arrived during comparison" in _texts(store).get("MEMORY.md", ""))
        state = _settled(store)
        assert state["dirty"] is False and state["lastError"] is None
        assert state["watchPublishedGeneration"] >= state["watchReadyGeneration"]
    finally:
        release.set()
        store.close()
