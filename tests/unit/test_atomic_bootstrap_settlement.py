"""Real exclusive publication retains its actual dispatch and settlement domain."""
from __future__ import annotations

import errno
import os
from pathlib import Path
import stat
import sys

import pytest

from memory_core import atomic_publication as publication
from memory_core.bootstrap.lifecycle import _write_file_if_missing


def _error(message):
    error = OSError(message)
    error.name, error.code = "Error", "EIO"
    return error


@pytest.mark.skipif(sys.platform not in {"linux", "darwin"}, reason="The native retained-directory ABI is POSIX")
def test_exclusive_rename_is_one_real_no_replace_syscall_and_keeps_a_foreign_winner(tmp_path):
    source, target = tmp_path / "stage", tmp_path / "AGENTS.md"
    source.write_bytes(b"complete private stage")
    target.write_bytes(b"existing winner")
    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(OSError) as refused:
            publication._rename_no_replace(parent, source.name, target.name)
        assert refused.value.errno == errno.EEXIST
        assert source.read_bytes() == b"complete private stage" and target.read_bytes() == b"existing winner"
        target.unlink()
        publication._rename_no_replace(parent, source.name, target.name)
    finally:
        os.close(parent)
    assert not source.exists() and target.read_bytes() == b"complete private stage"
    assert target.stat().st_nlink == 1


def test_unavailable_exclusive_abi_fails_before_creating_any_stage_or_target(tmp_path, monkeypatch):
    monkeypatch.setattr(publication.sys, "platform", "unsupported")
    with pytest.raises(publication.MemoryPublicationPathError) as raised:
        _write_file_if_missing(tmp_path / "AGENTS.md", "complete bootstrap\n")
    assert raised.value.code == "helper-unavailable"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("dispatched", [False, True])
def test_real_bootstrap_publication_loss_retains_indeterminate_receipt_without_extra_link(tmp_path, monkeypatch, dispatched):
    target = tmp_path / "AGENTS.md"
    original = publication._rename_no_replace
    failure = _error("literal publication reply failure")

    def rename(parent, source, destination):
        if dispatched:
            original(parent, source, destination)
        raise failure

    monkeypatch.setattr(publication, "_rename_no_replace", rename)
    with pytest.raises(publication.MemoryPublicationPathError) as raised:
        _write_file_if_missing(target, "complete bootstrap\n")
    assert raised.value.code == "invalid-path"
    suppressed = raised.value.cause
    assert suppressed.name == "SuppressedError"
    assert suppressed.suppressed.cause is failure
    assert suppressed.suppressed.details["publication"] == {
        "status": "indeterminate", "basename": "AGENTS.md", "overwrite": False,
    }
    assert suppressed.error.code == "not-removable"
    assert suppressed.error.details["cleanup"]["status"] == "preserved"
    entries = list(tmp_path.iterdir())
    assert len(entries) == 1
    assert entries[0].read_bytes() == b"complete bootstrap\n"
    assert entries[0].stat().st_nlink == 1 and stat.S_IMODE(entries[0].stat().st_mode) == 0o600
    assert target.exists() is dispatched
    if dispatched:
        assert entries == [target]
    else:
        assert entries[0].name.startswith(".fs-safe-")


def _observe_stage(monkeypatch, target, *, fail_sync=None, fail_cleanup=None, fail_close=None):
    original = {name: getattr(os, name) for name in ("open", "close", "fsync", "unlink")}
    stages, descriptors, closes = set(), {}, []

    def open_file(path, flags, *args, **kwargs):
        descriptor = original["open"](path, flags, *args, **kwargs)
        stage = bool(flags & os.O_CREAT and flags & os.O_EXCL)
        descriptors[descriptor] = Path(path), stage
        if stage:
            stages.add(Path(path))
        return descriptor

    def sync(descriptor):
        if descriptors.get(descriptor, (None, False))[1] and fail_sync is not None:
            raise fail_sync
        return original["fsync"](descriptor)

    def unlink(path, *args, **kwargs):
        result = original["unlink"](path, *args, **kwargs)
        if Path(path) in stages and fail_cleanup is not None:
            raise fail_cleanup
        return result

    def close(descriptor):
        filename, stage = descriptors.pop(descriptor, (None, False))
        result = original["close"](descriptor)
        closes.append(filename)
        if stage and fail_close is not None:
            raise fail_close
        return result

    for name, function in (("open", open_file), ("fsync", sync), ("unlink", unlink), ("close", close)):
        monkeypatch.setattr(os, name, function)
    return stages, closes


def test_preparation_and_delegated_cleanup_failures_both_survive_the_real_caller(tmp_path, monkeypatch):
    target = tmp_path / "AGENTS.md"
    sync, cleanup = _error("literal preparation failure"), _error("literal cleanup reply failure")
    stages, closes = _observe_stage(monkeypatch, target, fail_sync=sync, fail_cleanup=cleanup)
    with pytest.raises(publication.MemoryPublicationPathError) as raised:
        _write_file_if_missing(target, "complete bootstrap\n")
    error = raised.value
    assert error.code == "helper-failed" and error.details["phase"] == "prepare"
    assert error.cause.name == "AggregateError" and error.cause.errors[0] is sync
    cleanup_error = error.cause.errors[1]
    assert cleanup_error.cause is cleanup
    assert cleanup_error.details["phase"] == "cleanup"
    assert error.details["cleanup"]["status"] == "failed"
    assert error.details["cleanup"]["resources"] == "closed"
    assert all(stage in closes for stage in stages) and tmp_path in closes
    assert list(tmp_path.iterdir()) == []


def test_published_bootstrap_close_failure_keeps_receipt_and_attempts_parent_close(tmp_path, monkeypatch):
    target = tmp_path / "AGENTS.md"
    failure = _error("literal close reply failure")
    stages, closes = _observe_stage(monkeypatch, target, fail_close=failure)
    with pytest.raises(publication.MemoryPublicationPathError) as raised:
        _write_file_if_missing(target, "complete bootstrap\n")
    error = raised.value
    assert error.cause is failure and error.details["phase"] == "cleanup"
    assert error.details["publication"]["status"] == "published"
    assert error.details["cleanup"]["status"] == "not-needed"
    assert error.details["cleanup"]["resources"] == "close-failed"
    assert all(stage in closes for stage in stages) and tmp_path in closes
    assert target.read_bytes() == b"complete bootstrap\n" and list(tmp_path.iterdir()) == [target]


def test_foreign_stage_name_is_preserved_with_real_original_parked_inode(tmp_path, monkeypatch):
    target = tmp_path / "AGENTS.md"
    failure = _error("literal stage sync failure")
    stages, _ = _observe_stage(monkeypatch, target, fail_sync=failure)
    lstat = os.lstat
    parked = tmp_path / "parked-original"
    replaced = False

    def inspect(path, *args, **kwargs):
        nonlocal replaced
        if Path(path) in stages and not replaced:
            replaced = True
            os.rename(path, parked)
            Path(path).write_bytes(b"foreign winner")
        return lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", inspect)
    with pytest.raises(publication.MemoryPublicationPathError) as raised:
        _write_file_if_missing(target, "complete bootstrap\n")
    assert raised.value.cause is failure and raised.value.details["phase"] == "prepare"
    assert raised.value.details["cleanup"]["status"] == "preserved"
    stage = next(iter(stages))
    assert stage.read_bytes() == b"foreign winner" and parked.read_bytes() == b"complete bootstrap\n"
    assert stage.stat().st_ino != parked.stat().st_ino
    assert not target.exists()
