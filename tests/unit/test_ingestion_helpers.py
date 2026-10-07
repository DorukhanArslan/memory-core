"""Offline tests of the small ingestion helpers (the real TS code is compared in the oracle tests)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from memory_core.consolidation.daily_ingestion import (
    day_end_ms,
    daily_ingestion_lookback_days,
    is_day_within_lookback,
    normalize_daily_ingestion_state,
    normalize_memory_day,
    parse_daily_memory_file_name,
)
from memory_core.consolidation.session_ingestion import (
    SESSION_INGESTION_MAX_TRACKED_SCOPES,
    SessionCorpusEntry,
    append_session_corpus_text,
    foreign_session_ingestion_source,
    merge_tracked_message_hashes,
    normalize_session_ingestion_state,
    resolve_admission_policy,
    session_ingestion_source_from_corpus,
    session_path_for_file,
    trim_tracked_session_scopes,
)


def test_day_arithmetic_follows_v8_date_parse() -> None:
    assert day_end_ms("1970-01-01") == 86_399_999
    assert day_end_ms("2026-02-30") == day_end_ms("2026-03-02")  # V8 lets a day overflow its month
    assert math.isnan(day_end_ms("2026-13-01")) and math.isnan(day_end_ms("2026-01-00")) and math.isnan(day_end_ms("2026-01-32"))
    assert day_end_ms("0000-01-01") == -62_167_132_800_001
    cutoff = day_end_ms("2026-05-10")
    assert is_day_within_lookback("2026-05-10", cutoff) and not is_day_within_lookback("2026-05-09", cutoff)
    assert not is_day_within_lookback("2026-13-01", -1e18)


def test_daily_file_names_and_lookback() -> None:
    parsed = parse_daily_memory_file_name("2026-05-10-Notes.md")
    assert parsed is not None and parsed.day == "2026-05-10" and not parsed.canonical
    canonical = parse_daily_memory_file_name("2026-05-10.MD")
    assert canonical is not None and canonical.canonical
    assert parse_daily_memory_file_name("notes.md") is None and parse_daily_memory_file_name("2026-05-10.txt") is None
    assert daily_ingestion_lookback_days(2) == 14 and daily_ingestion_lookback_days(30) == 30
    assert normalize_memory_day(" 2026-05-10 ") == "2026-05-10" and normalize_memory_day("2026-5-10") is None


def test_checkpoint_normalization_drops_what_upstream_drops() -> None:
    state = normalize_daily_ingestion_state(
        {
            "files": {
                "memory/a.md": {"mtimeMs": 5.9, "size": "7", "lastDreamingDayIngested": "2026-05-10"},
                "memory/b.md": {"mtimeMs": -1, "size": 1},
                "memory/c.md": {"mtimeMs": "x", "size": 1},
                " ": {"mtimeMs": 1, "size": 1},
                "memory/d.md": "nope",
                "memory/e.md": {"mtimeMs": None, "size": 2, "lastDreamingDayIngested": "bad"},
            }
        }
    )
    assert state.to_json()["files"] == {
        "memory/a.md": {"mtimeMs": 5, "size": 7, "lastDreamingDayIngested": "2026-05-10"},
        "memory/e.md": {"mtimeMs": 0, "size": 2},
    }
    sessions = normalize_session_ingestion_state(
        {
            "files": {"k": {"mtimeMs": 1, "size": 2, "contentHash": " h ", "lineCount": 3, "lastContentLine": 9, "excludedReason": " forgotten "}},
            "seenMessages": {"s": ["a", "a", " b ", "", 5], "empty": [], " ": ["x"]},
        }
    )
    assert sessions.to_json() == {
        "version": 3,
        "files": {"k": {"mtimeMs": 1, "size": 2, "contentHash": "h", "lineCount": 3, "lastContentLine": 3, "excludedReason": "forgotten"}},
        "seenMessages": {"s": ["a", "b"]},
    }


def test_tracked_hashes_and_scopes_are_bounded() -> None:
    merged = merge_tracked_message_hashes([str(i) for i in range(4090)], [str(i) for i in range(4085, 4100)])
    assert len(merged) == 4096 and merged[-1] == "4099"
    seen = {f"scope-{i:05d}": ["x"] for i in range(SESSION_INGESTION_MAX_TRACKED_SCOPES + 5)}
    trimmed = trim_tracked_session_scopes(seen)
    assert len(trimmed) == SESSION_INGESTION_MAX_TRACKED_SCOPES and "scope-00000" not in trimmed


def test_admission_policy_reads_the_exclusions() -> None:
    assert resolve_admission_policy(None) is None
    assert resolve_admission_policy({"memoryPolicy": {"excludeSessions": {"channels": []}}}) is None
    policy = resolve_admission_policy(
        {"memoryPolicy": {"excludeSessions": {"channels": [" slack ", 3, ""], "chatTypes": ["group"], "hookExternalContentSources": ["gmail"]}}}
    )
    assert policy is not None
    assert (policy.channels, policy.chat_types, policy.hook_external_content_sources) == (("slack",), ("group",), ("gmail",))


def test_source_identity_depends_on_the_transcript_source(tmp_path: Path) -> None:
    file_entry = SessionCorpusEntry("main", "s1", str(tmp_path / "agents" / "main" / "sessions" / "s1.jsonl"), session_key="agent:main:s1")
    file_source = session_ingestion_source_from_corpus(file_entry)
    assert file_source is not None
    assert (file_source.scope, file_source.state_key) == ("main:s1", "main:sessions/main/s1.jsonl")
    store_source = session_ingestion_source_from_corpus(
        SessionCorpusEntry("main", "s1", file_entry.session_file, transcript_source="sqlite")
    )
    assert store_source is not None
    assert (store_source.scope, store_source.legacy_scope) == ("main:sessions/main/s1", "main:s1")
    assert session_ingestion_source_from_corpus(SessionCorpusEntry("main", "s2", "/x/s2.jsonl", session_kind="cron")) is None
    foreign = foreign_session_ingestion_source("main", str(tmp_path / "a.jsonl"))
    assert foreign.foreign and foreign.state_key.startswith("session-backfill:")
    assert session_path_for_file("/tmp/loose/s3.jsonl") == "sessions/s3.jsonl"


def test_the_corpus_append_refuses_symlinks_and_counts_lines(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    corpus = root / "memory" / ".dreams" / "session-corpus"
    target = corpus / "2026-05-10.txt"
    assert append_session_corpus_text(target, "a\nb\n", workspace_dir=root) == 0
    assert append_session_corpus_text(target, "c\n", workspace_dir=root) == 2
    target.write_bytes(b"x\r\ny")  # no trailing newline, CRLF
    assert append_session_corpus_text(target, "z\n", workspace_dir=root) == 2
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "memory" / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError, match="symlink"):
        append_session_corpus_text(root / "memory" / "linked" / "x.txt", "a\n", workspace_dir=root)
    assert list(outside.iterdir()) == []
