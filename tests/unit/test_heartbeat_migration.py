"""Offline tests for memory_core.heartbeat_migration (HEARTBEAT.md -> scratch, tasks: -> jobs).

Expected values come from src/commands/doctor-heartbeat-scratch-migration.test.ts and
doctor-heartbeat-task-migration.test.ts at v2026.9.6; the oracle suite runs the same fixtures
through the real doctor migrations (heartbeatScratchMigration, heartbeatTaskMigration,
legacyHeartbeatTasks).
"""

from __future__ import annotations

import os
import stat

import pytest

from memory_core.automation import FileAutomationStore, is_heartbeat_task_job
from memory_core.heartbeat_migration import (
    analyze_legacy_heartbeat_tasks,
    heartbeat_md_migration_findings,
    heartbeat_migration_archive_dir,
    heartbeat_task_migration_findings,
    migrate_heartbeat_md,
    migrate_heartbeat_tasks,
)
from memory_core.heartbeat_scratch import hash_heartbeat_scratch_source

NOW = 2_000_000_000_000
OPERATIONS = """# Operations

tasks:
  - name: inbox
    interval: 1h
    prompt: Check urgent inbox items
  - name: calendar
    interval: 2h
    prompt: Check the next meetings

# Keep alerts concise
"""


def test_analyze_keeps_surrounding_scratch_and_counts_every_entry():
    document = analyze_legacy_heartbeat_tasks(OPERATIONS)
    assert document.has_tasks_block and document.task_entry_count == 2
    assert [task.name for task in document.tasks] == ["inbox", "calendar"]
    assert document.stripped_content == "# Operations\n\n# Keep alerts concise\n"
    orphan = analyze_legacy_heartbeat_tasks(
        "tasks:\n  interval: 15m\n  prompt: Orphaned\n  - name: inbox\n    interval: 1h\n"
        "    prompt: Check\n"
    )
    assert (orphan.task_entry_count, len(orphan.tasks)) == (2, 1)


def test_analyze_ignores_tasks_hidden_in_comments_but_keeps_the_comment_bytes():
    hidden = "Notes <!--\ntasks:\n  - name: disabled\n    interval: 5m\n    prompt: x\n-->\n# Keep\n"
    assert analyze_legacy_heartbeat_tasks(hidden).has_tasks_block is False
    shared = (
        "tasks:\n  - name: active\n    interval: 1h\n    prompt: Run the active check <!--\n"
        "tasks:\n  - name: disabled\n    interval: 5m\n    prompt: off\n-->\n# Keep\n"
    )
    document = analyze_legacy_heartbeat_tasks(shared)
    assert [task.name for task in document.tasks] == ["active"]
    assert "<!--\ntasks:\n  - name: disabled" in document.stripped_content


@pytest.mark.parametrize("under_home", [True, False], ids=["inside-home", "outside-home"])
def test_heartbeat_md_migrates_archives_and_reruns_idempotently(tmp_path, monkeypatch, under_home):
    monkeypatch.setenv("HOME", str(tmp_path if under_home else tmp_path / "home"))
    content = "# Operations\n\ntasks:\n  - name: inbox\n    interval: 1h\n    prompt: Check inbox\n"
    (tmp_path / "HEARTBEAT.md").write_text(content, encoding="utf-8")
    store = FileAutomationStore(tmp_path)
    assert [f.requirement for f in heartbeat_md_migration_findings(tmp_path)] == [
        "legacy-heartbeat-file"
    ]

    result = migrate_heartbeat_md(tmp_path, store, now_ms=NOW)

    assert result.warnings == ()
    expected_path = "~/HEARTBEAT.md" if under_home else str(tmp_path / "HEARTBEAT.md")
    assert result.changes == (
        f"Migrated {expected_path} into cron scratch for Heartbeat (main).",
    )
    assert not (tmp_path / "HEARTBEAT.md").exists()
    scratch = store.read_scratch("main").scratch
    assert scratch is not None and scratch.content == content and scratch.revision == 1
    assert scratch.source_sha256 == hash_heartbeat_scratch_source(content)
    archive_dir = heartbeat_migration_archive_dir(tmp_path)
    entries = sorted(archive_dir.iterdir())
    assert [entry.is_dir() for entry in entries] == [False, True]
    assert entries[0].read_text(encoding="utf-8") == content
    assert (entries[1] / "HEARTBEAT.md").read_text(encoding="utf-8") == content
    assert stat.S_IMODE(os.stat(archive_dir).st_mode) == 0o700
    assert migrate_heartbeat_md(tmp_path, store, now_ms=NOW).changes == ()
    assert heartbeat_md_migration_findings(tmp_path) == ()


