"""Atomic fixture-clock journals over real threads; no original engines run."""
import os
import threading
from types import SimpleNamespace

import pytest

from equivalence import forget_index_fence_sdk_clock as module
from equivalence.forget_index_fence_sdk import _encode, _full_stat
from equivalence.forget_index_fence_sdk_clock import OwnedSourceWriteClock


def clock(root, **callbacks):
    return OwnedSourceWriteClock(root=root, actor="promoter", policy={"protocol": "owned-source-write-clock-v2"},
        owners={}, scope=callbacks.get("scope", lambda: None), encode=callbacks.get("encode", _encode),
        full_stat=callbacks.get("full_stat", _full_stat))


class ObservedLock:
    """Expose an actual second-thread lock attempt without replacing its mutex."""

    def __init__(self, actual, second_ident, attempted):
        self.actual, self.second_ident, self.attempted = actual, second_ident, attempted

    def __enter__(self):
        if threading.get_ident() == self.second_ident[0]:
            self.attempted.set()
        return self.actual.__enter__()

    def __exit__(self, *arguments):
        return self.actual.__exit__(*arguments)

    def locked(self):
        return self.actual.locked()


@pytest.mark.parametrize("second_collection", ["original_io", "source_reads", "receipts", "failures"])
def test_real_threads_publish_sequence_and_complete_rows_as_one_journal_prefix(tmp_path, monkeypatch, second_collection):
    recorder = clock(tmp_path)
    seed = recorder._event(recorder.receipts, "actual-seed", originalValue={"bytes": b"seed"})
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    first_ident, second_ident = [None], [None]
    original_clock = module.time.monotonic_ns
    values = {"first": {"original": b"complete first value", "scope": {"kind": "watch", "label": "first"}},
              "second": {"original": b"complete second value", "scope": {"kind": "watch", "label": "second"}}}
    result, errors = {}, []
    recorder._event_lock = ObservedLock(recorder._event_lock, second_ident, attempted)

    def checkpoint():
        if threading.get_ident() == first_ident[0]:
            entered.set()
            assert release.wait(5), "First recorder thread was never released"
        return original_clock()

    def record(which, collection, ident):
        ident[0] = threading.get_ident()
        try:
            result[which] = recorder._event(collection, "actual-" + which,
                originalValue=values[which], sourceThreadId=ident[0])
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(module.time, "monotonic_ns", checkpoint)
    first = threading.Thread(target=record, args=("first", recorder.original_io, first_ident))
    second = threading.Thread(target=record, args=("second", getattr(recorder, second_collection), second_ident))
    first.start()
    try:
        assert entered.wait(5)
        second.start()
        assert attempted.wait(5)
        # The timestamp checkpoint is after next-sequence allocation and before
        # complete append. No collection can expose that incomplete event.
        assert list.copy(recorder.receipts) == [seed]
        assert list.copy(recorder.original_io) == []
        assert list.copy(recorder.source_reads) == []
        assert list.copy(recorder.failures) == []
        assert result == {}
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert [seed["sequence"], result["first"]["sequence"], result["second"]["sequence"]] == [1, 2, 3]
    assert result["first"]["originalValue"] is values["first"]
    assert result["second"]["originalValue"] is values["second"]
    assert int(result["first"]["atNs"]) <= int(result["second"]["atNs"])
    assert result["first"]["sourceThreadId"] == first_ident[0]
    assert result["second"]["sourceThreadId"] == second_ident[0]
    assert all(row["pid"] == os.getpid() and row["actor"] == "promoter"
               for row in (seed, result["first"], result["second"]))
    snapshot = recorder.snapshot_journals()
    assert set(snapshot) == {"receipts", "original_io", "source_reads", "failures"}
    assert sum(map(len, snapshot.values())) == 3
    assert snapshot["original_io"][0] is result["first"]
    assert snapshot[second_collection][-1] is result["second"]
    later = recorder._event(recorder.source_reads, "actual-later", originalValue=b"later value")
    assert later["sequence"] == 4
    assert sum(map(len, snapshot.values())) == 3
    result["first"]["actualSettlement"] = {"returned": None}
    assert snapshot["original_io"][0]["actualSettlement"] == {"returned": None}


