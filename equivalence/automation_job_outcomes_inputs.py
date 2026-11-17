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


CALENDAR = (('@daily', 'UTC', 1767268800000, None),
 ('@hourly', 'UTC', 1767268800000, None),
 ('0 0 LW * *', 'UTC', 1767268800000, None),
 ('0 0 1W * *', 'UTC', 1767268800000, None),
 ('0 0 31W * *', 'UTC', 1767268800000, None),
 ('0 0 L,15 * *', 'UTC', 1767268800000, None),
 ('0 0 * * FRIL', 'UTC', 1767268800000, None),
 ('0 0 * * FRI#L', 'UTC', 1767268800000, None),
 ('0 0 * * FRI-SUN', 'UTC', 1767268800000, None),
 ('0 0 * * SUN-SAT/2', 'UTC', 1767268800000, None),
 ('0 1 * JAN-MAR MON-FRI#2', 'UTC', 1767268800000, None),
 ('0 0 15 * +MON', 'UTC', 1767268800000, None),
 ('0 0 ? * MON', 'UTC', 1767268800000, None),
 ('0 0 15 * ?', 'UTC', 1767268800000, None),
 ('0 0 */2 * FRI', 'UTC', 1767268800000, None),
 ('0 0 * * ?', 'UTC', 1767268800000, None),
 ('0 0 */4 * +5', 'UTC', 1767268800000, None),
 ('0 0 0 1 1 * 2028', 'UTC', 1767268800000, None),
 ('0 0 0 1 1 * */2', 'UTC', 1767268800000, None),
 ('0 0 0 1 1 * 2025-2030/2', 'UTC', 1767268800000, None),
 ('3/5 * * * *', 'UTC', 1767268800000, None),
 ('*/61 * * * *', 'UTC', 1767268800000, None),
 ('0 0 31 2 *', 'UTC', 1767268800000, None),
 ('0 0 0 * * * 2060', 'UTC', 1767268800000, None),
 ('0 * * * *', 'UTC', 1767268800000, None),
 ('0 ? * * *', 'UTC', 1767268800000, None),
 ('1 0 * * *', 'UTC', 1767268800000, None),
 ('2026-03-07T02:00:00', 'UTC', 1767268800000, None),
 ('0 1,2 * * *', 'UTC', 1767268800000, None),
 ('@reboot', 'UTC', 1767268800000, None),
 ('15 0 * * *', 'Europe/Istanbul', 1775246400000, None),
 ('30 2 * * *', 'America/New_York', 1772870400000, None),
 ('30 1 * * *', 'America/New_York', 1793511000000, None),
 ('5 2 * * *', 'Australia/Lord_Howe', 1791039600000, None),
 ('45 1 * * *', 'Australia/Lord_Howe', 1775314200000, None),
 ('0 0 1 1 *', 'Asia/Shanghai', 1798732799000, None),
 ('0 1 * * *', '+03:30', 1775250000000, None),
 ('0 1 * * *', 'america/new_york', 1775250000000, None),
 ('0 0 L * FRI-SUN#L', 'UTC', 1767225600000, None),
 ('0 * * * *', 'UTC', -2678400000, None),
 ('0 0 1 1 *', 'UTC', 32503679999000, None),
 ('0 * * * *', 'UTC', 1767268800000, 0),
 ('0 * * * *', 'UTC', 1767268800000, 1),
 ('0 * * * *', 'UTC', 1767268800000, 5000),
 ('0 * * * *', 'UTC', 1767268800000, 300000),
 ('0 * * * *', 'UTC', 1767268800000, '5000'))
ABSOLUTE_TIMES = ('0', '1', '0001', '8640000000000000', '8640000000000001', '9007199254740991', '1970-01-01',
 '1969-12-31T23:59:59.999Z', '0000-02-29', '0001-01-01', '-000000-01-01', '+000000-01-01',
 '-000001-12-31', '+275760-09-13T00:00:00Z', '-271821-04-20T00:00:00Z',
 '+275760-09-13T01:00:00+0100', '2026-02-30', '2024-02-29', '2026-01-01t12:30z',
 '2026-01-01T24:00:00.0000', '2026-01-01T24:00:00.0001', '2026-01-01T01:02:03.87654-04:30',
 '2026-01-01T00:00:00+24:00', '2026-01-01 12:00', '+178001', '\ufeff2026-01-01\ufeff')


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
    for expr, zone, stamp, stagger in CALENDAR:
        schedule = {"kind": "cron", "expr": expr, "tz": zone}
        if stagger is not None:
            schedule["staggerMs"] = stagger
        probe(_job("memory-probe", schedule), stamp)
    for absolute in ABSOLUTE_TIMES:
        probe(_job("memory-one-shot", {"kind": "at", "at": absolute}))
    ran = {"status": "ran", "durationMs": 0}
    skipped = {"status": "skipped", "reason": "empty-heartbeat-file"}
    return {"kind": "scheduling", "probes": probes, "jobs": jobs, "runs": [
        {"jobId": "interval", "atMs": NOW, "mode": "due", "reply": ran},
        {"jobId": "once", "atMs": NOW, "mode": "force", "reply": ran},
        {"jobId": "interval", "atMs": slot, "mode": "due", "reply": skipped},
        {"jobId": "weekday", "atMs": slot, "mode": "due", "reply": ran},
        {"jobId": "once", "atMs": slot, "mode": "due", "reply": ran},
        {"jobId": "interval", "atMs": slot + MINUTE, "mode": "due", "reply": ran},
        {"jobId": "interval", "atMs": slot + 2 * MINUTE, "mode": "due",
         "reply": {"status": "failed", "reason": "maintenance note unavailable"}},
        {"jobId": "interval", "atMs": slot + 3 * MINUTE, "mode": "due", "reply": ran},
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
