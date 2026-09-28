"""HostKit.heartbeat_prompt() and HeartbeatRun (docs/host_kit.md, entry point 6, Task 6)."""

from __future__ import annotations

import dataclasses

import pytest

from memory_core.automation import (
    AutomationJob,
    FileAutomationStore,
    due_automation_jobs,
    heartbeat_scheduled_tasks,
    heartbeat_task_declaration_key,
    record_automation_job_run,
)
from memory_core.bootstrap import build_workspace_context
from memory_core.client import Memory
from memory_core.config import MemoryConfig
from memory_core.flags import FeatureFlags
from memory_core.heartbeat import decide_heartbeat_reply, prepare_heartbeat_turn
from memory_core.host import HostKit, SessionState, TurnUsage

NOW_MS = 1_790_375_400_000  # 2026-09-25 22:30 UTC
HOUR = 3_600_000
SCRATCH = "- Check the release board for red builds.\n"


def _kit(root, **options) -> HostKit:
    config = MemoryConfig(workspace_dir=root, flags=FeatureFlags(vector_search=False))
    memory = Memory.from_workspace(root, config=config, initialize=False)
    return HostKit(memory, now_ms=lambda: NOW_MS, **options)


def _session(kind="heartbeat") -> SessionState:
    return SessionState.new(session_key="agent:main:heartbeat", session_id="h1", kind=kind)


def _job(job_id: str, name: str, *, next_run: int = NOW_MS - 1, task: bool = True) -> AutomationJob:
    return AutomationJob(
        id=job_id,
        name=name,
        agent_id="main",
        every_ms=HOUR,
        text=f"Check {name}.",
        declaration_key=heartbeat_task_declaration_key("main", name) if task else None,
        created_at_ms=NOW_MS - HOUR,
        updated_at_ms=NOW_MS - HOUR,
        next_run_at_ms=next_run,
    )


def _store(root, *jobs: AutomationJob, scratch: str | None = SCRATCH) -> FileAutomationStore:
    store = FileAutomationStore(root)
    if scratch is not None:
        store.write_scratch("main", scratch, now_ms=NOW_MS - HOUR)
    if jobs:
        store.save_jobs(list(jobs))
    return store


def test_heartbeat_message_equals_prepare_heartbeat_turn(tmp_path):
    store = _store(tmp_path, _job("job-a", "inbox"))
    kit = _kit(tmp_path, timezone="Europe/Istanbul", time_format="12")

    run = kit.heartbeat_prompt(_session(), source="interval")

    due = due_automation_jobs(store.list_jobs(agent_id="main"), NOW_MS)
    assert run.turn == prepare_heartbeat_turn(
        now_ms=NOW_MS,
        scratch=store.read_scratch("main"),
        scheduled_tasks=heartbeat_scheduled_tasks(due),
        source="interval",
        timezone="Europe/Istanbul",
        time_format="12",
    )
    assert "Check the release board" in run.turn.message
    assert "Check inbox." in run.turn.message
    assert run.transcript_prompt == "[memory-core heartbeat poll]"
    assert run.started_at_ms == NOW_MS


def test_empty_scratch_skips_without_context(tmp_path):
    store = _store(tmp_path, scratch="# Checklist\n\n- [ ]\n")
    kit = _kit(tmp_path, seed_bootstrap=True)

    run = kit.heartbeat_prompt(_session())
    outcome = run.complete(None)

    assert run.turn.skip_reason == "empty-heartbeat-file"
    assert run.context is None
    assert not (tmp_path / "BOOTSTRAP.md").exists()
    assert outcome.jobs_recorded == ()
    assert outcome.decision.deliver is False
    assert store.list_jobs() == []


def test_due_heartbeat_tasks_reach_the_turn_and_other_jobs_stay_with_the_host(tmp_path):
    task = _job("job-a", "inbox")
    other = _job("job-b", "digest", task=False)
    later = _job("job-c", "calendar", next_run=NOW_MS + HOUR)
    _store(tmp_path, task, other, later)

    run = _kit(tmp_path).heartbeat_prompt(_session())

    assert run.jobs == (task,)
    assert run.host_jobs == (other,)
    assert [scheduled.job_id for scheduled in run.turn.scheduled_tasks] == ["job-a"]


def test_heartbeat_context_uses_run_kind_heartbeat(tmp_path):
    _store(tmp_path)
    kit = _kit(tmp_path, seed_bootstrap=True)
    session = _session(kind="main")

    run = kit.heartbeat_prompt(session, runtime_context="channel: #ops")

    assert run.context.workspace == build_workspace_context(
        tmp_path, session_kind="main", run_kind="heartbeat", has_bootstrap_file_access=False
    )
    assert run.context.workspace.bootstrap_mode == "none"
    assert run.context.runtime_context is not None
    assert run.context.tools == tuple(kit.tools())
    assert run.session == run.context.session


