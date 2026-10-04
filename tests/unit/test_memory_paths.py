from pathlib import Path

import pytest

from memory_core.memory_flush import UnsafeMemoryFlushTargetError, validate_daily_memory_target
from memory_core.memory_paths import (
    UnsafeMemoryPathError,
    is_daily_memory_path,
    parse_dated_memory_path,
    validate_daily_memory_path,
)
from memory_core.workspace import MemoryWorkspace


def test_flush_target_error_is_the_shared_memory_path_error():
    assert UnsafeMemoryFlushTargetError is UnsafeMemoryPathError
    assert issubclass(UnsafeMemoryPathError, ValueError)


@pytest.mark.parametrize(
    "rel_path",
    [
        "memory/2026-05-03.md\n",
        "memory/2026-05-03.md\r\n",
        " memory/2026-05-03.md",
        "memory/2026-05-03.md ",
        "memory/2026-05-03-1430.md",
        "memory/nested/2026-05-03.md",
        "./memory/2026-05-03.md",
        "MEMORY.md",
    ],
)
def test_daily_validator_rejects_everything_but_the_exact_daily_path(rel_path: str):
    assert not is_daily_memory_path(rel_path)
    with pytest.raises(UnsafeMemoryPathError):
        validate_daily_memory_path(rel_path)
    with pytest.raises(UnsafeMemoryPathError):
        validate_daily_memory_target(rel_path)


def test_append_daily_memory_rejects_trailing_newline_path(tmp_path: Path):
    # Regression: re.match with a `$` anchor accepted "memory/YYYY-MM-DD.md\n" and
    # created a file whose name ends in a newline.
    workspace = MemoryWorkspace(tmp_path)

    with pytest.raises(UnsafeMemoryPathError):
        workspace.append_daily_memory("memory/2026-05-03.md\n", "- bad")

    assert not (tmp_path / "memory").exists()


def test_dated_memory_path_parser_follows_js_end_anchor():
    # temporal-decay.ts DATED_MEMORY_PATH_RE: `$` without the m flag never matches
    # before a trailing newline.
    assert parse_dated_memory_path("memory/2026-05-03.md") == (2026, 5, 3)
    assert parse_dated_memory_path("agents/memory/2026-05-03.md") == (2026, 5, 3)
    assert parse_dated_memory_path("memory/2026-05-03.md\n") is None
    # v2026.9.6: a suffix and subdirectories still make a dated file.
    assert parse_dated_memory_path("memory/2026-05-03-1430.md") == (2026, 5, 3)
    assert parse_dated_memory_path("memory/a/b/2026-05-03-notes.md") == (2026, 5, 3)
    assert parse_dated_memory_path("memory/topics/2026-05-03.md") == (2026, 5, 3)
