from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path

from demo.short_term_promotion import (
    SHORT_TERM_LOCK_RELATIVE_PATH,
    SHORT_TERM_LOCK_STALE_MS,
    SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH,
    acquire_short_term_promotion_lock,
    audit_short_term_promotion_artifacts,
)
from memory_core.config import MemoryConfig


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_lock_constants_match_openclaw_paths():
    assert SHORT_TERM_PHASE_SIGNAL_RELATIVE_PATH.as_posix() == "memory/.dreams/phase-signals.json"
    assert SHORT_TERM_LOCK_RELATIVE_PATH.as_posix() == "memory/.dreams/short-term-promotion.lock"
    assert SHORT_TERM_LOCK_STALE_MS == 60_000


def test_active_short_term_lock_blocks_second_owner(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))

    with acquire_short_term_promotion_lock(config, now) as first:
        assert first.acquired is True
        second = acquire_short_term_promotion_lock(config, now)
        with second as blocked:
            assert blocked.acquired is False
            assert blocked.reason == "locked"


def test_stale_short_term_lock_is_repaired(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    lock_path = tmp_path / SHORT_TERM_LOCK_RELATIVE_PATH
    lock_path.parent.mkdir(parents=True)
    stale_time = datetime(2026, 5, 8, 12, 0, tzinfo=UTC) - timedelta(minutes=5)
    lock_path.write_text('{"pid": 999999, "createdAt": "old"}\n', encoding="utf-8")
    old_seconds = stale_time.timestamp()
    os.utime(lock_path, times=(old_seconds, old_seconds))

    now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    with acquire_short_term_promotion_lock(config=config, now_ms=now) as lock:
        assert lock.acquired is True
        assert lock.stole_stale is True


def test_stale_owner_release_does_not_delete_new_owner_lock(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    first_now = ms(datetime(2026, 5, 8, 12, 0, tzinfo=UTC))
    second_now = first_now + SHORT_TERM_LOCK_STALE_MS + 1
    lock_path = tmp_path / SHORT_TERM_LOCK_RELATIVE_PATH

    first_manager = acquire_short_term_promotion_lock(config, first_now)
    first = first_manager.__enter__()
    first_released = False
    try:
        assert first.acquired is True
        second_manager = acquire_short_term_promotion_lock(config, second_now)
        second = second_manager.__enter__()
        try:
            assert second.acquired is True
            assert second.stole_stale is True

            first_manager.__exit__(None, None, None)
            first_released = True

            assert lock_path.exists() is True
        finally:
            second_manager.__exit__(None, None, None)
    finally:
        if not first_released:
            first_manager.__exit__(None, None, None)


def test_audit_reports_unreadable_recall_store(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    store_path = tmp_path / "memory" / ".dreams" / "short-term-recall.json"
    store_path.parent.mkdir(parents=True)
    store_path.write_bytes(b"\xff\xfe{not-json")

    audit = audit_short_term_promotion_artifacts(config, ms(datetime(2026, 5, 8, tzinfo=UTC)))

    assert audit.exists is True
    assert audit.invalid_entry_count == 0
    assert audit.issues[0].code == "recall-store-unreadable"


def test_audit_counts_readable_recall_store_entries(tmp_path: Path):
    config = MemoryConfig(workspace_dir=tmp_path)
    store_path = tmp_path / "memory" / ".dreams" / "short-term-recall.json"
    store_path.parent.mkdir(parents=True)
    store_path.write_text(
        json.dumps(
            {
                "entries": {
                    "promoted": {
                        "key": "promoted",
                        "path": "memory/topic.md",
                        "snippet": "Promoted claim",
                        "promotedAt": "2026-05-08T12:00:00Z",
                        "recallDays": ["2026-05-07"],
                        "conceptTags": ["topic"],
                    },
                    "spaced": {
                        "key": "spaced",
                        "path": "memory/topic.md",
                        "snippet": "Spaced claim",
                        "recallDays": ["2026-05-07", "2026-05-08"],
                        "conceptTags": [],
                    },
                    "invalid": {
                        "key": "invalid",
                        "path": "memory/topic.md",
                        "recallDays": [],
                    },
                    "not-dict": "invalid",
                }
            }
        ),
        encoding="utf-8",
    )

    audit = audit_short_term_promotion_artifacts(config, ms(datetime(2026, 5, 8, tzinfo=UTC)))

    assert audit.exists is True
    assert audit.entry_count == 3
    assert audit.promoted_entry_count == 1
    assert audit.spaced_entry_count == 1
    assert audit.concept_tagged_entry_count == 1
    assert audit.invalid_entry_count == 2
    assert audit.issues == ()
