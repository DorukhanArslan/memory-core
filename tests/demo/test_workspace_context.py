import os
from pathlib import Path

from demo.workspace_context import (
    DEMO_WORKSPACE_LAYOUT,
    DEMO_WORKSPACE_TEMPLATES,
    build_workspace_prompt,
    ensure_workspace_bootstrap_files,
    injected_file_order,
    workspace_file_contents,
    workspace_file_names,
)
from memory_core.bootstrap import (
    DEFAULT_BOOTSTRAP_MAX_CHARS,
    DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS,
    MEMORY_CORE_WORKSPACE_LAYOUT,
    bootstrap_status,
    trim_bootstrap_content,
)


def _heading(root: Path, name: str) -> str:
    return f"## {os.path.abspath(root)}/{name}"


def test_demo_uses_the_default_memory_core_layout():
    assert DEMO_WORKSPACE_LAYOUT is MEMORY_CORE_WORKSPACE_LAYOUT
    assert workspace_file_names() == [
        "AGENTS.md",
        "SOUL.md",
        "TOOLS.md",
        "IDENTITY.md",
        "USER.md",
        "PROACTIVE_PREFERENCES.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
    ]
    assert injected_file_order() == [
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "PROACTIVE_PREFERENCES.md",
        "TOOLS.md",
        "BOOTSTRAP.md",
        "MEMORY.md",
        "HEARTBEAT.md",
    ]


def test_workspace_bootstrap_files_are_seeded_without_overwriting(tmp_path):
    (tmp_path / "SOUL.md").write_text("# Custom Soul\n", encoding="utf-8")

    result = ensure_workspace_bootstrap_files(tmp_path)

    for name in ("AGENTS.md", "IDENTITY.md", "USER.md", "TOOLS.md", "HEARTBEAT.md"):
        assert (tmp_path / name).read_text(encoding="utf-8") == DEMO_WORKSPACE_TEMPLATES[name]
    assert (tmp_path / "PROACTIVE_PREFERENCES.md").read_text(encoding="utf-8") == ""
    assert (tmp_path / "user").is_dir() and (tmp_path / "workspace").is_dir()
    # A changed profile file is setup evidence: no BOOTSTRAP.md, setup complete.
    assert not (tmp_path / "BOOTSTRAP.md").exists()
    assert result.bootstrap_status == "complete"
    assert (tmp_path / "SOUL.md").read_text(encoding="utf-8") == "# Custom Soul\n"


def test_workspace_bootstrap_creates_bootstrap_for_brand_new_workspace(tmp_path):
    result = ensure_workspace_bootstrap_files(tmp_path)

    assert (tmp_path / "BOOTSTRAP.md").read_text(encoding="utf-8") == (
        DEMO_WORKSPACE_TEMPLATES["BOOTSTRAP.md"]
    )
    assert result.bootstrap_status == "pending"


def test_memory_evidence_completes_setup_and_removes_bootstrap(tmp_path):
    ensure_workspace_bootstrap_files(tmp_path)
    (tmp_path / "memory").mkdir()

    result = ensure_workspace_bootstrap_files(tmp_path)

    assert result.bootstrap_removed is True
    assert not (tmp_path / "BOOTSTRAP.md").exists()
    assert bootstrap_status(tmp_path) == "complete"
    assert "Bootstrap Pending" not in build_workspace_prompt(tmp_path)


def test_workspace_prompt_uses_project_context_order(tmp_path):
    ensure_workspace_bootstrap_files(tmp_path)
    (tmp_path / "MEMORY.md").write_text("# Long Term\n", encoding="utf-8")

    context = build_workspace_prompt(tmp_path)

    headings = [line for line in context.splitlines() if line.startswith(f"## {tmp_path}")]
    assert headings == [
        _heading(tmp_path, name)
        for name in (
            "AGENTS.md",
            "SOUL.md",
            "IDENTITY.md",
            "USER.md",
            "TOOLS.md",
            "BOOTSTRAP.md",
            "MEMORY.md",
            "HEARTBEAT.md",
        )
    ]
    # PROACTIVE_PREFERENCES.md is seeded empty and empty files are not injected.
    assert "PROACTIVE_PREFERENCES.md" not in context
    assert context.index("# Project Context\n") < context.index("# Dynamic Project Context\n")
    assert "/memory/" not in context


def test_workspace_prompt_marks_missing_files_and_truncates_agents(tmp_path):
    (tmp_path / "AGENTS.md").write_text("a" * (DEFAULT_BOOTSTRAP_MAX_CHARS + 100), encoding="utf-8")

    context = build_workspace_prompt(tmp_path)

    assert "[...truncated, read AGENTS.md for full content...]" in context
    assert "…(truncated AGENTS.md: kept 9000+policy 0+3000 chars of 20100)…" in context
    assert f"[MISSING] Expected at: {os.path.abspath(tmp_path)}/SOUL.md" in context
    # MEMORY.md is skipped entirely when absent; BOOTSTRAP.md absent means complete.
    assert "MEMORY.md" not in context.replace("MEMORY.md:", "")
    assert "BOOTSTRAP.md" not in context
    assert "## Bootstrap Context Notice\n[Bootstrap truncation warning]" in context


