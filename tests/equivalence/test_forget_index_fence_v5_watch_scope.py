"""Real detector/stdlib execution with a labelled worker, never an SDK index."""
from concurrent.futures import ThreadPoolExecutor
import sys
import threading

from equivalence.forget_index_fence_sdk import _OriginalObserver, _code_identity, _original_bindings
from memory_core.host.memory_watcher import MemoryFileWatcher


class _LabelledStore:
    def _run_memory_publication(self, job, token):
        job["actualWorkerReturned"] = True
        return {"labelledReturn": token}


def test_watch_scope_uses_actual_new_generation_instead_of_long_running_detector_entry(tmp_path):
    observer = _OriginalObserver(_original_bindings())
    worker = _LabelledStore._run_memory_publication
    observer.codes[worker.__code__] = {"name": "ManagedSQLiteMemoryStore._run_memory_publication",
        "receiver": "self", "code": _code_identity(worker.__code__)}
    store = _LabelledStore()
    observer.bind_owner(store, "labelled-store")
    jobs, futures = [], []
    callbacks = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)

    def changed():
        job = {"generationFromOriginalCallback": watcher.settling_generation}
        jobs.append(job)
        futures.append(executor.submit(store._run_memory_publication, job, "actual-token"))
        callbacks.set()

    watcher = MemoryFileWatcher(tmp_path, on_dirty=lambda: None, on_change=changed,
        debounce_ms=10, settle_ms=10, poll_interval_ms=10)
    # Bind before start to exercise the real scheduling case where _run's
    # original entry is observed at generation zero for its whole lifetime.
    observer.bind_watcher(watcher, store)
    previous, previous_threads = sys.getprofile(), threading.getprofile()
    try:
        sys.setprofile(observer.profile)
        threading.setprofile(observer.profile)
        with observer.call_scope("acquire", "acquire"):
            watcher.start()
        path = tmp_path / "MEMORY.md"
        path.write_text("- An actual externally written source.\n")
        assert callbacks.wait(5)
        assert futures[0].result(5) == {"labelledReturn": "actual-token"}
    finally:
        watcher.close()
        executor.shutdown(wait=True)
        sys.setprofile(previous)
        threading.setprofile(previous_threads)
    task = observer.submitted_tasks[0]["receipt"]
    scope = task["scope"]
    assert scope["kind"] == "watch" and scope["origin"] == "original-memory-watcher"
    assert scope["detectorGeneration"] == jobs[0]["generationFromOriginalCallback"] > 0
    assert scope["storeObjectId"] == str(id(store)) and scope["watcherObjectId"] == str(id(watcher))
    assert "wallClockNowMs" not in scope
    calls = [row for row in observer.events if row["event"] == "original-call"
             and row["name"] == "ManagedSQLiteMemoryStore._run_memory_publication"]
    assert calls and calls[0]["scope"] == scope
    returns = [row for row in observer.events if row["event"] == "original-return"
               and row["callSequence"] == calls[0]["sequence"]]
    assert returns[0]["returned"] == {"labelledReturn": "actual-token"}
