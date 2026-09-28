"""FlushRequest: the flush run's messages, write tool and completion (docs/host_kit.md, Task 4b)."""

from __future__ import annotations

import json
import os
import threading

import pytest

from memory_core.bootstrap import bootstrap_status, build_workspace_context
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.host import FlushOutcome, HostKit, SessionState, TurnUsage
from memory_core.memory_paths import UnsafeMemoryPathError
from memory_core.runtime_context_prompt import build_runtime_context_custom_message

NOW_MS = 1_790_375_400_000  # 2026-09-25 22:30 UTC
TARGET = "memory/2026-09-25.md"
DUE = TurnUsage(176_000, 10)  # over the default window's 176,000-token threshold
TRANSCRIPT = (
    {"role": "user", "content": "We picked velvetkiwi as the codename."},
    {"role": "assistant", "content": "Noted: velvetkiwi."},
)


def _kit(root, **options) -> HostKit:
    config = MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(root, config=config, initialize=False)
    return HostKit(memory, now_ms=lambda: NOW_MS, **options)


def _session(**entry) -> SessionState:
    return SessionState(
        session_key="agent:main:main",
        session_id="s1",
        entry={"sessionId": "s1", "compactionCount": 0, **entry},
    )


def _due(kit, session=None, transcript=TRANSCRIPT):
    record = kit.after_turn(session or _session(), transcript=transcript, usage=DUE)
    assert record.flush is not None, record.flush_decision
    return record


def test_flush_request_creates_the_empty_target_file(tmp_path):
    kit = _kit(tmp_path, seed_bootstrap=True)
    kit.ensure()
    assert bootstrap_status(tmp_path) == "pending"

    record = _due(kit)

    assert record.flush.target == TARGET == record.flush_plan.relative_path
    assert (tmp_path / TARGET).read_bytes() == b""
    assert record.flush_failure is None
    kit.ensure()
    assert bootstrap_status(tmp_path) == "complete"
    (tmp_path / TARGET).write_text("- kept\n")
    _due(kit)
    assert (tmp_path / TARGET).read_text() == "- kept\n"


def test_flush_setup_failure_records_a_strike(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "ws"
    root.mkdir()
    (root / "memory").symlink_to(outside, target_is_directory=True)

    record = _kit(root).after_turn(_session(), transcript=TRANSCRIPT, usage=DUE)

    assert record.flush_decision.should_flush
    assert record.flush is None
    assert record.flush_failure.failure_count == 1
    assert "symlink" in record.flush_failure.error
    assert record.session.entry["memoryFlush"] == {"kind": "failed", "failureCount": 1}
    assert record.session.entry["totalTokens"] == 176_000
    assert list(outside.iterdir()) == []


def test_flush_messages_carry_context_transcript_and_prompt(tmp_path):
    kit = _kit(tmp_path, templates={"AGENTS.md": "# AGENTS.md\n\nBe brief.\n"})
    kit.ensure()
    session = _session()

    record = _due(kit, session)

    context = build_workspace_context(
        tmp_path,
        session_kind="main",
        is_interactive_user_facing=False,
        has_bootstrap_file_access=False,
    )
    assert context.bootstrap_mode == "none"
    system = record.flush.messages[0]
    assert system == {
        "role": "system",
        "content": context.prompt_text.strip()
        + "\n\n## Conversation Context\n"
        + record.flush_plan.system_prompt,
    }
    assert "Be brief." in system["content"]
    assert "## Memory Recall" not in system["content"]
    assert record.flush.messages[1:-1] == TRANSCRIPT
    assert record.flush.messages[-1] == {"role": "user", "content": record.flush_plan.prompt}


def test_flush_transcript_drops_runtime_context_rows(tmp_path):
    runtime_row = build_runtime_context_custom_message("channel: #ops")
    transcript = (
        TRANSCRIPT[0],
        runtime_row,
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": '{"status": "ok"}'},
        {"role": "assistant", "content": ""},
        TRANSCRIPT[1],
    )

    record = _due(_kit(tmp_path), transcript=transcript)

    assert record.flush.messages[1:-1] == TRANSCRIPT


def test_flush_transcript_keeps_the_text_of_content_lists(tmp_path):
    transcript = (
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "My cat is "},
                {"type": "input_text", "text": "Tom."},
            ],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "reasoning", "text": "hidden"},
                {"type": "output_text", "text": "Noted."},
                {"type": "tool_use", "id": "t1", "name": "memory_search", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "https://x.test/a.png"}}],
        },
    )

    record = _due(_kit(tmp_path), transcript=transcript)

    assert record.flush.messages[1:-1] == (
        {"role": "user", "content": "My cat is Tom."},
        {"role": "assistant", "content": "Noted."},
    )


