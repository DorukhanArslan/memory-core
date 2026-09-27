import os
from pathlib import Path

import pytest

from memory_core.bootstrap import (
    GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES,
    OPENCLAW_COMPAT_LAYOUT,
    MEMORY_CORE_WORKSPACE_LAYOUT,
    WORKSPACE_BOOTSTRAP_FILENAMES,
    WorkspaceBootstrapFile,
    filter_bootstrap_files,
    filter_bootstrap_files_for_session,
    load_workspace_bootstrap_files,
    resolve_bootstrap_mode,
    resolve_context_injection,
)

# src/agents/workspace-bootstrap-policy.ts WORKSPACE_BOOTSTRAP_FILENAMES at v2026.9.6.
TAG_ORDER = [
    "AGENTS.md",
    "SOUL.md",
    "IDENTITY.md",
    "USER.md",
    "BOOTSTRAP.md",
    "MEMORY.md",
]


def _write(root: Path, name: str, content: str | bytes) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return path


def test_compat_layout_is_the_v2026_9_6_map():
    assert list(WORKSPACE_BOOTSTRAP_FILENAMES) == TAG_ORDER
    assert list(OPENCLAW_COMPAT_LAYOUT.load_order) == TAG_ORDER
    assert dict(OPENCLAW_COMPAT_LAYOUT.render_priorities) == {
        "agents.md": 10,
        "soul.md": 20,
        "identity.md": 30,
        "user.md": 40,
        "tools.md": 50,
        "bootstrap.md": 60,
        "memory.md": 70,
    }
    assert OPENCLAW_COMPAT_LAYOUT.required_files == ("AGENTS.md",)
    assert OPENCLAW_COMPAT_LAYOUT.optional_files == ("SOUL.md", "IDENTITY.md", "USER.md")
    assert OPENCLAW_COMPAT_LAYOUT.generated_files == GENERATED_WORKSPACE_BOOTSTRAP_FILENAMES
    assert OPENCLAW_COMPAT_LAYOUT.subagent_files == {"AGENTS.md"}
    assert OPENCLAW_COMPAT_LAYOUT.cron_files == {"AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md"}
    assert OPENCLAW_COMPAT_LAYOUT.skip_absent_files == {"USER.md", "MEMORY.md"}
    assert OPENCLAW_COMPAT_LAYOUT.extra_dirs == ()
    for layout in (OPENCLAW_COMPAT_LAYOUT, MEMORY_CORE_WORKSPACE_LAYOUT):
        assert "TOOLS.md" not in layout.load_order
        assert "HEARTBEAT.md" not in layout.load_order


def test_memory_core_layout_adds_proactive_preferences_after_user():
    order = list(MEMORY_CORE_WORKSPACE_LAYOUT.load_order)
    assert [name for name in order if name != "PROACTIVE_PREFERENCES.md"] == TAG_ORDER
    assert order.index("PROACTIVE_PREFERENCES.md") == order.index("USER.md") + 1
    assert MEMORY_CORE_WORKSPACE_LAYOUT.render_priority("proactive_preferences.md") == 45
    assert "PROACTIVE_PREFERENCES.md" in MEMORY_CORE_WORKSPACE_LAYOUT.optional_files
    assert "PROACTIVE_PREFERENCES.md" in MEMORY_CORE_WORKSPACE_LAYOUT.cron_files
    assert "PROACTIVE_PREFERENCES.md" not in MEMORY_CORE_WORKSPACE_LAYOUT.subagent_files
    assert "PROACTIVE_PREFERENCES.md" in MEMORY_CORE_WORKSPACE_LAYOUT.skip_absent_files
    assert MEMORY_CORE_WORKSPACE_LAYOUT.extra_dirs == ("user", "workspace")
    assert "MEMORY.md" not in MEMORY_CORE_WORKSPACE_LAYOUT.seed_order
    assert "BOOTSTRAP.md" not in MEMORY_CORE_WORKSPACE_LAYOUT.seed_order
    assert MEMORY_CORE_WORKSPACE_LAYOUT.is_expected_absent("PROACTIVE_PREFERENCES.md")
    assert not MEMORY_CORE_WORKSPACE_LAYOUT.is_expected_absent("AGENTS.md")


