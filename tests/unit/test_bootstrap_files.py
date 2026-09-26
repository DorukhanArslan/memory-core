import os
from pathlib import Path

import pytest

from memory_core.bootstrap import (
    MEMORY_CORE_WORKSPACE_LAYOUT,
    OPENCLAW_PIN_LAYOUT,
    WorkspaceBootstrapFile,
    filter_bootstrap_files,
    filter_bootstrap_files_for_session,
    load_workspace_bootstrap_files,
    resolve_bootstrap_mode,
    resolve_context_injection,
)

PIN_ORDER = [
    "AGENTS.md",
    "SOUL.md",
    "TOOLS.md",
    "IDENTITY.md",
    "USER.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",
    "MEMORY.md",
]


def _write(root: Path, name: str, content: str | bytes) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    return path


def test_pin_layout_orders_match_the_pin():
    assert list(OPENCLAW_PIN_LAYOUT.load_order) == PIN_ORDER
    assert dict(OPENCLAW_PIN_LAYOUT.render_priorities) == {
        "agents.md": 10,
        "soul.md": 20,
        "identity.md": 30,
        "user.md": 40,
        "tools.md": 50,
        "bootstrap.md": 60,
        "memory.md": 70,
    }
    assert OPENCLAW_PIN_LAYOUT.is_dynamic("HEARTBEAT.md")
    assert OPENCLAW_PIN_LAYOUT.required_files == ("AGENTS.md", "TOOLS.md")
    assert OPENCLAW_PIN_LAYOUT.extra_dirs == ()


def test_memory_core_layout_adds_proactive_preferences_after_user():
    order = list(MEMORY_CORE_WORKSPACE_LAYOUT.load_order)
    assert order.index("PROACTIVE_PREFERENCES.md") == order.index("USER.md") + 1
    assert MEMORY_CORE_WORKSPACE_LAYOUT.render_priority("proactive_preferences.md") == 45
    assert "PROACTIVE_PREFERENCES.md" in MEMORY_CORE_WORKSPACE_LAYOUT.optional_files
    assert "PROACTIVE_PREFERENCES.md" in MEMORY_CORE_WORKSPACE_LAYOUT.cron_files
    assert "PROACTIVE_PREFERENCES.md" not in MEMORY_CORE_WORKSPACE_LAYOUT.subagent_files
    assert MEMORY_CORE_WORKSPACE_LAYOUT.extra_dirs == ("user", "workspace")
    assert "MEMORY.md" not in MEMORY_CORE_WORKSPACE_LAYOUT.seed_order
    assert "BOOTSTRAP.md" not in MEMORY_CORE_WORKSPACE_LAYOUT.seed_order


def test_loader_skips_memory_without_exact_name_and_marks_missing(tmp_path):
    _write(tmp_path, "AGENTS.md", "rules\r\n")
    _write(tmp_path, "memory.md", "lowercase legacy file")

    files = load_workspace_bootstrap_files(tmp_path, OPENCLAW_PIN_LAYOUT)

    assert [file.name for file in files] == PIN_ORDER[:-1]
    assert files[0] == WorkspaceBootstrapFile(
        "AGENTS.md", os.path.join(os.path.abspath(tmp_path), "AGENTS.md"), "rules\r\n"
    )
    assert all(file.missing for file in files[1:])


def test_loader_includes_exact_memory_file(tmp_path):
    _write(tmp_path, "MEMORY.md", "- fact 記憶\n")

    files = load_workspace_bootstrap_files(tmp_path, MEMORY_CORE_WORKSPACE_LAYOUT)

    assert files[-1].name == "MEMORY.md"
    assert files[-1].content == "- fact 記憶\n"
    assert [file.name for file in files][5] == "PROACTIVE_PREFERENCES.md"


