"""Frozen scheduling drives and Doctor task migrations for memory-owned tasks."""
from copy import deepcopy
from datetime import datetime

NOW = 1767225600000
MINUTE = 60_000


def _time(text):
    return int(datetime.fromisoformat(text).timestamp() * 1000)


def _job(job_id, schedule, *, state=None, name=None, declaration=None, enabled=True):
    name = name or job_id
    return {"id": job_id, "name": name, "agentId": "main", "enabled": enabled,
            "declarationKey": declaration or "heartbeat-task:main:" + job_id,
            "createdAtMs": NOW, "updatedAtMs": NOW, "schedule": schedule,
            "sessionTarget": "main", "wakeMode": "next-heartbeat",
            "payload": {"kind": "systemEvent", "text": "Read the memory note for " + name + "."},
            "state": dict(state or {})}


def scheduling_input():
    interval = {"kind": "every", "everyMs": MINUTE, "anchorMs": NOW}
    at = {"kind": "at", "at": "2026-01-01T02:01:00+02:00"}
    cron = {"kind": "cron", "expr": "1,16 0 * * 1-5", "tz": "UTC", "staggerMs": 0}
    slot = NOW + MINUTE
    jobs = [_job("interval", interval, state={"nextRunAtMs": slot}),
            _job("once", at, state={"nextRunAtMs": slot}),
            _job("weekday", cron, state={"nextRunAtMs": slot})]
    probes = []

    def probe(job, when=NOW, forced=False):
        probes.append({"job": deepcopy(job), "nowMs": when, "forced": forced})

    for job in jobs:
        probe(job)
        probe(job, slot)
        probe(job, NOW, True)
    probe(_job("paused", interval, enabled=False, state={"nextRunAtMs": NOW}), NOW, True)
    for marker in ("queuedAtMs", "runningAtMs"):
        probe(_job("active", interval, state={marker: NOW, "nextRunAtMs": NOW}), NOW, True)
    probe(_job("anchored", interval, state={"lastRunAtMs": NOW + MINUTE // 2}), slot)
    probe(_job("invalid-every", {"kind": "every", "everyMs": 0}))
    probe(_job("invalid-at", {"kind": "at", "at": "not-a-date"}))
    probe(_job("finished", at, state={"lastRunAtMs": slot, "lastRunStatus": "ok"}), slot + 1)
    for clock, expr in (("2026-03-08T06:00:00+00:00", "30 2 * * *"),
                        ("2026-11-01T05:31:00+00:00", "30 1 * * *")):
        probe(_job("local-time", {"kind": "cron", "expr": expr, "tz": "America/New_York", "staggerMs": 0}),
              _time(clock))
    ran = {"status": "ran", "durationMs": 0}
    skipped = {"status": "skipped", "reason": "empty-heartbeat-file"}
    return {"kind": "scheduling", "probes": probes, "jobs": jobs, "runs": [
        {"jobId": "interval", "atMs": NOW, "mode": "due", "reply": ran},
        {"jobId": "once", "atMs": NOW, "mode": "force", "reply": ran},
        {"jobId": "interval", "atMs": slot, "mode": "due", "reply": skipped},
        {"jobId": "weekday", "atMs": slot, "mode": "due", "reply": ran},
        {"jobId": "once", "atMs": slot, "mode": "due", "reply": ran},
        {"jobId": "interval", "atMs": slot + MINUTE, "mode": "due", "reply": ran},
    ]}


def migration_input():
    key = "heartbeat-task:main:09660974ac63ba49395c010f"
    existing = _job("existing-notice", {"kind": "every", "everyMs": MINUTE, "anchorMs": NOW - MINUTE},
                    name="notice", declaration=key, state={"nextRunAtMs": NOW + MINUTE})
    def block(entries):
        return "Retain this note.\n\ntasks:\n" + "".join(
            "  - name: " + name + "\n    interval: " + interval + "\n    prompt: " + prompt + "\n"
            for name, interval, prompt in entries) + "\nKeep this last line.\n"

    valid = block([("notice", "1m", "Read the release board."), ("notice", "2m", "Read the other board."),
                   ("late", "30s", "Read the overdue note."), ("fresh", "3", "Read the new note.")])
    common = {"nowMs": NOW, "phases": ["preview", "repair", "repair-reopen"],
              "legacyTaskState": {"notice": NOW - 5_000, "late": NOW - 2 * MINUTE, "untouched": NOW - 10_000}}
    return {"kind": "migration", "scenarios": [
        {**common, "name": "convert", "scratch": valid, "jobs": [existing]},
        {**common, "name": "invalid", "scratch": block([("bad", "0m", "Leave this here.")]), "jobs": []},
        {**common, "name": "collision", "scratch": valid,
         "jobs": [existing, {**existing, "id": "second-existing-notice"}]},
    ]}


def case_inputs():
    return [scheduling_input(), migration_input()]
