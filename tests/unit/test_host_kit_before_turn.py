"""HostKit.before_turn(): ensure, prompt and session fold (docs/host_kit.md, entry point 3)."""

from __future__ import annotations

import dataclasses

import pytest

from memory_core.bootstrap import (
    WorkspaceStateMigrationRequiredError,
    bootstrap_status,
    build_workspace_context,
)
from memory_core.bootstrap.lifecycle import legacy_workspace_state_paths
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import MINIMAL_PROMPT_KINDS, HostKit, SessionState
from memory_core.prompt_section import build_prompt_section
from memory_core.runtime_context_prompt import build_runtime_context_system_context
from memory_core.runtime_identity import OPENCLAW_COMPAT_RUNTIME_IDENTITY, MEMORY_CORE_RUNTIME_IDENTITY


def test_auto_citations_preserve_memory_prompt_guidance():
    tools = {"memory_search", "memory_get"}
    assert build_prompt_section(tools, citations_mode="auto") == build_prompt_section(
        tools, citations_mode="on",
    )

NOW_MS = 1_790_375_400_000  # 2026-09-25 22:30 UTC
TEMPLATES = {
    "AGENTS.md": "# AGENTS.md\n\nAnswer briefly.\n",
    "SOUL.md": "# SOUL.md\n\nCalm.\n",
    "BOOTSTRAP.md": "# BOOTSTRAP.md\n\nAsk for a name, then delete this file.\n",
}


def _memory(root, **config_options) -> Memory:
    config = MemoryConfig(
        workspace_dir=root, flags=FeatureFlags(vector_search=False), **config_options
    )
    return Memory.from_workspace(root, config=config, initialize=False, reindex=False)


def _kit(root, **options) -> HostKit:
    return HostKit(_memory(root), now_ms=lambda: NOW_MS, **options)


def _session(kind="main") -> SessionState:
    return SessionState.new(session_key=f"agent:main:{kind}", session_id="s1", kind=kind)


def _files(root) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix != ".sqlite"
    }


def _core_context(root, session, **overrides):
    options = {
        "session_kind": session.kind,
        "has_bootstrap_file_access": False,
        "has_completed_bootstrap_turn": session.completed_bootstrap_turn,
        "seen_truncation_signatures": session.seen_truncation_signatures,
        **overrides,
    }
    return build_workspace_context(root, **options)


def test_before_turn_runs_the_ensure_every_turn(tmp_path):
    kit = _kit(tmp_path, templates=TEMPLATES)

    first = kit.before_turn(_session())

    assert first.workspace_init is not None and first.workspace_init.bootstrap_seeded
    assert first.workspace.bootstrap_status == "pending"
    assert "BOOTSTRAP.md" in [file.path.rsplit("/", 1)[-1] for file in first.workspace.files]
    (tmp_path / "memory").mkdir()

    second = kit.before_turn(first.session)

    assert second.workspace_init.bootstrap_removed
    assert not (tmp_path / "BOOTSTRAP.md").exists()
    assert second.workspace.bootstrap_status == "complete"
    assert "Ask for a name" not in second.system_prompt


def test_before_turn_without_ensure_writes_nothing(tmp_path):
    kit = _kit(tmp_path, templates=TEMPLATES)
    kit.ensure()
    (tmp_path / "memory").mkdir()
    before = _files(tmp_path)

    turn = kit.before_turn(_session(), ensure=False)

    assert turn.workspace_init is None
    assert _files(tmp_path) == before
    assert (tmp_path / "BOOTSTRAP.md").exists()
    assert bootstrap_status(tmp_path) == "pending"


def test_before_turn_prompt_equals_the_core_composition(tmp_path):
    kit = _kit(tmp_path, templates=TEMPLATES, seed_bootstrap=False)
    kit.ensure()
    (tmp_path / "MEMORY.md").write_text("# MEMORY.md\n\n- The zephyrquartz project is paused.\n")
    session = _session()

    turn = kit.before_turn(session)

    expected = _core_context(tmp_path, session)
    section = build_prompt_section({tool["name"] for tool in kit.tools()}, citations_mode="on")
    assert turn.workspace == expected
    assert turn.tools == tuple(kit.tools())
    assert turn.memory_recall == tuple(section)
    assert turn.system_prompt == "\n\n".join(
        ["\n".join(section).strip(), expected.prompt_text.strip()]
    )
    assert turn.system_prompt.startswith("## Memory Recall\n")
    assert "zephyrquartz" in turn.system_prompt
    assert turn.runtime_context is None


@pytest.mark.parametrize("kind", sorted(MINIMAL_PROMPT_KINDS))
def test_minimal_kinds_get_no_memory_recall_section(tmp_path, kind):
    kit = _kit(tmp_path, templates=TEMPLATES, seed_bootstrap=False)
    session = _session(kind)

    turn = kit.before_turn(session)

    assert MINIMAL_PROMPT_KINDS == frozenset({"subagent", "cron"})
    assert turn.memory_recall == ()
    assert turn.tools == tuple(kit.tools())
    assert turn.system_prompt == _core_context(tmp_path, session).prompt_text.strip()