def test_loader_guards_size_symlink_escape_and_hardlinks(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    _write(root, "TOOLS.md", b"t" * (2 * 1024 * 1024 + 1))
    outside = _write(tmp_path, "outside.md", "secret")
    (root / "SOUL.md").symlink_to(outside)
    _write(root, "AGENTS.md", "inside")
    (root / "USER.md").symlink_to(root / "AGENTS.md")
    heartbeat = _write(root, "HEARTBEAT.md", "beat")
    os.link(heartbeat, root / "IDENTITY.md")
    _write(root, "BOOTSTRAP.md", b"bad \xff utf8")

    files = {file.name: file for file in load_workspace_bootstrap_files(root, OPENCLAW_PIN_LAYOUT)}

    assert files["TOOLS.md"].missing
    assert files["SOUL.md"].missing
    assert files["IDENTITY.md"].missing
    assert files["HEARTBEAT.md"].missing
    assert files["USER.md"].content == "inside"
    assert files["BOOTSTRAP.md"].content == "bad � utf8"


def _all_files(layout=MEMORY_CORE_WORKSPACE_LAYOUT) -> list[WorkspaceBootstrapFile]:
    return [
        WorkspaceBootstrapFile(name, f"/w/{name}", name.lower()) for name in layout.load_order
    ]


@pytest.mark.parametrize("kind", ["main", "group", "channel", "direct", "heartbeat"])
def test_session_kinds_that_keep_every_file(kind):
    assert filter_bootstrap_files_for_session(_all_files(), kind, MEMORY_CORE_WORKSPACE_LAYOUT) == _all_files()


def test_subagent_and_cron_allowlists():
    subagent = filter_bootstrap_files_for_session(_all_files(), "subagent", MEMORY_CORE_WORKSPACE_LAYOUT)
    cron = filter_bootstrap_files_for_session(_all_files(), "cron", MEMORY_CORE_WORKSPACE_LAYOUT)
    pin_cron = filter_bootstrap_files_for_session(
        _all_files(OPENCLAW_PIN_LAYOUT), "cron", OPENCLAW_PIN_LAYOUT
    )

    assert [file.name for file in subagent] == ["AGENTS.md", "TOOLS.md"]
    assert [file.name for file in cron] == [
        "AGENTS.md",
        "SOUL.md",
        "TOOLS.md",
        "IDENTITY.md",
        "USER.md",
        "PROACTIVE_PREFERENCES.md",
    ]
    assert [file.name for file in pin_cron] == [
        "AGENTS.md",
        "SOUL.md",
        "TOOLS.md",
        "IDENTITY.md",
        "USER.md",
    ]
    with pytest.raises(ValueError):
        filter_bootstrap_files_for_session(_all_files(), "unknown", MEMORY_CORE_WORKSPACE_LAYOUT)


def _names(files):
    return [file.name for file in files]


def test_run_filters_follow_upstream_order():
    files = [WorkspaceBootstrapFile(n, f"/w/{n}", "x") for n in PIN_ORDER]
    common = {"root": "/w", "layout": OPENCLAW_PIN_LAYOUT}

    completed = filter_bootstrap_files(files, setup_completed=True, **common)
    lightweight_heartbeat = filter_bootstrap_files(
        files, context_mode="lightweight", run_kind="heartbeat", **common
    )
    lightweight_default = filter_bootstrap_files(files, context_mode="lightweight", **common)
    commitment = filter_bootstrap_files(files, run_kind="commitment-only", **common)
    no_heartbeat = filter_bootstrap_files(files, include_heartbeat=False, **common)
    heartbeat_run = filter_bootstrap_files(
        files, run_kind="heartbeat", include_heartbeat=False, **common
    )

    assert "BOOTSTRAP.md" not in _names(completed)
    assert _names(lightweight_heartbeat) == ["HEARTBEAT.md"]
    assert lightweight_default == []
    assert "HEARTBEAT.md" not in _names(commitment)
    assert "HEARTBEAT.md" not in _names(no_heartbeat)
    assert "HEARTBEAT.md" in _names(heartbeat_run)


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
