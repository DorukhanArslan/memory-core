"""Offline tests for memory_core.automation (job schedule, due selection, scheduled tasks, store).

Anchors and cadences follow src/commands/doctor-heartbeat-task-migration.test.ts at v2026.9.6
(nowMs 2e12, 1 h and 2 h tasks); tests/integration/test_openclaw_ts_oracle.py
(automationJobSchedule) compares the schedule math with the real computeJobNextRunAtMs.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from memory_core.automation import (
    AutomationJob,
    FileAutomationStore,
    assert_automation_jobs_can_persist,
    compute_job_next_run_at_ms,
    due_automation_jobs,
    heartbeat_scheduled_tasks,
    heartbeat_task_declaration_key,
    is_job_due,
    record_automation_job_run,
)
from memory_core.heartbeat import HeartbeatScheduledTask

NOW = 2_000_000_000_000


def _job(job_id: str, name: str, every_ms: int, anchor_ms: int | None, **fields) -> AutomationJob:
    job = AutomationJob(
        id=job_id,
        name=name,
        agent_id=fields.pop("agent_id", "main"),
        every_ms=every_ms,
        anchor_ms=anchor_ms,
        text=fields.pop("text", f"Check {name}"),
        declaration_key=heartbeat_task_declaration_key("main", name),
        created_at_ms=NOW,
        updated_at_ms=NOW,
        **fields,
    )
    return AutomationJob(**{**job.__dict__, "next_run_at_ms": compute_job_next_run_at_ms(job, NOW)})


def test_migrated_anchors_give_the_first_run():
    calendar = _job("b", "calendar", 2 * 3_600_000, NOW + 1)
    inbox = _job("a", "inbox", 3_600_000, NOW + 30 * 60_000)
    assert calendar.next_run_at_ms == NOW + 1
    assert inbox.next_run_at_ms == NOW + 30 * 60_000
    assert due_automation_jobs([calendar, inbox], NOW) == []
    assert due_automation_jobs([calendar, inbox], NOW + 1) == [calendar]
    assert due_automation_jobs([calendar, inbox], NOW + 30 * 60_000) == [calendar, inbox]


def test_next_run_follows_the_last_run_then_the_anchor_grid():
    job = _job("a", "inbox", 60_000, 0, last_run_at_ms=120_000)
    assert compute_job_next_run_at_ms(job, 150_000) == 180_000
    assert compute_job_next_run_at_ms(job, 181_000) == 240_000
    assert compute_job_next_run_at_ms(AutomationJob(**{**job.__dict__, "enabled": False}), 0) is None


def test_record_run_moves_the_next_slot_from_the_run_end():
    job = _job("a", "inbox", 3_600_000, NOW + 1)
    ran = record_automation_job_run(job, started_at_ms=NOW + 5, ended_at_ms=NOW + 10)
    assert ran.last_run_at_ms == NOW + 5
    assert ran.next_run_at_ms == NOW + 5 + 3_600_000
    assert not is_job_due(ran, NOW + 3_600_000)
    assert is_job_due(ran, NOW + 5 + 3_600_000)


def test_scheduled_tasks_are_heartbeat_task_jobs_sorted_by_job_id():
    other = AutomationJob(id="0", name="report", agent_id="main", every_ms=60_000, text="x")
    tasks = heartbeat_scheduled_tasks(
        [_job("b", "calendar", 60_000, 0), _job("a", "inbox", 60_000, 0), other]
    )
    assert tasks == (
        HeartbeatScheduledTask(job_id="a", name="inbox", prompt="Check inbox"),
        HeartbeatScheduledTask(job_id="b", name="calendar", prompt="Check calendar"),
    )


def test_declaration_key_keeps_the_first_occurrence_name_only():
    first = heartbeat_task_declaration_key("main", "inbox")
    assert first == heartbeat_task_declaration_key("main", "inbox", 0)
    assert first != heartbeat_task_declaration_key("main", "inbox", 1)
    assert first.startswith("heartbeat-task:main:") and len(first.rsplit(":", 1)[1]) == 24


def test_store_round_trips_jobs_and_upserts_by_id(tmp_path):
    store = FileAutomationStore(tmp_path)
    inbox = _job("a", "inbox", 3_600_000, NOW + 1)
    store.save_jobs([inbox, _job("b", "calendar", 60_000, 0, agent_id="ops")])
    assert store.list_jobs(agent_id="main") == [inbox]
    moved = record_automation_job_run(inbox, started_at_ms=NOW + 1)
    store.save_jobs([moved], remove=["b"])
    assert store.list_jobs() == [moved]
    assert AutomationJob.from_json(moved.to_json()) == moved


def test_store_saves_jobs_and_scratch_in_one_compare_and_swap(tmp_path):
    store = FileAutomationStore(tmp_path)
    store.write_scratch("main", "tasks:\n", now_ms=1)
    conflict = store.save_jobs(
        [_job("a", "inbox", 60_000, 0)],
        scratch_agent_id="main",
        scratch_content="",
        scratch_expected_revision=0,
        now_ms=2,
    )
    assert conflict is not None and conflict.reason == "revision-conflict"
    assert store.list_jobs() == []
    written = store.save_jobs(
        [_job("a", "inbox", 60_000, 0)],
        scratch_agent_id="main",
        scratch_content="",
        scratch_expected_revision=1,
        now_ms=3,
    )
    assert written is not None and written.current_revision == 2
    assert [job.id for job in store.list_jobs()] == ["a"]
    assert store.read_scratch("main").content == ""


def test_store_refuses_jobs_the_cron_store_cannot_persist(tmp_path):
    # assertCronStoreCanPersist: normalizeCronJobInput floors the schedule numbers, then
    # getInvalidPersistedCronJobReason checks the state timestamps and the schedule.
    inbox = _job("job-1", "inbox", 60 * 60_000, NOW)
    [floored] = assert_automation_jobs_can_persist([replace(inbox, every_ms=60_000.9, anchor_ms=NOW + 0.5)])
    assert (floored.every_ms, floored.anchor_ms) == (60_000, NOW)
    for bad in (
        replace(inbox, last_run_at_ms=NOW + 0.5),
        replace(inbox, last_run_at_ms=-5),
        replace(inbox, next_run_at_ms=2**53),
        replace(inbox, every_ms=0.5),
        replace(inbox, anchor_ms=-1),
        replace(inbox, id=" "),
    ):
        with pytest.raises(ValueError, match=r"^Cannot persist cron store with 1 invalid job\(s\)$"):
            assert_automation_jobs_can_persist([inbox, bad])
    store = FileAutomationStore(tmp_path)
    with pytest.raises(ValueError):
        store.save_jobs([inbox, replace(inbox, id="job-2", last_run_at_ms=-5)])
    assert store.list_jobs() == [] and not store.path.exists()
