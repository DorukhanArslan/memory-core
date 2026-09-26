import os
from pathlib import Path

from memory_core import OPENCLAW_COMPAT_RUNTIME_IDENTITY
from memory_core.bootstrap import (
    MEMORY_CORE_WORKSPACE_LAYOUT,
    OPENCLAW_PIN_LAYOUT,
    ContextFile,
    build_bootstrap_prompt_section_lines,
    build_workspace_context,
    initialize_agent_workspace,
    load_workspace_bootstrap_files,
    render_bootstrap_prompt_sections,
    render_project_context,
    render_workspace_files_injected,
    sort_context_files,
)
from memory_core.bootstrap.render import DEFAULT_HEARTBEAT_PROMPT_CONTEXT_BLOCK
from memory_core.workspace import MemoryWorkspace


def _paths(files):
    return [file.path for file in files]


def test_render_order_uses_priorities_then_icu_like_names():
    files = [
        ContextFile("/w/Zeta.md", "z"),
        ContextFile("/w/TOOLS.md", "t"),
        ContextFile("/w/PROACTIVE_PREFERENCES.md", "p"),
        ContextFile("/w/alpha.md", "a"),
        ContextFile("/w/USER.md", "u"),
        ContextFile("/w/AGENTS.md", "g"),
    ]

    assert _paths(sort_context_files(files, MEMORY_CORE_WORKSPACE_LAYOUT)) == [
        "/w/AGENTS.md",
        "/w/USER.md",
        "/w/PROACTIVE_PREFERENCES.md",
        "/w/TOOLS.md",
        "/w/alpha.md",
        "/w/Zeta.md",
    ]
    # Without the memory-core priority the file is an unknown basename.
    assert _paths(sort_context_files(files, OPENCLAW_PIN_LAYOUT))[-3:] == [
        "/w/alpha.md",
        "/w/PROACTIVE_PREFERENCES.md",
        "/w/Zeta.md",
    ]


def test_stable_block_drops_blank_lines_and_adds_guidance_lines():
    stable, dynamic = render_project_context(
        [
            ContextFile("/w/MEMORY.md", "- fact\n\n- next"),
            ContextFile("/w/SOUL.md", "calm"),
            ContextFile("/w/IDENTITY.md", ""),
        ],
        OPENCLAW_PIN_LAYOUT,
    )

    assert stable == (
        "# Project Context\n"
        "The following project context files have been loaded:\n"
        "SOUL.md: persona/tone. Follow it unless higher-priority instructions override.\n"
        "MEMORY.md: durable user preferences and behavior guidance. Keep following it "
        "throughout the session unless higher-priority instructions override.\n"
        "## /w/SOUL.md\n"
        "calm\n"
        "## /w/IDENTITY.md\n"
        "## /w/MEMORY.md\n"
        "- fact\n\n- next"
    )
    assert dynamic == ""


def test_heartbeat_is_dynamic_and_sanitized():
    content = f"tasks\n\n\n{DEFAULT_HEARTBEAT_PROMPT_CONTEXT_BLOCK}\n\n\nafter"
    stable, dynamic = render_project_context(
        [ContextFile("/w/AGENTS.md", "rules"), ContextFile("/w/HEARTBEAT.md", content)]
    )
    only_stable, only_dynamic = render_project_context([ContextFile("/w/HEARTBEAT.md", "beat")])

    assert "HEARTBEAT" not in stable
    assert dynamic == (
        "# Dynamic Project Context\n"
        "The following frequently-changing project context files are kept below the cache "
        "boundary when possible:\n"
        "## /w/HEARTBEAT.md\n"
        "tasks\n\nafter"
    )
    assert only_stable == ""
    assert only_dynamic.startswith("# Project Context\nThe following frequently-changing")


def test_workspace_files_line_goes_through_runtime_identity():
    assert render_workspace_files_injected() == (
        "## Workspace Files (injected)\n"
        "These user-editable files are loaded by memory-core and included below in Project Context."
    )
    assert render_workspace_files_injected(OPENCLAW_COMPAT_RUNTIME_IDENTITY) == (
        "## Workspace Files (injected)\n"
        "These user-editable files are loaded by OpenClaw and included below in Project Context."
    )


