import json

import pytest

from memory_core.bootstrap import (
    MEMORY_CORE_WORKSPACE_LAYOUT,
    OPENCLAW_PIN_LAYOUT,
    WorkspaceSetupState,
    bootstrap_status,
    initialize_agent_workspace,
    is_workspace_setup_completed,
    read_workspace_setup_state,
    strip_template_front_matter,
)

NOW_MS = 1_790_000_000_000
NOW_ISO = "2026-09-21T14:13:20.000Z"


def _state_file(root):
    return root / ".memory-core" / "workspace-state.json"


def test_fresh_memory_core_workspace_seeds_empty_files_dirs_and_bootstrap(tmp_path):
    root = tmp_path / "ws"

    result = initialize_agent_workspace(root, now_ms=NOW_MS)

    assert result.created_files == (
        "AGENTS.md",
        "SOUL.md",
        "TOOLS.md",
        "IDENTITY.md",
        "USER.md",
        "PROACTIVE_PREFERENCES.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
    )
    assert result.created_dirs == ("user", "workspace")
    assert result.bootstrap_seeded is True
    assert result.bootstrap_status == "pending"
    assert result.state == WorkspaceSetupState(bootstrap_seeded_at=NOW_ISO)
    for name in result.created_files:
        assert (root / name).read_text(encoding="utf-8") == ""
    assert not (root / "MEMORY.md").exists()
    assert not (root / "memory").exists()
    assert _state_file(root).read_text(encoding="utf-8") == (
        '{\n  "version": 1,\n  "bootstrapSeededAt": "2026-09-21T14:13:20.000Z"\n}\n'
    )


def test_templates_are_host_supplied_and_front_matter_is_stripped(tmp_path):
    templates = {
        "AGENTS.md": "---\ntitle: x\n---\n\n  # Host rules\n",
        "BOOTSTRAP.md": "Host ritual\n",
    }

    initialize_agent_workspace(tmp_path, layout=OPENCLAW_PIN_LAYOUT, templates=templates)

    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "# Host rules\n"
    assert (tmp_path / "BOOTSTRAP.md").read_text(encoding="utf-8") == "Host ritual\n"
    assert strip_template_front_matter("no front matter") == "no front matter"
    assert strip_template_front_matter("---\nunterminated") == "---\nunterminated"
    with pytest.raises(ValueError):
        initialize_agent_workspace(tmp_path, templates={"MEMORY.md": "never seeded"})


def test_existing_files_are_never_overwritten(tmp_path):
    (tmp_path / "AGENTS.md").write_text("mine", encoding="utf-8")

    result = initialize_agent_workspace(tmp_path, templates={"AGENTS.md": "template"})

    assert "AGENTS.md" not in result.created_files
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "mine"


def test_skip_optional_true_and_named(tmp_path):
    all_skipped = initialize_agent_workspace(tmp_path / "a", skip_optional=True)
    named = initialize_agent_workspace(tmp_path / "b", skip_optional=["SOUL.md", "AGENTS.md"])

    assert all_skipped.created_files == ("AGENTS.md", "TOOLS.md", "BOOTSTRAP.md")
    # Required files ignore the skip list, like upstream.
    assert "AGENTS.md" in named.created_files
    assert "SOUL.md" not in named.created_files
    assert "USER.md" in named.created_files


def test_skip_optional_accepts_a_single_name(tmp_path):
    result = initialize_agent_workspace(tmp_path / "ws", skip_optional="SOUL.md")

    assert "SOUL.md" not in result.created_files
    assert "USER.md" in result.created_files


@pytest.mark.parametrize(
    "evidence",
    [
        lambda root: (root / "memory").mkdir(),
        lambda root: (root / "MEMORY.md").write_text("- fact\n", encoding="utf-8"),
        lambda root: (root / ".git").mkdir(),
        lambda root: (root / "skills" / "demo").mkdir(parents=True)
        or (root / "skills" / "demo" / "SKILL.md").write_text("# s\n", encoding="utf-8"),
        lambda root: (root / "USER.md").write_text("Doruk\n", encoding="utf-8"),
    ],
    ids=["memory-dir", "memory-file", "git", "skill", "custom-profile"],
)
def test_configured_workspace_never_gets_bootstrap(tmp_path, evidence):
    root = tmp_path / "ws"
    root.mkdir()
    evidence(root)

    result = initialize_agent_workspace(root, now_ms=NOW_MS)

    assert result.bootstrap_seeded is False
    assert not (root / "BOOTSTRAP.md").exists()
    assert result.state == WorkspaceSetupState(setup_completed_at=NOW_ISO)
    assert result.bootstrap_status == "complete"


