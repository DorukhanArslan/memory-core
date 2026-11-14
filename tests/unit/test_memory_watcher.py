"""Real filesystem detector tests; no memory store or acceptance engine runs."""
from contextlib import contextmanager
import os
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
