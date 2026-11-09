"""Real OS replacement guards for the production memory-file read owner."""
import errno
import os
from pathlib import Path

import pytest

from memory_core.config import MemoryConfig
import memory_core.memory_read as memory_read
from memory_core.tools.memory_get import memory_get


@pytest.fixture
def subject(tmp_path):
    workspace, outside = tmp_path / "workspace", tmp_path / "outside"
    (workspace / "memory").mkdir(parents=True)
    outside.mkdir()
    file = workspace / "memory/race.md"
    file.write_bytes(b"Original admitted bytes.\n")
    (outside / "race.md").write_bytes(b"Owned outside sentinel must not be read.\n")
    return workspace, outside, file


def _read(workspace):
    return memory_get(MemoryConfig(workspace_dir=workspace), path="memory/race.md")


def _at_open(monkeypatch, filename, mutation, *, after_open=False):
    original = os.open
    observed = {"calls": 0, "descriptor": None, "flags": None}

    def open_file(path, flags, *args, **kwargs):
        if not isinstance(path, str | os.PathLike) or Path(path) != filename:
            return original(path, flags, *args, **kwargs)
        observed["calls"] += 1
        observed["flags"] = flags
        assert observed["calls"] == 1
        if not after_open:
            mutation()
        descriptor = original(path, flags, *args, **kwargs)
        observed["descriptor"] = descriptor
        if after_open:
            mutation()
        return descriptor

    monkeypatch.setattr(os, "open", open_file)
    return observed


def _assert_closed(observed):
    assert observed["descriptor"] is not None
    with pytest.raises(OSError) as failure:
        os.fstat(observed["descriptor"])
    assert failure.value.errno == errno.EBADF


def test_real_preopen_symlink_replacement_never_reads_the_outside_file(subject, monkeypatch):
    workspace, outside, file = subject

    def mutate():
        file.rename(file.with_name("before.md"))
        file.symlink_to(outside / "race.md")

    observed = _at_open(monkeypatch, file, mutate)
    result = _read(workspace)
    assert observed["flags"] & os.O_NOFOLLOW
    assert observed["flags"] & os.O_NONBLOCK
    assert result == {"path": "memory/race.md", "text": "", "status": "error", "code": "symlink",
                      "error": f"symlink open blocked | ELOOP: too many symbolic links encountered, open '{file}' | ELOOP"}
    assert (outside / "race.md").read_bytes() == b"Owned outside sentinel must not be read.\n"


@pytest.mark.parametrize("after_open", [False, True])
def test_regular_replacement_does_not_substitute_bytes_and_releases_the_descriptor(subject, monkeypatch, after_open):
    workspace, _, file = subject
    replacement = file.with_name("replacement.md")
    replacement.write_bytes(b"A different inode must not be consumed.\n")
    observed = _at_open(monkeypatch, file, lambda: replacement.replace(file), after_open=after_open)
    assert _read(workspace) == {"status": "not_found", "text": "", "path": "memory/race.md"}
    _assert_closed(observed)
    assert file.read_bytes() == b"A different inode must not be consumed.\n"


def test_unlinked_open_file_is_a_miss_and_releases_its_descriptor(subject, monkeypatch):
    workspace, _, file = subject
    observed = _at_open(monkeypatch, file, file.unlink, after_open=True)
    assert _read(workspace) == {"status": "not_found", "text": "", "path": "memory/race.md"}
    _assert_closed(observed)


@pytest.mark.parametrize("replace_root", [False, True])
def test_parent_or_root_replacement_does_not_consume_outside_bytes(subject, monkeypatch, replace_root):
    workspace, outside, file = subject
    if replace_root:
        (outside / "memory").mkdir()
        (outside / "memory/race.md").write_bytes(b"Outside replacement root.\n")

    def mutate():
        source = workspace if replace_root else file.parent
        source.rename(source.with_name("before"))
        source.symlink_to(outside, target_is_directory=True)

    observed = _at_open(monkeypatch, file, mutate)
    assert _read(workspace) == {"status": "not_found", "text": "", "path": "memory/race.md"}
    _assert_closed(observed)


def test_parent_escape_is_refused_even_when_outside_leaf_has_the_admitted_inode(subject, monkeypatch):
    workspace, outside, file = subject
    (outside / "race.md").unlink()
    (outside / "race.md").hardlink_to(file)

    def mutate():
        file.parent.rename(workspace / "before")
        file.parent.symlink_to(outside, target_is_directory=True)

    observed = _at_open(monkeypatch, file, mutate)
    result = _read(workspace)
    assert result["status"] == "error" and result["code"] == "outside-workspace" and result["text"] == ""
    _assert_closed(observed)


def test_nonblocking_open_refuses_a_fifo_replacement_without_reading_it(subject, monkeypatch):
    workspace, _, file = subject

    def mutate():
        file.unlink()
        os.mkfifo(file)

    observed = _at_open(monkeypatch, file, mutate)
    result = _read(workspace)
    assert result["status"] == "error" and result["text"] == ""
    assert result["error"] == "path must be a regular file | not a file | not-file"
    _assert_closed(observed)


def test_admitted_descriptor_is_not_reopened_or_rejected_after_consumption(subject, monkeypatch):
    workspace, _, file = subject
    original = memory_read._read_all
    replacement = file.with_name("replacement.md")
    replacement.write_bytes(b"Later path contents.\n")

    def consume(descriptor):
        data = original(descriptor)
        replacement.replace(file)
        return data

    monkeypatch.setattr(memory_read, "_read_all", consume)
    assert _read(workspace)["text"] == "Original admitted bytes."
    assert file.read_bytes() == b"Later path contents.\n"