def test_skill_dir_without_skill_file_is_not_evidence(tmp_path):
    (tmp_path / "skills" / "empty").mkdir(parents=True)

    assert initialize_agent_workspace(tmp_path).bootstrap_seeded is True


def test_reconcile_deletes_bootstrap_once_profile_is_configured(tmp_path):
    initialize_agent_workspace(tmp_path, now_ms=NOW_MS)
    (tmp_path / "IDENTITY.md").write_text("Name: memory-core\n", encoding="utf-8")

    result = initialize_agent_workspace(tmp_path, now_ms=NOW_MS + 1000)

    assert result.bootstrap_removed is True
    assert not (tmp_path / "BOOTSTRAP.md").exists()
    assert result.state == WorkspaceSetupState(
        bootstrap_seeded_at=NOW_ISO, setup_completed_at="2026-09-21T14:13:21.000Z"
    )
    assert bootstrap_status(tmp_path) == "complete"
    assert is_workspace_setup_completed(tmp_path)


def test_agent_deleting_bootstrap_completes_setup(tmp_path):
    initialize_agent_workspace(tmp_path, now_ms=NOW_MS)
    (tmp_path / "BOOTSTRAP.md").unlink()

    result = initialize_agent_workspace(tmp_path, now_ms=NOW_MS + 5)

    assert result.bootstrap_removed is False
    assert result.state.setup_completed_at == "2026-09-21T14:13:20.005Z"
    assert not (tmp_path / "BOOTSTRAP.md").exists()


def test_completed_setup_does_not_recreate_optional_files(tmp_path):
    initialize_agent_workspace(tmp_path, layout=MEMORY_CORE_WORKSPACE_LAYOUT)
    (tmp_path / "USER.md").write_text("configured", encoding="utf-8")
    initialize_agent_workspace(tmp_path)
    (tmp_path / "SOUL.md").unlink()
    (tmp_path / "PROACTIVE_PREFERENCES.md").unlink()
    (tmp_path / "TOOLS.md").unlink()

    result = initialize_agent_workspace(tmp_path)

    assert result.created_files == ("TOOLS.md",)
    assert not (tmp_path / "SOUL.md").exists()
    assert not (tmp_path / "PROACTIVE_PREFERENCES.md").exists()


def test_seed_bootstrap_false_leaves_state_unmarked(tmp_path):
    result = initialize_agent_workspace(tmp_path, seed_bootstrap=False)

    assert result.bootstrap_seeded is False
    assert not (tmp_path / "BOOTSTRAP.md").exists()
    assert result.state == WorkspaceSetupState()
    assert not _state_file(tmp_path).exists()
    assert result.bootstrap_status == "complete"


def test_state_falls_back_to_openclaw_files_and_migrates(tmp_path):
    legacy = tmp_path / ".openclaw" / "workspace-state.json"
    legacy.parent.mkdir()
    legacy.write_text('{"onboardingCompletedAt": "2026-01-02T03:04:05.006Z"}', encoding="utf-8")

    assert read_workspace_setup_state(tmp_path) == WorkspaceSetupState(
        setup_completed_at="2026-01-02T03:04:05.006Z"
    )
    assert not _state_file(tmp_path).exists()

    result = initialize_agent_workspace(tmp_path)

    assert result.created_files == ("AGENTS.md", "TOOLS.md")
    assert json.loads(_state_file(tmp_path).read_text(encoding="utf-8")) == {
        "version": 1,
        "setupCompletedAt": "2026-01-02T03:04:05.006Z",
    }


def test_upstream_canonical_state_file_is_read(tmp_path):
    (tmp_path / "openclaw-workspace-state.json").write_text(
        json.dumps({"version": 1, "bootstrapSeededAt": "x"}), encoding="utf-8"
    )
    (tmp_path / "BOOTSTRAP.md").write_text("ritual", encoding="utf-8")

    assert read_workspace_setup_state(tmp_path).bootstrap_seeded_at == "x"
    assert bootstrap_status(tmp_path) == "pending"


@pytest.mark.parametrize("raw", ["not json", "null", "42", '"text"', "NaN"])
def test_unparseable_state_counts_as_absent(tmp_path, raw):
    path = _state_file(tmp_path)
    path.parent.mkdir()
    path.write_text(raw, encoding="utf-8")

    assert read_workspace_setup_state(tmp_path) == WorkspaceSetupState()


def test_whitespace_completion_is_not_complete(tmp_path):
    path = _state_file(tmp_path)
    path.parent.mkdir()
    path.write_text('{"version": 1, "setupCompletedAt": "   "}', encoding="utf-8")
    (tmp_path / "BOOTSTRAP.md").write_text("ritual", encoding="utf-8")

    assert is_workspace_setup_completed(tmp_path) is False
    assert bootstrap_status(tmp_path) == "pending"