def test_flush_offers_only_the_upstream_write_tool(tmp_path):
    record = _due(_kit(tmp_path))

    assert record.flush.tools == (
        {
            "name": "write",
            "description": (
                "Write/overwrite file; creates parent directories. "
                "During memory flush, this tool may only append to memory/2026-09-25.md."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path; relative/absolute."},
                    "content": {"type": "string", "description": "File content."},
                },
                "required": ["path", "content"],
            },
        },
    )
    assert json.loads(json.dumps(record.flush.tools)) == list(record.flush.tools)
    assert record.flush.dispatch("add_memory_entry", {"section": "A", "text": "b"}) == {
        "status": "error",
        "tool": "add_memory_entry",
        "error": "tool add_memory_entry is not available",
    }


def test_flush_write_appends_to_the_target_and_reindexes(tmp_path):
    kit = _kit(tmp_path)
    flush = _due(kit).flush

    result = flush.dispatch("write", json.dumps({"path": TARGET, "content": "- velvetkiwi codename"}))

    assert result == {
        "status": "ok",
        "tool": "write",
        "path": TARGET,
        "action": "appended",
        "text": "Appended content to memory/2026-09-25.md.",
    }
    assert (tmp_path / TARGET).read_text() == "- velvetkiwi codename\n"
    hits = kit.dispatch("memory_search", {"query": "velvetkiwi"}, session=_session())["results"]
    assert [hit["path"] for hit in hits] == [TARGET]


def test_flush_write_keeps_the_append_when_the_reindex_fails(tmp_path, monkeypatch):
    kit = _kit(tmp_path)
    flush = _due(kit).flush

    def broken(workspace):
        raise RuntimeError("index broke")

    monkeypatch.setattr(kit.memory.store, "reindex", broken)

    result = flush.dispatch("write", {"path": TARGET, "content": "- kept"})

    assert result["action"] == "appended" and result["afterWriteError"] == "index broke"
    assert (tmp_path / TARGET).read_text() == "- kept\n"
    assert flush.complete(_session()).entries == ("- kept",)


def test_parallel_flush_writes_append_every_entry(tmp_path):
    flush = _due(_kit(tmp_path)).flush
    errors: list[BaseException] = []
    start = threading.Barrier(8)

    def write(index: int) -> None:
        try:
            start.wait()
            for round_ in range(5):
                content = f"- fact {index}.{round_}"
                result = flush.dispatch("write", {"path": TARGET, "content": content})
                assert result["action"] == "appended", result
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    expected = sorted(f"- fact {index}.{round_}" for index in range(8) for round_ in range(5))
    assert sorted((tmp_path / TARGET).read_text().splitlines()) == expected
    assert sorted(flush.complete(_session()).entries) == expected


def test_flush_write_accepts_the_absolute_target_path(tmp_path):
    flush = _due(_kit(tmp_path)).flush

    result = flush.dispatch("write", {"path": str(tmp_path / TARGET), "content": "- absolute"})

    assert result["action"] == "appended"
    assert (tmp_path / TARGET).read_text() == "- absolute\n"


def test_flush_write_elsewhere_returns_the_upstream_restriction(tmp_path):
    flush = _due(_kit(tmp_path)).flush
    restricted = {
        "status": "error",
        "tool": "write",
        "error": "Memory flush writes are restricted to memory/2026-09-25.md; use that path only.",
    }

    for path in (
        "MEMORY.md",
        "memory/2026-09-24.md",
        f"@{TARGET}",
        "memory/../memory/other.md",
        str(tmp_path / "memory" / "2026-09-24.md"),
    ):
        assert flush.dispatch("write", {"path": path, "content": "x"}) == restricted
    assert flush.dispatch("write", {"content": "x"})["error"] == "path required"
    assert flush.dispatch("write", {"path": TARGET})["error"] == "content required"
    assert flush.dispatch("write", "[]")["error"] == "arguments must be a JSON object"
    assert (tmp_path / TARGET).read_text() == ""


