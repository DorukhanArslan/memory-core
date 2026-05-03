from pathlib import Path

import pytest

from memory_core.workspace import MemoryWorkspace, UnsafeMemoryPathError


def test_discovers_root_and_dated_memory_files(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("# Long\n", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-05-03.md").write_text("# Day\n", encoding="utf-8")
    (tmp_path / "memory" / "abcd-ef-gh.md").write_text("skip\n", encoding="utf-8")
    (tmp_path / "memory" / "notes.txt").write_text("skip\n", encoding="utf-8")

    workspace = MemoryWorkspace(tmp_path)

    assert [entry.rel_path for entry in workspace.discover_memory_files()] == [
        "MEMORY.md",
        "memory/2026-05-03.md",
    ]


def test_discovery_skips_dated_symlink_that_escapes_workspace(tmp_path: Path):
    outside_file = tmp_path.parent / "outside-memory.md"
    outside_file.write_text("# Outside\n", encoding="utf-8")
    (tmp_path / "memory").mkdir()
    symlink_path = tmp_path / "memory" / "2026-05-04.md"
    try:
        symlink_path.symlink_to(outside_file)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks are not supported on this platform: {exc}")

    workspace = MemoryWorkspace(tmp_path)

    assert "memory/2026-05-04.md" not in [
        entry.rel_path for entry in workspace.discover_memory_files()
    ]


def test_safe_read_rejects_parent_escape(tmp_path: Path):
    workspace = MemoryWorkspace(tmp_path)
    with pytest.raises(UnsafeMemoryPathError):
        workspace.read_text("../secret.txt")


def test_safe_read_rejects_non_memory_workspace_file(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("not memory\n", encoding="utf-8")
    workspace = MemoryWorkspace(tmp_path)

    with pytest.raises(UnsafeMemoryPathError):
        workspace.read_text("notes.txt")


def test_safe_read_allows_dreams_file(tmp_path: Path):
    (tmp_path / "DREAMS.md").write_text("dream log\n", encoding="utf-8")
    workspace = MemoryWorkspace(tmp_path)

    result = workspace.read_text("DREAMS.md")

    assert result.path == "DREAMS.md"
    assert result.text == "dream log\n"


def test_read_lines_uses_one_based_line_window(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("a\nb\nc\nd\n", encoding="utf-8")
    workspace = MemoryWorkspace(tmp_path)

    result = workspace.read_text("MEMORY.md", from_line=2, line_count=2)

    assert result.path == "MEMORY.md"
    assert result.text == "b\nc\n"
    assert result.start_line == 2
    assert result.end_line == 3


def test_read_text_normalizes_returned_path(tmp_path: Path):
    (tmp_path / "MEMORY.md").write_text("a\n", encoding="utf-8")
    workspace = MemoryWorkspace(tmp_path)

    result = workspace.read_text("/MEMORY.md")

    assert result.path == "MEMORY.md"
