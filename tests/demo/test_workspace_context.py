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
    # The v2026.9.6 map plus the PROACTIVE_PREFERENCES.md extension; no TOOLS.md or
    # HEARTBEAT.md in either order.
    assert workspace_file_names() == [
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "PROACTIVE_PREFERENCES.md",
        "BOOTSTRAP.md",
    ]
    assert injected_file_order() == [
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "PROACTIVE_PREFERENCES.md",
        "BOOTSTRAP.md",
        "MEMORY.md",
    ]
    assert "TOOLS.md" not in DEMO_WORKSPACE_TEMPLATES
    assert "HEARTBEAT.md" not in DEMO_WORKSPACE_TEMPLATES
    # The Lab's former TOOLS.md bullets are the AGENTS.md "## Tools" section.
    assert "\n## Tools\n\n- Use memory search/get" in DEMO_WORKSPACE_TEMPLATES["AGENTS.md"]


def test_workspace_bootstrap_files_are_seeded_without_overwriting(tmp_path):
    (tmp_path / "SOUL.md").write_text("# Custom Soul\n", encoding="utf-8")

    result = ensure_workspace_bootstrap_files(tmp_path)

    for name in ("AGENTS.md", "IDENTITY.md", "USER.md"):
        assert (tmp_path / name).read_text(encoding="utf-8") == DEMO_WORKSPACE_TEMPLATES[name]
    assert not (tmp_path / "TOOLS.md").exists() and not (tmp_path / "HEARTBEAT.md").exists()
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
        for name in ("AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "BOOTSTRAP.md", "MEMORY.md")
    ]
    # PROACTIVE_PREFERENCES.md is seeded empty and empty files are not injected.
    assert "PROACTIVE_PREFERENCES.md" not in context
    assert "Dynamic Project Context" not in context
    assert "/memory/" not in context


def test_workspace_prompt_marks_missing_files_and_truncates_agents(tmp_path):
    (tmp_path / "AGENTS.md").write_text("a" * (DEFAULT_BOOTSTRAP_MAX_CHARS + 100), encoding="utf-8")

    context = build_workspace_prompt(tmp_path)

    assert "[...truncated, read AGENTS.md for full content...]" in context
    assert "…(truncated AGENTS.md: kept 9000+policy 0+3000 chars of 20100)…" in context
    assert f"[MISSING] Expected at: {os.path.abspath(tmp_path)}/SOUL.md" in context
    # MEMORY.md is skipped entirely when absent (no marker, no intro line);
    # BOOTSTRAP.md absent means complete.
    assert "MEMORY.md" not in context
    assert "BOOTSTRAP.md" not in context
    assert "## Bootstrap Context Notice\n[Bootstrap truncation warning]" in context


# v2026.9.6 wording (system-prompt.ts, bootstrap-prompt.ts, system-prompt-context-files.ts).
BOOTSTRAP_PENDING_FULL_IN_CONTEXT = (
    "## Bootstrap Pending\n"
    "BOOTSTRAP.md below; follow before normal reply.\n"
    "Can finish BOOTSTRAP.md here: do it.\n"
    "Cannot: brief blocker, safe possible steps, simplest next step.\n"
    "Never claim completion early. No generic greeting/normal reply before BOOTSTRAP.md "
    "handling.\n"
    "First visible reply must follow BOOTSTRAP.md; no generic greeting.\n"
)
WORKSPACE_FILES_LINES = (
    "## Workspace Files (injected)\n"
    "User-editable; memory-core loads below as Project Context.\n"
)
SOUL_LINE = "SOUL.md: persona/tone. Follow it unless higher-priority instructions override.\n"
MEMORY_LINE = (
    "MEMORY.md: durable non-profile facts and decisions; use when relevant unless "
    "higher-priority instructions override.\n"
)
USER_LINE = (
    "USER.md: durable user preferences and profile directives; follow unless higher-priority "
    "instructions override.\n"
)


def _write_marker_files(root: Path) -> None:
    for rel_path in MEMORY_CORE_WORKSPACE_LAYOUT.load_order:
        marker = rel_path.removesuffix(".md")[0]
        (root / rel_path).write_text(f"# {marker}\n", encoding="utf-8")


def test_workspace_prompt_matches_golden_snapshot(tmp_path):
    # Pure-read state: every layout file written by hand, no state file and no
    # initialization, so BOOTSTRAP.md and MEMORY.md render together. The Lab
    # itself never reaches this state (demo_config() initializes, which would
    # reconcile BOOTSTRAP.md away); see the snapshots below for reachable ones.
    # Regenerated 2026-09-27 for the v2026.9.6 map and wording (TOOLS.md and HEARTBEAT.md
    # are written but no longer loaded; no dynamic block).
    _write_marker_files(tmp_path)

    context = build_workspace_prompt(tmp_path)

    root = os.path.abspath(tmp_path)
    assert context == (
        BOOTSTRAP_PENDING_FULL_IN_CONTEXT
        + WORKSPACE_FILES_LINES
        + "# Project Context\n"
        "Loaded project context:\n"
        + SOUL_LINE
        + MEMORY_LINE
        + USER_LINE
        + f"## {root}/AGENTS.md\n# A\n"
        f"## {root}/SOUL.md\n# S\n"
        f"## {root}/IDENTITY.md\n# I\n"
        f"## {root}/USER.md\n# U\n"
        f"## {root}/PROACTIVE_PREFERENCES.md\n# P\n"
        f"## {root}/BOOTSTRAP.md\n# B\n"
        f"## {root}/MEMORY.md\n# M"
    )


