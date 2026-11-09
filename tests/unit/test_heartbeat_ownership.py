"""Durable heartbeat owner transitions through the real file-store public API.

These regressions exercise deletion/re-enrollment, in-flight writers, legacy
adoption and refusal of invalid persisted ownership. They run no scheduler,
native oracle, provider or model.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from memory_core.automation import AutomationJob, FileAutomationStore
from memory_core.heartbeat_scratch import (
    HeartbeatScratchTooLargeError,
    resolve_heartbeat_store_scratch,
)


NOW = 2_000_000_000_000
MAX_COUNTER = 2**53 - 1
MAX_CLOCK = 8_640_000_000_000_000


def _owned(root):
    return FileAutomationStore(root, require_monitor_owner=True)


def _enrolled(root):
    store = _owned(root)
    return store, store.enroll_heartbeat_monitor("main", "owner-main")


def _job(identifier, text="Check the queue"):
    return AutomationJob(
        id=identifier, name=identifier, agent_id="main", every_ms=60_000,
        text=text, created_at_ms=NOW, updated_at_ms=NOW,
    )


def _replace_catalog(store, change):
    """Put an explicit malformed or boundary state on real persisted storage."""
    data = json.loads(store.path.read_bytes())
    change(data["heartbeatOwnership"])
    store.path.write_text(json.dumps(data), encoding="utf-8")
    return store.path.read_bytes()


@pytest.mark.parametrize("required", [False, True])
def test_construction_and_monitor_reads_do_not_enroll_or_create_files(tmp_path, required):
    store = FileAutomationStore(tmp_path, require_monitor_owner=required)

    assert store.heartbeat_ownership_enabled is required
    assert store.read_heartbeat_monitor_scratch("main") is None
    assert store.read_scratch("main").to_json() == {"currentRevision": 0}
    assert store.read_job_scratch("main", "owner-main").to_json() == {"currentRevision": 0}
    assert resolve_heartbeat_store_scratch(store, "main")[0].to_json() == {"currentRevision": 0}
    assert store.list_jobs() == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content", [None, "late write"])
def test_required_owner_is_not_created_by_a_write(tmp_path, content):
    store = _owned(tmp_path)

    write = store.write_job_scratch("main", "owner-main", content, expected_revision=0, now_ms=NOW)

    assert write.to_json() == {"ok": False, "reason": "revision-conflict", "currentRevision": 0}
    assert store.read_heartbeat_monitor_scratch("main") is None
    assert not store.path.exists()


def test_oversize_content_is_refused_before_absent_owner_or_revision_checks(tmp_path):
    store = _owned(tmp_path)

    with pytest.raises(HeartbeatScratchTooLargeError, match="262145 bytes provided"):
        store.write_job_scratch("main", "owner-main", "a" * 262145,
                                expected_revision=9, now_ms=NOW)

    assert not store.path.exists()


@pytest.mark.parametrize("retained", ["retained private instructions", None], ids=["content", "tombstone"])
def test_removed_owner_and_orphan_revision_survive_default_reopen(tmp_path, retained):
    store, owner = _enrolled(tmp_path)
    store.write_job_scratch("main", owner.job_id, "initial", now_ms=NOW)
    store.write_job_scratch("main", owner.job_id, retained, now_ms=NOW + 1)
    before = store.read_job_scratch("main", owner.job_id)

    remover = FileAutomationStore(tmp_path)
    assert remover.remove_heartbeat_monitor("main", job_id=owner.job_id,
                                            expected_generation=owner.generation)
    persisted = store.path.read_bytes()
    reopened = FileAutomationStore(tmp_path)

    assert reopened.heartbeat_ownership_enabled is True
    assert reopened.read_heartbeat_monitor_scratch("main") is None
    assert reopened.read_job_scratch("main", owner.job_id) == before
    assert before.current_revision == 2 and before.content == retained
    visible, active = resolve_heartbeat_store_scratch(reopened, "main")
    assert visible.to_json() == {"currentRevision": 0}
    assert active is None
    for writer in (store, reopened):
        late = writer.write_job_scratch("main", owner.job_id, "late overwrite",
            expected_revision=2, expected_owner_generation=owner.generation, now_ms=NOW + 2)
        assert late.to_json() == {"ok": False, "reason": "revision-conflict", "currentRevision": 2}
    assert reopened.write_scratch("main", "legacy late write", now_ms=NOW + 2).ok is False
    assert store.path.read_bytes() == persisted


def test_removal_guard_does_not_retire_a_changed_generation_or_other_job(tmp_path):
    store, owner = _enrolled(tmp_path)
    persisted = store.path.read_bytes()

    assert store.remove_heartbeat_monitor("main", expected_generation=owner.generation + 1) is False
    assert store.remove_heartbeat_monitor("main", job_id="another-owner") is False
    assert store.path.read_bytes() == persisted
    assert FileAutomationStore(tmp_path).read_heartbeat_monitor_scratch("main").owner == owner


def test_same_job_reenrollment_rejects_a_stale_generation_even_at_revision_zero(tmp_path):
    store, first = _enrolled(tmp_path)
    store.write_job_scratch("main", first.job_id, "before removal", now_ms=NOW)
    assert store.remove_heartbeat_monitor("main", cleanup_scratch=True)
    second = FileAutomationStore(tmp_path).enroll_heartbeat_monitor("main", first.job_id)
    reopened = FileAutomationStore(tmp_path)
    assert second.generation == first.generation + 1
    assert reopened.read_job_scratch("main", second.job_id).current_revision == 0
    persisted = store.path.read_bytes()

    stale = store.write_job_scratch("main", first.job_id, "stale snapshot", expected_revision=0,
                                   expected_owner_generation=first.generation, now_ms=NOW + 1)

    assert stale.to_json() == {"ok": False, "reason": "revision-conflict", "currentRevision": 0}
    assert store.path.read_bytes() == persisted
    current = reopened.write_job_scratch("main", second.job_id, "current owner", expected_revision=0,
                                        expected_owner_generation=second.generation, now_ms=NOW + 2)
    assert current.ok and current.current_revision == 1
    assert FileAutomationStore(tmp_path).read_heartbeat_monitor_scratch("main").state.content == "current owner"


def test_owner_replacement_keeps_old_job_private_state_without_exposing_it_as_current(tmp_path):
    store, first = _enrolled(tmp_path)
    store.write_job_scratch("main", first.job_id, "old private scratch", now_ms=NOW)

    second = store.enroll_heartbeat_monitor("main", "replacement-owner")
    reopened = FileAutomationStore(tmp_path)

    assert second.generation == first.generation + 1
    monitor = reopened.read_heartbeat_monitor_scratch("main")
    assert monitor.owner == second and monitor.state.current_revision == 0
    assert reopened.read_job_scratch("main", first.job_id).content == "old private scratch"
    assert reopened.write_job_scratch("main", first.job_id, "late", now_ms=NOW + 1).ok is False
    persisted = store.path.read_bytes()
    assert reopened.enroll_heartbeat_monitor("main", second.job_id) == second
    assert store.path.read_bytes() == persisted


def test_job_identity_cannot_be_claimed_read_written_or_deleted_by_another_agent(tmp_path):
    store, owner = _enrolled(tmp_path)
    store.write_job_scratch("main", owner.job_id, "main private scratch", now_ms=NOW)
    persisted = store.path.read_bytes()

    operations = [
        lambda: store.enroll_heartbeat_monitor("ops", owner.job_id),
        lambda: store.read_job_scratch("ops", owner.job_id),
        lambda: store.write_job_scratch("ops", owner.job_id, "overwrite", now_ms=NOW),
        lambda: store.delete_job_scratch("ops", owner.job_id),
    ]
    for operation in operations:
        with pytest.raises(ValueError, match="different agent"):
            operation()
        assert store.path.read_bytes() == persisted
    assert FileAutomationStore(tmp_path).read_job_scratch("main", owner.job_id).content == "main private scratch"


def test_independent_store_roots_keep_identical_monitor_ids_isolated(tmp_path):
    left, left_owner = _enrolled(tmp_path / "left")
    right, right_owner = _enrolled(tmp_path / "right")
    assert left_owner == right_owner
    left.write_job_scratch("main", left_owner.job_id, "left", now_ms=NOW)
    right.write_job_scratch("main", right_owner.job_id, "right", now_ms=NOW)
    left.remove_heartbeat_monitor("main", cleanup_scratch=True)

    assert FileAutomationStore(tmp_path / "left").read_heartbeat_monitor_scratch("main") is None
    assert FileAutomationStore(tmp_path / "right").read_heartbeat_monitor_scratch("main").state.content == "right"


def test_legacy_default_has_no_implicit_monitor_and_keeps_agent_keyed_behavior(tmp_path):
    store = FileAutomationStore(tmp_path)
    store.write_scratch("main", "legacy", now_ms=NOW)
    expected = store.read_scratch("main")
    persisted = store.path.read_bytes()
    reopened = FileAutomationStore(tmp_path)

    assert reopened.heartbeat_ownership_enabled is False
    assert reopened.read_heartbeat_monitor_scratch("main") is None
    assert resolve_heartbeat_store_scratch(reopened, "main") == (expected, None)
    assert store.path.read_bytes() == persisted
    assert "heartbeatOwnership" not in json.loads(persisted)
    assert reopened.write_scratch("main", "legacy edit", expected_revision=1, now_ms=NOW + 1).ok


@pytest.mark.parametrize("content", ["legacy private instructions", None], ids=["content", "tombstone"])
def test_explicit_legacy_adoption_preserves_revision_and_tombstone(tmp_path, content):
    legacy = FileAutomationStore(tmp_path)
    legacy.write_scratch("main", "first", now_ms=NOW)
    legacy.write_scratch("main", content, now_ms=NOW + 1, source_sha256="  source  ")
    original = legacy.read_scratch("main")
    strict = _owned(tmp_path)
    assert strict.read_heartbeat_monitor_scratch("main") is None

    owner = strict.enroll_heartbeat_monitor("main", "adopted-owner", adopt_legacy_scratch=True)

    reopened = FileAutomationStore(tmp_path)
    assert reopened.read_heartbeat_monitor_scratch("main").state == original
    assert reopened.read_job_scratch("main", owner.job_id) == original
    assert original.current_revision == 2
    assert "main" not in json.loads(strict.path.read_bytes())["scratch"]
    assert reopened.heartbeat_ownership_enabled is True


def test_legacy_rows_are_not_adopted_implicitly_or_on_later_reenrollment(tmp_path):
    legacy = FileAutomationStore(tmp_path)
    legacy.write_scratch("main", "old legacy text", now_ms=NOW)
    first = legacy.enroll_heartbeat_monitor("main", "first-owner")
    assert legacy.read_job_scratch("main", first.job_id).current_revision == 0
    assert legacy.remove_heartbeat_monitor("main")

    second = FileAutomationStore(tmp_path).enroll_heartbeat_monitor(
        "main", "second-owner", adopt_legacy_scratch=True)

    assert FileAutomationStore(tmp_path).read_job_scratch("main", second.job_id).current_revision == 0
    assert json.loads(legacy.path.read_bytes())["scratch"]["main"]["content"] == "old legacy text"


@pytest.mark.parametrize("clock", [-1, True, 1.5, MAX_CLOCK + 1])
def test_invalid_write_clock_leaves_owner_scratch_and_jobs_bytes_unchanged(tmp_path, clock):
    store, owner = _enrolled(tmp_path)
    store.write_job_scratch("main", owner.job_id, "original", now_ms=NOW)
    persisted = store.path.read_bytes()

    with pytest.raises(ValueError):
        FileAutomationStore(tmp_path).write_job_scratch("main", owner.job_id, "replacement", now_ms=clock)
    assert store.path.read_bytes() == persisted
    with pytest.raises(ValueError):
        store.save_jobs([_job("new-task")], scratch_agent_id="main", scratch_job_id=owner.job_id,
                        scratch_content="replacement", scratch_expected_revision=1, now_ms=clock)
    assert store.path.read_bytes() == persisted


@pytest.mark.parametrize("revision", [-1, True, 1.5, MAX_COUNTER + 1])
def test_invalid_cas_counter_is_rejected_without_mutating_durable_state(tmp_path, revision):
    store, owner = _enrolled(tmp_path)
    store.write_job_scratch("main", owner.job_id, "original", now_ms=NOW)
    persisted = store.path.read_bytes()

    with pytest.raises(ValueError):
        store.write_job_scratch("main", owner.job_id, "replacement", expected_revision=revision, now_ms=NOW)
    assert store.path.read_bytes() == persisted


@pytest.mark.parametrize("content", ["at maximum revision", None], ids=["content", "tombstone"])
def test_safe_revision_limit_cannot_wrap_or_increment_on_disk(tmp_path, content):
    store, owner = _enrolled(tmp_path)
    store.write_job_scratch("main", owner.job_id, content, now_ms=NOW)
    if content is None:
        store.write_job_scratch("main", owner.job_id, "seed", now_ms=NOW)
        store.write_job_scratch("main", owner.job_id, None, now_ms=NOW)
    persisted = _replace_catalog(store, lambda catalog: catalog["scratch"][owner.job_id].update(revision=MAX_COUNTER))
    assert FileAutomationStore(tmp_path).read_job_scratch("main", owner.job_id).current_revision == MAX_COUNTER

    with pytest.raises(ValueError, match="safe integer"):
        store.write_job_scratch("main", owner.job_id, "overflow", expected_revision=MAX_COUNTER, now_ms=NOW)
    assert store.path.read_bytes() == persisted


def test_safe_generation_limit_is_retained_and_cannot_wrap_after_removal(tmp_path):
    store, owner = _enrolled(tmp_path)
    store.remove_heartbeat_monitor("main")

    def at_limit(catalog):
        catalog["agents"]["main"]["generation"] = MAX_COUNTER
        catalog["owners"][owner.job_id]["generation"] = MAX_COUNTER

    persisted = _replace_catalog(store, at_limit)
    assert FileAutomationStore(tmp_path).read_heartbeat_monitor_scratch("main") is None

    with pytest.raises(ValueError):
        store.enroll_heartbeat_monitor("main", "next-owner")
    assert store.path.read_bytes() == persisted


@pytest.mark.parametrize("change", [
    lambda catalog: catalog.update(version=True),
    lambda catalog: catalog.update(owners=[]),
    lambda catalog: catalog["agents"]["main"].update(generation=0),
    lambda catalog: catalog["agents"]["main"].update(generation=MAX_COUNTER + 1),
    lambda catalog: catalog["owners"]["owner-main"].update(active=1),
    lambda catalog: catalog["owners"]["owner-main"].update(agentId="ops"),
    lambda catalog: catalog["scratch"]["owner-main"].update(revision=True),
    lambda catalog: catalog["scratch"]["owner-main"].update(revision=MAX_COUNTER + 1),
    lambda catalog: catalog["scratch"]["owner-main"].update(updatedAtMs=MAX_CLOCK + 1),
    lambda catalog: catalog["scratch"].update(orphan={"revision": 1, "content": "private", "updatedAtMs": NOW}),
], ids=["catalog-version", "owners-shape", "zero-generation", "unsafe-generation", "owner-active-type",
        "owner-agent-binding", "boolean-revision", "unsafe-revision", "unsafe-clock", "unknown-job-scratch"])
def test_malformed_persisted_catalog_is_not_reset_reenrolled_or_overwritten(tmp_path, change):
    store, owner = _enrolled(tmp_path)
    store.write_job_scratch("main", owner.job_id, "private", now_ms=NOW)
    persisted = _replace_catalog(store, change)
    reopened = FileAutomationStore(tmp_path)

    operations = [
        lambda: reopened.read_heartbeat_monitor_scratch("main"),
        lambda: reopened.enroll_heartbeat_monitor("main", "replacement-owner"),
        lambda: reopened.write_scratch("main", "overwrite", now_ms=NOW),
        lambda: reopened.save_jobs([_job("new-task")]),
    ]
    for operation in operations:
        with pytest.raises(ValueError):
            operation()
        assert store.path.read_bytes() == persisted


@pytest.mark.parametrize("change", ["removed-owner", "replaced-owner", "changed-scratch"])
def test_save_jobs_from_held_owner_snapshot_conflicts_without_job_side_effects(tmp_path, change):
    store, owner = _enrolled(tmp_path)
    store.write_job_scratch("main", owner.job_id, "initial", now_ms=NOW)
    existing = _job("existing-task")
    store.save_jobs([existing])
    competing = FileAutomationStore(tmp_path)
    if change == "removed-owner":
        competing.remove_heartbeat_monitor("main")
    elif change == "replaced-owner":
        competing.enroll_heartbeat_monitor("main", "replacement-owner")
    else:
        competing.write_job_scratch("main", owner.job_id, "concurrent scratch", now_ms=NOW + 1)
    persisted = store.path.read_bytes()

    conflict = store.save_jobs([_job("new-task")], remove=[existing.id],
        scratch_agent_id="main", scratch_job_id=owner.job_id, scratch_owner_generation=owner.generation,
        scratch_expected_revision=1, scratch_content="held writer", now_ms=NOW + 2)

    assert conflict is not None and conflict.ok is False and conflict.reason == "revision-conflict"
    assert store.path.read_bytes() == persisted
    assert FileAutomationStore(tmp_path).list_jobs() == [existing]


def test_save_jobs_owner_removal_is_atomic_with_cleanup_and_blocks_same_batch_write(tmp_path):
    store, owner = _enrolled(tmp_path)
    store.write_job_scratch("main", owner.job_id, "initial", now_ms=NOW)
    persisted = store.path.read_bytes()

    conflict = store.save_jobs([_job("new-task")], remove=[owner.job_id],
        scratch_agent_id="main", scratch_job_id=owner.job_id, scratch_owner_generation=owner.generation,
        scratch_expected_revision=1, scratch_content="write during deletion", now_ms=NOW + 1)

    assert conflict is not None and conflict.ok is False
    assert store.path.read_bytes() == persisted
    assert store.read_heartbeat_monitor_scratch("main") is not None
    assert store.list_jobs() == []
    store.save_jobs([], remove=[owner.job_id])
    reopened = FileAutomationStore(tmp_path)
    assert reopened.read_heartbeat_monitor_scratch("main") is None
    assert reopened.read_job_scratch("main", owner.job_id).current_revision == 0
    assert reopened.write_job_scratch("main", owner.job_id, "late", now_ms=NOW + 2).ok is False


def test_a_real_other_process_cannot_write_after_owner_removal(tmp_path):
    store, owner = _enrolled(tmp_path)
    store.write_job_scratch("main", owner.job_id, "initial", now_ms=NOW)
    script = """
