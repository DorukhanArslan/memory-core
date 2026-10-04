import errno
import json
import os
from pathlib import Path

import pytest

from memory_core import session_memory
from memory_core._intl_zone_names import en_us_short_time_zone_name, localized_gmt_name
from memory_core.bootstrap import build_startup_context
from memory_core.session_memory import (
    SessionTimestamp,
    build_session_memory_entry,
    format_local_session_timestamp,
    is_session_memory_trigger,
    resolve_available_memory_filename,
    resolve_session_memory_message_count,
    save_session_memory,
)
from memory_core.workspace import MemoryWorkspace, UnsafeMemoryPathError

# Scenarios follow src/hooks/bundled/session-memory/handler.test.ts at v2026.9.6.
NOW_MS = 1767241815000  # 2026-01-01T04:30:15.000Z


def _row(role: str, content) -> dict:
    return {"type": "message", "message": {"role": role, "content": content}}


def _write_session(path: Path, *pairs) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(_row(*pair)) for pair in pairs), encoding="utf-8")
    return path


def test_trigger_gate_and_message_count():
    assert is_session_memory_trigger("command", "new")
    assert is_session_memory_trigger("command", "reset")
    # Automatic rollover: session/auto-reset with reason daily or idle.
    assert is_session_memory_trigger("session", "auto-reset", "daily")
    assert is_session_memory_trigger("session", "auto-reset", "idle")
    assert not is_session_memory_trigger("session", "auto-reset", "manual")
    assert not is_session_memory_trigger("session", "auto-reset")
    assert not is_session_memory_trigger("session", "start", "daily")
    assert not is_session_memory_trigger("command", "help")
    assert not is_session_memory_trigger("agent", "bootstrap")
    assert resolve_session_memory_message_count(3) == 3
    assert resolve_session_memory_message_count(2.5) == 2.5
    for value in (0, -2, "5", None, True, float("nan")):
        assert resolve_session_memory_message_count(value) == 15


def test_timestamp_uses_the_given_zone():
    assert format_local_session_timestamp(NOW_MS, "America/New_York") == SessionTimestamp(
        "2025-12-31", "23:30:15", "2330", "America/New_York"
    )
    assert format_local_session_timestamp(NOW_MS, " Europe/Istanbul ") == SessionTimestamp(
        "2026-01-01", "07:30:15", "0730", "Europe/Istanbul"
    )
    assert format_local_session_timestamp(NOW_MS + 999, "UTC").time == "04:30:15"
    for zone in ("Mars/Olympus", "", "../etc/passwd"):
        with pytest.raises(ValueError, match="unknown timezone"):
            format_local_session_timestamp(NOW_MS, zone)
    for value in (float("nan"), float("inf"), True, "1767241815000"):
        with pytest.raises(ValueError, match="invalid timestamp"):
            format_local_session_timestamp(value, "UTC")


def test_zone_names_follow_icu_en_us():
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    def name(zone: str, month: int) -> str:
        instant = datetime(2026, month, 15, 12, tzinfo=UTC)
        return en_us_short_time_zone_name(zone, instant.astimezone(ZoneInfo(zone)))

    assert [name("America/New_York", 1), name("America/New_York", 7)] == ["EST", "EDT"]
    assert [name("Europe/London", 1), name("Europe/London", 7)] == ["GMT", "GMT+1"]
    assert [name("Europe/Lisbon", 1), name("America/Adak", 1)] == ["GMT+0", "HAST"]
    assert [name("Etc/UTC", 1), name("UTC", 7), name("Asia/Kolkata", 1)] == [
        "UTC",
        "UTC",
        "GMT+5:30",
    ]
    assert [localized_gmt_name(-12_600), localized_gmt_name(-2_670)] == ["GMT-3:30", "GMT-0:44:30"]


