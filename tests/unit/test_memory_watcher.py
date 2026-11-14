"""Real filesystem detector tests; no memory store or acceptance engine runs."""
from contextlib import contextmanager
import os
from pathlib import Path
import queue
import threading
import time

import pytest

from memory_core.host import memory_watcher as module
from memory_core.host.memory_watcher import MemoryFileWatcher


def _files(root):
    return {path.relative_to(root).as_posix(): path.read_text() for path in root.rglob("*.md")
            if path.is_file() and not path.is_symlink()}


@contextmanager
def _watch(root, *, stat_backend=False, monkeypatch=None, **options):
    if stat_backend:
        def unavailable():
            raise OSError("actual inotify initialization unavailable")
        monkeypatch.setattr(module, "_Inotify", unavailable)
    calls, dirty, errors = queue.Queue(), threading.Event(), []
    watcher = MemoryFileWatcher(root, on_dirty=dirty.set, on_change=lambda: calls.put(_files(root)),
        on_unavailable=errors.append, debounce_ms=20, settle_ms=30, poll_interval_ms=10, **options)
    watcher.start()
    try:
        yield watcher, calls, dirty, errors
    finally:
        watcher.close()


def _until(calls, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        observed = calls.get(timeout=max(0.001, deadline - time.monotonic()))
        if predicate(observed):
            return observed
    raise AssertionError("The actual file state was not delivered")


@pytest.mark.parametrize("stat_backend", [False, True], ids=["platform-backend", "stat-fallback"])
def test_missing_memory_tree_atomic_replace_delete_and_root_replacement(tmp_path, monkeypatch, stat_backend):
    root = tmp_path / "workspace"
    root.mkdir()
    with _watch(root, stat_backend=stat_backend, monkeypatch=monkeypatch) as (watcher, calls, _, errors):
        original_thread = watcher.status()["threadId"]
        watcher.start()
        assert watcher.status()["threadId"] == original_thread
        assert calls.empty()
        nested = root / "memory" / "new" / "deep"
        nested.mkdir(parents=True)
        target = nested / "fact.md"
        target.write_text("first actual bytes")
        _until(calls, lambda files: files.get("memory/new/deep/fact.md") == "first actual bytes")
        temporary = root / "replacement.tmp"
        temporary.write_text("atomic replacement bytes")
        os.replace(temporary, target)
        _until(calls, lambda files: files.get("memory/new/deep/fact.md") == "atomic replacement bytes")
        target.unlink()
        _until(calls, lambda files: "memory/new/deep/fact.md" not in files)
        (root / "memory").rename(root / "old-memory")
        (root / "memory" / "replacement").mkdir(parents=True)
        (root / "memory" / "replacement" / "new.md").write_text("new root bytes")
        _until(calls, lambda files: files.get("memory/replacement/new.md") == "new root bytes")
        if stat_backend:
            assert watcher.status()["backend"] == "stat" and errors


@pytest.mark.parametrize("stat_backend", [False, True], ids=["platform-backend", "stat-fallback"])
def test_exact_root_files_and_watch_filters_skip_symlinks_and_ignored_paths(tmp_path, monkeypatch, stat_backend):
    root, outside = tmp_path / "workspace", tmp_path / "outside"
    (root / "memory").mkdir(parents=True)
    outside.mkdir()
    (outside / "external.md").write_text("outside")
    (root / "memory" / "linked.md").symlink_to(outside / "external.md")
    (root / "memory" / "linked-dir").symlink_to(outside, target_is_directory=True)
    with _watch(root, stat_backend=stat_backend, monkeypatch=monkeypatch) as (_, calls, _, _):
        (outside / "external.md").write_text("changed outside")
        (root / "OTHER.md").write_text("unselected root file")
        (root / "memory" / "unselected.txt").write_text("text file")
        for name in (".GiT", "node_modules", ".pnpm-store", ".venv", "venv", ".tox", "__pycache__", ".openclaw-repair"):
            directory = root / "memory" / name
            directory.mkdir()
            (directory / "ignored.md").write_text("ignored bytes")
        with pytest.raises(queue.Empty):
            calls.get(timeout=0.2)
        (root / "USER.md").write_text("selected root user")
        _until(calls, lambda files: files.get("USER.md") == "selected root user")
        (root / "MEMORY.md").write_text("selected root memory")
        _until(calls, lambda files: files.get("MEMORY.md") == "selected root memory")
        (root / "USER.md").unlink()
        _until(calls, lambda files: "USER.md" not in files)


def test_real_partial_write_is_debounced_until_complete_bytes_settle(tmp_path):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    target = root / "memory" / "fact.md"
    target.write_text("before")
    calls, dirty = queue.Queue(), threading.Event()
    watcher = MemoryFileWatcher(root, on_dirty=dirty.set, on_change=lambda: calls.put(target.read_text()),
                                debounce_ms=70, poll_interval_ms=10, settle_ms=30)
    watcher.start()
    try:
        with target.open("w") as writer:
            writer.write("first")
            writer.flush()
            os.fsync(writer.fileno())
            assert dirty.wait(4)
            writer.write(" complete")
            writer.flush()
            os.fsync(writer.fileno())
        assert calls.get(timeout=4) == "first complete"
        with pytest.raises(queue.Empty):
            calls.get(timeout=0.15)
    finally:
        watcher.close()


def test_changes_during_callback_are_delivered_by_a_later_nonoverlapping_pass(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "MEMORY.md"
    target.write_text("initial")
    entered, release, calls = threading.Event(), threading.Event(), queue.Queue()

    def changed():
        calls.put(target.read_text())
        if not entered.is_set():
            entered.set()
            assert release.wait(4)

    watcher = MemoryFileWatcher(root, on_dirty=lambda: None, on_change=changed,
                                debounce_ms=10, settle_ms=20, poll_interval_ms=10)
    watcher.start()
    try:
        target.write_text("first generation")
        assert entered.wait(4)
        assert calls.get(timeout=1) == "first generation"
        target.write_text("later generation")
        assert calls.empty()
        release.set()
        assert calls.get(timeout=4) == "later generation"
    finally:
        release.set()
        watcher.close()


def test_close_cancels_pending_debounce_and_releases_thread_and_descriptors(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    dirty, changed = threading.Event(), threading.Event()
    watcher = MemoryFileWatcher(root, on_dirty=dirty.set, on_change=changed.set,
                                debounce_ms=500, poll_interval_ms=10, settle_ms=30)
    watcher.start()
    descriptors = list(watcher._pipe)
    if watcher._backend is not None:
        descriptors.append(watcher._backend.fd)
    (root / "MEMORY.md").write_text("queued")
    assert dirty.wait(4)
    watcher.close()
    watcher.close()
    assert not changed.is_set()
    assert watcher.status()["closed"] is True and watcher.status()["alive"] is False
    assert watcher.status()["pendingChange"] is False
    assert watcher.snapshot()["completedCallbacks"] == 0
    assert "publications" not in watcher.snapshot()
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    with pytest.raises(RuntimeError, match="closed"):
        watcher.start()


def test_close_joins_an_entered_callback_and_callback_cannot_close_its_owner(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    callback_facts = []

    def changed():
        callback_facts.append(watcher.owns_current_thread())
        with pytest.raises(RuntimeError, match="own watcher"):
            watcher.close()
        entered.set()
        assert release.wait(4)

    watcher = MemoryFileWatcher(root, on_dirty=lambda: None, on_change=changed,
                                debounce_ms=10, settle_ms=20, poll_interval_ms=10)
    watcher.start()
    (root / "MEMORY.md").write_text("admitted")
    assert entered.wait(4)

    def close():
        watcher.close()
        closed.set()

    closer = threading.Thread(target=close)
    closer.start()
    try:
        assert not closed.wait(0.05)
    finally:
        release.set()
        closer.join(4)
    assert not closer.is_alive() and closed.is_set() and callback_facts == [True]
    assert watcher.status()["alive"] is False


def test_creation_of_initially_missing_workspace_is_observed(tmp_path):
    root = tmp_path / "missing" / "workspace"
    with _watch(root) as (_, calls, _, _):
        (root / "memory" / "nested").mkdir(parents=True)
        (root / "memory" / "nested" / "created.md").write_text("created after coverage")
        _until(calls, lambda files: files.get("memory/nested/created.md") == "created after coverage")


def test_real_inotify_burst_overflow_reconciles_all_sources_without_path_drops(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    entered, release, calls = threading.Event(), threading.Event(), queue.Queue()

    def changed():
        calls.put(_files(root))
        if not entered.is_set():
            entered.set()
            assert release.wait(4)

    # A small queue bound exercises the same genuine kernel event overflow
    # branch without creating thousands of fixtures. Events remain unmodified.
    monkeypatch.setattr(module, "_MAX_PATHS", 2)
    watcher = MemoryFileWatcher(root, on_dirty=lambda: None, on_change=changed,
                                debounce_ms=10, poll_interval_ms=10, settle_ms=20)
    watcher.start()
    try:
        if watcher.status()["backend"] != "inotify":
            pytest.skip("This real kernel-event test requires inotify")
        (root / "memory" / "first.md").write_text("first")
        assert entered.wait(4)
        calls.get(timeout=1)
        for number in range(6):
            (root / "memory" / f"burst-{number}.md").write_text(str(number))
        release.set()
        observed = _until(calls, lambda files: all(f"memory/burst-{number}.md" in files for number in range(6)))
        assert all(observed[f"memory/burst-{number}.md"] == str(number) for number in range(6))
        assert watcher.snapshot()["overflows"] >= 1
    finally:
        release.set()
        watcher.close()


def test_captured_actual_version_requires_real_delivery_and_callback_completion(tmp_path):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    dirty_generations, settling_generations = [], []

    def dirty():
        dirty_generations.append(watcher.delivery_generation)

    def changed():
        generation = watcher.settling_generation
        settling_generations.append(generation)
        assert watcher.snapshot()["settledGeneration"] < generation

    watcher = MemoryFileWatcher(root, on_dirty=dirty, on_change=changed,
                                debounce_ms=10, settle_ms=20, poll_interval_ms=10)
    watcher.start()
    try:
        target = root / "memory" / "new.md"
        target.write_text("actual delivered version")
        versions = watcher.capture_versions([target])
        info = target.lstat()
        assert versions == [{"path": str(target), "exists": True, "version": {
            "device": str(info.st_dev), "inode": str(info.st_ino), "size": info.st_size,
            "mtimeNs": str(info.st_mtime_ns), "ctimeNs": str(info.st_ctime_ns)}}]
        receipt = watcher.wait_for_versions(versions, timeout=4)
        assert receipt["targets"] == versions
        delivery = receipt["deliveries"][0]
        assert delivery["version"] == versions[0]["version"]
        if delivery["previousVersion"] is not None:
            # A genuine write_text may first deliver its zero-byte create.
            # Preserve that observed predecessor rather than assuming absence.
            assert any(row["path"] == delivery["path"] and row["version"] == delivery["previousVersion"]
                       and row["generation"] < delivery["generation"] for row in watcher.snapshot()["deliveries"])
        assert delivery["generation"] in dirty_generations
        assert receipt["settledGeneration"] in settling_generations
        assert delivery["generation"] <= receipt["settledGeneration"]
        assert delivery["backend"] in {"inotify", "stat"} and int(delivery["observedAtNs"]) > 0
        assert watcher.delivery_generation is None and watcher.settling_generation is None
        assert watcher._deliveries.maxlen >= 4096
    finally:
        watcher.close()


def test_baseline_or_absence_cannot_satisfy_wait_and_wait_performs_no_caller_filesystem_work(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "MEMORY.md"
    target.write_text("initial baseline")
    with _watch(root) as (watcher, calls, dirty, _):
        baseline = watcher.capture_versions([target])
        absent = watcher.capture_versions([root / "memory" / "never-seen.md"])
        assert absent == [{"path": str(root / "memory" / "never-seen.md"), "exists": False, "version": None}]
        caller = threading.get_ident()
        original_lstat, original_inventory = Path.lstat, module._inventory

        def guarded_lstat(path, *arguments, **options):
            assert threading.get_ident() != caller, "Waiting may not recapture physical metadata"
            return original_lstat(path, *arguments, **options)

        def guarded_inventory(*arguments, **options):
            assert threading.get_ident() != caller, "Waiting may not scan filesystem sources"
            return original_inventory(*arguments, **options)

        def forbidden_capture(*arguments, **options):
            raise AssertionError("Waiting must retain the caller's original target")

        monkeypatch.setattr(Path, "lstat", guarded_lstat)
        monkeypatch.setattr(module, "_inventory", guarded_inventory)
        monkeypatch.setattr(watcher, "capture_versions", forbidden_capture)
        for versions in (baseline, absent):
            with pytest.raises(TimeoutError, match="not delivered and settled"):
                watcher.wait_for_versions(versions, timeout=0.06)
        assert watcher.snapshot()["deliveries"] == []
        assert watcher.snapshot()["settledGeneration"] == 0
        assert not dirty.is_set() and calls.empty()


def test_actual_deletion_delivery_retains_the_previous_inode_version(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "USER.md"
    target.write_text("before deletion")
    with _watch(root) as (watcher, _, _, _):
        previous = watcher.capture_versions([target])[0]["version"]
        target.unlink()
        absent = watcher.capture_versions([target])
        receipt = watcher.wait_for_versions(absent, timeout=4)
        delivery = receipt["deliveries"][0]
        assert delivery["path"] == str(target) and delivery["exists"] is False and delivery["version"] is None
        assert delivery["previousVersion"] == previous
        assert receipt["settledGeneration"] >= delivery["generation"]


def test_retained_old_version_waits_for_its_actual_callback_then_survives_a_newer_version(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    entered, release, waiting, done = (threading.Event() for _ in range(4))
    results = {}

    def changed():
        if not entered.is_set():
            entered.set()
            assert release.wait(4)

    watcher = MemoryFileWatcher(root, on_dirty=lambda: None, on_change=changed,
                                debounce_ms=10, settle_ms=20, poll_interval_ms=10)
    watcher.start()
    waiter = None
    try:
        target = root / "MEMORY.md"
        target.write_text("first retained version")
        retained = watcher.capture_versions([target])
        assert entered.wait(4)

        def wait():
            waiting.set()
            results["old"] = watcher.wait_for_versions(retained, timeout=4)
            done.set()

        waiter = threading.Thread(target=wait)
        waiter.start()
        assert waiting.wait(1) and not done.wait(0.05)
        target.write_text("newer physical version")
        current = watcher.capture_versions([target])
        assert current != retained
        release.set()
        waiter.join(4)
        assert not waiter.is_alive() and done.is_set()
        assert results["old"]["targets"] == retained
        assert target.read_text() == "newer physical version"
        watcher.wait_for_versions(current, timeout=4)
        assert watcher.wait_for_versions(retained, timeout=0)["deliveries"][0]["version"] == retained[0]["version"]
    finally:
        release.set()
        if waiter is not None:
            waiter.join(4)
        watcher.close()


def test_version_overwritten_before_detector_observes_it_remains_unproved(tmp_path):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    entered, release = threading.Event(), threading.Event()

    def changed():
        if not entered.is_set():
            entered.set()
            assert release.wait(4)

    watcher = MemoryFileWatcher(root, on_dirty=lambda: None, on_change=changed,
                                debounce_ms=10, settle_ms=20, poll_interval_ms=10)
    watcher.start()
    try:
        (root / "MEMORY.md").write_text("hold a genuine earlier callback")
        assert entered.wait(4)
        target = root / "memory" / "transient.md"
        target.write_text("never observed version")
        lost = watcher.capture_versions([target])
        target.write_text("only this newer version can be observed")
        current = watcher.capture_versions([target])
        assert current != lost
        release.set()
        watcher.wait_for_versions(current, timeout=4)
        with pytest.raises(TimeoutError, match="not delivered and settled"):
            watcher.wait_for_versions(lost, timeout=0.06)
        assert not any(row["version"] == lost[0]["version"] for row in watcher.snapshot()["deliveries"])
    finally:
        release.set()
        watcher.close()


def test_version_api_rejects_empty_unowned_ignored_and_symlink_targets_without_admission(tmp_path):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside")
    (root / "memory" / "link.md").symlink_to(outside)
    (root / "memory" / "alias").symlink_to(root / "memory", target_is_directory=True)
    with _watch(root) as (watcher, _, _, _):
        for paths in ([], [outside], [root / "OTHER.md"], [root / "memory" / ".git" / "fact.md"],
                      [root / "memory" / "link.md"], [root / "memory" / "alias" / "fact.md"]):
            with pytest.raises(ValueError):
                watcher.capture_versions(paths)
        for versions in ([], [{"path": str(outside), "exists": False, "version": None}],
                         [{"path": str(root / "MEMORY.md"), "exists": True, "version": None}]):
            with pytest.raises(ValueError):
                watcher.wait_for_versions(versions, timeout=0)
        assert watcher.snapshot()["deliveries"] == []


def test_close_wakes_a_retained_version_waiter_without_manufacturing_delivery(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "MEMORY.md"
    target.write_text("unchanged baseline")
    with _watch(root) as (watcher, _, _, _):
        retained = watcher.capture_versions([target])
        entered, done, errors = threading.Event(), threading.Event(), []

        def wait():
            entered.set()
            try:
                watcher.wait_for_versions(retained)
            except RuntimeError as error:
                errors.append(str(error))
            finally:
                done.set()

        thread = threading.Thread(target=wait)
        thread.start()
        assert entered.wait(1) and not done.wait(0.05)
        watcher.close()
        thread.join(4)
        assert not thread.is_alive() and done.is_set() and errors
        assert watcher.snapshot()["deliveries"] == []
        with pytest.raises(RuntimeError, match="closed"):
            watcher.wait_for_versions(retained, timeout=0)


def test_failed_callback_does_not_settle_generation_or_expose_it_as_an_error_callback_generation(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    unavailable, callbacks = threading.Event(), []

    def changed():
        assert watcher.settling_generation is not None
        raise RuntimeError("actual callback failed")

    def failed(error):
        callbacks.append((str(error), watcher.delivery_generation, watcher.settling_generation))
        unavailable.set()

    watcher = MemoryFileWatcher(root, on_dirty=lambda: None, on_change=changed, on_unavailable=failed,
                                debounce_ms=10, settle_ms=20, poll_interval_ms=10)
    watcher.start()
    try:
        target = root / "MEMORY.md"
        target.write_text("unsettled version")
        retained = watcher.capture_versions([target])
        assert unavailable.wait(4)
        with pytest.raises(TimeoutError):
            watcher.wait_for_versions(retained, timeout=0.06)
        assert watcher.snapshot()["settledGeneration"] == 0
        assert watcher.snapshot()["completedCallbacks"] == 0
        assert callbacks == [("actual callback failed", None, None)]
    finally:
        watcher.close()


def test_new_directory_watch_attachment_gap_is_reconciled_immediately_with_actual_file_delivery(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    completed = threading.Event()
    watcher = MemoryFileWatcher(root, on_dirty=lambda: None, on_change=completed.set,
                                debounce_ms=1500, settle_ms=20, poll_interval_ms=10)
    watcher.start()
    try:
        backend = watcher._backend
        if backend is None:
            pytest.skip("This real directory-attachment race requires inotify")
        nested = root / "memory" / "attached"
        target = nested / "fact.md"
        created, rescanned = threading.Event(), threading.Event()
        retained = []
        original_reconcile, original_inventory = backend.reconcile, module._inventory

        def create_before_actual_watch_attachment(directories):
            if nested in directories and nested not in backend.paths and not created.is_set():
                # This directory was already enumerated without a file and has
                # no kernel watch yet. A parent directory watch cannot see this
                # nested file's write, so only real coverage reconciliation wins.
                target.write_text("created between enumeration and attachment")
                retained.extend(watcher.capture_versions([target]))
                created.set()
            return original_reconcile(directories)

        def observe_actual_rescan(*arguments, **options):
            actual = original_inventory(*arguments, **options)
            if created.is_set() and "file:memory/attached/fact.md" in actual[0]:
                rescanned.set()
            return actual

        monkeypatch.setattr(backend, "reconcile", create_before_actual_watch_attachment)
        monkeypatch.setattr(module, "_inventory", observe_actual_rescan)
        nested.mkdir()
        assert created.wait(4)
        # The 1500 ms debounce cannot be the source of this rescan. Coverage
        # attachment must immediately close its own actual filesystem gap.
        assert rescanned.wait(0.5)
        receipt = watcher.wait_for_versions(retained, timeout=4)
        assert completed.is_set()
        assert receipt["deliveries"][0]["version"] == retained[0]["version"]
        assert target.read_text() == "created between enumeration and attachment"
    finally:
        watcher.close()
