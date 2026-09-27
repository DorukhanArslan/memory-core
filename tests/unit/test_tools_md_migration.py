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
    assert should_merge_tools_md("　\n") is False
    assert should_merge_tools_md("x") is True
    # A fenced "## Tools" is not the Tools section.
    agents = "# A\n\n```\n## Tools\n```\n"
    assert merge_tools_md_into_agents_md(agents, "n\n") == f"{agents}\n## Tools\n\n{MIGRATED}\n\nn\n"


def test_archive_mode_is_private(tmp_path):
    root = _workspace(tmp_path, "# Agent\n", "notes\n")

    migrate_tools_md(root)

    assert oct(os.stat(_only_archive(root)).st_mode & 0o777) == oct(0o600)