def test_workspace_prompt_compat_layout_snapshot_has_no_extension_file(tmp_path):
    from memory_core.bootstrap import OPENCLAW_COMPAT_LAYOUT

    _write_marker_files(tmp_path)

    context = build_workspace_prompt(tmp_path, layout=OPENCLAW_COMPAT_LAYOUT)

    root = os.path.abspath(tmp_path)
    assert context == (
        BOOTSTRAP_PENDING_FULL_IN_CONTEXT
        + WORKSPACE_FILES_LINES
        + "# Project Context\n"
        "Loaded project context:\n"
        + SOUL_LINE
        + MEMORY_LINE
        + USER_LINE
        + f"## {root}/AGENTS.md\n# A\n"
        f"## {root}/SOUL.md\n# S\n"
        f"## {root}/IDENTITY.md\n# I\n"
        f"## {root}/USER.md\n# U\n"
        f"## {root}/BOOTSTRAP.md\n# B\n"
        f"## {root}/MEMORY.md\n# M"
    )


def _template_block(root: str, name: str) -> str:
    return f"## {root}/{name}\n{DEMO_WORKSPACE_TEMPLATES[name].rstrip()}\n"


def test_workspace_prompt_snapshot_of_a_fresh_lab_workspace(tmp_path):
    # Reachable: the Lab's first request on an empty workspace runs
    # ensure_workspace_bootstrap_files, which seeds the Lab templates and
    # BOOTSTRAP.md (no setup evidence yet), so bootstrap is pending.
    ensure_workspace_bootstrap_files(tmp_path)

    context = build_workspace_prompt(tmp_path)

    root = os.path.abspath(tmp_path)
    assert context == (
        BOOTSTRAP_PENDING_FULL_IN_CONTEXT
        + WORKSPACE_FILES_LINES
        + "# Project Context\n"
        "Loaded project context:\n"
        + SOUL_LINE
        + USER_LINE
        + "".join(
            _template_block(root, name) for name in ("AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md")
        )
        + _template_block(root, "BOOTSTRAP.md").rstrip("\n")
    )


def test_workspace_prompt_snapshot_after_the_lab_seeds_memory(tmp_path):
    # Reachable: a chat reset seeds memory/ and MEMORY.md, and the next
    # ensure_workspace_bootstrap_files reconciles setup and deletes BOOTSTRAP.md.
    ensure_workspace_bootstrap_files(tmp_path)
    (tmp_path / "memory").mkdir()
    (tmp_path / "MEMORY.md").write_text("# MEMORY.md - Long-Term Memory\n", encoding="utf-8")
    ensure_workspace_bootstrap_files(tmp_path)

    context = build_workspace_prompt(tmp_path)

    root = os.path.abspath(tmp_path)
    assert context == (
        WORKSPACE_FILES_LINES
        + "# Project Context\n"
        "Loaded project context:\n"
        + SOUL_LINE
        + MEMORY_LINE
        + USER_LINE
        + "".join(
            _template_block(root, name) for name in ("AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md")
        )
        + f"## {root}/MEMORY.md\n# MEMORY.md - Long-Term Memory"
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

    # Load order consumes the 60000 total: AGENTS (digest), SOUL, IDENTITY, then USER
    # clamped to what is left; later files are not injected at all.
    for name in ("AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md"):
        assert _heading(tmp_path, name) in context
    for name in ("PROACTIVE_PREFERENCES.md", "BOOTSTRAP.md", "MEMORY.md"):
        assert _heading(tmp_path, name) not in context
    # Injected content is trimEnd()ed, so the only trailing newline is the join.
    injected = sum(
        len(block.split("\n", 1)[1].removesuffix("\n"))
        for block in context.split(f"## {os.path.abspath(tmp_path)}/")[1:]
    )
    # USER.md gets the 7,886 units left and its head/tail marker render rounds to 7,885.
    assert injected == DEFAULT_BOOTSTRAP_TOTAL_MAX_CHARS - 1
    assert "## Bootstrap Context Notice\n[Bootstrap truncation warning]" in context


def test_workspace_file_contents_excludes_memory_md(tmp_path):
    ensure_workspace_bootstrap_files(tmp_path)
    (tmp_path / "MEMORY.md").write_text("# Long Term\n", encoding="utf-8")

    contents = workspace_file_contents(tmp_path)

    assert list(contents) == workspace_file_names()
    assert "PROACTIVE_PREFERENCES.md" in contents
    assert "BOOTSTRAP.md" in contents
    assert "MEMORY.md" not in contents
