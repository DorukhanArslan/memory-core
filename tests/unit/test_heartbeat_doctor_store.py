"""Actual store operations needed by doctor planning, adoption and rollback.

These tests use durable SDK files and fresh store instances. They do not run
native captures, migration adapters, providers or a scheduler.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from memory_core.automation import AUTOMATION_STORE_PARTS, FileAutomationStore
from memory_core.heartbeat_scratch import HeartbeatMonitorEnrollmentConflictError


NOW = 2_000_000_000_000


def _owned(root, **options):
    return FileAutomationStore(root, require_monitor_owner=True, **options)


def test_constructor_and_reads_do_not_prepare_a_monitor_even_for_custom_filename(tmp_path):
    store = _owned(tmp_path, store_path="custom/automation.json")

    assert store.path == tmp_path / "custom/automation.json"
    assert store.read_heartbeat_monitor_scratch("main") is None
    assert store.read_job_scratch("main", "heartbeat:main").current_revision == 0
    assert list(tmp_path.iterdir()) == []


def test_ensure_preserves_exact_existing_custom_owner_and_generation_after_reopen(tmp_path):
    store = _owned(tmp_path)
    first = store.enroll_heartbeat_monitor("main", "first-custom-owner")
    store.write_job_scratch("main", first.job_id, "retained original", now_ms=NOW)
    current = store.enroll_heartbeat_monitor("main", "operator-selected-owner")
    store.write_job_scratch("main", current.job_id, "operator scratch", now_ms=NOW + 1)
    persisted = store.path.read_bytes()

    ensured = FileAutomationStore(tmp_path).ensure_heartbeat_monitor("main", adopt_legacy_scratch=True)

    assert ensured == current
    assert ensured.generation == first.generation + 1
    assert ensured.job_id == "operator-selected-owner"
    assert store.path.read_bytes() == persisted
    reopened = FileAutomationStore(tmp_path)
    assert reopened.read_heartbeat_monitor_scratch("main").owner == current
    assert reopened.read_job_scratch("main", current.job_id).content == "operator scratch"
    assert reopened.read_job_scratch("main", first.job_id).content == "retained original"


def test_ensure_can_genuinely_prepare_a_missing_monitor_and_is_idempotent(tmp_path):
    store = _owned(tmp_path)

    owner = store.ensure_heartbeat_monitor("main")

    assert owner.agent_id == "main" and owner.job_id == "heartbeat:main" and owner.generation == 1
    persisted = store.path.read_bytes()
    assert FileAutomationStore(tmp_path).ensure_heartbeat_monitor("main") == owner
    assert store.path.read_bytes() == persisted
    assert FileAutomationStore(tmp_path).read_heartbeat_monitor_scratch("main").state.current_revision == 0


def test_explicit_ensure_after_retirement_uses_a_new_generation_without_stealing_active_owner(tmp_path):
    store = _owned(tmp_path)
    first = store.enroll_heartbeat_monitor("main", "custom-retired-owner")
    store.write_job_scratch("main", first.job_id, "orphan retained", now_ms=NOW)
    assert store.remove_heartbeat_monitor("main")

    revived = FileAutomationStore(tmp_path).ensure_heartbeat_monitor("main")

    assert revived.job_id == "heartbeat:main" and revived.generation == first.generation + 1
    assert store.read_job_scratch("main", first.job_id).content == "orphan retained"
    replacement = FileAutomationStore(tmp_path).enroll_heartbeat_monitor("main", "new-custom-owner")
    persisted = store.path.read_bytes()
    assert store.ensure_heartbeat_monitor("main") == replacement
    assert store.path.read_bytes() == persisted


@pytest.mark.parametrize("content", ["operator-authored checklist", None], ids=["content", "explicit-unset"])
def test_first_ensure_adoption_preserves_operator_revision_and_provenance(tmp_path, content):
    legacy = FileAutomationStore(tmp_path)
    legacy.write_scratch("main", "initial", now_ms=NOW)
    legacy.write_scratch("main", content, source_sha256="  legacy-source  ", now_ms=NOW + 1)
    expected = legacy.read_scratch("main")

    owner = _owned(tmp_path).ensure_heartbeat_monitor("main", adopt_legacy_scratch=True)

    reopened = FileAutomationStore(tmp_path)
    assert reopened.read_job_scratch("main", owner.job_id) == expected
    assert reopened.read_heartbeat_monitor_scratch("main").state == expected
    assert expected.current_revision == 2
    assert "main" not in json.loads(legacy.path.read_bytes())["scratch"]


def test_ensure_never_adopts_leftover_legacy_text_into_an_existing_active_custom_owner(tmp_path):
    legacy = FileAutomationStore(tmp_path)
    legacy.write_scratch("main", "leftover legacy text", now_ms=NOW)
    active = legacy.enroll_heartbeat_monitor("main", "custom-owner", adopt_legacy_scratch=False)
    legacy.write_job_scratch("main", active.job_id, "current operator scratch", now_ms=NOW + 1)
    persisted = legacy.path.read_bytes()

    assert FileAutomationStore(tmp_path).ensure_heartbeat_monitor("main", adopt_legacy_scratch=True) == active

    assert legacy.path.read_bytes() == persisted
    assert legacy.read_job_scratch("main", active.job_id).content == "current operator scratch"
    assert json.loads(persisted)["scratch"]["main"]["content"] == "leftover legacy text"


def test_enrollment_require_unconfigured_abi_still_refuses_a_catalog_created_by_ensure(tmp_path):
    store = _owned(tmp_path)
    store.ensure_heartbeat_monitor("main")
    persisted = store.path.read_bytes()

    with pytest.raises(HeartbeatMonitorEnrollmentConflictError):
        store.enroll_heartbeat_monitor("main", "replacement", require_unconfigured=True)

    assert store.path.read_bytes() == persisted


def test_default_filename_and_legacy_behavior_remain_unchanged(tmp_path):
    store = FileAutomationStore(tmp_path)
    assert store.root == tmp_path
    assert store.path == tmp_path.joinpath(*AUTOMATION_STORE_PARTS)
    store.write_scratch("main", "default legacy scratch", now_ms=NOW)
    persisted = store.path.read_bytes()

    reopened = FileAutomationStore(tmp_path, store_path=None)

    assert reopened.root == store.root and reopened.path == store.path
    assert reopened.read_scratch("main").content == "default legacy scratch"
    assert reopened.heartbeat_ownership_enabled is False
    assert reopened.path.read_bytes() == persisted


def test_custom_relative_and_absolute_filenames_reopen_the_selected_partitions_only(tmp_path):
    default = FileAutomationStore(tmp_path)
    default.write_scratch("main", "default private scratch", now_ms=NOW)
    default_bytes = default.path.read_bytes()
    relative = _owned(tmp_path, store_path="cron/custom.json")
    absolute_path = tmp_path / "separate/absolute.json"
    absolute = _owned(tmp_path / "other-workspace", store_path=absolute_path)
    left = relative.ensure_heartbeat_monitor("main")
    right = absolute.ensure_heartbeat_monitor("main")
    relative.write_job_scratch("main", left.job_id, "relative partition", now_ms=NOW)
    absolute.write_job_scratch("main", right.job_id, "absolute partition", now_ms=NOW)

    reopened_relative = FileAutomationStore(tmp_path, store_path=Path("cron/custom.json"))
    reopened_absolute = FileAutomationStore(tmp_path / "yet-another-root", store_path=absolute_path)

    assert reopened_relative.root == tmp_path
    assert reopened_relative.path == tmp_path / "cron/custom.json"
    assert reopened_absolute.root == tmp_path / "yet-another-root"
    assert reopened_absolute.path == absolute_path
    assert reopened_relative.read_heartbeat_monitor_scratch("main").state.content == "relative partition"
    assert reopened_absolute.read_heartbeat_monitor_scratch("main").state.content == "absolute partition"
    assert default.path.read_bytes() == default_bytes
    relative.remove_heartbeat_monitor("main", cleanup_scratch=True)
    assert reopened_absolute.read_heartbeat_monitor_scratch("main").state.content == "absolute partition"
    assert not (tmp_path / "other-workspace").exists()
    assert not (tmp_path / "yet-another-root").exists()


@pytest.mark.parametrize("transition", ["retired", "replaced", "same-id-aba"])
def test_delete_from_held_owner_snapshot_cannot_remove_retired_or_replacement_scratch(tmp_path, transition):
    store = _owned(tmp_path)
    old = store.enroll_heartbeat_monitor("main", "captured-owner")
    store.write_job_scratch("main", old.job_id, "original", now_ms=NOW)
    concurrent = FileAutomationStore(tmp_path)
    if transition == "retired":
        concurrent.remove_heartbeat_monitor("main")
    elif transition == "replaced":
        concurrent.enroll_heartbeat_monitor("main", "replacement-owner")
    else:
        concurrent.remove_heartbeat_monitor("main", cleanup_scratch=True)
        current = concurrent.enroll_heartbeat_monitor("main", old.job_id)
        concurrent.write_job_scratch("main", current.job_id, "replacement at same revision", now_ms=NOW + 1)
        assert current.generation == old.generation + 1
    persisted = store.path.read_bytes()

    deleted = store.delete_job_scratch("main", old.job_id, expected_revision=1,
                                       expected_owner_generation=old.generation)

    assert deleted is False
    assert store.path.read_bytes() == persisted
    expected = "replacement at same revision" if transition == "same-id-aba" else "original"
    assert FileAutomationStore(tmp_path).read_job_scratch("main", old.job_id).content == expected


def test_guarded_delete_requires_an_active_matching_owner_even_when_scratch_is_absent(tmp_path):
    store = _owned(tmp_path)

    assert store.delete_job_scratch("main", "missing-owner", expected_revision=0,
                                    expected_owner_generation=1) is False
    assert not store.path.exists()
    owner = store.ensure_heartbeat_monitor("main")
    persisted = store.path.read_bytes()
    assert store.delete_job_scratch("main", "different-job", expected_revision=0,
                                    expected_owner_generation=owner.generation) is False
    assert store.path.read_bytes() == persisted
    assert store.delete_job_scratch("main", owner.job_id, expected_revision=0,
                                    expected_owner_generation=owner.generation) is True
    assert store.path.read_bytes() == persisted


def test_matching_owner_generation_and_revision_delete_only_its_scratch(tmp_path):
    store = _owned(tmp_path)
    owner = store.enroll_heartbeat_monitor("main", "custom-owner")
    store.write_job_scratch("main", owner.job_id, "private", now_ms=NOW)
    persisted = store.path.read_bytes()

    assert store.delete_job_scratch("main", owner.job_id, expected_revision=2,
                                    expected_owner_generation=owner.generation) is False
    assert store.path.read_bytes() == persisted
    assert store.delete_job_scratch("main", owner.job_id, expected_revision=1,
                                    expected_owner_generation=owner.generation) is True
    reopened = FileAutomationStore(tmp_path)
    assert reopened.read_job_scratch("main", owner.job_id).current_revision == 0
    assert reopened.read_heartbeat_monitor_scratch("main").owner == owner


def test_omitting_delete_generation_preserves_deliberate_orphan_cleanup_abi(tmp_path):
    store = _owned(tmp_path)
    old = store.enroll_heartbeat_monitor("main", "old-owner")
    store.write_job_scratch("main", old.job_id, "orphan", now_ms=NOW)
    current = store.enroll_heartbeat_monitor("main", "current-owner")
    store.write_job_scratch("main", current.job_id, "current", now_ms=NOW + 1)

    assert FileAutomationStore(tmp_path).delete_job_scratch("main", old.job_id, expected_revision=1) is True

    assert store.read_job_scratch("main", old.job_id).current_revision == 0
    assert store.read_heartbeat_monitor_scratch("main").state.content == "current"
    assert store.read_heartbeat_monitor_scratch("main").owner == current


@pytest.mark.parametrize("generation", [True, 0, -1, 1.5, 2**53])
def test_invalid_delete_generation_is_refused_without_changing_bytes(tmp_path, generation):
    store = _owned(tmp_path)
    owner = store.ensure_heartbeat_monitor("main")
    store.write_job_scratch("main", owner.job_id, "private", now_ms=NOW)
    persisted = store.path.read_bytes()

    with pytest.raises(ValueError):
        store.delete_job_scratch("main", owner.job_id, expected_revision=1,
                                  expected_owner_generation=generation)

    assert store.path.read_bytes() == persisted


def test_concurrent_real_process_ensure_calls_reuse_one_durable_enrollment(tmp_path):
    script = """
import json,sys
from memory_core.automation import FileAutomationStore
sys.stdin.readline()
owner=FileAutomationStore(sys.argv[1],require_monitor_owner=True).ensure_heartbeat_monitor('main')
print(json.dumps({'agent':owner.agent_id,'job':owner.job_id,'generation':owner.generation}),flush=True)
"""
    environment = {"PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PATH": os.defpath, "LANG": "C.UTF-8"}
    children = [subprocess.Popen([sys.executable, "-c", script, str(tmp_path)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment) for _ in range(2)]
    try:
        for child in children:
            child.stdin.write("start\n")
            child.stdin.flush()
        replies = []
        for child in children:
            stdout, stderr = child.communicate(timeout=10)
            assert child.returncode == 0, stderr
            replies.append(json.loads(stdout))
        assert replies == [{"agent": "main", "job": "heartbeat:main", "generation": 1}] * 2
        owner = FileAutomationStore(tmp_path).read_heartbeat_monitor_scratch("main").owner
        assert owner.job_id == "heartbeat:main" and owner.generation == 1
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)
