import json
from pathlib import Path

import pytest

from memory_core.bootstrap import (
    OPENCLAW_COMPAT_LAYOUT,
    MEMORY_CORE_WORKSPACE_LAYOUT,
    WorkspaceSetupState,
    WorkspaceStateMigrationError,
    WorkspaceStateMigrationRequiredError,
    bootstrap_status,
    build_workspace_context,
    initialize_agent_workspace,
    is_workspace_setup_completed,
    migrate_legacy_workspace_state,
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

    # v2026.9.6 seeds neither TOOLS.md (669db2968fc) nor HEARTBEAT.md (3e2b3ea4d5e).
    assert result.created_files == (
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "PROACTIVE_PREFERENCES.md",
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

    initialize_agent_workspace(tmp_path, layout=OPENCLAW_COMPAT_LAYOUT, templates=templates)

    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "# Host rules\n"
    assert (tmp_path / "BOOTSTRAP.md").read_text(encoding="utf-8") == "Host ritual\n"
    assert strip_template_front_matter("no front matter") == "no front matter"
    assert strip_template_front_matter("---\nunterminated") == "---\nunterminated"
    with pytest.raises(ValueError):
        initialize_agent_workspace(tmp_path, templates={"MEMORY.md": "never seeded"})
    with pytest.raises(ValueError):
        initialize_agent_workspace(tmp_path, templates={"TOOLS.md": "retired"})


def test_existing_files_are_never_overwritten(tmp_path):
    (tmp_path / "AGENTS.md").write_text("mine", encoding="utf-8")

    result = initialize_agent_workspace(tmp_path, templates={"AGENTS.md": "template"})

    assert "AGENTS.md" not in result.created_files
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "mine"


def test_skip_optional_true_and_named(tmp_path):
    all_skipped = initialize_agent_workspace(tmp_path / "a", skip_optional=True)
    named = initialize_agent_workspace(tmp_path / "b", skip_optional=["SOUL.md", "AGENTS.md"])

    assert all_skipped.created_files == ("AGENTS.md", "BOOTSTRAP.md")
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
    (tmp_path / "AGENTS.md").unlink()

    result = initialize_agent_workspace(tmp_path)

    assert result.created_files == ("AGENTS.md",)
    assert not (tmp_path / "SOUL.md").exists()
    assert not (tmp_path / "PROACTIVE_PREFERENCES.md").exists()


def test_seed_bootstrap_false_marks_setup_complete(tmp_path):
    result = initialize_agent_workspace(tmp_path, seed_bootstrap=False, now_ms=NOW_MS)

    assert result.bootstrap_seeded is False
    assert not (tmp_path / "BOOTSTRAP.md").exists()
    # Extension: no ritual means nothing is pending, so setup completes right away.
    assert result.state == WorkspaceSetupState(setup_completed_at=NOW_ISO)
    assert json.loads(_state_file(tmp_path).read_text(encoding="utf-8")) == {
        "version": 1,
        "setupCompletedAt": NOW_ISO,
    }
    assert result.bootstrap_status == "complete"
    assert is_workspace_setup_completed(tmp_path) is True

    # Like any completed setup, optional files a user removed are not recreated.
    (tmp_path / "SOUL.md").unlink()
    again = initialize_agent_workspace(tmp_path, seed_bootstrap=False)
    assert again.created_files == ()
    assert not (tmp_path / "SOUL.md").exists()


def test_seed_bootstrap_false_still_honours_an_existing_bootstrap_file(tmp_path):
    (tmp_path / "BOOTSTRAP.md").write_text("host ritual\n", encoding="utf-8")

    result = initialize_agent_workspace(tmp_path, seed_bootstrap=False, now_ms=NOW_MS)

    assert result.state == WorkspaceSetupState(bootstrap_seeded_at=NOW_ISO)
    assert result.bootstrap_status == "pending"


@pytest.mark.parametrize(
    "legacy",
    [
        "openclaw-workspace-state.json",
        ".openclaw/workspace-state.json",
        "openclaw-workspace-state.json.doctor-importing",
    ],
)
def test_upstream_legacy_state_fails_closed_until_migrated(tmp_path, legacy):
    # workspace-legacy-state.ts assertNoUnmigratedWorkspaceState (#109147): upstream never
    # parses its retired JSON state at runtime and refuses the workspace instead.
    path = tmp_path / legacy
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not even json", encoding="utf-8")
    real = str(tmp_path.resolve())
    message = (
        f"Legacy workspace setup state requires migration for {real}; "
        "run memory_core.bootstrap.migrate_legacy_workspace_state()."
    )

    for call in (
        read_workspace_setup_state,
        is_workspace_setup_completed,
        bootstrap_status,
        build_workspace_context,
        initialize_agent_workspace,
    ):
        with pytest.raises(WorkspaceStateMigrationRequiredError) as raised:
            call(tmp_path)
        assert str(raised.value) == message
    # The refused ensure wrote nothing.
    assert sorted(item.name for item in tmp_path.iterdir()) == [Path(legacy).parts[0]]


def test_migrate_legacy_state_imports_archives_and_removes(tmp_path):
    legacy = tmp_path / ".openclaw" / "workspace-state.json"
    legacy.parent.mkdir()
    raw = '{"onboardingCompletedAt": "2026-01-02T03:04:05.006Z"}'
    legacy.write_text(raw, encoding="utf-8")

    result = migrate_legacy_workspace_state(tmp_path)

    assert result.imported == str(legacy.resolve())
    assert result.state == WorkspaceSetupState(setup_completed_at="2026-01-02T03:04:05.006Z")
    assert not legacy.exists()
    (archive,) = (Path(path) for path in result.archives)
    assert archive.parent == legacy.resolve().parent
    assert archive.name.startswith("workspace-state.json.migrated.")
    assert archive.read_text(encoding="utf-8") == raw
    assert json.loads(_state_file(tmp_path).read_text(encoding="utf-8")) == {
        "version": 1,
        "setupCompletedAt": "2026-01-02T03:04:05.006Z",
    }
    # The workspace runs again; setup was already complete, so nothing optional is seeded.
    assert initialize_agent_workspace(tmp_path).created_files == ("AGENTS.md",)


def test_migrate_legacy_state_keeps_existing_memory_core_state(tmp_path):
    initialize_agent_workspace(tmp_path, seed_bootstrap=False, now_ms=NOW_MS)
    (tmp_path / "openclaw-workspace-state.json").write_text(
        json.dumps({"version": 1, "bootstrapSeededAt": "2026-01-01T00:00:00.000Z"}),
        encoding="utf-8",
    )

    result = migrate_legacy_workspace_state(tmp_path)

    # Like upstream's "SQLite owns initialized milestones": cleanup only, no import.
    assert result.imported is None
    assert result.state == WorkspaceSetupState(setup_completed_at=NOW_ISO)
    assert not (tmp_path / "openclaw-workspace-state.json").exists()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("not json", "legacy workspace setup contains invalid JSON"),
        ("[]", "legacy workspace setup is not an object"),
        ('{"extra": 1}', "legacy workspace setup has an unexpected field"),
        ('{"version": 2}', "legacy workspace setup has an unsupported version"),
        ('{"setupCompletedAt": "2026-01-02"}', "legacy workspace setup completion timestamp is invalid"),
        (
            '{"setupCompletedAt": "2026-01-02T03:04:05.006Z", '
            '"onboardingCompletedAt": "2026-01-02T03:04:05.007Z"}',
            "legacy workspace setup has conflicting completion timestamps",
        ),
    ],
)
def test_migrate_legacy_state_refuses_malformed_sources(tmp_path, raw, message):
    source = tmp_path / "openclaw-workspace-state.json"
    source.write_text(raw, encoding="utf-8")

    with pytest.raises(WorkspaceStateMigrationError, match=message):
        migrate_legacy_workspace_state(tmp_path)
    # Nothing is removed or written when a source does not parse.
    assert source.read_text(encoding="utf-8") == raw
    assert not _state_file(tmp_path).exists()


