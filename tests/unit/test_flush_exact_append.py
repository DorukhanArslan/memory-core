"""Exact flush append bytes and ownership boundaries; curator writes stay distinct."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import os
from pathlib import Path

import pytest

from memory_core.consolidation.artifact_provenance import MemoryArtifactProvenanceStore
from memory_core.memory_paths import UnsafeMemoryPathError
from memory_core.memory_write_provenance import MemoryWriteProvenanceObserver
from memory_core.workspace import append_daily_memory_file, append_memory_flush_file


TARGET = "memory/2026-09-25.md"


@pytest.mark.parametrize(("before", "content", "expected"), [
    (None, "", b""),
    (b"", "NO_REPLY", b"NO_REPLY"),
    (b"", "  \r\n", b"  \r\n"),
    (b"first", "second", b"first\nsecond"),
    (b"first\n", "second", b"first\nsecond"),
    (b"first", "\nsecond", b"first\nsecond"),
    (b"first\r", "second\r\n\r\n", b"first\r\nsecond\r\n\r\n"),
    (b"first", "", b"first"),
    (b"first\n", "", b"first\n"),
    (b"\xfffirst", "😀\ud800", b"\xfffirst\n\xf0\x9f\x98\x80\xef\xbf\xbd"),
])
def test_flush_append_preserves_exact_native_content_bytes(tmp_path, before, content, expected):
    target = tmp_path / TARGET
    if before is not None:
        target.parent.mkdir()
        target.write_bytes(before)

    assert append_memory_flush_file(tmp_path, TARGET, content) == target
    assert target.read_bytes() == expected


def _observer(root: Path, store: MemoryArtifactProvenanceStore):
    return MemoryWriteProvenanceObserver(
        store=store, mutation_root=root, workspace_dir=root,
        resolve_origin_class=lambda: "agent", session_id="s1", session_key="agent:main:main",
        now=lambda: 1_790_375_400_000,
    )


def test_flush_and_curated_daily_appends_keep_their_respective_contracts(tmp_path):
    append_daily_memory_file(tmp_path, TARGET, "first\r\n\r\n")
    append_memory_flush_file(tmp_path, TARGET, "second\r\n\r\n")
    assert (tmp_path / TARGET).read_bytes() == b"first\nsecond\r\n\r\n"


def test_provenance_uses_exact_append_text_and_records_even_empty_append(tmp_path):
    store = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    observer = _observer(tmp_path, store)
    append_memory_flush_file(tmp_path, TARGET, "first\n", provenance=observer)
    append_memory_flush_file(tmp_path, TARGET, "second", provenance=observer)
    record = dict(store.list(tmp_path))[TARGET]
    assert record.file_hash == hashlib.sha256(b"first\nsecond").hexdigest()
    assert record.origin_class == "agent"
    append_memory_flush_file(tmp_path, TARGET, "", provenance=observer)
    # The original wrapper projects a separator for empty content; fs-safe itself
    # does not append one. Keep this upstream edge visible rather than repairing it.
    assert (tmp_path / TARGET).read_bytes() == b"first\nsecond"
    assert dict(store.list(tmp_path))[TARGET].file_hash == hashlib.sha256(b"first\nsecond\n").hexdigest()


def test_authority_failure_after_provenance_reservation_rolls_back_without_bytes(tmp_path):
    target = tmp_path / TARGET
    target.parent.mkdir()
    target.write_bytes(b"first")
    store = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    observer = _observer(tmp_path, store)
    revoked = asyncio.CancelledError("revoked after reservation")

    def assert_current():
        if dict(store.list(tmp_path)):
            raise revoked

    with pytest.raises(asyncio.CancelledError) as caught:
        append_memory_flush_file(tmp_path, TARGET, "second", provenance=observer,
                                 assert_current=assert_current)
    assert caught.value is revoked
    assert target.read_bytes() == b"first"
    assert dict(store.list(tmp_path)) == {}


def test_revocation_after_real_open_closes_descriptor_and_removes_new_unwritten_file(tmp_path, monkeypatch):
    original_open = os.open
    opened = []
    revoked = RuntimeError("revoked after open")

    def track_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def assert_current():
        if opened:
            raise revoked

    monkeypatch.setattr(os, "open", track_open)
    with pytest.raises(RuntimeError) as caught:
        append_memory_flush_file(tmp_path, TARGET, "second", assert_current=assert_current)
    assert caught.value is revoked
    assert not (tmp_path / TARGET).exists()
    assert opened
    for descriptor in opened:
        with pytest.raises(OSError) as closed:
            os.fstat(descriptor)
        assert closed.value.errno == errno.EBADF


def test_partial_writes_are_completed_and_file_sync_precedes_return(tmp_path, monkeypatch):
    original_write, original_fsync = os.write, os.fsync
    synced = []

    def short_write(descriptor, payload):
        return original_write(descriptor, payload[:2])

    def sync(descriptor):
        synced.append(os.fstat(descriptor).st_size)
        return original_fsync(descriptor)

    monkeypatch.setattr(os, "write", short_write)
    monkeypatch.setattr(os, "fsync", sync)
    append_memory_flush_file(tmp_path, TARGET, "second")
    assert (tmp_path / TARGET).read_bytes() == b"second"
    assert synced[0] == len(b"second")


def test_sync_failure_retains_committed_bytes_and_rolls_back_provenance(tmp_path, monkeypatch):
    store = MemoryArtifactProvenanceStore(tmp_path / "provenance.sqlite")
    observer = _observer(tmp_path, store)

    def fail_sync(_descriptor):
        raise OSError(errno.EIO, "sync failed")

    monkeypatch.setattr(os, "fsync", fail_sync)
    with pytest.raises(OSError, match="sync failed"):
        append_memory_flush_file(tmp_path, TARGET, "second", provenance=observer)
    assert (tmp_path / TARGET).read_bytes() == b"second"
    assert dict(store.list(tmp_path)) == {}


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "parent-symlink"])
def test_exact_append_retains_stricter_path_admission(tmp_path, kind):
    outside = tmp_path / "outside.md"
    outside.write_text("outside")
    target = tmp_path / TARGET
    if kind == "parent-symlink":
        (tmp_path / "memory").symlink_to(tmp_path, target_is_directory=True)
    else:
        target.parent.mkdir()
        if kind == "symlink":
            target.symlink_to(outside)
        else:
            os.link(outside, target)
    with pytest.raises(UnsafeMemoryPathError):
        append_memory_flush_file(tmp_path, TARGET, "second")
    assert outside.read_bytes() == b"outside"