def test_bootstrap_pending_variants():
    in_context = build_bootstrap_prompt_section_lines(
        "full", context_files=[ContextFile("/w/BOOTSTRAP.md", "ritual")]
    )
    read_file = render_bootstrap_prompt_sections("full")
    limited = render_bootstrap_prompt_sections("limited", truncation_notice=" notice ")

    assert in_context[:2] == [
        "## Bootstrap Pending",
        "BOOTSTRAP.md is included below in Project Context; follow it before replying normally.",
    ]
    assert in_context[-2:] == [
        "Your first user-visible reply for a bootstrap-pending workspace must follow "
        "BOOTSTRAP.md, not a generic greeting.",
        "",
    ]
    assert read_file.splitlines()[1] == (
        "Please read BOOTSTRAP.md from the workspace and follow it before replying normally."
    )
    assert limited.splitlines()[:2] == [
        "## Bootstrap Pending",
        "Bootstrap is still pending for this workspace, but this run cannot safely complete the "
        "full BOOTSTRAP.md workflow here.",
    ]
    assert limited.endswith("## Bootstrap Context Notice\nnotice")
    assert render_bootstrap_prompt_sections("none") == ""


def test_workspace_context_for_a_pending_memory_core_workspace(tmp_path):
    initialize_agent_workspace(
        tmp_path,
        templates={
            "AGENTS.md": "# Rules\n",
            "PROACTIVE_PREFERENCES.md": "Morning digest\n",
            "HEARTBEAT.md": "- check calendar\n",
            "BOOTSTRAP.md": "Ask the user's name.\n",
        },
    )
    (tmp_path / "user" / "profile.md").write_text("never injected", encoding="utf-8")

    context = build_workspace_context(tmp_path, path_style="relative")

    assert context.bootstrap_status == "pending"
    assert context.bootstrap_mode == "full"
    assert _paths(context.files) == [
        "AGENTS.md",
        "PROACTIVE_PREFERENCES.md",
        "BOOTSTRAP.md",
        "HEARTBEAT.md",
    ]
    assert "## BOOTSTRAP.md\nAsk the user's name." in context.stable_text
    assert "never injected" not in context.stable_text
    assert context.dynamic_text.endswith("## HEARTBEAT.md\n- check calendar")
    assert context.bootstrap_text.startswith("## Bootstrap Pending\nBOOTSTRAP.md is included")
    assert context.workspace_notes == (
        "Reminder: commit your changes in this workspace after edits.",
    )
    assert context.record_completed_bootstrap_turn is True
    assert context.truncated is False and context.truncation_notice is None


def test_workspace_context_drops_bootstrap_unless_mode_is_full(tmp_path):
    initialize_agent_workspace(tmp_path, templates={"BOOTSTRAP.md": "ritual"})

    heartbeat = build_workspace_context(tmp_path, session_kind="heartbeat")
    subagent = build_workspace_context(tmp_path, session_kind="subagent")

    assert heartbeat.bootstrap_mode == "none"
    assert "BOOTSTRAP.md" not in heartbeat.stable_text
    assert heartbeat.bootstrap_text == ""
    assert heartbeat.workspace_notes  # BOOTSTRAP.md was loaded before the mode filter
    assert subagent.bootstrap_mode == "none"
    assert [file.name for file in subagent.bootstrap_files] == ["AGENTS.md", "TOOLS.md"]
    assert subagent.files == ()  # empty templates are never injected


def test_workspace_context_injection_skip_and_truncation(tmp_path):
    initialize_agent_workspace(tmp_path, templates={"AGENTS.md": "a" * 500})
    (tmp_path / "USER.md").write_text("Doruk", encoding="utf-8")
    initialize_agent_workspace(tmp_path)

    never = build_workspace_context(tmp_path, context_injection="never")
    continuation = build_workspace_context(
        tmp_path, context_injection="continuation-skip", has_completed_bootstrap_turn=True
    )
    truncated = build_workspace_context(tmp_path, max_chars=100)

    assert never.injection_skipped is True and never.stable_text == ""
    assert continuation.injection_skipped is True
    assert truncated.truncated is True
    assert truncated.truncation_notice is not None
    assert "## Bootstrap Context Notice\n[Bootstrap truncation warning]" in truncated.bootstrap_text
    assert truncated.warnings == (
        "workspace bootstrap file AGENTS.md is 500 chars (limit 100); truncating in injected context",
    )


def test_memory_core_extra_dirs_are_never_injected_or_indexed(tmp_path):
    initialize_agent_workspace(tmp_path, seed_bootstrap=False)
    for relative, content in {
        "user/AGENTS.md": "per-user rules",
        "user/MEMORY.md": "per-user memory",
        "workspace/2026-09-26.md": "artifact",
        "workspace/memory/2026-09-26.md": "artifact log",
        "AGENTS.md": "root rules",
    }.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    loaded = load_workspace_bootstrap_files(tmp_path, MEMORY_CORE_WORKSPACE_LAYOUT)
    context = build_workspace_context(tmp_path)
    indexed = MemoryWorkspace(tmp_path).discover_memory_files()

    assert all(Path(file.path).parent == Path(os.path.abspath(tmp_path)) for file in loaded)
    assert [file.content for file in context.files] == ["root rules"]
    assert "per-user" not in context.stable_text
    assert indexed == []