def test_migrate_legacy_state_leaves_a_doctor_claim_alone(tmp_path):
    claim = tmp_path / "openclaw-workspace-state.json.doctor-importing"
    claim.write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceStateMigrationError, match="interrupted doctor claim"):
        migrate_legacy_workspace_state(tmp_path)
    assert claim.exists()


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


def test_initialize_rewrites_a_corrupt_memory_core_state_file(tmp_path):
    path = _state_file(tmp_path)
    path.parent.mkdir()
    path.write_text("not json", encoding="utf-8")

    result = initialize_agent_workspace(tmp_path, now_ms=NOW_MS)

    assert result.bootstrap_status == "pending"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1,
        "bootstrapSeededAt": NOW_ISO,
    }


def test_reconcile_keeps_completion_when_bootstrap_cleanup_fails(tmp_path, monkeypatch):
    import os

    from memory_core.bootstrap import lifecycle

    initialize_agent_workspace(tmp_path, templates={"BOOTSTRAP.md": "ritual\n"}, now_ms=NOW_MS)
    (tmp_path / "USER.md").write_text("Name: Doruk\n", encoding="utf-8")
    real_unlink = os.unlink

    def refuse_bootstrap(path, *args, **kwargs):
        if os.fspath(path).endswith("BOOTSTRAP.md"):
            raise PermissionError("read-only")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(lifecycle.os, "unlink", refuse_bootstrap)

    result = initialize_agent_workspace(
        tmp_path, templates={"BOOTSTRAP.md": "ritual\n"}, now_ms=NOW_MS + 1
    )

    # workspace.ts:437-459: completion state is authoritative, cleanup best-effort.
    assert result.bootstrap_removed is False
    assert (tmp_path / "BOOTSTRAP.md").exists()
    assert result.state.setup_completed_at == "2026-09-21T14:13:20.001Z"
    assert result.bootstrap_status == "complete"


