"""Offline tests for memory_core.heartbeat_scratch and the scratch side of FileAutomationStore.

Expected values come from src/cron/scratch-store.test.ts and src/cron/scratch-contract.ts at
v2026.9.6; tests/integration/test_openclaw_ts_oracle.py (heartbeatScratchContract) runs the
same sequence against the real TypeScript store.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from memory_core.automation import FileAutomationStore
from memory_core.heartbeat_scratch import (
    CRON_JOB_SCRATCH_MAX_BYTES,
    HeartbeatScratchState,
    HeartbeatScratchTooLargeError,
    apply_heartbeat_scratch_delete,
    apply_heartbeat_scratch_write,
    assert_heartbeat_scratch_content,
    hash_heartbeat_scratch_source,
)


def test_scratch_cap_is_256_kib_of_utf8():
    assert CRON_JOB_SCRATCH_MAX_BYTES == 256 * 1024
    assert_heartbeat_scratch_content("a" * CRON_JOB_SCRATCH_MAX_BYTES)
    assert_heartbeat_scratch_content("é" * (CRON_JOB_SCRATCH_MAX_BYTES // 2))
    with pytest.raises(HeartbeatScratchTooLargeError) as error:
        assert_heartbeat_scratch_content("é" * (CRON_JOB_SCRATCH_MAX_BYTES // 2) + "a")
    assert str(error.value) == "cron scratch exceeds 262144 bytes (262145 bytes provided)"


def test_store_distinguishes_no_row_from_present_empty_content(tmp_path):
    store = FileAutomationStore(tmp_path)
    assert store.read_scratch("main").to_json() == {"currentRevision": 0}

    write = store.write_scratch("main", "", now_ms=10)

    assert write.to_json() == {
        "ok": True,
        "currentRevision": 1,
        "scratch": {"content": "", "revision": 1, "updatedAtMs": 10},
    }
    assert store.read_scratch("main").to_json() == {
        "currentRevision": 1,
        "scratch": {"content": "", "revision": 1, "updatedAtMs": 10},
    }


def test_store_compare_and_swaps_and_keeps_a_tombstone_across_unset(tmp_path):
    store = FileAutomationStore(tmp_path)
    store.write_scratch("main", "first", now_ms=10)

    assert store.write_scratch("main", "stale", expected_revision=0, now_ms=20).to_json() == {
        "ok": False,
        "reason": "revision-conflict",
        "currentRevision": 1,
    }
    assert store.write_scratch("main", "second", expected_revision=1, now_ms=30).to_json() == {
        "ok": True,
        "currentRevision": 2,
        "scratch": {"content": "second", "revision": 2, "updatedAtMs": 30},
    }
    assert store.write_scratch("main", None, expected_revision=2, now_ms=40).to_json() == {
        "ok": True,
        "currentRevision": 3,
    }
    assert store.read_scratch("main").to_json() == {"currentRevision": 3}
    assert store.write_scratch("main", "resurrected", expected_revision=2).ok is False
    assert store.write_scratch("main", "recreated", expected_revision=3, now_ms=60).to_json() == {
        "ok": True,
        "currentRevision": 4,
        "scratch": {"content": "recreated", "revision": 4, "updatedAtMs": 60},
    }
    assert store.delete_scratch("main", expected_revision=3) is False
    assert store.read_scratch("main").current_revision == 4
    assert store.delete_scratch("main", expected_revision=4) is True
    assert store.read_scratch("main").to_json() == {"currentRevision": 0}
    assert store.delete_scratch("main", expected_revision=0) is True


def test_unset_of_an_absent_row_is_a_no_op(tmp_path):
    store = FileAutomationStore(tmp_path)
    assert store.write_scratch("main", None).to_json() == {"ok": True, "currentRevision": 0}
    assert not store.path.exists()


def test_source_hash_is_trimmed_kept_only_with_content_and_cleared_by_a_plain_write():
    state, write = apply_heartbeat_scratch_write(
        HeartbeatScratchState(), "x", now_ms=1, source_sha256="  abc  "
    )
    assert write.scratch is not None and write.scratch.source_sha256 == "abc"
    state, write = apply_heartbeat_scratch_write(state, "y", now_ms=2)
    assert write.scratch is not None and write.scratch.source_sha256 is None
    state, write = apply_heartbeat_scratch_write(state, "z", now_ms=3, source_sha256="   ")
    assert "sourceSha256" not in write.to_json()["scratch"]
    state, write = apply_heartbeat_scratch_write(state, None, now_ms=4, source_sha256="abc")
    assert write.to_json() == {"ok": True, "currentRevision": 4}
    assert apply_heartbeat_scratch_delete(state, expected_revision=3) == (state, False)


def test_oversized_writes_raise_before_the_revision_check(tmp_path):
    store = FileAutomationStore(tmp_path)
    with pytest.raises(HeartbeatScratchTooLargeError):
        store.write_scratch("main", "a" * (CRON_JOB_SCRATCH_MAX_BYTES + 1), expected_revision=9)
    assert store.read_scratch("main").current_revision == 0


def test_scratch_is_kept_per_agent_in_a_private_file(tmp_path):
    store = FileAutomationStore(tmp_path)
    store.write_scratch("main", "- Check status\n", now_ms=5)
    store.write_scratch("ops", "- Check queue\n", now_ms=6)
    assert store.read_scratch("ops").content == "- Check queue\n"
    assert store.path == tmp_path / ".memory-core" / "automation.json"
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(data["scratch"]) == {"main", "ops"}


def test_hash_matches_upstream_sha256_hex():
    assert hash_heartbeat_scratch_source("") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
