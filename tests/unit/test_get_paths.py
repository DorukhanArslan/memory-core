"""Actual file authorization for trusted memory-get extra roots."""

from dataclasses import FrozenInstanceError

import pytest

from memory_core.memory_paths import MemoryPathNotAllowedError, MemoryReadPathError
from memory_core.tools.get_paths import resolve_memory_get_path, resolve_memory_get_read_path


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


def test_pattern_entries_admit_only_matching_markdown_descendants(roots):
    workspace, outside = roots
    public = outside / "public"
    public.mkdir()
    allowed = public / "note.md"
    allowed.write_text("allowed", encoding="utf-8")
    paths = [{"path": str(outside), "pattern": "public/**/*.md"}]
    assert resolve_memory_get_path(workspace, str(allowed), paths) == (
        "../outside/public/note.md", allowed, False,
    )
    assert resolve_memory_get_path(workspace, str(public / "missing.md"), paths) == (
        "../outside/public/missing.md", None, False,
    )
    with pytest.raises(MemoryPathNotAllowedError):
        resolve_memory_get_path(
            workspace, str(outside / "note.md"), paths,
        )


def test_distinct_patterns_under_one_root_form_a_union(roots):
    workspace, outside = roots
    for relative in ("public/a.md", "shared/b.md", "private/c.md"):
        file = outside / relative
        file.parent.mkdir(exist_ok=True)
        file.write_text(relative, encoding="utf-8")
    paths = [
        {"path": str(outside), "pattern": "public/**/*.md"},
        {"path": str(outside), "pattern": "shared/*.md"},
        {"path": str(outside), "pattern": "public/**/*.md"},
    ]
    for relative in ("public/a.md", "shared/b.md"):
        file = outside / relative
        assert resolve_memory_get_path(workspace, str(file), paths)[1] == file
    with pytest.raises(MemoryPathNotAllowedError):
        resolve_memory_get_path(workspace, str(outside / "private/c.md"), paths)


def test_explicit_markdown_file_is_admitted_independently_of_pattern(roots):
    workspace, outside = roots
    note = outside / "note.md"
    assert resolve_memory_get_path(workspace, str(note), [
        {"path": str(note), "pattern": "excluded/**"},
    ])[1] == note


def test_pattern_normalization_reuses_trim_and_posix_separator_policy(roots):
    workspace, outside = roots
    nested = outside / "public" / "nested" / "note.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("note", encoding="utf-8")
    assert resolve_memory_get_path(workspace, str(nested), [
        {"path": "\ufeff " + str(outside) + "\u00a0", "pattern": "\tpublic\\**\\*.md \t"},
    ])[1] == nested


@pytest.mark.parametrize("name", ["note.txt", "note.MD"])
def test_patterns_never_bypass_markdown_extension_policy(roots, name):
    workspace, outside = roots
    file = outside / name
    file.write_text("not markdown", encoding="utf-8")
    with pytest.raises(MemoryPathNotAllowedError):
        resolve_memory_get_path(workspace, str(file), [{"path": str(outside), "pattern": "**"}])


def test_patterned_roots_do_not_authorize_symlinks_or_sibling_prefixes(roots):
    workspace, outside = roots
    link = outside / "linked.md"
    link.symlink_to("note.md")
    sibling = outside.parent / (outside.name + "-sibling")
    sibling.mkdir()
    (sibling / "note.md").write_text("sibling", encoding="utf-8")
    configured = [{"path": str(outside), "pattern": "**/*.md"}]
    for file in (link, sibling / "note.md"):
        with pytest.raises(MemoryPathNotAllowedError):
            resolve_memory_get_path(workspace, str(file), configured)


def test_admission_preserves_the_exact_selected_root_and_link_policy(roots):
    workspace, outside = roots
    builtin = resolve_memory_get_read_path(workspace, "MEMORY.md", [outside])
    assert (builtin.rel_path, builtin.path, builtin.root, builtin.suggest_read_fallback,
            builtin.follow_parent_symlinks) == (
        "MEMORY.md", workspace / "MEMORY.md", workspace, True, True,
    )
    configured = resolve_memory_get_read_path(workspace, str(outside / "note.md"), [outside])
    assert (configured.path, configured.root, configured.suggest_read_fallback,
            configured.follow_parent_symlinks) == (outside / "note.md", outside, False, False)
    explicit_file = resolve_memory_get_read_path(workspace, str(outside / "note.md"), [outside / "note.md"])
    assert explicit_file.root == outside
    missing = resolve_memory_get_read_path(workspace, str(outside / "missing.md"), [outside])
    assert missing.path is None and missing.root == outside
    with pytest.raises(FrozenInstanceError):
        configured.root = workspace


def test_get_factory_accepts_trusted_pattern_mapping_configuration(roots):
    from memory_core.config import MemoryConfig
    from memory_core.tools.get_factory import create_memory_get_tool

    workspace, outside = roots
    tool = create_memory_get_tool(
        MemoryConfig(workspace_dir=workspace),
        extra_paths=[{"path": str(outside), "pattern": "*.md"}],
    )
    assert tool is not None
    result = tool.execute("read-extra", {"path": str(outside / "note.md")})
    assert result["details"] == {
        "status": "ok", "text": "configured", "path": "../outside/note.md", "from": 1, "lines": 1,
    }