def test_operator_scratch_is_never_overwritten(tmp_path):
    store = FileAutomationStore(tmp_path)
    store.write_scratch("main", "operator scratch\n", now_ms=NOW)
    (tmp_path / "HEARTBEAT.md").write_text("recreated legacy file\n", encoding="utf-8")

    result = migrate_heartbeat_md(tmp_path, store, now_ms=NOW)

    assert result.changes == ()
    assert result.warnings == (
        'Agent "main" already has different cron scratch; it was left unchanged.',
    )
    assert (tmp_path / "HEARTBEAT.md").read_text(encoding="utf-8") == "recreated legacy file\n"
    assert store.read_scratch("main").content == "operator scratch\n"


def test_a_retained_source_reports_no_legacy_finding(tmp_path):
    # collectHeartbeatScratchMigrationFindings skips a file shared with a disabled owner.
    store = FileAutomationStore(tmp_path)
    (tmp_path / "HEARTBEAT.md").write_text("shared checklist\n", encoding="utf-8")
    assert [f.requirement for f in heartbeat_md_migration_findings(tmp_path)] == [
        "legacy-heartbeat-file"
    ]
    assert heartbeat_md_migration_findings(tmp_path, retain_source=True) == ()

    migrate_heartbeat_md(tmp_path, store, retain_source=True, now_ms=NOW)

    assert (tmp_path / "HEARTBEAT.md").is_file()
    assert heartbeat_md_migration_findings(tmp_path, retain_source=True) == ()
    (tmp_path / "HEARTBEAT.md").unlink()
    (tmp_path / "HEARTBEAT.md").mkdir()
    [blocked] = heartbeat_md_migration_findings(tmp_path, retain_source=True)
    assert blocked.requirement == "heartbeat-file-migration-blocked"


def test_refused_sources_stay_in_place(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("- outside\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "HEARTBEAT.md").symlink_to(outside)
    store = FileAutomationStore(workspace)

    result = migrate_heartbeat_md(workspace, store)

    assert result.warnings == (
        'Agent "main" HEARTBEAT.md was not migrated: HEARTBEAT.md symlink target escapes the '
        "agent workspace",
    )
    assert (workspace / "HEARTBEAT.md").is_symlink()
    assert store.read_scratch("main").current_revision == 0


def test_task_migration_creates_jobs_strips_the_block_and_clears_legacy_timestamps(tmp_path):
    store = FileAutomationStore(tmp_path)
    store.write_scratch("main", OPERATIONS, now_ms=NOW)
    assert [f.requirement for f in heartbeat_task_migration_findings(store)] == [
        "heartbeat-tasks-in-scratch"
    ]

    result = migrate_heartbeat_tasks(
        store, legacy_task_state={"inbox": NOW - 30 * 60_000, "other": 1}, now_ms=NOW
    )

    assert result.warnings == ()
    assert result.changes == ('Converted 2 heartbeat tasks into cron jobs for agent "main".',)
    jobs = {job.name: job for job in store.list_jobs() if is_heartbeat_task_job(job)}
    assert (jobs["calendar"].every_ms, jobs["calendar"].anchor_ms) == (2 * 3_600_000, NOW + 1)
    assert jobs["calendar"].next_run_at_ms == NOW + 1
    assert (jobs["inbox"].every_ms, jobs["inbox"].anchor_ms) == (3_600_000, NOW + 30 * 60_000)
    assert jobs["inbox"].last_run_at_ms == NOW - 30 * 60_000
    assert jobs["inbox"].text == "Check urgent inbox items"
    assert store.read_scratch("main").content == "# Operations\n\n# Keep alerts concise\n"
    assert (result.task_state, result.task_state_changed) == ({"other": 1}, True)
    rerun = migrate_heartbeat_tasks(store, now_ms=NOW + 10_000)
    assert (rerun.changes, rerun.warnings) == ((), ())
    assert len(store.list_jobs()) == 2


def test_task_migration_refuses_an_incomplete_block(tmp_path):
    content = "tasks:\n  interval: 15m\n  prompt: Orphaned\n  - name: inbox\n    interval: 1h\n    prompt: x\n"
    store = FileAutomationStore(tmp_path)
    store.write_scratch("main", content, now_ms=NOW)

    result = migrate_heartbeat_tasks(store, now_ms=NOW)

    assert result.warnings == (
        'Agent "main" heartbeat tasks were not migrated: tasks: block contains an incomplete '
        "name/interval/prompt entry.",
    )
    assert store.read_scratch("main").content == content
    assert store.list_jobs() == []


def test_duplicate_task_names_get_stable_distinct_declarations(tmp_path):
    store = FileAutomationStore(tmp_path)
    store.write_scratch(
        "main",
        "tasks:\n  - name: inbox\n    interval: 1h\n    prompt: First\n"
        "  - name: inbox\n    interval: 1h\n    prompt: Second\n",
        now_ms=NOW,
    )
    migrate_heartbeat_tasks(store, now_ms=NOW)
    keys = {job.declaration_key for job in store.list_jobs()}
    assert len(keys) == 2
    assert store.read_scratch("main").content == ""