def test_entry_template():
    stamp = SessionTimestamp("2026-01-16", "14:30:00", "1430", "America/New_York")

    assert build_session_memory_entry(
        timestamp=stamp,
        session_key="agent:main:main",
        session_id="abc123def456",
        source="telegram",
        session_content=None,
    ) == (
        "# Session: 2026-01-16 14:30:00 America/New_York\n\n"
        "- **Session Key**: agent:main:main\n"
        "- **Session ID**: abc123def456\n"
        "- **Source**: telegram\n"
    )
    # An automatic rollover (session event) records its reason instead of the source.
    assert build_session_memory_entry(
        timestamp=stamp,
        session_key="agent:main:main",
        session_id="abc123def456",
        source="telegram",
        session_content=None,
        reason="idle",
        event_type="session",
    ).endswith("- **Reason**: idle\n")
    assert "- **Reason**: unknown\n" in build_session_memory_entry(
        timestamp=stamp,
        session_key="k",
        session_id=None,
        session_content=None,
        event_type="session",
    )
    # A transcript the host could not read leaves a quoted note.
    assert build_session_memory_entry(
        timestamp=stamp,
        session_key="k",
        session_id="s",
        session_content=None,
        unavailable_reason='disk "full"',
    ).endswith(
        "## Conversation Summary\n\n"
        '> Transcript content was unavailable: "disk \\"full\\""\n'
    )
    assert build_session_memory_entry(
        timestamp=SessionTimestamp("2026-01-16", "14:30:00", "1430", None),
        session_key="agent:main:main",
        session_id=None,
        source="",
        session_content="user: Hello there",
    ) == (
        "# Session: 2026-01-16 14:30:00\n\n"
        "- **Session Key**: agent:main:main\n"
        "- **Session ID**: unknown\n"
        "- **Source**: unknown\n\n"
        "## Conversation Summary\n\n"
        "user: Hello there\n"
    )


def test_available_filename_adds_suffixes(tmp_path: Path):
    assert resolve_available_memory_filename(tmp_path, "2026-01-01", "0430") == "2026-01-01-0430.md"
    (tmp_path / "2026-01-01-0430.md").write_text("", encoding="utf-8")
    os.symlink(tmp_path / "missing", tmp_path / "2026-01-01-0430-2.md")

    # A dangling symlink takes its name too (stricter than upstream's fs.access).
    assert resolve_available_memory_filename(tmp_path, "2026-01-01", "0430") == (
        "2026-01-01-0430-3.md"
    )


def test_save_writes_the_upstream_entry(tmp_path: Path):
    session = _write_session(
        tmp_path / "sessions" / "test-session.jsonl",
        ("user", "Hello there"),
        ("assistant", "Hi! How can I help?"),
    )
    events = [_row("user", "Hello there"), _row("assistant", "Hi! How can I help?")]

    result = save_session_memory(
        tmp_path,
        session_key="agent:main:main",
        session_id="test-123",
        events=events,
        now_ms=NOW_MS,
        timezone="America/New_York",
    )
    from_file = save_session_memory(
        tmp_path / "from-file",
        session_key="agent:main:main",
        session_id="test-123",
        session_file=session,
        now_ms=NOW_MS,
        timezone="America/New_York",
    )

    assert result.rel_path == "memory/2025-12-31-2330.md"
    assert result.path == (tmp_path / "memory" / "2025-12-31-2330.md").resolve()
    assert result.slug == "2330" and result.llm_slug is False
    assert result.origin_class == "untrusted"  # no sender metadata: untrusted like upstream
    assert from_file.session_file == str(session) and from_file.entry == result.entry
    assert result.path.read_text(encoding="utf-8") == result.entry == (
        "# Session: 2025-12-31 23:30:15 America/New_York\n\n"
        "- **Session Key**: agent:main:main\n"
        "- **Session ID**: test-123\n"
        "- **Source**: unknown\n\n"
        "## Conversation Summary\n\n"
        'user: "Hello there"\nassistant: "Hi! How can I help?"\n'
    )


def test_same_minute_saves_get_suffixes_and_never_overwrite(tmp_path: Path):
    first = save_session_memory(
        tmp_path, session_key="agent:main:main", session_id="first-session", now_ms=NOW_MS
    )
    second = save_session_memory(
        tmp_path, session_key="agent:main:main", session_id="second-session", now_ms=NOW_MS
    )

    assert [first.rel_path, second.rel_path] == [
        "memory/2026-01-01-0430.md",
        "memory/2026-01-01-0430-2.md",
    ]
    assert "- **Session ID**: first-session" in first.path.read_text(encoding="utf-8")
    assert sorted(os.listdir(tmp_path / "memory")) == ["2026-01-01-0430-2.md", "2026-01-01-0430.md"]