def test_light_context_injects_no_bootstrap_file(tmp_path):
    _store(tmp_path)
    kit = _kit(tmp_path, templates={"AGENTS.md": "# AGENTS.md\n\nBe brief.\n"})

    full = kit.heartbeat_prompt(_session())
    light = kit.heartbeat_prompt(_session(), context_mode="lightweight")

    assert full.context.workspace.files
    assert light.context.workspace.files == ()
    assert "Be brief." not in light.context.system_prompt


def test_schedule_clock_is_separate_from_the_prompt_clock(tmp_path):
    store = _store(tmp_path, _job("job-a", "inbox", next_run=NOW_MS + HOUR))
    kit = _kit(tmp_path, timezone="UTC")

    idle = kit.heartbeat_prompt(_session())
    run = kit.heartbeat_prompt(_session(), schedule_now_ms=NOW_MS + 2 * HOUR)
    outcome = run.complete("NO_REPLY")

    assert idle.jobs == ()
    assert [job.id for job in run.jobs] == ["job-a"]
    assert run.started_at_ms == NOW_MS + 2 * HOUR
    assert "22:30" in run.turn.message
    assert store.list_jobs()[0].last_run_at_ms == NOW_MS + 2 * HOUR
    assert outcome.jobs_recorded == tuple(store.list_jobs())


def test_complete_records_only_the_jobs_in_the_turn(tmp_path):
    task = _job("job-a", "inbox")
    other = _job("job-b", "digest", task=False)
    store = _store(tmp_path, task, other)
    run = _kit(tmp_path).heartbeat_prompt(_session())

    outcome = run.complete("Inbox has 3 red builds.", ended_at_ms=NOW_MS + 5_000)

    expected = record_automation_job_run(task, started_at_ms=NOW_MS, ended_at_ms=NOW_MS + 5_000)
    assert outcome.jobs_recorded == (expected,)
    assert {job.id: job for job in store.list_jobs()} == {"job-a": expected, "job-b": other}


def test_complete_skips_jobs_changed_or_removed_during_the_run(tmp_path):
    edited = _job("job-a", "inbox")
    removed = _job("job-b", "calendar")
    kept = _job("job-c", "tickets")
    store = _store(tmp_path, edited, removed, kept)
    run = _kit(tmp_path).heartbeat_prompt(_session())
    assert len(run.jobs) == 3
    changed = dataclasses.replace(edited, text="Check the inbox twice.", updated_at_ms=NOW_MS)
    store.save_jobs([changed], remove=["job-b"])

    outcome = run.complete("NO_REPLY")

    assert [job.id for job in outcome.jobs_recorded] == ["job-c"]
    jobs = {job.id: job for job in store.list_jobs()}
    assert set(jobs) == {"job-a", "job-c"}
    assert jobs["job-a"] == changed
    assert jobs["job-c"].last_run_at_ms == NOW_MS


@pytest.mark.parametrize(
    ("reply", "delivered"),
    [("NO_REPLY", False), ("HEARTBEAT_OK", False), ("", False), ("Two builds are red.", True)],
)
def test_no_reply_and_ack_are_not_delivered(tmp_path, reply, delivered):
    _store(tmp_path)

    outcome = _kit(tmp_path).heartbeat_prompt(_session()).complete(reply)

    assert outcome.decision == decide_heartbeat_reply(reply)
    assert outcome.decision.deliver is delivered


def test_complete_records_usage_without_a_flush(tmp_path):
    _store(tmp_path)
    run = _kit(tmp_path).heartbeat_prompt(_session())

    outcome = run.complete("Two builds are red.", usage=TurnUsage(199_000, 40))

    assert outcome.session.entry["totalTokens"] == 199_000
    assert outcome.session.last_output_tokens == 40
    assert "memoryFlush" not in outcome.session.entry
    assert not (tmp_path / "memory").exists()
    assert outcome.transcript == (
        {"role": "user", "content": "[memory-core heartbeat poll]"},
        {"role": "assistant", "content": "Two builds are red."},
    )


def test_heartbeat_complete_twice_raises(tmp_path):
    _store(tmp_path)
    run = _kit(tmp_path).heartbeat_prompt(_session())
    run.complete("NO_REPLY")

    with pytest.raises(RuntimeError, match="already completed"):
        run.complete("NO_REPLY")