def test_loader_skips_absent_user_and_memory_and_marks_the_rest_missing(tmp_path):
    _write(tmp_path, "AGENTS.md", "rules\r\n")
    _write(tmp_path, "memory.md", "lowercase legacy file")

    files = load_workspace_bootstrap_files(tmp_path, OPENCLAW_COMPAT_LAYOUT)

    assert [file.name for file in files] == ["AGENTS.md", "SOUL.md", "IDENTITY.md", "BOOTSTRAP.md"]
    assert files[0] == WorkspaceBootstrapFile(
        "AGENTS.md", os.path.join(os.path.abspath(tmp_path), "AGENTS.md"), "rules\r\n"
    )
    assert all(file.missing for file in files[1:])


def test_loader_names_restrict_the_load(tmp_path):
    _write(tmp_path, "AGENTS.md", "a")
    _write(tmp_path, "USER.md", "u")

    files = load_workspace_bootstrap_files(tmp_path, OPENCLAW_COMPAT_LAYOUT, names=["USER.md", "AGENTS.md"])

    assert [file.name for file in files] == ["AGENTS.md", "USER.md"]


def test_loader_includes_exact_memory_file(tmp_path):
    _write(tmp_path, "MEMORY.md", "- fact 記憶\n")

    files = load_workspace_bootstrap_files(tmp_path, MEMORY_CORE_WORKSPACE_LAYOUT)

    assert files[-1].name == "MEMORY.md"
    assert files[-1].content == "- fact 記憶\n"
    # An absent extension file is skipped like an absent USER.md or MEMORY.md.
    assert "PROACTIVE_PREFERENCES.md" not in [file.name for file in files]
    assert "USER.md" not in [file.name for file in files]

    _write(tmp_path, "PROACTIVE_PREFERENCES.md", "")
    files = {file.name: file for file in load_workspace_bootstrap_files(tmp_path, MEMORY_CORE_WORKSPACE_LAYOUT)}
    assert files["PROACTIVE_PREFERENCES.md"].missing is False


def test_loader_marks_a_refused_extension_file_unreadable(tmp_path):
    # Listed but refused by the guarded read: upstream's [UNREADABLE: ...] content.
    outside = _write(tmp_path, "outside.md", "secret")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "PROACTIVE_PREFERENCES.md").symlink_to(outside)

    files = {file.name: file for file in load_workspace_bootstrap_files(root, MEMORY_CORE_WORKSPACE_LAYOUT)}

    refused = files["PROACTIVE_PREFERENCES.md"]
    assert refused.missing is False
    assert refused.content == "[UNREADABLE: symlink path component not allowed]"
    assert refused.unreadable_reason == "symlink path component not allowed"


