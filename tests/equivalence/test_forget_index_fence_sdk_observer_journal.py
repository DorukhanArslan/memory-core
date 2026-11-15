"""Concurrent passive receipts only; no original engine or database executes."""
import sys
import threading

import pytest

from equivalence import forget_index_fence_sdk as sdk
from equivalence.forget_index_fence_evidence import _events
from equivalence.forget_index_fence_sdk_clock import OwnedSourceWriteClock


class _AttemptLock:
    def __init__(self):
        self.lock = threading.Lock()
        self.second_attempted = threading.Event()
        self.capture_attempted = threading.Event()
        self.progress = threading.Event()

    def __enter__(self):
        if threading.current_thread().name == "second-recorder":
            self.second_attempted.set()
            self.progress.set()
        elif threading.current_thread().name == "capture":
            self.capture_attempted.set()
        self.lock.acquire()
        return self

    def __exit__(self, *exception):
        self.lock.release()


def test_actual_event_publishes_whole_ordered_rows_and_stable_snapshot_prefix(monkeypatch):
    observer = sdk._OriginalObserver({})
    observer._event_lock = lock = _AttemptLock()
    first_paused, release_first, second_finished = (threading.Event() for _ in range(3))
    original_ns = sdk.time.monotonic_ns
    failures, returned, captured = [], {}, []
    payloads = {"first": {"whole": ["watch", {"unmodified": 1}]},
                "second": {"whole": ["search", {"unmodified": 2}]}}

    def metadata_time():
        if threading.current_thread().name == "first-recorder":
            first_paused.set()
            assert release_first.wait(3)
        elif threading.current_thread().name == "second-recorder":
            lock.progress.set()
        return original_ns()

    def record(label):
        try:
            returned[label] = observer.event("original-call", name=label,
                callLabel=label, callKind="watch" if label == "first" else "search",
                scope={"label": label}, payload=payloads[label])
        except BaseException as error:
            failures.append(error)
        finally:
            if label == "second":
                second_finished.set()

    def snapshot():
        captured.extend(observer.snapshot_events())

    monkeypatch.setattr(sdk.time, "monotonic_ns", metadata_time)
    first = threading.Thread(target=record, args=("first",), name="first-recorder")
    second = threading.Thread(target=record, args=("second",), name="second-recorder")
    capture = threading.Thread(target=snapshot, name="capture")
    first.start()
    try:
        assert first_paused.wait(3)
        second.start()
        assert lock.progress.wait(3)
        # This branch also makes the prior unlocked implementation fail with
        # the actual [2, 1] race, rather than depending on scheduler luck.
        if not lock.second_attempted.is_set():
            assert second_finished.wait(3)
        capture.start()
        assert lock.capture_attempted.wait(3)
    finally:
        release_first.set()
        for thread in (first, second, capture):
            if thread.ident is not None:
                thread.join(3)
    assert not any(thread.is_alive() for thread in (first, second, capture))
    assert failures == []
    assert [row["sequence"] for row in observer.events] == [1, 2]
    assert [row["sequence"] for row in captured] == list(range(1, len(captured) + 1))
    assert captured and len(captured) in (1, 2)
    assert _events(observer.events) == {1: returned["first"], 2: returned["second"]}
    for number, label in enumerate(("first", "second"), 1):
        row = observer.events[number - 1]
        assert row is returned[label] and row["payload"] is payloads[label]
        assert row["scope"] == {"label": label} and row["callLabel"] == label
    observer.event("original-return", callSequence=1, name="first", returned={"whole": True})
    assert len(captured) <= 2 and captured[-1]["sequence"] <= 2
    assert observer.events[-1]["callSequence"] == 1


@pytest.mark.parametrize("key", ["sequence", "event", "pid", "threadId", "atNs"])
def test_reserved_metadata_cannot_replace_actual_receipt_or_consume_sequence(key):
    observer = sdk._OriginalObserver({})
    with pytest.raises(ValueError, match="cannot override journal metadata"):
        observer.event("original-call", **{key: "replacement"})
    assert observer.events == [] and observer._sequence == 0
    row = observer.event("original-call", payload={key: "preserved nested value"})
    assert row["sequence"] == 1 and row["payload"][key] == "preserved nested value"


