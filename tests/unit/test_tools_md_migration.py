"""memory_core.bootstrap.migrate_tools_md, with the inputs of upstream's
src/commands/doctor-tools-md-migration.test.ts at v2026.9.6 (the oracle comparison is
tests/integration/test_openclaw_ts_oracle.py › toolsMdMigration)."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from memory_core.bootstrap._tools_md_constants import (
    LEGACY_AGENTS_TOOLS_GUIDANCE_REWRITES,
    LEGACY_TOOLS_DEV_FALLBACK,
    LEGACY_TOOLS_DEV_MD_TEMPLATE,
    LEGACY_TOOLS_MD_TEMPLATE,
)
from memory_core.bootstrap.tools_md import (
    merge_tools_md_into_agents_md,
    migrate_tools_md,
    should_merge_tools_md,
    tools_md_archive_dir,
    tools_md_migration_findings,
)

MIGRATED = "### Local notes (migrated from TOOLS.md)"


def _workspace(tmp_path: Path, agents: str | None, tools: str | None) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    if agents is not None:
        (root / "AGENTS.md").write_text(agents, encoding="utf-8")
    if tools is not None:
        (root / "TOOLS.md").write_text(tools, encoding="utf-8")
    return root


def _only_archive(root: Path) -> Path:
    (archive,) = tools_md_archive_dir(root).iterdir()
    return archive


def test_customized_content_goes_under_the_tools_section_and_reruns_idempotently(tmp_path):
    agents = "# Agent\n\n## Tools\n\nExisting notes.\n\n## Safety\n\nBe careful.\n"
    tools = "### Cameras\n\n- kitchen → wide angle\n\nKeep trailing spaces.  \n"
    root = _workspace(tmp_path, agents, tools)

    result = migrate_tools_md(root)

    assert result.warnings == ()
    assert result.changes == (f"Merged {root / 'TOOLS.md'} into AGENTS.md and archived the original.",)
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == (
        "# Agent\n\n## Tools\n\nExisting notes.\n\n" + f"{MIGRATED}\n\n" + tools + "\n## Safety\n\nBe careful.\n"
    )
    archive = _only_archive(root)
    digest = hashlib.sha256(tools.encode("utf-8")).hexdigest()
    assert archive.name == f"main-{digest}.md"
    assert archive.read_text(encoding="utf-8") == tools
    assert not (root / "TOOLS.md").exists()

    again = migrate_tools_md(root)
    assert (again.changes, again.warnings) == ((), ())
    assert (root / "AGENTS.md").read_text(encoding="utf-8").count("migrated from TOOLS.md") == 1


def test_no_tools_heading_appends_a_tools_section(tmp_path):
    agents = "# Agent\n\nKeep safe."
    tools = "Local camera: kitchen → wide angle\n"
    root = _workspace(tmp_path, agents, tools)

    migrate_tools_md(root)

    assert (root / "AGENTS.md").read_text(encoding="utf-8") == (
        f"{agents}\n\n## Tools\n\n{MIGRATED}\n\n{tools}"
    )


def test_missing_agents_md_gets_the_tools_section(tmp_path):
    root = _workspace(tmp_path, None, "notes\n")

    migrate_tools_md(root)

    assert (root / "AGENTS.md").read_text(encoding="utf-8") == f"## Tools\n\n{MIGRATED}\n\nnotes\n"


@pytest.mark.parametrize("tools", [LEGACY_TOOLS_MD_TEMPLATE, "", " \n\t"], ids=["template", "empty", "blank"])
def test_untouched_template_and_blank_files_are_archived_and_removed(tmp_path, tools):
    agents = "# Agent\n\n## Tools\n\nLocal details stay unchanged.\n"
    root = _workspace(tmp_path, agents, tools)

    result = migrate_tools_md(root)

    assert result.warnings == ()
    assert result.merged is False
    assert result.changes == (f"Removed untouched {root / 'TOOLS.md'} after archiving it.",)
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == agents
    assert _only_archive(root).read_text(encoding="utf-8") == tools
    assert not (root / "TOOLS.md").exists()


@pytest.mark.parametrize(("legacy", "current"), LEGACY_AGENTS_TOOLS_GUIDANCE_REWRITES)
def test_legacy_agents_guidance_is_rewritten(tmp_path, legacy, current):
    root = _workspace(tmp_path, f"# Agent\n\n## Tools\n\n{legacy}\n", LEGACY_TOOLS_MD_TEMPLATE)

    result = migrate_tools_md(root)

    migrated = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert result.warnings == ()
    assert current in migrated and legacy not in migrated
    assert "TOOLS.md" not in migrated
    assert "### Local notes\n" in migrated


def test_interrupted_agents_temp_write_is_cleaned_up(tmp_path):
    agents = "# Agent\n\n## Tools\n\nExisting notes.\n"
    tools = "### Cameras\n\n- kitchen → wide angle\n"
    root = _workspace(tmp_path, agents, tools)
    (root / "AGENTS.md.doctor-writing-999999-interrupted").write_text("partial", encoding="utf-8")

    result = migrate_tools_md(root)

    assert result.warnings == ()
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == f"{agents}\n{MIGRATED}\n\n{tools}"
    assert sorted(entry.name for entry in root.iterdir()) == [".memory-core", "AGENTS.md"]


def test_already_merged_content_is_not_appended_twice(tmp_path):
    agents = "# Agent\n\n## Tools\n\nExisting notes.\n"
    tools = "### Cameras\n\n- kitchen → wide angle\n"
    merged = f"{agents}\n{MIGRATED}\n\n{tools}"
    root = _workspace(tmp_path, merged, tools)

    result = migrate_tools_md(root)

    assert result.warnings == ()
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == merged
    assert not (root / "TOOLS.md").exists()


def test_symlinked_agents_md_is_refused_and_tools_md_kept(tmp_path):
    root = _workspace(tmp_path, None, "Local tool notes.\n")
    outside = tmp_path / "outside-agents.md"
    outside.write_text("Private external instructions.\n", encoding="utf-8")
    (root / "AGENTS.md").symlink_to(outside)

    result = migrate_tools_md(root)

    assert result.changes == ()
    assert result.warnings == (
        'Agent "main" TOOLS.md was not migrated: AGENTS.md must be an unlinked regular file for '
        "automatic migration",
    )
    assert (root / "TOOLS.md").read_text(encoding="utf-8") == "Local tool notes.\n"
    assert outside.read_text(encoding="utf-8") == "Private external instructions.\n"


def test_tools_md_stays_when_the_archive_cannot_be_written(tmp_path):
    agents = "# Agent\n\n## Tools\n\nExisting notes.\n"
    tools = "Local camera: kitchen → wide angle\n"
    root = _workspace(tmp_path, agents, tools)
    (root / ".memory-core").write_text("not a directory", encoding="utf-8")

    result = migrate_tools_md(root)

    assert result.changes == ()
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith('Agent "main" TOOLS.md was not migrated: ')
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == agents
    assert (root / "TOOLS.md").read_text(encoding="utf-8") == tools


def test_beta_artifacts_block_the_migration(tmp_path):
    root = _workspace(tmp_path, "# Agent\n", "notes\n")
    (root / "TOOLS.md.doctor-importing-1").write_text("x", encoding="utf-8")

    result = migrate_tools_md(root)

    assert result.warnings == (
        'Agent "main" TOOLS.md was not migrated: Interrupted v2026.7.2-beta.5 migration '
        "artifact(s) left untouched: TOOLS.md.doctor-importing-1. Restore the desired file "
        "manually before rerunning doctor.",
    )
    assert (root / "TOOLS.md").exists()


def test_no_tools_md_is_a_no_op(tmp_path):
    root = _workspace(tmp_path, "# Agent\n", None)

    result = migrate_tools_md(root)

    assert (result.changes, result.warnings, result.merged) == ((), (), None)
    assert not (root / ".memory-core").exists()


def test_archive_name_sanitizes_the_agent_id(tmp_path):
    root = _workspace(tmp_path, "# Agent\n", "notes\n")

    migrate_tools_md(root, agent_id="ops team/α")

    assert _only_archive(root).name.startswith("ops-team-")


def test_should_merge_and_merge_helpers():
    for template in (LEGACY_TOOLS_MD_TEMPLATE, LEGACY_TOOLS_DEV_MD_TEMPLATE, LEGACY_TOOLS_DEV_FALLBACK):
        assert should_merge_tools_md(template) is False
        assert should_merge_tools_md(template.rstrip("\n")) is True
    assert should_merge_tools_md("\u3000\n") is False
    assert should_merge_tools_md("x") is True
    # A fenced "## Tools" is not the Tools section.
    agents = "# A\n\n```\n## Tools\n```\n"
    assert merge_tools_md_into_agents_md(agents, "n\n") == f"{agents}\n## Tools\n\n{MIGRATED}\n\nn\n"


def test_archive_mode_is_private(tmp_path):
    root = _workspace(tmp_path, "# Agent\n", "notes\n")
    umask = os.umask(0o022)
    try:
        migrate_tools_md(root)
    finally:
        os.umask(umask)

    assert oct(os.stat(_only_archive(root)).st_mode & 0o777) == oct(0o600)
    # fs.mkdir(archiveDir, {recursive: true, mode: 0o700}) creates every missing level 0o700.
    for relative in (".memory-core", ".memory-core/backups", ".memory-core/backups/tools-md-migration"):
        assert oct(os.stat(root / relative).st_mode & 0o777) == oct(0o700), relative


def test_an_existing_state_dir_keeps_its_mode(tmp_path):
    root = _workspace(tmp_path, "# Agent\n", "notes\n")
    (root / ".memory-core").mkdir(mode=0o755)
    os.chmod(root / ".memory-core", 0o755)

    migrate_tools_md(root)

    assert oct(os.stat(root / ".memory-core").st_mode & 0o777) == oct(0o755)
    assert oct(os.stat(root / ".memory-core" / "backups").st_mode & 0o777) == oct(0o700)


def _seed_archive(root: Path, tools: str, content: str) -> Path:
    digest = hashlib.sha256(tools.encode("utf-8")).hexdigest()
    archive = tools_md_archive_dir(root) / f"main-{digest}.md"
    archive.parent.mkdir(parents=True)
    archive.write_text(content, encoding="utf-8")
    return archive


def test_an_identical_existing_archive_is_reused(tmp_path):
    # archiveSource: EEXIST from publishFileNoClobber plus a matching SHA-256 is not an error.
    agents = "# Agent\n\n## Tools\n\nExisting notes.\n"
    tools = "Local camera: kitchen → wide angle\n"
    root = _workspace(tmp_path, agents, tools)
    archive = _seed_archive(root, tools, tools)

    result = migrate_tools_md(root)

    assert result.warnings == ()
    assert result.archive_path == str(archive)
    assert sorted(path.name for path in archive.parent.iterdir()) == [archive.name]
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == f"{agents}\n{MIGRATED}\n\n{tools}"
    assert not (root / "TOOLS.md").exists()


def test_a_different_existing_archive_is_a_collision_with_its_cause(tmp_path):
    # Upstream throws new Error("... archive collision at <path>", {cause: EEXIST error}) and
    # formatErrorMessage appends " | <cause message> | EEXIST"; the cause text is Python's here.
    agents = "# Agent\n\n## Tools\n\nExisting notes.\n"
    tools = "Local camera: kitchen → wide angle\n"
    root = _workspace(tmp_path, agents, tools)
    archive = _seed_archive(root, tools, f"{tools}\n")

    result = migrate_tools_md(root)

    assert result.changes == ()
    (warning,) = result.warnings
    prefix = f'Agent "main" TOOLS.md was not migrated: TOOLS.md migration archive collision at {archive} | '
    assert warning.startswith(prefix)
    assert warning.endswith(" | EEXIST")
    assert "File exists" in warning[len(prefix) :]
    assert archive.read_text(encoding="utf-8") == f"{tools}\n"
    assert sorted(path.name for path in archive.parent.iterdir()) == [archive.name]
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == agents
    assert (root / "TOOLS.md").read_text(encoding="utf-8") == tools


# --- collectToolsMdMigrationFindings ------------------------------------------------------------


def test_findings_name_a_leftover_tools_md_without_touching_anything(tmp_path):
    agents = "# Agent\n\n## Tools\n\nExisting notes.\n"
    tools = "### Cameras\n\n- kitchen → wide angle\n"
    root = _workspace(tmp_path, agents, tools)

    (finding,) = tools_md_migration_findings(root)

    assert finding.to_json() == {
        "checkId": "core/doctor/tools-md-migration",
        "severity": "warning",
        "message": 'Agent "main" still stores local tool notes in TOOLS.md.',
        "path": str(root / "TOOLS.md"),
        "target": "main",
        "requirement": "legacy-tools-md",
        "fixHint": "Run memory_core.bootstrap.migrate_tools_md() to merge TOOLS.md into AGENTS.md.",
    }
    assert sorted(entry.name for entry in root.iterdir()) == ["AGENTS.md", "TOOLS.md"]
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == agents


def test_findings_check_the_merged_size_in_utf16_units(tmp_path):
    # upstream's test: 15,000 + 15,000 characters against bootstrapMaxChars 20,000.
    agents = f"# Agent\n\n## Tools\n\n{'a' * 15_000}\n"
    tools = f"{'b' * 15_000}\n"
    merged = f"{agents}\n### Local notes (migrated from TOOLS.md)\n\n{tools}"
    root = _workspace(tmp_path, agents, tools)

    legacy, limit = tools_md_migration_findings(root, bootstrap_max_chars=20_000)

    assert legacy.requirement == "legacy-tools-md"
    assert limit.requirement == "tools-md-merged-bootstrap-limit"
    assert limit.path == str(root / "AGENTS.md")
    assert limit.message == (
        f'Agent "main" TOOLS.md migration will produce a {len(merged)}-character AGENTS.md, '
        "exceeding its configured bootstrapMaxChars limit of 20000. Raise "
        "`agents.entries.*.bootstrapMaxChars` for this agent, or `agents.defaults.bootstrapMaxChars` "
        "as fallback, to preserve all migrated instructions."
    )
    assert len(tools_md_migration_findings(root, bootstrap_max_chars=40_000)) == 1
    # An astral character is two UTF-16 units, as in JavaScript's String length.
    (root / "TOOLS.md").write_text("\U0001F600" * 10_001, encoding="utf-8")
    assert [f.requirement for f in tools_md_migration_findings(root, agent_id="ops")] == [
        "legacy-tools-md",
        "tools-md-merged-bootstrap-limit",
    ]


def test_findings_skip_the_size_check_for_a_template_and_report_blocked_files(tmp_path):
    root = _workspace(tmp_path, "x" * 30_000, LEGACY_TOOLS_MD_TEMPLATE)
    assert [f.requirement for f in tools_md_migration_findings(root)] == ["legacy-tools-md"]

    (root / "TOOLS.md.doctor-importing-1").write_text("x", encoding="utf-8")
    (blocked,) = tools_md_migration_findings(root)
    assert blocked.severity == "error"
    assert blocked.requirement == "tools-md-migration-blocked"
    assert blocked.message.startswith(
        'Agent "main" TOOLS.md cannot be migrated: Interrupted v2026.7.2-beta.5 migration'
    )


def test_findings_report_a_symlinked_agents_md_after_the_legacy_finding(tmp_path):
    root = _workspace(tmp_path, None, "Local tool notes.\n")
    outside = tmp_path / "outside-agents.md"
    outside.write_text("Private external instructions.\n", encoding="utf-8")
    (root / "AGENTS.md").symlink_to(outside)

    findings = tools_md_migration_findings(root)

    assert [(f.requirement, f.severity) for f in findings] == [
        ("legacy-tools-md", "warning"),
        ("tools-md-migration-blocked", "error"),
    ]
    assert findings[1].message == (
        'Agent "main" TOOLS.md cannot be migrated: AGENTS.md must be an unlinked regular file '
        "for automatic migration"
    )
    assert tools_md_migration_findings(tmp_path / "missing") == ()
