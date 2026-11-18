"""Automation jobs: recurring heartbeat tasks as independently scheduled jobs.

At v2026.9.6 a recurring ``tasks:`` entry of the retired HEARTBEAT.md is an automation (cron)
job of its own (b23c7bd0f84, #113165): an ``every`` schedule, a ``systemEvent`` payload whose
text is the task prompt, ``sessionTarget: "main"`` and a ``heartbeat-task:`` declaration key.
When such a job is due, cron hands it to the heartbeat runner as a scheduled task
(``src/cron/service/timer-execution.ts``: ``{jobId, name, prompt}``), and the heartbeat turn
lists it in ``Run the following periodic tasks ...``.

The host owns the scheduler (timers, retries, run history). memory-core owns the observable
decisions, ported from ``src/cron/service/jobs-scheduling.ts`` and ``src/cron/schedule.ts``:

- :func:`compute_job_next_run_at_ms` (``computeJobNextRunAtMs`` for ``every`` schedules:
  anchor from ``anchorMs`` or ``createdAtMs``, next slot after the last run, else the next
  anchor step after now) and :func:`is_job_due` (``isJobDue``: enabled, a scheduled next run,
  ``now >= nextRunAtMs``);
- :func:`due_automation_jobs` (the due jobs of one agent) and :func:`heartbeat_scheduled_tasks`
  (the heartbeat runner's ``tasks``: only heartbeat-task jobs, ``isHeartbeatTaskCronJob``,
  sorted by job id like ``resolveHeartbeatWakeStage``);
- :func:`record_automation_job_run`: after a successful or skipped run, ``lastRunAtMs`` is the
  run start and the next run is ``computeJobNextRunAtMs(job, endedAt)`` (the ok/skipped path of
  ``applyJobResult``, ``src/cron/service/timer-outcomes.ts``); error backoff is the host's;
- :func:`heartbeat_task_declaration_key` (``src/cron/heartbeat-task.ts``);
- the persist gate of ``src/cron/store/row-codec.ts`` (``assertCronStoreCanPersist``,
  ``normalizeCronJobForSqlite``): :func:`assert_automation_jobs_can_persist` refuses a job whose
  ``everyMs`` is not a safe integer >= 1 after the flooring of ``src/cron/normalize.ts``, whose
  ``anchorMs`` is not a non-negative safe integer after it, or whose ``lastRunAtMs`` /
  ``nextRunAtMs`` is not a non-negative safe integer (``getInvalidPersistedCronJobReason``,
  ``src/cron/persisted-shape.ts``); :class:`FileAutomationStore` applies it on every save.

:class:`AutomationStore` is the store interface of the monitor scratch and the jobs;
:class:`FileAutomationStore` is its default implementation: one JSON file,
``<root>/.memory-core/automation.json``, written atomically under a lock, so a migration can move
tasks out of the scratch and into jobs in one write (upstream: one state-DB transaction).

The SDK also accepts absolute one-shot and cron calendar schedules, including timezones,
DST transitions and deterministic stagger. Hosts can reserve one memory task by id, record its
settlement and migrate old interval timestamps. Gateway triggers, notification delivery,
configurable retry/auto-disable policies and startup recovery remain host integrations. FileAutomationStore optionally persists monitor
ownership and job-keyed scratch without constructing or running a scheduler.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, Protocol

from memory_core._heartbeat_constants import (
    CRON_STORE_CANNOT_PERSIST,
    HEARTBEAT_TASK_DECLARATION_PREFIX,
)
from memory_core.bootstrap._js import js_json_stringify, js_trim, locale_sort_key
from memory_core.heartbeat import HeartbeatScheduledTask
from memory_core.heartbeat_scratch import (
    HeartbeatMonitorOwner,
    HeartbeatMonitorScratch,
    HeartbeatMonitorEnrollmentConflictError,
    HeartbeatScratchState,
    HeartbeatScratchStore,
    HeartbeatScratchWrite,
    apply_heartbeat_scratch_delete,
    apply_heartbeat_scratch_write,
    assert_heartbeat_scratch_content,
)
from memory_core import heartbeat_ownership as _owners
from memory_core.project_name import STATE_DIRNAME
from memory_core.tools.common import parse_strict_finite_number

__all__ = [
    "AutomationJob",
    "AutomationStore",
    "FileAutomationStore",
    "SkippedAutomationJobRow",
    "assert_automation_jobs_can_persist",
    "compute_job_next_run_at_ms",
    "due_automation_jobs",
    "heartbeat_scheduled_tasks",
    "heartbeat_task_declaration_key",
    "is_heartbeat_task_job",
    "is_job_due",
    "record_automation_job_run",
]

# normalization-core number-coercion.ts MAX_DATE_TIMESTAMP_MS (Date's representable range).
_MAX_DATE_TIMESTAMP_MS = 8_640_000_000_000_000
_MAX_SAFE_INTEGER = 2**53 - 1
AUTOMATION_STORE_PARTS = (STATE_DIRNAME, "automation.json")


def _as_date_timestamp_ms(value: object) -> float | None:
    # asDateTimestampMs: a finite number inside Date's range.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if abs(value) > _MAX_DATE_TIMESTAMP_MS or not math.isfinite(value):
        return None
    return value


@dataclass(frozen=True)
class AutomationJob:
    """One stored memory job with an interval, absolute or cron calendar schedule.

    ``text`` is the ``systemEvent`` payload (a heartbeat task's prompt). ``to_json`` and
    ``from_json`` use upstream's field names, so a host can persist the job as it is.
    """

    id: str
    name: str
    agent_id: str
    every_ms: int | None
    text: str
    anchor_ms: int | None = None
    declaration_key: str | None = None
    display_name: str | None = None
    description: str | None = None
    enabled: bool = True
    created_at_ms: int | None = None
    updated_at_ms: int | None = None
    last_run_at_ms: int | None = None
    next_run_at_ms: int | None = None
    session_target: str = "main"
    wake_mode: str = "next-heartbeat"
    queued_at_ms: int | None = None
    running_at_ms: int | None = None
    calendar_schedule: dict[str, Any] | None = None
    agent_turn: dict[str, Any] | None = None
    has_agent_id: bool = True
    runtime_state: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        schedule: dict[str, Any] = {"kind": "every", "everyMs": self.every_ms}
        if self.anchor_ms is not None:
            schedule["anchorMs"] = self.anchor_ms
        state = dict(self.runtime_state)
        if self.last_run_at_ms is not None:
            state["lastRunAtMs"] = self.last_run_at_ms
        if self.next_run_at_ms is not None:
            state["nextRunAtMs"] = self.next_run_at_ms
        if self.queued_at_ms is not None:
            state["queuedAtMs"] = self.queued_at_ms
        if self.running_at_ms is not None:
            state["runningAtMs"] = self.running_at_ms
        out: dict[str, Any] = {**self.options, "id": self.id}
        if self.declaration_key is not None:
            out["declarationKey"] = self.declaration_key
        if self.display_name is not None:
            out["displayName"] = self.display_name
        out["name"] = self.name
        if self.description is not None:
            out["description"] = self.description
        if self.has_agent_id:
            out["agentId"] = self.agent_id
        out["enabled"] = self.enabled
        if self.created_at_ms is not None:
            out["createdAtMs"] = self.created_at_ms
        if self.updated_at_ms is not None:
            out["updatedAtMs"] = self.updated_at_ms
        out.update(
            {
                "schedule": dict(self.calendar_schedule) if self.calendar_schedule is not None else schedule,
                "payload": dict(self.agent_turn) if self.agent_turn is not None else {"kind": "systemEvent", "text": self.text},
                "sessionTarget": self.session_target,
                "wakeMode": self.wake_mode,
                "state": state,
            }
        )
        return out

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> AutomationJob:
        """Read a job in upstream's field names; ``ValueError`` for a shape it does not model.

        Values are taken as they are (the schedule math handles invalid ones like upstream);
        :meth:`FileAutomationStore.list_jobs` also skips rows the cron store would not load.
        """
        if not isinstance(data, dict):
            raise ValueError("job row is not an object")
        if not isinstance(data.get("id"), str):
            raise ValueError("job row has no string id")
        schedule = data.get("schedule") or {}
        payload = data.get("payload") or {}
        state = data.get("state") or {}
        if not all(isinstance(part, dict) for part in (schedule, payload, state)):
            raise ValueError("job schedule, payload and state must be objects")
        if schedule.get("kind") not in {"at", "cron", "every"} or payload.get("kind") not in {"systemEvent", "agentTurn"}:
            raise ValueError("unsupported schedule or payload")
        known_fields = {"id", "name", "agentId", "enabled", "schedule", "payload", "declarationKey", "displayName",
                        "description", "createdAtMs", "updatedAtMs", "state", "sessionTarget", "wakeMode"}
        known_state = {"lastRunAtMs", "nextRunAtMs", "queuedAtMs", "runningAtMs"}
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", "")),
            agent_id=str(data.get("agentId", "main")),
            every_ms=schedule.get("everyMs"),
            anchor_ms=schedule.get("anchorMs"),
            text=str(payload.get("text", "")),
            declaration_key=data.get("declarationKey"),
            display_name=data.get("displayName"),
            description=data.get("description"),
            enabled=data.get("enabled", True) is not False,
            created_at_ms=data.get("createdAtMs"),
            updated_at_ms=data.get("updatedAtMs"),
            last_run_at_ms=state.get("lastRunAtMs"),
            next_run_at_ms=state.get("nextRunAtMs"),
            queued_at_ms=state.get("queuedAtMs"),
            running_at_ms=state.get("runningAtMs"),
            session_target=str(data.get("sessionTarget", "main")),
            wake_mode=str(data.get("wakeMode", "next-heartbeat")),
            calendar_schedule=dict(schedule) if schedule["kind"] != "every" else None,
            has_agent_id="agentId" in data,
            agent_turn=dict(payload) if payload["kind"] == "agentTurn" else None,
            runtime_state={key: val for key, val in state.items() if key not in known_state},
            options={key: val for key, val in data.items() if key not in known_fields},
        )


def _as_safe_integer_in_range(value: object, minimum: int, maximum: int) -> bool:
    # normalization-core asSafeIntegerInRange: a number that is a safe integer within range.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):
        return False
    return abs(value) <= _MAX_SAFE_INTEGER and minimum <= value <= maximum


def _floor_schedule_number(value: object, minimum: int) -> object:
    # src/cron/normalize.ts coerceSchedule: a finite, Date-range everyMs >= 1 or anchorMs >= 0 is
    # floored (coerceFiniteScheduleNumber); anything else is left as it is.
    coerced = _as_date_timestamp_ms(parse_strict_finite_number(value))
    if coerced is not None and coerced >= minimum:
        return math.floor(coerced)
    return value


def _persisted_job(job: AutomationJob, *, normalize: bool = True) -> AutomationJob | None:
    """``normalizeCronJobForSqlite`` for an every-schedule ``systemEvent`` job (``None``: refused).

    ``normalizeCronJobInput`` floors the schedule numbers (``normalize``; the read path of
    ``rowToCronJob`` checks the stored values as they are), then
    ``getInvalidPersistedCronJobReason`` checks the id, the last/next run and active-run
    timestamps and the schedule (the payload text is always a string
    here).
    """
    if not js_trim(job.id):
        return None
    for value in (job.next_run_at_ms, job.last_run_at_ms, job.queued_at_ms, job.running_at_ms):
        if value is not None and not _as_safe_integer_in_range(value, 0, _MAX_DATE_TIMESTAMP_MS):
            return None
    if job.calendar_schedule is not None:
        from memory_core.automation_schedule import canonical_absolute_time, valid_calendar_schedule

        if not valid_calendar_schedule(job.calendar_schedule):
            return None
        if normalize and job.calendar_schedule["kind"] == "at":
            schedule = {**job.calendar_schedule, "at": canonical_absolute_time(job.calendar_schedule["at"])}
            return replace(job, calendar_schedule=schedule)
        return job
    every = _floor_schedule_number(job.every_ms, 1) if normalize else job.every_ms
    if not _as_safe_integer_in_range(every, 1, _MAX_DATE_TIMESTAMP_MS):
        return None
    anchor = job.anchor_ms
    if anchor is not None and normalize:
        anchor = _floor_schedule_number(anchor, 0)
    if anchor is not None and not _as_safe_integer_in_range(anchor, 0, _MAX_DATE_TIMESTAMP_MS):
        return None
    if every == job.every_ms and anchor == job.anchor_ms:
        return job
    new_anchor = None if anchor is None else int(anchor)  # type: ignore[call-overload]
    return replace(job, every_ms=int(every), anchor_ms=new_anchor)  # type: ignore[call-overload]


def assert_automation_jobs_can_persist(jobs: Sequence[AutomationJob]) -> list[AutomationJob]:
    """Port of ``assertCronStoreCanPersist``: the jobs as they would be stored, or ``ValueError``.

    Raises with upstream's ``Cannot persist cron store with N invalid job(s)`` when any job
    cannot be stored (see :func:`_persisted_job`); otherwise returns the normalized jobs.
    """
    persisted = [_persisted_job(job) for job in jobs]
    invalid = sum(1 for job in persisted if job is None)
    if invalid:
        raise ValueError(CRON_STORE_CANNOT_PERSIST.format(invalid_jobs=invalid))
    return [job for job in persisted if job is not None]


def _next_every_run_at_ms(every_ms: float, anchor_ms: float | None, now_ms: float) -> int | None:
    # src/cron/schedule.ts computeNextRunAtMs, kind "every".
    every_raw = _as_date_timestamp_ms(every_ms)
    if every_raw is None:
        return None
    every = math.floor(every_raw)
    if every < 1:
        return None
    anchor_raw = _as_date_timestamp_ms(anchor_ms) if anchor_ms is not None else None
    if anchor_ms is not None and (anchor_raw is None or anchor_raw < 0):
        return None
    anchor = max(0, math.floor(anchor_raw if anchor_raw is not None else now_ms))
    if now_ms < anchor:
        return anchor
    steps = math.floor((now_ms - anchor) / every) + 1
    result = _as_date_timestamp_ms(anchor + steps * every)
    return None if result is None else int(result)


def compute_job_next_run_at_ms(job: AutomationJob, now_ms: float) -> int | None:
    """Port of ``computeJobNextRunAtMs`` for an ``every`` schedule (``None``: never)."""
    if not job.enabled:
        return None
    if job.calendar_schedule is not None:
        from memory_core.automation_schedule import next_calendar_run

        return next_calendar_run(job, now_ms)
    anchor_ms = _as_date_timestamp_ms(parse_strict_finite_number(job.anchor_ms))
    if job.anchor_ms is not None and (anchor_ms is None or anchor_ms < 0):
        return None
    every_raw = _as_date_timestamp_ms(parse_strict_finite_number(job.every_ms))
    if every_raw is None:
        return None
    every = math.floor(every_raw)
    if every < 1:
        return None
    created = _as_date_timestamp_ms(job.created_at_ms)
    fallback = created if created is not None else now_ms
    if anchor_ms is not None:
        anchor = max(0, math.floor(anchor_ms))
    else:
        anchor = max(0, math.floor(fallback)) if _as_date_timestamp_ms(fallback) is not None else 0
    last = _as_date_timestamp_ms(job.last_run_at_ms)
    if last is not None and last >= anchor:
        from_last = _as_date_timestamp_ms(math.floor(last) + every)
        if from_last is None:
            return None
        if from_last > now_ms:
            return int(from_last)
    return _next_every_run_at_ms(every, anchor, now_ms)


def is_job_due(job: AutomationJob, now_ms: float, *, forced: bool = False) -> bool:
    """Whether a recurring job can be admitted at the due boundary."""
    next_run = _as_date_timestamp_ms(job.next_run_at_ms)
    active = any(type(marker) in (float, int) for marker in (job.queued_at_ms, job.running_at_ms))
    return not active and (forced or (job.enabled and next_run is not None and next_run > 0 and now_ms >= next_run))


def is_heartbeat_task_job(job: AutomationJob) -> bool:
    """``isHeartbeatTaskCronJob``: a ``heartbeat-task:`` declaration on the main session."""
    return bool(
        job.declaration_key
        and job.declaration_key.startswith(HEARTBEAT_TASK_DECLARATION_PREFIX)
        and job.session_target == "main"
        and job.agent_turn is None
    )


def heartbeat_task_declaration_key(agent_id: str, task_name: str, occurrence_index: int = 0) -> str:
    """Port of ``heartbeatTaskDeclarationKey`` (``src/cron/heartbeat-task.ts``).

    ``heartbeat-task:<agent>:<24 hex>`` of SHA-256 over agent id, NUL, task name, and for a
    repeated name also NUL and its occurrence ordinal.
    """
    digest = hashlib.sha256()
    digest.update(agent_id.encode("utf-8", errors="surrogatepass"))
    digest.update(b"\0")
    digest.update(task_name.encode("utf-8", errors="surrogatepass"))
    if occurrence_index > 0:
        digest.update(b"\0")
        digest.update(str(occurrence_index).encode("ascii"))
    return f"{HEARTBEAT_TASK_DECLARATION_PREFIX}{agent_id}:{digest.hexdigest()[:24]}"


def due_automation_jobs(
    jobs: Sequence[AutomationJob], now_ms: float, *, agent_id: str | None = None
) -> list[AutomationJob]:
    """The jobs due at ``now_ms`` (:func:`is_job_due`), optionally for one agent, in order."""
    return [
        job
        for job in jobs
        if (agent_id is None or job.agent_id == agent_id) and is_job_due(job, now_ms)
    ]


def heartbeat_scheduled_tasks(jobs: Sequence[AutomationJob]) -> tuple[HeartbeatScheduledTask, ...]:
    """The heartbeat runner's scheduled tasks for these (due) jobs.

    Heartbeat-task jobs become ``{jobId, name, prompt}`` (``timer-execution.ts``); the runner
    sorts them by job id with ``localeCompare`` (``resolveHeartbeatWakeStage``), approximated by
    :func:`memory_core.bootstrap._js.locale_compare` (exact for ASCII ids).
    """
    tasks = [
        HeartbeatScheduledTask(job_id=job.id, name=job.name, prompt=job.text)
        for job in jobs
        if is_heartbeat_task_job(job)
    ]
    return tuple(sorted(tasks, key=lambda task: locale_sort_key(task.job_id)))


def record_automation_job_run(
    job: AutomationJob, *, started_at_ms: int, ended_at_ms: int | None = None,
    status: Literal["ok", "skipped", "error"] = "ok", error: str | None = None, forced: bool = False,
) -> AutomationJob:
    """Record a completed heartbeat task and advance its durable scheduling state."""
    ended = started_at_ms if ended_at_ms is None else ended_at_ms
    state = dict(job.runtime_state)
    preserved = job.next_run_at_ms
    for key in ("forcePreservedNextRunAtMs", "pacedNextRunAtMs", "runningReceiptId", "runningScheduleChangeId",
                "lastError", "lastErrorReason", "lastDiagnostics", "lastDiagnosticSummary"):
        state.pop(key, None)
    state.update(lastRunStatus=status, lastStatus=status, lastDurationMs=max(0, ended - started_at_ms),
                 lastDeliveryStatus="not-requested", lastFailureNotificationDeliveryStatus="not-requested",
                 consecutiveErrors=state.get("consecutiveErrors", 0) + 1 if status == "error" else 0,
                 consecutiveSkipped=state.get("consecutiveSkipped", 0) + 1 if status == "skipped" else 0)
    if error is not None:
        state["lastError"] = error
    if status == "ok":
        state.pop("failureAlertIncident", None)
        state.pop("lastFailureAlertAtMs", None)
    else:
        state.setdefault("failureAlertIncident", {"scope": "run"})
    ran = replace(job, last_run_at_ms=int(started_at_ms), updated_at_ms=int(ended),
                  queued_at_ms=None, running_at_ms=None, runtime_state=state)
    once = (job.calendar_schedule or {}).get("kind") == "at"
    if forced and (not once or preserved is not None and preserved > started_at_ms):
        if preserved is not None:
            state["forcePreservedNextRunAtMs"] = preserved
        return ran
    if once:
        return replace(ran, enabled=False, next_run_at_ms=None)
    next_at = compute_job_next_run_at_ms(ran, ended)
    if next_at is not None and status == "error":
        delays = (30_000, 60_000, 300_000, 900_000, 3_600_000)
        lower_bound = ended + delays[min(state["consecutiveErrors"] - 1, len(delays) - 1)]
        if next_at < lower_bound and ran.calendar_schedule:
            next_at = compute_job_next_run_at_ms(ran, lower_bound - 1)
        else:
            next_at = max(next_at, lower_bound)
    return replace(ran, next_run_at_ms=next_at)


# --- store interface and default file-backed store ---------------------------------------------


class AutomationJobConflictError(RuntimeError):
    """A job definition changed during a proposed task migration."""


class AutomationStore(HeartbeatScratchStore, Protocol):
    """Where a host keeps the monitor scratch and the automation jobs (the migrations' store).

    :func:`memory_core.heartbeat_migration.migrate_heartbeat_tasks` needs, on top of
    :class:`~memory_core.heartbeat_scratch.HeartbeatScratchStore`:

    - ``list_jobs``: the jobs the store can load (rows it cannot load are skipped, like
      upstream's ``rowToCronJob`` returning ``null``);
    - ``save_jobs``: upsert ``jobs`` by id and drop ``remove`` ids in one atomic write. With
      ``scratch_agent_id`` the same write replaces that agent's scratch through
      :func:`~memory_core.heartbeat_scratch.apply_heartbeat_scratch_write`, a compare-and-swap on
      ``scratch_expected_revision``: on a conflict nothing is written and the conflicting
      :class:`~memory_core.heartbeat_scratch.HeartbeatScratchWrite` is returned, otherwise the
      scratch write (``None`` without ``scratch_agent_id``). Jobs that
      :func:`assert_automation_jobs_can_persist` refuses raise ``ValueError`` before anything
      is written (upstream: one state-DB transaction guarded by ``assertCronStoreCanPersist``).
    """

    def list_jobs(self, *, agent_id: str | None = None) -> list[AutomationJob]: ...

    def save_jobs(
        self,
        jobs: Sequence[AutomationJob],
        *,
        remove: Sequence[str] = (),
        scratch_agent_id: str | None = None,
        scratch_content: str | None = None,
        scratch_expected_revision: int | None = None,
        scratch_source_sha256: str | None = None,
        now_ms: int | None = None,
    ) -> HeartbeatScratchWrite | None: ...


@dataclass(frozen=True)
class SkippedAutomationJobRow:
    """A stored job row :meth:`FileAutomationStore.list_jobs` skipped: its index and why."""

    index: int
    job_id: str | None
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {"index": self.index, "id": self.job_id, "reason": self.reason}


class FileAutomationStore:
    """Monitor scratch and automation jobs in ``<root>/.memory-core/automation.json``.

    Implements :class:`AutomationStore`. Every change rewrites the file atomically (temp file +
    rename) under an advisory lock, so concurrent writers see compare-and-swap conflicts instead
    of lost updates. A job row it cannot load (a shape memory-core does not model, or values the
    cron store would not load) is skipped by ``list_jobs``, reported by
    :meth:`skipped_job_rows` and kept untouched by ``save_jobs``.

    Legacy per-agent scratch remains the default until explicit
    ``enroll_heartbeat_monitor``. ``require_monitor_owner=True`` rejects unowned
    writes even before enrollment. Once persisted, ownership applies to every
    later instance regardless of its constructor flag. Callers explicitly
    enroll each configured agent, optionally adopting its legacy scratch once;
    reads and heartbeat previews never enroll. This optional state interface
    does not add monitor jobs to the scheduler's ``AutomationJob`` collection.

    ``store_path`` selects an explicit storage filename; relative names are
    rooted at ``root``. The default filename and the workspace root retain
    their existing meaning, and locking and atomic replacement follow the
    selected filename.
    """

    def __init__(
        self, root: str | os.PathLike[str], *, require_monitor_owner: bool = False,
        store_path: str | os.PathLike[str] | None = None,
    ):
        if type(require_monitor_owner) is not bool:
            raise TypeError("require_monitor_owner must be a boolean")
        self.root = Path(os.path.abspath(os.path.expanduser(os.fspath(root))))
        if store_path is None:
            self.path = self.root.joinpath(*AUTOMATION_STORE_PARTS)
        else:
            selected = Path(os.path.expanduser(os.fspath(store_path)))
            self.path = Path(os.path.abspath(selected if selected.is_absolute() else self.root / selected))
        self._require_monitor_owner = require_monitor_owner

    # -- file plumbing

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 1, "scratch": {}, "jobs": []}
        if not isinstance(data, dict):
            raise ValueError(f"{self.path} is not an automation store")
        # An owned catalog must validate the original persisted version. Legacy
        # defaults must not repair a missing owned-store version before refusal.
        _owners.validate_catalog(data)
        data.setdefault("version", 1)
        if not isinstance(data.get("scratch"), dict):
            data["scratch"] = {}
        if not isinstance(data.get("jobs"), list):
            data["jobs"] = []
        return data

    def _save(self, data: dict[str, Any]) -> None:
        _owners.validate_catalog(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".automation.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                # JSON.stringify's well-formed output: a lone surrogate in a job field is kept
                # as a \udXXX escape (upstream job_json), never an unencodable character.
                handle.write(js_json_stringify(data, indent=2))
                handle.write("\n")
            os.chmod(temp, 0o600)
            os.replace(temp, self.path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp)
            raise

    @contextlib.contextmanager
    def _locked(self) -> Iterator[dict[str, Any]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(".lock")
        with open(lock_path, "a", encoding="utf-8") as lock:
            try:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):  # no advisory locks on this platform
                pass
            yield self._load()

    # -- scratch

    def _owned(self, data: dict[str, Any]) -> bool:
        return self._require_monitor_owner or _owners.CATALOG_KEY in data

    @property
    def heartbeat_ownership_enabled(self) -> bool:
        """Whether explicit ownership applies; reading never enrolls or writes.

        The opt-in is sticky once enrollment persists its catalog. Reopening a
        default legacy-compatible instance cannot revive a removed monitor.
        """
        return self._owned(self._load())

    def enroll_heartbeat_monitor(
        self, agent_id: str, job_id: str | None = None, *, adopt_legacy_scratch: bool = False,
        require_unconfigured: bool = False,
    ) -> HeartbeatMonitorOwner:
        """Explicit host configuration, independent of scheduling execution.

        Re-enrolling the same active job is idempotent. Replacement or revival
        increments the retained generation and leaves the previous job's
        scratch as an orphan. Legacy scratch is adopted only by an explicit
        request at first enrollment, preserving its existing revision.
        ``require_unconfigured`` atomically refuses an already persisted
        ownership catalog, so a first edit cannot adopt a competing owner.
        """
        _owners.identity(agent_id)
        job_id = _owners.identity(job_id if job_id is not None else f"heartbeat:{agent_id}")
        with self._locked() as data:
            if require_unconfigured and _owners.CATALOG_KEY in data:
                raise HeartbeatMonitorEnrollmentConflictError("heartbeat ownership was configured before enrollment")
            return self._enroll_heartbeat_monitor_unlocked(
                data, agent_id, job_id, adopt_legacy_scratch=adopt_legacy_scratch,
            )

    def ensure_heartbeat_monitor(
        self, agent_id: str, *, adopt_legacy_scratch: bool = False,
    ) -> HeartbeatMonitorOwner:
        """Explicitly prepare a configured monitor without replacing its owner.

        An existing active owner is returned exactly, including a custom job id
        and its generation. Otherwise enrollment and optional first adoption of
        legacy scratch share the same locked transaction. This method performs
        configuration work; construction and read APIs never call it.
        """
        _owners.identity(agent_id)
        with self._locked() as data:
            current = _owners.active_owner(data, agent_id)
            if current is not None:
                return current
            return self._enroll_heartbeat_monitor_unlocked(
                data, agent_id, f"heartbeat:{agent_id}", adopt_legacy_scratch=adopt_legacy_scratch,
            )

    def _enroll_heartbeat_monitor_unlocked(
        self, data: dict[str, Any], agent_id: str, job_id: str, *, adopt_legacy_scratch: bool,
    ) -> HeartbeatMonitorOwner:
        """Apply explicit enrollment while the caller holds this store's lock."""
        value = _owners.catalog(data, create=True)
        current = _owners.active_owner(data, agent_id)
        other = value["owners"].get(job_id)
        if other is not None and other["agentId"] != agent_id:
            raise ValueError("heartbeat job belongs to a different agent")
        if current is not None and current.job_id == job_id:
            return current
        previous = value["agents"].get(agent_id)
        generation = (previous["generation"] if previous is not None else 0) + 1
        _owners.bounded_integer(generation, minimum=1)
        if current is not None:
            value["owners"][current.job_id]["active"] = False
        value["agents"][agent_id] = {"jobId": job_id, "generation": generation}
        value["owners"][job_id] = {"agentId": agent_id, "generation": generation, "active": True}
        if adopt_legacy_scratch and previous is None and agent_id in data["scratch"]:
            value["scratch"][job_id] = data["scratch"].pop(agent_id)
        self._save(data)
        return HeartbeatMonitorOwner(agent_id, job_id, generation)

    def read_heartbeat_monitor_scratch(self, agent_id: str) -> HeartbeatMonitorScratch | None:
        """Resolve the current monitor without enrolling, repairing or writing."""
        data = self._load()
        owner = _owners.active_owner(data, agent_id)
        return (HeartbeatMonitorScratch(owner, _owners.job_state(data, agent_id, owner.job_id))
                if owner is not None else None)

    def remove_heartbeat_monitor(
        self, agent_id: str, *, job_id: str | None = None, expected_generation: int | None = None,
        cleanup_scratch: bool = False,
    ) -> bool:
        """Retire the owner, optionally deleting its scratch in the same write.

        Retained orphan rows remain accessible by job id for cleanup/recovery;
        monitor lookup returns ``None`` and every late writer is rejected.
        """
        with self._locked() as data:
            value = _owners.catalog(data)
            selected = _owners.agent_job(data, agent_id)
            record = value["owners"].get(selected)
            if expected_generation is not None:
                _owners.bounded_integer(expected_generation, minimum=1)
            if (record is None or (job_id is not None and selected != job_id)
                    or (expected_generation is not None and record["generation"] != expected_generation)):
                return False
            changed = record["active"] or (cleanup_scratch and selected in value["scratch"])
            record["active"] = False
            if cleanup_scratch:
                value["scratch"].pop(selected, None)
            if changed:
                self._save(data)
            return changed

    def read_job_scratch(self, agent_id: str, job_id: str) -> HeartbeatScratchState:
        """Read one known job's retained scratch, including a retired owner."""
        _owners.identity(agent_id)
        _owners.identity(job_id)
        return _owners.job_state(self._load(), agent_id, job_id)

    def write_job_scratch(
        self, agent_id: str, job_id: str, content: str | None, *, expected_revision: int | None = None,
        expected_owner_generation: int | None = None, source_sha256: str | None = None,
        now_ms: int | None = None,
    ) -> HeartbeatScratchWrite:
        """Atomically check durable owner identity/generation and scratch CAS."""
        if content is not None:
            assert_heartbeat_scratch_content(content)
        _owners.identity(agent_id)
        _owners.identity(job_id)
        with self._locked() as data:
            result, changed = _owners.write_owned(data, agent_id, job_id, content,
                now_ms=time.time_ns() // 1_000_000 if now_ms is None else now_ms,
                expected_revision=expected_revision, expected_owner_generation=expected_owner_generation,
                source_sha256=source_sha256)
            if changed:
                self._save(data)
            return result

    def delete_job_scratch(
        self, agent_id: str, job_id: str, *, expected_revision: int | None = None,
        expected_owner_generation: int | None = None,
    ) -> bool:
        """Guarded cleanup/rollback; retired owner identity remains durable.

        With ``expected_owner_generation``, only the exact active captured
        owner may delete. A retired, replaced or re-enrolled owner returns
        ``False`` without changing its scratch. Omitting this optional guard
        retains the existing API for deliberate orphan cleanup.
        """
        _owners.identity(agent_id)
        _owners.identity(job_id)
        with self._locked() as data:
            if expected_owner_generation is not None:
                _owners.bounded_integer(expected_owner_generation, minimum=1)
                current = _owners.active_owner(data, agent_id)
                if (current is None or current.job_id != job_id
                        or current.generation != expected_owner_generation):
                    return False
            state = _owners.job_state(data, agent_id, job_id)
            if expected_revision is not None:
                _owners.bounded_integer(expected_revision)
            new_state, deleted = apply_heartbeat_scratch_delete(state, expected_revision=expected_revision)
            if deleted and job_id in _owners.catalog(data)["scratch"]:
                _owners.put_job_state(data, job_id, new_state)
                self._save(data)
            return deleted

    def read_scratch(self, agent_id: str) -> HeartbeatScratchState:
        data = self._load()
        if self._owned(data):
            job_id = _owners.agent_job(data, agent_id)
            return _owners.job_state(data, agent_id, job_id) if job_id is not None else HeartbeatScratchState()
        return HeartbeatScratchState.from_json(data["scratch"].get(agent_id))

    def write_scratch(
        self,
        agent_id: str,
        content: str | None,
        *,
        expected_revision: int | None = None,
        source_sha256: str | None = None,
        now_ms: int | None = None,
        expected_owner_generation: int | None = None,
    ) -> HeartbeatScratchWrite:
        if content is not None:
            assert_heartbeat_scratch_content(content)
        with self._locked() as data:
            if self._owned(data):
                result, changed = _owners.write_owned(data, agent_id, _owners.agent_job(data, agent_id), content,
                    now_ms=time.time_ns() // 1_000_000 if now_ms is None else now_ms,
                    expected_revision=expected_revision, expected_owner_generation=expected_owner_generation,
                    source_sha256=source_sha256)
                if changed:
                    self._save(data)
                return result
            state = HeartbeatScratchState.from_json(data["scratch"].get(agent_id))
            new_state, result = apply_heartbeat_scratch_write(
                state,
                content,
                now_ms=int(time.time() * 1000) if now_ms is None else int(now_ms),
                expected_revision=expected_revision,
                source_sha256=source_sha256,
            )
            if new_state is not state:
                self._put_scratch(data, agent_id, new_state)
                self._save(data)
            return result

    def delete_scratch(self, agent_id: str, *, expected_revision: int | None = None) -> bool:
        with self._locked() as data:
            if self._owned(data):
                job_id = _owners.agent_job(data, agent_id)
                state = _owners.job_state(data, agent_id, job_id) if job_id is not None else HeartbeatScratchState()
                if expected_revision is not None:
                    _owners.bounded_integer(expected_revision)
                new_state, deleted = apply_heartbeat_scratch_delete(state, expected_revision=expected_revision)
                if deleted and job_id is not None and job_id in _owners.catalog(data)["scratch"]:
                    _owners.put_job_state(data, job_id, new_state)
                    self._save(data)
                return deleted
            state = HeartbeatScratchState.from_json(data["scratch"].get(agent_id))
            new_state, deleted = apply_heartbeat_scratch_delete(
                state, expected_revision=expected_revision
            )
            if deleted:
                self._put_scratch(data, agent_id, new_state)
                self._save(data)
            return deleted

    @staticmethod
    def _put_scratch(data: dict[str, Any], agent_id: str, state: HeartbeatScratchState) -> None:
        row = state.to_row()
        if row is None:
            data["scratch"].pop(agent_id, None)
        else:
            data["scratch"][agent_id] = row

    # -- jobs

    def _load_jobs(self) -> tuple[list[AutomationJob], list[SkippedAutomationJobRow]]:
        jobs: list[AutomationJob] = []
        skipped: list[SkippedAutomationJobRow] = []
        for index, item in enumerate(self._load()["jobs"]):
            raw_id = item.get("id") if isinstance(item, dict) else None
            job_id = raw_id if isinstance(raw_id, str) else None
            try:
                job = AutomationJob.from_json(item)
            except (ValueError, TypeError) as exc:
                skipped.append(SkippedAutomationJobRow(index, job_id, str(exc)))
                continue
            if _persisted_job(job, normalize=False) is None:
                # rowToCronJob: getInvalidPersistedCronJobReason rejects the stored values.
                skipped.append(SkippedAutomationJobRow(index, job_id, "invalid persisted job"))
                continue
            jobs.append(job)
        return jobs, skipped

    def list_jobs(self, *, agent_id: str | None = None) -> list[AutomationJob]:
        jobs, _skipped = self._load_jobs()
        return [job for job in jobs if agent_id is None or job.agent_id == agent_id]

    def skipped_job_rows(self) -> list[SkippedAutomationJobRow]:
        """The stored rows ``list_jobs`` skips (upstream keeps them as ``invalidConfigRows``)."""
        return self._load_jobs()[1]

    def claim_heartbeat_task(self, agent_id: str, job_id: str, now_ms: int, *, forced: bool) -> AutomationJob | str:
        """Atomically reserve one due task. Other host invocations see its running marker."""
        with self._locked() as data:
            for index, row in enumerate(data["jobs"]):
                if not isinstance(row, dict) or row.get("id") != job_id:
                    continue
                job = AutomationJob.from_json(row)
                if job.agent_id != agent_id or not is_heartbeat_task_job(job):
                    return "not-due"
                if job.running_at_ms is not None or job.queued_at_ms is not None:
                    return "already-running"
                if not is_job_due(job, now_ms, forced=forced):
                    return "not-due"
                claimed = replace(job, running_at_ms=now_ms,
                                  runtime_state={**job.runtime_state, "runningReceiptId": str(uuid.uuid4())})
                data["jobs"][index] = claimed.to_json()
                self._save(data)
                return claimed
            raise ValueError(f"unknown cron job id: {job_id}")

    def complete_claimed_job(self, claim: AutomationJob, completed: AutomationJob) -> bool:
        """Commit a matching durable reservation while preserving independent edits/removal."""
        with self._locked() as data:
            for index, row in enumerate(data["jobs"]):
                if not isinstance(row, dict) or row.get("id") != claim.id:
                    continue
                current = AutomationJob.from_json(row)
                if current.runtime_state.get("runningReceiptId") != claim.runtime_state.get("runningReceiptId"):
                    return False
                if current == claim:
                    if ((current.calendar_schedule or {}).get("kind") == "at"
                            and current.options.get("deleteAfterRun") is True and not completed.enabled
                            and completed.runtime_state.get("lastRunStatus") == "ok"):
                        del data["jobs"][index]
                    else:
                        data["jobs"][index] = completed.to_json()
                else:
                    # The latest edit still owns the future slot. Merge only
                    # the finished invocation's outcome and release our reservation.
                    state = dict(current.runtime_state)
                    for key in ("runningReceiptId", "lastError", "failureAlertIncident"):
                        state.pop(key, None)
                    state.update({key: val for key, val in completed.runtime_state.items()
                                  if key.startswith(("last", "consecutive")) or key == "failureAlertIncident"})
                    data["jobs"][index] = replace(current, running_at_ms=None,
                        last_run_at_ms=completed.last_run_at_ms, updated_at_ms=completed.updated_at_ms,
                        runtime_state=state).to_json()
                self._save(data)
                return current == claim
            return False

    def save_jobs(
        self,
        jobs: Sequence[AutomationJob],
        *,
        remove: Sequence[str] = (),
        expected_jobs: Sequence[tuple[AutomationJob | None, AutomationJob]] = (),
        scratch_agent_id: str | None = None,
        scratch_content: str | None = None,
        scratch_expected_revision: int | None = None,
        scratch_source_sha256: str | None = None,
        scratch_job_id: str | None = None,
        scratch_owner_generation: int | None = None,
        now_ms: int | None = None,
    ) -> HeartbeatScratchWrite | None:
        """Upsert ``jobs`` by id and drop ``remove`` ids in one atomic write.

        With ``scratch_agent_id`` the same write also replaces that agent's scratch through
        :func:`~memory_core.heartbeat_scratch.apply_heartbeat_scratch_write` (a compare-and-swap on
        ``scratch_expected_revision``); on a conflict nothing is written and the conflict is
        returned. Jobs are stored as :func:`assert_automation_jobs_can_persist` normalizes them;
        a job it refuses raises ``ValueError`` before anything is written (upstream's cron
        store runs ``assertCronStoreCanPersist`` on every save).

        For an owned scratch commit, ``scratch_job_id`` and
        ``scratch_owner_generation`` retain a writer's captured owner. Removing
        a monitor id through ``remove`` retires that owner and cleans its scratch
        in this same transaction. Combining its removal with a scratch write is
        refused atomically. Ordinary task job writes preserve the legacy API.
        """
        jobs = assert_automation_jobs_can_persist(jobs)
        if scratch_agent_id is not None and scratch_content is not None:
            assert_heartbeat_scratch_content(scratch_content)
        with self._locked() as data:
            result: HeartbeatScratchWrite | None = None
            if scratch_agent_id is not None:
                if self._owned(data):
                    job_id = scratch_job_id or _owners.agent_job(data, scratch_agent_id)
                    if job_id in set(remove):
                        state = _owners.job_state(data, scratch_agent_id, job_id)
                        return HeartbeatScratchWrite(False, state.current_revision, reason="revision-conflict")
                    result, _changed = _owners.write_owned(data, scratch_agent_id, job_id, scratch_content,
                        now_ms=time.time_ns() // 1_000_000 if now_ms is None else now_ms,
                        expected_revision=scratch_expected_revision, expected_owner_generation=scratch_owner_generation,
                        source_sha256=scratch_source_sha256)
                else:
                    state = HeartbeatScratchState.from_json(data["scratch"].get(scratch_agent_id))
                    new_state, result = apply_heartbeat_scratch_write(
                        state, scratch_content, now_ms=int(time.time() * 1000) if now_ms is None else int(now_ms),
                        expected_revision=scratch_expected_revision, source_sha256=scratch_source_sha256)
                    self._put_scratch(data, scratch_agent_id, new_state)
                if not result.ok:
                    return result
            for previous, proposed in expected_jobs:
                matches = [row for row in data["jobs"] if isinstance(row, dict)
                           and row.get("declarationKey") == proposed.declaration_key]
                if previous is None:
                    conflict = bool(matches) or any(isinstance(row, dict) and row.get("id") == proposed.id
                                                    for row in data["jobs"])
                else:
                    conflict = len(matches) != 1 or AutomationJob.from_json(matches[0]) != previous
                if conflict:
                    raise AutomationJobConflictError(proposed.id)
            by_id = {job.id: job for job in jobs}
            removed = set(remove)
            if self._owned(data):
                ownership = _owners.catalog(data)
                for job_id in removed:
                    owner = ownership["owners"].get(job_id)
                    if owner is not None:
                        owner["active"] = False
                        ownership["scratch"].pop(job_id, None)
            kept: list[dict[str, Any]] = []
            for item in data["jobs"]:
                job_id = item.get("id") if isinstance(item, dict) else None
                if job_id in removed:
                    continue
                if job_id in by_id:
                    kept.append(by_id.pop(job_id).to_json())
                else:
                    kept.append(item)
            kept.extend(job.to_json() for job in jobs if job.id in by_id)
            data["jobs"] = kept
            self._save(data)
            return result
