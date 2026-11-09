"""Public Doctor repair/preview, durable-owner races and actual OS claim evidence."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from memory_core.automation import FileAutomationStore
from memory_core import heartbeat_migration as migration
from memory_core.heartbeat_scratch import hash_heartbeat_scratch_source

NOW = 2_000_000_000_000
CONTENT = "- Real source instructions\n"


@pytest.mark.parametrize("content", [None, b"- Preview\r\n", b"\xff", b"x" * 262145])
def test_public_preview_validates_without_store_enrollment_or_any_file_mutation(
    tmp_path, monkeypatch, content
):
    source = tmp_path / "HEARTBEAT.md"
    if content is not None:
        source.write_bytes(content)
    store = FileAutomationStore(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("preview enrolled or recovered a source")

    monkeypatch.setattr(store, "ensure_heartbeat_monitor", forbidden)
    monkeypatch.setattr(migration, "_restore_claim_no_clobber", forbidden)
    result = migration.migrate_heartbeat_md(tmp_path, store, should_repair=False, now_ms=NOW)
    assert result.changes == ()
    assert bool(result.warnings) == (
        content is not None and (content == b"\xff" or len(content) > 262144)
    )
    assert source.read_bytes() == content if content is not None else not source.exists()
    assert not store.path.exists()
    assert not migration.heartbeat_migration_archive_dir(tmp_path).exists()


def test_preview_keeps_actual_dead_claim_in_place(tmp_path):
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    assert not Path(f"/proc/{child.pid}").exists()
    claim = tmp_path / f"HEARTBEAT.md.doctor-importing-{child.pid}-0123456789ab"
    claim.write_text(CONTENT)
    store = FileAutomationStore(tmp_path)
    result = migration.migrate_heartbeat_md(tmp_path, store, should_repair=False)
    assert result.changes == () and "interrupted migration claim" in result.warnings[0]
    assert claim.read_text() == CONTENT and not (tmp_path / "HEARTBEAT.md").exists()
    assert (
        not store.path.exists() and not migration.heartbeat_migration_archive_dir(tmp_path).exists()
    )


@pytest.mark.parametrize("source_bytes", [None, b"\xff"])
def test_repair_prepares_configured_owners_before_missing_or_invalid_source_and_reopens(
    tmp_path, source_bytes
):
    if source_bytes is not None:
        (tmp_path / "HEARTBEAT.md").write_bytes(source_bytes)
    result = migration.migrate_heartbeat_md(
        tmp_path,
        FileAutomationStore(tmp_path),
        agent_ids=["main"],
        monitor_agent_ids=["main", "disabled"],
        now_ms=NOW,
    )
    assert result.changes == ()
    reopened = FileAutomationStore(tmp_path)
    for agent in ("main", "disabled"):
        monitor = reopened.read_heartbeat_monitor_scratch(agent)
        assert (
            monitor is not None
            and monitor.state.current_revision == 0
            and monitor.state.scratch is None
        )
    assert reopened.list_jobs() == []
    assert bool(result.warnings) == (source_bytes is not None)


def test_shared_disabled_owner_is_prepared_and_reenabled_with_same_identity(tmp_path):
    source = tmp_path / "HEARTBEAT.md"
    source.write_text(CONTENT)
    store = FileAutomationStore(tmp_path)
    first = migration.migrate_heartbeat_md(
        tmp_path,
        store,
        agent_ids=["main"],
        monitor_agent_ids=["main", "ops"],
        retain_source=True,
        now_ms=NOW,
    )
    main, ops = [store.read_heartbeat_monitor_scratch(agent) for agent in ("main", "ops")]
    assert len(first.changes) == 1 and source.read_text() == CONTENT
    assert main.state.content == CONTENT and ops.state.current_revision == 0
    reopened = FileAutomationStore(tmp_path)
    second = migration.migrate_heartbeat_md(
        tmp_path,
        reopened,
        agent_ids=["main", "ops"],
        monitor_agent_ids=["main", "ops"],
        now_ms=NOW + 1,
    )
    assert len(second.changes) == 2 and not source.exists()
    assert reopened.read_heartbeat_monitor_scratch("main").owner == main.owner
    assert reopened.read_heartbeat_monitor_scratch("main").state.current_revision == 1
    assert reopened.read_heartbeat_monitor_scratch("ops").owner == ops.owner
    assert reopened.read_heartbeat_monitor_scratch("ops").state.content == CONTENT


@pytest.mark.parametrize("explicit_unset", [False, True])
def test_real_doctor_first_enrollment_preserves_legacy_operator_content_or_unset(
    tmp_path, explicit_unset
):
    source = tmp_path / "HEARTBEAT.md"
    source.write_text(CONTENT)
    store = FileAutomationStore(tmp_path)
    store.write_scratch("main", "operator notes", now_ms=NOW)
    if explicit_unset:
        store.write_scratch("main", None, expected_revision=1, now_ms=NOW)
    before = store.read_scratch("main")
    result = migration.migrate_heartbeat_md(tmp_path, store, now_ms=NOW)
    assert not result.changes and source.read_text() == CONTENT
    reopened = FileAutomationStore(tmp_path).read_heartbeat_monitor_scratch("main")
    assert reopened is not None and reopened.state == before


def test_repair_preserves_an_existing_custom_job_identity(tmp_path):
    (tmp_path / "HEARTBEAT.md").write_text(CONTENT)
    store = FileAutomationStore(tmp_path)
    owner = store.enroll_heartbeat_monitor("main", "existing-custom-monitor")
    assert migration.migrate_heartbeat_md(tmp_path, store, now_ms=NOW).warnings == ()
    actual = FileAutomationStore(tmp_path).read_heartbeat_monitor_scratch("main")
    assert actual.owner == owner and actual.state.content == CONTENT


def test_first_repair_keeps_the_exact_owner_returned_before_a_competing_aba(tmp_path, monkeypatch):
    source = tmp_path / "HEARTBEAT.md"
    source.write_text(CONTENT)
    store = FileAutomationStore(tmp_path)
    original = store.ensure_heartbeat_monitor
    saved = {}

    def replace_before_return(agent, **options):
        captured = original(agent, **options)
        assert store.remove_heartbeat_monitor(
            agent, expected_generation=captured.generation, cleanup_scratch=True
        )
        replacement = store.enroll_heartbeat_monitor(agent, captured.job_id)
        store.write_job_scratch(agent, replacement.job_id, "replacement owner", now_ms=NOW)
        saved["bytes"] = store.path.read_bytes()
        return captured

    monkeypatch.setattr(store, "ensure_heartbeat_monitor", replace_before_return)
    with pytest.raises(migration.HeartbeatMigrationError, match="scratch changed"):
        migration.migrate_heartbeat_md(tmp_path, store, now_ms=NOW)
    assert source.read_text() == CONTENT and store.path.read_bytes() == saved["bytes"]
    assert not migration.heartbeat_migration_archive_dir(tmp_path).exists()


def test_held_import_revision_conflict_restores_source_and_keeps_competing_bytes(
    tmp_path, monkeypatch
):
    source = tmp_path / "HEARTBEAT.md"
    source.write_text(CONTENT)
    store = FileAutomationStore(tmp_path)
    original = migration._Claim.__init__
    saved = {}

    def competing_edit(claim, captured):
        original(claim, captured)
        owner = store.read_heartbeat_monitor_scratch("main").owner
        store.write_job_scratch("main", owner.job_id, "competing edit", now_ms=NOW)
        saved["bytes"] = store.path.read_bytes()

    monkeypatch.setattr(migration._Claim, "__init__", competing_edit)
    result = migration.migrate_heartbeat_md(tmp_path, store, now_ms=NOW)
    assert result.changes == () and result.warnings
    assert store.path.read_bytes() == saved["bytes"] and source.read_text() == CONTENT


def test_rollback_cannot_delete_replacement_generation_with_same_job_and_revision(
    tmp_path, monkeypatch
):
    source = tmp_path / "HEARTBEAT.md"
    source.write_text(CONTENT)
    store = FileAutomationStore(tmp_path)
    original = store.write_job_scratch
    saved = {}

    def replace_after_import(agent_id, job_id, content, **options):
        result = original(agent_id, job_id, content, **options)
        if options.get("source_sha256") == hash_heartbeat_scratch_source(CONTENT) and not saved:
            old = store.read_heartbeat_monitor_scratch(agent_id).owner
            assert store.remove_heartbeat_monitor(
                agent_id, job_id=job_id, expected_generation=old.generation, cleanup_scratch=True
            )
            new = store.enroll_heartbeat_monitor(agent_id, job_id)
            assert new.generation == old.generation + 1
            assert (
                original(agent_id, job_id, "replacement generation", now_ms=NOW).current_revision
                == result.current_revision
            )
            saved["bytes"] = store.path.read_bytes()
        return result

    monkeypatch.setattr(store, "write_job_scratch", replace_after_import)
    result = migration.migrate_heartbeat_md(tmp_path, store, now_ms=NOW)
    assert not result.changes and any("rollback" in warning for warning in result.warnings)
    assert source.read_text() == CONTENT and store.path.read_bytes() == saved["bytes"]
    assert (
        FileAutomationStore(tmp_path).read_heartbeat_monitor_scratch("main").state.content
        == "replacement generation"
    )


@pytest.mark.skipif(sys.platform != "linux", reason="Actual Linux /proc claim fixture")
def test_real_single_thread_zombie_claim_is_recovered_but_live_owner_is_held(tmp_path):
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = Path(f"/proc/{pid}/status").read_text()
            if "State:\tZ" in status and "Threads:\t1\n" in status:
                break
            time.sleep(0.01)
        else:
            pytest.fail("Actual single-thread zombie did not establish")
        claim = tmp_path / f"HEARTBEAT.md.doctor-importing-{pid}-0123456789ab"
        claim.write_text(CONTENT)
        result = migration.migrate_heartbeat_md(tmp_path, FileAutomationStore(tmp_path), now_ms=NOW)
        assert not result.warnings and result.changes and not claim.exists()
        assert (
            FileAutomationStore(tmp_path).read_heartbeat_monitor_scratch("main").state.content
            == CONTENT
        )
    finally:
        os.waitpid(pid, 0)
    live_root = tmp_path / "live"
    live_root.mkdir()
    live_claim = live_root / f"HEARTBEAT.md.doctor-importing-{os.getpid()}-0123456789ab"
    # Use a foreign genuine live process, since the current run may recover its own claim.
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys;sys.stdin.readline()"], stdin=subprocess.PIPE
    )
    try:
        live_claim = live_claim.with_name(f"HEARTBEAT.md.doctor-importing-{child.pid}-0123456789ab")
        live_claim.write_text(CONTENT)
        result = migration.migrate_heartbeat_md(
            live_root, FileAutomationStore(live_root), now_ms=NOW
        )
        assert not result.changes and "held by running process" in result.warnings[0]
        assert live_claim.read_text() == CONTENT
    finally:
        child.terminate()
        child.wait(timeout=10)


@pytest.mark.parametrize("status", ["State:\tZ (zombie)\n", "State:\tZ (zombie)\nThreads:\t2\n"])
def test_missing_or_multiple_thread_evidence_does_not_revoke_a_live_claim(monkeypatch, status):
    from memory_core.consolidation import file_lock

    monkeypatch.setattr(file_lock.os, "kill", lambda *args: None)
    monkeypatch.setattr(file_lock.Path, "read_text", lambda *args, **kwargs: status)
    assert migration._is_process_alive(123456) is True


@pytest.mark.parametrize(
    "failure",
    [PermissionError("unreadable evidence"), FileNotFoundError("unknown thread evidence")],
)
def test_unreadable_zombie_evidence_keeps_an_existing_process_live(monkeypatch, failure):
    from memory_core.consolidation import file_lock

    monkeypatch.setattr(file_lock.os, "kill", lambda *args: None)

    def unreadable(*args, **kwargs):
        raise failure

    monkeypatch.setattr(file_lock.Path, "read_text", unreadable)
    assert migration._is_process_alive(123456) is True


def test_custom_partition_mapping_uses_only_new_public_filename_capability(tmp_path):
    from equivalence.heartbeat_doctor_probe import sdk_doctor_phase, phase

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "HEARTBEAT.md").write_text(CONTENT)
    input_value = phase("repair", custom=True)
    actual = sdk_doctor_phase({"fixtureDirectory": str(tmp_path), "input": input_value})
    target = tmp_path / "custom-cron/jobs.json"
    assert actual["raw"]["storeConfiguration"]["store_path"] == str(target)
    assert target.exists() and not FileAutomationStore(workspace).path.exists()
    assert (
        actual["raw"]["snapshots"][-1]["monitors"]["main"]["state"]["scratch"]["content"] == CONTENT
    )


def test_legacy_custom_scratch_protocol_keeps_its_existing_host_owned_abi(tmp_path):
    underlying = FileAutomationStore(tmp_path)

    class LegacyCustomStore:
        def read_scratch(self, *args, **options):
            return underlying.read_scratch(*args, **options)

        def write_scratch(self, *args, **options):
            return underlying.write_scratch(*args, **options)

        def delete_scratch(self, *args, **options):
            return underlying.delete_scratch(*args, **options)

    (tmp_path / "HEARTBEAT.md").write_text(CONTENT)
    result = migration.migrate_heartbeat_md(tmp_path, LegacyCustomStore(), now_ms=NOW)
    assert not result.warnings and result.changes
    assert underlying.read_scratch("main").content == CONTENT
    assert underlying.heartbeat_ownership_enabled is False
