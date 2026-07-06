from demo.workspace_context import (
    BOOTSTRAP_FILE_ORDER,
    BOOTSTRAP_MAX_CHARS,
    BOOTSTRAP_TOTAL_MAX_CHARS,
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
    assert (tmp_path / "HEARTBEAT.md").is_file()
    assert not (tmp_path / "BOOTSTRAP.md").exists()
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == "# Custom Soul\n"


def test_workspace_bootstrap_creates_bootstrap_for_brand_new_workspace(tmp_path):
    ensure_workspace_bootstrap_files(tmp_path)

    assert (tmp_path / "BOOTSTRAP.md").is_file()


def test_workspace_context_injects_bootstrap_before_memory(tmp_path):
    ensure_workspace_bootstrap_files(tmp_path)
    (tmp_path / "MEMORY.md").write_text("# Long Term\n", encoding="utf-8")

    context = build_workspace_context(tmp_path)

    assert context.startswith("## Workspace Files (injected)")
    assert context.index("### AGENTS.md") < context.index("### SOUL.md")
    assert context.index("### SOUL.md") < context.index("### TOOLS.md")
    assert context.index("### TOOLS.md") < context.index("### IDENTITY.md")
    assert context.index("### IDENTITY.md") < context.index("### USER.md")
    assert context.index("### USER.md") < context.index("### HEARTBEAT.md")
    assert context.index("### HEARTBEAT.md") < context.index("### BOOTSTRAP.md")
    assert context.index("### BOOTSTRAP.md") < context.index("### MEMORY.md")
    assert "### memory/" not in context


def test_workspace_context_marks_missing_and_truncates_large_files(tmp_path):
    (tmp_path / "AGENTS.md").write_text("a" * (BOOTSTRAP_MAX_CHARS + 100), encoding="utf-8")

    context = build_workspace_context(tmp_path)

    assert "[truncated workspace bootstrap file]" in context
    assert "[MISSING] Expected at:" in context
    assert "SOUL.md" in context


def test_workspace_context_matches_golden_snapshot(tmp_path):
    for rel_path in BOOTSTRAP_FILE_ORDER:
        marker = rel_path.removesuffix(".md")[0]
        (tmp_path / rel_path).write_text(f"# {marker}\n", encoding="utf-8")

    context = build_workspace_context(tmp_path)

    assert context == (
        "## Workspace Files (injected)\n\n"
        "### AGENTS.md\n# A\n\n\n"
        "### SOUL.md\n# S\n\n\n"
        "### TOOLS.md\n# T\n\n\n"
        "### IDENTITY.md\n# I\n\n\n"
        "### USER.md\n# U\n\n\n"
        "### HEARTBEAT.md\n# H\n\n\n"
        "### BOOTSTRAP.md\n# B\n\n\n"
        "### MEMORY.md\n# M\n"
    )


def test_workspace_context_truncates_each_file_to_exact_budget(tmp_path):
    ensure_workspace_bootstrap_files(tmp_path)
    (tmp_path / "AGENTS.md").write_text("x" * (BOOTSTRAP_MAX_CHARS + 5), encoding="utf-8")

    context = build_workspace_context(tmp_path)

    injected = context.split("### AGENTS.md\n")[1].split("\n\n### SOUL.md")[0]
    marker = "\n[truncated workspace bootstrap file]"
    assert len(injected) == BOOTSTRAP_MAX_CHARS
    assert injected.endswith(marker)
    assert injected.startswith("x" * (BOOTSTRAP_MAX_CHARS - len(marker)))


def test_workspace_context_stops_injecting_at_total_budget(tmp_path):
    per_file_budget_files = BOOTSTRAP_TOTAL_MAX_CHARS // BOOTSTRAP_MAX_CHARS
    for rel_path in BOOTSTRAP_FILE_ORDER[:per_file_budget_files]:
        (tmp_path / rel_path).write_text("y" * (BOOTSTRAP_MAX_CHARS * 2), encoding="utf-8")

    context = build_workspace_context(tmp_path)

    assert context.rstrip().endswith("[workspace bootstrap total limit reached]")
    assert "### MEMORY.md" not in context


def test_workspace_file_contents_excludes_memory_md(tmp_path):
    ensure_workspace_bootstrap_files(tmp_path)
    (tmp_path / "MEMORY.md").write_text("# Long Term\n", encoding="utf-8")

    contents = workspace_file_contents(tmp_path)

    assert "AGENTS.md" in contents
    assert "HEARTBEAT.md" in contents
    assert "BOOTSTRAP.md" in contents
    assert "MEMORY.md" not in contents