def test_flush_write_skips_empty_content_and_the_exact_no_reply_token(tmp_path):
    flush = _due(_kit(tmp_path)).flush

    for content in ("", "  \n", "NO_REPLY", "  NO_REPLY\n"):
        assert flush.dispatch("write", {"path": TARGET, "content": content}) == {
            "status": "ok",
            "tool": "write",
            "path": TARGET,
            "action": "skipped",
        }
    assert (tmp_path / TARGET).read_text() == ""
    # Only the exact token is silent (decision Q12, the curated daily note's rule too).
    for content in ("NO_REPLY nothing to keep", "NO_REPLY_FACTS: tea"):
        assert flush.dispatch("write", {"path": TARGET, "content": content})["action"] == "appended"
    assert (tmp_path / TARGET).read_text() == "NO_REPLY nothing to keep\nNO_REPLY_FACTS: tea\n"
    outcome = flush.complete(_session())
    assert outcome.entries == ("NO_REPLY nothing to keep", "NO_REPLY_FACTS: tea")


def test_flush_write_refuses_a_symlinked_daily_file(tmp_path):
    flush = _due(_kit(tmp_path)).flush
    outside = tmp_path / "outside.md"
    outside.write_text("")
    (tmp_path / TARGET).unlink()
    (tmp_path / TARGET).symlink_to(outside)

    result = flush.dispatch("write", {"path": TARGET, "content": "- leaked"})

    assert result["status"] == "error"
    assert "symlink" in result["error"]
    assert outside.read_text() == ""
    (tmp_path / TARGET).unlink()
    os.link(outside, tmp_path / TARGET)
    assert "hard link" in flush.dispatch("write", {"path": TARGET, "content": "x"})["error"]


def test_flush_complete_marks_the_cycle_flushed(tmp_path):
    kit = _kit(
        tmp_path, templates={"AGENTS.md": "# AGENTS.md\n\n" + "x" * 400}, bootstrap_max_chars=100
    )
    kit.ensure()
    record = _due(kit)
    record.flush.dispatch("write", {"path": TARGET, "content": "- first"})
    record.flush.dispatch("write", {"path": TARGET, "content": "- second"})
    # The flush runs detached while the next turn runs; that turn's state is the host's current one.
    current = kit.before_turn(record.session, ensure=False).session
    assert current.seen_truncation_signatures != record.session.seen_truncation_signatures

    outcome = record.flush.complete(current)

    assert outcome == FlushOutcome(
        session=outcome.session, wrote=True, entries=("- first", "- second"), failure=None
    )
    assert outcome.session.entry["memoryFlush"] == {"kind": "succeeded", "compactionCount": 0}
    assert outcome.session.seen_truncation_signatures == current.seen_truncation_signatures
    # The next turn's after_turn runs after complete() (one maintenance lane per session).
    after = kit.after_turn(outcome.session, transcript=TRANSCRIPT, usage=DUE)
    assert after.flush is None
    assert after.flush_decision.reason == "already_flushed"
    next_cycle = kit.after_turn(
        outcome.session.after_compaction(), transcript=TRANSCRIPT, usage=DUE
    )
    assert next_cycle.flush is not None


def test_an_abandoned_flush_is_requested_again(tmp_path):
    # No pending-flush state: a run the host abandons records nothing, as upstream records nothing
    # for a cancelled flush, so the session's next after_turn requests the same cycle again.
    kit = _kit(tmp_path)
    abandoned = _due(kit)

    retry = kit.after_turn(abandoned.session, transcript=TRANSCRIPT, usage=DUE)

    assert retry.flush is not None
    assert retry.session.entry == abandoned.session.entry
    retry.flush.dispatch("write", {"path": TARGET, "content": "- once"})
    outcome = retry.flush.complete(retry.session)
    assert kit.after_turn(outcome.session, transcript=TRANSCRIPT, usage=DUE).flush is None
    assert (tmp_path / TARGET).read_text() == "- once\n"