def test_memory_core_state_path_that_is_a_file_reads_as_absent(tmp_path):
    (tmp_path / ".memory-core").write_text("not a directory", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("rules", encoding="utf-8")

    assert read_workspace_setup_state(tmp_path) == WorkspaceSetupState()
    context = build_workspace_context(tmp_path, path_style="relative")
    assert [file.content for file in context.files if file.path == "AGENTS.md"] == ["rules"]
    # Writing the state still fails loudly.
    with pytest.raises(OSError):
        initialize_agent_workspace(tmp_path)


def test_symlinked_workspace_root_is_loaded(tmp_path):
    real_root = tmp_path / "real"
    initialize_agent_workspace(real_root, templates={"AGENTS.md": "rules\n"}, seed_bootstrap=False)
    link = tmp_path / "link"
    link.symlink_to(real_root, target_is_directory=True)

    context = build_workspace_context(link, path_style="relative")

    assert [(file.path, file.content) for file in context.files] == [("AGENTS.md", "rules")]
    assert is_workspace_setup_completed(link) is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"load_order": ("AGENTS.md", "../escape.md")},
        {"optional_files": ("nested/SOUL.md",)},
        {"required_files": ("/abs/AGENTS.md",)},
        {"extra_dirs": ("../../outside",)},
        {"extra_dirs": ("..",)},
        {"bootstrap_file": ""},
        {"memory_file": "win\\MEMORY.md"},
    ],
)
def test_layout_rejects_names_that_are_not_plain_basenames(overrides):
    from dataclasses import replace

    with pytest.raises(ValueError, match="plain basenames"):
        replace(MEMORY_CORE_WORKSPACE_LAYOUT, **overrides)
