"""memory_core.memory_read: the readMemoryFile rules the oracle fixtures cannot reach.

The oracle compares ordinary reads, refusals and fs-safe resolve errors with the real
TypeScript (tests/integration/test_openclaw_ts_oracle.py, memory_get tests). These cover what a
fixture cannot set up reliably or where the message text differs by design: operating-system
errors (Python's message, the errno name as code, decision D6), the transient-read retry, a file
that changes or vanishes during the read, the root checks and the error-detail escaping.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

import memory_core.memory_read as memory_read
from memory_core.config import MemoryConfig
from memory_core.memory_read import (
    MemoryReadError,
    build_memory_read_result,
    format_error_detail,
    read_memory_file,
    retry_transient_memory_read,
)
from memory_core.tools.common import extract_error_code, format_error_message
from memory_core.tools.memory_get import memory_get


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    (root / "memory" / "a.md").write_text("one\ntwo\n", encoding="utf-8")
    return root


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads files regardless of their mode")
def test_an_unreadable_file_is_an_error_with_the_errno_name_as_code(tmp_path: Path):
    root = _workspace(tmp_path)
    locked = root / "memory" / "locked.md"
    locked.write_text("secret", encoding="utf-8")
    locked.chmod(0)
    try:
        result = memory_get(MemoryConfig(workspace_dir=root), path="memory/locked.md")
    finally:
        locked.chmod(0o600)

    # Upstream: code "EACCES", error "EACCES: permission denied, open '<abs>'"; memory-core keeps
    # Python's message (documented deviation, D6).
    assert result == {
        "path": "memory/locked.md",
        "text": "",
        "status": "error",
        "code": "EACCES",
        "error": f"[Errno {errno.EACCES}] Permission denied: '{locked}'",
    }


def test_a_too_long_name_is_invalid_path(tmp_path: Path):
    root = _workspace(tmp_path)
    name = "memory/" + "a" * 300 + ".md"

    result = memory_get(MemoryConfig(workspace_dir=root), path=name)

    assert (result["status"], result["code"]) == ("error", "invalid-path")
    assert result["error"].startswith("relative path is too long | [Errno ")
    assert result["error"].endswith(" | ENAMETOOLONG")


def test_transient_read_errors_are_retried_twice_with_25_and_50_ms_delays():
    delays: list[float] = []
    attempts: list[int] = []

    def flaky() -> bytes:
        attempts.append(1)
        if len(attempts) < 3:
            raise BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable")
        return b"ok"

    assert retry_transient_memory_read(flaky, sleep=delays.append) == b"ok"
    assert delays == [0.025, 0.05]

    attempts.clear()
    delays.clear()

    def always() -> bytes:
        attempts.append(1)
        raise OSError(errno.EDEADLK, "Resource deadlock avoided")

    with pytest.raises(OSError):
        retry_transient_memory_read(always, sleep=delays.append)
    assert (len(attempts), delays) == (3, [0.025, 0.05])


def test_other_errors_and_the_libuv_text_follow_the_transient_rule():
    delays: list[float] = []
    with pytest.raises(PermissionError):
        retry_transient_memory_read(
            lambda: (_ for _ in ()).throw(PermissionError(errno.EACCES, "denied")),
            sleep=delays.append,
        )
    assert delays == []
    assert memory_read.is_transient_memory_read_error(RuntimeError("unknown system error -11"))
    assert not memory_read.is_transient_memory_read_error(RuntimeError("unknown system error -110"))


def test_a_file_that_vanishes_at_open_is_not_found(tmp_path: Path, monkeypatch):
    root = _workspace(tmp_path)
    real_open = os.open

    def vanished(path, flags, *args, **kwargs):
        if str(path).endswith("a.md"):
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", str(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(memory_read.os, "open", vanished)

    # fs-safe readRegularFile: path-mismatch "File changed during read", which readMemoryFile's
    # isFileDisappearedDuringReadError turns into not_found (read-file.ts:72-82, 180-182).
    assert read_memory_file(root, "memory/a.md") == {
        "status": "not_found",
        "text": "",
        "path": "memory/a.md",
    }


def test_a_file_replaced_between_stat_and_open_is_not_found(tmp_path: Path, monkeypatch):
    root = _workspace(tmp_path)
    other = root / "memory" / "other.md"
    other.write_text("other\n", encoding="utf-8")
    real_open = os.open

    def swapped(path, flags, *args, **kwargs):
        if str(path).endswith("a.md"):
            return real_open(other, flags, *args, **kwargs)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(memory_read.os, "open", swapped)

    assert read_memory_file(root, "memory/a.md")["status"] == "not_found"


def test_missing_and_non_directory_roots(tmp_path: Path):
    assert read_memory_file(tmp_path / "absent", "MEMORY.md") == {
        "status": "not_found",
        "text": "",
        "path": "MEMORY.md",
    }
    not_a_dir = tmp_path / "file-root"
    not_a_dir.write_text("x", encoding="utf-8")
    with pytest.raises(MemoryReadError) as raised:
        read_memory_file(not_a_dir, "MEMORY.md")
    assert (raised.value.code, str(raised.value)) == ("invalid-path", "root dir is not a directory")


def test_refusal_messages_escape_control_characters(tmp_path: Path):
    root = _workspace(tmp_path)
    outside = tmp_path / "out"
    outside.mkdir()
    try:
        (root / "memory" / "li\x01nk").symlink_to(outside)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not supported on this platform: {exc}")

    result = memory_get(MemoryConfig(workspace_dir=root), path="memory/li\x01nk/x.md")

    assert result["code"] == "outside-workspace"
    assert result["error"] == (
        f"file is outside workspace root | Symlink escapes root ({root}): {root}/memory/li\\u0001nk"
    )
    assert format_error_detail("a b\x7fc") == "a\\u2028b\\u007fc"


def test_error_codes_and_the_cause_chain_follow_error_coercion():
    class Coded(Exception):
        code = 409

    top = MemoryReadError("wrapper: disk failed", code="outside-workspace")
    top.__cause__ = MemoryReadError("disk failed", code="ENOTDIR")

    assert extract_error_code(top) == "outside-workspace"
    assert extract_error_code(Coded("x")) == "409"
    assert extract_error_code(FileNotFoundError(errno.ENOENT, "gone")) == "ENOENT"
    assert extract_error_code(ValueError("plain")) is None
    # The cause text is already in the message, so only its code is appended
    # (error-coercion.ts:152-162).
    assert format_error_message(top) == "wrapper: disk failed | ENOTDIR"


def test_the_read_result_counts_utf16_units_and_keeps_the_notice_for_an_empty_cut():
    # "\U0001f600" is two UTF-16 units: a 1-unit budget cuts it away entirely, and the notice
    # still follows because the single line was hard-truncated (read-file-shared.ts:79).
    assert build_memory_read_result(
        content="\U0001f600tail", rel_path="memory/e.md", max_chars=1, suggest_read_fallback=True
    ) == {
        "status": "ok",
        "text": "\n\n[More content available. Requested excerpt exceeded the default maxChars "
        "budget. If you need the full raw line, use read on the source file.]",
        "path": "memory/e.md",
        "from": 1,
        "lines": 1,
        "truncated": True,
    }
    assert build_memory_read_result(content="a\nb\n", rel_path="m.md", lines=2) == {
        "status": "ok",
        "text": "a\nb",
        "path": "m.md",
        "from": 1,
        "lines": 2,
    }