def test_save_no_longer_recovers_reset_rotated_session_files(tmp_path: Path):
    # v2026.9.6 reads the transcript from the host's store; the ``.reset.`` file recovery went
    # with the file-era runtime, so a session id alone writes no conversation.
    _write_session(tmp_path / "sessions" / "missing-session-file.jsonl", ("user", "Recovered"))

    result = save_session_memory(
        tmp_path, session_key="agent:main:main", session_id="missing-session-file", now_ms=NOW_MS
    )

    assert result.session_file is None and result.session_content is None


def test_events_follow_the_active_branch_and_the_message_count(tmp_path: Path):
    def message(entry_id, parent_id, role, text):
        return {
            "type": "message",
            "id": entry_id,
            "parentId": parent_id,
            "message": {"role": role, "content": text},
        }

    events = [
        message("a", None, "user", "root"),
        message("b", "a", "assistant", "abandoned branch"),
        message("c", "a", "assistant", "active branch"),
        {"type": "leaf", "id": "l", "parentId": "c", "targetId": "c"},
        {"type": "custom", "id": "x", "parentId": "c"},
    ]

    result = save_session_memory(
        tmp_path, session_key="k", session_id="s", events=events, message_count=5, now_ms=NOW_MS
    )

    assert result.session_content == 'user: "root"\nassistant: "active branch"'
    # 0 and fractions: the config rule keeps 15 for non-positive counts, floors fractions.
    floored = save_session_memory(
        tmp_path, session_key="k", events=events[:3], message_count=1.9, now_ms=NOW_MS
    )
    assert floored.session_content == 'assistant: "active branch"'


def test_unavailable_transcript_and_rollover_entries(tmp_path: Path):
    result = save_session_memory(
        tmp_path,
        session_key="agent:main:main",
        session_id="s",
        unavailable_reason="database is locked",
        event_type="session",
        reason="daily",
        now_ms=NOW_MS,
    )

    assert result.entry.endswith(
        "- **Reason**: daily\n\n## Conversation Summary\n\n"
        '> Transcript content was unavailable: "database is locked"\n'
    )
    assert result.session_content is None


def test_save_from_messages_with_a_count(tmp_path: Path):
    messages = [{"role": "user", "content": f"Message {i}"} for i in range(1, 11)]

    result = save_session_memory(
        tmp_path, session_key="agent:main:main", messages=messages, message_count=3, now_ms=NOW_MS
    )

    assert result.session_file is None
    assert result.session_content == (
        'user: "Message 8"\nuser: "Message 9"\nuser: "Message 10"'
    )
    with pytest.raises(ValueError, match="at most one"):
        save_session_memory(
            tmp_path, session_key="k", messages=messages, session_file=tmp_path / "s.jsonl"
        )


def test_slug_generator_is_off_by_default_and_needs_content(tmp_path: Path):
    prompts: list[str] = []

    def generator(prompt: str) -> str:
        prompts.append(prompt)
        return "simple-math"

    empty = save_session_memory(
        tmp_path, session_key="agent:main:main", now_ms=NOW_MS, slug_generator=generator
    )
    messages = [{"role": "user", "content": "What is 2+2?"}]
    anonymous = save_session_memory(
        tmp_path,
        session_key="agent:main:main",
        session_id="  ",
        messages=messages,
        now_ms=NOW_MS,
        slug_generator=generator,
    )
    named = save_session_memory(
        tmp_path,
        session_key="agent:main:main",
        session_id="s1",
        messages=messages,
        now_ms=NOW_MS,
        slug_generator=generator,
    )

    assert empty.rel_path == "memory/2026-01-01-0430.md"
    # Like upstream, the slug run needs a non-blank session id and content.
    assert anonymous.rel_path == "memory/2026-01-01-0430-2.md" and anonymous.llm_slug is False
    assert named.rel_path == "memory/2026-01-01-simple-math.md" and named.llm_slug is True
    assert len(prompts) == 1 and 'user: "What is 2+2?"' in prompts[0]


