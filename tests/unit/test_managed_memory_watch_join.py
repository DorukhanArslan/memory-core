"""Positive joins retain real source versions and actual admitted Futures."""
import threading

import pytest

from memory_core.host import memory_watcher

from tests.unit.test_managed_memory_watcher import _owner, _texts, _wait


def test_wait_joins_real_delivery_and_its_original_publisher_without_starting_work(tmp_path, monkeypatch):
    root, _, store = _owner(tmp_path, monkeypatch)
    watcher = store.memory_watcher
    original = store._submit_memory_publication
    submissions = []

    def record(*arguments, **options):
        submissions.append(threading.get_ident())
        return original(*arguments, **options)

    monkeypatch.setattr(store, "_submit_memory_publication", record)
    try:
        target = root / "MEMORY.md"
        target.write_text("- A positively delivered external version.\n")
        versions = watcher.capture_versions([target])
        returned = store.wait_for_memory_watches(versions, timeout=5)
        assert returned["status"] == "completed" and returned["futureReturned"] is None
        assert returned["delivery"]["targets"] == versions
        assert returned["job"]["publishedWatchGeneration"] >= returned["watchGeneration"]
        assert returned["futureObjectId"] == str(id(store._memory_job_futures[returned["job"]["id"]]))
        assert submissions and threading.get_ident() not in submissions
        assert "positively delivered external version" in _texts(store)["MEMORY.md"]
        assert all(row["path"] == str(target) for row in returned["delivery"]["deliveries"])
    finally:
        store.close()


def test_retained_target_is_not_recaptured_after_a_later_real_version(tmp_path, monkeypatch):
    root, _, store = _owner(tmp_path, monkeypatch)
    watcher = store.memory_watcher
    try:
        path = root / "MEMORY.md"
        path.write_text("- The first retained version.\n")
        retained = watcher.capture_versions([path])
        first = store.wait_for_memory_watches(retained, timeout=5)
        path.write_text("- The later physical version.\n")
        newer = watcher.capture_versions([path])
        store.wait_for_memory_watches(newer, timeout=5)
        assert newer != retained

        def forbidden(*arguments, **options):
            raise AssertionError("The deferred join cannot recapture a later file version")

        monkeypatch.setattr(watcher, "capture_versions", forbidden)
        original_inventory = memory_watcher._inventory

        def background_only(*arguments, **options):
            assert threading.current_thread() is not threading.main_thread()
            return original_inventory(*arguments, **options)

        monkeypatch.setattr(memory_watcher, "_inventory", background_only)
        deferred = store.wait_for_memory_watches(retained, timeout=1)
        assert deferred["delivery"]["targets"] == retained
        assert deferred["futureObjectId"] == first["futureObjectId"]
        assert "later physical version" in _texts(store)["MEMORY.md"]
    finally:
        store.close()


def test_initial_baseline_and_empty_versions_are_never_positive_delivery(tmp_path, monkeypatch):
    root, _, store = _owner(tmp_path, monkeypatch)
    try:
        watcher = store.memory_watcher
        baseline = watcher.capture_versions([root / "MEMORY.md"])
        before = store.lifecycle_snapshot()["memoryPublication"]["jobCount"]
        with pytest.raises(TimeoutError, match="not delivered"):
            store.wait_for_memory_watches(baseline, timeout=0.02)
        with pytest.raises(ValueError, match="At least one"):
            store.wait_for_memory_watches([], timeout=0)
        assert store.lifecycle_snapshot()["memoryPublication"]["jobCount"] == before
        assert store.memory_watcher is watcher
    finally:
        store.close()


def test_deletion_join_retains_real_removed_inode_and_publishes_absence(tmp_path, monkeypatch):
    root, _, store = _owner(tmp_path, monkeypatch)
    watcher = store.memory_watcher
    try:
        path = root / "MEMORY.md"
        previous = watcher.capture_versions([path])[0]["version"]
        path.unlink()
        retained = watcher.capture_versions([path])
        assert retained == [{"path": str(path), "exists": False, "version": None}]
        returned = store.wait_for_memory_watches(retained, timeout=5)
        delivery = returned["delivery"]["deliveries"][0]
        assert delivery["previousVersion"] == previous and delivery["version"] is None
        assert returned["status"] == "completed" and "MEMORY.md" not in _texts(store)
    finally:
        store.close()


def test_close_wakes_an_unproved_version_wait_without_creating_a_publisher(tmp_path, monkeypatch):
    root, _, store = _owner(tmp_path, monkeypatch)
    baseline = store.memory_watcher.capture_versions([root / "MEMORY.md"])
    errors = []

    def join():
        try:
            store.wait_for_memory_watches(baseline)
        except RuntimeError as error:
            errors.append(str(error))

    waiter = threading.Thread(target=join)
    waiter.start()
    try:
        _wait(lambda: any(row["name"] == "wait-memory-watches" and row["state"] == "running"
                         for row in store.lifecycle_snapshot()["operations"]))
        store.close()
        waiter.join(5)
        assert not waiter.is_alive() and errors and "closed" in errors[0]
        assert store.lifecycle_snapshot()["memoryPublication"]["jobCount"] == 0
    finally:
        store.close()
        waiter.join(5)
