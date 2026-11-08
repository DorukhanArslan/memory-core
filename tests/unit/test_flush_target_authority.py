"""Authority revocation and filesystem failure boundaries of flush target setup."""

from concurrent.futures import ThreadPoolExecutor
import errno
import os
from pathlib import Path

import pytest

from memory_core.memory_flush import ensure_memory_flush_target_file
from memory_core.memory_paths import UnsafeMemoryPathError
from memory_core.workspace import workspace_file_lock


RELATIVE_TARGET = "memory/2026-09-25.md"


def assert_descriptor_closed(descriptor: int) -> None:
    with pytest.raises(OSError) as caught:
        os.fstat(descriptor)
    assert caught.value.errno == errno.EBADF


@pytest.mark.parametrize("existing", [None, b"- kept\r\n\x00"])
def test_authority_observes_setup_stages_and_the_open_descriptor(tmp_path, monkeypatch, existing):
    target = tmp_path / RELATIVE_TARGET
    if existing is not None:
        target.parent.mkdir()
        target.write_bytes(existing)
    original_open = os.open
    descriptors = []
    observations = []

    def track_open(path, flags, mode=0o777):
        descriptor = original_open(path, flags, mode)
        descriptors.append(descriptor)
        return descriptor

    def assert_current():
        observations.append((target.parent.exists(), target.exists()))
        if len(observations) == 3:
            assert os.fstat(descriptors[0]).st_size == len(existing or b"")

    monkeypatch.setattr(os, "open", track_open)

    result = ensure_memory_flush_target_file(
        tmp_path, RELATIVE_TARGET, assert_current=assert_current
    )

    assert result == target
    assert observations == (
        [(False, False), (True, False), (True, True)]
        if existing is None
        else [(True, True)] * 3
    )
    assert target.read_bytes() == (existing or b"")
    assert len(descriptors) == 1
    assert_descriptor_closed(descriptors[0])


@pytest.mark.parametrize("fail_at", [1, 2, 3])
@pytest.mark.parametrize("existing", [None, b"- existing note\n"])
def test_revocation_stops_setup_at_its_boundary_and_closes_an_open_file(
    tmp_path, monkeypatch, fail_at, existing
):
    target = tmp_path / RELATIVE_TARGET
    if existing is not None:
        target.parent.mkdir()
        target.write_bytes(existing)
    revoked = RuntimeError("authority revoked")
    checks = 0
    descriptors = []
    original_open = os.open

    def track_open(path, flags, mode=0o777):
        descriptor = original_open(path, flags, mode)
        descriptors.append(descriptor)
        return descriptor

    def assert_current():
        nonlocal checks
        checks += 1
        if checks == fail_at:
            raise revoked

    monkeypatch.setattr(os, "open", track_open)

    with pytest.raises(RuntimeError) as caught:
        ensure_memory_flush_target_file(tmp_path, RELATIVE_TARGET, assert_current=assert_current)

    assert caught.value is revoked
    assert checks == fail_at
    assert target.parent.exists() == (existing is not None or fail_at > 1)
    assert target.exists() == (existing is not None or fail_at == 3)
    if target.exists():
        assert target.read_bytes() == (existing or b"")
    assert len(descriptors) == (1 if fail_at == 3 else 0)
    for descriptor in descriptors:
        assert_descriptor_closed(descriptor)


def test_initial_revocation_does_not_wait_for_another_writer(tmp_path):
    revoked = RuntimeError("authority already revoked")
    lock = workspace_file_lock(tmp_path.resolve(), RELATIVE_TARGET)

    def assert_current():
        raise revoked

    with ThreadPoolExecutor(max_workers=1) as executor:
        lock.acquire()
        try:
            result = executor.submit(
                ensure_memory_flush_target_file,
                tmp_path,
                RELATIVE_TARGET,
                assert_current=assert_current,
            )
            with pytest.raises(RuntimeError) as caught:
                result.result(timeout=2)
            assert caught.value is revoked
        finally:
            lock.release()
    assert not (tmp_path / "memory").exists()


