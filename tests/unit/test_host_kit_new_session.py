"""HostKit.on_new_session(): session memory and the bare reset turn (docs/host_kit.md, entry 5)."""

from __future__ import annotations

import pytest

from memory_core.bootstrap import (
    bootstrap_status,
    build_startup_context,
    format_session_reset_transcript_prompt,
    resolve_bare_session_reset_prompt_state,
)
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import HostKit, SessionState
from memory_core.session_memory import SESSION_MEMORY_FILE_RE, save_session_memory

NOW_MS = 1_790_375_400_000  # 2026-09-25 22:30 UTC, 2026-09-26 01:30 in Istanbul
TRANSCRIPT = [
    {"role": "user", "content": "The marbleowl migration moves to Friday."},
    {"role": "assistant", "content": "Understood, marbleowl is on Friday."},
]


def _kit(root, **options) -> HostKit:
    config = MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(root, config=config, initialize=False)
    kit = HostKit(memory, now_ms=lambda: NOW_MS, **options)
    kit.ensure()
    return kit


def _ending(kind="main") -> SessionState:
    return SessionState(
        session_key="agent:main:main",
        session_id="old",
        kind=kind,
        entry={"sessionId": "old", "compactionCount": 2, "memoryFlush": {"kind": "succeeded"}},
        last_output_tokens=9,
        seen_truncation_signatures=("sig",),
        completed_bootstrap_turn=True,
    )


def test_new_session_saves_the_ending_session_and_reindexes(tmp_path):
    kit = _kit(tmp_path / "ws")
    twin = tmp_path / "twin"
    twin.mkdir()

    result = kit.on_new_session(
        _ending(), command="new", session_id="new", transcript=TRANSCRIPT, source="lab"
    )

    expected = save_session_memory(
        twin, session_key="agent:main:main", session_id="old", messages=TRANSCRIPT,
        source="lab", now_ms=NOW_MS,
    )
    assert result.saved.rel_path == expected.rel_path
    assert SESSION_MEMORY_FILE_RE.match(result.saved.rel_path.removeprefix("memory/"))
    assert result.saved.entry == expected.entry
    hits = kit.dispatch("memory_search", {"query": "marbleowl"}, session=result.session)
    assert [hit["path"] for hit in hits["results"]] == [result.saved.rel_path]


def test_new_session_keeps_the_key_and_starts_a_fresh_entry(tmp_path):
    kit = _kit(tmp_path)

    result = kit.on_new_session(_ending("group"), command="reset", session_id="new", transcript=[])

    assert result.session == SessionState.new(
        session_key="agent:main:main", session_id="new", kind="group"
    )


def test_bare_reset_returns_the_upstream_prompt_and_transcript_row(tmp_path):
    kit = _kit(tmp_path)

    result = kit.on_new_session(_ending(), command="reset", session_id="new", transcript=TRANSCRIPT)

    state = resolve_bare_session_reset_prompt_state(
        tmp_path, now_ms=NOW_MS, has_bootstrap_file_access=False
    )
    assert result.reset.transcript_prompt == "[memory-core session reset]"
    assert result.reset.transcript_prompt == format_session_reset_transcript_prompt("reset")
    assert result.reset.bootstrap_mode == state.bootstrap_mode == "none"
    assert result.reset.prompt == state.prompt
    assert result.reset.model_prompt == f"{result.reset.startup_context}\n\n{state.prompt}"


def test_startup_context_quotes_the_saved_session_memory(tmp_path):
    kit = _kit(tmp_path)

    result = kit.on_new_session(_ending(), command="new", session_id="new", transcript=TRANSCRIPT)

    assert result.reset.startup_context == build_startup_context(tmp_path, now_ms=NOW_MS)
    assert result.saved.rel_path in result.reset.startup_context
    assert "marbleowl" in result.reset.startup_context


def test_new_session_reconciles_a_pending_bootstrap(tmp_path):
    kit = _kit(tmp_path, seed_bootstrap=True)
    assert bootstrap_status(tmp_path) == "pending"

    result = kit.on_new_session(_ending(), command="new", session_id="new", transcript=TRANSCRIPT)

    assert result.workspace_init.bootstrap_removed
    assert bootstrap_status(tmp_path) == "complete"
    assert result.reset.bootstrap_mode == "none"


def test_command_with_text_has_no_reset_turn(tmp_path):
    kit = _kit(tmp_path)

    result = kit.on_new_session(
        _ending(), command="new", session_id="new", transcript=TRANSCRIPT, text="plan Friday"
    )

    assert result.reset is None
    assert (tmp_path / result.saved.rel_path).is_file()
    assert kit.on_new_session(
        _ending(), command="new", session_id="n2", transcript=TRANSCRIPT, text="  "
    ).reset is not None


def test_new_session_passes_the_redactor_and_the_slug_generator(tmp_path):
    kit = _kit(tmp_path)
    prompts: list[str] = []

    def slug(prompt: str) -> str:
        prompts.append(prompt)
        return "marbleowl-migration"

    result = kit.on_new_session(
        _ending(),
        command="new",
        session_id="new",
        transcript=TRANSCRIPT,
        slug_generator=slug,
        redactor=lambda line: line.replace("Friday", "[day]"),
    )

    assert result.saved.slug == "marbleowl-migration" and result.saved.llm_slug
    assert result.saved.rel_path == "memory/2026-09-25-marbleowl-migration.md"
    text = (tmp_path / result.saved.rel_path).read_text()
    assert "Friday" not in text and "[day]" in text
    assert "Friday" not in prompts[0]


def test_new_session_uses_the_host_timezone_and_time_format(tmp_path):
    kit = _kit(tmp_path, timezone="Europe/Istanbul", time_format="12")

    result = kit.on_new_session(_ending(), command="new", session_id="new", transcript=TRANSCRIPT)

    state = resolve_bare_session_reset_prompt_state(
        tmp_path,
        now_ms=NOW_MS,
        timezone="Europe/Istanbul",
        time_format="12",
        has_bootstrap_file_access=False,
    )
    assert result.saved.rel_path == "memory/2026-09-26-0130.md"
    assert result.reset.model_prompt.endswith(state.prompt)
    assert "1:30 AM" in state.prompt


def test_both_transcript_sources_raise(tmp_path):
    kit = _kit(tmp_path)

    with pytest.raises(ValueError, match="not both"):
        kit.on_new_session(
            _ending(),
            command="new",
            session_id="new",
            transcript=TRANSCRIPT,
            session_file=tmp_path / "session.jsonl",
        )
    with pytest.raises(ValueError, match="command"):
        kit.on_new_session(_ending(), command="clear", session_id="new")  # type: ignore[arg-type]
    assert not (tmp_path / "memory").exists()