def test_loader_guards_size_symlinks_hardlinks_and_file_type(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    _write(root, "AGENTS.md", b"a" * (2 * 1024 * 1024 + 1))
    outside = _write(tmp_path, "outside.md", "secret")
    (root / "SOUL.md").symlink_to(outside)
    inside = _write(root, "inside.md", "inside")
    (root / "USER.md").symlink_to(inside)
    notes = _write(root, "notes.md", "beat")
    os.link(notes, root / "IDENTITY.md")
    (root / "MEMORY.md").mkdir()
    _write(root, "BOOTSTRAP.md", b"bad \xff utf8")

    files = {file.name: file for file in load_workspace_bootstrap_files(root, OPENCLAW_COMPAT_LAYOUT)}

    unreadable = {name: file.content for name, file in files.items() if file.unreadable_reason}
    assert unreadable == {
        "AGENTS.md": "[UNREADABLE: File exceeds 2097152 bytes]",
        "SOUL.md": "[UNREADABLE: symlink path component not allowed]",
        # Even a symlink that stays inside the root (openRootFile follow-parents-within-root).
        "USER.md": "[UNREADABLE: symlink path component not allowed]",
        "IDENTITY.md": "[UNREADABLE: path must not be hardlinked]",
        "MEMORY.md": "[UNREADABLE: path does not have the required file type]",
    }
    assert not any(file.missing for file in files.values())
    assert files["BOOTSTRAP.md"].content == "bad \ufffd utf8"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_loader_reports_a_permission_error_like_node(tmp_path):
    locked = _write(tmp_path, "AGENTS.md", "rules")
    locked.chmod(0)
    try:
        files = load_workspace_bootstrap_files(tmp_path, OPENCLAW_COMPAT_LAYOUT, names=["AGENTS.md"])
    finally:
        locked.chmod(0o600)

    real = os.path.realpath(locked)
    assert files[0].content == f"[UNREADABLE: EACCES: permission denied, open '{real}']"


def _all_files(layout=MEMORY_CORE_WORKSPACE_LAYOUT) -> list[WorkspaceBootstrapFile]:
    return [
        WorkspaceBootstrapFile(name, f"/w/{name}", name.lower()) for name in layout.load_order
    ]


@pytest.mark.parametrize("kind", ["main", "direct", "heartbeat"])
def test_private_session_kinds_keep_every_file(kind):
    assert filter_bootstrap_files_for_session(_all_files(), kind, MEMORY_CORE_WORKSPACE_LAYOUT) == _all_files()


@pytest.mark.parametrize("kind", ["group", "channel"])
def test_shared_sessions_drop_the_root_memory_file(kind):
    # d06fc25a0c5 (#119198): root MEMORY.md is private to main and direct sessions.
    kept = filter_bootstrap_files_for_session(_all_files(), kind, MEMORY_CORE_WORKSPACE_LAYOUT, root="/w")
    nested = WorkspaceBootstrapFile("MEMORY.md", "/w/extra/MEMORY.md", "nested")
    with_nested = filter_bootstrap_files_for_session(
        [*_all_files(), nested], kind, MEMORY_CORE_WORKSPACE_LAYOUT, root="/w"
    )
    no_root = filter_bootstrap_files_for_session(
        [*_all_files(), nested], kind, MEMORY_CORE_WORKSPACE_LAYOUT
    )

    assert _names(kept) == [name for name in MEMORY_CORE_WORKSPACE_LAYOUT.load_order if name != "MEMORY.md"]
    # With the workspace root only the root file goes; without it every MEMORY.md goes.
    assert nested in with_nested
    assert "MEMORY.md" not in _names(no_root)


def test_subagent_and_cron_allowlists():
    subagent = filter_bootstrap_files_for_session(_all_files(), "subagent", MEMORY_CORE_WORKSPACE_LAYOUT)
    cron = filter_bootstrap_files_for_session(_all_files(), "cron", MEMORY_CORE_WORKSPACE_LAYOUT)
    compat_cron = filter_bootstrap_files_for_session(
        _all_files(OPENCLAW_COMPAT_LAYOUT), "cron", OPENCLAW_COMPAT_LAYOUT
    )

    assert [file.name for file in subagent] == ["AGENTS.md"]
    assert [file.name for file in cron] == [
        "AGENTS.md",
        "SOUL.md",
        "IDENTITY.md",
        "USER.md",
        "PROACTIVE_PREFERENCES.md",
    ]
    assert [file.name for file in compat_cron] == ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md"]
    with pytest.raises(ValueError):
        filter_bootstrap_files_for_session(_all_files(), "unknown", MEMORY_CORE_WORKSPACE_LAYOUT)


def _names(files):
    return [file.name for file in files]


def test_run_filters_follow_upstream_order():
    files = [WorkspaceBootstrapFile(n, f"/w/{n}", "x") for n in TAG_ORDER]
    common = {"root": "/w", "layout": OPENCLAW_COMPAT_LAYOUT}

    completed = filter_bootstrap_files(files, setup_completed=True, **common)
    lightweight = filter_bootstrap_files(files, context_mode="lightweight", **common)
    group = filter_bootstrap_files(files, session_kind="group", **common)

    assert "BOOTSTRAP.md" not in _names(completed)
    # applyContextModeFilter: lightweight runs (heartbeat included) get no bootstrap files.
    assert lightweight == []
    assert _names(group) == TAG_ORDER[:-1]


def test_resolve_bootstrap_mode_matrix():
    assert resolve_bootstrap_mode(bootstrap_pending=False) == "none"
    assert resolve_bootstrap_mode(bootstrap_pending=True) == "full"
    assert resolve_bootstrap_mode(bootstrap_pending=True, run_kind="heartbeat") == "none"
    assert resolve_bootstrap_mode(bootstrap_pending=True, run_kind="cron") == "none"
    assert resolve_bootstrap_mode(bootstrap_pending=True, is_primary_run=False) == "none"
    assert (
        resolve_bootstrap_mode(bootstrap_pending=True, is_interactive_user_facing=False) == "none"
    )
    assert (
        resolve_bootstrap_mode(bootstrap_pending=True, has_bootstrap_file_access=False)
        == "limited"
    )
    assert resolve_bootstrap_mode(bootstrap_pending=True, is_canonical_workspace=False) == "limited"


def test_context_injection_modes():
    always = resolve_context_injection("always", bootstrap_mode="none")
    never = resolve_context_injection("never", bootstrap_mode="full")
    continuation = resolve_context_injection(
        "continuation-skip", bootstrap_mode="none", has_completed_bootstrap_turn=True
    )
    first_turn = resolve_context_injection(
        "continuation-skip", bootstrap_mode="none", has_completed_bootstrap_turn=False
    )
    full_pending = resolve_context_injection(
        "continuation-skip", bootstrap_mode="full", has_completed_bootstrap_turn=True
    )
    heartbeat = resolve_context_injection(
        "continuation-skip",
        bootstrap_mode="none",
        run_kind="heartbeat",
        has_completed_bootstrap_turn=True,
    )

    assert (always.skip_injection, always.record_completed_bootstrap_turn) == (False, False)
    assert never.skip_injection is True and never.record_completed_bootstrap_turn is False
    assert continuation.skip_injection is True and continuation.is_continuation_turn is True
    assert first_turn.skip_injection is False
    assert full_pending.skip_injection is False
    assert full_pending.record_completed_bootstrap_turn is True
    assert heartbeat.skip_injection is False
    with pytest.raises(ValueError):
        resolve_context_injection("sometimes", bootstrap_mode="none")


def test_guarded_read_accepts_exactly_the_byte_cap(tmp_path):
    from memory_core.bootstrap.files import (
        MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES,
        read_workspace_file_guarded,
    )

    at_cap = _write(tmp_path, "AGENTS.md", b"a" * MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES)
    over_cap = _write(tmp_path, "SOUL.md", b"s" * (MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES + 1))

    assert len(read_workspace_file_guarded(at_cap, tmp_path)) == MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES
    assert read_workspace_file_guarded(over_cap, tmp_path) is None


def test_dedupe_reports_blank_paths_like_sanitize_bootstrap_files(tmp_path):
    from memory_core.bootstrap.files import dedupe_bootstrap_files

    warnings: list[str] = []
    files = [
        WorkspaceBootstrapFile("SOUL.md", "  ", "no path"),
        WorkspaceBootstrapFile("AGENTS.md", "AGENTS.md", "rules"),
        WorkspaceBootstrapFile("AGENTS.md", str(tmp_path / "AGENTS.md"), "duplicate"),
    ]

    kept = dedupe_bootstrap_files(files, tmp_path, warn=warnings.append)

    assert [file.content for file in kept] == ["rules"]
    # bootstrap-files.ts:180-185, verbatim.
    assert warnings == [
        'skipping bootstrap file "SOUL.md" — missing or invalid "path" field '
        '(hook may have used "filePath" instead)'
    ]
    assert dedupe_bootstrap_files(files, tmp_path) == kept