import json,sys
from memory_core.automation import FileAutomationStore
store=FileAutomationStore(sys.argv[1])
monitor=store.read_heartbeat_monitor_scratch('main')
print(json.dumps({'jobId':monitor.owner.job_id,'generation':monitor.owner.generation,'revision':monitor.state.current_revision}),flush=True)
sys.stdin.readline()
result=store.write_job_scratch('main',monitor.owner.job_id,'late from held process',expected_revision=monitor.state.current_revision,expected_owner_generation=monitor.owner.generation,now_ms=2000000000001)
print(json.dumps(result.to_json()),flush=True)
"""
    process = subprocess.Popen([sys.executable, "-c", script, str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={"PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PATH": os.defpath, "LANG": "C.UTF-8"})
    try:
        captured = json.loads(process.stdout.readline())
        assert captured == {"jobId": owner.job_id, "generation": owner.generation, "revision": 1}
        assert FileAutomationStore(tmp_path).remove_heartbeat_monitor("main", expected_generation=owner.generation)
        persisted = store.path.read_bytes()
        stdout, stderr = process.communicate("continue\n", timeout=10)
        assert process.returncode == 0, stderr
        assert json.loads(stdout) == {"ok": False, "reason": "revision-conflict", "currentRevision": 1}
        assert store.path.read_bytes() == persisted
        assert FileAutomationStore(tmp_path).read_job_scratch("main", owner.job_id).content == "initial"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


@pytest.mark.parametrize("version", ["missing", None, False, "1", 0, 2])
def test_owned_original_top_level_version_is_refused_before_legacy_defaults(tmp_path, version):
    store, owner = _enrolled(tmp_path)
    store.write_job_scratch("main", owner.job_id, "preserve private content", now_ms=NOW)
    data = json.loads(store.path.read_text())
    if version == "missing":
        del data["version"]
    else:
        data["version"] = version
    store.path.write_text(json.dumps(data))
    before = store.path.read_bytes()

    for reopened in (store, FileAutomationStore(tmp_path), _owned(tmp_path)):
        for operation in (
            lambda: reopened.read_heartbeat_monitor_scratch("main"),
            lambda: reopened.read_job_scratch("main", owner.job_id),
            lambda: reopened.write_job_scratch("main", owner.job_id, "must not publish", now_ms=NOW + 1),
            lambda: reopened.write_scratch("main", "must not repair", now_ms=NOW + 1),
            lambda: reopened.save_jobs([]),
        ):
            with pytest.raises(ValueError, match="version"):
                operation()
            assert store.path.read_bytes() == before


def test_unowned_legacy_store_retains_missing_version_default_compatibility(tmp_path):
    store = FileAutomationStore(tmp_path)
    store.write_scratch("main", "legacy content", now_ms=NOW)
    data = json.loads(store.path.read_text())
    del data["version"]
    store.path.write_text(json.dumps(data))

    reopened = FileAutomationStore(tmp_path)
    assert reopened.read_scratch("main").content == "legacy content"
    assert reopened.write_scratch("main", "legacy update", now_ms=NOW + 1).ok
    assert json.loads(store.path.read_text())["version"] == 1