def test_callback_return_value_does_not_replace_raising_to_revoke(tmp_path):
    target = ensure_memory_flush_target_file(
        tmp_path, RELATIVE_TARGET, assert_current=lambda: False
    )

    assert target.read_bytes() == b""


@pytest.mark.parametrize(
    "relative_path",
    ["", " \ufeff ", "/tmp/flush-target.md", "../escape.md", "memory/../../escape.md", ".", "..cache.md"],
)
def test_invalid_path_is_rejected_before_checking_authority(tmp_path, relative_path):
    checks = []

    with pytest.raises(UnsafeMemoryPathError):
        ensure_memory_flush_target_file(
            tmp_path, relative_path, assert_current=lambda: checks.append(True)
        )

    assert checks == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failed_operation", ["mkdir", "open"])
def test_real_filesystem_error_stops_authority_checks_at_the_failed_operation(
    tmp_path, failed_operation
):
    # A real failing syscall avoids depending on access permissions when running as root.
    long_name = "x" * (os.pathconf(tmp_path, "PC_NAME_MAX") + 1)
    relative_path = (
        f"memory/{long_name}/note.md"
        if failed_operation == "mkdir"
        else f"memory/{long_name}.md"
    )
    checks = []

    with pytest.raises(OSError) as caught:
        ensure_memory_flush_target_file(
            tmp_path, relative_path, assert_current=lambda: checks.append(True)
        )

    assert caught.value.errno == errno.ENAMETOOLONG
    assert len(checks) == (1 if failed_operation == "mkdir" else 2)
    assert list((tmp_path / "memory").iterdir()) == []


@pytest.mark.parametrize("revoked_after_open", [False, True])
def test_close_error_propagates_even_when_authority_check_also_fails(
    tmp_path, monkeypatch, revoked_after_open
):
    close_error = OSError(errno.EIO, "close failed")
    revoked = RuntimeError("authority revoked after open")
    descriptors = []
    checks = 0
    original_close = os.close

    def close_then_fail(descriptor):
        descriptors.append(descriptor)
        original_close(descriptor)
        raise close_error

    def assert_current():
        nonlocal checks
        checks += 1
        if revoked_after_open and checks == 3:
            raise revoked

    monkeypatch.setattr(os, "close", close_then_fail)

    with pytest.raises(OSError) as caught:
        ensure_memory_flush_target_file(tmp_path, RELATIVE_TARGET, assert_current=assert_current)

    assert caught.value is close_error
    assert checks == 3
    assert len(descriptors) == 1
    assert_descriptor_closed(descriptors[0])
    assert (tmp_path / RELATIVE_TARGET).read_bytes() == b""
    if revoked_after_open:
        assert caught.value.__context__ is revoked


@pytest.mark.parametrize(
    "unsafe_kind", ["symlink", "hardlink", "directory", "fifo", "parent_symlink", "parent_file"]
)
def test_authority_callback_preserves_the_existing_write_safeguards(tmp_path, unsafe_kind):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "note.md"
    outside_file.write_bytes(b"- must remain untouched\n")
    target = root / RELATIVE_TARGET
    if unsafe_kind == "parent_symlink":
        target.parent.symlink_to(outside, target_is_directory=True)
    elif unsafe_kind == "parent_file":
        target.parent.write_bytes(b"not a directory")
    else:
        target.parent.mkdir()
        if unsafe_kind == "symlink":
            target.symlink_to(outside_file)
        elif unsafe_kind == "hardlink":
            os.link(outside_file, target)
        elif unsafe_kind == "directory":
            target.mkdir()
        else:
            os.mkfifo(target)
    checks = []

    with pytest.raises(UnsafeMemoryPathError):
        ensure_memory_flush_target_file(
            root, RELATIVE_TARGET, assert_current=lambda: checks.append(True)
        )

    assert checks == [True]
    assert outside_file.read_bytes() == b"- must remain untouched\n"
    assert not (outside / Path(RELATIVE_TARGET).name).exists()