def test_metadata_failure_releases_journal_lock_without_losing_next_sequence(monkeypatch):
    observer = sdk._OriginalObserver({})
    original_ns, actual_error = sdk.time.monotonic_ns, RuntimeError("actual metadata failure")

    def failed_metadata():
        raise actual_error

    monkeypatch.setattr(sdk.time, "monotonic_ns", failed_metadata)
    with pytest.raises(RuntimeError) as caught:
        observer.event("original-call")
    assert caught.value is actual_error
    assert observer.events == [] and observer._sequence == 0
    monkeypatch.setattr(sdk.time, "monotonic_ns", original_ns)
    assert observer.event("original-call")["sequence"] == 1


def test_original_body_encoding_and_functional_callbacks_run_outside_journal_lock(monkeypatch):
    observer = sdk._OriginalObserver({})
    checkpoints = []

    def unlocked(label):
        assert observer._event_lock.acquire(blocking=False), label
        observer._event_lock.release()
        checkpoints.append(label)

    def original_fixture(value):
        unlocked("original-body")
        return {"whole": value, "actual": True}

    observer.codes[original_fixture.__code__] = {"name": "fixture-original", "receiver": None}
    observer.gate_callback = lambda *args: unlocked("functional-gate")

    def functional_profile(frame, event, returned):
        if frame.f_code is original_fixture.__code__:
            unlocked("functional-profile")

    observer.functional_profile = functional_profile
    original_encode = sdk._encode

    def encode(value):
        unlocked("encode")
        return original_encode(value)

    monkeypatch.setattr(sdk, "_encode", encode)
    before = sys.getprofile()
    with observer.call_scope("selected", "search"):
        try:
            sys.setprofile(observer.profile)
            actual = original_fixture(["full", {"nested": 7}])
        finally:
            sys.setprofile(before)
    assert actual == {"whole": ["full", {"nested": 7}], "actual": True}
    assert "original-body" in checkpoints and "encode" in checkpoints
    assert checkpoints.count("functional-gate") == 2
    events = observer.snapshot_events()
    assert [row["event"] for row in events] == ["original-call", "original-return"]
    assert events[1]["callSequence"] == events[0]["sequence"] == 1
    assert events[1]["returned"] == actual


def test_snapshot_copy_never_encodes_or_calls_container_hooks_under_lock():
    observer = sdk._OriginalObserver({})

    class Journal(list):
        def append(self, value):
            pytest.fail("A user append hook ran in the journal critical section")

        def __iter__(self):
            pytest.fail("A user iteration hook ran in the journal critical section")

    class Payload:
        def __deepcopy__(self, memo):
            assert observer._event_lock.acquire(blocking=False)
            observer._event_lock.release()
            return {"whole": "copied only after membership snapshot"}

    observer.events = Journal()
    observer.event("original-call", payload=Payload())
    copied = sdk._observation_copy(observer.snapshot_events())
    assert copied[0]["payload"] == {"whole": "copied only after membership snapshot"}


def test_source_clock_observation_uses_one_joint_membership_cut_before_deep_copy(tmp_path):
    clock = OwnedSourceWriteClock(root=tmp_path, actor="foreground", policy={}, owners={},
        scope=lambda: None, encode=sdk._encode, full_stat=sdk._full_stat)
    later = []

    class DuringCopy:
        def __deepcopy__(self, memo):
            assert clock._event_lock.acquire(blocking=False)
            clock._event_lock.release()
            later.append(clock._event(clock.source_reads, "actual-later-read", fullResult={"bytes": "unchanged"}))
            return {"whole": "copied outside journal lock"}

    clock._event(clock.receipts, "actual-first-receipt", payload=DuringCopy())
    clock._event(clock.original_io, "actual-second-io", fullResult={"bytes": "retained"})
    captured = sdk._source_clock_observation(clock)
    assert captured["sourceClockReceipts"][0]["payload"] == {"whole": "copied outside journal lock"}
    assert captured["sourceClockOriginalIO"][0]["fullResult"] == {"bytes": "retained"}
    assert captured["sourceClockReads"] == captured["sourceClockFailures"] == []
    assert [captured[key][0]["sequence"] for key in ("sourceClockReceipts", "sourceClockOriginalIO")] == [1, 2]
    assert later == clock.source_reads and later[0]["sequence"] == 3
