"""Actual file authorization for trusted memory-get extra roots."""

import pytest

from memory_core.memory_paths import MemoryPathNotAllowedError, MemoryReadPathError
from memory_core.tools.get_paths import resolve_memory_get_path


@pytest.fixture
def roots(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "MEMORY.md").write_text("memory", encoding="utf-8")
    (outside / "note.md").write_text("configured", encoding="utf-8")
    return workspace, outside


def test_unconfigured_external_file_is_not_authorized(roots):
    workspace, outside = roots
    with pytest.raises(MemoryPathNotAllowedError):
        resolve_memory_get_path(workspace, str(outside / "note.md"))


@pytest.mark.parametrize("relative", [False, True])
def test_explicit_file_authorizes_only_that_file(roots, relative):
    workspace, outside = roots
    configured = "../outside/note.md" if relative else outside / "note.md"
    logical, physical, fallback = resolve_memory_get_path(
        workspace, "../outside/note.md", [configured],
    )
    assert (logical, physical, fallback) == ("../outside/note.md", outside / "note.md", False)
    (outside / "other.md").write_text("other", encoding="utf-8")
    with pytest.raises(MemoryPathNotAllowedError):
        resolve_memory_get_path(workspace, "../outside/other.md", [configured])


def test_directory_authorizes_nested_markdown_and_reports_missing_leaf(roots):
    workspace, outside = roots
    nested = outside / "nested" / "note.md"
    nested.parent.mkdir()
    nested.write_text("nested", encoding="utf-8")
    assert resolve_memory_get_path(workspace, str(nested), [outside]) == (
        "../outside/nested/note.md", nested, False,
    )
    assert resolve_memory_get_path(workspace, "../outside/missing.md", [outside]) == (
        "../outside/missing.md", None, False,
    )


@pytest.mark.parametrize("name", ["note.txt", "note.MD"])
def test_extra_directory_does_not_authorize_other_extensions(roots, name):
    workspace, outside = roots
    file = outside / name
    file.write_text("not eligible", encoding="utf-8")
    with pytest.raises(MemoryPathNotAllowedError):
        resolve_memory_get_path(workspace, str(file), [outside, file])


def test_configured_symlink_is_not_a_read_root(roots):
    workspace, outside = roots
    alias = workspace / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MemoryPathNotAllowedError):
        resolve_memory_get_path(workspace, "alias/note.md", [alias])


@pytest.mark.parametrize("parent", [False, True])
def test_extra_root_does_not_follow_descendant_symlinks(roots, parent):
    workspace, outside = roots
    if parent:
        (outside / "alias").symlink_to(".", target_is_directory=True)
        request = outside / "alias" / "note.md"
    else:
        request = outside / "alias.md"
        request.symlink_to("note.md")
    with pytest.raises(MemoryPathNotAllowedError):
        resolve_memory_get_path(workspace, str(request), [outside])


def test_builtin_policy_has_priority_over_extra_roots(roots):
    workspace, outside = roots
    (workspace / "memory").mkdir()
    link = workspace / "memory" / "linked.md"
    link.symlink_to(outside / "note.md")
    with pytest.raises(MemoryReadPathError, match="symlink path component"):
        resolve_memory_get_path(workspace, "memory/linked.md", [outside, link])
    assert resolve_memory_get_path(workspace, "MEMORY.md", [outside]) == (
        "MEMORY.md", workspace / "MEMORY.md", True,
    )


def test_regular_hard_link_can_be_read_from_configured_root(roots):
    workspace, outside = roots
    alias = outside / "hard.md"
    alias.hardlink_to(outside / "note.md")
    assert resolve_memory_get_path(workspace, str(alias), [outside])[1] == alias


def test_pattern_entries_fail_closed_until_supported(roots):
    workspace, outside = roots
    with pytest.raises(TypeError, match="plain file or directory"):
        resolve_memory_get_path(
            workspace, str(outside / "note.md"), [{"path": str(outside), "pattern": "*.md"}],
        )