def test_flush_complete_rejects_another_session(tmp_path):
    flush = _due(_kit(tmp_path)).flush
    other = SessionState.new(session_key="agent:main:main", session_id="s2")

    with pytest.raises(ValueError, match="s1"):
        flush.complete(other)
    assert flush.complete(_session()).failure is None


def test_flush_failures_strike_three_times_and_redact(tmp_path):
    kit = _kit(tmp_path)
    session = _session()

    for attempt in (1, 2, 3):
        record = _due(kit, session)
        cause = OSError("provider sk-secret-123 unreachable")
        try:
            raise RuntimeError("flush model failed") from cause
        except RuntimeError as error:
            outcome = record.flush.complete(
                record.session, error=error, redact=lambda text: text.replace("sk-secret-123", "***")
            )
        session = outcome.session
        assert outcome.failure.failure_count == attempt
        assert outcome.failure.error == "flush model failed | provider *** unreachable"
        assert outcome.wrote is False

    assert outcome.failure.exhausted
    assert session.entry["memoryFlush"] == {"kind": "succeeded", "compactionCount": 0}
    after = kit.after_turn(session, transcript=TRANSCRIPT, usage=DUE)
    assert after.flush_decision.reason == "already_flushed"


def test_flush_complete_twice_raises(tmp_path):
    flush = _due(_kit(tmp_path)).flush
    flush.complete(_session(), error="model timed out")

    with pytest.raises(RuntimeError, match="already completed"):
        flush.complete(_session())
    with pytest.raises(RuntimeError, match="already completed"):
        flush.dispatch("write", {"path": TARGET, "content": "late"})


# --- request_flush: the forced flush (memory-core extension, decision Q6) ---------------------


def test_after_turn_flush_request_carries_the_trigger_reason(tmp_path):
    record = _due(_kit(tmp_path))

    assert record.flush.reason == record.flush_decision.reason == "token_threshold"


def test_request_flush_is_forced_without_touching_the_token_snapshot(tmp_path):
    kit = _kit(tmp_path, templates={"AGENTS.md": "# AGENTS.md\n\nBe brief.\n"})
    kit.ensure()
    # Under the threshold and with a stale total: after_turn would not flush.
    session = _session(totalTokens=12, totalTokensFresh=False)
    assert kit.after_turn(session, transcript=TRANSCRIPT, usage=None).flush is None

    flush = kit.request_flush(session, transcript=TRANSCRIPT)

    assert flush.reason == "forced"
    assert flush.target == TARGET
    assert (tmp_path / TARGET).read_bytes() == b""
    # The same run after_turn would hand over: messages and the write tool.
    assert flush.messages == _due(kit, session).flush.messages
    assert [tool["name"] for tool in flush.tools] == ["write"]
    flush.dispatch("write", {"path": TARGET, "content": "- forced note"})
    outcome = flush.complete(session)
    assert outcome.entries == ("- forced note",)
    assert outcome.session.entry == {
        **session.entry,
        "memoryFlush": {"kind": "succeeded", "compactionCount": 0},
    }


def test_request_flush_keeps_the_heartbeat_skip(tmp_path):
    heartbeat = SessionState.new(session_key="agent:main:heartbeat", session_id="h1", kind="heartbeat")

    assert _kit(tmp_path).request_flush(heartbeat, transcript=TRANSCRIPT) is None
    assert not (tmp_path / "memory").exists()


def test_request_flush_keeps_the_one_flush_per_cycle_guard(tmp_path):
    kit = _kit(tmp_path)
    flushed = kit.request_flush(_session(), transcript=TRANSCRIPT).complete(_session()).session

    assert kit.request_flush(flushed, transcript=TRANSCRIPT) is None
    assert kit.request_flush(flushed.after_compaction(), transcript=TRANSCRIPT) is not None
    exhausted = _session()
    for _ in range(3):
        exhausted = kit.request_flush(exhausted, transcript=TRANSCRIPT).complete(
            exhausted, error="model timed out"
        ).session
    assert kit.request_flush(exhausted, transcript=TRANSCRIPT) is None


def test_request_flush_raises_when_the_target_cannot_be_created(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "ws"
    root.mkdir()
    (root / "memory").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafeMemoryPathError, match="symlink"):
        _kit(root).request_flush(_session(), transcript=TRANSCRIPT)
    assert list(outside.iterdir()) == []
