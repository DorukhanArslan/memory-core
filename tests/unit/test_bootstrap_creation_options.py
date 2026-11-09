"""Actual workspace effects of distinct baseline, creation and provisioning APIs."""
import pytest

from memory_core.bootstrap import (
    OPENCLAW_COMPAT_LAYOUT,
    WorkspaceBootstrapSeedConflictError,
    initialize_agent_workspace,
    is_workspace_setup_completed,
)


BASELINE = {"AGENTS.md": "Base instructions.\n", "SOUL.md": "Base personality.\n",
    "IDENTITY.md": "Base identity.\n", "USER.md": "Base user.\n", "BOOTSTRAP.md": "Setup ritual.\n"}
NOW = 1794182400000


def test_creation_override_does_not_replace_the_host_setup_baseline(tmp_path):
    result = initialize_agent_workspace(tmp_path, layout=OPENCLAW_COMPAT_LAYOUT, templates=BASELINE,
        creation_templates={"SOUL.md": "Approved custom role.\n"}, now_ms=NOW)
    assert (tmp_path / "SOUL.md").read_text() == "Approved custom role.\n"
    assert result.bootstrap_pending is False
    assert result.bootstrap_status == "complete"
    assert is_workspace_setup_completed(tmp_path)
    assert not (tmp_path / "BOOTSTRAP.md").exists()


def test_existing_host_baseline_api_still_seeds_a_pending_workspace(tmp_path):
    result = initialize_agent_workspace(tmp_path, layout=OPENCLAW_COMPAT_LAYOUT, templates=BASELINE, now_ms=NOW)
    assert result.bootstrap_pending is True
    assert result.bootstrap_status == "pending"
    assert not is_workspace_setup_completed(tmp_path)
    assert (tmp_path / "BOOTSTRAP.md").read_text() == BASELINE["BOOTSTRAP.md"]


def test_creation_bytes_keep_front_matter_while_baseline_templates_are_stripped(tmp_path):
    literal = "---\ntitle: Role\n---\n\nDo the approved task.\n"
    result = initialize_agent_workspace(tmp_path, layout=OPENCLAW_COMPAT_LAYOUT, templates=BASELINE,
        creation_templates={"IDENTITY.md": literal}, now_ms=NOW)
    assert (tmp_path / "IDENTITY.md").read_text() == literal
    assert result.bootstrap_pending is False


def test_approved_purpose_is_idempotent_and_a_conflict_preserves_existing_bytes(tmp_path):
    expected = "# Agent purpose\n\nHelp with the approved project.\n\n" + BASELINE["AGENTS.md"]
    first = initialize_agent_workspace(tmp_path, layout=OPENCLAW_COMPAT_LAYOUT, templates=BASELINE,
        purpose="\ufeff Help with the approved project. \n", now_ms=NOW)
    identity = (tmp_path / "AGENTS.md").stat().st_ino
    second = initialize_agent_workspace(tmp_path, layout=OPENCLAW_COMPAT_LAYOUT, templates=BASELINE,
        purpose="Help with the approved project.", now_ms=NOW)
    assert first.bootstrap_pending and second.bootstrap_pending
    assert (tmp_path / "AGENTS.md").read_text() == expected
    assert "AGENTS.md" not in second.created_files
    with pytest.raises(WorkspaceBootstrapSeedConflictError, match="Existing AGENTS.md was preserved"):
        initialize_agent_workspace(tmp_path, layout=OPENCLAW_COMPAT_LAYOUT, templates=BASELINE,
            purpose="A different purpose.", now_ms=NOW)
    assert (tmp_path / "AGENTS.md").read_text() == expected
    assert (tmp_path / "AGENTS.md").stat().st_ino == identity


def test_purpose_and_even_an_empty_creation_role_conflict_before_mutation(tmp_path):
    root = tmp_path / "workspace"
    with pytest.raises(WorkspaceBootstrapSeedConflictError, match="without a bundled role"):
        initialize_agent_workspace(root, templates=BASELINE, purpose="Approved task", creation_templates={})
    assert not root.exists()


def test_disabling_bootstrap_files_creates_only_the_directory(tmp_path):
    root = tmp_path / "workspace"
    result = initialize_agent_workspace(root, ensure_bootstrap_files=False, templates=BASELINE)
    assert root.is_dir() and list(root.iterdir()) == []
    assert result.created_files == result.created_dirs == ()
    assert result.bootstrap_pending is False
    assert result.bootstrap_status == "complete"
    assert result.state is not None and not result.state.has_marker


def test_disabled_seeding_has_a_false_ensure_decision_even_with_pending_status(tmp_path):
    (tmp_path / "BOOTSTRAP.md").write_text("Existing setup ritual.\n")
    result = initialize_agent_workspace(tmp_path, ensure_bootstrap_files=False)
    assert result.bootstrap_pending is False
    assert result.bootstrap_status == "pending"
    assert result.created_files == ()
    assert not (tmp_path / ".memory-core").exists()


def test_disabled_seeding_can_publish_only_approved_instructions(tmp_path):
    result = initialize_agent_workspace(tmp_path, ensure_bootstrap_files=False, templates=BASELINE,
        purpose="Approved task")
    assert result.created_files == ("AGENTS.md",)
    assert list(path.name for path in tmp_path.iterdir()) == ["AGENTS.md"]
    assert (tmp_path / "AGENTS.md").read_text() == "# Agent purpose\n\nApproved task\n\n" + BASELINE["AGENTS.md"]


def test_implicit_provisioning_skips_legacy_state_and_all_bootstrap_writes(tmp_path):
    (tmp_path / "openclaw-workspace-state.json").write_text("Retired setup state")
    result = initialize_agent_workspace(tmp_path, provisioning="runtime-managed-implicit", purpose="Approved task")
    assert result.bootstrap_pending is False
    assert result.bootstrap_status is None and result.state is None
    assert result.created_files == result.created_dirs == ()
    assert [path.name for path in tmp_path.iterdir()] == ["openclaw-workspace-state.json"]


def test_existing_seed_bootstrap_extension_remains_distinct_from_disabling_files(tmp_path):
    result = initialize_agent_workspace(tmp_path, templates=BASELINE, seed_bootstrap=False, now_ms=NOW)
    assert (tmp_path / "AGENTS.md").is_file()
    assert result.bootstrap_pending is False
    assert result.bootstrap_status == "complete"
    assert result.state is not None and result.state.setup_completed
