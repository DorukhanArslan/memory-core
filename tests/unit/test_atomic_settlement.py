"""Actual descriptor settlement preserves original errors, files and phase order."""
from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from memory_core.atomic_publication import (
    MemoryAtomicPublicationError,
    append_memory_content,
    commit_memory_content,
    hash_memory_content,
)


def _error(message, code="EIO"):
    error = OSError(message)
    error.name, error.code = "Error", code
    return error


def _observe_stage_io(monkeypatch, target, *, sync_error=None, read_error=None, cleanup_error=None, close_error=None):
    original = {name: getattr(os, name) for name in ("open", "close", "fsync", "read", "unlink")}
    descriptors, stages, events = {}, set(), []
    sync_failure = sync_error

    def open_file(path, flags, *args, **kwargs):
        descriptor = original["open"](path, flags, *args, **kwargs)
        filename = Path(path)
        stage = filename.parent == target.parent and bool(flags & os.O_CREAT and flags & os.O_EXCL)
        descriptors[descriptor] = filename, stage
        if stage:
            stages.add(filename)
        return descriptor

    def sync(descriptor):
        nonlocal sync_failure
        if descriptors.get(descriptor, (None, False))[1]:
            if sync_failure is not None:
                failure, sync_failure = sync_failure, None
                events.append("stage-sync-failed")
                raise failure
            events.append("stage-synced")
        return original["fsync"](descriptor)

    def read(descriptor, *args):
        if descriptors.get(descriptor, (None, False))[0] == target and read_error is not None:
            events.append("target-read-failed")
            raise read_error
        return original["read"](descriptor, *args)

    def unlink(path, *args, **kwargs):
        if Path(path) in stages:
            events.append("stage-cleanup-failed" if cleanup_error is not None else "stage-removed")
            if cleanup_error is not None:
                raise cleanup_error
        return original["unlink"](path, *args, **kwargs)

    def close(descriptor):
        filename, stage = descriptors.pop(descriptor, (None, False))
        if stage:
            events.append(("stage-closed", filename.exists()))
        result = original["close"](descriptor)
        if stage and close_error is not None:
            raise close_error
        return result

    for name, function in (("open", open_file), ("fsync", sync), ("read", read), ("unlink", unlink), ("close", close)):
        monkeypatch.setattr(os, name, function)
    return stages, events


def test_preparation_failure_closes_unadopted_descriptor_before_owned_cleanup(tmp_path, monkeypatch):
    target = tmp_path / "MEMORY.md"
    target.write_text("original\n")
    primary, close = _error("stage sync failed"), _error("stage close failed")
    stages, events = _observe_stage_io(monkeypatch, target, sync_error=primary, close_error=close)
    with pytest.raises(RuntimeError, match="Atomic temp write and close failed") as raised:
        commit_memory_content(target, content="replacement\n", expected_hash=hash_memory_content("original\n"))
    assert raised.value.name == "AggregateError" and raised.value.errors == [primary, close]
    assert events == ["stage-sync-failed", ("stage-closed", True), "stage-removed"]
    assert target.read_bytes() == b"original\n" and not any(path.exists() for path in stages)
    assert not hasattr(raised.value, "publication")


def test_adopted_owner_reports_cleanup_then_close_and_keeps_the_original_primary(tmp_path, monkeypatch):
    target = tmp_path / "MEMORY.md"
    target.write_text("original\n")
    primary, cleanup, close = (_error(message) for message in ("preimage read failed", "cleanup failed", "close failed"))
    stages, events = _observe_stage_io(monkeypatch, target, read_error=primary, cleanup_error=cleanup, close_error=close)
    with pytest.raises(RuntimeError, match="Atomic temp cleanup and close failed") as raised:
        commit_memory_content(target, content="replacement\n", expected_hash=hash_memory_content("original\n"))
    aggregate = raised.value
    assert aggregate.name == "AggregateError" and aggregate.errors[1] is close
    assert aggregate.errors[0].cause is primary
    assert str(aggregate.errors[0]) == "Atomic file replace failed (Error: preimage read failed); cleanup also failed (Error: cleanup failed)"
    assert events == ["stage-synced", "target-read-failed", "stage-cleanup-failed", ("stage-closed", True)]
    assert target.read_bytes() == b"original\n"
    assert len(stages) == 1 and next(iter(stages)).read_bytes() == b"replacement\n"


def test_committed_publication_close_failure_keeps_its_real_commit_receipt(tmp_path, monkeypatch):
    target = tmp_path / "MEMORY.md"
    target.write_text("original\n")
    close = _error("committed close failed")
    stages, events = _observe_stage_io(monkeypatch, target, close_error=close)
    with pytest.raises(MemoryAtomicPublicationError) as raised:
        commit_memory_content(target, content="replacement\n", expected_hash=hash_memory_content("original\n"))
    assert raised.value.publication == "committed" and raised.value.cause is close
    assert target.read_bytes() == b"replacement\n" and not any(path.exists() for path in stages)
    assert events == ["stage-synced", ("stage-closed", False)]