def test_workspace_prompt_matches_golden_snapshot(tmp_path):
    # Regenerated 2026-09-26 for the upstream render format (was "### <rel>"
    # sections in load order): bootstrap sections, Workspace Files lines,
    # "# Project Context" with "## <abs path>" headings in render order, then
    # HEARTBEAT.md in the dynamic block.
    for rel_path in MEMORY_CORE_WORKSPACE_LAYOUT.load_order:
        marker = rel_path.removesuffix(".md")[0]
        (tmp_path / rel_path).write_text(f"# {marker}\n", encoding="utf-8")

    context = build_workspace_prompt(tmp_path)

    root = os.path.abspath(tmp_path)
    assert context == (
        "## Bootstrap Pending\n"
        "BOOTSTRAP.md is included below in Project Context; follow it before replying normally.\n"
        "If this run can complete the BOOTSTRAP.md workflow, do so.\n"
        "If it cannot, explain the blocker briefly, continue with any bootstrap steps that are "
        "still possible here, and offer the simplest next step.\n"
        "Do not pretend bootstrap is complete when it is not.\n"
        "Do not use a generic first greeting or reply normally until after you have handled "
        "BOOTSTRAP.md.\n"
        "Your first user-visible reply for a bootstrap-pending workspace must follow "
        "BOOTSTRAP.md, not a generic greeting.\n"
        "## Workspace Files (injected)\n"
        "These user-editable files are loaded by memory-core and included below in Project Context.\n"
        "# Project Context\n"
        "The following project context files have been loaded:\n"
        "SOUL.md: persona/tone. Follow it unless higher-priority instructions override.\n"
        "MEMORY.md: durable user preferences and behavior guidance. Keep following it "
        "throughout the session unless higher-priority instructions override.\n"
        f"## {root}/AGENTS.md\n# A\n"
        f"## {root}/SOUL.md\n# S\n"
        f"## {root}/IDENTITY.md\n# I\n"
        f"## {root}/USER.md\n# U\n"
        f"## {root}/PROACTIVE_PREFERENCES.md\n# P\n"
        f"## {root}/TOOLS.md\n# T\n"
        f"## {root}/BOOTSTRAP.md\n# B\n"
        f"## {root}/MEMORY.md\n# M\n"
        "# Dynamic Project Context\n"
        "The following frequently-changing project context files are kept below the cache "
        "boundary when possible:\n"
        f"## {root}/HEARTBEAT.md\n# H"
    )


def test_workspace_prompt_truncates_each_file_to_its_budget(tmp_path):
    ensure_workspace_bootstrap_files(tmp_path)
    (tmp_path / "SOUL.md").write_text("x" * (DEFAULT_BOOTSTRAP_MAX_CHARS + 5), encoding="utf-8")

    context = build_workspace_prompt(tmp_path)

    injected = context.split(f"{_heading(tmp_path, 'SOUL.md')}\n")[1].split(
        f"\n{_heading(tmp_path, 'IDENTITY.md')}"
    )[0]
    expected = trim_bootstrap_content(
        "x" * (DEFAULT_BOOTSTRAP_MAX_CHARS + 5), "SOUL.md", DEFAULT_BOOTSTRAP_MAX_CHARS
    )
    assert injected == expected.content
    assert len(injected) <= DEFAULT_BOOTSTRAP_MAX_CHARS
    assert "…(truncated SOUL.md: kept " in injected


def test_workspace_prompt_stops_injecting_at_total_budget(tmp_path):
    for rel_path in MEMORY_CORE_WORKSPACE_LAYOUT.load_order:
        (tmp_path / rel_path).write_text("y" * (DEFAULT_BOOTSTRAP_MAX_CHARS * 2), encoding="utf-8")

    context = build_workspace_prompt(tmp_path)

    # Load order consumes the 60000 total: AGENTS (digest), SOUL, TOOLS, then
    # IDENTITY clamped to what is left; later files are not injected at all.
    for name in ("AGENTS.md", "SOUL.md", "TOOLS.md", "IDENTITY.md"):
        assert _heading(tmp_path, name) in context
    for name in ("USER.md", "PROACTIVE_PREFERENCES.md", "HEARTBEAT.md", "BOOTSTRAP.md", "MEMORY.md"):
        assert _heading(tmp_path, name) not in context
    # Injected content is trimEnd()ed, so the only trailing newline is the join.
    injected = sum(
        len(block.split("\n", 1)[1].removesuffix("\n"))
        for block in context.split(f"## {os.path.abspath(tmp_path)}/")[1:]
    )
    assert injected == DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS
    assert "## Bootstrap Context Notice\n[Bootstrap truncation warning]" in context


def test_workspace_file_contents_excludes_memory_md(tmp_path):
    ensure_workspace_bootstrap_files(tmp_path)
    (tmp_path / "MEMORY.md").write_text("# Long Term\n", encoding="utf-8")

    contents = workspace_file_contents(tmp_path)

    assert list(contents) == workspace_file_names()
    assert "PROACTIVE_PREFERENCES.md" in contents
    assert "BOOTSTRAP.md" in contents
    assert "MEMORY.md" not in contents