def test_memory_recall_section_follows_the_offered_tools(tmp_path):
    root = tmp_path / "ws"
    kit = HostKit(_memory(root, citation_mode="off"), seed_bootstrap=False)

    turn = kit.before_turn(_session())

    assert turn.memory_recall == tuple(
        build_prompt_section({tool["name"] for tool in kit.tools()}, citations_mode="off")
    )
    assert any(line.startswith("Citations are disabled") for line in turn.memory_recall)


def test_offer_tools_false_offers_no_tools_and_no_section(tmp_path):
    kit = _kit(tmp_path, templates=TEMPLATES, seed_bootstrap=False)
    session = _session()

    turn = kit.before_turn(session, offer_tools=False)

    assert turn.tools == ()
    assert turn.memory_recall == ()
    assert turn.system_prompt == _core_context(tmp_path, session).prompt_text.strip()


def test_run_kind_overrides_the_session_default(tmp_path):
    kit = _kit(tmp_path, templates=TEMPLATES, seed_bootstrap=True)
    session = _session()

    default = kit.before_turn(session)
    heartbeat = kit.before_turn(session, run_kind="heartbeat", context_mode="lightweight")

    assert default.workspace.bootstrap_mode == "full"
    assert heartbeat.workspace == _core_context(
        tmp_path, session, run_kind="heartbeat", context_mode="lightweight"
    )
    assert heartbeat.workspace.bootstrap_mode == "none"
    with pytest.raises(ValueError, match="run_kind"):
        kit.before_turn(session, run_kind="weekly")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="context_mode"):
        kit.before_turn(session, context_mode="heavy")  # type: ignore[arg-type]


def test_runtime_context_is_wrapped_in_the_identity_markers(tmp_path):
    kit = _kit(tmp_path, seed_bootstrap=False)
    compat = _kit(tmp_path, seed_bootstrap=False, identity=OPENCLAW_COMPAT_RUNTIME_IDENTITY)

    turn = kit.before_turn(_session(), runtime_context="  channel: #ops\n")

    assert turn.runtime_context == build_runtime_context_system_context("channel: #ops")
    assert MEMORY_CORE_RUNTIME_IDENTITY.runtime_context_begin in turn.runtime_context
    assert MEMORY_CORE_RUNTIME_IDENTITY.runtime_context_end in turn.runtime_context
    assert "channel: #ops" not in turn.system_prompt
    wrapped = compat.before_turn(_session(), runtime_context="channel: #ops").runtime_context
    assert OPENCLAW_COMPAT_RUNTIME_IDENTITY.runtime_context_begin in wrapped
    assert kit.before_turn(_session(), runtime_context=" \n").runtime_context is None


def test_before_turn_injects_no_search_results(tmp_path):
    kit = _kit(tmp_path, templates=TEMPLATES, seed_bootstrap=False)
    kit.ensure()
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "2026-09-25.md").write_text("- quokkabyte shipped the importer.\n")
    kit.memory.store.reindex(kit.memory.workspace)

    turn = kit.before_turn(_session(), runtime_context="quokkabyte")

    assert "shipped the importer" not in turn.system_prompt
    assert "shipped the importer" not in (turn.runtime_context or "")
    assert "Relevant memory" not in turn.system_prompt


def test_before_turn_folds_signatures_and_the_bootstrap_turn_into_the_session(tmp_path):
    kit = _kit(
        tmp_path,
        templates={**TEMPLATES, "AGENTS.md": "# AGENTS.md\n\n" + "rule. " * 400},
        seed_bootstrap=True,
        bootstrap_max_chars=600,
        truncation_warning_mode="once",
        context_injection="continuation-skip",
    )
    session = _session()

    first = kit.before_turn(session, has_bootstrap_file_access=True)

    expected = _core_context(
        tmp_path,
        session,
        has_bootstrap_file_access=True,
        max_chars=600,
        truncation_warning_mode="once",
        context_injection="continuation-skip",
    )
    assert first.workspace == expected
    assert first.workspace.prompt_warning.warning_shown
    assert first.session == dataclasses.replace(
        session,
        seen_truncation_signatures=tuple(expected.prompt_warning.warning_signatures_seen),
        completed_bootstrap_turn=True,
    )
    assert session.completed_bootstrap_turn is False
    second = kit.before_turn(first.session, has_bootstrap_file_access=True)
    assert not second.workspace.prompt_warning.warning_shown


def test_pending_bootstrap_without_file_access_is_limited(tmp_path):
    kit = _kit(tmp_path, seed_bootstrap=True)

    limited = kit.before_turn(_session())
    full = kit.before_turn(_session(), has_bootstrap_file_access=True)

    assert limited.workspace.bootstrap_status == "pending"
    assert limited.workspace.bootstrap_mode == "limited"
    assert full.workspace.bootstrap_mode == "full"


def test_retired_workspace_state_fails_closed(tmp_path):
    kit = _kit(tmp_path, seed_bootstrap=False)
    kit.ensure()
    legacy, _ = legacy_workspace_state_paths(tmp_path)
    legacy.write_text('{"version": 1, "setupCompletedAt": "2026-01-01T00:00:00.000Z"}')

    with pytest.raises(WorkspaceStateMigrationRequiredError):
        kit.before_turn(_session())
    with pytest.raises(WorkspaceStateMigrationRequiredError):
        kit.before_turn(_session(), ensure=False)
