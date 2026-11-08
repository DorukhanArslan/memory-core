"""Regressions found by the pinned readMemoryFile differential fixtures."""

from pathlib import Path

import pytest

from equivalence.storage_paths import build_storage_path_cases, run_storage_paths
from memory_core.config import MemoryConfig
from memory_core.tools.memory_get import memory_get
from memory_core.workspace import MemoryWorkspace


def test_read_fixtures_are_explicitly_partial_and_do_not_change_files():
    cases = build_storage_path_cases()
    assert len(cases) == 6
    for case in cases:
        assert case["covers"] == []
        assert run_storage_paths(case["input"])["filesUnchanged"] is True


@pytest.mark.parametrize(("content", "text", "lines"), [
    ("", "", 0),
    ("one", "one", 1),
    ("one\n", "one", 1),
    ("one\n\n", "one\n", 2),
    ("one\ntwo\n", "one\ntwo", 2),
    ("\n", "", 1),
])
def test_terminal_newline_closes_a_line_instead_of_creating_one(tmp_path, content, text, lines):
    (tmp_path / "MEMORY.md").write_text(content, encoding="utf-8")
    assert memory_get(MemoryConfig(workspace_dir=tmp_path), path="MEMORY.md") == {
        "status": "ok", "text": text, "path": "MEMORY.md", "from": 1, "lines": lines,
    }


def test_terminal_newline_does_not_suggest_an_empty_continuation(tmp_path):
    (tmp_path / "MEMORY.md").write_text("one\n", encoding="utf-8")
    assert memory_get(MemoryConfig(workspace_dir=tmp_path), path="MEMORY.md", lines=1) == {
        "status": "ok", "text": "one", "path": "MEMORY.md", "from": 1, "lines": 1,
    }


@pytest.mark.parametrize("target", ["note.md", "missing.md"])
def test_final_symlink_refusal_keeps_policy_code(tmp_path, target):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "note.md").write_text("note", encoding="utf-8")
    (tmp_path / "memory" / "link.md").symlink_to(target)
    assert memory_get(MemoryConfig(workspace_dir=tmp_path), path="memory/link.md") == {
        "path": "memory/link.md", "text": "", "status": "error", "code": "symlink",
        "error": "symlink path component not allowed",
    }


@pytest.mark.parametrize("leaf", ["secret.md", "missing.md"])
def test_outside_parent_is_refused_before_the_leaf_is_observed(tmp_path, leaf):
    root = tmp_path / "workspace"
    (root / "memory").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    (root / "memory" / "outside").symlink_to(outside, target_is_directory=True)
    result = memory_get(MemoryConfig(workspace_dir=root), path=f"memory/outside/{leaf}")
    assert result["status"] == "error"
    assert result["code"] == "outside-workspace"
    assert result["error"] == (
        f"file is outside workspace root | Symlink escapes root ({root.resolve()}): "
        f"{root.resolve() / 'memory' / 'outside'}"
    )
    assert (outside / "secret.md").read_text() == "secret"


def test_parent_symlink_within_workspace_is_readable(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "note.md").write_text("note", encoding="utf-8")
    (tmp_path / "memory" / "alias").symlink_to(".", target_is_directory=True)
    assert memory_get(MemoryConfig(workspace_dir=tmp_path), path="memory/alias/note.md")["text"] == "note"


def test_broken_parent_symlink_is_a_visible_policy_failure(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "broken").symlink_to("missing")
    result = memory_get(MemoryConfig(workspace_dir=tmp_path), path="memory/broken/note.md")
    assert result["status"] == "error"
    assert result["code"] == "outside-workspace"
    assert result["error"] == (
        f"file is outside workspace root | Symlink escapes root ({tmp_path.resolve()}): "
        f"{tmp_path.resolve() / 'memory' / 'broken'}"
    )


def test_parent_loop_keeps_stable_policy_diagnostic(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "loop").symlink_to("loop")
    result = memory_get(MemoryConfig(workspace_dir=tmp_path), path="memory/loop/note.md")
    assert result["status"] == "error"
    assert result["code"] == "symlink"
    # The tool also retains the OS cause; the reader's stable policy prefix
    # and code identify the failure independently of a platform's path text.
    assert result["error"].startswith("symlink path could not be resolved")


def test_non_directory_parent_is_a_read_failure_instead_of_a_miss(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "note.md").write_text("note", encoding="utf-8")
    result = memory_get(MemoryConfig(workspace_dir=tmp_path), path="memory/note.md/child.md")
    assert result["status"] == "error"
    assert result["code"] == "outside-workspace"
    assert result["error"] == (
        "file is outside workspace root | Path component is not a directory: "
        f"{tmp_path.resolve() / 'memory' / 'note.md'} | ENOTDIR"
    )


def test_non_directory_workspace_keeps_policy_code(tmp_path):
    root = tmp_path / "workspace"
    root.write_text("file", encoding="utf-8")
    result = memory_get(MemoryConfig(workspace_dir=root), path="MEMORY.md")
    assert result["status"] == "error"
    assert result["code"] == "invalid-path"
    assert result["error"] == "root dir is not a directory"


def test_directory_and_fifo_leaves_are_not_read(tmp_path):
    import os

    (tmp_path / "memory" / "directory.md").mkdir(parents=True)
    os.mkfifo(tmp_path / "memory" / "pipe.md")
    for leaf in ("directory.md", "pipe.md"):
        result = memory_get(MemoryConfig(workspace_dir=tmp_path), path=f"memory/{leaf}")
        assert result["status"] == "error"
        assert result["code"] == "MEMORY_READ_FAILED"
        assert result["error"] == "path must be a regular file | not a file | not-file"


def test_missing_normal_parent_returns_not_found(tmp_path):
    assert MemoryWorkspace(Path(tmp_path)).resolve_memory_read_path("memory/missing.md") == (
        "memory/missing.md", None,
    )