def test_snapshot_waits_for_complete_event_and_copies_all_journal_memberships_together(tmp_path, monkeypatch):
    recorder = clock(tmp_path)
    original = module.time.monotonic_ns
    entered, release, attempted, completed = (threading.Event() for _ in range(4))
    writer_ident, snapshot_ident = [None], [None]
    recorder._event_lock = ObservedLock(recorder._event_lock, snapshot_ident, attempted)
    result, errors = {}, []

    def checkpoint():
        if threading.get_ident() == writer_ident[0]:
            entered.set()
            assert release.wait(5)
        return original()

    def writer():
        writer_ident[0] = threading.get_ident()
        try:
            result["event"] = recorder._event(recorder.original_io, "actual-io", originalReturn=b"complete bytes")
        except BaseException as error:
            errors.append(error)

    def reader():
        snapshot_ident[0] = threading.get_ident()
        try:
            result["snapshot"] = recorder.snapshot_journals()
            completed.set()
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(module.time, "monotonic_ns", checkpoint)
    first, second = threading.Thread(target=writer), threading.Thread(target=reader)
    first.start()
    try:
        assert entered.wait(5)
        second.start()
        assert attempted.wait(5)
        assert not completed.is_set()
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert result["snapshot"] == {"receipts": [], "original_io": [result["event"]], "source_reads": [], "failures": []}
    assert result["event"]["sequence"] == 1


@pytest.mark.parametrize("field", ["sequence", "pid", "actor", "atNs"])
def test_payload_cannot_override_journal_metadata_or_consume_sequence(tmp_path, field):
    recorder = clock(tmp_path)
    with pytest.raises(ValueError, match="cannot replace journal metadata"):
        recorder._event(recorder.original_io, "actual", **{field: "forged"})
    assert recorder.sequence == 0
    assert all(not rows for rows in recorder.snapshot_journals().values())
    assert recorder._event(recorder.original_io, "actual-after-refusal")["sequence"] == 1


def test_failed_metadata_capture_releases_lock_without_publishing_a_partial_row(tmp_path, monkeypatch):
    recorder = clock(tmp_path)
    original = module.time.monotonic_ns

    def failed_metadata():
        raise RuntimeError("actual metadata recorder failure")

    monkeypatch.setattr(module.time, "monotonic_ns", failed_metadata)
    with pytest.raises(RuntimeError, match="actual metadata recorder failure"):
        recorder._event(recorder.original_io, "actual")
    assert not recorder._event_lock.locked()
    assert recorder.sequence == 0
    assert all(not rows for rows in recorder.snapshot_journals().values())
    monkeypatch.setattr(module.time, "monotonic_ns", original)
    assert recorder._event(recorder.original_io, "actual-after-failure")["sequence"] == 1


def test_journal_lock_is_released_before_callbacks_and_actual_source_clock_operation(tmp_path):
    holder, callbacks = {}, []

    def unlocked(kind, value):
        recorder = holder["clock"]
        assert not recorder._event_lock.locked()
        callbacks.append(kind)
        return value

    def scope():
        return unlocked("scope", {"kind": "promotion", "label": "source", "wallClockNowMs": 1794614400000})

    def encode(value):
        unlocked("encode", None)
        return _encode(value)

    def full_stat(value):
        unlocked("full-stat", None)
        return _full_stat(value)

    recorder = holder["clock"] = clock(tmp_path, scope=scope, encode=encode, full_stat=full_stat)
    tick = {"ordinal": 1, "actor": "promoter", "wallClockNowMs": 1794614400000,
            "mtimeMs": 1794528001000, "atimeMs": 1794528001000}
    recorder.policy["ticksByCall"] = {"promotion:source": tick}
    original_utime = recorder.original_os["utime"]

    def actual_utime(*arguments, **options):
        unlocked("original-utime", None)
        return original_utime(*arguments, **options)

    recorder.original_os["utime"] = actual_utime
    stage = tmp_path / ".actual-stage.tmp"
    payload = b"Whole original fixture-owned source bytes.\n"
    stage.write_bytes(payload)
    frame = SimpleNamespace(f_code=test_journal_lock_is_released_before_callbacks_and_actual_source_clock_operation.__code__, f_back=None)
    receipt = recorder._clock(frame=frame, mode="atomic-closed-stage", path=tmp_path / "MEMORY.md", stage=stage,
        descriptor=None, state={"expectedBytes": payload.hex()}, original_arguments=(str(stage), "whole original value"))
    assert receipt is recorder.receipts[0]
    assert receipt["utimeReturn"] is None
    assert receipt["before"]["bytes"] == receipt["after"]["bytes"] == payload.hex()
    assert stage.stat().st_mtime_ns == stage.stat().st_atime_ns == tick["mtimeMs"] * 1_000_000
    assert stage.read_bytes() == payload
    assert {"scope", "encode", "full-stat", "original-utime"} <= set(callbacks)
    assert not recorder._event_lock.locked()
