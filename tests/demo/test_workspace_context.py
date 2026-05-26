from demo.workspace_context import (
    BOOTSTRAP_MAX_CHARS,
    build_workspace_context,
    ensure_workspace_bootstrap_files,
    workspace_file_contents,
)


def test_workspace_bootstrap_files_are_seeded_without_overwriting(tmp_path):
    (tmp_path / "SOUL.md").write_text("# Custom Soul\n", encoding="utf-8")

    ensure_workspace_bootstrap_files(tmp_path)

    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / "IDENTITY.md").is_file()
    assert (tmp_path / "USER.md").is_file()
    assert (tmp_path / "TOOLS.md").is_file()
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == "# Custom Soul\n"


def test_workspace_context_injects_bootstrap_before_memory(tmp_path):
    ensure_workspace_bootstrap_files(tmp_path)
    (tmp_path / "MEMORY.md").write_text("# Long Term\n", encoding="utf-8")

    context = build_workspace_context(tmp_path)

    assert context.startswith("## Workspace Files (injected)")
    assert context.index("### AGENTS.md") < context.index("### SOUL.md")
    assert context.index("### SOUL.md") < context.index("### TOOLS.md")
    assert context.index("### TOOLS.md") < context.index("### IDENTITY.md")
    assert context.index("### IDENTITY.md") < context.index("### USER.md")
    assert context.index("### USER.md") < context.index("### MEMORY.md")
    assert "### memory/" not in context


def test_workspace_context_marks_missing_and_truncates_large_files(tmp_path):
    (tmp_path / "AGENTS.md").write_text("a" * (BOOTSTRAP_MAX_CHARS + 100), encoding="utf-8")

    context = build_workspace_context(tmp_path)

    assert "[truncated workspace bootstrap file]" in context
    assert "[MISSING] Expected at:" in context
    assert "SOUL.md" in context


def test_workspace_file_contents_excludes_memory_md(tmp_path):
    ensure_workspace_bootstrap_files(tmp_path)
    (tmp_path / "MEMORY.md").write_text("# Long Term\n", encoding="utf-8")

    contents = workspace_file_contents(tmp_path)

    assert "AGENTS.md" in contents
    assert "MEMORY.md" not in contents