def test_append_preserves_sync_and_real_close_errors_without_rolling_back_bytes(tmp_path, monkeypatch):
    target = tmp_path / "daily.md"
    target.write_bytes(b"before\n")
    inode, close_fd = target.stat().st_ino, []
    primary, close = _error("append sync failed"), _error("append close failed")
    original_sync, original_close = os.fsync, os.close

    def sync(descriptor):
        if os.fstat(descriptor).st_ino == inode:
            raise primary
        return original_sync(descriptor)

    def close_file(descriptor):
        selected = os.fstat(descriptor).st_ino == inode
        result = original_close(descriptor)
        if selected:
            close_fd.append(descriptor)
            raise close
        return result

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "close", close_file)
    with pytest.raises(RuntimeError, match="An error was suppressed during disposal") as raised:
        append_memory_content(target, "new\n")
    assert raised.value.name == "SuppressedError" and raised.value.error is close and raised.value.suppressed is primary
    assert not hasattr(raised.value, "publication") and not hasattr(raised.value, "cause")
    assert target.read_bytes() == b"before\nnew\n"
    with pytest.raises(OSError) as closed:
        os.fstat(close_fd[0])
    assert closed.value.errno == errno.EBADF


def test_append_cleanup_failure_suppresses_the_close_failure_after_the_primary(tmp_path, monkeypatch):
    target = tmp_path / "daily.md"
    primary, close, cleanup = (RuntimeError("authority expired"), _error("close failed"), _error("cleanup failed"))
    original_close = os.close
    checks = 0

    def assert_current():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise primary

    def close_file(descriptor):
        original_close(descriptor)
        raise close

    def unlink(path, *args, **kwargs):
        assert Path(path) == target
        raise cleanup

    monkeypatch.setattr(os, "close", close_file)
    monkeypatch.setattr(os, "unlink", unlink)
    with pytest.raises(RuntimeError, match="An error was suppressed during disposal") as raised:
        append_memory_content(target, "new\n", before_write=assert_current)
    failure = raised.value
    assert failure.name == "SuppressedError" and failure.error is cleanup
    assert failure.suppressed.name == "SuppressedError"
    assert failure.suppressed.error is close and failure.suppressed.suppressed is primary
    assert target.read_bytes() == b"" and not hasattr(failure, "publication")


def test_unadopted_append_admission_preserves_its_rejection_when_its_real_close_also_fails(tmp_path, monkeypatch):
    target = tmp_path / "daily.md"
    target.write_bytes(b"before\n")
    original_open, original_close, original_fstat = os.open, os.close, os.fstat
    descriptors = set()
    primary, close = _error("descriptor admission failed"), _error("unadopted close failed")

    def open_file(path, flags, *args, **kwargs):
        descriptor = original_open(path, flags, *args, **kwargs)
        if Path(path) == target:
            descriptors.add(descriptor)
        return descriptor

    def fstat(descriptor):
        if descriptor in descriptors:
            raise primary
        return original_fstat(descriptor)

    def close_file(descriptor):
        result = original_close(descriptor)
        if descriptor in descriptors:
            raise close
        return result

    monkeypatch.setattr(os, "open", open_file)
    monkeypatch.setattr(os, "fstat", fstat)
    monkeypatch.setattr(os, "close", close_file)
    with pytest.raises(OSError) as raised:
        append_memory_content(target, "new\n")
    assert raised.value is primary and not hasattr(raised.value, "suppressed")
    assert target.read_bytes() == b"before\n"
    with pytest.raises(OSError) as closed:
        original_fstat(next(iter(descriptors)))
    assert closed.value.errno == errno.EBADF


def test_promotion_in_place_final_close_preserves_its_original_overwrite_policy(tmp_path, monkeypatch):
    target = tmp_path / "MEMORY.md"
    target.write_text("original\n")
    original_open, original_close, original_sync = os.open, os.close, os.fsync
    in_place = set()
    syncs = 0
    primary, close = _error("fallback sync failed"), _error("fallback close failed")

    def open_file(path, flags, *args, **kwargs):
        if flags & os.O_EXCL:
            raise _error("staging refused", "EACCES")
        descriptor = original_open(path, flags, *args, **kwargs)
        if Path(path) == target and flags & os.O_RDWR:
            in_place.add(descriptor)
        return descriptor

    def sync(descriptor):
        nonlocal syncs
        if descriptor in in_place:
            syncs += 1
            if syncs == 1:
                raise primary
        return original_sync(descriptor)

    def close_file(descriptor):
        result = original_close(descriptor)
        if descriptor in in_place:
            raise close
        return result

    monkeypatch.setattr(os, "open", open_file)
    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "close", close_file)
    with pytest.raises(OSError) as raised:
        commit_memory_content(target, content="replacement\n", expected_content="original\n",
                              expected_hash=hash_memory_content("original\n"), allow_in_place_fallback=True)
    assert raised.value is close and not hasattr(raised.value, "suppressed")
    assert target.read_bytes() == b"original\n" and syncs == 2