def test_redactor_maps_lines_before_the_file_and_the_slug_prompt(tmp_path: Path):
    prompts: list[str] = []

    def generator(prompt: str) -> str:
        prompts.append(prompt)
        return "api-design"

    def redactor(line: str) -> str:
        return "" if "987-6543" in line else line.replace("123-4567", "[number]")

    result = save_session_memory(
        tmp_path,
        session_key="agent:main:main",
        session_id="s",
        messages=[
            {"role": "assistant", "content": "Your number is 123-4567"},
            {"role": "user", "content": "I changed it to 987-6543"},
        ],
        now_ms=NOW_MS,
        slug_generator=generator,
        redactor=redactor,
    )

    assert result.session_content == 'assistant: "Your number is [number]"'
    assert "123-4567" not in result.path.read_text(encoding="utf-8")
    assert "123-4567" not in prompts[0] and "987-6543" not in prompts[0]
    with pytest.raises(TypeError, match="redactor"):
        save_session_memory(
            tmp_path,
            session_key="k",
            messages=[{"role": "user", "content": "Hello"}],
            redactor=lambda line: None,
        )


def test_invalid_input_writes_nothing(tmp_path: Path):
    with pytest.raises(ValueError, match="unknown timezone"):
        save_session_memory(tmp_path, session_key="k", timezone="Mars/Olympus")
    with pytest.raises(TypeError, match="session_key"):
        save_session_memory(tmp_path, session_key=None)

    assert not (tmp_path / "memory").exists()


def test_memory_dir_outside_the_workspace_is_refused(tmp_path: Path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    os.symlink(outside, workspace / "memory")

    with pytest.raises(UnsafeMemoryPathError, match="escapes"):
        save_session_memory(workspace, session_key="k", now_ms=NOW_MS)
    assert os.listdir(outside) == []


def test_publish_without_hard_links_and_after_a_lost_race(tmp_path: Path, monkeypatch):
    real_link = os.link
    calls: list[str] = []

    def no_hard_links(src, dst, *args, **kwargs):
        calls.append(os.path.basename(dst))
        raise OSError(errno.EPERM, "hard links not supported")

    monkeypatch.setattr(session_memory.os, "link", no_hard_links)
    first = save_session_memory(tmp_path, session_key="k", session_id="first", now_ms=NOW_MS)

    def lose_first_race(src, dst, *args, **kwargs):
        calls.append(os.path.basename(dst))
        if len(calls) == 2:
            Path(dst).write_text("someone else", encoding="utf-8")
            raise FileExistsError(dst)
        return real_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(session_memory.os, "link", lose_first_race)
    second = save_session_memory(tmp_path, session_key="k", session_id="second", now_ms=NOW_MS)

    assert calls == ["2026-01-01-0430.md", "2026-01-01-0430-2.md", "2026-01-01-0430-3.md"]
    assert "- **Session ID**: first" in first.path.read_text(encoding="utf-8")
    assert (tmp_path / "memory" / "2026-01-01-0430-2.md").read_text(encoding="utf-8") == (
        "someone else"
    )
    assert second.rel_path == "memory/2026-01-01-0430-3.md"
    assert sorted(name for name in os.listdir(tmp_path / "memory") if name.startswith(".")) == []


def test_daily_flush_path_still_rejects_hook_names(tmp_path: Path):
    result = save_session_memory(
        tmp_path,
        session_key="agent:main:main",
        messages=[{"role": "user", "content": "Hello there"}],
        now_ms=NOW_MS,
    )
    workspace = MemoryWorkspace(tmp_path)

    with pytest.raises(UnsafeMemoryPathError, match="canonical daily"):
        workspace.append_daily_memory(result.rel_path, "- note")
    # The next session's startup context reads the slugged file (startup-context.ts).
    prelude = build_startup_context(tmp_path, now_ms=NOW_MS)
    assert "[Untrusted daily memory: memory/2026-01-01-0430.md]" in prelude
    assert 'user: "Hello there"' in prelude
