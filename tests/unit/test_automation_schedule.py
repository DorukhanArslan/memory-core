from datetime import datetime

import pytest

from memory_core.automation import AutomationJob, compute_job_next_run_at_ms
from memory_core.automation_schedule import canonical_absolute_time


def _ms(instant: str) -> int:
    return int(datetime.fromisoformat(instant).timestamp() * 1000)


@pytest.mark.parametrize("expression, zone, start, expected", [
    ("0 0 LW * *", "UTC", "2026-01-01T12:00Z", "2026-01-30T00:00Z"),
    ("0 0 * * FRI-SUN", "UTC", "2026-01-01T12:00Z", "2026-01-02T00:00Z"),
    ("30 2 * * *", "America/New_York", "2026-03-07T08:00Z", "2026-03-09T06:30Z"),
    ("45 1 * * *", "Australia/Lord_Howe", "2026-04-04T14:50Z", "2026-04-05T15:15Z"),
])
def test_calendar_jobs_follow_the_authored_wall_clock(expression, zone, start, expected):
    job = AutomationJob(id="memory", name="Read the note", agent_id="main", every_ms=None, text="read",
                        calendar_schedule={"kind": "cron", "expr": expression, "tz": zone, "staggerMs": 0})
    assert compute_job_next_run_at_ms(job, _ms(start)) == _ms(expected)


def test_one_shot_store_normalization_preserves_instant_and_year():
    assert canonical_absolute_time("2026-01-01T02:01:00+02:00") == "2026-01-01T00:01:00.000Z"
    assert canonical_absolute_time("0000-02-29T24:00:00.000Z") == "0000-03-01T00:00:00.000Z"
    assert canonical_absolute_time("+275760-09-13T01:00:00+0100") == "+275760-09-13T00:00:00.000Z"
    assert canonical_absolute_time("-271821-04-19T23:59:59.999Z") is None


def test_numeric_prefixed_cron_step_rejects_invalid_schedule():
    job = AutomationJob(id="memory", name="Read the note", agent_id="main", every_ms=None, text="read",
                        calendar_schedule={"kind": "cron", "expr": "3/5 * * * *", "tz": "UTC"})
    with pytest.raises(ValueError, match="requires a range"):
        compute_job_next_run_at_ms(job, _ms("2026-01-01T00:00Z"))
